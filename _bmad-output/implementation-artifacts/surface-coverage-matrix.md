---
title: Surface coverage across BMad epics
type: traceability
status: active
updated: 2026-09-10
sources:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/implementation-artifacts/sprint-status.yaml
  - _bmad-output/implementation-artifacts/epic-1-context.md
  - _bmad-output/implementation-artifacts/spec-1-1-start-an-authorized-hermes-turn.md
  - _bmad-output/implementation-artifacts/spec-1-2-render-honest-turn-phases-and-response-delivery.md
  - _bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md
  - _bmad-output/implementation-artifacts/spec-1-4-recover-without-replaying-an-uncertain-turn.md
  - ../hermes-relay-ios/_bmad-output/implementation-artifacts/epic-1-context.md
  - ../hermes-relay-ios/_bmad-output/implementation-artifacts/spec-1-2-render-honest-ios-turn-phases.md
  - ../hermes-relay-ios/_bmad-output/implementation-artifacts/spec-3-1-discover-unconfigured-devices.md
  - ../hermes-relay-ios/docs/plans/2026-09-09-epic-1-ios-device-validation-plan.md
  - ../hermes-relay-ios/docs/plans/2026-09-09-ios-16-hands-free-barge-in.md
---

# Surface coverage across BMad epics

This is the local BMad traceability view. It deliberately does not use GitHub
Project state. It reports surface-level implementation evidence; formal story
workflow remains in the owning repository's story artifacts and is not a
separate matrix-wide status column.

Stories are surface-specific. Evidence that iOS implements a story does not
close the TUI, Puck, Web/iPad, or ESP32 Touch work, and a surface cell marked
`Implemented` does not make Epic 1 globally `done`.

## Surfaces

| Code | Surface | Boundary |
|---|---|---|
| I | iOS app | Native SwiftUI conversation and device-administration client; implemented in the sibling repository. |
| P | ReSpeaker Puck | ESP32-based audio/status doorway without a touch display; physical wake, capture, local status, and response audio. |
| E | ESP32 touch display | Waveshare ESP32-S3/LVGL voice-plus-display doorway. It captures voice, renders its own response, and delivers response audio as well as showing room state. |
| W/K | Web and iPad voice/display surface | One Python/Svelte browser voice-plus-display surface; iPad is a Safari/Guided Access deployment, not a separate renderer or product surface. |
| T | TUI | Textual terminal conversation surface. |

The surface relationship is therefore:

```text
Python host / DisplaySnapshot contract
             ├── Svelte DOM renderer ──► W/K (web and iPad kiosk)
             └── native LVGL renderer + voice adapter ──► E (ESP32 touch)
```

W/K is one implementation boundary and deployment family. It includes browser
voice capture and streamed response audio when the appliance advertises those
capabilities, and it still needs kiosk, accessibility, and device smoke
validation before it can be called complete. E must conform semantically, but
it does not need to share the web renderer or its visual layout. E's voice
capture and response-audio path is a separate Epic 1 delivery contract; the
current snapshot/action transport is foundation evidence only.

## Cell labels

- `Implemented` — inspected implementation and validation evidence cover this
  surface's acceptance portion; this does not claim every surface or the
  overall story is formally closed.
- `In review` — an implementation/spec exists, but its review, validation, or
  target build gate is incomplete.
- `Foundation` — existing foundation or partial implementation, but not a
  completed BMad story for that surface.
- `Open` — the story applies to the surface, but no local implementation
  artifact closes it.
- `N/A` — not a direct participant in the story.

For a cross-surface story or Epic, do not describe the overall item as done
while an applicable surface remains `Open`, `Foundation`, or `In review`,
unless an explicit product decision scopes that surface out. Formal story
workflow remains authoritative in the owning repository; this matrix makes
surface evidence and remaining work visible without duplicating that queue.

## Rendering decision — 2026-09-09

Exact visual parity between the ESP32 touch display and the iPad/webview is
not a product requirement.

- The Python/Svelte webview is the primary web and iPad voice/display implementation.
- The ESP32 touch display uses native LVGL layout and rendering and is also a
  voice-capable Epic 1 doorway: it captures voice and delivers response audio.
- Both targets must preserve the shared snapshot schema, phase semantics,
  capability rules, room ownership, and normalized actions.
- The iPad kiosk is a deployment of the Svelte webview, not a second renderer.
- LVGL/WASM remains an optional portability or parity target; it is not a
  prerequisite for the webview or iPad surface.

The shared snapshot/state contract covers visual phases, response text, and
audio-delivery state. It does not carry microphone or response PCM. ESP32
Touch voice capture and audio playback therefore require a separate bounded
audio/session adapter; firmware must not invent Hermes responses or become a
second Hermes authority.

The migration should use the existing Svelte DOM surface where practical. Do
not remove the current WASM assets until the replacement has equivalent state,
prompt, error, reconnect, and accessibility coverage.

## iOS audit — 2026-09-09

The sibling `../hermes-relay-ios` repository was inspected for the
implementation audit. Its `main` now contains the merged Device Discovery
slice plus commit `6642147` (`test(ios): add device discovery smoke fixture`).
The Debug-only fixture supplies deterministic simulator evidence without
shipping a production Device discovery transport.

- The iOS Epic 1 artifacts explicitly close Stories 1.1 and 1.2, and the
  physical-device validation record says their device-only checks completed.
- The implementation and deterministic tests also cover the iOS participant
  behavior for recovery: fresh session creation, unconfirmed-turn marking,
  no automatic replay, and stale-event isolation.
- The current macOS target passes 263 XCTest cases with 0 failures, and the
  current iOS simulator target passes 267 XCTest cases with 0 failures. Story
  3.1 now has deterministic and interactive simulator evidence: the approved
  and unconfigured sections, successful identity confirmation without
  promotion, connection failure with retry, and manual identification without
  approval were observed. Its iOS surface is `Implemented`; the local TUI
  story workflow remains separate.
- The optional iOS hands-free slice has deterministic coverage, but its real
  device smoke is still pending. That does not block Epic 5 Story 5.1, whose
  required tap-to-speak and typed doorway behavior is already implemented.

## Epic 1 — Have a reliable Hermes conversation

| Surface story | I | P | E | W/K | T |
|---|---|---|---|---|---|
| I-1 Authorized iOS initiation | Implemented | N/A | N/A | N/A | N/A |
| I-2 iOS phases and response/audio delivery | Implemented | N/A | N/A | N/A | N/A |
| I-3 iOS fresh recovery without replay | Implemented | N/A | N/A | N/A | N/A |
| P-1 Authorized Puck wake and capture | N/A | Open | N/A | N/A | N/A |
| P-2 Puck status and response audio delivery | N/A | Open | N/A | N/A | N/A |
| P-3 Puck bounded follow-up and exact `stop` | N/A | Open | N/A | N/A | N/A |
| P-4 Puck recovery without replay | N/A | Open | N/A | N/A | N/A |
| E-1 ESP32 Touch authorized voice capture | N/A | N/A | Open | N/A | N/A |
| E-2 ESP32 Touch native phases and response rendering | N/A | N/A | Foundation | N/A | N/A |
| E-3 ESP32 Touch response audio delivery | N/A | N/A | Open | N/A | N/A |
| E-4 ESP32 Touch bounded follow-up and exact `stop` | N/A | N/A | Open | N/A | N/A |
| E-5 ESP32 Touch recovery without replay | N/A | N/A | Foundation | N/A | N/A |
| WK-1 Web/iPad browser voice, response, and delivery surface | N/A | N/A | N/A | Foundation | N/A |
| T-1 TUI authorized initiation | N/A | N/A | N/A | N/A | Implemented |
| T-2 TUI honest phases and response delivery | N/A | N/A | N/A | N/A | Implemented |
| T-3 TUI bounded follow-up and exact `stop` | N/A | N/A | N/A | N/A | Implemented |
| T-4 TUI recovery without replay | N/A | N/A | N/A | N/A | Implemented |

The checked local artifacts are TUI-led and remain the historical numeric
implementation record for T-1 through T-4. The iOS audit supplies surface
evidence for I-1 through I-3. P-1 through P-4 are open. E-2 and E-5 have
display/reducer foundation, but E-1, E-3, and E-4 remain open because the
touch microphone/audio path does not exist yet. WK-1 has browser voice/display
foundation but no closed surface story; its browser capture/audio path is not
the same as passive room-display behavior.

## Epic 2 — See and trust what the room is doing

| Surface story | I | P | E | W/K | T |
|---|---|---|---|---|---|
| 2-I-1 iOS capture state and live Transcription | Implemented | N/A | N/A | N/A | N/A |
| 2-I-2 iOS disconnected/unavailable state | Implemented | N/A | N/A | N/A | N/A |
| 2-P-1 Puck local capture and response status | N/A | Open | N/A | N/A | N/A |
| 2-P-2 Puck unavailable/disconnected status | N/A | Open | N/A | N/A | N/A |
| 2-E-1 ESP32 Touch native Ambient Surface | N/A | N/A | Foundation | N/A | N/A |
| 2-E-2 ESP32 Touch active-turn and Transcription presentation | N/A | N/A | Foundation | N/A | N/A |
| 2-E-3 ESP32 Touch prompt mirror | N/A | N/A | Foundation | N/A | N/A |
| 2-E-4 ESP32 Touch disconnected/cached context | N/A | N/A | Foundation | N/A | N/A |
| 2-WK-1 W/K browser Ambient Surface | N/A | N/A | N/A | Foundation | N/A |
| 2-WK-2 W/K browser active-turn and Transcription presentation | N/A | N/A | N/A | Foundation | N/A |
| 2-WK-3 W/K browser prompt mirror | N/A | N/A | N/A | Foundation | N/A |
| 2-WK-4 W/K browser disconnected/cached context | N/A | N/A | N/A | Foundation | N/A |
| 2-T-1 TUI capture and phase participant state | N/A | N/A | N/A | N/A | Foundation |
| 2-T-2 TUI disconnected/recovery presentation | N/A | N/A | N/A | N/A | Foundation |

The display shell, shared snapshot/reducer path, and portions of the appliance
wiring already exist. They are foundations for Epic 2, not local BMad story
completion. The iOS rows cover doorway participant behavior, not room Display
mirroring. Puck rows cover its status-only doorway, not full response text.
E and W/K each own their renderer-specific Ambient, Active Turn, prompt, and
disconnected slices; their `Foundation` cells do not imply the other renderer
is complete. Passive Room Display behavior is acceptance within the applicable
renderer rows, not a separate product surface.

## Epic 3 — Control household doorway identity and access

| Surface story | I | P | E | W/K | T |
|---|---|---|---|---|---|
| 3-I-1 iOS discover and connect an unconfigured Device | Implemented | N/A | N/A | N/A | N/A |
| 3-I-2 iOS approve and configure a Device | Open | N/A | N/A | N/A | N/A |
| 3-I-3 iOS validate unique Profile-specific Wake Mappings | Open | N/A | N/A | N/A | N/A |
| 3-I-4 iOS configure deterministic wake arbitration | Open | N/A | N/A | N/A | N/A |
| 3-I-5 iOS fail closed for revoked/unavailable identity | Open | N/A | N/A | N/A | N/A |
| 3-I-6 iOS revoke and require re-enrollment | Open | N/A | N/A | N/A | N/A |
| 3-P-1 Puck discovery identity and connection boundary | N/A | Open | N/A | N/A | N/A |
| 3-P-2 Puck approved configuration and Ready boundary | N/A | Open | N/A | N/A | N/A |
| 3-P-3 Puck Wake Mapping/Profile enforcement | N/A | Open | N/A | N/A | N/A |
| 3-P-4 Puck single-winner arbitration participation | N/A | Open | N/A | N/A | N/A |
| 3-P-5 Puck revoked/unavailable identity enforcement | N/A | Open | N/A | N/A | N/A |
| 3-P-6 Puck revocation and re-enrollment boundary | N/A | Open | N/A | N/A | N/A |

The iOS repository has a completed Story 3.1 artifact, a committed typed
discovery model, deterministic tests, a Debug-only simulator fixture, and the
iOS Settings entry point. The implementation compiles, the simulator test
suite passes, and the interactive smoke evidence covers the read-only identity
boundary. The local TUI story remains `backlog`; this `Implemented` iOS cell
does not close the cross-surface Epic. iOS is the intended control plane; the
ReSpeaker is the primary affected physical Device. The Puck rows are device-
side enforcement, not a second administration surface. ESP32 Touch, W/K, and
TUI remain `N/A` under the current pilot boundary.

## Epic 4 — Know when the household needs to leave

| Surface story | I | P | E | W/K | T |
|---|---|---|---|---|---|
| 4-E-1 ESP32 Touch Departure Card promotion | N/A | N/A | Open | N/A | N/A |
| 4-E-2 ESP32 Touch Departure Card recompute and clear | N/A | N/A | Open | N/A | N/A |
| 4-WK-1 W/K browser Departure Card promotion | N/A | N/A | N/A | Open | N/A |
| 4-WK-2 W/K browser Departure Card recompute and clear | N/A | N/A | N/A | Open | N/A |

The shared `4-C-1` calendar/travel evaluator remains a prerequisite outside
the surface columns. Departure Cards are display-only: no local BMad artifact
currently closes the evaluator or either synchronized E/W/K renderer. The
product requirement is synchronized semantics, not synchronized pixels.

## Epic 5 — Carry the Hermes relationship with you

| Surface story | I | P | E | W/K | T |
|---|---|---|---|---|---|
| 5-I-1 iOS independent conversation doorway | Implemented | N/A | N/A | N/A | N/A |
| 5-T-1 TUI independent direct voice-chat gateway | N/A | N/A | N/A | N/A | Foundation |

The existing TUI is substantial and supplies the strongest pre-existing Epic 5
foundation, but `5-T-1` has not been taken through the local BMad workflow.
The sibling iOS repository identifies its conversation slice as FR20 / Epic 5 /
`5-I-1`. The implementation has its own Hermes session, typed and tap-to-speak
turns, local history, honest capture/thinking/speaking states, and audio
fallback; the iOS audit therefore records surface implementation coverage even
though this repository's local story status remains `backlog`.

## Cross-epic surface conclusion

The surface split now applies beyond Epic 1. Epic 2 has separate participant
rows for iOS, Puck, and TUI, native E renderer rows, and W/K browser renderer
rows; E/W/K remain `Foundation` while the iOS participant rows are
`Implemented`. Epic 3 separates the iOS control plane from Puck device-side
enforcement; only `3-I-1` is currently `Implemented`, and the Puck rows remain
`Open`. Epic 4 separates the shared `4-C-1` evaluator prerequisite from E and
W/K Departure Card delivery; both renderer families remain `Open`. Epic 5 is
already split into `5-I-1` and `5-T-1`, with iOS `Implemented` and TUI
`Foundation`.

These surface keys are planning and coverage identities until their owning
story artifacts are created. They do not change the formal local sprint queue,
and no implementation in one surface closes a sibling surface row.

## Current cross-surface conclusion

Epic 1 is not complete across the product surfaces. The iOS and TUI surface
stories have implementation evidence, but the Puck cells remain `Open`, the
ESP32 Touch capture/audio stories remain `Open`, and its renderer/recovery
stories remain `Foundation`. WK-1 has one shared browser voice/display
foundation but is not closed. Passive room-display behavior is a separate
role, not a second W/K or iPad surface. Neither iOS evidence nor a TUI surface
cell is permission to mark the cross-surface Epic done.

The correct sequencing is to finish the remaining TUI review/closure, then
choose among the Puck's P-1 authorization slice, the ESP32 Touch E-1 capture
slice, and WK-1's remaining browser validation according to their settled
adapter prerequisites. Their dependent delivery work follows the relevant
capture path. Epic 2 should not be treated as the next completed product Epic
until the applicable Epic 1 surface gaps are either implemented and validated
or explicitly re-scoped.

## Current local conclusion

The iOS app now has implementation coverage for Epic 1 surface stories I-1,
I-2, and I-3; Epic 2 participant stories `2-I-1` and `2-I-2`; Epic 3 story
`3-I-1`; and Epic 5 story `5-I-1`. Its Epic 3 discovery slice has completed
its iOS implementation and simulator verification, with the committed
implementation compiling and passing the current deterministic test suite.
iOS Story 1.3 is not applicable to this surface. The Python appliance/webview
has supporting coverage around authorization, state, follow-up, and browser
voice, but its W/K surface stories remain `Foundation` until their validation
gates close. The physical Puck and ESP32 Touch voice stories still have no
closed Epic 1 surface evidence. E-2/E-5 and the Epic 2 E/W/K display rows have
foundation evidence from the native display/reducer path; voice and delivery
gaps remain explicit. The local TUI tracker still owns the formal status of
its historical Stories 1.1–1.4; this workflow status is intentionally separate
from the cross-repository surface evidence.

This matrix should be revised when new implementation evidence or validation
changes. A surface cell is not a substitute for the owning repository's BMad
workflow or formal story closure.
