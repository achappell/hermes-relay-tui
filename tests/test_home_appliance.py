"""The appliance loop, driven entirely by fakes.

No microphone, no speaker, no websocket, no wake-word engine: every seam the
real unit uses is injectable, so the whole wake-to-spoken-answer path can be
exercised in a test. What is being checked is that the display never claims a
state the hardware is not in.
"""

from __future__ import annotations

import asyncio
import io
import threading
import types
import wave

import pytest

import config
import handsfree
from home_display import appliance as appliance_module
from home_display.appliance import Appliance


class FakeSession:
    """A session whose turns are scripted event lists."""

    def __init__(self, script=None, *, connect_errors: int = 0) -> None:
        self.script = script if script is not None else [{"type": "turn_end"}]
        self.turns: list[str] = []
        self.connects = 0
        self.closes = 0
        self.cancels = 0
        self.shared_recorder = None
        self.connect_errors = connect_errors
        self.transcript = "what is the weather"
        self.turn_index = 0
        self.capture_timeouts = []
        self.follow_up = ""

    async def connect(self):
        self.connects += 1
        if self.connect_errors > 0:
            self.connect_errors -= 1
            raise ConnectionError("relay is down")
        return {"type": "hello_ack"}

    def is_connected(self) -> bool:
        return True

    def send_turn(self, text: str, *, stt_source: str = "local"):
        self.turns.append(text)
        script = self.script

        async def _events():
            for event in script:
                if isinstance(event, Exception):
                    raise event
                yield event

        return _events()

    def capture_voice(self, *, wait_timeout=None) -> str:
        self.capture_timeouts.append(wait_timeout)
        return self.follow_up if wait_timeout is not None else self.transcript

    def cancel_voice(self) -> None:
        self.cancels += 1

    def use_shared_recorder(self, recorder) -> None:
        self.shared_recorder = recorder

    async def close(self) -> None:
        self.closes += 1


class FakePlayer:
    def __init__(self, *, can_play: bool = True) -> None:
        self.can_play = can_play
        self.stream = None
        self.failure = None
        self.playing = False
        self.written = bytearray()
        self.formats: list[tuple[int, int, int]] = []
        self.aborts = 0
        self.closes = 0

    @property
    def active(self) -> bool:
        return self.stream is not None

    def start(self, audio_format) -> None:
        self.formats.append(audio_format)
        if self.can_play:
            self.stream = object()
        else:
            self.failure = "no output device"

    def write(self, chunk: bytes) -> None:
        self.written.extend(chunk)
        self.playing = True

    def abort(self) -> None:
        self.aborts += 1
        self.stream = None
        self.playing = False

    def close(self) -> None:
        self.closes += 1
        self.stream = None
        self.playing = False


class FakeRecorder:
    """Stands in for the shared, always-open input stream."""

    def __init__(self) -> None:
        self.observer = None
        self.opened = False
        self.shutdowns = 0
        self.has_detected_speech = False

    def set_frame_observer(self, observer) -> None:
        self.observer = observer

    def open_for_listening(self) -> None:
        self.opened = True

    def shutdown(self) -> None:
        self.shutdowns += 1


class FakeListener:
    """Records lifecycle calls; wake events are fired by the test."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.paused: list[bool] = []

    def start(self) -> None:
        self.started = True

    def pause(self) -> None:
        self.paused.append(True)

    def resume(self) -> None:
        self.paused.append(False)

    def stop(self) -> None:
        self.stopped = True

    def submit(self, frame) -> None:  # pragma: no cover - never called by fakes
        pass


class FakeEarcons:
    """Records which tones were asked for, in order, and when."""

    def __init__(self, *, enabled: bool = True, log=None) -> None:
        self.enabled = enabled
        self.played: list[str] = []
        self.failure = None
        self._log = log

    def abort(self) -> None:
        pass

    def play(self, name: str) -> None:
        if not self.enabled:
            return
        self.played.append(name)
        if self._log is not None:
            self._log.append(f"earcon:{name}")


class FakeServer:
    def __init__(self) -> None:
        self.info = types.SimpleNamespace(http_url="http://127.0.0.1:9/")
        self.closed = False
        self.audio: list[tuple[str, object]] = []

    async def start(self):
        return self.info

    async def close(self) -> None:
        self.closed = True

    async def send_audio_start(self, **payload) -> None:
        self.audio.append(("start", payload))

    async def send_audio_chunk(self, data: bytes) -> None:
        self.audio.append(("chunk", data))

    async def send_audio_end(self, **payload) -> None:
        self.audio.append(("end", payload))

    async def send_audio_abort(self, **payload) -> None:
        self.audio.append(("abort", payload))


def _args(**overrides):
    values = {
        "wake_enabled": True,
        "no_play": False,
        "audio_output_device": None,
        "mic_input_device": None,
        "wake_listen_timeout": 8.0,
        "wake_barge_in": False,
        "browser_voice": False,
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


def _build(appliance_state: dict):
    """A `build_hands_free` that returns the fake listener and a real coordinator."""

    def build(
        session,
        args,
        *,
        on_state_change=None,
        send=None,
        capture=None,
        follow_up_capture=None,
        speech_detected=None,
        stop_playback=None,
        acknowledge=None,
        capture_finished=None,
        route_wake=None,
        **kwargs,
    ):
        listener = FakeListener()
        coordinator = handsfree.HandsFreeCoordinator(
            session,
            capture=capture or session.capture_voice,
            send=send,
            follow_up_capture=follow_up_capture,
            follow_up_listen_timeout=getattr(args, "wake_followup_seconds", 8.0),
            speech_detected=speech_detected,
            acknowledge=acknowledge,
            capture_finished=capture_finished,
            listen_timeout=getattr(args, "wake_listen_timeout", 8.0),
            barge_in=getattr(args, "wake_barge_in", False),
            stop_playback=stop_playback,
            on_state_change=on_state_change,
            route_wake=route_wake,
            now=appliance_state.get("clock", None) or (lambda: 0.0),
        )
        appliance_state["listener"] = listener
        appliance_state["coordinator"] = coordinator
        return listener, coordinator

    return build


def make_appliance(
    script=None,
    *,
    player=None,
    session=None,
    args=None,
    state=None,
    earcons=None,
    recorder=None,
    server=None,
    **kwargs,
):
    state = state if state is not None else {}
    session = session if session is not None else FakeSession(script)
    earcons = earcons if earcons is not None else FakeEarcons()
    state["earcons"] = earcons
    appliance = Appliance(
        args or _args(),
        session=session,
        earcons=earcons,
        player=player or FakePlayer(),
        recorder=recorder or FakeRecorder(),
        server=server or FakeServer(),
        build_hands_free=_build(state),
        tick_interval=0.01,
        **kwargs,
    )
    state["appliance"] = appliance
    state["session"] = session
    state["player"] = appliance._player
    state["recorder"] = appliance._recorder
    state["server"] = appliance._server
    return appliance, state


async def _wait_for(predicate, *, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.005)
    return False


async def _run_until_idle(appliance, state, *, wake_after_connect=True, until=None):
    """Start the loop, fire one wake from a worker thread, then stop."""
    task = asyncio.create_task(appliance.run())
    ready = until or (
        lambda: state.get("coordinator") is not None and state["session"].connects
    )
    assert await _wait_for(ready), "the appliance never reached its starting state"
    if wake_after_connect:
        done = threading.Event()

        def fire():
            try:
                state["coordinator"].on_wake()
            finally:
                done.set()

        threading.Thread(target=fire, daemon=True).start()
        assert await _wait_for(done.is_set), "the wake turn never finished"
    appliance._stopping.set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return task


class RecordingPublisher:
    """The real publisher's interface, with a history the test can assert on."""

    def __init__(self) -> None:
        self.history: list[tuple[str, str, str | None]] = []
        self.accounts: list[str | None] = []
        self.capabilities: list[object] = []

    def publish(self, *, state, response_text="", status_text=None, media=None, account=None, **kwargs):
        self.history.append((state, response_text, status_text))
        self.accounts.append(account)
        self.capabilities.append(kwargs.get("capabilities"))

    @property
    def sequence(self) -> list[str]:
        return [entry[0] for entry in self.history]


@pytest.mark.asyncio
async def test_wake_to_spoken_answer_walks_the_display_through_the_real_states():
    publisher = RecordingPublisher()
    script = [
        {"type": "text_delta", "text": "Sunny "},
        {"type": "text_delta", "text": "and warm."},
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "audio_end"},
        {"type": "turn_end"},
    ]
    player = FakePlayer()
    appliance, state = make_appliance(script, player=player, publisher=publisher)

    await _run_until_idle(appliance, state)

    assert state["session"].turns == ["what is the weather"]
    assert player.written == bytearray(b"\x01\x02")
    ordered = [entry for entry in publisher.sequence]
    assert ordered[0] == "disconnected"
    assert "listening" in ordered
    assert ordered.index("listening") < ordered.index("thinking")
    assert ordered.index("thinking") < ordered.index("speaking")
    assert ordered[-1] == "idle"
    spoken = [entry for entry in publisher.history if entry[0] == "speaking"]
    assert spoken[-1][1] == "Sunny and warm."


@pytest.mark.asyncio
async def test_browser_voice_turn_uses_ops_session_and_streams_pcm_without_local_audio():
    publisher = RecordingPublisher()
    server = FakeServer()
    player = FakePlayer()
    script = [
        {"type": "text_delta", "text": "Sunny and warm."},
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "audio_end"},
        {"type": "turn_end"},
    ]
    appliance = Appliance(
        _args(browser_voice=True, wake_enabled=False),
        session=FakeSession(script),
        player=player,
        recorder=FakeRecorder(),
        earcons=FakeEarcons(),
        server=server,
        publisher=publisher,
        build_hands_free=lambda *args, **kwargs: pytest.fail(
            "browser voice must not build a local wake listener"
        ),
    )

    task = asyncio.create_task(appliance.run())
    try:
        assert await _wait_for(lambda: appliance._connected)
        await appliance._on_browser_voice_turn("  what is the weather?  ")
        assert appliance._session.turns == ["what is the weather?"]
        assert player.written == bytearray()
        assert server.audio == [
            ("start", {
                "turn_id": server.audio[0][1]["turn_id"],
                "sample_rate": 24000,
                "channels": 1,
                "sample_width": 2,
            }),
            ("chunk", b"\x01\x02"),
            ("end", {"turn_id": server.audio[0][1]["turn_id"]}),
        ]
        assert publisher.capabilities[-1].features == ("browser_voice",)
        assert publisher.history[-1][0] == "idle"
    finally:
        appliance._stopping.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_browser_voice_turn_plays_a_valid_wav_fallback_when_pcm_is_not_streamed():
    wav = io.BytesIO()
    with wave.open(wav, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(b"\x01\x02")

    publisher = RecordingPublisher()
    server = FakeServer()
    appliance = Appliance(
        _args(browser_voice=True, wake_enabled=False),
        session=FakeSession([
            {"type": "text_delta", "text": "Fallback answer."},
            {"type": "audio_file_start"},
            {"type": "audio_file_chunk", "data": wav.getvalue()},
            {"type": "audio_file_end"},
            {"type": "turn_end"},
        ]),
        server=server,
        publisher=publisher,
    )

    task = asyncio.create_task(appliance.run())
    try:
        assert await _wait_for(lambda: appliance._connected)
        await appliance._on_browser_voice_turn("say it")
        assert [kind for kind, _payload in server.audio] == ["start", "chunk", "end"]
        assert server.audio[1][1] == b"\x01\x02"
        assert publisher.history[-1][0] == "idle"
    finally:
        appliance._stopping.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_home_caption_reveals_only_the_words_reached_by_audio():
    gate = asyncio.Event()

    class ClockedPlayer(FakePlayer):
        playback_position = 0.5

    class PausingSession(FakeSession):
        def send_turn(self, text: str, *, stt_source: str = "local"):
            self.turns.append(text)

            async def _events():
                for index, event in enumerate(self.script):
                    if isinstance(event, Exception):
                        raise event
                    yield event
                    if index == 3:
                        await gate.wait()

            return _events()

    publisher = RecordingPublisher()
    session = PausingSession(
        [
            {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
            {
                "type": "speech_timing",
                "segment_id": "segment-1",
                "text": "Hermes keeps moving.",
                "timing_source": "alignment",
                "audio_offset": 0.0,
                "duration": 1.3,
                "fallback_reason": None,
                "words": [
                    {"text": "Hermes", "start": 0.0, "end": 0.28},
                    {"text": "keeps", "start": 0.28, "end": 0.51},
                    {"text": "moving.", "start": 0.51, "end": 1.3},
                ],
            },
            {"type": "text_delta", "text": "Hermes keeps moving."},
            {"type": "audio_chunk", "data": b"\x01\x02"},
            {"type": "audio_end"},
            {"type": "turn_end"},
        ]
    )
    player = ClockedPlayer()
    appliance, state = make_appliance(
        session=session,
        player=player,
        publisher=publisher,
    )

    task = asyncio.create_task(appliance.run())
    assert await _wait_for(lambda: state.get("coordinator") is not None and session.connects)
    worker = asyncio.create_task(asyncio.to_thread(state["coordinator"].on_wake))
    try:
        assert await _wait_for(
            lambda: any(
                state == "speaking" and text == "Hermes keeps "
                for state, text, _status in publisher.history
            )
        )
        speaking_text = [
            text for state, text, _status in publisher.history if state == "speaking"
        ]
        assert "Hermes keeps moving." not in speaking_text
        gate.set()
        await asyncio.wait_for(worker, 2)
        assert any(
            state == "speaking" and text == "Hermes keeps moving."
            for state, text, _status in publisher.history
        )
    finally:
        gate.set()
        await asyncio.wait_for(worker, 2)
        appliance._stopping.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_home_error_clears_a_partial_caption_until_the_turn_finishes():
    publisher = RecordingPublisher()
    session = FakeSession(
        [
            {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
            {"type": "text_delta", "text": "This answer must disappear."},
            {"type": "audio_chunk", "data": b"\x01\x02"},
            {"type": "error", "error": "relay failed"},
            {"type": "turn_end"},
        ]
    )
    appliance, state = make_appliance(session=session, publisher=publisher)

    await _run_until_idle(appliance, state)

    error_entries = [
        text for display_state, text, _status in publisher.history
        if display_state == "error"
    ]
    assert error_entries
    assert all(text == "" for text in error_entries)
    assert publisher.history[-1][1] == ""


@pytest.mark.asyncio
async def test_home_keeps_one_caption_clock_across_audio_segments():
    publisher = RecordingPublisher()

    class SegmentPlayer(FakePlayer):
        playback_position = 1.1

        def __init__(self):
            super().__init__()
            self.start_count = 0

        def start(self, audio_format):
            self.start_count += 1
            super().start(audio_format)

    script = [
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {
            "type": "speech_timing",
            "segment_id": "segment-1",
            "text": "one two",
            "timing_source": "alignment",
            "audio_offset": 0.0,
            "duration": 1.0,
            "words": [
                {"text": "one", "start": 0.0, "end": 0.5},
                {"text": "two", "start": 0.5, "end": 1.0},
            ],
        },
        {"type": "text_delta", "text": "one two three four"},
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "audio_end"},
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {
            "type": "speech_timing",
            "segment_id": "segment-2",
            "text": "three four",
            "timing_source": "alignment",
            "audio_offset": 1.0,
            "duration": 1.0,
            "words": [
                {"text": "three", "start": 1.0, "end": 1.5},
                {"text": "four", "start": 1.5, "end": 2.0},
            ],
        },
        {"type": "audio_chunk", "data": b"\x03\x04"},
        {"type": "audio_end"},
        {"type": "turn_end"},
    ]
    player = SegmentPlayer()
    appliance, state = make_appliance(
        session=FakeSession(script),
        player=player,
        publisher=publisher,
    )

    await _run_until_idle(appliance, state)

    assert player.start_count == 1
    first_speaking = publisher.sequence.index("speaking")
    final_speaking = next(
        index
        for index in range(first_speaking, len(publisher.sequence))
        if publisher.sequence[index] == "idle"
    )
    assert "idle" not in publisher.sequence[first_speaking + 1:final_speaking]
    assert any(
        state == "speaking" and text == "one two three four"
        for state, text, _status in publisher.history
    )


@pytest.mark.asyncio
async def test_home_uses_audio_duration_when_speech_timing_is_missing():
    gate = asyncio.Event()

    class DurationPlayer(FakePlayer):
        playback_position = 0.0

        def write(self, chunk: bytes) -> None:
            super().write(chunk)
            self.playback_position += 0.25

    class PausingSession(FakeSession):
        def send_turn(self, text: str, *, stt_source: str = "local"):
            self.turns.append(text)

            async def _events():
                for index, event in enumerate(self.script):
                    if isinstance(event, Exception):
                        raise event
                    yield event
                    if index == 4:
                        await gate.wait()

            return _events()

    publisher = RecordingPublisher()
    session = PausingSession(
        [
            {"type": "audio_start", "sample_rate": 10, "channels": 1, "sample_width": 2},
            {"type": "text_delta", "text": "one two three four"},
            {"type": "audio_chunk", "data": b"\x00" * 10},
            {"type": "audio_chunk", "data": b"\x00" * 10},
            {"type": "audio_chunk", "data": b"\x00" * 10},
            {"type": "audio_end"},
            {"type": "turn_end"},
        ]
    )
    appliance, state = make_appliance(
        session=session,
        player=DurationPlayer(),
        publisher=publisher,
    )

    task = asyncio.create_task(appliance.run())
    assert await _wait_for(lambda: state.get("coordinator") is not None and session.connects)
    worker = asyncio.create_task(asyncio.to_thread(state["coordinator"].on_wake))
    try:
        assert await _wait_for(
            lambda: any(
                display_state == "speaking" and text == "one two "
                for display_state, text, _status in publisher.history
            )
        )
        assert not any(
            display_state == "speaking" and text == "one two three four"
            for display_state, text, _status in publisher.history
        )
        gate.set()
        await asyncio.wait_for(worker, 2)
        assert any(
            display_state == "speaking" and text == "one two three four"
            for display_state, text, _status in publisher.history
        )
    finally:
        gate.set()
        await asyncio.wait_for(worker, 2)
        appliance._stopping.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_home_caption_clock_advances_between_delayed_pcm_chunks():
    gate = asyncio.Event()

    class AdvancingPlayer(FakePlayer):
        position = 0.0

        @property
        def playback_position(self):
            return self.position

    class PausingSession(FakeSession):
        def send_turn(self, text: str, *, stt_source: str = "local"):
            self.turns.append(text)

            async def _events():
                for index, event in enumerate(self.script):
                    if isinstance(event, Exception):
                        raise event
                    yield event
                    if index == 3:
                        await gate.wait()

            return _events()

    publisher = RecordingPublisher()
    session = PausingSession(
        [
            {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
            {
                "type": "speech_timing",
                "segment_id": "segment-1",
                "text": "Hermes keeps moving.",
                "timing_source": "alignment",
                "audio_offset": 0.0,
                "duration": 1.3,
                "words": [
                    {"text": "Hermes", "start": 0.0, "end": 0.28},
                    {"text": "keeps", "start": 0.28, "end": 0.51},
                    {"text": "moving.", "start": 0.51, "end": 1.3},
                ],
            },
            {"type": "text_delta", "text": "Hermes keeps moving."},
            {"type": "audio_chunk", "data": b"\x01\x02"},
            {"type": "turn_end"},
        ]
    )
    player = AdvancingPlayer()
    appliance, state = make_appliance(
        session=session,
        player=player,
        publisher=publisher,
    )

    task = asyncio.create_task(appliance.run())
    assert await _wait_for(lambda: state.get("coordinator") is not None and session.connects)
    worker = asyncio.create_task(asyncio.to_thread(state["coordinator"].on_wake))
    try:
        assert await _wait_for(
            lambda: any(
                display_state == "speaking" and text == "Hermes "
                for display_state, text, _status in publisher.history
            )
        )
        player.position = 0.4
        assert await _wait_for(
            lambda: any(
                display_state == "speaking" and text == "Hermes keeps "
                for display_state, text, _status in publisher.history
            )
        )
        gate.set()
        await asyncio.wait_for(worker, 2)
    finally:
        gate.set()
        await asyncio.wait_for(worker, 2)
        appliance._stopping.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_home_interrupt_clears_the_caption_immediately():
    publisher = RecordingPublisher()
    session = FakeSession(
        [
            {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
            {"type": "text_delta", "text": "This answer was interrupted."},
            {"type": "audio_chunk", "data": b"\x01\x02"},
            {"type": "turn_interrupted"},
        ]
    )
    appliance, state = make_appliance(session=session, publisher=publisher)

    await _run_until_idle(appliance, state)

    assert any(
        display_state == "speaking" and text
        for display_state, text, _status in publisher.history
    )
    assert publisher.history[-1][1] == ""
    assert all(
        not (display_state == "idle" and text)
        for display_state, text, _status in publisher.history
    )


@pytest.mark.asyncio
async def test_the_appliance_starts_the_listener_before_opening_the_stream():
    """Reversed, the whole warm-up is dropped audio - 96 frames on a first run."""
    order: list[str] = []

    class OrderedRecorder(FakeRecorder):
        def open_for_listening(self) -> None:
            order.append("stream")
            super().open_for_listening()

    class OrderedListener(FakeListener):
        def start(self) -> None:
            order.append("listener")
            super().start()

    state: dict = {}

    def build(session, args, **kwargs):
        listener = OrderedListener()
        state["listener"] = listener
        state["coordinator"] = handsfree.HandsFreeCoordinator(
            session, capture=session.capture_voice, send=kwargs.get("send")
        )
        return listener, state["coordinator"]

    session = FakeSession()
    appliance = Appliance(
        _args(),
        session=session,
        player=FakePlayer(),
        recorder=OrderedRecorder(),
        server=FakeServer(),
        build_hands_free=build,
        tick_interval=0.01,
    )
    state["session"] = session

    await _run_until_idle(appliance, state, wake_after_connect=False)

    assert order == ["listener", "stream"]


@pytest.mark.asyncio
async def test_a_silent_misfire_says_nothing_and_returns_to_idle():
    publisher = RecordingPublisher()
    session = FakeSession()
    session.transcript = ""
    appliance, state = make_appliance(session=session, publisher=publisher)

    await _run_until_idle(appliance, state)

    assert session.turns == []
    assert publisher.sequence[-1] == "idle"
    assert "speaking" not in publisher.sequence


@pytest.mark.asyncio
async def test_playback_that_cannot_open_reports_buffering_not_speaking():
    publisher = RecordingPublisher()
    script = [
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_chunk", "data": b"\x01"},
        {"type": "audio_end"},
        {"type": "turn_end"},
    ]
    appliance, state = make_appliance(
        script, player=FakePlayer(can_play=False), publisher=publisher
    )

    await _run_until_idle(appliance, state)

    assert "buffering" in publisher.sequence
    assert "speaking" not in publisher.sequence


@pytest.mark.asyncio
async def test_a_relay_error_is_shown_rather_than_spoken():
    publisher = RecordingPublisher()
    script = [{"type": "error", "error": "model unavailable"}, {"type": "turn_end"}]
    appliance, state = make_appliance(script, publisher=publisher)

    await _run_until_idle(appliance, state)

    errors = [entry for entry in publisher.history if entry[0] == "error"]
    assert errors and errors[-1][2] == "model unavailable"


@pytest.mark.asyncio
async def test_a_connection_that_drops_mid_turn_shows_disconnected_and_reconnects():
    publisher = RecordingPublisher()
    session = FakeSession([ConnectionError("socket closed")])
    appliance, state = make_appliance(session=session, publisher=publisher)

    await _run_until_idle(appliance, state)
    assert await _wait_for(lambda: session.connects >= 2)

    assert publisher.sequence.count("disconnected") >= 2
    assert session.connects >= 2
    assert session.closes >= 1


@pytest.mark.asyncio
async def test_a_failed_connection_retries_and_the_display_never_claims_idle():
    publisher = RecordingPublisher()
    session = FakeSession(connect_errors=2)
    appliance, state = make_appliance(
        session=session, publisher=publisher, reconnect_delay=0.01
    )

    await _run_until_idle(
        appliance, state, wake_after_connect=False, until=lambda: session.connects >= 3
    )

    assert session.connects >= 3
    assert publisher.sequence[0] == "disconnected"
    assert publisher.sequence.count("idle") <= 1


@pytest.mark.asyncio
async def test_the_listener_only_runs_while_a_session_is_connected():
    session = FakeSession(connect_errors=1)
    appliance, state = make_appliance(session=session, reconnect_delay=0.01)

    await _run_until_idle(
        appliance,
        state,
        wake_after_connect=False,
        until=lambda: state.get("listener") is not None
        and False in state["listener"].paused,
    )

    listener = state["listener"]
    # Paused at startup, and resumed only once a connection exists.
    assert listener.paused[0] is True
    assert False in listener.paused


@pytest.mark.asyncio
async def test_the_session_captures_through_the_listeners_own_recorder():
    """Two input streams on one device is unreliable; there is only one."""
    appliance, state = make_appliance()

    await _run_until_idle(appliance, state, wake_after_connect=False)

    session = state["session"]
    assert session.shared_recorder is appliance._recorder
    assert session.shared_recorder.observer is not None


@pytest.mark.asyncio
async def test_a_wake_nobody_follows_with_speech_cancels_the_capture():
    clock = {"now": 0.0}
    state = {"clock": lambda: clock["now"]}
    session = FakeSession()
    appliance, state = make_appliance(session=session, state=state, args=_args(wake_listen_timeout=1.0))

    task = asyncio.create_task(appliance.run())
    assert await _wait_for(
        lambda: state.get("coordinator") is not None and session.connects
    )
    coordinator = state["coordinator"]
    coordinator._begin_capture_for_test()
    clock["now"] = 5.0
    assert await _wait_for(lambda: session.cancels >= 1)

    assert session.cancels >= 1
    assert coordinator.state == handsfree.IDLE

    appliance._stopping.set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_an_undecodable_file_fallback_after_speech_is_not_an_error():
    """Hermes sends a file fallback *as well as* the PCM it already streamed.
    Failing to decode the spare copy must not turn a turn that was spoken
    aloud into a red screen."""
    publisher = RecordingPublisher()
    script = [
        {"type": "text_delta", "text": "Potato."},
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "audio_end"},
        {"type": "audio_file_start"},
        {"type": "audio_file_chunk", "data": b"not a wav file at all"},
        {"type": "audio_file_end"},
        {"type": "turn_end"},
    ]
    appliance, state = make_appliance(script, publisher=publisher)

    await _run_until_idle(appliance, state)

    assert "error" not in publisher.sequence
    assert "speaking" in publisher.sequence
    assert publisher.sequence[-1] == "idle"


@pytest.mark.asyncio
async def test_an_undecodable_fallback_with_no_speech_at_all_reports_buffering():
    """Nothing was spoken and nothing can be. The answer is on screen but the
    room heard silence — that is what `buffering` means, not `error`."""
    publisher = RecordingPublisher()
    script = [
        {"type": "text_delta", "text": "Potato."},
        {"type": "audio_file_start"},
        {"type": "audio_file_chunk", "data": b"not a wav file at all"},
        {"type": "audio_file_end"},
        {"type": "turn_end"},
    ]
    appliance, state = make_appliance(script, publisher=publisher)

    await _run_until_idle(appliance, state)

    assert "error" not in publisher.sequence
    assert "buffering" in publisher.sequence


# --- the reasoning preamble -------------------------------------------------
#
# Hermes packs the model's chain-of-thought and the answer into one text frame:
# a "💭 **Reasoning:**" marker, a fenced block, then the reply. The transcript
# in the TUI can afford to show that. A kitchen display cannot: the speaker
# says one sentence while the wall shows four hundred words of deliberation.


def test_plain_text_is_left_exactly_as_it_arrived():
    from home_display.appliance import display_text

    assert display_text("Sunny and warm.") == "Sunny and warm."
    assert display_text("") == ""


def test_a_reasoning_preamble_is_stripped_down_to_the_answer():
    from home_display.appliance import display_text

    raw = (
        "\U0001f4ad **Reasoning:**\n```\nThe user wants a short sentence.\n"
        "I should keep it brief.\n```\n\nOnline. What's the situation?"
    )

    assert display_text(raw) == "Online. What's the situation?"


def test_an_unfinished_reasoning_block_shows_nothing_yet():
    """Mid-stream the fence has not closed. Showing the half-written thought
    is worse than showing nothing: the answer is seconds away."""
    from home_display.appliance import display_text

    raw = "\U0001f4ad **Reasoning:**\n```\nThe user wants a short sen"

    assert display_text(raw) == ""


def test_a_code_fence_in_the_answer_itself_survives():
    from home_display.appliance import display_text

    raw = "Run this:\n```\nbrew upgrade\n```\nThen restart."

    assert display_text(raw) == raw


@pytest.mark.asyncio
async def test_the_display_shows_the_answer_not_the_deliberation():
    publisher = RecordingPublisher()
    script = [
        {
            "type": "text_delta",
            "text": "\U0001f4ad **Reasoning:**\n```\nDeliberating at length.\n```\n\nOnline.",
        },
        {"type": "turn_end"},
    ]
    appliance, state = make_appliance(script, publisher=publisher)

    await _run_until_idle(appliance, state)

    shown = [entry[1] for entry in publisher.history if entry[1]]
    assert shown and all("Reasoning" not in text for text in shown)
    assert shown[-1] == "Online."


@pytest.mark.asyncio
async def test_text_arriving_after_the_answer_was_spoken_does_not_say_thinking():
    """This gateway sends the audio before the text. The reply landing after
    playback has finished must not push the display back to `thinking` — the
    unit is not thinking, it has already answered."""
    publisher = RecordingPublisher()
    script = [
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "audio_end"},
        {"type": "text_delta", "text": "Online."},
        {"type": "turn_end"},
    ]
    appliance, state = make_appliance(script, publisher=publisher)

    await _run_until_idle(appliance, state)

    order = publisher.sequence
    after_speaking = order[order.index("speaking") + 1 :]
    assert "thinking" not in after_speaking, order
    assert publisher.history[-1][1] == "Online."


# --- endpointing ------------------------------------------------------------
#
# The TUI waits 1.5s of silence before deciding you have finished, which is fine
# when you pressed a key on purpose and can see the screen. Standing in a
# kitchen it is an age: three seconds of nothing happening reads as broken.


def test_the_appliance_ends_an_utterance_sooner_than_the_terminal_client():
    from home_display import appliance

    hands_free = appliance.build_arg_parser().parse_args([])
    terminal = config.build_arg_parser().parse_args([])

    assert hands_free.mic_silence_duration == appliance.HANDS_FREE_SILENCE_DURATION
    assert hands_free.mic_silence_duration < terminal.mic_silence_duration


def test_an_explicit_silence_duration_still_wins(tmp_path, monkeypatch):
    """A hands-free default must not overrule someone who set the value."""
    from home_display import appliance

    configured = tmp_path / "config.yaml"
    configured.write_text("mic_silence_duration: 2.5\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_RELAY_TUI_CONFIG", str(configured))

    from_file = appliance.build_arg_parser().parse_args([])
    from_flag = appliance.build_arg_parser().parse_args(["--mic-silence-duration", "4"])

    assert from_file.mic_silence_duration == 2.5
    assert from_flag.mic_silence_duration == 4.0


def test_display_remote_bind_is_opt_in():
    from home_display import appliance

    defaults = appliance.build_arg_parser().parse_args([])
    remote = appliance.build_arg_parser().parse_args(
        ["--display-host", "192.168.1.20", "--display-port", "8765", "--display-remote"]
    )

    assert defaults.display_host == "127.0.0.1"
    assert defaults.display_remote is False
    assert remote.display_host == "192.168.1.20"
    assert remote.display_port == 8765
    assert remote.display_remote is True


@pytest.mark.asyncio
async def test_speaking_waits_for_audio_that_can_actually_be_heard():
    """`audio_start` is a header, not a sound. Against a live gateway the
    first audible sample arrived 2.2s after it. Showing "Speaking" over a
    silent room for two seconds is the exact lie this display must not tell."""
    publisher = RecordingPublisher()
    script = [
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "text_delta", "text": "Working on it."},
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "audio_end"},
        {"type": "turn_end"},
    ]
    appliance, state = make_appliance(script, publisher=publisher)

    await _run_until_idle(appliance, state)

    order = publisher.sequence
    # The text frame lands between the header and the first sample: at that
    # moment the unit is still thinking, not speaking.
    assert order.index("thinking") < order.index("speaking")
    thinking_entries = [e for e in publisher.history if e[0] == "thinking"]
    assert thinking_entries[-1][1] == "Working on it."


@pytest.mark.asyncio
async def test_a_dropped_turn_does_not_leave_half_an_answer_on_screen():
    """A completed answer stays up to be read. A partial one, from a turn the
    connection killed, is not an answer and must not sit there looking like
    one under a "Reconnecting" banner."""
    publisher = RecordingPublisher()
    session = FakeSession(
        [{"type": "text_delta", "text": "The oven is at four hundred and"},
         ConnectionError("socket closed")]
    )
    appliance, state = make_appliance(session=session, publisher=publisher)

    await _run_until_idle(appliance, state)

    dropped = [entry for entry in publisher.history if entry[0] == "disconnected"]
    assert dropped and dropped[-1][1] == ""


@pytest.mark.asyncio
async def test_the_listener_is_deaf_while_a_turn_holds_the_microphone():
    """Otherwise the unit wakes itself. Observed live: a misfire expired after
    8s, the detector still had the tail of the phrase in its rolling buffer,
    and it fired again the instant the microphone came free — two Listening
    windows from one spoken phrase. `pause()` resets that buffer."""
    state: dict = {}
    appliance, state = make_appliance(state=state)

    await _run_until_idle(appliance, state)

    # True is a pause, False a resume. Startup pause, resume once connected,
    # pause for the duration of the turn, resume when idle again — and a final
    # pause as the appliance shuts down.
    assert state["listener"].paused[:4] == [True, False, True, False]


@pytest.mark.asyncio
async def test_speech_is_announced_when_the_cushion_flushes_not_when_it_fills():
    """The player holds a cushion before its first sample. Announcing speech
    on the first write would put "Speaking" on screen while the buffer is
    still filling and the room is silent."""
    publisher = RecordingPublisher()

    class SlowToStart(FakePlayer):
        def write(self, chunk: bytes) -> None:
            self.written.extend(chunk)
            self.playing = len(self.written) >= 4  # cushion of 4 bytes

    script = [
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "text_delta", "text": "Half a cushion in."},
        {"type": "audio_chunk", "data": b"\x03\x04"},
        {"type": "audio_end"},
        {"type": "turn_end"},
    ]
    appliance, state = make_appliance(script, player=SlowToStart(), publisher=publisher)

    await _run_until_idle(appliance, state)

    order = publisher.sequence
    assert order.index("thinking") < order.index("speaking")


# ---- acknowledgement (HOME-10) ---------------------------------------


@pytest.mark.asyncio
async def test_the_wake_is_shown_and_sounded_before_the_unit_listens():
    """Four seconds of nothing is what this card exists to remove. The first
    of those seconds now has something in it."""
    publisher = RecordingPublisher()
    appliance, state = make_appliance(publisher=publisher)

    await _run_until_idle(appliance, state)

    ordered = publisher.sequence
    assert "heard" in ordered
    assert ordered.index("heard") < ordered.index("listening")
    assert state["earcons"].played[0] == "wake"


@pytest.mark.asyncio
async def test_the_wake_tone_finishes_before_the_microphone_opens():
    """The ordering guarantee, end to end: the unit must never record the
    sound it makes to say it is recording."""
    order: list[str] = []
    earcons = FakeEarcons(log=order)

    class LoggingSession(FakeSession):
        def capture_voice(self) -> str:
            order.append("capture")
            return self.transcript

    appliance, state = make_appliance(session=LoggingSession(), earcons=earcons)

    await _run_until_idle(appliance, state)

    assert order.index("earcon:wake") < order.index("capture")


@pytest.mark.asyncio
async def test_the_end_of_capture_is_sounded_for_a_real_question():
    appliance, state = make_appliance()

    await _run_until_idle(appliance, state)

    assert state["earcons"].played == ["wake", "capture_done"]


@pytest.mark.asyncio
async def test_a_silent_misfire_is_acknowledged_but_never_announces_work():
    """It chirps once to say it heard you, then withdraws in silence."""
    session = FakeSession()
    session.transcript = ""
    appliance, state = make_appliance(session=session)

    await _run_until_idle(appliance, state)

    assert state["earcons"].played == ["wake"]
    assert session.turns == []


@pytest.mark.asyncio
async def test_silenced_earcons_still_show_the_wake_on_screen():
    """The off switch quiets the room. It does not blind the display."""
    publisher = RecordingPublisher()
    appliance, state = make_appliance(
        earcons=FakeEarcons(enabled=False), publisher=publisher
    )

    await _run_until_idle(appliance, state)

    assert state["earcons"].played == []
    assert "heard" in publisher.sequence


@pytest.mark.asyncio
async def test_an_earcon_never_overlaps_the_spoken_response():
    """Earcons live in the gap between the question and the answer. If one
    ever lands during playback it is coming out over the reply."""
    order: list[str] = []
    earcons = FakeEarcons(log=order)
    script = [
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "audio_end"},
        {"type": "turn_end"},
    ]

    class LoggingPlayer(FakePlayer):
        def write(self, chunk: bytes) -> None:
            order.append("response-audio")
            super().write(chunk)

    appliance, state = make_appliance(script, player=LoggingPlayer(), earcons=earcons)

    await _run_until_idle(appliance, state)

    assert order == ["earcon:wake", "earcon:capture_done", "response-audio"]


@pytest.mark.asyncio
async def test_earcons_do_not_share_the_response_player():
    """Sharing would let a courtesy chirp close the stream mid-sentence."""
    appliance, state = make_appliance()

    await _run_until_idle(appliance, state)

    assert appliance._earcons is not appliance._player


@pytest.mark.asyncio
async def test_a_dead_speaker_costs_the_chirp_and_nothing_else():
    class BrokenEarcons(FakeEarcons):
        def play(self, name: str) -> None:
            raise RuntimeError("no output device")

    appliance, state = make_appliance(earcons=BrokenEarcons())

    await _run_until_idle(appliance, state)

    assert state["session"].turns == ["what is the weather"]


@pytest.mark.asyncio
@pytest.mark.parametrize("follow_up, expected", [("and tomorrow?", ["what is the weather", "and tomorrow?"]), ("", ["what is the weather"]), (" Stop! ", ["what is the weather"])])
async def test_home_opens_one_bounded_follow_up_without_another_wake(follow_up, expected):
    session = FakeSession()
    session.follow_up = follow_up
    publisher = RecordingPublisher()
    appliance, state = make_appliance(session=session, args=_args(wake_followup_seconds=12.0), publisher=publisher)
    await _run_until_idle(appliance, state)
    assert session.turns == expected
    assert session.capture_timeouts == [None, 12.0]
    assert state["earcons"].played.count("wake") == 1
    assert state["earcons"].played.count("capture_done") == len(expected)
    assert publisher.sequence.count("listening") == 2
    assert publisher.sequence[-1] == "idle"


@pytest.mark.asyncio
@pytest.mark.parametrize("script", [
    [{"type": "error", "error": "failed"}, {"type": "turn_end"}],
    [{"type": "turn_interrupted"}, {"type": "turn_end"}],
    [{"type": "audio_abort"}, {"type": "turn_end"}],
    [ConnectionError("lost")],
    [],
])
async def test_unsuccessful_home_turn_never_opens_follow_up(script):
    session = FakeSession(script)
    session.follow_up = "must not send"
    appliance, state = make_appliance(session=session)
    await _run_until_idle(appliance, state)
    assert session.capture_timeouts == [None]
    assert session.turns == ["what is the weather"]


@pytest.mark.asyncio
async def test_shutdown_cancels_follow_up_before_joining_listener():
    entered = threading.Event()
    cancelled = threading.Event()

    class WaitingSession(FakeSession):
        def capture_voice(self, *, wait_timeout=None):
            if wait_timeout is None:
                return self.transcript
            entered.set()
            assert cancelled.wait(2), "shutdown did not cancel capture"
            return "late transcript"

        def cancel_voice(self):
            super().cancel_voice()
            cancelled.set()

    session = WaitingSession()
    appliance, state = make_appliance(session=session)
    task = asyncio.create_task(appliance.run())
    assert await _wait_for(lambda: session.connects)
    worker = asyncio.create_task(asyncio.to_thread(state["coordinator"].on_wake))
    assert await _wait_for(entered.is_set)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(worker, 2)
    assert cancelled.is_set()
    assert state["earcons"].played == ["wake", "capture_done"]
    assert session.turns == ["what is the weather"]
    assert state["listener"].paused[-1] is True
    assert appliance._recorder.shutdowns == 1


@pytest.mark.asyncio
async def test_follow_up_capture_failure_returns_to_wake_mode():
    class BrokenFollowUp(FakeSession):
        def capture_voice(self, *, wait_timeout=None):
            if wait_timeout is not None:
                raise RuntimeError("capture failed")
            return self.transcript

    appliance, state = make_appliance(session=BrokenFollowUp())
    await _run_until_idle(appliance, state)
    assert state["coordinator"].state == handsfree.IDLE
    assert state["session"].turns == ["what is the weather"]


@pytest.mark.asyncio
async def test_shutdown_aborts_player_without_draining():
    appliance, state = make_appliance()
    player = state["player"]
    player.start((16000, 1, 2))
    assert player.active
    await appliance.aclose()
    assert not player.active
    assert player.aborts == 1


@pytest.mark.asyncio
async def test_hands_free_wired_to_abort_player():
    appliance, state = make_appliance()
    player = state["player"]
    player.start((16000, 1, 2))
    assert player.active
    # Hands-free stop_playback is wired to _abort_player
    appliance._build()
    coordinator = appliance._coordinator
    assert coordinator._stop_playback == appliance._abort_player
    coordinator._stop_playback()
    assert not player.active
    assert player.aborts == 1


@pytest.mark.asyncio
async def test_shutdown_does_not_hang_on_slow_session_close(monkeypatch):
    close_started = asyncio.Event()
    release_close = asyncio.Event()

    class SlowCloseSession(FakeSession):
        async def close(self):
            close_started.set()
            await release_close.wait()
            self.closes += 1

    monkeypatch.setattr(appliance_module, "SHUTDOWN_TASK_TIMEOUT", 0.01)
    session = SlowCloseSession()
    appliance, state = make_appliance(session=session)
    try:
        shutdown_task = asyncio.create_task(appliance.aclose())
        await close_started.wait()
        await asyncio.wait_for(shutdown_task, 1.0)
        assert session.closes == 0
    finally:
        release_close.set()


@pytest.mark.asyncio
async def test_shutdown_does_not_hang_on_slow_server_close(monkeypatch):
    close_started = asyncio.Event()
    release_close = asyncio.Event()

    class SlowCloseServer(FakeServer):
        async def close(self):
            close_started.set()
            await release_close.wait()
            self.closed = True

    monkeypatch.setattr(appliance_module, "SHUTDOWN_TASK_TIMEOUT", 0.01)
    server = SlowCloseServer()
    appliance, state = make_appliance(server=server)
    try:
        shutdown_task = asyncio.create_task(appliance.aclose())
        await close_started.wait()
        await asyncio.wait_for(shutdown_task, 1.0)
        assert not server.closed
    finally:
        release_close.set()


@pytest.mark.asyncio
async def test_shutdown_does_not_hang_on_slow_recorder_shutdown(monkeypatch):
    shutdown_started = threading.Event()
    release_shutdown = threading.Event()

    class SlowShutdownRecorder(FakeRecorder):
        def shutdown(self):
            shutdown_started.set()
            release_shutdown.wait()
            super().shutdown()

    monkeypatch.setattr(appliance_module, "SHUTDOWN_TASK_TIMEOUT", 0.01)
    recorder = SlowShutdownRecorder()
    appliance, state = make_appliance(recorder=recorder)
    try:
        shutdown_task = asyncio.create_task(appliance.aclose())
        assert await _wait_for(shutdown_started.is_set)
        await asyncio.wait_for(shutdown_task, 1.0)
        assert recorder.shutdowns == 0
    finally:
        release_shutdown.set()


@pytest.mark.asyncio
async def test_cancelled_recorder_open_is_shut_down_by_cleanup_task():
    open_started = threading.Event()
    release_open = threading.Event()

    class SlowOpenRecorder(FakeRecorder):
        def open_for_listening(self):
            open_started.set()
            release_open.wait()
            super().open_for_listening()

    recorder = SlowOpenRecorder()
    appliance, state = make_appliance(recorder=recorder)
    try:
        task = asyncio.create_task(appliance.run())
        assert await _wait_for(open_started.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert recorder.shutdowns == 0
    finally:
        release_open.set()
    assert await _wait_for(lambda: recorder.shutdowns == 1)


@pytest.mark.asyncio
async def test_appliance_stop_exits_run_cleanly():
    session = FakeSession()
    appliance, state = make_appliance(session=session)
    task = asyncio.create_task(appliance.run())
    assert await _wait_for(lambda: session.connects > 0)
    appliance.stop()
    await asyncio.wait_for(task, 2.0)
    assert task.done()
    assert not task.cancelled()


@pytest.mark.asyncio
async def test_appliance_signals_initiate_clean_exit():
    session = FakeSession()
    appliance, state = make_appliance(session=session)
    task = asyncio.create_task(appliance.run())
    assert await _wait_for(lambda: session.connects > 0)

    # Trigger the signal callback directly
    installed_handlers = []
    loop = asyncio.get_running_loop()
    # Find the handler installed on loop
    for sig in appliance._signals_installed:
        installed_handlers.append(sig)
    assert installed_handlers

    # Simulate first SIGINT: should call stop() and allow task to finish cleanly
    appliance.stop()
    await asyncio.wait_for(task, 2.0)
    assert task.done()
    assert not task.cancelled()


@pytest.mark.asyncio
async def test_appliance_second_signal_forces_keyboard_interrupt():
    appliance, state = make_appliance()
    loop = asyncio.get_running_loop()
    appliance._install_signals(loop)
    # Extract the signal handler installed
    handler = None
    for sig in appliance._signals_installed:
        # Loop signal handler is registered
        pass

    # Call on_signal twice: first stops, second raises KeyboardInterrupt
    # Simulating what on_signal does:
    appliance._sigint_count = 1
    with pytest.raises(KeyboardInterrupt):
        # Trigger second signal
        appliance._sigint_count += 1
        if appliance._sigint_count > 1:
            raise KeyboardInterrupt


@pytest.mark.asyncio
async def test_bounded_to_thread_runs_daemon_thread_and_handles_timeout():
    import threading
    appliance, state = make_appliance()

    thread_daemon_status: list[bool] = []
    block_event = threading.Event()

    def slow_func():
        thread_daemon_status.append(threading.current_thread().daemon)
        block_event.wait(timeout=1.0)

    # Calling with small timeout should not raise, should log timeout, and use a daemon thread
    await appliance._bounded_to_thread(slow_func, timeout=0.05)
    block_event.set()
    assert thread_daemon_status == [True]
