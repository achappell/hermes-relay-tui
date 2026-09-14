#!/usr/bin/env python3
"""Validate the non-secret Ops profile catalog and filter its token env file."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


EXPECTED_PROFILES = {
    "amanda": ("Amanda", "hey missy", "VOICE_SESSION_TOKEN_AMANDA"),
    "jensen": ("Jensen", "hey skippy", "VOICE_SESSION_TOKEN_JENSEN"),
    "spark": ("Spark", "hey spark", "VOICE_SESSION_TOKEN_SPARK"),
}
ALLOWED_TOKEN_ENV = tuple(item[2] for item in EXPECTED_PROFILES.values())
ENV_ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
ALLOWED_CATALOG_KEYS = {
    "version",
    "profiles",
}
ALLOWED_PROFILE_KEYS = {
    "display_name",
    "wake_phrases",
    "url",
    "token_env",
    "client_id",
    "device_id",
    "session_id",
    "model",
}


def _read_catalog(path: Path) -> dict[str, Any]:
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ValueError("catalog could not be read") from error
    if not isinstance(data, dict) or set(data) - ALLOWED_CATALOG_KEYS:
        raise ValueError("catalog must contain only supported non-secret fields")
    if type(data.get("version")) is not int or data.get("version") != 1:
        raise ValueError("catalog version must be 1")
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != set(EXPECTED_PROFILES):
        raise ValueError("catalog must contain the three required profiles")

    for name, (display_name, wake_phrase, token_env) in EXPECTED_PROFILES.items():
        entry = profiles.get(name)
        if not isinstance(entry, dict) or set(entry) - ALLOWED_PROFILE_KEYS:
            raise ValueError("catalog contains an unsupported profile field")
        if entry.get("display_name") != display_name:
            raise ValueError("catalog display names do not match the profile contract")
        if entry.get("wake_phrases") != [wake_phrase]:
            raise ValueError("catalog wake phrases do not match the profile contract")
        if entry.get("token_env") != token_env:
            raise ValueError("catalog token sources do not match the profile contract")
        for key in ("url", "client_id", "device_id", "session_id"):
            value = entry.get(key)
            if not isinstance(value, str) or not value.strip() or any(
                char.isspace() for char in value
            ):
                raise ValueError("catalog contains an invalid connection field")
        endpoint = entry["url"]
        parsed = urlsplit(endpoint)
        if parsed.scheme != "wss" or not parsed.hostname:
            raise ValueError("catalog endpoints must be valid wss URLs")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("catalog endpoints must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("catalog endpoints must not contain query or fragment data")
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError("catalog endpoints must use a valid port") from error
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("catalog endpoints must use a valid port")
    return data


def _read_token_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as error:
        raise ValueError("token environment file could not be read") from error
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = ENV_ASSIGNMENT.match(stripped)
        if match is None:
            continue
        key, value = match.groups()
        if key not in ALLOWED_TOKEN_ENV:
            continue
        if key in values or not value.strip() or "\x00" in value:
            raise ValueError("token environment file is missing a required value")
        values[key] = value.strip()
    missing = [key for key in ALLOWED_TOKEN_ENV if key not in values]
    if missing:
        raise ValueError("token environment file is missing a required profile token")
    return values


def _write_filtered_env(path: Path, values: dict[str, str]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(f"{key}={values[key]}\n" for key in ALLOWED_TOKEN_ENV),
            encoding="utf-8",
        )
        os.chmod(path, 0o600)
    except Exception as error:
        raise ValueError("filtered token environment file could not be written") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--write-env", type=Path)
    args = parser.parse_args()
    try:
        _read_catalog(args.catalog)
        values = _read_token_values(args.env_file)
        if args.write_env is not None:
            if args.write_env.resolve() == args.env_file.resolve():
                raise ValueError("filtered token environment must be a separate file")
            _write_filtered_env(args.write_env, values)
    except ValueError as error:
        print(f"ops profile validation failed: {error}", file=sys.stderr)
        return 1
    print("ops profile catalog and token source validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
