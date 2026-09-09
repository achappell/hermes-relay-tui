---
title: 'Render honest turn phases and response delivery'
type: 'feature'
created: '2026-09-09'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'e36e9b39d471f9e5e0e1c9e2e35b347b5ac7a9f2'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-1-start-an-authorized-hermes-turn.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-hermes-relay-tui-2026-09-08/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-hermes-relay-tui-2026-09-07/EXPERIENCE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The TUI can let a raw Hermes status string replace its real turn
phase, leave a locally transcribed voice turn looking like transcription, and
call disabled or failed playback “buffering”. A successful turn then returns
to `ready` while the domain has a completed response, obscuring whether Hermes
is working, audio is playing, and text is usable.

**Approach:** Make guarded `TuiDomain` state and observed local milestones the
only sources for the TUI’s semantic phase. Keep status/tool detail separate,
track local audio availability independently, and finalize streamed text at
completion or failure so it survives unavailable audio and ambiguous transport
loss.

## Boundaries & Constraints

**Always:** This story hardens the Python TUI/client doorway only. Consume
`SessionProtocol` normalized events; keep one coherent inline assistant stream;
show only observed canonical phases; preserve text; keep stale-event rejection,
content-safe diagnostics, no-replay recovery, and off-loop capture/playback.

**Never:** Change the Hermes wire protocol, invent local response text, replay a
turn that may have reached Hermes, or modify Puck, iOS, browser/WASM, LVGL, or
cross-surface parity work. Do not add live audio hardware to automated tests or
expand this into the iOS 16 scope.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| LOCAL_VOICE_MILESTONES | Capture finishes and local STT returns text | TUI shows listening/transcribing, then thinking before the first remote event | Failed preflight remains disconnected/queued |
| NORMALIZED_RESPONSE | Thinking, text, audio, and turn-end events for the active turn | Text remains one inline response; only a real active player shows speaking; turn completion commits the response | Status/tool detail cannot regress an already speaking/buffering turn |
| AUDIO_UNAVAILABLE | `--no-play` or the player fails after Hermes supplies audio | Completed text remains readable and the TUI says audio unavailable; it never claims speaking | Preserve collected PCM/WAV recovery behavior |
| PARTIAL_TRANSPORT_FAILURE | Partial text followed by a normalized error or socket failure | Partial response is finalized and retained with an honest error/disconnected state | No automatic retry or duplicate submission |
| LATE_OR_UNKNOWN_EVENT | Stale event or unknown server event after/within a turn | Active phase and response are unchanged; a content-safe diagnostic may be shown | Rejected events do not mutate domain state |

</frozen-after-approval>

## Code Map

- `domain.py` -- guarded canonical phases, terminal state, response retention, and stale-event results consumed by the TUI.
- `app.py` -- local capture milestones, normalized event consumption, phase presentation, audio-output status, and streamed-response finalization.
- `tests/test_tui_domain.py` -- canonical transition and stale-event invariants.
- `tests/test_app.py` -- fake-session coverage for local milestones, phase ordering, audio-unavailable output, partial failures, and coherent text.
- `README.md` -- correct the user-facing description of playback-unavailable behavior if the final label/flow changes it.

## Tasks & Acceptance

**Execution:**
- [x] `domain.py` -- keep accepted normalized events and explicit local milestones authoritative, with terminal response facts independent of the idle display projection -- prevent invented or regressed phases.
- [x] `app.py` -- drive visible lifecycle labels from accepted domain state, move voice turns into thinking after local transcription, separate audio availability from turn phase, and finalize/preserve text on completion and failure -- make the TUI’s story honest without changing the protocol.
- [x] `tests/test_tui_domain.py`, `tests/test_app.py` -- add Given/When/Then regressions for phase order, ignored regressions, stale events, no-play/player failure, partial transport failure, and one coherent response -- prove the matrix with fakes and no hardware.
- [x] `README.md` -- align the audio-output explanation with explicit unavailable-audio behavior -- keep the operational contract truthful.

**Acceptance Criteria:**
- Given a verified voice capture returns text, when the turn is submitted, then the visible lifecycle reaches `transcribing` and `thinking` before any remote activity event can arrive.
- Given the active turn emits normalized activity, text, audio, and completion events, when the TUI consumes them, then only warranted phase transitions are rendered, status/tool detail cannot overwrite speaking or buffering, and all response deltas remain one coherent inline message.
- Given playback is disabled or the local player cannot start or later fails, when Hermes text completes, then the completed text remains available, the TUI explicitly reports audio unavailable, and it never reports that a sample is speaking.
- Given partial response text is followed by a turn error or transport loss, when the failure is handled, then the partial text remains readable, the state is error/disconnected rather than indefinite thinking, and the prompt is not replayed.
- Given a stale or unknown event arrives, when it is processed, then it cannot mutate the active turn phase or response and any diagnostic is content-safe.

## Implementation Notes

## Spec Change Log

## Review Triage Log

## Design Notes

`complete` remains the canonical domain terminal phase. The TUI may return its
steady idle label to `ready` after committing the response; the completed
assistant message remains visible. Audio output is separate: relay audio can
exist while playback is disabled or broken, so `buffering` and `speaking` must
not disguise that local limitation.

## Verification

**Commands:**
- `venv/bin/pytest tests/test_tui_domain.py tests/test_app.py` -- expected: focused phase, transcript, and audio-path tests pass.
- `venv/bin/pytest` -- expected: complete repository suite passes.
- `git diff --check` -- expected: no whitespace errors or accidental generated artifacts.

**Manual checks (if no CLI):**
- Against the configured Hermes endpoint, run a text turn, a voice turn with playback disabled, and a deliberately unavailable endpoint; expect honest phase transitions, preserved text, explicit unavailable audio, and no replay. If the speaker path changes, perform the supervised laptop-speaker smoke only; do not contact the Puck.
