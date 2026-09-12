---
title: 'Detect idle relay loss and present honest recovery without replaying an uncertain turn'
type: 'feature'
created: '2026-09-12'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '2c6b6854ed6e001000078d24e8ff259991881186'
source_story: '1-T-6'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-4-recover-without-replaying-an-uncertain-turn.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-t-2-keep-tui-disconnect-recovery-presentation-honest-without-replaying-an-uncertain-turn.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-hermes-relay-tui-2026-09-08/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Without an idle liveness observer, a vanished relay can leave the connected TUI falsely healthy until the next user operation. The transport boundary must remain precise across current and legacy `websockets` APIs.

**Approach:** Give each verified `HermesSession` one lifecycle-bound observer that waits only for connection close, using explicit WebSocket keepalive settings (`ping_interval=20s`, `ping_timeout=20s`). A remote close is observed immediately; silent loss is bounded by the next ping plus its timeout, roughly 40 seconds. Route loss through existing honest disconnected and no-replay recovery; later prompts use a fresh verified session before sending once.

## Boundaries & Constraints

**Always:** Only `hello_ack` produces connected/ready state. Supported connections must expose callable `wait_closed()` before readiness; otherwise setup fails closed without an observer. `SessionProtocol.wait_for_disconnect() -> None` binds that connection, waits only for `wait_closed()`, never calls `recv()` or polls, and propagates cancellation; the app owns close, recovery, classification, and UI state. Keep one watcher per session generation; expected app-owned close is silent, prior watchers are bounded before replacement, and stale watchers cannot act.

The observer signals only an idempotent loss transition; the active consumer remains the sole `recv()` owner and settles the turn. Cancellation is silent; `TransportError` enters recovery; another observer exception reports an application error and ends monitoring without claiming network loss. Automatic recovery and `/reconnect` share one single-flight guard.

No turn begins during loss handling or replacement. New prompts remain FIFO-queued until verified recovery; handshake alone never drains them. A later explicit submission may drain known-unsent prompts in FIFO order, unless an ambiguous turn blocks it. A replacement is a new `HermesSession` with a new UUID, preserved profile/client/device/microphone configuration, no old-history hydration, and turn-local reset only after verification.

Every event consumer and audio callback captures session identity and generation. `app.py` rejects stale callbacks, `domain.py` rejects stale events, replacement aborts old playback, and pending structured prompts are bound to session, generation, and prompt ID. Late PCM, queued writes, or prompt responses cannot affect the replacement.

Post-loss recovery reuses bounded retries, handshake timeout, and cleanup. Construction, token, handshake, retry, or close failure leaves the TUI disconnected, preserves partial text, ambiguous state, and queued prompts, clears recovery, and registers no observer until verification. A turn or structured-response write is definitely unsent only when writing never began; otherwise it is ambiguous and never replayed.

At network read and close boundaries, only `ConnectionClosed`, `ConnectionError`, `OSError`, `EOFError`/`IncompleteReadError`, and `asyncio.TimeoutError` become `TransportError`. Malformed JSON, `ProtocolError`, modern `ConcurrencyError`, and legacy concurrent-reader `RuntimeError` remain application failures. The keepalive values are code-level constants, not CLI or environment inputs.

**Never:** Add a background `recv()` loop, duplicate Hermes turn, automatic replay, fabricated completion/playback, or a new wire protocol. Do not alter normal streaming, bounded follow-up, exact local `stop`, wake-resource ownership, or explicit reconnect. Do not broaden this TUI slice to other surfaces.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| HEALTHY_IDLE | Verified session remains open and idle | One watcher remains pending; TUI stays connected | No duplicate watcher or receive task |
| REMOTE_CLOSE | Idle `wait_closed()` completes or keepalive misses | TUI reaches existing disconnected/unavailable state without user action | Recovery hint is visible; no prompt is sent |
| EXPECTED_CLOSE | Quit, reload, or `/reconnect` marks app-owned close | Cancellation/close completion is silent | No loss transition or duplicate recovery |
| UNSUPPORTED_TRANSPORT | Connection lacks callable `wait_closed()` | Setup fails before readiness; no observer or fallback reader starts | Report setup/transport failure |
| OBSERVER_FAILURE | Watcher is cancelled, raises `TransportError`, or another exception | Cancellation is silent; transport loss recovers; other failure reports application error and ends monitoring | Other failure does not claim network loss |
| ACTIVE_TURN | `send_turn()` owns `recv()` while socket loss races watcher | Both paths converge once; partial response remains and turn is ambiguous | No second reader, turn, queue drain, or playback completion |
| WRITE_FAILURE | Turn or prompt-response write fails before or after writing may begin | Definitely-unstarted work is not sent; uncertain work is ambiguous and unreplayed | Preserve no-replay semantics |
| POST_LOSS_RECOVERY | New prompt arrives; replacement handshake succeeds or fails | New UUID-bearing session sends the new prompt once; prompts known not to have been sent remain FIFO and pending until explicit drain | Failure leaves disconnected state and sends nothing |
| STALE_REPLACEMENT | Old session emits event, PCM, callback, queued write, or prompt response | Identity/generation/prompt-ID guards reject it before UI or playback mutation | Old session cannot affect replacement |
| TRANSPORT_CLASSIFICATION | Owned path sees network exception, protocol error, or concurrent-reader failure | Actual transport exceptions become `TransportError`; protocol/programming failures retain their meaning | Do not classify by broad `RuntimeError` |

</frozen-after-approval>

## Code Map

- `config.py` — pass the fixed 20-second keepalive interval/deadline through compatible current and legacy connection signatures.
- `client.py` — define `TransportError` and classify owned network reads/writes without swallowing protocol or programming failures.
- `session.py` — require `wait_closed()` and expose `wait_for_disconnect()` without wire parsing or a second reader.
- `app.py` — own watcher lifecycle, generation/expected-close guards, single-flight recovery, prompt admission, stale output rejection, and presentation.
- `domain.py` and `audio.py` — retain stale-event rejection and prevent old PCM from completing or enqueueing after replacement.
- `tests/test_config.py`, `tests/test_client.py`, `tests/test_session.py`, `tests/test_tui_domain.py`, and `tests/test_app.py` — cover compatibility, liveness, recovery, races, and stale output with fakes.

## Tasks & Acceptance

**Execution:**
- [ ] `config.py`, `client.py`, and `session.py` — implement fixed keepalive settings, the explicit transport boundary, and the wait-for-close session contract — keep the core UI-independent and legacy-compatible.
- [ ] `app.py` — add one generation-guarded watcher, idempotent loss handling, bounded fresh-session recovery, serialized FIFO admission, expected-close suppression, and stale output/prompt rejection — preserve T-4 no-replay behavior.
- [ ] `domain.py` and `audio.py` — enforce stale event/PCM/callback isolation and abort old playback — keep replacement presentation uncontaminated.
- [ ] `tests/test_config.py`, `tests/test_client.py`, `tests/test_session.py`, `tests/test_tui_domain.py`, and `tests/test_app.py` — add fake transport tests for every matrix path while preserving explicit reconnect/streaming coverage.

**Acceptance Criteria:**
- Given a verified idle session, when the relay closes or misses the 20-second ping/pong policy, then the TUI reaches disconnected/unavailable without waiting for user input.
- Given an active streamed turn, when watcher and reader loss signals race, then one receive owner and one idempotent loss transition preserve partial text, ambiguity, and no queue drain.
- Given current or legacy `websockets`, when an owned path sees a supported network failure, then it raises `TransportError`; malformed JSON, protocol errors, and concurrent-reader programming errors do not.
- Given a prompt arrives during automatic recovery or concurrent `/reconnect`, when recovery completes, then only one fresh UUID-bearing session exists, prompts known not to have been sent remain FIFO, and the new prompt is sent once only after verification.
- Given recovery or app-owned teardown fails or completes, when its tasks settle, then the TUI remains honest, preserves queued/ambiguous state, and reports no duplicate loss or recovery.
- Given old-session events, audio, callbacks, queued writes, or structured responses arrive after replacement, when the new session is active, then identity/generation/prompt-ID guards reject them before mutation.

## Implementation Notes

- Added fixed 20-second keepalive settings through current and legacy-compatible connection signatures, plus an explicit `TransportError` boundary for owned websocket reads and writes.
- Added the verified-session `wait_for_disconnect()` contract and one generation-bound, close-only app watcher. Expected teardown is silent; transport loss is idempotent and recovers through a fresh UUID-bearing session without history hydration or prompt replay.
- Bound turn consumers, audio callbacks, structured prompts, and prompt admission to session identity and generation. The admission critical section also preserves FIFO while loss handling is acquiring the connection lock.
- Retained the existing domain stale-event and player-abort authorities; no UI framework dependency entered the core modules.
- Added fake transport, liveness, recovery, race, stale-stream, compatibility, and programming-error regressions.

## Review Triage Log

- Local blind/edge/verification review (2026-09-12; no subagent runtime available): sampled the complete 302.5 KiB unified diff at the required ten-item floor and found no unresolved omission. The known playback-drain wake failure was reproduced as a pass in the baseline worktree and passed repeatedly plus in the complete wake module, so it was treated as suite timing noise rather than a T-6 regression.
- Local edge review: stale timeout and `connection_lost` paths could resolve the current session dynamically after replacement; verdict: medium, patched by passing the originating session and generation through the loss paths.
- Local edge review: a prompt could pass its initial loss check while loss handling was waiting for the connection lock; verdict: medium, patched with an admission critical section and a deterministic FIFO/no-send regression.
- Local edge review: a stale stream exception could finalize old output into the replacement; verdict: medium, patched with session-generation guards around result, exception, finalization, and cleanup paths.
- Local cleanup review: shutdown close bypassed the session-keyed bounded cleanup registry; verdict: low, patched to reuse the retained-task helper and avoid a duplicate close race.
- Verification-gap review: no remaining gaps were found against the frozen matrix after the focused and complete suites passed.

## Verification

**Commands:**
- `venv/bin/pytest -q tests/test_config.py tests/test_client.py tests/test_session.py tests/test_tui_domain.py tests/test_app.py` — `357 passed` in 42.36s after rebasing the PR comparison onto current `main`.
- `venv/bin/pytest` — `1,064 passed, 1 skipped, 1 warning` in 97.83s; the warning is the existing `websockets.legacy` deprecation.
- `venv/bin/python -m compileall -q app.py client.py config.py prompts.py session.py` — passed.
- `git diff --check` — passed.

**Manual checks (if no CLI):**
- With an unavailable fake endpoint, verify idle loss by the configured bound, preserve uncertain context, send no old prompt, then confirm one fresh post-recovery send.
