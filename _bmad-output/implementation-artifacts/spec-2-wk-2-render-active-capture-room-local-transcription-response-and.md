---
title: 'Show W/K user transcription and retain completed responses'
type: 'feature'
created: '2026-09-10'
status: 'ready-for-dev'
route: 'correct-course'
review_loop_iteration: 0
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

- [ ] Add a browser-local callback or equivalent state path for interim and
  final user recognition text without changing the Hermes wire contract.
- [ ] Render user transcription distinctly from streamed and completed
  Hermes response text in the semantic DOM surface.
- [ ] Clear prior response text at the beginning of every push-to-talk and
  hands-free capture; make the 60-second retention timer generation-safe.
- [ ] Add focused tests for interim/final text, successful retention, timeout,
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
