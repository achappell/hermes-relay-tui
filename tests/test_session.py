import asyncio
import json
import types

import pytest

import config
from session import HermesSession, SessionNotReadyError


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


async def test_session_is_not_connected_until_hello_ack_is_verified(monkeypatch):
    hello_started = asyncio.Event()
    release_hello = asyncio.Event()
    websocket = FakeWebSocket([])

    async def recv_hello():
        hello_started.set()
        await release_hello.wait()
        return json.dumps({"type": "hello_ack", "chat_id": "chat"})

    websocket.recv = recv_hello
    monkeypatch.setattr(
        config,
        "connect_factory",
        lambda: lambda *args, **kwargs: FakeContextManager(websocket),
    )
    session = HermesSession(make_args())
    connecting = asyncio.create_task(session.connect())

    await hello_started.wait()
    assert session.is_connected() is False
    with pytest.raises(SessionNotReadyError):
        session.send_turn("premature")
    assert session.turn_index == 0
    assert session.active_turn_id is None
    assert all(json.loads(frame)["type"] != "turn" for frame in websocket.sent)

    release_hello.set()
    await connecting

    assert session.is_connected() is True


async def test_session_becomes_unready_at_close_entry_before_cleanup_finishes(monkeypatch):
    websocket = FakeWebSocket(
        [json.dumps({"type": "hello_ack", "chat_id": "chat"})]
    )
    exit_started = asyncio.Event()
    release_exit = asyncio.Event()

    class BlockingContextManager(FakeContextManager):
        async def __aexit__(self, exc_type, exc, tb):
            exit_started.set()
            await release_exit.wait()

    monkeypatch.setattr(
        config,
        "connect_factory",
        lambda: lambda *args, **kwargs: BlockingContextManager(websocket),
    )
    session = HermesSession(make_args())
    await session.connect()

    closing = asyncio.create_task(session.close())
    await exit_started.wait()

    assert session.is_connected() is False
    with pytest.raises(SessionNotReadyError):
        session.send_turn("must not send during close")
    assert session.turn_index == 0
    assert all(json.loads(frame)["type"] != "turn" for frame in websocket.sent)

    release_exit.set()
    await closing


def test_session_rejects_turn_before_a_verified_connection():
    session = HermesSession(make_args())

    with pytest.raises(RuntimeError, match="Not connected to relay"):
        session.send_turn("hello")

    assert session.turn_index == 0
    assert session.active_turn_id is None


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


async def test_session_uses_the_selected_profile_token_source_without_generic_fallback(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("VOICE_SESSION_TOKEN", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text('VOICE_SESSION_TOKEN_AMANDA="profile-token"\n', encoding="utf-8")
    websocket = FakeWebSocket(
        [json.dumps({"type": "hello_ack", "chat_id": "chat"})]
    )
    captured = {}

    def connect(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeContextManager(websocket)

    monkeypatch.setattr(config, "connect_factory", lambda: connect)
    session = HermesSession(
        make_args(
            token="",
            profile_env=env_path,
            profile_token_env="VOICE_SESSION_TOKEN_AMANDA",
        )
    )

    await session.connect()

    assert captured["kwargs"]["extra_headers"] == {
        "Authorization": "Bearer profile-token"
    }


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
                    "chat_id": "chat-42",
                    "session_id": "custom-sid",
                    "model": "qwen2.5:7b",
                    "title": "My Session",
                    "server_version": "0.8.0",
                    "context_limit": 128000,
                    "history": history,
                    "capabilities": ["interrupt", "structured_prompts"],
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
    assert session.confirmed_chat_id == "chat-42"
    assert session.confirmed_model == "qwen2.5:7b"
    assert session.confirmed_title == "My Session"
    assert session.confirmed_server_version == "0.8.0"
    assert session.confirmed_context_limit == 128000
    assert session.capabilities == frozenset({"interrupt", "structured_prompts"})
    assert session.initial_history == history

    await session.close()
    assert session.confirmed_chat_id is None
    assert session.confirmed_server_version is None
    assert session.confirmed_context_limit is None
    assert session.capabilities == frozenset()


async def test_session_hello_uses_the_doorway_session_identity(monkeypatch):
    websocket = FakeWebSocket(
        [json.dumps({"type": "hello_ack", "session_id": "doorway-unique"})]
    )
    monkeypatch.setattr(
        config,
        "connect_factory",
        lambda: lambda *args, **kwargs: FakeContextManager(websocket),
    )
    session = HermesSession(make_args(session_id="doorway-unique"))

    await session.connect()

    hello = json.loads(websocket.sent[0])
    assert hello["session_id"] == "doorway-unique"


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
                    "chat_id": "chat-fresh",
                    "model": "qwen2.5:7b",
                    "server_version": "0.8.0",
                    "context_limit": 64000,
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
    assert session.confirmed_chat_id == "chat-fresh"
    assert session.confirmed_model == "qwen2.5:7b"
    assert session.confirmed_title == "Fresh Chat"
    assert session.confirmed_server_version == "0.8.0"
    assert session.confirmed_context_limit == 64000


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
                    "chat_id": "chat-target",
                    "model": "qwen2.5:7b",
                    "server_version": "0.8.0",
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
    assert session.confirmed_chat_id == "chat-target"
    assert session.confirmed_model == "qwen2.5:7b"
    assert session.confirmed_title == "Target Chat"
    assert session.confirmed_server_version == "0.8.0"
    assert result["history"] == history
