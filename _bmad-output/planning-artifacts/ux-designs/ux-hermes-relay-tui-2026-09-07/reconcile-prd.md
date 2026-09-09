# Input Reconciliation — Product Requirements Document

## Input

`_bmad-output/planning-artifacts/prds/prd-hermes-relay-tui-2026-09-07/prd.md`

## UX decisions carried forward

- UJ-1 through UJ-6 establish the surface map: shared Puck/Display conversation, iOS administration and history, TUI conversation, and household-wide visual Departure Cards.
- FR-1 through FR-6 become the conversation contract: profile known before capture, live transcription, truthful heard/listening/transcribing/thinking/buffering/speaking/complete/disconnected states, aligned text and audio, bounded follow-up, and fresh sessions after reconnect.
- FR-7 through FR-19 carry the privacy and recovery behavior: unique mappings, fail-closed unavailable profiles, one closest winner, room-local mirroring, inert unapproved Devices, guided setup, revocation, and verified recovery without a silent turn.
- The UX decisions make those states readable and animated for children, use a local sound plus visible status for unavailable profiles, show the active profile in Display/iOS/TUI headers, and make Retry reconnect-only.

## Intentionally not duplicated or dropped

- PRD identifiers, glossary definitions, test metrics, and requirement prose remain authoritative upstream; this file records their UX handoff rather than restating them.
- Wire formats, reducer mechanics, credential algorithms, proximity signals, audio buffering, and hardware validation stay out of the UX spine. No user-visible requirement or explicit non-goal was dropped.

## Open item / ambiguity

The PRD’s seven phase-gated questions remain open: proximity, offline configuration, credentials, Media Server transport, Immich filters, calendar freshness, and future barge-in qualification. Exact iOS profile-switching/mapping behavior and some accessibility/platform details still need downstream closure.
