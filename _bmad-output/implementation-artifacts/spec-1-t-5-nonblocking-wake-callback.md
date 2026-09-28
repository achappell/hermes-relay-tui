---
id: T-5
status: in-review
product_epic: 1
created: 2026-09-27
baseline_commit: 7d089389a91cfdc608b3e0c1e0da3d042f2d3950
---

# T-5 — Release the wake state lock before running conversation callbacks

## Intent and evidence

Amanda's physical test triggers the wake and capture-finished tones but shows no transcript; Ctrl+R captures and transcribes successfully. The capture-finished tone runs only after a nonempty, non-hallucinated transcript, immediately before submission. `WakeListener._notify` holds `_state_lock` throughout `HandsFreeCoordinator.on_wake`. The worker then waits in `_send_wake_turn` for the event-loop turn; `_run_turn` calls `listener.pause`, which waits for the same lock. A bounded two-thread probe reproduces that pause cannot finish until the callback returns. This is a real lock cycle, not a wake-threshold failure.

## Approved scope

Complete the existing T-5 responsive lifecycle contract in `epics.md`, preserving TUI-DEFECT-102 and TUI-DEFECT-104 as separately accepted physical reports. Correct callback lock ownership and verify real listener thread integration. Do not change wake thresholds, Home protocol, microphone timing, or speech models to mask the defect.

## Tasks

- `tests/test_wake.py`: add a bounded regression in which a real listener callback waits for a second thread to pause the listener; assert pause completes before the callback returns. Preserve stop/quiesce rejection of queued callbacks and repeated teardown.
- `wake.py::WakeListener._notify`: check dispatch admission under the state lock, then run the potentially blocking callback outside it. Keep worker single-flight and exception containment; lifecycle locks must not span client code that waits for the UI loop. Clarify that admitted callbacks are in flight and remain subject to existing capture/turn cancellation.
- `tests/test_app_wake.py`: exercise the real listener worker through a Textual turn and wake-free follow-up with fake audio/session inputs. Bound the regression so a failure cannot hang the suite.
- Owning validation and tracker: record the reproduced cycle, tests, review, and Amanda's physical retest separately. Do not claim T-5 or either defect closed without applicable acceptance.

## Acceptance

- Given a wake callback waiting for the TUI, when the TUI pauses or resumes detection, then those operations finish without waiting for the callback's return.
- Given quiesce or stop before callback admission, when queued frames are processed, then no new callback is admitted; already running capture/turn work is cancelled by its owner and teardown remains bounded.
- Given a wake-triggered transcript and a follow-up, when the real worker dispatches both, then each appears in the transcript and is sent once, with the UI responsive.
- Given the physical candidate, when Amanda speaks a wake request and a second turn, then both must be observed before the original wake report is considered superseded.

## Verification

Run the focused wake and Textual wake modules, independent concurrency review, then the full repository suite. Perform a physical retest on the candidate. Keep the current Home acceptance limitations and unrelated checkout edits intact.

## Review and verification

Independent concurrency review found no verified regression: callback invocation stays synchronous on the single worker, state changes remain locked, and stop joins outside the lock. The real-worker Textual regression proves initial turn, wake-free follow-up, UI responsiveness, and recorder teardown; reinstating the old lock produces a bounded subprocess failure. Focused wake coverage passed 95 tests and the complete suite passed 1670 tests with one environment skip. See [validation](validation-1-t-5-nonblocking-wake-callback.md) for physical evidence and remaining gates.

Amanda completed the candidate physical checklist, including quit during capture and successful relaunch. Local implementation and acceptance are ready for delivery review; status remains in-review pending merge/release.
