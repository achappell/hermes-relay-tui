from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from puck_bridge.home_textual_session import HomeTextualSession
from home_client import Grant, PairingRecord
from session import UnsupportedTransportError


READY = {
    "schema": 1,
    "status": "ready",
    "conversation_handle": "opaque-handle",
    "route": {"class": "home", "id": "approved"},
    "capabilities": {"commands": [], "heartbeat": True, "timing": "absent"},
}


class FakeHomeSession:
    def __init__(self, _url, credential, handle, **kwargs):
        self.credential = credential
        self.handle = handle
        self.options = kwargs
        self.session_id = kwargs["session_id"]
        self.connected = False
        self.turn_index = 0
        self.active_turn_id = None
        self.capabilities = frozenset({"heartbeat"})
        self.supports_structured_prompts = kwargs["supports_structured_prompts"]
        self.supports_interrupt = False
        self.closed = False

    async def connect(self):
        self.connected = True
        return READY

    def is_connected(self):
        return self.connected

    async def wait_for_disconnect(self):
        self.connected = False

    async def close(self):
        self.connected = False
        self.closed = True

    def send_turn(self, _text, *, stt_source="local"):
        assert stt_source == "voice"
        self.turn_index += 1
        self.active_turn_id = "home-turn-1"

        async def events():
            yield {"type": "text_delta", "text": "continued"}
            self.active_turn_id = None
            yield {"type": "turn_end"}

        return events()

    async def send_prompt_response(self, **_payload):
        return True

    async def interrupt_active_turn(self):
        return False


class FakePairingStore:
    def load(self, home):
        return PairingRecord(home, "device-1", "device-secret", 1, 9_999_999_999)


class FakeHomeClient:
    def __init__(self, _url):
        self.home = "https://home.example"
        self.store = FakePairingStore()
        self.claim_count = 0

    async def credential(self, *, renew=True):
        return self.store.load(self.home)

    async def configuration(self, _record):
        return 1, [Grant("grant-1", "Amanda", "active", True)]

    async def claim(self, _record, _revision, _grant, mode, _ref, *, claim_id):
        self.claim_count += 1
        return {"conversation_handle": "opaque-handle", "session": {"mode": mode}}


@pytest.mark.asyncio
async def test_textual_home_session_delegates_turns_and_keeps_pairing_private(monkeypatch):
    monkeypatch.setattr("puck_bridge.home_textual_session.HomeClient", FakeHomeClient)
    args = SimpleNamespace(
        url="wss://home.example/api/v1/bridge/ws",
        session_id="home-local-display",
    )
    session = HomeTextualSession(args, home_session_factory=FakeHomeSession)

    ready = await session.connect()
    try:
        assert ready["status"] == "ready"
        assert session.is_connected()
        assert session.session_id == "home-local-display"
        assert session.capabilities == frozenset({"heartbeat"})
        assert session.supports_structured_prompts is True
        assert session._home_session.credential == "device-secret"
        assert session._home_session.handle == "opaque-handle"
        assert session._home_session.options["session_label"] == "TUI"

        events = [event async for event in session.send_turn("hello", stt_source="voice")]

        assert events == [
            {"type": "text_delta", "text": "continued"},
            {"type": "turn_end"},
        ]
        assert session.turn_index == 1
        with pytest.raises(UnsupportedTransportError, match="Choose a conversation from /sessions"):
            await session.switch_session("another-session")
    finally:
        await session.close()

    assert session._home_session.closed is True


def test_textual_home_session_marks_recovery_as_reconnect(monkeypatch):
    monkeypatch.setattr("puck_bridge.home_textual_session.HomeClient", FakeHomeClient)
    args = SimpleNamespace(
        url="wss://home.example/api/v1/bridge/ws",
        session_id="home-default",
    )
    session = HomeTextualSession(args, home_session_factory=FakeHomeSession)

    async def recover():
        await session.connect()
        original = session._home_session
        await session.close()
        await session.connect()
        assert session._home_session is original
        assert session.home_client.claim_count == 1
        assert session._home_session.handle == "opaque-handle"
        await session.close()

    asyncio.run(recover())


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["message_complete", "error", "turn_interrupted"])
async def test_textual_normalizes_home_completion_boundary(monkeypatch, terminal):
    class NativeShapeHome(FakeHomeSession):
        def send_turn(self, _text, *, stt_source="local"):
            async def events():
                yield {"type": "text_delta", "text": "answer"}
                yield {"type": terminal}
                if terminal == "message_complete":
                    yield {"type": "audio_end"}
            return events()

    monkeypatch.setattr("puck_bridge.home_textual_session.HomeClient", FakeHomeClient)
    session = HomeTextualSession(SimpleNamespace(url="https://home.example", session_id="local"),
                                 home_session_factory=NativeShapeHome)
    await session.connect()
    try:
        events = [event async for event in session.send_turn("TEST")]
        if terminal == "message_complete":
            assert events[-2:] == [{"type": "audio_end", "final": True}, {"type": "turn_end"}]
        else:
            assert events[-1] == {"type": terminal}
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["end", "fallback", "unavailable"])
async def test_textual_real_bridge_finishes_text_then_audio(monkeypatch, ending):
    from puck_bridge.home_session import HomePuckSession
    from tests.test_puck_home_session import _FakeConnect, _ready_socket, _audio, _event

    class BoundClient(FakeHomeClient):
        async def claim(self, *args, **kwargs):
            result = await super().claim(*args, **kwargs)
            result["conversation_handle"] = "opaque-home-handle"
            return result

    monkeypatch.setattr("puck_bridge.home_textual_session.HomeClient", BoundClient)
    socket = _ready_socket(
        _audio("start", "home-turn-1", sample_rate=24000, channels=1,
               sample_width=2, byte_order="little"),
        _event("message.complete", "home-turn-1", {}),
        b"\x01\x00",
        _audio(ending, "home-turn-1"),
    )
    def factory(*args, **kwargs):
        return HomePuckSession(*args, connect_factory=_FakeConnect([socket]), **kwargs)

    session = HomeTextualSession(SimpleNamespace(url="https://home.example", session_id="local"),
                                 home_session_factory=factory)
    await session.connect()
    try:
        events = [event async for event in session.send_turn("TEST")]
        assert events[-1] == {"type": "turn_end"}
        assert events[-2] == ({"type": "audio_end", "final": True} if ending == "end" else
                              {"type": "audio_unavailable", "reason": "Home bridge response audio unavailable"})
        assert session.active_turn_id is None
    finally:
        await session.close()
