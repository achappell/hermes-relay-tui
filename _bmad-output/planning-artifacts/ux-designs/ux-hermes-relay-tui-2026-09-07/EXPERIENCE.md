---
title: Hermes Home Assistant Platform — Experience
status: final
created: '2026-09-07'
updated: '2026-09-07'
sources:
  - "{planning_artifacts}/briefs/brief-hermes-relay-tui-2026-09-07/brief.md"
  - "{planning_artifacts}/briefs/brief-hermes-relay-tui-2026-09-07/addendum.md"
  - "{planning_artifacts}/prds/prd-hermes-relay-tui-2026-09-07/prd.md"
  - "{planning_artifacts}/prds/prd-hermes-relay-tui-2026-09-07/reconcile-brief.md"
  - "{planning_artifacts}/prds/prd-hermes-relay-tui-2026-09-07/reconcile-ios-client.md"
  - "{planning_artifacts}/prds/prd-hermes-relay-tui-2026-09-07/reconcile-shared-display.md"
  - "{planning_artifacts}/prds/prd-hermes-relay-tui-2026-09-07/review-rubric.md"
design: DESIGN.md
---

# Hermes Home Assistant Platform — Experience Spine

## Foundation

This is a multi-surface household experience: a physical Puck, a room Display, an iPad Display running Safari/Guided Access, a native iOS/macOS Client, and the existing TUI. The first release proves one complete single-Room pilot while keeping the shared contracts multi-Room-ready. The native macOS simulator is development tooling, not a household surface.

`DESIGN.md` is the visual identity reference. It defines the Night Console direction, semantic tokens, density, contrast, and motion treatment. This spine defines behavior: which doorway acts, what state is honest, where text is allowed to appear, and how recovery works. The [Night Console mockup](mockups/direction-night-console.html) illustrates the room Display's dense active-turn composition; the spine wins on conflict.

Hermes remains the response authority. Hermes owns answer content, wording, correctness, model behavior, and domain context. This UX pass owns the doorway interaction: Wake Mapping and profile routing, capture gating, turn-state feedback, room-local presentation, child-readable status, privacy, device administration, and recovery. No section below specifies what Hermes should answer.

The dinner pilot succeeds when Amanda finishes the exchange with everything Hermes gave her to start dinner and know when to begin. The doorway keeps that answer findable and the follow-up natural; it does not manufacture, shorten, or correct the answer.

The household includes children using shared Pucks and Displays. Children can use ordinary wake, conversation, and follow-up. Device setup, profile mapping, credential management, revocation, and re-enrollment remain iOS administration work.

### Shared vocabulary

The following terms retain the PRD glossary meanings and spelling so downstream architecture and story work can extract them without translation.

| Term | Contract meaning |
|---|---|
| **Device** | A physical household endpoint managed by iOS: a Puck or Display with its own Device Credential. |
| **Puck** | The room voice Device that detects a Wake Mapping, captures speech, and plays Hermes audio. |
| **Display** | A room visual Device that renders the Ambient Surface, Active Turn state, live Transcription, response text, and Departure Card. |
| **Client** | A software doorway, currently iOS or TUI, that can create an Hermes Session without being a physical Device. |
| **Room** | A named household location that binds Devices to presentation policy and room-local Active Turn mirroring. |
| **Wake Mapping** | One unique wake phrase mapped to one Hermes Profile on a Device. |
| **Hermes Profile** | The configured Hermes identity and authorized context selected by a Wake Mapping or Client configuration. Missy is one Hermes Profile. |
| **Hermes Session** | The conversation session owned by one doorway. A reconnect starts a new Hermes Session. |
| **Media Server** | The trusted home-LAN service that transcribes Puck audio before the transcript reaches Hermes. |
| **Transcription** | The text representation of captured speech produced while a Puck or Client is listening. |
| **Device Credential** | The individually revocable credential that authorizes one Device; it is never shared by multiple Devices. |
| **Active Turn** | One user request and its Hermes response, including listening, transcription, thinking, buffering, speaking, and completion states. |
| **Turn Phase** | One of the user-visible Active Turn states: heard, listening, transcribing, thinking, buffering, speaking, complete, or Disconnected State. |
| **Ambient Surface** | The normal Display state, initially Immich photos filtered by Room policy. |
| **Departure Card** | The visual calendar state showing event name, location, departure time, and countdown when a qualifying event is actionable. |
| **Local History** | Conversation history retained intentionally by iOS or the TUI; Puck, Display, and Media Server do not create a transcript archive by default. |
| **Disconnected State** | The honest local state shown when a Device cannot use the Hermes path; it is visual-only in v1. |

## Information Architecture

| Surface | Reached from | Purpose and behavioral boundary |
|---|---|---|
| **Puck** | Wake Mapping detection or follow-up | Captures only after the selected Profile is fixed, sends Puck audio through the Media Server, and plays Hermes audio. Its TFT is a status surface, not a transcript. |
| **Room Display** | Ambient Surface in a Room | Shows room-local Active Turn state, live Transcription, response text, and the active Profile identity. It does not capture, speak, or create a second Hermes Session. See the [room active-turn key screen](mockups/key-room-active-turn.html). |
| **iPad Display** | Safari/Guided Access kiosk URL | Consumes the same display contract as the ESP32-S3/LVGL Display for Ambient Surface, Active Turn, Departure Card, and Disconnected State. It is not a separate native iPad application in v1. |
| **iOS Client** | App launch; conversation or Settings | Provides tap-to-speak and typed conversation, visible listening/thinking/speaking state, active Profile in the header, Local History, and the sole physical-Device control plane. |
| **iOS Settings** | iOS Client Settings | Discovers, approves, connects, assigns Rooms, configures Wake Mappings, revokes Device Credentials, and guides re-enrollment. A discovered Device is inert until explicit approval and setup. See the [iOS setup key screen](mockups/key-ios-setup.html). |
| **TUI** | Terminal launch or existing Hermes Session | Provides a direct voice-chat doorway, shared phase semantics, active Profile in the header, conversation rendering, and engineering diagnostics. It is not the household configuration surface. |
| **Media Server** | Puck voice path | A supporting home-LAN service, not a user surface. It produces transient Transcription and does not become a transcript archive by default. |
| **Ambient Surface** | Display idle state | Shows room-filtered Immich photos; a Room with no matching photos receives a neutral ambient background, not a widened filter or setup prompt. |
| **Departure Card** | Qualifying shared-calendar event | Replaces the Ambient Surface on every Display, remains visual-only, and clears or recomputes from calendar changes. |
| **Local History** | iOS Client or TUI conversation | Stores deliberate conversation history only on those intentional Client surfaces. Pucks and Displays do not expose it. |

Surface closure is deliberate: conversation reaches the Puck/Room Display, iOS Client, and TUI; physical administration reaches iOS Settings; ambient and departure context reaches Displays; recovery is visible at the doorway that failed. Other Displays do not receive room-local conversation text. Household-wide propagation is reserved for the Departure Card.

### Product-requirement crosswalk

This crosswalk keeps the UX spine mechanically traceable to the confirmed PRD requirements without copying their acceptance criteria into a second backlog.

| PRD requirement | UX anchor |
|---|---|
| FR-1 Start an Active Turn | UJ-1, UJ-5, UJ-6; Wake, routing, and capture |
| FR-2 Show live capture state and Transcription | UJ-1; State Patterns: `listening` and `transcribing` |
| FR-3 Show honest turn phases | State presentation mapping; Turn Path |
| FR-4 Deliver the Hermes response multimodally | UJ-1 and UJ-5; `speaking`, `complete`, Audio unavailable |
| FR-5 Continue a bounded conversation | UJ-1; Follow-up Window |
| FR-6 Start a clean Hermes Session after reconnect | Recovery and explicit actions; UJ-5/UJ-6 failure paths |
| FR-7 Enforce unique Wake Mappings | Wake, routing, and capture; Device Setup |
| FR-8 Fail closed for unavailable identity | Revoked / unavailable identity; UJ-1 failure path |
| FR-9 Select one Device for a wake | Wake, routing, and capture; UJ-1 step 2 |
| FR-10 Render the Ambient Surface | Information Architecture; Ambient Surface pattern; UJ-4 |
| FR-11 Mirror a room-local Active Turn | Room Display pattern; UJ-1; Surface state matrix |
| FR-12 Show Disconnected State honestly | Disconnected State; Recovery and explicit actions |
| FR-13 Qualify calendar events | Calendar and ambient context; UJ-4 step 2 |
| FR-14 Promote a shared Departure Card | Departure Card pattern; UJ-4 step 3 |
| FR-15 Maintain and clear the Departure Card | Departure Card pattern; UJ-4 steps 4–5 |
| FR-16 Discover and connect a Device | iOS Settings; Device Discovery; UJ-2 |
| FR-17 Guide initial Device setup | Device Setup; UJ-2 steps 4–6 |
| FR-18 Revoke a Device | Device Details; UJ-3 |
| FR-19 Recover without a silent turn | Recovery and explicit actions; Surface state matrix |
| FR-20 Use iOS as a full conversation doorway | iOS Client; UJ-5 |
| FR-21 Use the TUI as a direct voice-chat gateway | TUI; UJ-6 |
| FR-22 Mirror prompts without touch actions | Prompt Mirror; Surface state matrix; UJ-1 prompt boundary |

## Voice and Tone

The shared feedback personality is **clear, fun, and friendly**. “Fun” belongs in the Display presentation, the Puck's tiny status presentation, and light active-state motion; it must never obscure privacy, identity, or a failure. Hermes' answer voice and content remain outside this spine.

| Situation | Prefer | Avoid |
|---|---|---|
| Core phase | `Heard`, `Listening`, `Transcribing`, `Thinking`, `Buffering`, `Speaking`, `Complete` | Technical codes, unlabeled spinners, or a later phase shown early |
| Local terminal state | `Stopped` | A pretend assistant response or a dramatic success message |
| Loss of usable path | `Unavailable` or `Disconnected` with the actual doorway status | “Working…” forever, local fallback speech, or a false ready state |
| Active identity | `Profile: Missy` from the `heard` acknowledgement through completion on the Room Display, and in the iOS/TUI header before capture through completion | Speaking the profile name through the Puck or hiding which profile answered |
| Recovery | `Retry` with an explanation that it reconnects only | `Try again` when it would replay the prior prompt |
| Setup | Short ordered labels: `Discover`, `Connect`, `Room`, `Wake Mappings`, `Ready` | Silent list updates that make Amanda infer success |
| Departure context | Event name, location, calculated departure time, countdown, and `estimated` when applicable | Spoken announcements, fabricated countdowns, or a manual-dismiss requirement |

Copy is short, complete, and readable by a child. Status language reports what the doorway knows; it does not claim Hermes understood, answered, or recovered until that has actually happened. The UX does not rewrite or paraphrase response text.

## Component Patterns

These are behavioral contracts. Visual anatomy, token usage, density, color, and motion live in `DESIGN.md`.

| Component | Behavioral rules |
|---|---|
| **Room Display** | Mirrors the selected Puck's room-local Active Turn, including live Transcription, Turn Phase, response text, and active Profile identity. It never captures, speaks, creates a second Session, or shows another Room's conversation. |
| **Puck Status** | Shows one short, readable local phase. It acknowledges wake, exposes listening/working/speaking/unavailable/stopped status, plays Hermes audio only for an authorized turn, and never displays full response text or retained transcript history. |
| **Profile Header** | Shows the active Hermes Profile from the `heard` acknowledgement through completion on the Room Display and in the active iOS/TUI conversation header. The Puck does not speak the profile name as a UX requirement. The header identifies routing; it must not imply that the answer is correct. Hermes owns the answer content. |
| **Turn Path** | Exposes the supported phases in order as they occur. A doorway does not paint Thinking, Buffering, Speaking, or Complete before the corresponding event is known. `Disconnected State` replaces an indefinite active path after transport loss. |
| **State Label** | Gives every core state a readable label. Animation and sound support it; neither is the sole signal. Child-readable labels include heard, listening, working, speaking, unavailable, and stopped while preserving the canonical Turn Phase vocabulary. |
| **Voice Visualizer** | Runs during active connection or response presentation as a supplementary signal. During Speaking it may synchronize with the voice. With reduced motion it becomes static. It never implies audio is playing when audio is unavailable. |
| **Transcript** | Updates live during Transcription and streams the same Hermes response text on the Room Display, iOS Client, or TUI. A completed response remains visible as specified by the doorway. It is never shown on the Puck's tiny status display and never mirrored to other Rooms. |
| **Follow-up Window** | Opens after each response for eight seconds without another Wake Mapping. When the window opens, play a sound cue and show `Listening` again. When it closes without new speech, play the closing cue and return to wake detection; exactly `stop` closes capture/follow-up silently and creates no replacement turn. |
| **Ambient Surface** | Remains in the background when idle. It shows Room-filtered Immich photos or a neutral ambient background when no photos match. It yields to a Departure Card or room-local Active Turn according to the still-open priority rule below. |
| **Departure Card** | Promotes the same visual-only event state to every Display when the event crosses its effective threshold. It contains event name, location, calculated departure time, countdown, and `estimated` when a configured estimate replaces a live route. Time/location changes recompute it; cancellation and event start clear it. |
| **Disconnected State** | Persists visibly when the Hermes path is unavailable. Displays may retain useful cached Ambient Surface or Departure Card content. The Puck captures nothing and speaks no fallback; recovery clears the state only after verification and never reopens capture silently. |
| **Retry Action** | Appears after a dropped connection where an explicit action is useful. Retry reconnects only, leaves the interrupted turn unresolved, and does not resend the previous prompt. A fresh wake or explicit new prompt is required after recovery. See the [recovery key screen](mockups/key-recovery.html). |
| **Device Discovery** | Lists discovered Devices separately from approved Devices. Selecting a discovered Device shows a connecting state while it remains unconfigured and inert. Discovery alone never grants capture or Hermes access. |
| **Device Setup** | Guides the ordered flow: approval/connection, Room assignment, one or more Wake Mappings, then ready confirmation. Both iOS and the Device show success; incomplete setup leaves the Device inactive. Duplicate Wake Mappings are blocked before save, and a pending or offline configuration is labeled pending rather than ready. |
| **Device Details** | Shows the Device's current status and makes Disconnect consequential. Confirmation explains that the Device stops working until re-enrolled. Revocation removes access even if the powered Device remains reachable. Edits to Wake Mappings show validation and publish status; an unverified edit never masquerades as the applied mapping. |
| **Local History** | Exists only where the user intentionally keeps it: iOS Client and TUI. It supports continuity on those surfaces; Puck, Display, and Media Server do not create a default transcript archive. |
| **Prompt Mirror** | May show an active Hermes clarification or approval prompt on the Room Display. The answer comes through the active Puck or Client voice path; the Display has no touch prompt action in v1. |
| **TUI Header** | Shows the active Profile in the terminal conversation header and preserves the shared phase semantics. Diagnostics remain an engineering capability and do not become the validated household journey. |

## State Patterns

The named Turn Phases are `heard`, `listening`, `transcribing`, `thinking`, `buffering`, `speaking`, and `complete`, with `Disconnected State` as the honest unavailable state. `Stopped` is a local presentation state for a user-initiated stop, not a new Hermes response phase.

| State | Applies to | Entry and behavior | Exit and failure rule |
|---|---|---|---|
| **Idle / Ambient Surface** | Room Display, iPad Display | Display stays in the background with Room-filtered Immich photos. | A qualifying Active Turn or Departure Card replaces it. No matching photos use a neutral background. |
| **Unconfigured** | New Puck/Display and iOS discovery | A discovered Device is visibly inert and cannot capture or use Hermes. | Explicit approval and setup move it toward Connected/Ready; failure never silently activates it. |
| **Connecting** | iOS setup, Device setup, reconnecting doorway | Show that a connection attempt is in progress; the Device remains honest about whether it is configured. The active-state motion may be used as a supplementary signal. | Success is visible on both surfaces. Failure remains visible and actionable without claiming Ready. |
| **heard** | Puck, Displays, iOS Client, TUI | The doorway acknowledges a recognized and authorized initiation before capture. The selected Profile is already fixed for a Puck. | Move to `listening` or fail closed if identity/authorization is unavailable. |
| **listening** | Puck, Displays, iOS Client, TUI | Show that capture is open. The follow-up variant adds the opening sound cue and does not require another Wake Mapping. | Capture ends, cancellation occurs, or the eight-second follow-up expires. |
| **transcribing** | Puck path, Room Display, iOS Client, TUI | Show live Transcription as words arrive. Puck audio is transient and remains on the home-LAN Media Server path before Hermes receives text. | Move to `thinking`; loss of path becomes `Disconnected State`, not indefinite listening. |
| **thinking** | All conversation doorways | Show that Hermes is processing without suggesting that answer content is defined by the doorway. | Move to `buffering`, `speaking`, or `Disconnected State` when transport fails. |
| **buffering** | Puck, Room Display, iOS Client, TUI | Show that response audio is preparing. Keep response text and audio status distinct. | Move to `speaking` only when audio is actually available, or to complete text plus unavailable-audio status if text completes and audio fails. |
| **speaking** | Puck, Room Display, iOS Client, TUI | Puck/Client plays the Hermes response; Display/Client/TUI presents the same response text. The Room Display's visualizer may synchronize with voice. | Move to `complete`; active-playback barge-in remains out of v1 until the audio route is echo-safe. |
| **complete** | All conversation doorways | Leave the completed response visible where the doorway supports text. Show the active Profile in the Room Display response and iOS/TUI header. | Puck opens the eight-second follow-up. If no follow-up arrives, the window closes with its closing cue and the Display returns to Ambient/idle. |
| **Stopped** | Puck capture/follow-up, local doorway UI | Exactly `stop` closes local capture or follow-up silently and creates no replacement Hermes turn. | Return to wake detection or doorway idle state without a spoken or celebratory reply. |
| **Audio unavailable** | Display, iOS Client, TUI | If Hermes text completes but response audio fails, show the text as complete with an unavailable-audio status. | Never show `speaking` or claim audio was delivered. Recovery is a fresh turn unless the doorway offers an explicit non-replay action. |
| **Disconnected State** | Every Device/Client as applicable | Persistent visual state when Media Server, Hermes, or the doorway path is unavailable. Displays may retain useful cached context; Puck captures nothing and speaks no fallback. | Verified recovery clears it but never silently reopens capture or resumes the old turn. A dropped active turn remains unresolved. |
| **Revoked / unavailable identity** | Puck and administration surfaces | Fail closed with local sound and visible status. No capture, no submission, no alternate Profile. | Explicit re-enrollment is required after revocation; unavailable identity stays unavailable. |
| **Departure Card** | Every Display | Replaces Ambient Surface when a qualifying shared-calendar event crosses the effective threshold. | Recompute on event time/location change, clear on cancellation or event start, and never generate unsolicited audio. |
| **Prompt waiting** | Room Display plus active Puck/Client | Mirror Hermes clarification or approval text and show that a spoken answer is awaited. | Answer follows the active Session; no touch response action exists in v1. |

### Priority and persistence notes

- Conversation text is Room-local; other Displays remain unaware of it. Departure Cards are the explicit household-wide exception.
- A room-local Active Turn has priority on its selected Room Display until it reaches a terminal state: completed response plus follow-up close, or `Stopped`. Other Displays continue to show the household-wide Departure Card. When the turn ends, the selected Room Display promotes the still-qualifying Departure Card.
- Disconnected State is persistent and visual-only. Useful cached context may remain, but stale context must not be presented as live recovery. A shared Puck/Display transcript is volatile: it is cleared when the follow-up closes, on `Stopped`, on a fresh session, or on reboot. If partial text remains during Disconnected State, purge it on Retry, fresh session, or restart; never rehydrate it from browser storage or a service worker.

### State presentation mapping

The doorway keeps one canonical state model while presenting a small child-readable vocabulary. The primary label is always text; color, motion, and sound are supporting channels. Client and TUI surfaces may expose the technical label alongside the child-readable label, but a Room Display or Puck must not require protocol knowledge.

| Canonical/local state | Child-readable label | Technical label or detail | Supporting cue | Assistive presentation |
|---|---|---|---|---|
| `idle` / Ambient Surface | Ready | Ambient | None; remain quiet | Announce only on entry if the surface is already in use |
| `unconfigured` | Not ready | Unconfigured | Static attention marker | Expose setup status and next action |
| `connecting` | Connecting | Connecting | Controlled connecting animation | Announce once on entry and once on success/failure |
| `heard` | Heard | Heard | Local acknowledgement sound | Announce once; identify the selected Profile |
| `listening` | Listening | Listening | Listening cue and optional live motion | Announce once; do not announce every audio frame |
| `transcribing` | Working | Transcribing | Word arrival or restrained motion | Announce once; expose live text as it changes without repeating every delta |
| `thinking` | Working | Thinking | Processing motion | Announce once; never imply an answer is ready |
| `buffering` | Working | Buffering | Preparing-audio motion | Announce once; keep text and audio availability distinct |
| `speaking` | Speaking | Speaking | Voice-synchronized motion and Hermes audio | Announce once; never use motion as proof of audio |
| `complete` | Complete | Complete | Completion state; follow-up opening cue when applicable | Announce response text on completion, then the follow-up state |
| `stopped` | Stopped | Stopped | Silent local close | Announce the state, not a fictional response |
| audio unavailable | Response ready | Audio unavailable | Explicit unavailable status | Announce text complete and audio unavailable |
| `disconnected` | Unavailable | Disconnected State | Persistent unavailable status | Announce once, expose recovery route where supported |
| `error` | Something went wrong | Error | Explicit failure status; no indefinite motion | Announce the failure once and expose the available action without implying recovery |
| revoked/unavailable identity | Unavailable | Identity unavailable | Local sound plus visible status | Announce no capture is allowed; never offer fallback Profile |
| Departure Card | Time to leave | Departure Card | No sound or motion requirement | Announce only on an intentional Display/client context, never as unsolicited Puck audio |
| prompt waiting | Needs your answer | Prompt waiting | Waiting indicator | Announce prompt once; Display mirror is not actionable |

### Surface state matrix

This matrix assigns the visible contract when a surface is cold, empty, active, offline, permission-blocked, failed, or recovering. `Retry` is a Client action in v1: iOS and TUI render it; Room Displays and Pucks show status and direct the user to a Client rather than inventing a touch action.

| Surface | Cold / empty | Active turn | Offline / permission / failure | Recovery and persistence |
|---|---|---|---|---|
| **Puck** | `Ready` when configured; `Not ready` when unconfigured; no transcript history | `Heard` → `Listening` → `Working` → `Speaking`; tiny TFT shows one short label and local cues | `Unavailable` or `Disconnected`; no capture, submission, fallback, or profile substitution | Reconnect never opens the microphone. After verified recovery, a fresh wake is required; no shared text persists |
| **Room Display / iPad Display** | Ambient Surface or neutral fallback; no matching Immich photos do not become an error | Mirrors the selected Room's state, Profile, live Transcription, and response; the selected Room Active Turn outranks Departure Card | Shows persistent Disconnected/Unavailable and may retain clearly stale-labeled ambient/calendar context; no room text from another Room | Retry is described as a Client action. Room-local turn text clears at terminal state, new session, Retry, or restart; Departure Card remains household-wide when qualifying |
| **iOS Client** | Empty conversation has a ready state; Settings separately shows discovered vs approved Devices | Header shows Profile before capture; state, response, audio status, and Local History are visible | Permission denial, revoked identity, or transport failure is explicit; no silent fallback; `Retry` is available after connection loss | Retry reconnects only. Local History is intentional and may persist completed turns; unresolved turns are not replayed |
| **iOS Settings** | Empty discovery shows no approved Devices and a clear Add path | Connecting/setup steps show pending Room and Wake Mapping work | Discovery is not approval; permission, duplicate mapping, offline publish, and revocation failures remain visibly unresolved | Only verified configuration is shown as applied. Re-enrollment is explicit; pending edits are not treated as ready |
| **TUI** | Ready header with active Profile when configured; empty transcript is not an error | Shared phase labels, inline streamed response text, active Profile, and explicit diagnostics where enabled | Disconnected or unavailable state is visible; no fake answer or replay | `Retry` reconnects only. Local History is deliberate; a fresh explicit prompt is required after recovery |
| **Local History** | Empty state explains that history is local to iOS/TUI | Stores only intentional Client turns, not shared-device room text | No history is created for Puck, Display, or Media Server failures | History may survive a Client restart; shared Puck/Display text never rehydrates from it |

## Interaction Primitives

### Wake, routing, and capture

- A Wake Mapping selects exactly one Hermes Profile before Puck capture begins. Duplicate or ambiguous mappings are rejected before deployment.
- If a mapping is revoked or unavailable, the doorway gives a local sound and visible status, then fails closed: no capture, no Hermes submission, and no alternate Profile.
- When multiple authorized Devices hear a Wake Mapping, the closest Device wins; configured Device priority resolves an effective proximity tie. Losing Devices stay silent and create no duplicate Active Turn.
- The selected Profile is fixed before capture. The Room Display exposes that identity at the `heard` acknowledgement and keeps it visible through completion; iOS and TUI show it in the header before capture and through completion. The Puck does not speak the Profile name.
- The proximity signal, arbitration window, and exact tie semantics remain an architecture decision; their unresolved mechanics must not weaken the single-winner or fixed-identity contract.

### Turn-taking and cues

- Each Puck or Client shows the honest phase sequence: heard → listening → transcribing → thinking → buffering → speaking → complete. A doorway may omit a phase it cannot observe, but it must not show a later phase early.
- After every response, the active Puck opens an eight-second follow-up window. When the window opens, play a sound cue and show `Listening` again; when it closes without new speech, play the closing cue.
- When the user says exactly `stop` during capture or the follow-up window, close the local window silently. It creates no replacement turn. A Display may show `Stopped` as a local status while returning to its idle listening contract.
- Active-playback barge-in is deferred until the v1 audio route proves echo-safe. Explicit controls supported by a Client remain distinct from automatic hands-free interruption.

### Presentation and privacy

- The Room Display mirrors the selected Puck's Active Turn but never captures, speaks, or creates a second Hermes Session.
- Live Transcription and response text stay in the selected Room. The Puck's tiny TFT shows status only; the iPad Display and ESP32-S3/LVGL Display share semantics, not necessarily geometry.
- Departure Cards intentionally propagate to every Display but remain visual-only. No Puck speaks or announces them.
- Puck audio is transient and home-LAN-only. The Media Server may buffer for Transcription, then discards it; diagnostic recording is bounded and opt-in. iOS/TUI may retain deliberate Local History.

### Recovery and explicit actions

- A transport loss during a turn moves the doorway to `Disconnected State` or its equivalent honest local error. It does not linger in Thinking and does not replay a request.
- `Retry` reconnects only. In v1 it is an explicit iOS/TUI Client action; Room Displays and Pucks show the unresolved status and direct the user to a Client. The interrupted turn remains unresolved because the original may have reached Hermes. After verified recovery, a fresh wake or explicit new prompt is required.
- Connection recovery never silently reopens the microphone or submits a pending turn. A revoked Device remains unusable until re-enrolled.
- Setup is an explicit sequence: discovery → approval/connection → Room → Wake Mappings → ready. Success is visible on iOS and the Device.

### Calendar and ambient context

- A Departure Card requires an event location and a usable live route or configured travel estimate from the household home. A configured estimate is visibly labeled `estimated`.
- Live route is preferred. If neither live route nor configured estimate is usable, no fabricated countdown appears.
- The effective household default threshold applies unless an event override exists. Time/location changes recompute the card; cancellation and event start clear it automatically.
- Calendar freshness, missed-update recovery, route refresh, stale-estimate handling, and threshold-editing UX remain open for Hermes/vault integration and iOS.

## Accessibility Floor

The minimum behavior is household-readable and multimodal without making any single channel authoritative.

- Every core state has readable text. The child-readable set includes heard, listening, working, speaking, unavailable, and stopped; the canonical Turn Phase labels remain available for precise diagnosis.
- Animation and sound support state comprehension but never carry the only meaning. A user can identify the current state from text and layout when sound is unavailable or the user is not watching continuously.
- `prefers-reduced-motion` replaces active animation, connecting loops, and visualizer transitions with one static frame and readable text. Sound cues remain available as a turn-taking aid; a quiet/night preference may suppress cues without changing visual state.
- The visualizer is not a caption, a transcript, or proof that speech is playing. If audio is unavailable, the text is complete and the state says unavailable.
- The active Profile is shown before capture at the `heard` acknowledgement on the Room Display and in the iOS/TUI header, then remains visible through completion. It is not required to be spoken by the Puck, preventing an extra spoken interruption while preserving visual identity.
- Shared Devices retain no conversation history. Room-local response text must not appear on other Displays; the household-wide exception is the visual-only Departure Card.
- iOS typed turns and the TUI provide non-Puck conversation paths. Device setup and administration remain iOS-only so a child can use the ordinary voice path without receiving credential-management controls.
- On iPad, the canvas has an accessible DOM status mirror. A live region announces each state transition once, not every Transcription or response delta; response text is announced when complete. Profile identity, unavailable status, and recovery instructions are exposed as text.
- On iOS, VoiceOver order is Profile → current state → response/Transcription → available action. After Retry completes, focus returns to the state and Profile; after setup, focus lands on the next incomplete step. Room Display prompt mirrors are not focusable or actionable.
- On the TUI, every recovery action has a keyboard-equivalent command and the header retains Profile identity. Touch actions use at least 44pt on iOS and 44px on touch-capable room surfaces. Icons, color, motion, and sound are always paired with text or structure.
- Puck-only visuals have no screen-reader channel; iOS/TUI provide the accessible configuration and conversation alternative. Sound-off does not remove state comprehension, and no Departure Card or Disconnected State produces unsolicited Puck audio.
- Validate the child-readable labels with the household's children at room distance. Technical labels remain secondary to `Ready`, `Heard`, `Listening`, `Working`, `Speaking`, `Unavailable`, and `Stopped`. The pilot assumes English labels; localization requires a follow-up review of width, comprehension, and cue timing.

## Responsive & Platform

| Platform/surface | Required adaptation |
|---|---|
| ReSpeaker Lite prototype Puck with small TFT | Status-only presentation. Use short readable phase labels and local cues; never place full response text or a transcript archive on the TFT. Exact electrical, acoustic, thermal, controller, and firmware behavior remains hardware validation. |
| ESP32-S3/LVGL Display | Dense Night Console active state and quiet Ambient Surface at the physical 1024×600 form factor. It consumes the shared `/ws`-style display state contract and sends no voice or touch prompt response in v1. |
| iPad Display | Safari/Guided Access kiosk using the same Display semantics as the ESP32-S3/LVGL target. Keep an accessible DOM status mirror alongside the canvas; kiosk authentication, offline behavior, and exact responsive reflow remain open. |
| iOS Client | Native conversation doorway with tap-to-speak and typed turns, listening/thinking/speaking status, active Profile header, Local History, and Settings-based Device administration. iOS may use its existing local push-to-talk Transcription path; the Puck Media Server requirement does not automatically apply to iOS microphone bytes. |
| macOS Client | A companion doorway may share the iOS conversation/admin contract; exact macOS behavior is not defined by the confirmed UX sources. |
| TUI | Direct voice-chat doorway with terminal transcript and state rendering. Preserve inline streamed text and Profile identity in the header; diagnostics are engineering-only. |
| Native macOS simulator | Development tooling for the exact C/LVGL UI codebase, not a household surface or a separate product contract. |

The pilot is one Room, but presentation and state contracts must not encode a one-room assumption. Exact breakpoints and platform navigation remain implementation details, provided the shared state, identity, privacy, and recovery contracts survive reflow.

## Inspiration & Anti-patterns

The behavioral anti-patterns below are the tests for every doorway. The selected visual direction, rejected alternatives, and density rationale live in `DESIGN.md` so visual history has one home.

Hard anti-patterns for this experience:

- Wrong Profile answering, or a revoked/unavailable mapping silently falling back to another Profile.
- Multiple Devices acknowledging or answering the same wake.
- A doorway claiming Listening, Speaking, Complete, or recovered when it does not know that to be true.
- A Display in one Room receiving another Room's Active Turn text.
- A Puck capturing, speaking, or replaying during Disconnected State.
- A retry that resends a turn that may already have reached Hermes.
- A shared Device retaining an ambient transcript archive or full response text on the tiny Puck TFT.
- A Departure Card speaking, sounding, or requiring manual dismissal.
- A touchable prompt response on the Display in v1.
- Chain-of-thought, a local fallback assistant, or doorway-authored answer content.
- Active-playback barge-in before an echo-safe audio route is proven.

## Key Flows

### UJ-1 — Amanda asks Missy what is for dinner in the kitchen

1. Amanda is in the kitchen. The room Puck is idle and connected to the Media Server and Hermes. She says, “Hey Missy.”
2. The authorized Wake Mapping is resolved before capture. If more than one Device hears it, the closest wins and effective priority resolves a tie; losers stay silent.
3. The winning Puck shows `heard` and then `listening`. The Room Display shows the same phase and the active Profile identity. Amanda speaks one utterance.
4. The Puck's transient audio travels over the home LAN to the Media Server for Transcription. The Room Display shows live Transcription as it arrives; it does not capture or create a second Session.
5. The doorway shows `thinking`, then `buffering` if response audio is preparing. If Hermes asks for clarification or approval, the Room Display mirrors the prompt, the active Puck/Client waits for a spoken answer, and no touch response action appears. Hermes owns the answer; the UX does not author or correct it.
6. The Puck speaks the Hermes response while the Room Display streams the same response text. The Display's active visualizer may move with the voice, and the active Profile remains visible in the response.
7. On completion, the doorway shows `complete`, leaves the response visible where text is supported, and opens the eight-second follow-up. A sound cue and Listening state make the resumed turn-taking obvious.
8. When Amanda says exactly `stop` during the follow-up window, the local window closes silently. If she says nothing, the closing cue plays and the Display returns to its Ambient Surface.

**Climax:** The conversational back-and-forth feels like one continuous Hermes relationship: Amanda can follow up naturally because the doorway reopens Listening without another wake, while the Display and Puck make each phase honest.

**Failure path:** If the Profile is unavailable or revoked, the Puck gives a local sound and visible unavailable status, captures nothing, submits nothing, and does not choose another Profile. If the connection drops during the turn, the doorway enters Disconnected State and exposes Retry where appropriate; Retry reconnects only, the turn stays unresolved, and a fresh wake or explicit prompt is required. Other Displays never receive the conversation text.

### UJ-2 — Amanda adds a new puck from iOS Settings

1. Amanda powers on a new Puck and opens iOS Settings. She taps Add.
2. iOS shows a Device-discovery list. The new Puck appears as discovered, not approved; it remains inert.
3. Amanda taps the Puck. iOS shows Connecting while the Puck shows its unconfigured setup state.
4. When the connection succeeds, iOS and the Puck both show success. iOS continues directly into guided setup rather than silently returning to the discovery list.
5. Guided setup asks for the Room first, then collects one or more unique Wake Mappings, and ends with a ready confirmation.
6. The Puck becomes an active household doorway only after the setup sequence completes.

**Climax:** Amanda can see that both sides agree on connection success, then watch the device become ready through an explicit Room → Wake Mappings → Ready sequence.

**Failure path:** A discovered but unapproved or incompletely configured Device remains inert and cannot capture or access Hermes. A connection or setup failure remains visible as not ready; the UX must not present a silent list update as approval.

### UJ-3 — Amanda disconnects an approved puck

1. Amanda opens the iOS Device list, selects the approved Puck, and opens Device Details.
2. She taps Disconnect.
3. iOS explains that the Puck will stop working until it is re-enrolled, then asks for confirmation.
4. Amanda confirms. iOS revokes that Device's individual Device Credential and Hermes access rather than merely closing its current connection.
5. The iOS status shows disconnected/revoked. The powered Puck shows Disconnected State and cannot wake, capture, or submit a turn.

**Climax:** The household has a trustworthy revocation boundary: powered and reachable does not mean authorized.

**Failure path:** If Amanda does not confirm, the Device remains in its prior approved state. If revocation cannot be verified, iOS must not show the Device as revoked; the unresolved status remains visible for recovery. Restoring access requires explicit re-enrollment.

### UJ-4 — The household prepares to leave for a calendar event

1. Amanda is near a Display showing its normal Ambient Surface. A shared family-calendar event with a location approaches its household default or event-specific departure threshold.
2. The event qualifies only when it has a usable live route or configured travel estimate from the household home. A configured estimate is labeled `estimated`.
3. Every Display replaces the Ambient Surface with the same Departure Card showing event name, location, calculated departure time, and countdown.
4. If event time or location changes, every Display recomputes the card. If the event is cancelled, every Display clears it.
5. When the event starts, the Departure Card clears automatically and Displays return to the Ambient Surface.

**Climax:** Amanda and the household can see when to leave and where they are going without summoning Hermes or receiving an unsolicited announcement.

**Failure path:** An event with no usable route or configured estimate remains ordinary calendar context and produces no fabricated countdown. The card is never spoken or made audible in v1. If a Display is disconnected, it may retain useful cached content but must not claim live recovery.

### UJ-5 — Amanda updates Missy from the iOS doorway

1. Amanda opens the iOS Client and chooses a typed turn or taps to speak.
2. For voice, the Client shows `listening` while she speaks. It then shows `thinking`, `buffering` where applicable, and `speaking` when Hermes audio is actually available.
3. The Client presents the conversation transcript from the same Hermes response and keeps the active Profile visible in the conversation header.
4. Amanda hears the Hermes response through iOS and sees the corresponding transcript.
5. The exchange remains available in iOS Local History.

**Climax:** Amanda can move from the room to a portable doorway without entering a competing assistant relationship; the state and response remain one Hermes conversation on this Client.

**Failure path:** If the connection drops, iOS shows Disconnected State and an explicit Retry. Retry reconnects only; it does not replay the prior prompt, and Amanda must start a fresh turn after verified recovery. If Hermes text completes but audio fails, the transcript is shown as complete with an unavailable-audio status rather than a false Speaking state.

### UJ-6 — Amanda reaches Missy through the TUI

1. Amanda is at a terminal with the TUI connected to its Hermes Session. She starts a voice turn.
2. The TUI shows the shared conversation phases and keeps streamed response text inline in the terminal surface.
3. The TUI header shows the active Hermes Profile. Diagnostic detail remains available as engineering capability, not as a prerequisite for ordinary conversation.
4. Amanda sees the Hermes response through the TUI's conversation surface and may retain deliberate Local History there.

**Climax:** The TUI is another direct doorway into the same Hermes relationship, not a second assistant behavior or a diagnostic-first household surface.

**Failure path:** A transport loss becomes an honest disconnected state rather than indefinite thinking. Retry reconnects only, the interrupted turn is not replayed, and a fresh explicit prompt is required after verified recovery. Audio failure leaves any completed text visibly complete with unavailable-audio status.

## Open Questions and Deferred Decisions

These items are intentionally not resolved into architecture or implementation here. They are non-blocking downstream or future-scope questions, not gaps in the locked UX contract above. Each has an owner and revisit gate; any later answer must preserve the fixed identity, state, privacy, recovery, and surface-ownership rules.

- What proximity signal, arbitration window, and configured priority semantics select the closest Device? **Owner:** Architecture. **Revisit:** before arbitration is finalized for architecture and story creation. **Status:** downstream, non-blocking.
- How should iOS publish mapping, Room, and credential changes, and what last-known configuration is safe while a Device is offline? **Owner:** iOS + Architecture. **Revisit:** before enrollment and configuration stories. **Status:** downstream, non-blocking.
- What Device Credential storage, rotation, expiry, offline revocation, and re-enrollment mechanism fits the Puck and iPad Display? **Owner:** Architecture + Security. **Revisit:** before Device enrollment implementation. **Status:** downstream, non-blocking.
- What Media Server audio transport, bounded buffering, and cleanup behavior covers success, cancellation, and failure? **Owner:** Architecture + Media Server integration. **Revisit:** before Puck voice implementation. **Status:** downstream, non-blocking.
- Which people and exclusions define each Room's Immich filter, and what freshness policy applies? **Owner:** UX + iOS. **Revisit:** before Room presentation settings. **Status:** downstream, non-blocking.
- Where are travel estimates keyed in the vault, how is staleness detected, and how are missed calendar updates recovered? **Owner:** Hermes/vault integration. **Revisit:** before calendar integration stories. **Status:** downstream, non-blocking.
- When does a future release earn active-playback barge-in? **Owner:** UX + Audio. **Revisit:** only after the v1 audio route proves echo-safe. **Status:** future release, non-blocking.
- What kiosk authentication and offline re-entry behavior does the iPad Display require? **Owner:** iPad/platform engineering. **Revisit:** before Guided Access deployment. **Status:** downstream, non-blocking.
- What exact conversation and administration behavior should the macOS Client support beyond the TUI and iOS contracts? **Owner:** macOS + UX. **Revisit:** before a native macOS Client is scoped; **Status:** future surface, does not block the pilot.
- Which localization targets follow the English pilot, and how should translated labels be revalidated for child comprehension and room-distance wrapping? **Owner:** UX + product. **Revisit:** before localization work. **Status:** downstream, non-blocking.
- What exact microcopy and cue durations should accompany an unavailable identity, connection loss, the opening and closing of the follow-up window, and audio-unavailable states? The semantic behaviors are decided; the final phrase/tone and timing remain a producer detail. **Owner:** UX + audio. **Revisit:** before implementation sign-off. **Status:** downstream, non-blocking; semantic contract is final.
