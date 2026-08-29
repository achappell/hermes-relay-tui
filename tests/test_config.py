import os

import pytest

from config import _env_choice, _env_float, _env_int, _resolve_token, _connection_kwargs, build_arg_parser


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


def test_parser_reads_busy_mode_from_environment(monkeypatch):
    monkeypatch.setenv("VOICE_SESSION_BUSY_MODE", "steer")
    assert build_arg_parser().parse_args([]).busy_mode == "steer"


def test_parser_accepts_busy_mode_flag():
    assert build_arg_parser().parse_args(["--busy-mode", "interrupt"]).busy_mode == "interrupt"


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
