#!/usr/bin/env python3
"""Smoke-test the public HOME display through its Caddy origin."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from websockets.asyncio.client import connect


DEFAULT_ORIGIN = "https://hermes-home.chappell-home.dev"
DEFAULT_TIMEOUT = 10.0
EXPECTED_STATES = {
    "idle",
    "heard",
    "listening",
    "thinking",
    "speaking",
    "buffering",
    "error",
    "disconnected",
    "prompt",
}
EXPECTED_ACTION_ERROR = b'"error": "action_id and choice are required"'
EXPECTED_PAGE_MARKERS = (b"<title>Hermes Home Display</title>", b'id="app"')


class CheckError(RuntimeError):
    """A public deployment check failed in an expected, reportable way."""


def origin_urls(value: str) -> tuple[str, str, str]:
    """Return the canonical origin, page URL, and state WebSocket URL."""
    parsed = urlsplit(value)
    if any(char.isspace() for char in value):
        raise ValueError("URL must not contain whitespace")
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("URL must be an http(s) origin without credentials or a path")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("URL has an invalid port") from error
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("URL has an invalid port")

    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    page_url = f"{origin}/"
    websocket_scheme = "wss" if parsed.scheme == "https" else "ws"
    websocket_url = urlunsplit((websocket_scheme, parsed.netloc, "/state", "", ""))
    return origin, page_url, websocket_url


def _tls_context(*, ca_file: Path | None, insecure: bool) -> ssl.SSLContext | None:
    if ca_file is None and not insecure:
        return None
    context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
    if insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def check_page(
    page_url: str,
    *,
    origin: str,
    timeout: float,
    tls_context: ssl.SSLContext | None = None,
) -> None:
    request = Request(page_url, headers={"Accept": "text/html", "Origin": origin})
    try:
        with urlopen(request, timeout=timeout, context=tls_context) as response:
            if response.status != 200:
                raise CheckError(f"static page returned HTTP {response.status}")
            if response.geturl() != page_url:
                raise CheckError("static page redirected away from the configured origin")
            body = response.read()
            if not all(marker in body for marker in EXPECTED_PAGE_MARKERS):
                raise CheckError("static page is not the Hermes Home display")
    except HTTPError as error:
        raise CheckError(f"static page returned HTTP {error.code}") from error


def check_action_route(
    origin: str,
    *,
    timeout: float,
    tls_context: ssl.SSLContext | None = None,
) -> None:
    """Reach /action without sending a valid household action payload."""
    request = Request(
        f"{origin}/action",
        data=b"",
        method="POST",
        headers={"Origin": origin},
    )
    try:
        with urlopen(request, timeout=timeout, context=tls_context) as response:
            if response.geturl() != f"{origin}/action":
                raise CheckError("/action redirected away from the configured origin")
            raise CheckError(
                f"/action unexpectedly returned HTTP {response.status} for a malformed payload"
            )
    except HTTPError as error:
        if error.code != 400:
            raise CheckError(f"/action returned HTTP {error.code}, expected 400") from error
        if EXPECTED_ACTION_ERROR not in error.read():
            raise CheckError("/action returned an unexpected malformed-payload response")


async def check_state_channel(
    websocket_url: str,
    *,
    origin: str,
    timeout: float,
    tls_context: ssl.SSLContext | None,
) -> None:
    connect_kwargs = {
        "origin": origin,
        "open_timeout": timeout,
        "close_timeout": timeout,
    }
    if tls_context is not None:
        connect_kwargs["ssl"] = tls_context
    try:
        async with connect(websocket_url, **connect_kwargs) as websocket:
            frame = await asyncio.wait_for(websocket.recv(), timeout=timeout)
    except Exception as error:
        raise CheckError(f"/state WebSocket check failed: {type(error).__name__}") from error

    try:
        payload = json.loads(frame)
    except (TypeError, ValueError) as error:
        raise CheckError("/state returned a non-JSON initial snapshot") from error
    if (
        not isinstance(payload, dict)
        or payload.get("type") != "snapshot"
        or payload.get("schema") != 1
        or not isinstance(payload.get("sequence"), int)
        or payload.get("sequence", -1) < 0
        or payload.get("state") not in EXPECTED_STATES
    ):
        raise CheckError("/state returned an invalid initial snapshot")


async def run_check(
    origin_url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    ca_file: Path | None = None,
    insecure: bool = False,
) -> None:
    origin, page_url, websocket_url = origin_urls(origin_url)
    tls_context = _tls_context(ca_file=ca_file, insecure=insecure)
    check_page(page_url, origin=origin, timeout=timeout, tls_context=tls_context)
    check_action_route(origin, timeout=timeout, tls_context=tls_context)
    await check_state_channel(
        websocket_url,
        origin=origin,
        timeout=timeout,
        tls_context=_tls_context(ca_file=ca_file, insecure=insecure),
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check the public HOME display page, action route, and state WebSocket."
    )
    parser.add_argument("--origin", default=DEFAULT_ORIGIN, help="public display origin")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--ca-file", type=Path, help="CA bundle for an internal HTTPS certificate")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="disable HTTPS certificate verification for a deliberate local check",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        print("timeout must be positive", file=sys.stderr)
        return 2
    try:
        asyncio.run(
            run_check(
                args.origin,
                timeout=args.timeout,
                ca_file=args.ca_file,
                insecure=args.insecure,
            )
        )
    except (CheckError, OSError, ValueError) as error:
        print(f"ops web check failed: {error}", file=sys.stderr)
        return 1
    print(f"ops web check passed: {args.origin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
