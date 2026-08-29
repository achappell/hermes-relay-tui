# AGENTS.md

## Project

This repository contains a small Python/Textual terminal UI for the Hermes voice-session WebSocket channel. It keeps the user interface, protocol client, audio playback, microphone loading, and configuration in separate modules:

- `app.py` — Textual application, transcript rendering, turn lifecycle, and CLI entry point.
- `client.py` — Hermes `hello` handshake and streamed turn events.
- `config.py` — command-line arguments, environment variables, token lookup, and connection defaults.
- `audio.py` — streamed signed 16-bit PCM playback and WAV fallback.
- `mic.py` — dynamic loading of `LocalMicrophone` from the local Hermes checkout.
- `tests/` — unit and integration-style tests using fakes; do not require a live Hermes endpoint.

The implementation is a laptop-side client. The Hermes server owns sessions, model routing, speech generation, and the voice-session protocol.

## Working agreement

- Keep the code modular and direct. Avoid abstractions that do not remove real duplication.
- Preserve the existing voice-session protocol and event names unless a protocol change is explicitly requested.
- Do not commit bearer tokens, profile `.env` files, audio captures, or machine-specific credentials.
- Treat the default endpoint and local Hermes checkout as runtime configuration, not test fixtures. Tests should use fake sessions and WebSocket objects.
- Keep streamed text inline in the transcript. A widget that renders every delta on a separate line is a regression.
- Keep the UI responsive: blocking microphone capture and audio writes belong off the Textual event loop.
- Record non-blocking bugs and usability snags in `docs/friction-log.md`; defer them unless they block current work, risk data loss, or repeat.
- When changing behavior, update or add a focused test in `tests/` before declaring the work finished.

## Setup

Use the repository virtual environment when it exists:

```bash
venv/bin/pip install -r requirements-dev.txt
```

The voice path is in-process with Hermes' source modules, so this environment must include the voice stack declared in `requirements.txt` (`PyYAML`, `numpy`, `sounddevice`, and `faster-whisper`). Installing only the Hermes checkout's separate `.venv` is not enough.

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

The client can also read `VOICE_SESSION_TOKEN` from `--profile-env`, which defaults to `~/.hermes/profiles/amanda/.env`. The token precedence is:

1. `--token`
2. `VOICE_SESSION_TOKEN`
3. `VOICE_SESSION_TOKEN` in the profile `.env`

Do not put a real token in this file or in the README.

### Controls

- Type a message in the multiline composer and press `Enter` to send it.
- Press `Shift+Enter` or `Alt+Enter` to insert a newline without submitting.
- Press `Tab` after `/` to complete a slash command.
- While a turn is active, ordinary prompts enter the FIFO queue; use `/queue` to inspect or edit it.
- `Ctrl+C` interrupts the active turn; when idle it clears the draft, clears the queue, or exits.
- `/steer <prompt>` interrupts the active turn and sends the replacement after reconnecting.
- Slash commands are routed before ordinary text; do not silently send an unknown command as a model prompt.
- `Ctrl+R` captures a local microphone turn and sends its transcript.
- `F1` displays help in the transcript.
- `Ctrl+Q` quits.

### Important options

The complete source of truth is `config.build_arg_parser()`. The main runtime options are:

- `--url` — voice-session WebSocket URL.
- `--session-id` — session to create or resume.
- `--checkout` — Hermes checkout containing `scripts/voice-session-client.py`.
- `--profile-env` — optional `.env` file containing the bearer token.
- `--no-play` — buffer audio without opening the local speaker.
- `--output PATH` — save response audio as WAV; later turns receive numbered suffixes.
- `--turn-timeout SECONDS` — response timeout; default is 195 seconds, and `0` disables it.
- `--mic-max-seconds`, `--mic-silence-duration`, `--mic-silence-threshold` — microphone tuning.
- `--stt-model` — optional local Faster-Whisper model selection.

Relevant environment variables include `HERMES_VOICE_SESSION_URL`, `VOICE_SESSION_TOKEN`, `VOICE_SESSION_CLIENT_ID`, `VOICE_SESSION_DEVICE_ID`, `VOICE_SESSION_ID`, `VOICE_SESSION_MIC_MAX_SECONDS`, `VOICE_SESSION_MIC_SILENCE_DURATION`, `VOICE_SESSION_MIC_SILENCE_THRESHOLD`, `VOICE_SESSION_STT_MODEL`, and `VOICE_SESSION_TURN_TIMEOUT`.

## Integration boundaries

- `client.send_hello()` sends the protocol v1 `hello` payload and requires a `hello_ack` response.
- `client.send_turn()` sends a transcript turn and yields structured events for text, status, audio, errors, and turn completion.
- Binary WebSocket frames are raw PCM audio. `audio_start` supplies sample rate, channel count, and sample width.
- `app.py` owns presentation and turn state. It should not grow protocol parsing logic that belongs in `client.py`.
- `mic.py` loads `LocalMicrophone` from `<checkout>/scripts/voice-session-client.py`; that file and the project's voice dependencies must exist for `Ctrl+R` to work.
- `audio.py` supports signed 16-bit PCM for live playback. If playback cannot start, the app reports buffering and can still save the collected PCM as WAV.
- The current voice-session protocol has no explicit interrupt operation. Interruption closes the current client connection and reconnects before the next turn, preventing stale events from being consumed as new-turn data; server-side generation cancellation remains a protocol concern.
- On macOS, microphone permission belongs to the launching app (Terminal, iTerm, VS Code, or the IDE), and a missing accessible default input is reported by PortAudio as device `-1`.

## Change checklist

Before handing off a change:

1. Run the focused tests for the changed module.
2. Run `venv/bin/pytest`.
3. If the change affects the live channel, exercise a text turn, a voice turn, and the failure path against a deliberately configured endpoint.
4. Review `git diff` for credentials, generated audio, cache files, and accidental edits outside the requested scope.

The design and implementation history live under `docs/superpowers/` and `docs/plans/`; consult them when changing the architecture, but keep this file and the code as the operational source of truth.
