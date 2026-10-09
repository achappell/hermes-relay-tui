"""Shared browser-origin syntax contract, independent of deployment topology."""
from __future__ import annotations

import pytest

from home_display.origin import validate_public_origin


@pytest.mark.parametrize("origin", [
    "https://example.com",
    "https://display",
    "https://home.example.com",
    "https://other.example.com:443",
    "https://display.deep.example.com",
    "https://node-2.example.com",
    "https://123.example.com",
    "https://display.household.ts.net",
    "https://display.household.ts.net:443",
    "https://" + "a" * 63 + ".example.com",
])
@pytest.mark.parametrize("allow_tailnet_port", [False, True])
def test_operator_dns_origins_are_preserved_exactly(origin, allow_tailnet_port):
    assert validate_public_origin(origin, allow_tailnet_port=allow_tailnet_port) == origin


@pytest.mark.parametrize("port", [1, 8443, 65535])
def test_runtime_preserves_valid_tailnet_ports_but_caddy_requires_https_port(port):
    origin = f"https://display.household.ts.net:{port}"
    assert validate_public_origin(origin) == origin
    with pytest.raises(ValueError):
        validate_public_origin(origin, allow_tailnet_port=False)


@pytest.mark.parametrize("origin", [
    "",
    "http://home.example.com",
    "wss://home.example.com",
    "HTTPS://home.example.com",
    "https://HOME.example.com",
    "https://home.example.com.",
    "https://home.example.com/",
    "https://home.example.com/state",
    "https://home.example.com?x=1",
    "https://home.example.com?",
    "https://home.example.com#x",
    "https://home.example.com#",
    "https://user@home.example.com",
    "https://user:password@home.example.com",
    "https://@home.example.com",
    "https://home.example.com\\state",
    "https://home.example.com\n",
    " https://home.example.com",
    "https://home.\texample.com",
    "https://home.example.com https://other.example.com",
    "https://home.example.com,https://other.example.com",
    "https://*.example.com",
    "https://*.household.ts.net",
    "https://127.0.0.1",
    "https://127.0.0.1:443",
    "https://[::1]",
    "https://[::ffff:127.0.0.1]",
    "https://127.1",
    "https://127.0.1",
    "https://2130706433",
    "https://0177.0.0.1",
    "https://017700000001",
    "https://0x7f000001",
    "https://0x7f.0.0.1",
    "https://0x7f.1",
    "https://0x",
    "https://home.0x",
    "https://example.123",
    "https://example.0x123",
    "https://home.example.com:",
    "https://home.example.com:0",
    "https://home.example.com:0443",
    "https://home.example.com:+443",
    "https://home.example.com:-443",
    "https://home.example.com:443.0",
    "https://home.example.com:abc",
    "https://home.example.com:65536",
    "https://home.example.com:8443",
    "https://display.household.ts.net:0",
    "https://display.household.ts.net:08443",
    "https://display.household.ts.net:65536",
    "https://ts.net:8443",
    "https://display.household.ts.net.example.com:8443",
    "https://display.householdts.net:8443",
    "https://display.household.ts.net.:8443",
    "https://-home.example.com",
    "https://home-.example.com",
    "https://home_display.example.com",
    "https://home..example.com",
    "https://.example.com",
    "https://hôme.example.com",
    "https://%68ome.example.com",
    "https://" + "a" * 64 + ".example.com",
    "https://" + ".".join(["a" * 63] * 4),
])
@pytest.mark.parametrize("allow_tailnet_port", [False, True])
def test_invalid_or_ambiguous_origins_fail_closed(origin, allow_tailnet_port):
    with pytest.raises(ValueError):
        validate_public_origin(origin, allow_tailnet_port=allow_tailnet_port)
