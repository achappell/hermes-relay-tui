# Epic 5 Context: Carry the Hermes relationship with you

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Make iOS, Android, and the TUI independent, trustworthy doorways into the same Hermes relationship. Each surface owns its conversation session, presentation, recovery, and intentional local continuity while preserving shared turn-phase semantics and Hermes as the sole authority for response content. This lets a household member move between portable and terminal conversation without sessions, profiles, transcripts, or failure states bleeding across surfaces.

## Stories

- Story 5-I-1: iOS independent typed and tap-to-speak conversation doorway
- Story 5-A-1: Android independent typed and tap-to-speak conversation doorway
- Story 5-T-1: TUI independent direct voice-chat gateway

## Requirements & Constraints

- iOS and Android support typed and tap-to-speak turns; the TUI provides direct voice chat and its existing typed conversation path. Every doorway shows the active Hermes Profile before capture or submission and keeps that identity visible through completion.
- Doorways expose the observed phase sequence: `heard`, `listening`, `transcribing`, `thinking`, `buffering`, `speaking`, and `complete`. A surface may omit an unobservable phase, but must not advance early or present a later phase as though it has happened.
- Streamed response text and response audio must be the same Hermes response. No doorway may invent, summarize, or replace it with local fallback prose. If text completes but audio fails, show completed text with an unavailable-audio state rather than claiming `speaking`.
- Transport loss must become an honest disconnected state. Retry reconnects only; an unresolved turn is never replayed automatically, and verified recovery requires a fresh explicit prompt or voice initiation. Avoid duplicate active turns.
- Permission, authorization, revoked identity, or profile verification failure fails closed before capture or submission. First spoken response audio should meet the shared working target of roughly four seconds after speech ends where the surface can measure it.
- Completed Local History is intentional and surface-local: iOS and Android keep per-profile history, and the TUI may keep its own history. Raw audio is not retained by default, and Puck, Display, and Media Server state or transcripts must not be imported into a Client's history.
- Diagnostics are optional content-safe engineering detail. They must not expose prompts, responses, audio, or bearer credentials, and must not be required for the ordinary conversation journey.

## Technical Decisions

Use ports-and-adapters: Hermes owns model, profile, response, and speech authority; each doorway owns its platform lifecycle, permissions, audio, presentation, and local state. Native iOS and Android remain separate repositories and independently deployable Clients; the TUI remains a separate terminal doorway. No shared database, broker, or cross-front-end transcript store is introduced.

All surfaces consume normalized Hermes session and turn events through typed adapters. Presentation code does not parse Hermes wire frames, invent unsupported operations, or decide replay policy. Reconnect creates a fresh Hermes Session, and a turn that may have reached Hermes is never automatically resubmitted. Mobile credentials are profile-bound and stored in platform-secure storage; credentials and Local History are not shared between mobile Clients or with the TUI.

## UX & Interaction Patterns

The TUI follows terminal conventions: its header shows the active Profile, its conversation surface renders streamed response text inline as one coherent response, and its phase labels use the shared vocabulary. Recovery actions have keyboard equivalents. Diagnostics remain available as an engineering view rather than taking over the conversation surface. Mobile Clients use native navigation and controls while preserving the same phase, identity, response, audio-status, and recovery meaning.

## Cross-Story Dependencies

Epic 5 consumes Epic 1's normalized session, turn, response-audio, and recovery semantics; that dependency is a prerequisite, not a hidden shared doorway story. The iOS, Android, and TUI Sessions and histories must remain isolated when multiple doorways are active simultaneously. `5-A-1` is a separate delivery identity from `5-I-1`; implementation or closure on one mobile surface is evidence only, never closure of the other.
