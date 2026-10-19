"""Repository-local Puck bridge deploy contract; never opens SSH or changes a host."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shlex
import socket
import subprocess
import sys

import pytest

from puck_bridge.server import build_arg_parser

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("deploy_puck_bridge", SCRIPTS / "deploy_puck_bridge.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)

BIND = "192.168.1.20"
HOME_URL = "wss://home.household.ts.net/api/v1/bridge/ws"
SECRET_KEYS = ("PUCK_DEVICE_TOKEN", "HOME_DEVICE_CREDENTIAL", "HOME_CONVERSATION_HANDLE",
               "HOME_DEVICE_ID", "HOME_WAKE_MAPPING_ID", "VOICE_SESSION", "--token",
               "--home-device-credential-file", "--home-conversation-handle", "Authorization")


def rendered(bind=BIND, port=8766, home=HOME_URL):
    return deploy.unit(bind, port, home)


def directives(text):
    return [line for line in text.splitlines() if "=" in line and not line.startswith("#")]


def test_unit_is_hardened_lan_bound_home_only_and_secret_free():
    text = rendered()
    lines = directives(text)
    for required in (
        "User=hermes-puck", "Group=hermes-puck",
        "StateDirectory=hermes-puck-bridge", "StateDirectoryMode=0700", "UMask=0077",
        "NoNewPrivileges=true", "ProtectSystem=strict", "ProtectHome=true", "PrivateTmp=true",
        "ReadWritePaths=/var/lib/hermes-puck-bridge",
        "EnvironmentFile=-/var/lib/hermes-puck-bridge/bridge.env",
        "Environment=HOME=/var/lib/hermes-puck-bridge",
        "Environment=XDG_CACHE_HOME=/var/lib/hermes-puck-bridge/cache",
        "Environment=HF_HOME=/var/lib/hermes-puck-bridge/cache/huggingface",
        "Restart=on-failure", "After=network-online.target", "Wants=network-online.target",
    ):
        assert required in lines
    assert [line for line in lines if line.startswith("ReadWritePaths=")] == ["ReadWritePaths=/var/lib/hermes-puck-bridge"]
    exec_start = next(line for line in lines if line.startswith("ExecStart="))
    assert exec_start == (
        "ExecStart=/opt/hermes-puck-bridge/current/venv/bin/python -m puck_bridge "
        f"--transport home --host {BIND} --port 8766 --home-url {HOME_URL}"
    )
    for forbidden in (*SECRET_KEYS, "0.0.0.0", "127.0.0.1", "legacy", "hermes-home", "8765", "8875"):
        assert forbidden not in text


def test_exec_start_uses_only_real_bridge_flags():
    exec_start = next(line for line in directives(rendered()) if line.startswith("ExecStart="))
    argv = shlex.split(exec_start.removeprefix("ExecStart="))
    assert argv[1:3] == ["-m", "puck_bridge"]
    args, remaining = build_arg_parser().parse_known_args(argv[3:])
    assert remaining == []
    assert (args.transport, args.host, args.port, args.home_url) == ("home", BIND, 8766, HOME_URL)
    assert args.play_on_device is True


def pre_start(env_file, user):
    line = next(line for line in directives(rendered()) if line.startswith("ExecStartPre="))
    command = line.removeprefix("ExecStartPre=")
    command = command.replace("/var/lib/hermes-puck-bridge/bridge.env", str(env_file)).replace("-user hermes-puck", f"-user {user}")
    return subprocess.run(shlex.split(command), capture_output=True, text=True)


def test_pre_start_fails_clearly_without_a_private_operator_env_file(tmp_path):
    import getpass

    env_file = tmp_path / "bridge.env"
    missing = pre_start(env_file, getpass.getuser())
    assert missing.returncode != 0
    assert "missing or unsafe" in missing.stderr and "docs/puck-ops-deployment.md" in missing.stderr
    env_file.write_text("")
    env_file.chmod(0o644)
    assert pre_start(env_file, getpass.getuser()).returncode != 0
    env_file.chmod(0o600)
    assert pre_start(env_file, getpass.getuser()).returncode == 0


@pytest.mark.parametrize("bind", ["0.0.0.0", "127.0.0.1", "127.1.2.3", "100.64.0.1", "100.101.102.103",
                                  "100.127.255.254", "8.8.8.8", "169.254.1.1", "::1", "fd00::1",
                                  "192.168.1.20/24", " 192.168.1.20", "192.168.001.020", "ops.local", ""])
def test_bind_must_be_one_lan_ipv4_address(bind):
    with pytest.raises(ValueError):
        deploy.lan_bind(bind)


@pytest.mark.parametrize("bind", ["192.168.1.20", "10.0.0.5", "172.16.4.2"])
def test_lan_bind_accepted(bind):
    assert deploy.lan_bind(bind) == bind


@pytest.mark.parametrize("port", [8765, 8875, 80, 1023, 65536, 0])
def test_reserved_and_privileged_ports_rejected(port):
    with pytest.raises(ValueError):
        deploy.bridge_port(port)


def test_default_port_is_8766():
    assert deploy.DEFAULT_PORT == 8766
    assert deploy.bridge_port(8766) == 8766


@pytest.mark.parametrize("url", ["ws://home.example/api/v1/bridge/ws", "https://home.example/api/v1/bridge/ws",
                                 "wss://home.example/", "wss://home.example/api/v1/bridge/ws?token=x",
                                 "wss://user:pw@home.example/api/v1/bridge/ws", "wss://home.example/api/v1/bridge/ws#x",
                                 "wss://HOME.example/api/v1/bridge/ws", "wss://home.example/api/v1/bridge/ws\n"])
def test_home_url_is_exact_bridge_websocket(url):
    with pytest.raises(ValueError):
        deploy.home_bridge_url(url)


def forbid_host_contact(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("must not contact a host or build")
    monkeypatch.setattr(deploy.subprocess, "run", fail)
    monkeypatch.setattr(deploy.subprocess, "check_output", fail)


@pytest.mark.parametrize("extra", [
    ["--transport", "legacy"], ["--transport", "voice-session"], ["--bind", "0.0.0.0"],
    ["--bind", "100.100.1.1"], ["--port", "8765"], ["--port", "8875"],
    ["--home-url", "wss://home.example/v1/voice-session"],
])
def test_cli_rejects_invalid_arguments_before_any_host_contact(monkeypatch, capsys, extra):
    forbid_host_contact(monkeypatch)
    argv = ["rollback", "--ops-host", "ops", "--bind", BIND, "--home-url", HOME_URL, *extra]
    assert deploy.main(argv) == 1
    assert "refused" in capsys.readouterr().err


def test_deploy_requires_release_tag(monkeypatch):
    forbid_host_contact(monkeypatch)
    for tag in ([], ["--tag", "main"], ["--tag", "v1.2"]):
        assert deploy.main(["deploy", "--ops-host", "ops", "--bind", BIND, "--home-url", HOME_URL, *tag]) == 1


def test_deploy_cli_uploads_package_and_runs_remote_with_rendered_unit(monkeypatch, tmp_path):
    calls = []
    package = tmp_path / "package"

    def build(tag, directory, unit_text):
        assert tag == "v0.14.0"
        assert unit_text == rendered()
        return "a" * 40, package

    def output(command, **kwargs):
        calls.append(command)
        return "/tmp/hermes-puck-release.AbC123\n"

    monkeypatch.setattr(deploy, "build_package", build)
    monkeypatch.setattr(deploy.subprocess, "check_output", output)
    monkeypatch.setattr(deploy.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))
    assert deploy.main(["deploy", "--ops-host", "ops", "--bind", BIND, "--home-url", HOME_URL, "--tag", "v0.14.0"]) == 0
    assert calls[0][:2] == ["ssh", "-o"] and "StrictHostKeyChecking=yes" in calls[0]
    assert calls[1][0][0] == "scp"
    command, options = calls[2]
    remote = shlex.split(command[-1])
    assert remote == ["bash", "-s", "--", "deploy", "a" * 40, "/tmp/hermes-puck-release.AbC123", BIND, "8766", rendered()]
    assert options["input"] == deploy.REMOTE


def test_build_refuses_tag_without_home_claim_recovery(monkeypatch, tmp_path):
    import tarfile

    def run(command, **kwargs):
        assert command[:2] == ["git", "archive"], "older release must not be built"
        archive_path = next(part.removeprefix("--output=") for part in command if part.startswith("--output="))
        readme = tmp_path / "README.md"
        readme.write_text("old\n")
        with tarfile.open(archive_path, "w") as archive:
            archive.add(readme, arcname="README.md")

    monkeypatch.setattr(deploy.subprocess, "check_output", lambda *a, **k: "b" * 40 + "\n")
    monkeypatch.setattr(deploy.subprocess, "run", run)
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(ValueError):
        deploy.build_package("v0.1.0", work, rendered())


def test_remote_script_touches_only_the_bridge_unit():
    for line in deploy.REMOTE.splitlines():
        if "systemctl" in line and "daemon-reload" not in line:
            assert '"$unit"' in line, line
    for forbidden in ("hermes-home", "hermes-relay-home", "8765", "8875", "bridge.env\" >", "tee"):
        assert forbidden not in deploy.REMOTE


# --- Embedded remote bash, exercised locally with fake privileged commands ---

FAKES = r'''
sudo() { if [ "$1" = -u ]; then shift 2; fi; "$@"; }
flock() { [ ! -e "$FAKE/locked" ]; }
id() { [ "$1" = hermes-puck ]; }
sleep() { :; }
stat() {
  if [ "$2" = %U ]; then cat "$FAKE/owner"; else python3 -c 'import os,sys;print(oct(os.stat(sys.argv[1]).st_mode&0o777)[2:])' "$3"; fi
}
mv() { if [ "$1" = -Tf ]; then rm -f "$3"; command mv "$2" "$3"; else command mv "$@"; fi; }
python3.14() {
  mkdir -p "$3/bin"
  printf '#!/bin/sh\necho "$@" >> "%s/pip.log"\n' "$FAKE" > "$3/bin/pip"
  chmod +x "$3/bin/pip"
}
systemctl() {
  echo "$*" >> "$FAKE/systemctl.log"
  case "$1" in
    restart) if [ -e "$FAKE/fail-restart" ]; then rm -f "$FAKE/fail-restart"; return 1; fi ;;
    is-active) [ ! -e "$FAKE/inactive" ] ;;
  esac
}
'''


class Host:
    def __init__(self, tmp_path):
        self.base = tmp_path
        self.fake = tmp_path / "fake"
        self.root = tmp_path / "opt"
        self.state = tmp_path / "state"
        self.units = tmp_path / "units"
        for path in (self.fake, self.root, self.units):
            path.mkdir()
        self.state.mkdir(mode=0o700)
        self.state.chmod(0o700)
        env_file = self.state / "bridge.env"
        env_file.write_text("")
        env_file.chmod(0o600)
        (self.fake / "owner").write_text("hermes-puck\n")
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.port = self.listener.getsockname()[1]

    def script(self):
        return (deploy.REMOTE
                .replace("/opt/hermes-puck-bridge", str(self.root))
                .replace("/var/lib/hermes-puck-bridge", str(self.state))
                .replace("/etc/systemd/system", str(self.units)))

    def run(self, operation, commit="", unit_text=None):
        incoming = ""
        if operation == "deploy":
            staging = self.base / f"incoming-{commit}"
            staging.mkdir()
            (staging / "hermes_relay_tui-0-py3-none-any.whl").write_text("wheel")
            (staging / "unit.service").write_text(unit_text or f"unit {commit}")
            incoming = str(staging)
        expected = unit_text or "unit a"
        args = [operation, commit, incoming, "127.0.0.1", str(self.port), expected]
        return subprocess.run(
            ["bash", "-c", FAKES + self.script(), "remote", *args],
            env={"HOME": str(self.base), "FAKE": str(self.fake), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:" + str(Path(sys.executable).parent)},
            capture_output=True, text=True,
        )

    def current(self):
        link = self.root / "current"
        return Path(link.resolve()).name if link.is_symlink() else None

    def previous(self):
        link = self.root / "previous"
        return Path(link.resolve()).name if link.is_symlink() else None

    def systemctl(self):
        log = self.fake / "systemctl.log"
        return log.read_text().splitlines() if log.exists() else []


@pytest.fixture
def host(tmp_path):
    host = Host(tmp_path)
    yield host
    host.listener.close()


def test_remote_deploy_installs_release_switches_current_and_enables_only_its_unit(host):
    result = host.run("deploy", "a")
    assert result.returncode == 0, result.stderr
    assert host.current() == "a" and host.previous() is None
    assert (host.root / "releases/a/.puck-bridge-v1").is_file()
    assert (host.units / "hermes-puck-bridge.service").read_text() == "unit a"
    assert "[voice]" in (host.fake / "pip.log").read_text()
    assert not (host.base / "incoming-a").exists()
    assert host.run("deploy", "b").returncode == 0
    assert (host.current(), host.previous()) == ("b", "a")
    calls = host.systemctl()
    assert {call.split()[-1] for call in calls if call != "daemon-reload"} == {"hermes-puck-bridge.service"}
    assert "enable hermes-puck-bridge.service" in calls


def test_remote_refuses_to_overwrite_an_existing_release(host):
    assert host.run("deploy", "a").returncode == 0
    result = host.run("deploy", "a")
    assert result.returncode == 1 and "refusing overwrite" in result.stderr
    assert host.current() == "a"


@pytest.mark.parametrize("failure", ["fail-restart", "inactive"])
def test_remote_failed_restart_or_health_rolls_back_automatically(host, failure):
    assert host.run("deploy", "a").returncode == 0
    (host.fake / failure).write_text("")
    result = host.run("deploy", "b")
    assert result.returncode == 1
    assert "restoring the previous release" in result.stderr
    assert host.current() == "a"
    assert (host.units / "hermes-puck-bridge.service").read_text() == "unit a"
    assert not (host.root / "releases/b").exists(), "a failed release is removed so the tag can be retried"
    assert host.systemctl()[-1] == "restart hermes-puck-bridge.service"


def test_remote_failed_first_deploy_leaves_no_active_unit(host):
    (host.fake / "inactive").write_text("")
    result = host.run("deploy", "a")
    assert result.returncode == 1
    assert host.current() is None
    assert not (host.units / "hermes-puck-bridge.service").exists()
    assert "stop hermes-puck-bridge.service" in host.systemctl()
    assert not any(call.startswith("enable") for call in host.systemctl())


def test_remote_rollback_restores_previous_and_restarts(host):
    assert host.run("deploy", "a", "unit a").returncode == 0
    assert host.run("deploy", "b", "unit a").returncode == 0
    result = host.run("rollback", unit_text="unit a")
    assert result.returncode == 0, result.stderr
    assert (host.current(), host.previous()) == ("a", "b")
    assert host.systemctl()[-2:] == ["is-active --quiet hermes-puck-bridge.service", "enable hermes-puck-bridge.service"]


def test_remote_rollback_refuses_mismatched_unit_or_missing_previous(host):
    assert host.run("rollback").returncode == 1
    assert host.run("deploy", "a", "unit a").returncode == 0
    assert host.run("deploy", "b", "unit a").returncode == 0
    result = host.run("rollback", unit_text="other unit")
    assert result.returncode == 1 and "does not match" in result.stderr
    assert host.current() == "b"


@pytest.mark.parametrize("break_state", ["missing", "mode", "owner", "lock"])
def test_remote_preconditions_fail_before_any_change(host, break_state):
    env_file = host.state / "bridge.env"
    if break_state == "missing":
        env_file.unlink()
    elif break_state == "mode":
        env_file.chmod(0o640)
    elif break_state == "owner":
        (host.fake / "owner").write_text("root\n")
    else:
        (host.fake / "locked").write_text("")
    result = host.run("deploy", "a")
    assert result.returncode == 1
    assert not (host.root / "releases").exists()
    assert host.systemctl() == []
    if break_state == "missing":
        assert "Missing operator-created" in result.stderr
