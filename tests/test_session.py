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
