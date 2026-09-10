---
title: "Hermes Home Assistant Platform"
status: final
created: 2026-09-07
updated: 2026-09-10
---

# PRD: Hermes Home Assistant Platform

## 0. Document Purpose

This PRD turns the finalized product brief into testable product behavior for the private household pilot and its downstream UX, architecture, and implementation work. It uses journey-led discovery, a stable glossary, globally numbered functional requirements, cross-cutting quality constraints, explicit non-goals, and measurable success criteria. The source brief and its decision addendum remain at `../briefs/brief-hermes-relay-tui-2026-09-07/`.

## 1. Vision

The household can reach its chosen Hermes voice profile from the room without a phone or terminal. A device makes each phase legible—heard, listening, transcribing, thinking, buffering, and responding—so the household knows what happened instead of guessing whether the system heard them.

The private pilot proves this through a kitchen dinner question: Missy remains the response authority, the media-server handles transcription where the selected voice path requires it, and the active room device makes the exchange audible and visible without becoming a second assistant.

## 2. Target User

### 2.1 Jobs To Be Done

- Ask the household’s chosen Hermes voice profile a natural question from the room and know whether it heard, understood, and answered.
- See the active conversation state without needing to hold a phone or inspect a terminal.
- Add, configure, disconnect, and re-enroll physical household doorways without editing files.
- See useful household context—photos and imminent departures—without summoning the assistant.
- Reach the same Hermes relationship from iOS or the TUI when a portable or terminal doorway is more convenient.

### 2.2 Non-Users (v1)

- People expecting a commercial Google Home replacement with vendor-cloud compatibility.
- People needing a general smart-home ecosystem, local large-model inference, or public multi-household provisioning.
- Household members who require unsolicited audible calendar announcements; v1 keeps departure context visual-only.

### 2.3 Key User Journeys

#### UJ-1. Amanda asks Missy what is for dinner in the kitchen

- **Persona + context:** Amanda is in the kitchen and wants the current dinner plan without reaching for her phone or opening the TUI.
- **Entry state:** The room Puck is idle and connected to the Media Server and Hermes. Amanda says, “Hey Missy.”
- **Path:**
  1. The Puck acknowledges the wake and the Display shows the Listening Turn Phase.
  2. Amanda speaks her question; the Display shows Transcription live as words arrive.
  3. The Display shows the Thinking Turn Phase while Hermes determines the answer.
  4. The Display may show the Buffering Turn Phase while Missy’s response audio is preparing.
  5. Missy responds with voice while the Display streams the response text explaining the dinner plan and leaves the completed answer visible.
- **Climax:** Amanda sees the dinner answer in the room and hears Missy respond with the same answer, making the household plan available without another surface.
- **Resolution:** The response is complete and the device returns to its normal post-response state, including the bounded follow-up window.
- **Edge case:** If the Media Server or Hermes connection is unavailable, the Display shows Disconnected State and the Puck shows a local visual indicator. The Puck must not capture speech, pretend to have heard, answer as Missy, or speak a local fallback phrase.

#### UJ-1A. Amanda asks Missy through the ESP32 touch Display

- **Persona + context:** Amanda is near the configured Waveshare ESP32-S3/LVGL touch unit and starts its supported voice capture without using the Puck.
- **Entry state:** The touch unit has a verified authorized Profile and an available bounded microphone/audio path.
- **Path:** The touch unit captures voice, renders `heard`/`listening`/`transcribing`, shows the streamed Hermes response in its native LVGL console, and plays the corresponding response audio. A passive Room Display may mirror the state but never opens a second capture path.
- **Resolution:** The touch unit leaves the completed response visible, reports unavailable audio if playback fails, and enters only a configured bounded follow-up path.
- **Edge case:** If authorization, transport, or audio is unavailable, the touch unit fails closed before capture/playback or shows an honest unavailable state. It never replays an uncertain turn.

#### UJ-2. Amanda adds a new puck from iOS Settings

- **Persona + context:** Amanda has powered on a new Puck and wants to bring it into the household without editing configuration files.
- **Entry state:** Amanda is in the iOS app’s Settings and taps an Add button.
- **Path:**
  1. iOS shows a Device-discovery list, and the new Puck appears in it.
  2. Amanda taps the Puck.
  3. iOS shows a connecting state while the Puck remains visibly in its unconfigured setup state.
  4. When the connection succeeds, the iOS Client shows success and the Puck changes its visual state to connected.
  5. iOS immediately continues into guided setup for the device instead of returning Amanda to the unconfigured device list.
  6. Guided setup asks for the room first, then collects one or more wake-word/profile mappings, and ends with a ready confirmation.
- **Climax:** Both surfaces agree that the device connection succeeded; Amanda does not have to infer success from a silent list update.
- **Resolution:** Guided setup collects the room and wake-word/profile configuration before the device becomes an active household doorway.
- **Edge case:** A discovered Device that has not been approved and configured remains inert and cannot capture or access Hermes.

#### UJ-3. Amanda disconnects an approved puck

- **Persona + context:** Amanda wants to remove an approved Puck from household access while the physical Device may still be powered on.
- **Entry state:** Amanda opens the iOS Device list and taps the Puck.
- **Path:**
  1. iOS shows the Puck’s Device details.
  2. Amanda taps **Disconnect**.
  3. iOS asks for confirmation and explains that the Puck will stop working until it is re-enrolled.
  4. Amanda confirms; iOS revokes the Puck’s individual Device access rather than merely closing its current connection.
- **Climax:** The Device is no longer an authorized Hermes doorway, even if it remains physically powered and reachable on the LAN.
- **Resolution:** iOS shows the Device as disconnected/revoked; the Puck shows Disconnected State and cannot wake, capture, or submit a turn until it is explicitly re-enrolled.

#### UJ-4. The household prepares to leave for a calendar event

- **Persona + context:** Amanda or another household member is near a Display showing its normal Ambient Surface; a shared family-calendar event with a location is approaching its effective departure threshold.
- **Entry state:** All Displays are on the Ambient Surface. The event has a usable live route or configured travel estimate from the household home.
- **Path:**
  1. The event crosses its household default or event-specific departure threshold.
  2. Every Display replaces the Ambient Surface with a Departure Card.
  3. The Departure Card shows the event name, location, calculated departure time, and a countdown to leaving time.
  4. If the event time or location changes, every Display recomputes the Departure Card; if the event is cancelled, every Display clears it.
- **Climax:** The household can see when it needs to leave and where it is going without asking the assistant.
- **Resolution:** When the event starts, the Departure Card clears automatically and Displays return to the Ambient Surface. The card remains visual-only in v1.
- **Edge case:** An event without a usable route or configured travel estimate remains ordinary calendar context and does not produce a fabricated countdown.

#### UJ-5. Amanda updates Missy from the iOS doorway

- **Persona + context:** Amanda is using the iOS app and wants to tell Missy that a household event has been cancelled.
- **Entry state:** The iOS Client conversation is available and ready for a voice turn.
- **Path:**
  1. Amanda taps to speak.
  2. The app shows a listening indicator while she says that the event is cancelled.
  3. The app shows thinking while Hermes processes the request.
  4. The app shows speaking while Missy responds.
  5. Amanda hears Missy’s voice and sees the conversation transcript.
- **Climax:** Amanda receives Missy’s spoken response and can see the same exchange in the conversation.
- **Resolution:** The conversation remains available in iOS Local History for continuity.

#### UJ-6. Amanda reaches Missy through the TUI

- **Persona + context:** Amanda is at a terminal and wants another direct voice-chat doorway to Missy.
- **Entry state:** The TUI is connected to its Hermes Session.
- **Path:** Amanda starts a voice turn from the TUI, speaks to Missy, and watches the TUI show the conversation and response state.
- **Climax:** Missy responds through the same Hermes relationship without the TUI inventing a separate assistant behavior.
- **Resolution:** The TUI remains a conversation surface. Diagnostic detail exists as an engineering capability but is not yet a validated household user journey.

## 3. Glossary

- **Device** — A physical household endpoint managed by iOS. A Device is either a Puck or a Display and has its own Device Credential.
- **Puck** — The ESP32-based room voice Device without a touch display. It detects a Wake Mapping, captures speech, and plays Hermes audio; its small TFT is status-only.
- **Display** — A room visual Device that renders the Ambient Surface, Active Turn state, live Transcription, response text, and Departure Card. The Waveshare ESP32 Touch Display is also a voice-capable doorway: it can capture speech, own a Hermes Session, render the response, and play Hermes audio.
- **Web/iPad Voice Surface** — One browser voice-plus-display surface, implemented by the Python/Svelte webview and deployed to iPad through Safari/Guided Access. It is not a separate iPad renderer.
- **Passive Room Display** — A display-only target that mirrors the active doorway's room-local state without capturing, speaking, or creating a second Hermes Session. This is a role a Display can take when it is not the active voice doorway; it does not describe the ESP32 Touch or W/K voice surfaces when their voice capability is enabled.
- **Client** — A software doorway, currently iOS or TUI, that can create an Hermes Session without being a physical Device.
- **Room** — A named household location that binds Devices to presentation policy and room-local Active Turn mirroring.
- **Wake Mapping** — One unique wake phrase mapped to one Hermes Profile on a Device.
- **Hermes Profile** — The configured Hermes identity and authorized context selected by a Wake Mapping or Client configuration. Missy is one Hermes Profile.
- **Hermes Session** — The conversation session owned by one doorway. A reconnect starts a new Hermes Session.
- **Media Server** — The trusted home-LAN service that may transcribe captured Puck or ESP32 Touch audio before the transcript reaches Hermes.
- **Transcription** — The text representation of captured speech produced while a Puck, ESP32 Touch Display, or Client is listening.
- **Device Credential** — The individually revocable credential that authorizes one Device; it is never shared by multiple Devices.
- **Active Turn** — One user request and its Hermes response, including listening, transcription, thinking, buffering, speaking, and completion states.
- **Turn Phase** — One of the user-visible Active Turn states: heard, listening, transcribing, thinking, buffering, speaking, complete, or Disconnected State.
- **Ambient Surface** — The normal Display state, initially Immich photos filtered by Room policy.
- **Departure Card** — The visual calendar state showing event name, location, departure time, and countdown when a qualifying event is actionable.
- **Local History** — Conversation history retained intentionally by iOS or the TUI; Puck, Display, and Media Server do not create a transcript archive by default.
- **Disconnected State** — The honest local state shown when a Device cannot use the Hermes path; it is visual-only in v1.

## 4. Features

### 4.1 Voice doorway and Hermes session

**Description:** A Puck, ESP32 Touch Display, enabled W/K browser voice surface, or Client gives the household a direct doorway to a selected Hermes Profile. The doorway makes the Active Turn visible and audible without inventing a second assistant. A passive Room Display may mirror that turn. This feature realizes UJ-1, UJ-5, and UJ-6.

**Functional Requirements:**

#### FR-1: Start an Active Turn

A Puck, configured ESP32 Touch Display, or enabled W/K browser voice surface can accept its supported voice initiation, and an iOS Client or TUI can accept an explicit user-initiated turn when its Device Credential or Client configuration is authorized.

**Consequences (testable):**
- The selected Hermes Profile is known before Puck or ESP32 Touch audio is captured or submitted.
- An unauthorized, revoked, or unavailable mapping cannot start an Active Turn.

#### FR-2: Show live capture state and Transcription

The active Puck, ESP32 Touch Display, or W/K browser voice surface shows its local capture acknowledgement, while a passive Room Display mirrors the Listening Turn Phase and live Transcription for the owning Room. iOS and TUI show their own corresponding capture state.

**Consequences (testable):**
- Live Transcription updates as words arrive rather than appearing only after capture ends.
- The Listening state remains visible until capture ends or is cancelled.

#### FR-3: Show honest turn phases

Each supported doorway exposes the appropriate Turn Phase—heard, listening, transcribing, thinking, buffering, speaking, complete, or Disconnected State—without presenting a later phase early.

**Consequences (testable):**
- A response cannot appear complete while Hermes audio is still pending or playing.
- A disconnected doorway cannot show an indefinite thinking state.

#### FR-4: Deliver the Hermes response multimodally

The Puck, ESP32 Touch Display, W/K browser voice surface, or iOS Client speaks the Hermes response. The active ESP32 Touch and W/K surfaces render their own streamed response text, while a passive room Display may stream the same room-local response before leaving the completed answer visible. The TUI renders the conversation through its terminal surface.

**Consequences (testable):**
- The spoken and displayed response come from the same Hermes response and remain aligned while text streams.
- No Client paraphrases or replaces a Hermes response with local fallback prose.

#### FR-5: Continue a bounded conversation

After each response, a voice doorway that supports follow-up enters its configured bounded window; the Puck's v1 window is eight seconds without requiring another Wake Mapping, and the W/K browser voice surface uses its advertised bounded capability. Saying exactly “stop” during capture or follow-up closes the local window silently.

**Consequences (testable):**
- “stop” creates no replacement Hermes turn.
- The Puck returns to Wake Mapping detection after the follow-up window expires.

#### FR-6: Start a clean Hermes Session after reconnect

When a doorway reconnects after transport loss, it starts a fresh Hermes Session and does not replay or silently resume the prior Active Turn.

**Consequences (testable):**
- The next user request requires a fresh wake or explicit initiation.
- A reconnect never submits an old captured request automatically.

### 4.2 Device identity, profile routing, and arbitration

**Description:** Physical Devices are individually authorized and can host multiple explicit Wake Mappings. Profile selection is a privacy boundary. When several Devices hear the same phrase, one Device owns the Active Turn. This feature realizes UJ-1, UJ-2, and UJ-3.

**Functional Requirements:**

#### FR-7: Enforce unique Wake Mappings

The household configuration can assign multiple Wake Mappings to one Device, but each wake phrase maps to exactly one Hermes Profile.

**Consequences (testable):**
- Configuration rejects duplicate or ambiguous phrases before publishing them to a Device.
- The selected Hermes Profile is fixed before capture begins.

#### FR-8: Fail closed for unavailable identity

When a Wake Mapping points to a revoked or unavailable Hermes Profile, the Device shows Disconnected State and captures no audio for that mapping.

**Consequences (testable):**
- No audio payload or Hermes turn is produced.
- The Device does not fall back to another Hermes Profile.

#### FR-9: Select one Device for a wake

When multiple authorized Devices hear a Wake Mapping, the system selects the closest Device; an effective proximity tie is resolved by configured Device priority.

**Consequences (testable):**
- Only the selected Device acknowledges, captures, and answers.
- Losing Devices stay silent and create no duplicate Active Turn.

### 4.3 Room Display and Ambient Surface

**Description:** A passive Display provides calm room context when idle and mirrors the Active Turn only in the Room that owns the selected doorway. An ESP32 Touch Display may itself be the active voice doorway; its conversation behavior is owned by the Epic 1 touch surface stories. This feature realizes UJ-1 and UJ-4.

**Functional Requirements:**

#### FR-10: Render the Ambient Surface

A Display shows Immich photos selected by its Room-level face filters while no higher-priority household state is active.

**Consequences (testable):**
- A Room with no matching photos shows a neutral ambient background.
- The Display does not widen filters or expose a setup prompt merely because no photo matches.

#### FR-11: Mirror a room-local Active Turn

The passive Display bound to the selected doorway's Room renders live Transcription, turn phases, and response text for that Active Turn without capturing audio, speaking, or creating a second Hermes Session. An ESP32 Touch Display or enabled W/K browser voice surface that is the selected doorway is exempt from the passive-mirror boundary: it captures, speaks, and owns its Epic 1 doorway contract.

**Consequences (testable):**
- Other Displays do not receive conversation text from the Active Turn.
- A Display can return to its Ambient Surface after the Active Turn completes.

#### FR-12: Show Disconnected State honestly

A Display shows a persistent visual Disconnected State when the Media Server or Hermes connection is unavailable and continues to show cached Ambient Surface or cached Departure Card content when available.

**Consequences (testable):**
- The Display does not show an indefinite thinking state after transport loss.
- Disconnected State is visual-only in v1; no local spoken status phrase is played.

### 4.4 Household calendar Departure Card

**Description:** The shared family calendar can promote a visual Departure Card to every Display. Events are evaluated independently using the household home, route duration, family buffer, and effective threshold. This feature realizes UJ-4.

**Functional Requirements:**

#### FR-13: Qualify calendar events

The system can qualify an event for a Departure Card only when it has a location and a usable live route or configured travel estimate from the household home.

**Consequences (testable):**
- An event with no usable route or estimate remains ordinary calendar context and produces no countdown.
- A configured estimate is visibly labeled estimated when used instead of a live route.

#### FR-14: Promote a shared Departure Card

When a qualifying event crosses its effective threshold, every Display replaces its Ambient Surface with the same Departure Card containing event name, location, calculated departure time, and countdown.

**Consequences (testable):**
- The household default threshold applies when the event has no override.
- An event-level threshold override affects that event without changing other events.
- The Departure Card is visual-only and does not trigger an unsolicited Puck announcement.

#### FR-15: Maintain and clear the Departure Card

The system updates the Departure Card when event time or location changes, clears it when the event is cancelled, and returns Displays to the Ambient Surface when the event starts.

**Consequences (testable):**
- Every Display receives the same recomputed or cleared state.
- No manual dismissal is required after event start.

### 4.5 Device administration and recovery

**Description:** iOS is the sole physical-Device control plane. Setup gives immediate feedback on both iOS and the Device, then walks the user through Room and Wake Mapping configuration. This feature realizes UJ-2 and UJ-3.

**Functional Requirements:**

#### FR-16: Discover and connect a Device

From iOS Settings, Amanda can tap Add, see an unconfigured Device in a discovery list, select it, and see a connecting state followed by success indicators on both iOS and the Device.

**Consequences (testable):**
- A discovered Device remains inert before approval.
- Connection success is visible on both surfaces and does not depend on a silent list update.

#### FR-17: Guide initial Device setup

After connection success, iOS immediately guides Amanda through Room assignment, one or more Wake Mappings, and a final ready confirmation.

**Consequences (testable):**
- The Device cannot become an active household doorway before setup completes.
- The setup order is Room, Wake Mappings, then ready confirmation.

#### FR-18: Revoke a Device

From Device details, Amanda can tap Disconnect, confirm the consequence, and revoke the Device Credential and Hermes access for that Device.

**Consequences (testable):**
- Confirmation explains that the Device stops working until re-enrolled.
- Revocation prevents wake, capture, and Hermes submission even while the Device remains powered.
- Re-enrollment is required to restore access.

#### FR-19: Recover without a silent turn

When the Hermes path returns, an authorized Device reconnects automatically and clears Disconnected State only after verified recovery; it does not reopen capture or submit a pending turn.

**Consequences (testable):**
- Recovery requires a fresh Wake Mapping or explicit initiation.
- A failed recovery remains visibly disconnected.

### 4.6 iOS and TUI companion doorways

**Description:** iOS and the TUI are independent Hermes doorways. iOS supports typed and tap-to-speak conversation plus Local History. The TUI currently serves as another direct voice-chat gateway; diagnostic detail is an engineering capability, not a validated household journey. This feature realizes UJ-5 and UJ-6.

**Functional Requirements:**

#### FR-20: Use iOS as a full conversation doorway

The iOS Client can start a voice turn by tap-to-speak and can support typed turns through its own Hermes Session.

**Consequences (testable):**
- iOS shows listening, thinking, and speaking indicators for a voice turn.
- Amanda hears Missy’s voice and sees the corresponding transcript.
- The conversation remains in iOS Local History.

#### FR-21: Use the TUI as a direct voice-chat gateway

The TUI can start a voice conversation through its own Hermes Session and render the conversation and response state without becoming a second assistant.

**Consequences (testable):**
- TUI voice chat follows the same session and response semantics as the other doorways.
- Diagnostic detail is not required to complete the private pilot’s household journeys.

### 4.7 Voice-only Hermes prompts

**Description:** When Hermes needs clarification or approval, the room Display can mirror the prompt text and state while the user answers through voice. This keeps the room informed without creating a second prompt-control surface.

**Functional Requirements:**

#### FR-22: Mirror prompts without touch actions

The room Display can show an active Hermes clarification or approval prompt, while the active Puck, ESP32 Touch Display, W/K browser voice surface, or Client accepts the user’s spoken answer.

**Consequences (testable):**
- Prompt text and state are visible on the room Display.
- No Display touch action creates, submits, or resumes a prompt response in v1.
- The spoken answer is routed to the active Hermes Session.

## 5. Non-Goals (Explicit)

- Replacing Hermes intelligence or running a large model on a Device.
- A general smart-home ecosystem, vendor-cloud migration, camera history product, or media catalog.
- Touch-based Hermes prompt choices.
- Spoken or audible Departure Cards.
- Active-playback barge-in before an echo-safe audio route is proven.
- Full response text on the Puck’s 1.28-inch status display.
- A public provisioning system or multi-household commercial deployment.
- A separate native iPad display application for the private pilot.
- A diagnostic-first TUI experience.
- Splitting the repositories before a real dependency conflict requires it.

## 6. MVP Scope

### 6.1 In Scope

- One complete single-Room pilot with a Puck, an ESP32-S3 Display, an iPad browser Display, iOS, and the TUI.
- Hermes voice/text turns, local wake and capture, Media Server transcription over the home LAN, Hermes audio response, live Transcription, and visible turn phases.
- Multiple unique Wake Mappings, per-Device credentials, iOS discovery/approval/setup/revocation, closest-Device arbitration, and fresh Hermes Sessions after reconnect.
- Immich Ambient Surface, room-local Active Turn mirroring, shared calendar Departure Cards, and honest Disconnected State/recovery.
- Shared state/action contracts, fixture-driven behavior, and conformance tests across supported Display surfaces.

### 6.2 Out of Scope for MVP

- Multi-room hardware rollout as a prerequisite; the contract remains multi-Room-ready.
- Live active-playback interruption, touch prompt actions, audible calendar alerts, and local fallback speech.
- Retained raw audio or a Media Server transcript archive.
- Broader product naming, public distribution, and commercial operations.

## 7. Cross-Cutting NFRs

- **Performance:** Wake acknowledgement and visible Puck status should appear in roughly one second; first spoken Hermes audio should begin in roughly four seconds after speech ends.
- **Reliability:** Supported surfaces must expose the actual turn phase, avoid duplicate Active Turns, and recover from transport loss without replaying captured speech.
- **Privacy:** Raw Puck and ESP32 Touch audio remain transient on the home LAN; the Media Server/audio bridge does not retain transcripts; Local History is limited to intentional iOS/TUI storage.
- **Security:** Every Device uses an individual revocable Device Credential; unapproved, revoked, or unavailable identity fails closed before capture.
- **Consistency:** ESP32-S3 Touch and W/K Web/iPad surfaces consume the same visual semantics for Ambient Surface, Active Turn, Departure Card, and Disconnected State; the touch and enabled W/K voice surfaces additionally own their voice capture and response-audio paths.

## 8. Constraints and Guardrails

### 8.1 Privacy and Data Retention

- Hermes remains the response authority; no doorway presents local fallback text or speech as Missy.
- Profile context must not cross Wake Mappings or Hermes Sessions.
- Raw audio and Media Server transcripts are not retained by default. Diagnostic recording is opt-in and bounded.
- Active response text is Room-local; Departure Cards are the deliberate household-wide exception.

### 8.2 Hardware and Deployment

- Puck wake detection and capture run at the Device boundary; Media Server transcription is required because of Puck resource limits.
- The first Puck audio path is home-LAN-only.
- The ESP32 Touch Display is a first-class Epic 1 voice-plus-display Device. Its native LVGL UI consumes the shared visual contract, while microphone ingress and response-audio egress use a separate bounded adapter. The current snapshot/action firmware path is foundation only until that adapter is implemented.
- The private pilot uses the ReSpeaker Lite prototype, salvaged speaker driver, printed enclosure, and provisional TFT; exact electrical, acoustic, thermal, and firmware compatibility remain validation work.
- The W/K browser surface uses Safari/Guided Access on iPad at a local kiosk URL. LAN discovery is primary; QR/manual pairing is fallback.

### 8.3 Hermes Boundary

- Clients route, present, and report state. They do not duplicate Hermes tools or silently alter Hermes responses.
- Hermes/vault owns agent/profile context, shared family calendar, household home, and travel estimates. iOS owns Device administration and Room-level presentation policy.

## 9. Success Metrics

### Primary

- **SM-1:** UJ-1 dinner journey completes without phone, keyboard, or TUI in at least 4 of 5 scripted pilot attempts. `[ASSUMPTION: initial pilot threshold]` Validates FR-1 through FR-6.
- **SM-2:** In every scripted disconnected and revoked-device test, zero audio payloads and zero Hermes turns are produced. Validates FR-8, FR-12, and FR-18.
- **SM-3:** Every calendar fixture test produces one consistent Departure Card state across all Displays, with correct promotion, recomputation, cancellation, and clearing. Validates FR-13 through FR-15.

### Secondary

- **SM-4:** Median wake acknowledgement and visible Puck status are at or below the one-second working target; median first spoken audio is at or below the four-second working target. Validates FR-2 through FR-4.
- **SM-5:** Device enrollment completes from discovery through ready confirmation with visible success on both iOS and the Device in every pilot setup run. Validates FR-16 and FR-17.
- **SM-6:** iOS and TUI can complete independent Hermes conversations without merging live Sessions. Validates FR-20 and FR-21.

### Counter-metrics

- **SM-C1:** False wake submissions remain at zero, even if a false wake briefly paints Listening. Counterbalances responsiveness in FR-1 and FR-2.
- **SM-C2:** Unsolicited audio remains at zero for Departure Cards and Disconnected State. Counterbalances convenience in FR-12 and FR-14.
- **SM-C3:** Default raw-audio and Media Server transcript artifacts remain at zero. Counterbalances diagnostic convenience in the privacy guardrails.

## 10. Open Questions

1. What proximity signal and tie window should select the closest Device? **Owner:** Architecture. **Revisit:** before arbitration is finalized for architecture and story creation.
2. How should iOS publish mapping, Room, and credential changes, and what last-known configuration is safe while a Device is offline? **Owner:** iOS + Architecture. **Revisit:** before enrollment and configuration stories are created.
3. What exact Device Credential storage, rotation, expiry, and re-enrollment mechanism fits the Puck and W/K browser deployment? **Owner:** Architecture + Security. **Revisit:** before Device enrollment implementation.
4. What Media Server/audio-bridge transport, bounded buffering, and cleanup behavior covers success, cancellation, and failure for the Puck and ESP32 Touch Display? **Owner:** Architecture + Media Server integration. **Revisit:** before either physical voice surface is implemented.
5. Which people and exclusions define each Room’s Immich filter, and what freshness policy applies? **Owner:** UX + iOS. **Revisit:** before Room presentation settings are implemented.
6. Where are travel estimates keyed in the vault, how is staleness detected, and how are missed calendar updates recovered? **Owner:** Hermes/vault integration. **Revisit:** before calendar integration stories are created.
7. When does a future release earn active-playback barge-in? **Owner:** UX + Audio. **Revisit:** only after the v1 audio route proves echo-safe.

## 11. Assumptions Index

- `[ASSUMPTION: initial pilot threshold]` — The first private pilot treats 4 successful UJ-1 completions out of 5 scripted attempts as an initial success threshold; adjust after real-room measurements.
