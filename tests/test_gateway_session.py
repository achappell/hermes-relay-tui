import asyncio
from types import SimpleNamespace

import pytest

import gateway_session as gateway_session_module
from gateway_client import GatewayTransportError, GatewayUnsupportedError
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
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeGateway:
    instances = []

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
            return {"status": "interrupted"}
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


@pytest.fixture
def fake_gateway(monkeypatch):
    FakeGateway.instances.clear()
    monkeypatch.setattr(gateway_session_module, "GatewayClient", FakeGateway)
    return FakeGateway


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
