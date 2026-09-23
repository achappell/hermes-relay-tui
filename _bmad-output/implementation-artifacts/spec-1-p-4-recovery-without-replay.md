---
title: 'Puck recovery without replay'
type: 'feature'
created: '2026-09-22'
status: 'in-progress'
route: 'dispatch'
review_loop_iteration: 3
baseline_commit: '08c22634506e0dc79e3be94ebffb885183920d67'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-p-1-authorized-wake-and-capture.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-p-2-status-and-response-audio-delivery.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-p-3-bounded-follow-up-and-exact-stop.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-4-recover-without-replaying-an-uncertain-turn.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Direct Hermes recovery reuses its session identity, and initial audio-upload failure lacks the refusal cue used for response failures.

**Approach:** Bound cleanup, create a fresh Hermes session after loss, and accept only a later fresh-wake capture. Home must retire its old claim without delivering the unresolved response; a later wake gets a new claim only with calibrated proximity evidence. Report failure once and return to wake when identity is authorized.

**Outcome:** A later wake submits once under a fresh session. Home stays capture-closed until calibrated proximity evidence supports a new claim. Authentication rejection stays fail-closed.

## Boundaries & Constraints

**Always:** Keep Hermes frame parsing and session ownership in the bridge. Require a verified fresh session before sending a later capture; never replay an uncertain turn. On Home loss, stop forwarding events and use at most one bounded control-only connection to close the old claim; discard unresolved events. A later physical wake may request a new claim only with calibrated proximity evidence, never wake-model confidence. Preserve response sequencing, transient audio, one refusal cue, and content-safe logs. Identity rejection stays unauthorized.

**Never:** Retry uncertain delivery, continue an interrupted response, reuse an old Home handle for a new turn, reopen capture silently, add local fallback speech, change ESP32 Touch or TUI behavior, broaden into shutdown/underrun/I2S work, or add a dependency. Home uses its existing claim and close contracts.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected behavior | Error handling |
|---|---|---|---|
| MID_TURN_LOSS | Transport fails after submission | Mark unavailable; never replay; give one refusal and return to wake | Bound cleanup; no fallback audio |
| FRESH_WAKE_RECOVERY | A later wake arrives while transport is down | Verify a fresh session, then submit this capture once | Refuse if recovery fails |
| HOME_TURN_LOSS | Home transport drops during a turn | Stop the response; use bounded control-only cleanup to close the old claim; discard its events | If close is unconfirmed, keep Home capture closed |
| HOME_FRESH_WAKE | Later physical wake follows Home claim retirement | With calibrated evidence, get a new Home claim/handle, open a fresh session, and submit once | Without evidence or a grant, issue no claim and refuse |
| UPLOAD_OR_IDENTITY_FAILURE | Initial upload fails or identity is rejected | Refuse once; return to wake only if authorized | Never retry the capture; rejected identity stays closed |
| FOLLOW_UP_FAILURE | P-3 follow-up or response fails | End the sequence and return to wake without replay | Clear follow-up ownership |

## Code Map

| Area | Path | Role |
|---|---|---|
| Bridge | puck_bridge/turn.py, session.py, puck_bridge/home_session.py, puck_bridge/server.py, config.py | Replace failed sessions; close old Home claims; create a per-wake claim/session only with calibrated evidence |
| Capture and status | puck_bridge/receiver.py, puck_bridge/response.py | Preserve sequence ownership and report failures |
| Device recovery | firmware/respeaker-lite/pcm_capture.h, firmware/respeaker-lite/puck_response.h, firmware/respeaker-lite/respeaker-lite.yaml | Refuse upload failure and resume wake only when authorized |
| Contract coverage | tests/test_puck_bridge.py, tests/test_puck_firmware.py, tests/test_puck_home_session.py | Prove no replay, fresh sessions/claims, refusal, and fail-closed identity |

## Tasks & Acceptance

**Execution:**

- [x] Replace the failed direct session; never resubmit its transcript.
- [x] Stop Home's automatic turn continuation; close the old claim through one bounded control-only path without forwarding unresolved events.
- [x] Add a per-wake Home claim/session path that uses a new handle and requires calibrated proximity evidence; absent evidence or an unconfirmed close stays fail-closed.
- [x] Route initial upload failure through refusal and wake recovery; preserve identity lockout.
- [x] Run focused Puck checks, required repository checks, and ESPHome configuration validation when available.

**Acceptance Criteria:**

- Given transport fails during a Puck turn, recovery marks it unavailable, never replays it, bounds cleanup, and gives one refusal before wake resumes.
- Given a later fresh wake, a verified fresh Hermes session submits only that capture once.
- Given Home loses a turn, recovery closes the old claim without delivering response events; if closure is unconfirmed, Home stays capture-closed.
- Given a later Home wake has calibrated proximity evidence and receives a new claim, it opens a new handle/session and submits that capture once; with no evidence, it refuses without requesting a claim.
- Given initial upload fails, the Puck refuses once without replay; identity rejection keeps capture closed.
- Given focused recovery checks run, the contract passes without changing ESP32 Touch or TUI behavior.

## Verification

**Commands:** Focused bridge/firmware checks, the full repository suite, ESPHome configuration validation when installed, and git diff --check all pass.

**Manual checks (if hardware is available):** Interrupt a response and confirm one refusal; ask again and confirm one turn. With no calibrated Home evidence, confirm Home capture stays closed.

</frozen-after-approval>

## Implementation Notes

The first implementation acquired a replacement Home claim only when a transcript reached the bridge. That was too late: Hermes Home requires a granted wake claim before the Puck records the later wake. The Home path must carry admission to the device before `wake_capture::prepare` opens the microphone. A denied or missing-evidence admission must play one refusal and leave capture closed; a Home identity rejection must remain locked out. A successful grant must be bound to the current wake, and its fresh Home session must be verified before the device is allowed to record. The Puck has no calibrated proximity provider, so the production path currently denies later Home admission.

Before every Home wake opens the microphone, the device must query the bridge's pre-capture admission endpoint, even when its local admission latch is clear. A still-connected current claim may admit that wake without creating another claim; a retired or disconnected claim requires fresh calibrated evidence and a verified replacement session. Only the matching admission response for that wake may open capture. A timeout, missing or expired response, bridge loss, reboot, or identity rejection must leave Home capture closed. The per-turn terminal status is an additional signal, never the sole authorization state. Direct Hermes mode must retain its existing capture behavior.

Keep the direct Hermes recovery path's fresh session identity, bounded cleanup, and no-replay behavior. Keep Home's single bounded control-only reattach for `conversation.close`, discard queued events when the Puck connection fails, and validate the returned handle and closure status. Keep the initial upload refusal path and its response sequence. Separate local delivery failures from transport uncertainty so a completed Home turn does not retire a usable claim merely because playback failed.

Every live Home claim is bound to its authorized wake mapping. The configured initial handle may infer its mapping only when Home exposes one active mapping; otherwise set `HOME_WAKE_MAPPING_ID`. The bridge checks the phrase-to-mapping association before every physical capture and checks the live session before every wake-free follow-up capture. Follow-ups never create Home claims.

Persist the current Home handle and mapping in a private, atomic per-device recovery record before opening a new claim. On process restart, do not reopen the saved handle as an active conversation. An active marker gets one control-only close attempt on the next physical wake; a write-ahead unconfirmed marker or failed close keeps capture closed across restarts. A verified close permits a new claim only when the calibrated evidence provider is available.

The Home service contract is documented in `~/Development/hermes-relay-home/docs/contracts/v1/README.md` and its claim schema. The current claim and close request/response shapes match that contract. The acoustic calibration format and trusted provider remain a hardware-contract decision; do not enable Home re-claims without one.

Verification on 2026-09-23: focused bridge, Home, firmware, HandsFree, and config tests passed (324 passed, 1 skipped); the full repository suite passed (1,597 passed, 2 skipped); ESPHome 2026.8.2 configuration validation and compilation passed; Python compileall and git diff --check passed. Hardware smoke was unavailable. Production wiring has no calibrated proximity provider, so replacement Home claims remain fail-closed; calibration policy and late-grant reconciliation remain deferred to the hardware and Home API contracts.

## Review Triage Log

- [Review][Spec] Home fresh-claim path was unreachable from the current Puck adapter — it starts with one configured handle and has no per-wake claim client. Clarified that P-4 adds a claim/session factory, gated by calibrated proximity evidence.
- [Review][Spec] Home automatically resumes an uncertain turn and local close does not retire its claim — specified one bounded control-only reattach for conversation.close, event discard, and fail-closed behavior if closure is unconfirmed.
- [Review][Defer] carried — the Puck still has no calibrated proximity signal and production wiring still supplies no provider; new Home claims remain denied until the trusted hardware provider exists, as selected by the user.


- `verification-gap/initial-upload-dispatch` — resolved 2026-09-23: `upload_failed(seq)` now owns the initial-versus-follow-up dispatch and the compiled C++ harness asserts both sequence behaviors.
- `verification-gap/direct-session-factory-wiring` — resolved 2026-09-23: server wiring passes the fresh Hermes factory, and the recovery test proves it connects and verifies a replacement for the next fresh question.
- `verification-gap/home-claim-response-binding` — resolved 2026-09-23: factory tests reject responses bound to the wrong claim ID or configuration revision.
- `blind-hunter/failed-delivery-reconnect` — resolved 2026-09-23: local delivery failures are separated from transport uncertainty, so a completed Home claim remains usable; transport loss still retires it.
- `blind-hunter/home-identity-after-capture` — resolved 2026-09-23: every physical wake performs sequence-bound pre-capture Home admission; missing, denied, stale, or identity-rejected responses keep capture closed, including after status expiry, idle disconnect, or reboot.
- `blind-hunter/home-claim-after-capture` — resolved 2026-09-23: fresh claim acquisition runs through the pre-capture wake-admission endpoint before `wake_capture::prepare`.
- `blind-hunter/home-claim-contract-shape` — verdict `false`: the local Hermes Home service contract confirms `POST /api/v1/wake-claims`, Device authorization, and `configuration_revision` in `~/Development/hermes-relay-home/docs/contracts/v1/README.md` and `src/hermes_home/api/application.py`.
- `blind-hunter/calibration-provenance` — verdict `maybe-false`, route `defer`: carried — no production provider is installed, and the Home contract leaves acoustic calibration encoding to a hardware decision; a trusted fresh provider and its provenance contract would settle whether the dataclass is sufficient.
- `blind-hunter/claim-timeout-orphan` — verdict `maybe-false`, route `defer`: carried — a timed-out worker may receive a late grant that occupies a Home claim until its first-open expiry; a delayed-response test or claim reconciliation contract would settle the impact.
- `blind-hunter/reused-home-handle` — verdict `false`: the production Home conversation-claim store uses unique handles and returns no grant on a handle collision, so a successful new grant cannot reuse the closed claim's handle.
- `blind-hunter/close-rpc-contract` — verdict `false`: `hermes-relay-home` implements `conversation.close` and returns the exact `{schema, conversation_handle, status: closed}` result checked by this adapter.
- `blind-hunter/reconnect-budget` — verdict `false`: the 10-second `RECONNECT_TIMEOUT_SECONDS` is the explicit overall recovery ceiling; the acceptance requires bounded recovery and refusal on timeout, not a full run at every nested operation timeout.
- `blind-hunter/epic-context-session-isolation` — verdict `medium`, route `defer`: carried — the modified epic context omits explicit stale session/turn rejection and concurrent doorway isolation, but that human-owned rewrite was already present before P-4 began.
- `blind-hunter/epic-context-diagnostics` — verdict `medium`, route `defer`: carried — the modified epic context omits bounded opt-in diagnostics and content-safe snapshots, but that human-owned rewrite was already present before P-4 began.
- `blind-hunter/epic-context-acceptance-gates` — verdict `medium`, route `defer`: carried — the modified epic context omits measurable zero-audio, zero-recording, and zero-false-wake gates, but that human-owned rewrite was already present before P-4 began.
- `edge-case-hunter/queued-events-after-loss` — resolved 2026-09-23: disconnect clears queued events before transport failure; `test_home_drops_queued_events_after_socket_disconnect` asserts that no stale event is delivered.
- `edge-case-hunter/home-claim-after-capture` — resolved 2026-09-23: `on_wake_word_detected` waits for bridge admission before preparing or starting capture; denied paths cancel the pending capture.
- `edge-case-hunter/calibration-id-payload` — verdict `maybe-false`, route `defer`: carried — the provider's calibration identifier is not sent to Home, but the Home contract leaves the evidence encoding open and no provider is deployed; the hardware evidence contract would settle whether Home must receive it.
- `edge-case-hunter/blocking-evidence-provider` — resolved 2026-09-23: synchronous evidence providers now execute through `asyncio.to_thread` under the evidence timeout, so they cannot block the event loop.
- `edge-case-hunter/late-claim-after-timeout` — verdict `maybe-false`, route `defer`: carried — cancelling the `to_thread` waiter cannot cancel a request already running; a late grant could remain active until its 90-second first-open expiry, pending an API reconciliation contract.
- `blind-hunter/home-admission-status-latch` — resolved 2026-09-23: authorization no longer depends on the volatile terminal-status latch; every Home wake must receive a matching pre-capture admission.
- `edge-case-hunter/idle-home-transport-loss` — resolved 2026-09-23: a physical wake queries bridge admission even when idle transport loss left no response sequence to mark.
- `edge-case-hunter/home-admission-status-window` — resolved 2026-09-23: the next physical wake performs fresh bridge admission regardless of the prior response polling window.
- `edge-case-hunter/home-admission-status-expiry` — resolved 2026-09-23: expiring response status cannot clear the requirement for a new pre-capture admission.
- `edge-case-hunter/home-admission-reboot` — resolved 2026-09-23: each booted Home wake obtains matching bridge admission before microphone capture; the compiled firmware harness covers denial and matching grant branches.
- `blind-hunter/home-grant-session-open-cleanup` — resolved 2026-09-23: failed WebSocket open triggers one bounded control-only close attempt and records retired or unconfirmed state; `test_home_fresh_claim_closes_grant_when_websocket_open_fails` covers the confirmed path.
- `edge-case-hunter/boolean-calibrated-proximity-value` — resolved 2026-09-23: `_valid_evidence` explicitly rejects booleans, and the invalid-evidence parameterization proves no Home request is sent.
- `blind-hunter/calibrated-evidence-qualification` — verdict `maybe-false`, route `defer`: the validator checks range and freshness but no qualifying score or calibration policy; the trusted hardware provider contract is needed to determine whether every value in range is sufficient.
- `blind-hunter/shared-authorization-scope` — verdict `medium`, route `defer`: the pre-existing human-owned epic context narrows authorization language to Puck and ESP32 Touch despite listing Android, browser, and TUI stories; resolving the cross-surface rule belongs to the context owner.
- `verification-gap/queued-event-discard-assertion` — resolved 2026-09-23: the disconnect regression asserts `delivered == []` before the transport error.
- `verification-gap/fresh-session-factory-recovery` — resolved 2026-09-23: `test_turn_runner_reconnects_only_for_a_fresh_question_after_failure` proves the next question uses a newly created, connected replacement and the uncertain question is not replayed.
- `verification-gap/unconfirmed-home-close-denial` — resolved 2026-09-23: `test_unconfirmed_home_claim_close_survives_restart_and_denies_factory_call` asserts the claim factory is never called both before and after restart.
- `verification-gap/wake-admission-branch` — resolved 2026-09-23: the compiled C++ harness calls `prepare()` and `start_pending()` for denial, wrong-sequence, and grant outcomes, and the YAML test checks pre-capture ordering.
- `verification-gap/invalid-calibrated-evidence-cases` — resolved 2026-09-23: stale, future, out-of-range, non-finite, blank-ID, and Boolean values are parameterized and denied before any Home request.
- `edge-case-hunter/active-claim-wake-mapping` — resolved 2026-09-23: every active Home wake now checks that the phrase resolves to the mapping bound to the live claim; multiple active mappings require an explicit initial mapping ID.
- `edge-case-hunter/follow-up-home-readiness` — resolved 2026-09-23: every follow-up capture gets a sequence-bound bridge check, Home requires the live session, and the follow-up path cannot create a claim.
- `edge-case-hunter/follow-up-mailbox-liveness` — resolved 2026-09-23: coordinator completion always disarms an unused follow-up mailbox, including early readiness exits.
- `edge-case-hunter/grant-disconnect-retirement` — resolved 2026-09-23: a granted replacement that loses its socket during handoff receives one bounded control-only retirement attempt; an unconfirmed result denies later claims.
- `edge-case-hunter/home-claim-restart-state` — resolved 2026-09-23: private write-ahead recovery state preserves active, retired, and unconfirmed claim status across bridge process restarts.
- `verification-gap/query-token-admission` — resolved 2026-09-23: route tests now exercise the firmware's query-token transport and verify invalid tokens never invoke the admission callback.
- `verification-gap/firmware-wake-admission-execution` — resolved 2026-09-23: the compiled C++ harness exercises actual `prepare()` and `start_pending()` outcomes for denial, wrong-sequence replies, and a one-capture grant.
- `verification-gap/home-turn-recovery-integration` — resolved 2026-09-23: an integration test submits one uncertain Home turn, verifies a fresh claim, then proves a later capture is submitted once through the replacement session.
- `verification-gap/follow-up-capture-admission` — resolved 2026-09-23: compiled firmware coverage requires an admitted matching response sequence before `start_follow_up()` can open capture.

## Spec Change Log

- 2026-09-22: Home transport included; abandon interrupted turns and require calibrated proximity evidence for fresh claims.
- 2026-09-23: Review clarified Home cleanup, per-wake claim acquisition, and fail-closed behavior while calibrated evidence is unavailable.
- 2026-09-23: Code review found Home authorization was acquired after Puck recording and transcription. Clarified pre-capture Home admission and firmware refusal/lockout, avoiding audio capture without a current grant. KEEP: fresh direct Hermes sessions, bounded Home claim retirement, event discard, claim-response validation, initial upload refusal, and no-replay coverage.
- 2026-09-23: Review found the volatile status-fed Home admission latch can be missed after idle loss, a delayed or expired terminal status, or reboot. Clarified an admission check before every Home capture, fail-closed handling for missing responses, and preservation of direct Hermes capture. KEEP: fresh direct Hermes sessions, bounded Home claim retirement, event discard, claim-response validation, initial upload refusal, and no-replay coverage.
