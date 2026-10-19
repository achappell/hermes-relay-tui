---
id: P-HOME-01
title: 'Deploy the Puck bridge to ops as a systemd service and write the Puck Home rollout runbook'
type: 'feature'
created: '2026-10-18'
status: 'review'
route: 'dispatch'
story_key: 'p-home-01-deploy-puck-bridge-on-ops'
baseline_commit: '95809e1'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/course-correction-2026-09-23.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-standard-6-puck-migrate-respeaker-puck-path.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-p-4-recovery-without-replay.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-p-6-graceful-bridge-service-shutdown-and-entry-point-coverage.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-p-7-make-raw-pcm-diagnostics-explicitly-opt-in-and-bounded.md'
  - '{project-root}/scripts/deploy_home_browser.py'
---

# P-HOME-01 — Puck bridge on ops: deployment and rollout runbook

Tooling, unit, tests and runbook are implemented. Nothing is deployed or flashed.

## Intent

**Problem:** No story owns running `puck_bridge` on the household host `ops`.
P-6 owns service lifecycle but excludes deployment (P-6 spec, Boundaries,
"Never"). WK-HOME-01 deploys only the browser appliance. Home MIG-09 AC-8
covers a runbook for CaticornQueen and media-server, not ops. The Puck
rollout also spans several owning stories whose live checks have no single
ordered procedure.

**Approach:** Add deployment tooling for the bridge on ops that mirrors
`scripts/deploy_home_browser.py`, plus one runbook that orders the Puck Home
rollout and sends each live check's evidence to its owning story. This story
adds no bridge behavior.

## Scope

1. `scripts/deploy_puck_bridge.py deploy|rollback`, mirroring
   `deploy_home_browser.py`: build from a release tag, release directories
   with `current`/`previous` symlinks, lock, refusal to overwrite a release,
   automatic rollback when restart fails, and no contact with the browser
   appliance or legacy units.
2. A hardened systemd unit template for the bridge, using the browser unit's
   hardening as the baseline: dedicated user, `StateDirectory` 0700,
   `UMask=0077`, `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`,
   `PrivateTmp`, `ReadWritePaths` limited to the state directory. Credentials
   and tokens live only in operator-created 0600 files in the state
   directory, never in the unit, argv, the repository or logs. The bridge
   listens on the ops LAN address on port 8766 (verified free 2026-10-18),
   never on a Tailscale interface.
3. The bridge's claim-recovery state lives under the service state directory
   so it persists across restarts, as P-4 requires (P-4 Implementation Notes,
   "Persist the current Home handle").
4. A runbook (`docs/puck-ops-deployment.md`) covering install, start/restart,
   upgrade, rollback, removal, firmware flash steps from
   `firmware/respeaker-lite/README.md` ("Build & Flashing"), and the ordered
   rollout below. Each step is either exercised or marked unexercised.

## Existing owners (not re-scoped here)

| Concern | Owner | Current state |
|---|---|---|
| Home transport adapter, credential/opaque-handle resolution | STD-6 (`spec-standard-6-puck-migrate-respeaker-puck-path.md`) | Implementation done; live gate deferred |
| Fresh wake admission after retirement, restart recovery, no replay | P-4 (`spec-1-p-4-recovery-without-replay.md`) | Done; production calibrated provider absent (see Blocker) |
| Service shutdown and entry points | P-6 | Done |
| Raw PCM diagnostics default-off | P-7 | Review; hardware check open |
| Applying the approved Room, credential and Wake Mapping | 3-P-2 (`planning-artifacts/epics.md`, Epic 3 Puck map) | Backlog |
| Mapping/Profile enforcement before capture | 3-P-3 | Backlog |
| Arbitration participation | 3-P-4 | Backlog |
| Revoked/unverified identity, credential retirement, re-enrollment | 3-P-5, 3-P-6 | Backlog |
| Pairing a service-hosted room device in Home | hermes-relay-home `HOME-NW-17-room-device-admission` | Draft |
| Live per-surface pilot incl. renewal and revocation | hermes-relay-home MIG-09 AC-5; `course-correction-2026-09-23.md` "Finish the replacement and retire the old system" | Backlog |
| Retiring legacy direct mode | TUI-RETIRE-01 | Backlog |

## Blocker (existing, unresolved)

The Puck can admit a new Home claim only with calibrated proximity evidence
from a trusted hardware provider, never wake-model confidence. This rule is
locked in P-4 (frozen Boundaries, "Always"; Review Triage `[Review][Defer]`:
"as selected by the user") and tracked in `deferred-work.md`
(`source_spec: spec-1-p-4-recovery-without-replay.md`, calibrated proximity
provider). Production wiring passes no provider (`puck_bridge/server.py:269`),
so every wake after a claim is retired, the bridge restarts with a
non-active record, or Home restarts is refused
(`puck_bridge/home_admission.py:247-248`). This story neither resolves nor
reopens that decision. Released bridges up to `v0.13.1` (the releases
exercised in this story's smoke) serve only their initially configured claim
until the provider exists. 3-P-5 (PR #249, unreleased) binds admission to a
Home wake-configuration revision that only a calibrated fresh admission
sets, so it serves no claim at all without the provider. Either way, the rollout cannot
show service that survives restarts.

## Prerequisites and gates

**Code prerequisites** (merged before a release is deployed): STD-6, P-4,
P-6 implementation. P-7 firmware code is merged (#246); its open hardware
check is a rollout gate, not a prerequisite.

**Rollout prerequisites** (before the household rollout, not before the
tooling is written): the Home pairing gap closed and the Puck paired under
3-P-2's ordered flow; the P-4 trusted provider available.

**Rollout gates performed during the rollout.** Evidence is recorded in the
owning story, not here:
- STD-6 deferred external gate (STD-6 spec, Tasks: "Deferred external gate").
- P-7 controlled hardware check (P-7 spec, Verification).
- The Puck row of MIG-09 AC-5, including renewal and revocation.

## Acceptance Criteria

- Given a release tag, when `deploy_puck_bridge.py deploy` runs against a
  disposable Linux host, then it installs a new release, switches `current`,
  keeps `previous`, enables the unit and leaves unrelated units untouched; a
  failed restart rolls back automatically.
- Given `rollback`, then `previous` is restored and the unit restarts.
- Given the unit template, then it contains the hardening above, no secret
  values, and a LAN-only bind; secret files are 0600 and owned by the
  service user.
- Given `systemctl restart` or a host reboot on the disposable host, then the
  unit returns without manual action and claim-recovery state persists.
- Given the runbook, then every step is labelled exercised or unexercised,
  each live check names its owning story for evidence, and no step offers a
  direct-Hermes fallback.
- Repository checks for the new script and its tests pass.

## Tasks

- [x] `scripts/deploy_puck_bridge.py deploy|rollback`: tagged build, `releases/<sha>`
  with atomic `current`/`previous`, lock, overwrite refusal, automatic rollback
  on restart or health failure, pre-activation cleanup of the new release and
  staging upload, stale `current.next` removal, only `hermes-puck-bridge.service`; `--bind` LAN
  IPv4 only, `--port` default 8766 (8765/8875 refused), `--transport home` only,
  `--home-url` exact Home bridge URL with port 1-65535.
- [x] Hardened unit rendered by the script (user `hermes-puck`, state dir 0700,
  `EnvironmentFile` in the state dir with an `ExecStartPre` presence/owner/mode
  check, `HOME`/`XDG_CACHE_HOME`/`HF_HOME` under the state dir, LAN-only bind,
  no secret values).
- [x] `tests/test_deploy_puck_bridge.py`: unit content and flags against the real
  bridge parser, argument validation, embedded remote script run locally with
  fake privileged commands (deploy, overwrite, automatic rollback, rollback,
  preconditions, lock), `ExecStartPre` check. No network.
- [x] `docs/puck-ops-deployment.md` with every step labelled; firmware README
  pointer; CHANGELOG.
- [ ] Disposable Linux run: partial, PID-1 systemd and reboot are outstanding. A 2026-10-18 unprivileged Ubuntu 26.04
  container smoke ran the real CLI with real GNU/uutils tools and sudo. It
  covered deploy, upgrade, rollback, precondition refusal, first-deploy
  failure cleanup, restart and container-restart persistence, and synthetic
  Home authentication. It found and fixed the first-deploy `previous` defect
  (also seen in CI) and the stranded staging directory after a failed upload.
  See `docs/puck-ops-deployment.md`.
- [ ] PID-1 systemd sandboxing and a true host reboot. Unexercised: this
  needs a privileged container or a VM, which is not available without
  elevating privileges on a shared host.

## Never

- Implement pairing, renewal, admission, evidence or arbitration behavior.
- Propose or enable a substitute for the calibrated trusted provider.
- Touch the browser appliance's unit, state or credential, or reuse its pairing.
- Mark STD-6's gate, P-7's hardware check or MIG-09 AC-5 done from this story.

## Open operational questions

- Which ops address is stable enough to bind (DHCP lease vs reservation)?
- Speech-to-text model and compute settings for an Intel N150 with no GPU,
  and the acceptable transcription latency. Measure before choosing.
- Whether the Puck's address should be reserved, and whether the bridge
  should restrict upload sources.
- Whether a rollback firmware image is kept, given the 2026-09-12 build's
  secrets are lost.
- Renewal of the bridge's Home credential: 3-P-2/3-P-6 and MIG-09 AC-5 cover
  credential application and renewal acceptance, but no story names the
  bridge-side renewal implementation. Owner to assign.
- **Blocker for the P-4/STD-6 owner** (bridge behavior, not changed here):
  the smoke showed that `server.main` persists an `active` claim-recovery
  record before the first Home connect. If that first connect fails (a TLS
  failure in the smoke), every later start treats the record as a persisted
  claim and never reopens Home. The fix must come from verified retirement
  plus fresh calibrated admission, never from erasing state. This story's
  runbook forbids operators from deleting or editing the record. Only a full
  device retirement after explicit Home credential revocation may remove
  retained state, and that procedure sits outside the deploy helper. After a
  failed first deploy, re-running `deploy` is not a recovery: the leftover
  record makes the bridge listen without ever contacting Home.

## Dependencies

Code: `tui:STD-6`, `tui:P-4`, `tui:P-6`. Rollout: `home:HOME-NW-17-room-device-admission`,
`tui:3-P-2`, the P-4 trusted provider. Feeds hermes-relay-home MIG-09 AC-5.
