# Input Reconciliation — PRD/Shared Display

## Input

`_bmad-output/planning-artifacts/prds/prd-hermes-relay-tui-2026-09-07/reconcile-shared-display.md`

## UX decisions carried forward

- ESP32-S3/LVGL and Safari/iPad Displays share the same state/action semantics for Ambient Surface, room-local Active Turn, live Transcription, Departure Card, and Disconnected State.
- A Display mirrors but never captures, speaks, or creates a second session; conversation text stays in the owning Room, while Departure Cards propagate household-wide.
- The Puck’s small status display is not a transcript surface. Active states use readable labels, supportive sound, and animation; reduced motion becomes a static readable state.

## Intentionally not duplicated or dropped

- LVGL/WASM mechanics, wire formats, reducers, wake-engine choice, proximity implementation, audio buffering, and electrical/acoustic validation remain implementation concerns.
- The native macOS simulator remains development tooling, not a household surface. Touch prompt actions, full Puck response text, and audible Departure Cards remain excluded.

## Open item / ambiguity

Room-level Immich people/exclusions and freshness, iPad kiosk authentication/offline behavior, and exact layout/token details remain open. The Night Console direction supplies the current visual anchor without changing the shared contract.
