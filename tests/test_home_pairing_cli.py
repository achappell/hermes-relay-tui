from __future__ import annotations

import shlex

import pytest
import yaml

import config
import home_pairing_cli
from home_client import HomeClient, HomeError
from home_pairing_cli import pair, run_pairing_command
from profile_cli import run_profile_command
from tests.home_pairing_fakes import HOME, NOW, MemoryPairings, material


@pytest.fixture
def enrollment(monkeypatch):
    store = MemoryPairings()
    client = HomeClient(HOME, store=store)
    client.calls = []
    client.pending = True
    client.consume_error = None

    async def request(method, path, body=None, *, record=None):
        client.calls.append((method, path, body))
        if path == "/api/v1/enrollment/requests":
            assert body["type"] == "tui"
            assert body["requested_rooms"] == []
            assert body["requested_capabilities"] == ["client_claim"]
            assert body["secure_storage"] == "platform_secure_store"
            return {"schema": 1, "request_id": "request-1", "confirmation_code": "VERIFY42", "expires_at": NOW + 60}
        assert path == "/api/v1/enrollment/requests/request-1/consume"
        if client.consume_error:
            raise HomeError(client.consume_error)
        if client.pending:
            client.pending = False
            raise HomeError("approval_pending")
        return material(grants=True)

    async def no_poll_delay(_seconds):
        return None

    client.request = request
    monkeypatch.setattr(home_pairing_cli, "HomeClient", lambda _home: client)
    monkeypatch.setattr(home_pairing_cli.time, "time", lambda: NOW)
    monkeypatch.setattr(home_pairing_cli.asyncio, "sleep", no_poll_delay)
    return client, store


def test_approved_pairing_saves_secure_record_and_launchable_profile_preserving_other_profiles(tmp_path, enrollment):
    client, store = enrollment
    path = tmp_path / "config.yaml"
    original_profile = {"transport": "gateway", "url": "wss://standard.example/api/ws", "token_env": "SYNTHETIC_TEST_TOKEN"}
    original = {"profile_env": str(tmp_path / "no-private-env"), "profiles": {"standard": original_profile}, "active_profile": "standard", "no_play": True}
    path.write_text(yaml.safe_dump(original))
    output = []
    result = run_pairing_command(["pair", "--home", HOME, "--profile", "household", "--config", str(path)], secret_fn=lambda _: "synthetic-pairing-code", output_fn=output.append)

    assert result == 0
    record = store.load(HOME)
    assert record.credential == material()["credential"]
    assert record.generation == 1
    saved = yaml.safe_load(path.read_text())
    assert saved["profiles"]["standard"] == original_profile
    assert saved["no_play"] is True
    # A pending grant with the same label must never displace the approved ID.
    assert saved["profiles"]["household"]["home_grant"] == "grant-approved"
    argv = ["--config", str(path), "--profile", "household"]
    args = config.build_arg_parser(argv, resolve_relay_profile_tokens=False).parse_args(argv)
    assert args.transport == "home"
    assert args.url == "wss://home.example/api/v1/bridge/ws"
    assert args.home_grant == "grant-approved"
    assert args.token == ""
    assert len(client.calls) == 3
    assert any("VERIFY42" in line for line in output)
    public = path.read_text() + "\n".join(output)
    assert material()["credential"] not in public
    assert "synthetic-pairing-code" not in public
    assert not (tmp_path / "no-private-env").exists()


@pytest.mark.asyncio
async def test_secure_store_preflight_failure_stops_before_enrollment_or_consumption(enrollment):
    client, store = enrollment
    store.backend.fail_probe = True
    with pytest.raises(HomeError) as error:
        await pair(HOME, "synthetic-pairing-code", label="Laptop")
    assert error.value.code == "secure_store"
    assert client.calls == []
    assert store.load(HOME) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["lost_consume_response", "save_after_consume"])
async def test_consume_and_save_failures_preserve_truthful_single_use_guidance(enrollment, failure):
    client, store = enrollment
    output = []
    if failure == "lost_consume_response":
        client.consume_error = "transport"
    else:
        store.backend.fail_generation = 1
    with pytest.raises(HomeError) as error:
        await pair(HOME, "synthetic-pairing-code", label="Laptop", output_fn=output.append)
    if failure == "lost_consume_response":
        assert error.value.code == "transport"
        assert any("may already have issued" in line for line in output)
    else:
        assert error.value.code == "storage_after_consume"
        assert "consumed this pairing" in str(error.value)
        assert "revoke the unused device" in str(error.value)
    assert store.load(HOME) is None
    assert material()["credential"] not in "\n".join(output) + str(error.value)


def test_saved_credential_can_recover_missing_public_config_without_reenrollment(tmp_path, monkeypatch, enrollment):
    client, store = enrollment
    path = tmp_path / "config.yaml"
    output = []
    real_save = config.save_home_profile

    def fail_public_save(*args, **kwargs):
        raise OSError("synthetic config write failure")

    monkeypatch.setattr(config, "save_home_profile", fail_public_save)
    result = run_pairing_command(["pair", "--home", HOME, "--profile", "household", "--config", str(path)], secret_fn=lambda _: "synthetic-pairing-code", output_fn=output.append)
    assert result == 1
    assert store.load(HOME).credential == material()["credential"]
    recovery = shlex.split(output[-1].split("with: ", 1)[1])
    assert recovery[:3] == ["hermes-relay", "profile", "add"]
    monkeypatch.setattr(config, "save_home_profile", real_save)
    calls_before = len(client.calls)
    result = run_profile_command(recovery[2:], input_fn=lambda _: "", secret_fn=lambda _: pytest.fail("Home recovery requested a bearer token"), output_fn=lambda _: None)
    assert result == 0
    assert len(client.calls) == calls_before
    assert yaml.safe_load(path.read_text())["profiles"]["household"]["home_grant"] == "grant-approved"
