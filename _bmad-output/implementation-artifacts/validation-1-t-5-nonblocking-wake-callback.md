# T-5 wake callback deadlock validation — 2026-09-27

## Physical evidence

Amanda reports Ctrl+R captures/transcribes correctly. Wake mode reports bundled hey_hermes at threshold 0.6. Testing Sherpa with hey hermes produces the acknowledgement and capture-finished tones, but no transcript appears. The latter tone follows successful nonempty transcription in `HandsFreeCoordinator._deliver`, so the wake engine is not the cause of the observed post-tone stall. Earlier speculation about wake sensitivity is superseded by this evidence.

## Reproduction and correction

The real listener invokes the entire conversation callback while holding `_state_lock`. The worker waits for `_run_turn` on Textual's loop; `_run_turn` pauses that listener before sending and blocks on the same lock. A bounded two-thread probe reproduces the cycle. New regression `test_wake_callback_does_not_hold_state_lock_while_waiting_for_ui_pause` fails before the correction (pause cannot complete while callback waits), then passes after it.

The correction admits callbacks under the lifecycle lock and invokes client code outside it. Quiesce/stop still reject queued callback admission, and an already admitted callback is in flight and subject to the owner's existing capture/turn cancellation. The focused wake module passes 29 tests. Real-listener Textual integration, independent concurrency review, full-suite verification and physical retest are pending at this checkpoint.

TUI-DEFECT-102 (second-turn capture) and TUI-DEFECT-104 (sustained-utterance tail) remain separate reports; this reproduction alone does not close either.

## Verified correction

The combined wake and Textual wake modules passed **95 tests in 37.05 seconds**. The new subprocess-bounded Textual integration uses a real listener worker, a real coordinator, and a real Textual app with fake recorder/session input. One detection produces an initial request and a wake-free follow-up exactly once; keyboard input remains responsive during both, and disarm closes the recorder. Reinstating the old lock ownership in a negative probe deadlocks; the child is killed/reaped after six seconds. Independent concurrency review found no verified regression.

Amanda restarted the corrected candidate and explicitly confirmed **text and spoken reply** after the wake phrase and first request. This is user-reported physical microphone, transcription, submission and playback evidence, not inferred from a fake. Second-turn and sustained-utterance checks are still in progress.

Amanda subsequently confirmed the second wake-free request was captured completely and received a spoken reply within the configured follow-up window. The corrected candidate therefore has direct user-reported first- and second-turn evidence. This addresses the physical reproduction in TUI-DEFECT-102 on Home mode with Sherpa; merge/release remains separate from this candidate acceptance.

Amanda also confirmed that a sustained wake-captured utterance retained its complete distinctive ending, “purple umbrella beside the kitchen window.” No tail truncation was reported in this controlled physical check. This supplies candidate supersession evidence for TUI-DEFECT-104; it does not claim a newly identified VAD defect or a separate recorder-code correction. Live disarm/re-arm, reload/reconnect microphone release, and quit acceptance remain to be recorded.

## Final automated verification

`../../venv/bin/pytest -q -rs`: **1670 passed, 1 skipped, 6 warnings in 304.16 seconds**. The only skip is the unavailable ESPHome firmware environment; warnings are existing websockets deprecations. `git diff --check` passed. The code correction is reviewed and verified; the physical microphone-release checklist and delivery status remain separate.

Amanda confirmed `/wake off` removed the microphone-open marker without freezing, and `/wake on` then allowed another complete wake-triggered request. This supplies physical disarm/re-arm evidence on the corrected candidate.

Amanda confirmed `/reload` and `/reconnect` both remained responsive and left the microphone closed until an explicit `/wake on`. This supplies physical configuration-reload and explicit-reconnect teardown evidence. Quit during capture and relaunch is the final pending manual step.

## Physical checklist complete

Amanda confirmed Ctrl+Q during wake capture exited promptly and a wake request succeeded after relaunch. Candidate physical acceptance now covers first-turn text/spoken reply, complete wake-free second turn, full sustained-utterance ending, responsive disarm/re-arm, reload/reconnect leaving the microphone closed, and quit/relaunch. Actual unexpected connection loss during physical capture was not induced; the automated connection-loss/cancellation coverage remains the evidence for that path.

T-5, TUI-DEFECT-102 and TUI-DEFECT-104 are in local review pending merge/release. No remote issue closure is claimed. Home pairing/session story TUI-HOME-01 retains its separately documented Linux, enrollment, owner-decision, renewal, multiple-Home and transient-failure acceptance limits.
