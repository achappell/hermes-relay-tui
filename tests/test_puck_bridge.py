"""Fakes-only coverage for the standalone Puck audio bridge.

No live Hermes endpoint and no hardware: the HTTP receiver is exercised
against a real loopback socket (so the wire protocol is genuinely tested),
transcription is a fake, and the Hermes session is the same style of fake
double `test_handsfree_wiring.py` already uses for `SessionProtocol`.
"""

from __future__ import annotations

import asyncio
import http.client
import struct
import threading
import wave

import pytest

from puck_bridge.receiver import (
    TOKEN_HEADER,
    ThreadingHTTPServer,
    make_handler,
    process_frame_sample,
    raw_stereo32_to_wav,
)
from puck_bridge.server import build_session_args
from puck_bridge.turn import TurnRunner


# ---------------------------------------------------------------------------
# Conversion math
# ---------------------------------------------------------------------------


def _label_captures_process_frame_sample(raw4: bytes) -> int:
    """Inline copy of tools/label_captures.py's conversion for comparison.

    That script lives under firmware/respeaker-lite/tools, outside this
    package's import path (and it is a standalone script, not a library) --
    duplicated here only for the byte-for-byte parity assertion below, not
    as a dependency.
    """
    sample = int.from_bytes(raw4, byteorder="little", signed=True)
    sample >>= 6
    sample *= 4  # GAIN_FACTOR
    q25_max = (1 << 25) - 1
    q25_min = ~q25_max
    sample = max(q25_min, min(q25_max, sample))
    sample *= 1 << 6
    sample32 = sample & 0xFFFFFFFF
    out16 = (sample32 >> 16) & 0xFFFF
    if out16 >= 0x8000:
        out16 -= 0x10000
    return out16


@pytest.mark.parametrize(
    "value",
    [0, 1, -1, 1000, -1000, 2**30, -(2**30), 2**31 - 1, -(2**31)],
)
def test_process_frame_sample_matches_label_captures_conversion(value):
    raw4 = struct.pack("<i", value)
    assert process_frame_sample(raw4) == _label_captures_process_frame_sample(raw4)


def test_raw_stereo32_to_wav_selects_channel_index_one(tmp_path):
    # Two stereo frames: channel 0 carries an obviously-wrong constant so a
    # channel-selection bug (reading ch0 instead of ch1, matching this
    # board's documented "ch1 fits micro_wake_word" split) would be caught.
    # Channel 1's raw values are arbitrary Q31 samples; the expected 16-bit
    # output comes from calling the already-verified conversion directly,
    # not from hand-deriving the gain/shift chain a second time here.
    ch0_wrong = struct.pack("<i", 0x7FFFFFFF)
    ch1_raw_a = struct.pack("<i", 40_000_000)
    ch1_raw_b = struct.pack("<i", -40_000_000)
    raw = ch0_wrong + ch1_raw_a + ch0_wrong + ch1_raw_b

    wav_path = tmp_path / "out.wav"
    n_frames = raw_stereo32_to_wav(raw, str(wav_path))

    assert n_frames == 2
    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        samples = struct.unpack("<2h", wf.readframes(2))
    assert samples == (process_frame_sample(ch1_raw_a), process_frame_sample(ch1_raw_b))
    # A real channel-selection bug would read ch0's saturated constant
    # instead, which converts to a very different (and identical across
    # both frames) value -- assert against that too for a stronger signal.
    assert samples != (process_frame_sample(ch0_wrong), process_frame_sample(ch0_wrong))


# ---------------------------------------------------------------------------
# HTTP receiver
# ---------------------------------------------------------------------------


class _RecordingSink:
    def __init__(self) -> None:
        self.transcripts: list[str] = []
        self.event = threading.Event()

    def __call__(self, transcript: str) -> None:
        self.transcripts.append(transcript)
        self.event.set()


def _fake_transcribe(success: bool = True, transcript: str = "what's for dinner"):
    calls: list[str] = []

    def transcribe(wav_path: str) -> dict:
        calls.append(wav_path)
        if not success:
            return {"success": False, "transcript": "", "error": "boom"}
        return {"success": True, "transcript": transcript}

    transcribe.calls = calls  # type: ignore[attr-defined]
    return transcribe


def _start_server(handler_cls) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _post_chunk(port: int, *, seq: int, chunk: int, total: int, body: bytes, token: str | None) -> int:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        headers = {}
        if token is not None:
            headers[TOKEN_HEADER] = token
        conn.request(
            "POST",
            f"/upload?seq={seq}&chunk={chunk}&total={total}",
            body=body,
            headers=headers,
        )
        return conn.getresponse().status
    finally:
        conn.close()


def test_upload_missing_token_is_rejected_and_no_turn_is_submitted(tmp_path):
    sink = _RecordingSink()
    transcribe = _fake_transcribe()
    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=sink,
        transcribe_fn=transcribe,
        work_dir=tmp_path,
    )
    server = _start_server(handler_cls)
    try:
        status = _post_chunk(
            server.server_address[1],
            seq=1,
            chunk=0,
            total=1,
            body=b"\x00" * 8,
            token=None,
        )
        assert status == 401
    finally:
        server.shutdown()

    assert transcribe.calls == []
    assert sink.transcripts == []


def test_upload_wrong_token_is_rejected_and_no_turn_is_submitted(tmp_path):
    sink = _RecordingSink()
    transcribe = _fake_transcribe()
    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=sink,
        transcribe_fn=transcribe,
        work_dir=tmp_path,
    )
    server = _start_server(handler_cls)
    try:
        status = _post_chunk(
            server.server_address[1],
            seq=1,
            chunk=0,
            total=1,
            body=b"\x00" * 8,
            token="wrong",
        )
        assert status == 401
    finally:
        server.shutdown()

    assert transcribe.calls == []
    assert sink.transcripts == []


def test_bad_chunk_metadata_is_rejected_and_no_turn_is_submitted(tmp_path):
    # chunk >= total is one of several invalid-metadata shapes rejected by
    # the same 400 path (alongside negative seq/chunk and total<=0) -- this
    # must never touch `captures`, call `transcribe`, or call `on_transcript`.
    sink = _RecordingSink()
    transcribe = _fake_transcribe()
    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=sink,
        transcribe_fn=transcribe,
        work_dir=tmp_path,
    )
    server = _start_server(handler_cls)
    try:
        status = _post_chunk(
            server.server_address[1],
            seq=1,
            chunk=1,
            total=1,
            body=b"\x00" * 8,
            token="s3cret",
        )
        assert status == 400
        threading.Event().wait(0.2)
    finally:
        server.shutdown()

    assert transcribe.calls == []
    assert sink.transcripts == []


def test_complete_capture_with_valid_token_transcribes_and_delivers(tmp_path):
    sink = _RecordingSink()
    transcribe = _fake_transcribe(transcript="what's for dinner")
    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=sink,
        transcribe_fn=transcribe,
        work_dir=tmp_path,
    )
    server = _start_server(handler_cls)
    try:
        # Two chunks of one stereo/32-bit frame each, arriving in order.
        frame_a = struct.pack("<i", 0) + struct.pack("<i", 500 << 6)
        frame_b = struct.pack("<i", 0) + struct.pack("<i", -500 << 6)
        status_a = _post_chunk(
            server.server_address[1],
            seq=7,
            chunk=0,
            total=2,
            body=frame_a,
            token="s3cret",
        )
        status_b = _post_chunk(
            server.server_address[1],
            seq=7,
            chunk=1,
            total=2,
            body=frame_b,
            token="s3cret",
        )
        # 202 = chunk accepted into an incomplete reassembly; 200 = the
        # capture is now whole. This test previously asserted 200 for both,
        # which encoded the very ambiguity that let three captures be lost
        # silently on 2026-09-10 -- the firmware could not distinguish
        # "bytes accepted" from "capture delivered".
        assert status_a == 202
        assert status_b == 200
        assert sink.event.wait(5.0)
    finally:
        server.shutdown()

    assert transcribe.calls, "transcribe() was never called"
    assert sink.transcripts == ["what's for dinner"]


def test_out_of_order_chunks_still_reassemble_correctly(tmp_path):
    sink = _RecordingSink()
    transcribe = _fake_transcribe(transcript="hello")
    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=sink,
        transcribe_fn=transcribe,
        work_dir=tmp_path,
    )
    server = _start_server(handler_cls)
    try:
        frame_a = struct.pack("<i", 0) + struct.pack("<i", 1 << 6)
        frame_b = struct.pack("<i", 0) + struct.pack("<i", 2 << 6)
        # chunk 1 arrives before chunk 0.
        _post_chunk(server.server_address[1], seq=3, chunk=1, total=2, body=frame_b, token="s3cret")
        _post_chunk(server.server_address[1], seq=3, chunk=0, total=2, body=frame_a, token="s3cret")
        assert sink.event.wait(5.0)
    finally:
        server.shutdown()

    assert sink.transcripts == ["hello"]


def test_failed_transcription_produces_no_turn(tmp_path):
    sink = _RecordingSink()
    transcribe = _fake_transcribe(success=False)
    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=sink,
        transcribe_fn=transcribe,
        work_dir=tmp_path,
    )
    server = _start_server(handler_cls)
    try:
        frame = struct.pack("<i", 0) + struct.pack("<i", 100 << 6)
        _post_chunk(server.server_address[1], seq=9, chunk=0, total=1, body=frame, token="s3cret")
        # Give the (synchronous, already-completed) callback a moment; a
        # failure must never call on_transcript, so there is nothing to wait
        # on -- a short grace period is enough to catch a wrongly-fired call.
        threading.Event().wait(0.2)
    finally:
        server.shutdown()

    assert sink.transcripts == []


def test_empty_transcript_produces_no_turn(tmp_path):
    sink = _RecordingSink()
    transcribe = _fake_transcribe(transcript="")
    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=sink,
        transcribe_fn=transcribe,
        work_dir=tmp_path,
    )
    server = _start_server(handler_cls)
    try:
        frame = struct.pack("<i", 0) + struct.pack("<i", 100 << 6)
        _post_chunk(server.server_address[1], seq=11, chunk=0, total=1, body=frame, token="s3cret")
        threading.Event().wait(0.2)
    finally:
        server.shutdown()

    assert sink.transcripts == []


# ---------------------------------------------------------------------------
# Turn runner
# ---------------------------------------------------------------------------


class FakePlayer:
    """Stands in for `audio.PCMPlayer` without touching real audio hardware."""

    def __init__(self) -> None:
        self._active = False
        self.started_with: tuple | None = None
        self.written: list[bytes] = []
        self.closed = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self, fmt) -> None:
        self._active = True
        self.started_with = fmt

    def write(self, chunk: bytes) -> None:
        self.written.append(chunk)

    def close(self) -> None:
        self._active = False
        self.closed = True


class FakeSession:
    """A minimal `SessionProtocol` double, matching test_handsfree_wiring.py."""

    def __init__(self, events: list[dict] | None = None) -> None:
        self.turns: list[tuple[str, str]] = []
        self.connected = False
        self._events = events if events is not None else [
            {"type": "audio_start", "sample_rate": 16000, "channels": 1, "sample_width": 2},
            {"type": "audio_chunk", "data": b"\x01\x02"},
            {"type": "audio_chunk", "data": b"\x03\x04"},
        ]

    async def connect(self):
        self.connected = True
        return {}

    def is_connected(self) -> bool:
        return self.connected

    async def close(self):
        self.connected = False

    def send_turn(self, text: str, *, stt_source: str = "local"):
        self.turns.append((text, stt_source))

        async def _events():
            for event in self._events:
                yield event

        return _events()


def test_turn_runner_submits_exactly_one_turn_and_plays_the_response():
    session = FakeSession()
    player = FakePlayer()
    runner = TurnRunner(session, player=player)
    runner.start()
    try:
        delivered = runner.submit_transcript("what's for dinner")
        assert delivered is True
    finally:
        runner.stop()

    assert session.turns == [("what's for dinner", "local")]
    assert player.started_with == (16000, 1, 2)
    assert player.written == [b"\x01\x02", b"\x03\x04"]
    assert player.closed is True


def test_turn_runner_falls_back_to_the_audio_file_when_no_chunks_streamed(tmp_path):
    from audio import write_wav

    wav_path = tmp_path / "response.wav"
    write_wav(wav_path, b"\x05\x06\x07\x08", (16000, 1, 2))
    wav_bytes = wav_path.read_bytes()

    session = FakeSession(
        events=[
            {"type": "audio_file_start"},
            {"type": "audio_file_chunk", "data": wav_bytes[:20]},
            {"type": "audio_file_end", "data": wav_bytes[20:]},
        ]
    )
    player = FakePlayer()
    runner = TurnRunner(session, player=player)
    runner.start()
    try:
        delivered = runner.submit_transcript("what's for dinner")
        assert delivered is True
    finally:
        runner.stop()

    assert player.written == [b"\x05\x06\x07\x08"]


def test_turn_runner_ignores_a_wake_while_a_turn_is_already_in_flight():
    """Single-flight: the coordinator's own state machine drops a second
    detection during CAPTURING/SENDING rather than overlapping turns."""
    session = FakeSession()
    player = FakePlayer()
    runner = TurnRunner(session, player=player)
    runner.start()
    try:
        # Force the coordinator into a busy state without a real capture.
        runner.coordinator._begin_capture_for_test()
        delivered = runner.submit_transcript("a second question")
        assert delivered is False
        assert session.turns == []
    finally:
        runner.stop()


# ---------------------------------------------------------------------------
# Bridge session identity
# ---------------------------------------------------------------------------


def test_build_session_args_suffixes_the_profile_s_own_session_id(monkeypatch):
    """`config.build_arg_parser` always populates a non-empty `session_id`
    from the selected profile's own YAML config, so this bridge must always
    suffix it -- an emptiness check would never fire and every bridge
    invocation would silently collide with that profile's other doorway."""
    monkeypatch.delenv("VOICE_SESSION_ID", raising=False)
    args = build_session_args([])
    assert args.session_id == "hybrid-tui-puck-bridge"


def test_build_session_args_honors_an_explicit_session_id_flag():
    args = build_session_args(["--session-id", "custom-id"])
    assert args.session_id == "custom-id"

# --- 1-p-1 task 6: no fallback ---------------------------------------------


def test_build_session_args_never_substitutes_another_profile(monkeypatch):
    """An unusable or unexpected configuration must stay itself or fail --
    it must never quietly resolve to a *different* profile's identity.
    Epic 1: unapproved/unavailable identity fails closed and "must not
    select a fallback"."""
    from puck_bridge import server

    class _Parsed:
        session_id = "guest-kiosk"
        profile_name = "guest"

    class _Parser:
        def parse_args(self, argv):
            return _Parsed()

    monkeypatch.setattr(server.config, "build_arg_parser", lambda argv: _Parser())
    args = server.build_session_args([])
    assert args.session_id == "guest-kiosk-puck-bridge"
    # The resolved identity is derived from the configured profile alone;
    # no other profile's name may leak in as a substitute.
    assert "amanda" not in args.session_id


# --- upload completion signalling ------------------------------------------


def test_incomplete_chunks_get_202_and_the_final_chunk_gets_200(tmp_path):
    """The firmware cannot otherwise tell "you accepted my bytes" from "you
    have the whole capture". With a flat 200 on every chunk it logged
    "Uploaded wake capture" even on runs the bridge had already evicted on
    its reassembly TTL -- three turns were lost that way on 2026-09-10 with
    neither side reporting a failure."""
    sink = _RecordingSink()
    transcribe = _fake_transcribe(transcript="hello")
    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=sink,
        transcribe_fn=transcribe,
        work_dir=tmp_path,
    )
    server = _start_server(handler_cls)
    try:
        frame_a = struct.pack("<i", 0) + struct.pack("<i", 1 << 6)
        frame_b = struct.pack("<i", 0) + struct.pack("<i", 2 << 6)
        port = server.server_address[1]
        first = _post_chunk(port, seq=7, chunk=0, total=2, body=frame_a, token="s3cret")
        last = _post_chunk(port, seq=7, chunk=1, total=2, body=frame_b, token="s3cret")
        assert sink.event.wait(5.0)
    finally:
        server.shutdown()

    assert first == 202, "an accepted-but-incomplete chunk must not claim completion"
    assert last == 200, "the chunk that completes the capture must say so"
    # Both are 2xx, so the firmware's existing chunk_ok check and
    # puck_identity's 2xx -> AUTHORIZED transition are unaffected.
    assert 200 <= first < 300 and 200 <= last < 300


def test_a_single_chunk_capture_completes_immediately_with_200(tmp_path):
    sink = _RecordingSink()
    transcribe = _fake_transcribe(transcript="hi")
    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=sink,
        transcribe_fn=transcribe,
        work_dir=tmp_path,
    )
    server = _start_server(handler_cls)
    try:
        frame = struct.pack("<i", 0) + struct.pack("<i", 1 << 6)
        status = _post_chunk(
            server.server_address[1], seq=8, chunk=0, total=1, body=frame, token="s3cret"
        )
        assert sink.event.wait(5.0)
    finally:
        server.shutdown()

    assert status == 200


# --- 1-p-2 task 6: turn timeout bounds responsiveness, not duration -------


class _SlowSession(FakeSession):
    """Emits events with a controllable delay before the first one and
    between subsequent ones."""

    def __init__(self, *, first_delay=0.0, gap=0.0, events=None):
        super().__init__(events=events)
        self._first_delay = first_delay
        self._gap = gap

    def send_turn(self, text: str, *, stt_source: str = "local"):
        self.turns.append((text, stt_source))
        first_delay, gap, events = self._first_delay, self._gap, self._events

        async def _events():
            await asyncio.sleep(first_delay)
            for i, event in enumerate(events):
                if i:
                    await asyncio.sleep(gap)
                yield event

        return _events()


def test_a_long_answer_is_not_timed_out():
    """The regression this fixes. The old single 10s bound covered the whole
    turn INCLUDING playing the answer, so every real response "timed out"
    mid-sentence. Here the stream takes well over the old bound in total,
    but never stalls -- it must succeed."""
    import puck_bridge.turn as turn_mod

    many_chunks = [
        {"type": "audio_start", "sample_rate": 16000, "channels": 1, "sample_width": 2}
    ] + [{"type": "audio_chunk", "data": b"\x01\x02"} for _ in range(40)]
    session = _SlowSession(gap=0.02, events=many_chunks)
    player = FakePlayer()
    runner = TurnRunner(session, player=player)
    runner.start()
    try:
        # Total stream time far exceeds any single gap budget.
        assert runner._send("a long question") is True
    finally:
        runner.stop()
    assert len(player.written) == 40


def test_an_unresponsive_hermes_still_fails_fast(monkeypatch):
    """A relay that never produces a first event must not wedge the device."""
    import puck_bridge.turn as turn_mod

    monkeypatch.setattr(turn_mod, "FIRST_EVENT_TIMEOUT_SECONDS", 0.2)
    session = _SlowSession(first_delay=5.0)
    player = FakePlayer()
    runner = TurnRunner(session, player=player)
    runner.start()
    try:
        assert runner._send("a question nobody answers") is False
    finally:
        runner.stop()


def test_a_stream_that_dies_midway_is_abandoned(monkeypatch):
    """A stall mid-response is a dead turn, not a long answer."""
    import puck_bridge.turn as turn_mod

    monkeypatch.setattr(turn_mod, "STALL_TIMEOUT_SECONDS", 0.2)
    session = _SlowSession(gap=5.0)
    player = FakePlayer()
    runner = TurnRunner(session, player=player)
    runner.start()
    try:
        assert runner._send("a question that stalls") is False
    finally:
        runner.stop()


def test_the_player_is_closed_when_a_turn_is_abandoned(monkeypatch):
    """A turn that fails must not leave the shared player open for the next
    one to interleave into."""
    import puck_bridge.turn as turn_mod

    monkeypatch.setattr(turn_mod, "STALL_TIMEOUT_SECONDS", 0.2)
    session = _SlowSession(gap=5.0)
    player = FakePlayer()
    runner = TurnRunner(session, player=player)
    runner.start()
    try:
        runner._send("a question that stalls")
    finally:
        runner.stop()
    assert player.active is False


def test_a_stream_that_hangs_on_close_does_not_swallow_the_timeout(monkeypatch):
    """Regression for a hang introduced while fixing the turn timeout: the
    `finally` block awaited stream.aclose() unbounded, so a generator parked
    on a socket read waited forever and the TurnTimeout never surfaced. The
    turn then neither completed, timed out, nor logged anything."""
    import puck_bridge.turn as turn_mod

    monkeypatch.setattr(turn_mod, "FIRST_EVENT_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(turn_mod, "STREAM_CLOSE_TIMEOUT_SECONDS", 0.2)

    class _HangingCloseSession(FakeSession):
        def send_turn(self, text, *, stt_source="local"):
            self.turns.append((text, stt_source))

            class _Stream:
                def __aiter__(self_inner):
                    return self_inner

                async def __anext__(self_inner):
                    await asyncio.sleep(30)  # never yields

                async def aclose(self_inner):
                    await asyncio.sleep(30)  # and never closes

            return _Stream()

    runner = TurnRunner(_HangingCloseSession(), player=FakePlayer())
    runner.start()
    try:
        # Must return promptly rather than hanging until the 600s backstop.
        assert runner._send("a question") is False
    finally:
        runner.stop()


def test_a_dropped_capture_is_logged(tmp_path, caplog):
    """Single-flight means a capture arriving mid-turn is discarded. That was
    silent: on 2026-09-11 a wedged turn swallowed a following question with
    nothing in the log to say it had been thrown away."""
    import logging

    transcribe = _fake_transcribe(transcript="a question")

    def _busy_sink(_text: str) -> bool:
        return False  # coordinator is busy

    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=_busy_sink,
        transcribe_fn=transcribe,
        work_dir=tmp_path,
    )
    server = _start_server(handler_cls)
    try:
        with caplog.at_level(logging.WARNING):
            frame = struct.pack("<i", 0) + struct.pack("<i", 1 << 6)
            _post_chunk(
                server.server_address[1], seq=11, chunk=0, total=1,
                body=frame, token="s3cret",
            )
            import time as _t
            for _ in range(50):
                if any("dropped a capture" in r.message for r in caplog.records):
                    break
                _t.sleep(0.1)
    finally:
        server.shutdown()

    assert any("dropped a capture" in r.message for r in caplog.records), (
        "a discarded question must say so"
    )


def test_playback_that_never_drains_aborts_the_turn(monkeypatch):
    """The gap that let a turn hang for minutes: the per-event deadlines
    bound FETCHING events from Hermes, not PROCESSING them, so a blocking
    player.write had no timeout around it at all."""
    import puck_bridge.turn as turn_mod

    monkeypatch.setattr(turn_mod, "PLAYBACK_WRITE_TIMEOUT_SECONDS", 0.2)

    class _StuckPlayer(FakePlayer):
        def write(self, data):  # noqa: D102
            import time as _t
            _t.sleep(30)  # device never accepts the data

    runner = TurnRunner(FakeSession(), player=_StuckPlayer())
    runner.start()
    try:
        assert runner._send("a question") is False
    finally:
        runner.stop()


# --- 1-p-2 tasks 3-4: response streaming to the Puck ----------------------


def test_streaming_wav_header_declares_a_sentinel_length():
    """A live WAV has no known length at header time. micro_wav's decoder
    validates only num_channels and sample_rate -- data_chunk_size_ is
    copied into a uint32_t counter with no validation and decoding stops
    when the input runs out -- so a sentinel streams correctly."""
    from puck_bridge.response import streaming_wav_header

    header = streaming_wav_header((24000, 1, 2))
    assert len(header) == 44
    assert header[:4] == b"RIFF" and header[8:12] == b"WAVE"
    assert struct.unpack("<I", header[24:28])[0] == 24000          # sample rate
    assert struct.unpack("<I", header[40:44])[0] == 0xFFFFFFFF     # data size
    # A zero data chunk would make the decoder stop immediately.
    assert struct.unpack("<I", header[40:44])[0] != 0


def test_response_stream_delivers_chunks_in_order_then_ends():
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    stream.begin(1, (24000, 1, 2))
    stream.write(b"aa")
    stream.write(b"bb")
    stream.finish()
    assert list(stream.iter_chunks()) == [b"aa", b"bb"]


def test_response_stream_ends_the_body_when_the_producer_stalls():
    """Rather than hanging: the device treats a zero-length read as a
    timeout, not EOF, so an unterminated body leaves it waiting for its own
    ~30s failure instead of stopping cleanly."""
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    stream.begin(1, (24000, 1, 2))
    stream.write(b"aa")
    # never finished
    chunks = list(stream.iter_chunks(stall_timeout=0.6))
    assert chunks == [b"aa"]


def test_response_stream_wait_for_format_gives_up_rather_than_blocking():
    from puck_bridge.response import ResponseStream

    assert ResponseStream().wait_for_format(timeout=0.2) is None


def test_a_turn_publishes_audio_to_the_response_stream_not_the_host():
    """Task 4: with a response stream attached the answer goes to the Puck,
    and must NOT also be played on this host."""
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    player = FakePlayer()
    runner = TurnRunner(FakeSession(), player=player, response_stream=stream)
    runner.start()
    try:
        assert runner._send("a question") is True
    finally:
        runner.stop()

    assert list(stream.iter_chunks()) == [b"\x01\x02", b"\x03\x04"]
    assert player.written == [], "the host must stay silent when the Puck plays"
    assert stream.finished, "the body must be terminated for the device"


def test_the_response_stream_is_finished_even_when_a_turn_fails(monkeypatch):
    """The device is blocked reading; an abandoned turn must still end the
    body rather than leaving it to time out."""
    import puck_bridge.turn as turn_mod
    from puck_bridge.response import ResponseStream

    monkeypatch.setattr(turn_mod, "FIRST_EVENT_TIMEOUT_SECONDS", 0.2)

    class _SilentSession(FakeSession):
        def send_turn(self, text, *, stt_source="local"):
            async def _events():
                await asyncio.sleep(30)
                yield {}

            return _events()

    stream = ResponseStream()
    runner = TurnRunner(_SilentSession(), player=FakePlayer(), response_stream=stream)
    runner.start()
    try:
        assert runner._send("a question") is False
    finally:
        runner.stop()
    assert stream.finished


def _get_response(port: int, *, token: str | None, seq: int | None = None):
    """Fetch /response and return (status, body-bytes).

    `seq` defaults to omitting the parameter entirely: the bridge only
    validates it when the device actually asks for a specific capture, and
    most tests here care about other behaviour. Tests that exercise the
    stale-capture guard pass it explicitly.
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        headers = {}
        if token is not None:
            headers[TOKEN_HEADER] = token
        path = "/response" if seq is None else f"/response?seq={seq}"
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, body
    finally:
        conn.close()


def test_response_endpoint_streams_a_wav_the_device_can_decode(tmp_path):
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=_RecordingSink(),
        transcribe_fn=_fake_transcribe(transcript="x"),
        work_dir=tmp_path,
        response_stream=stream,
    )
    server = _start_server(handler_cls)
    port = server.server_address[1]

    def _produce():
        stream.begin(1, (24000, 1, 2))
        stream.write(b"\x01\x02" * 8)
        stream.write(b"\x03\x04" * 8)
        stream.finish()

    threading.Thread(target=_produce, daemon=True).start()
    try:
        status, body = _get_response(port, token="s3cret")
    finally:
        server.shutdown()

    assert status == 200
    # http.client de-chunks for us, so this is the reassembled body.
    assert body[:4] == b"RIFF"
    assert struct.unpack("<I", body[24:28])[0] == 24000
    assert struct.unpack("<I", body[40:44])[0] == 0xFFFFFFFF
    assert body[44:] == b"\x01\x02" * 8 + b"\x03\x04" * 8


def test_response_endpoint_rejects_a_bad_token(tmp_path):
    """Response audio is as private as the question that produced it."""
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    stream.begin(1, (24000, 1, 2))
    stream.finish()
    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=_RecordingSink(),
        transcribe_fn=_fake_transcribe(transcript="x"),
        work_dir=tmp_path,
        response_stream=stream,
    )
    server = _start_server(handler_cls)
    try:
        status, _ = _get_response(server.server_address[1], token="wrong")
    finally:
        server.shutdown()
    assert status == 401


def test_response_fails_fast_when_no_turn_was_accepted():
    """The device fetches /response as soon as its upload is confirmed --
    before the bridge knows whether the capture held a question at all. An
    empty transcript runs no turn, so making the device wait out the full
    format budget for audio that never existed is pure latency. Observed
    2026-09-11 as four 15s waits; this asserts the fast path."""
    import time
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    started = time.monotonic()
    assert stream.wait_for_format(timeout=10.0) is None
    assert time.monotonic() - started < 1.0, (
        "must not wait the budget when nothing is expected"
    )


def test_response_waits_when_a_turn_is_actually_coming():
    """The counterpart: once a turn is accepted, the format wait is real --
    audio_start arrives slightly after the turn begins."""
    import threading as _th
    import time
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    stream.expect()

    def _late_format():
        time.sleep(0.3)
        stream.begin(1, (24000, 1, 2))

    _th.Thread(target=_late_format, daemon=True).start()
    assert stream.wait_for_format(timeout=5.0) == (24000, 1, 2)


def test_abandon_releases_a_waiting_reader():
    """A turn that fails after being accepted must release the device
    immediately rather than leaving it on the full budget."""
    import threading as _th
    import time
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    stream.expect()

    def _fail():
        time.sleep(0.2)
        stream.abandon()

    _th.Thread(target=_fail, daemon=True).start()
    started = time.monotonic()
    assert stream.wait_for_format(timeout=10.0) is None
    assert time.monotonic() - started < 2.0


def test_a_fetch_arriving_during_transcription_waits_for_the_answer(tmp_path):
    """The race that cost a delivered answer on 2026-09-11.

    The device fetches /response the instant its upload is confirmed, but
    transcription takes seconds. If `expect()` is set only after the
    transcript is accepted, that fetch fast-fails with 504 and the turn then
    produces audio with nobody reading it -- a lost answer that looks like a
    successful turn in the log. The declaration must happen when capture
    processing STARTS.
    """
    import threading as _th
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    slow_started = _th.Event()

    def _slow_transcribe(path):
        slow_started.set()
        import time as _t
        _t.sleep(0.8)  # stand in for faster-whisper
        return {"success": True, "transcript": "a question"}

    def _sink(_text):
        # The turn produces audio shortly after the transcript lands.
        def _produce():
            stream.begin(1, (24000, 1, 2))
            stream.write(b"\x07\x08" * 4)
            stream.finish()
        _th.Thread(target=_produce, daemon=True).start()
        return True

    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=_sink,
        transcribe_fn=_slow_transcribe,
        work_dir=tmp_path,
        response_stream=stream,
    )
    server = _start_server(handler_cls)
    port = server.server_address[1]
    try:
        frame = struct.pack("<i", 0) + struct.pack("<i", 1 << 6)
        _th.Thread(
            target=_post_chunk,
            kwargs=dict(port=port, seq=21, chunk=0, total=1, body=frame, token="s3cret"),
            daemon=True,
        ).start()
        assert slow_started.wait(5.0), "transcription should have begun"
        # Fetch mid-transcription, exactly as the device does.
        status, body = _get_response(port, token="s3cret")
    finally:
        server.shutdown()

    assert status == 200, "a fetch during transcription must wait, not 504"
    assert body[:4] == b"RIFF"
    assert body[44:] == b"\x07\x08" * 4


def test_a_second_concurrent_response_fetch_is_refused(tmp_path):
    """Two readers would each pop from the same queue and split the answer
    between them, so both would play garbage. The device was observed
    opening two connections for a single response on 2026-09-11."""
    import threading as _th
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    stream.expect()
    stream.begin(1, (24000, 1, 2))

    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=_RecordingSink(),
        transcribe_fn=_fake_transcribe(transcript="x"),
        work_dir=tmp_path,
        response_stream=stream,
    )
    server = _start_server(handler_cls)
    port = server.server_address[1]
    first_status: list[int] = []

    def _first():
        # Holds the reader slot while the producer dribbles chunks.
        first_status.append(_get_response(port, token="s3cret")[0])

    t = _th.Thread(target=_first, daemon=True)
    t.start()
    import time as _t
    _t.sleep(0.4)  # let the first claim the slot
    try:
        second_status, _ = _get_response(port, token="s3cret")
    finally:
        stream.finish()
        t.join(timeout=5)
        server.shutdown()

    assert second_status == 409, "a concurrent fetch must be refused, not served"
    assert first_status == [200], "the first fetch must be unaffected"


def test_the_reader_slot_is_released_after_a_stream_ends(tmp_path):
    """Otherwise one response would poison every later one."""
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    stream.expect()
    stream.begin(1, (24000, 1, 2))
    stream.write(b"ab")
    stream.finish()

    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=_RecordingSink(),
        transcribe_fn=_fake_transcribe(transcript="x"),
        work_dir=tmp_path,
        response_stream=stream,
    )
    server = _start_server(handler_cls)
    port = server.server_address[1]
    try:
        first, _ = _get_response(port, token="s3cret")
        # A later, non-concurrent fetch must not be refused.
        stream.expect()
        stream.begin(2, (24000, 1, 2))
        stream.write(b"cd")
        stream.finish()
        second, body = _get_response(port, token="s3cret")
    finally:
        server.shutdown()

    assert first == 200 and second == 200
    assert body[44:] == b"cd"


# --- code-review findings: four high-severity regressions ------------------


def test_the_producer_is_not_blocked_while_a_consumer_is_mid_yield():
    """HIGH 1. iter_chunks used to yield while holding the condition lock,
    so the consumer held it across its blocking socket write. The producer
    writes from the asyncio event-loop thread, so that blocked the entire
    loop -- including the wait_for timeouts meant to catch a stalled turn.
    And since the device plays in real time, backpressure is the NORMAL
    case."""
    import threading as _th
    import time as _t
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    stream.expect()
    stream.begin(1, (24000, 1, 2))
    stream.write(b"first")

    gen = stream.iter_chunks()
    assert next(gen) == b"first"  # consumer is now suspended at the yield

    produced = _th.Event()

    def _produce():
        stream.write(b"second")  # must not block on the consumer
        produced.set()

    _th.Thread(target=_produce, daemon=True).start()
    assert produced.wait(2.0), (
        "producer blocked while the consumer sat at a yield -- this is the "
        "event-loop deadlock"
    )
    stream.finish()


def test_a_turn_that_finishes_without_audio_releases_the_waiter():
    """HIGH 2. finish() left _expecting set, so a turn that never emitted
    audio_start (text-only reply, TTS failure) left the device waiting the
    full format budget for a 504 -- the exact behaviour this class claims
    to have removed."""
    import threading as _th
    import time as _t
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    stream.expect()

    def _finish_without_audio():
        _t.sleep(0.2)
        stream.finish()

    _th.Thread(target=_finish_without_audio, daemon=True).start()
    started = _t.monotonic()
    assert stream.wait_for_format(timeout=10.0) is None
    assert _t.monotonic() - started < 2.0, "must not wait out the budget"


def test_the_reader_slot_survives_a_dead_connection(tmp_path):
    """HIGH 3. acquire_reader() ran outside the try/finally, so a header
    write to an already-closed socket leaked the slot and every later fetch
    got 409 -- the Puck went permanently mute until a bridge restart."""
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=_RecordingSink(),
        transcribe_fn=_fake_transcribe(transcript="x"),
        work_dir=tmp_path,
        response_stream=stream,
    )
    server = _start_server(handler_cls)
    port = server.server_address[1]
    try:
        # Fetch and hang up immediately, mid-headers.
        for _ in range(3):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            stream.expect()
            stream.begin(1, (24000, 1, 2))
            conn.request("GET", "/response?seq=1", headers={TOKEN_HEADER: "s3cret"})
            conn.close()  # drop without reading
            import time as _t
            _t.sleep(0.2)
            stream.finish()
        # The slot must still be free for a normal fetch.
        stream.expect()
        stream.begin(2, (24000, 1, 2))
        stream.write(b"ok")
        stream.finish()
        status, _ = _get_response(port, token="s3cret")
    finally:
        server.shutdown()

    assert status != 409, "the reader slot leaked -- device would be mute"
    assert status == 200


def test_a_second_capture_cannot_truncate_an_answer_still_streaming():
    """HIGH 4. expect() unconditionally cleared the shared stream, so an
    ordinary follow-up question dropped the tail of the answer already
    playing, un-finished the stream, and could splice the new answer's PCM
    into the old body under the old WAV header."""
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    stream.expect()
    stream.begin(1, (24000, 1, 2))
    stream.write(b"answer-one-tail")
    assert stream.acquire_reader(), "reader should claim the slot"

    # A second wake arrives while answer one is still being delivered.
    assert stream.expect() is False, "must refuse while a reader is active"
    stream.abandon()  # must be a no-op too

    stream.finish()
    remaining = list(stream.iter_chunks(stall_timeout=1.0))
    assert remaining == [b"answer-one-tail"], (
        "the in-flight answer was truncated by a follow-up capture"
    )
    stream.release_reader()


def test_a_stale_capture_fetch_is_refused_not_answered_with_the_wrong_audio(tmp_path):
    """MEDIUM. The firmware asks for a specific capture and pcm_capture.h
    documents that as preventing wrong-answer playback -- but nothing read
    the parameter, so a retried or late fetch after a newer turn began would
    silently play a different question's answer."""
    from puck_bridge.response import ResponseStream

    stream = ResponseStream()
    stream.expect(seq=7)
    stream.begin(7, (24000, 1, 2))
    stream.write(b"answer-for-seven")
    stream.finish()

    handler_cls = make_handler(
        expected_token="s3cret",
        on_transcript=_RecordingSink(),
        transcribe_fn=_fake_transcribe(transcript="x"),
        work_dir=tmp_path,
        response_stream=stream,
    )
    server = _start_server(handler_cls)
    port = server.server_address[1]
    try:
        stale, _ = _get_response(port, token="s3cret", seq=3)
        matching, body = _get_response(port, token="s3cret", seq=7)
    finally:
        server.shutdown()

    assert stale == 409, "a fetch for a different capture must be refused"
    assert matching == 200
    assert body[44:] == b"answer-for-seven"
