---
title: 'Recover without replaying an uncertain turn'
type: 'feature'
created: '2026-09-09'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '974bec8ed068b0a67172242ceeae460e7d860e2f'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-hermes-relay-tui-2026-09-08/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-hermes-relay-tui-2026-09-07/EXPERIENCE.md'

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The TUI already bounds reconnect attempts and refuses to replay a prompt that may have reached Hermes, but recovery is implicit: there is no reconnect-only action, and a reconnect reuses the prior session object. The client also filters streamed frames by turn identity without rejecting a frame that advertises a different Hermes session, leaving a stale-session path insufficiently explicit.

**Approach:** Add an explicit `/reconnect` command that closes the failed session, creates a fresh `HermesSession`, performs the existing bounded verified handshake, resets turn-local domain state, and leaves all queued prompts untouched. Strengthen the normalized client boundary to discard JSON frames from another session while retaining the existing turn-id, generation, and late-audio guards.

## Boundaries & Constraints

**Always:** Recovery is visible as connecting/retrying/disconnected/ready state; only a successful `hello_ack` can restore connected/ready state. `/reconnect` never sends a prompt, drains the queue, reopens wake capture, or replays an ambiguous turn. Prompts proven not to have been sent remain FIFO-ordered for a later explicit submission. Partial text remains visible after an uncertain turn. Blocking close, capture, and handshake work stay off the Textual event loop. Diagnostics remain content-safe.

**Never:** Change the Hermes wire protocol or server behavior, invent a response, automatically resend a turn, discard unsent queued prompts during recovery, alter ordinary `Ctrl+R` semantics, or change Story 1.3's bounded follow-up and exact local `stop` behavior. Do not broaden this into iOS, appliance, firmware, or cross-surface recovery.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|-----------------------------|----------------|
| RECONNECT_SUCCESS | Idle disconnected TUI; `/reconnect`; endpoint accepts `hello_ack` | Old session is closed, a fresh session object handshakes, domain turn state resets, and the TUI returns ready without sending a prompt | Wake remains disarmed; queued prompts remain visible and unchanged |
| RECONNECT_FAILURE | Idle disconnected TUI; bounded attempts exhausted or handshake rejected | TUI remains disconnected and explains that recovery failed | No ready state, prompt send, queue drain, or wake re-arm |
| UNCERTAIN_TURN | Active turn loses transport after submission | Partial response remains readable and the prompt is marked ambiguous | No automatic resend; explicit reconnect is the only recovery action |
| UNSENT_QUEUE | Prompt cannot be sent before a verified connection; reconnect then succeeds | The prompt remains FIFO-queued across recovery and is not sent by `/reconnect` | A later explicit submission may drain safe queued prompts in order |
| STALE_SESSION_FRAME | JSON frame carries a different `session_id` than the active connection | Frame is discarded without changing transcript, phase, prompt, or audio state | Existing turn-id, generation, and late-event rejection remain authoritative |

</frozen-after-approval>

## Code Map

- `app.py` — `_connect`, `_mark_connection_lost`, `_run_turn`, `_run_single_turn`, `_profile_switch_is_busy`, and command dispatch own connection state, prompt outcome, queue preservation, session replacement, and wake disarm.
- `commands.py` — `COMMAND_REGISTRY` owns slash-command help, completion, and the new reconnect-only command.
- `client.py` — `send_turn` owns normalized frame filtering; add session-identity rejection beside its existing turn-id filtering without changing wire names.
- `domain.py` — `TuiDomain.reset_session` and `_reject_stale_event` already provide the turn-local reset and late-event invariants; reuse them rather than adding a second state owner.
- `tests/test_app.py` — fake sessions cover reconnect attempts, queue preservation, ambiguous turns, and command behavior; add fresh-session and reconnect-only regressions.
- `tests/test_client.py` and `tests/test_tui_domain.py` — cover wrong-session JSON frames and late event/audio rejection at the core boundaries.
- `README.md` — document `/reconnect` and distinguish reconnect-only recovery from safe `/retry` of an unsent prompt.

## Tasks & Acceptance

**Execution:**
- [x] `app.py` — add `/reconnect` handling and a guarded fresh-session recovery path that preserves the queue, disarms wake, uses bounded `_connect`, and never submits text — make recovery explicit and single-flight.
- [x] `commands.py` and `README.md` — register and explain the reconnect-only command — keep the visible recovery contract honest and discoverable.
- [x] `client.py` — reject JSON frames whose advertised session identity differs from the active session — prevent stale-session content from crossing the protocol boundary.
- [x] `tests/test_app.py`, `tests/test_client.py`, and `tests/test_tui_domain.py` — add Given/When/Then coverage for successful/failed reconnect, fresh session identity, queue retention, ambiguous no-replay, wrong-session frames, and late audio — prove the recovery matrix with fakes and no live endpoint.

**Acceptance Criteria:**
- Given the TUI is idle and disconnected, when `/reconnect` succeeds, then a new verified session is created, turn-local state is reset, the TUI is ready, wake remains off, and no prompt is sent.
- Given reconnect attempts fail, when recovery ends, then the TUI remains visibly disconnected and queued prompts and ambiguous turns are unchanged.
- Given a submitted turn loses transport, when recovery is requested, then partial text remains visible and neither the failed turn nor an ambiguous prompt is replayed.
- Given an unsent prompt is queued, when `/reconnect` succeeds, then it remains in FIFO order until a later explicit submission drains it.
- Given a frame from another Hermes session or a late event/audio frame arrives, when the active TUI consumes it, then it cannot mutate the current session's transcript, phase, prompt, or playback.

## Implementation Notes

- Added reconnect-only recovery with a fresh session object, bounded cleanup and handshake, no history hydration, no queue drain, no prompt replay, and a single-flight/prompt guard.
- Preserved the selected microphone input across a fresh session and rejected stale session identities in both top-level and nested JSON event payloads.
- Added app, wake, client, command, and domain regression coverage; focused and complete suites pass.

## Spec Change Log

## Review Triage Log

- blind-hunter: reconnect could race an ordinary prompt submission — verdict: medium; route: patch; `_run_turn` now queues prompts while `_reconnect_in_flight`, with a concurrent recovery regression covering the no-send guarantee.
- blind-hunter: failed reconnect reset domain state before the new handshake — verdict: medium; route: patch; pre-handshake `reset_session` was removed so `_connect` resets turn-local state only after verified connection, while disconnected recovery preserves the prior response projection.
- blind-hunter: reconnect suppresses server history hydration — verdict: false; the reconnect-only contract preserves the existing transcript so fresh-session history cannot be mixed into an uncertain turn; ordinary initial connection still hydrates history, and the reconnect test locks this behavior.
- blind-hunter: interactive audio input selection was lost when replacing the session — verdict: medium; route: patch; the selected device is reapplied to the fresh session and covered by a regression test.
- blind-hunter: raw PCM bytes lack a new session identity filter — verdict: false; raw bytes are read from the session's websocket, and `/reconnect` blocks active turns before replacing that session; the changed cross-session boundary is JSON, while domain generation and late-audio guards remain the authority for event/audio rejection.
- blind-hunter: an old-session close exception could leak cleanup — verdict: low; route: patch; reconnect cleanup is now bounded and retained, and close failures are contained so a fresh session can still be established without trapping the TUI.
- blind-hunter: the UI did not show disconnected state until old-session close returned — verdict: medium; route: patch; disconnected/reconnecting state is painted before cleanup, and cleanup has the existing bounded timeout policy.
- edge-case-hunter: reconnect history hydration lacked a test — verdict: low; route: patch; a fresh-session history fixture now proves recovery does not mix server history into the preserved transcript.
- edge-case-hunter: active-turn reconnect refusal lacked a caller-path test — verdict: low; route: patch; the command-path regression proves the old session remains open and no replacement is created while a turn is active.
- edge-case-hunter: configured wake behavior across explicit reconnect lacked a test — verdict: low; route: patch; the wake regression proves explicit recovery disarms wake and does not re-arm it from launch configuration.
- edge-case-hunter: single-flight reconnect protection lacked a concurrency test — verdict: low; route: patch; a gated handshake test proves a second command is rejected and does not replace the in-flight fresh session.
- edge-case-hunter: nested payload session identity lacked coverage — verdict: low; route: patch; the client regression includes a current top-level identity with a stale nested identity and confirms the frame is discarded.
- verification-gap: a hanging close could leave recovery waiting — verdict: medium; route: patch; recovery now paints disconnected state before cleanup and bounds retained close work with `SHUTDOWN_TASK_TIMEOUT`.
- verification-gap: a session factory exception could leave the old closed session appearing connected — verdict: medium; route: patch; fresh-session construction is contained, leaves the app disconnected, and reports that no prompt was sent.
- verification-gap: close failure was silently ignored — verdict: low; route: patch; close failures are diagnosed and do not prevent bounded recovery from proceeding to the fresh session.

## Design Notes

`/retry` remains deliberately narrow: it can resend only a prompt proven never to have reached Hermes. `/reconnect` is therefore a separate command that repairs the transport without implying that any prior request is safe to repeat.

## Verification

**Commands:**
- `venv/bin/pytest -q tests/test_app.py tests/test_client.py tests/test_tui_domain.py tests/test_commands.py` — expected: all focused recovery, command, and stale-event tests pass.
- `venv/bin/pytest` — expected: complete suite passes with only known pre-existing warnings.
- `git diff --check` — expected: no whitespace errors.

**Manual checks (if no CLI):**
- Against a deliberately unavailable endpoint, run `/reconnect` and verify bounded failure, disconnected state, no wake re-arm, and no queue drain; after restoring the endpoint, run `/reconnect` and verify ready state before submitting a fresh prompt. No bearer token or live endpoint is required for automated validation.
