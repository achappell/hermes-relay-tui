import asyncio
from types import SimpleNamespace

import pytest

import gateway_session as gateway_session_module
from gateway_client import GatewayProtocolError, GatewayTransportError, GatewayUnsupportedError
from gateway_session import GatewaySession


def make_args(**overrides):
    values = {
        "token": "gateway-token",
        "profile_env": None,
        "profile_token_env": None,
        "url": "ws://hermes.test/api/ws",
        "session_id": "doorway-random-id",
        "session_id_explicit": False,
        "hermes_profile": "amanda",
        "mic_input_device": None,
        "mic_max_seconds": 15.0,
        "mic_silence_duration": 1.5,
        "mic_silence_threshold": 200,
        "stt_model": None,
        "transport": "voice-session",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeGateway:
    instances = []
    interrupt_status = "interrupted"

    def __init__(self, url, token):
        self.url = url
        self.token = token
        self.requests = []
        self.events = asyncio.Queue()
        self.connected = False
        self.closed = False
        type(self).instances.append(self)

    @property
    def is_connected(self):
        return self.connected and not self.closed

    async def connect(self):
        self.connected = True
        return {"type": "gateway.ready", "payload": {"heartbeat": True}}

    async def request(self, method, params=None):
        self.requests.append((method, dict(params or {})))
        if method == "session.create":
            title = params.get("title")
            return {
                "session_id": "runtime-1",
                "stored_session_id": "stored-1",
                "session_key": "profile:stored-1",
                "title": title or "Fresh doorway",
                "messages": [
                    {"role": "user", "content": "old question"},
                    {"role": "assistant", "content": "old answer"},
                ],
                "info": {"model": "hermes-test", "version": "9"},
            }
        if method == "session.resume":
            return {
                "session_id": "runtime-resumed",
                "stored_session_id": params["session_id"],
                "messages": [{"role": "assistant", "content": "history"}],
                "info": {"model": "hermes-test"},
            }
        if method == "prompt.submit":
            return {"status": "streaming"}
        if method == "session.interrupt":
            return {"status": self.interrupt_status}
        if method == "session.list":
            return {
                "sessions": [
                    {"id": "stored-2", "title": "Second", "message_count": 3}
                ]
            }
        raise AssertionError(f"unexpected method: {method}")

    async def next_event(self):
        event = await self.events.get()
        if isinstance(event, BaseException):
            raise event
        return event

    async def wait_for_disconnect(self):
        await asyncio.Event().wait()

    async def close(self):
        self.closed = True
        self.connected = False

    def push(self, event):
        self.events.put_nowait(event)


class FakeAudio:
    instances = []

    def __init__(self, url, token, *, profile=None):
        self.url = url
        self.token = token
        self.profile = profile
        self.events = asyncio.Queue()
        self.text = []
        self.finished = False
        self.stopped = False
        self.closed = False
        type(self).instances.append(self)

    async def open(self):
        return None

    async def send_text(self, text):
        self.text.append(text)

    async def finish(self):
        self.finished = True

    async def next_event(self):
        return await self.events.get()

    async def stop(self):
        self.stopped = True
        self.closed = True

    async def close(self):
        self.closed = True

    def push(self, event):
        self.events.put_nowait(event)


@pytest.fixture
def fake_gateway(monkeypatch):
    FakeGateway.instances.clear()
    FakeGateway.interrupt_status = "interrupted"
    monkeypatch.setattr(gateway_session_module, "GatewayClient", FakeGateway)
    return FakeGateway


@pytest.fixture
def fake_audio(monkeypatch):
    FakeAudio.instances.clear()
    monkeypatch.setattr(gateway_session_module, "GatewayAudioStream", FakeAudio)
    return FakeAudio


async def connected_session(fake_gateway, **args_overrides):
    session = GatewaySession(make_args(**args_overrides))
    hello = await session.connect()
    return session, fake_gateway.instances[-1], hello


@pytest.mark.asyncio
async def test_connect_waits_for_gateway_session_and_keeps_runtime_history(fake_gateway):
    session, gateway, hello = await connected_session(fake_gateway)

    assert hello["type"] == "gateway_ready"
    assert session.is_connected() is True
    assert session.session_id == "runtime-1"
    assert session.initial_history[0]["content"] == "old question"
    assert gateway.requests == [
        ("session.create", {"source": "tui", "profile": "amanda"})
    ]
    await session.close()


@pytest.mark.asyncio
async def test_explicit_gateway_session_id_resumes_durable_key(fake_gateway):
    session, gateway, _hello = await connected_session(
        fake_gateway,
        session_id="stored-9",
        session_id_explicit=True,
    )

    assert session.session_id == "runtime-resumed"
    assert session.args.gateway_resume_session_id == "stored-9"
    assert gateway.requests[0] == (
        "session.resume",
        {"session_id": "stored-9", "source": "tui", "profile": "amanda"},
    )
    await session.close()


@pytest.mark.asyncio
async def test_switch_session_resumes_the_requested_durable_key_and_history(fake_gateway):
    session, gateway, _hello = await connected_session(fake_gateway)

    result = await session.switch_session("stored-22")

    assert gateway.requests[-1] == (
        "session.resume",
        {"session_id": "stored-22", "source": "tui", "profile": "amanda"},
    )
    assert session.session_id == "runtime-resumed"
    assert result["history"] == [{"role": "assistant", "content": "history"}]
    await session.close()


@pytest.mark.asyncio
async def test_conflicting_runtime_session_ids_are_rejected(fake_gateway):
    session, _gateway, _hello = await connected_session(fake_gateway)

    with pytest.raises(GatewayProtocolError, match="conflicting runtime IDs"):
        session._apply_session_result(
            {"session_id": "runtime-a", "runtime_session_id": "runtime-b"}
        )

    await session.close()


@pytest.mark.asyncio
async def test_stale_lower_sequence_events_are_ignored(fake_gateway):
    session, gateway, _hello = await connected_session(fake_gateway)
    stream = session.send_turn("ordered")
    gateway.push(
        {
            "type": "message.delta",
            "session_id": "runtime-1",
            "seq": 2,
            "payload": {"text": "current"},
        }
    )
    gateway.push(
        {
            "type": "message.delta",
            "session_id": "runtime-1",
            "seq": 1,
            "payload": {"text": "stale"},
        }
    )
    gateway.push(
        {
            "type": "message.complete",
            "session_id": "runtime-1",
            "seq": 3,
            "payload": {"text": "current", "status": "complete"},
        }
    )

    received = [event async for event in stream]

    assert "stale" not in "".join(event.get("text", "") for event in received)
    assert received[-1]["type"] == "turn_end"
    await session.close()


@pytest.mark.asyncio
async def test_new_session_uses_argument_as_title_and_hermes_owns_id(fake_gateway):
    session, gateway, _hello = await connected_session(fake_gateway)

    result = await session.new_session(session_id="Kitchen display")

    assert gateway.requests[-1] == (
        "session.create",
        {"source": "tui", "profile": "amanda", "title": "Kitchen display"},
    )
    assert result["session_id"] == "runtime-1"
    assert session.initial_history
    await session.close()


@pytest.mark.asyncio
async def test_text_turn_is_inline_ignores_other_sessions_and_ends_once(fake_gateway):
    session, gateway, _hello = await connected_session(fake_gateway)
    stream = session.send_turn("hello")
    received = []

    async def consume():
        async for event in stream:
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    gateway.push({"type": "message.delta", "session_id": "other", "payload": {"text": "wrong"}})
    gateway.push({"type": "message.start", "session_id": "runtime-1", "payload": {}})
    gateway.push({"type": "message.delta", "session_id": "runtime-1", "payload": {"text": "Hel"}})
    gateway.push({"type": "status.update", "session_id": "runtime-1", "payload": {"text": "thinking"}})
    gateway.push({"type": "message.delta", "session_id": "runtime-1", "payload": {"text": "lo"}})
    gateway.push({"type": "message.complete", "session_id": "runtime-1", "payload": {"text": "Hello", "status": "complete"}})
    await task

    assert [event["type"] for event in received].count("turn_end") == 1
    assert [event["type"] for event in received].count("text_delta") == 2
    assert "wrong" not in "".join(event.get("text", "") for event in received)
    assert received[-1]["type"] == "turn_end"
    assert received[-1]["text"] == "Hello"
    await session.close()


@pytest.mark.asyncio
async def test_sessionless_events_are_not_attributed_to_the_active_turn(fake_gateway):
    session, gateway, _hello = await connected_session(fake_gateway)
    stream = session.send_turn("hello")
    received = []

    async def consume():
        async for event in stream:
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    gateway.push({"type": "message.delta", "payload": {"text": "wrong"}})
    gateway.push(
        {
            "type": "message.complete",
            "session_id": "runtime-1",
            "payload": {"text": "right", "status": "complete"},
        }
    )
    await task

    assert "wrong" not in "".join(event.get("text", "") for event in received)
    assert received[-1]["text"] == "right"
    await session.close()


@pytest.mark.asyncio
async def test_gateway_error_event_ends_the_turn_without_waiting_for_timeout(fake_gateway):
    session, gateway, _hello = await connected_session(fake_gateway)
    stream = session.send_turn("fail promptly")
    gateway.push(
        {
            "type": "error",
            "session_id": "runtime-1",
            "payload": {"message": "provider refused the turn"},
        }
    )

    received = [event async for event in stream]

    assert received[-1] == {
        "type": "error",
        "error": "provider refused the turn",
        "turn_id": received[-1]["turn_id"],
        "session_id": "runtime-1",
    }
    await session.close()


@pytest.mark.asyncio
async def test_interrupt_before_prompt_submission_does_not_send_the_prompt(fake_gateway):
    session, gateway, _hello = await connected_session(fake_gateway)
    stream = session.send_turn("must not be submitted")

    assert await session.interrupt_active_turn() is True
    received = [event async for event in stream]

    assert received[0]["type"] == "turn_interrupted"
    assert not any(method == "prompt.submit" for method, _params in gateway.requests)
    await session.close()


@pytest.mark.asyncio
async def test_gateway_audio_interleaves_pcm_and_holds_turn_end_until_audio_end(
    fake_gateway, fake_audio
):
    session, gateway, _hello = await connected_session(
        fake_gateway,
        transport="gateway",
        gateway_audio_enabled=True,
    )
    stream = session.send_turn("say hello")
    received = []

    async def consume():
        async for event in stream:
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    audio = fake_audio.instances[-1]
    gateway.push(
        {
            "type": "message.delta",
            "session_id": "runtime-1",
            "payload": {"text": "Hello"},
        }
    )
    await asyncio.sleep(0)
    audio.push(
        {
            "type": "audio_start",
            "sample_rate": 24000,
            "channels": 1,
            "sample_width": 2,
        }
    )
    audio.push(
        {
            "type": "speech_timing",
            "segment_id": "speech-tts-0",
            "text": "Hello",
            "timing_source": "duration_fallback",
            "audio_offset": 0.0,
            "duration": 0.2,
            "fallback_reason": "disabled",
            "words": [],
        }
    )
    audio.push({"type": "audio_chunk", "data": b"\x00\x01"})
    gateway.push(
        {
            "type": "message.complete",
            "session_id": "runtime-1",
            "payload": {"text": "Hello", "status": "complete"},
        }
    )
    for _ in range(20):
        await asyncio.sleep(0)
        if audio.finished:
            break

    assert audio.text == ["Hello"]
    assert audio.finished is True
    assert not any(event["type"] == "turn_end" for event in received)

    audio.push({"type": "audio_end"})
    await task

    kinds = [event["type"] for event in received]
    assert kinds.index("audio_start") < kinds.index("audio_chunk")
    timing = next(event for event in received if event["type"] == "speech_timing")
    assert timing["segment_id"] == "speech-tts-0"
    assert timing["turn_id"]
    assert timing["session_id"] == "runtime-1"
    assert kinds.index("audio_end") < kinds.index("turn_end")
    assert received[-1]["type"] == "turn_end"
    await session.close()


@pytest.mark.asyncio
async def test_gateway_audio_activity_extends_the_drain_deadline(
    fake_gateway, fake_audio, monkeypatch
):
    monkeypatch.setattr(gateway_session_module, "AUDIO_DRAIN_TIMEOUT", 0.1)
    session, gateway, _hello = await connected_session(
        fake_gateway,
        transport="gateway",
        gateway_audio_enabled=True,
    )
    stream = session.send_turn("long audio")
    received = []

    async def consume():
        async for event in stream:
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    audio = fake_audio.instances[-1]
    audio.push(
        {
            "type": "audio_start",
            "sample_rate": 24000,
            "channels": 1,
            "sample_width": 2,
        }
    )
    gateway.push(
        {
            "type": "message.complete",
            "session_id": "runtime-1",
            "payload": {"text": "Long audio", "status": "complete"},
        }
    )
    for _ in range(20):
        await asyncio.sleep(0)
        if audio.finished:
            break
    assert audio.finished is True

    await asyncio.sleep(0.06)
    audio.push({"type": "audio_chunk", "data": b"\x00\x01"})
    await asyncio.sleep(0.06)
    audio.push({"type": "audio_end"})
    await task

    assert not any(event["type"] == "audio_unavailable" for event in received)
    assert received[-1]["type"] == "turn_end"
    await session.close()


@pytest.mark.asyncio
async def test_gateway_audio_drain_timeout_releases_a_stalled_turn(
    fake_gateway, fake_audio, monkeypatch
):
    monkeypatch.setattr(gateway_session_module, "AUDIO_DRAIN_TIMEOUT", 0.05)
    session, gateway, _hello = await connected_session(
        fake_gateway,
        transport="gateway",
        gateway_audio_enabled=True,
    )
    stream = session.send_turn("stalled audio")
    received = []

    async def consume():
        async for event in stream:
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    audio = fake_audio.instances[-1]
    audio.push(
        {
            "type": "audio_start",
            "sample_rate": 24000,
            "channels": 1,
            "sample_width": 2,
        }
    )
    gateway.push(
        {
            "type": "message.delta",
            "session_id": "runtime-1",
            "payload": {"text": "Readable while audio stalls"},
        }
    )
    gateway.push(
        {
            "type": "message.complete",
            "session_id": "runtime-1",
            "payload": {
                "text": "Readable while audio stalls",
                "status": "complete",
            },
        }
    )
    await task

    assert audio.finished is True
    assert any(
        event["type"] == "audio_unavailable"
        and "timed out" in event["reason"]
        for event in received
    )
    assert received[-1]["type"] == "turn_end"
    assert received[-1]["text"] == "Readable while audio stalls"
    await session.close()


@pytest.mark.asyncio
async def test_gateway_audio_open_failure_keeps_the_text_lane_alive(
    fake_gateway, fake_audio, monkeypatch
):
    async def fail_open(_audio):
        raise TimeoutError("sidecar did not accept the connection")

    monkeypatch.setattr(FakeAudio, "open", fail_open)
    session, gateway, _hello = await connected_session(
        fake_gateway,
        transport="gateway",
        gateway_audio_enabled=True,
    )
    stream = session.send_turn("open failure")
    received = []

    async def consume():
        async for event in stream:
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    gateway.push(
        {
            "type": "message.delta",
            "session_id": "runtime-1",
            "payload": {"text": "Text survives sidecar setup"},
        }
    )
    gateway.push(
        {
            "type": "message.complete",
            "session_id": "runtime-1",
            "payload": {
                "text": "Text survives sidecar setup",
                "status": "complete",
            },
        }
    )
    await task

    assert [method for method, _params in gateway.requests].count("prompt.submit") == 1
    assert any(event["type"] == "audio_unavailable" for event in received)
    assert received[-1]["type"] == "turn_end"
    assert received[-1]["text"] == "Text survives sidecar setup"
    await session.close()


@pytest.mark.asyncio
async def test_gateway_audio_failure_keeps_text_turn_certain(fake_gateway, fake_audio):
    session, gateway, _hello = await connected_session(
        fake_gateway,
        transport="gateway",
        gateway_audio_enabled=True,
    )
    stream = session.send_turn("text only")
    received = []

    async def consume():
        async for event in stream:
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    audio = fake_audio.instances[-1]
    audio.push({"type": "audio_unavailable", "reason": "server fallback"})
    gateway.push(
        {
            "type": "message.delta",
            "session_id": "runtime-1",
            "payload": {"text": "Readable"},
        }
    )
    gateway.push(
        {
            "type": "message.complete",
            "session_id": "runtime-1",
            "payload": {"text": "Readable", "status": "complete"},
        }
    )
    await task

    assert any(event["type"] == "audio_unavailable" for event in received)
    assert received[-1]["type"] == "turn_end"
    assert received[-1]["text"] == "Readable"
    await session.close()


@pytest.mark.asyncio
async def test_gateway_text_deltas_feed_audio_once_without_cumulative_duplicates(
    fake_gateway, fake_audio
):
    session, gateway, _hello = await connected_session(
        fake_gateway,
        transport="gateway",
        gateway_audio_enabled=True,
    )
    stream = session.send_turn("delta test")
    task = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)
    audio = fake_audio.instances[-1]
    gateway.push(
        {
            "type": "message.delta",
            "session_id": "runtime-1",
            "payload": {"rendered": "Hel"},
        }
    )
    first = await task
    assert first["text"] == "Hel"
    gateway.push(
        {
            "type": "message.delta",
            "session_id": "runtime-1",
            "payload": {"rendered": "Hello"},
        }
    )
    second = await stream.__anext__()
    assert second["text"] == "lo"
    assert audio.text == ["Hel", "lo"]
    await stream.aclose()
    await session.close()


@pytest.mark.asyncio
async def test_gateway_loss_closes_audio_without_replaying_the_prompt(fake_gateway, fake_audio):
    session, gateway, _hello = await connected_session(
        fake_gateway,
        transport="gateway",
        gateway_audio_enabled=True,
    )
    stream = session.send_turn("do not replay")
    received = []

    async def consume():
        try:
            async for event in stream:
                received.append(event)
        except GatewayTransportError:
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    audio = fake_audio.instances[-1]
    gateway.push(
        {
            "type": "message.delta",
            "session_id": "runtime-1",
            "payload": {"text": "Partial answer"},
        }
    )
    await asyncio.sleep(0)
    gateway.push(
        GatewayTransportError("gateway receive", ConnectionError("lost"))
    )
    await task

    assert audio.closed is True
    assert [method for method, _params in gateway.requests].count("prompt.submit") == 1
    assert "Partial answer" in "".join(
        event.get("text", "") for event in received
    )
    assert not any(event["type"] == "turn_end" for event in received)
    await session.close()


@pytest.mark.asyncio
async def test_interrupt_stops_audio_and_waits_for_gateway_cancellation(
    fake_gateway, fake_audio
):
    session, gateway, _hello = await connected_session(
        fake_gateway,
        transport="gateway",
        gateway_audio_enabled=True,
    )
    stream = session.send_turn("stop speaking")
    received = []

    async def consume():
        async for event in stream:
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    audio = fake_audio.instances[-1]
    assert await session.interrupt_active_turn() is True
    gateway.push(
        {
            "type": "message.complete",
            "session_id": "runtime-1",
            "payload": {"text": "partial", "status": "cancelled"},
        }
    )
    await task

    assert audio.stopped is True
    assert any(event["type"] == "turn_interrupted" for event in received)
    assert not any(event["type"] == "turn_end" for event in received)
    await session.close()


@pytest.mark.asyncio
async def test_text_segments_keep_their_boundary_in_one_assistant_message(fake_gateway):
    session, gateway, _hello = await connected_session(fake_gateway)
    stream = session.send_turn("two parts")
    received = []

    async def consume():
        async for event in stream:
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    gateway.push(
        {
            "type": "message.delta",
            "session_id": "runtime-1",
            "payload": {"draft_id": "draft-1", "rendered": "one"},
        }
    )
    gateway.push(
        {
            "type": "message.delta",
            "session_id": "runtime-1",
            "payload": {"draft_id": "draft-2", "rendered": "two"},
        }
    )
    gateway.push(
        {
            "type": "message.complete",
            "session_id": "runtime-1",
            "payload": {"text": "two", "status": "complete"},
        }
    )
    await task

    text = "".join(event.get("text", "") for event in received if event["type"] == "text_delta")
    assert text == "one\n\ntwo"
    assert received[-1]["type"] == "turn_end"
    assert received[-1]["text"] == "one\n\ntwo"
    await session.close()


@pytest.mark.asyncio
async def test_interim_message_is_preserved_before_the_final_answer(fake_gateway):
    session, gateway, _hello = await connected_session(fake_gateway)
    stream = session.send_turn("use a tool")
    received = []

    async def consume():
        async for event in stream:
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    gateway.push(
        {
            "type": "message.interim",
            "session_id": "runtime-1",
            "payload": {"text": "Checking first.", "already_streamed": False},
        }
    )
    gateway.push(
        {
            "type": "message.complete",
            "session_id": "runtime-1",
            "payload": {"text": "All done.", "status": "complete"},
        }
    )
    await task

    text = "".join(event.get("text", "") for event in received if event["type"] == "text_delta")
    assert text == "Checking first.\n\nAll done."
    assert received[-1]["text"] == "Checking first.\n\nAll done."
    await session.close()


@pytest.mark.asyncio
async def test_interrupt_requires_cancelled_completion(fake_gateway):
    session, gateway, _hello = await connected_session(fake_gateway)
    stream = session.send_turn("keep going")
    received = []

    async def consume():
        async for event in stream:
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    assert await session.interrupt_active_turn() is True
    gateway.push(
        {
            "type": "message.complete",
            "session_id": "runtime-1",
            "payload": {"text": "partial", "status": "cancelled"},
        }
    )
    await task

    assert any(event["type"] == "turn_interrupted" for event in received)
    assert not any(event["type"] == "turn_end" for event in received)
    assert [method for method, _params in gateway.requests].count("session.interrupt") == 1
    await session.close()


@pytest.mark.asyncio
async def test_interrupt_acknowledgement_does_not_claim_terminal_cancellation(fake_gateway):
    fake_gateway.interrupt_status = "accepted"
    session, gateway, _hello = await connected_session(fake_gateway)
    stream = session.send_turn("keep going")
    received = []

    async def consume():
        async for event in stream:
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    assert await session.interrupt_active_turn() is True
    await asyncio.sleep(0)
    assert not task.done()
    assert not any(event["type"] == "turn_interrupted" for event in received)

    gateway.push(
        {
            "type": "message.complete",
            "session_id": "runtime-1",
            "payload": {"text": "partial", "status": "interrupted"},
        }
    )
    await task
    assert any(event["type"] == "turn_interrupted" for event in received)
    await session.close()


@pytest.mark.asyncio
async def test_connection_loss_keeps_partial_output_and_does_not_resubmit(fake_gateway):
    session, gateway, _hello = await connected_session(fake_gateway)
    stream = session.send_turn("do not replay")
    received = []

    async def consume():
        try:
            async for event in stream:
                received.append(event)
        except GatewayTransportError:
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    gateway.push(
        {
            "type": "message.delta",
            "session_id": "runtime-1",
            "payload": {"text": "partial"},
        }
    )
    gateway.push(GatewayTransportError("gateway receive", ConnectionError("lost")))
    await task

    assert any(event.get("text") == "partial" for event in received)
    assert [method for method, _params in gateway.requests].count("prompt.submit") == 1
    await session.close()


@pytest.mark.asyncio
async def test_unsupported_prompt_is_cancelled_without_collecting_a_value(fake_gateway):
    session, gateway, _hello = await connected_session(fake_gateway)
    stream = session.send_turn("needs approval")
    gateway.push(
        {
            "type": "clarify.request",
            "session_id": "runtime-1",
            "payload": {
                "request_id": "request-1",
                "question": "private question",
                "choices": [{"label": "secret choice"}],
            },
        }
    )
    gateway.push(
        {
            "type": "message.complete",
            "session_id": "runtime-1",
            "payload": {"status": "cancelled"},
        }
    )

    with pytest.raises(GatewayUnsupportedError):
        async for _event in stream:
            pass

    assert ("session.interrupt", {"session_id": "runtime-1"}) in gateway.requests
    assert not any(method == "prompt.respond" for method, _params in gateway.requests)
    await session.close()


@pytest.mark.asyncio
async def test_list_sessions_normalizes_durable_ids(fake_gateway):
    session, _gateway, _hello = await connected_session(fake_gateway)
    sessions = await session.list_sessions(limit=100)
    assert sessions == [
        {
            "id": "stored-2",
            "title": "Second",
            "message_count": 3,
            "session_id": "stored-2",
        }
    ]
    await session.close()
