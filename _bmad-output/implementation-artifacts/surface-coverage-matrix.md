---
title: Surface coverage across BMad epics
type: traceability
status: active
updated: 2026-09-09
sources:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/implementation-artifacts/sprint-status.yaml
  - _bmad-output/implementation-artifacts/epic-1-context.md
  - _bmad-output/implementation-artifacts/spec-1-1-start-an-authorized-hermes-turn.md
  - _bmad-output/implementation-artifacts/spec-1-2-render-honest-turn-phases-and-response-delivery.md
  - _bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md
  - ../hermes-relay-ios/_bmad-output/implementation-artifacts/epic-1-context.md
  - ../hermes-relay-ios/_bmad-output/implementation-artifacts/spec-1-2-render-honest-ios-turn-phases.md
  - ../hermes-relay-ios/_bmad-output/implementation-artifacts/spec-3-1-discover-unconfigured-devices.md
  - ../hermes-relay-ios/docs/plans/2026-09-09-epic-1-ios-device-validation-plan.md
  - ../hermes-relay-ios/docs/plans/2026-09-09-ios-16-hands-free-barge-in.md
---

# Surface coverage across BMad epics

This is the local BMad traceability view. It deliberately does not use GitHub
Project state. The iOS column now includes the read-only sibling-repository
audit recorded below; the local workflow status still belongs to this TUI
repository.

## Surfaces

| Code | Surface | Boundary |
|---|---|---|
| I | iOS app | Native SwiftUI conversation and device-administration client; implemented in the sibling repository. |
| P | ReSpeaker Puck | Physical wake, capture, local status, and audio doorway. |
| E | ESP32 touch display | Waveshare ESP32-S3/LVGL room display. It mirrors state; it is not a voice doorway. |
| K | iPad kiosk | Safari/Guided Access deployment of the Python/Svelte webview; not a separate renderer. |
| T | TUI | Textual terminal conversation surface. |
| W | Python/Svelte webview | Primary web display implementation: `home_display` Python host plus Svelte DOM view. The web renderer is independent of the ESP32 renderer; LVGL/WASM is optional. |

The surface relationship is therefore:

```text
Python host / DisplaySnapshot contract
             ├── Svelte DOM renderer ──► W / K (webview and iPad kiosk)
             └── native LVGL renderer ──► E (ESP32 touch display)
```

W is the implementation boundary and K is its deployment target. K still needs
its own kiosk, accessibility, and device smoke validation before it can be
called complete. E must conform semantically, but it does not need to share
the web renderer or its visual layout.

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

The local sprint tracker is authoritative for story workflow: Epic 1 is
`in-progress`; Stories 1.1–1.3 are `review`; Story 1.4 is `backlog`; Epics 2–5
and all of their stories are `backlog`.

## Rendering decision — 2026-09-09

Exact visual parity between the ESP32 touch display and the iPad/webview is
not a product requirement.

- The Python/Svelte webview is the primary web and iPad implementation.
- The ESP32 touch display may use native LVGL layout and rendering.
- Both targets must preserve the shared snapshot schema, phase semantics,
  capability rules, room ownership, and normalized actions.
- The iPad kiosk is a deployment of the Svelte webview, not a second renderer.
- LVGL/WASM remains an optional portability or parity target; it is not a
  prerequisite for the webview or iPad surface.

The migration should use the existing Svelte DOM surface where practical. Do
not remove the current WASM assets until the replacement has equivalent state,
prompt, error, reconnect, and accessibility coverage.

## iOS audit — 2026-09-09

The sibling `../hermes-relay-ios` repository was inspected read-only for the
implementation audit. Its local `main` commit is now `211787c` (`feat: discover
unconfigured household devices`), while `origin/main` remains `53b69bf`. The
Device Discovery slice is committed; its active feature checkout is one local
configuration commit ahead, with only unrelated `.gitignore` and
documentation-only `AGENTS.md` changes still uncommitted.

- The iOS Epic 1 artifacts explicitly close Stories 1.1 and 1.2, and the
  physical-device validation record says their device-only checks completed.
- The implementation and deterministic tests also cover the iOS participant
  behavior for recovery: fresh session creation, unconfirmed-turn marking,
  no automatic replay, and stale-event isolation.
- The current macOS target passes 263 XCTest cases with 0 failures, and the
  current iOS simulator target passes 265 XCTest cases with 0 failures. Story
  3.1 remains `In review` because its local BMad specification is still marked
  `in-review`; the committed implementation now compiles and passes its
  deterministic tests.
- The optional iOS hands-free slice has deterministic coverage, but its real
  device smoke is still pending. That does not block Epic 5 Story 5.1, whose
  required tap-to-speak and typed doorway behavior is already implemented.

## Epic 1 — Have a reliable Hermes conversation

| Story | Local status | I | P | E | K | T | W |
|---|---|---|---|---|---|---|---|
| 1.1 Start an authorized Hermes turn | review | Implemented | Open | N/A | N/A | Implemented | Foundation |
| 1.2 Render honest turn phases and response delivery | review | Implemented | Open | Foundation | Foundation | Implemented | Foundation |
| 1.3 Continue with bounded follow-up and exact `stop` | review | N/A | Open | N/A | N/A | Implemented | Foundation |
| 1.4 Recover without replaying an uncertain turn | backlog | Implemented | Open | Foundation | Foundation | Foundation | Foundation |

The checked local artifacts are TUI-led. Story 1.1 also preserves and tests the
Python appliance's fail-closed session guard. Story 1.3 preserves the existing
appliance coordinator path while implementing the TUI outcome gate. The iOS
audit closes the iOS portions of Stories 1.1 and 1.2 and finds recovery
implementation/test coverage for 1.4; the separate iOS device record does not
formally close 1.4. Story 1.3 remains `N/A` for iOS because the BMad story is
specifically the Puck's bounded follow-up window; iOS's opt-in hands-free slice
is a separate capability with its own pending device smoke.

## Epic 2 — See and trust what the room is doing

| Story | Local status | I | P | E | K | T | W |
|---|---|---|---|---|---|---|---|
| 2.1 Keep each Display in its Room-scoped Ambient Surface | backlog | N/A | N/A | Foundation | Foundation | N/A | Foundation |
| 2.2 Show live capture state and transcription | backlog | Implemented | Open | Foundation | Foundation | Foundation | Foundation |
| 2.3 Mirror only the owning Room's Active Turn | backlog | N/A | Open | Foundation | Foundation | N/A | Foundation |
| 2.4 Mirror Hermes prompts without becoming another assistant | backlog | N/A | Open | Foundation | Foundation | N/A | Foundation |
| 2.5 Stay useful and honest when disconnected | backlog | Implemented | Open | Foundation | Foundation | Foundation | Foundation |

The display shell, shared snapshot/reducer path, and portions of the appliance
wiring already exist. They are foundations for Epic 2, not local BMad story
completion. The primary Epic 2 implementation path is W, deployed as K, while
E remains a separate native adapter. The iOS cells cover its direct capture
state/live transcription and associated doorway disconnected state; they do
not claim room Display mirroring. Ambient photos, full room ownership behavior,
prompt mirroring, and the complete disconnected Display experience remain
unstarted in the local tracker.

## Epic 3 — Control household doorway identity and access

| Story | Local status | I | P | E | K | T | W |
|---|---|---|---|---|---|---|---|
| 3.1 Discover unconfigured Devices safely | backlog | In review | Open | N/A | N/A | N/A | N/A |
| 3.2 Approve and configure a Device | backlog | Open | Open | N/A | N/A | N/A | N/A |
| 3.3 Keep Wake Mappings unique and Profile-specific | backlog | Open | Open | N/A | N/A | N/A | N/A |
| 3.4 Select one Device for a simultaneous wake | backlog | Open | Open | N/A | N/A | N/A | N/A |
| 3.5 Fail closed for revoked or unavailable identities | backlog | Open | Open | N/A | N/A | N/A | N/A |
| 3.6 Revoke access and require verified re-enrollment | backlog | Open | Open | N/A | N/A | N/A | N/A |

The iOS repository has an in-review Story 3.1 artifact, a committed typed
discovery model, deterministic tests, and the iOS Settings entry point. The
current implementation compiles and its simulator test suite passes, but the
local story artifact remains in review, so this is not yet a formally closed
iOS surface. iOS is the intended control plane; the ReSpeaker is the primary
affected physical Device. The other four surfaces are not administration
surfaces for these stories.

## Epic 4 — Know when the household needs to leave

| Story | Local status | I | P | E | K | T | W |
|---|---|---|---|---|---|---|---|
| 4.1 Qualify events using usable travel context | backlog | N/A | N/A | Open | Open | N/A | Open |
| 4.2 Promote a household-wide Departure Card | backlog | N/A | N/A | Open | Open | N/A | Open |
| 4.3 Recompute and clear Departure Cards automatically | backlog | N/A | N/A | Open | Open | N/A | Open |

Departure Cards are display-only. No local BMad artifact currently closes the
calendar/travel evaluator or its synchronized E, K, and W states. The product
requirement is synchronized semantics, not synchronized pixels.

## Epic 5 — Carry the Hermes relationship with you

| Story | Local status | I | P | E | K | T | W |
|---|---|---|---|---|---|---|---|
| 5.1 Use iOS as an independent conversation doorway | backlog | Implemented | N/A | N/A | N/A | N/A | N/A |
| 5.2 Use the TUI as an independent direct voice-chat gateway | backlog | N/A | N/A | N/A | N/A | Foundation | N/A |

The existing TUI is substantial and supplies the strongest pre-existing Epic 5
foundation, but Story 5.2 has not been taken through the local BMad workflow.
The sibling iOS repository identifies its conversation slice as FR20 / Epic 5 /
Story 5.1. The implementation has its own Hermes session, typed and tap-to-speak
turns, local history, honest capture/thinking/speaking states, and audio
fallback; the iOS audit therefore records surface implementation coverage even
though this repository's local story status remains `backlog`.

## Current local conclusion

The iOS app now has implementation coverage for Epic 1 Stories 1.1, 1.2, and
1.4, the iOS participant path of Epic 2 Stories 2.2 and 2.5, and Epic 5 Story
5.1. Its Epic 3 Story 3.1 slice is in review, with the committed implementation
compiling and passing the current deterministic test suite. iOS Story 1.3 is
not applicable to this surface. The Python appliance/webview has supporting
coverage around
authorization, state, and follow-up, but not a completed local BMad story of its
own. The physical Puck, ESP32 display, and iPad kiosk still have no equivalent
closed surface evidence. For the display work, W/K is now the preferred
implementation path; E is the native companion target, and WASM is optional.
The local TUI tracker still leaves Epic 1.4 and all of Epics 2–5 open; that
workflow status is intentionally separate from the cross-repository iOS audit.

This matrix should be revised when new implementation evidence or validation
changes. A surface cell is not a substitute for the owning repository's BMad
workflow or formal story closure.
