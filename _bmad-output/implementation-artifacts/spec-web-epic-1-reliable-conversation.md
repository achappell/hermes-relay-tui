---
title: 'Reliable browser Hermes conversation for the iPad display'
type: 'feature'
created: '2026-09-09'
status: 'draft'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/planning-artifacts/epic-1-context.md'
  - '{project-root}/docs/testing/home-03-kiosk-display.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The browser/WASM display has the transport pieces for a Hermes turn, but its voice control can become available before a valid hydrated connection exists, and a terminal server error can leave the control stuck on “Sending…”. The accessible DOM state surface exists but is not mounted beside the shared LVGL canvas, so an iPad user or assistive technology cannot reliably observe the same conversation phases.

**Approach:** Make browser voice readiness an explicit consequence of a hydrated, healthy display snapshot and the advertised `browser_voice` capability. Reconcile local voice and audio state on every terminal display outcome, mount the existing accessible state mirror alongside the WASM canvas, and document a repeatable iPad Safari kiosk run.

## Boundaries & Constraints

**Always:** The browser uses the existing same-origin `/state` WebSocket and `voice_turn` envelope; Hermes authentication and session ownership remain on the appliance. Only one bounded, final recognized utterance is sent per tap. Controls are unavailable until a valid snapshot has hydrated the current socket, the connection is healthy, the appliance advertises `browser_voice`, and the display is idle. Errors and disconnects stop playback, return the control to a usable state, and never replay or resubmit a possibly delivered turn. The DOM mirror and canvas consume the same latest snapshot and connection state, with child-readable phase labels.

**Never:** Do not add credentials, raw audio, or Hermes protocol parsing to the browser. Do not introduce a new wire format, automatic retry of a voice turn, local audio-device dependencies, or Puck-specific wake-word/follow-up/exact-spoken-stop behavior. This slice targets a Safari browser tab used as an iPad/Guided Access kiosk; installed Home Screen/PWA packaging is not a completion claim until the open deployment decision and a physical iPad check are settled.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| READY_TURN | Hydrated connected idle snapshot with `browser_voice` | Tap starts one recognition session; final non-empty text sends once; thinking/speaking/idle phases and streamed response/audio appear | A failed send shows a safe actionable error and does not retry |
| NOT_READY | Connecting, stale, disconnected, unhealthy, busy, or capability absent | Button is disabled or unavailable; no microphone session starts and no `voice_turn` is written | The display remains honest about unavailable/disconnected state |
| CAPTURE_FAILURE | Browser lacks recognition or denies microphone permission | No turn is sent; control returns from listening to error/idle with a safe message | No browser exception or credential detail is surfaced |
| TERMINAL_TURN | Server error, interruption, or socket loss while submitting/playback | Playback stops; local “Sending…” state clears; error/disconnected status is rendered; any partial turn is abandoned | Reconnect hydrates current state and never resubmits the old text |

</frozen-after-approval>

## Open Questions

- iPad launch mode — Safari tab with Guided Access (recommended: the currently supported browser speech path and the existing same-origin server model) / installed Home Screen web app (more appliance-like, but requires a separate physical WebKit speech and audio-lifecycle validation before it can be supported).

## Code Map

- `home_display/web/src/App.svelte` -- owns browser voice gating, local voice state, canvas composition, and lifecycle cleanup.
- `home_display/web/src/state/channel.ts` -- owns socket hydration, reconnect, and browser `voice_turn` writes.
- `home_display/web/src/state/bridge.ts` -- adapts channel snapshots/actions/audio into the front end.
- `home_display/web/src/state/voice.ts` -- owns browser SpeechRecognition and streamed Web Audio playback.
- `home_display/web/src/surfaces/StateSurface.svelte` -- existing accessible state/response mirror to mount beside the canvas.
- `home_display/appliance.py` -- publishes browser capability and runs the authenticated browser-originated turn.
- `home_display/web/src/App.test.ts`, `home_display/web/src/state/channel.test.ts`, `home_display/web/src/state/voice.test.ts`, `tests/test_home_appliance.py` -- focused regression seams.
- `README.md`, `docs/testing/home-03-kiosk-display.md` -- build, LAN bind, and iPad smoke instructions.

## Tasks & Acceptance

**Execution:**
- [ ] `home_display/web/src/App.svelte`, `state/channel.ts`, `state/voice.ts` -- gate capture on verified readiness and reset local state for every terminal outcome -- prevent premature microphone access and stuck controls.
- [ ] `home_display/web/src/surfaces/StateSurface.svelte` and `App.svelte` -- mount the accessible mirror without duplicating conversation state -- make canvas state observable on the iPad.
- [ ] `home_display/appliance.py` -- advertise browser voice only after the relay session is connected and preserve safe unavailable/error transitions -- align capability with actual authorization.
- [ ] `home_display/web/src/*.test.ts` and `tests/test_home_appliance.py` -- cover not-ready capture, hydration, terminal error/disconnect, and no-replay behavior -- lock the Epic 1 contract.
- [ ] `README.md`, `docs/testing/home-03-kiosk-display.md` -- document the selected iPad launch mode and manual smoke gate -- make the physical validation reproducible.

**Acceptance Criteria:**
- Given a browser page that has not received a valid current snapshot, when the user taps the voice control, then no recognition object starts and no voice frame is sent.
- Given a connected, hydrated, idle snapshot advertising `browser_voice`, when the user completes one utterance, then exactly one normalized final transcript is sent and the local control leaves “Sending…” on the next idle, error, or disconnected outcome.
- Given a socket loss or server error after submission, when the channel reconnects, then the page shows disconnected until fresh hydration and does not resend the prior transcript.
- Given any accepted snapshot, when the canvas renders it, then the mounted DOM mirror exposes the same child-readable phase and response without a second state source.
- Given the documented build and LAN launch commands, when the page is opened in the selected iPad mode, then the manual smoke procedure covers permission, one voice turn, streamed response/audio, stop, disconnect, reconnect, and no-replay evidence.

## Implementation Notes

## Spec Change Log

## Review Triage Log

## Verification

**Commands:**
- `npm --prefix home_display/web test` -- all web tests pass, including readiness, terminal-state, and accessible-surface cases.
- `npm --prefix home_display/web run check` -- zero Svelte/TypeScript errors and warnings.
- `venv/bin/pytest tests/test_home_appliance.py tests/test_display_server.py` -- appliance/server browser path remains green.
- `venv/bin/pytest` -- complete Python suite passes.
- `git diff --check` -- no whitespace errors.

**Manual checks (if no CLI):**
- Run the documented LAN command, open the selected iPad mode, grant microphone permission, complete one turn, confirm audible/visible response, then stop/restart the host and verify disconnected status, fresh hydration, and no automatic replay.
