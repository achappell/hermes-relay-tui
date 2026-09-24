# Epic 1 Context: Connect personal clients through HomeBridge

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Make TUI, iOS, macOS and Android usable personal conversation clients through HomeBridge: enroll normally, receive approved Profile access, start and resume conversations, and recover honestly. Existing completed stories retain their evidenced scope; new pairing and session acceptance still needs implementation. This is the first epic in the approved nine-epic delivery order, which supersedes historical epic numbering.

## Stories

- Story SPEC-home-service-foundation: Build the durable Home service foundation
- Story HOME-NW-01: Pin and prove the Standard Hermes compatibility boundary
- Story HOME-NW-02: Pair endpoints with QR enrollment and limited credentials
- Story HOME-NW-03: Serve the versioned Home bridge over one approved local route
- Story HOME-NW-04: Add approved-route roaming and same-household identity proof
- Story HOME-NW-17: Pair personal clients from a Home page and admit their direct conversations
- Story STD-3: Migrate the terminal client to the Standard Home boundary
- Story T-1: Authorized initiation
- Story T-2: Honest phases and response delivery
- Story T-3: Bounded follow-up and exact `stop`
- Story T-4: Recovery without replay
- Story T-5: Non-blocking wake-listener and microphone teardown during recovery, reload, disarm, and quit
- Story T-6: Detect idle relay loss and present honest recovery without replaying an uncertain turn
- Story 2-T-1: Keep the direct TUI doorway's capture and phase state visible while a Room Display may mirror separately
- Story 2-T-2: Keep TUI disconnect/recovery presentation honest without replaying an uncertain turn
- Story 5-T-1: Use the TUI as an independent direct voice-chat gateway with inline response rendering, diagnostics, and deliberate local history
- Story TUI-HOME-01: Pair with Home and own the session lifecycle
- Story TUI-DEFECT-102: Resolve first-turn wake failure
- Story TUI-DEFECT-104: Resolve truncated microphone capture
- Story 1-I-1: Start an authorized Hermes turn
- Story 1-I-2: Render honest iOS turn phases and response delivery
- Story 1-I-3: Recover without replaying an uncertain iOS turn
- Story 2-I-1: Show iOS capture acknowledgement and live transcription
- Story 2-I-2: Show honest iOS disconnected or unavailable state
- Story 5-I-1: Use iOS as an independent conversation doorway
- Story IOS-UX-F1: Make unavailable and unconfigured states lead with the usable action
- Story IOS-UX-F2: Reconcile the live session after deleting the selected profile
- Story IOS-UX-F3: Replace configuration save-banner validation with field-level guidance
- Story IOS-DESIGN-F1: Run a deliberate visual design pass across the iOS doorway
- Story IOS-BRAND-F1: Create and wire the Hermes Relay app icon set
- Story STD-4: Migrate the Apple client to the Standard Home boundary
- Story IOS-HOME-02: Pair iOS and macOS personal clients with Home and manage sessions
- Story 1-A-1: Start an authorized typed or tap-to-speak Hermes turn
- Story 1-A-2: Render honest phases with response text and audio delivery
- Story 1-A-3: Recover without replaying an uncertain turn
- Story 1-A-4: Configure the relay with Keystore credentials and live transport
- Story 1-A-5: Interrupt an active Android turn
- Story 1-A-6: Continue hands-free capture with echo-safe barge-in
- Story 1-A-7: Deliver typed turns through normalized events
- Story 1-A-8: Play streamed response audio
- Story 1-A-9: Capture microphone input and transcribe on device
- Story 2-A-1: Show Android capture acknowledgement and live transcription
- Story 2-A-2: Show honest Android disconnected or unavailable state
- Story 5-A-1: Use Android as an independent conversation doorway
- Story 5-A-2: Preserve accessibility order and focus restoration
- Story 5-A-3: Apply the Night Console visual language as a Material 3 adaptation
- Story 5-A-4: Migrate Android from the fork route to the Home bridge
- Story 5-A-4-LIVE-HOME-GATE: Prove Android against the live Home bridge
- Story ANDROID-HOME-02: Pair the Android personal client with Home and manage sessions

## Requirements & Constraints

- Both HomeBridge and clients depend on unmodified Standard Hermes through supported interfaces. Never require a fork endpoint, agent patch or custom agent protocol. Unsupported optional capabilities are explicitly unavailable; unsupported required capabilities need a scope decision.
- Personal clients require typed input, streamed replies, microphone input, spoken responses, supported stop, intentional local history and recovery without replay. Existing privacy and opt-in rules govern history.
- Normal Home setup must not require manually supplied credentials or conversation handles. Home owns enrollment, Profile grants, renewal and revocation; clients retain only their scoped credentials.
- No Room, wake mapping or acoustic arbitration is required for personal-client admission. Room device setup remains separate.
- Diagnostics must be bounded and content-safe. Credentials must not enter ordinary logs or history. Keep connection credentials and local history scoped to mode, Home/endpoint and identity.
- Timing-dependent highlighting and advanced prompt UI are later work. Unsupported prompts must visibly decline, cancel where supported, or report/end the blocked turn; never silently approve, expose protected input in chat or pretend progress remains possible.

## Technical Decisions

- HomeBridge connects to Standard Hermes and owns household authorization. Endpoint clients consume Home's supported contract rather than taking over its policy or receiving upstream secrets.
- Reuse existing Home credential machinery. Pairings are keyed per Home. Shared Profiles may be approved by the administrator; owned Profiles require owner approval, with the recorded first-client administrator bootstrap.
- Home exposes scoped session references for approved Profiles, including authorized conversations started on other devices. A session held by another active claim is busy, not simultaneously controllable.
- Personal-client claim defaults are eight active claims per device and 120 seconds of reconnect grace, configurable by Home. Closing a client releases its claim; claim expiry does not delete its Standard session. Pausing alone does not end a personal conversation.
- Reconnect attempts continuity of the existing conversation. Never retransmit a turn whose delivery is uncertain. Recovered history is display content, never submission input.
- HomeBridge and direct Standard are explicit separate setup modes. Home failure leaves Home disconnected; it must not trigger a mode switch or fallback suggestion. Direct Standard setup belongs to Epic 2.

## UX & Interaction Patterns

- The authenticated Home page supplies a QR/copyable link or short code plus Home address. The personal client requests enrollment, displays a confirmation code and waits for identity verification and Profile approval. It then stores and renews its credential without operator intervention.
- Expose deliberate New and Resume actions. TUI launches a new conversation by default unless the user explicitly chooses continue/resume. Keep the selected Profile and connection identity clear.
- Report busy, revoked, unavailable and continuity failures honestly with actionable recovery. Retry means reconnect, not repeat submission. When continuity cannot be restored, offer a deliberate new conversation and retain the uncertain outcome visibly.
- Changing mode, Home or Profile requires resolving or explicitly leaving active/uncertain work. Permitted old history remains viewable under its original identity; do not transfer transcripts, credentials or references automatically.
- Follow terminal conventions and shared phase vocabulary. Represent text and audio progress honestly when speech timing is unavailable.

## Cross-Story Dependencies

- HOME-NW-01 through HOME-NW-04 supply compatibility, enrollment credentials, bridge routing and Home identity foundations. HOME-NW-17 supplies the personal-client enrollment and session contract consumed by TUI-HOME-01, IOS-HOME-02 and ANDROID-HOME-02.
- TUI-HOME-01 extends the existing terminal conversation and Standard adapter work; wake, microphone teardown and capture defects remain separately tracked requirements.
- Epic 2 adds reduced direct Standard setup. Epic 3 owns room-device admission. Epic 4 owns legacy removal and live cutover after replacement acceptance; do not recreate legacy rollback as a supported dependency.
