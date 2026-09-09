---
name: Hermes Night Console
description: Shared dark, high-contrast visual identity for the Hermes Home Assistant Platform's truthful multi-doorway interaction states.
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
colors:
  surface-base: '#0B101B'
  surface-console: '#101725'
  surface-panel: '#0D1320'
  surface-panel-raised: '#182338'
  surface-grid: '#1A2639'
  ink-primary: '#EAF7FF'
  ink-secondary: '#B3C0D2'
  ink-muted: '#91A0B5'
  border-subtle: '#2A3850'
  border-emphasis: '#7189AA'
  accent-live: '#62E6C7'
  accent-live-on: '#08241D'
  accent-attention: '#FFCF5C'
  accent-attention-on: '#201A08'
  accent-identity: '#7C8CFF'
  accent-identity-on: '#0B101B'
  status-unavailable: '#FF7D9C'
  status-unavailable-on: '#260A12'
  focus-ring: '#EAF7FF'
  overlay-scrim: '#05080F'
typography:
  display-state:
    fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 64px
    fontWeight: '800'
    lineHeight: '0.95'
    letterSpacing: '-0.05em'
  heading:
    fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 28px
    fontWeight: '800'
    lineHeight: '1.1'
    letterSpacing: '-0.03em'
  body:
    fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 18px
    fontWeight: '500'
    lineHeight: '1.45'
  transcript:
    fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 20px
    fontWeight: '500'
    lineHeight: '1.5'
  label:
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace'
    fontSize: 12px
    fontWeight: '700'
    lineHeight: '1.3'
    letterSpacing: '0.12em'
  meta:
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace'
    fontSize: 11px
    fontWeight: '600'
    lineHeight: '1.3'
    letterSpacing: '0.1em'
  puck-state:
    fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 14px
    fontWeight: '800'
    lineHeight: '1.1'
  button:
    fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 16px
    fontWeight: '700'
    lineHeight: '1.2'
  caption:
    fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 14px
    fontWeight: '500'
    lineHeight: '1.4'
  room-response:
    fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 24px
    fontWeight: '500'
    lineHeight: '1.4'
  room-recovery:
    fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 20px
    fontWeight: '700'
    lineHeight: '1.3'
rounded:
  sm: 2px
  DEFAULT: 6px
  md: 6px
  lg: 12px
  xl: 20px
  full: 9999px
spacing:
  '1': 4px
  '2': 8px
  '3': 12px
  '4': 16px
  '5': 24px
  '6': 32px
  '7': 40px
  '8': 48px
  display-gutter: 48px
  puck-gutter: 8px
  panel-gap: 16px
  section-gap: 32px
  touch-target: 44px
components:
  room-display:
    surface: '{colors.surface-console}'
    text: '{colors.ink-primary}'
    padding: '{spacing.display-gutter}'
    radius: '{rounded.xl}'
    border: '{colors.border-subtle}'
  puck-status:
    surface: '{colors.surface-base}'
    text: '{colors.ink-primary}'
    state: '{typography.puck-state}'
    padding: '{spacing.puck-gutter}'
    radius: '{rounded.md}'
  profile-header:
    label: '{typography.label}'
    name: '{typography.heading}'
    identity: '{colors.accent-identity}'
    divider: '{colors.border-subtle}'
  turn-path:
    label: '{typography.label}'
    current: '{colors.accent-attention}'
    complete: '{colors.accent-live}'
    gap: '{spacing.panel-gap}'
  state-label:
    type: '{typography.display-state}'
    text: '{colors.ink-primary}'
    live: '{colors.accent-live}'
    unavailable: '{colors.status-unavailable}'
  voice-visualizer:
    active: '{colors.accent-live}'
    frame: '{colors.border-emphasis}'
    background: '{colors.surface-panel}'
    radius: '{rounded.sm}'
  transcript:
    text: '{typography.transcript}'
    live: '{colors.accent-live}'
    completed: '{colors.ink-primary}'
    spacing: '{spacing.4}'
  follow-up-window:
    surface: '{colors.surface-panel}'
    cue: '{colors.accent-live}'
    state: '{typography.body}'
    border: '{colors.border-emphasis}'
  ambient-surface:
    background: '{colors.surface-base}'
    fallback: '{colors.surface-console}'
    overlay: '{colors.overlay-scrim}'
  departure-card:
    surface: '{colors.surface-panel-raised}'
    heading: '{typography.heading}'
    attention: '{colors.accent-attention}'
    text: '{colors.ink-primary}'
    padding: '{spacing.6}'
    radius: '{rounded.lg}'
  disconnected-state:
    surface: '{colors.surface-panel}'
    status: '{colors.status-unavailable}'
    text: '{colors.ink-primary}'
    border: '{colors.status-unavailable}'
  retry-action:
    text: '{colors.ink-primary}'
    border: '{colors.accent-identity}'
    focus: '{colors.focus-ring}'
    label: '{typography.button}'
    radius: '{rounded.md}'
  device-discovery:
    row: '{colors.surface-panel}'
    selected: '{colors.accent-identity}'
    divider: '{colors.border-subtle}'
    label: '{typography.body}'
  device-setup:
    step: '{typography.label}'
    current: '{colors.accent-attention}'
    complete: '{colors.accent-live}'
    gap: '{spacing.5}'
  device-details:
    surface: '{colors.surface-panel}'
    destructive: '{colors.status-unavailable}'
    divider: '{colors.border-subtle}'
    padding: '{spacing.5}'
  local-history:
    row: '{colors.surface-panel}'
    date: '{typography.meta}'
    text: '{colors.ink-primary}'
    divider: '{colors.border-subtle}'
  prompt-mirror:
    surface: '{colors.surface-panel-raised}'
    prompt: '{typography.body}'
    waiting: '{colors.accent-attention}'
    border: '{colors.border-emphasis}'
  tui-header:
    surface: '{colors.surface-console}'
    profile: '{typography.heading}'
    divider: '{colors.border-subtle}'
---

# Hermes Home Assistant Platform — Design

## Brand & Style

Night Console is a dense, dark instrument panel for a household assistant that must never bluff. It makes the current doorway state legible at room distance while leaving the idle Display quiet in the background. The visual personality is clear, fun, and friendly through concise labels, a live signal vocabulary, and purposeful motion—not through jokes in Hermes' answers, gamification, or decorative clutter.

Hermes is the shared relationship across doorways. Missy is a Hermes Profile and is shown as the active identity from the `heard` acknowledgement through response completion; the visual system does not turn the profile into a separate product brand. The design direction is anchored by the [Night Console visual reference](mockups/direction-night-console.html), which illustrates the dense console frame, explicit Turn Path, active profile, large state label, and voice-synchronized visualizer. The spine wins if the mockup and this document disagree.

The rejected visual directions were Sunlit Storybook and Comic Stage. Quiet Gallery had useful restraint but was too bright for the household Display; only a darkened adaptation may return. Night Console keeps the chosen density because scanning speed matters more here than spaciousness.

## Colors

The palette is dark by default because the physical Display is an ambient household surface and the active conversation should emerge from it without flooding the room. Every color has a semantic job.

- **Base and console surfaces** — `{colors.surface-base}` is the outer dark canvas; `{colors.surface-console}` is the main Night Console surface; `{colors.surface-panel}` and `{colors.surface-panel-raised}` create tonal layers for supporting information and Departure Card content. `{colors.surface-grid}` is a quiet structural grid, never a content signal.
- **Text** — `{colors.ink-primary}` is the load-bearing text color. `{colors.ink-secondary}` supports explanatory copy and `{colors.ink-muted}` supports metadata and secondary labels only when contrast remains readable at the rendered size. Body and state text must meet a WCAG 2.2 AA contrast target against their actual surface: 4.5:1 for ordinary text and 3:1 for large text.
- **Structure** — `{colors.border-subtle}` separates panels without becoming a second headline; it is never the sole grouping, focus, or state signal. `{colors.border-emphasis}` frames the active visualizer, focus, or a load-bearing card and must meet the non-text contrast target against its actual surface.
- **Live** — `{colors.accent-live}` means an active, healthy signal: wake acknowledgement, completed Turn Path steps, follow-up listening, and voice activity. Its dark companion `{colors.accent-live-on}` is used when live color becomes a fill.
- **Attention** — `{colors.accent-attention}` marks the current Turn Phase or a Departure Card that asks the household to notice time. It is not an error color. `{colors.accent-attention-on}` is its dark readable foreground.
- **Identity** — `{colors.accent-identity}` identifies the active Hermes Profile and interactive focus. It is a structural identity accent, not a claim that a response is correct. `{colors.accent-identity-on}` is the dark readable foreground when identity becomes a fill.
- **Unavailable** — `{colors.status-unavailable}` marks Disconnected State, revoked or unavailable access, and unavailable audio. `{colors.status-unavailable-on}` is the dark foreground for an unavailable fill. The label remains explicit; color never carries the meaning alone.
- **Focus and privacy** — `{colors.focus-ring}` is the visible keyboard/touch focus treatment. `{colors.overlay-scrim}` is reserved for modal or kiosk overlays and never obscures a recovery state without an explicit route back.

Avoid a white canvas, saturated rainbow state coding, chromatic decoration in the idle surface, or gradients that imply a state without a label. A small live glow may support an active visualizer, but the readable state is always the authority.

## Typography

Readable system sans-serif carries the human-facing state and response text. Monospace labels carry the instrument-panel metadata and Turn Path without forcing the whole experience into a terminal. `{typography.display-state}` is the room Display's dominant state word; it scales down to `{typography.puck-state}` on the Puck's tiny TFT. `{typography.heading}` identifies the active Hermes Profile and primary surface headings. `{typography.body}` and `{typography.transcript}` keep the response and live Transcription readable for children and room-distance scanning.

Labels may use the tracked monospace treatment from `{typography.label}` for secondary console chrome, but the primary state must remain a readable word such as `Listening`, `Thinking`, `Speaking`, `Unavailable`, or `Stopped`, not a code or color-only mark. `{typography.meta}` is for timestamps, Room metadata, and supporting status. `{typography.button}` is reserved for explicit actions such as `Retry` and `Disconnect`; `{typography.caption}` supports short explanations.

Room-distance minimums are explicit: on the 1024×600 Display, the primary state is at least 56px, the active Profile is at least 24px, response text is at least `{typography.room-response}` (24px), and recovery text is at least `{typography.room-recovery}` (20px). Labels and metadata are supplementary, never the only copy. The Puck's 14px status label must be validated on the actual TFT at the intended distance; no response text is placed there. Native platform type scaling remains authoritative on iOS and the TUI.

## Layout & Spacing

The spacing scale is 4 / 8 / 12 / 16 / 24 / 32 / 40 / 48 px (`{spacing.1}` through `{spacing.8}`). `{spacing.display-gutter}` frames the room Display; `{spacing.puck-gutter}` protects the Puck's tiny status surface; `{spacing.panel-gap}` separates dense instrument regions; `{spacing.section-gap}` marks a meaningful change of context. `{spacing.touch-target}` is the intended minimum sizing token for explicit touch actions where the platform can support it; the platform-specific accessibility behavior remains open.

The Night Console composition is intentionally dense: a profile header across the top, a Turn Path rail, a central state/visualizer region, and supporting status or recovery information. On a smaller surface those regions stack in the same semantic order rather than being dropped or replaced by unlabeled icons. The idle Display has no active console chrome demanding attention; it is an Ambient Surface. Platform-specific adaptations are specified in `EXPERIENCE.md`.

Room Displays and iPad Displays share the same state contract but may reflow for their form factor. iOS follows native navigation and the TUI follows terminal conventions; neither inherits the physical Display's exact geometry. Breakpoints, kiosk chrome, and platform-specific navigation are downstream implementation details, not changes to the shared visual contract.

## Elevation & Depth

Depth comes from tonal layering, hairline borders, and restrained signal glows. `{colors.surface-panel}` is a quiet panel; `{colors.surface-panel-raised}` is reserved for information that must stand above the active surface, such as a Departure Card or mirrored prompt. `{colors.border-emphasis}` and the live visualizer provide enough depth to make the current event apparent without casting a luminous appliance across the room.

Shadows, if used, are soft and subordinate to the surfaces. Do not use elevation to imply trust, profile correctness, or a completed Hermes answer. A response is trustworthy because the selected profile and state are explicit, not because its card floats.

## Shapes

The shape language is rectilinear with restrained rounding: `{rounded.sm}` for the visualizer frame and fine-grain console elements, `{rounded.md}` for actions and compact panels, `{rounded.lg}` for cards, and `{rounded.xl}` only for the outer Display frame or a platform-owned container. `{rounded.full}` is reserved for a small signal dot or equivalent status marker; it is never the shape of a whole information surface.

Shapes should make the dense console feel approachable without becoming a toy. Images follow their container shape. A Departure Card may be softer than a Turn Path rail, but no shape should hide a state transition or make a destructive action look playful.

## Components

Visual rules live here; interaction and state behavior live in `EXPERIENCE.md`. The chosen visual reference is the [Night Console mockup](mockups/direction-night-console.html).

| Component | Visual specification |
|---|---|
| **Room Display** | Use `{components.room-display.surface}` as the dark canvas with `{components.room-display.padding}` framing the composition, `{components.room-display.border}` for the outer boundary, and `{components.room-display.radius}` only at the device/frame edge. The active layout reads as a dense console: profile header, Turn Path, central state label and visualizer, then supporting status. See the [room active-turn key screen](mockups/key-room-active-turn.html). |
| **Puck Status** | Use `{components.puck-status.surface}` with `{components.puck-status.state}` for one short, readable phase label. Keep the surface status-only: no full response text, transcript archive, or miniature console that cannot be read. `{components.puck-status.padding}` is generous relative to the tiny form factor. |
| **Profile Header** | Show the active Hermes Profile name in `{components.profile-header.name}` with a small label in `{components.profile-header.label}` and an identity signal in `{components.profile-header.identity}`. Use `{components.profile-header.divider}` to separate identity from the turn body. |
| **Turn Path** | Render the supported Turn Phases as a visible progression using `{components.turn-path.label}`. Completed steps use `{components.turn-path.complete}`, the current step uses `{components.turn-path.current}`, and the gap uses `{components.turn-path.gap}`. The path is supplementary to the large state label, not a replacement for it. |
| **State Label** | Make the current state the dominant readable word using `{components.state-label.type}` and `{components.state-label.text}`. `{components.state-label.live}` supports healthy activity and `{components.state-label.unavailable}` supports failure, but every state also has a text label. |
| **Voice Visualizer** | Frame the live waveform with `{components.voice-visualizer.frame}` over `{components.voice-visualizer.background}` and use `{components.voice-visualizer.active}` for motion synchronized with response audio. It must not be the only indication of Listening, Speaking, or completion. `prefers-reduced-motion` leaves one static frame and the readable state label; no transition or loop is required. |
| **Transcript** | Use `{components.transcript.text}` for live Transcription and streamed response text. `{components.transcript.live}` distinguishes text arriving now from `{components.transcript.completed}` text that remains visible after completion. Transcript text is room-local on a Display and absent from the Puck. |
| **Follow-up Window** | Use `{components.follow-up-window.surface}` and `{components.follow-up-window.border}` to make the short follow-up state distinct from ordinary Listening. `{components.follow-up-window.cue}` is the visual counterpart to the opening sound cue; the state remains readable in `{components.follow-up-window.state}`. |
| **Ambient Surface** | Keep `{components.ambient-surface.background}` visually quiet and behind household activity. Immich imagery may fill the surface according to Room policy; `{components.ambient-surface.fallback}` is the neutral background when no image matches. `{components.ambient-surface.overlay}` must provide a controlled contrast layer or opaque card behind any load-bearing state or response text; ambience never competes with meaning. |
| **Departure Card** | Use `{components.departure-card.surface}` and `{components.departure-card.padding}` for a household-wide visual-only card. The event name, location, calculated departure time, countdown, and `estimated` label when applicable use `{components.departure-card.heading}` and `{components.departure-card.text}`; `{components.departure-card.attention}` is a restrained time signal. |
| **Disconnected State** | Use `{components.disconnected-state.surface}`, `{components.disconnected-state.border}`, and `{components.disconnected-state.status}` for a persistent visual state. Preserve useful cached ambient or calendar content where available, but never style the screen as active or ready. |
| **Retry Action** | Render `{components.retry-action.label}` as an explicit, focused action with `{components.retry-action.border}` and `{components.retry-action.focus}`. The action is visually separate from the unresolved turn and never resembles a replay or send button. See the [recovery key screen](mockups/key-recovery.html). |
| **Device Discovery** | Use `{components.device-discovery.row}` for discovered devices, `{components.device-discovery.selected}` for the selected row or focus, and `{components.device-discovery.divider}` between entries. Status must be readable in `{components.device-discovery.label}`; discovery is not approval. |
| **Device Setup** | Show the ordered setup steps with `{components.device-setup.step}`, `{components.device-setup.current}`, `{components.device-setup.complete}`, and `{components.device-setup.gap}`. The visual sequence is Room, Wake Mappings, then ready confirmation. See the [iOS setup key screen](mockups/key-ios-setup.html). |
| **Device Details** | Use `{components.device-details.surface}` and `{components.device-details.padding}` for a device's management surface. `{components.device-details.destructive}` identifies Disconnect/revocation; `{components.device-details.divider}` keeps credential and status information distinct. |
| **Local History** | Use `{components.local-history.row}` and `{components.local-history.text}` for intentional iOS/TUI history, with `{components.local-history.date}` for supporting metadata and `{components.local-history.divider}` for separation. Puck and Display surfaces do not expose this component. |
| **Prompt Mirror** | Use `{components.prompt-mirror.surface}`, `{components.prompt-mirror.border}`, and `{components.prompt-mirror.prompt}` to display an active Hermes clarification or approval prompt. `{components.prompt-mirror.waiting}` means the doorway is waiting for a spoken answer; no touch control is styled as available in v1. |
| **TUI Header** | Use `{components.tui-header.surface}` and `{components.tui-header.divider}` for the terminal header, with `{components.tui-header.profile}` showing the active Hermes Profile. It may be denser than iOS, but it must preserve profile identity and the shared phase vocabulary. |

## Do's and Don'ts

| Do | Don't |
|---|---|
| Put a clear readable state word beside any animation or sound cue. | Make a waveform, glow, or tone carry the only meaning. |
| Show the active Hermes Profile from the `heard` acknowledgement through completion in the response and companion headers. | Hide identity or imply that Missy is the product itself. |
| Keep idle Displays atmospheric and in the background. | Turn ambient photos into a notification wall or dashboard. |
| Let animation make a live response feel present; honor reduced motion with a static state. | Use motion that continues after completion or competes with the response text. |
| Use clear, fun, friendly presentation in the Display and tiny Puck status. | Put jokes, gamification, or invented answer content into the doorway layer. |
| Keep departure information visual-only and household-wide. | Add an unsolicited spoken or audible Departure Card. |
| Use contrast, labels, and state structure together. | Depend on color alone, especially for children or room-distance viewing. |
| Make Retry visibly mean reconnect only. | Label a replay or duplicate submission as Retry. |
| Preserve the dense Night Console structure where it helps scanning. | Add density that buries the current state or makes the Puck pretend to be a transcript surface. |
