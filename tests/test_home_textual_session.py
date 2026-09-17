from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from puck_bridge.home_textual_session import HomeTextualSession
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


@pytest.mark.asyncio
async def test_textual_home_session_delegates_turns_and_keeps_pairing_private(tmp_path):
    profile_env = tmp_path / "private.env"
    profile_env.write_text(
        'HOME_DEVICE_CREDENTIAL="device-secret"\n'
        'HOME_CONVERSATION_HANDLE="opaque-handle"\n',
        encoding="utf-8",
    )
    args = SimpleNamespace(
        url="wss://home.example/api/v1/bridge/ws",
        profile_env=profile_env,
        session_id="stale-hermes-session",
    )
    session = HomeTextualSession(args, home_session_factory=FakeHomeSession)

    ready = await session.connect()
    try:
        assert ready["status"] == "ready"
        assert session.is_connected()
        assert session.session_id == "stale-hermes-session"
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
        with pytest.raises(UnsupportedTransportError, match="Home owns conversation selection"):
            await session.switch_session("another-session")
    finally:
        await session.close()

    assert session._home_session.closed is True


def test_textual_home_session_marks_recovery_as_reconnect(tmp_path):
    profile_env = tmp_path / "private.env"
    profile_env.write_text(
        'HOME_DEVICE_CREDENTIAL="device-secret"\n'
        'HOME_CONVERSATION_HANDLE="opaque-handle"\n',
        encoding="utf-8",
    )
    args = SimpleNamespace(
        url="wss://home.example/api/v1/bridge/ws",
        profile_env=profile_env,
        session_id="home-default",
        home_reconnect_required=True,
    )
    session = HomeTextualSession(args, home_session_factory=FakeHomeSession)

    session._get_home_session()

    assert session._home_session.options["reconnect_required"] is True
    asyncio.run(session.close())
