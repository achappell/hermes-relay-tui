# Epic 1 Context: Have a reliable Hermes conversation

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Each configured doorway completes an authorized voice turn, presents the actual Hermes response and delivery state, supports its bounded continuation capability, and recovers without duplicating an uncertain request. Delivery is surface-specific: Puck, ESP32 Touch, Web/iPad, TUI, iOS, and Android each require their own evidence. Passive room mirrors do not become additional conversation owners.

## Stories

- Story I-1: Authorized iOS initiation
- Story I-2: iOS phases and response delivery
- Story I-3: iOS recovery without replay
- Story A-1: Authorized Android initiation
- Story A-2: Android phases and response delivery
- Story A-3: Android recovery without replay
- Story A-4: Android relay configuration and secure profiles
- Story A-5: Android interruption and playback stop
- Story A-6: Android continuation and echo-safe barge-in
- Story A-7: Android typed turns and normalized events
- Story A-8: Android response playback
- Story A-9: Android capture and local transcription
- Story P-1: Authorized Puck wake and capture
- Story P-2: Puck status and response audio
- Story P-3: Puck follow-up and exact stop
- Story P-4: Puck recovery without replay
- Story P-5: Continuous Puck streamed playback
- Story P-6: Puck bridge shutdown and startup coverage
- Story P-7: Opt-in bounded PCM diagnostics
- Story P-8: Deterministic ReSpeaker audio formats
- Story P-9: Fail-safe ReSpeaker I2S lifecycle
- Story P-10: Internal wake-model routing isolation
- Story P-11: Honest Puck audio-output failure
- Story E-1: Authorized Touch voice capture
- Story E-2: Native Touch phases and response rendering
- Story E-3: Touch response audio
- Story E-4: Touch follow-up and exact stop
- Story E-5: Touch recovery without replay
- Story WK-1: Shared browser voice and display
- Story WK-2: Concurrent browser session isolation
- Story T-1: Authorized TUI initiation
- Story T-2: TUI phases and response delivery
- Story T-3: TUI follow-up and exact stop
- Story T-4: TUI recovery without replay
- Story T-5: Non-blocking TUI voice teardown
- Story T-6: Idle relay-loss detection

## Requirements & Constraints

- Fix the selected Profile before capture or submission. Missing approval, revoked credentials, rejected identity, or an unverified binding must fail closed without substituting another Profile. Transport unreachability is not proof of approval or revocation.
- Allow one active turn per doorway and one submission per accepted initiation. Reject stale session/turn events; keep simultaneous doorway contexts isolated.
- Present observed capture, processing, buffering, playback, completion, and failure. Preserve completed response text if audio fails, while reporting audio unavailable. No local fallback answer may impersonate Hermes.
- Follow-up is capability-bound and finite; the Puck default is eight seconds. Exact spoken `stop`, ignoring terminal punctuation, closes local capture silently without a replacement turn. Empty capture submits nothing.
- Transport loss marks an unresolved turn uncertain. Bounded recovery verifies a fresh session and requires fresh initiation; it must not replay speech, reopen capture silently, or accept prior-session audio. Shutdown releases owned capture/playback resources without blocking UI work.
- Raw household audio and bridge transcripts are transient; recording diagnostics require bounded opt-in. Persistent Local History is an intentional client feature, never a shared-device transcript store. Credentials and content must not leak through snapshots or diagnostics.
- Pilot working targets are roughly one second to Puck acknowledgement and four seconds from end of speech to first audio. Rejected/revoked-device checks must produce zero audio payloads and turns; default recording artifacts and false-wake submissions remain zero.

## Technical Decisions

- Hermes owns sessions, generation, and response authority. Home owns household identity, authorization, and configuration. UI-independent session adapters normalize protocol events; presentation and firmware do not parse Hermes wire frames or invent protocol behavior.
- Visual state uses the shared versioned display contract. Bounded microphone/response PCM is a separate transport contract, never embedded in display JSON. Snapshot/action support alone cannot close the Touch voice stories.
- Touch uses the S3 as its sole networked, Home-bound doorway; the C6 is an offline local audio peripheral without a Home identity or Hermes session. Home binds one approved Room/Profile before capture. Begin with tap-to-talk; wake and follow-up are separate delivery work.
- The Home-side Python adapter owns Touch transcription, authorization, session lifecycle, and uncertain-turn handling. The S3 supplies capture and renders returned state/audio. Initial capture uses final transcripts; partial words remain separate work.
- Keep one receive owner per connection and explicit state ownership. Configuration, retry limits, and audio devices remain runtime concerns. A second front end must not introduce a household database or framework dependency into the shared core.
- Shared-contract changes require matching schemas, fixtures, and cross-target conformance evidence. Native mobile platform lifecycle, audio, storage, and delivery records remain in their owning repositories.

## UX & Interaction Patterns

- Make the selected Profile visible before capture and during the response. Use readable state labels; color, sound, and motion supplement text. A Puck shows status rather than transcript history; an active Touch or browser doorway renders its own response.
- Show Listening only while capture is open, Speaking only during actual playback, and persistent Unavailable/Disconnected when appropriate. Retry reconnects; it is never a disguised resend.
- Keep active conversation text Room-local and volatile. Clear shared transcripts when the interaction closes or a fresh session begins; do not rehydrate them from browser storage. Passive mirrors neither capture nor speak nor own a second session.

## Cross-Story Dependencies

- Surface completion is independent. TUI numeric Stories 1.1–1.4 remain aliases for T-1–T-4; iOS and Android rows provide context and do not transfer delivery ownership here.
- Authorization, normalized session events, visual-state semantics, and bounded audio contracts precede consuming surface slices. Touch additionally requires Home admission/ready binding and a defined C6 board, GPIO map, and local audio/control interface before physical integration.
- Device provisioning, revocation, and wake arbitration belong to device-administration work. Epic 1 consumes verified configuration rather than inventing an administration flow.
- Capture, response delivery, continuation, and recovery remain separately validated Touch/Puck capabilities. Later room-context work consumes their normalized events without creating alternate session authorities.
