#!/usr/bin/env bash

set -Eeuo pipefail
shopt -s nullglob

readonly DEFAULT_ORIGIN="https://hermes-home.chappell-home.dev"
readonly DEFAULT_BASE_DIR="/opt/hermes-relay-home"
readonly DEFAULT_SERVICE="hermes-relay-home"
readonly DEFAULT_SERVICE_USER="hermes-home"
readonly DEFAULT_DISPLAY_PORT="8765"
readonly DEFAULT_CADDYFILE="/etc/caddy/Caddyfile"
readonly DEFAULT_CADDY_SITE_DIR="/etc/caddy/sites-enabled"
readonly DEFAULT_REMOTE_PYTHON="python3.14"
readonly SSH_OPTIONS=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

operation="deploy"
if (( $# > 0 )) && [[ "$1" != -* ]]; then
	operation="$1"
	shift
fi

case "$operation" in
	deploy|bootstrap|rollback|help|--help|-h) ;;
	*)
		printf 'Unknown operation: %s\n\n' "$operation" >&2
		exit 2
		;;
esac

ops_host="${OPS_HOST:-}"
base_dir="${OPS_BASE_DIR:-$DEFAULT_BASE_DIR}"
service_name="${OPS_SERVICE:-$DEFAULT_SERVICE}"
service_user="${OPS_SERVICE_USER:-$DEFAULT_SERVICE_USER}"
display_port="${OPS_DISPLAY_PORT:-$DEFAULT_DISPLAY_PORT}"
public_origin="${OPS_ORIGIN:-$DEFAULT_ORIGIN}"
caddyfile="${OPS_CADDYFILE:-$DEFAULT_CADDYFILE}"
caddy_site_dir="${OPS_CADDY_SITE_DIR:-$DEFAULT_CADDY_SITE_DIR}"
remote_python="${OPS_REMOTE_PYTHON:-$DEFAULT_REMOTE_PYTHON}"
health_ca_file="${OPS_CHECK_CA_FILE:-}"
health_insecure="${OPS_CHECK_INSECURE:-0}"
python_bin="${PYTHON_BIN:-}"

usage() {
	cat <<'USAGE'
Usage:
  scripts/deploy_ops_web.sh deploy [options]
  scripts/deploy_ops_web.sh bootstrap [options]
  scripts/deploy_ops_web.sh rollback [options]

Operations:
  deploy       Build, upload, activate, restart, and smoke-test a release.
  bootstrap    Install the managed systemd unit and Caddy site once.
  rollback     Activate the previous versioned release without rebuilding.

Options:
  --ops-host HOST             SSH target (also OPS_HOST; required)
  --base-dir PATH             Remote release root (default: /opt/hermes-relay-home)
  --service NAME              systemd service name (default: hermes-relay-home)
  --service-user USER         systemd service user (default: hermes-home)
  --display-port PORT         Loopback appliance port (default: 8765)
  --origin URL                Public HTTPS origin
  --caddyfile PATH            Remote Caddyfile (default: /etc/caddy/Caddyfile)
  --caddy-site-dir PATH       Imported Caddy site directory
  --ca-file PATH              CA bundle for the public smoke check
  --insecure-health-check     Disable HTTPS verification for a deliberate check
  --help                      Show this help

Environment overrides:
  OPS_HOST, OPS_BASE_DIR, OPS_SERVICE, OPS_SERVICE_USER, OPS_DISPLAY_PORT,
  OPS_ORIGIN, OPS_CADDYFILE, OPS_CADDY_SITE_DIR, OPS_REMOTE_PYTHON,
  OPS_CHECK_CA_FILE, OPS_CHECK_INSECURE, PYTHON_BIN

The deploy account must be able to write the remote base directory. The
bootstrap operation requires sudo for systemd and Caddy configuration.
USAGE
}

die() {
	printf 'ops-web deployment failed: %s\n' "$*" >&2
	exit 1
}

need_value() {
	if (( $# < 2 )); then
		die "$1 requires a value"
	fi
}

while (( $# > 0 )); do
	case "$1" in
		--ops-host)
			need_value "$@"
			ops_host="$2"
			shift 2
			;;
		--base-dir)
			need_value "$@"
			base_dir="$2"
			shift 2
			;;
		--service)
			need_value "$@"
			service_name="$2"
			shift 2
			;;
		--service-user)
			need_value "$@"
			service_user="$2"
			shift 2
			;;
		--display-port)
			need_value "$@"
			display_port="$2"
			shift 2
			;;
		--origin)
			need_value "$@"
			public_origin="$2"
			shift 2
			;;
		--caddyfile)
			need_value "$@"
			caddyfile="$2"
			shift 2
			;;
		--caddy-site-dir)
			need_value "$@"
			caddy_site_dir="$2"
			shift 2
			;;
		--ca-file)
			need_value "$@"
			health_ca_file="$2"
			shift 2
			;;
		--insecure-health-check)
			health_insecure="1"
			shift
			;;
		--help|-h)
			usage
			exit 0
			;;
		*)
			die "unknown option: $1"
			;;
	esac
done

if [[ "$operation" == "help" ]]; then
	usage
	exit 0
fi

[[ -n "$ops_host" ]] || die "--ops-host or OPS_HOST is required"
[[ "$ops_host" =~ ^[A-Za-z0-9_.@:-]+$ ]] || die "ops host contains unsupported characters"
[[ "$service_name" =~ ^[A-Za-z0-9_.@-]+$ ]] || die "service name contains unsupported characters"
[[ "$service_user" =~ ^[A-Za-z0-9_.@-]+$ ]] || die "service user contains unsupported characters"
[[ "$remote_python" =~ ^[A-Za-z0-9_./-]+$ ]] || die "remote Python command contains unsupported characters"
[[ "$base_dir" =~ ^/[A-Za-z0-9._/-]+$ && "$base_dir" != *..* && "$base_dir" != */./* && "$base_dir" != */ ]] || die "base directory must be a simple absolute path"
[[ "$caddyfile" =~ ^/[A-Za-z0-9._/-]+$ && "$caddyfile" != *..* && "$caddyfile" != */./* && "$caddyfile" != */ ]] || die "Caddyfile must be a simple absolute path"
[[ "$caddy_site_dir" =~ ^/[A-Za-z0-9._/-]+$ && "$caddy_site_dir" != *..* && "$caddy_site_dir" != */./* && "$caddy_site_dir" != */ ]] || die "Caddy site directory must be a simple absolute path"
[[ "$display_port" =~ ^[0-9]+$ ]] || die "display port must be between 1 and 65535"
display_port_value=$((10#$display_port))
(( display_port_value >= 1 && display_port_value <= 65535 )) || die "display port must be between 1 and 65535"
display_port="$display_port_value"

if [[ "$public_origin" =~ ^https://([A-Za-z0-9.-]+)(:([0-9]+))?$ ]]; then
	public_host="${BASH_REMATCH[1]}"
	public_site="$public_host"
	if [[ -n "${BASH_REMATCH[3]}" ]]; then
		public_port_value=$((10#${BASH_REMATCH[3]}))
		(( public_port_value >= 1 && public_port_value <= 65535 )) || die "public origin port must be between 1 and 65535"
		public_site="$public_site:$public_port_value"
	fi
else
	die "public origin must be an https://hostname origin without a path"
fi

if [[ -n "$health_ca_file" && ! -f "$health_ca_file" ]]; then
	die "CA file does not exist: $health_ca_file"
fi

require_command() {
	command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

required_commands=(git ssh scp)
if [[ "$operation" == "deploy" ]]; then
	required_commands+=(npm tar diff)
fi
for command_name in "${required_commands[@]}"; do
	require_command "$command_name"
done

if [[ "$operation" != "bootstrap" && -z "$python_bin" ]]; then
	for candidate in \
		"$REPO_ROOT/venv/bin/python" \
		"$REPO_ROOT/../../venv/bin/python"; do
		if [[ -x "$candidate" ]]; then
			python_bin="$candidate"
			break
		fi
	done
fi
if [[ -z "$python_bin" ]]; then
	python_bin="$(command -v python3.14 || command -v python3 || true)"
fi
if [[ "$operation" != "bootstrap" ]]; then
	[[ -n "$python_bin" ]] || die "Python 3.14 was not found; set PYTHON_BIN"
fi

ensure_clean_tree() {
	local status
	status="$(git -C "$REPO_ROOT" status --porcelain)"
	[[ -z "$status" ]] || die "worktree is not clean; commit or remove local changes before deploying"
}

BUILD_ROOT=""
DEPLOY_COMMIT=""
cleanup() {
	if [[ -n "$BUILD_ROOT" && -d "$BUILD_ROOT" ]]; then
		rm -rf -- "$BUILD_ROOT"
	fi
}
trap cleanup EXIT

build_release() {
	ensure_clean_tree
	DEPLOY_COMMIT="$(git -C "$REPO_ROOT" rev-parse --verify HEAD)" || die "could not identify HEAD"
	"$python_bin" -m build --help >/dev/null 2>&1 || die "Python build module is unavailable in $python_bin"

	BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/hermes-ops-build.XXXXXX")"
	local snapshot="$BUILD_ROOT/source"
	local dist="$snapshot/dist"
	mkdir -p "$snapshot"

	git -C "$REPO_ROOT" archive --format=tar "$DEPLOY_COMMIT" | tar -xf - -C "$snapshot"
	npm ci --prefix "$snapshot/home_display/web"
	npm --prefix "$snapshot/home_display/web" test
	npm --prefix "$snapshot/home_display/web" run check
	npm --prefix "$snapshot/home_display/web" run build
	(
		cd -- "$snapshot"
		"$python_bin" -m pytest
	)
	if ! diff -ru "$REPO_ROOT/home_display/static" "$snapshot/home_display/static" >/dev/null; then
		die "the web build differs from committed home_display/static; commit the generated assets first"
	fi
	[[ "$(git -C "$REPO_ROOT" rev-parse --verify HEAD)" == "$DEPLOY_COMMIT" ]] || \
		die "HEAD changed while building; rerun from the intended commit"

	mkdir -p "$dist"
	"$python_bin" -m build --wheel --outdir "$dist" "$snapshot"
	local wheels=("$dist"/*.whl)
	(( ${#wheels[@]} == 1 )) || die "expected exactly one wheel, found ${#wheels[@]}"
	WHEEL_PATH="${wheels[0]}"
	WHEEL_NAME="$(basename -- "$WHEEL_PATH")"
}

render_template() {
	local template="$1"
	local output="$2"
	local escaped_base escaped_user escaped_port escaped_origin escaped_site
	escaped_base="$(printf '%s' "$base_dir" | sed 's/[\\&|]/\\&/g')"
	escaped_user="$(printf '%s' "$service_user" | sed 's/[\\&|]/\\&/g')"
	escaped_port="$(printf '%s' "$display_port" | sed 's/[\\&|]/\\&/g')"
	escaped_origin="$(printf '%s' "$public_origin" | sed 's/[\\&|]/\\&/g')"
	escaped_site="$(printf '%s' "$public_site" | sed 's/[\\&|]/\\&/g')"
	sed \
		-e "s|@BASE_DIR@|$escaped_base|g" \
		-e "s|@SERVICE_USER@|$escaped_user|g" \
		-e "s|@DISPLAY_PORT@|$escaped_port|g" \
		-e "s|@PUBLIC_ORIGIN@|$escaped_origin|g" \
		-e "s|@PUBLIC_HOST@|$escaped_site|g" \
		"$template" > "$output"
}

bootstrap_remote() {
	local temp_root="$BUILD_ROOT/bootstrap"
	local unit_local="$temp_root/$service_name.service"
	local caddy_filename="$public_host.caddy"
	local caddy_local="$temp_root/$caddy_filename"
	local unit_upload="/tmp/hermes-relay-home-bootstrap-${BASHPID}.service"
	local caddy_upload="/tmp/hermes-relay-home-bootstrap-${BASHPID}.caddy"
	mkdir -p "$temp_root"
	render_template "$REPO_ROOT/deploy/systemd/hermes-relay-home.service" "$unit_local"
	render_template "$REPO_ROOT/deploy/caddy/hermes-home.chappell-home.dev.caddy" "$caddy_local"
	scp "${SSH_OPTIONS[@]}" "$unit_local" "$ops_host:$unit_upload"
	scp "${SSH_OPTIONS[@]}" "$caddy_local" "$ops_host:$caddy_upload"
	ssh "${SSH_OPTIONS[@]}" "$ops_host" bash -s -- \
		"$base_dir" "$service_name" "$service_user" "$caddyfile" \
		"$caddy_site_dir" "$caddy_filename" "$unit_upload" "$caddy_upload" <<'REMOTE_BOOTSTRAP'
set -Eeuo pipefail

base_dir="$1"
service_name="$2"
service_user="$3"
caddyfile="$4"
caddy_site_dir="$5"
caddy_filename="$6"
unit_upload="$7"
caddy_upload="$8"
unit_path="/etc/systemd/system/${service_name}.service"
site_path="${caddy_site_dir}/${caddy_filename}"
service_env_file="/etc/hermes-relay/home.env"
unit_backup="/tmp/hermes-relay-home-unit-backup-$$"
site_backup="/tmp/hermes-relay-home-site-backup-$$"
had_unit=0
had_site=0
was_enabled=0

fail() {
	printf 'remote bootstrap failed: %s\n' "$*" >&2
	exit 1
}

cleanup() {
	sudo rm -f -- "$unit_upload" "$caddy_upload" "$unit_backup" "$site_backup"
}
trap cleanup EXIT

id -u "$service_user" >/dev/null 2>&1 || fail "service user does not exist: $service_user"
sudo sh -c 'test -r "$1"' -- "$service_env_file" || \
	fail "service environment is not readable: $service_env_file"
sudo sh -c 'test -r "$1"' -- "$caddyfile" || \
	fail "Caddyfile is not readable: $caddyfile"

if ! sudo awk -v prefix="$caddy_site_dir/" '
    /^[[:space:]]*import[[:space:]]+/ {
        line=$0
        sub(/^[[:space:]]*import[[:space:]]+/, "", line)
        if (index(line, prefix) == 1) found=1
    }
    END { exit found ? 0 : 1 }
' "$caddyfile"; then
	fail "Caddyfile must import the configured site directory: $caddy_site_dir"
fi

if sudo test -e "$unit_path"; then
	had_unit=1
	sudo grep -q 'Managed by hermes-relay-tui' "$unit_path" || \
		fail "refusing to overwrite an unmanaged systemd unit: $unit_path"
	sudo cp -- "$unit_path" "$unit_backup"
fi
if sudo test -e "$site_path"; then
	had_site=1
	sudo grep -q 'Managed by hermes-relay-tui' "$site_path" || \
		fail "refusing to overwrite an unmanaged Caddy site: $site_path"
	sudo cp -- "$site_path" "$site_backup"
fi
if sudo systemctl is-enabled --quiet "$service_name"; then
	was_enabled=1
fi

if [[ ! -e "$base_dir" ]]; then
	sudo install -d -m 0755 -- "$base_dir"
	sudo chown "$(id -un):$(id -gn)" -- "$base_dir"
fi
[[ -d "$base_dir" && -w "$base_dir" ]] || \
	fail "remote base directory must be writable by the SSH account: $base_dir"
mkdir -p -- "$base_dir/releases" "$base_dir/.incoming"

undo_files() {
	if (( had_unit )); then
		sudo install -m 0644 -- "$unit_backup" "$unit_path"
	else
		sudo rm -f -- "$unit_path"
	fi
	if (( had_site )); then
		sudo install -m 0644 -- "$site_backup" "$site_path"
	else
		sudo rm -f -- "$site_path"
	fi
	if (( ! was_enabled )); then
		sudo systemctl disable "$service_name" >/dev/null 2>&1 || true
	fi
	sudo systemctl daemon-reload >/dev/null 2>&1 || true
}

if ! sudo install -d -m 0755 -- "$caddy_site_dir"; then
	undo_files
	fail "could not create the Caddy site directory; managed files were restored"
fi
if ! sudo install -m 0644 -- "$unit_upload" "$unit_path"; then
	undo_files
	fail "could not install the systemd unit; managed files were restored"
fi
if ! sudo install -m 0644 -- "$caddy_upload" "$site_path"; then
	undo_files
	fail "could not install the Caddy site; managed files were restored"
fi

if ! sudo caddy validate --config "$caddyfile"; then
	undo_files
	fail "Caddy validation failed; managed files were restored"
fi
if ! sudo systemctl daemon-reload; then
	undo_files
	fail "systemd daemon-reload failed; managed files were restored"
fi
if ! sudo systemctl enable "$service_name"; then
	undo_files
	fail "could not enable $service_name; managed files were restored"
fi
if ! sudo systemctl reload caddy; then
	undo_files
	if sudo caddy validate --config "$caddyfile" >/dev/null 2>&1; then
		sudo systemctl reload caddy >/dev/null 2>&1 || true
	fi
	fail "Caddy reload failed; managed files were restored"
fi

printf 'bootstrap ready: service=%s site=%s\n' "$service_name" "$site_path"
REMOTE_BOOTSTRAP
}

deploy_remote() {
	local incoming="$base_dir/.incoming/$WHEEL_NAME"
	ssh "${SSH_OPTIONS[@]}" "$ops_host" "mkdir -p -- $base_dir/.incoming $base_dir/releases"
	scp "${SSH_OPTIONS[@]}" "$WHEEL_PATH" "$ops_host:$incoming"
	ssh "${SSH_OPTIONS[@]}" "$ops_host" bash -s -- \
		"$base_dir" "$service_name" "$remote_python" "$display_port" \
		"$public_origin" "$caddyfile" "$WHEEL_NAME" "$DEPLOY_COMMIT" <<'REMOTE_DEPLOY'
set -Eeuo pipefail

base_dir="$1"
service_name="$2"
remote_python="$3"
display_port="$4"
public_origin="$5"
caddyfile="$6"
wheel_name="$7"
commit="$8"
incoming="$base_dir/.incoming/$wheel_name"
release_dir="$base_dir/releases/$commit"
release_installing=0

fail() {
	printf 'remote deploy failed: %s\n' "$*" >&2
	exit 1
}

cleanup() {
	if (( release_installing )); then
		if ! rm -rf -- "$release_dir"; then
			printf 'could not remove incomplete release: %s\n' "$release_dir" >&2
		fi
	fi
	if ! rm -f -- "$incoming"; then
		printf 'could not remove uploaded wheel: %s\n' "$incoming" >&2
	fi
}
trap cleanup EXIT

atomic_link() {
	local target="$1"
	local link="$2"
	local temporary="$base_dir/.${link##*/}.next.$$"
	if ! rm -f -- "$temporary"; then
		return 1
	fi
	if ! ln -s -- "$target" "$temporary"; then
		return 1
	fi
	mv -Tf -- "$temporary" "$link"
}

restart_service() {
	sudo systemctl restart "$service_name"
	sudo systemctl is-active --quiet "$service_name"
}

[[ -d "$base_dir" && -w "$base_dir" ]] || fail "base directory is not writable: $base_dir"
[[ -f "$incoming" ]] || fail "uploaded wheel is missing: $incoming"
exec 9>"$base_dir/.ops-web.lock"
flock -n 9 || fail "another ops-web deployment or rollback is active"

validate_release() {
	local release="$1"
	local expected_commit="$2"
	[[ -d "$release" && ! -L "$release" ]] || fail "release path is not a directory: $release"
	[[ -f "$release/.hermes-release" ]] || fail "release exists without a manifest: $release"
	grep -Fqx "commit=$expected_commit" "$release/.hermes-release" || \
		fail "release manifest does not match its commit: $release"
	[[ -x "$release/venv/bin/hermes-relay-home" ]] || fail "release runtime is incomplete: $release"
}

restore_pointers() {
	local failed=0
	if [[ -n "$current_target" ]]; then
		if ! atomic_link "$current_target" "$base_dir/current"; then
			failed=1
		fi
	elif [[ -e "$base_dir/current" ]] && ! rm -f -- "$base_dir/current"; then
		failed=1
	fi
	if [[ -n "$previous_target" ]]; then
		if ! atomic_link "$previous_target" "$base_dir/previous"; then
			failed=1
		fi
	elif [[ -e "$base_dir/previous" ]] && ! rm -f -- "$base_dir/previous"; then
		failed=1
	fi
	return "$failed"
}

if [[ -e "$release_dir" ]]; then
	validate_release "$release_dir" "$commit"
else
	release_installing=1
	mkdir -p -- "$release_dir"
	"$remote_python" -m venv "$release_dir/venv"
	"$release_dir/venv/bin/python" -m pip install --disable-pip-version-check --no-input "$incoming"
	cp -- "$incoming" "$release_dir/$wheel_name"
	printf 'commit=%s\nwheel=%s\norigin=%s\n' "$commit" "$wheel_name" "$public_origin" > "$release_dir/.hermes-release"
	release_installing=0
fi

current_target="$(readlink -f -- "$base_dir/current" 2>/dev/null || true)"
previous_target="$(readlink -f -- "$base_dir/previous" 2>/dev/null || true)"
if [[ -e "$base_dir/current" && ! -L "$base_dir/current" ]]; then
	fail "current is not a symlink: $base_dir/current"
fi
if [[ -L "$base_dir/current" && -z "$current_target" ]]; then
	fail "current is a dangling symlink: $base_dir/current"
fi
if [[ -n "$current_target" && "$current_target" != "$base_dir/releases/"* ]]; then
	fail "current points outside the release directory: $current_target"
fi
if [[ -e "$base_dir/previous" && ! -L "$base_dir/previous" ]]; then
	fail "previous is not a symlink: $base_dir/previous"
fi
if [[ -L "$base_dir/previous" && -z "$previous_target" ]]; then
	fail "previous is a dangling symlink: $base_dir/previous"
fi
if [[ -n "$previous_target" && "$previous_target" != "$base_dir/releases/"* ]]; then
	fail "previous points outside the release directory: $previous_target"
fi

sudo caddy validate --config "$caddyfile" || fail "Caddy configuration is invalid"

atomic_link "$release_dir" "$base_dir/current"
if [[ -n "$current_target" && "$current_target" != "$release_dir" ]]; then
	if ! atomic_link "$current_target" "$base_dir/previous"; then
		if restore_pointers; then
			fail "release pointer activation failed; prior pointers restored"
		fi
		fail "release pointer activation failed and pointer restoration failed"
	fi
fi
restore_previous() {
	if ! restore_pointers; then
		printf 'automatic pointer restoration failed\n' >&2
		return 1
	fi
	if ! restart_service; then
		printf 'automatic restoration could not restart %s\n' "$service_name" >&2
		return 1
	fi
}

if ! restart_service; then
	if restore_previous; then
		fail "service restart failed; previous release restored"
	fi
	fail "service restart failed and previous release restoration failed"
fi
if ! sudo systemctl reload caddy; then
	if restore_previous; then
		fail "Caddy reload failed; previous release restored"
	fi
	fail "Caddy reload failed and previous release restoration failed"
fi

printf 'active_commit=%s\nrelease=%s\nport=%s\norigin=%s\n' \
	"$commit" "$release_dir" "$display_port" "$public_origin"
REMOTE_DEPLOY
}

rollback_remote() {
	local allow_without_previous="${1:-0}"
	local remote_output
	local remote_status
	if remote_output="$(ssh "${SSH_OPTIONS[@]}" "$ops_host" bash -s -- \
		"$base_dir" "$service_name" "$caddyfile" "$allow_without_previous" <<'REMOTE_ROLLBACK'
set -Eeuo pipefail

base_dir="$1"
service_name="$2"
caddyfile="$3"
allow_without_previous="$4"

fail() {
	printf 'remote rollback failed: %s\n' "$*" >&2
	exit 1
}

[[ -d "$base_dir" && -w "$base_dir" ]] || fail "base directory is not writable: $base_dir"
exec 9>"$base_dir/.ops-web.lock"
flock -n 9 || fail "another ops-web deployment or rollback is active"

atomic_link() {
	local target="$1"
	local link="$2"
	local temporary="$base_dir/.${link##*/}.next.$$"
	if ! rm -f -- "$temporary"; then
		return 1
	fi
	if ! ln -s -- "$target" "$temporary"; then
		return 1
	fi
	mv -Tf -- "$temporary" "$link"
}

restart_service() {
	sudo systemctl restart "$service_name"
	sudo systemctl is-active --quiet "$service_name"
}

current_target="$(readlink -f -- "$base_dir/current" 2>/dev/null || true)"
previous_target="$(readlink -f -- "$base_dir/previous" 2>/dev/null || true)"
if [[ -z "$previous_target" ]]; then
	if [[ "$allow_without_previous" == 1 && -n "$current_target" ]]; then
		[[ "$current_target" == "$base_dir/releases/"* ]] || fail "current points outside releases"
		[[ -x "$current_target/venv/bin/hermes-relay-home" ]] || fail "active release runtime is incomplete"
		sudo systemctl stop "$service_name" || fail "could not stop the failed first release"
		rm -f -- "$base_dir/current" "$base_dir/previous" || fail "could not clear the failed first release"
		printf 'deactivated_failed_release=%s\n' "$current_target"
		exit 0
	fi
	fail "no previous release is available"
fi
[[ -n "$current_target" ]] || fail "no active release is available"
[[ "$current_target" != "$previous_target" ]] || fail "previous release is the active release"
[[ "$current_target" == "$base_dir/releases/"* ]] || fail "current points outside releases"
[[ "$previous_target" == "$base_dir/releases/"* ]] || fail "previous points outside releases"
[[ -L "$base_dir/current" ]] || fail "current is not a symlink"
[[ -L "$base_dir/previous" ]] || fail "previous is not a symlink"

validate_release() {
	local release="$1"
	local expected_commit="$2"
	[[ -d "$release" && ! -L "$release" ]] || fail "release path is not a directory: $release"
	[[ -f "$release/.hermes-release" ]] || fail "release exists without a manifest: $release"
	grep -Fqx "commit=$expected_commit" "$release/.hermes-release" || \
		fail "release manifest does not match its directory: $release"
	[[ -x "$release/venv/bin/hermes-relay-home" ]] || fail "release runtime is incomplete: $release"
}

validate_release "$current_target" "${current_target##*/}"
validate_release "$previous_target" "${previous_target##*/}"

sudo caddy validate --config "$caddyfile" || fail "Caddy configuration is invalid"
atomic_link "$previous_target" "$base_dir/current"
atomic_link "$current_target" "$base_dir/previous"

restore_current() {
	if ! atomic_link "$current_target" "$base_dir/current"; then
		return 1
	fi
	if ! atomic_link "$previous_target" "$base_dir/previous"; then
		return 1
	fi
	if ! restart_service; then
		printf 'automatic rollback restoration could not restart %s\n' "$service_name" >&2
		return 1
	fi
}

if ! restart_service; then
	if restore_current; then
		fail "rollback service restart failed; original release restored"
	fi
	fail "rollback service restart failed and original release restoration failed"
fi
if ! sudo systemctl reload caddy; then
	if restore_current; then
		fail "Caddy reload failed during rollback; original release restored"
	fi
	fail "Caddy reload failed and original release restoration failed"
fi

active_origin="$(sed -n 's/^origin=//p' "$previous_target/.hermes-release" | head -n 1)"
printf 'rolled_back_to=%s\nprevious_release=%s\n' "$previous_target" "$current_target"
if [[ -n "$active_origin" ]]; then
	printf 'active_origin=%s\n' "$active_origin"
fi
REMOTE_ROLLBACK
	)"; then
		:
	else
		remote_status=$?
		printf '%s\n' "$remote_output"
		return "$remote_status"
	fi
	printf '%s\n' "$remote_output"
	while IFS= read -r remote_line; do
		if [[ "$remote_line" == active_origin=https://* ]]; then
			public_origin="${remote_line#active_origin=}"
		fi
	done <<< "$remote_output"
}

run_public_check() {
	local check_args=("--origin" "$public_origin")
	if [[ -n "$health_ca_file" ]]; then
		check_args+=("--ca-file" "$health_ca_file")
	fi
	if [[ "$health_insecure" == "1" || "$health_insecure" == "true" ]]; then
		check_args+=("--insecure")
	fi
	"$python_bin" "$REPO_ROOT/scripts/check_ops_web.py" "${check_args[@]}"
}

case "$operation" in
	bootstrap)
	BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/hermes-ops-bootstrap.XXXXXX")"
	bootstrap_remote
	;;
	deploy)
	build_release
	deploy_remote
	if ! run_public_check; then
		printf 'public smoke check failed; attempting automatic rollback\n' >&2
		if rollback_remote 1; then
			die "public smoke check failed; previous release restored or failed release deactivated"
		fi
		die "public smoke check failed and automatic rollback failed"
	fi
	printf 'deployment complete: %s\n' "$public_origin"
	;;
	rollback)
	rollback_remote
	if ! run_public_check; then
		die "rollback completed but the public smoke check failed"
	fi
	printf 'rollback complete: %s\n' "$public_origin"
	;;
esac
