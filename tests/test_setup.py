from __future__ import annotations

import asyncio
import json
import stat
import sys

import pytest
import yaml

import app
import config
import setup_wizard
from setup_wizard import save_setup_files
from setup_wizard import probe_connection, run_setup


@pytest.fixture(autouse=True)
def avoid_real_model_downloads(monkeypatch):
    monkeypatch.setattr(setup_wizard, "prepare_stt_model", lambda model: model)


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
        ["--transport", "voice-session"],
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


def test_run_setup_prepares_the_configured_stt_model(tmp_path, monkeypatch):
    answers = iter(["wss://hermes.example/voice-session", "jensen-laptop", "kitchen"])
    secrets = iter(["secret-token"])
    prepared = []

    def prepare(model):
        prepared.append(model)
        return "/cached/faster-whisper-base"

    monkeypatch.setattr(setup_wizard, "prepare_stt_model", prepare)

    result = run_setup(
        ["--transport", "voice-session"],
        config_path=tmp_path / "config.yaml",
        token_path=tmp_path / ".env",
        input_fn=lambda prompt: next(answers),
        secret_fn=lambda prompt: next(secrets),
        output_fn=lambda message: None,
        check_connection=False,
    )

    assert result == 0
    assert prepared == ["base"]
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert saved["stt_model"] == "base"


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
        ["--transport", "voice-session"],
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


def test_app_main_dispatches_install_subcommand(monkeypatch):
    called = []

    def fake_install(argv):
        called.append(argv)
        return 9

    monkeypatch.setattr(app, "install_crash_logging", lambda: None)
    monkeypatch.setattr("installer.run_install", fake_install)
    monkeypatch.setattr(sys, "argv", ["hermes-relay", "install", "voice"])

    assert app.main() == 9
    assert called == [["voice"]]


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


@pytest.mark.parametrize("session_result", [{"session_id": "runtime-1"}, {}])
def test_probe_connection_verifies_the_standard_gateway_handshake(session_result):
    class FakeWebSocket:
        def __init__(self):
            self.incoming = asyncio.Queue()
            self.sent = []
            self.closed = asyncio.Event()
            self.incoming.put_nowait(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "event",
                        "params": {
                            "type": "gateway.ready",
                            "payload": {"heartbeat": True},
                        },
                    }
                )
            )

        async def send(self, frame):
            payload = json.loads(frame)
            self.sent.append(payload)
            if payload.get("method") == "session.create":
                self.incoming.put_nowait(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": payload["id"],
                            "result": session_result,
                        }
                    )
                )

        async def recv(self):
            return await self.incoming.get()

    websocket = FakeWebSocket()

    class Connection:
        def __init__(self, url, **kwargs):
            self.url = url
            self.kwargs = kwargs

        async def __aenter__(self):
            return websocket

        async def __aexit__(self, *exc_info):
            websocket.closed.set()
            return False

    ok, message = asyncio.run(
        probe_connection(
            "wss://hermes.example/api/ws",
            "secret-token",
            "jensen-laptop",
            "jensen-mac",
            "kitchen",
            transport="gateway",
            hermes_profile="server-amanda",
            connect_factory=Connection,
        )
    )

    assert ok is ("session_id" in session_result)
    assert ("Standard gateway ready" in message) is ok
    assert [frame["method"] for frame in websocket.sent] == ["session.create"]


def test_run_setup_checks_the_saved_connection_when_requested(tmp_path):
    answers = iter(["wss://hermes.example/voice-session", "jensen-laptop", "kitchen"])
    secrets = iter(["secret-token"])
    output = []
    calls = []

    def check(url, token, client_id, device_id, session_id):
        calls.append((url, token, client_id, device_id, session_id))
        return True, "Connection verified"

    result = run_setup(
        ["--transport", "voice-session"],
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


def test_normalize_endpoint_defaults_to_standard_gateway_path_when_selected():
    from setup_wizard import normalize_endpoint

    assert normalize_endpoint("https://hermes.example", transport="gateway") == (
        "wss://hermes.example/api/ws"
    )


def test_normalize_endpoint_switches_between_known_transport_paths():
    from setup_wizard import normalize_endpoint

    assert normalize_endpoint(
        "wss://hermes.example/voice-session", transport="gateway"
    ) == "wss://hermes.example/api/ws"
    assert normalize_endpoint(
        "wss://hermes.example/api/ws", transport="voice-session"
    ) == "wss://hermes.example/voice-session"


def test_normalize_endpoint_rejects_home_bridge_path_for_direct_gateway():
    from setup_wizard import normalize_endpoint

    with pytest.raises(ValueError, match="Home bridge routes"):
        normalize_endpoint(
            "wss://home.example/api/v1/bridge/ws",
            transport="gateway",
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "wss://user:secret@hermes.example/api/ws",
        "wss://hermes.example/api/ws?to%6ben=secret",
        "wss://hermes.example/api/ws?access%5ftoken=secret",
        "wss://hermes.example/api/ws?api-key=secret",
    ],
)
def test_normalize_endpoint_rejects_standard_credentials_in_url(endpoint):
    from setup_wizard import normalize_endpoint

    with pytest.raises(ValueError, match="credentials|token separately"):
        normalize_endpoint(endpoint, transport="gateway")


def test_run_setup_can_select_standard_transport_without_token_in_config(tmp_path):
    answers = iter(["https://hermes.example", "amanda-laptop", "kitchen"])
    secrets = iter(["gateway-secret"])

    result = run_setup(
        ["--transport", "gateway", "--hermes-profile", "server-amanda", "--no-check"],
        config_path=tmp_path / "config.yaml",
        token_path=tmp_path / ".env",
        input_fn=lambda prompt: next(answers),
        secret_fn=lambda prompt: next(secrets),
        output_fn=lambda message: None,
        check_connection=False,
    )

    assert result == 0
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert saved["transport"] == "gateway"
    assert saved["hermes_profile"] == "server-amanda"
    assert saved["url"] == "wss://hermes.example/api/ws"
    assert "gateway-secret" not in (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_standard_setup_rejects_query_token_before_writing_config(tmp_path):
    output = []
    secret_calls = []
    answers = iter(["standard", "https://hermes.example/api/ws?token=private"])

    result = run_setup(
        config_path=tmp_path / "config.yaml",
        token_path=tmp_path / ".env",
        input_fn=lambda _prompt: next(answers),
        secret_fn=lambda _prompt: secret_calls.append(True),
        output_fn=output.append,
        check_connection=False,
    )

    assert result == 1
    assert not (tmp_path / "config.yaml").exists()
    assert not (tmp_path / ".env").exists()
    assert secret_calls == []
    assert "credentials separately" in output[-1]


@pytest.mark.parametrize("choice", ["", "some other mode"])
def test_fresh_setup_requires_an_explicit_home_or_standard_choice(tmp_path, choice):
    config_path = tmp_path / "config.yaml"
    token_path = tmp_path / ".env"
    output = []
    secret_calls = []

    result = run_setup(
        config_path=config_path,
        token_path=token_path,
        input_fn=lambda _prompt: choice,
        secret_fn=lambda _prompt: secret_calls.append(True),
        output_fn=output.append,
        check_connection=False,
    )

    assert result == 1
    assert not config_path.exists()
    assert not token_path.exists()
    assert not secret_calls
    assert "choose HomeBridge or Standard Hermes" in output[-1]


def test_standard_setup_connection_failure_keeps_the_selected_mode(tmp_path):
    answers = iter(
        ["standard", "https://hermes.example", "amanda", "amanda-laptop", "kitchen"]
    )
    checked = []

    def check(
        url,
        token,
        client_id,
        device_id,
        session_id,
        *,
        transport,
        hermes_profile,
    ):
        checked.append((url, transport, hermes_profile))
        return False, "Standard connection failed"

    result = run_setup(
        config_path=tmp_path / "config.yaml",
        token_path=tmp_path / ".env",
        input_fn=lambda _prompt: next(answers),
        secret_fn=lambda _prompt: "standard-token",
        output_fn=lambda _message: None,
        connection_check_fn=check,
    )

    assert result == 1
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert saved["transport"] == "gateway"
    assert saved["url"] == "wss://hermes.example/api/ws"
    assert saved["hermes_profile"] == "amanda"
    assert checked == [("wss://hermes.example/api/ws", "gateway", "amanda")]


def test_fresh_homebridge_choice_enters_pairing_without_standard_token_prompt(
    tmp_path, monkeypatch
):
    from home_client import Grant

    prompts = []
    answers = iter(["HomeBridge", "household", "Home TUI"])

    async def fake_pair(home, code, *, label, output_fn):
        assert home == "https://home.example"
        assert code == "short-code"
        assert label == "Home TUI"
        return [Grant("grant-1", "Amanda", "active", True)]

    monkeypatch.setattr("home_pairing_cli.pair", fake_pair)
    result = run_setup(
        config_path=tmp_path / "config.yaml",
        token_path=tmp_path / "private.env",
        input_fn=lambda prompt: next(answers),
        secret_fn=lambda prompt: prompts.append(prompt)
        or "hermes-home://pair?home=https%3A%2F%2Fhome.example&code=short-code",
        output_fn=lambda _message: None,
        check_connection=False,
    )

    assert result == 0
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert saved["profiles"]["household"]["transport"] == "home"
    assert not (tmp_path / "private.env").exists()
    assert all("Bearer token" not in prompt for prompt in prompts)


def test_standard_setup_prepares_explicitly_selected_speech_model(tmp_path, monkeypatch):
    prepared = []
    answers = iter(["https://hermes.example", "amanda"])
    monkeypatch.setattr(
        setup_wizard,
        "prepare_stt_model",
        lambda model: prepared.append(model) or "/cache/tiny",
    )

    result = run_setup(
        ["--transport", "gateway", "--stt-model", "tiny", "--no-check"],
        config_path=tmp_path / "config.yaml",
        token_path=tmp_path / ".env",
        input_fn=lambda _prompt: next(answers),
        secret_fn=lambda _prompt: "standard-token",
        output_fn=lambda _message: None,
        check_connection=False,
    )

    assert result == 0
    assert prepared == ["tiny"]
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert saved["stt_model"] == "tiny"


def test_standard_setup_preserves_root_legacy_connection_as_a_profile(tmp_path):
    config_path = tmp_path / "config.yaml"
    token_path = tmp_path / ".env"
    config_path.write_text(
        yaml.safe_dump(
            {
                "url": "wss://legacy.example/voice-session",
                "profile_env": str(token_path),
                "client_id": "legacy-client",
                "device_id": "legacy-device",
                "session_id": "legacy-session",
                "transport": "voice-session",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    token_path.write_text('VOICE_SESSION_TOKEN="legacy-token"\n', encoding="utf-8")
    answers = iter(["https://standard.example", "amanda"])

    result = run_setup(
        ["--transport", "gateway", "--no-check"],
        config_path=config_path,
        token_path=token_path,
        input_fn=lambda _prompt: next(answers),
        secret_fn=lambda _prompt: "standard-token",
        output_fn=lambda _message: None,
        check_connection=False,
    )

    assert result == 0
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["active_profile"] == "standard"
    assert saved["profiles"]["default"]["transport"] == "voice-session"
    assert saved["profiles"]["default"]["url"] == "wss://legacy.example/voice-session"
    assert saved["profiles"]["standard"]["transport"] == "gateway"
    assert saved["profiles"]["standard"]["url"] == "wss://standard.example/api/ws"
    private_env = token_path.read_text(encoding="utf-8")
    assert 'VOICE_SESSION_TOKEN="legacy-token"' in private_env
    assert 'VOICE_SESSION_TOKEN_STANDARD="standard-token"' in private_env


def test_voice_session_setup_requires_new_token_when_profile_endpoint_changes(
    tmp_path,
):
    config_path = tmp_path / "config.yaml"
    token_path = tmp_path / ".env"
    config.save_relay_profile(
        config_path,
        name="legacy",
        display_name="Legacy",
        url="wss://old.example/voice-session",
        token="existing-token",
        client_id="legacy-client",
        device_id="legacy-device",
        session_id="legacy-session",
        transport="voice-session",
        profile_env=token_path,
    )
    original_config = config_path.read_text(encoding="utf-8")
    original_env = token_path.read_text(encoding="utf-8")

    result = run_setup(
        ["--transport", "voice-session", "--profile", "legacy", "--no-check"],
        config_path=config_path,
        token_path=token_path,
        input_fn=lambda _prompt: "wss://new.example/voice-session",
        secret_fn=lambda _prompt: "",
        output_fn=lambda _message: None,
        check_connection=False,
    )

    assert result == 1
    assert config_path.read_text(encoding="utf-8") == original_config
    assert token_path.read_text(encoding="utf-8") == original_env


def test_first_run_standard_setup_skips_local_speech_model_preparation(
    tmp_path, monkeypatch
):
    answers = iter(
        [
            "Standard Hermes",
            "https://hermes.example",
            "amanda",
            "amanda-laptop",
            "kitchen",
        ]
    )
    output = []
    prompts = []
    prepared = []

    def prepare(model):
        prepared.append(model)
        raise AssertionError("Standard setup must not require a local speech model")

    monkeypatch.setattr(setup_wizard, "prepare_stt_model", prepare)
    result = run_setup(
        config_path=tmp_path / "config.yaml",
        token_path=tmp_path / ".env",
        input_fn=lambda prompt: prompts.append(prompt) or next(answers),
        secret_fn=lambda _prompt: "standard-token",
        output_fn=output.append,
        check_connection=False,
    )

    assert result == 0
    assert prepared == []
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert saved["transport"] == "gateway"
    assert saved["url"] == "wss://hermes.example/api/ws"
    assert saved["hermes_profile"] == "amanda"
    assert "stt_model" not in saved
    assert "Standard Hermes" in "\n".join(output)
    assert "Local microphone capture is optional" in "\n".join(output)
    assert all("Client ID" not in prompt and "Session ID" not in prompt for prompt in prompts)
    assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600


def test_first_run_standard_setup_does_not_reuse_legacy_credentials(tmp_path):
    config_path = tmp_path / "config.yaml"
    token_path = tmp_path / ".env"
    original_config = {
        "url": "wss://legacy.example/voice-session",
        "profile_env": str(token_path),
    }
    original_yaml = yaml.safe_dump(original_config, sort_keys=False)
    config_path.write_text(original_yaml, encoding="utf-8")
    token_path.write_text('VOICE_SESSION_TOKEN="legacy-token"\n', encoding="utf-8")
    original_env = token_path.read_text(encoding="utf-8")
    answers = iter(["standard", "https://standard.example", "amanda"])
    output = []

    result = run_setup(
        config_path=config_path,
        token_path=token_path,
        input_fn=lambda _prompt: next(answers),
        secret_fn=lambda _prompt: "",
        output_fn=output.append,
        check_connection=False,
    )

    assert result == 1
    assert config_path.read_text(encoding="utf-8") == original_yaml
    assert token_path.read_text(encoding="utf-8") == original_env
    assert "bearer token is required" in output[-1]


def test_standard_setup_adds_a_profile_without_overwriting_other_profiles(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "config.yaml"
    token_path = tmp_path / ".env"
    original_home = {
        "display_name": "Household",
        "url": "wss://home.example/api/v1/bridge/ws",
        "client_id": "home-client",
        "device_id": "home-device",
        "session_id": "home-session",
        "transport": "home",
        "home_grant": "grant-7",
    }
    original_fork = {
        "display_name": "Legacy",
        "url": "wss://legacy.example/voice-session",
        "client_id": "legacy-client",
        "device_id": "legacy-device",
        "session_id": "legacy-session",
        "transport": "voice-session",
        "token_env": "VOICE_SESSION_TOKEN_FORK",
    }
    config_path.write_text(
        yaml.safe_dump(
            {
                "active_profile": "household",
                "profile_env": str(token_path),
                "profiles": {"household": original_home, "fork": original_fork},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    token_path.write_text('VOICE_SESSION_TOKEN_FORK="legacy-token"\n', encoding="utf-8")
    monkeypatch.setattr(
        setup_wizard,
        "prepare_stt_model",
        lambda _model: pytest.fail("Standard setup must not prepare a speech model"),
    )
    answers = iter(["https://standard.example", "amanda-laptop", "default"])

    result = run_setup(
        ["--transport", "gateway", "--profile", "standard", "--hermes-profile", "amanda", "--no-check"],
        config_path=config_path,
        input_fn=lambda _prompt: next(answers),
        secret_fn=lambda _prompt: "standard-token",
        output_fn=lambda _message: None,
        check_connection=False,
    )

    assert result == 0
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["active_profile"] == "standard"
    assert saved["profiles"]["household"] == original_home
    assert saved["profiles"]["fork"] == original_fork
    assert saved["profiles"]["standard"]["transport"] == "gateway"
    assert saved["profiles"]["standard"]["hermes_profile"] == "amanda"
    assert "standard-token" not in config_path.read_text(encoding="utf-8")
    private_env = token_path.read_text(encoding="utf-8")
    assert 'VOICE_SESSION_TOKEN_FORK="legacy-token"' in private_env
    assert 'VOICE_SESSION_TOKEN_STANDARD="standard-token"' in private_env


def test_standard_setup_requires_a_new_token_when_endpoint_changes(tmp_path):
    config_path = tmp_path / "config.yaml"
    token_path = tmp_path / ".env"
    config.save_relay_profile(
        config_path,
        name="standard",
        display_name="Standard",
        url="wss://relay.example/api/ws",
        token="existing-standard-token",
        client_id="standard-client",
        device_id="standard-device",
        session_id="standard-session",
        transport="gateway",
        hermes_profile="amanda",
        profile_env=token_path,
    )
    original_config = config_path.read_text(encoding="utf-8")
    original_env = token_path.read_text(encoding="utf-8")
    output = []

    result = run_setup(
        ["--transport", "gateway", "--profile", "standard", "--no-check"],
        config_path=config_path,
        input_fn=lambda _prompt: "https://other-relay.example",
        secret_fn=lambda _prompt: "",
        output_fn=output.append,
        check_connection=False,
    )

    assert result == 1
    assert config_path.read_text(encoding="utf-8") == original_config
    assert token_path.read_text(encoding="utf-8") == original_env
    assert "bearer token is required" in output[-1]


def test_standard_setup_reuses_token_for_matching_default_profile_identity(tmp_path):
    config_path = tmp_path / "config.yaml"
    token_path = tmp_path / ".env"
    config.save_relay_profile(
        config_path,
        name="standard",
        display_name="Standard",
        url="wss://relay.example/api/ws",
        token="existing-standard-token",
        client_id="standard-client",
        device_id="standard-device",
        session_id="standard-session",
        transport="gateway",
        profile_env=token_path,
    )
    output = []

    result = run_setup(
        ["--transport", "gateway", "--profile", "standard", "--no-check"],
        config_path=config_path,
        input_fn=lambda _prompt: "",
        secret_fn=lambda _prompt: "",
        output_fn=output.append,
        check_connection=False,
    )

    assert result == 0
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["profiles"]["standard"]["hermes_profile"] == "default"
    assert 'VOICE_SESSION_TOKEN_STANDARD="existing-standard-token"' in token_path.read_text(encoding="utf-8")


def test_home_endpoint_normalization_enforces_the_secure_bridge_route():
    from setup_wizard import normalize_endpoint

    assert normalize_endpoint("https://home.example", transport="home") == (
        "wss://home.example/api/v1/bridge/ws"
    )
    assert normalize_endpoint(
        "wss://home.example/voice-session", transport="home"
    ) == "wss://home.example/api/v1/bridge/ws"
    with pytest.raises(ValueError, match="secure wss://"):
        normalize_endpoint("ws://home.example", transport="home")
    with pytest.raises(ValueError, match="approved"):
        normalize_endpoint("wss://home.example/other", transport="home")


def test_home_setup_uses_pairing_and_never_prompts_for_a_bearer_token(
    tmp_path, monkeypatch
):
    from home_client import Grant
    config_path = tmp_path / "config.yaml"
    profile_env = tmp_path / "private.env"
    answers = iter(["household", "Home TUI"])

    async def fake_pair(home, code, *, label, output_fn):
        assert home == "https://home.example"
        assert code == "short-code"
        assert label == "Home TUI"
        return [Grant("grant-1", "Amanda", "active", True)]

    monkeypatch.setattr("home_pairing_cli.pair", fake_pair)
    result = run_setup(
        ["--transport", "home", "--no-check"],
        config_path=config_path,
        token_path=profile_env,
        input_fn=lambda _prompt: next(answers),
        secret_fn=lambda _prompt: "hermes-home://pair?home=https%3A%2F%2Fhome.example&code=short-code",
        output_fn=lambda _message: None,
        check_connection=False,
    )

    assert result == 0
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    profile = saved["profiles"]["household"]
    assert profile["transport"] == "home"
    assert profile["url"] == "wss://home.example/api/v1/bridge/ws"
    assert profile["home_grant"] == "grant-1"
    assert "profile_env" not in profile
    assert not profile_env.exists()
    assert "short-code" not in config_path.read_text(encoding="utf-8")
    assert "opaque-handle" not in config_path.read_text(encoding="utf-8")


def test_run_setup_accepts_async_connection_checker(tmp_path):
    answers = iter(["wss://hermes.example/voice-session", "jensen-laptop", "kitchen"])
    secrets = iter(["secret-token"])

    async def check(*args):
        return True, "Connection verified asynchronously"

    result = run_setup(
        ["--transport", "voice-session"],
        config_path=tmp_path / "config.yaml",
        token_path=tmp_path / ".env",
        input_fn=lambda prompt: next(answers),
        secret_fn=lambda prompt: next(secrets),
        output_fn=lambda message: None,
        connection_check_fn=check,
    )

    assert result == 0
