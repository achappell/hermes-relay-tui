---
title: 'Show W/K user transcription and retain completed responses'
type: 'feature'
created: '2026-09-10'
status: 'done'
route: 'correct-course'
review_loop_iteration: 0
failed_layers: 'Edge Case Hunter'
baseline_commit: '959dc2b7ea89c83d4d1908560ef9f4115ed84b81'
source_story: '2-WK-2'
change_proposal: '{project-root}/_bmad-output/planning-artifacts/sprint-change-proposal-2026-09-10.md'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-web-epic-1-reliable-conversation.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-web-epic-1-hands-free.md'
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
---

<frozen-after-approval reason="human-owned intent — approved by Amanda in the 2026-09-10 sprint change proposal">

## Intent

**Problem:** The W/K browser sends the captured utterance to Hermes but gives
the speaker no visible confirmation of what was heard. It also leaves the
completed response's retention timing implicit, so the answer is not reliably
readable after playback.

**Approach:** Add transient browser-local presentation state for interim and
final user recognition text, keep the final utterance visible through
submission, and retain the completed Hermes response while idle for a bounded
period. A new push-to-talk or hands-free capture clears the prior response
immediately; terminal failures clear stale conversation claims.

**Success:** The W/K surface visibly distinguishes the user's live/final
transcription from Hermes response text, keeps a completed answer readable
after playback, and never turns either into an archive or a second shared
state authority.

## Boundaries & Constraints

**Always:** Keep user text transient and room-local, preserve the existing
same-origin state/audio channel and appliance-owned Hermes session, expose
honest capture and audio phases, and keep the accessible DOM surface as the
presentation authority for the browser.

**Never:** Do not add raw audio or transcript persistence, a new Hermes wire
field, a shared `DisplaySnapshot` schema field for this browser-local state, a
second transcript store, or a claim of `Speaking` when response audio is not
available. Do not make iPad a separate renderer or alter WASM as part of this
slice.

</frozen-after-approval>

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| CAPTURE_INTERIM | Browser recognition emits interim text | User transcription is visible in the active capture surface | Empty interim results do not create a stale line |
| CAPTURE_FINAL | Recognition finalizes a non-empty utterance | Final user transcription remains visible through submission | Empty/cancelled capture sends nothing |
| RESPONSE_STREAM | Hermes response text arrives with audio | Streamed response remains distinct from user transcription | Audio phase stays honest if playback cannot start |
| RESPONSE_COMPLETE | Playback and turn complete successfully | Completed response remains visible while idle for up to 60 seconds | Timer is cleared by the next capture |
| NEW_CAPTURE | Push-to-talk or hands-free capture begins | Prior response is cleared immediately | Cancelled capture does not restore stale response text |
| TERMINAL_FAILURE | Disconnect, error, or unrecoverable audio state | Stale conversation presentation clears safely | No transcript or response is archived or replayed |

## Code Map

- `home_display/web/src/state/voice.ts` — interim/final recognition callbacks
  and capture lifecycle notifications.
- `home_display/web/src/App.svelte` — local user-text state, new-capture reset,
  response-retention timer, and terminal-state cleanup.
- `home_display/web/src/surfaces/StateSurface.svelte` — distinct accessible
  user transcription, streamed response, completed response, and phase/audio
  presentation.
- `home_display/web/src/state/*.test.ts`, `App.test.ts` — recognition,
  retention, timer, cancellation, audio, and accessibility regressions.

## Tasks & Acceptance

**Execution:**

- [x] Add a browser-local callback or equivalent state path for interim and
  final user recognition text without changing the Hermes wire contract.
- [x] Render user transcription distinctly from streamed and completed
  Hermes response text in the semantic DOM surface.
- [x] Clear prior response text at the beginning of every push-to-talk and
  hands-free capture; make the 60-second retention timer generation-safe.
- [x] Add focused tests for interim/final text, successful retention, timeout,
  next-capture clearing, cancelled capture, disconnect, and unavailable audio.

**Acceptance Criteria:**

- Given active browser capture, when interim or final recognition text is
  available, then the W/K surface shows it as the user's transcription; the
  final utterance remains visible through submission and is never archived.
- Given a successful response, when playback ends and the display returns to
  idle, then the completed Hermes response remains readable until the next
  capture begins or 60 seconds elapse, whichever comes first.
- Given a new push-to-talk or hands-free capture, when capture begins, then
  the previous response is cleared immediately, including when the new capture
  is cancelled or yields no usable text.
- Given a streamed response or unavailable audio, when the surface updates,
  then response text remains distinct and the phase never claims `Speaking`
  without available response audio.
- Given a disconnect or terminal error, when the surface resets, then stale
  user and response presentation is cleared without replaying a turn or
  persisting a transcript.
- Given the browser's accessible DOM surface, when a user or assistant text
  update is announced, then labels and live-region behavior distinguish active
  capture, response streaming, completed response, and terminal state.

## Implementation Notes

- The current appliance snapshot already carries completed `response_text`;
  this story keeps the new user transcription and retention trigger local to
  the W/K browser controller/App state rather than expanding schema 1.
- The 60-second default is the approved W/K behavior. It is a browser
  presentation policy, not a server timeout and not a transcript retention
  guarantee.
- The existing DOM-first Svelte restoration and optional WASM target remain
  unchanged; the DOM surface is the supported accessible browser path.

## Validation Plan

- `npm test -- --run` from `home_display/web` with focused App/voice/surface
  tests first.
- `npm run check` and `npm run build` from `home_display/web`.
- `venv/bin/pytest` from the repository root for appliance and shared-state
  regressions.
- Manual Chrome, iPad/Safari, and Samsung Bespoke checks for visible user
  text, post-playback retention, next-capture clearing, and honest error/audio
  state.

## Spec Change Log

- 2026-09-10 — Created through the approved BMad Correct Course proposal
  after live W/K browser feedback.

## Review Triage Log

- `F-01` — `verification-gap` — `medium / patch` — The App-level follow-up test checks the follow-up label but not that the previous response and user text were cleared; `App.svelte:263-272` does clear them, so add the missing boundary assertion.
- `F-02` — `verification-gap` — `medium / patch` — The controller test proves the submitted wake-plus-question remainder but not the callback value; add an assertion that the displayed callback excludes the wake phrase.
- `F-03` — `verification-gap` — `medium / patch` — PTT cancellation has no App-boundary assertion for clearing interim text, and `BrowserVoiceController.stop()` currently emits no clear callback; patch the cancellation path and test it.
- `F-04` — `verification-gap` — `medium / patch` — The unavailable-audio App test leaves the snapshot idle, so it cannot observe the speaking-without-playback or hands-free recovery path; add a real failed playback sequence.
- `F-05` — `blind-hunter` — `medium / patch` — The idle retention timer starts at `App.svelte:104-119` before queued Web Audio sources finish; verified by the separate `playbackFinished` gate, so schedule only after playback settles.
- `F-06` — `blind-hunter` — `medium / patch` — A `PcmAudioPlayer` failure leaves `responseHasAudio` true and hands-free in `submitting`; verified because `maybeCompleteHandsFreeTurn()` refuses completion while the stale flag remains, so reset playback and abort hands-free.
- `F-07` — `blind-hunter` — `medium / patch` — Audio failure changes only the voice-control error while the snapshot can still render `Speaking`; verified by `StateSurface` deriving its state from the snapshot, so add a local unavailable-audio presentation state.
- `F-08` — `blind-hunter` — `medium / patch` — `audio_abort` clears local presentation before checking `pendingAudioTurnId`; a late older-turn abort can therefore erase the current turn, so scope cleanup to the matching turn.
- `F-09` — `blind-hunter` — `medium / patch` — PTT `stop()` and `reset()` leave the callback-owned transcript untouched; this is the same cancellation-cleanup defect as `F-03`, and both paths need to notify a clear.
- `F-10` — `blind-hunter` — `medium / patch` — Hands-free `disarm()` leaves interim text on the idle surface; this is the same local-cancellation root cause as `F-03`/`F-09`, so notify a clear on disarm.
- `F-11` — `blind-hunter` — `low / patch` — Empty recognition results do not call `onTranscript`, so a browser correction can leave the preceding interim text visible; forward an empty callback to clear it.
- `F-12` — `blind-hunter` — `medium / patch` — `StateSurface` hides response text in `thinking` and `buffering` even though the appliance publishes streamed text there; include those honest non-speaking response phases.
- `F-13` — `blind-hunter` — `medium / patch` — `data-response-phase` labels buffering, error, and disconnected states as streaming; verified as a semantic contradiction, so expose explicit buffering/unavailable/hidden values.
- `F-14` — `blind-hunter` — `maybe-false / rejected-low` — Nested live-region duplication is plausible but cannot be established from the diff without assistive-technology behavior; the proposed fix would be a low-impact accessibility refinement rather than a demonstrated everyday defect.
- `F-15` — `blind-hunter` — `medium / patch` — The response region has no completion announcement while its ancestor disables live updates during speaking; add a polite live region only for the completed response and keep active audio quiet.
- `F-16` — `blind-hunter` — `medium / patch` — The unavailable-audio test does not drive a speaking snapshot or queued audio, so it would pass if the false-Speaking and follow-up-deadlock regressions were reintroduced; extend it with the failing playback path.
- `F-17` — `blind-hunter` — `maybe-false / defer` — Epic 2 context names `transcribing`, but this story has no settled browser-local mapping or paintable interval distinct from recognition/listening and submission; deciding whether to add a new public phase requires a follow-up contract decision.
- `F-18` — `blind-hunter` — `medium / patch` — The checked task claims cancellation, timer, unavailable-audio, and lifecycle tests are complete while the listed regressions are not covered; add the missing focused assertions and implementation paths.
- `F-19` — `blind-hunter` — `low / rejected` — The new `epic-2-context.md` is not listed in this spec's context frontmatter; the claim is true, but correcting the build's spec during its own review is explicitly prohibited.
- `F-20` — `acceptance-auditor` — `medium / patch` — The retention behavior violates AC2 because the 60-second window begins on idle before playback completion; this is the same root cause as `F-05`.
- `F-21` — `acceptance-auditor` — `medium / patch` — Hiding streamed text in thinking/buffering violates AC4; this is the same root cause as `F-12`.
- `F-22` — `acceptance-auditor` — `medium / patch` — Failed browser audio can still present Speaking and hide the current response, violating AC4 and the no-false-Speaking constraint; this is the same root cause as `F-04`/`F-07`.
- `F-23` — `acceptance-auditor` — `medium / patch` — Playback failure can let `audio_end` complete a hands-free turn with no sources and open follow-up incorrectly; this is the same stale-audio-state root cause as `F-06`.
- `F-24` — `acceptance-auditor` — `medium / patch` — Cancelled PTT can leave stale transcription visible, violating the capture-cancellation edge case; this is the same root cause as `F-03`/`F-09`.
- `F-25` — `acceptance-auditor` — `medium / patch` — An older audio abort can clear a current turn, violating late-event isolation; this is the same root cause as `F-08`.

The Edge Case Hunter layer failed before producing findings because its reviewer
agent reached its external usage limit. Blind Hunter, Verification Gap Reviewer,
and Acceptance Auditor completed; the failed layer remains recorded so this is
not reported as a fully clean review.
