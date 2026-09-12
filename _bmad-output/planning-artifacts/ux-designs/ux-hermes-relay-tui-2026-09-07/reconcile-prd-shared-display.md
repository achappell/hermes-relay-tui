# Input Reconciliation — PRD/Shared Display

## Input

`_bmad-output/planning-artifacts/prds/prd-hermes-relay-tui-2026-09-07/reconcile-shared-display.md`

## UX decisions carried forward

- ESP32-S3/LVGL and Safari/iPad Displays share the same state/action semantics for Ambient Surface, room-local Active Turn, live Transcription, Departure Card, and Disconnected State.
- A passive Display mirrors but never captures, speaks, submits a choice, or creates a second session; the active ESP32 Touch, direct-use W/K, and TUI surfaces may submit the approved typed choice operations while conversation text stays in the owning Room, and Departure Cards propagate household-wide.
- The Puck’s small status display is not a transcript surface. Active states use readable labels, supportive sound, and animation; reduced motion becomes a static readable state.

## Intentionally not duplicated or dropped

- LVGL/WASM mechanics, wire formats, reducers, wake-engine choice, proximity implementation, audio buffering, exact typed-choice schema, and electrical/acoustic validation remain implementation concerns.
- The native macOS simulator remains development tooling, not a household surface. Arbitrary Hermes-authored UI, passive/Puck choice actions, consequence-bearing commits before policy/confirmation, full Puck response text, and audible Departure Cards remain excluded.

## Open item / ambiguity

Room-level Immich people/exclusions and freshness, iPad kiosk authentication/offline behavior, and exact layout/token details remain open. The Night Console direction supplies the current visual anchor without changing the shared contract.
