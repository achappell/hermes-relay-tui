---
id: P-HOME-01
title: 'Run the reSpeaker Puck permanently through Hermes Home, with the Puck bridge as a systemd service on ops'
type: 'feature'
created: '2026-10-18'
status: 'draft'
route: 'dispatch'
story_key: 'p-home-01-run-puck-permanently-through-home'
baseline_commit: '95809e1'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/course-correction-2026-09-23.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-standard-6-puck-migrate-respeaker-puck-path.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-p-7-make-raw-pcm-diagnostics-explicitly-opt-in-and-bounded.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-wk-home-01-migrate-production-browser-to-homebridge.md'
  - 'hermes-relay-home: _bmad-output/implementation-artifacts/spec-home-nw-17-room-device-admission.md'
---

# P-HOME-01 — Puck permanently on Home via ops

Planning only: no code, flash, deployment or host change has been made.
Decisions marked **[OWNER]** block `ready-for-dev`.

## Intent

**Problem:** The Puck has no working conversation path.

- Legacy direct mode is dead: media-server (192.168.0.2) no longer serves
  `/voice-session` (8792 refused, 8644 → 404, verified 2026-10-18). TUI-RETIRE-01
  retires it.
- Home mode cannot admit a fresh wake. `HomePuckSessionFactory.admit_wake`
  returns `denied: calibration_unavailable` when `evidence_provider is None`
  (`puck_bridge/home_admission.py:247-248`), and `server.py:269` always passes
  `None`. The bridge works only while its initially configured claim stays
  active; after a bridge restart that finds a non-active recovery record, any
  claim retirement, or any Home restart (Home closes all claims
  `service_restart`), every wake is refused until a human provisions a new
  handle.
- The bridge requires an operator-supplied initial conversation handle
  (`--home-conversation-handle`) and reads a raw credential file with no
  renewal (`server.py:161-167`), while Home credentials expire after 90 days.
  A permanent service cannot depend on either.
- There is no ops deployment for the bridge; STANDARD-6-PUCK's live Home round
  trip on hardware was never run, and P-7's controlled hardware check is open.

**Approach:** Give the bridge an explicit, opt-in *fixed-device* evidence
source so a fixed-location Puck can claim fresh on every wake; let it claim
on first wake instead of needing a pre-provisioned handle; pair it as its own
Home Room device (Home story HOME-NW-17-room-device-admission) with renewal;
deploy it to ops with a hardened systemd unit mirroring
`scripts/deploy_home_browser.py`; flash Home-transport firmware with fresh
secrets; close STANDARD-6-PUCK's deferred gate and P-7's hardware check in the
same hardware session.

## Boundaries & Constraints

**Always:**
- Home is the only transport. No direct-Hermes fallback; no Hermes bearer on
  ops or the Puck.
- Puck has its own Home Device credential, device ID and wake mapping; never
  reuse `/var/lib/hermes-home-browser/pairing.json`.
- Fixed-device evidence is off unless explicitly configured; the factory keeps
  denying `calibration_unavailable` without it.
- Preserve no-replay, exact `stop`, bounded follow-up, interrupt, and
  follow-up-never-claims behavior (`tests/test_puck_bridge.py:1337`).
- Credential, Puck token and Wi-Fi secrets never appear in unit files, argv,
  logs, the repository, or support bundles.
- Bind `192.168.0.4:8766` (LAN only), never `0.0.0.0`, never Tailscale-exposed.

**Never:**
- Reuse or resurrect a closed Home handle; persist claims across Home restart.
- Touch the browser appliance unit, its state dir, or its credential.
- Read the private recovery `secrets.yaml` values into chat, logs, or commits.
- Default `puck_pcm_diagnostics` to on in household firmware.

## Design

### D1 — Admission across restarts (bridge)

Add `FixedDeviceEvidenceProvider` in `puck_bridge/home_admission.py`, enabled
by `--home-fixed-evidence <score>` / `HOME_FIXED_EVIDENCE` (0 < score ≤ 1).
Each wake returns `CalibratedProximityEvidence(value=score,
calibration_id="fixed:<device_id>:v1", observed_at_ms=<wake receipt>)`.
`server.py` passes it instead of `None` when configured. Home receives the
claim as today (`acoustic_evidence.kind=opaque-v1`).

Restart behavior that results:

| Event | Today | After |
|---|---|---|
| Bridge restart, record active | Reuses handle without reconnect | Same; if Home rejects it, retire and claim fresh on next wake |
| Bridge restart, record retired/unconfirmed | Every wake denied | Next wake claims fresh |
| Home restart | Claim closed; every wake denied | Next wake claims fresh |
| ops reboot | As bridge restart | Unit starts after network-online; next wake claims fresh |
| Puck power-cycle | No bridge state change | Unchanged; next wake admitted (current or fresh claim) |
| Uncertain prior submission | No replay | No replay (unchanged) |

Make `--home-conversation-handle` optional when fixed evidence is on: with no
handle and no active recovery record, the first wake claims. Keep it required
otherwise (current fail-closed behavior).

**Security tradeoff [OWNER D-T1]:** the score is a constant, so a Home claim
no longer proves anyone is near the Puck. Anyone on the LAN holding the Puck
token can POST `/upload` and start a conversation in the Puck Room's mapped
Profile. Mitigations in scope: LAN-only bind; new per-device Puck token
(fresh secrets); optional source-address allowlist `--allow-source
192.168.0.184` **[OWNER D-T2: requires a DHCP reservation]**; single Room,
`wake_claim`-only credential; Home revocation stops it. Alternative
(Option C in the Home spec): firmware forwards microWakeWord probability;
deferred because it changes firmware wake upload and re-opens P-7/firmware
tests.

Rejected: keeping one claim alive forever (Home closes claims on restart and
handles cannot reopen); a Home-side "always grant" policy (wider blast radius,
arbitration change).

### D2 — Pairing and renewal (bridge)

Add `python -m puck_bridge pair --home https://caticornqueen.taila59979.ts.net
--room <room> --label "Puck <room>" --state-dir /var/lib/hermes-puck-bridge`.
It submits the Home room-device enrollment (`type=<D-H3 type>`,
`requested_rooms=[room]`, `requested_capabilities=["wake_claim"]`,
`secure_storage="service_private_file"`), prints the confirmation code, polls
consume, and writes `credential.json` (0600, `device_id`, `credential`,
`generation`, `expires_at`) atomically. The enrollment code is read from a
TTY prompt, never argv. Reuse `home_client.py` request/consume/renew logic;
add a file-backed store with the persisted renewal request ID pattern from
TUI-HOME-01.

The server loads `credential.json` (`--home-credential-store`), derives the
device ID from it (no separate `HOME_DEVICE_ID`), renews inside the 14-day
window before creating a claim (renewal can invalidate claims — never renew
with a claim open), and logs only `expires_at`. A daily systemd timer is not
needed: renewal runs at startup and before each fresh claim.

Pairing requires HOME-NW-17-room-device-admission; existing NW-17 pairing
accepts only `client_claim` personal-client types
(Home `credentials.py:40`, `pairing.py:376-386`).

### D3 — ops deployment

`scripts/deploy_puck_bridge.py deploy|rollback --ops-host ops --tag vX.Y.Z
--home https://caticornqueen.taila59979.ts.net --bind 192.168.0.4 --port 8766`,
mirroring `deploy_home_browser.py`: archive tag → test → wheel → scp →
`/opt/hermes-puck-bridge/releases/<commit>/venv`, `current`/`previous`
symlinks, flock, refuse overwrite, restart-failure auto-rollback, marker file
`.puck-bridge-v1`, never touches the browser unit or legacy units.

Unit `hermes-puck-bridge.service`:

```ini
[Unit]
Description=Hermes Puck bridge (Home transport)
After=network-online.target tailscaled.service
Wants=network-online.target
[Service]
User=hermes-puck
Group=hermes-puck
StateDirectory=hermes-puck-bridge
StateDirectoryMode=0700
UMask=0077
EnvironmentFile=/var/lib/hermes-puck-bridge/bridge.env
WorkingDirectory=/opt/hermes-puck-bridge/current
ExecStart=/opt/hermes-puck-bridge/current/venv/bin/python -m puck_bridge \
  --transport home --host 192.168.0.4 --port 8766 \
  --home-url wss://caticornqueen.taila59979.ts.net/api/v1/bridge/ws \
  --home-credential-store /var/lib/hermes-puck-bridge/credential.json \
  --home-fixed-evidence 0.9 --allow-source 192.168.0.184
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ReadWritePaths=/var/lib/hermes-puck-bridge
Environment=HOME=/var/lib/hermes-puck-bridge
Environment=HF_HOME=/var/lib/hermes-puck-bridge/models
[Install]
WantedBy=multi-user.target
```

- `bridge.env` (0600, owner `hermes-puck`): `PUCK_DEVICE_TOKEN`, STT settings,
  `HOME_WAKE_MAPPING_ID` if Home exposes more than one mapping. Created by the
  operator, never by the deploy script from argv.
- Claim recovery state moves under the state dir (today
  `~/.hermes-relay-tui/home-claim-state/`; `HOME` points there).
- Binding `192.168.0.4` needs the address present at start: `After=
  network-online.target` plus `Restart=on-failure` covers late DHCP;
  **[OWNER D-T3: static/reserved 192.168.0.4 on ops]**.
- STT: faster-whisper on CPU, `int8`. Budget on N150 (4c, ~2.9 GiB free):
  model `base.en` (~150 MB RAM) target ≤ 1.5 s transcription for a ≤ 8 s
  utterance; `small.en` (~500 MB) only if P95 stays ≤ 3 s. Pre-download the
  model during deploy into `HF_HOME` so the first wake after reboot does not
  fetch. `MemoryMax=1200M`, `CPUQuota=300%` **[OWNER D-T4: model choice /
  latency target]**. End-to-end target: wake → first reply audio ≤ 6 s P50
  excluding Hermes thinking time — measure and record, do not gate on Hermes.

### D4 — Firmware

1. Fill a fresh `firmware/respeaker-lite/secrets.yaml` (git-ignored) from the
   private recovery copy without echoing values: `puck_bridge_host:
   192.168.0.4`, `puck_bridge_port: 8766`, new `puck_device_token` (same value
   as `PUCK_DEVICE_TOKEN` in `bridge.env`), Wi-Fi, `api_encryption_key`,
   `ota_password`.
2. `venv-firmware/bin/esphome -s puck_home_transport true compile
   firmware/respeaker-lite/respeaker-lite.yaml`; confirm
   `puck_pcm_diagnostics` is `"false"` in the rendered config.
3. First flash over USB (old OTA password lost): `esphome upload … --device
   /dev/cu.usbmodem101`; verify `firmware.factory.bin` mtime is from step 2.
4. `esphome logs … --device 192.168.0.184` shows boot, Wi-Fi, bridge
   reachable, no `RAW MICROPHONE PCM DIAGNOSTICS ENABLED` warning.
5. Later updates OTA with the new password.

### D5 — Hardware session (closes STANDARD-6-PUCK deferred gate and P-7)

Run once after D1–D4, record in the validation file:

- P-7 default build: boot log has no `pcm_capture` allocation or warning;
  wake round trip unchanged.
- P-7 opt-in build (temporary, then reflashed default): boot warning shows,
  exactly 15 two-second windows upload to a throwaway receiver, then
  `COMPLETE`. Captures deleted after the count check.
- STANDARD-6 live round trip: wake → capture → STT → Home → spoken reply on
  the Puck; exact `stop`; interrupt; follow-up; revoked credential fails
  closed; clean `systemctl stop`.

## I/O & Edge-Case Matrix

| Scenario | State | Expected | Error handling |
|---|---|---|---|
| First boot, no handle | Fixed evidence on, credential paired | First wake claims, reply plays | Home down → wake denied, Puck error tone |
| Fixed evidence off | Default flags | `calibration_unavailable` as today | — |
| Bridge restart | Recovery record retired | Next wake admitted fresh | — |
| Home restart | Claim closed `service_restart` | Next wake admitted fresh | — |
| ops reboot | Unit enabled | Service up ≤ 60 s after network; next wake admitted | Bind fails → restart loop until address present |
| Puck power-cycle | Bridge running | Next wake admitted | — |
| Credential near expiry | <14 days | Renewed before next claim | Renewal fails → keep old until expiry; log `expires_at` |
| Credential revoked | Home revokes | `identity_rejected`; no retries storm; Puck error tone | Operator re-pairs |
| Upload from other host | Source ≠ allowlist | `403`, no Home call | — |
| Bad Puck token | Wrong `X-Puck-Token` | `401`, no Home call | — |
| Uncertain turn | Disconnect mid-turn | No replay | — |

## Code Map

- `puck_bridge/home_admission.py`: `FixedDeviceEvidenceProvider`; fresh claim with no prior handle.
- `puck_bridge/server.py`: flags, provider wiring (replaces `evidence_provider=None` at :269), optional initial handle, credential store load/renew, source allowlist.
- `puck_bridge/receiver.py`: source-address check before token check.
- `puck_bridge/pair.py` (new) + `home_client.py` reuse: room-device enrollment and file store.
- `scripts/deploy_puck_bridge.py` (new), `deploy/systemd/hermes-puck-bridge.service` (template).
- `firmware/respeaker-lite/README.md`: Home flash steps; `docs/` ops runbook for the Puck.
- `tests/test_puck_home_session.py`, `tests/test_puck_bridge.py`, new `tests/test_deploy_puck_bridge.py`, `tests/test_puck_pair.py`.

## Tasks & Acceptance

**Execution:**
- [ ] Owner decisions D-T1…D-T6 and Home D-H1…D-H4 recorded.
- [ ] Home HOME-NW-17-room-device-admission delivered and deployed on caticornqueen.
- [ ] D1 provider + optional handle; D2 pair/renew; allowlist; tests.
- [ ] D3 deploy script + unit; dry-run against a throwaway VM/container before ops.
- [ ] Pair the Puck in Home; create `bridge.env`; deploy tag to ops; enable unit.
- [ ] D4 flash; D5 hardware session; validation record `validation-p-home-01.md`.
- [ ] Update STANDARD-6-PUCK deferred gate and P-7 open check with evidence; tracker updates.

**Acceptance Criteria:**
- Given the deployed unit and flashed Puck, when someone says the wake phrase, then the Puck plays Hermes's spoken reply through Home, and the bridge logs show a Home claim, no Hermes bearer, and no direct-Hermes call.
- Given `sudo reboot` on ops, when ops is back, then `hermes-puck-bridge` is active without manual action and the next wake gets a reply.
- Given the Puck is unplugged and replugged, then the next wake after boot gets a reply.
- Given `systemctl restart hermes-puck-bridge` (and separately a Home restart and a deliberate claim retirement), then the next wake gets a reply, with no replay of an uncertain prompt.
- Given fixed evidence is not configured, then wakes are denied `calibration_unavailable` (current behavior preserved).
- Given a Home revocation of the Puck credential, then wakes fail closed and the bridge does not loop retrying claims.
- Given an upload from an address outside the allowlist or with a wrong token, then the bridge rejects it before contacting Home.
- Given the P-7 checks in D5, then default firmware allocates/exports no PCM and the opt-in build stops after 15 windows.
- Given the browser appliance, then its unit, state and pairing are untouched and it still works.
- Given credential age within 14 days of expiry, then the bridge renews without re-pairing (unit test + one forced-window integration test against an isolated Home).
- STT latency for ≤ 8 s utterances on ops is measured and recorded against the D-T4 budget.

## Rollback

- Bridge: `deploy_puck_bridge.py rollback` (previous release) or `systemctl disable --now hermes-puck-bridge`. No legacy path exists to fall back to; rollback means "Puck offline", accepted because direct mode is dead.
- Home: revoke the Puck device credential on the pairing page; this ends all Puck claims.
- Firmware: reflash the previous build over USB (keep the 2026-09-12 build artifact if recoverable — **[OWNER D-T5]**); note its old secrets are lost, so it will not reconnect to anything.
- ops cleanup: remove unit, `/opt/hermes-puck-bridge`, `/var/lib/hermes-puck-bridge`, user `hermes-puck`.

## Owner decisions

- **D-T1** Accept fixed-score admission (constant evidence, LAN token + allowlist as the only proximity proxy) for production, or require firmware-reported wake score first.
- **D-T2** Source-address allowlist for the Puck, with a DHCP reservation for 192.168.0.184.
- **D-T3** Reserve/static 192.168.0.4 on ops (bind is address-specific).
- **D-T4** STT model (`base.en` vs `small.en`) and latency budget.
- **D-T5** Keep the pre-P-7 2026-09-12 firmware image as a rollback artifact or discard.
- **D-T6** Puck Room, wake mapping/Profile, and wake phrase (must match Home's mapping phrase).
- Plus Home D-H1…D-H4 (endpoint type, approval-without-config, touch capability).

## Open questions

- STANDARD-6-PUCK is `done` in `sprint-status.yaml:53` but `in-progress` in its spec frontmatter with an open deferred gate; which is authoritative? This story assumes the spec (gate open).
- Does the Home room device need `health_view` for an ops health probe, or is a local `/healthz` (bridge up + credential valid) enough?
- Should TUI-RETIRE-01 remove `--transport legacy` from the bridge in the same release, or after this story bakes?
- Is caticornqueen (Windows scheduled task) reliable enough as a dependency for a permanent room device, or should its restart/uptime be part of this rollout's monitoring?
- Backlog stories P-3 (enforce wake mapping/Profile before capture), P-4 (single-winner arbitration) and P-5 (reject unverified identity before capture) overlap D1/D2. Does this story absorb the parts it needs, or depend on them?

## Dependencies
- hermes-relay-home `HOME-NW-17-room-device-admission` (pairing a service-hosted room device).
- STANDARD-6-PUCK (Home session code), P-7 (firmware), TUI-HOME-01 (Home client/renewal patterns), WK-HOME-01 (deploy pattern).
