# Epic 1 Context: Have a reliable Hermes conversation

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give every configured Hermes doorway one honest conversation path: authorization and Profile identity are settled before capture or submission, the request crosses one normalized SessionProtocol boundary, observed response phases remain consistent, and transport failure cannot duplicate or silently resume a turn. This includes the audio-only Puck, the voice-plus-display ESP32 Touch doorway, the W/K browser voice-plus-display surface, iOS, Android, and TUI. Passive room Displays consume the same visual semantics without becoming alternate Hermes doorways.

## Stories

- Puck P-1: Authorized wake and capture.
- Puck P-2: Status and response-audio delivery.
- Puck P-3: Bounded follow-up and exact `stop`.
- Puck P-4: Recovery without replay.
- Puck P-5: Complete streamed response playback without underrun; the current promoted slice carried forward from P-2 deferred work.
- ESP32 Touch E-1 through E-5: Authorized capture, native phases and response rendering, response-audio delivery, bounded follow-up/`stop`, and recovery.
- Web/iPad WK-1: One shared browser voice-plus-display surface for authorized capture, honest phases, response text/audio, delivery/error state, and bounded hands-free recovery.
- iOS I-1 through I-3: Authorized initiation, honest phases with response/audio delivery, and fresh recovery without replay.
- Android A-1 through A-3: Feature-parity mobile initiation, honest phases with response/audio delivery, and fresh recovery without replay.
- TUI T-1 through T-5: Authorized initiation, honest phases and response delivery, bounded follow-up/`stop`, recovery, and non-blocking voice-resource teardown.

## Requirements & Constraints

- Bind each supported doorway to an authorized Hermes Profile before Puck, ESP32 Touch, or W/K capture or Hermes submission; unavailable, revoked, or unverified identity fails closed without fallback.
- Expose only observed normalized phases: `heard`, `listening`, `transcribing`, `thinking`, `buffering`, `speaking`, `complete`, and honest Disconnected State. No doorway advances or regresses before the corresponding event.
- Preserve one Active Turn per doorway, one initial submission per accepted initiation, and no automatic replay after an uncertain transport failure. Late events from an old Session cannot mutate a new one.
- Keep the Puck audio/status-only: response text and transcript history do not belong on its TFT. Raw Puck and ESP32 Touch audio remain transient on the home LAN; only deliberate iOS/Android/TUI Local History may persist by default.
- Wake-capable doorways may use a bounded wake-free follow-up window after success; exact `stop` closes local capture silently without submitting a turn. Blocking capture and playback stay outside UI event loops.
- Developer and CI validation uses fake Hermes sessions/WebSockets and local fixtures. Live text/voice smoke tests are explicit runtime checks, not fixtures.

## Technical Decisions

- Use ports and adapters with a UI-independent Python core. `client.py` owns Hermes wire normalization and typed protocol errors; `session.py` owns one connection and turn lifecycle; front ends consume `SessionProtocol` rather than parsing wire frames.
- `HermesSession` owns connection, capabilities, session identity, and active-turn facts. Presentation, drafts, queues, and optional history remain surface-local.
- Transport loss is an explicit disconnected/error transition. Bounded reconnect creates a fresh verified Session and requires fresh user initiation.
- Surface-specific audio and microphone adapters may differ, but Hermes answer authority and session semantics remain behind the owning adapter. Do not introduce a shared database, broker, transcript store, or front-end dependency into the core.

## UX & Interaction Patterns

- Show the active Profile from `heard` through completion on text-capable doorways and room displays; identity explains routing, not answer correctness.
- Use readable child-friendly phase labels with supporting color, motion, and sound. The Puck uses short local phases and cues, never full response text or a transcript archive.
- Play response audio only when it is actually available. If audio fails, preserve usable text where supported and show an unavailable-audio state; never imply `speaking` without delivery.
- Keep conversation state Room-local. Passive Displays mirror the owning Room and never capture, speak, create a second Session, or answer Hermes prompts by touch in v1.

## Cross-Story Dependencies

- Shared authorization, SessionProtocol, display-state, and bounded-audio contracts are prerequisites consumed by each surface story; evidence from one surface does not close another.
- P-5 consumes the P-1/P-2 Puck wake, capture, response-stream, and speaker foundation. P-3 follow-up and P-4 recovery remain separate Puck slices; P-6 through P-11 own bridge lifecycle, diagnostics, format, I2S, routing, and low-level output-failure concerns.
- Later room-context work consumes Epic 1 turn events and shared display semantics. Passive Displays must not create alternate sessions or authorities.
- Physical-device credentials, provisioning, revocation, and wake arbitration belong to device-administration work; Epic 1 consumes an authorized configuration and does not invent that system.
