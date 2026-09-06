"""Tests for HOME-13: Household account profiles routed by wake word.

Verifies:
- Profile configuration model and private token boundaries (never in repr/logs).
- Migration/fallback from legacy single-profile configuration.
- Resolution of tokens from env references (${VAR}, $VAR, token_env).
- Multi-wake routing table: unique phrases route, ambiguous phrases are ignored,
  unknown phrases are ignored.
- Profile switching on wake event: closing previous session, connecting new target,
  maintaining shared recorder without reopening hardware audio.
- Protection against account switching during capture, playback, or an active turn.
- Safe display channel reporting (account label shown, tokens never leaked).
"""

from __future__ import annotations

import asyncio
import types
from pathlib import Path

import pytest

import config
import handsfree
from config import HouseholdProfile, load_household_profiles, make_profile_args, resolve_profile_token
from home_display.appliance import Appliance
from home_display.state import DisplaySnapshot, DisplayStatePublisher
from tests.test_home_appliance import (
    FakeEarcons,
    FakeListener,
    FakePlayer,
    FakeRecorder,
    FakeServer,
    FakeSession,
    RecordingPublisher,
    _args,
    _build,
    _wait_for,
)


def test_household_profile_dataclass_and_token_redaction():
    profile = HouseholdProfile(
        name="amanda",
        display_name="Amanda",
        wake_phrases=("hey missy", "missy"),
        url="ws://localhost:8792/voice-session",
        token="super-secret-bearer-token",
        client_id="amanda-home",
        device_id="kitchen-kiosk",
        session_id="amanda-display",
        model="hermes-3",
    )
    assert profile.name == "amanda"
    assert profile.display_name == "Amanda"
    assert profile.wake_phrases == ("hey missy", "missy")
    assert profile.url == "ws://localhost:8792/voice-session"
    assert profile.token == "super-secret-bearer-token"
    assert profile.client_id == "amanda-home"
    assert profile.device_id == "kitchen-kiosk"
    assert profile.session_id == "amanda-display"
    assert profile.model == "hermes-3"

    # Acceptance criterion 6: tokens must stay in private boundary and never appear in repr
    rep = repr(profile)
    assert "super-secret-bearer-token" not in rep
    assert "token='***'" in rep


def test_token_resolution_from_env_and_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "VOICE_SESSION_TOKEN_FILE=file-token-123\nVOICE_SESSION_TOKEN_JENSEN=jensen-file-token\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("ENV_TOKEN_DIRECT", "env-token-456")

    # 1. token_env resolving from environment variable
    tok1 = resolve_profile_token({"token_env": "ENV_TOKEN_DIRECT"}, env_file)
    assert tok1 == "env-token-456"

    # 2. token_env resolving from env file
    tok2 = resolve_profile_token({"token_env": "VOICE_SESSION_TOKEN_FILE"}, env_file)
    assert tok2 == "file-token-123"

    # 3. token with ${VAR} syntax
    tok3 = resolve_profile_token({"token": "${ENV_TOKEN_DIRECT}"}, env_file)
    assert tok3 == "env-token-456"

    # 4. token with $VAR syntax
    tok4 = resolve_profile_token({"token": "$VOICE_SESSION_TOKEN_FILE"}, env_file)
    assert tok4 == "file-token-123"

    # 5. literal token
    tok5 = resolve_profile_token({"token": "literal-token-xyz"}, env_file)
    assert tok5 == "literal-token-xyz"

    # 6. Fallback by name VOICE_SESSION_TOKEN_<NAME>
    tok6 = resolve_profile_token({"name": "jensen"}, env_file)
    assert tok6 == "jensen-file-token"


def test_fallback_migration_synthesizes_default_profile():
    # When no profiles are configured, existing settings migrate cleanly
    cfg = {
        "url": "ws://relay.lan:8792/voice-session",
        "client_id": "living-room",
        "wake_phrases": "hey hermes, computer",
    }
    args = types.SimpleNamespace(
        url="ws://relay.lan:8792/voice-session",
        token="tok-123",
        client_id="living-room",
        device_id="appliance-01",
        session_id="relay-kiosk",
        display_name="Kitchen Display",
        model="hermes-3",
        profile_env=Path("/tmp/nonexistent"),
        wake_phrases="hey hermes, computer",
    )
    profiles = load_household_profiles(cfg, args)
    assert len(profiles) == 1
    default_prof = profiles[0]
    assert default_prof.name == "default"
    assert default_prof.display_name == "Kitchen Display"
    assert default_prof.url == "ws://relay.lan:8792/voice-session"
    assert default_prof.token == "tok-123"
    assert default_prof.client_id == "living-room"
    assert default_prof.device_id == "appliance-01"
    assert default_prof.session_id == "relay-kiosk"
    assert default_prof.model == "hermes-3"
    assert default_prof.wake_phrases == ("hey hermes", "computer")


def test_load_household_profiles_dict_and_list_schemas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AMANDA_SECRET_TOKEN", "amanda-bearer-secret")
    monkeypatch.setenv("JENSEN_SECRET_TOKEN", "jensen-bearer-secret")

    cfg_dict = {
        "profiles": {
            "amanda": {
                "display_name": "Amanda",
                "wake_phrase": "hey missy",
                "url": "ws://localhost:8792/voice-session",
                "token": "${AMANDA_SECRET_TOKEN}",
                "client_id": "amanda-home",
                "session_id": "amanda-kiosk",
            },
            "jensen": {
                "display_name": "Jensen",
                "wake_phrases": ["hey skippy", "skippy"],
                "url": "ws://localhost:8793/voice-session",
                "token_env": "JENSEN_SECRET_TOKEN",
                "client_id": "jensen-home",
                "session_id": "jensen-kiosk",
            },
        }
    }

    profiles = load_household_profiles(cfg_dict)
    assert len(profiles) == 2
    amanda, jensen = profiles[0], profiles[1]

    assert amanda.name == "amanda"
    assert amanda.display_name == "Amanda"
    assert amanda.wake_phrases == ("hey missy",)
    assert amanda.token == "amanda-bearer-secret"
    assert amanda.client_id == "amanda-home"

    assert jensen.name == "jensen"
    assert jensen.display_name == "Jensen"
    assert jensen.wake_phrases == ("hey skippy", "skippy")
    assert jensen.token == "jensen-bearer-secret"
    assert jensen.client_id == "jensen-home"


def test_make_profile_args_overrides_session_parameters():
    base_args = types.SimpleNamespace(
        url="ws://default:8792",
        token="default-token",
        client_id="default-client",
        device_id="device-1",
        session_id="default-session",
        display_name="Default Display",
        model="hermes-2",
        wake_enabled=True,
    )
    profile = HouseholdProfile(
        name="jensen",
        display_name="Jensen",
        wake_phrases=("hey skippy",),
        url="ws://jensen-relay:8793",
        token="jensen-tok",
        client_id="jensen-client",
        device_id="device-1",
        session_id="jensen-session",
        model="hermes-3",
    )
    p_args = make_profile_args(base_args, profile)
    assert p_args.url == "ws://jensen-relay:8793"
    assert p_args.token == "jensen-tok"
    assert p_args.client_id == "jensen-client"
    assert p_args.session_id == "jensen-session"
    assert p_args.display_name == "Jensen"
    assert p_args.model == "hermes-3"
    assert p_args.wake_enabled is True  # preserved from base


def test_display_snapshot_account_field_and_serialization():
    # Initial snapshot has account=None
    snapshot = DisplaySnapshot()
    assert snapshot.account is None
    d = snapshot.to_dict()
    assert "account" not in d

    # Snapshot with account set
    named_snapshot = DisplaySnapshot(state="idle", account="Amanda")
    assert named_snapshot.account == "Amanda"
    d_named = named_snapshot.to_dict()
    assert d_named["account"] == "Amanda"

    # Rejects non-string account
    with pytest.raises(TypeError, match="account"):
        DisplaySnapshot(account=123)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_appliance_routes_wake_phrase_to_matching_profile():
    amanda_prof = HouseholdProfile(
        name="amanda",
        display_name="Amanda",
        wake_phrases=("hey missy",),
        url="ws://localhost:8792",
        token="amanda-tok",
        client_id="amanda-client",
        device_id="dev-1",
        session_id="amanda-sess",
    )
    jensen_prof = HouseholdProfile(
        name="jensen",
        display_name="Jensen",
        wake_phrases=("hey skippy",),
        url="ws://localhost:8793",
        token="jensen-tok",
        client_id="jensen-client",
        device_id="dev-1",
        session_id="jensen-sess",
    )

    session_amanda = FakeSession(script=[{"type": "turn_end"}])
    session_jensen = FakeSession(script=[{"type": "turn_end"}])
    sessions = {"amanda": session_amanda, "jensen": session_jensen}

    publisher = RecordingPublisher()
    state = {}
    args = _args()

    appliance = Appliance(
        args,
        profiles=[amanda_prof, jensen_prof],
        sessions=sessions,
        publisher=publisher,
        build_hands_free=_build(state),
        player=FakePlayer(),
        earcons=FakeEarcons(),
        recorder=FakeRecorder(),
        server=FakeServer(),
        tick_interval=0.01,
    )

    task = asyncio.create_task(appliance.run())
    try:
        # Wait until connected to initial profile (amanda)
        assert await _wait_for(lambda: session_amanda.connects > 0)
        assert appliance.active_profile.name == "amanda"
        assert session_amanda.is_connected()

        # Wake with Amanda's phrase -> stays on Amanda without session reconnect
        assert await appliance.route_wake("hey missy") is True
        assert appliance.active_profile.name == "amanda"
        assert session_amanda.closes == 0

        # Wake with Jensen's phrase -> switches to Jensen
        assert await appliance.route_wake("hey skippy") is True
        assert appliance.active_profile.name == "jensen"
        # Amanda session was cleanly closed before Jensen session connected
        assert session_amanda.closes == 1
        assert session_jensen.connects == 1

        # Display channel received Jensen's account label
        assert "Jensen" in publisher.accounts
    finally:
        appliance.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_appliance_ignores_ambiguous_and_unknown_phrases():
    # Two profiles sharing the phrase "computer"
    p1 = HouseholdProfile(
        name="p1",
        display_name="Profile 1",
        wake_phrases=("computer", "phrase one"),
        url="ws://localhost:8792",
        token="tok1",
        client_id="c1",
        device_id="d1",
        session_id="s1",
    )
    p2 = HouseholdProfile(
        name="p2",
        display_name="Profile 2",
        wake_phrases=("computer", "phrase two"),
        url="ws://localhost:8793",
        token="tok2",
        client_id="c2",
        device_id="d1",
        session_id="s2",
    )

    sessions = {"p1": FakeSession(), "p2": FakeSession()}
    state = {}
    appliance = Appliance(
        _args(),
        profiles=[p1, p2],
        sessions=sessions,
        publisher=RecordingPublisher(),
        build_hands_free=_build(state),
        player=FakePlayer(),
        earcons=FakeEarcons(),
        recorder=FakeRecorder(),
        server=FakeServer(),
        tick_interval=0.01,
    )

    task = asyncio.create_task(appliance.run())
    try:
        assert await _wait_for(lambda: sessions["p1"].connects > 0)

        # 1. Ambiguous phrase "computer" claimed by both p1 and p2 -> ignored!
        assert await appliance.route_wake("computer") is False
        assert appliance.active_profile.name == "p1"
        assert sessions["p2"].connects == 0

        # 2. Unknown phrase -> ignored!
        assert await appliance.route_wake("hey alexa") is False
        assert appliance.active_profile.name == "p1"
        assert sessions["p2"].connects == 0

        # 3. Valid unique phrase -> routes to p2
        assert await appliance.route_wake("phrase two") is True
        assert appliance.active_profile.name == "p2"
        assert sessions["p2"].connects == 1
    finally:
        appliance.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_appliance_blocks_account_switch_during_active_turn():
    p1 = HouseholdProfile(
        name="amanda",
        display_name="Amanda",
        wake_phrases=("hey missy",),
        url="ws://localhost:8792",
        token="tok1",
        client_id="c1",
        device_id="d1",
        session_id="s1",
    )
    p2 = HouseholdProfile(
        name="jensen",
        display_name="Jensen",
        wake_phrases=("hey skippy",),
        url="ws://localhost:8793",
        token="tok2",
        client_id="c2",
        device_id="d1",
        session_id="s2",
    )

    sessions = {"amanda": FakeSession(), "jensen": FakeSession()}
    state = {}
    appliance = Appliance(
        _args(),
        profiles=[p1, p2],
        sessions=sessions,
        publisher=RecordingPublisher(),
        build_hands_free=_build(state),
        player=FakePlayer(),
        earcons=FakeEarcons(),
        recorder=FakeRecorder(),
        server=FakeServer(),
        tick_interval=0.01,
    )

    task = asyncio.create_task(appliance.run())
    try:
        assert await _wait_for(lambda: sessions["amanda"].connects > 0)
        coordinator = state["coordinator"]

        # Simulate coordinator entering CAPTURING state
        coordinator._set_state(handsfree.CAPTURING)
        assert coordinator.state == handsfree.CAPTURING

        # Criterion 4: A new wake phrase cannot switch accounts during capture, playback, or an active turn
        assert await appliance.route_wake("hey skippy") is False
        assert appliance.active_profile.name == "amanda"
        assert sessions["jensen"].connects == 0

        # Simulate coordinator entering SPEAKING state
        coordinator._set_state(handsfree.SPEAKING)
        assert await appliance.route_wake("hey skippy") is False
        assert appliance.active_profile.name == "amanda"
        assert sessions["jensen"].connects == 0

        # Once returned to IDLE, switching is allowed
        coordinator._set_state(handsfree.IDLE)
        assert await appliance.route_wake("hey skippy") is True
        assert appliance.active_profile.name == "jensen"
        assert sessions["jensen"].connects == 1
    finally:
        appliance.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_appliance_handles_failed_profile_switch_gracefully():
    p1 = HouseholdProfile(
        name="amanda",
        display_name="Amanda",
        wake_phrases=("hey missy",),
        url="ws://localhost:8792",
        token="tok1",
        client_id="c1",
        device_id="d1",
        session_id="s1",
    )
    p2 = HouseholdProfile(
        name="jensen",
        display_name="Jensen",
        wake_phrases=("hey skippy",),
        url="ws://broken:9999",
        token="tok2",
        client_id="c2",
        device_id="d1",
        session_id="s2",
    )

    # Jensen's session will fail connection
    sessions = {"amanda": FakeSession(), "jensen": FakeSession(connect_errors=5)}
    state = {}
    publisher = RecordingPublisher()
    appliance = Appliance(
        _args(),
        profiles=[p1, p2],
        sessions=sessions,
        publisher=publisher,
        build_hands_free=_build(state),
        player=FakePlayer(),
        earcons=FakeEarcons(),
        recorder=FakeRecorder(),
        server=FakeServer(),
        tick_interval=0.01,
    )

    task = asyncio.create_task(appliance.run())
    try:
        assert await _wait_for(lambda: sessions["amanda"].connects > 0)
        assert appliance.active_profile.name == "amanda"

        # Attempt to switch to Jensen -> fails connection
        result = await appliance.route_wake("hey skippy")
        assert result is False
        # Previous Amanda session was closed
        assert sessions["amanda"].closes == 1
        # Display entered disconnected state
        assert publisher.history[-1][0] == "disconnected"
    finally:
        appliance.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_route_wake_synchronous_from_worker_thread():
    """Verify the synchronous _route_wake works when called from a background worker thread."""
    p1 = HouseholdProfile(
        name="amanda",
        display_name="Amanda",
        wake_phrases=("hey missy",),
        url="ws://localhost:8792",
        token="tok1",
        client_id="c1",
        device_id="d1",
        session_id="s1",
    )
    p2 = HouseholdProfile(
        name="jensen",
        display_name="Jensen",
        wake_phrases=("hey skippy",),
        url="ws://localhost:8793",
        token="tok2",
        client_id="c2",
        device_id="d1",
        session_id="s2",
    )

    sessions = {"amanda": FakeSession(), "jensen": FakeSession()}
    state = {}
    appliance = Appliance(
        _args(),
        profiles=[p1, p2],
        sessions=sessions,
        publisher=RecordingPublisher(),
        build_hands_free=_build(state),
        player=FakePlayer(),
        earcons=FakeEarcons(),
        recorder=FakeRecorder(),
        server=FakeServer(),
        tick_interval=0.01,
    )

    task = asyncio.create_task(appliance.run())
    try:
        assert await _wait_for(lambda: sessions["amanda"].connects > 0)

        # Call synchronous _route_wake from a worker thread (just like WakeListener does)
        result = await asyncio.to_thread(appliance._route_wake, "hey skippy")
        assert result is True
        assert appliance.active_profile.name == "jensen"
        assert sessions["amanda"].closes == 1
        assert sessions["jensen"].connects == 1
    finally:
        appliance.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

