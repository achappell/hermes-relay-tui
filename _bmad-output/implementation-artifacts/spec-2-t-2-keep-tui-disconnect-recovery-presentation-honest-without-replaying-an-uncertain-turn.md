---
title: 'Keep TUI disconnect and recovery presentation honest'
type: 'feature'
created: '2026-09-11'
status: 'done'
route: 'dispatch'
review_loop_iteration: 1
baseline_commit: 'ec2f0f1d4bcd62b00746e4fdb838a0b5593f6dea'
source_story: '2-T-2'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-4-recover-without-replaying-an-uncertain-turn.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-t-1-keep-tui-capture-and-phase-state-visible.md'
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The TUI already has bounded reconnect and no-replay mechanics, but the visible recovery contract is not fully proved at the widget boundary. A transport failure must never leave the conversation looking as though Hermes is still thinking or ready, and compact layouts must not hide the only useful recovery signal.

**Approach:** Make the TUI's disconnected, failed-turn, and verified-recovery presentation explicit and regression-tested. Preserve partial assistant text and safe queued prompts while keeping ambiguous turns unreplayable; return to `ready` only after a fresh verified handshake.

**Decision:** Generic transport failures use the same visible `Disconnected` recovery state as explicit connection-loss events. The TUI does not make the household distinguish failure source before recovery is available.

## Boundaries & Constraints

**Always:** Show an observed disconnected or unavailable state until `hello_ack` verifies recovery; keep partial response text readable; preserve FIFO ordering for unsent prompts; keep ambiguous prompts out of `/retry`; require fresh user initiation after recovery; keep wake and microphone disarmed after connection loss and reconnect.

**Never:** Change the Hermes wire protocol or server; automatically resend an uncertain turn; delete partial text or queued prompts; add a second WebSocket reader or recovery state owner; alter bounded follow-up or exact `stop`; broaden this story to iOS, browser, appliance, firmware, or the deferred non-blocking wake-teardown refactor.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| PARTIAL_TRANSPORT_LOSS | Active turn has streamed partial response, then the session loses transport | The partial response remains readable; connection presentation is visibly unavailable/disconnected and never remains indefinitely `thinking`; the prompt is ambiguous and is not replayed | Preserve the failure state and expose the existing explicit recovery action |
| IDLE_DISCONNECTED_COMPACT | No active turn; connection is lost; terminal is compact | The connection status remains visible and the empty state explains that recovery is required | Do not hide the only recovery signal because of compact layout |
| RECONNECT_SUCCESS | Disconnected TUI invokes `/reconnect`; fresh session receives verified `hello_ack` | The UI shows connected/ready; queued prompts remain unchanged; no prior prompt is sent; wake remains off | A later explicit fresh submission may proceed |
| RECONNECT_FAILURE | `/reconnect` exhausts bounded attempts or handshake is rejected | The UI remains visibly disconnected/unavailable and retains safe partial/queued context | No ready claim, queue drain, wake re-arm, or replay |

</frozen-after-approval>

## Code Map

- `app.py` — `_set_connection_state`, `_refresh_connection_status`, `_refresh_voice_status`, `_connect`, `_mark_connection_lost`, `_consume_turn`, and `_handle_reconnect_command` own the presentation and recovery transitions. Reuse the existing bounded handshake, session replacement, transcript finalization, queue preservation, and wake-disarm paths; do not add protocol parsing here.
- `domain.py` — `ConnectionPhase`, `TurnPhase`, `DomainState.display_state`, `reset_session`, and stale-event guards remain the normalized state authority. Reuse them rather than creating a TUI-only recovery state.
- `tests/test_app.py` — existing fakes cover reconnect, ambiguous partial responses, queue retention, cleanup failures, and fresh session identity. Extend the caller-path assertions to inspect visible connection/voice widgets and compact-layout behavior without fixed sleeps.
- `tests/test_client.py` and `tests/test_tui_domain.py` — existing stale-session, late-event, late-audio, and disconnected transition coverage remains the lower-boundary proof; change only if the implementation exposes a genuine missing invariant.
- `commands.py` and `README.md` — existing `/reconnect` behavior is already defined; preserve its reconnect-only wording unless the final presentation choice requires a precise label clarification.

## Tasks & Acceptance

**Execution:**
- [x] `app.py` — align visible connection/voice labels and compact-layout visibility with the approved failure-label decision, preserving existing recovery ownership and no-replay behavior.
- [x] `tests/test_app.py` — add synchronized Given/When/Then coverage for partial transport loss, compact disconnected presentation, successful recovery, failed recovery, and no replay/queue drain.
- [x] `tests/test_client.py` and `tests/test_tui_domain.py` — retain and extend lower-boundary assertions only where the implementation changes a normalized state invariant.
- [x] `README.md` — update recovery wording only if the approved failure-label decision changes the documented user-facing state vocabulary.

**Acceptance Criteria:**
- Given a partial Hermes response followed by transport loss, when the TUI settles the turn, then partial text remains visible, the UI shows an honest failure/recovery state, and the uncertain prompt cannot be retried automatically.
- Given an idle disconnected TUI in a compact terminal, when the layout refreshes, then the disconnected status and recovery explanation remain visible.
- Given `/reconnect` succeeds, when a fresh `hello_ack` is received, then the TUI returns to `ready` without replaying the prior prompt, draining the queue, or rearming wake.
- Given `/reconnect` fails, when bounded recovery ends, then the TUI remains disconnected/unavailable and retains safe partial or queued context.
- Given a later explicit fresh prompt after verified recovery, when it is submitted, then it is the only new Hermes turn sent.

## Implementation Notes

- Generic stream transport failures now retain the explicit `Disconnected` voice and connection presentation instead of being overwritten by a generic `error` label.
- Connection-state changes refresh the empty-state recovery explanation, keeping the disconnected signal visible in compact idle layouts.
- Added app-level regressions for partial transport loss, compact disconnected presentation, connected-idle state refresh, failed reconnect visibility, and explicit post-recovery submission without replay.
- Transport classification now limits disconnected presentation to built-in connection errors and WebSocket closure/concurrency errors; application failures remain visible as `error` without forcing recovery.
- Focused recovery suite: `venv/bin/pytest tests/test_app.py tests/test_client.py tests/test_tui_domain.py tests/test_commands.py -q` — 285 passed.
- Complete suite: `venv/bin/pytest` — 999 passed, 1 failed. The remaining failure is `tests/test_app_wake.py::test_tui_waits_for_playback_drain_before_opening_a_follow_up`, the pre-existing timing-sensitive wake playback-drain issue outside this story.
- `git diff --check` — passed. The four matrix rows are covered by the compact-disconnect, transport-loss, explicit-reconnect, and existing bounded-failure/no-replay tests, all included in the focused run.

## Spec Change Log

## Review Triage Log

- [x] [Review][Patch][medium] Blind hunter: idle connected-to-disconnected empty-state coverage was missing — added a caller-path regression that clears the transcript, changes the live connection state, and asserts the compact recovery copy/status refresh.
- [x] [Review][Patch][low] Blind hunter: successful recovery assertions did not include ready, wake-off, or the explicit fresh prompt boundary — added ready and wake assertions; existing reconnect coverage retains the queue and verifies no prompt is sent during recovery.
- [x] [Review][Patch][medium] Blind hunter and edge hunter: the generic exception branch treated every exception as transport loss — added `_is_transport_error()` for built-in connection errors and WebSocket closure/concurrency errors; non-transport failures remain `error` without forcing reconnect.
- [x] [Review][False][false] Blind hunter: spec and tracker status differed during review — this is the intentional build lifecycle (`in-progress` while implementation is active, `review`/`done` at the corresponding gates); they will be aligned when this review closes.
- [x] [Review][False][false] Blind hunter: the verification note did not claim a green complete suite — it records the exact 955/16 result, native SDK-link failures, the unchanged-baseline wake failure, and the isolated passing Ctrl+C check; no spec rewrite is required.
- [x] [Review][Patch][low] Blind hunter: explicit failed-reconnect visibility was not asserted together with uncertain text and queued prompts — extended the failed `/reconnect` caller-path test to assert the disconnected status and retained queue.
- [x] [Review][False][false] Edge hunter: `_connect()` could theoretically see a connected session while the app state is disconnected — `/reconnect` sets `force=True`, replaces the session, and only returns connected after that session's verified `connect()` path; the non-forced fast path is the already-verified normal session path.
- [x] [Review][False][false] Verification-gap hunter: no additional verification gap was identified.
- [x] [Review][False][false] Post-patch verification-gap hunter: the reported 958/15 result conflicts with the witnessed 959/14 run, and the targeted wake test passes; the final verification record will use the directly observed rerun rather than the stale reviewer claim.
- [x] [Review][Patch][low] Post-patch verification-gap hunter: the newly supported WebSocket exception classes lacked caller-path coverage — added parameterized closure and concurrency failures asserting disconnected presentation and recovery hint.
- [x] [Review][Patch][low] Post-patch verification-gap hunter: the explicit fresh-prompt test did not begin with an uncertain old turn — it now does, and asserts only that uncertain turn on the old session and only the fresh prompt on the recovered session.
- [x] [Review][Patch][low] Post-patch verification-gap hunter: compact transition coverage still refreshed the transcript first — removed that refresh and runs the connected-to-disconnected transition at compact size directly.
- [x] [Review][Patch][high] Post-patch edge hunter: non-transport failures left the domain turn active — the exception path now applies a terminal domain error event, and the regression submits a subsequent prompt successfully.
- [x] [Review][Patch][medium] Post-patch blind hunter: ambiguous sent turns could drain queued prompts — queue draining now requires `PROMPT_COMPLETED`, and transport-loss coverage asserts the queue remains intact.
- [x] [Review][Patch][medium] Post-patch blind hunter: failed-session cleanup could block recovery — connection-loss cleanup now uses the bounded retained-task helper.
- [x] [Review][Patch][medium] Post-patch blind hunter: status/detail-only transcript records suppressed the idle recovery explanation — empty-state visibility now keys off meaningful user/assistant conversation records.
- [x] [Review][False][false] Post-patch blind hunter: the 955/16 verification totals and `venv/bin/pytest` path describe the earlier implementation pass, not the final observed run; the implementation notes are reconciled to the final worktree-relative commands below.
- [x] [Review][False][false] Post-patch blind hunter: the 958/15 report was stale and conflicted with the directly observed final run; the wake failure did occur in the final suite but is documented as pre-existing from the unchanged baseline, with the isolated wake check passing.
- [x] [Review][Patch][low] Post-patch blind hunter: the queue could drain after an ambiguous sent turn — queue draining now requires `PROMPT_COMPLETED`, and the transport-loss test asserts the pending prompt remains queued.
- [x] [Review][Patch][medium] Post-patch blind hunter: a hanging close could block recovery — `_mark_connection_lost()` now uses bounded cleanup with retained late ownership.
- [x] [Review][Patch][medium] Post-patch blind hunter: status-only records hid the idle disconnected explanation — empty-state visibility now counts only meaningful visible conversation, while connected startup still hides it.
- [x] [Review][Patch][high] Post-patch edge hunter: non-transport exceptions could leave a phantom active turn — the exception path applies the terminal domain error transition, and the follow-up prompt regression passes.
- [x] [Review][Patch][high] Final edge hunter: unconditional `ConcurrencyError` import would break supported websockets 13.x installations — the import now falls back safely when that newer exception is unavailable, and the test collection uses the same compatibility guard.
- [x] [Review][False][false] Final blind hunter: preferring the live session ID in the status line would break the existing `/reload` contract, which intentionally reflects the current configured session target before a new handshake; the unrelated suggestion was reverted.
- [x] [Review][False][false] Final verification-gap hunter: reviewer-run totals varied because the wake test is timing-sensitive; the authoritative direct final worktree run is the 999 passed/1 failed result recorded above, with the known pre-existing wake failure outside this story.

### Review Findings

- [x] [Review][Patch] Prevent a timed-out failed-session cleanup from being reused or closed twice [app.py:1129-1137,1327-1365,3613-3619] — fixed by guarding reconnect-required sessions from the connected fast path, reusing one session-keyed close task, and adding caller-path coverage for stale connected state, bounded return, and one close call.
- [x] [Review][Patch] Preserve a domain-rejected turn as an unsent FIFO prompt [app.py:3497-3523] — fixed by resetting the pre-wire rejection to `PROMPT_NOT_SENT`, applying the terminal domain error, and proving no session send plus queue retention.
- [x] [Review][Patch] Point transport-loss recovery at the explicit reconnect action [app.py:3561-3578; tests/test_app.py:1094-1115] — fixed by naming `/reconnect` and the required fresh prompt in `RETRY_HINT`, with the focused assertion updated.
- [x] [Review][Patch] Prove the compact connected-to-disconnected transition at the widget boundary [tests/test_app.py:331-357] — fixed by asserting the compact connection widget remains visible and carries the disconnected class.
- [x] [Review][Defer] Verify legacy websockets 13.x transport classification [app.py:41-46,373-377; tests/test_app.py:15-20,1087-1091] — deferred: `maybe-false`; the current fallback avoids an import failure on websockets 13.x, but the diff does not establish whether that version's concurrent-reader `RuntimeError` should be classified as transport loss, and the one-reader guard makes the path unreachable in normal use. Settle with a supported 13.x test environment and an explicit classification decision before changing the broad `RuntimeError` boundary.
- [x] [Review][Defer] Detect a relay drop while the TUI is idle [client.py:272-316; app.py:814-819] — deferred: pre-existing and outside `2-T-2`; the client has no idle receive/liveness path, so a remote drop can remain visibly connected until the next operation. This requires a separate liveness policy and is not introduced by the reviewed presentation change.

#### Rejected

- `false` — Plain `OSError` and `EOFError` are not automatically transport failures here: `OSError` can be a local playback failure, while the Hermes websocket path exposes `ConnectionClosed`/`ConnectionError`; broadening the classifier would mislabel local errors as relay loss.
- `false` — Wake disarm on connection loss is already covered by `tests/test_app_wake.py`, including microphone release and disconnected reporting.
- `false` — The story/tracker status difference is the intentional review lifecycle; the tracker remains authoritative until this gate closes.
- `false` — The `../../venv/bin/pytest` commands are valid when run from the implementation-artifact directory, which is the documented context for that recorded command; this is not a product or code defect.
- `false` — Adding failing test identifiers and baseline command detail would edit the story’s verification prose only; the review workflow does not turn that documentation request into a code finding.

## Verification

**Commands:**
- `../../venv/bin/pytest tests/test_app.py tests/test_client.py tests/test_tui_domain.py tests/test_commands.py -q` — expected: all focused recovery and presentation tests pass.
- `../../venv/bin/pytest -q` — expected: complete Python suite passes; any unrelated native display/WASM SDK-link failure is recorded rather than misattributed to the TUI.
- `git diff --check` — expected: no whitespace errors.

**Manual checks (if no CLI):**
- Against a deliberately unavailable endpoint, verify that the TUI shows disconnected/unavailable in both normal and compact layouts, preserves partial text and queued prompts, and returns to ready only after explicit verified reconnect; no live token is required for the automated path.
