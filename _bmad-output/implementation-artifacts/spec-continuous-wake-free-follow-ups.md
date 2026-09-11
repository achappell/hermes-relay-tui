---
title: 'Continuous wake-free follow-ups across wake-enabled surfaces'
type: 'feature'
created: '2026-09-10'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'dadd72807b3f5632c8fd487d19fc7d1cf0c8403e'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/surface-coverage-matrix.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-web-epic-1-hands-free.md'
---

<frozen-after-approval reason="human-owned intent — approved by Amanda's 2026-09-10 clarification">

## Intent

**Problem:** A wake phrase currently establishes one initial turn and only one
wake-free follow-up on the TUI, native appliance, and W/K browser. After that
follow-up, the surface returns to `ready` and demands the wake phrase again,
which breaks the conversation the wake phrase was meant to establish.

**Approach:** Make the wake-word conversation loop continuous on every surface
that has a wake-word capture adapter: after each successful response, open the
same bounded silence window again without another wake phrase. Preserve the
existing exact `stop`, silence, failure, disconnect, disarm, and no-replay
exits. Pre-wake idle remains `ready`/wake phrase waiting.

**Scope:** Apply the contract to the shared Python coordinator, TUI, native
appliance, and W/K browser. Native iOS already keeps hands-free capture alive
for repeated turns and receives regression confirmation. Puck and ESP32 Touch
do not yet have the microphone/session adapter needed for a follow-up; their
future wake-capable adapters must consume this contract, but this slice does
not invent that missing transport.

## Boundaries & Constraints

**Always:** A successful non-empty turn is followed by another wake-free
capture window until the user is silent, says exactly `stop` (normal terminal
punctuation ignored), disarms, disconnects, or a capture/send/recognition
failure ends the conversation. Response playback must finish before the next
window. Each accepted utterance uses the existing Hermes session and is sent
once. Failures never replay an uncertain turn. Ordinary text, `Ctrl+R`, and
barge-in remain their existing one-shot paths.

**Never:** Do not change Hermes wire events, add a second session, reopen a
disarmed microphone, or let a wake detector score response/capture audio. Do
not claim continuous parity for Puck or ESP32 Touch before their bounded audio
and session adapters exist. Do not remove the configured per-window timeout or
turn the wake phrase itself into a transcript.

</frozen-after-approval>

## Code Map

- `handsfree.py` — shared wake capture/send state machine; refactor delivery
  cleanup and repeat follow-up capture without an intermediate wake-ready state.
- `app.py` — TUI wake wiring, listener pause/resume gating, and follow-up
  capture timeout; keep direct `Ctrl+R` and barge-in semantics unchanged.
- `home_display/appliance.py` — native appliance coordinator, recorder lease,
  display state publication, and playback-drained handoff.
- `home_display/web/src/state/voice.ts`, `App.svelte` — browser wake FSM,
  post-playback recognition recovery, and state presentation.
- `tests/test_handsfree.py`, `tests/test_app_wake.py`,
  `tests/test_home_appliance.py`, `home_display/web/src/state/voice.test.ts`,
  `home_display/web/src/App.test.ts` — repeated-turn, stop/silence, failure,
  listener ownership, and playback-boundary regression seams.
- `~/Development/hermes-relay-ios/HermesRelayIOS/ViewModels/VoiceSessionCoordinator.swift`
  and its tests — existing continuous iOS hands-free behavior to verify, not
  duplicate in this repository.
- `puck_bridge/turn.py`, `firmware/respeaker-lite/pcm_capture.h`, and
  `firmware/esp32-s3-touch-lcd-7/main/src/` — current single-shot/no-audio
  boundaries; document the shared contract without fabricating transport.

## Tasks & Acceptance

**Execution:**
- [x] `handsfree.py` — loop successful follow-up capture/send and retain the
  active conversation state until a defined exit — eliminate the one-follow-up
  ceiling without weakening fail-closed behavior.
- [x] `app.py`, `home_display/appliance.py` — keep wake detection paused during
  every follow-up handoff and return to wake-ready only after silence/stop —
  prevent stale audio or a second wake from racing the next window.
- [x] `home_display/web/src/state/voice.ts`, `App.svelte` — reopen the bounded
  follow-up phase after every completed response — preserve Safari retries,
  generation guards, and explicit disarm on failure.
- [x] Focused Python/web tests — prove at least three wake-free turns, silence,
  exact stop, failed response, disconnect, and playback completion boundaries.
- [x] `README.md`, `AGENTS.md`, existing wake/browser specs, and smoke notes —
  replace one-follow-up language with the continuous contract and record the
  Puck/ESP32 adapter boundary.

**Acceptance Criteria:**
- Given a successful wake-triggered answer, when each non-empty follow-up
  completes, then another configured wake-free window opens without returning
  to `ready` or requiring the wake phrase.
- Given silence or exact `stop` in any follow-up window, when capture closes,
  then no empty/stop turn is sent and the surface returns to wake detection.
- Given a failed, interrupted, disconnected, or ambiguous turn, when cleanup
  finishes, then no follow-up capture opens and no uncertain turn is replayed.
- Given an active response, when playback is still streaming or draining, then
  recognition remains paused; only completed playback can open the next window.
- Given a future wake-capable Puck or ESP32 Touch adapter, when it is delivered,
  then its owning story uses this same repeated-window contract rather than a
  one-follow-up exception.

## Design Notes

Planning facts: Amanda's clarification closes the only product intent gap;
there are no migrations, external deployments, or destructive effects; the
footprint is limited to the shared coordinator, three capable front ends,
their tests, operational docs/spec notes, and generated browser assets.

## Implementation Notes

- 2026-09-11: `HandsFreeCoordinator` now owns a repeated follow-up loop. A
  successful non-empty delivery keeps the coordinator busy through playback
  handoff, so TUI and appliance listeners cannot rearm between responses; the
  existing send/readiness/stop/failure exits still finish the conversation.
- 2026-09-11: The TUI projects the coordinator's active handoff as listening
  rather than pre-wake `ready`. The native appliance suppresses a stale
  `thinking` repaint after spoken playback while retaining its busy state for
  the next bounded capture. The browser's `turnFinished()` now starts the next
  bounded follow-up for every successful response, retaining its Safari
  prime/watchdog/retry and generation guards. Its local heard/listening state
  also overrides the shared surface's idle label during capture, while the
  host idle snapshot remains the readiness gate for controls.
- 2026-09-11: Puck and ESP32 Touch remain explicit adapter boundaries: the Puck
  bridge still accepts a single transcribed upload and the ESP32 transport
  still has no microphone/session path. Native iOS already has continuous
  hands-free capture; no duplicate implementation was added here.

## Spec Change Log

- 2026-09-10: Amanda approved the cross-surface continuous wake-free
  follow-up intent after confirming that post-response `ready` was wrong for
  every wake-word interface.

## Review Triage Log

- 2026-09-11 — The formal BMad blind-hunter, edge-case-hunter, and
  verification-gap review layers were launched against the full baseline diff;
  all three timed out without returning a report. No reviewer finding is
  claimed from those layers.
- 2026-09-11 — Local adversarial review found one presentation defect: the W/K
  browser could be in its local `follow_up` phase while the shared StateSurface
  still rendered host `idle`/“Ready”. `App.svelte` now projects local
  heard/listening/submitting phases for display only, and the App regression
  test asserts the follow-up surface is `listening`. Focused tests and
  `svelte-check` pass.
- 2026-09-11 — Local review found no further defects in repeated coordinator
  delivery, detector pause/resume ownership, playback boundaries, failure or
  disconnect exits, no-replay behavior, or the Puck/ESP32 adapter boundary.

## Verification

**Commands:**
- `venv/bin/pytest tests/test_handsfree.py tests/test_app_wake.py tests/test_home_appliance.py` — passed: the focused wake/appliance regression set passes, including the repeated-turn, listener-handoff, silence, stop, and failure cases.
- `npm test -- --run` from `home_display/web` — passed: 178 browser tests.
- `npm run check && npm run build` from `home_display/web` — passed: zero Svelte/TypeScript errors or warnings; production bundle generated as `home_display/static/assets/index-4-_N7Rxp.js`.
- `venv/bin/pytest` — passed: 949 tests, with one pre-existing `websockets.legacy` deprecation warning.
- `git diff --check` — passed after the review fix.

**Manual checks (if no CLI):**
- On a configured wake-capable surface, wake once, complete the initial
  question, ask at least three follow-ups without repeating the wake phrase,
  then end with silence and exact `stop`; confirm playback, visible phases,
  and no stale/replayed turn.
- Live Hermes voice smoke was not run in this worktree because no configured
  endpoint or bearer token is available; fake sessions and browser fixtures
  cover the success, playback, silence, stop, failure, disconnect, and
  no-replay paths.
