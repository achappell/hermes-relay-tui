"""Repository-local Home deploy contract; never opens SSH or changes a host."""
from __future__ import annotations

import importlib.util
from copy import deepcopy
import shlex
import subprocess
from pathlib import Path
import sys
from urllib.parse import urlsplit

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("deploy_home_browser", SCRIPTS / "deploy_home_browser.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)
from validate_ops_profile_config import read_home_catalog

ORIGIN = "https://display.household.ts.net"
CUSTOM_ORIGINS = [
    "https://home.example.com",
    "https://display.nested.example.com",
    "https://other.example.com:443",
    ORIGIN,
]


def status():
    return {"TCP": {"443": {"HTTPS": True}}, "Web": {"display.household.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8875"}}}}, "AllowFunnel": {"display.household.ts.net:443": False}}


def test_tailnet_route_is_exact_and_cannot_override_ws_or_enable_funnel():
    deploy.validate_serve(status(), ORIGIN, 8875)
    for changed in (
        {**status(), "AllowFunnel": {"display.household.ts.net:443": True}},
        {**status(), "Web": {"display.household.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8875"}, "/state": {"Proxy": "http://127.0.0.1:8765"}}}}},
        {**status(), "Web": {"display.household.ts.net:443": {"Handlers": {"/": {"Proxy": "http://0.0.0.0:8875"}}}}},
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


def caddy_servers(origin="https://home.example.com"):
    # Native shape produced by Caddy adapt for home-browser.caddy.example.
    return {"srv0": {"listen": [":443"], "routes": [{
        "match": [{"host": [urlsplit(origin).hostname]}],
        "handle": [{"handler": "subroute", "routes": [{
            "handle": [{"handler": "subroute", "routes": [
                {
                    "handle": [{"handler": "static_response", "status_code": 403}],
                    "match": [{"not": [{"remote_ip": {"ranges": ["127.0.0.1", "::1"]}}]}],
                },
                {"handle": [{"handler": "reverse_proxy", "upstreams": [{"dial": "127.0.0.1:8875"}]}]},
            ]}],
        }]}],
        "terminal": True,
    }]}}


@pytest.mark.parametrize("origin", [
    "https://home.example.com/", "http://home.example.com",
    "https://home.example.com:444", "https://home.example.com/state",
    "https://user@home.example.com", "https://home.example.com?x=1",
    "https://home.example.com#x", "https://home.example.com\n",
    "https://HOME.example.com", ORIGIN + ":8443",
    "https://127.0.0.1", "https://[::1]", "https://2130706433",
])
def test_caddy_ingress_rejects_invalid_or_nondefault_port_origins(origin):
    with pytest.raises(ValueError):
        deploy.public_origin(origin, "caddy")


@pytest.mark.parametrize("origin", CUSTOM_ORIGINS)
def test_existing_origin_and_custom_origin_modes_are_explicit_and_single(origin):
    assert deploy.public_origin(ORIGIN, "serve") == ORIGIN
    assert deploy.public_origin(ORIGIN + ":443", "serve") == ORIGIN + ":443"
    assert deploy.public_origin(origin, "caddy") == origin
    with pytest.raises(ValueError):
        deploy.public_origin("https://home.example.com", "serve")
    for ambiguous in (ORIGIN + "\n", "\t" + ORIGIN, ORIGIN + "/"):
        with pytest.raises(ValueError):
            deploy.public_origin(ambiguous, "serve")
    saved = deploy.unit(origin, "https://home.household.ts.net", 8875)
    assert saved.count("--display-public-origin ") == 1
    assert "--display-public-origin " + origin in saved
    assert "--display-host 127.0.0.1 --display-port 8875" in saved
    assert "EnvironmentFile" not in saved


@pytest.mark.parametrize("origin", CUSTOM_ORIGINS)
def test_custom_ingress_accepts_only_raw_tcp_to_caddy_with_no_funnel(origin):
    raw = {"TCP": {"443": {"TCPForward": "127.0.0.1:443"}}}
    deploy.validate_serve(raw, origin, 8875, "caddy")
    # Unrelated Serve ports are not deleted or repurposed.
    raw["TCP"]["8443"] = {"TCPForward": "127.0.0.1:8443"}
    deploy.validate_serve(raw, origin, 8875, "caddy")
    for changed in (
        {},
        status(),
        {"TCP": {"443": {"TCPForward": "127.0.0.1:8875"}}},
        {"TCP": {"443": {"TCPForward": "0.0.0.0:443"}}},
        {"TCP": {"443": {"TCPForward": "127.0.0.1:443", "TerminateTLS": "host.ts.net"}}},
        {"TCP": {"443": {"TCPForward": "127.0.0.1:443", "ProxyProtocol": 2}}},
        {**raw, "AllowFunnel": {"display.household.ts.net:443": True}},
        {**raw, "Web": {"display.household.ts.net:443": {"Handlers": {"/": {}}}}},
    ):
        with pytest.raises(ValueError):
            deploy.validate_serve(changed, origin, 8875, "caddy")


@pytest.mark.parametrize("origin", CUSTOM_ORIGINS)
def test_live_caddy_gate_is_all_path_immediate_peer_then_exact_backend(origin):
    deploy.validate_caddy(caddy_servers(origin), urlsplit(origin).hostname, 8875)


@pytest.mark.parametrize("origin", CUSTOM_ORIGINS)
@pytest.mark.parametrize("mutation", [
    "no_gate", "gate_last", "client_ip", "lan_peer", "path_gate", "allow_response",
    "public_backend", "extra_proxy", "wrong_host", "non_terminal", "catch_all_first",
    "wildcard_first", "duplicate_site", "wrong_listener", "header_rewrite",
    "proxy_protocol",
])
def test_caddy_route_bypasses_fail_closed(mutation, origin):
    servers = caddy_servers(origin)
    server = servers["srv0"]
    route = server["routes"][0]
    rules = route["handle"][0]["routes"][0]["handle"][0]["routes"]
    if mutation == "no_gate":
        rules.pop(0)
    elif mutation == "gate_last":
        rules.reverse()
    elif mutation == "client_ip":
        rules[0]["match"][0]["not"][0] = {"client_ip": {"ranges": ["127.0.0.1", "::1"]}}
    elif mutation == "lan_peer":
        rules[0]["match"][0]["not"][0]["remote_ip"]["ranges"].append("192.168.0.0/24")
    elif mutation == "path_gate":
        rules[0]["match"][0]["path"] = ["/state"]
    elif mutation == "allow_response":
        rules[0]["handle"][0]["status_code"] = 200
    elif mutation == "public_backend":
        rules[1]["handle"][0]["upstreams"][0]["dial"] = "0.0.0.0:8875"
    elif mutation == "extra_proxy":
        server["routes"].append({"handle": [{"handler": "reverse_proxy", "upstreams": [{"dial": "localhost:8875"}]}]})
    elif mutation == "wrong_host":
        route["match"][0]["host"] = ["wrong.example.com"]
    elif mutation == "non_terminal":
        route["terminal"] = False
    elif mutation == "catch_all_first":
        server["routes"].insert(0, {"handle": [{"handler": "static_response", "status_code": 200}]})
    elif mutation == "wildcard_first":
        wildcard = "*." + urlsplit(origin).hostname.split(".", 1)[1]
        server["routes"].insert(0, {"match": [{"host": [wildcard]}], "handle": []})
    elif mutation == "duplicate_site":
        server["routes"].append(deepcopy(route))
    elif mutation == "wrong_listener":
        server["listen"] = ["192.168.0.4:443"]
    elif mutation == "header_rewrite":
        rules[1]["handle"][0]["headers"] = {"request": {"set": {"Origin": [origin]}}}
    elif mutation == "proxy_protocol":
        server["listener_wrappers"] = [{"wrapper": "proxy_protocol"}, {"wrapper": "tls"}]
    with pytest.raises(ValueError):
        deploy.validate_caddy(servers, urlsplit(origin).hostname, 8875)


def test_other_caddy_names_are_preserved_without_intercepting_named_host():
    servers = caddy_servers()
    original = deepcopy(servers["srv0"]["routes"][0])
    servers["srv0"]["routes"].insert(0, {
        "match": [{"host": ["portal.example.com"]}],
        "handle": [{"handler": "reverse_proxy", "upstreams": [{"dial": "127.0.0.1:3005"}]}],
    })
    servers["srv0"]["routes"].append({
        "match": [{"host": ["*.example.com"]}],
        "handle": [{"handler": "static_response", "status_code": 404}],
    })
    before = deepcopy(servers)
    deploy.validate_caddy(servers, "home.example.com", 8875)
    assert servers == before
    assert servers["srv0"]["routes"][1] == original


@pytest.mark.parametrize("origin", CUSTOM_ORIGINS)
def test_caddy_live_check_is_remote_and_does_not_retrieve_private_config(monkeypatch, origin):
    calls = []
    monkeypatch.setattr(deploy.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    ssh = ["ssh", *deploy.SSH_OPTIONS, "HOUSEHOLD_OPS"]
    deploy.check_caddy(ssh, origin, 8875)
    command, options = calls[0]
    assert command[0] == [*ssh, f"sudo python3 - {urlsplit(origin).hostname} 8875"]
    assert options["check"] is True
    assert "127.0.0.1:2019/config/apps/http/servers" in options["input"]
    assert "print(servers" not in options["input"]
    assert "StrictHostKeyChecking=yes" in command[0]
    assert "BatchMode=yes" in command[0]


@pytest.mark.parametrize("saved_origin,saved_home,saved_port,expected", [
    (ORIGIN, "https://home.household.ts.net", 8875, 0),
    ("https://home.example.com", "https://home.household.ts.net", 8875, 1),
    (ORIGIN, "https://other.household.ts.net", 8875, 1),
    (ORIGIN, "https://home.household.ts.net", 8876, 1),
])
def test_rollback_compares_saved_unit_before_any_activation(tmp_path, saved_origin, saved_home, saved_port, expected):
    (tmp_path / "unit.service").write_text(deploy.unit(saved_origin, saved_home, saved_port))
    guard = next(line for line in deploy.REMOTE.splitlines() if "sudo cmp -s" in line)
    script = "sudo() { \"$@\"; }\n" + "target=" + shlex.quote(str(tmp_path)) + "\n"
    script += "expected_unit=" + shlex.quote(deploy.unit(ORIGIN, "https://home.household.ts.net", 8875)) + "\n"
    result = subprocess.run(["bash"], input=script + guard, text=True, capture_output=True)
    assert result.returncode == expected
    assert deploy.REMOTE.index(guard) < deploy.REMOTE.index('sudo install -m 0644 "$target/unit.service"')


def test_rollback_cli_uses_restored_https_ingress_and_saved_exact_unit(monkeypatch):
    import json

    calls = []
    monkeypatch.setattr(deploy.subprocess, "check_output", lambda *args, **kwargs: json.dumps(status()))
    monkeypatch.setattr(deploy.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    async def smoke(origin, **kwargs):
        assert origin == ORIGIN
        assert kwargs == {"home": True}

    monkeypatch.setattr(deploy, "run_check", smoke)
    assert deploy.main(["rollback", "--ops-host", "ops", "--origin", ORIGIN,
                        "--home", "https://home.household.ts.net"]) == 0
    command, options = calls[0]
    assert "StrictHostKeyChecking=yes" in command[0]
    remote_args = shlex.split(command[0][-1])
    assert remote_args[:4] == ["bash", "-s", "--", "rollback"]
    assert remote_args[-1] == deploy.unit(ORIGIN, "https://home.household.ts.net", 8875)
    assert options["input"] == deploy.REMOTE


def test_named_cli_rejects_an_older_release_helper_before_build_or_install(monkeypatch, tmp_path):
    import json
    import tarfile

    calls = []

    def output(command, **kwargs):
        if command[0] == "ssh":
            return json.dumps({"TCP": {"443": {"TCPForward": "127.0.0.1:443"}}})
        return "a" * 40

    def run(command, **kwargs):
        calls.append(command)
        assert command[:2] == ["git", "archive"], "older release must not be built, uploaded or activated"
        archive_path = next(part.removeprefix("--output=") for part in command if part.startswith("--output="))
        admission = tmp_path / "home_admission.py"
        admission.write_text("# Existing Home contract\n")
        helper = tmp_path / "deploy_home_browser.py"
        helper.write_text("# Older helper without named-ingress support\n")
        with tarfile.open(archive_path, "w") as archive:
            archive.add(admission, arcname="home_display/home_admission.py")
            archive.add(helper, arcname="scripts/deploy_home_browser.py")

    monkeypatch.setattr(deploy.subprocess, "check_output", output)
    monkeypatch.setattr(deploy.subprocess, "run", run)
    monkeypatch.setattr(deploy, "check_caddy", lambda *args: None)
    assert deploy.main(["deploy", "--ops-host", "ops", "--ingress", "caddy",
                        "--origin", "https://home.example.com", "--home", "https://home.household.ts.net",
                        "--tag", "v0.12.0"]) == 1
    assert len(calls) == 1


def test_invalid_live_named_ingress_never_activates_or_builds(monkeypatch):
    import json

    monkeypatch.setattr(deploy.subprocess, "check_output", lambda *args, **kwargs: json.dumps(status()))
    monkeypatch.setattr(deploy.subprocess, "run", lambda *args, **kwargs: pytest.fail("no build/upload/activation allowed"))
    assert deploy.main(["deploy", "--ops-host", "ops", "--ingress", "caddy",
                        "--origin", "https://home.example.com", "--home", "https://home.household.ts.net",
                        "--tag", "v1.0.0"]) == 1


@pytest.mark.parametrize("funnel", [{}, {"ops.household.ts.net:443": False}])
def test_explicit_disabled_funnel_matches_omitted_empty_map(funnel):
    raw = {"TCP": {"443": {"TCPForward": "127.0.0.1:443"}}, "AllowFunnel": funnel}
    deploy.validate_serve(raw, "https://home.example.com", 8875, "caddy")


@pytest.mark.parametrize("funnel", [None, [], False, {"host:443": None}, {"host:443": 0}, {"host:443": True}])
def test_malformed_or_enabled_funnel_is_rejected(funnel):
    raw = {"TCP": {"443": {"TCPForward": "127.0.0.1:443"}}, "AllowFunnel": funnel}
    with pytest.raises(ValueError):
        deploy.validate_serve(raw, "https://home.example.com", 8875, "caddy")


@pytest.mark.parametrize("foreground", [
    {"AllowFunnel": {"host:8443": True}},
    {"TCP": {"443": {"HTTPS": True}}},
    {"Web": {"host:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8875"}}}}},
    {"Foreground": {"nested": {"AllowFunnel": {"host:443": True}}}},
])
def test_foreground_funnel_or_ingress_override_is_rejected(foreground):
    raw = {"TCP": {"443": {"TCPForward": "127.0.0.1:443"}}, "Foreground": {"session": foreground}}
    with pytest.raises(ValueError):
        deploy.validate_serve(raw, "https://home.example.com", 8875, "caddy")


def test_named_nonstandard_backend_is_rejected_before_any_host_contact(monkeypatch):
    monkeypatch.setattr(deploy.subprocess, "check_output", lambda *args, **kwargs: pytest.fail("no SSH allowed"))
    assert deploy.main(["deploy", "--ops-host", "ops", "--ingress", "caddy",
                        "--origin", "https://home.example.com", "--home", "https://home.household.ts.net",
                        "--tag", "v1.0.0", "--port", "8876"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("ingress,origin", [
    ("serve", ORIGIN),
    ("serve", ORIGIN + ":443"),
    *[("caddy", origin) for origin in CUSTOM_ORIGINS],
])
async def test_deployer_origins_start_the_real_home_appliance_and_display(tmp_path, ingress, origin):
    import asyncio
    import json
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    from home_display.appliance import Appliance, build_arg_parser

    accepted = deploy.public_origin(origin, ingress)
    saved_unit = deploy.unit(accepted, "https://home.household.ts.net", 8875)
    command = next(line.removeprefix("ExecStart=") for line in saved_unit.splitlines() if line.startswith("ExecStart="))
    args = build_arg_parser([]).parse_args(shlex.split(command)[1:])
    assert args.display_public_origin == accepted
    assert args.display_host == "127.0.0.1"
    assert args.display_port == 8875
    # Exercise the actual startup path, not a replacement validator or fake
    # DisplayServer. Only the test's listener/storage locations are isolated.
    args.display_port = 0
    args.home_device_credential_file = tmp_path / "pairing.json"
    relay = Appliance(args)
    relay._build()
    server = relay._server
    info = await server.start()
    try:
        assert server._origin_is_allowed(accepted)
        if accepted.endswith(":443"):
            assert server._origin_is_allowed(accepted.removesuffix(":443"))
        assert not server._origin_is_allowed("https://unrelated.example")
        other_public_origin = "https://different.example.com"
        assert not server._origin_is_allowed(other_public_origin)

        def request_error(path, supplied_origin, *, post=False):
            request = Request(
                info.http_url.rstrip("/") + path,
                data=b"" if post else None,
                headers={"Origin": supplied_origin},
            )
            with pytest.raises(HTTPError) as error:
                urlopen(request, timeout=5)
            return error.value.code, json.loads(error.value.read()) if error.value.code != 403 else None

        status, payload = await asyncio.to_thread(request_error, "/action", accepted, post=True)
        assert status == 400
        assert isinstance(payload["error"], str)
        status, _ = await asyncio.to_thread(request_error, "/action", other_public_origin, post=True)
        assert status == 403
        # No Home is enrolled/contacted in this test. Health remains honestly
        # degraded, not Origin-rejected or falsely reported healthy.
        status, payload = await asyncio.to_thread(request_error, "/healthz", accepted)
        assert status == 503
        assert payload["status"] == "degraded"
    finally:
        await server.close()


@pytest.mark.parametrize("origin", [
    "https://-display.household.ts.net",
    "https://display-.household.ts.net",
    "https://display.house_hold.ts.net",
    "https://display..ts.net",
    "https://display.household.ts.net.",
    "https://display.household.ts.net:0443",
])
def test_serve_and_home_origins_reject_invalid_dns_and_port_syntax(origin):
    with pytest.raises(ValueError):
        deploy.tailnet_origin(origin)
    with pytest.raises(ValueError):
        deploy.public_origin(origin, "serve")
