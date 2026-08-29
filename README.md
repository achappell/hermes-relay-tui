# Hermes Streaming TUI

A small Textual terminal UI for authenticated Hermes voice sessions. Type text, capture a local microphone turn, watch the reply stream into the transcript, and play streamed PCM audio locally.

This is a client for the existing Hermes voice-session channel. It does not run the Hermes server or provide a session browser.

## Features

- Streaming text transcript rendered inline as deltas arrive.
- Text turns submitted from the input box.
- Local microphone capture with Hermes' `LocalMicrophone` and local STT.
- Live signed 16-bit PCM playback through `sounddevice`.
- WAV output when playback is disabled or `--output` is supplied.
- Session create/resume through `--session-id`.
- Connection, timeout, and turn errors shown in the UI instead of crashing the app.

## Requirements

- Python 3.14
- Access to a Hermes voice-session WebSocket endpoint
- A bearer token for that endpoint
- A local Hermes checkout containing `scripts/voice-session-client.py` for microphone turns
- A working audio input/output device for voice and playback

The project virtualenv installs the local voice stack (`PyYAML`, `numpy`, and `faster-whisper`) because the microphone adapter imports Hermes’ source modules in the TUI process.

## Install

```bash
python3.14 -m venv venv
venv/bin/pip install -r requirements-dev.txt
```

That installs the local STT dependencies as well. The first transcription may download the selected Faster-Whisper model.

If the repository already has `venv/`, install or refresh the dependencies with:

```bash
venv/bin/pip install -r requirements-dev.txt
```

## Configure credentials

The client looks for the bearer token in this order:

1. `--token`
2. `VOICE_SESSION_TOKEN`
3. `VOICE_SESSION_TOKEN` in `~/.hermes/profiles/amanda/.env`

For a one-off run:

```bash
VOICE_SESSION_TOKEN='redacted-token' venv/bin/python app.py
```

Keep real tokens in your environment or an ignored local profile file. Never commit them.

## Quick start

```bash
VOICE_SESSION_TOKEN='redacted-token' venv/bin/python app.py
```

The default connection is `ws://100.90.186.57:8792/voice-session`, with session ID `hybrid-tui`. Override those values when needed:

```bash
venv/bin/python app.py \
  --url ws://example.internal:8792/voice-session \
  --session-id my-session \
  --checkout ~/.hermes/hermes-agent
```

The endpoint must be reachable from the machine running the TUI, and the server must accept the supplied bearer token.

## Controls

| Key | Action |
| --- | --- |
| `Enter` | Send the composer contents |
| `Shift+Enter` / `Alt+Enter` | Insert a newline |
| `/` at an empty composer | Open the visual slash-command palette |
| `Tab` | Complete a slash command |
| `Ctrl+R` | Capture and send a microphone turn |
| `Ctrl+C` | Interrupt the active turn; otherwise clear the draft, queue, or quit |
| `F1` | Show keyboard help |
| `Ctrl+Q` | Quit |

Typed text is sent as-is. During an active response, ordinary prompts follow
the configured `--busy-mode`: `queue` preserves them for later, `steer`
replaces the active response, and `interrupt` stops the active response without
sending the new message.

Slash commands are routed before ordinary prompts. Typing `/` in an empty
composer opens a searchable command palette; filter by name or description,
use the arrow keys to choose a command, then press `Enter` to return it to the
composer. `Escape` closes the palette and leaves the slash draft in place. The
initial local commands
are `/help`, `/clear`, `/status`, `/queue`, `/busy`, `/voice`, and `/quit`;
`/queue`
also supports `list`, `edit <number> <replacement>`, `drop <number>`, and
`clear`. `/busy [queue|steer|interrupt]` changes the mode for the current
session. `/steer` is retained only as a migration warning. `/model`, `/new`,
`/sessions`, `/resume`, and other commands use the
gateway-dispatch boundary when one is supplied. The current voice-session
protocol does not yet expose gateway command dispatch, so those commands fail
visibly instead of being sent to the model as prose.

Because the current voice-session protocol has no explicit interrupt frame,
`Ctrl+C` and busy-mode `steer` cancel local stream consumption, close the
current connection, and reconnect before the next turn. This prevents stale
audio and events from corrupting the replacement; remote generation itself
remains best-effort until the protocol grows a server-side interrupt operation.

## Useful options

| Option | Purpose |
| --- | --- |
| `--url URL` | Override the voice-session WebSocket URL |
| `--token TOKEN` | Supply the bearer token explicitly |
| `--session-id ID` | Create or resume a server-side session |
| `--checkout PATH` | Hermes checkout used for microphone/STT loading |
| `--profile-env PATH` | `.env` file used for token lookup |
| `--no-play` | Do not open the local speaker; buffer audio instead |
| `--output PATH` | Save response audio to WAV |
| `--turn-timeout SECONDS` | Timeout a turn; default `195`, `0` disables |
| `--busy-mode MODE` | Active-turn behavior: `queue` (default), `steer`, or `interrupt` |
| `--mic-max-seconds SECONDS` | Maximum microphone capture duration |
| `--mic-silence-duration SECONDS` | Silence duration that ends capture |
| `--mic-silence-threshold VALUE` | Capture silence threshold |
| `--stt-model NAME` | Select the local Faster-Whisper model |

Run `venv/bin/python app.py --help` for the full option list.

## Audio output

By default, the app plays supported 16-bit PCM as it arrives. If playback is unavailable, it reports the failure and continues buffering the turn. Use `--no-play --output response.wav` to capture audio without using a speaker.

When `--output` is set, the first turn uses that path and later turns use numbered suffixes such as `response-1.wav`. Without `--output`, audio that was not played live is written to the current directory as `hybrid-tui-<turn-id>.wav`.

## Environment variables

| Variable | Default / role |
| --- | --- |
| `VOICE_SESSION_TOKEN` | Bearer token |
| `HERMES_VOICE_SESSION_URL` | `ws://100.90.186.57:8792/voice-session` |
| `VOICE_SESSION_CLIENT_ID` | `amanda-laptop` |
| `VOICE_SESSION_DEVICE_ID` | `amanda-mac` |
| `VOICE_SESSION_ID` | `hybrid-tui` |
| `VOICE_SESSION_MIC_MAX_SECONDS` | `15.0` |
| `VOICE_SESSION_MIC_SILENCE_DURATION` | `3.0` |
| `VOICE_SESSION_MIC_SILENCE_THRESHOLD` | `200` |
| `VOICE_SESSION_STT_MODEL` | unset; use the Hermes/local-STT default |
| `VOICE_SESSION_TURN_TIMEOUT` | `195.0` seconds |
| `VOICE_SESSION_BUSY_MODE` | `queue`, `steer`, or `interrupt` |

## Test

The suite uses fake sessions and protocol objects, so it does not require a live endpoint or credentials:

```bash
venv/bin/pytest
```

## Troubleshooting

### `No voice-session token found`

Set `VOICE_SESSION_TOKEN`, pass `--token`, or point `--profile-env` at a file containing `VOICE_SESSION_TOKEN=...`.

### Microphone capture cannot start

Check that `--checkout` points to a Hermes checkout containing `scripts/voice-session-client.py`, and that the project virtualenv was refreshed with `venv/bin/pip install -r requirements-dev.txt`. The TUI loads `LocalMicrophone` from that file at runtime, using the TUI process' Python environment.

On macOS, also grant microphone access to the app that launches the TUI (Terminal, iTerm, VS Code, or your IDE) under **System Settings → Privacy & Security → Microphone**, then fully restart that app. `Error querying device -1` means PortAudio cannot see an accessible default input device; check the selected input in **System Settings → Sound → Input** as well.

### Audio is buffered instead of played

The PCM stream must be signed 16-bit audio, and `sounddevice` must be able to open the selected output device. Use `--output response.wav` to preserve the response while diagnosing local audio.

### A turn times out

The default timeout is 195 seconds. Check the endpoint and server-side model health, then retry with a fresh `--session-id`. Use `--turn-timeout 0` only when an unbounded wait is genuinely wanted.

## Project layout

```text
app.py        Textual UI and executable entry point
client.py     Hermes WebSocket protocol and streamed events
config.py     CLI and environment configuration
audio.py      PCM playback and WAV writing
mic.py        Hermes microphone loader
tests/        Automated tests
docs/         Design and implementation notes
```
