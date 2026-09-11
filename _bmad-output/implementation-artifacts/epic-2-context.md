# Epic 2 Context: See and trust what the room is doing

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Epic 2 gives household Displays a calm, room-scoped view of ambient context
and the active conversation, including live capture, response, prompts, and
honest recovery. It makes the room legible without turning a passive Display
into another assistant: the selected doorway owns capture, Hermes authority,
and response audio, while other Displays only mirror the owning Room's state.

## Stories

- Story 2.1: Keep each Display in its Room-scoped Ambient Surface
- Story 2.2: Show live capture state and transcription
- Story 2.3: Mirror only the owning Room's Active Turn
- Story 2.4: Mirror Hermes prompts without becoming another assistant
- Story 2.5: Stay useful and honest when disconnected
- Surface story 2-A-1: Show the Android doorway's capture acknowledgement and live Transcription participant state
- Surface story 2-A-2: Show honest Android disconnected/unavailable state without stale-turn replay
- Surface story 2-WK-1: Render the shared Room-scoped Ambient Surface for web and iPad
- Surface story 2-WK-2: Render active capture, transcription, response, and phase state in W/K
- Surface story 2-WK-3: Mirror Hermes prompts without touch approval or a second Session
- Surface story 2-WK-4: Render honest disconnected state, cached context, and accessible recovery

## Requirements & Constraints

- The active Puck, ESP32 Touch Display, W/K browser, iOS Client, Android Client, or TUI shows
  its own capture state; the owning Room Display may mirror live Transcription
  and the canonical Turn Phase.
- W/K is one Web/iPad voice-plus-display surface. When its voice capability is
  active, it owns browser capture, response rendering, and response audio; it
  is not a passive mirror of itself.
- Active-turn text is room-local. Other Rooms receive no conversation text,
  prompts, or stale events. Passive Displays never capture, speak, create a
  Hermes Session, or offer touch-based prompt approval.
- Capture, response, and recovery must show the observed phase honestly:
  heard, listening, transcribing, thinking, buffering, speaking, complete, or
  Disconnected/Unavailable. No indefinite Thinking, false Speaking, or stale
  Listening state is allowed.
- Raw audio and transient transcription are not retained by the Puck, Display,
  or Media Server. Reconnect is explicit and never replays an uncertain turn.
- Idle Displays may show Room-scoped ambient or clearly marked cached content;
  higher-priority Active Turn and Departure Card state takes precedence.

## Technical Decisions

- The shared `DisplaySnapshot`/action contract, reducer, Room filtering, and
  normalized event feed are prerequisites. Surface presentation state belongs
  to the owning renderer; do not add a second database, broker, transcript
  store, or browser-side Hermes authority.
- The DOM-first Svelte renderer is the supported accessible W/K path; WASM is
  optional. Web/iPad and native LVGL share semantics but may adapt layout.
- The Python appliance owns authenticated Hermes sessions and sends normalized
  browser events through the same-origin channel. Browser code receives no
  bearer token and must not invent or replay answers.
- Use fake Hermes/WebSocket sessions and local fixtures for automated checks;
  reserve a live endpoint for the explicit text/voice smoke path. Shared
  contract changes require schema, fixture, Python, TypeScript, and target
  adapter coverage together.

## UX & Interaction Patterns

The browser surface distinguishes live user Transcription from streamed and
completed Hermes response text. Active state is visually and semantically
clear, with accessible DOM/live-region behavior and no reliance on color alone.
After a terminal turn, a completed response may remain visible where supported;
the surface then returns to the Room's Ambient Surface without archiving the
conversation. Ambient imagery stays quiet and never competes with load-bearing
capture, response, prompt, or disconnected state.

## Cross-Story Dependencies

- All Epic 2 surfaces depend on the shared snapshot/reducer, Room ownership,
  normalized events, and honest phase semantics.
- W/K `2-WK-2` consumes the Epic 1 W/K doorway's capture, response-text, audio,
  and terminal lifecycle. The merged browser audio repair is foundation; the
  follow-on `WK-1` recovery slice remains separately tracked.
- W/K prompt and disconnected stories use the same presentation and cleanup
  boundaries. No calendar or Device-administration prerequisite is required.
