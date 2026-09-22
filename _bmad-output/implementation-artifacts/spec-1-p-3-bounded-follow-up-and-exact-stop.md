---
title: 'Bounded Puck follow-up and exact stop'
type: 'feature'
created: '2026-09-22'
status: 'in-progress'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'dcdb0a4'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-continuous-wake-free-follow-ups.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-p-1-authorized-wake-and-capture.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-p-2-status-and-response-audio-delivery.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The ReSpeaker Puck can wake, upload one capture, and play one Hermes response, but every new request requires the wake word again. It also has no explicit local terminal path for a person who says exactly `stop`; treating that phrase as an ordinary Hermes turn would create an unwanted request and spoken response.

**Approach:** Reuse the existing `HandsFreeCoordinator` session contract in the Puck bridge. After a successful response, the firmware opens one bounded eight-second follow-up capture without another wake word. The bridge feeds each completed follow-up into the same Hermes session exactly once. An exact standalone `stop`, with ordinary terminal punctuation ignored, closes the local conversation silently. Empty, expired, failed, or disconnected captures also end the follow-up loop without replaying an uncertain request.

**Outcome:** A household member can ask a question, hear the answer, ask a short follow-up, and continue until silence, exact `stop`, or a real failure returns the Puck to wake mode. The Puck remains the only hardware surface changed by this story; ESP32 Touch is explicitly excluded.

## Boundaries & Constraints

**Always:** Keep the normalized session/profile contract in the bridge; do not parse Hermes wire events in firmware. Preserve one initial submission and one Hermes turn per accepted non-empty transcript. Keep follow-up audio and transcripts transient. Use the existing Puck response sequence/status transport and the existing eight-second capture buffer. Treat `stop`, `STOP`, and `stop.`/`stop!`/`stop?` as the same exact local command, but do not classify phrases such as `stop the music` as local stop.

**Never:** Modify the ESP32 Touch adapter, its firmware, or its story status. Do not add a second Hermes session, replay a capture after an uncertain upload/transcription result, leave the microphone open indefinitely, persist raw audio/transcripts, add a dependency, or broaden this story into Puck recovery, low-level speaker/DMA failure handling, or wake-model changes.

## Puck conversation contract

| State/event | Required behavior |
|---|---|
| Wake capture has a non-empty transcript | Send exactly one initial turn through the existing session. |
| Initial response succeeds | Finish playback, then open an eight-second follow-up window with no wake word. |
| Follow-up capture has a non-empty ordinary transcript | Send exactly one follow-up through the same session/profile, then repeat the bounded window after successful playback. |
| Transcript is exact standalone `stop` | End locally with no Hermes request and no assistant audio; return to wake mode. |
| Follow-up is empty, times out, or has no usable speech | End locally with no empty Hermes request; return to wake mode. |
| Transcription, response, upload, or connection failure | Mark the sequence unavailable/refused as appropriate and return to wake mode; never replay the capture. |
| A second upload arrives while no capture window is admitted | Reject or silently abandon it without creating a turn. |

## Code Map

| Area | Path | Role |
|---|---|---|
| Session coordinator | `handsfree.py` | Reuse exact-stop matching, bounded follow-up loop, and same-session send contract; change only if a narrow seam is required. |
| Puck turn owner | `puck_bridge/turn.py` | Admit initial/follow-up transcripts, queue the next capture outcome, and keep response success separate from silent/rejected outcomes. |
| Puck HTTP transport | `puck_bridge/receiver.py` | Represent empty/stop captures as a silent terminal and surface transcription failure without starting a turn. |
| Response lifecycle | `puck_bridge/response.py` | Retain a sequence-scoped silent terminal alongside complete/unavailable. |
| Puck server wiring | `puck_bridge/server.py` | Connect the follow-up capture/failure callbacks without changing the standalone entry point contract. |
| Firmware capture | `firmware/respeaker-lite/pcm_capture.h` | Reuse the bounded buffer for follow-up windows, distinguish no-speech timeout from speech-ending silence, and upload an empty capture once for silent completion. |
| Firmware response state | `firmware/respeaker-lite/puck_response.h` | Keep the wake gate held through follow-up scheduling/capture and resume wake after complete, silent, or bounded failure. |
| Firmware automations | `firmware/respeaker-lite/respeaker-lite.yaml` | Start follow-up capture after successful playback and route silent/failed response outcomes back to wake mode. |
| Contract coverage | `tests/test_puck_bridge.py`, `tests/test_puck_firmware.py` | Prove same-session follow-up, exact stop, silence, failure/no-replay, sequence ownership, and firmware state transitions. |

## Tasks & Acceptance

**Execution:**

- [x] Add focused bridge tests first for one initial turn followed by multiple same-session follow-ups, exact `stop` with punctuation/case variants, phrases containing more than `stop`, empty/timeout completion, response failure, and an upload arriving outside an admitted follow-up window.
- [x] Extend the bridge outcome contract so empty and exact-stop captures become a sequence-scoped silent terminal, while transcription/transport failures become unavailable or rejected without invoking Hermes.
- [x] Connect `TurnRunner` to the existing bounded follow-up coordinator with a thread-safe one-capture handoff; preserve the existing boolean `submit_transcript` compatibility surface for current callers/tests.
- [x] Add firmware capture/state tests and implementation for an eight-second follow-up window, no-speech timeout, speech-ending silence, one empty upload, and follow-up state transitions after `complete` and `silent` response status.
- [x] Update the Puck YAML and README with the follow-up ordering and exact-stop behavior; do not alter ESP32 Touch files or docs.
- [x] Run focused bridge/firmware tests, the complete repository suite, and the installed ESPHome configuration gate when available.

**Acceptance Criteria:**

- Given an admitted wake capture that produces a successful response, when playback finishes, then the Puck opens an eight-second follow-up window without requiring the wake word and keeps the wake detector/capture state ordered so it cannot accept two windows at once.
- Given one non-empty follow-up transcript, when it is admitted, then exactly one Hermes request uses the original session/profile, and after successful response playback the next bounded follow-up window is offered.
- Given an initial or follow-up transcript equal to `stop` after trimming and ignoring only terminal `.`, `!`, `?`, or `,`, when it is received, then no Hermes request or assistant response is created and the Puck returns to wake mode.
- Given a follow-up transcript that is empty, whitespace-only, absent because the eight-second window expires, or otherwise unusable, when the capture completes, then no empty Hermes request is created and the Puck returns to wake mode.
- Given a phrase containing additional words, such as `stop the music`, when it is transcribed, then it follows the ordinary Hermes path rather than the local stop path.
- Given a transcription, upload, response, or connection failure, when the bridge or firmware detects it, then the sequence becomes unavailable or rejected, the Puck resumes wake mode after bounded cleanup, and no uncertain capture is replayed.
- Given the focused bridge and firmware tests plus the repository suite, when they run from the clean story worktree, then they pass without changing ESP32 Touch behavior or adding dependencies.

## Verification

**Commands:**

- `venv/bin/pytest tests/test_puck_bridge.py tests/test_puck_firmware.py` -- focused Puck contract and state tests pass.
- `venv/bin/pytest` -- complete repository suite passes.
- `venv-firmware/bin/esphome config firmware/respeaker-lite/respeaker-lite.yaml` -- generated Puck configuration remains valid when the firmware environment is installed.

**Manual checks (if hardware is available):** Wake the Puck once, ask a question, wait for the answer to finish, ask a follow-up without the wake word, then say `stop.` and confirm there is no second answer and the next wake works. Also confirm an empty follow-up returns to wake mode without a stuck `/response` request.

</frozen-after-approval>

## Implementation Notes

Implemented on branch `feat/1-p-3-puck-follow-up-stop`, based on `dcdb0a4`. The bridge now admits one initial transcript and hands later Puck captures to the existing `HandsFreeCoordinator` through a thread-safe one-capture mailbox. Normal follow-ups reuse the same session; exact standalone `stop` and empty captures become `silent`; transcription, upload, and turn failures become unavailable/rejected without replay.

The Puck firmware now keeps wake ownership through `FOLLOW_UP_PENDING` and `FOLLOW_UP_CAPTURING`, uses an eight-second no-speech deadline for follow-ups, sends one empty chunk for a silent capture, and resumes wake after the bridge reports `silent`. README/YAML documentation records the ordering. No ESP32 Touch file was changed.

Verification: focused bridge `100 passed`; focused firmware `13 passed, 1 skipped`; the added `pcm_capture.h` C++ harness compiled and executed; Python bytecode compilation passed; `git diff --check` passed; and `esphome config firmware/respeaker-lite/respeaker-lite.yaml` passed with temporary non-secret placeholder substitutions under ESPHome 2026.8.2. The actual compile reached ESP-IDF 5.5.5 framework installation and stopped with the installer return code `-11` before C++ diagnostics, so no firmware binary or hardware claim is made.

The repository-wide run reported `1566 passed, 1 skipped, 1 failed`. The single failure is the existing `tests/test_app_wake.py::test_spoken_stop_interrupts_active_response_without_a_new_turn` assertion: this story's required worktree name contains `follow-up-stop`, and the app includes `hybrid-tui-turn-1.wav`'s resolved path in transcript text, so the assertion's broad substring check sees the directory name. It reproduces through a symlink because Python resolves the real path; it does not touch the Puck code or change the focused result.

## Review Triage Log

- `verification-gap/esphome-compile` — environment limitation: configuration generation passes, but the installed ESP-IDF 5.5.5 framework setup exits `-11` before compilation; defer binary/hardware evidence to a machine with a working ESP-IDF toolchain cache.
- `test-environment/path-sensitive-stop` — existing unrelated test failure: the app-wake assertion searches the full transcript for `stop`, including the resolved worktree path; no implementation change is warranted in this Puck story.

## Dev Agent Record

- Reused the repository's existing normalized session and `HandsFreeCoordinator` loop; no Hermes wire parsing or new dependency was introduced.
- Added sequence-scoped `silent` response handling so the device can complete an empty/local-stop capture without a fake turn or refusal.
- Kept the Puck bridge, Puck firmware, and tests as the implementation surface; ESP32 Touch remains out of scope.

## File List

- `_bmad-output/implementation-artifacts/spec-1-p-3-bounded-follow-up-and-exact-stop.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `puck_bridge/turn.py`, `puck_bridge/receiver.py`, `puck_bridge/response.py`, `puck_bridge/server.py`
- `firmware/respeaker-lite/pcm_capture.h`, `puck_response.h`, `respeaker-lite.yaml`, `README.md`
- `tests/test_puck_bridge.py`, `tests/test_puck_firmware.py`

## Spec Change Log

- 2026-09-22: Created from the Puck Epic 1 contract at baseline `dcdb0a4`; ESP32 Touch explicitly excluded.
- 2026-09-22: Implemented the Puck follow-up mailbox, silent terminal, bounded firmware window, and exact-stop flow; moved to review.

### Review Findings

- [x] [Review][Patch] Preserve string transcript outcomes from the production receiver [puck_bridge/receiver.py:760-779; puck_bridge/server.py:270-278] — `submit_transcript_outcome()` returns `"accepted"`, `"silent"`, or `"rejected"`, but `_finish_capture()` only treats literal `True` and `"silent"` as success. Production accepted initial and follow-up captures can therefore mark the response stream unavailable after the runner returns, preventing or truncating normal Puck audio. Verdict: high. Sources: blind-hunter, acceptance-auditor. Fixed by accepting the explicit `"accepted"` outcome while retaining boolean compatibility.
- [x] [Review][Patch] Discard buffered PCM when a follow-up expires without speech [firmware/respeaker-lite/pcm_capture.h:469-483; firmware/respeaker-lite/pcm_capture.h:511-527] — the no-speech deadline sets `capture_pending_upload` but leaves `write_pos` intact, so the eight-second silent window can upload accumulated microphone frames instead of one empty capture. That can send an unusable or false transcript to Hermes, violating the no-empty-turn acceptance. Verdict: medium. Sources: blind-hunter, acceptance-auditor. Fixed by zeroing the buffered length and sending the existing explicit empty chunk.
- [x] [Review][Patch] Keep follow-up admission armed through response playback [puck_bridge/turn.py:562-581; firmware/respeaker-lite/respeaker-lite.yaml:706-718] — the bridge's ten-second mailbox wait begins when the producer finishes, before the Puck finishes response playback and starts its next capture. A long answer can expire the waiter before the valid follow-up arrives; a very short answer can also race an upload before `_follow_up_waiting` is armed. The later capture is then rejected or treated as a new initial wake instead of the next same-session follow-up. Verdict: medium. Sources: blind-hunter, edge-case-hunter, acceptance-auditor. Fixed by arming the mailbox during the in-flight response and extending the backstop for the documented Puck audio read-ahead and capture/upload window.
- [x] [Review][Patch] Add executable coverage for Puck capture and production silent paths [tests/test_puck_firmware.py:42-115; tests/test_puck_bridge.py:353-457; puck_bridge/server.py:270-278] — the new capture checks are source-string assertions, the response harness excludes `pcm_capture.h`, and the bridge tests use recording/fake callbacks instead of the live `TurnRunner` mailbox and production server wiring. Add runtime capture-state coverage plus end-to-end empty, empty-transcript, and exact-stop status assertions. Verdict: medium. Source: verification-gap. Fixed with a compiled capture-header harness, live mailbox admission coverage, and sequence-scoped silent endpoint assertions.
- [x] [Review][Defer] Prove the silent HTTP 204 handoff releases wake [firmware/respeaker-lite/respeaker-lite.yaml:769-783; firmware/respeaker-lite/puck_response.h:109-157] — deferred: the silent path enters `WAITING_FOR_MEDIA_IDLE`, starts a 204 media fetch, and relies on the ESPHome audio pipeline emitting the idle callback before status polling can resume wake. Static checks cannot settle that device behavior; a physical empty-capture/exact-stop run with response-state logs is required.
- [x] [Review][Defer] Synchronize capture state shared by the I2S task and interval loop [firmware/respeaker-lite/pcm_capture.h:430-495] — deferred: `capturing`, `write_pos`, and the close/upload flags cross the microphone task and the main-loop intervals without an explicit synchronization boundary. The same shape predates P-3 for initial capture, so a task-timing or hardware check should settle the risk before changing this shared path.

#### Rejected

- `false` — The claim that response failures have no firmware recovery path overlooks `/response-status`: unavailable, HTTP errors, and transport failures enter `REFUSAL_PENDING`, then the refusal watchdog returns the Puck to wake mode.
- `false` — A missing follow-up opening/closing cue is not a P-3 violation; the frozen flow deliberately removes the wake phrase and keeps the existing acknowledgement on the initial wake path.
- `false` — A continuously active VAD does not by itself prove an unbounded capture: `write()` closes the bounded buffer when it fills. The reported failure requires VAD to remain active while capture data stops, which this diff does not establish.
