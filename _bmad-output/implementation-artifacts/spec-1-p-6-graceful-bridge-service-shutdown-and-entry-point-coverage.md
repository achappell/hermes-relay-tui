---
title: 'Graceful Puck bridge service shutdown and entry-point coverage'
type: 'bugfix'
created: '2026-09-22'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
story_key: '1-p-6-graceful-bridge-service-shutdown-and-entry-point-coverage'
baseline_commit: '1cb112865a7ff791890af0949132c751e5153b11'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The standalone Puck bridge handles KeyboardInterrupt but not SIGTERM. Startup failures can escape cleanup, and stopping its event loop can strand an active turn, playback, or response reader.

**Approach:** Give startup, signals, and failures one idempotent shutdown path. Close admission, terminate interrupted response delivery, cancel active work once, and release owned resources within an explicit wait budget while retaining ownership of cleanup that cannot immediately finish.

## Boundaries & Constraints

**Always:** Preserve legacy and Home configuration, token validation before resource startup, one active turn, no replay, and normal successful playback draining. SIGINT and SIGTERM request shutdown without blocking the signal handler. Reject late uploads/transcripts after shutdown starts. Preserve reconnect cancellation ownership; do not cancel cleanup repeatedly. Report incomplete cleanup truthfully using content-safe diagnostics.

**Never:** Change Hermes wire semantics, firmware, pairing, response success criteria, or P-7 diagnostics policy. Do not kill threads, force process exit, drop cleanup ownership to claim success, or call HTTPServer.shutdown from its serving thread. No deployment or live household interruption is part of this implementation.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected behavior | Error handling |
|---|---|---|---|
| Missing configuration | No PUCK_DEVICE_TOKEN | Nonzero clear configuration failure; no server or runner construction/start | No credential values printed |
| Service termination | SIGINT/SIGTERM while idle or active | Stop admission; serving loop exits; interrupted stream unavailable; owned cooperative workers/resources finish | No successful response terminator for interrupted delivery |
| Repeated shutdown | Repeated signals or concurrent stop calls | One cleanup owner; no double-close exception | No renewed wait budget |
| Partial startup | Connect, handler creation, or bind fails | Release everything already acquired | Preserve original failure |
| Late work | Upload/transcription completes during shutdown | No new turn or response admitted | Existing no-replay behavior retained |
| Slow cleanup | Session/generator/native operation outlives wait budget | Caller returns within budget; retain cleanup owner until it finishes | Explicit pending-cleanup evidence; never claim release prematurely |

**Approved process policy (2026-09-22):** Stop serving within one second. All bounded shutdown callers share ten seconds from the first request. If cleanup remains pending, warn without private content and keep the standalone process non-serving until retained cleanup finishes. There is no hard process-exit deadline for a permanently stuck native operation; never discard its owner or call it released.

</frozen-after-approval>

## Code Map

- `puck_bridge/server.py`: main owns configuration, session, ResponseStream, TurnRunner and HTTP server; start and handler construction currently precede its finally block.
- `puck_bridge/turn.py`: start/stop own the background loop; _send does not retain its turn future; _run_turn finally drains playback. Preserve reconnect cleanup ordering.
- `puck_bridge/response.py`: fail_delivery clears queued PCM and wakes blocked readers/producers; add permanent shutdown admission protection without altering normal sequence reuse.
- `puck_bridge/receiver.py`: daemon HTTP workers can outlive listener closure; track active request workers, capture buffers and temporary WAV/directory ownership as well as sockets; prevent late admission and verify eventual cleanup.
- `puck_bridge/__main__.py`: module entry delegates to main and propagates its exit code.
- `tests/test_puck_bridge.py`: existing fakes and reconnect cleanup test provide regression coverage; add focused lifecycle tests in `tests/test_puck_bridge_shutdown.py`.

## Tasks & Acceptance

**Execution:**
- [x] `puck_bridge/server.py` — protect all acquired resources, install/restore signal handlers before blocking startup, coordinate serving shutdown outside its serving thread, and prevent listener startup after a stop request.
- [x] `puck_bridge/turn.py` — synchronize shutdown admission independently of the transcript lock; retain/cancel initial connection and active work once; abort interrupted playback independently of stalled generator cleanup; close the session and event loop after owned cleanup.
- [x] `puck_bridge/response.py`, `puck_bridge/receiver.py` — latch shutdown, wake blocked delivery, close active sockets, release partial capture buffers, retain transcription/WAV cleanup ownership and reject late admission without changing ordinary response handling.
- [x] `tests/test_puck_bridge_shutdown.py`, `tests/test_puck_bridge.py` — cover the matrix with fake sessions/audio, real local sockets, and subprocess signals; verify module entry wiring and exit behavior.
- [x] This specification and `sprint-status.yaml` — record verified implementation/review evidence; retain tracker `review` pending remote delivery. Board mirror remains pending under the coordinator board-pause instruction.

**Acceptance Criteria:**
- Given a serving bridge, when SIGINT or SIGTERM arrives, then serving exits within one second and cooperative session, active-turn, socket, audio and response resources are released within ten seconds of the first request; use monotonic deadlines, with no per-stage budget resets.
- Given shutdown already started, when another signal/stop call or late transcript arrives, then cleanup runs once and no new turn starts.
- Given missing Puck credentials, when main runs, then it returns nonzero with a useful error before constructing the runner or server.
- Given valid legacy or Home configuration, when main runs, then the expected server, runner and response/playback mode are wired and share the cleanup path.
- Given a partial startup failure or blocked cleanup, when shutdown runs, then acquired resources retain a single owner and the bounded caller never reports pending cleanup as complete.

- Given initial connection is pending, when either signal arrives, then cancellation is requested once, no listener starts afterward, and session closure follows connection cleanup.
- Given a partial upload or active transcription, when shutdown starts, then sockets and partial buffers are released, late results cannot submit or change response ownership, and the temporary WAV and owned directory are removed when the retained worker finishes.
- Given an async generator stalls during cleanup, when host playback is active, then playback abort is requested independently without waiting for that generator; no cleanup task, executor operation or loop is reported released while still active.

## Implementation Notes

- Added permanent response/receiver admission latches, active request/socket ownership, partial-capture clearing, and retained temporary WAV/directory cleanup. Late transcription results cannot submit a turn or replace its response sequence.
- TurnRunner uses an independent lifecycle lock and a single monotonic deadline. It retains initial connect, active turn, reconnect, native startup, playback abort, and event-loop/executor ownership. Async child cancellation is requested once, including shutdown during timeout cleanup. Normal successful playback still drains.
- Bridge-owned PCM playback performs native teardown in retained executor work. Native open, write, and close completion are observed independently from cancellation of their asyncio wrappers; late native opens are closed after they complete.
- Main installs and restores SIGINT/SIGTERM handlers around startup. Signal handlers latch intent; a coordinator initiates cleanup and reports budget expiry even while initial connection cleanup remains pending. HTTP serving checks the stop latch every 0.1 seconds and separates server construction, bind, and activation. The standalone process remains non-serving until retained cleanup finishes.
- Added `tests/test_puck_bridge_shutdown.py` with fake sessions/audio, loopback sockets, actual module-entry subprocess signals (idle, connecting, and active turn), repeated signals beyond an injected wait budget, partial startup failures, concurrent stop calls, delayed transcription, and native/generator ownership checks. Existing successful response tests now consume audio before stopping the bridge, because shutdown intentionally discards undelivered audio.
- Verification: existing bridge plus the initial 18 lifecycle cases passed (111 tests). The complete suite passed 1544 tests with one skip and six websockets deprecation warnings in 218.06 seconds. After full-suite collection, two additional audit cases were added for actual occupied-port bind cleanup and interrupted HTTP body framing; the final lifecycle module passed all 25 cases in 2.37 seconds. `git diff HEAD --check` passed. No live endpoint, microphone, household service, or physical device was used.
- Implementation remains `in-progress` pending workflow review and accepted local status/mirror reconciliation; no accepted-review or deployment claim is made here.

- Post-review resolution: backstop cancellation is scoped to its original task and uses the same cancellation-once guard; native abort retains final close behind the actual writer; failed native/session release retains its owner and retries without resetting the shutdown deadline. Playback cleanup remains independent of session cleanup, and a failed shutdown future cannot certify release.
- Post-review receiver resolution: the final request worker removes its owned temporary directory without requiring an additional wait_workers caller. Six subprocess cases combine real SIGINT/SIGTERM with partial uploads, active response sockets and delayed transcription; they prove prompt socket/listener closure, retained process lifetime after budget expiry, eventual WAV/directory removal, and no late turn.
- Post-review focused verification: 130 bridge/lifecycle tests passed; the final lifecycle rerun passed 37 tests. All confirmed review defects are fixed; no code findings were deferred. Earlier implementation-state and unresolved-policy entries above are historical; Amanda approved the policy before implementation, and all three review layers have now been triaged.

## Spec Change Log

## Review Triage Log

- High — Process-exit policy is unresolved: daemon loop/request owners cannot guarantee eventual cleanup after main returns, while executor work can delay interpreter exit. Added an explicit Open Question; draft remains unapproved.
- Medium — Startup signals were absent from acceptance: initial connect blocks before serving. Added cancellation and no-late-listener assertions.
- Medium — Receiver cleanup omitted capture buffers, transcription workers and temporary files. Added ownership and eventual removal assertions.
- Medium — “Promptly” and an unspecified allowance were not measurable. Defined one-second serving exit and a shared ten-second cooperative cleanup deadline.
- Medium — Generator cleanup precedes player close, so a stalled generator can prevent playback abort. Require independent shutdown abort and retained async/executor ownership.



- blind/backstop-double-cancel — high, patch: `_send` still cancels the concurrent future after the shutdown owner cancelled its task; schedule a cancellation-once check on the event loop and test cleanup spanning the backstop.
- blind/native-writer-outlives-abort — high, patch: inherited abort can time out on the write lock before native close; retain final release through actual writer completion.
- blind/failed-native-close-reference — high, patch: the new override clears its stream even on close failure; retain that reference and unsuccessful cleanup ownership.
- blind/session-close-failure-success — medium, patch: caught close errors currently permit `_closed` and a successful stop result; separate failed cleanup from released resources.
- blind/abort-exception-skips-late-open — high, patch: awaiting failed abort exits before late-open cleanup, while the callback stops the loop anyway; finish independent cleanup and retain/report unresolved owners.
- blind/constructors-outside-finally — false: both session constructors create only inert state; sockets/tasks open in connect, already inside the protected lifecycle. ResponseStream and TurnRunner constructors likewise do not acquire native audio or worker threads.
- blind/context-manager-directory — medium, patch: server_close with a live worker does not arrange eventual directory removal unless a separate wait_workers caller exists; the final worker must own that cleanup.
- blind/serving-pending-signal-test — medium, patch: existing signal cases do not combine serving HTTP workers with deferred cleanup; add a real-process socket/lifetime test.
- blind/spec-status-wording — low, rejected spec-only: implementation notes record the pre-review state; final workflow reconciliation will append actual accepted state without changing intent.
- edge/native-writer-outlives-abort — high, patch: independently reproduced stop returning true with an active native stream after abort lock timeout; same defect as blind/native-writer-outlives-abort.
- edge/failed-native-close-reference — high, patch: close failure clears the only native stream reference; same defect as blind/failed-native-close-reference.
- edge/backstop-double-cancel — high, patch: the synchronous turn backstop can deliver a second cancellation during owned cleanup; same defect as blind/backstop-double-cancel.
- verification/standalone-active-http-worker — medium, patch: direct socket tests do not prove main wires socket release under signals; add serving subprocess cases for partial upload and retained transcription.

- Review resolution — all `patch` entries above are resolved by the post-review changes and their 37 lifecycle regressions; constructor ownership was disproved by reading both session constructors. Final full-suite evidence follows in Verification. No findings deferred.

## Design Notes

The process-lifetime policy is approved; no irreversible action is proposed. This dispatch-sized change spans concurrent resource owners. All shutdown phases share one monotonic ten-second deadline from the first request; serving exits within one second, inside that budget. Python cannot forcibly terminate arbitrary blocked native calls. Tests must distinguish serving exit, stop() return, actual resource release and process exit; do not substitute one for another. Preserve the reconnect-cleanup regression. Isolate OS signals in subprocess tests using fake sessions/audio, shortened injected deadlines and explicit synchronization; require no live endpoint or microphone. Add startup, active-response, blocked-producer, repeated-stop, delayed-transcription and delayed-cleanup cases. Keep normal response completion/draining covered. For blocked native playback, observe underlying worker completion separately from cancellation of its asyncio wrapper.

## Verification

- Run focused lifecycle and bridge tests using the repository virtual environment.
- Run the complete pytest suite from the feature worktree.
- Review exact diffs for credentials, generated files, unrelated changes, and unchanged protocol/firmware behavior.
- No physical-device or production-service validation is claimed by these fake-session and local-process tests.

- Approval recorded: Amanda accepted retained process lifetime for pending cleanup; the process-policy review finding is resolved.

- Final verification after all review patches: `python -m pytest -q -rs` passed **1558 tests**, with **1 skip** (ESPHome environment absent in this worktree) and **6 websockets deprecation warnings**, in 221.20 seconds. All 37 lifecycle cases were collected in this final run. Diff whitespace and exact-path credential review passed. Spec implementation is complete; tracker remains `review` pending publication and remote checks. No deployment or physical-device validation.
