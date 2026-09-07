"""Terminal configuration commands for named Hermes relay profiles."""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import sys
from typing import Any

import config
from setup_wizard import normalize_endpoint


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    # The top-level option handles `profile --config path list`; the suppressed
    # copy lets the equally natural `profile list --config path` work too.
    parser.add_argument(
        "--config",
        type=Path,
        default=argparse.SUPPRESS,
        help="YAML config file for relay profiles",
    )


def _add_profile_fields(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", help="WebSocket endpoint")
    parser.add_argument("--display-name", help="human-readable profile label")
    parser.add_argument("--client-id", help="Hermes client identity")
    parser.add_argument("--device-id", help="machine/device identity")
    parser.add_argument("--session-id", help="Hermes session identity")
    parser.add_argument("--model", help="configured model hint")
    parser.add_argument(
        "--wake-phrases",
        help="comma-separated wake phrases for this profile",
    )
    parser.add_argument("--token-env", help="private env variable containing the bearer token")
    parser.add_argument(
        "--profile-env",
        type=Path,
        help="private env file for the bearer token",
    )


def build_profile_parser(argv: list[str] | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-relay profile")
    _add_config_argument(parser)
    default_config = config.config_path_from_argv(argv)
    parser.set_defaults(config=default_config)
    commands = parser.add_subparsers(dest="action", required=True)

    list_parser = commands.add_parser("list", aliases=("ls",), help="list saved profiles")
    _add_config_argument(list_parser)

    migrate_parser = commands.add_parser(
        "migrate",
        help="convert the legacy single-profile config to a named default",
    )
    _add_config_argument(migrate_parser)

    select_parser = commands.add_parser(
        "select",
        aliases=("use", "switch"),
        help="choose the profile used by future launches",
    )
    _add_config_argument(select_parser)
    select_parser.add_argument("name", help="profile name")

    create_parser = commands.add_parser(
        "create",
        aliases=("add",),
        help="create a named profile",
    )
    _add_config_argument(create_parser)
    create_parser.add_argument("name", help="new profile name")
    _add_profile_fields(create_parser)

    edit_parser = commands.add_parser("edit", help="edit a saved profile")
    _add_config_argument(edit_parser)
    edit_parser.add_argument("name", help="profile name")
    _add_profile_fields(edit_parser)

    delete_parser = commands.add_parser(
        "delete",
        aliases=("remove",),
        help="delete a saved profile",
    )
    _add_config_argument(delete_parser)
    delete_parser.add_argument("name", help="profile name")
    delete_parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm deletion of the profile and its private token entry",
    )

    return parser


def _profile_for_name(config_path: Path, name: str) -> config.RelayProfile:
    document = config.load_config_file(config_path)
    canonical = config.validate_profile_name(name)
    profiles = config.load_relay_profiles(document)
    try:
        return next(profile for profile in profiles if profile.name == canonical)
    except StopIteration as exc:
        available = ", ".join(profile.name for profile in profiles) or "none"
        raise ValueError(f"unknown relay profile: {canonical}; available: {available}") from exc


def _configured_names(config_path: Path) -> set[str]:
    document = config.load_config_file(config_path)
    return {
        config.validate_profile_name(str(entry.get("name") or key))
        for key, entry in config._profile_entries(document)
    }


def _render_profiles(profiles: list[config.RelayProfile], active: str | None) -> str:
    lines = ["Relay profiles:"]
    for profile in profiles:
        marker = "*" if profile.name == active else " "
        token_state = (
            f"token configured via {profile.token_env}"
            if profile.token_configured
            else f"token missing ({profile.token_env})"
        )
        endpoint = profile.url.split("?", 1)[0]
        lines.append(
            f"{marker} {profile.name} — {profile.display_name} · {endpoint} · "
            f"client {profile.client_id} · device {profile.device_id} · "
            f"session {profile.session_id} · {token_state}"
        )
    return "\n".join(lines)


def _required_create_value(
    value: str | None,
    question: str,
    *,
    default: str = "",
    input_fn: Any,
) -> str:
    if value is not None:
        return str(value).strip()
    suffix = f" [{default}]" if default else ""
    return str(input_fn(f"{question}{suffix}: ") or "").strip() or default


def _profile_fields_for_create(args: argparse.Namespace, *, input_fn: Any) -> dict[str, str]:
    name = config.validate_profile_name(args.name)
    url = _required_create_value(args.url, "WebSocket endpoint", input_fn=input_fn)
    display_name = _required_create_value(
        args.display_name,
        "Display name",
        default=name.capitalize(),
        input_fn=input_fn,
    )
    client_id = _required_create_value(
        args.client_id,
        "Client ID",
        default=f"{name}-relay",
        input_fn=input_fn,
    )
    device_id = _required_create_value(
        args.device_id,
        "Device ID",
        default=config.default_device_id(),
        input_fn=input_fn,
    )
    session_id = _required_create_value(
        args.session_id,
        "Session ID",
        default=f"{name}-session",
        input_fn=input_fn,
    )
    if not url or not display_name or not client_id or not device_id or not session_id:
        raise ValueError("endpoint, display name, client ID, device ID, and session ID are required")
    return {
        "name": name,
        "url": normalize_endpoint(url),
        "display_name": display_name,
        "client_id": client_id,
        "device_id": device_id,
        "session_id": session_id,
    }


def _profile_fields_for_edit(
    args: argparse.Namespace,
    existing: config.RelayProfile,
) -> dict[str, str]:
    url = normalize_endpoint(args.url) if args.url else existing.url
    return {
        "name": existing.name,
        "url": url,
        "display_name": str(args.display_name or existing.display_name),
        "client_id": str(args.client_id or existing.client_id),
        "device_id": str(args.device_id or existing.device_id),
        "session_id": str(args.session_id or existing.session_id),
    }


def run_profile_command(
    argv: list[str] | None = None,
    *,
    input_fn: Any = input,
    secret_fn: Any = getpass.getpass,
    output_fn: Any = print,
) -> int:
    """Run the non-Textual profile configuration surface."""
    command_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_profile_parser(command_argv)
    args = parser.parse_args(command_argv)
    config_path = Path(args.config).expanduser()

    try:
        if args.action in ("list", "ls"):
            document = config.load_config_file(config_path)
            profiles = config.load_relay_profiles(document)
            active = str(document.get("active_profile") or profiles[0].name)
            output_fn(_render_profiles(profiles, active))
            return 0

        if args.action == "migrate":
            profile = config.migrate_legacy_profile_config(config_path)
            output_fn(
                f"Migrated the legacy connection to profile '{profile.name}'. "
                f"Endpoint: {profile.url.split('?', 1)[0]}."
            )
            return 0

        if args.action in ("select", "use", "switch"):
            profile = config.select_relay_profile(config_path, args.name)
            output_fn(
                f"Selected profile '{profile.name}'. "
                f"Endpoint: {profile.url.split('?', 1)[0]}; session: {profile.session_id}."
            )
            return 0

        if args.action in ("create", "add"):
            name = config.validate_profile_name(args.name)
            if name in _configured_names(config_path):
                raise ValueError(f"relay profile already exists: {name}")
            fields = _profile_fields_for_create(args, input_fn=input_fn)
            token = str(secret_fn("Bearer token (hidden; leave blank to cancel): ") or "").strip()
            if not token:
                output_fn("Profile creation cancelled: a bearer token is required.")
                return 1
            profile = config.save_relay_profile(
                config_path,
                **fields,
                token=token,
                model=args.model,
                wake_phrases=args.wake_phrases,
                token_env=args.token_env,
                profile_env=args.profile_env,
            )
            output_fn(
                f"Created profile '{profile.name}'. "
                f"Endpoint: {profile.url.split('?', 1)[0]}; token stored in private env."
            )
            return 0

        if args.action == "edit":
            existing = _profile_for_name(config_path, args.name)
            fields = _profile_fields_for_edit(args, existing)
            token = str(secret_fn("Bearer token (hidden; leave blank to keep it): ") or "").strip()
            profile = config.save_relay_profile(
                config_path,
                **fields,
                token=token or None,
                model=args.model,
                wake_phrases=args.wake_phrases,
                token_env=args.token_env,
                profile_env=args.profile_env,
            )
            output_fn(
                f"Updated profile '{profile.name}'. "
                f"Endpoint: {profile.url.split('?', 1)[0]}; token stored in private env."
            )
            return 0

        if args.action in ("delete", "remove"):
            if not args.yes:
                output_fn(
                    "Refusing to delete a relay profile without confirmation; "
                    "repeat with --yes."
                )
                return 2
            name = config.validate_profile_name(args.name)
            config.delete_relay_profile(config_path, name)
            output_fn(f"Deleted profile '{name}'.")
            return 0

        raise ValueError(f"unknown profile action: {args.action}")
    except (OSError, UnicodeDecodeError, ValueError, SystemExit) as exc:
        if isinstance(exc, SystemExit):
            output_fn(str(exc))
        else:
            output_fn(f"Profile command failed: {exc}")
        return 1


__all__ = ["build_profile_parser", "run_profile_command"]


def main() -> int:
    return run_profile_command()


if __name__ == "__main__":
    raise SystemExit(main())
