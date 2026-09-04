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

### HOME-03 kiosk display distribution

The kiosk display ships as compiled browser assets in `home_display/static/`.
Before building a Python wheel or source distribution, build those assets:

```bash
npm --prefix home_display/web run build
venv/bin/python -m build
```

Node, Svelte, Vite, TypeScript, and browser test packages are build-time tools,
not appliance runtime dependencies. Follow the
[HOME-03 kiosk display smoke procedure](docs/testing/home-03-kiosk-display.md)
to validate the local fake-state display after building.

This slice is only the display shell: touch controls, photo playback,
YouTube/video, Hermes integration, and audio are outside its scope.

## Upgrade and uninstall

### Upgrade

```bash
# Homebrew
brew update
brew upgrade achappell/hermes-relay/hermes-relay-tui

# Python package
python3.14 -m pip install --upgrade hermes-relay-tui
pipx upgrade hermes-relay-tui
uv tool upgrade hermes-relay-tui
```

Upgrades never touch `~/.hermes-relay-tui/`, so the endpoint, token, session
defaults, and prompt history survive. Re-run `hermes-relay setup` only to
change an answer; it rewrites `config.yaml` in place and leaves unrelated keys
alone.

Two upgrades are worth knowing about:

- Releases before `home_display` shipped have no `hermes-relay-home` command.
  Homebrew links it automatically once you upgrade to a release that provides
  it — no reinstall needed.
- If `stt_model` is absent from `config.yaml` (installs predating guided model
  setup), the first `Ctrl+R` after upgrading downloads the model. Run
  `hermes-relay setup` once to move that download out of the TUI.

### Uninstall

Removing the program leaves your data in place. Uninstall it first:

```bash
# Homebrew
brew uninstall achappell/hermes-relay/hermes-relay-tui
brew untap achappell/hermes-relay

# Python package
python3.14 -m pip uninstall hermes-relay-tui
pipx uninstall hermes-relay-tui
uv tool uninstall hermes-relay-tui
```

Then remove the runtime state you no longer want. Everything this client
writes lives in one directory:

| Path | Contents |
| --- | --- |
| `~/.hermes-relay-tui/config.yaml` | editable connection defaults |
| `~/.hermes-relay-tui/.env` | **bearer token** (owner-only) |
| `~/.hermes-relay-tui/history.jsonl`, `history/` | prompt history, per endpoint |
| `~/.hermes-relay-tui/crash.log` | crash reports; appends until removed |
| `$TMPDIR/hermes-relay-tui-debug.log` | debug trace, only with `--debug` |

```bash
rm -rf ~/.hermes-relay-tui
rm -f "${TMPDIR:-/tmp}/hermes-relay-tui-debug.log"
```

The `.env` holds a live bearer token. Remove it even if you keep everything
else, and rotate the token if the machine is leaving your control.

Older installs may also have a token at
`~/.hermes/profiles/amanda/.env`, which is still read as a fallback. That path
belongs to a local Hermes install, so remove the file rather than the
directory.

### Speech model cache

The local speech model is **not** stored under `~/.hermes-relay-tui`. It goes
to the shared Hugging Face cache, and only this entry belongs to this client:

```bash
du -sh ~/.cache/huggingface/hub/models--Systran--faster-whisper-*
rm -rf ~/.cache/huggingface/hub/models--Systran--faster-whisper-*
```

Remove only the `Systran--faster-whisper-*` directories. The rest of
`~/.cache/huggingface` belongs to other tools on the machine, and deleting the
whole cache will force unrelated software to re-download several gigabytes.

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
| `/wake` | Arm or release local hands-free listening (`on`/`off`/`status`) |
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
are `/help`, `/clear`, `/status`, `/queue`, `/busy`, `/details`, `/voice`, `/wake`, `/audio`, `/image`, `/history`, `/save`, `/copy`, `/logs`, `/retry`, `/undo`, `/usage`, `/compress`, and `/quit`;
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

When the connected endpoint advertises the `interrupt` capability, `Ctrl+C` and
busy-mode `steer`/`interrupt` send an explicit interrupt for the active turn
and wait for Hermes to confirm it. `audio_abort` and `turn_interrupted` are
handled as intentional lifecycle events, and late JSON frames from another
turn are discarded. Older endpoints without that capability retain the safe
close-and-reconnect fallback; the client does not claim remote cancellation in
that case.

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
| `--wake-barge-in-min-speech-duration SECONDS` | Sustained audio required before candidate audio is sent to local STT; default `0.45` |
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

## Hands-free wake word

The home unit can listen continuously for a spoken phrase instead of waiting
for a keypress. It is **off by default** and needs an optional extra, because a
terminal install should not pull an ONNX runtime onto a laptop that will never
hear a wake word:

```bash
# On the household appliance — installs everything the home unit needs.
pip install 'hermes-relay-tui[home]'

# Then run the appliance: wake phrase in, spoken answer out, display in step.
hermes-relay-home --wake-enabled

# From a checkout, with no install, the same thing:
venv/bin/python -m home_display.appliance --wake-enabled

# On a laptop, to experiment with detection without running the appliance.
pip install 'hermes-relay-tui[wake]'
python scripts/wake_check.py

# In the terminal client, hands-free is armed in-session, never at launch.
hermes-relay          # then type: /wake on
```

`hermes-relay-home` is the whole unit: it opens one microphone stream for the
listener to hear the room, captures a turn when the phrase fires, plays the
reply, and serves the kiosk display on a loopback URL that reflects what is
actually happening. `hermes-relay-home-demo` still serves the display alone,
driven by a scripted fake, for working on the browser shell with no relay and
no hardware. Use `--display-port` to pin the display to a fixed loopback port
so a kiosk browser can be pointed at it. The [HOME-09 smoke procedure](docs/testing/home-09-appliance-loop.md)
is how the real loop gets validated — including
`scripts/fake_relay.py`, a stand-in server that lets the whole appliance be
tested with no Hermes at all.

**A plain install does not include this.** `pip install hermes-relay-tui` and
`brew install hermes-relay-tui` give you the `hermes-relay-home` command
and the bundled models, but no wake-word engine, so the listener cannot start.
That is deliberate: the engine brings an ONNX runtime that a laptop running the
terminal client would never use. The appliance names its own dependencies with
the `home` extra.

Detection is entirely on-device. No audio leaves the machine to decide whether
the phrase was spoken.

**It is self-contained.** Everything openWakeWord needs ships in the package —
the trained "hey hermes" model plus the two shared feature-extraction models
that openWakeWord's own wheel omits and downloads on first use. There is no
Hermes install to read models out of and no download at first wake, so the unit
works on a clean machine and on a network that is not up yet when it boots.

| Flag | Default | What it does |
|---|---|---|
| `--wake-enabled` | off | Listen continuously for the phrase. **Appliance only** — `hermes-relay` refuses it and points at `/wake on`. |
| `--wake-model` | bundled `hey_hermes` | Path to a `.onnx` model, or a built-in openWakeWord name. |
| `--wake-threshold` | `0.6` | Per-frame score above which the phrase counts as present. |
| `--wake-confirmation-frames` | `3` | Consecutive over-threshold frames required to fire. |
| `--wake-refractory-seconds` | `2.0` | Minimum gap between two fires. |
| `--wake-listen-timeout` | `8.0` | How long to wait for speech to begin after the phrase. |
| `--wake-followup-seconds` | `8.0` | How long to wait for a follow-up after the reply, without another wake phrase. |
| `--wake-barge-in` | off | Let local speech interrupt the active response; no second wake phrase is needed. See the warning below. |
| `--no-earcons` | tones on | Silence the acknowledgement tones. Does not disable the wake word. |

**Confirmation frames are the setting that matters.** The detector scores about
twelve frames a second, and a stray sound can push a single frame over the
threshold. A real utterance holds the score high across several frames in a
row, so requiring three consecutive frames rejects background conversation far
better than raising the threshold — which only makes the phrase harder to say.
Setting this to `1` restores naive single-frame behaviour and is the fastest
way to make the unit start answering the radio.

**The listening timeout is not a recording limit.** Silence endpointing already
decides when you have *stopped* talking. This setting answers a different
question: did anyone ever *start*? It covers the case where the detector fired
at an extractor fan and nobody is in the room. The window is cancelled the
instant speech is detected, so it never cuts anyone off mid-sentence; if no
speech arrives, the unit discards the capture and returns to idle silently. It
never announces a misfire.

### Hands-free in the terminal client

`hermes-relay` never arms the microphone at launch. Wake mode is turned on
inside the session and stays on until you turn it off:

| Command | What happens |
|---|---|
| `/wake on` | Starts wake mode without freezing the TUI. The status line and transcript show wake-model loading and microphone opening; once ready, saying the phrase runs a turn and leaves an 8-second follow-up window after the reply so one next question needs no wake phrase. |
| `/wake off` | Stops the listener **and closes the stream**, so the system microphone indicator clears and other applications get the device back. |
| `/wake` or `/wake status` | Whether it is armed, and the model and threshold in use. |

During the follow-up window, the wake detector is paused while the same local
capture path waits for speech. Silence returns to wake-word listening; spoken
text starts one normal turn, then returns to wake-word listening. Say exactly
`stop` to close this follow-up window silently; matching ignores case and
surrounding whitespace, plus normal terminal punctuation from transcription,
while longer phrases such as `stop the timer` remain ordinary turns. The
initial wake capture also treats `stop` as a local cancel; `Ctrl+R` remains an
ordinary voice turn. Set the window with `--wake-followup-seconds` or
`VOICE_SESSION_WAKE_FOLLOWUP_SECONDS`. The normal TUI silence endpoint is 1.5
seconds, so it no longer waits three seconds after the user stops talking.

With `--wake-barge-in`, the armed TUI also taps the same microphone stream while
Hermes is generating, buffering, or speaking. Sustained audio becomes a local
STT candidate first; only a non-empty transcript closes local playback and
causes one explicit remote interrupt. Raw microphone PCM never crosses the
WebSocket. Saying exactly `stop` ends the answer without submitting a new turn.
Any other transcript becomes one new turn, without a second wake phrase. This
remains opt-in because a normal laptop speaker route can still feed Hermes'
voice back into the microphone, and local STT may recognize that echo as words.

The first `/wake on` can take a few seconds while the local wake model warms up
and CoreAudio opens the input stream. That setup runs away from the Textual event
loop, so the status remains repaintable and `/wake off` can cancel startup.
The local microphone uses a blocking reader worker rather than running wake or
barge-in Python inside PortAudio's CoreAudio callback; this keeps the input
device lifecycle stable while the stream remains open.

Whenever the microphone is open the status line above the composer carries a
`◉ mic open` marker in a colour of its own — during a `Ctrl+R` capture, during
a wake capture, and continuously while wake mode is armed. The state word
beside it says what the client is doing; the marker says whether the device is
live. One physical condition, one appearance, whichever path opened it. You
should never have to remember whether your microphone is on.

Quitting the client releases the microphone whether or not wake mode was on.

Wake mode is deliberately session-local. A successful `/reload` disarms it so
new wake settings take effect only after an explicit `/wake on`; a connection
loss also releases the microphone and reconnecting never re-arms it. The
transcript reports both transitions. A malformed reload is not applied, so an
already-armed listener remains unchanged while the error is shown.

This is deliberately not a command-line flag. An always-open microphone should
be something you did on purpose and can see, not a side effect of how the
process was started — which is why `hermes-relay --wake-enabled` refuses rather
than silently arming. The household appliance is the opposite case by design:
it exists to listen, so it takes the flag.

### Knowing it heard you

Between your last word and the unit's first is about four seconds: silence
endpointing, transcription, and — the largest part — roughly two seconds
between Hermes announcing the audio format and producing a sample anyone can
hear. Left empty, that gap reads as a hang.

The unit fills it honestly:

| Moment | What you get |
|---|---|
| The phrase lands | A short rising tone, and `Heard you` on the display. The microphone is not open yet. |
| You stop talking | A single lower tone. Listening has stopped and work has started. |
| Waiting for speech | `Thinking`, with a slowly breathing dot — a sign of life that is not a claim to be talking. |
| A sample really plays | `Speaking`, and not one moment sooner. |

The wake tone finishes *before* the microphone opens. That ordering is
deliberate and enforced in the coordinator: a tone that overlapped the capture
would either be transcribed into your question or re-trigger the detector.

A misfire is acknowledged and then withdrawn in silence — one tone, a wait, and
back to idle. The unit never makes the second sound unless it has something to
work on, so a chirp followed by nothing means "I thought I heard you, I was
wrong" without ever saying so out loud.

`--no-earcons` (or `earcons: false` in the config file) silences both tones and
leaves the display and the wake word alone.

### Checking it hears you

`scripts/wake_check.py` opens the real microphone through the real capture path
and prints a live score. Nothing is sent to Hermes and no turn is captured — it
only answers "does it hear me, and does it hear things that are not me".

```bash
pip install 'hermes-relay-tui[wake]'

# Watch the meter and say the phrase.
python scripts/wake_check.py

# A ten-minute soak with the fan, the tap and the radio going.
python scripts/wake_check.py --seconds 600 --quiet
```

```bash
# Prove the detector without a microphone or a voice.
python scripts/wake_check.py --self-test
```

The meter shows **two** bars: the microphone input level and the wake score.
That distinction matters, because "it did not hear the phrase" and "it is not
hearing anything" look identical otherwise and only one of them is a wake-word
problem. The summary names which one you hit — silence from the microphone,
audio arriving but no match, a near miss under the threshold, or a score that
crossed but was rejected as too brief.

`--self-test` synthesizes the phrase with macOS `say` and scores it with no
microphone involved. If it fires, the software is fine and the problem is
between your voice and the input device. If it does not, the problem is in the
software.

The first run takes about twenty seconds to load the model. Detection itself
costs roughly 2 ms per 80 ms frame, so there is ample headroom on modest
hardware.

**Do not enable `--wake-barge-in` without echo cancellation.** With a shared
microphone and speaker the unit hears its own voice, retriggers on itself, and
interrupts its own sentence. Keep it off on ordinary laptop speakers unless
the route provides echo cancellation, headphones, or equivalent isolation.

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
| `VOICE_SESSION_MIC_SILENCE_DURATION` | `1.5` |
| `VOICE_SESSION_MIC_SILENCE_THRESHOLD` | `200` |
| `VOICE_SESSION_WAKE_FOLLOWUP_SECONDS` | `8.0` seconds of silence after a wake-triggered reply |
| `VOICE_SESSION_WAKE_BARGE_IN_MIN_SPEECH_DURATION` | `0.45` seconds of sustained audio before candidate audio is sent to local STT |
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
