from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "deploy_ops_web.sh"
pytestmark = pytest.mark.skipif(
    not (ROOT / ".git").exists(),
    reason="deployment harness requires a Git checkout",
)


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=run_env,
    )


@pytest.fixture
def fake_ops(tmp_path: Path) -> dict[str, str | Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    fake_etc = tmp_path / "etc"
    (fake_etc / "systemd/system").mkdir(parents=True)
    (fake_etc / "hermes-relay").mkdir()
    (fake_etc / "hermes-relay/home.env").touch()
    transport_log = tmp_path / "transport.log"
    real_git = shutil.which("git")
    assert real_git

    def install(name: str, content: str) -> None:
        path = fake_bin / name
        path.write_text(content)
        path.chmod(0o755)

    install(
        "git",
        """#!/bin/sh
if [ "${3:-}" = status ] && [ "${4:-}" = --porcelain ]; then
    if [ "${FAKE_DIRTY_WORKTREE:-0}" = 1 ]; then
        printf ' M simulated-change\n'
    fi
    exit 0
fi
exec "$FAKE_REAL_GIT" "$@"
""",
    )
    install(
        "npm",
        """#!/bin/sh
printf 'npm %s\n' "$*" >> "$FAKE_TRANSPORT_LOG"
if [ "${FAKE_NPM_FAIL:-0}" = 1 ]; then
    exit 1
fi
exit 0
""",
    )
    install(
        "diff",
        """#!/bin/sh
if [ "${FAKE_DIFF_FAIL:-0}" = 1 ]; then
    exit 1
fi
exit 0
""",
    )
    install(
        "fake-python",
        """#!/bin/sh
set -eu
if [ "${1:-}" = -m ] && [ "${2:-}" = build ]; then
    if [ "${3:-}" = --help ]; then
        exit 0
    fi
    if [ "${3:-}" = --wheel ]; then
        mkdir -p -- "$5"
        : > "$5/hermes_relay_tui-0.0.0-py3-none-any.whl"
        exit 0
    fi
fi
case "${1:-}" in
    *scripts/check_ops_web.py)
        printf 'check %s\n' "$*" >> "$FAKE_TRANSPORT_LOG"
        if [ "${FAKE_CHECK_FAIL:-0}" = 1 ]; then
            exit 1
        fi
        exit 0
        ;;
esac
exit 0
""",
    )
    install(
        "fake-remote-python",
        """#!/bin/sh
set -eu
if [ "${1:-}" = -m ] && [ "${2:-}" = venv ]; then
    target="$3"
    mkdir -p -- "$target/bin"
    printf '%s\n' '#!/bin/sh' 'if [ "${FAKE_PIP_FAIL:-0}" = 1 ]; then exit 1; fi' 'exit 0' > "$target/bin/python"
    chmod 755 "$target/bin/python"
    printf '#!%s/bin/python\nexit 0\n' "$target" > "$target/bin/hermes-relay-home"
    chmod 755 "$target/bin/hermes-relay-home"
    exit 0
fi
exit 0
""",
    )
    install(
        "ssh",
        """#!/bin/sh
set -eu
printf 'ssh\n' >> "$FAKE_TRANSPORT_LOG"
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o)
            shift 2
            ;;
        *)
            break
            ;;
    esac
done
shift
if [ "${1:-}" = bash ]; then
    shift
    exec /bin/bash "$@"
fi
exec /bin/bash -c "$*"
""",
    )
    install(
        "scp",
        """#!/bin/sh
set -eu
printf 'scp\n' >> "$FAKE_TRANSPORT_LOG"
if [ "${FAKE_SCP_FAIL:-0}" = 1 ]; then
    exit 1
fi
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o)
            shift 2
            ;;
        *)
            break
            ;;
    esac
done
source="$1"
destination="$2"
destination="${destination#*:}"
cp -- "$source" "$destination"
""",
    )
    install(
        "sudo",
        """#!/bin/bash
set -eu
map_path() {
    case "$1" in
        /etc/systemd/system/*) printf '%s/%s' "$FAKE_ETC_DIR/systemd/system" "${1#/etc/systemd/system/}" ;;
        /etc/hermes-relay/*) printf '%s/%s' "$FAKE_ETC_DIR/hermes-relay" "${1#/etc/hermes-relay/}" ;;
        *) printf '%s' "$1" ;;
    esac
}
command="$1"
shift
if [ "$command" = chown ]; then
    exit 0
fi
if [ "$command" = sh ] && [ "${1:-}" = -c ]; then
    script="$2"
    shift 2
    shell_name="$1"
    shift
    mapped_args=()
    for argument in "$@"; do
        mapped_args+=("$(map_path "$argument")")
    done
    exec /bin/sh -c "$script" "$shell_name" "${mapped_args[@]}"
fi
case "$command" in
    test|grep|cp|install|rm)
        mapped=()
        for argument in "$@"; do
            mapped+=("$(map_path "$argument")")
        done
        exec "$command" "${mapped[@]}"
        ;;
    *)
        exec "$command" "$@"
        ;;
esac
""",
    )
    install(
        "id",
        """#!/bin/sh
case "${1:-}" in
    -u)
        printf '1000\n'
        ;;
    -un)
        printf 'fakeuser\n'
        ;;
    -gn)
        printf 'fakegroup\n'
        ;;
    *)
        /usr/bin/id "$@"
        ;;
esac
""",
    )
    install(
        "caddy",
        """#!/bin/sh
set -eu
if [ "${1:-}" = validate ] && [ "${FAKE_CADDY_VALIDATE_FAIL:-0}" = 1 ]; then
    exit 1
fi
exit 0
""",
    )
    install(
        "flock",
        """#!/bin/sh
exit 0
""",
    )
    install(
        "mv",
        """#!/bin/sh
set -eu
if [ "${1:-}" = -Tf ]; then
    shift
    if [ "${1:-}" = -- ]; then
        shift
    fi
    source="$1"
    destination="$2"
    if [ "${FAKE_MV_FAIL_DEST:-}" = "${destination##*/}" ]; then
        exit 1
    fi
    rm -f -- "$destination"
    exec /bin/mv "$source" "$destination"
fi
exec /bin/mv "$@"
""",
    )
    install(
        "systemctl",
        """#!/bin/sh
set -eu
state="$FAKE_STATE_DIR"
command="${1:-}"
case "$command" in
    is-enabled)
        test -f "$state/enabled"
        ;;
    enable)
        : > "$state/enabled"
        ;;
    disable)
        rm -f -- "$state/enabled"
        ;;
    daemon-reload)
        ;;
    stop)
        rm -f -- "$state/active"
        ;;
    restart)
        count=0
        if [ -f "$state/restarts" ]; then
            count=$(/bin/cat "$state/restarts")
        fi
        count=$((count + 1))
        printf '%s\n' "$count" > "$state/restarts"
        if [ "$count" -le "${FAKE_RESTART_FAILS:-0}" ]; then
            exit 1
        fi
        : > "$state/active"
        ;;
    is-active)
        test -f "$state/active"
        ;;
    reload)
        count=0
        if [ -f "$state/reloads" ]; then
            count=$(/bin/cat "$state/reloads")
        fi
        count=$((count + 1))
        printf '%s\n' "$count" > "$state/reloads"
        if [ "$count" -le "${FAKE_RELOAD_FAILS:-0}" ]; then
            exit 1
        fi
        ;;
    *)
        exit 1
        ;;
esac
""",
    )

    env = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_REAL_GIT": real_git,
        "FAKE_TRANSPORT_LOG": str(transport_log),
        "FAKE_STATE_DIR": str(state_dir),
        "FAKE_ETC_DIR": str(fake_etc),
        "PYTHON_BIN": str(fake_bin / "fake-python"),
        "OPS_REMOTE_PYTHON": "fake-remote-python",
    }
    return {
        "env": env,
        "base": tmp_path / "releases-root",
        "caddyfile": tmp_path / "Caddyfile",
        "etc": fake_etc,
    }


def _seed_current(base: Path) -> Path:
    old_release = base / "releases" / "old"
    (old_release / "venv/bin").mkdir(parents=True)
    executable = old_release / "venv/bin/hermes-relay-home"
    executable.touch()
    executable.chmod(0o755)
    (old_release / ".hermes-release").write_text("commit=old\nwheel=old.whl\norigin=https://display.example\n")
    base.mkdir(exist_ok=True)
    (base / "current").symlink_to(old_release)
    return old_release


def _deploy_args(fake_ops: dict[str, str | Path]) -> tuple[str, ...]:
    return (
        "deploy",
        "--ops-host",
        "fake",
        "--base-dir",
        str(fake_ops["base"]),
        "--caddyfile",
        str(fake_ops["caddyfile"]),
    )


def test_deployment_script_help_is_available_without_an_ops_target():
    result = _run("--help")

    assert result.returncode == 0
    assert "deploy" in result.stdout
    assert "rollback" in result.stdout


def test_deployment_script_rejects_an_unknown_operation():
    result = _run("depl0y")

    assert result.returncode == 2
    assert "Unknown operation: depl0y" in result.stderr


def test_deployment_script_rejects_a_non_absolute_release_root_before_ssh():
    result = _run("deploy", "--ops-host", "fake", "--base-dir", "relative/path")

    assert result.returncode == 1
    assert "base directory must be a simple absolute path" in result.stderr
    assert "ssh" not in result.stderr.lower()


def test_deployment_script_rejects_a_public_origin_path_before_ssh():
    result = _run(
        "deploy",
        "--ops-host",
        "fake",
        "--origin",
        "https://display.example/home",
    )

    assert result.returncode == 1
    assert "public origin must be an https://hostname origin without a path" in result.stderr
    assert "ssh" not in result.stderr.lower()


def test_dirty_worktree_stops_before_transport(fake_ops):
    fake_ops["env"]["FAKE_DIRTY_WORKTREE"] = "1"

    result = _run(*_deploy_args(fake_ops), env=fake_ops["env"])

    assert result.returncode == 1
    assert "worktree is not clean" in result.stderr
    log = Path(fake_ops["env"]["FAKE_TRANSPORT_LOG"])
    assert not log.exists() or not any(line in {"ssh", "scp"} for line in log.read_text().splitlines())


def test_failed_local_web_check_does_not_upload_or_mutate_ops(fake_ops):
    fake_ops["env"]["FAKE_NPM_FAIL"] = "1"

    result = _run(*_deploy_args(fake_ops), env=fake_ops["env"])

    assert result.returncode == 1
    assert not Path(fake_ops["base"]).exists()
    log = Path(fake_ops["env"]["FAKE_TRANSPORT_LOG"])
    assert not log.exists() or not any(line in {"ssh", "scp"} for line in log.read_text().splitlines())


def test_bootstrap_renders_and_installs_the_managed_service_and_caddy_site(fake_ops):
    site_dir = Path(fake_ops["base"]).parent / "sites-enabled"
    Path(fake_ops["caddyfile"]).write_text(f"import {site_dir}/*.caddy\n")

    result = _run(
        "bootstrap",
        "--ops-host",
        "fake",
        "--base-dir",
        str(fake_ops["base"]),
        "--caddyfile",
        str(fake_ops["caddyfile"]),
        "--caddy-site-dir",
        str(site_dir),
        env=fake_ops["env"],
    )

    assert result.returncode == 0, result.stderr
    unit = Path(fake_ops["etc"]) / "systemd/system/hermes-relay-home.service"
    site = site_dir / "hermes-home.chappell-home.dev.caddy"
    assert "--display-host 127.0.0.1" in unit.read_text()
    assert "--display-public-origin https://hermes-home.chappell-home.dev" in unit.read_text()
    assert "hermes-home.chappell-home.dev {" in site.read_text()
    assert "reverse_proxy 127.0.0.1:8765" in site.read_text()
    assert (Path(fake_ops["env"]["FAKE_STATE_DIR"]) / "enabled").exists()
    assert (Path(fake_ops["env"]["FAKE_STATE_DIR"]) / "reloads").read_text() == "1\n"


def test_bootstrap_rejects_a_caddy_directory_only_mentioned_in_a_comment(fake_ops):
    site_dir = Path(fake_ops["base"]).parent / "sites-enabled"
    Path(fake_ops["caddyfile"]).write_text(f"# import {site_dir}/*.caddy\n")

    result = _run(
        "bootstrap",
        "--ops-host",
        "fake",
        "--base-dir",
        str(fake_ops["base"]),
        "--caddyfile",
        str(fake_ops["caddyfile"]),
        "--caddy-site-dir",
        str(site_dir),
        env=fake_ops["env"],
    )

    assert result.returncode == 1
    assert "must import the configured site directory" in result.stderr
    assert not (site_dir / "hermes-home.chappell-home.dev.caddy").exists()


def test_generated_asset_drift_stops_before_transport(fake_ops):
    fake_ops["env"]["FAKE_DIFF_FAIL"] = "1"

    result = _run(*_deploy_args(fake_ops), env=fake_ops["env"])

    assert result.returncode == 1
    assert "generated assets" in result.stderr
    log = Path(fake_ops["env"]["FAKE_TRANSPORT_LOG"])
    assert not log.exists() or not any(line in {"ssh", "scp"} for line in log.read_text().splitlines())


def test_successful_deploy_activates_a_commit_release_and_records_previous(fake_ops):
    old_release = _seed_current(Path(fake_ops["base"]))

    result = _run(*_deploy_args(fake_ops), env=fake_ops["env"])

    assert result.returncode == 0, result.stderr
    current = Path(fake_ops["base"]) / "current"
    previous = Path(fake_ops["base"]) / "previous"
    assert current.resolve() != old_release
    assert current.resolve().parent == Path(fake_ops["base"]) / "releases"
    assert previous.resolve() == old_release
    entrypoint = current / "venv/bin/hermes-relay-home"
    assert entrypoint.read_text().splitlines()[0] == f"#!{current.resolve()}/venv/bin/python"
    assert "active_commit=" in result.stdout


@pytest.mark.parametrize(
    "failure_env",
    [
        {"FAKE_SCP_FAIL": "1"},
        {"FAKE_PIP_FAIL": "1"},
        {"FAKE_RESTART_FAILS": "1"},
        {"FAKE_CADDY_VALIDATE_FAIL": "1"},
        {"FAKE_RELOAD_FAILS": "1"},
        {"FAKE_MV_FAIL_DEST": "previous"},
    ],
)
def test_activation_failures_leave_the_prior_current_release_active(fake_ops, failure_env):
    old_release = _seed_current(Path(fake_ops["base"]))
    fake_ops["env"].update(failure_env)

    result = _run(*_deploy_args(fake_ops), env=fake_ops["env"])

    assert result.returncode == 1
    assert (Path(fake_ops["base"]) / "current").resolve() == old_release


def test_public_smoke_failure_automatically_rolls_back(fake_ops):
    old_release = _seed_current(Path(fake_ops["base"]))
    fake_ops["env"]["FAKE_CHECK_FAIL"] = "1"

    result = _run(*_deploy_args(fake_ops), env=fake_ops["env"])

    assert result.returncode == 1
    assert "previous release restored" in result.stderr
    assert (Path(fake_ops["base"]) / "current").resolve() == old_release


def test_first_deploy_smoke_failure_deactivates_without_a_previous_release(fake_ops):
    fake_ops["env"]["FAKE_CHECK_FAIL"] = "1"

    result = _run(*_deploy_args(fake_ops), env=fake_ops["env"])

    assert result.returncode == 1
    assert "failed release deactivated" in result.stderr
    assert "deactivated_failed_release=" in result.stdout
    assert not (Path(fake_ops["base"]) / "current").exists()


def test_rollback_refuses_when_no_previous_release_exists(fake_ops):
    old_release = _seed_current(Path(fake_ops["base"]))

    result = _run(
        "rollback",
        "--ops-host",
        "fake",
        "--base-dir",
        str(fake_ops["base"]),
        "--caddyfile",
        str(fake_ops["caddyfile"]),
        env=fake_ops["env"],
    )

    assert result.returncode == 1
    assert "no previous release is available" in result.stderr
    assert (Path(fake_ops["base"]) / "current").resolve() == old_release


def test_rollback_reactivates_previous_release_without_rebuilding(fake_ops):
    old_release = _seed_current(Path(fake_ops["base"]))
    deploy_result = _run(*_deploy_args(fake_ops), env=fake_ops["env"])
    assert deploy_result.returncode == 0, deploy_result.stderr
    active_release = (Path(fake_ops["base"]) / "current").resolve()
    log = Path(fake_ops["env"]["FAKE_TRANSPORT_LOG"])
    before_rollback = log.read_text().splitlines()

    result = _run(
        "rollback",
        "--ops-host",
        "fake",
        "--base-dir",
        str(fake_ops["base"]),
        "--caddyfile",
        str(fake_ops["caddyfile"]),
        env=fake_ops["env"],
    )

    assert result.returncode == 0, result.stderr
    assert (Path(fake_ops["base"]) / "current").resolve() == old_release
    assert (Path(fake_ops["base"]) / "previous").resolve() == active_release
    assert "rollback complete" in result.stdout
    after_rollback = log.read_text().splitlines()[len(before_rollback) :]
    assert "scp" not in after_rollback
    assert not any(line.startswith("npm ") for line in after_rollback)


def test_rollback_uses_the_origin_recorded_by_the_active_release(fake_ops):
    old_release = _seed_current(Path(fake_ops["base"]))
    custom_origin = "https://custom.example"
    deploy_result = _run(
        *_deploy_args(fake_ops),
        "--origin",
        custom_origin,
        env=fake_ops["env"],
    )
    assert deploy_result.returncode == 0, deploy_result.stderr

    result = _run(
        "rollback",
        "--ops-host",
        "fake",
        "--base-dir",
        str(fake_ops["base"]),
        "--caddyfile",
        str(fake_ops["caddyfile"]),
        env=fake_ops["env"],
    )

    assert result.returncode == 0, result.stderr
    assert (Path(fake_ops["base"]) / "current").resolve() == old_release
    assert f"rollback complete: {custom_origin}" not in result.stdout
    assert "rollback complete: https://display.example" in result.stdout
