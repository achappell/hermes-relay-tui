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

Review pass 1 (full mode; layers: blind-hunter, edge-case-hunter,
verification-gap, acceptance-auditor; scoped implementation diff =
`a01e5f3` → `44f6ef3`, reviewed against the current delivery tree):

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | blind-hunter | Clean stream EOF leaves the domain turn active and can make the next prompt hit `turn_already_active`. | false | The post-stream guard at `app.py:4146-4155` applies a domain `error` event before returning, and `domain.py:653-663` clears `turn_active`; the cited stranded state does not occur. | reject |
| 2 | blind-hunter | A normalized `connection_lost` updates only the voice label and leaves connection cleanup stale. | false | `app.py:3809-3812` calls `_mark_connection_lost()`, which updates connection state, disarms wake, marks reconnect required, and closes the session at `app.py:3491-3503`. | reject |
| 3 | blind-hunter | Rejected domain events are merely logged and ignored, leaving the active turn alive. | false | Non-stale rejections at `app.py:3780-3807` apply a terminal domain error, set the error phase, append a diagnostic, and stop consumption; `domain.py:653-663` clears the active turn. | reject |
| 4 | blind-hunter | Error, interruption, and transport-failure paths can finish only the audio-timed visible prefix instead of the accumulated response text. | medium | `render_assistant(complete=True)` is only reached in the `turn_end` branch (`app.py:4121-4144`); error/interruption return early (`app.py:4102-4120`), while transport exceptions finish the stream from `_run_single_turn` without access to a final render (`app.py:3459-3475`). | patch |
| 5 | blind-hunter | Collected PCM is saved only after `turn_end`, so an error or transport failure loses WAV recovery. | medium | `_save_turn_audio()` is called only from the `turn_end` branch (`app.py:4133-4142`), while all failure exits return before it; audio accumulated before failure is therefore discarded. | patch |
| 6 | blind-hunter | An undecodable file-only audio fallback can finish as `ready` without an explicit audio-unavailable state. | low | The no-format/no-live-audio branch at `app.py:4041-4052` appends an error and continues; `turn_end` then marks no playback failure and sets `VOICE_READY`, despite having no playable audio. | patch |
| 7 | blind-hunter | `VOICE_HEARD` is defined and mapped but no wake path produces it. | medium | `_apply_wake_state()` handles only `CAPTURING` and `IDLE` (`app.py:1872-1883`); `ACKNOWLEDGING` and `SENDING` are never mapped, so the wake path cannot show `heard` or `transcribing`. | patch |
| 8 | blind-hunter | Empty capture ignores the domain result and unconditionally paints `ready`. | false | `capture_empty` is explicitly accepted from the listening phase and transitions to idle (`domain.py:517-524`, `domain.py:249-257`); the cited rejected-domain branch does not occur in this path. | reject |
| 9 | blind-hunter | The story's `done` status conflicts with the tracker's `review` status. | false | This is the prescribed pre-review lifecycle state, and the workflow owns the status transition after findings are handled; fixing it now would edit review metadata rather than the implementation. | reject |
| 10 | blind-hunter | The story's completion boxes and verification log are incomplete. | false | This is a documentation-state observation whose proposed fix is to alter the reviewed story metadata; it is not an implementation defect and is rejected by the review workflow's spec-edit rule. | reject |
| 11 | edge-case-hunter | A non-stale rejected event is logged and ignored while the turn remains active. | false | The current rejection branch applies a terminal domain error, sets `turn_failed`, renders an error, and returns at `app.py:3793-3807`; it does not ignore the event. | reject |
| 12 | edge-case-hunter | A normalized connection loss is accepted without updating the app connection state or cleanup. | false | The explicit connection-loss branch at `app.py:3809-3812` invokes `_mark_connection_lost()`, including connection/session cleanup. | reject |
| 13 | edge-case-hunter | EOF without `turn_end` leaves the active turn stranded. | false | The current EOF guard applies `error` and clears the domain turn before returning (`app.py:4146-4156`, `domain.py:653-663`). | reject |
| 14 | edge-case-hunter | A failure can close a captioned stream before the accumulated response text is committed. | medium | Failure exits at `app.py:4102-4120` and outer transport handling at `app.py:3459-3475` do not call `render_assistant(complete=True)`, so playback-timed captions may remain a prefix. | patch; grouped with #4 |
| 15 | verification-gap | Clean EOF coverage does not prove the full honest failed-turn contract. | medium | The existing EOF regression (`tests/test_app.py:2758-2773`) proves cleanup and a diagnostic, but does not assert the final displayed phase/text or the failure-path recovery guarantees; filed as a patch gap. | patch |
| 16 | verification-gap | Audio-file fallback coverage checks the WAV but not the displayed unavailable phase. | low | `tests/test_app.py:3145-3172` verifies the recovered file only; it does not assert the UI state after the fallback path. | patch; grouped with #6 |
| 17 | verification-gap | Player-failure tests do not observe transient states after audio write failure. | low | `tests/test_app.py:2878-2914` checks the final unavailable label and WAV, but no state history proves that a failed write never presents a speaking sample afterward. | patch |
| 18 | verification-gap | No regression proves audio-unavailable state clears on a later successful turn. | low | `_clear_audio_unavailable()` exists at `app.py:737-741` and is called at turn start, but the app tests do not reuse the same app across a failed-audio and successful-audio turn. | patch |
| 19 | verification-gap | No app-level test covers a playback failure reported only by `close()`. | medium | The completion path inspects `player.failure` after `_close_player()` (`app.py:4129-4133`), but `tests/test_app.py:2917-2951` covers close timing/counting without a close-only failure assertion. | patch |
| 20 | verification-gap | A normalized connection-loss event reaches generic domain/state sync without an explicit recovery path. | false | The explicit recovery path is present at `app.py:3809-3812` and delegates to `_mark_connection_lost()`; the filed claim describes code no longer in the tree. | reject |
| 21 | verification-gap | A rejected non-stale event is rendered and then ignored, risking a stranded turn. | false | The current branch makes the domain terminal, marks failure, reports the error, and returns (`app.py:3793-3807`); the claimed ignore path is absent. | reject |
| 22 | acceptance-auditor | Failure paths drop the unseen tail of streamed text instead of retaining the complete accumulated response. | medium | This is the same missing failure finalization as #4/#14: only the successful `turn_end` branch commits with `complete=True`. | patch; grouped with #4 |
| 23 | acceptance-auditor | Hands-free wake turns skip `heard` and `transcribing` before remote activity. | medium | `_apply_wake_state()` maps wake capture only to listening, and `_send_wake_turn()` invokes `_run_turn()` directly after the coordinator's `SENDING` state (`app.py:1872-1883`, `app.py:1910-1923`); the canonical local phases are therefore omitted. | patch; grouped with #7 |

### Review Findings

Patch findings:

- [x] [Review][Patch] Finalize accumulated streamed response text on error, interruption, EOF, and transport failure [app.py:3459]
- [x] [Review][Patch] Preserve collected PCM as WAV recovery output when a turn fails before `turn_end` [app.py:4135]
- [x] [Review][Patch] Map wake acknowledgement and send states to `heard` and `transcribing` [app.py:1872]
- [x] [Review][Patch] Mark an undecodable file-only fallback as audio unavailable and assert the resulting UI state [app.py:4041]
- [x] [Review][Patch] Extend clean-EOF coverage to the complete failed-turn phase and response contract [tests/test_app.py:2758]
- [x] [Review][Patch] Assert that a player write failure never presents a speaking state after the failure [tests/test_app.py:2878]
- [x] [Review][Patch] Prove audio-unavailable state clears on a subsequent successful turn [tests/test_app.py:737]
- [x] [Review][Patch] Cover playback failure reported only when the player closes [tests/test_app.py:4129]

Rejected findings:

- `false` (#1, blind-hunter): EOF applies a terminal domain error and clears `turn_active`; the alleged `turn_already_active` outcome is disproven by the current code.
- `false` (#2, blind-hunter): normalized connection loss already calls `_mark_connection_lost()`, which updates the connection and closes the session.
- `false` (#3, blind-hunter): non-stale rejected events already become terminal domain errors and stop consumption.
- `false` (#8, blind-hunter): empty capture is accepted from listening and transitions the domain to idle; the claimed rejection is not present.
- `false` (#9, blind-hunter): tracker-versus-spec lifecycle is the expected pre-review state and is resolved by the workflow after review handling; it is not an implementation defect.
- `false` (#10, blind-hunter): the proposed remedy edits review metadata in the story under review, so it is rejected rather than treated as a code finding.
- `false` (#11, edge-case-hunter): the rejection branch marks failure, renders an error, and returns; it does not ignore the event.
- `false` (#12, edge-case-hunter): normalized connection loss has an explicit cleanup branch in the current consumer.
- `false` (#13, edge-case-hunter): EOF applies a terminal domain error and clears the active turn before returning.
- `false` (#20, verification-gap): the explicit connection-loss recovery path is present; the filed claim is stale against the current tree.
- `false` (#21, verification-gap): rejected non-stale events are terminalized and reported; the claimed ignored path is absent.

Fix round 1 (2026-09-10): all eight patch findings were applied. Failure paths
now commit the accumulated response and preserve collected PCM, wake states map
through `heard` and `transcribing`, malformed file-only fallback is explicitly
unavailable, and the focused regressions cover EOF, failed playback, recovery,
and close-only failure. Focused app/wake tests passed (240); the full suite
passed (931) with one existing `websockets.legacy` deprecation warning.

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
