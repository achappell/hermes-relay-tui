---
stepsCompleted: ['step-01-validate-prerequisites', 'step-02-design-epics', 'step-03-create-stories', 'step-04-final-validation']
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-hermes-relay-tui-2026-09-07/prd.md
  - _bmad-output/specs/spec-hermes-relay-tui/SPEC.md
  - _bmad-output/planning-artifacts/briefs/brief-hermes-relay-tui-2026-09-07/addendum.md
  - _bmad-output/planning-artifacts/architecture/architecture-hermes-relay-tui-2026-09-08/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/ux-designs/ux-hermes-relay-tui-2026-09-07/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-hermes-relay-tui-2026-09-07/EXPERIENCE.md
---

# hermes-relay-tui - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for hermes-relay-tui, decomposing the requirements from the PRD, the canonical product spec, UX design contract, and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: A configured Puck, ESP32 Touch Display, or enabled W/K browser voice surface accepts its supported authorized voice initiation, and an authorized iOS Client or TUI accepts an explicit user-initiated turn.

FR2: The active Puck, ESP32 Touch Display, or W/K browser voice surface shows its capture acknowledgement and Listening phase; a passive room Display mirrors the owning Room's Listening phase and live Transcription; iOS and TUI show corresponding capture state.

FR3: Each supported doorway exposes the appropriate Turn Phase—heard, listening, transcribing, thinking, buffering, speaking, complete, or Disconnected State—without presenting a later phase early.

FR4: The Puck, ESP32 Touch Display, W/K browser voice surface, or iOS Client speaks the Hermes response; active text-capable surfaces render their own response text, passive room Displays stream the same room-local response text, and the TUI renders the conversation through its terminal surface.

FR5: After each response, a configured voice doorway may open a bounded follow-up window; the active Puck's v1 window is eight seconds without another Wake Mapping, the W/K browser surface uses its advertised bounded capability, and exactly “stop” during capture or follow-up closes the local window silently.

FR6: After transport loss, a doorway starts a fresh Hermes Session and does not replay or silently resume the prior Active Turn.

FR7: A Device can host multiple Wake Mappings, but each wake phrase maps to exactly one Hermes Profile; duplicate or ambiguous mappings are rejected before publishing.

FR8: A Wake Mapping pointing to a revoked or unavailable Hermes Profile fails closed with Disconnected State; it captures no audio, submits no Hermes turn, and does not fall back to another Profile.

FR9: When multiple authorized Devices hear a Wake Mapping, the closest Device wins and an effective proximity tie resolves by configured Device priority; losing Devices remain silent and create no duplicate Active Turn.

FR10: A Display shows Immich photos selected by its Room-level face filters while no higher-priority household state is active; no matching photos produce a neutral ambient background without widening filters or showing setup.

FR11: A passive Display bound to the selected doorway's Room renders live Transcription, Turn Phases, and response text for that Active Turn without capturing audio, speaking, or creating a second Hermes Session; an ESP32 Touch Display may itself be the selected doorway and then owns its capture, response rendering, and audio delivery; other Rooms receive no conversation text.

FR12: A Display shows a persistent visual Disconnected State when the Media Server or Hermes connection is unavailable and may continue showing cached Ambient Surface or cached Departure Card content; it never remains indefinitely in Thinking and never speaks a local outage phrase.

FR13: An event qualifies for a Departure Card only when it has a location and a usable live route or configured travel estimate from the household home; a configured estimate is labeled estimated.

FR14: When a qualifying event crosses its effective threshold, every Display replaces its Ambient Surface with the same visual-only Departure Card containing event name, location, calculated departure time, and countdown; household defaults apply unless an event override exists.

FR15: The Departure Card recomputes when event time or location changes, clears when the event is cancelled, and clears at event start so Displays return to the Ambient Surface; no manual dismissal is required.

FR16: From iOS Settings, Amanda can discover an unconfigured Device, select it, see a connecting state, and see success indicators on both iOS and the Device after connection.

FR17: After connection success, iOS guides Room assignment, one or more Wake Mappings, and final ready confirmation; the Device cannot become an active household doorway before setup completes.

FR18: From Device details, Amanda can confirm Disconnect to revoke the Device Credential and Hermes access; the powered Device cannot wake, capture, or submit until explicitly re-enrolled.

FR19: When the Hermes path returns, an authorized Device reconnects and clears Disconnected State only after verified recovery; it does not reopen capture or submit a pending turn, and failed recovery remains visibly disconnected.

FR20: The iOS Client starts voice turns by tap-to-speak and supports typed turns through its own Hermes Session, showing listening, thinking, and speaking indicators and retaining the conversation in iOS Local History.

FR21: The TUI starts voice conversation through its own Hermes Session and renders conversation and response state without becoming a second assistant; diagnostic detail is not required for the household journey.

FR22: A passive room Display mirrors an active Hermes clarification or approval prompt while the active Puck, ESP32 Touch Display, W/K browser voice surface, or Client accepts the spoken answer; no passive Display touch action creates, submits, or resumes a prompt response in v1.

### NonFunctional Requirements

NFR1: Wake acknowledgement and visible Puck status should appear in roughly one second; first spoken Hermes audio should begin in roughly four seconds after speech ends.

NFR2: Supported surfaces expose the actual Turn Phase, avoid duplicate Active Turns, and recover from transport loss without replaying captured speech.

NFR3: Raw Puck and ESP32 Touch audio remain transient on the home LAN; the Media Server/audio bridge retains no transcripts; only intentional iOS/TUI Local History may persist by default.

NFR4: Every Device uses an individual revocable Device Credential, and unapproved, revoked, or unavailable identity fails closed before capture.

NFR5: ESP32-S3 Touch and W/K Web/iPad surfaces consume the same visual semantics for Ambient Surface, Active Turn, Departure Card, and Disconnected State; each voice-enabled surface additionally owns its voice capture and response-audio path.

### Additional Requirements

- Use ports-and-adapters with functional cores. The Python core owns Hermes protocol normalization, session/turn lifecycle, configuration, and reusable local I/O ports; the portable C display core owns bounded display state and action rules.
- Core modules must not import Textual or another front-end framework, assume a terminal, or import app.py, home_display/, browser code, or firmware. Front ends depend on SessionProtocol; display-capable front ends also consume the shared display contract.
- Keep one owner for each state domain: HermesSession owns connection/capabilities/turn facts; appliance coordinators own local device lifecycle and snapshots; shared/display owns reducer validation and stale-sequence rejection; surface-local drafts, queues, presentation, and optional history stay local.
- Keep Hermes wire behavior behind client.py and session.py. Front ends consume normalized events and typed errors rather than parsing wire frames or inventing payloads; a turn that may have reached Hermes is never automatically replayed.
- Treat display_snapshot.schema.json, display_action.schema.json, and fixtures as the versioned cross-target contract. The portable C reducer is semantic authority; unknown fields are ignored, malformed known fields are rejected, display epochs establish baselines, sequences increase strictly within an epoch, and actions require advertised capability, current-state validity, and reducer acceptance.
- Keep Active Turn text, phases, and prompts Room-local. Household-wide propagation is reserved for an explicitly defined state such as a Departure Card.
- Keep hermes-relay, hermes-relay-home, browser kiosk, and ESP/native display targets as independent deployment units. Do not introduce a shared database, broker, or transcript store.
- Make recovery and shutdown explicit state transitions: run blocking capture/playback outside UI loops, use bounded reconnect, cancel workers before releasing audio, and require fresh user initiation after recovery.
- Treat the ESP32 Touch Display and enabled W/K browser surface as first-class Epic 1 voice-plus-display surfaces. Their visual state uses the shared display contract; microphone ingress and response-audio egress use bounded surface-specific contracts and do not move Hermes answer authority into firmware or browser presentation code.
- Keep Hermes credentials in the owning local process/profile. Snapshots, actions, diagnostics, and display clients contain no bearer tokens; the display server binds to loopback by default and remote LAN binding is explicit opt-in.
- Isolate front-end dependencies. The base install contains the core/TUI path; voice, wake, hardware, browser, and firmware dependencies remain in optional extras or target-specific environments with separate front-end entry points.
- Any shared contract change updates schemas and fixtures together and runs Python contract tests, portable/native C reducer tests, Web/TypeScript parser or reducer tests, target adapter tests, and the core import-boundary test.
- Use fake Hermes sessions/WebSockets and local fixtures for developer and CI validation; require a live endpoint only for the explicit text/voice smoke path. Runtime URLs, identities, tokens, devices, retry limits, and timeouts remain configuration.
- Preserve the observed brownfield baselines unless compatibility checks justify change: Python 3.14.7, Textual 8.2.8, websockets 17.1, Svelte 5.57.0, TypeScript 5.9.3, Vite 6.4.3, Vitest 3.2.7, LVGL 8.3.11, Emscripten SDK 6.0.5, and PlatformIO espressif32 6.6.0.
- No starter or greenfield template is specified by Architecture; Epic 1 Story 1 must be a product slice rather than a template-bootstrap story.

### UX Design Requirements

UX-DR1: Implement the Night Console semantic palette for dark base/console/panel surfaces, readable primary/secondary/muted ink, structural borders, live, attention, identity, unavailable, focus, and overlay signals; state meaning must never depend on color alone.

UX-DR2: Implement the typography tokens for system sans-serif human-facing text and restrained monospace metadata, including room state, headings, body, transcript, labels, Puck status, buttons, captions, room response, and recovery text; validate at least 56px primary state, 24px profile, 24px response, 20px recovery on the 1024×600 Display and readable status on the Puck TFT.

UX-DR3: Implement the 4/8/12/16/24/32/40/48px spacing scale, Display/Puck gutters, panel and section gaps, restrained radius scale, and minimum 44px/44pt touch targets where touch actions exist.

UX-DR4: Build the Room Display as a dense active console with Profile Header, Turn Path, dominant readable State Label, voice visualizer, transcript, and supporting recovery/status information; keep the idle Display quiet as an Ambient Surface.

UX-DR5: Build the Puck Status surface as one short readable local phase with acknowledgement and audio cues; never place full response text, a transcript archive, or a miniature unreadable console on the TFT.

UX-DR6: Show the active Hermes Profile from `heard` acknowledgement through completion on the Room Display and in iOS/TUI headers; identify routing without implying answer correctness, and do not require the Puck to speak the profile name.

UX-DR7: Render a visible Turn Path and dominant State Label using the canonical phase vocabulary; do not show a later phase early, and pair every animation or sound cue with readable text.

UX-DR8: Implement a supplementary Voice Visualizer that can synchronize with response audio, becomes static under `prefers-reduced-motion`, and never implies audio is playing when it is unavailable.

UX-DR9: Implement live Transcription and streamed response presentation with distinct live/completed treatment; keep text Room-local on Displays, inline on the TUI, and absent from the Puck.

UX-DR10: Implement the Follow-up Window with an opening cue, readable Listening state, eight-second timeout, closing cue, wake detection return, and silent exact-`stop` close without a replacement turn.

UX-DR11: Implement the Ambient Surface with Room-filtered Immich imagery, a neutral fallback when no photo matches, and an overlay/card contrast layer behind load-bearing text; ambience must not become a notification wall.

UX-DR12: Implement the household-wide visual-only Departure Card with event name, location, calculated departure time, countdown, and `estimated` label; recompute on time/location changes, clear on cancellation/event start, and never add sound or manual dismissal.

UX-DR13: Implement persistent Disconnected/Unavailable presentation that preserves clearly stale cached context when useful, never looks active or ready, and exposes Retry only where supported; Retry reconnects only and never resembles replay or send.

UX-DR14: Implement Device Discovery as a list of discovered versus approved Devices; selecting a discovered Device shows Connecting while it remains unconfigured, inert, and unable to capture or access Hermes.

UX-DR15: Implement the ordered Device Setup presentation: Discover, Connect/approval, Room, Wake Mappings, and Ready; show success on iOS and the Device, block duplicate mappings, and label pending/offline configuration as pending rather than ready.

UX-DR16: Implement Device Details with readable status, credential/configuration boundaries, destructive Disconnect confirmation, visible publish/verification state, and explicit re-enrollment after revocation.

UX-DR17: Implement Local History only on intentional iOS/TUI Client surfaces; do not expose or rehydrate conversation history on Pucks, Displays, or the Media Server.

UX-DR18: Implement Prompt Mirror as a visible Hermes clarification/approval state that waits for a spoken answer through the active Puck, ESP32 Touch Display, W/K browser voice surface, or Client; passive room Displays have no touch prompt action in v1.

UX-DR19: Implement the TUI Header with active Profile identity and shared phase semantics while keeping diagnostics an engineering capability rather than the household journey.

UX-DR20: Implement child-readable state labels (`Ready`, `Heard`, `Listening`, `Working`, `Speaking`, `Unavailable`, `Stopped`) alongside technical labels; use live regions or announcements once per state transition, not once per transcript delta.

UX-DR21: Implement accessibility behavior: WCAG 2.2 AA contrast targets, reduced-motion static states, iPad accessible DOM status mirror and completion announcement, iOS VoiceOver order Profile → state → response/Transcription → action with focus restoration, TUI keyboard-equivalent recovery actions, and non-actionable Display prompt mirrors.

UX-DR22: Adapt the shared semantics to the ReSpeaker/TFT Puck, 1024×600 ESP32-S3/LVGL Display, Safari/Guided Access iPad kiosk, native iOS Client, companion macOS behavior, TUI, and native macOS simulator without encoding one-room assumptions or requiring identical geometry.

UX-DR23: Preserve the interaction anti-pattern guardrails: no wrong-profile response, duplicate wake, false phase/recovery claim, cross-Room text, disconnected capture/fallback, replaying Retry, Puck transcript, audible Departure Card, touch prompt response, chain-of-thought display, or pre-echo-safe barge-in.

### FR Coverage Map

FR1: Epic 1 - Authorized Puck/ESP32 Touch/WK doorway or Client starts a Hermes turn.
FR2: Epic 1 surface stories + Epic 2 passive mirror - Voice-capable Puck/ESP32 Touch/WK doorway captures; room Displays mirror live capture state and Transcription.
FR3: Epic 1 - Doorways expose honest Turn Phases.
FR4: Epic 1 - Hermes response is delivered through Puck, ESP32 Touch, W/K, iOS, TUI, and passive display surfaces.
FR5: Epic 1 - Configured voice doorways provide bounded follow-up listening and silent stop where supported, including W/K's advertised browser capability.
FR6: Epic 1 - Reconnect starts a clean Session without replay.
FR7: Epic 3 - Wake Mappings are unique and profile-specific.
FR8: Epic 3 - Revoked or unavailable identity fails closed.
FR9: Epic 3 - One Device wins a simultaneous wake.
FR10: Epic 2 - Displays render Room-filtered Ambient Surface content.
FR11: Epic 1 surface stories for active ESP32 Touch and W/K delivery; Epic 2 passive Displays mirror only the owning Room's Active Turn.
FR12: Epic 2 - Displays show honest Disconnected State and useful cached context.
FR13: Epic 4 - Calendar events qualify only with usable location and travel data.
FR14: Epic 4 - Qualifying events promote a shared visual Departure Card.
FR15: Epic 4 - Departure Cards recompute and clear automatically.
FR16: Epic 3 - iOS discovers and connects unconfigured Devices.
FR17: Epic 3 - iOS guides Room, Wake Mapping, and Ready setup.
FR18: Epic 3 - iOS revokes Device access and requires re-enrollment.
FR19: Epic 1 - Verified recovery never silently resumes a turn.
FR20: Epic 5 - iOS provides an independent full conversation doorway.
FR21: Epic 5 - TUI provides an independent direct voice-chat doorway.
FR22: Epic 2 - Passive Displays mirror voice-only Hermes prompts without touch actions; the active Puck, ESP32 Touch Display, W/K browser voice surface, or Client supplies the spoken answer.

## Epic List

### Epic 1: Have a reliable Hermes conversation

A configured doorway can complete an honest voice turn, continue briefly after the response, and recover safely from transport loss. Epic 1 is decomposed into surface-specific delivery stories; shared session, display-state, and bounded-audio contracts are prerequisites rather than a hidden generic story.
**FRs covered:** FR1, FR3, FR4, FR5, FR6, FR19
**Natural dependency:** Establishes the normalized session and turn semantics consumed by later display and companion-doorway epics. It needs only an authorized configured doorway and can be validated with fake sessions plus the explicit live smoke path.

### Epic 2: See and trust what the room is doing

Passive Room Displays and the W/K iPad/web surface's room-context mode show calm ambient context, the owning Room's active conversation, visible prompts, and honest recovery state without becoming another assistant. W/K voice capture/audio and the ESP32 Touch Display's active voice capture, response rendering, and audio delivery remain Epic 1 surface work.
**FRs covered:** FR2, FR10, FR11, FR12, FR22
**Natural dependency:** Consumes Epic 1's turn events and the shared display contract; it can be developed and validated independently with display fixtures and does not require calendar or Device administration.

### Surface-specific Epic 2 story map — decision 2026-09-10

Epic 2 stories belong to the renderer or doorway that owns the visible
behavior. The shared `DisplaySnapshot` schema, reducer, Room filtering, and
normalized event feed are prerequisites, not an unowned closure story. A
passive Room Display is a role exercised by a Display renderer; it is not a
second W/K or iPad surface.

| Surface story key | Surface | Scope |
|---|---|---|
| `2-I-1` | iOS Client | Show the iOS doorway's capture acknowledgement and live Transcription participant state. |
| `2-I-2` | iOS Client | Show honest iOS disconnected/unavailable state without stale-turn replay. |
| `2-P-1` | ReSpeaker Puck | Expose the Puck's local capture, response, and status phases without putting transcript text on the TFT. |
| `2-P-2` | ReSpeaker Puck | Fail closed and show unavailable/disconnected status when the Puck or Hermes path is unavailable. |
| `2-E-1` | ESP32 Touch Display | Render the Room-scoped Ambient Surface in native LVGL. |
| `2-E-2` | ESP32 Touch Display | Render room-local active-turn state, live Transcription, and the touch doorway's observed response state. |
| `2-E-3` | ESP32 Touch Display | Mirror Hermes prompts without creating touch response actions or a second Session. |
| `2-E-4` | ESP32 Touch Display | Render honest disconnected state and safe cached context on the native Display. |
| `2-WK-1` | W/K browser voice-plus-display surface | Render the shared Room-scoped Ambient Surface for web and iPad deployment. |
| `2-WK-2` | W/K browser voice-plus-display surface | Render active capture, room-local Transcription, response, and phase state in the browser surface. |
| `2-WK-3` | W/K browser voice-plus-display surface | Mirror Hermes prompts without touch approval or a second Session. |
| `2-WK-4` | W/K browser voice-plus-display surface | Render honest disconnected state, cached context, and accessible recovery presentation. |
| `2-T-1` | TUI | Keep the direct TUI doorway's capture and phase state visible while a Room Display may mirror separately. |
| `2-T-2` | TUI | Keep TUI disconnect/recovery presentation honest without replaying an uncertain turn. |

The generic numeric Stories 2.1–2.5 below retain the original acceptance
language as the requirements template. The surface keys above are the delivery
identities for implementation and coverage; status in one row never closes
the other rows.

### Epic 3: Control household doorway identity and access

iOS can configure physical Devices and Wake Mappings, preserve profile isolation, revoke access, and select one authorized Device when several hear a wake.
**FRs covered:** FR7, FR8, FR9, FR16, FR17, FR18
**Natural dependency:** Uses the conversation/session boundary from Epic 1 but is independently testable with fake profiles, Devices, and relay endpoints; it enables trusted use of later room and companion journeys.

### Surface-specific Epic 3 story map — decision 2026-09-10

Epic 3 has two ownership boundaries in the pilot. iOS is the sole physical
Device control plane; the Puck owns the device-side identity, mapping, and
fail-closed enforcement. The initial pilot names the ReSpeaker Puck as the
affected physical target. ESP32 Touch, W/K, and TUI remain `N/A` for Epic 3
until a separate administration boundary is adopted rather than silently
borrowing the Puck story.

| Surface story key | Surface | Scope |
|---|---|---|
| `3-I-1` | iOS Settings | Discover and connect an unconfigured Device without granting access. |
| `3-I-2` | iOS Settings | Approve a Device and guide Room, Wake Mapping, and Ready setup. |
| `3-I-3` | iOS Settings | Validate unique Wake Mappings and Profile-specific publish state. |
| `3-I-4` | iOS Settings | Configure and expose deterministic single-Device wake arbitration. |
| `3-I-5` | iOS Settings | Show and enforce unavailable or revoked identity as a failed-closed state. |
| `3-I-6` | iOS Settings | Revoke access and require explicit verified re-enrollment. |
| `3-P-1` | ReSpeaker Puck | Advertise independently identifiable unconfigured state for discovery and connection. |
| `3-P-2` | ReSpeaker Puck | Apply approved Room, credential, and Wake Mapping configuration without becoming Ready early. |
| `3-P-3` | ReSpeaker Puck | Enforce the selected Wake Mapping and Profile before capture. |
| `3-P-4` | ReSpeaker Puck | Participate in single-winner wake arbitration and remain silent when it loses. |
| `3-P-5` | ReSpeaker Puck | Reject revoked, unavailable, or unverified identity before capture or submission. |
| `3-P-6` | ReSpeaker Puck | Retire revoked credentials and require the ordered setup flow on re-enrollment. |

The generic numeric Stories 3.1–3.6 below remain the acceptance template for
the paired iOS control-plane and Puck device-side slices. No other surface is
implicitly closed by either family.

### Epic 4: Know when the household needs to leave

Displays promote, update, and clear a consistent visual Departure Card from qualifying shared-calendar events without unsolicited audio.
**FRs covered:** FR13, FR14, FR15
**Natural dependency:** Consumes the display surface from Epic 2 and can be validated independently with calendar and route fixtures; it does not require a voice turn or Device enrollment.

### Surface-specific Epic 4 story map — decision 2026-09-10

Departure qualification is a shared calendar/travel prerequisite, not a
surface closure claim. Once a qualifying state exists, each Display family
owns its own rendering and lifecycle behavior.

| Surface story key | Surface | Scope |
|---|---|---|
| `4-C-1` | Shared calendar/travel evaluator | Qualify events only with usable location, route or estimate, family buffer, and effective threshold; label configured estimates. This is a shared prerequisite, not a Display surface story. |
| `4-E-1` | ESP32 Touch Display | Promote the household-wide Departure Card in native LVGL while preserving Room-local Active Turn precedence. |
| `4-E-2` | ESP32 Touch Display | Recompute and clear the native Departure Card on time, location, cancellation, and event-start changes. |
| `4-WK-1` | W/K browser voice-plus-display surface | Promote the same Departure Card in the shared web/iPad browser renderer without audio. |
| `4-WK-2` | W/K browser voice-plus-display surface | Recompute and clear the browser Departure Card while preserving active-turn precedence and accessible state. |

The generic numeric Stories 4.1–4.3 below retain the evaluator and lifecycle
acceptance language. `4-C-1` must be settled before either surface renderer
can be closed; E and W/K cells are then closed independently.

### Epic 5: Carry the Hermes relationship with you

iOS and the TUI provide independent portable and terminal conversation doorways with deliberate local history and shared phase semantics.
**FRs covered:** FR20, FR21
**Natural dependency:** Consumes Epic 1's session semantics but remains independently usable through configured Client sessions; diagnostics remain an engineering capability rather than a household prerequisite.

### Surface-specific Epic 5 story map — decision 2026-09-10

Epic 5 is already naturally surface-specific: the iOS and TUI doorways own
separate Sessions, presentation, and deliberate Local History boundaries.

| Surface story key | Surface | Scope |
|---|---|---|
| `5-I-1` | iOS Client | Use iOS as an independent typed and tap-to-speak conversation doorway with response audio, phase state, recovery, and Local History. |
| `5-T-1` | TUI | Use the TUI as an independent direct voice-chat gateway with inline response rendering, diagnostics, and deliberate local history. |

The existing numeric Stories 5.1 and 5.2 below remain stable aliases for
`5-I-1` and `5-T-1`; neither surface's implementation closes the other.

## Epic 1: Have a reliable Hermes conversation

A configured doorway can complete an honest voice turn, continue briefly after the response, and recover safely from transport loss. Epic 1 is decomposed into surface-specific delivery stories; shared session, display-state, and bounded-audio contracts are prerequisites rather than a hidden generic story.

**FRs covered:** FR1, FR3, FR4, FR5, FR6, FR19

### Surface-specific Epic 1 story map — decision 2026-09-10

The surface key is part of the story identity. A completed story closes only
the named surface; another surface's implementation is evidence, not closure.

| Surface story key | Surface | Scope |
|---|---|---|
| `I-1` to `I-3` | iOS | Authorized initiation; honest phases with response/audio delivery; fresh recovery without replay. |
| `P-1` to `P-4` | ReSpeaker Puck | Authorized wake/capture; status and response audio; bounded follow-up/`stop`; recovery. |
| `E-1` to `E-5` | ESP32 Touch Display | Authorized voice capture; native phase and streamed-response rendering; response audio delivery; bounded follow-up/`stop`; recovery without replay. |
| `WK-1` | Web/iPad | One shared W/K browser voice-plus-display surface for authorized capture, honest phases, streamed/completed response text, response audio, and delivery/error state. iPad is a deployment target, not a separate surface. |
| `T-1` to `T-4` | TUI | Existing local TUI authorization, phase/delivery, follow-up, and recovery slices. The historical numeric artifacts 1.1–1.4 remain stable aliases for these stories. |

The ESP32 Touch stories cannot be closed by the existing `DisplaySnapshot`
transport alone. The surface must capture voice and deliver response audio as
well as render its own response. Its implementation may use the Python
appliance/session adapter or a direct device adapter, but the choice must be
explicit; firmware must not become a second Hermes authority. The current
snapshot/action firmware path is foundation evidence only.

The following four numeric stories are retained as the local TUI delivery
record. New surface work must use the ownership map above rather than treating
one TUI story as global Epic 1 completion.

### Story 1.1: Start an authorized Hermes turn

As a household member using a configured Puck or Client,
I want an authorized wake or explicit initiation to bind to the selected Hermes Profile before capture or submission,
So that my request reaches the intended Hermes relationship and unauthorized paths fail closed.

**Covers:** FR1; NFR2, NFR4; architecture rules AD-1, AD-2, AD-3, AD-7, AD-8.

**Acceptance Criteria:**

**Given** a configured doorway with valid authorization and a verified Hermes handshake
**When** the Puck recognizes its configured wake or an authorized Client initiates a turn
**Then** the selected Hermes Profile is fixed before Puck capture or Hermes submission begins
**And** the turn is owned by that doorway’s Hermes Session.

**Given** an initiation lacks authorization, targets an unavailable identity, or has no verified handshake
**When** the user attempts to start the turn
**Then** the doorway fails closed before capture or submission
**And** it exposes a local unavailable/error state without selecting a fallback Profile.

**Given** a valid initiation is accepted
**When** the session boundary begins the turn
**Then** the front end receives normalized session/turn events through the session contract
**And** it does not parse Hermes wire frames or invent a separate assistant response.

**Given** a valid initiation is accepted
**When** the turn request is submitted
**Then** exactly one initial turn is submitted for that initiation
**And** the request is not automatically retried after an uncertain transport failure.

### Story 1.2: Render honest turn phases and response delivery

As a household member using any supported Hermes doorway,
I want every participating front end to reflect the same observed turn phase and response,
So that the Puck, iOS Client, TUI, and room-display mirror never tell different stories about one conversation.

**Covers:** FR3, FR4; NFR1, NFR2, NFR5; normalized session events, explicit state ownership, shared semantic state, and front-end-specific presentation.

**Acceptance Criteria:**

**Given** an accepted turn and normalized lifecycle events
**When** capture, processing, response, and completion events arrive
**Then** each participating front end maps them to the same canonical phase semantics
**And** no front end advances or regresses before the observed event warrants it.

**Given** streamed response text and audio for the active turn
**When** deltas and audio chunks arrive
**Then** text-capable surfaces render one coherent response for that turn
**And** voice-capable surfaces present audio from that same Hermes response without duplicating or inventing content.

**Given** response text completes but audio cannot start or fails
**When** the turn reaches its terminal state
**Then** voice-capable surfaces report audio as unavailable while preserving the completed text
**And** display-only surfaces show the supported semantic state without implying that they are playing audio.

**Given** an unknown, stale, or differently identified event
**When** it is received by the session or a front end
**Then** it cannot mutate the active turn’s phase or response
**And** any diagnostic remains content-safe.

### Story 1.3: Continue with bounded follow-up and exact `stop`

As a household member speaking through the Puck,
I want a short follow-up window after a wake-triggered response,
So that I can continue naturally without repeating the wake phrase or leaving the microphone open indefinitely.

**Covers:** FR5; NFR2, NFR3; bounded capture, explicit shutdown, and session ownership.

**Acceptance Criteria:**

**Given** a wake-triggered turn completes
**When** follow-up listening begins
**Then** the Puck listens for the configured bounded window—8 seconds by default—without requiring another wake phrase.

**Given** the user speaks a non-empty phrase during that window
**When** local capture and transcription complete
**Then** exactly one follow-up turn is submitted to the same Hermes Session and selected Profile.

**Given** the transcription is exactly `stop`, ignoring normal terminal punctuation
**When** it occurs during the initial wake capture or follow-up window
**Then** capture closes locally and silently
**And** no Hermes turn is submitted and no assistant response is requested.

**Given** the follow-up window expires, capture is empty, or transcription produces no usable phrase
**When** the window closes
**Then** the Puck returns to wake-word detection or idle state
**And** it does not submit an empty turn.

**Given** the phrase contains more than `stop`, or the user uses `Ctrl+R`
**When** it is captured
**Then** it follows the ordinary turn path rather than being treated as the silent stop command.

### Story 1.4: Recover without replaying an uncertain turn

As a household member whose Hermes connection is interrupted,
I want the doorway to recover into a fresh verified Session,
So that I can continue safely without duplicate requests, stale responses, or silent resumption.

**Covers:** FR6, FR19; NFR2, NFR4; explicit recovery and shutdown, session identity, and stale-event isolation.

**Acceptance Criteria:**

**Given** an active turn loses its transport before a definitive terminal event
**When** recovery begins
**Then** the active turn is treated as uncertain
**And** it is never automatically replayed.

**Given** bounded reconnection succeeds
**When** a new verified Hermes handshake completes
**Then** the doorway creates a fresh Hermes Session
**And** it clears stale turn state and returns to a ready state.

**Given** prompts were not confirmed as sent
**When** recovery completes
**Then** they remain queued in FIFO order for explicit later submission.

**Given** a turn may have reached Hermes before transport loss
**When** recovery completes
**Then** the user must explicitly initiate a new turn
**And** the doorway never silently resumes the old one.

**Given** retries are exhausted or the new handshake fails authorization or identity checks
**When** recovery ends
**Then** the doorway remains visibly disconnected or unavailable
**And** it does not claim completion, playback, or readiness.

**Given** late events or audio from the prior Session arrive after recovery
**When** they are received
**Then** they are discarded without mutating the new Session’s state, transcript, or audio.

## Epic 2: See and trust what the room is doing

Passive Room Displays and the W/K iPad/web surface's room-context mode show calm ambient context, the owning Room's active conversation, visible prompts, and honest recovery state without becoming another assistant. W/K voice capture/audio and the ESP32 Touch Display's active voice capture, response rendering, and audio delivery remain Epic 1 surface work.

**FRs covered:** FR2, FR10, FR11, FR12, FR22

### Story 2.1: Keep each Display in its Room-scoped Ambient Surface

As a household member looking at a room Display,
I want its idle imagery to follow that Room’s presentation policy,
So that the Display feels calm and personal without exposing another Room’s content or inventing setup problems.

**Covers:** FR10; NFR3, NFR5; Room-scoped state, shared Display semantics, and platform-specific presentation.

**Acceptance Criteria:**

**Given** a Display is idle and no higher-priority household state is active
**When** its Ambient Surface renders
**Then** it shows Immich photos selected by that Display’s Room-level face filters.

**Given** the Room has no matching Immich photos
**When** the Ambient Surface renders
**Then** it shows a neutral ambient background
**And** it does not widen the filters or expose a setup prompt merely because no photo matches.

**Given** an Active Turn, Departure Card, or other higher-priority state becomes active
**When** the Display updates
**Then** the Ambient Surface yields without competing with or overwriting that state.

**Given** the higher-priority state ends and no other priority state remains
**When** the Display returns to idle
**Then** it returns to the correct Room-scoped Ambient Surface.

**Given** two Displays belong to different Rooms
**When** their Ambient Surfaces render
**Then** each uses only its own Room policy and cached content.

**UX expectation:** ESP32-S3 Touch and W/K browser deployments share the same ambient semantics while adapting layout to their platforms; ambience remains quiet and never competes with load-bearing state.

### Story 2.2: Show live capture state and transcription

As a household member speaking through a Puck, ESP32 Touch Display, iOS Client, or TUI,
I want the relevant doorway and owning Room Display to show capture progress and live words as they arrive,
So that I know the system is listening rather than waiting in mysterious silence.

**Covers:** FR2; NFR1, NFR2, NFR3, NFR5; transient audio, Media Server boundaries, and shared capture-state semantics.

**Acceptance Criteria:**

**Given** an authorized wake or explicit turn initiation is accepted
**When** capture begins
**Then** the active voice doorway shows its capture acknowledgement and Listening state
**And** the owning Room Display mirrors that state
**And** iOS/TUI show their corresponding capture state.

**Given** partial transcription becomes available
**When** words arrive
**Then** the Room Display, W/K browser surface, iOS Client, and TUI update live rather than waiting for capture to finish.

**Given** Puck, ESP32 Touch, or W/K browser capture is active
**When** a passive Room Display mirrors it
**Then** the Display receives transcription/state information only
**And** it does not capture, speak, or create another Hermes Session.

**Given** capture ends or is cancelled
**When** the capture stream closes
**Then** Listening ends and the doorway advances to the appropriate next phase
**And** it does not leave a stale Listening indicator.

**Given** the capture path is cancelled, empty, or unavailable
**When** cleanup completes
**Then** no empty Hermes turn is submitted
**And** raw audio/transcription is not retained by the Puck, Display, or Media Server.

**Given** normal pilot conditions
**When** a wake is recognized
**Then** the median wake acknowledgement and visible Puck status meet the roughly one-second working target.

### Story 2.3: Mirror only the owning Room’s Active Turn

As a household member near a Room Display,
I want that Display to mirror the conversation happening in its Room,
So that the exchange is visible without leaking into other rooms or creating a second assistant.

**Covers:** FR11; NFR2, NFR3, NFR5; room-local state, authoritative response ownership, and the shared Display contract.

**Acceptance Criteria:**

**Given** a Puck, ESP32 Touch, or W/K browser voice doorway is assigned to a Room and has an Active Turn
**When** normalized turn events arrive
**Then** that Room’s Display shows the live Transcription, canonical phase, streamed response text, and active Hermes Profile.

**Given** multiple Displays belong to different Rooms
**When** one voice doorway has an Active Turn
**Then** only the owning Room’s Display receives or renders that conversation text and state.

**Given** a passive Display mirrors an Active Turn
**When** the turn is in progress
**Then** the Display does not capture audio, speak the response, create another Hermes Session, or expose a touch-based response action.

**Given** an ESP32 Touch Display is the selected active doorway
**When** the turn is in progress
**Then** its Epic 1 surface owns capture, response rendering, and response audio delivery
**And** any other Room Display remains a passive mirror.

**Given** the W/K browser voice surface is the selected active doorway
**When** the turn is in progress
**Then** its Epic 1 surface owns browser capture, response rendering, and response audio delivery
**And** any other Room Display remains a passive mirror.

**Given** a household-wide Departure Card is active
**When** the owning Room has an Active Turn
**Then** that Room’s Active Turn takes priority on its Display
**And** other Displays retain the Departure Card.

**Given** the Active Turn reaches its terminal state, including follow-up close or local stop
**When** no higher-priority state remains
**Then** the completed response remains visible where supported
**And** the Display returns to its Room’s Ambient Surface.

**Given** a stale event or event for another Room or turn arrives
**When** the Display processes it
**Then** it does not alter the current Room’s conversation state.

### Story 2.4: Mirror Hermes prompts without becoming another assistant

As a household member near a Room Display,
I want Hermes clarification and approval prompts to be visible while I answer by voice,
So that the room stays informed without creating a second prompt-control surface.

**Covers:** FR22; NFR2, NFR3, NFR5; active-Session ownership, room-local mirroring, and passive Display behavior.

**Acceptance Criteria:**

**Given** Hermes sends a clarification or approval prompt for the active Session
**When** the prompt event arrives
**Then** the owning Room Display shows the prompt text and that a spoken answer is awaited.

**Given** a prompt is visible
**When** the user answers through the active Puck, ESP32 Touch Display, W/K browser voice surface, or Client
**Then** the answer follows that existing Hermes Session
**And** the Display remains a mirror only.

**Given** a prompt is visible
**When** the user interacts with the Display
**Then** no touch action can approve, reject, cancel, submit, or create another Hermes turn.

**Given** a prompt belongs to another Room or Session
**When** the Display receives it
**Then** it does not render the prompt or alter its current state.

**Given** Hermes resolves, cancels, or replaces the prompt
**When** the prompt state changes
**Then** the Display clears or updates the prompt without leaving stale controls or text.

**Given** the prompt is displayed
**When** its text is rendered
**Then** the Display presents Hermes’ prompt faithfully without authoring, paraphrasing, or correcting it.

### Story 2.5: Stay useful and honest when disconnected

As a household member looking at a Display during a service outage,
I want the Display and associated doorway to show an honest unavailable state while preserving safe cached context,
So that the household understands what is offline without hearing a fabricated answer or triggering accidental capture.

**Covers:** FR12; NFR2, NFR3, NFR4, NFR5; explicit recovery, transient data, and truthful failure state.

**Acceptance Criteria:**

**Given** the Media Server, Hermes connection, or Display path becomes unavailable
**When** the failure is detected
**Then** the Display shows a persistent visual Disconnected or Unavailable state
**And** it does not remain indefinitely in Thinking.

**Given** cached Ambient Surface or Departure Card content is available
**When** the Display enters Disconnected State
**Then** it may continue showing that content with a clear stale/cached indication.

**Given** the doorway is disconnected or unavailable
**When** a wake or capture attempt occurs
**Then** the Puck captures no audio, submits no Hermes turn, and speaks no local fallback status phrase.

**Given** the Display is disconnected
**When** a user interacts with it
**Then** it does not present a touch-based retry or turn-control action
**And** retry remains an explicit Client action.

**Given** the Hermes path returns
**When** verified recovery completes
**Then** the Display clears Disconnected State
**And** no Puck or Client silently reopens capture or resumes the unresolved turn.

**Given** recovery fails or identity remains unavailable
**When** the recovery attempt ends
**Then** the Display remains visibly disconnected or unavailable.

## Epic 3: Control household doorway identity and access

iOS can configure physical Devices and Wake Mappings, preserve Profile isolation, revoke access, and select one authorized Device when several hear a wake.

**FRs covered:** FR7, FR8, FR9, FR16, FR17, FR18

### Story 3.1: Discover unconfigured Devices safely

As a household administrator using iOS Settings,
I want to discover and connect to a new household Device,
So that I can identify it clearly before granting it any ability to capture audio or use Hermes.

**Covers:** FR16; NFR4, NFR5; iOS as the sole physical-Device control plane and discovery/approval separation.

**Acceptance Criteria:**

**Given** Amanda taps `Add` in iOS Settings
**When** discovery runs
**Then** unconfigured Devices appear in a clearly separate discovery list from approved Devices.

**Given** a Device is discovered but not approved
**When** it appears or is selected
**Then** it remains visibly unconfigured and inert
**And** it cannot capture audio, wake, or use Hermes.

**Given** Amanda selects a discovered Device
**When** connection is attempted
**Then** iOS shows a connecting state while the Device remains unconfigured.

**Given** connection succeeds
**When** the Device confirms the connection
**Then** success is visible on both iOS and the Device
**And** success does not depend on a silent list refresh.

**Given** LAN discovery is unavailable or blocked
**When** Amanda chooses the fallback
**Then** QR or manual pairing can identify the same unconfigured Device without granting access automatically.

**Given** discovery or connection fails
**When** the attempt ends
**Then** iOS shows an actionable failure
**And** the Device remains inert and unapproved.

### Story 3.2: Approve and configure a Device

As a household administrator using iOS Settings,
I want to approve a discovered Device and configure it in a clear order,
So that it cannot become an active household doorway before its Room and wake behavior are known.

**Covers:** FR17; NFR4, NFR5; individual revocable credentials, explicit approval, and visible setup state.

**Acceptance Criteria:**

**Given** a connected but unconfigured Device
**When** Amanda explicitly approves it
**Then** iOS grants authorization and provisions an individual revocable Device Credential
**And** the Device remains inactive until setup completes.

**Given** approval succeeds
**When** setup begins
**Then** iOS guides the user through the ordered steps `Room` → `Wake Mappings` → `Ready`.

**Given** Room assignment is incomplete
**When** the Device is powered or reachable
**Then** it remains visibly pending
**And** it cannot wake, capture, or submit to Hermes.

**Given** Room assignment is complete
**When** one or more valid Wake Mappings are configured
**Then** iOS and the Device show the pending setup state rather than implying readiness.

**Given** all required setup steps complete
**When** Amanda confirms `Ready`
**Then** iOS and the Device show matching success indicators
**And** the Device may operate as an active doorway.

**Given** setup fails, is offline, or has unverified changes
**When** the setup attempt ends
**Then** the Device remains inactive
**And** iOS labels the configuration as pending or failed rather than applied.

### Story 3.3: Keep Wake Mappings unique and Profile-specific

As a household administrator,
I want each Wake Mapping to resolve unambiguously to one Hermes Profile,
So that a recognized phrase can never route to the wrong identity.

**Covers:** FR7; NFR2, NFR4; profile isolation, configuration validation, and verified publish state.

**Acceptance Criteria:**

**Given** multiple Wake Mappings are configured across the household
**When** a new or edited wake phrase would duplicate or ambiguously target another Profile
**Then** iOS rejects it before publishing.

**Given** a valid Wake Mapping is saved
**When** it is published to a Device
**Then** the mapping resolves to exactly one Hermes Profile.

**Given** a Wake Mapping is edited
**When** the edit is pending, offline, or fails validation
**Then** the previously verified mapping remains active
**And** the pending edit is visibly labeled as unapplied.

**Given** a Wake Mapping is successfully published
**When** its Device recognizes the phrase
**Then** the selected Hermes Profile is fixed before capture begins.

**Given** a Device has several valid Wake Mappings
**When** one configured phrase is recognized
**Then** only that phrase’s Profile is eligible for the resulting turn.

**Given** a mapping references a different Profile than the one selected for the recognized phrase
**When** the Device evaluates the mapping
**Then** it cannot substitute that Profile or fall back silently.

### Story 3.4: Select one Device for a simultaneous wake

As a household member in range of multiple authorized Devices,
I want one Device to own a recognized wake,
So that a single phrase never creates duplicate captures, turns, or responses.

**Covers:** FR9; NFR2, NFR4; proximity arbitration, configured priority, and single-turn ownership.

**Acceptance Criteria:**

**Given** multiple authorized Devices hear the same configured Wake Mapping within the arbitration window
**When** proximity is evaluated
**Then** the closest eligible Device is selected as the owner.

**Given** two or more eligible Devices have an effective proximity tie
**When** arbitration resolves
**Then** configured Device priority selects the owner deterministically.

**Given** a Device lacks a valid mapping, credential, or available Profile
**When** arbitration evaluates candidates
**Then** that Device is excluded before acknowledgement or capture.

**Given** one Device wins arbitration
**When** ownership is announced
**Then** only the selected Device acknowledges, captures, submits, and plays the response.

**Given** a Device loses arbitration
**When** the winner is selected
**Then** the losing Device cancels any pending acknowledgement or capture
**And** it returns to its prior listening/idle state without submitting audio or a Hermes turn.

**Given** arbitration produces no eligible winner
**When** the arbitration window closes
**Then** no Device captures, acknowledges as owner, or submits a turn.

### Story 3.5: Fail closed for revoked or unavailable identities

As a household member using a configured Device,
I want an unavailable or revoked Hermes Profile to stop the doorway before capture,
So that the system never sends speech to the wrong identity or invents a fallback.

**Covers:** FR8; NFR2, NFR4; credential enforcement, identity verification, and fail-closed behavior.

**Acceptance Criteria:**

**Given** a recognized Wake Mapping points to a revoked or unavailable Hermes Profile
**When** the Device evaluates it
**Then** the Device shows a visible Unavailable or Disconnected state before capture begins.

**Given** the mapped Profile cannot be verified
**When** a wake is recognized
**Then** the Device captures no audio, sends no audio payload, and submits no Hermes turn.

**Given** other Wake Mappings on the Device point to valid Profiles
**When** an unavailable mapping is triggered
**Then** the Device does not substitute another Profile or fall back silently.

**Given** a powered Device has had its credential revoked
**When** it attempts to operate
**Then** Hermes access remains denied even if the Device is still reachable.

**Given** the Profile or credential later becomes potentially available
**When** the Device has not completed verified recovery or re-enrollment
**Then** it remains unavailable and does not silently reactivate.

### Story 3.6: Revoke access and require verified re-enrollment

As a household administrator,
I want to disconnect a Device and revoke its access explicitly,
So that a powered Device cannot continue operating until it has been trusted again.

**Covers:** FR18; NFR2, NFR4; credential revocation, visible consequence, and explicit re-enrollment.

**Acceptance Criteria:**

**Given** Amanda opens approved Device details
**When** she taps `Disconnect`
**Then** iOS shows a confirmation explaining that the Device will stop working until it is re-enrolled.

**Given** Amanda confirms the disconnect
**When** revocation succeeds
**Then** the Device Credential and Hermes access are revoked
**And** iOS and the Device show the revoked or unavailable state.

**Given** a powered Device has been revoked
**When** it attempts to wake or operate
**Then** it captures no audio and submits no Hermes turn.

**Given** a revoked Device remains reachable on the network
**When** it reconnects
**Then** reachability does not restore access or readiness.

**Given** Amanda wants to restore the Device
**When** re-enrollment begins
**Then** it requires explicit approval and the ordered setup flow again
**And** it does not silently restore the old credential.

**Given** revocation or re-enrollment cannot be confirmed
**When** the operation ends
**Then** iOS shows a visible pending or failed state
**And** it does not present the Device as safely ready.

## Epic 4: Know when the household needs to leave

Displays promote, update, and clear a consistent visual Departure Card from qualifying shared-calendar events without unsolicited audio.

**FRs covered:** FR13, FR14, FR15

### Story 4.1: Qualify events using usable travel context

As a household member relying on the household calendar,
I want each event evaluated only when its travel information is usable,
So that the system never invents a leave time or countdown.

**Covers:** FR13; NFR2, NFR5; per-event evaluation, household-home routing, and explicit estimate labeling.

**Acceptance Criteria:**

**Given** a shared family-calendar event has a location and a usable live route from the household home
**When** it is evaluated
**Then** it produces a qualifying travel context and calculates departure from event start, route duration, and the family buffer.

**Given** a live route is unavailable but a configured travel estimate is usable
**When** the event is evaluated
**Then** the configured estimate is used
**And** the resulting context is visibly labeled `estimated`.

**Given** an event has no location, no usable live route, and no usable configured estimate
**When** it is evaluated
**Then** it remains ordinary calendar context
**And** it produces no departure countdown or card candidate.

**Given** multiple calendar events exist
**When** they are evaluated
**Then** each event is qualified independently
**And** one unusable event does not invalidate another event with usable travel context.

### Story 4.2: Promote a household-wide Departure Card

As a household member,
I want every Display to show the same departure information when an event becomes actionable,
So that the household can leave on time without an unsolicited announcement.

**Covers:** FR14; NFR2, NFR5; shared Display state, threshold precedence, and visual-only behavior.

**Acceptance Criteria:**

**Given** an event has qualifying travel context and crosses its effective departure threshold
**When** promotion occurs
**Then** every Display receives the same Departure Card state containing the event name, location, calculated departure time, and countdown.

**Given** a qualifying event has no event-level threshold override
**When** its threshold is evaluated
**Then** the household default departure threshold applies.

**Given** a qualifying event has an event-level threshold override
**When** its threshold is evaluated
**Then** that override affects only the event
**And** it does not change thresholds for other events.

**Given** a Display is showing its Ambient Surface
**When** the Departure Card is promoted
**Then** the card replaces ambient imagery with the shared visual state.

**Given** a Room Display is showing a higher-priority Active Turn
**When** the Departure Card is promoted
**Then** that Room preserves the Active Turn until its terminal state
**And** other Displays show the card.

**Given** a Departure Card is displayed
**When** the household is notified
**Then** the notification remains visual-only
**And** it does not trigger an unsolicited Puck announcement or audio.

**Given** the qualifying travel context used a configured estimate
**When** the card renders
**Then** it retains the visible `estimated` label.

### Story 4.3: Recompute and clear Departure Cards automatically

As a household member relying on a Departure Card,
I want it to stay synchronized with calendar changes and disappear when it is no longer actionable,
So that the household never follows stale departure information.

**Covers:** FR15; NFR2, NFR5; synchronized Display state, automatic lifecycle transitions, and no manual dismissal.

**Acceptance Criteria:**

**Given** a Departure Card is active
**When** the event time or location changes
**Then** the system recomputes the departure time and countdown
**And** every Display receives the same updated card.

**Given** an active event is cancelled
**When** the cancellation is received
**Then** every Display clears the Departure Card.

**Given** the event reaches its start time
**When** the event-start transition occurs
**Then** every Display clears the Departure Card and returns to its Ambient Surface when no higher-priority state remains.

**Given** a Room Display is still completing a higher-priority Active Turn
**When** the card clears or updates
**Then** that turn remains unaffected
**And** the Display returns to the correct next state afterward.

**Given** a Departure Card has been cleared by cancellation or event start
**When** the household views any Display
**Then** no stale countdown or manual-dismiss control remains.

## Epic 5: Carry the Hermes relationship with you

iOS and the TUI provide independent portable and terminal conversation doorways with deliberate local history and shared phase semantics.

**FRs covered:** FR20, FR21

### Story 5.1: Use iOS as an independent conversation doorway

As a household member using the iOS Client,
I want to start typed or tap-to-speak conversations through my own Hermes Session,
So that iOS remains a complete doorway with clear state, audio, transcript, and local continuity.

**Covers:** FR20; NFR1, NFR2, NFR3, NFR4, NFR5; independent Session ownership, active Profile visibility, and intentional Local History.

**Acceptance Criteria:**

**Given** the iOS Client has valid configuration and authorization
**When** Amanda starts a tap-to-speak turn
**Then** iOS creates or uses its own Hermes Session
**And** it shows the active Profile before capture begins.

**Given** a tap-to-speak turn is active
**When** capture, processing, response, and playback events arrive
**Then** iOS shows the corresponding Listening, Thinking, Speaking, and completion states without advancing early.

**Given** Amanda submits a typed prompt
**When** the turn is sent
**Then** it follows the same iOS Hermes Session
**And** it receives the corresponding Hermes response without merging with a Puck, Display, TUI, or other Client Session.

**Given** Hermes returns response text and audio
**When** they stream
**Then** iOS shows the transcript and plays the same Hermes response without replacing it with local fallback prose.

**Given** a turn completes successfully
**When** Local History is updated
**Then** the completed conversation is retained intentionally on iOS
**And** raw audio is not stored.

**Given** transport loss interrupts a turn
**When** iOS reconnects
**Then** Retry reconnects only
**And** the unresolved turn is not replayed and a fresh explicit initiation is required.

**Given** permission, authorization, or Profile verification fails
**When** Amanda attempts a turn
**Then** iOS shows the failure
**And** it captures or submits no audio.

### Story 5.2: Use the TUI as an independent direct voice-chat gateway

As a household member using the TUI,
I want to start direct voice conversations through the TUI’s own Hermes Session,
So that the terminal remains a complete doorway with shared semantics and useful engineering visibility.

**Covers:** FR21; NFR1, NFR2, NFR3, NFR4, NFR5; independent Session ownership, terminal-specific presentation, and deliberate local history.

**Acceptance Criteria:**

**Given** the TUI has valid configuration and authorization
**When** Amanda starts a voice turn, including with `Ctrl+R`
**Then** the TUI uses its own Hermes Session
**And** it shows the active Profile in the header.

**Given** a TUI voice turn is active
**When** capture, transcription, processing, response, playback, and completion events arrive
**Then** the TUI exposes the same canonical phase semantics without blocking its event loop or advancing early.

**Given** Hermes streams response text
**When** deltas arrive
**Then** the TUI renders one coherent inline response rather than one transcript entry per delta.

**Given** Hermes returns response audio and text
**When** they stream
**Then** the TUI presents the same Hermes response
**And** it never replaces it with local fallback prose.

**Given** the TUI conversation completes
**When** local history is retained
**Then** it is deliberate and local to the TUI
**And** Puck, Display, and Media Server state are not imported into it.

**Given** diagnostics are enabled
**When** protocol or turn details are shown
**Then** they remain content-safe engineering detail
**And** they are not required for the household conversation journey.

**Given** transport loss interrupts a turn
**When** the TUI reconnects
**Then** Retry reconnects only
**And** the unresolved turn is not replayed and a fresh explicit prompt is required.

**Given** the TUI and another doorway are active simultaneously
**When** both receive events
**Then** their Sessions, transcripts, and response states remain isolated.
