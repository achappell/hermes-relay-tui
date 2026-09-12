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

FR1: A configured Puck, ESP32 Touch Display, or enabled W/K browser voice surface accepts its supported authorized voice initiation, and an authorized iOS Client, Android Client, or TUI accepts an explicit user-initiated turn.

FR2: The active Puck, ESP32 Touch Display, or W/K browser voice surface shows its capture acknowledgement and Listening phase; a passive room Display mirrors the owning Room's Listening phase and live Transcription; iOS and TUI show corresponding capture state.

FR3: Each supported doorway exposes the appropriate Turn Phase—heard, listening, transcribing, thinking, buffering, speaking, complete, or Disconnected State—without presenting a later phase early.

FR4: The Puck, ESP32 Touch Display, W/K browser voice surface, iOS Client, or Android Client speaks the Hermes response; active text-capable surfaces render their own response text, passive room Displays stream the same room-local response text, and the TUI renders the conversation through its terminal surface.

FR5: After each response, a configured voice doorway with a wake-capture adapter reopens a bounded silence window without requiring another wake phrase, and continues to do so until an explicit exit; the bound governs each window rather than the number of windows. The active Puck's v1 window is eight seconds and the W/K browser surface uses its advertised bounded capability. Exactly “stop” during capture or follow-up closes the local window silently, as do silence, failure, transport loss, and disarm. Pre-wake idle remains waiting for the wake phrase, and a surface without a wake-capture adapter opens no follow-up.

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

FR16: From iOS or Android Settings, Amanda can discover an unconfigured Device, select it, see a connecting state, and see success indicators on the selected Client and the Device after connection.

FR17: After connection success, iOS or Android guides Room assignment, one or more Wake Mappings, and final ready confirmation; the Device cannot become an active household doorway before setup completes.

FR18: From Device details in iOS or Android, Amanda can confirm Disconnect to revoke the Device Credential and Hermes access; the powered Device cannot wake, capture, or submit until explicitly re-enrolled.

FR19: When the Hermes path returns, an authorized Device reconnects and clears Disconnected State only after verified recovery; it does not reopen capture or submit a pending turn, and failed recovery remains visibly disconnected.

FR20: The iOS and Android Clients start voice turns by tap-to-speak and support typed turns through their own Hermes Sessions, showing listening, thinking, and speaking indicators and retaining the conversation in per-profile mobile Local History.

FR21: The TUI starts voice conversation through its own Hermes Session and renders conversation and response state without becoming a second assistant; diagnostic detail is not required for the household journey.

FR22: A passive room Display mirrors an active Hermes clarification or approval prompt while a free-text answer follows the active doorway's Hermes Session; passive Displays never become prompt owners.

FR23: When Hermes emits a bounded typed choice object, the active ESP32 Touch Display, direct-use W/K browser/iPad surface, and TUI render native `choose` and `explore` actions; `choose` commits an option, `explore` requests detail without committing, passive Displays mirror read-only, and the Puck exposes no choice UI.

### NonFunctional Requirements

NFR1: Wake acknowledgement and visible Puck status should appear in roughly one second; first spoken Hermes audio should begin in roughly four seconds after speech ends.

NFR2: Supported surfaces expose the actual Turn Phase, avoid duplicate Active Turns, and recover from transport loss without replaying captured speech.

NFR3: Raw Puck and ESP32 Touch audio remain transient on the home LAN; the Media Server/audio bridge retains no transcripts; only intentional iOS/Android/TUI Local History may persist by default.

NFR4: Every Device uses an individual revocable Device Credential, and unapproved, revoked, or unavailable identity fails closed before capture.

NFR5: ESP32-S3 Touch and W/K Web/iPad surfaces consume the same visual semantics for Ambient Surface, Active Turn, Departure Card, and Disconnected State; each voice-enabled surface additionally owns its voice capture and response-audio path.

NFR6: Typed choice actions are bound to the current Hermes Session, turn, object, option, advertised capability, and freshness context; accepted actions are idempotent, transcript-visible, and rejected safely when stale, unsupported, expired, replaced, or duplicated.

### Additional Requirements

- Use ports-and-adapters with functional cores. The Python core owns Hermes protocol normalization, session/turn lifecycle, configuration, and reusable local I/O ports; the portable C display core owns bounded display state and action rules.
- Core modules must not import Textual or another front-end framework, assume a terminal, or import app.py, home_display/, browser code, or firmware. Front ends depend on SessionProtocol; display-capable front ends also consume the shared display contract.
- Keep one owner for each state domain: HermesSession owns connection/capabilities/turn facts; appliance coordinators own local device lifecycle and snapshots; shared/display owns reducer validation and stale-sequence rejection; surface-local drafts, queues, presentation, and optional history stay local.
- Keep Hermes wire behavior behind client.py and session.py. Front ends consume normalized events and typed errors rather than parsing wire frames or inventing payloads; a turn that may have reached Hermes is never automatically replayed.
- Treat display_snapshot.schema.json, display_action.schema.json, and fixtures as the versioned cross-target contract. The portable C reducer is semantic authority; unknown fields are ignored, malformed known fields are rejected, display epochs establish baselines, sequences increase strictly within an epoch, and typed actions require advertised capability, current-state validity, object/turn freshness, and reducer acceptance.
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

UX-DR6: Show the active Hermes Profile from `heard` acknowledgement through completion on the Room Display and in iOS/Android/TUI headers; identify routing without implying answer correctness, and do not require the Puck to speak the profile name.

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

UX-DR17: Implement Local History only on intentional iOS/Android/TUI Client surfaces; do not expose or rehydrate conversation history on Pucks, Displays, or the Media Server.

UX-DR18: Implement Prompt Mirror as a visible Hermes clarification/approval state with explicit active/passive roles; render typed choice objects as native `Choose`/`Explore` controls on active ESP32 Touch, direct-use W/K, and TUI surfaces, while passive room Displays and the Puck remain read-only for choices.

UX-DR19: Implement the TUI Header with active Profile identity and shared phase semantics while keeping diagnostics an engineering capability rather than the household journey.

UX-DR20: Implement child-readable state labels (`Ready`, `Heard`, `Listening`, `Working`, `Speaking`, `Unavailable`, `Stopped`) alongside technical labels; use live regions or announcements once per state transition, not once per transcript delta.

UX-DR21: Implement accessibility behavior: WCAG 2.2 AA contrast targets, reduced-motion static states, iPad accessible DOM status mirror and completion announcement, iOS VoiceOver and Android accessibility order Profile → state → response/Transcription → action with focus restoration, TUI keyboard-equivalent recovery and choice actions (`Enter` choose, `Right Arrow` explore), and non-actionable passive Display prompt mirrors.

UX-DR22: Adapt the shared semantics to the ReSpeaker/TFT Puck, 1024×600 ESP32-S3/LVGL Display, Safari/Guided Access iPad kiosk, native iOS Client, native Android Client, companion macOS behavior, TUI, and native macOS simulator without encoding one-room assumptions or requiring identical geometry.

UX-DR23: Preserve the interaction anti-pattern guardrails: no wrong-profile response, duplicate wake, false phase/recovery claim, cross-Room text, disconnected capture/fallback, replaying Retry, Puck transcript or choice UI, passive-display choice action, stale/duplicate commit, audible Departure Card, chain-of-thought display, arbitrary Hermes-authored UI, or pre-echo-safe barge-in.

### FR Coverage Map

FR1: Epic 1 - Authorized Puck/ESP32 Touch/WK doorway or iOS/Android/TUI Client starts a Hermes turn.
FR2: Epic 1 surface stories + Epic 2 passive mirror - Voice-capable Puck/ESP32 Touch/WK doorway captures; room Displays mirror live capture state and Transcription.
FR3: Epic 1 - Doorways expose honest Turn Phases.
FR4: Epic 1 - Hermes response is delivered through Puck, ESP32 Touch, W/K, iOS, Android, TUI, and passive display surfaces.
FR5: Epic 1 - Configured voice doorways provide continuously reopening bounded follow-up listening and silent stop where supported, including W/K's advertised browser capability.
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
FR16: Epic 3 - iOS and Android discover and connect unconfigured Devices.
FR17: Epic 3 - iOS and Android guide Room, Wake Mapping, and Ready setup.
FR18: Epic 3 - iOS and Android revoke Device access and require re-enrollment.
FR19: Epic 1 - Verified recovery never silently resumes a turn.
FR20: Epic 5 - iOS and Android provide independent full conversation doorways.
FR21: Epic 5 - TUI provides an independent direct voice-chat doorway.
FR22: Epic 2 - Passive Displays mirror Hermes prompts with explicit active/passive roles; free-text answers follow the owning doorway.
FR23: Epic 2 - Active ESP32 Touch, direct-use W/K, and TUI surfaces render typed choices with structured choose/explore actions; passive Displays mirror and the Puck remains actionless.

## Epic List

### Epic 1: Have a reliable Hermes conversation

A configured doorway can complete an honest voice turn, continue briefly after the response, and recover safely from transport loss. Epic 1 is decomposed into surface-specific delivery stories; shared session, display-state, and bounded-audio contracts are prerequisites rather than a hidden generic story.
**FRs covered:** FR1, FR3, FR4, FR5, FR6, FR19
**Natural dependency:** Establishes the normalized session and turn semantics consumed by later display and companion-doorway epics. It needs only an authorized configured doorway and can be validated with fake sessions plus the explicit live smoke path.

### Epic 2: See and trust what the room is doing

Passive Room Displays and the W/K iPad/web surface's room-context mode show calm ambient context, the owning Room's active conversation, visible prompts, typed choice objects, and honest recovery state without becoming another assistant. Active W/K and ESP32 Touch surfaces, plus the TUI, may operate the approved typed choices; W/K voice capture/audio and the ESP32 Touch Display's active voice capture, response rendering, and audio delivery remain Epic 1 surface work.
**FRs covered:** FR2, FR10, FR11, FR12, FR22, FR23
**Natural dependency:** Consumes Epic 1's turn events and the shared display contract; it can be developed and validated independently with display fixtures and does not require calendar or Device administration.

### Surface-specific Epic 2 story map — decision 2026-09-10; Android parity addendum 2026-09-11; interactive-choice amendment 2026-09-12

Epic 2 stories belong to the renderer or doorway that owns the visible
behavior. The shared `DisplaySnapshot` schema, reducer, Room filtering, and
normalized event feed are prerequisites, not an unowned closure story. A
passive Room Display is a role exercised by a Display renderer; it is not a
second W/K or iPad surface.

| Surface story key | Surface | Scope |
|---|---|---|
| `2-I-1` | iOS Client | Show the iOS doorway's capture acknowledgement and live Transcription participant state. |
| `2-I-2` | iOS Client | Show honest iOS disconnected/unavailable state without stale-turn replay. |
| `2-A-1` | Android Client | Show the Android doorway's capture acknowledgement and live Transcription participant state with the same session/turn identity rules as iOS. |
| `2-A-2` | Android Client | Show honest Android disconnected/unavailable state without stale-turn replay. |
| `2-P-1` | ReSpeaker Puck | Expose the Puck's local capture, response, and status phases without putting transcript text on the TFT. |
| `2-P-2` | ReSpeaker Puck | Fail closed and show unavailable/disconnected status when the Puck or Hermes path is unavailable. |
| `2-E-1` | ESP32 Touch Display | Render the Room-scoped Ambient Surface in native LVGL. |
| `2-E-2` | ESP32 Touch Display | Render room-local active-turn state, live Transcription, and the touch doorway's observed response state. |
| `2-E-3` | ESP32 Touch Display | Mirror prompts read-only when the renderer is acting as a passive Room Display. |
| `2-E-4` | ESP32 Touch Display | Render honest disconnected state and safe cached context on the native Display. |
| `2-E-5` | ESP32 Touch Display | Render and submit native `Choose`/`Explore` actions for current typed choice objects when the touch unit is the active doorway. |
| `2-WK-1` | W/K browser voice-plus-display surface | Render the shared Room-scoped Ambient Surface for web and iPad deployment. |
| `2-WK-2` | W/K browser voice-plus-display surface | Render active capture, room-local Transcription, response, and phase state in the browser surface, including live/final user text, streamed/completed response text, explicit audio state, and bounded post-turn response retention. |
| `2-WK-3` | W/K browser voice-plus-display surface | Mirror prompts read-only when the browser is acting as a passive Room Display. |
| `2-WK-4` | W/K browser voice-plus-display surface | Render honest disconnected state, cached context, and accessible recovery presentation. |
| `2-WK-5` | W/K browser voice-plus-display surface | Validate direct-use typed-choice actions at the server boundary against current state, object freshness, and capability. |
| `2-WK-6` | W/K browser voice-plus-display surface | Render accessible native `Choose`/`Explore` actions for current typed choice objects in direct-use mode. |
| `2-T-1` | TUI | Keep the direct TUI doorway's capture and phase state visible while a Room Display may mirror separately. |
| `2-T-2` | TUI | Keep TUI disconnect/recovery presentation honest without replaying an uncertain turn. |
| `2-T-3` | TUI | Render typed choice objects with keyboard `Choose`/`Explore` actions and transcript-visible structured input. |

The generic numeric Stories 2.1–2.5 below retain the original acceptance
language as the requirements template. The surface keys above are the delivery
identities for implementation and coverage; status in one row never closes
the other rows.

### Epic 3: Control household doorway identity and access

iOS and Android can configure physical Devices and Wake Mappings, preserve profile isolation, revoke access, and select one authorized Device when several hear a wake.
**FRs covered:** FR7, FR8, FR9, FR16, FR17, FR18
**Natural dependency:** Uses the conversation/session boundary from Epic 1 but is independently testable with fake profiles, Devices, and relay endpoints; it enables trusted use of later room and companion journeys.

### Surface-specific Epic 3 story map — decision 2026-09-10; Android parity addendum 2026-09-11

Epic 3 has two ownership boundaries in the pilot. iOS and Android are the
co-equal mobile physical-Device control planes; the Puck owns the device-side
identity, mapping, and fail-closed enforcement. The initial pilot names the
ReSpeaker Puck as the affected physical target. ESP32 Touch, W/K, and TUI
remain `N/A` for Epic 3 until a separate administration boundary is adopted
rather than silently borrowing the Puck story.

| Surface story key | Surface | Scope |
|---|---|---|
| `3-I-1` | iOS Settings | Discover and connect an unconfigured Device without granting access. |
| `3-I-2` | iOS Settings | Approve a Device and guide Room, Wake Mapping, and Ready setup. |
| `3-I-3` | iOS Settings | Validate unique Wake Mappings and Profile-specific publish state. |
| `3-I-4` | iOS Settings | Configure and expose deterministic single-Device wake arbitration. |
| `3-I-5` | iOS Settings | Show and enforce unavailable or revoked identity as a failed-closed state. |
| `3-I-6` | iOS Settings | Revoke access and require explicit verified re-enrollment. |
| `3-A-1` | Android Settings | Discover and connect an unconfigured Device without granting access. |
| `3-A-2` | Android Settings | Approve a Device and guide Room, Wake Mapping, and Ready setup. |
| `3-A-3` | Android Settings | Validate unique Wake Mappings and Profile-specific publish state. |
| `3-A-4` | Android Settings | Configure and expose deterministic single-Device wake arbitration. |
| `3-A-5` | Android Settings | Show and enforce unavailable or revoked identity as a failed-closed state. |
| `3-A-6` | Android Settings | Revoke access and require explicit verified re-enrollment. |
| `3-P-1` | ReSpeaker Puck | Advertise independently identifiable unconfigured state for discovery and connection. |
| `3-P-2` | ReSpeaker Puck | Apply approved Room, credential, and Wake Mapping configuration without becoming Ready early. |
| `3-P-3` | ReSpeaker Puck | Enforce the selected Wake Mapping and Profile before capture. |
| `3-P-4` | ReSpeaker Puck | Participate in single-winner wake arbitration and remain silent when it loses. |
| `3-P-5` | ReSpeaker Puck | Reject revoked, unavailable, or unverified identity before capture or submission. |
| `3-P-6` | ReSpeaker Puck | Retire revoked credentials and require the ordered setup flow on re-enrollment. |

The generic numeric Stories 3.1–3.6 below remain the acceptance template for
the paired mobile control-plane (iOS and Android) and Puck device-side slices.
No other surface is implicitly closed by either family.

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

iOS, Android, and the TUI provide independent portable and terminal conversation doorways with deliberate local history and shared phase semantics.
**FRs covered:** FR20, FR21
**Natural dependency:** Consumes Epic 1's session semantics but remains independently usable through configured Client sessions; diagnostics remain an engineering capability rather than a household prerequisite.

### Surface-specific Epic 5 story map — decision 2026-09-10; Android parity addendum 2026-09-11

Epic 5 is already naturally surface-specific: the iOS and TUI doorways own
separate Sessions, presentation, and deliberate Local History boundaries.

| Surface story key | Surface | Scope |
|---|---|---|
| `5-I-1` | iOS Client | Use iOS as an independent typed and tap-to-speak conversation doorway with response audio, phase state, recovery, and Local History. |
| `5-A-1` | Android Client | Use Android as an independent typed and tap-to-speak conversation doorway with response audio, phase state, recovery, secure profile storage, and per-profile Local History matching iOS capability and safety behavior. |
| `5-T-1` | TUI | Use the TUI as an independent direct voice-chat gateway with inline response rendering, diagnostics, and deliberate local history. |

The existing numeric Stories 5.1 and 5.2 below remain stable aliases for
`5-I-1` and `5-T-1`; Android's `5-A-1` is a separate delivery identity and
neither mobile surface's implementation closes the other.

## Epic 1: Have a reliable Hermes conversation

A configured doorway can complete an honest voice turn, continue briefly after the response, and recover safely from transport loss. Epic 1 is decomposed into surface-specific delivery stories; shared session, display-state, and bounded-audio contracts are prerequisites rather than a hidden generic story.

**FRs covered:** FR1, FR3, FR4, FR5, FR6, FR19

### Surface-specific Epic 1 story map — decision 2026-09-10; Android parity addendum 2026-09-11

The surface key is part of the story identity. A completed story closes only
the named surface; another surface's implementation is evidence, not closure.

| Surface story key | Surface | Scope |
|---|---|---|
| `I-1` | iOS | Authorized initiation. |
| `I-2` | iOS | Honest phases with response/audio delivery. |
| `I-3` | iOS | Fresh recovery without replay. |
| `A-1` | Android | Authorized typed or tap-to-speak initiation bound to the selected Profile. |
| `A-2` | Android | Honest phases with response text/audio delivery and explicit unavailable-state behavior. |
| `A-3` | Android | Fresh recovery without replaying an uncertain turn. |
| `P-1` | ReSpeaker Puck | Authorized wake and capture. |
| `P-2` | ReSpeaker Puck | Status and response-audio delivery. |
| `P-3` | ReSpeaker Puck | Bounded follow-up and exact `stop`. |
| `P-4` | ReSpeaker Puck | Recovery without replay. |
| `P-5` | ReSpeaker Puck | Complete streamed response playback without underrun. |
| `P-6` | ReSpeaker Puck | Graceful bridge-service shutdown and entry-point coverage. |
| `P-7` | ReSpeaker Puck | Make raw PCM diagnostics explicitly opt-in and bounded. |
| `P-8` | ReSpeaker Puck | Make the vendored reSpeaker audio-format boundary deterministic and testable. |
| `P-9` | ReSpeaker Puck | Make ReSpeaker I2S channel startup and teardown fail-safe. |
| `P-10` | ReSpeaker Puck | Keep internal wake models out of ordinary capture routing. |
| `P-11` | ReSpeaker Puck | Surface runtime audio-output failures honestly and recoverably. |
| `E-1` | ESP32 Touch Display | Authorized voice capture. |
| `E-2` | ESP32 Touch Display | Native phases and streamed-response rendering. |
| `E-3` | ESP32 Touch Display | Response-audio delivery. |
| `E-4` | ESP32 Touch Display | Bounded follow-up and exact `stop`. |
| `E-5` | ESP32 Touch Display | Recovery without replay. |
| `WK-1` | Web/iPad | One shared W/K browser voice-plus-display surface for authorized capture, honest phases, streamed/completed response text, response audio, and delivery/error state, including bounded post-playback hands-free recovery across supported browsers. iPad is a deployment target, not a separate surface. |
| `T-1` | TUI | Authorized initiation. The historical numeric artifact 1.1 remains its stable local alias. |
| `T-2` | TUI | Honest phases and response delivery. The historical numeric artifact 1.2 remains its stable local alias. |
| `T-3` | TUI | Bounded follow-up and exact `stop`. The historical numeric artifact 1.3 remains its stable local alias. |
| `T-4` | TUI | Recovery without replay. The historical numeric artifact 1.4 remains its stable local alias. |
| `T-5` | TUI | Non-blocking wake-listener and microphone teardown during recovery, reload, disarm, and quit. |
| `T-6` | TUI | Detect idle relay loss and present honest recovery without replaying an uncertain turn. |

The ESP32 Touch stories cannot be closed by the existing `DisplaySnapshot`
transport alone. The surface must capture voice and deliver response audio as
well as render its own response. Its implementation may use the Python
appliance/session adapter or a direct device adapter, but the choice must be
explicit; firmware must not become a second Hermes authority. The current
snapshot/action firmware path is foundation evidence only.

The following four numeric stories are retained as the local TUI delivery
record and are stable aliases for T-1 through T-4. New surface work must use
the ownership map above rather than treating one TUI story as global Epic 1
completion. For sprint tracking, the surface-map rows are the delivery
identities; the generic numeric Stories 2.1–5.2 below are acceptance templates,
not additional backlog entries, unless a matching owning story artifact makes
one an explicit local alias.

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
So that the Puck, iOS Client, Android Client, TUI, and room-display mirror never tell different stories about one conversation.

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

### Story T-5: Shut down local voice resources without blocking the TUI

As a TUI user recovering from a connection problem or quitting,
I want wake listening and microphone teardown to happen without blocking the Textual event loop,
So that reconnect, reload, disarm, and quit remain responsive and do not leak or reopen native audio resources.

**Covers:** FR5, FR6, FR19; NFR2; explicit shutdown, cancellation ownership, and front-end responsiveness.

**Acceptance Criteria:**

**Given** wake listening or capture is active
**When** `/reconnect`, connection loss, reload, or quit disarms it
**Then** the UI handler returns promptly
**And** worker joins and native recorder shutdown run outside the Textual event loop.

**Given** shutdown is cancelled or a microphone open completes late
**When** the recorder becomes available after cancellation
**Then** it is closed exactly once
**And** a timed-out native close remains poisoned and cannot be reopened.

**Given** a listener is disarmed and later re-armed
**When** queued frames from the prior listener are present
**Then** they cannot trigger the old wake or invoke `on_wake` after disarm.

**Given** teardown is requested repeatedly
**When** each request is processed
**Then** teardown is idempotent
**And** no worker, capture task, native stream, or late callback remains owned by the discarded listener.

**Given** the lifecycle changes are implemented
**When** the focused test suite runs
**Then** it covers prompt UI return, cancellation, late-open cleanup, stale-frame rejection, idempotence, and the existing successful wake path.

### Story T-6: Detect idle relay loss and present honest recovery without replaying an uncertain turn

As a TUI user whose relay may disappear while the screen is idle,
I want the client to detect and present that loss within a bounded interval,
So that it does not claim to be connected and never replays a turn whose delivery is uncertain.

**Covers:** FR6, FR19; NFR2, NFR4; idle liveness, transport classification, single-reader ownership, and no-replay recovery.

**Acceptance Criteria:**

**Given** a Hermes Session is connected and idle
**When** the relay closes the socket or fails the configured liveness/heartbeat deadline
**Then** the TUI transitions to its existing disconnected or unavailable presentation within that bounded policy
**And** it does not wait for the next user operation to discover the loss.

**Given** the Session is actively receiving a turn
**When** liveness checks or transport events run
**Then** the existing receive owner remains the only reader
**And** no duplicate receive task, competing `recv()`, or second Hermes turn is created.

**Given** a supported transport version, including the repository's legacy websockets 13.x compatibility path
**When** the owned receive path reports a close, timeout, or reader failure
**Then** the client classifies that condition through an explicit transport boundary
**And** it does not convert an unrelated programming `RuntimeError` into a network-loss claim.

**Given** an idle relay loss is detected after a prior turn may have reached Hermes
**When** the TUI enters recovery
**Then** it preserves the existing uncertain-turn/no-replay behavior
**And** it does not fabricate completion, playback, or a fresh submission of the old prompt.

**Given** a later prompt is submitted after the idle loss
**When** bounded recovery and a new handshake succeed
**Then** the new prompt is sent once through the new Session
**And** stale events, audio, and queued state from the disconnected Session cannot mutate it.

**Given** idle liveness and compatibility handling are implemented
**When** focused fake-WebSocket tests run against healthy idle, remote close, missed heartbeat, legacy 13.x error, active-turn, and post-loss recovery cases
**Then** the state transition, classification, reader ownership, and no-replay guarantees are verified
**And** normal active-turn streaming and explicit user reconnect behavior remain unchanged.

### Story P-5: Deliver streamed Puck responses without underrun

As a household member hearing a Hermes answer on the Puck,
I want streamed response audio to play continuously to completion,
So that the device does not stop cleanly halfway through a valid answer while the bridge still has audio available.

**Covers:** FR4, FR6, FR19; NFR1, NFR2, NFR3; bounded streaming, honest failure, and surface-owned audio delivery.

**Acceptance Criteria:**

**Given** a valid authenticated `/response?seq=N` stream whose audio arrives at normal live pace
**When** the Puck plays it
**Then** every response segment is consumed through EOF
**And** the answer is audible to completion without a premature transition to `IDLE`.

**Given** the same audio is served with fixed-length or chunked transfer framing
**When** playback is tested
**Then** both paths remain complete
**And** neither framing mode causes premature `IDLE`.

**Given** a temporary delivery gap or genuine stream failure
**When** the playback path cannot continue
**Then** the Puck exposes an explicit unavailable or error outcome
**And** it returns to a reusable idle state without claiming completion.

**Given** a subsequent response follows completed or failed playback
**When** it starts
**Then** it receives an isolated audio path
**And** no stale bytes, clipped prior stream, or cross-turn corruption is audible.

**Given** the pacing or buffering change is implemented
**When** focused host tests and a controlled hardware run execute
**Then** they record buffer-fill and consumption timing for a representative full response
**And** the implementation does not rely on blindly increasing prebuffer, because larger prebuffers have already produced worse delivery.

### Story P-6: Gracefully stop and directly test the standalone Puck bridge

As an operator running `puck_bridge` as a background or launchd service,
I want startup failures and termination signals handled explicitly,
So that the bridge does not leave worker threads, audio resources, or response streams behind.

**Covers:** FR6, FR19; NFR2, NFR4; explicit process lifecycle, bounded cleanup, and tested service wiring.

**Acceptance Criteria:**

**Given** `puck_bridge` is serving
**When** it receives `SIGTERM` or `SIGINT`
**Then** `serve_forever()` exits within a bounded interval
**And** the `TurnRunner` is stopped and owned worker, audio, and response-stream resources are released.

**Given** shutdown is requested more than once
**When** subsequent signals or cleanup paths run
**Then** shutdown remains idempotent
**And** double-stop or double-close does not raise.

**Given** `PUCK_DEVICE_TOKEN` is missing
**When** `server.main()` starts
**Then** it exits with a clear nonzero configuration failure
**And** it does not construct or start the HTTP server or turn runner.

**Given** valid startup configuration
**When** `server.main()` is invoked under test
**Then** it wires the expected `ThreadingHTTPServer` and `TurnRunner`
**And** it performs the same cleanup path when serving is asked to stop.

**Given** the service-lifecycle changes are implemented
**When** the focused bridge tests run
**Then** they cover missing-token failure, constructor wiring, signal-triggered termination, bounded cleanup, and idempotence
**And** no Hermes protocol or firmware behavior changes are required.

### Story P-7: Make raw PCM diagnostics explicitly opt-in

As an operator diagnosing a wake-word or microphone problem,
I want raw PCM capture and export disabled by default,
So that ordinary household firmware cannot retain or emit microphone recordings accidentally.

**Covers:** FR5, FR19; NFR3, NFR4; explicit diagnostic ownership, bounded capture, and privacy-safe defaults.

**Acceptance Criteria:**

**Given** the default firmware configuration
**When** the Puck boots and receives microphone data
**Then** no training-data PCM buffer is started for export
**And** no raw PCM or base64 payload is written to logs, serial, or the network.

**Given** an explicit diagnostic opt-in
**When** bounded capture is enabled
**Then** the build or configuration makes that choice visible
**And** it warns that microphone data is being captured and enforces a finite capture/export limit.

**Given** diagnostic capture is active
**When** the audio callback and export or reset path operate concurrently
**Then** ownership is synchronized or snapshot-based
**And** no partial read, data race, buffer overrun, or use-after-reset occurs.

**Given** the normal wake-capture path is running
**When** diagnostic capture is disabled or completes
**Then** wake detection, VAD-gated capture, upload, and response playback are unchanged.

**Given** the diagnostic boundary is implemented
**When** focused host/build checks and a controlled hardware check run
**Then** they prove default-off behavior and bounded explicit opt-in
**And** content-safe amplitude and status diagnostics remain separate from raw PCM export.

### Story P-8: Make the vendored reSpeaker audio-format boundary deterministic and testable

As an engineer maintaining the ReSpeaker firmware,
I want the declared microphone formats and conversion path to agree,
So that a configuration cannot silently produce malformed or misinterpreted audio.

**Covers:** FR5, FR19; NFR1, NFR2, NFR4; explicit format contracts, safe sample conversion, and repeatable verification.

**Acceptance Criteria:**

**Given** a microphone format outside the proven board path
**When** firmware configuration is validated
**Then** it is rejected with a clear reason or handled by an explicitly tested conversion path
**And** the schema does not imply unsupported combinations.

**Given** signed 32-bit stereo fixture samples, including negative values and boundary values
**When** the microphone path and diagnostics decode them
**Then** conversion is defined and produces the expected 16 kHz/channel output
**And** no shift overflow or undefined signed behavior occurs.

**Given** the supported ReSpeaker configuration—48 kHz, 32-bit, stereo input to the wake-word consumer
**When** a deterministic fixture runs
**Then** output sample count, channel selection, duration, and representative sample values match the documented contract.

**Given** the format-boundary changes are applied
**When** the current wake-word and response paths run
**Then** wake detection, VAD-gated capture, upload, and response playback retain their existing behavior.

**Given** the conversion contract is implemented
**When** focused host tests and a firmware/configuration check run
**Then** they complete repeatably without a live Hermes endpoint
**And** the fixture and expected output remain in the repository for future component changes.

### Story P-9: Make ReSpeaker I2S channel startup and teardown fail-safe

As an engineer maintaining the ReSpeaker firmware,
I want microphone and shared-I2S channel lifecycle failures to clean up deterministically,
So that one partial start cannot strand a lock, stale handle, or unusable audio path.

**Covers:** FR5, FR6, FR19; NFR2, NFR4; explicit resource ownership, safe failure, and reusable audio lifecycle.

**Acceptance Criteria:**

**Given** RX channel allocation succeeds but initialization or enable fails
**When** startup returns
**Then** the channel is disabled or deleted as applicable
**And** the handle is cleared, the parent I2S lock is released exactly once, and the component reports a structured failure.

**Given** startup fails before the driver is locked
**When** teardown runs
**Then** it does not unlock an unowned parent or touch an invalid handle.

**Given** disable or delete reports an error during teardown
**When** cleanup continues
**Then** the error is logged with the operation and channel context
**And** all safe cleanup still runs so later starts do not reuse stale ownership.

**Given** shared-bus configuration is generated
**When** its pins, port, and lifecycle fields are initialized
**Then** no uninitialized value can reach the ESP-IDF driver
**And** the input/output ownership contract is explicit.

**Given** the lifecycle changes are implemented
**When** focused host or mocked-driver checks and a firmware compile exercise allocation, initialization, enable, disable, delete, and retry paths
**Then** each failure path is repeatable and recoverable
**And** wake capture and P-5 playback pacing behavior remain unchanged.

### Story P-10: Keep internal wake models out of ordinary capture routing

As the Puck’s hands-free conversation path,
I want internal wake models such as `stop` excluded from normal wake-capture routing,
So that an internal control signal cannot start a microphone upload or Hermes turn as if it were a public wake phrase.

**Covers:** FR5, FR6, FR19; NFR2, NFR4; internal-control isolation, authorized capture, and fail-closed routing.

**Acceptance Criteria:**

**Given** the internal `stop` model detects while the wake engine is running
**When** `on_wake_word_detected` executes
**Then** it does not start `wake_capture`, upload audio, create a Hermes turn, or select a Profile.

**Given** a configured public wake model detects
**When** the same callback executes
**Then** the existing authorized capture path is unchanged.

**Given** an internal model is detected
**When** the event is logged or surfaced for diagnostics
**Then** it remains content-safe
**And** it clearly distinguishes internal control from public wake routing.

**Given** the internal model list changes
**When** firmware configuration is validated
**Then** internal models cannot accidentally become public wake entities or bypass the routing guard.

**Given** the internal-model boundary is implemented
**When** focused configuration and firmware checks exercise internal and public detections
**Then** both routing outcomes are verified
**And** exact spoken `stop` transcription behavior remains owned by P-3 rather than being redefined here.

### Story P-11: Surface Puck audio-output failures honestly and recoverably

As a household member hearing a response on the Puck,
I want speaker-path failures to be visible and safely terminated,
So that clipped or unavailable audio is not reported as a completed answer and the next turn remains usable.

**Covers:** FR4, FR6, FR19; NFR1, NFR2, NFR3; runtime failure propagation, honest terminal state, and turn isolation.

**Acceptance Criteria:**

**Given** callback registration, preload, channel-enable, queue, or DMA-write failure occurs during playback
**When** the speaker path handles it
**Then** it records an explicit playback error with operation context and stops or aborts the affected stream safely.

**Given** a partial DMA write or lockstep queue desynchronization
**When** recovery runs
**Then** buffer alignment is not reused as valid audio
**And** the media path does not claim successful completion.

**Given** playback fails after a response stream has begun
**When** the Puck returns to idle
**Then** its existing media-player or diagnostic state distinguishes unavailable/error from normal completion
**And** it leaves the output quiet.

**Given** a later response starts after a failed playback
**When** its audio path opens
**Then** it starts from clean queues and state
**And** no stale bytes or inherited failure state is audible.

**Given** the output-failure boundary is implemented
**When** focused fault-injection or mocked-driver checks and a controlled hardware check run
**Then** they cover callback registration, preload, enable, queue overflow or desynchronization, partial writes, and recovery
**And** P-5 pacing and P-9 channel lifecycle behavior remain unchanged.

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

As a household member speaking through a Puck, ESP32 Touch Display, iOS Client, Android Client, or TUI,
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
**Then** the Room Display, W/K browser surface, iOS Client, Android Client, and TUI update live rather than waiting for capture to finish.

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

**W/K refinement:**

**Given** browser capture has ended and the final SpeechRecognition result is still pending
**When** the browser has a real interval before submission
**Then** the W/K surface may paint a local `transcribing` state
**And** it keeps the final user text visible once available.

**Given** the final SpeechRecognition result arrives immediately when capture ends
**When** the browser submits the non-empty transcript
**Then** it does not manufacture a visible `transcribing` interval
**And** it proceeds through the existing local submission state.

**Given** W/K renders its local transcription interval
**When** the browser publishes or receives shared display state
**Then** `transcribing` remains a browser-local presentation decision
**And** no new `DisplaySnapshot` phase or Hermes wire event is introduced.

**Given** recognition produces an empty, cancelled, or failed final result
**When** the local capture lifecycle closes
**Then** the browser clears the temporary transcription state safely
**And** it submits no empty Hermes turn or stale user text.

**Given** the W/K timing refinement is implemented
**When** focused browser tests run with immediate and delayed finalization
**Then** they verify the optional local `transcribing` interval, final-text retention, no artificial phase, and safe empty/error cleanup
**And** native, TUI, passive-display, shared-state, and Hermes protocol behavior remain unchanged.

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
**Then** the Display does not capture audio, speak the response, create another Hermes Session, or expose a prompt/choice action.

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
I want Hermes clarification and approval prompts to be visible with clear surface ownership,
So that free-text answers remain voice-led and typed choices do not turn a passive mirror into another assistant.

**Covers:** FR22; NFR2, NFR3, NFR5; active-Session ownership, room-local mirroring, and passive Display behavior. Typed choice operations are covered by Story 2.6 and surface stories `2-E-5`, `2-WK-5`, `2-WK-6`, and `2-T-3`.

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
**Then** a passive Display exposes no touch action that approves, rejects, cancels, submits, or creates another Hermes turn.

**Given** Hermes sends a free-text clarification or approval prompt
**When** the active doorway receives it
**Then** the active Puck, ESP32 Touch Display, W/K browser voice surface, or Client waits for the spoken answer through its existing Hermes Session
**And** no typed choice controls are invented by the doorway.

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

### Story 2.6: Turn Hermes choices into structured actions

As a household member evaluating a Hermes recommendation,
I want to inspect or choose a visible option through the surface I am using,
So that a decision can become structured input without requiring another free-form spoken turn.

**Covers:** FR23; NFR2, NFR5, NFR6; typed object semantics, native controls, active/passive surface roles, freshness, and idempotent action handling.

**Acceptance Criteria:**

**Given** the active Hermes Session emits a current bounded Interactive Choice Object
**When** an active ESP32 Touch, direct-use W/K, or TUI surface renders it
**Then** the surface shows Hermes' explanation, the active Profile, every option, a primary `Choose` action, and a visible secondary `Explore` action for each option
**And** a passive Room Display may mirror the same object without exposing controls.

**Given** Amanda explores an option
**When** the active surface submits the `explore` action
**Then** the action is one structured input to the owning Hermes Session
**And** the choice remains unresolved and its consequence is not triggered.

**Given** Amanda chooses an option
**When** the active surface submits the `choose` action
**Then** the action is one structured input to the owning Hermes Session
**And** the accepted action is visible once in the session trail before the object advances or resolves.

**Given** an action is stale, unsupported, expired, replaced, or duplicated
**When** the reducer or server boundary evaluates it
**Then** it rejects the action without changing the current object or invoking a consequence.

**Given** the surface is touch-capable
**When** an option action is available
**Then** touch targets and focus treatment meet the shared accessibility rules
**And** the same operation is available through a visible control rather than press-and-hold alone.

**Given** the surface is the TUI
**When** a choice object is current
**Then** `Enter` chooses the focused option and `Right Arrow` explores it
**And** the action remains visible in the terminal transcript.

**Given** the first proving slice is validated
**When** choice fixtures run across active ESP32 Touch, direct-use W/K, TUI, and passive-display roles
**Then** harmless choose/explore behavior, capability/freshness rejection, idempotency, transcript visibility, and read-only mirroring are verified
**And** consequence-bearing policy/confirmation remains a later slice.

### Story 2-WK-5: Validate direct-use typed-choice actions at the server boundary

As a household member using the direct-use Web/iPad display,
I want typed-choice actions accepted only when the current server state authorizes them,
So that stale, unsupported, or out-of-date requests cannot trigger an appliance callback or change Room state.

**Covers:** FR23; NFR2, NFR4, NFR5, NFR6; server-side action authority, stale-object rejection, capability enforcement, idempotency, and direct-use/passive separation.

**Acceptance Criteria:**

**Given** the current published snapshot contains an active typed choice object, advertises the requested `prompt.choose` or `prompt.explore` capability, and lists the requested option
**When** a direct-use client posts the matching session, turn, object, option, operation, and freshness context
**Then** the server accepts the request and dispatches one normalized callback for that current object.

**Given** an action context is unknown, expired, replaced, or no longer belongs to the current choice object
**When** the request reaches `/action`
**Then** the server rejects it safely
**And** it does not invoke the appliance callback.

**Given** the requested operation is not currently advertised, the option is not one of the current object options, or the snapshot is not in an actionable choice state
**When** the request reaches the server
**Then** it is rejected before callback dispatch
**And** the published choice object remains unchanged.

**Given** a choice object is replaced, dismissed, or disconnected while an action request is in flight
**When** validation and dispatch complete
**Then** the request is evaluated against one consistent current-state boundary
**And** a stale request cannot affect the replacement or disconnected state.

**Given** a client retries the same action request
**When** the server has already accepted it
**Then** it does not invoke the callback more than once for that session, turn, object, option, and operation.

**Given** the operation is `explore`
**When** the server accepts it
**Then** it dispatches a non-committing structured input
**And** it does not resolve the object or trigger the option's consequence.

**Given** the operation is `choose`
**When** the server accepts it
**Then** it dispatches the committing structured input exactly once
**And** the action is available to the session trail for transcript-visible rendering.

**Given** the server-side action boundary is implemented
**When** focused HTTP and state-transition tests run
**Then** they cover valid actions, stale prompts, invalid choices, missing capabilities, duplicate requests, prompt replacement, and disconnect
**And** the display wire contract, browser voice/session transport, and passive-mirror read-only boundary remain explicit.

## Epic 3: Control household doorway identity and access

iOS and Android can configure physical Devices and Wake Mappings, preserve Profile isolation, revoke access, and select one authorized Device when several hear a wake.

**FRs covered:** FR7, FR8, FR9, FR16, FR17, FR18

### Story 3.1: Discover unconfigured Devices safely

As a household administrator using iOS or Android Settings,
I want to discover and connect to a new household Device,
So that I can identify it clearly before granting it any ability to capture audio or use Hermes.

**Covers:** FR16; NFR4, NFR5; iOS and Android as co-equal mobile control planes with discovery/approval separation.

**Acceptance Criteria:**

**Given** Amanda taps `Add` in the selected mobile Client's Settings
**When** discovery runs
**Then** unconfigured Devices appear in a clearly separate discovery list from approved Devices.

**Given** a Device is discovered but not approved
**When** it appears or is selected
**Then** it remains visibly unconfigured and inert
**And** it cannot capture audio, wake, or use Hermes.

**Given** Amanda selects a discovered Device
**When** connection is attempted
**Then** the selected mobile Client shows a connecting state while the Device remains unconfigured.

**Given** connection succeeds
**When** the Device confirms the connection
**Then** success is visible on both the selected mobile Client and the Device
**And** success does not depend on a silent list refresh.

**Given** LAN discovery is unavailable or blocked
**When** Amanda chooses the fallback
**Then** QR or manual pairing can identify the same unconfigured Device without granting access automatically.

**Given** discovery or connection fails
**When** the attempt ends
**Then** the selected mobile Client shows an actionable failure
**And** the Device remains inert and unapproved.

### Story 3.2: Approve and configure a Device

As a household administrator using iOS or Android Settings,
I want to approve a discovered Device and configure it in a clear order,
So that it cannot become an active household doorway before its Room and wake behavior are known.

**Covers:** FR17; NFR4, NFR5; individual revocable credentials, explicit approval, and visible setup state.

**Acceptance Criteria:**

**Given** a connected but unconfigured Device
**When** Amanda explicitly approves it
**Then** the selected mobile Client grants authorization and provisions an individual revocable Device Credential
**And** the Device remains inactive until setup completes.

**Given** approval succeeds
**When** setup begins
**Then** the selected mobile Client guides the user through the ordered steps `Room` → `Wake Mappings` → `Ready`.

**Given** Room assignment is incomplete
**When** the Device is powered or reachable
**Then** it remains visibly pending
**And** it cannot wake, capture, or submit to Hermes.

**Given** Room assignment is complete
**When** one or more valid Wake Mappings are configured
**Then** the selected mobile Client and the Device show the pending setup state rather than implying readiness.

**Given** all required setup steps complete
**When** Amanda confirms `Ready`
**Then** the selected mobile Client and the Device show matching success indicators
**And** the Device may operate as an active doorway.

**Given** setup fails, is offline, or has unverified changes
**When** the setup attempt ends
**Then** the Device remains inactive
**And** the selected mobile Client labels the configuration as pending or failed rather than applied.

### Story 3.3: Keep Wake Mappings unique and Profile-specific

As a household administrator,
I want each Wake Mapping to resolve unambiguously to one Hermes Profile,
So that a recognized phrase can never route to the wrong identity.

**Covers:** FR7; NFR2, NFR4; profile isolation, configuration validation, and verified publish state.

**Acceptance Criteria:**

**Given** multiple Wake Mappings are configured across the household
**When** a new or edited wake phrase would duplicate or ambiguously target another Profile
**Then** the selected mobile Client rejects it before publishing.

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

### Story 3-P-3: Carry each detected wake mapping through capture and route it to its bound Hermes Profile

As a household member using a configured Puck,
I want the recognized Wake Mapping to remain bound to its selected Hermes Profile through capture and submission,
So that each wake phrase reaches the intended identity and never falls back to one fixed or unrelated Profile.

**Covers:** FR7, FR8; NFR2, NFR4; mapping identity propagation, profile isolation, verified routing, and fail-closed capture.

**Acceptance Criteria:**

**Given** a verified Device has one or more unique Wake Mappings
**When** a configured public wake phrase is recognized
**Then** the capture path retains the matching mapping identity through upload
**And** the mapping is fixed before audio capture or Hermes submission begins.

**Given** a completed capture reaches `puck_bridge`
**When** the receiver dispatches the transcript
**Then** it resolves the mapping to its bound Hermes Profile
**And** submits through a session or turn runner bound to that Profile rather than the bridge's unrelated default.

**Given** the mapping is missing, ambiguous, stale, revoked, or points to an unavailable Profile
**When** the Device or bridge evaluates the wake
**Then** it fails closed
**And** it performs no capture, upload, Hermes submission, or fallback to another Profile.

**Given** multiple valid mappings exist on one Device
**When** different phrases are recognized across separate turns
**Then** each turn is dispatched using only the Profile bound to its recognized mapping
**And** Profile context, session identity, and response state do not cross routes.

**Given** a mapping is changed or removed while a prior capture or turn is in flight
**When** the in-flight request completes
**Then** it remains tied to the mapping version that authorized that capture
**And** if that mapping is no longer valid at dispatch, the request is rejected without rerouting
**And** a later turn cannot inherit the prior route implicitly.

**Given** mapping propagation and dispatch are implemented
**When** focused firmware, receiver, and bridge tests run
**Then** they cover public detection, metadata transport, valid profile selection, missing or stale mappings, unavailable profiles, duplicate mappings, and route isolation
**And** the Hermes wire protocol and non-Puck front ends remain unchanged.

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
**Then** the selected mobile Client shows a confirmation explaining that the Device will stop working until it is re-enrolled.

**Given** Amanda confirms the disconnect
**When** revocation succeeds
**Then** the Device Credential and Hermes access are revoked
**And** the selected mobile Client and the Device show the revoked or unavailable state.

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
**Then** the selected mobile Client shows a visible pending or failed state
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

iOS, Android, and the TUI provide independent portable and terminal conversation doorways with deliberate local history and shared phase semantics.

**FRs covered:** FR20, FR21

### Story 5.1: Use a native mobile Client as an independent conversation doorway

As a household member using the iOS or Android Client,
I want to start typed or tap-to-speak conversations through my own Hermes Session,
So that the selected mobile Client remains a complete doorway with clear state, audio, transcript, and local continuity.

**Covers:** FR20; NFR1, NFR2, NFR3, NFR4, NFR5; independent Session ownership, active Profile visibility, and intentional Local History.

**Acceptance Criteria:**

**Given** the selected mobile Client has valid configuration and authorization
**When** Amanda starts a tap-to-speak turn
**Then** the selected mobile Client creates or uses its own Hermes Session
**And** it shows the active Profile before capture begins.

**Given** a tap-to-speak turn is active
**When** capture, processing, response, and playback events arrive
**Then** the selected mobile Client shows the corresponding Listening, Thinking, Speaking, and completion states without advancing early.

**Given** Amanda submits a typed prompt
**When** the turn is sent
**Then** it follows the same selected mobile Client Hermes Session
**And** it receives the corresponding Hermes response without merging with a Puck, Display, TUI, or other Client Session.

**Given** Hermes returns response text and audio
**When** they stream
**Then** the selected mobile Client shows the transcript and plays the same Hermes response without replacing it with local fallback prose.

**Given** a turn completes successfully
**When** Local History is updated
**Then** the completed conversation is retained intentionally on the selected mobile Client
**And** raw audio is not stored.

**Given** transport loss interrupts a turn
**When** the selected mobile Client reconnects
**Then** Retry reconnects only
**And** the unresolved turn is not replayed and a fresh explicit initiation is required.

**Given** permission, authorization, or Profile verification fails
**When** Amanda attempts a turn
**Then** the selected mobile Client shows the failure
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
