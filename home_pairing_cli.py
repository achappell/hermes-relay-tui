"""Explicit Home enrollment and local forgetting, with hidden code input."""
from __future__ import annotations

import argparse
import asyncio
import getpass
from pathlib import Path
import time
import warnings
import shlex
from typing import Any
from urllib.parse import parse_qs, urlsplit
import uuid

import config
from home_client import HomeClient, HomeError, PairingRecord, SecurePairings, canonical_home, bridge_url, parse_grants, _string, _timestamp, secure_call


def parse_pairing_input(value: str, code: str = "") -> tuple[str, str]:
    if value.startswith("hermes-home:"):
        try:
            p = urlsplit(value)
            fields = parse_qs(p.query, strict_parsing=True)
            if p.scheme != "hermes-home" or p.netloc != "pair" or p.path or p.fragment or set(fields) != {"home", "code"} or any(len(v) != 1 for v in fields.values()):
                raise ValueError
            return canonical_home(fields["home"][0]), _string(fields["code"][0], 256)
        except (ValueError, HomeError):
            raise ValueError("Invalid Home pairing link") from None
    return canonical_home(value), _string(code, 256)


async def pair(home: str, code: str, *, label: str, output_fn: Any = print, timeout: float = 300) -> list:
    client = HomeClient(home)
    async with client.store.locked(client.home):
        if await asyncio.to_thread(client.store.load, client.home) is not None:
            raise HomeError("pairing_exists")
        # Exercise the selected native store before consuming a single-use grant.
        probe_name = client.home + "/storage-probe-" + uuid.uuid4().hex
        try:
            await asyncio.to_thread(client.store.backend.set_password, "hermes-relay-tui.home.probe", probe_name, "probe")
            value = await asyncio.to_thread(client.store.backend.get_password, "hermes-relay-tui.home.probe", probe_name)
            if value != "probe":
                raise HomeError("secure_store")
            await asyncio.to_thread(client.store.backend.delete_password, "hermes-relay-tui.home.probe", probe_name)
        except Exception:
            raise HomeError("secure_store") from None
        request = await client.request("POST", "/api/v1/enrollment/requests", {"schema": 1, "enrollment_code": code, "endpoint_id": "tui-" + uuid.uuid4().hex, "label": _string(label, 128), "type": "tui", "requested_rooms": [], "requested_capabilities": ["client_claim"], "secure_storage": "platform_secure_store"})
        request_id = _string(request.get("request_id"), 128)
        confirmation = _string(request.get("confirmation_code"), 64)
        expiry = _timestamp(request.get("expires_at"))
        output_fn(f"Home: {client.home}\nDevice: {label}\nConfirmation code: {confirmation}\nApprove this device and its Profiles on Home's pairing page after comparing the code.")
        deadline = time.monotonic() + max(0, min(timeout, expiry - time.time()))
        from urllib.parse import quote
        while time.monotonic() < deadline:
            try:
                material = await client.request("POST", f"/api/v1/enrollment/requests/{quote(request_id, safe='')}/consume", {"schema": 1, "enrollment_code": code, "secure_storage": "platform_secure_store"})
            except HomeError as exc:
                if exc.code != "approval_pending":
                    if exc.code in {"transport", "invalid_response", "service_unavailable"}:
                        output_fn("Approval consumption could not be confirmed. Home may already have issued this single-use credential. Check Home's page and revoke any unused device before pairing again.")
                    raise
                await asyncio.sleep(min(2, max(0, deadline - time.monotonic())))
                continue
            try:
                record = PairingRecord.material(client.home, material)
                grants = parse_grants(material.get("client_grants", []))
                if record.expires_at <= time.time():
                    raise HomeError("invalid_response")
                await secure_call(client.store.save, record)
            except Exception:
                raise HomeError("storage_after_consume") from None
            return grants
        raise HomeError("request_expired")


def _hidden_input(secret_fn: Any, prompt: str) -> str:
    if secret_fn is not getpass.getpass:
        return str(secret_fn(prompt) or "").strip()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return str(secret_fn(prompt) or "").strip()
    except getpass.GetPassWarning:
        raise ValueError("Hidden input is unavailable. Run pairing from an interactive terminal; pairing material will not be read with echo enabled") from None


def _config_recovery_command(args: Any, home: str, selected: str) -> str:
    path = str(args.config)
    local_home = str(Path.home())
    if path.startswith(local_home + "/"):
        path = "~" + path[len(local_home):]
    return shlex.join(["hermes-relay", "profile", "add", args.profile, "--config", path, "--transport", "home", "--url", bridge_url(home), "--home-grant", selected or "<approved-selection-id>"])


def run_pairing_command(argv: list[str] | None = None, *, input_fn: Any = input, secret_fn: Any = getpass.getpass, output_fn: Any = print) -> int:
    parser = argparse.ArgumentParser(prog="hermes-relay")
    commands = parser.add_subparsers(dest="action", required=True)
    pairing = commands.add_parser("pair", help="Pair with Home using its page's link or short code")
    pairing.add_argument("--home", help="HTTPS Home address (code is entered privately)")
    pairing.add_argument("--label", default="Hermes TUI")
    pairing.add_argument("--profile", default="home", help="new local relay profile name")
    pairing.add_argument("--config", type=Path, default=config.DEFAULT_CONFIG_PATH)
    unpairing = commands.add_parser("unpair", help="Forget this Home locally; server revocation is on Home's page")
    unpairing.add_argument("--home", required=True)
    args = parser.parse_args(argv)
    home = ""
    selected = ""
    paired = False
    try:
        if args.action == "unpair":
            home = canonical_home(args.home)
            async def forget():
                store = SecurePairings()
                async with store.locked(home):
                    await secure_call(store.delete, home)
            asyncio.run(forget())
            output_fn("Forgot this Home on this computer. Close existing TUI windows. This does not revoke the device on Home; revoke it on Home's device/pairing page. Saved history and public profiles remain.")
            return 0
        name = config.validate_profile_name(args.profile)
        document = config.load_config_file(args.config.expanduser())
        if name in {str(entry.get("name") or key) for key, entry in config._profile_entries(document)}:
            raise ValueError("That local relay profile already exists; choose a new --profile name")
        value = args.home or _hidden_input(secret_fn, "Paste the Home pairing link, or enter its HTTPS address (hidden): ")
        code = "" if value.startswith("hermes-home:") else _hidden_input(secret_fn, "Home enrollment code (hidden): ")
        home, code = parse_pairing_input(value, code)
        grants = asyncio.run(pair(home, code, label=args.label, output_fn=output_fn))
        paired = True
        for index, grant in enumerate(grants, 1):
            output_fn(f"{index}. {grant.label} — {grant.status} (selection: {grant.grant_id})" + ("" if grant.available else " (unavailable)"))
        usable = [g for g in grants if g.usable]
        selected = usable[0].grant_id if len(usable) == 1 else ""
        if len(usable) > 1:
            choice = str(input_fn("Profile label or selection ID to use: ") or "").strip()
            if sum(choice in {g.label, g.grant_id} for g in usable) != 1:
                output_fn("Pairing saved securely; no Profile selected. Choose an available label with --home-grant on launch.")
            else:
                selected = next(g.grant_id for g in usable if choice in {g.label, g.grant_id})
        config.save_home_profile(args.config, name=name, home=home, grant_label=selected, display_name=args.label)
        output_fn(f"Paired securely. Launch with: hermes-relay --profile {name}" + ("" if selected else " --home-grant <approved-label>"))
        return 0
    except (HomeError, ValueError, OSError, SystemExit):
        import sys
        exc = sys.exception()
        output_fn(f"Home pairing: {exc}" if isinstance(exc, (HomeError, ValueError)) else "Home pairing: local configuration could not be saved. If approval completed, the credential may already be in secure storage.")
        if args.action == "pair" and home:
            output_fn("If the credential is saved, restore only the missing public profile with: " + _config_recovery_command(args, home, selected))
        return 1
    except (KeyboardInterrupt, EOFError):
        output_fn("Pairing stopped. " + ("The credential was saved; public configuration may still be missing." if paired else "If consumption was interrupted, check whether the credential was saved before enrolling again."))
        if args.action == "pair" and home:
            output_fn("If the credential is saved, restore only the missing public profile with: " + _config_recovery_command(args, home, selected))
        return 1
