---
title: 'Browser hands-free wake, follow-up, and spoken stop'
type: 'feature'
created: '2026-09-09'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '9c0ce3a00b2649351e5b3d18a4fa806060610481'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-web-epic-1-reliable-conversation.md'
  - '{project-root}/docs/testing/home-09-appliance-loop.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The iPad browser can currently perform a single explicit push-to-talk turn, but it cannot behave like the household appliance: wake on a configured phrase, capture a question without another tap, accept one wake-free follow-up after the answer, and withdraw silently when the speaker says exactly “stop”.

**Approach:** Extend the existing browser speech controller into an opt-in hands-free mode. The browser owns recognition and local phase timing; the appliance remains the authenticated Hermes session owner and sends only normalized question text over the existing display channel. Pause recognition during response playback to prevent the display hearing its own answer.

## Boundaries & Constraints

**Always:** Hands-free is explicitly armed by a user gesture after the display is connected, hydrated, healthy, idle, and advertising the feature. The configured active-profile wake phrase(s) are the source of truth. A wake event starts one initial bounded capture; a successful answer opens one bounded follow-up window (default eight seconds) without another wake phrase, then returns to wake detection. Exact `stop`, case-insensitive with ordinary terminal punctuation ignored, cancels the current capture locally and sends nothing. Connection loss, server error, permission failure, or recognition failure disarms hands-free, stops playback/timers, and requires an explicit re-arm after recovery. The browser never receives a bearer token or raw relay audio.

**Never:** Do not send the wake phrase or `stop` as a Hermes turn. Do not automatically replay a transcript after a socket loss. Do not keep recognition open while Hermes is thinking, speaking, or buffering; full-duplex barge-in and stopping playback by voice remain a separate story. Do not add a second Hermes session, a browser-side protocol implementation, or a claim that installed Home Screen/PWA mode works without physical validation. Completion is judged in a Safari browser tab under Guided Access; Home Screen/PWA packaging is not part of this story.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| ARM_WAKE | User taps Enable hands-free on a connected idle display | Browser requests permission once, shows the configured wake-ready state, and listens locally | Unsupported recognition or denied permission leaves hands-free off with a safe action message |
| WAKE_ONLY | Final recognition is only the configured wake phrase | Wake text is discarded; display acknowledges, then captures one bounded question | Silence returns to wake-ready without a Hermes turn |
| WAKE_PLUS_TEXT | One recognition result contains wake phrase followed by a question | Wake phrase is removed; question is sent exactly once | Empty/ambiguous remainder is treated as silence, not a blank turn |
| LOCAL_STOP | Exact `stop` arrives during initial or follow-up capture | Capture closes silently; no turn, capture tone, or replay occurs | Recognition returns to wake-ready |
| FOLLOW_UP | Initial turn completes successfully and playback ends | One wake-free bounded follow-up capture begins; one non-empty result sends once | Silence, exact `stop`, error, or disconnect ends follow-up and returns to wake mode without a third capture |
| FAILURE | Permission loss, recognition end/error, server error, or disconnect | Recognition/timers/audio stop; status is honest; hands-free is disarmed | Recovery hydrates fresh state but never resubmits old text; user re-arms |

</frozen-after-approval>

## Code Map

- `home_display/web/src/state/voice.ts` -- browser recognition lifecycle, wake matching, bounded capture, local stop, and Web Audio coordination.
- `home_display/web/src/App.svelte` -- arm/disarm control, connection/readiness gating, display-phase coordination, follow-up timer, and cleanup.
- `home_display/web/src/state/channel.ts`, `state/bridge.ts` -- hydrated transport readiness and existing voice/audio envelopes.
- `home_display/web/src/state/protocol.ts`, `home_display/state.py` -- validated, non-secret browser capability/config metadata.
- `home_display/appliance.py` -- active-profile wake configuration, capability publication, and authenticated browser turn lifecycle.
- `home_display/web/src/state/voice.test.ts`, `App.test.ts`, `channel.test.ts`, `tests/test_home_appliance.py` -- recognition, state, transport, and no-replay regression seams.
- `README.md`, `docs/testing/home-09-appliance-loop.md` -- iPad arm, wake, follow-up, stop, disconnect, and physical validation procedure.

## Tasks & Acceptance

**Execution:**
- [x] `home_display/state.py`, `home_display/web/src/state/protocol.ts`, `home_display/appliance.py` -- expose only the active profile’s non-secret hands-free capability, wake phrase(s), and follow-up limit when the authorized session is ready -- keep browser configuration aligned with the relay.
- [x] `home_display/web/src/state/voice.ts` -- implement opt-in wake recognition, wake-prefix extraction, bounded initial/follow-up capture, exact local stop, and generation-safe cancellation -- guarantee one local wake cycle produces at most two turns.
- [x] `home_display/web/src/App.svelte` -- add explicit arm/disarm UX and coordinate recognition with connected idle/speaking/error/disconnected phases -- prevent premature capture, echo, and silent re-opening after failure.
- [x] `home_display/web/src/state/*.test.ts`, `App.test.ts`, `tests/test_home_appliance.py` -- test wake-only, wake-plus-text, silence, stop, follow-up, error, disconnect, and no-replay paths -- lock the observable contract.
- [x] `README.md`, `docs/testing/home-09-appliance-loop.md` -- document the selected iPad mode, permission gesture, and manual smoke gate -- make hands-free validation reproducible.

**Acceptance Criteria:**
- Given a connected, hydrated, idle display and a user gesture, when hands-free is enabled, then the browser requests permission and listens for the configured phrase without sending ambient speech.
- Given a wake phrase followed by a question, when recognition finalizes, then the phrase is stripped and exactly one question reaches Hermes; the phrase itself never appears as a turn.
- Given a successful answer, when response playback ends, then one wake-free follow-up window opens and closes after silence or its deadline; a second follow-up is never created.
- Given exact `stop` during either capture window, when recognition finalizes, then no Hermes turn or capture-complete signal is sent and the browser returns silently to wake-ready.
- Given a server error or connection loss at any point, when the page reconnects, then it remains disarmed until explicitly enabled and never resubmits an uncertain transcript.
- Given the selected iPad launch mode, when the manual smoke is run, then it records permission, wake, one initial turn, one follow-up, silence timeout, both stop cases, response playback pause, disconnect, recovery, and no-replay evidence.

## Implementation Notes

- Safari browser-tab mode under Guided Access is the selected delivery target. Home Screen/PWA packaging remains outside this story’s physical gate.
- Hands-free uses the browser’s native SpeechRecognition surface and the existing same-origin `voice_turn`/audio bridge. The browser receives neither the bearer token nor raw relay audio.
- Wake metadata is optional schema-1 configuration. It is published only on a connected browser session; invalid, duplicate, empty, or oversized active-profile phrases suppress hands-free while preserving tap-to-talk.
- Follow-up begins only after the appliance is idle and all queued Web Audio sources for the completed turn have ended. Interruptions, errors, and disconnects disarm the controller and request a fresh relay connection.
- Recognition callbacks, timers, and send failures are generation-guarded so a stopped or replaced Safari recognition instance cannot create a late turn.

## Spec Change Log

- 2026-09-09 — Selected Safari browser tab under Guided Access; implemented and reviewed the browser hands-free slice.
- 2026-09-10 — The approved cross-surface
  `spec-continuous-wake-free-follow-ups.md` supersedes this slice's historical
  one-follow-up limit. The browser now repeats the bounded wake-free window
  after every successful non-empty turn; this document remains the historical
  browser hands-free delivery record.

## Review Triage Log

- `C-01` — `medium / patch` — `displayReady` now includes `protocolError`, and post-permission checks re-read the live connection/view state before opening the microphone.
- `C-02` — `medium / patch` — `_browser_capabilities()` now withholds `browser_hands_free` when no valid wake phrase exists.
- `C-03` — `medium / patch` — Python and TypeScript both enforce the eight-phrase, 128-character contract; appliance publication suppresses invalid profile configuration.
- `C-04` — `medium / patch` — prompt and busy snapshots abort hands-free unless the controller is already submitting its current turn.
- `C-05` — `high / patch` — interrupted audio and turn events now terminate the browser turn as an error/reconnect path, so idle cannot open follow-up.
- `C-06` — `medium / patch` — browser turn errors publish a terminal error, disarm through the view path, and request a fresh session.
- `C-07` — `medium / patch` — PTT reset detaches and stops the active recognition object before clearing local state.
- `C-08` — `low / patch` — the controller exposes a short `heard` phase before starting bounded capture, making the acknowledgement observable.
- `C-09` — `medium / patch` — the semantic surface retains the final assistant response while idle.
- `C-10` — `low / patch` — streamed response text is not repeatedly announced; the live region is polite outside active speaking and off while streaming.
- `C-11` — `low / patch` — prompt title, body, and option labels are mirrored into the semantic surface.
- `C-12` — `low / patch` — the decorative WASM canvas is `aria-hidden` so it cannot compete with the semantic surface.
- `C-13` — `low / patch` — the semantic surface now exposes the configured account/profile label.
- `C-14` — `documentation / patch` — implementation tasks are checked, verification evidence is recorded below, and the kiosk document now points to the current Safari smoke procedure.
- `C-15` — `verification / patch` — focused tests now cover capability validation, protocol-error gating, prompt/interruption disarm, idle response semantics, playback completion, nonzero result indexes, and late callback no-replay behavior.
- `P-01` — `medium / patch` — invalid or non-finite follow-up configuration falls back to the safe eight-second default before capability publication.
- `P-02` — `medium / patch` — invalid, duplicate, empty, and oversized active-profile phrases suppress hands-free capability instead of raising from the appliance loop.
- `P-03` — `medium / patch` — the browser parser rejects more than eight phrases, matching the Python contract.
- `P-04` — `medium / patch` — `resume()` is followed by a live readiness check; a disconnect during the permission gesture cannot arm the controller.
- `P-05` — `medium / patch` — prompt, error, connecting, and non-idle snapshots stop or abort recognition as appropriate.
- `P-06` — `medium / patch` — `audio_abort` and `turn_interrupted` enter the terminal error/reconnect path and cannot be treated as successful follow-up triggers.
- `P-07` — `false` — mismatched `audio_end` events are ignored by the pending-turn guard; only the matching turn’s end can complete playback.
- `P-08` — `low / patch` — local stop normalization ignores terminal comma, period, question mark, exclamation, semicolon, colon, and Unicode ellipsis.
- `P-09` — `medium / patch` — recognition error callbacks verify both generation and recognition identity before disarming a current listener.
- `P-10` — `false` — stopped recognition handlers are detached and stale result callbacks fail the generation check, so a late result cannot submit.
- `P-11` — `medium / patch` — wake-ready restart is deferred briefly after stopping the old Safari recognition instance; follow-up also retries after a start race.
- `P-12` — `low / patch` — capture timers clamp to the browser’s maximum practical `setTimeout` delay.
- `P-13` — `medium / patch` — synchronous and asynchronous `sendText` failures leave the controller disarmed rather than stuck in `submitting`.
- `P-14` — `medium / patch` — changing phrases or timeout while armed aborts the old generation and requires an explicit re-arm.
- `V-01` — `verification / patch` — added a two-source Web Audio completion test; follow-up waits until the last source ends.
- `V-02` — `verification / patch` — added a cumulative-result test with a nonzero `resultIndex`.
- `V-03` — `verification / patch` — added an App-level semantic live-response test and decorative-canvas accessibility assertion.
- `V-04` — `verification / patch` — added a disconnect/late-callback test proving no replay after recovery.
- `V-05` — `false` — duplicate of `C-01`; the shared `displayReady` fix and regression test cover both review observations.
- `V-06` — `false` — duplicate of `C-02`/`C-03`; the shared capability contract and appliance/parser tests cover both review observations.
- `V-07` — `false` — duplicate of `C-05`/`P-06`; terminal interruption handling is covered by the same patch and App regression path.

## Design Notes

The browser should treat the wake listener as a local finite-state machine, not as another conversation transport:

```text
OFF → WAKE_READY → INITIAL_CAPTURE → TURN_IN_FLIGHT
                         ↑                 ↓ success
                         └──── FOLLOW_UP ←─┘
```

Recognition is paused in `TURN_IN_FLIGHT` and during streamed playback. `stop`, silence, timeout, error, and disconnect all have explicit exits; none falls through to an implicit resend.

## Verification

**Commands:**
- `npm test -- --run` (from `home_display/web`) -- 149 tests passed.
- `npm run check` (from `home_display/web`) -- zero Svelte/TypeScript errors and warnings.
- `npm run build` (from `home_display/web`) -- production bundle generated successfully.
- `/Users/amandachappell/Development/hermes-relay-tui/venv/bin/pytest` -- 884 tests passed, one pre-existing `websockets.legacy` deprecation warning.
- `git diff --check` -- no whitespace errors.

**Manual checks (if no CLI):**
- On the selected iPad mode, arm once, say the wake phrase plus a question, let the answer finish, ask exactly one follow-up without the phrase, wait through silence, repeat with exact `stop` during both capture windows, then stop/restart the host and verify explicit re-arm and no replay.
- Manual Safari/iPad execution remains the physical validation gate; it has not been claimed complete by the automated checks.
