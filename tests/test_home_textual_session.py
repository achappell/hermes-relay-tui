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
        events = []
        async for event in session.send_turn("TEST"):
            events.append(event)
            if event["type"] == "turn_end":
                # The app may block draining PCM before requesting another event.
                assert session._home_session.active_turn_id is None
                assert session.active_turn_id is None
        assert events[-1] == {"type": "turn_end"}
        assert events[-2] == ({"type": "audio_end", "final": True} if ending == "end" else
                              {"type": "audio_unavailable", "reason": "Home bridge response audio unavailable"})
        assert session.active_turn_id is None
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("audio_started", [False, True])
async def test_textual_completed_text_survives_audio_disconnect_without_replaying_tail(monkeypatch, audio_started):
    import json
    from puck_bridge.home_session import HomePuckSession
    from session import SessionNotReadyError
    from tests.test_puck_home_session import _FakeConnect, _FakeSocket, _ready_socket, _audio, _event, _reply, READY as BRIDGE_READY

    class BoundClient(FakeHomeClient):
        async def claim(self, *args, **kwargs):
            result = await super().claim(*args, **kwargs)
            result["conversation_handle"] = "opaque-home-handle"
            return result

    class TailSocket(_FakeSocket):
        async def send(self, raw):
            request = json.loads(raw)
            if request["method"] != "conversation.reconnect":
                return await super().send(raw)
            self.sent.append(request)
            self.incoming.put_nowait(_reply(request["id"], BRIDGE_READY))
            self.incoming.put_nowait(b"\x02\x00")
            self.incoming.put_nowait(_audio("end", "home-turn-1"))

    monkeypatch.setattr("puck_bridge.home_textual_session.HomeClient", BoundClient)
    frames = []
    if audio_started:
        frames.append(_audio("start", "home-turn-1", sample_rate=24000, channels=1,
                             sample_width=2, byte_order="little"))
    frames.extend([
        _event("message.delta", "home-turn-1", {"text": "Confirmed answer."}),
        _event("message.complete", "home-turn-1", {}),
    ])
    first, recovered = _ready_socket(*frames), TailSocket()
    fresh = _ready_socket(_event("message.complete", "home-turn-1", {}))
    connector = _FakeConnect([first, recovered, fresh])

    def factory(*args, **kwargs):
        assert kwargs["resume_uncertain_turn"] is False
        return HomePuckSession(*args, connect_factory=connector, **kwargs)

    session = HomeTextualSession(SimpleNamespace(url="https://home.example", session_id="local"),
                                 home_session_factory=factory)
    await session.connect()
    session._home_session._capabilities |= {"audio"}
    try:
        events = []
        async for event in session.send_turn("First question"):
            events.append(event)
            if event["type"] == "message_complete":
                first.incoming.put_nowait(ConnectionError("audio transport dropped"))
        assert {"type": "text_delta", "text": "Confirmed answer."} in events
        assert events[-1] == {"type": "turn_end"}
        assert events[-2]["type"] == "audio_unavailable"
        assert "text completed" in events[-2]["reason"]
        assert not session.is_connected()
        assert connector.contexts[0].closed
        assert len(connector.calls) == 1  # No automatic recovery or replay.
        assert session.conversation_replacement_required

        await session.connect()
        with pytest.raises(SessionNotReadyError, match="Choose /new"):
            session.send_turn("Must not consume the old audio tail")
        assert all(request["method"] != "prompt.submit" for request in recovered.sent)

        await session.new_session()
        assert connector.contexts[1].closed
        assert not session.conversation_replacement_required
        next_events = [event async for event in session.send_turn("Deliberate new question")]
        assert [event["type"] for event in next_events] == ["message_complete", "turn_end"]
        assert sum(request["method"] == "prompt.submit" for socket in (first, recovered, fresh) for request in socket.sent) == 2
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_leaving_uncertain_turn_requires_successful_replacement(monkeypatch):
    from session import SessionNotReadyError

    class ClosableHome(FakeHomeSession):
        async def close_claim(self):
            await self.close()
            return True

    monkeypatch.setattr("puck_bridge.home_textual_session.HomeClient", FakeHomeClient)
    session = HomeTextualSession(SimpleNamespace(url="https://home.example", session_id="local"),
                                 home_session_factory=ClosableHome)
    await session.connect()
    session.leave_uncertain_turn()
    try:
        with pytest.raises(SessionNotReadyError, match="Choose /new"):
            session.send_turn("Blocked", stt_source="voice")
        original = session.home_client.configuration

        async def unavailable(_record):
            raise ConnectionError("Home unavailable")

        session.home_client.configuration = unavailable
        with pytest.raises(ConnectionError):
            await session.new_session()
        assert session.conversation_replacement_required
        session.home_client.configuration = original
        await session.new_session()
        assert not session.conversation_replacement_required
        events = [event async for event in session.send_turn("New question", stt_source="voice")]
        assert events[-1] == {"type": "turn_end"}
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_explicit_replacement_handshake_retry_unblocks_without_another_claim(monkeypatch):
    class RetryHome(FakeHomeSession):
        async def close_claim(self):
            await self.close()
            return True

    created = []

    def factory(*args, **kwargs):
        home = RetryHome(*args, **kwargs)
        connect = home.connect

        async def fail_first_replacement_connect():
            home.connect = connect
            raise ConnectionError("Replacement handshake failed")

        if created:
            home.connect = fail_first_replacement_connect
        created.append(home)
        return home

    monkeypatch.setattr("puck_bridge.home_textual_session.HomeClient", FakeHomeClient)
    session = HomeTextualSession(SimpleNamespace(url="https://home.example", session_id="local"),
                                 home_session_factory=factory)
    await session.connect()
    session.leave_uncertain_turn()
    try:
        with pytest.raises(ConnectionError, match="Replacement handshake failed"):
            await session.new_session()
        assert session.conversation_replacement_required
        assert session.home_client.claim_count == 2
        replacement = session._home_session
        await session.connect()
        assert session._home_session is replacement
        assert session.home_client.claim_count == 2
        assert not session.conversation_replacement_required
        events = [event async for event in session.send_turn("Deliberate question", stt_source="voice")]
        assert events[-1] == {"type": "turn_end"}
        # The app's presentation flag can remain set until it paints. It must
        # not authorize reusing this claim after a later explicit abandonment.
        assert session.pending_replacement
        session.leave_uncertain_turn()
        await session.connect()
        assert session.conversation_replacement_required
    finally:
        await session.close()
