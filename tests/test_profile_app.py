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
        assert "profile amanda" in app.sub_title
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
        assert "profile jensen" in app.sub_title
        assert app.args.wake_phrases == "hey skippy"
        assert composer.text == "draft for Jensen"
        assert app._queued_prompts == []
        assert "Amanda private transcript" not in transcript_of(app)
        assert "switching profile" in transcript_of(app)
        assert "Connected to s1 (profile jensen" in transcript_of(app)
        assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["active_profile"] == "jensen"


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
