---
id: SPEC-hermes-relay-tui
companions:
  - ../../planning-artifacts/prds/prd-hermes-relay-tui-2026-09-07/prd.md
  - ../../planning-artifacts/briefs/brief-hermes-relay-tui-2026-09-07/addendum.md
  - ../../planning-artifacts/architecture/architecture-hermes-relay-tui-2026-09-08/ARCHITECTURE-SPINE.md
  - ../../planning-artifacts/ux-designs/ux-hermes-relay-tui-2026-09-07/DESIGN.md
  - ../../planning-artifacts/ux-designs/ux-hermes-relay-tui-2026-09-07/EXPERIENCE.md
sources:
  - ../../planning-artifacts/briefs/brief-hermes-relay-tui-2026-09-07/brief.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability.

# Hermes Home Assistant Platform

## Why

The private household pilot needs natural access to the household's chosen Hermes relationship from a room, without a phone or terminal, while remaining truthful about which doorway heard, captured, spoke, displayed, or failed. A Puck, ESP32-S3/LVGL touch Display, passive room Display, iOS/macOS Client, TUI, and iPad kiosk now make fragmentation the central risk: each surface could invent different identity, turn-state, privacy, and recovery behavior. This work creates one inspectable, household-owned contract before the first-room pilot expands.

## Capabilities

- **CAP-1**
  - **intent:** An authorized Puck, ESP32 Touch Display, enabled W/K browser voice surface, or Client can start a turn for a selected Hermes Profile, with the profile fixed before device capture.
  - **success:** The dinner journey selects the configured profile before Puck, ESP32 Touch, or W/K browser voice capture; iOS and TUI can start their own authorized voice or typed turns; an unavailable or revoked mapping starts no turn.

- **CAP-2**
  - **intent:** Each doorway exposes the actual turn phase and delivers the same Hermes response through its supported text and audio surfaces.
  - **success:** Tests or a live pilot observe `heard` → `listening` → `transcribing` → `thinking` → `buffering` → `speaking` → `complete` only when known; the Puck, ESP32 Touch Display, and enabled W/K browser voice surface deliver response audio, active text-capable surfaces render their own response, passive Displays mirror room-local text, and completed text with failed audio is marked unavailable rather than falsely speaking.

- **CAP-3**
  - **intent:** A configured voice doorway can continue one conversation briefly after a response and recover from transport loss without silently reopening capture or replaying an uncertain turn.
  - **success:** The Puck's v1 follow-up window lasts eight seconds; any ESP32 Touch or W/K browser follow-up is explicitly bounded; exactly `stop` creates no replacement turn; reconnect creates a fresh Hermes Session and requires a fresh initiation; a dropped active turn is never automatically resent.

- **CAP-4**
  - **intent:** The platform routes wake phrases through uniquely mapped profiles and selects one authorized physical Device when several hear the same wake.
  - **success:** Duplicate mappings are rejected; revoked, unavailable, or unapproved identity fails closed before capture; a simultaneous-wake fixture produces one winner using proximity and configured tie priority, with silent losers and no duplicate Hermes turn.

- **CAP-5**
  - **intent:** Passive Room Displays and the W/K browser surface render shared ambient, active-turn, prompt, and recovery semantics while keeping conversation local to the owning Room; W/K is also an active Epic 1 voice surface when `browser_voice` is advertised.
  - **success:** ESP32-S3/LVGL and browser fixtures accept the same valid states and actions; the selected Room mirrors profile, live transcription, response, and honest failure; the active W/K path may capture and deliver audio through its browser adapter; other Rooms receive no turn text; prompts are visible but have no touch response action in v1.

- **CAP-6**
  - **intent:** Displays provide useful idle household context and a consistent visual departure reminder for qualifying shared-calendar events.
  - **success:** Room-filtered Immich photos or a neutral fallback appear while idle; every Display shows the same event name, location, departure time, countdown, and `estimated` label when applicable; time/location changes recompute, cancellation and event start clear, and missing travel data produces no fabricated card or audio.

- **CAP-7**
  - **intent:** iOS can discover, approve, configure, revoke, and re-enroll physical household Devices without file editing.
  - **success:** A discovered Device stays inert until explicit approval; setup visibly completes in the order Room → Wake Mappings → Ready on iOS and the Device; revocation removes access while powered, and re-enrollment is required to restore it.

- **CAP-8**
  - **intent:** iOS and the TUI provide independent portable and terminal doorways into the Hermes relationship, with deliberate local history where supported.
  - **success:** iOS and TUI conversations do not merge live Sessions; each can show its own response and phase state; intentional history persists only on those Client surfaces, and TUI diagnostics are not required for the household pilot.

## Constraints

- Hermes remains authoritative for profile context, answer content, correctness, calendar, household home, and travel estimates; doorways do not create local assistant behavior or fallback answers.
- Core session/protocol and portable display rules are framework-independent; front ends consume `SessionProtocol` and the shared display contract rather than duplicating policy.
- Active response text and prompts are Room-local; the visual Departure Card is the explicit household-wide exception.
- Puck and ESP32 Touch audio are transient and home-LAN-only; the Media Server is not a transcript archive, while iOS/TUI may retain deliberate Local History.
- Every physical Device uses an individual revocable credential, and unapproved, revoked, or unavailable identity fails closed before capture.
- The first release is a single-Room pilot with the ReSpeaker-based Puck prototype, ESP32-S3/LVGL Display, iPad browser kiosk, separate iOS/macOS Client boundary, and TUI; contracts remain multi-Room-ready.
- The Puck prototype hardware is the Seeed reSpeaker Lite (XMOS XU316 onboard AEC/beamforming DSP + XIAO ESP32-S3), distinct from the classic ReSpeaker Raspberry Pi HAT family whose `seeed-voicecard`/DKMS driver fragility ruled it out for the stationary appliance (HOME-05); the Lite's own stock USB Audio Class firmware satisfies HOME-05's stationary-speakerphone hardware requirement but not the Puck role.
- The Puck runs custom ESP32-S3 firmware with on-device wake-word detection and its own network identity/credential, rather than streaming raw audio to a host for wake detection; this is required by FR1/FR9's multi-Device wake arbitration and NFR4's fail-closed-before-capture identity check, both of which need the Puck itself to be the independently identified trust boundary.
- Supported surfaces preserve truthful phase semantics, with roughly one-second wake acknowledgement and roughly four-second first spoken audio as v1 working targets.
- The private pilot uses an explicitly enabled trusted-LAN display binding; credentials never enter snapshots, actions, diagnostics, browser state, or display transport.
- The ESP32 Touch Display is a first-class Epic 1 voice-plus-display surface. Its visual state consumes the shared display contract, while its microphone/audio path must use an explicit bounded transport and must not move Hermes answer authority onto the device. The current snapshot/action firmware path is foundation only until that audio path is implemented.
- The Puck's on-device wake-word engine is ESPHome's `micro_wake_word` component, following Seeed's own reSpeaker Lite firmware reference for this exact board rather than Espressif ESP-SR or a from-scratch port; sherpa-onnx is explicitly excluded because its million-parameter streaming-ASR-transducer KWS models target embedded Linux/mobile-class hardware, not a bare-metal microcontroller like the XIAO ESP32-S3. `micro_wake_word` v2 also runs multiple independently-trained models concurrently and reports which one fired, serving FR7's multiple-Wake-Mappings-per-Device requirement directly. Consequence: the existing `wakewords/*.onnx` (openWakeWord-style) assets, including `hey_hermes.onnx`, do not carry over — `micro_wake_word` uses its own model format, so keeping the "hey hermes" phrase on the Puck means retraining it through the `OHF-Voice/micro-wake-word` TensorFlow pipeline, not reusing the current file; the host-side `wake.py`/`wakewords/*.onnx` stack is untouched by this decision.

## Non-goals

- Hosting Hermes intelligence or a large model on a Device, or becoming a second assistant.
- A general smart-home ecosystem, vendor-cloud migration, camera-history product, media catalog, public provisioning system, or commercial multi-household deployment.
- Touch-based Hermes prompt choices, audible Departure Cards, or unsolicited Puck speech for calendar or outage state.
- Active-playback barge-in before an echo-safe audio route is proven.
- Full response text on the Puck's small TFT or default transcript archives on Pucks, passive Displays, or the Media Server. The ESP32 Touch Display may render the active response because it is a voice-capable surface.
- A native iPad application separate from the W/K browser surface, or a multi-room hardware rollout as an MVP prerequisite.
- Splitting repositories before a demonstrated dependency or platform conflict requires it.

## Success signal

The single-Room pilot completes the UJ-1 dinner journey without a phone, keyboard, or TUI in at least four of five scripted attempts. Revoked/disconnected tests produce zero audio payloads and zero Hermes turns, display fixtures produce one consistent calendar state across targets, median wake acknowledgement is at or below one second, median first spoken audio is at or below four seconds, and no default raw-audio or Media Server transcript archive appears.

## Assumptions

- The initial four-of-five UJ-1 threshold is provisional and will be recalibrated after real-room measurements.

## Open Questions

- What proximity signal, arbitration window, and configured priority semantics select the closest Device?
- How does iOS publish Room, Wake Mapping, and credential changes, and what last-known configuration is safe while a Device is offline?
- What Device Credential storage, rotation, expiry, offline revocation, and re-enrollment mechanism fits each physical target?
- What Media Server/audio bridge transport, bounded buffering, and cleanup behavior covers success, cancellation, and disconnect for the Puck and ESP32 Touch Display?
- Which people and exclusions define each Room's Immich filter, and what freshness policy applies?
- Where are travel estimates keyed in the vault, how is staleness detected, and how are missed calendar updates recovered?
- What kiosk authentication and offline re-entry behavior does the W/K browser deployment on iPad require?
- When does a future release earn active-playback barge-in after the v1 audio route proves echo-safe?
- Which localization targets and child-comprehension checks follow the English pilot, and what exact microcopy and cue durations remain to be chosen?
