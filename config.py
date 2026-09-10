"""Environment/argument resolution for the Hermes streaming TUI.

Ported from hermes-hybrid-tui.py's config/argparse setup, unchanged in
behavior — only relocated so config concerns don't live in the same
file as protocol or UI code.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import re
import socket
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Optional

from diagnostics import configure_logging

DEFAULT_URL = "ws://localhost:8792/voice-session"
DEFAULT_PROFILE_ENV = Path.home() / ".hermes-relay-tui" / ".env"
LEGACY_PROFILE_ENV = Path.home() / ".hermes" / "profiles" / "amanda" / ".env"
DEFAULT_CONFIG_PATH = Path.home() / ".hermes-relay-tui" / "config.yaml"
BUSY_MODES = ("queue", "steer", "interrupt")
WAKE_ENGINES = ("openwakeword", "sherpa")


def default_device_id() -> str:
    """Derive a stable device ID from the machine's hostname.

    device_id is never checked against the server allowlist (client_id is)
    — it only scopes session state per machine — so deriving it removes a
    setup question without weakening anything.
    """
    return socket.gethostname().split(".", 1)[0] or "computer"


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


def config_path_from_argv(argv: Optional[list[str]]) -> Path:
    """Find --config's value without building the full parser yet.

    Needed because YAML values become argparse *defaults*, so the config
    file has to be located and loaded before the real parser is built.
    """
    items = list(sys.argv[1:] if argv is None else argv)
    for index, item in enumerate(items):
        if item == "--config" and index + 1 < len(items):
            return Path(items[index + 1]).expanduser()
        if item.startswith("--config="):
            return Path(item.split("=", 1)[1]).expanduser()
    env_value = os.getenv("HERMES_RELAY_TUI_CONFIG")
    if env_value:
        return Path(env_value).expanduser()
    return DEFAULT_CONFIG_PATH


def load_config_file(path: Optional[Path]) -> dict[str, Any]:
    """Load YAML settings used as argparse defaults.

    CLI flags and environment variables still win over these — see
    ``build_arg_parser``'s precedence for each option: CLI flag > env var >
    config file > built-in default.
    """
    if path is None:
        return {}
    path = path.expanduser()
    if not path.exists():
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
    path = path.expanduser()
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
    return Path(value).expanduser() if value else hardcoded


def _cfg_bool(cfg: dict[str, Any], key: str, hardcoded: bool = False) -> bool:
    value = cfg.get(key)
    return bool(value) if value is not None else hardcoded


def _cfg_choice(cfg: dict[str, Any], key: str, choices: tuple[str, ...], hardcoded: str) -> str:
    value = cfg.get(key)
    if isinstance(value, str) and value.strip().lower() in choices:
        return value.strip().lower()
    return hardcoded


@dataclass(frozen=True)
class HouseholdProfile:
    name: str
    display_name: str
    wake_phrases: tuple[str, ...]
    url: str
    token: str
    client_id: str
    device_id: str
    session_id: str
    model: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"HouseholdProfile(name={self.name!r}, display_name={self.display_name!r}, "
            f"wake_phrases={self.wake_phrases!r}, url={self.url!r}, token='***', "
            f"client_id={self.client_id!r}, device_id={self.device_id!r}, "
            f"session_id={self.session_id!r}, model={self.model!r})"
        )


@dataclass(frozen=True)
class RelayProfile:
    """One laptop relay target with its bearer token resolved in memory.

    ``token_env`` is the only credential reference that belongs in the
    editable YAML document. ``token`` exists for the connection boundary and
    is deliberately redacted from ``repr`` so diagnostics and test failures
    cannot turn a profile object into a credential leak.
    """

    name: str
    display_name: str
    url: str
    token: str
    token_env: str
    client_id: str
    device_id: str
    session_id: str
    model: Optional[str] = None
    legacy: bool = False
    wake_phrases: tuple[str, ...] = ()

    @property
    def token_configured(self) -> bool:
        return bool(self.token)

    def __repr__(self) -> str:
        return (
            f"RelayProfile(name={self.name!r}, display_name={self.display_name!r}, "
            f"url={self.url!r}, token='***', token_env={self.token_env!r}, "
            f"client_id={self.client_id!r}, device_id={self.device_id!r}, "
            f"session_id={self.session_id!r}, model={self.model!r}, "
            f"legacy={self.legacy!r}, wake_phrases={self.wake_phrases!r})"
        )


_PROFILE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_TOKEN_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_profile_name(value: str) -> str:
    """Return a canonical profile name suitable for config and file paths."""
    name = str(value or "").strip().lower()
    if not _PROFILE_NAME_RE.fullmatch(name):
        raise ValueError(
            "profile name must start with a letter and contain only letters, "
            "numbers, '-' or '_'"
        )
    return name


def validate_token_env(value: str) -> str:
    """Validate a private environment variable reference."""
    env_name = str(value or "").strip()
    if not _TOKEN_ENV_RE.fullmatch(env_name):
        raise ValueError("token environment name must be a valid variable name")
    return env_name


def profile_token_env(name: str) -> str:
    """Return the default private env key for a profile."""
    canonical = validate_profile_name(name)
    if canonical == "default":
        return "VOICE_SESSION_TOKEN"
    return f"VOICE_SESSION_TOKEN_{canonical.upper()}"


def _lookup_env_file(path: Path, key: str) -> str:
    resolved_path = Path(path).expanduser()
    paths = [resolved_path]
    if resolved_path == DEFAULT_PROFILE_ENV and LEGACY_PROFILE_ENV != DEFAULT_PROFILE_ENV:
        paths.append(LEGACY_PROFILE_ENV)
    for p in paths:
        if not p.exists():
            continue
        try:
            from dotenv import dotenv_values

            val = dotenv_values(p).get(key)
            if val:
                return str(val).strip()
        except ImportError:
            try:
                for raw_line in p.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line.startswith(f"{key}="):
                        continue
                    value = line.split("=", 1)[1].strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                        value = value[1:-1]
                    if value:
                        return value
            except (OSError, UnicodeDecodeError):
                continue
        except (OSError, UnicodeDecodeError):
            continue
    return ""


def _resolve_token(explicit: Optional[str], env_path: Path) -> str:
    if explicit:
        return explicit
    from_environment = os.getenv("VOICE_SESSION_TOKEN", "").strip()
    if from_environment:
        return from_environment
    return _lookup_env_file(env_path, "VOICE_SESSION_TOKEN")

def resolve_profile_token(
    data: dict[str, Any],
    profile_env: Path,
    fallback_token: str = "",
    *,
    allow_generic_fallback: bool = True,
) -> str:
    token_env = data.get("token_env")
    if token_env and isinstance(token_env, str):
        env_key = token_env.strip()
        val = os.getenv(env_key)
        if val:
            return val.strip()
        file_val = _lookup_env_file(profile_env, env_key)
        if file_val:
            return file_val

    raw_token = data.get("token")
    if raw_token and isinstance(raw_token, str):
        raw_token = raw_token.strip()
        if raw_token.startswith("${") and raw_token.endswith("}"):
            var_name = raw_token[2:-1].strip()
            val = os.getenv(var_name)
            if val:
                return val.strip()
            file_val = _lookup_env_file(profile_env, var_name)
            if file_val:
                return file_val
        elif raw_token.startswith("$") and len(raw_token) > 1 and raw_token[1:].isidentifier():
            var_name = raw_token[1:]
            val = os.getenv(var_name)
            if val:
                return val.strip()
            file_val = _lookup_env_file(profile_env, var_name)
            if file_val:
                return file_val
        else:
            return raw_token

    name = str(data.get("name", "")).upper().replace("-", "_")
    if name:
        specific_env = f"VOICE_SESSION_TOKEN_{name}"
        val = os.getenv(specific_env)
        if val:
            return val.strip()
        file_val = _lookup_env_file(profile_env, specific_env)
        if file_val:
            return file_val

    if fallback_token:
        return fallback_token
    if allow_generic_fallback:
        return _resolve_token(None, profile_env)
    return ""


def _profile_entries(cfg: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Read either HOME-13's mapping or list profile shape in file order."""
    raw_profiles = cfg.get("profiles")
    entries: list[tuple[str, dict[str, Any]]] = []
    if isinstance(raw_profiles, dict):
        for key, value in raw_profiles.items():
            if isinstance(value, dict):
                entries.append((str(key), dict(value)))
    elif isinstance(raw_profiles, list):
        for item in raw_profiles:
            if isinstance(item, dict):
                key = str(item.get("name") or len(entries) + 1)
                entries.append((key, dict(item)))
    return entries


def _profile_token_source(entry: dict[str, Any], name: str, *, legacy: bool = False) -> str:
    explicit = entry.get("token_env")
    if isinstance(explicit, str) and explicit.strip():
        return validate_token_env(explicit)

    raw_token = entry.get("token")
    if isinstance(raw_token, str):
        token = raw_token.strip()
        if token.startswith("${") and token.endswith("}"):
            return validate_token_env(token[2:-1].strip())
        if token.startswith("$") and len(token) > 1 and token[1:].isidentifier():
            return validate_token_env(token[1:])

    return profile_token_env(name) if not legacy else "VOICE_SESSION_TOKEN"


def _private_env_value(path: Path, key: str) -> str:
    """Resolve one profile-specific key without falling back to another key."""
    value = os.getenv(key, "").strip()
    return value or _lookup_env_file(path, key)


def _resolve_relay_profile_token(
    entry: dict[str, Any],
    name: str,
    profile_env: Path,
) -> str:
    """Resolve a laptop profile token without generic-token cross-talk."""
    explicit_source = entry.get("token_env")
    if isinstance(explicit_source, str) and explicit_source.strip():
        return _private_env_value(profile_env, validate_token_env(explicit_source))

    raw_token = entry.get("token")
    if isinstance(raw_token, str):
        raw_token = raw_token.strip()
        if raw_token.startswith("${") and raw_token.endswith("}"):
            return _private_env_value(profile_env, validate_token_env(raw_token[2:-1].strip()))
        if raw_token.startswith("$") and len(raw_token) > 1 and raw_token[1:].isidentifier():
            return _private_env_value(profile_env, validate_token_env(raw_token[1:]))
        if raw_token:
            return raw_token

    return _private_env_value(profile_env, profile_token_env(name))


def resolve_profile_token_source(profile_env: Path, token_env: str) -> str:
    """Resolve exactly one profile token source for a session boundary."""
    return _private_env_value(Path(profile_env).expanduser(), validate_token_env(token_env))


# The Puck bridge's temporary stand-in for Story 4's real per-device
# credential system (blocked on Epic 3's DEVICE-01/02/06 landing first).
# Same token_env indirection as the relay-profile tokens above: only the
# *name* of an environment variable lives here in config, the actual secret
# lives in the environment or the profile `.env` file, and it is never a
# literal in source. Replace this with Story 4's real credential once it
# exists -- do not treat this as adequate for a real household deployment.
PUCK_DEVICE_TOKEN_ENV = "PUCK_DEVICE_TOKEN"


def resolve_puck_device_token(profile_env: Path | None = None) -> str:
    """Resolve the standalone Puck-bridge device token."""
    env_path = Path(profile_env or DEFAULT_PROFILE_ENV).expanduser()
    return _private_env_value(env_path, PUCK_DEVICE_TOKEN_ENV)


def _profile_env_path(cfg: dict[str, Any], args: Any = None) -> Path:
    value = getattr(args, "profile_env", None) if args is not None else None
    if value is None:
        value = cfg.get("profile_env")
    return Path(value).expanduser() if value else DEFAULT_PROFILE_ENV


def load_relay_profiles(cfg: dict[str, Any], args: Any = None) -> list[RelayProfile]:
    """Resolve laptop relay profiles without importing a user-interface layer."""
    if not isinstance(cfg, dict):
        raise ValueError("config must contain a mapping of settings")

    entries = _profile_entries(cfg)
    profile_env = _profile_env_path(cfg, args)
    if entries:
        # A named profile is self-contained. Root-level connection keys are
        # legacy single-target settings and must not leak into this catalog.
        profiles: list[RelayProfile] = []
        seen: set[str] = set()
        for key, entry in entries:
            name = validate_profile_name(str(entry.get("name") or key))
            if name in seen:
                raise ValueError(f"duplicate relay profile: {name}")
            seen.add(name)
            token = _resolve_relay_profile_token(entry, name, profile_env)
            wake_phrases = _parse_wake_phrases(
                entry.get("wake_phrases") or entry.get("wake_phrase")
            )
            profiles.append(
                RelayProfile(
                    name=name,
                    display_name=str(entry.get("display_name") or name.capitalize()).strip(),
                    url=str(entry.get("url") or DEFAULT_URL).strip(),
                    token=token,
                    token_env=_profile_token_source(entry, name),
                    client_id=str(entry.get("client_id") or f"{name}-relay").strip(),
                    device_id=str(entry.get("device_id") or default_device_id()).strip(),
                    session_id=str(entry.get("session_id") or f"{name}-session").strip(),
                    model=str(entry["model"]).strip() if entry.get("model") is not None else None,
                    wake_phrases=wake_phrases,
                )
            )
        return profiles

    # A legacy root config is a real, usable one-profile catalog. It becomes
    # persistent only when a profile command writes the config.
    fallback_url = (
        getattr(args, "url", None) if args is not None else None
    ) or _cfg_str(cfg, "url", DEFAULT_URL) or DEFAULT_URL
    fallback_client_id = (
        getattr(args, "client_id", None) if args is not None else None
    ) or _cfg_str(cfg, "client_id", "amanda-laptop") or "amanda-laptop"
    fallback_device_id = (
        getattr(args, "device_id", None) if args is not None else None
    ) or _cfg_str(cfg, "device_id", default_device_id()) or default_device_id()
    fallback_session_id = (
        getattr(args, "session_id", None) if args is not None else None
    ) or _cfg_str(cfg, "session_id", "hybrid-tui") or "hybrid-tui"
    explicit_token = getattr(args, "token", None) if args is not None else None
    raw_token = explicit_token or cfg.get("token")
    token = _resolve_token(raw_token, profile_env)
    display_name = (
        getattr(args, "display_name", None) if args is not None else None
    ) or _cfg_str(cfg, "display_name", "Amanda streaming TUI") or "Amanda streaming TUI"
    model = (
        getattr(args, "model", None) if args is not None else None
    ) or _cfg_str(cfg, "model")
    raw_wake_phrases = (
        getattr(args, "wake_phrases", None) if args is not None else None
    ) or _cfg_str(cfg, "wake_phrases") or _cfg_str(cfg, "wake_phrase")
    wake_phrases = _parse_wake_phrases(raw_wake_phrases)
    return [
        RelayProfile(
            name="default",
            display_name=display_name,
            url=str(fallback_url).strip(),
            token=token,
            token_env="VOICE_SESSION_TOKEN",
            client_id=str(fallback_client_id).strip(),
            device_id=str(fallback_device_id).strip(),
            session_id=str(fallback_session_id).strip(),
            model=str(model).strip() if model is not None else None,
            legacy=True,
            wake_phrases=wake_phrases,
        )
    ]


def _write_private_env_lines(path: Path, lines: list[str]) -> None:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_private_env_value(path: Path, key: str, value: str) -> None:
    """Replace one private env value without exposing it in YAML."""
    key = validate_token_env(key)
    if not value or any(char in value for char in "\r\n"):
        raise ValueError("bearer token must be a non-empty single line")
    path = Path(path).expanduser()
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []
    replacement = f"{key}={json.dumps(value)}\n"
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"export {key}="):
            lines[index] = replacement
            break
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(replacement)
    _write_private_env_lines(path, lines)


def _remove_private_env_value(path: Path, key: str) -> None:
    key = validate_token_env(key)
    path = Path(path).expanduser()
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [
        line
        for line in lines
        if not line.lstrip().startswith((f"{key}=", f"export {key}="))
    ]
    if kept != lines:
        _write_private_env_lines(path, kept)


def _write_config_document(path: Path, document: dict[str, Any]) -> None:
    import yaml

    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = yaml.safe_dump(document, sort_keys=False)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _mutable_config(path: Path) -> dict[str, Any]:
    document = load_config_file(path)
    return dict(document)


def _legacy_config_has_connection(document: dict[str, Any]) -> bool:
    return any(
        key in document
        for key in (
            "url",
            "token",
            "profile_env",
            "client_id",
            "device_id",
            "session_id",
            "display_name",
            "model",
            "wake_phrase",
            "wake_phrases",
        )
    )


def _migrate_document(document: dict[str, Any], profile_env: Path | None = None) -> RelayProfile:
    """Convert legacy root connection keys in a mutable document."""
    env_path = Path(profile_env or _profile_env_path(document)).expanduser()
    raw_token = document.get("token")
    token_data: dict[str, Any]
    if raw_token:
        token_data = {"token": raw_token, "name": "default"}
    else:
        token_data = {"token_env": "VOICE_SESSION_TOKEN", "name": "default"}
    token = resolve_profile_token(token_data, env_path)
    if token:
        write_private_env_value(env_path, "VOICE_SESSION_TOKEN", token)

    entry: dict[str, Any] = {
        "display_name": str(document.get("display_name") or "Amanda streaming TUI"),
        "url": str(document.get("url") or DEFAULT_URL),
        "token_env": "VOICE_SESSION_TOKEN",
        "client_id": str(document.get("client_id") or "amanda-laptop"),
        "device_id": str(document.get("device_id") or default_device_id()),
        "session_id": str(document.get("session_id") or "hybrid-tui"),
    }
    for key in ("model", "wake_phrase", "wake_phrases"):
        if key in document:
            entry[key] = document[key]

    document.pop("token", None)
    document["profiles"] = {"default": entry}
    document["active_profile"] = "default"
    profiles = load_relay_profiles(document, types.SimpleNamespace(profile_env=env_path))
    return profiles[0]


def migrate_legacy_profile_config(config_path: Path) -> RelayProfile:
    """Persist the legacy root connection as the private-token default profile."""
    path = Path(config_path).expanduser()
    document = _mutable_config(path)
    if _profile_entries(document):
        profiles = load_relay_profiles(document)
        return profiles[0]
    profile = _migrate_document(document)
    _write_config_document(path, document)
    return profile


def _normalized_profile_document(
    document: dict[str, Any],
    config_path: Path,
    *,
    profile_env: Path | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], Path]:
    """Prepare a document and mapping for a profile mutation."""
    entries = _profile_entries(document)
    if not entries and _legacy_config_has_connection(document):
        _migrate_document(document, profile_env=profile_env)
        entries = _profile_entries(document)
    elif not entries:
        document["profiles"] = {}
    env_path = Path(
        profile_env
        or document.get("profile_env")
        or DEFAULT_PROFILE_ENV
    ).expanduser()
    if profile_env is not None:
        document["profile_env"] = str(env_path)
    profiles: dict[str, dict[str, Any]] = {}
    for key, entry in entries:
        name = validate_profile_name(str(entry.get("name") or key))
        if name in profiles:
            raise ValueError(f"duplicate relay profile: {name}")
        profiles[name] = dict(entry)
        profiles[name].pop("name", None)
    document["profiles"] = profiles
    return document, profiles, env_path


def save_relay_profile(
    config_path: Path,
    *,
    name: str,
    display_name: str,
    url: str,
    token: str | None,
    client_id: str,
    device_id: str,
    session_id: str,
    model: str | None = None,
    wake_phrases: str | None = None,
    token_env: str | None = None,
    profile_env: Path | None = None,
) -> RelayProfile:
    """Create or update one profile, keeping its bearer token private."""
    canonical = validate_profile_name(name)
    path = Path(config_path).expanduser()
    document = _mutable_config(path)
    document, profiles, env_path = _normalized_profile_document(
        document,
        path,
        profile_env=profile_env,
    )
    old_entry = profiles.get(canonical, {})
    old_source = _profile_token_source(old_entry, canonical) if old_entry else None
    old_token = (
        _resolve_relay_profile_token(old_entry, canonical, env_path)
        if old_entry
        else ""
    )
    source = validate_token_env(token_env) if token_env else (old_source or profile_token_env(canonical))
    if token and token.strip():
        write_private_env_value(env_path, source, token.strip())
    elif old_entry and old_token and source != old_source:
        # Changing the reference while retaining the old secret must not leave
        # the newly selected profile disconnected by accident.
        write_private_env_value(env_path, source, old_token)
    elif old_entry and "token" in old_entry and old_token:
        # HOME-13 tolerated a literal token for backwards compatibility. Any
        # profile edit is the opportunity to remove that leak from YAML.
        write_private_env_value(env_path, source, old_token)

    entry = dict(old_entry)
    entry.update(
        {
            "display_name": str(display_name).strip(),
            "url": str(url).strip(),
            "token_env": source,
            "client_id": str(client_id).strip(),
            "device_id": str(device_id).strip(),
            "session_id": str(session_id).strip(),
        }
    )
    if model is not None and str(model).strip():
        entry["model"] = str(model).strip()
    elif not old_entry:
        entry.pop("model", None)
    if wake_phrases is not None:
        parsed_wake_phrases = _parse_wake_phrases(wake_phrases)
        if parsed_wake_phrases:
            entry["wake_phrases"] = list(parsed_wake_phrases)
            entry.pop("wake_phrase", None)
        else:
            entry.pop("wake_phrases", None)
            entry.pop("wake_phrase", None)
    entry.pop("token", None)
    profiles[canonical] = entry
    document["profiles"] = profiles
    active = str(document.get("active_profile") or "").strip().lower()
    if not active or active not in profiles:
        document["active_profile"] = canonical
    _write_config_document(path, document)
    resolved = load_relay_profiles(document, types.SimpleNamespace(profile_env=env_path))
    return next(profile for profile in resolved if profile.name == canonical)


def select_relay_profile(config_path: Path, name: str) -> RelayProfile:
    """Persist the active profile selection and return its resolved profile."""
    canonical = validate_profile_name(name)
    path = Path(config_path).expanduser()
    document = _mutable_config(path)
    document, profiles, env_path = _normalized_profile_document(document, path)
    if canonical not in profiles:
        raise ValueError(f"unknown relay profile: {canonical}")
    document["active_profile"] = canonical
    _write_config_document(path, document)
    resolved = load_relay_profiles(document, types.SimpleNamespace(profile_env=env_path))
    return next(profile for profile in resolved if profile.name == canonical)


def delete_relay_profile(config_path: Path, name: str) -> None:
    """Delete a profile and its private token when no profile shares it."""
    canonical = validate_profile_name(name)
    path = Path(config_path).expanduser()
    document = _mutable_config(path)
    document, profiles, env_path = _normalized_profile_document(document, path)
    if canonical not in profiles:
        raise ValueError(f"unknown relay profile: {canonical}")
    if len(profiles) <= 1:
        raise ValueError("cannot delete the last relay profile")
    removed = profiles.pop(canonical)
    source = _profile_token_source(removed, canonical)
    shared_sources = {
        _profile_token_source(entry, other_name)
        for other_name, entry in profiles.items()
    }
    document["profiles"] = profiles
    if str(document.get("active_profile") or "").strip().lower() == canonical:
        document["active_profile"] = next(iter(profiles))
    _write_config_document(path, document)
    if source not in shared_sources:
        _remove_private_env_value(env_path, source)


def _parse_wake_phrases(raw: Any) -> tuple[str, ...]:
    if not raw:
        return ()
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return tuple(parts)
    if isinstance(raw, (list, tuple, set)):
        parts = [str(p).strip() for p in raw if str(p).strip()]
        return tuple(parts)
    return ()


def load_household_profiles(
    cfg: dict[str, Any],
    args: Any = None,
) -> list[HouseholdProfile]:
    profile_env = getattr(args, "profile_env", None) or _cfg_path(cfg, "profile_env", DEFAULT_PROFILE_ENV)

    raw_profiles = cfg.get("profiles")
    if raw_profiles and isinstance(raw_profiles, (dict, list)):
        profiles: list[HouseholdProfile] = []
        entries: list[tuple[str, dict[str, Any]]] = []
        if isinstance(raw_profiles, dict):
            for k, v in raw_profiles.items():
                if isinstance(v, dict):
                    entries.append((str(k), v))
        elif isinstance(raw_profiles, list):
            for item in raw_profiles:
                if isinstance(item, dict):
                    k = str(item.get("name") or len(entries) + 1)
                    entries.append((k, item))

        for key, entry in entries:
            name = str(entry.get("name") or key).strip()
            display_name = str(entry.get("display_name") or name.capitalize()).strip()
            raw_phrases = entry.get("wake_phrases") or entry.get("wake_phrase")
            wake_phrases = _parse_wake_phrases(raw_phrases)
            url = str(entry.get("url") or DEFAULT_URL).strip()
            token = resolve_profile_token(
                dict(entry, name=name),
                profile_env,
                allow_generic_fallback=False,
            )
            client_id = str(entry.get("client_id") or f"{name}-home").strip()
            device_id = str(entry.get("device_id") or default_device_id()).strip()
            session_id = str(entry.get("session_id") or f"{name}-home").strip()
            model = entry.get("model")
            if model is not None:
                model = str(model).strip()

            profiles.append(
                HouseholdProfile(
                    name=name,
                    display_name=display_name,
                    wake_phrases=wake_phrases,
                    url=url,
                    token=token,
                    client_id=client_id,
                    device_id=device_id,
                    session_id=session_id,
                    model=model,
                )
            )
        if profiles:
            return profiles

    # Without a profiles mapping, preserve the original single-target config.
    # Once profiles exist, their connection fields are canonical; none of the
    # root-level connection keys above are consulted for those entries.
    fallback_url = getattr(args, "url", None) or _cfg_str(cfg, "url", DEFAULT_URL)
    fallback_client_id = getattr(args, "client_id", None) or _cfg_str(cfg, "client_id", "amanda-laptop")
    fallback_device_id = getattr(args, "device_id", None) or _cfg_str(cfg, "device_id", default_device_id())
    fallback_session_id = getattr(args, "session_id", None) or _cfg_str(cfg, "session_id", "hybrid-tui")
    fallback_token = _resolve_token(getattr(args, "token", None) or _cfg_str(cfg, "token"), profile_env)
    fallback_model = getattr(args, "model", None) or _cfg_str(cfg, "model")
    display_name = getattr(args, "display_name", None) or _cfg_str(cfg, "display_name", "Home")
    raw_phrases = getattr(args, "wake_phrases", None) or _cfg_str(cfg, "wake_phrases") or _cfg_str(cfg, "wake_phrase")
    wake_phrases = _parse_wake_phrases(raw_phrases)
    if not wake_phrases:
        wake_phrases = ("hey hermes",)

    return [
        HouseholdProfile(
            name="default",
            display_name=display_name,
            wake_phrases=wake_phrases,
            url=fallback_url,
            token=fallback_token,
            client_id=fallback_client_id,
            device_id=fallback_device_id,
            session_id=fallback_session_id,
            model=fallback_model,
        )
    ]


def make_profile_args(base_args: Any, profile: HouseholdProfile) -> Any:
    """Create a copy of base_args with profile-specific session fields overridden."""
    if hasattr(base_args, "__dict__"):
        data = dict(vars(base_args))
    else:
        data = {}
    data.update({
        "url": profile.url,
        "token": profile.token,
        "client_id": profile.client_id,
        "device_id": profile.device_id,
        "session_id": profile.session_id,
        "display_name": profile.display_name,
        "model": profile.model or data.get("model"),
        "wake_phrases": ", ".join(getattr(profile, "wake_phrases", ())) or None,
        "profile_name": profile.name,
        "profile_token_env": getattr(profile, "token_env", None),
        "profile_legacy": getattr(profile, "legacy", False),
        "profiles_configured": not getattr(profile, "legacy", False),
    })
    return argparse.Namespace(**data)


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


def _option_value(argv: list[str], option: str) -> str | None:
    """Read one simple option before argparse has been built."""
    for index, item in enumerate(argv):
        if item == option and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith(option + "="):
            return item.split("=", 1)[1]
    return None


def _profile_selection(argv: list[str], cfg: dict[str, Any]) -> str | None:
    explicit = _option_value(argv, "--profile")
    if explicit:
        return explicit.strip().lower()
    if argv and not argv[0].startswith("-") and argv[0] not in {
        "setup",
        "install",
        "profile",
    }:
        # A bare first word is the concise launch form: `hermes-relay amanda`.
        # The reserved subcommands are dispatched by app.main before this
        # parser runs and must never be mistaken for profile names here.
        return argv[0].strip().lower()
    from_environment = os.getenv("VOICE_SESSION_PROFILE", "").strip()
    if from_environment:
        return from_environment.lower()
    configured = cfg.get("active_profile")
    if configured:
        return str(configured).strip().lower()
    entries = _profile_entries(cfg)
    if entries:
        return str(entries[0][1].get("name") or entries[0][0]).strip().lower()
    return "default"


def build_arg_parser(argv: Optional[list[str]] = None) -> argparse.ArgumentParser:
    """Build the CLI parser, layering defaults as CLI flag > env var > YAML config > built-in.

    ``argv`` only affects finding ``--config`` before the full parser exists;
    the returned parser still needs ``parse_args(argv)`` called on it as usual.
    """
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    config_path = config_path_from_argv(raw_argv)
    cfg = load_config_file(config_path)

    profile_env_override = _option_value(raw_argv, "--profile-env")
    profile_args = types.SimpleNamespace(
        profile_env=Path(profile_env_override).expanduser()
        if profile_env_override
        else None
    )
    try:
        relay_profiles = load_relay_profiles(cfg, profile_args)
    except ValueError as exc:
        raise SystemExit(f"error: invalid relay profile configuration: {exc}") from exc
    configured_profile_names = tuple(profile.name for profile in relay_profiles)
    selected_name = _profile_selection(raw_argv, cfg) or "default"
    try:
        selected_profile = next(
            profile for profile in relay_profiles if profile.name == selected_name
        )
    except StopIteration as exc:
        available = ", ".join(configured_profile_names) or "none"
        raise SystemExit(
            f"error: unknown relay profile {selected_name!r}; available: {available}"
        ) from exc
    profiles_configured = bool(_profile_entries(cfg))

    parser = argparse.ArgumentParser(description="Hermes streaming TUI")
    parser.add_argument(
        "--config",
        type=Path,
        default=config_path,
        help=f"YAML config file for defaults (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--profile",
        default=selected_profile.name,
        choices=configured_profile_names if profiles_configured else None,
        help=(
            "named relay profile to use (default: active_profile in the config; "
            "also accepts VOICE_SESSION_PROFILE)"
        ),
    )
    parser.add_argument(
        "profile_shorthand",
        nargs="?",
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(
        profile_name=selected_profile.name,
        profile_token_env=selected_profile.token_env,
        profile_legacy=selected_profile.legacy,
        profiles_configured=profiles_configured,
        profile_names=configured_profile_names,
    )
    selected_url = selected_profile.url
    selected_client_id = selected_profile.client_id
    selected_device_id = selected_profile.device_id
    selected_session_id = selected_profile.session_id
    selected_display_name = selected_profile.display_name
    selected_model = selected_profile.model
    selected_token = selected_profile.token
    selected_wake_phrases = ", ".join(selected_profile.wake_phrases) or None
    parser.add_argument(
        "--url", default=os.getenv("HERMES_VOICE_SESSION_URL", selected_url)
    )
    parser.add_argument(
        "--token",
        default=_cfg_str(cfg, "token") if selected_profile.legacy else selected_token,
        help="Bearer token; prefer VOICE_SESSION_TOKEN or the profile .env",
    )
    parser.add_argument("--profile-env", type=Path, default=_cfg_path(cfg, "profile_env", DEFAULT_PROFILE_ENV))
    parser.add_argument(
        "--client-id",
        default=os.getenv("VOICE_SESSION_CLIENT_ID", selected_client_id),
    )
    parser.add_argument(
        "--device-id",
        default=os.getenv("VOICE_SESSION_DEVICE_ID", selected_device_id),
    )
    parser.add_argument(
        "--session-id", default=os.getenv("VOICE_SESSION_ID", selected_session_id)
    )
    parser.add_argument("--display-name", default=selected_display_name)
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
        default=_env_float("VOICE_SESSION_MIC_SILENCE_DURATION", cfg.get("mic_silence_duration", 1.5)),
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
        "--wake-enabled",
        action="store_true",
        default=_cfg_bool(cfg, "wake_enabled"),
        help="listen continuously for the wake phrase (needs the 'wake' extra)",
    )
    parser.add_argument(
        "--wake-engine",
        choices=WAKE_ENGINES,
        default=_env_choice(
            "VOICE_SESSION_WAKE_ENGINE",
            WAKE_ENGINES,
            _cfg_choice(cfg, "wake_engine", WAKE_ENGINES, "openwakeword"),
        ),
        help="wake-word detection engine ('openwakeword' or 'sherpa')",
    )
    parser.add_argument(
        "--wake-phrases",
        default=os.getenv(
            "VOICE_SESSION_WAKE_PHRASES",
            selected_wake_phrases,
        ),
        help="comma-separated wake phrases for Sherpa-ONNX (e.g. 'hey hermes, computer')",
    )
    parser.add_argument(
        "--wake-keywords-score",
        type=float,
        default=_env_float(
            "VOICE_SESSION_WAKE_KEYWORDS_SCORE",
            cfg.get("wake_keywords_score", 1.0),
        ),
        help="keyword boosting score for Sherpa-ONNX (default: 1.0)",
    )
    parser.add_argument(
        "--wake-keywords-threshold",
        type=float,
        default=_env_float(
            "VOICE_SESSION_WAKE_KEYWORDS_THRESHOLD",
            cfg.get("wake_keywords_threshold", 0.25),
        ),
        help="keyword spotting threshold for Sherpa-ONNX (default: 0.25)",
    )
    parser.add_argument(
        "--wake-model",
        default=_cfg_str(cfg, "wake_model"),
        help="path to a wake-word .onnx model, or a built-in openWakeWord name",
    )
    parser.add_argument(
        "--wake-threshold",
        type=float,
        default=cfg.get("wake_threshold", 0.6),
        help="per-frame score above which the wake phrase is considered present",
    )
    parser.add_argument(
        "--wake-confirmation-frames",
        type=int,
        default=cfg.get("wake_confirmation_frames", 3),
        help=(
            "consecutive over-threshold frames required to fire; the main "
            "defence against triggering on background conversation"
        ),
    )
    parser.add_argument(
        "--wake-refractory-seconds",
        type=float,
        default=cfg.get("wake_refractory_seconds", 2.0),
        help="minimum gap between two wake fires",
    )
    parser.add_argument(
        "--wake-listen-timeout",
        type=float,
        default=cfg.get("wake_listen_timeout", 8.0),
        help="how long to wait after the wake phrase for speech to begin",
    )
    parser.add_argument(
        "--wake-followup-seconds",
        type=float,
        default=_env_float(
            "VOICE_SESSION_WAKE_FOLLOWUP_SECONDS",
            cfg.get("wake_followup_seconds", 8.0),
        ),
        help="how long to listen for a follow-up after a wake-triggered response",
    )
    parser.add_argument(
        "--wake-barge-in",
        action="store_true",
        default=_cfg_bool(cfg, "wake_barge_in"),
        help=(
            "allow local speech to interrupt an active response; needs echo "
            "cancellation or the unit hears its own voice"
        ),
    )
    parser.add_argument(
        "--wake-barge-in-min-speech-duration",
        type=float,
        default=_env_float(
            "VOICE_SESSION_WAKE_BARGE_IN_MIN_SPEECH_DURATION",
            cfg.get("wake_barge_in_min_speech_duration", 0.30),
        ),
        help=(
            "seconds of windowed microphone audio required before barge-in "
            "interrupts; local speech recognition decides whether to follow up"
        ),
    )
    parser.add_argument(
        "--no-earcons",
        dest="earcons",
        action="store_false",
        # Deliberately independent of --wake-enabled. An appliance that chirps
        # at the wrong moment has to be quietable without being made deaf.
        default=_cfg_bool(cfg, "earcons", hardcoded=True),
        help="silence the wake and end-of-capture tones on the home unit",
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
        default=os.getenv("VOICE_SESSION_MODEL") or selected_model,
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
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_PROFILE_ENV",
    "LEGACY_PROFILE_ENV",
    "DEFAULT_URL",
    "HouseholdProfile",
    "RelayProfile",
    "_connection_kwargs",
    "_env_bool",
    "_env_choice",
    "_env_float",
    "_env_int",
    "_resolve_token",
    "build_arg_parser",
    "config_path_from_argv",
    "configure_logging",
    "connect_factory",
    "default_device_id",
    "ensure_default_config_file",
    "load_config_file",
    "load_household_profiles",
    "load_relay_profiles",
    "make_profile_args",
    "delete_relay_profile",
    "migrate_legacy_profile_config",
    "profile_token_env",
    "PUCK_DEVICE_TOKEN_ENV",
    "resolve_profile_token",
    "resolve_profile_token_source",
    "resolve_puck_device_token",
    "save_relay_profile",
    "select_relay_profile",
    "validate_profile_name",
    "validate_token_env",
    "write_private_env_value",
]
