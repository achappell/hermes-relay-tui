"""Environment/argument resolution for the Hermes streaming TUI.

Ported from hermes-hybrid-tui.py's config/argparse setup, unchanged in
behavior — only relocated so config concerns don't live in the same
file as protocol or UI code.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Optional

DEFAULT_URL = "ws://100.90.186.57:8792/voice-session"
DEFAULT_CHECKOUT = Path.home() / ".hermes" / "hermes-agent"
DEFAULT_PROFILE_ENV = Path.home() / ".hermes" / "profiles" / "amanda" / ".env"
BUSY_MODES = ("queue", "steer", "interrupt")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_choice(name: str, choices: tuple[str, ...], default: str) -> str:
    value = os.getenv(name, default).strip().lower()
    return value if value in choices else default


def _resolve_token(explicit: Optional[str], env_path: Path) -> str:
    if explicit:
        return explicit
    from_environment = os.getenv("VOICE_SESSION_TOKEN", "").strip()
    if from_environment:
        return from_environment
    if not env_path.exists():
        return ""
    try:
        from dotenv import dotenv_values

        value = dotenv_values(env_path).get("VOICE_SESSION_TOKEN")
        return str(value).strip() if value else ""
    except ImportError:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line.startswith("VOICE_SESSION_TOKEN="):
                continue
            value = line.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            return value
    except OSError:
        return ""
    return ""


def connect_factory():
    try:
        from websockets.asyncio.client import connect
    except ImportError:
        from websockets import connect  # type: ignore[no-redef]
    return connect


def _connection_kwargs(connect: Any, token: str) -> dict[str, Any]:
    import inspect

    headers = {"Authorization": f"Bearer {token}"}
    try:
        params = inspect.signature(connect).parameters
    except (TypeError, ValueError):
        params = {}
    header_name = "additional_headers" if "additional_headers" in params else "extra_headers"
    return {header_name: headers, "max_size": 256 * 1024}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes streaming TUI")
    parser.add_argument("--url", default=os.getenv("HERMES_VOICE_SESSION_URL", DEFAULT_URL))
    parser.add_argument("--token", help="Bearer token; prefer VOICE_SESSION_TOKEN or the profile .env")
    parser.add_argument("--profile-env", type=Path, default=DEFAULT_PROFILE_ENV)
    parser.add_argument("--checkout", type=Path, default=DEFAULT_CHECKOUT)
    parser.add_argument("--client-id", default=os.getenv("VOICE_SESSION_CLIENT_ID", "amanda-laptop"))
    parser.add_argument("--device-id", default=os.getenv("VOICE_SESSION_DEVICE_ID", "amanda-mac"))
    parser.add_argument("--session-id", default=os.getenv("VOICE_SESSION_ID", "hybrid-tui"))
    parser.add_argument("--display-name", default="Amanda streaming TUI")
    parser.add_argument("--no-play", action="store_true", help="buffer audio instead of opening the local speaker")
    parser.add_argument("--output", type=Path, help="also save each response WAV (later turns get a suffix)")
    parser.add_argument("--mic-max-seconds", type=float, default=_env_float("VOICE_SESSION_MIC_MAX_SECONDS", 15.0))
    parser.add_argument("--mic-silence-duration", type=float, default=_env_float("VOICE_SESSION_MIC_SILENCE_DURATION", 3.0))
    parser.add_argument("--mic-silence-threshold", type=int, default=_env_int("VOICE_SESSION_MIC_SILENCE_THRESHOLD", 200))
    parser.add_argument("--stt-model", default=os.getenv("VOICE_SESSION_STT_MODEL") or None)
    parser.add_argument(
        "--busy-mode",
        choices=BUSY_MODES,
        default=_env_choice("VOICE_SESSION_BUSY_MODE", BUSY_MODES, "queue"),
        help="what an ordinary message does while a turn is active",
    )
    parser.add_argument(
        "--turn-timeout",
        type=float,
        default=_env_float("VOICE_SESSION_TURN_TIMEOUT", 195.0),
        help="seconds to wait for a response before closing the session (0 disables)",
    )
    return parser
