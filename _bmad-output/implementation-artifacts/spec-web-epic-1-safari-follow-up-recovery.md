---
title: 'Recover Safari hands-free follow-up after audio playback'
type: 'bugfix'
created: '2026-09-09'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
baseline_commit: 'a6cb54280c5b77c6d3507def29380eadf3ec1ac9'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-web-epic-1-hands-free.md'
  - '{project-root}/docs/testing/home-09-appliance-loop.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** On iPad Safari, the first hands-free turn completes and the UI enters “Listening for a follow-up…”, but the next `SpeechRecognition` session can silently hang after Web Audio playback: it produces no result, error, or end event, so the wake-free follow-up is ignored.

**Approach:** Make the browser follow-up recognizer resilient to this WebKit audio-session failure with a single microphone-session prime and bounded, escalating restart attempts. A working recognition session still accepts one wake-free final utterance; exact `stop`, silence, disconnect, and turn ownership retain their existing no-replay behavior.

**Success:** After an audible response on affected Safari, a follow-up recognition attempt either captures and sends exactly one final question or exits the bounded window honestly without leaving hands-free in a phantom listening state.

## Boundaries & Constraints

**Always:** Keep the existing same-origin `voice_turn` bridge and local finite-state machine. Detach stale recognition callbacks before each retry, guard every asynchronous attempt by generation, prime the microphone at most once per follow-up recovery, and keep the retry budget inside the configured follow-up window. Do not send wake phrases, raw audio, or duplicate transcripts.

**Never:** Do not add a server protocol, browser credential, automatic replay, or full-duplex capture. Do not treat the WebKit workaround as proof that Safari’s underlying defect is fixed; retain a safe bounded fallback when every attempt fails.

</frozen-after-approval>

## Implementation Notes

- Root cause is externally corroborated by WebKit bug 321436: Safari 26 on iOS/iPadOS can appear to restart SpeechRecognition after media playback while emitting no recognition lifecycle callbacks. The current controller retries only when `start()` throws or `onend`/`onerror` fires, so this silent hang is invisible to it.
- Keep the fix in `home_display/web/src/state/voice.ts`; inject the microphone-prime hook for deterministic tests and use the browser default only at the edge.
- Add a red regression test that simulates a first follow-up attempt which silently hangs, then verifies a later retry accepts one wake-free result. Cover normal follow-up, local stop, disarm, and the bounded failure exit as regression guards.
- Update the Safari kiosk testing note with the expected retry/fallback behavior, then run the focused web suite, type checks, production build, and full Python suite. The physical iPad follow-up gate remains required after the host is restarted.
- Implemented the one-time `getUserMedia` prime, `onstart` watchdog, and escalating replacement-recognition retries. Stale callbacks are detached, retry timers are generation-safe, and the configured follow-up deadline remains the outer bound.
- Added focused browser coverage for silent recovery, prime ordering, temporary-stream cleanup, and the existing follow-up/stop paths. Updated `docs/testing/home-09-appliance-loop.md` with the Safari recovery expectation.
- Verification so far: 154 browser tests pass, `npm run check` reports zero errors and warnings, `npm run build` serves the rebuilt bundle, `git diff --check` is clean, and the complete Python suite passes 891 tests with one existing websockets deprecation warning.
- Final verification: 154 browser tests pass after covering the `onstart`-without-result Safari variant. The live HTTPS host serves the new bundle; the remaining physical iPad retry is the release gate, not a claimed automated result.

## Review Triage Log

- `medium / patch` — Self-review identified that an `onstart` callback could clear the original watchdog even when Safari then emitted no speech. Added a separate post-start activity watchdog and regression coverage; normal started recognition still clears the watchdog on the first result.
