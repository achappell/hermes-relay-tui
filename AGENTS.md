# AGENTS.md

## Project

This repository contains a small Python/Textual terminal UI for the Hermes voice-session WebSocket channel. It keeps the user interface, protocol client, audio playback, microphone loading, and configuration in separate modules:

- `app.py` — Textual application, transcript rendering, turn lifecycle, and CLI entry point.
- `session.py` — connection, turn lifecycle, and microphone wiring for one session.
- `client.py` — Hermes `hello` handshake and streamed turn events.
- `config.py` — command-line arguments, environment variables, token lookup, and connection defaults.
- `diagnostics.py` — opt-in content-safe protocol and turn tracing for live debugging.
- `audio.py` — streamed signed 16-bit PCM playback and WAV fallback.
- `earcons.py` — short generated tones for wake and end-of-capture acknowledgement.
- `voice.py` — owned local microphone capture (sounddevice) and speech-to-text (faster-whisper).
- `mic.py` — device-selection and cancellation glue around `voice.py`'s recorder.
- `wake.py` — wake-word detection and the listener worker for hands-free capture.
- `handsfree.py` — turns a wake event into one or more session turns.
- `home_display/appliance.py` — the home unit's front end: joins the session,
  the wake listener, audio playback, and the display state channel.
- `transcript.py` — typed transcript records and Rich Markdown rendering.
- `tests/` — unit and integration-style tests using fakes; do not require a live Hermes endpoint.

The implementation is a laptop-side client. The Hermes server owns sessions, model routing, speech generation, and the voice-session protocol.

## Core and front ends

The repository is expected to hold more than one front end: the Textual TUI
today, and a household voice/display client (`HOME-*`) alongside it. The
modules are therefore split into a front-end-agnostic **core** and the front
ends that consume it.

**Core — must not import a user-interface framework:**
`session.py`, `client.py`, `config.py`, `diagnostics.py`, `audio.py`,
`earcons.py`, `mic.py`, `shell.py`, `attachments.py`, `clipboard.py`,
`history.py`, `timing.py`, `wake.py`, `handsfree.py`, `domain.py`.

**Front-end-specific:** `app.py` (Textual), `transcript.py` (Rich rendering for
a terminal transcript), `prompts.py` (structured-prompt state and rendering
for the Textual TUI), `session_picker.py` (interactive session picker modal for
the Textual TUI), `home_display/` (the household appliance: its
display server, state channel, and `appliance.py` loop), and
`firmware/esp32-s3-touch-lcd-7/` (the unified C / LVGL smart display firmware
and simulator).

### Smart Display Appliance & Shared LVGL Architecture

The smart display appliance UI is powered by a **Single-Source C / LVGL UI Engine**
located in `firmware/esp32-s3-touch-lcd-7/main/src/`:

- **Modular UI Components (`ui_*.c`):** Implements appliance states (`ui_snapshot.c`),
  interactive prompt dialogs (`ui_prompt.c`), timers, weather, and context cards in C using LVGL 8.
- **Three Compilation Targets from One Codebase:**
  1. **Physical ESP32-S3 Hardware:** Waveshare ESP32-S3-Touch-LCD-7B (1024×600 RGB LCD,
     GT911 capacitive touch over I2C, 8MB Octal PSRAM double buffering, dual I2S audio).
  2. **Native macOS Desktop Simulator:** Compiles the exact C codebase directly on macOS via
     Clang and SDL2 (`./scripts/simulate_native.sh`) for rapid desktop UI development.
  3. **WebAssembly Web Kiosk (HOME-16):** Compiles the C/LVGL UI to WebAssembly (`.wasm`),
     hosted in an HTML5 `<canvas>` for iPad / Chromium kiosks with a lightweight
     Web Audio and WebSocket bridge.
- **Shared State Contract:** All targets consume the exact same `/ws` `DisplaySnapshot`
  JSON stream from `home_display/server.py` and dispatch touch choices back to `/action`.

The ESP32-S3 touch target is a first-class Epic 1 voice-plus-display surface,
not only a passive room mirror. Its product scope includes microphone capture,
native response/phase rendering, and response-audio delivery. The shared
`DisplaySnapshot` contract carries visual state and response presentation; a
separate bounded audio/session adapter must carry microphone and response PCM.
The current firmware transport implements snapshot receipt and `/action` only,
so that audio path remains an explicit implementation slice. Hermes answer
authority and no-replay session semantics stay behind the owning adapter; the
firmware must not invent responses or parse Hermes wire frames.


Rules:

- A core module may not import `textual`, and may not assume a terminal,
  a keyboard, a scrollback transcript, or a human watching a screen.
  `tests/test_core_boundary.py` enforces the import half of this by
  importing each core module in a subprocess and failing if Textual
  appears in `sys.modules`.
- A front end drives a session through `session.SessionProtocol`. New front
  ends implement against that protocol rather than importing `app.py`.
- Presentation decisions — wording, layout, state labels, colour — belong to
  the front end. The core returns normalized events and raises typed errors;
  it does not format user-facing strings for a specific surface.
- When a second front end is added, it gets its own directory and its own
  `[project.scripts]` console entry point, sharing the core by plain import.
  Front-end-only dependencies (wake-word engine, TTS, display driver) belong
  in a `[project.optional-dependencies]` extra, not the base dependency list,
  so installing the TUI does not drag in appliance hardware libraries.

**Repository boundary:** the native Apple client lives in the sibling
`~/Development/hermes-relay-ios` repository, and the feature-parity native
Android client is planned for the sibling `~/Development/hermes-relay-android`
repository. Those splits are intentional: keep SwiftUI, Android platform
services, mobile lifecycle/audio/secure-storage concerns, and terminal-specific
UI assumptions in their respective delivery repositories. Extracting a shared
`hermes-relay-core` package remains gated by a demonstrated dependency or
ownership conflict, not by speculative growth. The repository name and
published package remain `hermes-relay-tui`; see `DIST-02` for release
implications.

## BMad project workflow

This repository uses BMad for product discovery, architecture, UX, story
specification, implementation planning, and review. The Personal Vault is now
the canonical home for durable cross-repository product intent and
reconciliation decisions:

`~/Documents/Vaults/Personal Vault/projects/hermes-home/hermes-home.md`

BMad artifacts are part of the engineering record. While GitHub Project work
is paused, [`_bmad-output/implementation-artifacts/surface-coverage-matrix.md`](_bmad-output/implementation-artifacts/surface-coverage-matrix.md)
is a thin shared cross-repository coverage and dependency index, not a second
backlog or status system. The Personal Vault remains canonical for durable
product intent and reconciliation; local BMad artifacts remain the delivery
record for each repository. See
[`docs/bmad-upstream.md`](docs/bmad-upstream.md) for the delivery boundary and
reading order.

- Existing tracked planning artifacts under `_bmad-output/planning-artifacts/`
  are preserved historical snapshots and implementation evidence. Read the
  relevant Personal Vault hub and source notes first; do not create a second,
  silently divergent PRD or epic set here.
- Tracked implementation artifacts live under
  `_bmad-output/implementation-artifacts/`. Keep active story specifications,
  task lists, validation notes, and sprint-status evidence aligned with the
  implementation when the BMad workflow calls for them.
- Run the BMad build workflow for substantive feature or story work. Follow
  its clarify, plan, implement, review, and presentation gates; do not jump
  from a board title straight to code when the workflow requires a ready
  specification.
- Use the repository-local BMAD runtime at the intentional shared version; do
  not copy `_bmad/` or local tool configuration from `hermes-relay-ios`.
- Keep one active vertical slice per repository/workstream. Independent TUI
  and iOS cards may both be in `Building` when their contracts are settled and
  their files do not contend. Shared protocol or contract work remains a
  prerequisite when both clients depend on it. Feed durable cross-repository
  discoveries back to the Personal Vault hub.
- Surface-specific story maps in `_bmad-output/planning-artifacts/epics.md`
  define story identities and scope. A story closes only the named surface;
  `I`, `P`, `E`, `W/K`, and `T` are separate delivery boundaries, with W/K
  covering both web and iPad deployment and the ESP32 Touch Display owning
  both its voice and display behavior.
- The owning repository's story specification, validation record, and local
  `sprint-status.yaml` are authoritative for delivery status and formal
  closure. Never infer closure from another surface's implementation or from
  a matrix row.
- Read the surface coverage index before selecting the next story. Use it to
  find applicable surfaces, cross-repository gaps, evidence, and shared
  prerequisites; then follow the story ID to its owning `epics.md` and story
  artifact. The index must not duplicate acceptance criteria, formal status,
  or a task queue.
- Update the surface coverage index only when surface applicability, evidence,
  ownership, or a cross-surface dependency changes. Keep it compact: story
  IDs, owner, evidence/dependency, and links to the authoritative artifacts.
- After a planning change is merged, run the BMad sprint-planning readiness
  gate and refresh the local sprint tracker from the surface-specific epics
  before selecting new implementation work. Preserve the matrix as planning
  context, not as a replacement for the tracker.
- The BMad framework under `_bmad/` and local tool integrations under
  `.agents/`, `.claude/`, and `.opencode/` are tooling, not product scope by
  themselves. Rendered workflow/cache output is transient. Include these
  directories in a commit only when their repository-wide adoption is
  intentional and reviewed; never sweep them into a feature commit merely
  because they appear as untracked files.
- Before a BMad implementation, use a clean, appropriately named feature
  branch or worktree. Preserve unrelated local tooling and generated files;
  review the exact staged paths before committing. Never commit bearer tokens,
  profile `.env` files, audio captures, or machine-specific credentials.

## GitHub Project task management — paused by Amanda

Amanda has explicitly paused GitHub Project #3 work while the local BMad
surface reconciliation is completed. Until she explicitly reopens the board:

- Do not inspect, query, create, edit, move, delete, or reconcile Project #3
  items for ordinary planning or implementation.
- Do not require a GitHub card before doing local BMad reconciliation, and do
  not present the board as the current source of truth for next-story choice.
- Before answering "what's next" or starting substantive story work, read
  [`_bmad-output/implementation-artifacts/surface-coverage-matrix.md`](_bmad-output/implementation-artifacts/surface-coverage-matrix.md),
  the relevant epic context, and the owning repository's implementation or
  validation artifacts.
- Prioritize, in order: finish an `In review` slice whose build or validation
  gate is close and unlocks later stories; then choose an open story with the
  strongest useful coverage across incomplete surfaces and settled
  prerequisites; then choose the smallest independently verifiable vertical
  slice. Keep one active slice per repository/workstream.
- Use local `sprint-status.yaml` and story artifacts to record delivery state.
  The surface coverage index records cross-surface evidence and dependencies,
  not formal closure in another repository and not a replacement task queue.
- Do not use this pause to create a competing backlog in `docs/plans/` or
  `.hermes/plans/`; select from the existing BMad epics/stories and record any
  prioritization decision in the appropriate local implementation artifact.

When Amanda explicitly reopens GitHub Project work, restore the board procedure
before choosing a new board-scoped task: run `gh auth status`, verify the
credential scopes, inspect Project #3, and reconcile its state with the matrix
and local artifacts. Never print token values.

## Working agreement

- Keep the code modular and direct. Avoid abstractions that do not remove real duplication.
- Preserve the existing voice-session protocol and event names unless a protocol change is explicitly requested.
- Do not commit bearer tokens, profile `.env` files, audio captures, or machine-specific credentials.
- Treat the default endpoint as runtime configuration, not a test fixture. Tests should use fake sessions and WebSocket objects.
- Keep streamed text inline in the transcript. A widget that renders every delta on a separate line is a regression.
- Keep the UI responsive: blocking microphone capture and audio writes belong off the Textual event loop.
- When changing behavior, update or add a focused test in `tests/` before declaring the work finished.

## Setup

Use the repository virtual environment when it exists:

```bash
venv/bin/pip install -r requirements-dev.txt
```

relay-tui owns its voice path directly (`voice.py`), so this environment must include the voice stack declared in `requirements.txt` (`PyYAML`, `numpy`, `sounddevice`, and `faster-whisper`). No Hermes checkout is needed for microphone capture or local transcription.

For a fresh checkout, create it with the repository's supported Python version (currently Python 3.14):

```bash
python3.14 -m venv venv
venv/bin/pip install -r requirements-dev.txt
```

## Verification

Run the complete suite from the repository root:

```bash
venv/bin/pytest
```

For a focused change, run the closest test module first, then the complete suite. There is no formatter or linter configured in this repository; keep formatting consistent with the surrounding Python code.

## Running the TUI

The entry point is `app.py`:

```bash
VOICE_SESSION_TOKEN='redacted-token' venv/bin/python app.py
```

The client can also read `VOICE_SESSION_TOKEN` from `--profile-env`, which defaults to `~/.hermes-relay-tui/.env`. Existing installs using `~/.hermes/profiles/amanda/.env` are recognized as a migration fallback when the new default file is absent. The token precedence is:

1. `--token`
2. `VOICE_SESSION_TOKEN`
3. `VOICE_SESSION_TOKEN` in the profile `.env`

Do not put a real token in this file or in the README.

### Controls

- Type a message in the multiline composer and press `Enter` to send it.
- Press `Shift+Enter` or `Alt+Enter` to insert a newline without submitting.
- Type `/` and a command name directly in the composer, same as any other text; a live, non-blocking suggestion line above the composer shows matching commands and their args/description as you type, and disappears once you've typed a space or the text stops looking like a command.
- Press `Tab` after `/` to complete a uniquely-matching command name in place, without leaving the composer.
- While a turn is active, ordinary prompts follow `--busy-mode` (`queue` by default; `steer` or `interrupt` are alternatives).
- Queued prompts are shown in the ambient queue shelf; `/undo` removes the last
  unsent local prompt.
- Use `/busy [queue|steer|interrupt]` to change the mode for the current session.
- Use `/details [show|hide]` or `--hide-thinking` to control thinking/tool detail in the transcript.
- The voice status line carries a `◉ mic open` marker whenever the input
  device is open — `app.microphone_is_open` is the single source: a capture in
  flight, or wake mode holding the stream. Gate it on a feature rather than on
  the device and the same open microphone renders two ways depending on which
  path opened it. The state word describes the phase; the marker describes the
  hardware.
- Repainting is not automatic. Arming while idle does not change `voice_state`,
  and a capture starting does not always either, so `_arm_wake`, `_disarm_wake`
  and the capture teardown all call `_refresh_voice_status` directly. The
  capture task must also be assigned *before* the listening state paints.
- Use `/wake [on|off|status]` to arm or release local hands-free listening.
  It is off by default; `wake_enabled: true` in config or
  `hermes-relay --wake-enabled` arms it after the initial connection. `/wake
  off` closes the input stream, it does not merely pause the detector. A
  successful `/reload` and a connection loss both disarm wake mode and report
  that `/wake on` is required to arm it again; reconnect never reopens the
  microphone silently. After each successful wake-triggered response, the TUI
  opens a bounded wake-free follow-up window (`--wake-followup-seconds`,
  default 8 seconds) and reopens it after every non-empty follow-up without
  another wake phrase. Silence, exact `stop`, failure, disconnect, or disarm
  returns to wake detection.
  Saying exactly `stop` during hands-free capture closes it locally and
  silently, both for the initial wake capture and any follow-up window;
  normal terminal punctuation from transcription is ignored, while longer
  phrases and `Ctrl+R` remain ordinary turns.
  `/wake on` reports model-loading and microphone-opening stages without
  blocking the Textual event loop; a slow or failed startup must leave the
  microphone disarmed, and `/wake off`, reload, connection loss, and quit must
  cancel in-flight startup.
  A malformed reload leaves an already-armed listener unchanged.
- Use `/audio [list|status|input <device>|output <device>]` to inspect and select local audio devices for the current session.
- Use `/image <path>`, `/image list`, or `/image clear` to stage and inspect local image attachments. `@path` references support local path completion; the current relay reports attachments as unsupported rather than sending them.
- Use `!command` or `{!command}` only after opting in with `--allow-shell`; execution is local, bounded, and visible, with shell operators rejected.
- Use `/reload` to re-read the config file/environment without restarting. Any of busy-mode, show-details, or audio devices you've changed interactively this session are left alone; everything else picks up the new values. A malformed config file reports an error instead of crashing.
- Drag across transcript text to select it; releasing the mouse copies the selection, shows a brief toast, and clears the selection after success. `Ctrl+C` copies an existing selection or, with no selection, interrupts the active turn or, when idle, clears the draft, queue, or exits.
- Steering happens when an ordinary message is submitted in `--busy-mode steer`; there is no separate slash command.
- Slash commands are routed before ordinary text; do not silently send an unknown command as a model prompt.
- `Ctrl+R` captures a local microphone turn and sends its transcript.
- `F1` opens temporary keyboard help; Escape closes it without adding help to
  the transcript.
- `Ctrl+Q` quits.

### Important options

The complete source of truth is `config.build_arg_parser()`. The main runtime options are:

- `--url` — voice-session WebSocket URL.
- `--session-id` — session to create or resume.
- `--profile-env` — optional `.env` file containing the bearer token.
- `--no-play` — buffer audio without opening the local speaker.
- `--output PATH` — save response audio as WAV; later turns receive numbered suffixes.
- `--turn-timeout SECONDS` — response timeout; default is 195 seconds, and `0` disables it.
- `--connect-retries COUNT` — additional connection attempts after the first failure; default is 3.
- `--connect-retry-delay SECONDS` — base delay before reconnect attempts; default is 1 second.
- `--busy-mode MODE` — active-turn behavior: `queue` (default), `steer`, or `interrupt`.
- `--allow-shell` — opt in to bounded local `!command` execution and `{!command}` interpolation; disabled by default.
- `--no-earcons` — silence the home unit's wake and end-of-capture tones; the
  wake word keeps working.
- `--wake-barge-in` — opt in to calibrated, windowed local speech detection
  during an active response. The energy trigger stops playback and sends one
  remote interrupt before local STT finishes; only a non-empty transcript
  becomes a replacement turn, and playback transcripts matching the current
  assistant text are discarded as likely echo. Exact `stop` sends no
  replacement turn. Keep it off unless the audio route has echo cancellation
  or equivalent isolation.
- `--hide-thinking` — hide thinking and tool detail in the transcript.
- `--debug` — write a content-safe protocol trace to a temporary log file.
- `--log-file PATH` — choose the debug trace path; supplying it implies `--debug`.
- Uncaught main-thread and worker-thread exceptions are always appended to the
  private `~/.hermes-relay-tui/crash.log`; `/logs` reports its status without
  exposing contents.
- `--mic-max-seconds`, `--mic-silence-duration`, `--mic-silence-threshold` — microphone tuning; TUI silence endpointing defaults to 1.5 seconds.
- `--wake-barge-in-min-speech-duration` — windowed microphone energy required
  before immediate interruption; local STT decides whether to follow up;
  default `0.30` seconds.
- `--wake-followup-seconds` — bounded silence window for each wake-free follow-up after a successful response; each non-empty follow-up opens another window.
- `--mic-input-device`, `--audio-output-device` — optional local input/output device name or index; `default` restores the system default.
- `--stt-model` — optional local Faster-Whisper model selection.

Relevant environment variables include `HERMES_VOICE_SESSION_URL`, `VOICE_SESSION_TOKEN`, `VOICE_SESSION_CLIENT_ID`, `VOICE_SESSION_DEVICE_ID`, `VOICE_SESSION_ID`, `VOICE_SESSION_MIC_MAX_SECONDS`, `VOICE_SESSION_MIC_SILENCE_DURATION`, `VOICE_SESSION_MIC_SILENCE_THRESHOLD`, `VOICE_SESSION_MIC_INPUT_DEVICE`, `VOICE_SESSION_AUDIO_OUTPUT_DEVICE`, `VOICE_SESSION_STT_MODEL`, `VOICE_SESSION_WAKE_FOLLOWUP_SECONDS`, `VOICE_SESSION_WAKE_BARGE_IN_MIN_SPEECH_DURATION`, `VOICE_SESSION_TURN_TIMEOUT`, `VOICE_SESSION_CONNECT_RETRIES`, `VOICE_SESSION_CONNECT_RETRY_DELAY`, `VOICE_SESSION_BUSY_MODE`, and `HERMES_RELAY_TUI_ALLOW_SHELL`.

`HERMES_RELAY_TUI_DEBUG` and `HERMES_RELAY_TUI_LOG_FILE` configure the
optional debug trace without command-line flags. The trace records event
ordering, protocol event names, payload keys, text/byte lengths, and short
SHA-256 fingerprints. It intentionally does not record bearer tokens, prompts,
response text, or audio contents. The always-on crash report records only
structural traceback locations and exception types, never exception messages or
local variable values; it appends until manually removed.

## Integration boundaries

- `client.send_hello()` sends the protocol v1 `hello` payload and requires a `hello_ack` response.
- `client.send_turn()` sends a transcript turn and yields normalized events for text, activity, audio, errors, and turn completion; unknown server events become explicit diagnostics.
- Hermes splits one answer into segments, each carrying its own `draft_id`,
  streaming cumulatively, and finishing with its own `text` frame. `client.py`
  banks each finished segment in `committed` and keeps `rendered_preview` for
  the segment in progress; segments are joined with a blank line into one
  assistant message. A `text_replace` must always carry the finished segments
  with it — emitting only the current segment silently deletes the earlier
  ones, which is exactly what TURN-03 fixed.
- `app.py` prepares local attachment metadata and optional shell substitutions before submission. The current channel remains text-only: attachment-bearing prompts stop visibly before `client.send_turn()` rather than using an invented wire payload.
- Binary WebSocket frames are raw PCM audio. `audio_start` supplies sample rate, channel count, and sample width.
- `app.py` owns presentation and turn state. It should not grow protocol parsing logic that belongs in `client.py`.
- Thinking/status/tool activity is rendered as a replaceable transcript line; the assistant response gets its own line once text begins, so repeated activity cannot pollute the final answer.
- `voice.py` owns `LocalMicrophone`, its sounddevice-based recorder, and faster-whisper transcription; `mic.py`'s adapter supplies session-local input selection and cancellation on top of it. The project's voice dependencies (`sounddevice`, `numpy`, `faster-whisper`) must be installed for `Ctrl+R` to work.
- `BargeInListener` follows Hermes' full-duplex shape: it calibrates the quiet
  room before playback, holds that floor while the speaker is active, applies
  playback grace/headroom, and uses a majority energy window. If that room
  floor is already loud, it reduces the multiplier so the trigger remains
  reachable without treating steady background audio as speech. Its speech
  callback interrupts immediately; local STT decides whether the captured
  phrase becomes a follow-up turn.
- `wake.WakeListener.pause()` and `resume()` both drain the frame queue.
  `on_wake` blocks the listener's worker for the whole turn, so frames
  captured just before the pause pile up with nothing consuming them, and
  `resume()` runs before `on_wake` returns — scoring that backlog re-detects
  the same spoken phrase. Resetting the detector alone does not prevent it.
- `earcons.py` generates its own tones and plays them on a stream of its own.
  It must never share `audio.PCMPlayer`: the appliance closes that player for
  barge-in and end-of-turn, so a shared stream lets a courtesy tone cut off a
  sentence. An earcon failure is logged and dropped, never raised.
- App shutdown cancels the active capture/turn workers before releasing audio.
  `PCMPlayer.abort()` is used for Ctrl+C, quit, interruption, and
  `audio_abort`; normal `close()` remains the draining path for successful
  playback. The wake capture is cancelled before its listener is joined, and
  an active earcon is aborted before that join. Native stream close calls are
  guarded by a timeout; a timed-out stream is poisoned and cannot be reopened,
  while a reader that remains stuck retains deferred close ownership until it
  exits. A wake open that outlives cancellation closes its recorder after the
  late open completes, and that cleanup task is retained by the app. Do not
  add a shutdown path that leaves PortAudio cleanup to its process-exit handler.
- The wake tone blocks in `HandsFreeCoordinator.on_wake` between
  `ACKNOWLEDGING` and the capture. That ordering is the guarantee that the
  unit cannot record its own acknowledgement; do not make it asynchronous.
- `audio.py` supports signed 16-bit PCM for live playback. If playback cannot start, the app reports buffering and can still save the collected PCM as WAV.
- Connection setup uses bounded exponential-backoff retries. Prompts that cannot be sent remain FIFO-queued; a turn that may have reached Hermes is never replayed automatically after a socket failure.
- When `hello_ack` advertises the `interrupt` capability, the client sends an explicit interrupt frame for the active turn and waits for `turn_interrupted`; `audio_abort` is a typed, intentional playback event rather than an unhandled server event. Late JSON frames carrying another turn ID are discarded. Older endpoints without the capability retain the close-and-reconnect fallback and are never described as server-confirmed cancellation.
- On macOS, microphone permission belongs to the launching app (Terminal, iTerm, VS Code, or the IDE), and a missing accessible default input is reported by PortAudio as device `-1`.

## Change checklist

Before handing off a change:

1. Run the focused tests for the changed module.
2. Run `venv/bin/pytest`.
3. If the change affects the live channel, exercise a text turn, a voice turn, and the failure path against a deliberately configured endpoint.
4. Review `git diff` for credentials, generated audio, cache files, and accidental edits outside the requested scope.

The design and implementation history live under `docs/superpowers/` and `docs/plans/`; consult them when changing the architecture, but keep this file and the code as the operational source of truth.
