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
  `/action`, and `/healthz`. The default ingress is Tailscale Serve HTTPS with
  `/` proxied to that exact loopback port. The opt-in named Caddy ingress below
  uses raw TCP Serve instead. Disable Funnel, remove public reverse-proxy
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
Use an existing reviewed **published** `vX.Y.Z` release containing
`home_admission.py`; use its tagged checkout, not a newer helper against an
older tag. Confirm the release's commit and published artifacts before any
host change. Merge the code PR and the repository's generated release PR,
then wait for publication through the normal release process. Do not create
manual tags, bypass CI/release policy, or deploy unpublished main.

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

The saved rollback unit must exactly match the requested Origin, Home URL,
backend port, and unit hardening. Restore the matching network ingress first;
the helper fails before switching the release/unit if these disagree.
The helper validates prepared ingress but **does not edit Caddy, Serve, DNS,
ACLs, or private environment files**. SSH and SCP require `BatchMode=yes` and
`StrictHostKeyChecking=yes`; provision trusted host keys independently, never
disable these checks.

`GET /healthz` is admission-only: `200 {\"status\":\"ok\"}` means current pairing,
Home configuration, claim accounting, and at least one usable Profile.
`503 {\"status\":\"degraded\",\"reason\":\"…\"}` distinguishes unavailable Home,
authorization, renewal, and Profile admission failures. The local page starts
without waiting for Home HTTP; checks must not mistake a reachable page for
healthy admission or claim Hermes/audio health. No new Ops monitoring is
installed here.

### Optional named Caddy ingress: `home.chappell-home.dev`

This is an alternate URL, **not** the legacy `hermes-home.chappell-home.dev`
default switch, R6 bake, or R7 retirement. Leave legacy sites, gateways,
units, tokens, and unrelated services unchanged. The only supported named
origin is exactly `https://home.chappell-home.dev`; no trailing path, alias,
additional public Origin, or proxy-rewritten Origin is accepted. The existing
local-listener Origin and missing-Origin native-client behavior are unchanged.
Keep the backend bound only to `127.0.0.1:8875`.

**Stage A is code/review only.** A published release containing both this helper
and the appliance's matching named-Origin startup support is required.
`v0.12.0` has no named deploy support; **`v0.13.0` is also ineligible** because
its runtime still rejected non-`.ts.net` Origins despite accepting the deploy
arguments. That cutover was rolled back to the prior `.ts.net` Home release.
Do not hot-patch a release, rewrite Origin headers, or relax the boundary.
Wait for a corrected published release and renewed owner authorization.

Named deploy compares the helper with the selected tag's helper and refuses
an older/different one; matching helpers alone do not prove runtime readiness.
The regression suite now parses generated deployment-unit arguments, executes
the real Home appliance `_build()` path, starts its loopback display server,
and checks the admitted public Origin, rejected alternate Origin, malformed
action response, and honest unpaired health response. Server Origin matching
remains exact scheme/host/effective-port matching; `/healthz` remains a local
admission-state check, not a hostname allowlist or proof of Hermes readiness.
Home's separate service URL remains restricted by the deployer's tailnet
validator. None of these local tests substitutes for Stage B's real network,
pairing, and browser acceptance.

Approved layout:

```text
household Tailscale TCP443 ACL -> Serve raw TCP443 -> 127.0.0.1:443 Caddy
    -> exact named-host all-path immediate-loopback-peer gate
    -> 127.0.0.1:8875 hermes-home-browser.service
```

Ops already has Porkbun wildcard DNS `*.chappell-home.dev` pointing to its
Tailscale address and the `porkbun_tls` DNS-01 TLS snippet. Reconfirm DNS
before cutover; no record edit is necessary while this remains true. Public
DNS pointing to a tailnet IP alone is **not** an access boundary: Caddy also
listens on LAN. Use `deploy/ops/home-browser.caddy.example` verbatim as the
new `/srv/ops/caddy/sites-enabled/home.chappell-home.dev.caddy`. It imports
the existing TLS automation; do not copy private keys, read credential values,
add new public ingress, trust forwarded IP headers, or enable PROXY protocol.
The first handler denies every non-loopback immediate peer with403, before
any page, health, action, or WebSocket can reach the appliance.

The deployer checks live Caddy HTTP configuration through its existing
loopback admin endpoint (`127.0.0.1:2019`) on Ops. Only pass/fail leaves the
host. It requires the example's exact terminal route, gate before proxy, no
preceding catch-all for this host, no peer-overriding listener wrappers, and
no additional static proxy to port8875. It does not establish the household
ACL or prove LAN/WAN denial; the following operator evidence is mandatory.

#### Stage B prerequisites, backup, and inventory

1. Use strict SSH: `ssh -oBatchMode=yes -oStrictHostKeyChecking=yes jensen@ops`.
   Reconfirm the approved household owner set on Ops TCP443; do not broaden
   ACLs. Confirm Serve/Funnel state, loopback backend, service/private-file
   metadata, Home admission health, and the published release provenance.
2. Inventory **every** existing Caddy hostname and listener, including legacy,
   voice, portal, and wildcard/fallback routing. Privately record baseline
   TLS, HTTP status and safe page/health checks from the same tailnet and LAN
   vantage points. Never probe legacy actions. Record pre-existing502 or
   TLS failures as such, not as successful service health.
3. Coordinate browser witnesses; require their tabs closed, no appliance
   sockets, no owned active Home claims or turns. Recheck immediately before
   ingress mutation and appliance restart. Do not interrupt an active user.
4. On Ops, create a new root-owned0700 backup directory under
   `/var/backups/hermes-home-browser` (unique name; never overwrite an older
   backup). With root-only access, preserve Caddyfile, `sites-enabled`, Caddy
   unit/drop-ins and `/srv/ops/caddy/porkbun.env`, the browser systemd unit/
   drop-ins and any EnvironmentFiles, Serve JSON, and current/previous link
   targets. Capture the browser pairing file's checksum privately plus its
   owner/mode and directory mode; do not print/copy it into evidence.
   Keep any copied env files inside the0700 backup and never print values.
   Preserve the previous tagged Home release and its saved `unit.service`.
   Record backup path, metadata and non-secret hashes only.

#### Stage B cutover (only after explicit authorization)

1. Refuse to overwrite an existing unrelated named site. Install only the new
   example site, owned `root:caddy`, mode0640, under the existing site import.
   Validate the **complete** Caddyfile using the same protected environment as
   the Caddy unit, without shell tracing or dumping environment/configuration.
   Reload, not restart, Caddy using its existing `systemctl reload caddy`
   command (which inherits that unit's EnvironmentFile). On validation/reload
   failure, remove/restore only the new site and leave ingress unchanged.
2. Change only Serve443; never use `serve reset` or alter other Serve ports:

   ```bash
   sudo tailscale serve --https=443 off
   sudo tailscale serve --bg --tcp=443 tcp://127.0.0.1:443
   ```

   Confirm raw `TCPForward: 127.0.0.1:443`, no TLS termination, no Web443
   handlers, no PROXY protocol and no Funnel. **All SNI names on tailnet443
   now reach Caddy**, not just the browser name. This is why the complete
   other-name inventory must be compared before/after. If checks fail, use
   the scoped rollback below; do not repair unrelated sites opportunistically.
3. From the published tagged checkout, in the agreed idle maintenance window:

   ```bash
   python scripts/deploy_home_browser.py deploy --ops-host jensen@ops \
     --ingress caddy --origin https://home.chappell-home.dev \
     --home https://caticornqueen.taila59979.ts.net --port 8875 --tag vX.Y.Z
   ```

   Substitute the actually published tag, not a locally invented one. The
   helper builds/tests that source, installs its isolated release, saves a
   unit with the **single new public Origin**, switches `current`, and restarts
   only `hermes-home-browser.service`. The maintenance window includes these
   build/test steps; it does not continue serving the old `.ts.net` UI.
   Pairing and grants are reused, never re-paired. No legacy service is stopped.
4. Verify trusted certificate/hostname, admission health, exact Origin
   success, wrong/old/null Origin denial for WS/actions, and no Origin rewrite.
   Verify all paths (page, `/state`, `/action`, `/healthz`) deny direct LAN
   access using the named Host **and SNI**; inspect all IPv4/IPv6 listeners,
   ensure port8875 is refused over LAN/tailnet, and recheck no Funnel.
   An allowed tailnet response does not prove external-WAN or non-household
   denial: use actual independent vantage points or record that gate missing.
   Compare all other Caddy names against baseline; do not call an unchanged
   pre-existing failure healthy. Confirm legacy PIDs/config hashes unchanged.
5. Verify pairing metadata/checksum unchanged and Home catalog usable. Only
   then provide the named URL to an independent real-browser witness for
   benign turns, dynamic Profiles, independent tabs and fresh no-replay
   reconnect. Any restart-persistence check needs another coordinated idle
   gate. Do not claim physical iPad/voice acceptance from desktop evidence.

#### Rollback to the prior `.ts.net` Home release

On a fresh idle gate, restore the backed-up named-site state (remove only this
new site if previously absent), validate/reload Caddy without changing other
sites, and restore the previous HTTPS Serve route:

```bash
sudo tailscale serve --tcp=443 off
sudo tailscale serve --bg --https=443 http://127.0.0.1:8875
```

Confirm the saved Serve JSON's HTTPS443 root route and no Funnel, then run the
current reviewed helper's `rollback` with `--ingress serve`,
`--origin https://ops.taila59979.ts.net`, the same Home URL and port8875.
It checks the saved prior unit matches before restoring it and the prior Home
release. If the deploy never advanced `current`, retain that prior release and
restore its backed-up unit instead; do not invoke a rollback to an unrelated
older `previous`. A failed-restart service fallback does not restore ingress;
the operator must finish the network/unit rollback and recheck `.ts.net`
health and Origin behavior. Preserve pairing, backups and the failed release
for diagnosis. The legacy8765 path is **not** a supported rollback.

#### Stage C: portal link after verified Stage B

Only after the new origin passes Stage B, back up Homepage's existing
`/srv/ops/homepage/config/services.yaml` with original metadata and add an
`Agents` tile following its existing conventions: `Hermes Home`, destination
`https://home.chappell-home.dev/`, `icon: mdi-robot`, a short description.
Do not add monitoring or alter existing legacy tiles. Validate YAML and verify
the portal renders the tile and clicking it opens the verified appliance.
Follow the Ops repository's ownership/commit conventions and update the
Family Vault Homelab Services note under its rules (leave vault changes
uncommitted; never blindly stage the vault). Portal discovery is not permission
to mutate it before Stage B; its own network boundary must be reported
separately from the stricter appliance boundary.

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
