import os

import pytest

from config import _env_float, _env_int, _resolve_token, _connection_kwargs


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
