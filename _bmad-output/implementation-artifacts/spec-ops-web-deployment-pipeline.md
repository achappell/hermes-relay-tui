---
title: 'Repeatable ops deployment for the W/K browser display'
type: 'feature'
created: '2026-09-12'
status: 'done'
route: 'dispatch'
review_loop_iteration: 1
baseline_commit: '8ced0fdf80d49693713434b924bba5db735c5a2d'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/README.md'
  - '{project-root}/home_display/server.py'
  - '{project-root}/home_display/appliance.py'
  - '{project-root}/pyproject.toml'
  - '{project-root}/docs/testing/home-09-appliance-loop.md'
---

<frozen_intent>
## Intent

Make the W/K browser display repeatably deployable from a clean checkout to the
existing ops Linux box, with its own Caddy hostname:
`hermes-home.chappell-home.dev`.

The operator should be able to build, upload, activate, verify, and roll back a
versioned release with one local command. The appliance remains a normal
`hermes-relay-home` process on loopback; systemd owns its lifecycle and Caddy
terminates HTTPS and proxies the browser page, `/state` WebSocket, and `/action`
requests. The Hermes bearer token remains only in the ops service environment.

## Approach

Add an explicit, exact-match `--display-public-origin` setting to the display
server/appliance. When configured, it allows the browser's public HTTPS Origin
through the existing origin check while preserving the current listener-origin
behavior for direct HTTP/HTTPS deployments. Add a repository deployment script,
systemd unit template, Caddy site snippet, and operator documentation. The
deployment script runs the W/K checks, builds the wheel, uploads it over the
operator's existing SSH configuration, installs it into a versioned release,
atomically advances `current`, restarts the service, validates/reloads Caddy,
and checks the public page before reporting success. A rollback subcommand
re-activates the previous release.

## Boundaries

Always bind the appliance to `127.0.0.1:8765` behind Caddy, use a hostname site
block rather than a path-prefix rewrite, keep browser voice token-free, and
preserve exact Origin validation. Reject dirty worktrees and incomplete
deployments before changing the active release.

Never add bearer tokens or host-specific credentials to Git, auto-deploy on
push, silently rewrite Origin headers in Caddy, expose the appliance directly,
or overwrite an unrelated Caddy configuration. The script may install its
documented service/site files only after validating the rendered configuration.

## I/O Matrix

| Scenario | Expected behavior |
| --- | --- |
| Clean checkout, valid ops target | Build, upload, atomically activate, restart, validate, and report the public URL. |
| Dirty worktree or failed local check | Stop before upload or remote mutation, naming the failed preflight. |
| Upload/install/restart failure | Leave the prior `current` release active; report the failing phase. |
| Public health check failure after activation | Attempt activation of the previous release, restart, and report both outcomes. |
| Explicit rollback with no previous release | Refuse safely with a clear diagnostic. |
</frozen_intent>

## Code Map

| Area | Existing location | Planned change |
| --- | --- | --- |
| Origin policy | `home_display/server.py` | Accept and validate one configured public origin in addition to the listener origin. |
| Appliance CLI | `home_display/appliance.py` | Expose `--display-public-origin` and pass it to `DisplayServer`. |
| Regression coverage | `tests/test_home_display_server.py`, `tests/test_home_appliance.py` | Cover public-origin acceptance, rejection, and parser wiring while retaining direct-origin behavior. |
| Deployment | `scripts/deploy_ops_web.sh` | Preflight, package, SSH release upload/activation, health check, and rollback. |
| Public smoke probe | `scripts/check_ops_web.py` | Verify the public static page, `/state` WebSocket handshake, and safe `/action` routing through Caddy. |
| Ops service | `deploy/systemd/hermes-relay-home.service` | Loopback browser appliance service with an external `EnvironmentFile`. |
| HTTPS proxy | `deploy/caddy/hermes-home.chappell-home.dev.caddy` | Hostname-scoped reverse proxy for the appliance, including WebSocket traffic. |
| Operator runbook | `docs/ops-web-deployment.md`, `README.md` | One-time ops bootstrap, repeatable deploy/rollback commands, DNS/TLS and secret handling. |

## Tasks & Acceptance

### Execution

- [x] Implement exact public-origin configuration without weakening existing origin checks.
- [x] Add focused unit tests for the new policy and CLI option.
- [x] Implement a public smoke probe that checks the static page, accepts the
  public-origin `/state` WebSocket, and reaches `/action` with a deliberately
  malformed payload that cannot dispatch a household action.
- [x] Implement a shell deployment command with explicit target configuration,
  clean-tree and `npm ci`/build preflight, versioned releases, atomic `current`
  switch, service restart, Caddy validation/reload, the public smoke probe, and
  rollback.
- [x] Add systemd/Caddy templates that contain no credentials and document the
  one-time include/service installation on ops.
- [x] Document local usage, required SSH/sudo prerequisites, and failure recovery.

### Acceptance criteria

- [ ] A browser served from `https://hermes-home.chappell-home.dev` can load the
  static display, open `/state`, and post `/action` through Caddy; the automated
  smoke gate proves all three paths without dispatching a real household action.
- [x] A direct deployment with no public-origin option retains current behavior.
- [x] A failed preflight cannot mutate ops; a failed activation preserves or
  restores the last known-good release.
- [x] `deploy` and `rollback` are repeatable and identify the active commit.
- [x] No token, `.env`, audio capture, or machine-specific credential is added
  to the release artifact or repository.

## Design Notes

Caddy's ordinary `reverse_proxy` already supports WebSocket upgrades and keeps
the browser Origin unless configured otherwise. Therefore the application must
explicitly know the public origin; rewriting it at the proxy would hide the
security boundary. The hostname gets its own Caddy site block and no public
path prefix, which keeps browser-relative asset and WebSocket URLs unchanged.
The configured origin is parsed as an origin, not compared as a string prefix:
standard ports are normalized so a browser Origin of
`https://hermes-home.chappell-home.dev` matches the public site while the
backend's private `:8765` remains invisible. Paths, credentials, queries,
fragments, lookalike hosts, and alternate schemes remain rejected.

## Implementation Notes

The deployment command will accept the ops SSH target explicitly (with an
`OPS_HOST` environment fallback) and keep the base directory, service name,
service user, listener port, and public origin overridable without editing the
script. Its defaults will describe this installation, including
`hermes-home.chappell-home.dev`, but no machine-specific hostname or secret will
be required in source. `ssh` and `scp` are the only remote transport
assumptions; the runbook will list the required Python, systemd, Caddy, and
sudo setup.

Because `home_display/static` is tracked, local preflight will run `npm ci`,
the web tests/check/build, and the same generated-asset drift check used by CI.
Packaging will happen from an isolated snapshot of the clean `HEAD`, so a
successful build cannot leave generated files or an untracked dependency cache
in the operator's checkout. The release identifier is the commit SHA, not the
mutable package version.

An explicit `bootstrap` operation may install the managed systemd unit and
hostname-scoped Caddy file after checking that the configured Caddyfile imports
the documented site directory. Normal `deploy` will not edit an unknown shared
Caddyfile. Remote release directories will contain the wheel and a small
manifest identifying the Git commit plus an isolated runtime for that release;
the service environment file remains outside the release tree. The systemd
unit resolves its executable through the `current` symlink, so rollback changes
code and dependencies together without rebuilding or re-uploading. Activation
will preserve the prior `current` target, and all post-activation failures will
report whether automatic restoration succeeded. Rollback will be independently
callable and will not rebuild or re-upload code.

Tests will exercise the script's command construction with a fake SSH/SCP
environment rather than requiring ops access. The public-origin server tests
will assert exact scheme, host, port, and URL-shape matching, including rejection
of lookalike origins and paths. Documentation will distinguish one-time ops
bootstrap from ordinary local deploys so the repeatable path stays short.

## Verification

- `npm ci --prefix home_display/web`
- `npm --prefix home_display/web test`
- `npm --prefix home_display/web run check`
- `npm --prefix home_display/web run build`
- `git diff --exit-code -- home_display/static` after the isolated build
- `../../venv/bin/pytest tests/test_home_display_server.py tests/test_home_appliance.py`
- `../../venv/bin/pytest`
- `bash -n scripts/deploy_ops_web.sh`, `bash scripts/deploy_ops_web.sh --help`,
  and mocked/preflight deployment tests
- `../../venv/bin/python scripts/check_ops_web.py --help`
- On ops: `caddy validate`, service status, HTTPS page load, browser WebSocket
  connection, safe `/action` route probe, and a real browser voice turn followed
  by the W/K follow-up behavior.

## Change Log

| Date | Change |
| --- | --- |
| 2026-09-12 | Initial draft for the ops Linux deployment pipeline and Caddy hostname. |
| 2026-09-12 | Approved implementation completed; local and fake-remote gates passed. Live Ops/browser gate remains for the target machine. |
| 2026-09-12 | Real Ops bootstrap exposed a protected-environment readability edge case; the root-shell check and fake-remote regression are now included. |
| 2026-09-12 | Snapshot preflight now skips the Git-checkout-only deployment harness when running from the archived source tree. |
| 2026-09-12 | First real deploy exposed `readlink -f` treating an absent pointer as a path; missing `current`/`previous` links are now handled as an empty first-deploy state. |

## Review Log

| Iteration | Result |
| --- | --- |
| 0 | Draft prepared for checkpoint 1 approval. |
| 1 | Review closed the tracked-static build, public WebSocket/action smoke, and release-isolation gaps. |

## Review Triage Log

| ID | Finding | Verdict | Route | Evidence |
| --- | --- | --- | --- | --- |
| V1 | Public smoke page and state checks were not exercised. | medium | patch | The original tests covered URL construction and /action only; run_check now has an exercised page/action/WebSocket test. |
| V2 | Any HTTP 400 was accepted as proof that /action reached the appliance. | medium | patch | The original checker accepted status alone; it now requires the appliance's malformed-action JSON error and tests an unrelated 400 rejection. |
| V3 | Bootstrap had no executable coverage. | medium | patch | The original deployment tests never invoked bootstrap; a fake-remote bootstrap test now asserts rendered service/site installation, enablement, and Caddy reload. |
| V4 | The dirty-worktree guard was hidden by the fake Git fixture. | medium | patch | The fixture now emits simulated dirty status and verifies deploy stops before SSH/SCP. |
| V5 | Generated-asset drift failure was not tested. | medium | patch | The fake diff failure path is now exercised and verified to stop before transport. |
| V6 | Rollback's no-rebuild/no-upload promise was not asserted. | medium | patch | The rollback test now compares the transport log and proves no npm or SCP activity occurs during rollback. |
| V7 | Caddy import validation could accept a comment or unrelated import. | medium | patch | Bootstrap now examines an actual import directive with the configured directory prefix, and the comment-only case is tested. |
| B1 | A venv built under staging would retain a dead entry-point shebang after relocation. | high | patch | The release venv is now created at its final path; the fake entry point records and tests that final shebang. |
| B2 | The public site has no authentication beyond Origin handling. | maybe-false | defer | Wider exposure is not established by this task; upstream architecture records trusted-LAN pilot access and open kiosk-auth work. The runbook now states that Origin is not authentication and records the follow-up in deferred-work.md. |
| B3 | Private-CA/insecure settings skipped the page and action HTTPS probes. | medium | patch | One TLS context is now passed to all urllib probes and the WebSocket; the run_check test observes the same context. |
| B4 | Separate current and previous swaps could leave inconsistent pointers. | high | patch | Pointer restoration now captures both prior targets, checks each operation, and restores both when activation of the second link fails. |
| B5 | Concurrent deploy and rollback operations were un-serialized. | medium | patch | Both remote paths now hold a non-blocking flock across validation, pointer changes, restart, and Caddy reload. |
| B6 | First-deploy smoke failure could not use rollback because no previous release existed. | high | patch | Automatic recovery now stops the failed first service and removes its current link; the first-deploy failure test covers it. |
| B7 | HEAD could change between archiving and commit labeling. | medium | patch | The commit is captured before archiving, the archive uses it, and HEAD is rechecked before packaging completes. |
| B8 | Failed remote installation could leave staging and uploaded artifacts. | medium | patch | Installation now uses the final release path with an EXIT cleanup trap that removes incomplete releases and incoming wheels. |
| B9 | Existing release identity was checked too weakly. | medium | patch | Existing and rollback targets now require a matching commit manifest and executable entry point. |
| B10 | The spec said releases retain the wheel, but the script deleted it. | low | patch | The wheel is now copied into the versioned release and recorded in the manifest. |
| B11 | Remote dependencies resolve broad lower bounds from a live index. | maybe-false | defer | The repository has no pinned/hash lock and the frozen intent does not promise offline or bit-for-bit dependency resolution; reproducible dependency locking is recorded in deferred-work.md. |
| B12 | Deploy preflight omitted the Python suite despite changing Python server behavior. | medium | patch | The isolated snapshot now runs python -m pytest from its own root before packaging. |
| B13 | The wheel was not locally installed and exercised before upload. | false | reject | The remote path installs the wheel into the release venv, systemd starts its entry point, and the public page/state/action smoke gate observes the packaged runtime; a separate local install is not required by the captured intent. |
| B14 | A generic HTTP 200 page could pass the page probe. | medium | patch | The checker now requires the Hermes Home title and application mount marker. |
| B15 | An unrelated WebSocket with a string state could pass. | medium | patch | The checker now requires snapshot type, schema 1, non-negative sequence, and a known display state. |
| B16 | HTTP redirects were not constrained. | medium | patch | Page and action probes now reject a final URL different from the configured endpoint. |
| B17 | Bootstrap had no exact import protection. | medium | patch | Same root cause as V7; the actual directive check and test reject comment-only matches. |
| B18 | An unrelated existing systemd unit could be overwritten. | medium | patch | Bootstrap now requires the managed marker before replacing an existing unit. |
| B19 | Plain rollback after a custom-origin deploy could probe the wrong hostname. | medium | patch | Each new manifest records its origin; rollback reads the activated target's origin before its public smoke probe. |
| B20 | Old release directories are never reclaimed. | low | defer | Retention policy affects destructive operational cleanup and was not captured in the intent; active/previous protection and retention are recorded in deferred-work.md. |
| E1 | Invalid public origin could escape startup as an uncaught ValueError. | medium | patch | Appliance display construction now converts this configuration error to the existing RuntimeError CLI diagnostic, with focused coverage. |
| E2 | https://:443 lacked a host check in the smoke URL parser. | low | patch | origin_urls now requires parsed.hostname and the malformed-origin test includes this case. |
| E3 | Infinite timeout values were not rejected. | low | patch | CLI validation now requires a finite positive timeout and tests inf. |
| E4 | Custom TLS context still skipped urllib probes. | medium | patch | Same verified root cause as B3; all HTTP probes now receive the context. |
| E5 | A 200 fallback page could pass as the display. | medium | patch | Same verified root cause as B14; expected display markers are required and tested. |
| E6 | A proxy-generated 400 could pass as the appliance action route. | medium | patch | Same verified root cause as V2; the exact malformed-action error body is required and tested. |
| E7 | Arbitrary JSON state could pass the state check. | medium | patch | Same verified root cause as B15; the initial snapshot contract is now checked. |
| E8 | Unknown operation printed help and exited zero. | medium | patch | Unknown operations now exit 2, with a dedicated test. |
| E9 | Leading-zero display ports could trigger Bash octal parsing. | low | patch | Port validation now parses decimal values with 10# and normalizes the rendered port. |
| E10 | Leading-zero public-origin ports could trigger Bash octal parsing. | low | patch | Public-origin port validation uses decimal parsing and renders the normalized Caddy port. |
| E11 | Caddy directory matching was not anchored to an import directive. | medium | patch | Same verified root cause as V7; directive-aware matching and a comment-only regression test are present. |
| E12 | Bootstrap could report ready without its required service environment. | medium | patch | Bootstrap now checks /etc/hermes-relay/home.env readability before installing managed files. |
| E13 | Bootstrap lacked an unmanaged-systemd-unit guard. | medium | patch | Same verified root cause as B18; existing units must carry the managed marker. |
| E14 | Trailing-slash or ./ base paths could break release-prefix checks. | low | patch | Simple absolute path validation now rejects trailing slashes and /. segments before transport. |
| E15 | HEAD labeling could diverge from the archived snapshot. | medium | patch | Same verified root cause as B7; pre-build capture and post-build equality check are implemented. |
| E16 | Existing release manifest could name a different commit. | medium | patch | Same verified root cause as B9; exact manifest identity is required. |
| E17 | A successful systemd restart could leave the old service process serving. | false | reject | The remote function requires both systemctl restart success and systemctl is-active; under systemd's unit contract this is not an independently reachable success path in the changed code. |
| E18 | Failure updating previous after current could leave a bad activation. | high | patch | Same verified root cause as B4; both pointer operations are checked and prior pointers restored. |
| E19 | Restoration could report success after a failed pointer removal. | medium | patch | Restoration now checks every link operation and returns failure before claiming recovery. |
| E20 | Failed activation could destroy the pre-existing rollback target. | medium | patch | The prior previous target is captured and restored alongside current on failure. |
| E21 | Incoming-wheel cleanup could fail after a successful activation and turn it into a false failure. | low | patch | Cleanup is now EXIT-trapped and best-effort; the post-activation explicit removal that could fail the transaction was removed. |
| E22 | Concurrent operations could race on release pointers. | medium | patch | Same verified root cause as B5; both remote transactions take the release lock. |
| E23 | SSH/SCP could wait indefinitely on a dead connection. | medium | patch | Transport calls now use batch mode, connect timeout, and server-alive bounds. |
| E24 | A local interrupt after activation could leave an unverified release active. | maybe-false | defer | The risk depends on signal timing and SSH forwarding semantics; a safe trap must distinguish pre-activation transport from post-activation state. It is recorded for a dedicated interruption design. |
| E25 | Rollback restart could report success while the original process served. | false | reject | As with E17, restart plus active checks are the systemd lifecycle boundary; the claimed state is not reachable as a successful changed-code path. |
| E26 | Rollback's second pointer update could fail after switching current. | high | patch | Rollback now checks both swaps and has a restoration path. |
| E27 | Rollback restoration pointer updates could be ignored. | medium | patch | restore_current now checks each pointer swap before restarting or reporting restoration. |
| E28 | Rollback could activate a pointer with no matching manifest. | medium | patch | Both current and previous targets are validated against their directory commit identity before swapping. |
| E29 | A failed smoke probe after explicit rollback might need a second rollback. | maybe-false | defer | The intent specifies reporting rollback health failure but not whether the pre-rollback release should be reactivated; policy is recorded for product/operations decision. |
| E30 | The claim that the smoke gate proves all three paths was false in the original diff. | medium | patch | The checker now validates display markup, exact action error, and the full initial snapshot contract; run_check and deployment tests exercise the routes. |
| E31 | The claim that failed activation preserves the last-known-good release lacked pointer-failure recovery. | high | patch | Pointer restoration now covers both links and is exercised through fake-remote activation failures. |
