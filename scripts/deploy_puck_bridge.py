#!/usr/bin/env python3
"""Opt-in tagged Puck bridge release tooling for ops (P-HOME-01).

Installs `puck_bridge` in Home transport as `hermes-puck-bridge.service`.
It never touches the Home browser appliance or any other unit, and never
writes credential values: the operator creates the private env file.
Host execution is explicit; preparing and testing this tool does not
authorize deployment or acceptance.
"""
from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=15"]

SERVICE_USER = "hermes-puck"
UNIT_NAME = "hermes-puck-bridge.service"
RELEASE_ROOT = "/opt/hermes-puck-bridge"
STATE = "/var/lib/hermes-puck-bridge"
ENV_FILE = f"{STATE}/bridge.env"
DEFAULT_PORT = 8766
# 8765: legacy voice-session/display; 8875: Home browser appliance backend.
RESERVED_PORTS = frozenset({8765, 8875})
TAILSCALE = ipaddress.IPv4Network("100.64.0.0/10")
HOME_BRIDGE_PATH = "/api/v1/bridge/ws"


def lan_bind(value: str) -> str:
    """Accept one private LAN IPv4 address; never wildcard, loopback or Tailscale."""
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:
        raise ValueError("--bind must be one LAN IPv4 address") from None
    if str(address) != value:
        raise ValueError("--bind must be one LAN IPv4 address")
    if address.is_unspecified or address.is_loopback or address in TAILSCALE:
        raise ValueError("--bind must not be 0.0.0.0, loopback or a Tailscale address")
    if not address.is_private or address.is_link_local or address.is_multicast or address.is_reserved:
        raise ValueError("--bind must be a private LAN IPv4 address")
    return value


def bridge_port(value: int) -> int:
    if not 1024 <= value <= 65535 or value in RESERVED_PORTS:
        raise ValueError("--port must be 1024-65535 and not 8765 (legacy) or 8875 (browser appliance)")
    return value


def home_bridge_url(value: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme != "wss" or not parts.hostname or parts.username or parts.password
        or parts.query or parts.fragment or parts.path != HOME_BRIDGE_PATH
        or value != value.strip() or any(c.isspace() for c in value)
        or not re.fullmatch(r"[a-z0-9.-]+(?::[0-9]{1,5})?", parts.netloc)
    ):
        raise ValueError(f"--home-url must be an exact wss://<host>{HOME_BRIDGE_PATH} URL")
    try:
        port = parts.port
    except ValueError:
        port = 0
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("--home-url port must be 1-65535")
    return value


def unit(bind: str, port: int, home_url: str) -> str:
    missing = (
        f"hermes-puck-bridge: missing or unsafe {ENV_FILE}; the operator must create it "
        f"(owner {SERVICE_USER}, mode 0600). See docs/puck-ops-deployment.md"
    )
    return f"""[Unit]
Description=Hermes Puck bridge (Home transport)
After=network-online.target
Wants=network-online.target

[Service]
User={SERVICE_USER}
Group={SERVICE_USER}
StateDirectory=hermes-puck-bridge
StateDirectoryMode=0700
UMask=0077
Environment=HOME={STATE}
Environment=XDG_CACHE_HOME={STATE}/cache
Environment=HF_HOME={STATE}/cache/huggingface
EnvironmentFile=-{ENV_FILE}
WorkingDirectory={RELEASE_ROOT}/current
ExecStartPre=/bin/sh -c 'find {ENV_FILE} -maxdepth 0 -type f -user {SERVICE_USER} -perm 0600 2>/dev/null | grep -q . || {{ echo "{missing}" >&2; exit 1; }}'
ExecStart={RELEASE_ROOT}/current/venv/bin/python -m puck_bridge --transport home --host {bind} --port {port} --home-url {home_url}
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths={STATE}

[Install]
WantedBy=multi-user.target
"""


REMOTE = r'''
set -Eeuo pipefail
operation="$1"; commit="$2"; incoming="$3"; bind="$4"; port="$5"; expected_unit="$6"
root=/opt/hermes-puck-bridge
state=/var/lib/hermes-puck-bridge
env_file="$state/bridge.env"
unit=hermes-puck-bridge.service
unit_path="/etc/systemd/system/$unit"
marker=.puck-bridge-v1
created=0; activated=0; target=""
# Before activation, a failed run removes only what it created plus the
# staging upload, so the same tag can be retried. Never an existing release.
cleanup() {
  if [ "$created" = 1 ] && [ "$activated" = 0 ] && [ -n "$target" ]; then sudo rm -rf -- "$target"; fi
  if [ -n "$incoming" ]; then rm -rf -- "$incoming"; fi
}
trap cleanup EXIT
exec 9>"$HOME/.hermes-puck-bridge-deploy.lock"
flock -n 9 || { echo 'Another Puck bridge deployment holds the lock' >&2; exit 1; }
id hermes-puck >/dev/null || { echo 'Create the hermes-puck system user first' >&2; exit 1; }
# Only presence, owner and mode are checked; values are never read here.
sudo test -f "$env_file" || { echo "Missing operator-created $env_file" >&2; exit 1; }
[ "$(sudo stat -c %a "$state")" = 700 ] || { echo "$state must be mode 0700" >&2; exit 1; }
[ "$(sudo stat -c %a "$env_file")" = 600 ] || { echo "$env_file must be mode 0600" >&2; exit 1; }
[ "$(sudo stat -c %U "$env_file")" = hermes-puck ] || { echo "$env_file must be owned by hermes-puck" >&2; exit 1; }
healthy() {
  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
    if sudo systemctl is-active --quiet "$unit" && (exec 3<>"/dev/tcp/$bind/$port") 2>/dev/null; then
      return 0
    fi
    sleep 2
  done
  return 1
}
# GNU readlink -f prints the path itself when `current` does not exist yet;
# on a first deploy that path later resolves to the NEW release, which would
# make `previous` point at `current`. Only a real existing release counts.
old=""
if [ -L "$root/current" ]; then
  old=$(readlink -f "$root/current" || true)
  case "$old" in "$root"/releases/*) ;; *) old="" ;; esac
fi
if [ "$operation" = rollback ]; then
  target=$(readlink -f "$root/previous" || true)
  case "$target" in "$root"/releases/*) ;; *) target="" ;; esac
  [ -n "$target" ] && [ "$target" != "$old" ] && [ -f "$target/$marker" ] || { echo 'No previous Puck bridge release to roll back to' >&2; exit 1; }
  printf '%s' "$expected_unit" | sudo cmp -s - "$target/unit.service" || { echo 'Previous release unit does not match the requested bind/port/Home URL' >&2; exit 1; }
else
  target="$root/releases/$commit"
  [ ! -e "$target" ] || { echo 'Release already exists; refusing overwrite' >&2; exit 1; }
  sudo install -d -m 0755 "$root/releases"
  sudo install -d -m 0755 "$target"
  created=1
  sudo python3.14 -m venv "$target/venv"
  for wheel in "$incoming/"*.whl; do sudo "$target/venv/bin/pip" install "$wheel[voice]"; done
  sudo install -m 0644 "$incoming/unit.service" "$target/unit.service"
  sudo touch "$target/$marker"
fi
activated=1
sudo install -m 0644 "$target/unit.service" "$unit_path"
sudo rm -f -- "$root/current.next"
sudo ln -s "$target" "$root/current.next"
sudo mv -Tf "$root/current.next" "$root/current"
sudo systemctl daemon-reload
if ! { sudo systemctl restart "$unit" && healthy; }; then
  echo 'Puck bridge restart or health check failed; restoring the previous release' >&2
  if [ -n "$old" ] && [ "$old" != "$target" ] && [ -f "$old/$marker" ]; then
    sudo rm -f -- "$root/current.next"
    sudo ln -s "$old" "$root/current.next"
    sudo mv -Tf "$root/current.next" "$root/current"
    sudo install -m 0644 "$old/unit.service" "$unit_path"
    sudo systemctl daemon-reload
    sudo systemctl restart "$unit" || true
  else
    sudo systemctl stop "$unit" || true
    sudo rm -f -- "$root/current" "$unit_path"
    sudo systemctl daemon-reload
  fi
  if [ "$operation" = deploy ]; then sudo rm -rf -- "$target"; fi
  exit 1
fi
sudo systemctl enable "$unit"
if [ -n "$old" ] && [ "$old" != "$target" ] && [ -f "$old/$marker" ]; then
  sudo rm -f -- "$root/previous.next"
  sudo ln -s "$old" "$root/previous.next"
  sudo mv -Tf "$root/previous.next" "$root/previous"
fi
'''


def build_package(tag: str, directory: Path, rendered_unit: str) -> tuple[str, Path]:
    commit = subprocess.check_output(["git", "rev-parse", f"refs/tags/{tag}^{{commit}}"], cwd=ROOT, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("release tag did not resolve to a commit")
    archive_path = directory / "source.tar"
    subprocess.run(["git", "archive", "--format=tar", f"--output={archive_path}", commit], cwd=ROOT, check=True)
    source = directory / "source"
    with tarfile.open(archive_path) as archive:
        archive.extractall(source, filter="data")
    if not (source / "puck_bridge/home_admission.py").is_file():
        raise ValueError("release tag predates the Puck Home transport and claim recovery")
    subprocess.run([sys.executable, "-m", "pytest"], cwd=source, check=True)
    subprocess.run([sys.executable, "-m", "build", "--wheel"], cwd=source, check=True)
    wheels = list((source / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("expected one built wheel")
    package = directory / "package"
    package.mkdir()
    shutil.copy2(wheels[0], package)
    (package / "unit.service").write_text(rendered_unit)
    return commit, package


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("deploy", "rollback"))
    parser.add_argument("--ops-host", required=True)
    parser.add_argument("--bind", required=True, help="ops LAN IPv4 address; never 0.0.0.0, loopback or Tailscale")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="bridge port (default 8766; 8765 and 8875 are prohibited)")
    parser.add_argument("--transport", default="home", help="only 'home' is supported; legacy direct mode is retired")
    parser.add_argument("--home-url", required=True, help=f"paired Home bridge URL, wss://<host>{HOME_BRIDGE_PATH}")
    parser.add_argument("--tag", help="existing vX.Y.Z release tag; required for deploy")
    args = parser.parse_args(argv)
    try:
        if args.transport != "home":
            raise ValueError("only --transport home is supported; legacy direct mode and its voice-session endpoint are retired")
        lan_bind(args.bind)
        bridge_port(args.port)
        home_bridge_url(args.home_url)
        if not re.fullmatch(r"[A-Za-z0-9_.@-]+", args.ops_host):
            raise ValueError("invalid SSH host")
        if args.operation == "deploy" and (not args.tag or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", args.tag)):
            raise ValueError("deploy requires an existing vX.Y.Z release tag")
        rendered = unit(args.bind, args.port, args.home_url)
        ssh = ["ssh", *SSH_OPTIONS, args.ops_host]
        with tempfile.TemporaryDirectory(prefix="hermes-puck-release-") as temporary:
            commit = ""
            incoming = ""
            if args.operation == "deploy":
                commit, package = build_package(args.tag, Path(temporary), rendered)
                incoming = subprocess.check_output([*ssh, "mktemp -d /tmp/hermes-puck-release.XXXXXX"], text=True).strip()
                if not re.fullmatch(r"/tmp/hermes-puck-release\.[A-Za-z0-9]+", incoming):
                    raise ValueError("invalid remote staging directory")
                try:
                    subprocess.run(["scp", *SSH_OPTIONS, "-r", str(package) + "/.", f"{args.ops_host}:{incoming}/"], check=True)
                except (OSError, subprocess.CalledProcessError):
                    # The remote script owns staging cleanup only once it runs;
                    # a failed upload must not strand the mktemp directory.
                    subprocess.run([*ssh, "rm -rf -- " + shlex.quote(incoming)], check=False)
                    raise
            remote = "bash -s -- " + shlex.join([args.operation, commit, incoming, args.bind, str(args.port), rendered])
            subprocess.run([*ssh, remote], input=REMOTE, text=True, check=True)
        print(f"{UNIT_NAME} active and listening on {args.bind}:{args.port}. Live Puck/Home gates remain with their owning stories.")
        return 0
    except ValueError as error:
        print(f"Puck bridge deployment refused: {error}", file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError, RuntimeError):
        print("Puck bridge deployment failed; see the output above. Nothing is activated before a successful upload, and a failed restart or health check restores the previous release.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
