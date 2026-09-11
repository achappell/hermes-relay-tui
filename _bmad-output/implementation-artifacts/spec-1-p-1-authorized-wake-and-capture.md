---
title: 'Authorized wake and capture'
type: 'feature'
created: '2026-09-10'
status: 'in-progress'
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

**Approach:** Make identity a precondition of capture rather than a property checked afterwards. The Puck must know, before it opens the microphone buffer, which Hermes Profile it is acting for and that that identity is currently usable; if it does not, a wake must fail closed — audibly acknowledged as unavailable (P-2's status audio), but with no capture, no upload, and no fallback profile.

**What this story does NOT do:** it does not invent a credential system. Per `epic-1-context.md`, *"Physical-device credentials, provisioning, revocation, and wake arbitration belong to the separate device-administration work. This epic consumes an authorized configuration and does not invent that system."* The hardcoded shared token stays as the stand-in; this story makes the Puck *consume* it correctly and fail closed on its absence or rejection.

## Boundaries & Constraints

**Always:** Raw Puck audio stays transient and home-LAN-only (PRD NFR3). Fail closed, never open: any unknown, missing, rejected, or unverified identity results in no capture. A refusal must be observable — silence is indistinguishable from a broken device. Keep `pcm_capture.h`'s existing safety machinery (heap-watermark reboot, 2-failure abandonment, 30ms inter-chunk delay) untouched. The bridge keeps its own independent token check — defence in depth; the device-side gate does not replace it.

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

## Tasks & Acceptance

1. **Define the Puck's authorized-identity precondition.** Decide and document what the device checks before capture: at minimum a non-empty configured token *and* a known-good reachable bridge/profile binding. *Acceptance:* written into this spec as the explicit contract, since "authorized" is otherwise unfalsifiable.
2. **Gate capture on that precondition.** `on_wake_word_detected:` consults identity state before `wake_capture::start()`. *Acceptance:* with identity unavailable, a wake produces zero captured bytes and zero upload attempts.
3. **Make refusal observable.** An unauthorized wake gives an audible "unavailable" distinct from the normal acknowledgement. Depends on P-2 task 1 (speaker), already delivered. *Acceptance:* a person can tell refusal from breakage without reading logs.
4. **Learn that identity has become unusable.** The device must transition to unauthorized when the bridge rejects it (401) or is unreachable, rather than continuing to capture into a void. *Acceptance:* after a 401, the next wake fails closed rather than capturing again.
5. **Fix the bridge session-identity collision (deferred #40).** `build_session_args()` populates `session_id` from the profile's YAML (e.g. `amanda-kiosk`) before the "only set when unset" guard runs, so the bridge always inherits the TUI's session id. Needs a decision — unconditional distinct suffix, or a bridge-specific config key — not a one-line patch. *Acceptance:* a Puck turn and a concurrent TUI session never share a `session_id`.
6. **No fallback on failure.** Verify no path silently selects another profile when the configured one is unusable. *Acceptance:* a test asserts refusal rather than substitution.

## Risks & Open Questions

- **"Authorized" needs a falsifiable definition and the honest answer is that the real one is blocked.** With provisioning and revocation explicitly out of scope, the strongest available check is "configured token present, and the bridge has not rejected it." That is meaningfully weaker than the AC's "unapproved, revoked, or unverified", and this story should say so plainly rather than claim more than it delivers. Task 1 exists to pin this down before implementation.
- **A device-side gate against a build-time constant is weak by construction.** A token baked into firmware cannot be revoked without reflashing. The value here is ordering (no capture before authorization) and observability (a refusal is visible), not cryptographic assurance.
- **Failing closed must not make the Puck look dead.** An appliance that silently ignores wakes is indistinguishable from broken hardware — task 3 is not optional polish.
- **P-1 was started after P-2.** Some of P-1's wake/capture substrate already exists from stories 3 and 5 and was only made to work by the 2026-09-10 VAD fix. Evidence from those stories is *input*, not closure — per the epic's own rule that another surface's or story's implementation is evidence, not closure.

## Verification

Hardware, with bridge and logs attached: (a) normal wake with valid identity captures and transcribes as today; (b) wake with the token cleared produces an audible refusal, zero captured bytes, zero POSTs; (c) wake after a bridge 401 fails closed on the following wake; (d) no fallback profile is ever selected; (e) Puck and TUI `session_id`s differ during a concurrent session.
