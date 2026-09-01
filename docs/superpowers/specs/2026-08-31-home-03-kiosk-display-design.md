# HOME-03 Kiosk Display Shell and State Channel

Status: Design approved in chat; implementation not started.

Project item: `HOME-03 Kiosk display shell and state channel`

## Outcome

The repository gains a second, non-terminal front-end foundation for a
household voice/display appliance. A local Chromium kiosk renders the unit's
current state over a localhost WebSocket. The surface is calm and ambient at
rest, becomes a temporary voice-status surface during a turn, and has clear
extension points for future touch controls, photos, and video.

The first implementation is a display shell and fake-state demonstration. It
does not capture audio, connect to Hermes, play photos, or play YouTube media.

## Product decisions

- The front end lives in this repository and has its own `home_display/`
  directory. A repository split is not justified.
- The display is a browser-based kiosk surface, not Textual, Pygame, or a
  terminal transcript.
- The first visual direction is an ambient canvas: media can own the screen at
  rest, while assistant state and responses appear as a temporary overlay.
- Future controls use a bottom-sheet reveal, preserving the ambient content
  while exposing large shared-device actions.
- The first slice has no visible touch controls, but its component and protocol
  boundaries must support touch, mouse, and stylus input later.
- Actual photo playback belongs to `HOME-04`. YouTube is a later media
  provider, not part of this slice.
- Node/Svelte/Vite are build-time tools. The appliance runs Python and
  Chromium; Node is not a device runtime requirement.

## Scope

### In scope

- A Svelte/Vite web application under `home_display/web/`.
- A Python local host that serves the built assets and exposes the display
  state channel on loopback.
- A typed, versioned snapshot model and publisher.
- Ambient, listening, thinking, speaking, buffering, error, and disconnected
  surfaces.
- Stable streamed response rendering in one DOM region.
- Browser reconnect behavior and current-snapshot hydration.
- A deterministic fake state source for browser/manual validation.
- Build and focused test commands for the Python host and web application.

### Out of scope

- Real Hermes session orchestration or wake-word capture.
- Microphone, speaker, echo cancellation, or hardware bring-up (`HOME-02`,
  `HOME-05`).
- Photo discovery, Immich integration, slideshow timing, or local photo cache
  (`HOME-04`).
- YouTube integration or a general media catalog.
- Chromium autostart, process supervision, or headless recovery (`HOME-06`).
- Visible touch controls in the first implementation.

## Architecture

```text
HermesSession / future home coordinator
             │
             ▼
      home_display.state
             │ snapshots
             ▼
      home_display.server ── localhost WebSocket ──► Chromium kiosk
             │                                      │
             └── static built assets ◄─────────────┘
```

The Python display host owns transport and the latest published snapshot. It
does not own a Hermes turn and does not import `app.py` or Textual. A future
`hermes-relay-home` entry point will connect `HermesSession`, wake-word/audio
coordination, and this publisher.

The web application owns presentation state only. It must not infer session
state from timing, call Hermes, or duplicate protocol parsing. UI-local actions
such as opening or dismissing the future bottom sheet remain in the browser;
device actions eventually become explicit typed intents.

Proposed source layout:

```text
home_display/
  __init__.py
  server.py
  state.py
  web/
    package.json
    src/
      App.svelte
      surfaces/
      state/
      media/
      input/
  static/                 # production build output
```

The host binds to `127.0.0.1` initially and serves the static assets and
WebSocket endpoint from one configured local origin. The serving adapter may
use the existing `websockets` dependency and standard-library HTTP support; it
must not require a new base runtime dependency merely to serve the shell.

## State channel

The channel publishes complete snapshots, not replayable event logs or
token-per-message UI instructions:

```json
{
  "type": "snapshot",
  "schema": 1,
  "sequence": 42,
  "state": "speaking",
  "response_text": "The answer so far…",
  "status_text": null,
  "media": null
}
```

Rules:

- `state` is one of `idle`, `listening`, `thinking`, `speaking`, `buffering`,
  `error`, or `disconnected`.
- `schema` permits an intentional future protocol revision.
- `sequence` increases for each published snapshot. The browser ignores older
  snapshots.
- A newly connected browser receives the latest snapshot immediately.
- `response_text` replaces one stable response region as it grows.
- `status_text` is short display-safe supporting text, not a traceback.
- `media` is nullable and reserved for future provider descriptors; HOME-03
  does not resolve or play media.
- An outbound `intent` envelope is reserved for future touch actions. No
  visible control emits one in this slice.
- Malformed or unsupported snapshots produce a safe display error and do not
  crash the browser.

## Display behavior

- **Idle:** ambient canvas with no persistent assistant chrome.
- **Listening:** calm listening indicator without a noisy transcript.
- **Thinking:** subtle working state.
- **Speaking:** temporary response overlay with inline, readable text.
- **Buffering:** honest indication that audio or response data is still being
  collected or recovered.
- **Error/disconnected:** concise explanation and next action; never a stack
  trace, bearer token, or stale `ready` state.

The layout is responsive to the selected landscape panel and targets legibility
from roughly two metres. The future touch grammar is a bottom sheet: tapping
the ambient surface reveals large actions while preserving the underlying
content, and dismissing it restores the canvas.

## Testing and validation

Python tests cover:

- Snapshot construction, JSON serialization, and allowed state values.
- Monotonic sequence behavior and current-snapshot delivery on connect.
- Loopback binding and malformed inbound/outbound message handling.
- Fake state transitions without Hermes or audio hardware.

Web tests cover:

- Rendering each supported state.
- Ignoring stale snapshots.
- Replacing one response region as text grows.
- WebSocket disconnect and reconnect behavior.
- Responsive shell structure and the absence of terminal-specific UI.

Build and manual validation:

1. Build the web assets with the supported frontend build command.
2. Launch the fake state source and local display host.
3. Exercise idle → listening → thinking → speaking → buffering → idle.
4. Stop the Python host and confirm a calm disconnected surface.
5. Restart it and confirm the browser reconnects and hydrates from the latest
   snapshot.
6. Review the landscape layout at approximately two metres and confirm the
   response remains one stable readable block.

CI must not require a live Hermes endpoint, microphone, speaker, photo library,
YouTube, or target appliance hardware.

## Acceptance criteria

- The new display package is isolated from Textual and can be driven by a fake
  state source.
- All seven states have distinct, glanceable presentations.
- A reconnecting browser shows disconnected honestly and recovers without a
  page restart.
- Streamed response text remains one stable block.
- The host serves only on loopback and keeps the browser free of session logic.
- The build works without Node installed on the eventual appliance.
- The architecture leaves explicit seams for future touch intents, photo
  playback, and video providers without expanding HOME-03 into those systems.
