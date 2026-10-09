"""Repository-local Home deploy contract; never opens SSH or changes a host."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("deploy_home_browser", SCRIPTS / "deploy_home_browser.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)
from validate_ops_profile_config import read_home_catalog

ORIGIN = "https://display.household.ts.net"


def status():
    return {"Web": {"display.household.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8875"}}}}, "AllowFunnel": {"display.household.ts.net:443": False}}


def test_tailnet_route_is_exact_and_cannot_override_ws_or_enable_funnel():
    deploy.validate_serve(status(), ORIGIN, 8875)
    for changed in (
        {**status(), "AllowFunnel": {"display.household.ts.net:443": True}},
        {"Web": {"display.household.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8875"}, "/state": {"Proxy": "http://127.0.0.1:8765"}}}}},
        {"Web": {"display.household.ts.net:443": {"Handlers": {"/": {"Proxy": "http://0.0.0.0:8875"}}}}},
    ):
        with pytest.raises(ValueError):
            deploy.validate_serve(changed, ORIGIN, 8875)


@pytest.mark.parametrize("origin", ["http://display.household.ts.net", "https://public.example", "https://display.household.ts.net/state", "https://user@display.household.ts.net", "https://display.household.ts.net:444", "https://display.household.ts.net?x=1"])
def test_public_or_ambiguous_origins_are_rejected(origin):
    with pytest.raises(ValueError):
        deploy.tailnet_origin(origin)


def test_home_unit_has_private_storage_loopback_and_no_legacy_dependencies():
    unit = deploy.unit(ORIGIN, "https://home.household.ts.net", 8875)
    for required in ("UMask=0077", "StateDirectoryMode=0700", "--browser-transport home", "--display-host 127.0.0.1", "--display-public-origin " + ORIGIN, "pairing.json", "User=hermes-home"):
        assert required in unit
    for forbidden in ("EnvironmentFile", "VOICE_SESSION", "conversation-handle", "--token", "home.env"):
        assert forbidden not in unit
    assert '"$target/unit.service"' in deploy.REMOTE
    assert '"$old/unit.service"' in deploy.REMOTE
    assert ".home-browser-v1" in deploy.REMOTE
    assert "hermes-relay-home.service" not in deploy.REMOTE


def test_shortcuts_are_optional_and_bound_to_stable_grants(tmp_path):
    path = tmp_path / "shortcuts.yaml"
    path.write_text("version: 1\nprofiles: {}\n")
    assert read_home_catalog(path)["profiles"] == {}
    path.write_text("version: 1\nprofiles:\n  later:\n    display_name: Later\n    home_grant: stable-grant\n    wake_phrases: [Hey Later]\n")
    catalog = read_home_catalog(path)
    assert catalog["profiles"]["later"]["home_grant"] == "stable-grant"
    path.write_text("version: 1\nprofiles:\n  later:\n    display_name: Later\n    token_env: SECRET\n    wake_phrases: [Hey Later]\n")
    with pytest.raises(ValueError):
        read_home_catalog(path)
