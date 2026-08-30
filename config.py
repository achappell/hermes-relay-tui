"""Environment/argument resolution for the Hermes streaming TUI.

Ported from hermes-hybrid-tui.py's config/argparse setup, unchanged in
behavior — only relocated so config concerns don't live in the same
file as protocol or UI code.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Optional

from diagnostics import configure_logging

DEFAULT_URL = "ws://localhost:8792/voice-session"
DEFAULT_CHECKOUT = Path.home() / ".hermes" / "hermes-agent"
DEFAULT_PROFILE_ENV = Path.home() / ".hermes" / "profiles" / "amanda" / ".env"
DEFAULT_CONFIG_PATH = Path.home() / ".hermes-relay-tui" / "config.yaml"
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


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _device_selector(value: Optional[str | int]) -> int | str | None:
    """Convert a device name or numeric index from configuration.

    Accepts a bare ``int`` too — a YAML config can write ``mic_input_device: 2``
    directly rather than a quoted string.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    normalized = value.strip()
    if not normalized or normalized.lower() == "default":
        return None
    try:
        return int(normalized)
    except ValueError:
        return normalized


def _config_path_from_argv(argv: Optional[list[str]]) -> Path:
    """Find --config's value without building the full parser yet.

    Needed because YAML values become argparse *defaults*, so the config
    file has to be located and loaded before the real parser is built.
    """
    items = list(sys.argv[1:] if argv is None else argv)
    for index, item in enumerate(items):
        if item == "--config" and index + 1 < len(items):
            return Path(items[index + 1])
        if item.startswith("--config="):
            return Path(item.split("=", 1)[1])
    env_value = os.getenv("HERMES_RELAY_TUI_CONFIG")
    if env_value:
        return Path(env_value)
    return DEFAULT_CONFIG_PATH


def load_config_file(path: Optional[Path]) -> dict[str, Any]:
    """Load YAML settings used as argparse defaults.

    CLI flags and environment variables still win over these — see
    ``build_arg_parser``'s precedence for each option: CLI flag > env var >
    config file > built-in default.
    """
    if path is None or not path.exists():
        return {}
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SystemExit(f"error: could not read config file {path}: {exc}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SystemExit(f"error: config file {path} must contain a mapping of settings")
    return data


def ensure_default_config_file(path: Path) -> bool:
    """Create ``path`` from the bundled example config if it doesn't exist.

    The example file is entirely comments — no active keys — so writing it
    out changes nothing about how args resolve; it just gives a first-time
    user a real, discoverable file to edit before their first ``/reload``
    instead of a silent absence. A no-op when the file already exists, or
    when the example template isn't present alongside this module (e.g. a
    packaged install that doesn't ship it — see DIST-01/DIST-02).
    """
    if path.exists():
        return False
    template = Path(__file__).parent / "config.example.yaml"
    if not template.exists():
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        return False
    return True


def _cfg_str(cfg: dict[str, Any], key: str, hardcoded: Optional[str] = None) -> Optional[str]:
    value = cfg.get(key)
    return str(value) if value is not None else hardcoded


def _cfg_path(cfg: dict[str, Any], key: str, hardcoded: Optional[Path] = None) -> Optional[Path]:
    value = cfg.get(key)
    return Path(value) if value else hardcoded


def _cfg_bool(cfg: dict[str, Any], key: str, hardcoded: bool = False) -> bool:
    value = cfg.get(key)
    return bool(value) if value is not None else hardcoded


def _cfg_choice(cfg: dict[str, Any], key: str, choices: tuple[str, ...], hardcoded: str) -> str:
    value = cfg.get(key)
    if isinstance(value, str) and value.strip().lower() in choices:
        return value.strip().lower()
    return hardcoded


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


def build_arg_parser(argv: Optional[list[str]] = None) -> argparse.ArgumentParser:
    """Build the CLI parser, layering defaults as CLI flag > env var > YAML config > built-in.

    ``argv`` only affects finding ``--config`` before the full parser exists;
    the returned parser still needs ``parse_args(argv)`` called on it as usual.
    """
    config_path = _config_path_from_argv(argv)
    cfg = load_config_file(config_path)

    parser = argparse.ArgumentParser(description="Hermes streaming TUI")
    parser.add_argument(
        "--config",
        type=Path,
        default=config_path,
        help=f"YAML config file for defaults (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--url", default=os.getenv("HERMES_VOICE_SESSION_URL", _cfg_str(cfg, "url", DEFAULT_URL))
    )
    parser.add_argument(
        "--token",
        default=_cfg_str(cfg, "token"),
        help="Bearer token; prefer VOICE_SESSION_TOKEN or the profile .env",
    )
    parser.add_argument("--profile-env", type=Path, default=_cfg_path(cfg, "profile_env", DEFAULT_PROFILE_ENV))
    parser.add_argument("--checkout", type=Path, default=_cfg_path(cfg, "checkout", DEFAULT_CHECKOUT))
    parser.add_argument(
        "--client-id",
        default=os.getenv("VOICE_SESSION_CLIENT_ID", _cfg_str(cfg, "client_id", "amanda-laptop")),
    )
    parser.add_argument(
        "--device-id",
        default=os.getenv("VOICE_SESSION_DEVICE_ID", _cfg_str(cfg, "device_id", "amanda-mac")),
    )
    parser.add_argument(
        "--session-id", default=os.getenv("VOICE_SESSION_ID", _cfg_str(cfg, "session_id", "hybrid-tui"))
    )
    parser.add_argument("--display-name", default=_cfg_str(cfg, "display_name", "Amanda streaming TUI"))
    parser.add_argument(
        "--no-play",
        action="store_true",
        default=_cfg_bool(cfg, "no_play"),
        help="buffer audio instead of opening the local speaker",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_cfg_path(cfg, "output"),
        help="also save each response WAV (later turns get a suffix)",
    )
    parser.add_argument(
        "--mic-max-seconds",
        type=float,
        default=_env_float("VOICE_SESSION_MIC_MAX_SECONDS", cfg.get("mic_max_seconds", 15.0)),
    )
    parser.add_argument(
        "--mic-silence-duration",
        type=float,
        default=_env_float("VOICE_SESSION_MIC_SILENCE_DURATION", cfg.get("mic_silence_duration", 3.0)),
    )
    parser.add_argument(
        "--mic-silence-threshold",
        type=int,
        default=_env_int("VOICE_SESSION_MIC_SILENCE_THRESHOLD", cfg.get("mic_silence_threshold", 200)),
    )
    parser.add_argument(
        "--mic-input-device",
        type=_device_selector,
        default=_device_selector(
            os.getenv("VOICE_SESSION_MIC_INPUT_DEVICE", cfg.get("mic_input_device"))
        ),
        help="microphone device name or index (default: system default)",
    )
    parser.add_argument(
        "--audio-output-device",
        type=_device_selector,
        default=_device_selector(
            os.getenv("VOICE_SESSION_AUDIO_OUTPUT_DEVICE", cfg.get("audio_output_device"))
        ),
        help="speaker device name or index (default: system default)",
    )
    parser.add_argument(
        "--stt-model", default=os.getenv("VOICE_SESSION_STT_MODEL") or _cfg_str(cfg, "stt_model")
    )
    parser.add_argument(
        "--model",
        default=os.getenv("VOICE_SESSION_MODEL") or _cfg_str(cfg, "model"),
        help="model shown as the session's active model (relay-confirmed changes are not yet supported)",
    )
    parser.add_argument(
        "--history-path",
        type=Path,
        default=_cfg_path(cfg, "history_path"),
        help=(
            "prompt-history file path (default: scoped to --url's host under "
            "~/.hermes-relay-tui/history/, so different Hermes backends "
            "don't share one file; this is client-only state, not part of "
            "the Hermes install)"
        ),
    )
    parser.add_argument(
        "--busy-mode",
        choices=BUSY_MODES,
        default=_env_choice("VOICE_SESSION_BUSY_MODE", BUSY_MODES, _cfg_choice(cfg, "busy_mode", BUSY_MODES, "queue")),
        help="what an ordinary message does while a turn is active",
    )
    parser.add_argument(
        "--hide-thinking",
        action="store_true",
        default=_cfg_bool(cfg, "hide_thinking"),
        help="hide thinking and tool detail in the transcript",
    )
    parser.add_argument(
        "--allow-shell",
        action="store_true",
        default=_env_bool("HERMES_RELAY_TUI_ALLOW_SHELL", _cfg_bool(cfg, "allow_shell")),
        help="allow bounded local !command execution and {!command} interpolation",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=_env_bool("HERMES_RELAY_TUI_DEBUG", _cfg_bool(cfg, "debug")),
        help="write a content-safe protocol trace for live-session debugging",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path(os.environ["HERMES_RELAY_TUI_LOG_FILE"])
        if os.getenv("HERMES_RELAY_TUI_LOG_FILE")
        else _cfg_path(cfg, "log_file"),
        help="debug trace path; implies --debug when supplied",
    )
    parser.add_argument(
        "--turn-timeout",
        type=float,
        default=_env_float("VOICE_SESSION_TURN_TIMEOUT", cfg.get("turn_timeout", 195.0)),
        help="seconds to wait for a response before closing the session (0 disables)",
    )
    parser.add_argument(
        "--connect-retries",
        type=int,
        default=_env_int("VOICE_SESSION_CONNECT_RETRIES", cfg.get("connect_retries", 3)),
        help="additional connection attempts after the first failure",
    )
    parser.add_argument(
        "--connect-retry-delay",
        type=float,
        default=_env_float("VOICE_SESSION_CONNECT_RETRY_DELAY", cfg.get("connect_retry_delay", 1.0)),
        help="base seconds before reconnect attempts; delay doubles each time",
    )
    return parser


__all__ = [
    "BUSY_MODES",
    "DEFAULT_CHECKOUT",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_PROFILE_ENV",
    "DEFAULT_URL",
    "_connection_kwargs",
    "_env_bool",
    "_env_choice",
    "_env_float",
    "_env_int",
    "_resolve_token",
    "build_arg_parser",
    "configure_logging",
    "connect_factory",
    "ensure_default_config_file",
    "load_config_file",
]
