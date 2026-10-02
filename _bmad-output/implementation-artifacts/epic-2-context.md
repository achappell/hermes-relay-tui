# Epic 2 Context: Use personal clients with Standard Hermes alone

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Epic 2 lets a personal client connect directly to unmodified Standard Hermes without HomeBridge, using only the connection, authentication, session, and response features verified for its supported upstream baseline. In the approved nine-epic plan, Epic 2 is “Use personal clients with Standard Hermes alone”; the imported planning file’s older room-display Epic 2 is historical, not the active parent. The local story index assigns TUI-STD-01 here, while historical numeric story prefixes remain stable aliases rather than current epic assignments.

## Stories

- Story TUI-STD-01: Offer explicit Standard-only terminal setup

## Requirements & Constraints

- Standard Hermes means an unmodified upstream agent at a recorded supported release or commit, using its supported configuration and interfaces. Do not require an agent patch, fork-only endpoint, or custom protocol extension.
- Standard mode must connect without HomeBridge pairing or Home credentials, using Standard’s supported authentication. Required personal-client behavior includes typed conversation and streamed response text. Microphone input and spoken responses are optional for the initial reduced release and may be offered only when verified for both the TUI and upstream baseline.
- Offer only capabilities verified for this TUI and baseline. Direct mode does not provide Home Profile grants, room-session access, or cross-device history. Missing optional listing or resume support must be reported truthfully; basic text conversation remains available.
- Keep history intentional and scoped to the direct connection and identity under the existing privacy rules. Do not carry credentials, session references, or transcripts into another mode or endpoint automatically.
- A new TUI launch starts a new session by default; continuing or resuming is deliberate. Reconnect recovers the existing conversation. If continuity cannot be established, say so and offer a deliberate new conversation. Never resend a turn that may have reached Hermes.
- Local stop always applies to enabled capture and playback. Offer remote interruption only when the supported channel advertises and verifies it. Unsupported prompts or interactions must end, cancel through a supported operation, or report the block visibly and safely; never silently approve, leak protected input into ordinary chat, or leave the turn appearing usable.
- Record setup, capability limits, privacy, failure, and recovery against the actual unmodified baseline. A client control or fake-server test alone does not prove upstream support. Detailed execution/API decisions and a bounded plan remain a readiness gate before implementation.

## Technical Decisions

- Reuse the verified direct adapter from STD-3 and preserve the normalized session/event contract. Hermes wire parsing and supported operations stay behind the client/session adapter; Textual presentation must not invent frames or Hermes behavior.
- Keep Standard and HomeBridge endpoint/auth configuration separate in appropriate local storage. Secrets must not enter ordinary logs or history. Treat the Standard endpoint, identity, credential source, and supported capabilities as connection-specific runtime state.
- Keep session ownership and history bound to the selected mode, endpoint, and identity. Before changing any of them, resolve or explicitly leave an active or uncertain conversation; switching modes never implies that a session continues there.

## UX & Interaction Patterns

Present HomeBridge and Standard Hermes as an explicit setup choice and keep the selected mode visible in connection settings. Standard setup asks only for the supported direct connection and authentication details; it must not request a Home pairing code or Home credential. Explain unavailable features without offering controls that cannot work. A HomeBridge outage remains a disconnected HomeBridge connection, with no automatic switch or fallback suggestion. Mode changes are deliberate settings actions, and recovery controls reconnect only; they never resemble replay or send.

## Cross-Story Dependencies

- The local story index lists TUI-HOME-01 as the formal dependency. TUI-STD-01 also reuses STD-3’s verified direct adapter; retain that adapter’s session contract and evidence.
- This repository’s current Epic 2 delivery is TUI-STD-01. Other clients’ direct Standard setup remains owned by their respective repositories.
