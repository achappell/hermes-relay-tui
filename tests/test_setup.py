from __future__ import annotations

import asyncio
import json
import stat
import sys

import yaml

import app
import config
from setup_wizard import save_setup_files
from setup_wizard import probe_connection, run_setup


def test_save_setup_files_writes_editable_config_and_private_token(tmp_path):
    config_path = tmp_path / "config.yaml"
    token_path = tmp_path / ".env"

    save_setup_files(
        config_path=config_path,
        token_path=token_path,
        url="wss://hermes.example/voice-session",
        token="secret-token",
        client_id="jensen-laptop",
        device_id="jensen-mac",
        session_id="kitchen",
        display_name="Jensen's relay",
    )

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved == {
        "url": "wss://hermes.example/voice-session",
        "profile_env": str(token_path),
        "client_id": "jensen-laptop",
        "device_id": "jensen-mac",
        "session_id": "kitchen",
        "display_name": "Jensen's relay",
    }
    assert "secret-token" not in config_path.read_text(encoding="utf-8")
    assert token_path.read_text(encoding="utf-8") == 'VOICE_SESSION_TOKEN="secret-token"\n'
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


def test_run_setup_guides_user_and_saves_the_answers(tmp_path):
    config_path = tmp_path / "config.yaml"
    token_path = tmp_path / ".env"
    answers = iter(
        [
            "https://hermes.example/voice-session/",
            "jensen-laptop",
            "kitchen",
        ]
    )
    secrets = iter(["secret-token"])
    output = []

    result = run_setup(
        config_path=config_path,
        token_path=token_path,
        input_fn=lambda prompt: next(answers),
        secret_fn=lambda prompt: next(secrets),
        output_fn=output.append,
        check_connection=False,
    )

    assert result == 0
    assert "Setup complete" in output[-1]
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["url"] == "wss://hermes.example/voice-session"
    assert saved["client_id"] == "jensen-laptop"
    assert saved["device_id"] == config.default_device_id()
    assert saved["session_id"] == "kitchen"


def test_run_setup_reuses_an_existing_custom_token_file(tmp_path):
    config_path = tmp_path / "config.yaml"
    token_path = tmp_path / "custom.env"
    config_path.write_text(
        yaml.safe_dump(
            {
                "url": "wss://hermes.example/voice-session",
                "profile_env": str(token_path),
            }
        ),
        encoding="utf-8",
    )
    token_path.write_text('VOICE_SESSION_TOKEN="existing-token"\n', encoding="utf-8")

    result = run_setup(
        config_path=config_path,
        input_fn=lambda prompt: "",
        secret_fn=lambda prompt: "",
        output_fn=lambda message: None,
        check_connection=False,
    )

    assert result == 0
    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["profile_env"] == str(
        token_path
    )
    assert "VOICE_SESSION_TOKEN=\"existing-token\"" in token_path.read_text(encoding="utf-8")


def test_app_main_dispatches_setup_subcommand(monkeypatch):
    called = []

    def fake_setup(argv):
        called.append(argv)
        return 7

    monkeypatch.setattr(app, "install_crash_logging", lambda: None)
    monkeypatch.setattr("setup_wizard.run_setup", fake_setup)
    monkeypatch.setattr(sys, "argv", ["hermes-relay", "setup", "--no-check"])

    assert app.main() == 7
    assert called == [["--no-check"]]


def test_app_main_installs_crash_logging_before_dispatch(monkeypatch):
    installed = []

    monkeypatch.setattr(app, "install_crash_logging", lambda: installed.append(True), raising=False)
    monkeypatch.setattr("setup_wizard.run_setup", lambda argv: 0)
    monkeypatch.setattr(sys, "argv", ["hermes-relay", "setup"])

    assert app.main() == 0
    assert installed == [True]


def test_probe_connection_verifies_the_voice_session_handshake():
    class FakeWebSocket:
        def __init__(self):
            self.sent = []

        async def send(self, frame):
            self.sent.append(json.loads(frame))

        async def recv(self):
            return json.dumps(
                {
                    "type": "hello_ack",
                    "protocol_version": 1,
                    "chat_id": "jensen-laptop:jensen-mac",
                }
            )

    websocket = FakeWebSocket()

    class Connection:
        def __init__(self, url, **kwargs):
            self.url = url
            self.kwargs = kwargs

        async def __aenter__(self):
            return websocket

        async def __aexit__(self, *exc_info):
            return False

    ok, message = asyncio.run(
        probe_connection(
            "wss://hermes.example/voice-session",
            "secret-token",
            "jensen-laptop",
            "jensen-mac",
            "kitchen",
            connect_factory=Connection,
        )
    )

    assert ok is True
    assert "Connection verified" in message
    assert websocket.sent == [
        {
            "type": "hello",
            "protocol_version": 1,
            "client_id": "jensen-laptop",
            "device_id": "jensen-mac",
            "session_id": "kitchen",
            "display_name": "jensen-laptop relay",
        }
    ]


def test_run_setup_checks_the_saved_connection_when_requested(tmp_path):
    answers = iter(["wss://hermes.example/voice-session", "jensen-laptop", "kitchen"])
    secrets = iter(["secret-token"])
    output = []
    calls = []

    def check(url, token, client_id, device_id, session_id):
        calls.append((url, token, client_id, device_id, session_id))
        return True, "Connection verified"

    result = run_setup(
        config_path=tmp_path / "config.yaml",
        token_path=tmp_path / ".env",
        input_fn=lambda prompt: next(answers),
        secret_fn=lambda prompt: next(secrets),
        output_fn=output.append,
        connection_check_fn=check,
    )

    assert result == 0
    assert calls == [
        (
            "wss://hermes.example/voice-session",
            "secret-token",
            "jensen-laptop",
            config.default_device_id(),
            "kitchen",
        )
    ]
    assert output[-1] == "Connection verified"


def test_normalize_endpoint_accepts_http_urls_pasted_from_server_docs():
    from setup_wizard import normalize_endpoint

    assert normalize_endpoint("https://hermes.example/voice-session/") == (
        "wss://hermes.example/voice-session"
    )


def test_run_setup_accepts_async_connection_checker(tmp_path):
    answers = iter(["wss://hermes.example/voice-session", "jensen-laptop", "kitchen"])
    secrets = iter(["secret-token"])

    async def check(*args):
        return True, "Connection verified asynchronously"

    result = run_setup(
        config_path=tmp_path / "config.yaml",
        token_path=tmp_path / ".env",
        input_fn=lambda prompt: next(answers),
        secret_fn=lambda prompt: next(secrets),
        output_fn=lambda message: None,
        connection_check_fn=check,
    )

    assert result == 0
