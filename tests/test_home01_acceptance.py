"""Home-specific acceptance gaps through the actual Textual app and adapter."""
import asyncio
from copy import copy

import pytest

from app import HermesStreamingApp, PROMPT_AMBIGUOUS
from home_client import Grant, HomeError
from session import UnsupportedTransportError
from puck_bridge.home_textual_session import HomeTextualSession
from tests.test_app import make_args, transcript_of
from tests.test_home_textual_session import FakeHomeClient, FakeHomeSession


@pytest.mark.parametrize("failure", ["claim", "bridge"])
async def test_home_replacement_failure_after_release_retains_transcript_without_replay(tmp_path, monkeypatch, failure):
    operations = []

    class Client(FakeHomeClient):
        async def configuration(self, record):
            return 1, [Grant("grant-1", "Amanda", "active", True),
                       Grant("grant-2", "QA second profile", "active", True)]

        async def claim(self, *args, **kwargs):
            operations.append("claim")
            if operations.count("claim") == 2 and failure == "claim":
                raise HomeError("profile_unavailable")
            return await super().claim(*args, **kwargs)

    class Bridge(FakeHomeSession):
        async def connect(self):
            operations.append("connect")
            if operations.count("connect") == 2 and failure == "bridge":
                raise HomeError("transport")
            return await super().connect()

        async def wait_for_disconnect(self):
            await asyncio.Event().wait()

        async def close_claim(self):
            operations.append("release")
            self.connected = False
            return True

        async def retry_uncertain_claim(self):
            return await self.close_claim()

        def send_turn(self, *args, **kwargs):
            pytest.fail("Replacement failure replayed a prompt")

    monkeypatch.setattr("puck_bridge.home_textual_session.HomeClient", Client)
    args = make_args(transport="home", url="wss://home.example/api/v1/bridge/ws",
                     home_grant="grant-1", history_path=tmp_path / "history.jsonl")
    session = HomeTextualSession(args, home_session_factory=Bridge)
    app = HermesStreamingApp(args=args, session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._connection_is_ready()
        previous_id = session.session_id
        app._append_block("Original conversation remains visible")
        previous_history = app._history
        await app._handle_home_command("select QA second profile")
        assert operations[:4] == ["claim", "connect", "release", "claim"]
        assert app.connection_state == "disconnected"
        assert not session.is_connected()
        assert session.session_id == previous_id
        assert session.pending_replacement
        assert app._history is previous_history
        assert "Original conversation remains visible" in transcript_of(app)
        assert "Home conversation unchanged on screen" in transcript_of(app)
        assert len([op for op in operations if op == "claim"]) == 2


def test_home_prompt_history_separates_origin_and_grant_and_canonicalizes_urls(tmp_path):
    args = make_args(transport="home", url="wss://HOME.example:443/api/v1/bridge/ws",
                     home_history_identity="grant-1", history_path=tmp_path / "history.jsonl")
    app = HermesStreamingApp(args=args)
    first = app._prompt_history_for_args(args)
    first.append("Only this Home and grant may see this prompt")
    canonical = copy(args)
    canonical.url = "https://home.example/"
    assert app._prompt_history_for_args(canonical).entries == first.entries
    other_home = copy(args)
    other_home.url = "https://other-home.example"
    other_grant = copy(args)
    other_grant.home_history_identity = "grant-2"
    assert app._prompt_history_for_args(other_home).entries == []
    assert app._prompt_history_for_args(other_grant).entries == []
    assert app._prompt_history_for_args(args).entries == first.entries


@pytest.mark.parametrize("blocked", ["uncertain", "queued"])
async def test_home_change_guards_never_invoke_replacement(tmp_path, blocked):
    from tests.test_app import FakeSession
    app = HermesStreamingApp(args=make_args(history_path=tmp_path / "history"),
                             session_factory=FakeSession)
    async with app.run_test() as pilot:
        await pilot.pause()
        if blocked == "uncertain":
            app._last_prompt_status = PROMPT_AMBIGUOUS
        else:
            app._queued_prompts.append("deliberately unsent")

        async def forbidden():
            pytest.fail("Guard allowed replacement")

        await app._home_change(forbidden)
        text = transcript_of(app)
        assert ("uncertain outcome" if blocked == "uncertain" else "Unsent prompts") in text


@pytest.mark.parametrize("operation", ["title", "explicit-new-id", "unknown-resume"])
async def test_unsupported_home_operations_never_dispatch_or_replace(monkeypatch, operation):
    from types import SimpleNamespace

    monkeypatch.setattr("puck_bridge.home_textual_session.HomeClient", FakeHomeClient)
    session = HomeTextualSession(make_args(transport="home", url="https://home.example"))

    async def forbidden(*args, **kwargs):
        pytest.fail("Unsupported Home operation reached dispatch or claim replacement")

    session._home_session = SimpleNamespace(capabilities=frozenset(), dispatch_title=forbidden)
    monkeypatch.setattr(session, "_replace", forbidden)
    with pytest.raises(UnsupportedTransportError):
        if operation == "title":
            await session.set_title("Unsupported title")
        elif operation == "explicit-new-id":
            await session.new_session(session_id="caller-chosen-id")
        else:
            await session.switch_session("unknown-reference")
