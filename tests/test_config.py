import os

import pytest

from config import (
    DEFAULT_URL,
    DEFAULT_PROFILE_ENV,
    _env_choice,
    _env_float,
    _env_int,
    _resolve_token,
    _connection_kwargs,
    build_arg_parser,
    ensure_default_config_file,
    load_config_file,
)


def test_env_float_uses_default_when_unset(monkeypatch):
    monkeypatch.delenv("SOME_FLOAT", raising=False)
    assert _env_float("SOME_FLOAT", 1.5) == 1.5


def test_env_float_parses_set_value(monkeypatch):
    monkeypatch.setenv("SOME_FLOAT", "3.25")
    assert _env_float("SOME_FLOAT", 1.5) == 3.25


def test_env_float_falls_back_on_bad_value(monkeypatch):
    monkeypatch.setenv("SOME_FLOAT", "not-a-number")
    assert _env_float("SOME_FLOAT", 1.5) == 1.5


def test_env_int_parses_set_value(monkeypatch):
    monkeypatch.setenv("SOME_INT", "42")
    assert _env_int("SOME_INT", 7) == 42


def test_env_choice_uses_default_for_an_invalid_value(monkeypatch):
    monkeypatch.setenv("SOME_MODE", "bogus")
    assert _env_choice("SOME_MODE", ("queue", "steer"), "queue") == "queue"


def test_parser_defaults_to_queue_busy_mode(monkeypatch):
    monkeypatch.delenv("VOICE_SESSION_BUSY_MODE", raising=False)
    assert build_arg_parser().parse_args([]).busy_mode == "queue"


def test_parser_defaults_to_local_voice_session_endpoint(monkeypatch):
    monkeypatch.delenv("HERMES_VOICE_SESSION_URL", raising=False)
    assert build_arg_parser().parse_args([]).url == DEFAULT_URL
    assert DEFAULT_URL == "ws://localhost:8792/voice-session"


def test_default_token_file_belongs_to_the_relay_app():
    assert DEFAULT_PROFILE_ENV.parts[-2:] == (".hermes-relay-tui", ".env")


def test_parser_reads_busy_mode_from_environment(monkeypatch):
    monkeypatch.setenv("VOICE_SESSION_BUSY_MODE", "steer")
    assert build_arg_parser().parse_args([]).busy_mode == "steer"


def test_parser_accepts_busy_mode_flag():
    assert build_arg_parser().parse_args(["--busy-mode", "interrupt"]).busy_mode == "interrupt"


def test_parser_accepts_hidden_transcript_detail_flag():
    assert build_arg_parser().parse_args(["--hide-thinking"]).hide_thinking is True


def test_parser_disables_shell_by_default(monkeypatch):
    monkeypatch.delenv("HERMES_RELAY_TUI_ALLOW_SHELL", raising=False)
    assert build_arg_parser().parse_args([]).allow_shell is False


def test_parser_reads_shell_opt_in_from_environment(monkeypatch):
    monkeypatch.setenv("HERMES_RELAY_TUI_ALLOW_SHELL", "true")
    assert build_arg_parser().parse_args([]).allow_shell is True


def test_parser_reads_audio_device_selectors_from_flags_and_environment(monkeypatch):
    monkeypatch.setenv("VOICE_SESSION_MIC_INPUT_DEVICE", "2")
    monkeypatch.setenv("VOICE_SESSION_AUDIO_OUTPUT_DEVICE", "USB Headset")

    args = build_arg_parser().parse_args([])
    assert args.mic_input_device == 2
    assert args.audio_output_device == "USB Headset"

    args = build_arg_parser().parse_args(
        ["--mic-input-device", "Built-in Microphone", "--audio-output-device", "3"]
    )
    assert args.mic_input_device == "Built-in Microphone"
    assert args.audio_output_device == 3


def test_parser_accepts_debug_trace_options(tmp_path):
    args = build_arg_parser().parse_args(["--debug", "--log-file", str(tmp_path / "trace.log")])
    assert args.debug is True
    assert args.log_file == tmp_path / "trace.log"


def test_parser_defaults_to_bounded_connection_retries(monkeypatch):
    monkeypatch.delenv("VOICE_SESSION_CONNECT_RETRIES", raising=False)
    monkeypatch.delenv("VOICE_SESSION_CONNECT_RETRY_DELAY", raising=False)
    args = build_arg_parser().parse_args([])
    assert args.connect_retries == 3
    assert args.connect_retry_delay == 1.0


def test_parser_reads_connection_retry_settings_from_environment(monkeypatch):
    monkeypatch.setenv("VOICE_SESSION_CONNECT_RETRIES", "5")
    monkeypatch.setenv("VOICE_SESSION_CONNECT_RETRY_DELAY", "0.25")
    args = build_arg_parser().parse_args([])
    assert args.connect_retries == 5
    assert args.connect_retry_delay == 0.25


def test_resolve_token_prefers_explicit_argument(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("VOICE_SESSION_TOKEN=from-file\n")
    assert _resolve_token("explicit-token", env_path) == "explicit-token"


def test_resolve_token_prefers_env_var_over_file(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("VOICE_SESSION_TOKEN=from-file\n")
    monkeypatch.setenv("VOICE_SESSION_TOKEN", "from-environment")
    assert _resolve_token(None, env_path) == "from-environment"


def test_resolve_token_reads_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("VOICE_SESSION_TOKEN", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text('VOICE_SESSION_TOKEN="quoted-token"\n')
    assert _resolve_token(None, env_path) == "quoted-token"


def test_resolve_token_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("VOICE_SESSION_TOKEN", raising=False)
    assert _resolve_token(None, tmp_path / "nope.env") == ""


def test_resolve_token_falls_back_to_the_legacy_profile_file(tmp_path, monkeypatch):
    monkeypatch.delenv("VOICE_SESSION_TOKEN", raising=False)
    default_path = tmp_path / "default.env"
    legacy_path = tmp_path / "legacy.env"
    legacy_path.write_text("VOICE_SESSION_TOKEN=legacy-token\n")
    monkeypatch.setattr("config.DEFAULT_PROFILE_ENV", default_path)
    monkeypatch.setattr("config.LEGACY_PROFILE_ENV", legacy_path)

    assert _resolve_token(None, default_path) == "legacy-token"


def test_connection_kwargs_uses_additional_headers_when_supported():
    def fake_connect(url, additional_headers=None, max_size=None):
        pass

    kwargs = _connection_kwargs(fake_connect, "tok")
    assert kwargs["additional_headers"] == {"Authorization": "Bearer tok"}


def test_connection_kwargs_falls_back_to_extra_headers():
    def fake_connect(url, extra_headers=None, max_size=None):
        pass

    kwargs = _connection_kwargs(fake_connect, "tok")
    assert kwargs["extra_headers"] == {"Authorization": "Bearer tok"}


# --- YAML config file --------------------------------------------------------


def test_load_config_file_returns_empty_dict_when_missing(tmp_path):
    assert load_config_file(tmp_path / "nope.yaml") == {}


def test_load_config_file_returns_empty_dict_for_none_path():
    assert load_config_file(None) == {}


def test_load_config_file_parses_yaml_mapping(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("url: ws://media-server.local:8792/voice-session\nbusy_mode: steer\n")
    assert load_config_file(path) == {
        "url": "ws://media-server.local:8792/voice-session",
        "busy_mode": "steer",
    }


def test_load_config_file_rejects_a_non_mapping_document(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("- just\n- a\n- list\n")
    with pytest.raises(SystemExit):
        load_config_file(path)


def test_load_config_file_rejects_invalid_yaml(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("url: [unterminated\n")
    with pytest.raises(SystemExit):
        load_config_file(path)


def test_load_config_file_treats_an_empty_file_as_no_settings(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("")
    assert load_config_file(path) == {}


def test_config_file_fills_the_fiddly_defaults(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "url: ws://media-server.local:8792/voice-session",
                "profile_env: /custom/profile.env",
                "client_id: laptop-client",
                "device_id: laptop-device",
                "session_id: media-server-session",
                "busy_mode: steer",
                "mic_input_device: 2",
                "audio_output_device: USB Headset",
                "connect_retries: 7",
                "connect_retry_delay: 2.5",
                "turn_timeout: 60",
                "history_path: /custom/history.jsonl",
                "allow_shell: true",
            ]
        )
    )
    argv = ["--config", str(config_path)]
    args = build_arg_parser(argv).parse_args(argv)

    assert args.url == "ws://media-server.local:8792/voice-session"
    assert str(args.profile_env) == "/custom/profile.env"
    assert args.client_id == "laptop-client"
    assert args.device_id == "laptop-device"
    assert args.session_id == "media-server-session"
    assert args.busy_mode == "steer"
    assert args.mic_input_device == 2
    assert args.audio_output_device == "USB Headset"
    assert args.connect_retries == 7
    assert args.connect_retry_delay == 2.5
    assert args.turn_timeout == 60
    assert str(args.history_path) == "/custom/history.jsonl"
    assert args.allow_shell is True


def test_cli_flag_overrides_config_file(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("busy_mode: steer\n")
    argv = ["--config", str(config_path), "--busy-mode", "interrupt"]
    args = build_arg_parser(argv).parse_args(argv)
    assert args.busy_mode == "interrupt"


def test_env_var_overrides_config_file(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("busy_mode: steer\n")
    monkeypatch.setenv("VOICE_SESSION_BUSY_MODE", "interrupt")
    argv = ["--config", str(config_path)]
    args = build_arg_parser(argv).parse_args(argv)
    assert args.busy_mode == "interrupt"


def test_config_file_overrides_hardcoded_default_but_not_env_or_cli(tmp_path, monkeypatch):
    monkeypatch.delenv("VOICE_SESSION_BUSY_MODE", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("busy_mode: steer\n")
    argv = ["--config", str(config_path)]
    args = build_arg_parser(argv).parse_args(argv)
    assert args.busy_mode == "steer"


def test_invalid_busy_mode_in_config_file_falls_back_to_hardcoded_default(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("busy_mode: not-a-real-mode\n")
    argv = ["--config", str(config_path)]
    args = build_arg_parser(argv).parse_args(argv)
    assert args.busy_mode == "queue"


def test_default_config_path_is_used_when_no_flag_or_env_given(tmp_path, monkeypatch):
    import config as config_module

    default_path = tmp_path / "config.yaml"
    default_path.write_text("busy_mode: steer\n")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", default_path)
    assert build_arg_parser([]).parse_args([]).busy_mode == "steer"


def test_ensure_default_config_file_creates_missing_file_from_template(tmp_path):
    target = tmp_path / "nested" / "config.yaml"
    assert ensure_default_config_file(target) is True
    assert target.exists()
    assert target.read_text(encoding="utf-8").startswith("# Example hermes-relay config file.")


def test_ensure_default_config_file_does_not_overwrite_an_existing_file(tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text("busy_mode: steer\n")
    assert ensure_default_config_file(target) is False
    assert target.read_text(encoding="utf-8") == "busy_mode: steer\n"


def test_ensure_default_config_file_created_content_is_behaviorally_inert(tmp_path):
    """The auto-created file must not change how args resolve — it's just discoverable."""
    target = tmp_path / "config.yaml"
    ensure_default_config_file(target)
    argv = ["--config", str(target)]
    args = build_arg_parser(argv).parse_args(argv)
    assert args.busy_mode == "queue"
    assert args.url == DEFAULT_URL
