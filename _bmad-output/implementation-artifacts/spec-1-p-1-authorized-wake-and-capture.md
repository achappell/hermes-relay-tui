---
title: 'Authorized wake and capture'
type: 'feature'
created: '2026-09-10'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '64ee9b7'
context:
  - '{project-root}/_bmad-output/planning-artifacts/prds/prd-hermes-relay-tui-2026-09-07/prd.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Puck captures household audio *before* anything checks whether it is allowed to. Wake detection fires `wake_capture::start()` directly from `on_wake_word_detected:` with no identity check; the device's only credential is a hardcoded `X-Puck-Token` from `secrets.yaml`, and that token is not validated until the audio is already recorded and being POSTed to the bridge (`puck_bridge/receiver.py:219`). The bridge's check is correctly fail-closed *for the bridge* — it refuses to reassemble or run a turn — but by then the Puck has already recorded several seconds of a room and put it on the network.

Epic 1's acceptance is explicit and this inverts it: *"Fix the selected Profile before Puck ... capture or Hermes submission. Unapproved, revoked, unavailable, or unverified identity must fail closed **before capture** and must not select a fallback."*

**Approach:** Make identity a precondition of capture rather than a property checked afterwards. The Puck must know, before it opens the microphone buffer, that its identity has not been refused; if it has, a wake must fail closed — audibly acknowledged as unavailable (P-2's status audio), but with no capture, no upload, and no fallback profile.

**What this story does NOT do:** it does not invent a credential system. Per `epic-1-context.md`, *"Physical-device credentials, provisioning, revocation, and wake arbitration belong to the separate device-administration work. This epic consumes an authorized configuration and does not invent that system."* The hardcoded shared token stays as the stand-in; this story makes the Puck *consume* it correctly and fail closed on its absence or rejection.

## Boundaries & Constraints

**Always:** Raw Puck audio stays transient and home-LAN-only (PRD NFR3). Fail closed on rejection: a missing token or a `401` results in no capture, no upload, and no fallback. (Amended 2026-09-10 by human decision — see "The identity contract" below — from an earlier blanket "any unverified identity" to exclude mere unreachability, which is `DEGRADED` and still captures.) A refusal must be observable — silence is indistinguishable from a broken device. Keep `pcm_capture.h`'s existing safety machinery (heap-watermark reboot, 2-failure abandonment, 30ms inter-chunk delay) untouched. The bridge keeps its own independent token check — defence in depth; the device-side gate does not replace it.

**Never:** No Story 4 / device-administration credential system, provisioning flow, or revocation protocol. No fallback profile selection on failure. No persisting raw audio. No `voice_assistant:` component. No changes to `wake.py`/`handsfree.py` core contracts.

</frozen-after-approval>

## Current state (verified 2026-09-10)

| Fact | Where | Implication |
|---|---|---|
| Wake fires capture with no identity check | `respeaker-lite.yaml` `on_wake_word_detected:` → `wake_capture::start()` | Capture precedes authorization entirely |
| Token is a build-time constant | `secrets.yaml` `puck_device_token`, baked into the upload URL headers | Device cannot learn it is no longer authorized |
| Token validated only at upload | `puck_bridge/receiver.py:219` | Audio is already captured and in flight |
| Bridge resolves its own expected token | `config.resolve_puck_device_token()` | Correct, and stays as the second gate |
| Bridge session identity is wrong | deferred-work #40: `build_session_args()` hands the bridge the TUI's own `session_id` (observed live as `amanda-kiosk`) | Adjacent identity defect, in scope here |

## The identity contract — decided 2026-09-10 (human decision)

Three states. Only **rejection** blocks capture; **unreachability** does not.

| State | Entered when | Wake behaviour |
|---|---|---|
| `AUTHORIZED` | Configured token is non-empty and has not been rejected | Capture normally |
| `UNAUTHORIZED` | Token missing/empty at boot, **or** the bridge answered `401` | **Fail closed** — no capture, no upload, audible refusal, no fallback |
| `DEGRADED` | Bridge unreachable: connection refused, timeout, DNS/network error | **Capture proceeds.** Not a refusal |

**Why unreachability does not fail closed**, despite a strict reading of the AC ("unverified identity must fail closed before capture"):

1. **Unreachability is not evidence about identity.** A dropped WiFi link says nothing about whether this device is approved; it says only that nobody is currently answering. Treating absence of an answer as revocation is a category error.
2. **The privacy argument does not apply.** Failing closed before capture exists so that unauthorized audio is never recorded or transmitted. When the bridge is unreachable there is nowhere for audio to go: it sits in the PSRAM buffer, the upload fails, `pcm_capture.h`'s existing 2-consecutive-failure abandonment drops it, and the next capture overwrites it. The failure mode is a **lost turn, not a leak**. That is materially different from a `401`, where a reachable authority has actively said no.
3. **An appliance that refuses wakes during a WiFi blip reads as broken.** In a kitchen, indistinguishable-from-dead is a worse outcome than a lost turn, and it trains people to stop trusting the device.

This is a deliberate, human-owned narrowing of the AC and must be reviewed as such, not silently. A reviewer should challenge it if the threat model changes — specifically, if audio ever gains a persistence path or a second possible destination, point 2 collapses and unreachability should fail closed.

## Tasks & Acceptance

1. **[DONE — see the contract above] Define the Puck's authorized-identity precondition.**
2. **[DONE 2026-09-10 — permit path verified on hardware; refusal path not yet] Gate capture on that precondition.** `on_wake_word_detected:` consults identity state before `wake_capture::start()`. *Acceptance:* with identity unavailable, a wake produces zero captured bytes and zero upload attempts.
3. **Make refusal observable.** An unauthorized wake gives an audible "unavailable" distinct from the normal acknowledgement. Depends on P-2 task 1 (speaker), already delivered. *Acceptance:* a person can tell refusal from breakage without reading logs.
4. **[CODE DONE 2026-09-10 — not yet hardware-verified] Learn that identity has been rejected.** The device transitions to `UNAUTHORIZED` when the bridge answers `401`. Unreachability transitions to `DEGRADED` and must NOT block capture (see the contract). *Acceptance:* after a `401`, the next wake fails closed; after a connection failure, the next wake still captures.
5. **[DONE 2026-09-10] Fix the bridge session-identity collision (deferred #40).** `build_session_args()` populates `session_id` from the profile's YAML (e.g. `amanda-kiosk`) before the "only set when unset" guard runs, so the bridge always inherits the TUI's session id. Needs a decision — unconditional distinct suffix, or a bridge-specific config key — not a one-line patch. *Acceptance:* a Puck turn and a concurrent TUI session never share a `session_id`.
6. **[DONE 2026-09-10] No fallback on failure.** Verify no path silently selects another profile when the configured one is unusable. *Acceptance:* a test asserts refusal rather than substitution.

## Risks & Open Questions

- **"Authorized" is weaker here than the AC implies, by necessity.** With provisioning and revocation out of scope, the contract above is the strongest available check. It cannot detect an *unapproved* or *revoked* device except by the bridge actively rejecting it, and it cannot detect an unverified one at all. Stated plainly so the story is not read as delivering more than it does.
- **A device-side gate against a build-time constant is weak by construction.** A token baked into firmware cannot be revoked without reflashing. The value here is ordering (no capture before authorization) and observability (a refusal is visible), not cryptographic assurance.
- **Failing closed must not make the Puck look dead.** An appliance that silently ignores wakes is indistinguishable from broken hardware — task 3 is not optional polish.
- **P-1 was started after P-2.** Some of P-1's wake/capture substrate already exists from stories 3 and 5 and was only made to work by the 2026-09-10 VAD fix. Evidence from those stories is *input*, not closure — per the epic's own rule that another surface's or story's implementation is evidence, not closure.

## Verification results — 2026-09-10

All six tasks implemented. Hardware-verified by a deliberate rejection test: the
bridge was restarted expecting a different token, then two wakes were spoken.

| Check | Result |
|---|---|
| Normal wake with valid identity captures | PASS -- `state: AUTHORIZED (may_capture=true)`, capture and upload proceed |
| Bridge `401` flips the device to `UNAUTHORIZED` | PASS -- wake 1 captured, was rejected, state changed |
| Next wake after a `401` fails closed | PASS -- wake 2 refused, zero captured bytes, zero POSTs |
| Refusal is audible | PASS -- descending 660->440Hz tone, confirmed by ear |
| No fallback profile is ever selected | PASS -- covered by test in `tests/test_puck_bridge.py` |
| Puck and TUI `session_id` differ | PASS -- `amanda-kiosk-puck-bridge`, verified live |

`DEGRADED` VERIFIED 2026-09-11, incidentally: while the bridge was restarting,
the device logged `state: DEGRADED (may_capture=true)` and went on to capture,
upload and complete a turn once the bridge returned. That is exactly the
contract's deliberate narrowing working as intended -- an unreachable bridge
says nothing about identity, and refusing wakes during it would make the
appliance look broken. No longer an untested state.

Task 5 note: the session-id collision was already fixed on main in #138 before
this branch began; a duplicate written here was discarded in favour of main's
during the merge. Only the no-fallback test survived.

## Verification

Hardware, with bridge and logs attached: (a) normal wake with valid identity captures and transcribes as today; (b) wake with the token cleared produces an audible refusal, zero captured bytes, zero POSTs; (c) wake after a bridge 401 fails closed on the following wake; (d) no fallback profile is ever selected; (e) Puck and TUI `session_id`s differ during a concurrent session.

### Review Findings

Review scope: the P-1 slice from `64ee9b7` through `eecd393`, with the current branch inspected for follow-on behavior. Focused host and firmware tests passed (59 tests). The edge-case-hunter layer timed out before producing a final report; its incomplete commentary was not promoted to a finding.

#### Decision needed

- [x] [Review][Patch] Reconcile the P-1 unavailable-identity contract [prd.md:51, prd.md:174, prd.md:230-238, prd.md:432, prd.md:463] — applied the selected P-1 amendment: authoritative rejection/revocation fails closed, while temporary bridge unreachability is explicitly degraded, transient, and never a fallback path.
- [x] [Review][Patch] Define non-2xx HTTP status handling [firmware/respeaker-lite/puck_identity.h:84-108] — applied the selected policy: `4xx` enters `UNAUTHORIZED`, while `5xx`, `3xx`, and transport failures remain `DEGRADED`; the native identity harness covers 403, 503, transport loss, and recovery.

#### Patch findings

- [x] [Review][Patch] Stop an in-flight upload immediately after a 401 [firmware/respeaker-lite/pcm_capture.h:433-467] — applied an immediate break for every reachable `4xx` after the response is closed; the firmware source test protects the refusal break before the generic failure breaker.
- [x] [Review][Patch] Apply the identity gate to the boot-time PCM capture path [firmware/respeaker-lite/respeaker-lite.yaml:70-72; firmware/respeaker-lite/pcm_capture.h:61-84] — applied the precondition to both rolling-buffer start and write paths, clearing buffered diagnostic state when identity is rejected.
- [x] [Review][Patch] Ship the offline refusal sound [firmware/respeaker-lite/respeaker-lite.yaml:440-442] — added reproducible 16 kHz mono PCM status assets and `tools/generate_sounds.sh`; the asset test validates both refusal and acknowledgement WAVs.
- [x] [Review][Patch] Add firmware-level identity-gate coverage [tests/test_puck_firmware.py:15-112] — added a native C++ identity harness plus capture/upload source invariants covering empty/rejected capture behavior and degraded transport handling.
- [x] [Review][Patch] Make the no-fallback test exercise an actual failure [tests/test_puck_bridge.py:653-713] — added a bridge-start test proving a missing selected Puck identity returns before any Hermes session starts and resolves only that selected profile's environment.

#### Deferred

- [x] [Review][Defer] Add ESPHome schema/compile validation [tests/test_puck_firmware.py:6-12] — deferred: this is a pre-existing repository/toolchain validation gap rather than a P-1 behavior fix; the configured `venv-firmware` toolchain is not installed on this host. The missing refusal asset remains an immediate patch finding.

#### Rejected

- `false` — The alleged token-source mismatch is disproved by the explicit `substitutions` entries mapping `puck_device_token` to the same secret used by the upload path.
- `false` — Treating any non-empty configured token as initially authorized is the deliberate P-1 stand-in; provisioning and revocation are explicitly out of scope.
- `false` — RAM-only rejection is intentional: the frozen contract says only reboot/reflash or restored configuration clears the rejected state.
- `false` — The proposed state-race defect was not demonstrated; the reviewed identity transitions and wake automation use the ESPHome application path, and adding synchronization would be speculative.
- `false` — The GPIO stop/announcement concern belongs to the later P-2 playback surface, not this P-1 review slice.
- `false` — The current branch already fetches `/response?seq=...&token=...`; the alleged missing response playback described an earlier P-2 state.
- `false` — The alleged recurring `/test.wav` boot playback is absent; the current YAML explicitly records that proof as removed.
- `false` — Unauthenticated `web_server` controls are outside the P-1 story and were not caused by this slice.
- `false` — The session-identity documentation is historically untidy, but the current code, story note, and deferred-work resolution all record the collision as fixed.
- `false` — Refusal and normal acknowledgement are distinct in the current branch: descending refusal audio and ascending acknowledgement audio are configured separately in the P-2 follow-on.
- `false` — The verification layer's stale boot-playback claim is disproved by the same current YAML removal and absence of a `/test.wav` reference.
