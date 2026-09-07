from __future__ import annotations

import stat
import types
from pathlib import Path

import pytest
import yaml

import config
from config import (
    RelayProfile,
    delete_relay_profile,
    load_relay_profiles,
    migrate_legacy_profile_config,
    profile_token_env,
    save_relay_profile,
    select_relay_profile,
)


def test_relay_profile_redacts_token_and_exposes_private_source():
    profile = RelayProfile(
        name="amanda",
        display_name="Amanda",
        url="wss://relay.example/voice-session",
        token="secret-token",
        token_env="VOICE_SESSION_TOKEN_AMANDA",
        client_id="amanda-laptop",
        device_id="amanda-mac",
        session_id="amanda-session",
    )

    assert profile.token_configured is True
    assert "secret-token" not in repr(profile)
    assert "VOICE_SESSION_TOKEN_AMANDA" in repr(profile)


def test_profile_token_env_uses_safe_stable_names():
    assert profile_token_env("amanda") == "VOICE_SESSION_TOKEN_AMANDA"
    assert profile_token_env("default") == "VOICE_SESSION_TOKEN"
    with pytest.raises(ValueError):
        profile_token_env("../secrets")


def test_load_relay_profiles_resolves_private_token_source(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text('VOICE_SESSION_TOKEN_AMANDA="amanda-secret"\n', encoding="utf-8")
    cfg = {
        "profile_env": str(env_path),
        "active_profile": "amanda",
        "profiles": {
            "amanda": {
                "display_name": "Amanda",
                "url": "wss://amanda.example/voice-session",
                "token_env": "VOICE_SESSION_TOKEN_AMANDA",
                "client_id": "amanda-client",
                "device_id": "amanda-device",
                "session_id": "amanda-session",
            },
            "jensen": {
                "display_name": "Jensen",
                "url": "wss://jensen.example/voice-session",
                "token_env": "VOICE_SESSION_TOKEN_JENSEN",
                "client_id": "jensen-client",
                "device_id": "jensen-device",
                "session_id": "jensen-session",
            },
        },
    }
    monkeypatch.setenv("VOICE_SESSION_TOKEN_JENSEN", "jensen-secret")

    profiles = load_relay_profiles(cfg)

    assert [profile.name for profile in profiles] == ["amanda", "jensen"]
    assert profiles[0].token == "amanda-secret"
    assert profiles[1].token == "jensen-secret"
    assert profiles[0].token_env == "VOICE_SESSION_TOKEN_AMANDA"


def test_named_profiles_do_not_fall_back_to_another_profile_token(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text('VOICE_SESSION_TOKEN="default-secret"\n', encoding="utf-8")
    monkeypatch.delenv("VOICE_SESSION_TOKEN_JENSEN", raising=False)
    profiles = load_relay_profiles(
        {
            "profile_env": str(env_path),
            "profiles": {
                "jensen": {
                    "url": "wss://jensen.example/voice-session",
                    "token_env": "VOICE_SESSION_TOKEN_JENSEN",
                    "client_id": "jensen-client",
                    "device_id": "device",
                    "session_id": "jensen-session",
                }
            },
        }
    )

    assert profiles[0].token == ""


def test_legacy_migration_moves_literal_token_to_private_env(tmp_path):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    config_path.write_text(
        yaml.safe_dump(
            {
                "url": "wss://relay.example/voice-session",
                "profile_env": str(env_path),
                "token": "legacy-secret",
                "client_id": "legacy-client",
                "device_id": "legacy-device",
                "session_id": "legacy-session",
                "display_name": "Legacy relay",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    profile = migrate_legacy_profile_config(config_path)

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert isinstance(profile, RelayProfile)
    assert profile.name == "default"
    assert profile.token == "legacy-secret"
    assert saved["active_profile"] == "default"
    assert saved["profiles"]["default"]["token_env"] == "VOICE_SESSION_TOKEN"
    assert "token" not in saved
    assert "legacy-secret" not in config_path.read_text(encoding="utf-8")
    assert env_path.read_text(encoding="utf-8") == 'VOICE_SESSION_TOKEN="legacy-secret"\n'
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


def test_save_profile_preserves_unrelated_config_and_env_values(tmp_path):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    config_path.write_text(
        yaml.safe_dump(
            {"profile_env": str(env_path), "busy_mode": "steer", "custom": {"keep": True}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    env_path.write_text("UNRELATED=value\n", encoding="utf-8")

    save_relay_profile(
        config_path,
        name="amanda",
        display_name="Amanda",
        url="wss://relay.example/voice-session",
        token="new-secret",
        client_id="amanda-client",
        device_id="amanda-device",
        session_id="amanda-session",
    )

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["busy_mode"] == "steer"
    assert saved["custom"] == {"keep": True}
    assert "new-secret" not in config_path.read_text(encoding="utf-8")
    assert "UNRELATED=value" in env_path.read_text(encoding="utf-8")
    assert "VOICE_SESSION_TOKEN_AMANDA=\"new-secret\"" in env_path.read_text(encoding="utf-8")


def test_select_and_delete_profiles_update_active_selection(tmp_path):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    save_relay_profile(
        config_path,
        name="amanda",
        display_name="Amanda",
        url="wss://amanda.example/voice-session",
        token="amanda-secret",
        client_id="amanda-client",
        device_id="device",
        session_id="amanda-session",
        profile_env=env_path,
    )
    save_relay_profile(
        config_path,
        name="jensen",
        display_name="Jensen",
        url="wss://jensen.example/voice-session",
        token="jensen-secret",
        client_id="jensen-client",
        device_id="device",
        session_id="jensen-session",
        profile_env=env_path,
    )

    selected = select_relay_profile(config_path, "jensen")
    assert selected.name == "jensen"
    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["active_profile"] == "jensen"

    delete_relay_profile(config_path, "amanda")
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert list(saved["profiles"]) == ["jensen"]
    assert saved["active_profile"] == "jensen"


def test_delete_rejects_the_last_profile(tmp_path):
    config_path = tmp_path / "config.yaml"
    save_relay_profile(
        config_path,
        name="amanda",
        display_name="Amanda",
        url="wss://relay.example/voice-session",
        token="secret",
        client_id="client",
        device_id="device",
        session_id="session",
        profile_env=tmp_path / ".env",
    )

    with pytest.raises(ValueError, match="last relay profile"):
        delete_relay_profile(config_path, "amanda")


def test_parser_uses_selected_profile_connection_defaults(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text('VOICE_SESSION_TOKEN_JENSEN="jensen-secret"\n', encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "profile_env": str(env_path),
                "active_profile": "amanda",
                "profiles": {
                    "amanda": {
                        "url": "wss://amanda.example/voice-session",
                        "token_env": "VOICE_SESSION_TOKEN_AMANDA",
                        "client_id": "amanda-client",
                        "device_id": "amanda-device",
                        "session_id": "amanda-session",
                        "display_name": "Amanda",
                    },
                    "jensen": {
                        "url": "wss://jensen.example/voice-session",
                        "token_env": "VOICE_SESSION_TOKEN_JENSEN",
                        "client_id": "jensen-client",
                        "device_id": "jensen-device",
                        "session_id": "jensen-session",
                        "display_name": "Jensen",
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("VOICE_SESSION_PROFILE", raising=False)

    argv = ["--config", str(config_path), "--profile", "jensen"]
    args = config.build_arg_parser(argv).parse_args(argv)

    assert args.profile == "jensen"
    assert args.profile_name == "jensen"
    assert args.url == "wss://jensen.example/voice-session"
    assert args.token == "jensen-secret"
    assert args.client_id == "jensen-client"
    assert args.device_id == "jensen-device"
    assert args.session_id == "jensen-session"
    assert args.display_name == "Jensen"


def test_parser_keeps_explicit_connection_overrides_above_profile(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "profiles": {
                    "amanda": {
                        "url": "wss://profile.example/voice-session",
                        "token_env": "VOICE_SESSION_TOKEN_AMANDA",
                        "client_id": "profile-client",
                        "device_id": "profile-device",
                        "session_id": "profile-session",
                        "display_name": "Amanda",
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    argv = [
        "--config",
        str(config_path),
        "--profile",
        "amanda",
        "--url",
        "wss://cli.example/voice-session",
        "--client-id",
        "cli-client",
    ]

    args = config.build_arg_parser(argv).parse_args(argv)

    assert args.url == "wss://cli.example/voice-session"
    assert args.client_id == "cli-client"
    assert args.device_id == "profile-device"


def test_parser_uses_configured_or_environment_selected_profile(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "active_profile": "jensen",
                "profiles": {
                    "amanda": {"url": "wss://amanda.example"},
                    "jensen": {"url": "wss://jensen.example"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    argv = ["--config", str(config_path)]
    assert config.build_arg_parser(argv).parse_args(argv).profile == "jensen"

    monkeypatch.setenv("VOICE_SESSION_PROFILE", "amanda")
    args = config.build_arg_parser(argv).parse_args(argv)
    assert args.profile == "amanda"
    assert args.url == "wss://amanda.example"


def test_parser_accepts_bare_profile_shorthand_and_flags_after_it(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "profiles": {
                    "amanda": {
                        "url": "wss://amanda.example/voice-session",
                        "client_id": "amanda-client",
                    },
                    "jensen": {
                        "url": "wss://jensen.example/voice-session",
                        "client_id": "jensen-client",
                    },
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    argv = ["amanda", "--config", str(config_path), "--no-play"]
    args = config.build_arg_parser(argv).parse_args(argv)

    assert args.profile == "amanda"
    assert args.profile_shorthand == "amanda"
    assert args.url == "wss://amanda.example/voice-session"
    assert args.client_id == "amanda-client"
    assert args.no_play is True

    explicit = ["amanda", "--config", str(config_path), "--profile", "jensen"]
    explicit_args = config.build_arg_parser(explicit).parse_args(explicit)
    assert explicit_args.profile == "jensen"
    assert explicit_args.url == "wss://jensen.example/voice-session"


def test_parser_rejects_unknown_selected_profile(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("profiles:\n  amanda:\n    url: wss://amanda.example\n", encoding="utf-8")
    argv = ["--config", str(config_path), "--profile", "jensen"]

    with pytest.raises(SystemExit, match="unknown relay profile"):
        config.build_arg_parser(argv)


def test_parser_rejects_malformed_profile_token_source(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "profiles": {
                    "amanda": {
                        "url": "wss://amanda.example/voice-session",
                        "token_env": "not a variable",
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    argv = ["--config", str(config_path)]

    with pytest.raises(SystemExit, match="invalid relay profile configuration"):
        config.build_arg_parser(argv)
