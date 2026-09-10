---
title: 'Restore the DOM-first Svelte home display'
type: 'feature'
created: '2026-09-09'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'ed56bcbccce3fff5655f8fd7c36309361aa3e10f'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/docs/testing/home-03-kiosk-display.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The cleaner, non-WASM Svelte home display was replaced as the browser default by a mandatory LVGL/WebAssembly canvas. That makes the page depend on generated WASM assets and leaves the existing DOM state surface hidden; it also removes the direct-use prompt buttons that made the display pleasant to operate.

**Approach:** Restore the DOM-first Svelte `DisplayBridge` and surfaces as the primary Web/iPad implementation. Direct-use displays render the existing touch-capable `PromptOverlay`; passive consumers remain read-only and are not given a second interaction path. Preserve the current browser voice, hands-free, audio, HTTPS/WSS, appliance ownership, and no-replay behavior. WASM files remain an optional target, not a startup prerequisite.

## Boundaries & Constraints

**Always:** Use the existing same-origin state channel and normalized `DisplayBridge` reducer for snapshots and prompt actions. Start the bridge without waiting for WASM so connecting, disconnected, error, idle, response, and prompt states are visible in ordinary DOM. Only advertised, current prompt choices may dispatch; failed actions leave the prompt available. Browser voice and hands-free controls remain gated by a hydrated, healthy, idle snapshot.

**Never:** Change the display wire contract, appliance authentication/session ownership, browser voice transport, audio lifecycle, HTTPS behavior, or uncertain-turn recovery. Do not delete the tested WASM reducer/canvas target, add a second state source, expose prompt actions on passive mirrors, or require Emscripten assets to build or open the direct-use Svelte display. The supported iPad launch remains a Safari tab under Guided Access; Home Screen/PWA packaging stays out of scope.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| DOM_START | WASM files absent; browser opens the kiosk | DOM state surface starts the same-origin bridge and shows connecting/ready state | No WASM bootstrap error; channel errors remain visible |
| DIRECT_PROMPT | Hydrated prompt with `prompt.choose` and options | Touch buttons render in `PromptOverlay`; one selected normalized action reaches the bridge | Rejected/failed action keeps the prompt open and shows a safe error |
| TERMINAL_STATE | Error, disconnect, or reconnect after a turn | DOM surface clears stale response/prompt claims and shows the observed terminal state | Voice, hands-free, and playback reset without replay |
| VOICE_READY | Connected, hydrated, idle snapshot advertising `browser_voice` | Existing voice control sends one final non-empty transcript | Not-ready, denied, or failed capture sends nothing and returns usable |

</frozen-after-approval>

## Code Map

- `home_display/web/src/App.svelte` -- currently awaits `loadDisplayWasm` and mounts `WasmCanvas`; restore direct DOM bridge startup, prompt routing, and existing voice/audio lifecycle.
- `home_display/web/src/surfaces/StateSurface.svelte` -- polished DOM renderer for observed phases and streamed response; keep it as the normal surface and preserve its semantic state output.
- `home_display/web/src/surfaces/PromptOverlay.svelte` -- existing touch buttons, timeout behavior, bridge action callback, and standalone HTTP compatibility; mount it for direct-use prompt states.
- `home_display/web/src/state/bridge.ts` and `state/reducer.ts` -- already provide the plain TypeScript reducer, snapshot transition guards, action validation, and `/action` transport; do not create another state owner.
- `home_display/web/src/state/channel.ts`, `state/voice.ts`, and `home_display/appliance.py` -- retain the existing hydration, browser voice, hands-free, audio, capability, and terminal-state behavior.
- `home_display/web/src/App.test.ts` -- replace WASM/canvas bootstrap assumptions with DOM startup, direct prompt, terminal state, and existing voice regressions.
- `README.md`, `docs/testing/home-03-kiosk-display.md`, `shared/display/README.md` -- describe the DOM Svelte bundle as the browser default and WASM as optional.

## Tasks & Acceptance

**Execution:**
- [x] `home_display/web/src/App.svelte` -- start `DisplayBridge` with its default TypeScript reducer, render `StateSurface`/`PromptOverlay`, and retain current voice, hands-free, audio, and terminal cleanup -- restore the old direct-use path without losing Epic 1 behavior.
- [x] `home_display/web/src/App.test.ts` -- remove mandatory-WASM assumptions and cover DOM startup, direct-use touch action dispatch, no stale prompt on disconnect, and voice readiness -- lock the restored path.
- [x] `README.md`, `docs/testing/home-03-kiosk-display.md`, `shared/display/README.md` -- update build and smoke instructions and label WASM optional -- prevent the documentation from reinstalling the lost dependency.

**Acceptance Criteria:**
- Given a browser page that has not received a valid current snapshot, when the user taps the voice control, then no recognition object starts and no voice frame is sent.
- Given the generated WASM artifacts are absent, when a direct-use Web/iPad page opens, then the DOM Svelte surface connects and renders without a bootstrap error.
- Given a current prompt advertises `prompt.choose`, when a user taps an option, then exactly one validated action is sent and the prompt is dismissed only after transport acceptance.
- Given the state channel disconnects or reports an error, when the page receives the terminal outcome, then stale response/prompt claims disappear and voice, hands-free, and playback are reset without resubmitting a turn.
- Given a hydrated idle snapshot advertises browser voice, when the user completes one utterance, then the existing voice path sends one final non-empty transcript and remains usable after idle, error, or disconnect.
- Given the documented web build and smoke commands, when they run without Emscripten setup, then check/build/test pass for the DOM path; the optional WASM tests remain independently green.

## Implementation Notes

- Restored `App.svelte` to start `DisplayBridge` immediately with the plain TypeScript reducer and render the DOM `StateSurface` instead of waiting for `loadDisplayWasm` or mounting `WasmCanvas`.
- Mounted the existing direct-use `PromptOverlay` through the bridge action boundary, added safe action-failure feedback and timeout cleanup, and preserved browser voice, hands-free, audio, HTTPS/WSS, and terminal reset behavior.
- Updated the browser distribution, HOME-03 smoke procedure, and shared-display notes so Emscripten/WASM is optional; `npm run build` regenerated the tracked static bundle.
- Verification completed: 163 web tests, zero `svelte-check` diagnostics, production build, 87 focused Python appliance/server tests, 2 focused prompt-demo tests, 892 full Python tests, and `git diff --check` passed after review patches.
- Built and installed a local wheel, then verified both hashed browser assets resolve from the installed `home_display/static/` package data.

## Spec Change Log

## Review Triage Log

- [blind-hunter B1] `onValidSnapshot` cleared the App's protocol error before sequence filtering — verdict: medium; evidence: `StateChannel` deliberately calls that listener for duplicate and older snapshots, so the App no longer subscribes to it and now clears the error only in the accepted `onView` path; route: patch.
- [blind-hunter B2] A prompt could arrive while ordinary browser voice recognition remained open — verdict: medium; evidence: the restored App now resets `BrowserVoiceController` whenever a non-idle snapshot arrives while listening, with coverage for busy and disconnected snapshots; route: patch.
- [blind-hunter B3] Keying the prompt overlay by every display sequence could restart a prompt and its timer — verdict: medium; evidence: the key now reflects prompt content rather than the global sequence, and the overlay keeps a stable timeout key for an identical republished prompt; the regression is covered by the republish test; route: patch.
- [blind-hunter B4] An in-flight click request would become an obsolete action after overlay unmount — verdict: false; evidence: unmount clears only the auto-action timer, while a user-initiated action is already validated and its completion mutates only the originating component's local state; no parent or replacement prompt is mutated; route: reject.
- [blind-hunter B5] A hung action request could leave the prompt disabled indefinitely — verdict: medium; evidence: bridge and standalone transports now abort after ten seconds, the overlay reports the safe failure, and its button becomes usable again; route: patch.
- [blind-hunter B6] HTTP 200 was treated as callback completion — verdict: false; evidence: `DisplayServer` intentionally returns 200 after scheduling its fire-and-forget callback, and the spec requires dismissal after transport acceptance rather than appliance callback completion; route: reject.
- [blind-hunter B7] The server accepts a syntactically valid action without checking the current prompt or capability — verdict: medium; evidence: `/action` remains a transport callback, while the restored App validates through `DisplayBridge`; server-side authority would require a separate shared state/action design and predates this story; route: defer.
- [blind-hunter B8] The modal does not move or trap keyboard focus — verdict: low; evidence: this is a pre-existing accessibility enhancement beyond the direct-touch restoration, and implementing a complete focus lifecycle is more than a direct correction for the supported touch path; route: reject.
- [blind-hunter B9] The state summary remains in the accessibility tree beneath the prompt modal — verdict: low; evidence: the restored App now places the state surface under `aria-hidden="true"` while the direct-use overlay is visible; route: patch.
- [blind-hunter B10] A prompt advertising only `prompt.dismiss` has no visible dismissal button — verdict: false; evidence: this App exposes direct-use controls only when `prompt.choose` is advertised, so a prompt without that capability is intentionally read-only under the frozen passive-mirror boundary; route: reject.
- [blind-hunter B11] The App prompt test did not prove one successful action call — verdict: low; evidence: the direct-use test now asserts `dispatchAction` was called once, alongside the component-level success assertion; route: patch.
- [blind-hunter B12] The failed-action App test bypassed the bridge error callback — verdict: medium; evidence: the redundant global callback/error state was removed; the real bridge result is `false`, which the mounted overlay now renders as its local safe error, so the test exercises the production failure path; route: patch.
- [blind-hunter B13] The no-WASM test did not open a package with WASM absent — verdict: low; evidence: the production Vite build and type checks were run without Emscripten, and the App has no WASM bootstrap/import; the remaining suggestion is verification strengthening, not a demonstrated defect; route: reject.
- [blind-hunter B14] The README optional-WASM build order could leave packaged artifacts stale — verdict: low; evidence: README now explicitly requires rerunning the browser build after optional WASM generation and before Python packaging; route: patch.
- [blind-hunter B15] The prompt manual check lacked a reproducible fixture — verdict: medium; evidence: `home_display.demo --prompt` now publishes a capability-gated prompt and logs each normalized action, and the smoke procedure invokes it; route: patch.
- [blind-hunter B16] The frozen intent block was edited while the spec was still draft — verdict: false; evidence: the direct-use touch clarification was explicitly supplied and approved by the human before the spec entered implementation; route: reject.
- [blind-hunter B17] The spec did not record an explicit Safari/iPad physical gate — verdict: medium; evidence: automated/local checks cannot establish Guided Access, iPad permissions, secure WSS hydration, audio, or physical touch behavior; that external validation remains recorded as deferred work; route: defer.
- [blind-hunter B18] The spec claimed verification while `git diff --check` was pending — verdict: false; evidence: the check was rerun and passed, and the implementation note now records that result; route: reject.
- [blind-hunter B19] Shared display documentation promised a WASM caller path absent from production App — verdict: false; evidence: `DisplayBridge` still accepts an injected reducer and `WasmCanvas` remains available; only the normal App startup default changed to DOM-first, as documented; route: reject.
- [edge-case-hunter E1] A never-settling action transport could strand the overlay — verdict: medium; evidence: this is the same bounded-action-transport defect as B5; the ten-second abort/error path now covers it; route: patch, grouped with B5.
- [edge-case-hunter E2] A very large prompt timeout could overflow JavaScript timers and fire immediately — verdict: medium; evidence: prompt timeouts are now clamped to the JavaScript timer maximum, with a regression test for an oversized value; route: patch.
- [edge-case-hunter E3] Display busy state could leave ordinary voice listening — verdict: medium; evidence: this is the same non-idle voice-reset defect as B2; the App now resets listening recognition before a busy snapshot can submit it; route: patch, grouped with B2.
- [edge-case-hunter E4] A late action failure could appear on a replacement prompt — verdict: medium; evidence: the global App-level action error channel was removed; rejected actions now render only in the originating overlay, preventing cross-prompt error leakage; route: patch, grouped with B12.
- [edge-case-hunter E5] A stale prompt could post after disconnect — verdict: medium; evidence: the App action boundary now requires a connected state, a prompt state, and `can_choose` before calling the bridge; route: patch.
- [edge-case-hunter E6] Sequence-keyed remounts could permit duplicate action requests — verdict: medium; evidence: this shares B3's prompt identity root cause; prompt-content keys and stable timeout identity retain the submission guard across identical republished snapshots; route: patch, grouped with B3.
- [edge-case-hunter E7] A disconnected snapshot did not reset ordinary voice recognition — verdict: medium; evidence: the App now resets the voice controller for both disconnected snapshots and transport disconnects, covered in the voice regression; route: patch, grouped with B2.
- [edge-case-hunter E8] A valid stale snapshot could clear an error and re-enable an old idle view — verdict: medium; evidence: this shares B1's pre-filter recovery root cause; the App no longer handles `onValidSnapshot`, so only an accepted snapshot can recover the surface; route: patch, grouped with B1.
- [verification-gap V1] App tests hid the default reducer behind a bridge mock — verdict: low; evidence: `DisplayBridge` now has a real default-reducer test asserting a normalized accepted view reaches `onView`; route: patch.
- [verification-gap V2] Passive prompts were not asserted to remain read-only — verdict: low; evidence: the existing passive-prompt App test now asserts no overlay and no prompt buttons; route: patch.
- [verification-gap V3] App action-error mapping was not exercised through the bridge callback — verdict: false; evidence: the callback-only App mapping was removed because `dispatchAction(false)` already gives the overlay the same safe error; bridge transport and rejection tests remain direct, and the App test covers the mounted failure path; route: reject after patch.
- [verification-gap V4] Prompt timeout cleanup after unmount lacked a test — verdict: low; evidence: `PromptOverlay.test.ts` now unmounts a timed prompt, advances the clock, and asserts no action; route: patch.
- [verification-gap V5] Prompt arrival lacked an App-level playback reset assertion — verdict: medium; evidence: an App test now streams PCM, delivers a direct-use prompt, and asserts the active source is stopped; route: patch.
- [verification-gap V6] Successful direct-use action lacked an exact-once assertion — verdict: low; evidence: both App and overlay success paths now assert one call; route: patch.
- [verification-gap V7] Installed static asset references lacked a wheel smoke check — verdict: medium; evidence: CI now installs the built wheel, resolves `home_display/static/index.html` through `importlib.resources`, and verifies every referenced asset exists; route: patch.

## Design Notes

The current `DisplayBridge` accepts an optional reducer specifically so the
plain TypeScript reducer can own the normal browser path while the WASM reducer
remains injectable for experiments or another target. `PromptOverlay` already
supports a bridge callback, so direct-use touch actions remain validated at the
same boundary as every other browser action.

## Verification

**Commands:**
- `npm --prefix home_display/web test -- --run` -- all DOM, prompt, bridge, voice, and optional-WASM tests pass.
- `npm --prefix home_display/web run check` -- zero Svelte/TypeScript errors and warnings.
- `npm --prefix home_display/web run build` -- the browser bundle builds without a WASM toolchain.
- `venv/bin/pytest -k 'home_appliance or home_display_server'` -- appliance and state-channel browser paths pass.
- `venv/bin/pytest` -- complete Python suite passes.
- `git diff --check` -- no whitespace errors.

**Manual checks (if no CLI):**
- Open the local demo without generated WASM, observe the DOM phase transitions, present a prompt and tap each direct-use option, then stop/restart the host and verify disconnected state, fresh hydration, and no replay.
