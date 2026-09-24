---
id: TUI-RETIRE-01
status: backlog
product_epic: 4
created: 2026-09-23
---

# TUI-RETIRE-01 — Remove legacy terminal and room-device pairing and fork integration

## Approved scope

Inventory/remove old voice-session pairing, fork adapters, config, launch scripts and docs across TUI/Puck/Touch/WK. Preserve direct Standard for TUI and current Home room admission. Record surface evidence and coordinate Home Story 9 cutover. Existing per-surface physical gates remain required.

## Acceptance

- Deliver the owner-specific behavior above using unmodified Standard Hermes and the approved [delivery contract](course-correction-2026-09-23.md).
- Preserve existing story evidence and supported adapters; no automatic mode switch or replay of an uncertain turn.
- Record applicable setup, capability limits, privacy, failure and recovery behavior against the actual supported baseline.
- Record implementation, merge and physical/live acceptance separately; do not declare an unexercised gate complete.

## Dependencies

- tui:TUI-HOME-01
- tui:TUI-STD-01
- epic:3

## Readiness

Approved backlog scope. Owning BMAD specification/readiness review must settle API details and a bounded execution plan before implementation. No implementation or runtime acceptance is claimed.
