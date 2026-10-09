#!/usr/bin/env python3
"""Opt-in tagged Home browser release tooling; never touches legacy units/tokens.

This is the pre-R6 supported Home path. Host execution is explicit; preparing
and testing this tool does not authorize deployment or acceptance.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlsplit

from check_ops_web import run_check
from validate_ops_profile_config import read_home_catalog

ROOT = Path(__file__).resolve().parents[1]


def tailnet_origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not re.fullmatch(r"[a-z0-9-]+\.[a-z0-9-]+\.ts\.net", parsed.hostname or "") or parsed.port not in {None, 443} or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("expected an exact household Tailscale HTTPS origin")
    return value


def unit(origin: str, home: str, port: int) -> str:
    return f"""[Unit]
Description=Hermes Home browser appliance (Home admission)
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=hermes-home
Group=hermes-home
StateDirectory=hermes-home-browser
StateDirectoryMode=0700
UMask=0077
WorkingDirectory=/opt/hermes-home-browser/current
ExecStart=/opt/hermes-home-browser/current/venv/bin/hermes-relay-home --browser-voice --browser-transport home --home-bridge-url {home.replace('https://', 'wss://')}/api/v1/bridge/ws --home-device-credential-file /var/lib/hermes-home-browser/pairing.json --config /var/lib/hermes-home-browser/shortcuts.yaml --display-host 127.0.0.1 --display-port {port} --display-public-origin {origin}
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/hermes-home-browser

[Install]
WantedBy=multi-user.target
"""


def validate_serve(status: dict, origin: str, port: int) -> None:
    host = urlsplit(origin).hostname + ":443"
    if any(status.get("AllowFunnel", {}).values()):
        raise ValueError("Tailscale Funnel must be disabled")
    route = status.get("Web", {}).get(host, {}).get("Handlers", {}).get("/", {})
    handlers = status.get("Web", {}).get(host, {}).get("Handlers", {})
    if set(handlers) != {"/"} or route.get("Proxy") != f"http://127.0.0.1:{port}":
        raise ValueError("pre-existing Tailscale Serve route must target the exact isolated loopback backend")


REMOTE = r'''
set -Eeuo pipefail
operation="$1"; commit="$2"; incoming="$3"; port="$4"
root=/opt/hermes-home-browser
state=/var/lib/hermes-home-browser
unit=hermes-home-browser.service
sudo install -d -m 0755 "$root/releases"
exec 9>"$HOME/.hermes-home-browser-deploy.lock"
flock -n 9
# A new service/port is intentional: never activate the dead legacy rollback.
id hermes-home >/dev/null
sudo -u hermes-home test -r "$state/pairing.json"
[ "$(sudo stat -c %a "$state")" = 700 ]
[ "$(sudo stat -c %a "$state/pairing.json")" = 600 ]
[ "$(sudo stat -c %U "$state/pairing.json")" = hermes-home ]
old=$(readlink -f "$root/current" || true)
if [ "$operation" = rollback ]; then
  target=$(readlink -f "$root/previous" || true)
  [ -n "$target" ] && [ -f "$target/.home-browser-v1" ] || { echo 'No compatible Home rollback; leave safe unavailable page running' >&2; exit 1; }
else
  target="$root/releases/$commit"
  [ ! -e "$target" ] || { echo 'Release already exists; refusing overwrite' >&2; exit 1; }
  sudo install -d -m 0755 "$target"
  sudo python3.14 -m venv "$target/venv"
  sudo "$target/venv/bin/pip" install "$incoming/"*.whl
  sudo touch "$target/.home-browser-v1"
  sudo install -m 0644 "$incoming/unit.service" "$target/unit.service"
  if [ -f "$incoming/shortcuts.yaml" ]; then
    sudo install -o hermes-home -g hermes-home -m 0600 "$incoming/shortcuts.yaml" "$state/shortcuts.yaml"
  elif ! sudo test -e "$state/shortcuts.yaml"; then
    printf 'version: 1\nprofiles: {}\n' | sudo -u hermes-home tee "$state/shortcuts.yaml" >/dev/null
  fi
fi
sudo install -m 0644 "$target/unit.service" "/etc/systemd/system/$unit"
sudo ln -s "$target" "$root/current.next"
sudo mv -Tf "$root/current.next" "$root/current"
sudo systemctl daemon-reload
if ! sudo systemctl restart "$unit"; then
  if [ -n "$old" ] && [ -f "$old/.home-browser-v1" ]; then
    sudo ln -s "$old" "$root/current.next"
    sudo mv -Tf "$root/current.next" "$root/current"
    sudo install -m 0644 "$old/unit.service" "/etc/systemd/system/$unit"
    sudo systemctl daemon-reload
    sudo systemctl restart "$unit"
  fi
  exit 1
fi
if [ -n "$old" ] && [ -f "$old/.home-browser-v1" ]; then
  sudo ln -s "$old" "$root/previous.next"
  sudo mv -Tf "$root/previous.next" "$root/previous"
fi
if [ -n "$incoming" ]; then rm -rf -- "$incoming"; fi
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("deploy", "rollback"))
    parser.add_argument("--ops-host", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--tag", help="existing release tag; required for deploy")
    parser.add_argument("--port", type=int, default=8875, help="dedicated loopback port; legacy 8765 is prohibited")
    parser.add_argument("--shortcuts", type=Path, help="optional service-local ID-bound wake shortcuts; never token env")
    args = parser.parse_args(argv)
    try:
        tailnet_origin(args.origin)
        tailnet_origin(args.home)
        if not re.fullmatch(r"[A-Za-z0-9_.@-]+", args.ops_host) or not 1024 <= args.port <= 65535 or args.port == 8765:
            raise ValueError("invalid SSH host or isolated backend port")
        if args.shortcuts:
            read_home_catalog(args.shortcuts)
        if args.operation == "deploy" and (not args.tag or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", args.tag)):
            raise ValueError("deploy requires an existing vX.Y.Z release tag")
        ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", args.ops_host]
        serve = subprocess.check_output([*ssh, "tailscale serve status --json"], text=True)
        validate_serve(json.loads(serve), args.origin, args.port)
        with tempfile.TemporaryDirectory(prefix="hermes-home-release-") as temporary:
            directory = Path(temporary)
            incoming = ""
            commit = ""
            if args.operation == "deploy":
                commit = subprocess.check_output(["git", "rev-parse", f"refs/tags/{args.tag}^{{commit}}"], cwd=ROOT, text=True).strip()
                archive_path = directory / "source.tar"
                subprocess.run(["git", "archive", "--format=tar", f"--output={archive_path}", commit], cwd=ROOT, check=True)
                source = directory / "source"
                with tarfile.open(archive_path) as archive:
                    archive.extractall(source, filter="data")
                if not (source / "home_display/home_admission.py").is_file():
                    raise ValueError("release tag predates the supported Home admission contract")
                web = source / "home_display/web"
                for command in (["npm", "ci"], ["npm", "test"], ["npm", "run", "check"], ["npm", "run", "build"]):
                    subprocess.run(command, cwd=web, check=True)
                subprocess.run([sys.executable, "-m", "pytest"], cwd=source, check=True)
                subprocess.run([sys.executable, "-m", "build", "--wheel"], cwd=source, check=True)
                package = directory / "package"
                package.mkdir()
                wheels = list((source / "dist").glob("*.whl"))
                if len(wheels) != 1:
                    raise ValueError("expected one built wheel")
                import shutil
                shutil.copy2(wheels[0], package)
                (package / "unit.service").write_text(unit(args.origin, args.home, args.port))
                if args.shortcuts:
                    shutil.copy2(args.shortcuts, package / "shortcuts.yaml")
                incoming = subprocess.check_output([*ssh, "mktemp -d /tmp/hermes-home-release.XXXXXX"], text=True).strip()
                if not re.fullmatch(r"/tmp/hermes-home-release\.[A-Za-z0-9]+", incoming):
                    raise ValueError("invalid remote staging directory")
                subprocess.run(["scp", "-r", str(package) + "/.", f"{args.ops_host}:{incoming}/"], check=True)
            remote = "bash -s -- " + shlex.join([args.operation, commit, incoming, str(args.port)])
            subprocess.run([*ssh, remote], input=REMOTE, text=True, check=True)
        # Home-down health never triggers rollback to a legacy build. Keep the
        # new package's honest unavailable page and report acceptance failure.
        asyncio.run(run_check(args.origin, home=True))
        print("Home package active; admission smoke passed. S7 hardware/network/monitoring acceptance and R6 bake remain open.")
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, RuntimeError):
        print("Home deployment or admission check failed. No legacy rollback is supported; inspect the safe unavailable page and Home-only rollback target.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
