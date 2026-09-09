---
title: 'Start an authorized Hermes turn'
type: 'feature'
created: '2026-09-08'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '25c332b7e32b0801f19c4c08a7fbcad1a14c3283'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-hermes-relay-tui-2026-09-08/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-hermes-relay-tui-2026-09-07/EXPERIENCE.md'
---

## Intent

**Problem:** The generic TUI can begin local microphone capture while its selected
Hermes profile is still disconnected or has not completed the `hello_ack`
handshake. That captures speech before authorization is known and makes the
resulting failure look like a usable turn.

**Approach:** Treat the selected profile's successful handshake as the gate for
every turn initiation. Make the active profile visible in the TUI connection
surface, keep wake and explicit initiation on the `SessionProtocol`, and retain
the existing no-replay behavior when transport failure is ambiguous.

## Boundaries & Constraints

**Always:** Authorization means the selected profile's resolved token plus a
verified `hello_ack`; no other profile or generic token may be substituted.
Capture starts only after the session reports that verified connection. Front
ends consume normalized session events, and tests use fakes rather than a live
Hermes endpoint or audio hardware.

**Never:** Change the Hermes wire protocol or invent a local response path. Do
not auto-replay a turn that may have reached Hermes. Do not modify the Puck
firmware or other-thread work, broaden this into iOS 16, or run live tests that
open speakers, a microphone, or the connected Puck device.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| VERIFIED_EXPLICIT | Selected profile, valid token, `hello_ack`, explicit voice request | Active profile is visible; capture runs once, then one turn is submitted through `SessionProtocol` | Normalized events drive the existing UI |
| RECONNECT_BEFORE_CAPTURE | Selected profile exists but session is disconnected; bounded reconnect succeeds | Reconnect and handshake complete before the microphone opens; the request is not duplicated | Existing connection status/retry surface is used |
| UNAUTHORIZED_INITIATION | Missing/invalid selected-profile token or failed handshake | Microphone is never opened; no turn is sent; no fallback profile is selected | Show disconnected/unavailable state and retain the honest recovery path |
| AMBIGUOUS_SEND | Capture and initial submission occur, then transport fails before completion | No automatic second submission | Preserve the existing ambiguous/error state and retry guidance |

## Code Map

- `app.py` -- TUI connection preflight, explicit voice capture, active-profile metadata, and state presentation.
- `session.py` -- verified handshake lifecycle and the session turn contract used by front ends.
- `handsfree.py` -- shared wake-to-capture coordinator; its pre-capture readiness guard protects wake-driven initiation.
- `config.py` -- selected-profile token resolution and connection arguments; the authorization source must remain isolated.
- `home_display/appliance.py` -- existing appliance-side reference guard; avoid changing the concurrent Puck surface unless a regression is found.
- `tests/test_app.py` -- fake-session coverage for capture gating, reconnect-before-capture, and single submission.
- `tests/test_session.py` -- session-level protection against sending on an unverified connection.
- `tests/test_handsfree.py` -- wake initiation coverage when the owning session is disconnected.

## Tasks & Acceptance

**Execution:**
- [x] `app.py` -- gate explicit voice initiation on a verified selected-profile session and expose the active profile in the connection header -- prevent unauthorized capture and make routing observable.
- [x] `session.py` -- reject turn initiation when the handshake-backed connection is absent -- keep the core contract fail-closed for every front end.
- [x] `handsfree.py` -- refuse wake initiation before acknowledgement or capture when the owning session is unverified -- keep the wake path fail-closed.
- [x] `home_display/appliance.py` -- keep the household front end on the current verified profile for capture, follow-up, and send -- preserve its existing fail-closed boundary while closing the routed-session race.
- [x] `tests/test_app.py` -- add disconnected, reconnecting, handshake-order, profile-display, and ambiguous-send regression cases -- prove the edge-case matrix without audio hardware.
- [x] `tests/test_session.py` -- cover the unconnected and in-flight-handshake turn guards while retaining normalized event behavior -- protect the shared core boundary.
- [x] `tests/test_handsfree.py` -- prove a disconnected or interrupted wake produces no acknowledgement, capture, or send -- cover the wake branch of the initiation contract.
- [x] `tests/test_home_appliance.py`, `tests/test_household_profiles.py`, and `tests/test_wake_sherpa.py` -- keep appliance wiring, profile routing, and test doubles aligned with the readiness contract.

**Acceptance Criteria:**
- Given the selected profile has a valid token and verified `hello_ack`, when an explicit or wake-driven turn begins, then the active profile is fixed before capture, capture occurs once, and exactly one initial submission is made through `SessionProtocol`.
- Given the selected profile has no usable authorization or no verified handshake, when a turn is initiated, then capture and submission do not occur, the UI reports unavailable/disconnected state, and no fallback profile or token is used.
- Given Hermes streams activity, text, audio, and completion events after a valid initiation, when the front end consumes them, then it renders the existing normalized session events without adding wire parsing to the UI.
- Given the initial submission may have reached Hermes but the transport fails before completion, when the failure is handled, then the prompt is not automatically replayed.
- Given the appliance-side connection guard already passes, when this story is implemented, then its existing fail-closed behavior and the other thread's Puck work remain unchanged.

## Implementation Notes

- `HermesSession.is_connected()` is now true only after `hello_ack` completes and is cleared at the beginning of `close()`. `send_turn()` raises `SessionNotReadyError` before advancing turn state or writing a turn frame.
- Explicit TUI voice capture reconnects through the selected profile before opening the microphone. Wake and appliance paths use a readiness callback so profile routing and connection loss are checked against the current session, including immediately after acknowledgement and before follow-up capture.
- A pre-wire readiness failure remains `PROMPT_NOT_SENT` and is queued. Once a turn has been displayed as submitted, transport failure retains the existing ambiguous/no-replay behavior.
- Review fixes were validated with the focused fake-session run (`281 passed, 1 skipped`) and the complete suite (`842 passed, 1 skipped`). No live Hermes, microphone, speaker, or Puck smoke test was run; that check remains intentionally pending for a supervised session.
- Live smoke on 2026-09-09 passed against the selected `amanda` profile: the real TUI completed a text turn; the real MacBook Air Microphone (input index 1) produced a non-empty Whisper transcript and a completed voice turn; and an intentionally refused endpoint kept the TUI disconnected with no microphone created. Response PCM was discarded and earcons/playback were disabled, so speakers and the Puck remained silent.

## Spec Change Log

## Review Triage Log

| # | Layer | Verdict / route | Evidence |
|---:|---|---|---|
| 1 | verification-gap | medium / patch | The missing explicit voice ordering case was added with a blocked handshake; it records `hello-start`, `hello-ack`, then `capture`, and passes. |
| 2 | verification-gap | medium / patch | The missing open-websocket/in-flight-handshake case was added; `send_turn()` raises before changing turn state or writing a frame. |
| 3 | verification-gap | medium / patch | The stale coordinator-session finding is real; readiness is now supplied dynamically and the household profile test drives `on_wake()` through Jensen after routing. |
| 4 | blind-hunter | medium / patch; grouped with #3 | Same cross-profile defect, independently reported; the dynamic readiness fix and routed-profile regression cover it. |
| 5 | blind-hunter | medium / patch | A connection loss during the blocking acknowledgement could open the microphone; readiness is rechecked immediately before capture and the race is tested. |
| 6 | blind-hunter | medium / patch | The new pre-wire exception previously fell into the ambiguous path; `SessionNotReadyError` now records `PROMPT_NOT_SENT`, queues the text, and has a regression test. |
| 7 | blind-hunter | false | The reconnect row is explicitly for an explicit voice request. Wake mode is disarmed on connection loss and requires `/wake on` after recovery; refusing wake while unverified is the captured fail-closed behavior. |
| 8 | blind-hunter | medium / patch; grouped with #2 | Same in-flight-handshake test gap, independently reported; the session test now asserts no index, ID, or wire turn. |
| 9 | blind-hunter | medium / patch; grouped with #1 | The boolean-only app fixture did not prove ordering; the slow-handshake fake now does, and the full suite passes. |
| 10 | blind-hunter | false | The proposed fix is a spec-only verification-list edit, which this workflow rejects; the complete `venv/bin/pytest` run exercised the changed handsfree, appliance, profile, and wake surfaces successfully. |
| 11 | blind-hunter | false | `in-review`, unchecked tasks, and an empty triage section were the prescribed state before review processing; the review is now recorded and Step 5 owns the final status transition. |
| 12 | edge-case-hunter | medium / patch; grouped with #3 | Same routed-profile stale-session defect; the appliance now passes a readiness callback bound to its current session. |
| 13 | edge-case-hunter | medium / patch; grouped with #5 | Same acknowledgement-loss race; the post-tone readiness check prevents capture and returns the coordinator to idle. |
| 14 | edge-case-hunter | medium / patch | The optional follow-up could open after the connection dropped; readiness is checked before claiming and before invoking follow-up capture. |
| 15 | edge-case-hunter | false | Profile switching is rejected while `_voice_capture_task` is live; the task is assigned synchronously before the next await, so the cited interleaving cannot occur through the Textual event loop. |
| 16 | edge-case-hunter | false | The second readiness check refuses capture when the session is no longer verified, which is the desired fail-closed result; there is no event-loop interleave between `_connect()` returning and that check. |
| 17 | edge-case-hunter | medium / patch | The close-time race was real; `_hello_verified` is cleared at `close()` entry before cancellation or cleanup can yield. |

## Verification

**Commands:**
- `venv/bin/pytest tests/test_app.py tests/test_session.py tests/test_profile_app.py` -- expected: all focused tests pass.
- `venv/bin/pytest` -- expected: complete suite passes with no new failures.
- `git diff --check` -- expected: no whitespace errors.

**Manual checks (if no CLI):**
- Live Hermes text and voice smoke passed on 2026-09-09 with playback disabled; the failure control against `ws://127.0.0.1:1/voice-session` also passed. Audible playback and the connected Puck were intentionally not exercised.
