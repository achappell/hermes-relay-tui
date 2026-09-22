"""Tests for the ESP32 Touch doorway: admission, bounds, phases, no replay."""

import asyncio
import json
import urllib.error
import urllib.request

import pytest
from websockets.legacy.client import connect

import home_display.server as server_module
import home_display.touch as touch_module
from home_display.server import DisplayServer, TouchFrame
from home_display.state import DisplayStatePublisher
from home_display.touch import (
    MAX_CAPTURE_BYTES,
    MAX_FINAL_TRANSCRIPT_CHARACTERS,
    MAX_PCM_CHUNK_BYTES,
    TOUCH_CLAIM_PATH,
    TouchClaimError,
    TouchConfigurationError,
    TouchDeviceConfig,
    TouchDoorway,
    load_touch_device_config,
    touch_claim_url,
)


BRIDGE_URL = "wss://home.example/api/v1/bridge/ws"


def _device_config() -> TouchDeviceConfig:
    return TouchDeviceConfig(
        device_id="touch-kitchen",
        config_revision="rev-7",
        credential="device-credential",
        claim_url=f"https://home.example{TOUCH_CLAIM_PATH}",
        bridge_url=BRIDGE_URL,
    )


class RecordingPublisher(DisplayStatePublisher):
    """A real publisher that also remembers the phase sequence it emitted."""

    def __init__(self) -> None:
        super().__init__()
        self.states: list[str] = []

    def publish(self, **kwargs):
        snapshot = super().publish(**kwargs)
        self.states.append(snapshot.state)
        return snapshot


class FakeSender:
    def __init__(self, *, fail_audio_start: bool = False) -> None:
        self.controls: list[dict] = []
        self.audio: list[tuple] = []
        self.fail_audio_start = fail_audio_start

    async def send_control(self, payload):
        self.controls.append(payload)
        return True

    async def send_audio_start(self, *, turn_id, sample_rate, channels, sample_width):
        if self.fail_audio_start:
            raise ConnectionError("browser connection is closed")
        self.audio.append(("start", turn_id, sample_rate, channels, sample_width))

    async def send_audio_chunk(self, data):
        self.audio.append(("chunk", data))

    async def send_audio_end(self, *, turn_id):
        self.audio.append(("end", turn_id))

    async def send_audio_abort(self, *, turn_id, reason):
        self.audio.append(("abort", turn_id, reason))

    async def close(self, **_kwargs):
        return None

    @property
    def control_types(self) -> list[str]:
        return [str(control.get("type")) for control in self.controls]


class FakeClaimClient:
    def __init__(self, handle="handle-1", error: Exception | None = None) -> None:
        self.handle = handle
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def claim(self, *, claim_id, observed_at):
        self.calls.append((claim_id, observed_at))
        if self.error is not None:
            raise self.error
        return self.handle


class FakeSession:
    def __init__(self, events=None, *, gate: asyncio.Event | None = None) -> None:
        self._events = list(events or [{"type": "turn_end"}])
        self._gate = gate
        self.prompts: list[str] = []
        self.active_turn_id = "turn-1"
        self.interrupts = 0
        self.closed = False

    def send_turn(self, text, **_kwargs):
        self.prompts.append(text)
        return self._stream()

    async def _stream(self):
        for index, event in enumerate(self._events):
            if self._gate is not None and index == 1:
                await self._gate.wait()
            if isinstance(event, Exception):
                raise event
            yield event

    async def interrupt_active_turn(self):
        self.interrupts += 1
        return True

    async def close(self):
        self.closed = True


def _doorway(
    *,
    publisher=None,
    sender=None,
    claim_client=None,
    session=None,
    transcript="turn on the lights",
    transcriber=None,
    connection_id="touch-1",
):
    resolved_session = session if session is not None else FakeSession()

    async def session_factory(handle):
        resolved_session.handle = handle
        return resolved_session

    return TouchDoorway(
        connection_id=connection_id,
        publisher=publisher or RecordingPublisher(),
        sender=sender or FakeSender(),
        device_config=_device_config(),
        claim_client=claim_client or FakeClaimClient(),
        session_factory=session_factory,
        transcriber=transcriber
        or (lambda pcm: {"success": True, "transcript": transcript}),
        id_factory=lambda: "claim-id",
    )


async def _settle(doorway: TouchDoorway) -> None:
    """Wait for the doorway's single turn task, if one was started."""
    task = doorway._turn_task
    if task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(task), 5)
        except asyncio.CancelledError:
            pass
    await asyncio.sleep(0)


async def _capture(doorway, capture_id="c1", chunks=(b"\x01\x02" * 8,)):
    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id=capture_id))
    await doorway.handle_touch_frame(
        TouchFrame("mic_capture_started", capture_id=capture_id)
    )
    for chunk in chunks:
        await doorway.handle_touch_audio(chunk)
    await doorway.handle_touch_frame(TouchFrame("mic_end", capture_id=capture_id))
    await _settle(doorway)


# ---- configuration fails closed ----------------------------------------


def test_claim_url_is_derived_from_the_one_configured_bridge_route():
    assert touch_claim_url(BRIDGE_URL) == f"https://home.example{TOUCH_CLAIM_PATH}"


def test_claim_url_rejects_a_route_that_is_not_the_approved_bridge():
    with pytest.raises(TouchConfigurationError):
        touch_claim_url("https://home.example/api/v1/bridge/ws")


class _Args:
    def __init__(self, **kwargs):
        self.home_bridge_url = BRIDGE_URL
        self.touch_device_id = "touch-kitchen"
        self.touch_config_revision = "rev-7"
        self.touch_claim_url = ""
        self.home_device_credential_file = None
        self.profile_env = None
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_touch_configuration_fails_closed_without_approved_credential_storage(tmp_path):
    missing = tmp_path / "absent.credential"
    with pytest.raises(TouchConfigurationError, match="credential storage"):
        load_touch_device_config(_Args(home_device_credential_file=missing))


def test_touch_configuration_fails_closed_without_a_device_identity(tmp_path):
    credential = tmp_path / "credential"
    credential.write_text("secret", encoding="utf-8")
    with pytest.raises(TouchConfigurationError, match="touch-device-id"):
        load_touch_device_config(
            _Args(touch_device_id="", home_device_credential_file=credential)
        )


def test_touch_configuration_refuses_a_plaintext_remote_claim_route(tmp_path):
    credential = tmp_path / "credential"
    credential.write_text("secret", encoding="utf-8")
    with pytest.raises(TouchConfigurationError, match="https"):
        load_touch_device_config(
            _Args(
                touch_claim_url="http://home.example/api/v1/touch-claims",
                home_device_credential_file=credential,
            )
        )


def test_device_config_never_reveals_its_credential_in_a_repr():
    assert "device-credential" not in repr(_device_config())


# ---- HttpTouchClaimClient ------------------------------------------------


class _FakeHttpResponse:
    """A minimal stand-in for `urlopen`'s context-manager response."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self, _size: int = -1) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


@pytest.mark.asyncio
async def test_http_touch_claim_client_returns_the_granted_handle(monkeypatch):
    def fake_urlopen(request, timeout=None):
        assert request.full_url == _device_config().claim_url
        assert request.get_header("Authorization") == "Bearer device-credential"
        return _FakeHttpResponse(
            json.dumps({"conversation_handle": " granted-1 "}).encode("utf-8")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = touch_module.HttpTouchClaimClient(_device_config())

    handle = await client.claim(claim_id="c1", observed_at="2026-01-01T00:00:00+00:00")

    assert handle == "granted-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_http_touch_claim_client_maps_auth_failures_to_unauthorized(
    monkeypatch, status
):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, status, "denied", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = touch_module.HttpTouchClaimClient(_device_config())

    with pytest.raises(touch_module.TouchClaimError) as excinfo:
        await client.claim(claim_id="c1", observed_at="now")

    assert excinfo.value.reason == "unauthorized"


@pytest.mark.asyncio
async def test_http_touch_claim_client_maps_other_http_errors_to_unavailable(
    monkeypatch,
):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 500, "boom", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = touch_module.HttpTouchClaimClient(_device_config())

    with pytest.raises(touch_module.TouchClaimError) as excinfo:
        await client.claim(claim_id="c1", observed_at="now")

    assert excinfo.value.reason == "unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        json.dumps({}).encode("utf-8"),
        json.dumps({"conversation_handle": ""}).encode("utf-8"),
        json.dumps({"conversation_handle": "   "}).encode("utf-8"),
        json.dumps([1, 2, 3]).encode("utf-8"),
    ],
    ids=["not-json", "missing-handle", "empty-handle", "blank-handle", "not-an-object"],
)
async def test_http_touch_claim_client_rejects_a_malformed_body(monkeypatch, body):
    def fake_urlopen(request, timeout=None):
        return _FakeHttpResponse(body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = touch_module.HttpTouchClaimClient(_device_config())

    with pytest.raises(touch_module.TouchClaimError) as excinfo:
        await client.claim(claim_id="c1", observed_at="now")

    assert excinfo.value.reason == "unavailable"


# ---- admission ----------------------------------------------------------


@pytest.mark.asyncio
async def test_unadmitted_mic_start_is_rejected_without_a_session_or_pcm():
    sender = FakeSender()
    claim = FakeClaimClient(error=TouchClaimError("unauthorized"))
    doorway = _doorway(sender=sender, claim_client=claim)

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await doorway.handle_touch_audio(b"\x01\x02")

    assert sender.control_types == ["mic_reject"]
    assert sender.controls[0]["reason"] == "unauthorized"
    assert doorway._session is None
    assert doorway._capture is None


@pytest.mark.asyncio
async def test_a_ready_claim_publishes_heard_and_sends_mic_ready():
    sender = FakeSender()
    publisher = RecordingPublisher()
    claim = FakeClaimClient()
    doorway = _doorway(sender=sender, publisher=publisher, claim_client=claim)

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))

    assert sender.controls == [
        {"type": "mic_ready", "schema": 1, "capture_id": "c1", "capture_terminal": True}
    ]
    assert publisher.snapshot.state == "heard"
    assert claim.calls == [("claim-id", claim.calls[0][1])]


@pytest.mark.asyncio
async def test_one_bounded_capture_produces_exactly_one_home_turn():
    session = FakeSession(
        [
            {"type": "text_delta", "text": "Lights on."},
            {"type": "turn_end"},
        ]
    )
    publisher = RecordingPublisher()
    doorway = _doorway(session=session, publisher=publisher)

    await _capture(doorway)

    assert session.prompts == ["turn on the lights"]
    assert publisher.snapshot.state == "complete"
    assert publisher.snapshot.response_text == "Lights on."
    assert publisher.snapshot.transcript_text == "turn on the lights"
    assert "transcribing" in publisher.states


@pytest.mark.asyncio
async def test_the_transcript_is_published_apart_from_the_response_text():
    session = FakeSession(
        [{"type": "text_replace", "text": "Done."}, {"type": "turn_end"}]
    )
    publisher = RecordingPublisher()
    doorway = _doorway(session=session, publisher=publisher, transcript="hello there")

    await _capture(doorway)

    snapshot = publisher.snapshot
    assert snapshot.transcript_text == "hello there"
    assert snapshot.response_text == "Done."


@pytest.mark.asyncio
async def test_pcm_before_capture_started_is_rejected_and_clears_the_capture():
    publisher = RecordingPublisher()
    doorway = _doorway(publisher=publisher)

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await doorway.handle_touch_audio(b"\x01\x02")

    assert doorway._capture is None
    assert publisher.snapshot.state == "idle"
    assert "listening" not in publisher.states


@pytest.mark.asyncio
async def test_capture_started_publishes_listening_and_admits_that_capture_only():
    publisher = RecordingPublisher()
    doorway = _doorway(publisher=publisher)

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await doorway.handle_touch_frame(
        TouchFrame("mic_capture_started", capture_id="c1")
    )
    assert publisher.snapshot.state == "listening"

    await doorway.handle_touch_audio(b"\x01\x02" * 4)
    assert doorway._capture is not None
    assert doorway._capture.total_bytes == 8


@pytest.mark.asyncio
async def test_capture_started_for_another_capture_id_clears_transient_state():
    session = FakeSession()
    doorway = _doorway(session=session)

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await doorway.handle_touch_frame(
        TouchFrame("mic_capture_started", capture_id="c2")
    )

    assert doorway._capture is None
    assert session.prompts == []


@pytest.mark.asyncio
async def test_a_terminal_turn_lets_the_same_socket_reuse_its_ready_binding():
    session = FakeSession([{"type": "turn_end"}, {"type": "turn_end"}])
    claim = FakeClaimClient()
    doorway = _doorway(session=session, claim_client=claim)

    await _capture(doorway, "c1")
    await _capture(doorway, "c2")

    assert len(claim.calls) == 1
    assert session.prompts == ["turn on the lights", "turn on the lights"]


@pytest.mark.asyncio
async def test_a_second_socket_claims_admission_independently():
    claim = FakeClaimClient()
    first = _doorway(claim_client=claim, connection_id="touch-1")
    second = _doorway(claim_client=claim, connection_id="touch-2")

    await first.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await second.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))

    assert len(claim.calls) == 2


# ---- bounds and malformed input ----------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chunk",
    [b"\x01", b"", b"\x00" * (MAX_PCM_CHUNK_BYTES + 2)],
    ids=["odd-length", "empty", "oversized-chunk"],
)
async def test_invalid_pcm_clears_the_capture_and_creates_no_turn(chunk):
    session = FakeSession()
    doorway = _doorway(session=session)

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await doorway.handle_touch_frame(
        TouchFrame("mic_capture_started", capture_id="c1")
    )
    await doorway.handle_touch_audio(chunk)
    await doorway.handle_touch_frame(TouchFrame("mic_end", capture_id="c1"))
    await _settle(doorway)

    assert doorway._capture is None
    assert session.prompts == []


@pytest.mark.asyncio
async def test_a_capture_over_the_total_byte_budget_is_dropped():
    session = FakeSession()
    doorway = _doorway(session=session)

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await doorway.handle_touch_frame(
        TouchFrame("mic_capture_started", capture_id="c1")
    )
    chunk = b"\x00" * MAX_PCM_CHUNK_BYTES
    sent = 0
    while sent + MAX_PCM_CHUNK_BYTES <= MAX_CAPTURE_BYTES:
        await doorway.handle_touch_audio(chunk)
        sent += MAX_PCM_CHUNK_BYTES
    assert doorway._capture is not None
    # One chunk past the budget takes the whole capture with it.
    await doorway.handle_touch_audio(chunk)

    assert doorway._capture is None
    assert session.prompts == []


@pytest.mark.asyncio
async def test_a_duplicate_mic_start_is_rejected_and_drops_the_open_capture():
    sender = FakeSender()
    session = FakeSession()
    doorway = _doorway(sender=sender, session=session)

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await doorway.handle_touch_frame(
        TouchFrame("mic_capture_started", capture_id="c1")
    )
    await doorway.handle_touch_audio(b"\x01\x02")
    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c2"))

    assert sender.control_types == ["mic_ready", "mic_terminal", "mic_reject"]
    assert doorway._capture is None
    assert session.prompts == []


@pytest.mark.asyncio
async def test_a_stale_mic_end_clears_state_and_creates_no_turn():
    session = FakeSession()
    doorway = _doorway(session=session)

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await doorway.handle_touch_frame(
        TouchFrame("mic_capture_started", capture_id="c1")
    )
    await doorway.handle_touch_audio(b"\x01\x02")
    await doorway.handle_touch_frame(TouchFrame("mic_end", capture_id="stale"))
    await _settle(doorway)

    assert doorway._capture is None
    assert session.prompts == []


@pytest.mark.asyncio
async def test_mic_abort_clears_audio_and_submits_nothing():
    session = FakeSession()
    publisher = RecordingPublisher()
    doorway = _doorway(session=session, publisher=publisher)

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await doorway.handle_touch_frame(
        TouchFrame("mic_capture_started", capture_id="c1")
    )
    await doorway.handle_touch_audio(b"\x01\x02")
    await doorway.handle_touch_frame(TouchFrame("mic_abort", capture_id="c1"))

    assert doorway._capture is None
    assert session.prompts == []
    assert publisher.snapshot.state == "idle"


@pytest.mark.asyncio
async def test_an_empty_transcript_submits_nothing():
    session = FakeSession()
    publisher = RecordingPublisher()
    doorway = _doorway(session=session, publisher=publisher, transcript="   ")

    await _capture(doorway)

    assert session.prompts == []
    assert publisher.snapshot.state == "idle"
    assert publisher.snapshot.transcript_text == ""


@pytest.mark.asyncio
async def test_a_failed_transcription_submits_nothing():
    session = FakeSession()
    doorway = _doorway(
        session=session,
        transcriber=lambda pcm: {"success": False, "transcript": "", "error": "x"},
    )

    await _capture(doorway)

    assert session.prompts == []


@pytest.mark.asyncio
async def test_a_whisper_hallucination_transcript_submits_nothing():
    """`_is_hallucination`'s gate inside `_transcribe_and_submit`, verified."""
    import voice as voice_module

    assert voice_module.is_whisper_hallucination("thank you.") is True

    session = FakeSession()
    publisher = RecordingPublisher()
    doorway = _doorway(session=session, publisher=publisher, transcript="thank you.")

    await _capture(doorway)

    assert session.prompts == []
    assert publisher.snapshot.state == "idle"


@pytest.mark.asyncio
async def test_a_long_transcript_is_bounded_before_it_reaches_home():
    session = FakeSession()
    doorway = _doorway(session=session, transcript="a" * (MAX_FINAL_TRANSCRIPT_CHARACTERS + 500))

    await _capture(doorway)

    assert len(session.prompts[0]) == MAX_FINAL_TRANSCRIPT_CHARACTERS


@pytest.mark.asyncio
async def test_a_malformed_frame_clears_the_capture_and_reports_the_rejection():
    sender = FakeSender()
    session = FakeSession()
    doorway = _doorway(sender=sender, session=session)

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await doorway.handle_touch_malformed("malformed")

    assert doorway._capture is None
    assert sender.control_types == ["mic_ready", "mic_terminal"]
    assert session.prompts == []


@pytest.mark.asyncio
async def test_an_unknown_frame_type_is_treated_as_malformed():
    sender = FakeSender()
    doorway = _doorway(sender=sender)

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await doorway.handle_touch_frame(TouchFrame("mic_shout", capture_id="c1"))

    assert doorway._capture is None
    assert sender.control_types == ["mic_ready", "mic_terminal"]


# ---- isolation ----------------------------------------------------------


@pytest.mark.asyncio
async def test_one_doorways_capture_state_and_audio_never_reach_another():
    first_publisher = RecordingPublisher()
    first_sender = FakeSender()
    second_publisher = RecordingPublisher()
    second_sender = FakeSender()
    first = _doorway(
        publisher=first_publisher,
        sender=first_sender,
        session=FakeSession(
            [
                {
                    "type": "audio_start",
                    "sample_rate": 24000,
                    "channels": 1,
                    "sample_width": 2,
                },
                {"type": "audio_chunk", "data": b"\x10\x11"},
                {"type": "turn_end"},
            ]
        ),
        connection_id="touch-1",
    )
    second = _doorway(
        publisher=second_publisher,
        sender=second_sender,
        connection_id="touch-2",
    )

    await _capture(first)

    assert any(entry[0] == "chunk" for entry in first_sender.audio)
    assert second_sender.audio == []
    assert second_sender.controls == []
    assert second_publisher.snapshot.state == "idle"
    assert second_publisher.snapshot.transcript_text == ""
    assert second._session is None


# ---- response audio, playback truth, and completion --------------------


@pytest.mark.asyncio
async def test_response_audio_reaches_only_the_owning_doorway_with_its_format():
    sender = FakeSender()
    session = FakeSession(
        [
            {
                "type": "audio_start",
                "sample_rate": 24000,
                "channels": 1,
                "sample_width": 2,
            },
            {"type": "audio_chunk", "data": b"\x01\x02\x03\x04"},
            {"type": "turn_end"},
        ]
    )
    doorway = _doorway(sender=sender, session=session)

    await _capture(doorway)

    assert sender.audio[0] == ("start", "turn-1", 24000, 1, 2)
    assert ("chunk", b"\x01\x02\x03\x04") in sender.audio
    assert ("end", "turn-1") in sender.audio


@pytest.mark.asyncio
async def test_speaking_is_published_only_after_the_endpoint_reports_playback():
    gate = asyncio.Event()
    session = FakeSession(
        [
            {
                "type": "audio_start",
                "sample_rate": 24000,
                "channels": 1,
                "sample_width": 2,
            },
            {"type": "text_delta", "text": "Hello"},
            {"type": "turn_end"},
        ],
        gate=gate,
    )
    publisher = RecordingPublisher()
    doorway = _doorway(session=session, publisher=publisher)

    await _capture_without_settle(doorway)
    await _wait_for_state(publisher, "buffering")
    assert "speaking" not in publisher.states

    await doorway.handle_touch_frame(
        TouchFrame("audio_playback_started", turn_id="turn-1")
    )
    assert publisher.snapshot.state == "speaking"

    gate.set()
    await _settle(doorway)
    assert publisher.snapshot.state == "complete"


@pytest.mark.asyncio
async def test_playback_failure_keeps_completed_text_without_claiming_speech():
    gate = asyncio.Event()
    session = FakeSession(
        [
            {
                "type": "audio_start",
                "sample_rate": 24000,
                "channels": 1,
                "sample_width": 2,
            },
            {"type": "text_delta", "text": "Hello"},
            {"type": "turn_end"},
        ],
        gate=gate,
    )
    publisher = RecordingPublisher()
    doorway = _doorway(session=session, publisher=publisher)

    await _capture_without_settle(doorway)
    await _wait_for_state(publisher, "buffering")
    await doorway.handle_touch_frame(
        TouchFrame("audio_playback_failed", turn_id="turn-1")
    )
    gate.set()
    await _settle(doorway)

    assert "speaking" not in publisher.states
    assert publisher.snapshot.state == "complete"
    assert publisher.snapshot.response_text == "Hello"
    assert publisher.snapshot.status_text == touch_module.AUDIO_UNAVAILABLE_STATUS


@pytest.mark.asyncio
async def test_a_playback_report_for_another_turn_is_ignored():
    gate = asyncio.Event()
    session = FakeSession(
        [
            {
                "type": "audio_start",
                "sample_rate": 24000,
                "channels": 1,
                "sample_width": 2,
            },
            {"type": "text_delta", "text": "Hello"},
            {"type": "turn_end"},
        ],
        gate=gate,
    )
    publisher = RecordingPublisher()
    doorway = _doorway(session=session, publisher=publisher)

    await _capture_without_settle(doorway)
    await _wait_for_state(publisher, "buffering")
    await doorway.handle_touch_frame(
        TouchFrame("audio_playback_started", turn_id="someone-elses-turn")
    )
    assert publisher.snapshot.state == "buffering"

    gate.set()
    await _settle(doorway)


@pytest.mark.asyncio
async def test_complete_is_never_published_before_homes_terminal_event():
    gate = asyncio.Event()
    session = FakeSession(
        [
            {"type": "text_delta", "text": "Thinking about it"},
            {"type": "turn_end"},
        ],
        gate=gate,
    )
    publisher = RecordingPublisher()
    doorway = _doorway(session=session, publisher=publisher)

    await _capture_without_settle(doorway)
    await _wait_for_state(publisher, "thinking")
    assert "complete" not in publisher.states

    gate.set()
    await _settle(doorway)
    assert publisher.snapshot.state == "complete"


@pytest.mark.asyncio
async def test_a_failed_response_audio_open_reports_unavailable_audio():
    sender = FakeSender(fail_audio_start=True)
    session = FakeSession(
        [
            {
                "type": "audio_start",
                "sample_rate": 24000,
                "channels": 1,
                "sample_width": 2,
            },
            {"type": "text_delta", "text": "Hello"},
            {"type": "turn_end"},
        ]
    )
    publisher = RecordingPublisher()
    doorway = _doorway(sender=sender, session=session, publisher=publisher)

    await _capture(doorway)

    assert "speaking" not in publisher.states
    assert publisher.snapshot.state == "complete"
    assert publisher.snapshot.response_text == "Hello"
    assert publisher.snapshot.status_text == touch_module.AUDIO_UNAVAILABLE_STATUS


# ---- stop, interruption, and no replay ---------------------------------


@pytest.mark.asyncio
async def test_turn_stop_before_submission_aborts_the_capture_without_a_turn():
    session = FakeSession()
    publisher = RecordingPublisher()
    doorway = _doorway(session=session, publisher=publisher)

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await doorway.handle_touch_frame(
        TouchFrame("mic_capture_started", capture_id="c1")
    )
    await doorway.handle_touch_audio(b"\x01\x02")
    await doorway.handle_touch_frame(TouchFrame("turn_stop"))

    assert doorway._capture is None
    assert session.prompts == []
    assert publisher.snapshot.state == "idle"


@pytest.mark.asyncio
async def test_a_stop_during_submission_is_latched_until_the_turn_id_exists():
    released = asyncio.Event()
    loop = asyncio.get_running_loop()

    def slow_transcriber(_pcm):
        asyncio.run_coroutine_threadsafe(_set(released), loop)
        # Block until the test has had a chance to send `turn_stop`.
        import time

        time.sleep(0.05)
        return {"success": True, "transcript": "stop that"}

    async def _set(event):
        event.set()

    session = FakeSession([{"type": "turn_interrupted"}])
    publisher = RecordingPublisher()
    doorway = _doorway(
        session=session, publisher=publisher, transcriber=slow_transcriber
    )

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await doorway.handle_touch_frame(
        TouchFrame("mic_capture_started", capture_id="c1")
    )
    await doorway.handle_touch_audio(b"\x01\x02")
    await doorway.handle_touch_frame(TouchFrame("mic_end", capture_id="c1"))

    await asyncio.wait_for(released.wait(), 5)
    await doorway.handle_touch_frame(TouchFrame("turn_stop"))
    # No Home turn exists yet, so the stop is held rather than spent.
    assert session.interrupts == 0

    await _settle(doorway)
    assert session.interrupts == 1
    assert session.prompts == ["stop that"]
    assert publisher.snapshot.state == "complete"


@pytest.mark.asyncio
async def test_a_transport_failure_mid_turn_is_never_replayed():
    session = FakeSession(
        [
            {"type": "text_delta", "text": "partial"},
            ConnectionError("socket died"),
        ]
    )
    publisher = RecordingPublisher()
    doorway = _doorway(session=session, publisher=publisher)

    await _capture(doorway)

    assert session.prompts == ["turn on the lights"]
    assert publisher.snapshot.state == "disconnected"

    await doorway.close()
    assert session.prompts == ["turn on the lights"]


@pytest.mark.asyncio
async def test_closing_a_doorway_discards_the_unsubmitted_capture():
    session = FakeSession()
    doorway = _doorway(session=session)

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))
    await doorway.handle_touch_frame(
        TouchFrame("mic_capture_started", capture_id="c1")
    )
    await doorway.handle_touch_audio(b"\x01\x02")
    await doorway.close()

    assert doorway._capture is None
    assert session.prompts == []
    assert session.closed is True


@pytest.mark.asyncio
async def test_a_closed_doorway_accepts_no_further_frames():
    sender = FakeSender()
    doorway = _doorway(sender=sender)
    await doorway.close()

    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="c1"))

    assert sender.controls == []


# ---- helpers used by the gated tests -----------------------------------


async def _capture_without_settle(doorway, capture_id="c1"):
    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id=capture_id))
    await doorway.handle_touch_frame(
        TouchFrame("mic_capture_started", capture_id=capture_id)
    )
    await doorway.handle_touch_audio(b"\x01\x02" * 8)
    await doorway.handle_touch_frame(TouchFrame("mic_end", capture_id=capture_id))


async def _wait_for_state(publisher, state, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if publisher.snapshot.state == state:
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"never reached {state}: {publisher.states}")


# ---- display server ingress --------------------------------------------


def test_touch_frames_require_schema_one_and_bounded_identifiers():
    parse = DisplayServer._parse_touch_frame

    assert parse(json.dumps({"type": "mic_start", "schema": 1, "capture_id": "c1"})) == (
        TouchFrame("mic_start", capture_id="c1")
    )
    assert parse(json.dumps({"type": "turn_stop", "schema": 1})) == TouchFrame(
        "turn_stop"
    )
    assert parse(
        json.dumps({"type": "audio_playback_started", "schema": 1, "turn_id": "t1"})
    ) == TouchFrame("audio_playback_started", turn_id="t1")

    assert parse(json.dumps({"type": "mic_start", "schema": 2, "capture_id": "c"})) is None
    assert parse(json.dumps({"type": "mic_start", "schema": 1})) is None
    assert parse(json.dumps({"type": "mic_start", "schema": 1, "capture_id": ""})) is None
    assert (
        parse(json.dumps({"type": "mic_start", "schema": 1, "capture_id": "a" * 65}))
        is None
    )
    assert (
        parse(json.dumps({"type": "mic_start", "schema": 1, "capture_id": "a b"}))
        is None
    )
    assert parse(json.dumps({"type": "voice_turn", "schema": 1, "text": "hi"})) is None
    assert parse("not json") is None
    assert parse(json.dumps([1, 2, 3])) is None


def test_touch_mode_cannot_be_combined_with_a_browser_factory(tmp_path):
    async def factory(_connection_id, _sender):
        return None

    with pytest.raises(ValueError, match="browser context factory"):
        DisplayServer(
            DisplayStatePublisher(),
            tmp_path,
            on_browser_connect=factory,
            on_touch_connect=factory,
        )


class _RecordingBinding:
    def __init__(self) -> None:
        self.publisher = DisplayStatePublisher()
        self.frames: list = []
        self.audio: list[bytes] = []
        self.malformed: list[str] = []
        self.closed = False

    async def handle_touch_frame(self, frame):
        self.frames.append(frame)

    async def handle_touch_audio(self, data):
        self.audio.append(data)

    async def handle_touch_malformed(self, reason="malformed"):
        self.malformed.append(reason)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_the_server_routes_touch_control_frames_and_binary_pcm(tmp_path):
    (tmp_path / "index.html").write_text("touch", encoding="utf-8")
    binding = _RecordingBinding()

    async def factory(_connection_id, _sender):
        return binding

    server = DisplayServer(DisplayStatePublisher(), tmp_path, on_touch_connect=factory)
    assert server.touch_contexts_enabled is True
    info = await server.start()
    try:
        async with connect(info.websocket_url) as socket:
            assert json.loads(await socket.recv())["state"] == "idle"
            await socket.send(
                json.dumps({"type": "mic_start", "schema": 1, "capture_id": "c1"})
            )
            await socket.send(b"\x01\x02\x03\x04")
            await socket.send(b"\x01")  # odd length: rejected before the doorway
            await socket.send(json.dumps({"type": "garbage"}))
            for _ in range(200):
                if binding.frames and binding.audio and len(binding.malformed) >= 2:
                    break
                await asyncio.sleep(0.01)
        assert binding.frames == [TouchFrame("mic_start", capture_id="c1")]
        assert binding.audio == [b"\x01\x02\x03\x04"]
        assert binding.malformed == ["malformed", "malformed"]
    finally:
        await server.close()
    assert binding.closed is True


@pytest.mark.asyncio
async def test_the_server_rejects_an_oversized_pcm_chunk_without_the_doorway(tmp_path):
    (tmp_path / "index.html").write_text("touch", encoding="utf-8")
    binding = _RecordingBinding()

    async def factory(_connection_id, _sender):
        return binding

    server = DisplayServer(DisplayStatePublisher(), tmp_path, on_touch_connect=factory)
    info = await server.start()
    try:
        async with connect(info.websocket_url) as socket:
            await socket.recv()
            await socket.send(b"\x00" * (MAX_PCM_CHUNK_BYTES + 2))
            for _ in range(200):
                if binding.malformed:
                    break
                await asyncio.sleep(0.01)
        assert binding.audio == []
        assert binding.malformed == ["malformed"]
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_a_touch_ingress_flood_reports_overflow_instead_of_a_holed_capture():
    binding = _RecordingBinding()
    queue = asyncio.Queue(maxsize=2)
    server = DisplayServer.__new__(DisplayServer)
    for _ in range(4):
        DisplayServer._enqueue_touch_message(server, queue, b"\x01\x02")

    worker = asyncio.create_task(
        DisplayServer._run_touch_ingress(server, binding, queue)
    )
    for _ in range(200):
        if binding.malformed:
            break
        await asyncio.sleep(0.005)
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker

    assert binding.malformed == ["overflow"]


@pytest.mark.asyncio
async def test_the_browser_voice_path_is_untouched_by_touch_mode(tmp_path):
    """Browser regression: a non-touch server still parses voice turns."""
    assert server_module.DisplayServer._parse_websocket_voice_turn(
        json.dumps({"type": "voice_turn", "schema": 1, "text": "hello"})
    ).text == "hello"
    server = DisplayServer(DisplayStatePublisher(), tmp_path)
    assert server.touch_contexts_enabled is False
    assert server.browser_contexts_enabled is False


@pytest.mark.asyncio
async def test_stale_abort_cannot_cancel_new_capture():
    doorway = _doorway()
    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="new"))
    await doorway.handle_touch_frame(TouchFrame("mic_abort", capture_id="old"))
    assert doorway._capture.capture_id == "new"
    await doorway.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
async def test_watchdog_discards_and_emits_one_correlated_terminal(monkeypatch, started):
    monkeypatch.setattr(touch_module, "TOUCH_START_TIMEOUT", .01)
    monkeypatch.setattr(touch_module, "TOUCH_CAPTURE_END_TIMEOUT", .01)
    sender, session = FakeSender(), FakeSession()
    doorway = _doorway(sender=sender, session=session)
    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="timeout"))
    if started:
        await doorway.handle_touch_frame(TouchFrame("mic_capture_started", capture_id="timeout"))
        await doorway.handle_touch_audio(b"\0\0")
    await asyncio.sleep(.03)
    terminals = [c for c in sender.controls if c["type"] == "mic_terminal"]
    assert len(terminals) == 1
    assert terminals[0]["capture_id"] == "timeout"
    assert terminals[0]["outcome"] == "no_turn"
    assert not session.prompts
    await doorway.handle_touch_frame(TouchFrame("mic_capture_started", capture_id="timeout"))
    assert len(sender.controls) == 2
    await doorway.close()


@pytest.mark.asyncio
async def test_mic_end_cancels_watchdog_before_slow_transcription(monkeypatch):
    import time
    monkeypatch.setattr(touch_module, "TOUCH_CAPTURE_END_TIMEOUT", .01)
    def transcribe(_pcm):
        time.sleep(.03)
        return {"success": True, "transcript": "Turn on the lights"}
    sender = FakeSender()
    doorway = _doorway(sender=sender, transcriber=transcribe)
    await _capture(doorway)
    assert [c["outcome"] for c in sender.controls if c["type"] == "mic_terminal"] == ["complete"]
    assert doorway._deadline_task is None
    await doorway.close()


@pytest.mark.asyncio
async def test_admission_deadline_never_sends_a_late_grant(monkeypatch):
    monkeypatch.setattr(touch_module, "TOUCH_ADMISSION_TIMEOUT", .01)
    class SlowClaim:
        async def claim(self, **kwargs):
            await asyncio.sleep(.1)
            return "late"
    sender = FakeSender()
    doorway = _doorway(sender=sender, claim_client=SlowClaim())
    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="slow"))
    await asyncio.sleep(.02)
    assert sender.control_types == ["mic_reject"]
    assert doorway._capture is None
    await doorway.close()


@pytest.mark.asyncio
async def test_audio_abort_keeps_following_text_until_real_terminal():
    sender, publisher = FakeSender(), RecordingPublisher()
    session = FakeSession(events=[
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_abort"}, {"type": "text_delta", "text": "Still the answer"},
        {"type": "turn_end"},
    ])
    doorway = _doorway(sender=sender, publisher=publisher, session=session)
    await _capture(doorway)
    assert doorway._response_text == "Still the answer"
    assert publisher.states.count("complete") == 1
    assert sender.controls[-1]["outcome"] == "complete"
    await doorway.close()


@pytest.mark.asyncio
async def test_failed_terminal_delivery_invalidates_connection():
    class BrokenTerminal(FakeSender):
        async def send_control(self, payload):
            await super().send_control(payload)
            return payload["type"] != "mic_terminal"
    session = FakeSession()
    doorway = _doorway(sender=BrokenTerminal(), session=session)
    await _capture(doorway)
    assert doorway._closed and session.closed
    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="again"))
    assert len(session.prompts) == 1


@pytest.mark.asyncio
async def test_close_cancels_and_awaits_pending_admission():
    started, cancelled = asyncio.Event(), asyncio.Event()
    class PendingClaim:
        async def claim(self, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
    sender = FakeSender()
    doorway = _doorway(sender=sender, claim_client=PendingClaim())
    task = asyncio.create_task(doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="pending")))
    await started.wait()
    await doorway.close()
    await task
    assert cancelled.is_set()
    assert doorway._admission_task is None
    assert sender.controls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["transcribing", "turn"])
async def test_late_mic_controls_and_pcm_retain_owned_turn(stage):
    import threading
    release_stt = threading.Event()
    started_stt = threading.Event()
    release_turn = asyncio.Event()
    sender = FakeSender()
    session = FakeSession(events=[{"type": "text_delta", "text": "Answer"}, {"type": "turn_end"}], gate=release_turn)
    def transcribe(_pcm):
        started_stt.set()
        assert release_stt.wait(3)
        return {"success": True, "transcript": "Turn on the lights"}
    doorway = _doorway(sender=sender, session=session, transcriber=transcribe)
    try:
        await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="owned"))
        await doorway.handle_touch_frame(TouchFrame("mic_capture_started", capture_id="owned"))
        await doorway.handle_touch_audio(b"\0\0")
        await doorway.handle_touch_frame(TouchFrame("mic_end", capture_id="owned"))
        await asyncio.to_thread(started_stt.wait, 1)
        task = doorway._turn_task
        if stage == "turn":
            release_stt.set()
            for _ in range(100):
                if session.prompts: break
                await asyncio.sleep(.001)
            assert session.prompts
        for identity in ("owned", "old"):
            for kind in ("mic_end", "mic_capture_started", "mic_abort"):
                await doorway.handle_touch_frame(TouchFrame(kind, capture_id=identity))
        await doorway.handle_touch_audio(b"\0\0")
        await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="second"))
        assert doorway._turn_task is task and not task.done()
        assert doorway._active_capture_id == "owned"
        assert not any(c["type"] == "mic_terminal" for c in sender.controls)
        assert sender.controls[-1]["type"] == "mic_reject"
        release_stt.set(); release_turn.set()
        await task
        assert len(session.prompts) == 1
        assert [c["outcome"] for c in sender.controls if c["type"] == "mic_terminal"] == ["complete"]
    finally:
        release_stt.set(); release_turn.set()
        await doorway.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("visible_before_wait", [False, True])
async def test_admission_waits_for_terminal_finalization(visible_before_wait):
    terminal_entered, release_terminal = asyncio.Event(), asyncio.Event()
    class PausedTerminal(FakeSender):
        async def send_control(self, payload):
            if payload["type"] == "mic_terminal":
                if visible_before_wait:
                    await super().send_control(payload)
                terminal_entered.set()
                await release_terminal.wait()
                if visible_before_wait:
                    return True
            return await super().send_control(payload)
    sender = PausedTerminal()
    doorway = _doorway(sender=sender)
    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="first"))
    await doorway.handle_touch_frame(TouchFrame("mic_capture_started", capture_id="first"))
    await doorway.handle_touch_audio(b"\0\0")
    await doorway.handle_touch_frame(TouchFrame("mic_end", capture_id="first"))
    task = doorway._turn_task
    await asyncio.wait_for(terminal_entered.wait(), 2)
    audio_report = asyncio.create_task(doorway.handle_touch_frame(
        TouchFrame("audio_playback_failed", turn_id=doorway._turn_id)))
    admission = asyncio.create_task(doorway.handle_touch_frame(
        TouchFrame("mic_start", capture_id="second")))
    await asyncio.sleep(0)
    assert not admission.done() and not audio_report.done()
    assert doorway._turn_task is task and not task.done()
    assert "mic_reject" not in sender.control_types
    release_terminal.set()
    await asyncio.wait_for(asyncio.gather(task, audio_report, admission), 2)
    assert doorway._capture.capture_id == "second"
    assert sender.controls[-1]["type"] == "mic_ready"
    assert sender.control_types.count("mic_terminal") == 1
    assert "mic_reject" not in sender.control_types
    await doorway.close()


@pytest.mark.asyncio
async def test_invalidation_clears_transient_fields_before_cleanup_awaits():
    entered, release = asyncio.Event(), asyncio.Event()
    doorway = _doorway()
    doorway._capture = touch_module._Capture("capture", chunks=[b"\0\0"])
    capture = doorway._capture
    doorway._active_capture_id = "capture"
    doorway._turn_id = "turn"
    doorway._transcript_text = "private transcript"
    doorway._response_text = "private response"
    doorway._interrupt_pending = doorway._audio_open = doorway._playback_started = True
    async def paused_cleanup():
        entered.set()
        await release.wait()
    doorway._cancel_deadline = paused_cleanup
    task = asyncio.create_task(doorway._invalidate_connection())
    await entered.wait()
    assert doorway._closed and doorway._capture is None and not capture.chunks
    assert doorway._active_capture_id is None and doorway._turn_id is None
    assert doorway._transcript_text == doorway._response_text == ""
    assert not doorway._interrupt_pending and not doorway._audio_open and not doorway._playback_started
    release.set()
    await task


@pytest.mark.asyncio
async def test_playback_started_then_audio_abort_keeps_following_text_out_of_speaking():
    gate = asyncio.Event()
    sender, publisher = FakeSender(), RecordingPublisher()
    session = FakeSession(events=[
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_abort"}, {"type": "text_delta", "text": "Still the answer"},
        {"type": "turn_end"},
    ], gate=gate)
    doorway = _doorway(sender=sender, publisher=publisher, session=session)
    capture = asyncio.create_task(_capture(doorway))
    for _ in range(100):
        if doorway._audio_open: break
        await asyncio.sleep(.001)
    assert doorway._audio_open
    await doorway.handle_touch_frame(TouchFrame("audio_playback_started", turn_id="turn-1"))
    assert publisher.states[-1] == "speaking"
    after_started = len(publisher.states)
    gate.set()
    await capture
    assert "speaking" not in publisher.states[after_started:]
    assert doorway._response_text == "Still the answer"
    assert doorway._last_published_state == "complete"
    assert not doorway._playback_started
    await doorway.close()


@pytest.mark.asyncio
async def test_close_cancels_a_locked_terminal_finalizer_without_deadlock():
    entered = asyncio.Event()
    class PausedTerminal(FakeSender):
        async def send_control(self, payload):
            if payload["type"] == "mic_terminal":
                entered.set()
                await asyncio.Event().wait()
            return await super().send_control(payload)
    doorway = _doorway(sender=PausedTerminal())
    await doorway.handle_touch_frame(TouchFrame("mic_start", capture_id="first"))
    await doorway.handle_touch_frame(TouchFrame("mic_capture_started", capture_id="first"))
    await doorway.handle_touch_audio(b"\0\0")
    await doorway.handle_touch_frame(TouchFrame("mic_end", capture_id="first"))
    task = doorway._turn_task
    await asyncio.wait_for(entered.wait(), 2)
    await asyncio.wait_for(doorway.close(), 2)
    assert task.done() and doorway._turn_task is None
    assert doorway._closed and not doorway._lock.locked()
