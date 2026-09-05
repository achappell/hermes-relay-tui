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
- `handsfree.py` — turns a wake event into exactly one session turn.
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
`history.py`, `wake.py`, `handsfree.py`.

**Front-end-specific:** `app.py` (Textual), `transcript.py` (Rich rendering for
a terminal transcript), and `home_display/` (the household appliance: its
display server, state channel, and `appliance.py` loop).

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

**When to split into separate repositories:** not yet, and not on
anticipated growth. The trigger is a genuine, demonstrated dependency
conflict — a front end needing a package version another front end cannot
accept, or a platform-specific wheel that will not install alongside the
existing stack. At that point the core becomes an installable
`hermes-relay-core` package that each front end depends on. Until `pip
install` actually fails, one repository is cheaper than keeping two in
version lockstep.

**Naming:** the repository name `hermes-relay-tui` stops describing the
contents once a second, non-terminal front end lands. Renaming is deferred
until that front end exists rather than done speculatively, because the name
is currently load-bearing in the published package name, the Homebrew tap
(`achappell/homebrew-hermes-relay`), and the release workflow — see
`DIST-02`.

## GitHub Project task management — check this first

Before answering "what's next" or starting any work, inspect the
[Hermes Streaming TUI GitHub Project](https://github.com/users/achappell/projects/3/views/2)
first. It is the sole source of truth for task scope, priority, ownership,
dependencies, and progress — not `docs/plans/`, not `.hermes/plans/`, not this
file's own roadmap-sounding prose. Those directories hold design history,
testing procedures, and superseded operating-model proposals; none of them is
a task queue, and several are stale relative to the board. If a plan file's
status conflicts with the board, the board wins.

```bash
gh project item-list 3 --owner achappell --format json -L 100
```

- Before starting work, inspect the project and choose the highest-priority
  unblocked item in `Ready` or `Building`. Do not invent a parallel task list
  in the repository.
- Give every substantive task a project item. Shape new items with an
  outcome, acceptance criteria, UX expectations, and a validation scenario;
  fill in `Priority`, `Area`, `Layer`, and `Horizon`.
- Move work through the `Workflow` field: `Inbox` → `Ready` → `Building` →
  `Verify` → `Done`. Use `Blocked` when progress depends on Hermes, a
  protocol change, an external service, or an explicit design decision.
- Keep the built-in `Status` field aligned with `Workflow` (`Todo` for
  planned work, `In Progress` for active work, and `Done` only after
  completion). `Workflow` is the board's kanban state.
- Keep one active vertical slice in `Building`. Move the current item there
  before implementation and move it out promptly when the work is blocked,
  ready for verification, or complete.
- Manage the board continuously as the work changes: add newly discovered
  follow-ups, split oversized tasks, edit acceptance criteria, link PRs and
  evidence, remove duplicates or abandoned tasks, and delete stale work
  rather than leaving ghosts in `Building`.
- When blocked, record the concrete blocker and the next unblocking action
  on the item. Do not present a local fallback as complete relay support.
- Move an item to `Verify` after implementation, then run focused tests, the
  full suite, and the required manual smoke test. Record the evidence on the
  item; move it to `Done` only when the change is validated and merged.
- At the end of a work session, reconcile the board with the code and GitHub
  state: no completed item left in `Building`, no active work without a
  card, and no release or administrative PR allowed to hide unfinished
  product work.
- When multiple `Ready` items tie on `Priority` and `Horizon`, ask which one
  to pick rather than guessing — the board doesn't encode a tiebreaker.

## Working agreement

- Keep the code modular and direct. Avoid abstractions that do not remove real duplication.
- Preserve the existing voice-session protocol and event names unless a protocol change is explicitly requested.
- Do not commit bearer tokens, profile `.env` files, audio captures, or machine-specific credentials.
- Treat the default endpoint as runtime configuration, not a test fixture. Tests should use fake sessions and WebSocket objects.
- Keep streamed text inline in the transcript. A widget that renders every delta on a separate line is a regression.
- Keep the UI responsive: blocking microphone capture and audio writes belong off the Textual event loop.
- Record non-blocking bugs and usability snags in `docs/friction-log.md`; defer them unless they block current work, risk data loss, or repeat.
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
- Use `/queue` to inspect or edit queued prompts.
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
  It is off at every launch; `hermes-relay --wake-enabled` refuses rather than
  arming a microphone from a command-line flag. `/wake off` closes the input
  stream, it does not merely pause the detector. A successful `/reload` and a
  connection loss both disarm wake mode and report that `/wake on` is required
  to arm it again; reconnect never reopens the microphone silently. After a
  wake-triggered response, the TUI listens for a bounded follow-up window
  (`--wake-followup-seconds`, default 8 seconds) without another wake phrase.
  Saying exactly `stop` during hands-free capture closes it locally and
  silently, both for the initial wake capture and that follow-up window;
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
- `F1` displays help in the transcript.
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
- `--wake-followup-seconds` — silence window after a wake-triggered response before returning to wake-word detection.
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
  guarded by a timeout, and a wake open that outlives cancellation closes its
  recorder after the late open completes. Do not add a shutdown path that
  leaves PortAudio cleanup to its process-exit handler.
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
