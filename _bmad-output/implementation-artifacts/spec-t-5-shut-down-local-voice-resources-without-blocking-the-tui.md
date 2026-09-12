---
title: 'Shut down local voice resources without blocking the TUI'
type: 'feature'
created: '2026-09-12'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '60f8ac34bc3957bf3422c30700e15134d82b60a2'
source_story: 'T-5'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/deferred-work.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-4-recover-without-replaying-an-uncertain-turn.md'
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** TUI wake teardown still joins the wake worker and closes the native recorder synchronously from the Textual event loop. Reconnect, reload, disarm, or quit can therefore pause the interface while native audio cleanup waits, and stale frames or a microphone that opens late can outlive the discarded listener.

**Approach:** Detach wake resources from the live TUI state immediately, then perform listener joins, recorder cancellation, and native shutdown in tracked worker cleanup. Make the discarded listener fail closed before cleanup runs, retain late-open ownership until the open completes, and prevent re-arming from racing an unfinished prior cleanup.

## Boundaries & Constraints

**Always:** Keep one wake listener and one shared recorder per armed TUI. Return control to Textual promptly while blocking joins and native recorder operations run off-loop. Make cleanup idempotent and tracked, close a recorder whose open completes after cancellation exactly once, preserve the recorder's poisoned-stream rule, and reject queued frames or callbacks from a discarded listener. Preserve current wake phases, continuous follow-ups, cancellation semantics, and no-replay recovery.

**Never:** Change Hermes wire events or session ownership, open a second input stream, silently re-arm after reconnect or disarm, wait synchronously on a worker join or native audio close in a Textual handler, weaken bounded cleanup, or move UI behavior into core modules.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| DISARM_ACTIVE | Armed listener and open shared recorder | `/wake off`, reconnect, reload, connection loss, and quit detach both resources and return promptly; cleanup completes in a tracked worker | Cleanup failures are logged structurally and do not strand the TUI in an armed state |
| CANCELLED_OPEN | Microphone open is in flight when startup is cancelled | The listener is stopped, the late-open recorder is closed exactly once after open returns, and it cannot be re-used | A timed-out native close remains poisoned and is not reopened |
| STALE_FRAME | Frames are queued or being scored when disarm occurs | The discarded listener cannot invoke the old wake callback or submit a turn after disarm; a later arm starts with a drained detector | Stale callbacks are ignored without user-facing false turns |
| REPEATED_TEARDOWN | Multiple teardown paths address the same listener/recorder | Each resource is stopped and closed at most once, and a later arm waits for prior cleanup before opening a new stream | Repeated cleanup is harmless and diagnostics retain only safe structural details |

</frozen-after-approval>

## Code Map

- `app.py` — `_disarm_wake`, `_arm_wake`, `_finish_cancelled_wake_open`, `_track_cleanup_task`, `_wait_for_cleanup_tasks`, `on_unmount`, `_handle_reconnect_command`, `_switch_to_args`, `_apply_reload_settings`, and `_mark_connection_lost` own wake-resource detachment and all teardown callers. Reuse the existing retained-task budget and session cleanup pattern.
- `wake.py` — `WakeListener.pause`, `resume`, `start`, `_loop`, and `stop` own queued-frame draining, detector reset, worker lifetime, and callback safety. Preserve fixed-size chunking and non-blocking `submit`.
- `voice.py` — `AudioRecorder.shutdown`, `_close_stream_with_timeout`, late reader ownership, and stream poisoning are the native cleanup boundary. Do not duplicate PortAudio close logic in `app.py`.
- `tests/test_app_wake.py` — existing fake listener/recorder seams cover startup cancellation, late microphone open, reload, reconnect, quit, and re-arm; extend them with prompt-return and once-only cleanup assertions.
- `tests/test_wake.py` — detector/listener unit seam for proving stop drains or disables queued work and cannot invoke a stale wake callback.

## Tasks & Acceptance

**Execution:**
- [x] `app.py` — detach wake ownership synchronously, schedule serialized listener/recorder cleanup off the Textual loop, retain late-open tasks, and gate re-arm on prior cleanup — keep every teardown caller responsive and resource-safe.
- [x] `wake.py` — make listener shutdown fail closed against queued or in-flight frames while preserving pause/resume reset behavior — prevent stale wake callbacks after disarm.
- [x] `tests/test_app_wake.py` and `tests/test_wake.py` — add prompt-return, cancellation, late-open, stale-frame, repeated-teardown, and re-arm regression cases — lock the lifecycle guarantees at both boundaries.

**Acceptance Criteria:**
- Given wake listening or capture is active, when reconnect, connection loss, reload, or quit disarms it, then the UI handler returns promptly and worker joins/native recorder shutdown run outside the Textual event loop.
- Given shutdown is cancelled or microphone open completes late, when the recorder becomes available, then it is closed exactly once and any timed-out native close remains poisoned and cannot be reopened.
- Given a listener is disarmed and later re-armed, when queued frames from the prior listener are present, then they cannot trigger the old wake or invoke its callback.
- Given teardown is requested repeatedly, when each request is processed, then teardown is idempotent and no discarded worker, capture task, native stream, or late callback remains active.
- Given the lifecycle changes are implemented, when the focused suite runs, then it covers prompt UI return, cancellation, late-open cleanup, stale-frame rejection, idempotence, and the existing successful wake path.

## Implementation Notes

- Wake teardown now detaches the listener, coordinator, recorder, and observer synchronously, quiesces the listener immediately, and tracks serialized cancellation, worker joins, late-open waiting, observer removal, and recorder shutdown outside the Textual event loop.
- `WakeListener` rejects frames after quiescence or stop, drains and resets detector state during shutdown, and serializes callback admission against stop so discarded listeners cannot fire stale wakes.
- Re-arm waits for prior cleanup, and late microphone opens retain ownership until they complete; the existing native close/poisoning boundary remains in `voice.py`.
- Added regressions for blocked off-loop teardown, cancellation and late-open cleanup, stale queued frames, repeated disarm, and re-arm serialization. No product or protocol behavior changed.

## Review Triage Log

- local review: no actionable findings; the delegated blind-hunter and verification-gap layers exceeded their bounded wait without returning findings, and the edge-case layer returned an invalid empty-input sentinel. No issue was deferred; the final implementation was checked locally against the approved matrix.

## Verification

**Commands:**
- `../../venv/bin/pytest tests/test_wake.py tests/test_app_wake.py tests/test_app.py -q` — expected: focused lifecycle and existing app tests pass.
- `../../venv/bin/pytest -q` — expected: complete Python suite passes with no new failures.
- `git diff --check` — expected: no whitespace errors.

**Observed:**
- `../../venv/bin/pytest tests/test_wake.py tests/test_app_wake.py -q` — 92 passed.
- `../../venv/bin/pytest tests/test_wake.py tests/test_app_wake.py tests/test_app.py -q` — 298 passed; one timing-sensitive reconnect logging assertion failed once in the combined run and passed in isolation and repeated reruns.
- `../../venv/bin/pytest -q` — 1019 passed; one pre-existing `websockets.legacy` deprecation warning.
- `git diff --check` — passed.

**Manual checks (if no CLI):**
- With a configured wake-capable TUI, start wake mode, exercise `/wake off`, `/reload`, `/reconnect`, `Ctrl+C`, and quit while opening/capturing; confirm the interface remains responsive, the microphone indicator clears, stale audio never produces a turn, and re-arm does not overlap the prior stream.
