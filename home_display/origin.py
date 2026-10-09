"""Operator-configured HTTPS Origin syntax shared by Home startup and deployment."""
from __future__ import annotations

import re

_HTTPS_ORIGIN = re.compile(
    r"https://(?P<host>[a-z0-9.-]+)(?::(?P<port>[1-9][0-9]{0,4}))?"
)
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_NUMERIC_LABEL = re.compile(r"(?:[0-9]+|0x[0-9a-f]*)")


def validate_public_origin(value: str, *, allow_tailnet_port: bool = True) -> str:
    """Require one unambiguous DNS origin; this is not network authorization.

    Explicit 443 is equivalent to the default HTTPS port. Existing tailnet
    runtime configurations may use another port; Caddy deployment may not.
    """
    match = _HTTPS_ORIGIN.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError(
            "public Origin must be one exact lowercase HTTPS DNS origin "
            "without credentials, path, query or fragment"
        )
    host = match.group("host")
    labels = host.split(".")
    # Browsers interpret numeric/hex final labels as IPv4 addresses, including
    # abbreviated, integer and octal forms; never accept those as DNS names.
    if (
        len(host) > 253
        or any(_DNS_LABEL.fullmatch(label) is None for label in labels)
        or _NUMERIC_LABEL.fullmatch(labels[-1])
    ):
        raise ValueError(
            "public Origin must use a DNS hostname, not an IP address, "
            "wildcard or ambiguous hostname"
        )
    port = int(match.group("port") or "443")
    if port > 65535 or (
        port != 443 and not (allow_tailnet_port and host.endswith(".ts.net"))
    ):
        raise ValueError(
            "public Origin requires the default HTTPS port "
            "except for existing tailnet runtime origins"
        )
    return value
