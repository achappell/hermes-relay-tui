import json
import types

import config
from session import HermesSession


class FakeWebSocket:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        return self.frames.pop(0)


class FakeContextManager:
    def __init__(self, websocket):
        self.websocket = websocket

    async def __aenter__(self):
        return self.websocket

    async def __aexit__(self, exc_type, exc, tb):
        return None


def make_args(**overrides):
    values = {
        "token": "token",
        "profile_env": None,
        "url": "ws://test",
        "client_id": "client",
        "device_id": "device",
        "session_id": "session",
        "display_name": "Test",
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


async def test_session_sends_interrupt_for_the_active_turn_when_capability_is_advertised(
    monkeypatch,
):
    websocket = FakeWebSocket(
        [
            json.dumps(
                {
                    "type": "hello_ack",
                    "chat_id": "chat",
                    "capabilities": ["text_stream", "interrupt"],
                }
            )
        ]
    )
    monkeypatch.setattr(config, "connect_factory", lambda: lambda *args, **kwargs: FakeContextManager(websocket))
    session = HermesSession(make_args())

    await session.connect()
    stream = session.send_turn("hello")

    assert session.active_turn_id
    websocket.frames.append(
        json.dumps(
            {"type": "text_delta", "turn_id": session.active_turn_id, "text": "partial"}
        )
    )
    await stream.__anext__()
    sent_turn = json.loads(websocket.sent[-1])
    assert sent_turn["type"] == "turn"
    assert sent_turn["turn_id"] == session.active_turn_id
    assert await session.interrupt_active_turn() is True
    sent = json.loads(websocket.sent[-1])
    assert sent == {
        "type": "interrupt",
        "protocol_version": 1,
        "turn_id": session.active_turn_id,
        "session_id": "session",
    }

    sent_count = len(websocket.sent)
    assert await session.interrupt_active_turn() is True
    assert len(websocket.sent) == sent_count

    await stream.aclose()


async def test_session_does_not_claim_interrupt_support_when_capability_is_absent(
    monkeypatch,
):
    websocket = FakeWebSocket(
        [json.dumps({"type": "hello_ack", "chat_id": "chat", "capabilities": []})]
    )
    monkeypatch.setattr(config, "connect_factory", lambda: lambda *args, **kwargs: FakeContextManager(websocket))
    session = HermesSession(make_args())

    await session.connect()
    session.send_turn("hello")

    assert session.supports_interrupt is False
    assert await session.interrupt_active_turn() is False
    assert len(websocket.sent) == 1


async def test_session_exposes_structured_prompt_capability_and_sends_response(
    monkeypatch,
):
    websocket = FakeWebSocket(
        [
            json.dumps(
                {
                    "type": "hello_ack",
                    "chat_id": "chat",
                    "capabilities": ["text_stream", "structured_prompts"],
                }
            )
        ]
    )
    monkeypatch.setattr(
        config,
        "connect_factory",
        lambda: lambda *args, **kwargs: FakeContextManager(websocket),
    )
    session = HermesSession(make_args())

    await session.connect()

    assert session.supports_structured_prompts is True
    assert await session.send_prompt_response(
        prompt_id="prompt-1",
        prompt_kind="approval",
        option_id="once",
        reason="one-time access",
    ) is True
    assert json.loads(websocket.sent[-1]) == {
        "type": "prompt_response",
        "protocol_version": 1,
        "prompt_id": "prompt-1",
        "prompt_kind": "approval",
        "session_id": "session",
        "option_id": "once",
        "reason": "one-time access",
    }


async def test_session_does_not_send_prompt_response_without_capability(monkeypatch):
    websocket = FakeWebSocket(
        [json.dumps({"type": "hello_ack", "chat_id": "chat", "capabilities": []})]
    )
    monkeypatch.setattr(
        config,
        "connect_factory",
        lambda: lambda *args, **kwargs: FakeContextManager(websocket),
    )
    session = HermesSession(make_args())

    await session.connect()

    assert session.supports_structured_prompts is False
    assert await session.send_prompt_response(
        prompt_id="prompt-1",
        prompt_kind="secret",
        value="should-not-send",
    ) is False
    assert len(websocket.sent) == 1


async def test_session_records_confirmed_model_and_hydrates_history(monkeypatch):
    history = [
        {"role": "user", "content": "prior question"},
        {"role": "assistant", "content": "prior answer"},
    ]
    websocket = FakeWebSocket(
        [
            json.dumps(
                {
                    "type": "hello_ack",
                    "chat_id": "chat",
                    "session_id": "custom-sid",
                    "model": "qwen2.5:7b",
                    "title": "My Session",
                    "history": history,
                    "capabilities": [],
                }
            )
        ]
    )
    monkeypatch.setattr(
        config,
        "connect_factory",
        lambda: lambda *args, **kwargs: FakeContextManager(websocket),
    )
    session = HermesSession(make_args(session_id="custom-sid"))

    hello = await session.connect()

    assert session.session_id == "custom-sid"
    assert session.confirmed_model == "qwen2.5:7b"
    assert session.confirmed_title == "My Session"
    assert session.initial_history == history


async def test_session_list_sessions_delegates_to_client(monkeypatch):
    websocket = FakeWebSocket(
        [
            json.dumps({"type": "hello_ack", "chat_id": "chat"}),
            json.dumps(
                {
                    "type": "session_list_result",
                    "sessions": [{"session_id": "s1", "title": "S1"}],
                }
            ),
        ]
    )
    monkeypatch.setattr(
        config,
        "connect_factory",
        lambda: lambda *args, **kwargs: FakeContextManager(websocket),
    )
    session = HermesSession(make_args())
    await session.connect()

    result = await session.list_sessions()

    assert len(result) == 1
    assert result[0]["session_id"] == "s1"


async def test_session_new_session_updates_session_id_and_resets_turn_index(monkeypatch):
    websocket = FakeWebSocket(
        [
            json.dumps({"type": "hello_ack", "chat_id": "chat"}),
            json.dumps(
                {
                    "type": "session_switched",
                    "session_id": "s-fresh",
                    "title": "Fresh Chat",
                    "model": "qwen2.5:7b",
                }
            ),
        ]
    )
    monkeypatch.setattr(
        config,
        "connect_factory",
        lambda: lambda *args, **kwargs: FakeContextManager(websocket),
    )
    session = HermesSession(make_args())
    await session.connect()
    session.turn_index = 5

    result = await session.new_session(session_id="s-fresh")

    assert session.session_id == "s-fresh"
    assert session.turn_index == 0
    assert session.confirmed_model == "qwen2.5:7b"
    assert session.confirmed_title == "Fresh Chat"


async def test_session_switch_session_updates_session_id_and_returns_history(monkeypatch):
    history = [{"role": "user", "content": "resumed message"}]
    websocket = FakeWebSocket(
        [
            json.dumps({"type": "hello_ack", "chat_id": "chat"}),
            json.dumps(
                {
                    "type": "session_switched",
                    "session_id": "s-target",
                    "title": "Target Chat",
                    "model": "qwen2.5:7b",
                    "history": history,
                }
            ),
        ]
    )
    monkeypatch.setattr(
        config,
        "connect_factory",
        lambda: lambda *args, **kwargs: FakeContextManager(websocket),
    )
    session = HermesSession(make_args())
    await session.connect()
    session.turn_index = 3

    result = await session.switch_session("s-target")

    assert session.session_id == "s-target"
    assert session.turn_index == 0
    assert result["history"] == history

