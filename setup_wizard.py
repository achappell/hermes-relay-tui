"""Interactive first-run setup for hermes-relay."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import inspect
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import yaml

import config
import config as config_module
from voice import DEFAULT_STT_MODEL


DEFAULT_TOKEN_ENV_PATH = config.DEFAULT_PROFILE_ENV
_CREDENTIAL_QUERY_SUFFIXES = (
    "token",
    "apikey",
    "password",
    "secret",
    "credential",
)
_CREDENTIAL_QUERY_KEYS = frozenset({"auth", "authorization"})


def prepare_stt_model(model_name: str) -> str:
    """Download the local Faster-Whisper model and return its cache path."""
    model = str(model_name or DEFAULT_STT_MODEL).strip()
    if not model:
        model = DEFAULT_STT_MODEL

    local_path = Path(model).expanduser()
    if local_path.exists():
        if not local_path.is_dir():
            raise ValueError(f"STT model path is not a directory: {local_path}")
        return str(local_path)

    try:
        from faster_whisper import download_model
    except ImportError as exc:
        raise RuntimeError(
            "local voice dependencies are unavailable; install them with: "
            "hermes-relay install voice"
        ) from exc
    return str(download_model(model))


def _ask(input_fn: Any, question: str, *, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return str(input_fn(f"{question}{suffix}: ") or "").strip() or default


def _existing_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"config file {path} must contain a mapping")
    return value


def _setup_transport_label(transport: str) -> str:
    return {
        "gateway": "Standard Hermes",
        "home": "HomeBridge",
        "voice-session": "Legacy voice-session",
    }.get(transport, "Unknown transport")


def normalize_endpoint(value: str, *, transport: str = "voice-session") -> str:
    """Normalize a pasted endpoint for the selected transport."""
    raw = str(value or "").strip()
    if raw.startswith("http://"):
        raw = "ws://" + raw[len("http://") :]
    elif raw.startswith("https://"):
        raw = "wss://" + raw[len("https://") :]
    parsed = urlsplit(raw)
    if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
        raise ValueError("endpoint must be a ws:// or wss:// URL")
    path = parsed.path.rstrip("/")
    if path.endswith("/health"):
        path = path[: -len("/health")].rstrip("/")
    if transport == "home":
        if parsed.scheme != "wss":
            raise ValueError("Home bridge requires a secure wss:// endpoint")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Home bridge URL must not contain credentials or query data")
        if path not in {"", "/voice-session", "/api/ws", config.HOME_BRIDGE_PATH}:
            raise ValueError(
                f"Home transport requires the approved {config.HOME_BRIDGE_PATH} route"
            )
        return urlunsplit(
            (parsed.scheme, parsed.netloc, config.HOME_BRIDGE_PATH, "", "")
        )
    default_path = "/api/ws" if transport == "gateway" else "/voice-session"
    if transport == "gateway":
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(
                "Standard Hermes credentials must be entered separately, not in the endpoint URL"
            )
        if any(
            (
                normalized := "".join(
                    char for char in key.casefold() if char.isalnum()
                )
            )
            in _CREDENTIAL_QUERY_KEYS
            or normalized.endswith(_CREDENTIAL_QUERY_SUFFIXES)
            for key, _value in parse_qsl(parsed.query)
        ):
            raise ValueError(
                "enter Standard Hermes credentials separately instead of putting them in the endpoint URL"
            )
    # A transport switch commonly reuses the saved endpoint. Replace the
    # known route from the other transport instead of preserving a URL that
    # will pass parsing but can never complete the selected handshake.
    if transport == "gateway" and path == "/voice-session":
        path = default_path
    elif transport == "gateway" and path not in {"", "/api/ws"}:
        raise ValueError(
            "gateway transport requires the Standard /api/ws endpoint; "
            "Home bridge routes are not direct gateway endpoints"
        )
    elif transport != "gateway" and path == "/api/ws":
        path = default_path
    return urlunsplit((parsed.scheme, parsed.netloc, path or default_path, parsed.query, ""))


def _write_private_env(path: Path, token: str) -> None:
    if not token or any(char in token for char in "\r\n"):
        raise ValueError("voice-session token must be a non-empty single line")

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []
    replacement = f"VOICE_SESSION_TOKEN={json.dumps(token)}\n"
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("VOICE_SESSION_TOKEN=") or stripped.startswith("export VOICE_SESSION_TOKEN="):
            lines[index] = replacement
            break
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(replacement)

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


def save_setup_files(
    *,
    config_path: Path,
    token_path: Path,
    url: str,
    token: str,
    client_id: str,
    device_id: str,
    session_id: str,
    display_name: str,
    stt_model: str | None = None,
    transport: str | None = None,
    hermes_profile: str | None = None,
) -> None:
    """Persist setup answers without placing the bearer token in YAML."""
    if config_path.exists():
        existing = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if existing is None:
            config: dict[str, Any] = {}
        elif isinstance(existing, dict):
            config = existing
        else:
            raise ValueError(f"config file {config_path} must contain a mapping")
    else:
        config = {}

    config.update(
        {
            "url": url,
            "profile_env": str(token_path),
            "client_id": client_id,
            "device_id": device_id,
            "session_id": session_id,
            "display_name": display_name,
        }
    )
    if stt_model:
        config["stt_model"] = stt_model
    if transport is not None:
        selected_transport = str(transport).strip().lower()
        if selected_transport not in config_module.TRANSPORTS:
            raise ValueError(f"unsupported transport: {transport}")
        config["transport"] = selected_transport
    if hermes_profile is not None:
        selected_hermes_profile = str(hermes_profile).strip()
        if selected_hermes_profile:
            config["hermes_profile"] = selected_hermes_profile
        else:
            config.pop("hermes_profile", None)

    config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_path.write_text(
        "# Generated by `hermes-relay setup`; edit this file to change defaults.\n"
        + yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )
    os.chmod(config_path, 0o600)
    if token:
        _write_private_env(token_path, token)
    elif transport != "home":
        raise ValueError("a bearer token is required outside Home transport")


def run_setup(
    argv: list[str] | None = None,
    *,
    config_path: Path | None = None,
    token_path: Path | None = None,
    input_fn: Any = input,
    secret_fn: Any = getpass.getpass,
    output_fn: Any = print,
    check_connection: bool = True,
    connection_check_fn: Any = None,
) -> int:
    """Ask for connection details and save an editable local setup."""
    parser = argparse.ArgumentParser(prog="hermes-relay setup")
    parser.add_argument(
        "--config",
        type=Path,
        default=config_path or config.DEFAULT_CONFIG_PATH,
        help="editable YAML config path",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=token_path,
        help="private .env path for the bearer token",
    )
    parser.add_argument(
        "--stt-model",
        default=None,
        help=f"local Faster-Whisper model to prepare (default: {DEFAULT_STT_MODEL})",
    )
    parser.add_argument(
        "--transport",
        choices=config.TRANSPORTS,
        default=None,
        help="connection transport; gateway expects a Standard /api/ws endpoint",
    )
    parser.add_argument(
        "--hermes-profile",
        default=None,
        help="Hermes server profile when --transport gateway is selected",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="local relay profile to create or update in a named profile catalog",
    )
    parser.add_argument("--no-check", action="store_true", help="save without testing the relay")
    args = parser.parse_args([] if argv is None else argv)
    config_path = args.config.expanduser()
    if connection_check_fn is None:
        connection_check_fn = probe_connection

    try:
        existing = _existing_config(config_path)
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValueError) as exc:
        output_fn(f"Setup failed: {exc}")
        return 1
    if args.token_file is not None:
        token_path = args.token_file
    elif existing.get("profile_env"):
        token_path = Path(str(existing["profile_env"]))
    else:
        token_path = DEFAULT_TOKEN_ENV_PATH
    token_path = token_path.expanduser()

    output_fn("Hermes Relay setup")
    output_fn(f"Config file: {config_path}")

    try:
        catalog_entries = config._profile_entries(existing)
        catalog_entry_by_name = {
            config.validate_profile_name(str(entry.get("name") or key)): entry
            for key, entry in catalog_entries
        }
        known_profiles = config.load_relay_profiles(
            existing,
            argparse.Namespace(profile_env=token_path),
        )
        profile_by_name = {profile.name: profile for profile in known_profiles}
        requested_profile = (
            config.validate_profile_name(args.profile) if args.profile else None
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        output_fn(f"Setup failed: {exc}")
        return 1

    active_name = str(existing.get("active_profile") or "").strip().lower()
    current_profile = profile_by_name.get(requested_profile or active_name)
    if current_profile is None and known_profiles and requested_profile is None:
        current_profile = known_profiles[0]

    selected_transport = args.transport
    current_entry = (
        catalog_entry_by_name.get(current_profile.name)
        if current_profile is not None
        else None
    )
    if (
        selected_transport is None
        and current_profile is not None
        and current_entry is not None
        and "transport" in current_entry
    ):
        selected_transport = current_profile.transport
    if selected_transport is None and existing.get("transport"):
        selected_transport = str(existing.get("transport")).strip().lower()
    if selected_transport is None:
        choice = _ask(
            input_fn,
            "Connection mode: HomeBridge or Standard Hermes (home/standard)",
        ).lower()
        selected_transport = {
            "home": "home",
            "homebridge": "home",
            "1": "home",
            "standard": "gateway",
            "standard hermes": "gateway",
            "gateway": "gateway",
            "2": "gateway",
        }.get(choice)
        if selected_transport is None:
            output_fn("Setup cancelled: choose HomeBridge or Standard Hermes.")
            return 1
    transport = str(selected_transport).strip().lower()
    if transport not in config.TRANSPORTS:
        output_fn(f"Setup cancelled: unsupported transport '{transport}'.")
        return 1

    target_name = requested_profile
    target_profile = profile_by_name.get(target_name) if target_name else current_profile
    if (
        not catalog_entries
        and requested_profile is None
        and current_profile is not None
        and config._legacy_config_has_connection(existing)
        and current_profile.transport != transport
    ):
        # Root-level settings are a usable default profile. Keep them as a
        # named connection when setup adds a different transport.
        target_name = {
            "gateway": "standard",
            "home": "home",
            "voice-session": "legacy",
        }[transport]
        target_profile = None
    if catalog_entries or requested_profile:
        if target_name is None and target_profile is not None:
            if target_profile.transport == transport:
                target_name = target_profile.name
            else:
                target_profile = None
        if target_name is None:
            suggestion = "standard" if transport == "gateway" else transport
            used = set(profile_by_name)
            default_name = suggestion if suggestion not in used else ""
            target_name = _ask(
                input_fn,
                "Local profile name",
                default=default_name,
            )
            try:
                target_name = config.validate_profile_name(target_name)
            except ValueError as exc:
                output_fn(f"Setup cancelled: {exc}.")
                return 1
            if target_name in used:
                output_fn(
                    f"Setup cancelled: profile '{target_name}' already exists; "
                    "pass --profile to update it."
                )
                return 1
        target_profile = profile_by_name.get(target_name)

    hermes_profile = (
        args.hermes_profile
        if args.hermes_profile is not None
        else (
            target_profile.hermes_profile
            if target_profile is not None
            else (
                str(existing.get("hermes_profile") or "").strip()
                if not catalog_entries and requested_profile is None
                else ""
            )
        )
    ) or None
    if transport == "home":
        from home_pairing_cli import run_pairing_command

        name = target_name or _ask(
            input_fn,
            "New local Home profile name",
            default="home" if "home" not in profile_by_name else "",
        )
        try:
            name = config.validate_profile_name(name)
        except ValueError as exc:
            output_fn(f"Setup cancelled: {exc}.")
            return 1
        label = _ask(input_fn, "Device label shown to the approver", default="Hermes TUI")
        return run_pairing_command(
            ["pair", "--config", str(config_path), "--profile", name, "--label", label],
            input_fn=input_fn,
            secret_fn=secret_fn,
            output_fn=output_fn,
        )

    default_url = (
        target_profile.url
        if target_profile is not None
        else str(existing.get("url") or "")
    )
    url = _ask(input_fn, "Hermes WebSocket URL", default=default_url)
    if not url:
        output_fn("Setup cancelled: a WebSocket URL is required.")
        return 1
    try:
        url = normalize_endpoint(url, transport=transport)
    except ValueError as exc:
        output_fn(f"Setup cancelled: {exc}.")
        return 1

    if transport == "gateway" and not hermes_profile:
        hermes_profile = _ask(
            input_fn,
            "Hermes Profile",
            default="default",
        )

    target_endpoint_matches = False
    if target_profile is not None:
        try:
            target_endpoint_matches = (
                normalize_endpoint(target_profile.url, transport=transport) == url
            )
        except ValueError:
            pass
    profile_identity_matches = (
        target_profile is not None
        and target_profile.transport == transport
        and target_endpoint_matches
        and (
            transport != "gateway"
            or (target_profile.hermes_profile or "default") == hermes_profile
        )
    )
    existing_endpoint_matches = False
    try:
        existing_endpoint_matches = (
            normalize_endpoint(str(existing.get("url") or ""), transport=transport)
            == url
        )
    except ValueError:
        pass

    output_fn("The bearer token is stored separately in a private .env file.")
    output_fn("Copy the WebSocket endpoint and token from the Hermes server setup.")
    if transport == "gateway":
        output_fn(
            "Mode: Standard Hermes at /api/ws (0.21.1, "
            "2237be355906fbe6065ce1815711eee52b2d646e). Typed chat is supported; "
            "local voice is optional and structured prompts are unavailable."
        )

    token = str(
        secret_fn(
            "Bearer token (hidden; leave blank only to reuse a matching connection identity): "
        )
        or ""
    ).strip()
    if not token:
        try:
            if profile_identity_matches and target_profile is not None:
                token = target_profile.token
            elif (
                target_profile is None
                and not catalog_entries
                and requested_profile is None
                and config._legacy_config_has_connection(existing)
                and str(existing.get("transport") or "voice-session").strip().lower()
                == transport
                and existing_endpoint_matches
                and (
                    transport != "gateway"
                    or (
                        str(existing.get("hermes_profile") or "").strip()
                        or "default"
                    )
                    == (hermes_profile or "default")
                )
            ):
                token = config._resolve_token(None, token_path)
        except (OSError, UnicodeDecodeError):
            token = ""
    if not token:
        output_fn("Setup cancelled: a bearer token is required.")
        return 1

    if transport == "gateway":
        # Standard's session.create contract uses source/Profile and ignores
        # the legacy client/device/session identifiers. Keep local schema
        # values without asking users to configure unused wire fields.
        client_id = target_profile.client_id if target_profile else "hermes-relay"
        device_id = target_profile.device_id if target_profile else config.default_device_id()
        session_id = target_profile.session_id if target_profile else "default"
    else:
        client_id = _ask(
            input_fn,
            "Client ID",
            default=(target_profile.client_id if target_profile else str(existing.get("client_id") or "hermes-relay")),
        )
        device_id = (
            target_profile.device_id
            if target_profile
            else str(existing.get("device_id") or config.default_device_id())
        )
        session_id = _ask(
            input_fn,
            "Session ID",
            default=(
                target_profile.session_id
                if profile_identity_matches and target_profile is not None
                else str(existing.get("session_id") or "default")
            ),
        )
    display_name = (
        target_profile.display_name
        if target_profile
        else str(existing.get("display_name") or f"{client_id} relay")
    )

    stt_model = (
        args.stt_model
        or os.getenv("VOICE_SESSION_STT_MODEL")
        or str(existing.get("stt_model") or DEFAULT_STT_MODEL)
    )
    model_path = None
    if transport != "gateway" or args.stt_model is not None:
        output_fn(f"Preparing local speech model '{stt_model}'...")
        try:
            model_path = prepare_stt_model(stt_model)
        except Exception as exc:
            output_fn(f"Setup failed: local speech model could not be prepared: {exc}")
            return 1
    else:
        output_fn(
            "Local microphone capture is optional; install `hermes-relay install voice` "
            "if you want to speak to this Standard Hermes connection."
        )

    try:
        if target_name is not None:
            config.save_relay_profile(
                config_path,
                name=target_name,
                display_name=display_name,
                url=url,
                token=token,
                client_id=client_id,
                device_id=device_id,
                session_id=session_id,
                transport=transport,
                hermes_profile=(hermes_profile or "") if transport == "gateway" else "",
                home_grant="",
                profile_env=token_path,
            )
            config.select_relay_profile(config_path, target_name)
            if model_path is not None and args.stt_model is not None:
                document = _existing_config(config_path)
                document["stt_model"] = stt_model
                config._write_config_document(config_path, document)
        else:
            save_setup_files(
                config_path=config_path,
                token_path=token_path,
                url=url,
                token=token,
                client_id=client_id,
                device_id=device_id,
                session_id=session_id,
                display_name=display_name,
                stt_model=stt_model if model_path is not None else None,
                transport=transport,
                hermes_profile=(hermes_profile or "") if transport == "gateway" else None,
            )
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        output_fn(f"Setup failed: {exc}")
        return 1

    if model_path:
        output_fn(f"Local speech model ready at {model_path}.")
    selected_label = f"profile '{target_name}'" if target_name else "the default profile"
    output_fn(f"Setup complete for {_setup_transport_label(transport)} {selected_label}.")
    if check_connection and not args.no_check and connection_check_fn is not None:
        if transport == "gateway":
            result = connection_check_fn(
                url,
                token,
                client_id,
                device_id,
                session_id,
                transport=transport,
                hermes_profile=hermes_profile,
            )
        else:
            result = connection_check_fn(url, token, client_id, device_id, session_id)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        ok, message = result
        output_fn(message)
        return 0 if ok else 1
    return 0


async def probe_connection(
    url: str,
    token: str,
    client_id: str,
    device_id: str,
    session_id: str,
    *,
    transport: str = "voice-session",
    hermes_profile: str | None = None,
    profile_env: Path | None = None,
    connect_factory: Any = None,
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """Verify credentials and protocol compatibility without sending a turn."""
    connect = connect_factory or config.connect_factory()
    if transport == "home":
        from home_client import HomeClient
        try:
            home = HomeClient(url)
            record = await home.credential()
            _, grants = await home.configuration(record)
            return (True, "Home pairing verified; " + str(sum(g.usable for g in grants)) + " available Profile(s). Bridge readiness is checked on launch.")
        except Exception:
            return False, "Home pairing/configuration could not be verified. Run hermes-relay pair."
    if transport == "gateway":
        from gateway_client import GatewayClient

        gateway = GatewayClient(url, token, connect_factory=connect)
        try:
            await asyncio.wait_for(gateway.connect(), timeout=timeout)
            params: dict[str, Any] = {"source": "tui"}
            if hermes_profile:
                params["profile"] = hermes_profile
            result = await asyncio.wait_for(
                gateway.request("session.create", params),
                timeout=timeout,
            )
            runtime_id = None
            if isinstance(result, dict):
                runtime_id = result.get("session_id") or result.get("runtime_session_id")
            if not runtime_id:
                return False, "Connection failed: gateway session has no runtime identity"
            return True, "Connection verified: Standard gateway ready"
        except Exception:
            # Do not echo an exception containing an authenticated gateway URL.
            return False, "Connection failed: Standard gateway handshake was not verified"
        finally:
            await gateway.close()

    try:
        async with connect(url, **config._connection_kwargs(connect, token)) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "type": "hello",
                        "protocol_version": 1,
                        "client_id": client_id,
                        "device_id": device_id,
                        "session_id": session_id,
                        "display_name": f"{client_id} relay",
                    }
                )
            )
            while True:
                frame = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                if isinstance(frame, bytes):
                    continue
                payload = json.loads(frame)
                break
    except Exception as exc:
        return False, f"Connection failed: {exc}"

    if payload.get("type") != "hello_ack":
        return False, f"Connection failed: {payload.get('error') or 'server rejected hello'}"
    if payload.get("protocol_version") != 1:
        return False, "Connection failed: server does not support protocol v1"
    return True, f"Connection verified: {payload.get('chat_id') or client_id}"
