# W/K browser deployment

Use the supported Home path below for the paired appliance integration.
The later legacy sections retain the existing Caddy deployment at
`https://hermes-home.chappell-home.dev`, with its `127.0.0.1:8765` backend,
only until separately authorized rollout and post-bake retirement.

## Supported Home browser path

This is the repository-supported, explicitly selected Home appliance path.
The remaining Caddy/three-token sections below document the retained legacy
deployment only. They are not Home prerequisites or a supported Home rollback.
S7 host/iPad acceptance, the R6 default switch and bake, and R7 legacy retirement
remain separate authorized work; this implementation does not mark W/K deployed.

### Boundary and one-time pairing

- Use a dedicated loopback backend (`127.0.0.1:8875`) and separate
  `hermes-home-browser.service`; do not reuse the legacy `8765` listener/unit.
- Household Tailscale ACLs must protect the entire origin: page, `/state`,
  `/action`, and `/healthz`. Tailscale Serve terminates HTTPS and proxies `/`
  to that exact loopback port. Disable Funnel, remove public reverse-proxy
  paths to this backend, and deny direct off-tailnet access. Exact Origin
  checks remain enabled; Origin is not authentication.
- Provision the dedicated `hermes-home` service user and Python 3.14. Install
  a reviewed release wheel containing this integration in a bootstrap venv
  outside the checkout. This is an operator prerequisite, not an action
  performed by the repository or by local smoke tests.
- Create `/var/lib/hermes-home-browser` owned by `hermes-home`, mode `0700`.
  As that user, run the pairing command from the bootstrap venv:

  ```bash
  hermes-relay-browser-pair \
    --home https://home.household.ts.net \
    --credential-file /var/lib/hermes-home-browser/pairing.json \
    --label "Household browser appliance"
  ```

  Use Home's existing admin pairing UI/tools to create the offer, enter the
  code at the hidden prompt, compare the confirmation code, and approve the
  requested Profiles. Pairing attests `type=browser` and
  `secure_storage=service_private_file`; the browser itself cannot approve.
  Do not put the code or credential in shell arguments, env files, logs,
  the repository, browser storage, screenshots, or support bundles.

The persisted record must remain service-owned `0600` in its `0700` directory.
Symlinks, group/other access, hardlinks, and checkout storage are rejected.
Atomic file/directory fsync preserves the credential and renewal request ID;
an exclusive process lease prevents competing appliance cleanup sweeps.
Stop the appliance before re-pairing. For a consumed offer whose credential
could not be saved, revoke the unused Device in Home before creating a new
offer; never repeatedly consume/reuse the code.

### Profiles and consumer lifecycle

Home configuration is the authorized Profile catalog. The selector refreshes
at startup, on admission errors, and periodically (15 seconds), including later
grants made through Home's existing **add Profile to existing Device** control.
No local phrase or three-profile catalog is required. Pending/unavailable
Profiles are non-selectable; duplicate labels fail closed; renames do not
change grant identity. Browsers see per-tab opaque selector tokens, not grants.

Optional `/var/lib/hermes-home-browser/shortcuts.yaml` starts with:

```yaml
version: 1
profiles: {}
```

To add a shortcut, an admin may add a named entry with `display_name`,
`wake_phrases`, and `home_grant` set to the exact stable grant ID from Home.
Validate with `scripts/validate_ops_profile_config.py --browser-transport home
--config PATH`. Never add bearer URLs/tokens or retarget by a reused label.
Removing/revoking that grant disables the shortcut. Profiles without shortcuts
remain usable through the selector and typed/microphone input.

Idle tabs do not claim conversations. Each tab's first deliberate action
claims once with `mode=new`; switching Profiles closes that tab's old claim.
Browser disconnect, appliance restart, bridge loss, or credential renewal
never replays text or resumes a prior conversation. Bound WebSocket close is
preferred; HTTP NW18 list/close reconciles orphaned/uncertain claim refs while
preserving other live tabs. Failed cleanup remains a capacity tombstone.
Credential renewal is serialized, persists its request ID before requesting
replacement, and publishes only durably saved material. Uncertain renewal
retires conversations and displays a safe error until recovery.

### Tagged deployment and rollback

Prepare and verify the household-only Serve route before invoking the tool.
Use an existing reviewed `vX.Y.Z` release tag containing `home_admission.py`:

```bash
python scripts/deploy_home_browser.py deploy --ops-host HOUSEHOLD_OPS \
  --origin https://display.household.ts.net \
  --home https://home.household.ts.net --tag vX.Y.Z
```

This explicit host-mutating command is **not** part of local validation.
It builds/tests the tagged source and bundled web UI, checks Serve/Funnel,
requires the already-paired private file, installs an isolated release and
restricted systemd unit, then runs `scripts/check_ops_web.py --home` against
the public tailnet origin. It uses no legacy env/catalog or token. Rollback:

```bash
python scripts/deploy_home_browser.py rollback --ops-host HOUSEHOLD_OPS \
  --origin https://display.household.ts.net \
  --home https://home.household.ts.net
```

Only a prior marked Home release and its saved unit are eligible. A Home outage
does not trigger legacy rollback: retain the safe unavailable page and repair
Home admission. With no compatible previous release, rollback fails explicitly.

`GET /healthz` is admission-only: `200 {\"status\":\"ok\"}` means current pairing,
Home configuration, claim accounting, and at least one usable Profile.
`503 {\"status\":\"degraded\",\"reason\":\"…\"}` distinguishes unavailable Home,
authorization, renewal, and Profile admission failures. The local page starts
without waiting for Home HTTP; checks must not mistake a reachable page for
healthy admission or claim Hermes/audio health. No new Ops monitoring is
installed here.

### Required rollout evidence still outstanding

Record exact allowed-Origin and wrong/null-Origin probes plus off-tailnet
denial of page/WS/actions/backend bypass, real Home authorization/revocation,
independent tabs, fresh reconnects, and cleanup/capacity recovery on the host.
Complete physical Safari/iPad secure-origin microphone, speaker, touch/kiosk,
and post-playback tests. Local Chromium and controlled-Standard smoke are not
hardware, production-network, or real-Hermes acceptance. Keep legacy retirement
separate and disabled until the independently approved post-bake R7 gate.

Local reproducibility: install the actual merged Home checkout into the dev
venv, build `home_display/web`, then run
`.venv/bin/python scripts/smoke_home_browser.py`. `--serve` retains an isolated
temporary Home and actual appliance UI for browser inspection; its printed
loopback `/fixture` controls affect only temporary test state. Standard text/
silent PCM is a controlled fixture; all Home enrollment, grants, claim cleanup,
and HomeBridge HTTP/WS traffic uses the real Home implementation.
To validate a built wheel rather than the source appliance, install it in a
fresh venv and pass `--appliance-python /path/to/venv/bin/python`; the harness
then launches that interpreter outside the checkout and repeats the same real
Home API/bridge smoke. No extra appliance test dependency is installed into
the wheel environment.

## Legacy-only one-time ops preparation

The SSH account used by the deployment command must be able to write the
release root. The service user must already exist; it does not need shell
access. The remote host also needs Python 3.14, Caddy, systemd, `flock`, and
sudo access for the bootstrap operation. The examples use `hermes-home` and
`/opt/hermes-relay-home`, but both are command options.

The pilot assumes the hostname is protected by the household LAN or another
trusted network boundary. The display's exact `Origin` check is not
authentication, and kiosk authentication remains a separate follow-up before
wider exposure.

Create the service environment on ops, owned and readable only by the service
user. The catalog references exactly these three variable names:

```bash
sudo install -d -m 0750 -o hermes-home -g hermes-home /etc/hermes-relay
sudoedit /etc/hermes-relay/home.env
sudo chown hermes-home:hermes-home /etc/hermes-relay/home.env
sudo chmod 0600 /etc/hermes-relay/home.env
```

The file contains runtime settings, for example:

```dotenv
VOICE_SESSION_TOKEN_AMANDA=redacted-token
VOICE_SESSION_TOKEN_JENSEN=redacted-token
VOICE_SESSION_TOKEN_SPARK=redacted-token
```

Keep one non-secret catalog outside Git, based on
`deploy/ops/hermes-home-profile-config.yaml.example`, and fill in the three
Ops WebSocket endpoints and allowlisted client/device/session identities. The
catalog fixes `amanda` to `hey missy`, `jensen` to `hey skippy`, and `spark` to
`hey spark`; the deployment validator rejects a different profile set or token
mapping.

The client and device identities must already be allowlisted by the Hermes
endpoint. An arbitrary new pair will connect to the network but be rejected
during `hello`.

Keep the real token in this file on ops. Do not copy it into the repository,
the deployment command, a wheel, or a Caddy file.

Add this import to the main Caddyfile once, using the actual site directory if
it differs:

```caddyfile
import /etc/caddy/sites-enabled/*.caddy
```

Make sure DNS for `hermes-home.chappell-home.dev` reaches the ops box and that
Caddy can complete its certificate flow. For a private CA, keep the CA bundle
available to the operator and pass `--ca-file` to the smoke check; the browser
must trust that CA separately.

From this repository, install the service and hostname site:

```bash
OPS_HOST=ops.example \
  ./scripts/deploy_ops_web.sh bootstrap \
  --service-user hermes-home
```

Bootstrap is explicit and idempotent for files marked as managed by this
repository. It refuses to overwrite an unrelated Caddy site, validates the
complete Caddyfile, enables the service, and reloads Caddy. It does not start
the appliance until the first deploy.

## Routine deploy

Run from a clean worktree containing the commit you want to serve. A complete
catalog deploy takes both private inputs; the script validates the catalog,
replaces only the three allowlisted token bindings, and preserves other
runtime entries in `/etc/hermes-relay/home.env`:

```bash
OPS_HOST=ops.example \
  ./scripts/deploy_ops_web.sh deploy \
  --profile-config /secure/ops/hermes-home-profile-config.yaml \
  --profile-env-source /secure/ops/home.env
```

The command installs Node dependencies in a temporary source snapshot, runs
the browser tests, type check, production build, generated-asset drift check,
and Python wheel build. It then uploads the wheel over SSH, installs that
commit into an isolated remote runtime, atomically advances `current`,
restarts systemd, validates/reloads Caddy, and probes the public page, state
WebSocket, action route, and the expected three-profile wake-word catalog. A
failed post-activation probe attempts to restore the prior release automatically.

The managed service's `ExecStart` intentionally remains on `legacy` until the
Home route has passed its deployment gate. When that route is ready, make the
transport change as a separately reviewed service/configuration rollout with
the private Device pairing values; do not add a bearer-token fallback to Home
mode. Rollback is the legacy release procedure below.

Useful overrides:

```bash
OPS_HOST=ops.example ./scripts/deploy_ops_web.sh deploy \
  --origin https://hermes-home.chappell-home.dev \
  --base-dir /opt/hermes-relay-home \
  --profile-config /secure/ops/hermes-home-profile-config.yaml \
  --profile-env-source /secure/ops/home.env
```

The public-origin option is passed to the appliance as an exact Origin allow
entry. Caddy does not rewrite the browser's Origin header. The private
listener origin remains accepted for direct testing.

## Rollback

Rollback uses the previous installed release; it does not rebuild or contact a
package index:

```bash
OPS_HOST=ops.example ./scripts/deploy_ops_web.sh rollback
```

The command restarts the service, reloads Caddy, and runs the same public smoke
probe. Private environment snapshots are retained beside each catalog release,
so a rollback restores the matching code, catalog, and token bindings. If the
service cannot start, it attempts to restore the release that was active before
the rollback.

For a deliberate internal-certificate check:

```bash
OPS_HOST=ops.example OPS_CHECK_CA_FILE=/path/to/ops-ca.pem \
  ./scripts/deploy_ops_web.sh deploy \
  --profile-config /secure/ops/hermes-home-profile-config.yaml \
  --profile-env-source /secure/ops/home.env
```

Use `--insecure-health-check` only for a controlled diagnostic. It changes
certificate verification for the local probe, not for the browser or Caddy.

## Failure handling

- A dirty worktree, missing build tool, failed browser check, generated asset
  drift, invalid catalog, or missing profile token stops before SSH upload.
- An install or restart failure leaves the existing `current` release in place
  when one exists.
- A public smoke failure triggers a remote rollback and reports whether that
  rollback succeeded.
- A missing previous release makes `rollback` fail without changing the
  active target.

Inspect the relevant logs on ops with `journalctl -u hermes-relay-home` and
`journalctl -u caddy`. The service should report the loopback display URL; the
browser URL is the public hostname above.

After deployment, complete the physical W/K browser voice gate on the target
iPad or Chromium kiosk. A successful HTTP/WebSocket probe proves the transport,
not microphone permission, speech recognition, playback, wake-free follow-up,
or the Samsung post-playback recovery behavior.
