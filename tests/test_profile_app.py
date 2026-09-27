from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from textual.widgets import Static

import config
from history import history_path_for_profile
from app import Composer, HermesStreamingApp
from tests.test_app import FakeSession, make_args, transcript_of
from commands import parse_slash_command


def _profile_args(tmp_path: Path):
    env_path = tmp_path / ".env"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "profile_env": str(env_path),
                "active_profile": "amanda",
                "profiles": {
                    "amanda": {
                        "display_name": "Amanda",
                        "url": "wss://amanda.example/voice-session",
                        "token_env": "VOICE_SESSION_TOKEN_AMANDA",
                        "client_id": "amanda-client",
                        "device_id": "device",
                        "session_id": "amanda-session",
                    },
                    "jensen": {
                        "display_name": "Jensen",
                        "url": "wss://jensen.example/voice-session",
                        "wake_phrase": "hey skippy",
                        "token_env": "VOICE_SESSION_TOKEN_JENSEN",
                        "client_id": "jensen-client",
                        "device_id": "device",
                        "session_id": "jensen-session",
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    env_path.write_text(
        'VOICE_SESSION_TOKEN_AMANDA="amanda-secret"\n'
        'VOICE_SESSION_TOKEN_JENSEN="jensen-secret"\n',
        encoding="utf-8",
    )
    argv = ["--config", str(config_path)]
    args = config.build_arg_parser(argv).parse_args(argv)
    args.no_play = True
    args.connect_retries = 0
    args.connect_retry_delay = 0
    return args, argv, config_path


class SessionFactory:
    def __init__(self, *, fail_names: set[str] | None = None):
        self.fail_names = fail_names or set()
        self.sessions: list[tuple[str, FakeSession]] = []

    def __call__(self, args):
        name = getattr(args, "profile_name", "default")
        session = FakeSession(connected=name not in self.fail_names)
        self.sessions.append((name, session))
        return session


@pytest.mark.asyncio
async def test_profile_list_is_visible_without_exposing_tokens(tmp_path):
    args, argv, _ = _profile_args(tmp_path)
    factory = SessionFactory()
    app = HermesStreamingApp(args=args, session_factory=factory, argv=argv)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_command(parse_slash_command("/profile list"))
        rendered = transcript_of(app)

    assert "amanda" in rendered
    assert "jensen" in rendered
    assert "wss://amanda.example/voice-session" in rendered
    assert "amanda-secret" not in rendered


@pytest.mark.asyncio
async def test_profile_switch_closes_old_session_preserves_draft_and_scopes_state(tmp_path):
    args, argv, config_path = _profile_args(tmp_path)
    factory = SessionFactory()
    app = HermesStreamingApp(args=args, session_factory=factory, argv=argv)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert "Profile: Amanda" in app.sub_title
        old_session = app.session
        composer = app.query_one("#composer", Composer)
        composer.text = "draft for Jensen"
        app._queued_prompts.append("must not cross profiles")
        app._append_block("Amanda private transcript")

        await app._handle_command(parse_slash_command("/profile select jensen"))
        await pilot.pause()

        assert old_session.closed is True
        assert factory.sessions[-1][0] == "jensen"
        assert factory.sessions[-1][1].connect_calls == 1
        assert app.args.profile_name == "jensen"
        assert app.args.url == "wss://jensen.example/voice-session"
        assert "Profile: Jensen" in app.sub_title
        assert app.args.wake_phrases == "hey skippy"
        assert composer.text == "draft for Jensen"
        assert app._queued_prompts == []
        assert "Amanda private transcript" not in transcript_of(app)
        assert "switching profile" in transcript_of(app)
        assert "Connected to s1 (profile jensen, chat chat-1)." in transcript_of(app)
        await app._run_turn("hello from Jensen")
        assert "Jensen: ok" in transcript_of(app)
        assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["active_profile"] == "jensen"


@pytest.mark.asyncio
async def test_profile_switch_migrates_legacy_prompt_history_without_deleting_source(
    tmp_path, monkeypatch
):
    import history as history_module
    from history import history_path_for_url

    monkeypatch.setattr(history_module, "DEFAULT_HISTORY_DIR", tmp_path / "history")
    legacy = history_path_for_url("wss://jensen.example/voice-session")
    legacy.parent.mkdir(parents=True)
    original = '"Jensen legacy prompt"\n"Jensen legacy prompt"\n'
    legacy.write_text(original, encoding="utf-8")
    args, argv, _ = _profile_args(tmp_path)
    app = HermesStreamingApp(args=args, session_factory=SessionFactory(), argv=argv)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_command(parse_slash_command("/profile select jensen"))
        await pilot.pause()

        assert app._history.entries == ["Jensen legacy prompt"]

    assert legacy.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_profile_selection_mints_a_distinct_session_identity(tmp_path):
    args, argv, _ = _profile_args(tmp_path)
    captured = []

    def factory(session_args):
        captured.append((session_args.profile_name, session_args.session_id))
        return FakeSession(session_id=session_args.session_id)

    app = HermesStreamingApp(args=args, session_factory=factory, argv=argv)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_command(parse_slash_command("/profile select jensen"))
        await pilot.pause()

    assert captured[0][0] == "amanda"
    assert captured[1][0] == "jensen"
    assert captured[0][1] != "amanda-session"
    assert captured[1][1] != "jensen-session"
    assert captured[0][1] != captured[1][1]


@pytest.mark.asyncio
async def test_profile_switch_is_refused_during_an_active_turn(tmp_path):
    args, argv, _ = _profile_args(tmp_path)
    factory = SessionFactory()
    app = HermesStreamingApp(args=args, session_factory=factory, argv=argv)

    async with app.run_test() as pilot:
        await pilot.pause()
        old_session = app.session
        app._turn_in_flight = True

        await app._handle_command(parse_slash_command("/profile select jensen"))

        assert old_session.closed is False
        assert app.args.profile_name == "amanda"
        assert "Cannot switch profile while a turn is active" in transcript_of(app)


@pytest.mark.asyncio
async def test_failed_profile_switch_does_not_fall_back_or_replay(tmp_path):
    args, argv, _ = _profile_args(tmp_path)
    factory = SessionFactory(fail_names={"jensen"})
    app = HermesStreamingApp(args=args, session_factory=factory, argv=argv)

    async with app.run_test() as pilot:
        await pilot.pause()
        old_session = app.session
        await app._handle_command(parse_slash_command("/profile select jensen"))
        await pilot.pause()

        assert old_session.closed is True
        assert app.args.profile_name == "jensen"
        assert app.connection_state == "disconnected"
        assert "unable to connect" in transcript_of(app)
        assert all(text != "must not replay" for text, _ in factory.sessions[-1][1].sent_turns)


@pytest.mark.asyncio
async def test_reload_switches_when_the_persisted_active_profile_changes(tmp_path):
    args, argv, config_path = _profile_args(tmp_path)
    factory = SessionFactory()
    app = HermesStreamingApp(args=args, session_factory=factory, argv=argv)

    async with app.run_test() as pilot:
        await pilot.pause()
        old_session = app.session
        config.select_relay_profile(config_path, "jensen")
        app._handle_reload_command()
        await pilot.pause(0.1)

        assert old_session.closed is True
        assert app.args.profile_name == "jensen"
        assert factory.sessions[-1][0] == "jensen"
        assert "profile jensen" in transcript_of(app)


@pytest.mark.asyncio
async def test_named_profile_scopes_prompt_history_and_default_transcript_export(
    tmp_path, monkeypatch
):
    args, argv, _ = _profile_args(tmp_path)
    monkeypatch.chdir(tmp_path)
    app = HermesStreamingApp(args=args, session_factory=SessionFactory(), argv=argv)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._history.path == history_path_for_profile(
            "wss://amanda.example/voice-session", "amanda"
        )
        app._append_block("export this transcript")
        await app._handle_command(parse_slash_command("/save"))

        saved_lines = list((tmp_path / "profiles" / "amanda").glob("hermes-transcript-*.txt"))
        assert len(saved_lines) == 1
        assert "export this transcript" in saved_lines[0].read_text(encoding="utf-8")
        assert app._history.path != config.DEFAULT_CONFIG_PATH
        assert "profiles" in str(app._history.path)


def test_home_prompt_history_is_scoped_by_canonical_home_and_granted_identity(
    tmp_path,
):
    history_path = tmp_path / "prompts.jsonl"
    args = make_args(
        transport="home",
        profile_name="amanda",
        url="wss://home.example/api/v1/bridge/ws",
        history_path=history_path,
    )
    app = HermesStreamingApp(args=args, session_factory=SessionFactory())

    args.home_history_identity = "grant-amanda"
    amanda_home = app._history_path_for_args(args)
    args.url = "https://home.example/"
    canonical_same_home = app._history_path_for_args(args)

    args.home_history_identity = "grant-jensen"
    jensen_home = app._history_path_for_args(args)
    args.url = "https://other-home.example"
    same_grant_other_home = app._history_path_for_args(args)

    voice_args = make_args(
        transport="voice-session",
        profile_name="amanda",
        profiles_configured=True,
        url="wss://home.example/voice-session",
        history_path=history_path,
    )
    voice_profile = app._history_path_for_args(voice_args)

    assert amanda_home == canonical_same_home
    assert len({amanda_home, jensen_home, same_grant_other_home, voice_profile}) == 4


def _home_app(tmp_path, monkeypatch):
    from puck_bridge.home_textual_session import HomeTextualSession
    from tests.test_home_textual_session import FakeHomeClient, FakeHomeSession

    class Bridge(FakeHomeSession):
        release_ok = True

        async def wait_for_disconnect(self):
            await asyncio.Event().wait()

        async def close_claim(self):
            if self.release_ok:
                await self.close()
            return self.release_ok

    monkeypatch.setattr("puck_bridge.home_textual_session.HomeClient", FakeHomeClient)
    args = make_args(transport="home", url="https://home.example", home_grant="Amanda",
                     history_path=tmp_path / "prompts.jsonl", config=tmp_path / "config.yaml")
    return HermesStreamingApp(args=args, session_factory=lambda args: HomeTextualSession(args, home_session_factory=Bridge))


@pytest.mark.asyncio
async def test_home_reload_keeps_granted_artifact_and_history_scope(tmp_path, monkeypatch):
    from copy import copy

    app = _home_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        scope, history = app._artifact_profile_name(), app._history.path
        replacement = copy(app.args)
        del replacement.home_history_identity
        replacement.home_grant = "Amanda"
        assert app.args.home_grant == "Amanda"
        class ReloadParser:
            def parse_args(self, _argv):
                return replacement
        monkeypatch.setattr(config, "build_arg_parser", lambda _argv: ReloadParser())
        app._handle_reload_command()
        await pilot.pause()
        assert app.session.home_client.claim_count == 1
        assert app.args.home_grant == "Amanda"
        assert app.args.home_history_identity == "grant-1"
        assert app._artifact_profile_name() == scope
        assert app._history.path == history


@pytest.mark.asyncio
async def test_home_failed_release_refuses_reload_and_new_without_losing_transcript(tmp_path, monkeypatch):
    from copy import copy

    app = _home_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        old_args, old_session = app.args, app.session
        app._append_block("Keep this conversation")
        app.session._home_session.release_ok = False
        target = copy(app.args)
        target.url = "https://another-home.example"
        target.profile_name = "other"
        await app._reload_profile_after_config(target)
        assert app.args is old_args
        assert app.session is old_session
        assert "Keep this conversation" in transcript_of(app)
        await app._handle_command(parse_slash_command("/new"))
        assert app.session is old_session
        assert app.session.home_client.claim_count == 1
        assert "Keep this conversation" in transcript_of(app)
        app.session._home_session.release_ok = True


@pytest.mark.asyncio
async def test_failed_profile_switch_exports_retained_transcript_under_original_profile(tmp_path, monkeypatch):
    args, argv, _ = _profile_args(tmp_path)
    monkeypatch.chdir(tmp_path)
    app = HermesStreamingApp(args=args, session_factory=SessionFactory(fail_names={"jensen"}), argv=argv)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._append_block("Amanda private transcript")
        await app._handle_command(parse_slash_command("/profile select jensen"))
        await app._handle_command(parse_slash_command("/save"))
        saved = list((tmp_path / "profiles" / "amanda").glob("hermes-transcript-*.txt"))
        assert len(saved) == 1
        assert "Amanda private transcript" in saved[0].read_text()
        assert not list((tmp_path / "profiles" / "jensen").glob("hermes-transcript-*.txt"))


@pytest.mark.asyncio
async def test_home_leave_requires_successful_replacement_before_next_prompt(tmp_path, monkeypatch):
    from app import PROMPT_AMBIGUOUS

    app = _home_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._last_prompt_status = PROMPT_AMBIGUOUS
        await app._handle_command(parse_slash_command("/home leave"))
        composer = app.query_one("#composer", Composer)
        composer.text = "keep this draft"
        await app._submit_text(composer.text, composer=composer)
        assert composer.text == "keep this draft"
        assert app.session.turn_index == 0
        assert not await app._run_turn("must not reach old claim")
        def forbidden_capture():
            raise AssertionError("microphone must remain closed")
        monkeypatch.setattr(app.session, "capture_voice", forbidden_capture)
        await app._capture_voice_turn()
        await app._arm_wake()
        assert not app.wake_armed
        assert "before opening the microphone" in transcript_of(app)
        app.session._home_session.release_ok = False
        await app._handle_command(parse_slash_command("/new"))
        assert app.session.conversation_replacement_required
        app.session._home_session.release_ok = True
        await app._handle_command(parse_slash_command("/new"))
        assert not app.session.conversation_replacement_required
        assert app.session.home_client.claim_count == 2


@pytest.mark.asyncio
async def test_failed_home_to_legacy_switch_preserves_transcript_export_scope(tmp_path, monkeypatch):
    app = _home_app(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        scope = app._artifact_profile_name()
        app._append_block("Home private transcript")
        app._session_factory = lambda _args: FakeSession(connected=False)
        target = make_args(transport="voice-session", profiles_configured=False,
                           url="wss://legacy.example/voice-session", connect_retries=0)
        assert not await app._switch_to_args(target, reason="test")
        await app._handle_command(parse_slash_command("/save"))
        saved = list((tmp_path / "profiles" / scope).glob("hermes-transcript-*.txt"))
        assert len(saved) == 1
        assert "Home private transcript" in saved[0].read_text()
        assert not list(tmp_path.glob("hermes-transcript-*.txt"))
