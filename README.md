# Hermes Streaming TUI

A small Textual terminal UI for authenticated Hermes voice sessions. Type text, capture a local microphone turn, watch the reply stream into the transcript, and play streamed PCM audio locally.

This is a client for the existing Hermes voice-session channel. It does not run the Hermes server or provide a session browser.

## Features

- Streaming text transcript rendered inline as deltas arrive.
- Text turns submitted from the input box.
- Local microphone capture with Hermes' `LocalMicrophone` and local STT.
- Cancellable microphone capture with session-local input/output device selection.
- Live signed 16-bit PCM playback through `sounddevice`.
- WAV output when playback is disabled or `--output` is supplied.
- Session create/resume through `--session-id`.
- Bounded reconnect attempts with visible connection state and local prompt preservation.
- Structured thinking, status, tool, notification, and background activity rendering with unsupported-event diagnostics.
- Typed Markdown transcript rendering with `/details [show|hide]` and `--hide-thinking` controls.
- Connection, timeout, and turn errors shown in the UI instead of crashing the app.
- Local image staging and `@path` attachment previews with an explicit text-only relay boundary.
- Opt-in bounded local `!command` execution and `{!command}` prompt interpolation.

## Requirements

- Python 3.14
- Access to a Hermes voice-session WebSocket endpoint
- A bearer token for that endpoint
- A working audio input/output device for voice and playback

The project virtualenv installs its own local voice stack (`PyYAML`, `sounddevice`, `numpy`, and `faster-whisper`) — relay-tui owns microphone capture and local transcription directly, with no dependency on a Hermes checkout.

## Install

```bash
python3.14 -m venv venv
venv/bin/pip install -r requirements-dev.txt
```

That installs the local STT dependencies as well. `hermes-relay setup` also
downloads the selected Faster-Whisper model so the first microphone turn does
not perform setup inside the TUI.

### Homebrew install

The public Homebrew tap is ready:

```bash
brew tap achappell/hermes-relay
brew install achappell/hermes-relay/hermes-relay-tui
hermes-relay --help
```

On a new computer, use the guided setup before launching the client:

```bash
hermes-relay setup
hermes-relay
```

It asks for the Hermes WebSocket endpoint, bearer token, and client/device
names, session name. It writes editable connection
defaults to `~/.hermes-relay-tui/config.yaml` and keeps the token in the
private `~/.hermes-relay-tui/.env`. Use `hermes-relay setup` again to change
them. See [`docs/packaging/jensen-trial.md`](docs/packaging/jensen-trial.md)
for the server-side setup and smoke-test steps.

### Python package

Each tagged release publishes a wheel and source distribution to GitHub
Releases. Once PyPI publishing is enabled, the same package can also be
installed with:

```bash
python3.14 -m pip install hermes-relay-tui
pipx install hermes-relay-tui
uv tool install hermes-relay-tui
```

## Project automation

- GitHub Actions runs the test suite and verifies the installed console command
  on every push and pull request.
- Dependabot checks Python and GitHub Actions dependencies weekly, grouping
  compatible minor and patch updates into reviewable pull requests.
- Release-please watches conventional commits and opens the next version PR;
  merging it updates `pyproject.toml`, the manifest, and the changelog.

The public Homebrew tap has its own formula CI and GitHub Actions Dependabot
updates. Its formula is pinned to a source tag and revision; releases can open
a reviewable cross-repository formula update PR when tap automation is enabled.

If the repository already has `venv/`, install or refresh the dependencies with:

```bash
venv/bin/pip install -r requirements-dev.txt
```

## Configure credentials

The client looks for the bearer token in this order:

1. `--token`
2. `VOICE_SESSION_TOKEN`
3. `VOICE_SESSION_TOKEN` in `~/.hermes-relay-tui/.env`

The old `~/.hermes/profiles/amanda/.env` is also recognized as a migration
fallback when the default relay file does not exist.

For a one-off run:

```bash
VOICE_SESSION_TOKEN='redacted-token' venv/bin/python app.py
```

Keep real tokens in your environment or an ignored local profile file. Never commit them.

## Quick start

```bash
VOICE_SESSION_TOKEN='redacted-token' venv/bin/python app.py
```

The default connection is `ws://localhost:8792/voice-session`, assuming a local
Hermes gateway, with session ID `hybrid-tui`. Set `HERMES_VOICE_SESSION_URL` or
use `--url` when connecting to a remote gateway:

```bash
venv/bin/python app.py \
  --url ws://example.internal:8792/voice-session \
  --session-id my-session
```

The endpoint must be reachable from the machine running the TUI, and the server must accept the supplied bearer token.

Richer gateway-style events are normalized when the relay sends them. Thinking
deltas accumulate into one replaceable detail line and become a short elapsed
summary when the answer starts. If the relay supplies reasoning only with
`message.complete`, the client surfaces that fallback through the same lane.
Tool progress uses the same activity lane, repeated status updates are
suppressed, and the final assistant text starts on its own `hermes:` line.
Event types the client does not understand are shown as diagnostic transcript
entries instead of being discarded.

For a live-session smoke test that needs diagnosis, enable the content-safe
protocol trace:

```bash
venv/bin/python app.py --debug --log-file /tmp/hermes-relay-tui.log
```

In another terminal, use `tail -f /tmp/hermes-relay-tui.log`. The trace
includes frame order, event names, payload keys, text/byte lengths, hashes, and
turn state. It does not record bearer tokens, prompts, response text, or audio.

Uncaught exceptions are logged independently of `--debug` to
`~/.hermes-relay-tui/crash.log`. Each report includes the timestamp, installed
client version, exception type, thread, and file/line traceback locations, but
not exception messages, prompts, response text, audio, bearer tokens, or local
variable values. Reports append to this file until it is manually removed; the
file is created with owner-only permissions. Use `/logs` after relaunch to see
whether a crash report exists and its path.

## Controls

| Key | Action |
| --- | --- |
| `Enter` | Send the composer contents |
| `Shift+Enter` / `Alt+Enter` | Insert a newline |
| `/` | Type a command name; a live suggestion line shows matches as you type |
| `Tab` | Complete a uniquely-matching slash command in place |
| `Ctrl+R` | Capture and send a microphone turn |
| `/voice [on\|off\|tts\|status]` | Control voice mode for this relay session |
| `/audio` | Show or select local audio devices |
| `/image` | Stage, list, or clear a local image attachment |
| `/save [path]` | Save the visible transcript locally without overwriting files |
| `/copy` | Copy the visible transcript to the system clipboard |
| `/logs` | Show local debug and crash logging status and paths |
| `/retry` | Retry a prompt only when it was proven not to reach Hermes |
| `/undo` | Remove an unsent local prompt from the queue |
| Mouse drag | Select transcript text; release to copy it automatically and show a brief toast |
| `Ctrl+C` | Copy the current selection; without one, interrupt the active turn or clear/quit when idle |
| `F1` | Show keyboard help |
| `Ctrl+Q` | Quit |

Typed text is sent as-is unless it contains an explicitly staged or referenced
local file, or an opted-in `{!command}` interpolation. During an active response, ordinary prompts follow
the configured `--busy-mode`: `queue` preserves them for later, `steer`
replaces the active response, and `interrupt` stops the active response without
sending the new message.

When prompts are waiting, a compact queue shelf above the composer shows the
pending count and previews; it disappears as the queue drains. Use `/queue` to
edit or remove pending prompts.

Slash commands are routed before ordinary prompts. Typing `/` and a command
name works like any other text — a compact, non-blocking suggestion line
above the composer lists matching commands and their args/description as you
type, and disappears once you've typed a space or the text no longer looks
like a command. `Tab` fills in a uniquely-matching command name without
moving focus out of the composer. The initial commands
are `/help`, `/clear`, `/status`, `/queue`, `/busy`, `/details`, `/voice`, `/audio`, `/image`, `/history`, `/save`, `/copy`, `/logs`, `/retry`, `/undo`, `/usage`, `/compress`, and `/quit`;
`/queue`
also supports `list`, `edit <number> <replacement>`, `drop <number>`, and
`clear`. `/busy [queue|steer|interrupt]` changes the mode for the current
session. `/details [show|hide]` controls thinking and tool detail. `/audio`
shows the current devices; `/audio list` lists PortAudio devices, and
`/audio input <device>` / `/audio output <device>` select a device for the
current session. Use `default` to return to the system default. `/model`, `/new`,
`/voice` is forwarded through the connected voice-session channel, so its
settings apply only to that client/device session. `/model`, `/new`,
`/sessions`, `/resume`, and other commands use the gateway-dispatch boundary
when one is supplied. The current voice-session protocol does not expose
those other gateway commands, usage, conversation compression, or remote undo,
so they fail visibly instead of being sent to the model as prose. Use
`/busy steer` or `--busy-mode steer` to change what ordinary submissions do
while a turn is active.

`/save` and `/copy` use the exact visible transcript projection, so hidden
thinking and tool detail is excluded while `/details show` includes it. `/save`
defaults to `hermes-transcript-YYYYMMDD-HHMMSS.txt` in the current directory and
never overwrites an existing file. `/retry` refuses a turn that may have reached
Hermes; `/undo` only removes a prompt that is still local and unsent.

Drag across any visible transcript text to select an individual message or
range. Releasing the mouse copies that selection through the native system
clipboard and shows a brief confirmation toast. `Ctrl+C` can copy the current
selection again; after automatic copy the selection is cleared. If nothing is
selected, `Ctrl+C` keeps its interrupt/idle behavior.

Use `/image <path>` to stage a local image, `/image list` to inspect staged
metadata, and `/image clear` to cancel them. A unique final `@path` token can
be completed with `Tab`; inline `@path` references and staged images are
prepared locally with filename, MIME type, size, and resolved path previews.
The current voice-session relay accepts text only, so attachment-bearing
prompts remain in the composer and are rejected visibly; no attachment bytes
are sent until Hermes exposes upload and capability operations.

Local shell preparation is disabled by default. Enable it with
`--allow-shell`, `HERMES_RELAY_TUI_ALLOW_SHELL=true`, or `allow_shell: true` in
the YAML config. A standalone `!command` runs locally and never becomes a
Hermes turn. In ordinary text, `{!command}` substitutes successful stdout.
Commands use `shell=False`, reject shell operators, run for at most 10 seconds,
and produce at most 64 KiB of combined output. `VOICE_SESSION_TOKEN`,
`GH_TOKEN`, and `GITHUB_TOKEN` are removed from child environments. Errors,
timeouts, and malformed commands remain local and preserve the composer draft.

Because the current voice-session protocol has no explicit interrupt frame,
`Ctrl+C` and busy-mode `steer` cancel local stream consumption, close the
current connection, and reconnect before the next turn. This prevents stale
audio and events from corrupting the replacement; remote generation itself
remains best-effort until the protocol grows a server-side interrupt operation.

Connection setup retries up to three additional times by default, using an
exponential delay capped at eight seconds. Override this with
`--connect-retries` and `--connect-retry-delay`. If a connection is unavailable,
the submitted prompt remains in the local queue and newer prompts wait behind
it. A turn that may already have reached Hermes is never replayed automatically.

## Useful options

| Option | Purpose |
| --- | --- |
| `--url URL` | Override the voice-session WebSocket URL |
| `--token TOKEN` | Supply the bearer token explicitly |
| `--session-id ID` | Create or resume a server-side session |
| `--profile-env PATH` | `.env` file used for token lookup |
| `--no-play` | Do not open the local speaker; buffer audio instead |
| `--output PATH` | Save response audio to WAV |
| `--hide-thinking` | Hide thinking and tool detail in the transcript |
| `--debug` | Write a content-safe protocol trace to the default temporary log |
| `--log-file PATH` | Write the debug trace to `PATH` (also enables debug logging) |
| `--turn-timeout SECONDS` | Timeout a turn; default `195`, `0` disables |
| `--connect-retries COUNT` | Additional connection attempts after the first failure; default `3` |
| `--connect-retry-delay SECONDS` | Base delay before reconnect attempts; default `1.0` |
| `--busy-mode MODE` | Active-turn behavior: `queue` (default), `steer`, or `interrupt` |
| `--allow-shell` | Opt in to bounded local `!command` execution and `{!command}` interpolation |
| `--mic-max-seconds SECONDS` | Maximum microphone capture duration |
| `--mic-silence-duration SECONDS` | Silence duration that ends capture |
| `--mic-silence-threshold VALUE` | Capture silence threshold |
| `--mic-input-device DEVICE` | Microphone name or index; `default` uses the system default |
| `--audio-output-device DEVICE` | Speaker name or index; `default` uses the system default |
| `--stt-model NAME` | Select the local Faster-Whisper model |

Run `venv/bin/python app.py --help` for the full option list.

### Guided setup

Use `hermes-relay setup` on a new computer. It asks for the server endpoint,
token, and client identity, then saves the editable YAML and private token
file under `~/.hermes-relay-tui/`, and prepares the local `base`
Faster-Whisper model. Add `--stt-model NAME` to choose another model, or
`--no-check` to save the answers without probing the server. The model is still
prepared when `--no-check` is used.

## Audio output

By default, the app plays supported 16-bit PCM as it arrives. If playback is unavailable, it reports the failure and continues buffering the turn. Use `--audio-output-device` or `/audio output <device>` to select a speaker, and `--no-play --output response.wav` to capture audio without using one.

When `--output` is set, the first turn uses that path and later turns use numbered suffixes such as `response-1.wav`. Without `--output`, audio that was not played live is written to the current directory as `hybrid-tui-<turn-id>.wav`.

## Config file

Instead of retyping flags every launch, put your defaults in a YAML file at
`~/.hermes-relay-tui/config.yaml` (or point `--config`/`HERMES_RELAY_TUI_CONFIG`
at a different path). Copy [`config.example.yaml`](config.example.yaml) as a
starting point — every key is documented and optional.

Precedence for every setting: **CLI flag > environment variable > config
file > built-in default.** So the config file only fills gaps — a flag on
the command line, or an env var you already have set, still wins.

```bash
mkdir -p ~/.hermes-relay-tui
cp config.example.yaml ~/.hermes-relay-tui/config.yaml
# edit it, then:
hermes-relay
```

## Environment variables

| Variable | Default / role |
| --- | --- |
| `VOICE_SESSION_TOKEN` | Bearer token |
| `HERMES_VOICE_SESSION_URL` | `ws://localhost:8792/voice-session` |
| `VOICE_SESSION_CLIENT_ID` | `amanda-laptop` |
| `VOICE_SESSION_DEVICE_ID` | `amanda-mac` |
| `VOICE_SESSION_ID` | `hybrid-tui` |
| `VOICE_SESSION_MIC_MAX_SECONDS` | `15.0` |
| `VOICE_SESSION_MIC_SILENCE_DURATION` | `3.0` |
| `VOICE_SESSION_MIC_SILENCE_THRESHOLD` | `200` |
| `VOICE_SESSION_MIC_INPUT_DEVICE` | Microphone name or index; unset uses the system default |
| `VOICE_SESSION_AUDIO_OUTPUT_DEVICE` | Speaker name or index; unset uses the system default |
| `VOICE_SESSION_STT_MODEL` | unset; use the Hermes/local-STT default |
| `VOICE_SESSION_TURN_TIMEOUT` | `195.0` seconds |
| `VOICE_SESSION_CONNECT_RETRIES` | `3` additional connection attempts |
| `VOICE_SESSION_CONNECT_RETRY_DELAY` | `1.0` second base reconnect delay |
| `VOICE_SESSION_BUSY_MODE` | `queue`, `steer`, or `interrupt` |
| `HERMES_RELAY_TUI_ALLOW_SHELL` | `1`, `true`, `yes`, or `on` enables bounded local shell preparation |
| `HERMES_RELAY_TUI_DEBUG` | `1`, `true`, `yes`, or `on` enables the debug trace |
| `HERMES_RELAY_TUI_LOG_FILE` | Debug trace path; implies debug logging |

## Test

The suite uses fake sessions and protocol objects, so it does not require a live endpoint or credentials:

```bash
venv/bin/pytest
```

For a copy-paste manual check of attachments and safe shell preparation, see
[`docs/testing/daily-03-attachments-shell.md`](docs/testing/daily-03-attachments-shell.md).

For a copy-paste manual check of recovery, transcript export, diagnostics, and
relay-boundary behavior, see
[`docs/plans/2026-08-30-daily-04-recovery-testing-plan.md`](docs/plans/2026-08-30-daily-04-recovery-testing-plan.md).

## Troubleshooting

### `No voice-session token found`

Run `hermes-relay setup`, set `VOICE_SESSION_TOKEN`, pass `--token`, or point
`--profile-env` at a file containing `VOICE_SESSION_TOKEN=...`.

### Microphone capture cannot start

Check that the project virtualenv was refreshed with `venv/bin/pip install -r requirements-dev.txt` — `voice.py` needs `sounddevice`, `numpy`, and `faster-whisper` installed directly in the TUI's own Python environment.

On macOS, also grant microphone access to the app that launches the TUI (Terminal, iTerm, VS Code, or your IDE) under **System Settings → Privacy & Security → Microphone**, then fully restart that app. `Error querying device -1` means PortAudio cannot see an accessible default input device; check the selected input in **System Settings → Sound → Input** as well.

Use `/audio list` to find device indexes, then `/audio input <index>` to select
one for the current session. Press `Ctrl+C` while `● listening…` is shown to
cancel capture without leaving the TUI.

### Audio is buffered instead of played

The PCM stream must be signed 16-bit audio, and `sounddevice` must be able to open the selected output device. Use `--output response.wav` to preserve the response while diagnosing local audio.

### A turn times out

The default timeout is 195 seconds. Check the endpoint and server-side model health, then retry with a fresh `--session-id`; a timed-out turn is not replayed automatically because the remote side may already have processed it. Use `--turn-timeout 0` only when an unbounded wait is genuinely wanted.

## Project layout

```text
app.py        Textual UI and executable entry point
client.py     Hermes WebSocket protocol and streamed events
config.py     CLI and environment configuration
audio.py      PCM playback and WAV writing
mic.py        Hermes microphone loader
transcript.py Typed message records and Markdown rendering
tests/        Automated tests
docs/         Design and implementation notes
```
