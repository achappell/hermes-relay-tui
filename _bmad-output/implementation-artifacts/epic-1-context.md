# Epic 1 Context: Have a reliable Hermes conversation

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give every configured Hermes doorway one honest conversation path: authorization and Profile identity are settled before capture or submission, the request crosses one normalized SessionProtocol boundary, the response phases remain observable, and transport failure cannot duplicate or silently resume a turn. This is the foundation consumed by the room Display, Puck, iOS, and TUI surfaces.

## Stories

- Story 1.1: Start an authorized Hermes turn
- Story 1.2: Render honest turn phases and response delivery
- Story 1.3: Continue with bounded follow-up and exact `stop`
- Story 1.4: Recover without replaying an uncertain turn

## Requirements & Constraints

- Support an authorized Puck wake or explicit Client/TUI initiation for a selected Hermes Profile (FR1).
- Fix the selected Profile before Puck capture or Hermes submission. Unapproved, revoked, unavailable, or unverified identity must fail closed before capture and must not select a fallback.
- Expose normalized session and turn events through the shared SessionProtocol. Front ends must not parse Hermes wire frames or invent assistant responses.
- Preserve one Active Turn per doorway and one initial submission per accepted initiation. A request that may have reached Hermes is never automatically replayed.
- Surfaces expose only observed phases: `heard`, `listening`, `transcribing`, `thinking`, `buffering`, `speaking`, `complete`, and honest Disconnected State. Completed text remains available when audio is unavailable.
- Puck follow-up is bounded—eight seconds by default—and exact `stop` closes local capture silently without a replacement turn. Blocking capture/playback stays outside UI event loops.
- Credentials remain in the owning local process/profile. Raw Puck audio and shared-device transcripts are transient; only deliberate iOS/TUI Local History may persist by default.
- Developer and CI validation uses fake Hermes sessions/WebSockets and local fixtures. Live text/voice smoke testing is an explicit runtime check, not a test fixture.

## Technical Decisions

- Use ports-and-adapters with a UI-independent Python functional core. `client.py` owns Hermes hello, streamed-event normalization, typed protocol errors, and diagnostics; `session.py` owns one connection and turn lifecycle.
- `HermesSession` is the owner of connection, capabilities, session identity, and active-turn protocol facts. Drafts, queues, presentation, and optional history remain surface-local.
- Transport loss is an explicit disconnected/error transition. Reconnects are bounded and observable; verified recovery creates a fresh Hermes Session and requires fresh user initiation.
- Runtime URL, identity, Profile token, audio devices, retry limits, and timeouts remain configuration. Do not introduce a shared database, broker, transcript store, or front-end dependency into the core.

## UX & Interaction Patterns

- Show the active Profile from `heard` through completion on the Room Display and in iOS/TUI headers; identity explains routing, not answer correctness.
- Use readable child-friendly labels alongside technical phases. Color, motion, and sound support state text but never replace it. The Puck remains status-only; response text and transcript history do not belong on its TFT.
- Stream the same Hermes response text on text-capable surfaces and play audio only when audio is actually available. `Retry` reconnects only and never resembles send or replay.
- Keep conversation text and active-turn state Room-local. Displays do not capture, speak, create a second Session, or expose touch actions for Hermes prompts in v1.

## Cross-Story Dependencies

- Story 1.1 establishes the authorization, SessionProtocol, identity, and single-submission boundary that Stories 1.2–1.4 refine.
- Later Display and companion-doorway epics consume Epic 1’s normalized events and recovery semantics; they must not create alternate protocol paths.
- Physical-device credentials, provisioning, revocation, and wake arbitration belong to the separate device-administration work. This epic consumes an authorized configuration and does not invent that system.
