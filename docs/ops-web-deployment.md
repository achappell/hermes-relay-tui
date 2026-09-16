# W/K ops deployment behind Caddy

This runbook deploys the browser voice/display surface to the existing ops
Linux box at:

`https://hermes-home.chappell-home.dev`

The Python appliance listens only on `127.0.0.1:8765`. Caddy owns the public
HTTPS hostname and forwards the page, `/state` WebSocket, and `/action` POST
route. The browser never receives the Hermes bearer token.

## STD-8 Home bridge transport (opt-in)

The browser and iPad are one W/K surface. The managed deployment described in
this runbook still starts the `legacy` direct-profile transport, which remains
the rollback path. The migrated Home transport is selected explicitly only
when the approved Home route is available:

```bash
hermes-relay-home --browser-voice \
  --browser-transport home \
  --home-bridge-url wss://home.example/api/v1/bridge/ws \
  --home-device-credential-file ~/.hermes-relay-tui/home-device-credential \
  --home-conversation-handle household-browser
```

The Device credential file is read by the appliance process and should be
owned by its service user with mode `0600`. Alternatively, put
`HOME_DEVICE_CREDENTIAL` and `HOME_CONVERSATION_HANDLE` in the private profile
environment. Do not place the credential in the WebSocket URL, a query string,
the browser bundle, or a display snapshot. Home mode requires the exact secure
`/api/v1/bridge/ws` route and fails closed; it does not fall back to a direct
bearer session.

Home choice/clarify prompts use the bridge's `prompt.respond` request. The
current browser UI cannot collect secret/sudo values, so those prompt types
are reported as unavailable and the turn is interrupted. Home readiness
advertises timing as `absent`; the browser must not invent arrival-time data.
Physical Safari/iPad, secure-channel, audio, touch, kiosk, and concurrent live
session validation remain deployment gates, not claims made by the unit tests.

## One-time ops preparation

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
