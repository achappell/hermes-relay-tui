---
title: 'Recover W/K hands-free after response playback'
type: 'bugfix'
created: '2026-09-10'
status: 'ready-for-dev'
route: 'correct-course'
review_loop_iteration: 0
source_story: 'WK-1'
change_proposal: '{project-root}/_bmad-output/planning-artifacts/sprint-change-proposal-2026-09-10.md'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-web-epic-1-hands-free.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-web-epic-1-safari-follow-up-recovery.md'
  - '{project-root}/docs/testing/home-09-appliance-loop.md'
---

<frozen-after-approval reason="human-owned intent — approved by Amanda in the 2026-09-10 sprint change proposal">

## Intent

**Problem:** A Samsung Bespoke smart-fridge browser completed its first W/K
voice turn, then reported the generic “Microphone or speech recognition is
unavailable” state when hands-free recognition needed to resume after response
playback. The initial success means the browser must not be classified as
unsupported from that message alone.

**Approach:** Harden the browser-local hands-free transition from completed
playback into the bounded follow-up window. Preserve the existing Safari
silent-hang recovery, classify the actual browser recognition failure when it
is available, retry transient restart failures within the configured deadline,
and leave hands-free disarmed with a precise recoverable state when the budget
is exhausted.

**Success:** After a successful W/K turn and completed response playback, a
supported browser accepts one wake-free follow-up or exits the bounded window
honestly. No retry, stale callback, or late result creates a duplicate Hermes
turn or leaves phantom listening active.

## Boundaries & Constraints

**Always:** Keep the existing same-origin `voice_turn` bridge, appliance-owned
Hermes session, generation guards, configured follow-up deadline, and explicit
re-arm requirement after terminal failure. Capture only safe recognition error
categories and structural diagnostics; do not log prompts, raw audio, tokens,
or unrestricted browser internals.

**Never:** Do not add a browser credential, server protocol, automatic replay,
second Hermes session, full-duplex capture, or vendor-specific claim that has
not passed its manual gate. Do not weaken the successful Chrome/iPad/Safari
paths to accommodate one unobserved Samsung error.

</frozen-after-approval>

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| FOLLOW_UP_READY | Initial turn succeeds and all response audio ends | One wake-free follow-up window opens | No second follow-up is created |
| TRANSIENT_RESTART | Browser rejects or prematurely ends a replacement recognition attempt | Retry within the configured follow-up deadline | Retry is generation-safe and bounded |
| SILENT_HANG | Recognition starts or appears to start but emits no usable lifecycle callback | Existing watchdog/replacement path gets a bounded chance to recover | Exhaustion disarms hands-free and reports an honest recoverable state |
| VENDOR_ERROR | Browser emits a recognition error after the first turn | Error category is retained for safe classification and validation | Do not label a previously working browser as unsupported without evidence |
| LATE_CALLBACK | A stopped/replaced recognizer emits a result or error | Callback is ignored | No duplicate turn, wake phrase, or stale state mutation |
| DISCONNECT | State channel or Hermes turn fails during recovery | Recognition and timers stop; fresh user action is required | No replay of the uncertain turn |

## Code Map

- `home_display/web/src/state/voice.ts` — recognition identity, generation,
  retry, watchdog, safe error classification, and follow-up deadline.
- `home_display/web/src/App.svelte` — playback completion, follow-up start,
  disarm/error presentation, and connection gating.
- `home_display/web/src/state/voice.test.ts`, `App.test.ts` — fake recognition
  and playback lifecycle coverage, including late callbacks and no-replay.
- `docs/testing/home-09-appliance-loop.md` — browser and physical-device
  smoke procedure, including the Samsung validation note.

## Tasks & Acceptance

**Execution:**

- [ ] Preserve the existing Safari prime/watchdog/retry behavior while making
  post-playback error handling explicit for other browser implementations.
- [ ] Retain a safe recognition error category and expose a specific,
  recoverable user state after bounded retry exhaustion.
- [ ] Add fake-recognition coverage for a successful first turn followed by a
  vendor error, retry, recovery, bounded failure, disarm, and late callback.
- [ ] Update the browser smoke note with the Samsung Bespoke observation and
  the exact error category once captured without sensitive content.

**Acceptance Criteria:**

- Given a successful W/K voice turn and completed response playback, when
  hands-free recognition resumes, then one configured follow-up window opens
  and one non-empty final utterance can submit exactly one turn.
- Given a transient post-playback restart failure, when the retry budget has
  not expired, then replacement recognition is attempted without duplicate
  listeners or duplicate submissions.
- Given retry exhaustion or an unsupported recognition error after a browser
  has already completed a first turn, when recovery ends, then hands-free is
  disarmed and the UI reports a specific honest recoverable state rather than
  the generic unsupported message alone.
- Given a stale result, error, or end callback from an earlier recognizer,
  when it arrives after replacement or disarm, then it cannot submit text or
  mutate the current follow-up state.
- Given a connection, playback, or turn failure, when the browser recovers,
  then it requires explicit re-arm and never resubmits the uncertain turn.
- Given Chrome, iPad/Safari, and Samsung Bespoke manual gates, when the smoke
  procedure is run, then each result records success or the bounded failure
  category without claiming unsupported capability from incomplete evidence.

## Implementation Notes

- Amanda's Samsung Bespoke browser completed the first voice turn, so initial
  microphone permission and speech recognition are known to work on that
  device. The precise `SpeechRecognitionErrorEvent.error` value was not
  captured and must be observed during implementation validation.
- The existing Safari recovery artifact remains the regression baseline. This
  slice addresses the post-playback path's generic error handling and
  vendor-specific evidence gap; it does not reopen the frozen Safari intent.
- The browser remains a presentation and capture adapter. Hermes remains the
  answer authority, session owner, and no-replay boundary.

## Validation Plan

- `npm test -- --run` from `home_display/web` with focused recognition tests
  first.
- `npm run check` and `npm run build` from `home_display/web`.
- `venv/bin/pytest` from the repository root.
- Manual Chrome and physical iPad/Safari follow-up checks, then Samsung
  Bespoke first-turn/follow-up validation with the safe error category
  recorded if recovery still fails.

## Spec Change Log

- 2026-09-10 — Created through the approved BMad Correct Course proposal
  after live Samsung Bespoke feedback.
- 2026-09-10 — The approved cross-surface
  `spec-continuous-wake-free-follow-ups.md` supersedes the one-follow-up
  boundary recorded here for future W/K behavior; the current implementation
  and acceptance are tracked by that cross-surface spec.
