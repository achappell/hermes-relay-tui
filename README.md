# Hermes Streaming TUI

A small Textual terminal UI for authenticated Hermes voice sessions. Type text, capture a local microphone turn, watch the reply stream into the transcript, and play streamed PCM audio locally.

The TUI supports an explicitly selected HomeBridge connection with Home-owned pairing and approved Profile grants, or the existing direct Standard Hermes `gateway` connection. The legacy voice-session transport remains available pending TUI-RETIRE-01. No connection silently changes mode. This client does not run Hermes or Home, and the new Home pairing/session flow has not yet passed live deployment acceptance.

## BMAD surface ownership

This repository owns BMAD delivery status for the surfaces registered in
[`bmad-surface.yaml`](bmad-surface.yaml): the TUI, ReSpeaker Puck, ESP32 Touch
Display, and W/K web/iPad surface. iOS, Android, and Home own their own story
indexes and local `sprint-status.yaml` files. The epic snapshot and coverage
matrix here are read-only cross-repository context.

Portfolio coordination lives in the public
[`hermes-relay-coordinator`](https://github.com/achappell/hermes-relay-coordinator)
repository. It owns the read-only repository roster, status renderer, and any
mechanical board-mirror procedure. This repository owns only TUI, Puck, ESP32,
and W/K delivery records; do not add sibling status or coordinator tooling
here.

## Features

- Streaming text transcript rendered inline as deltas arrive.
- Text turns submitted from the input box.
- Local microphone capture with Hermes' `LocalMicrophone` and local STT.
- Cancellable microphone capture with session-local input/output device selection.
- Live signed 16-bit PCM playback through `sounddevice`.
- WAV output when playback is disabled or `--output` is supplied.
- A new conversation on launch by default; explicit Home continue/resume and Profile selection.
- Bounded reconnect attempts with visible connection state and local prompt preservation.
- Home reconnect recovers the same in-memory claim without replaying an uncertain turn; failed continuity stays visible.
- Structured thinking, status, tool, notification, and background activity rendering with unsupported-event diagnostics available on demand.
- Typed Markdown transcript rendering with `/details [show|hide]` and `--hide-thinking` controls.
- Connection, timeout, and turn errors shown in the UI instead of crashing the app.
- Local image staging and `@path` attachment previews with an explicit text-only relay boundary.
- Opt-in bounded local `!command` execution and `{!command}` prompt interpolation.
- Opt-in direct Standard Hermes `/api/ws` text turns with a separate PCM speech
  sidecar. Home uses its own Device authentication and bridge adapter.

## Requirements

- Python 3.14
- Access to Home with NW-17 client enrollment/session APIs, or a supported direct Hermes endpoint.
- For Home: a working macOS Keychain or Linux Secret Service, plus approval on Home’s pairing page. For direct connections: their existing bearer-token setup.
- A working audio input/output device for voice and playback

The base install includes the typed client and configuration support. Local microphone capture and speech-to-text are optional extras, so a package or Homebrew install stays quick; `hermes-relay install` adds them with visible pip progress when you want voice.

## Install

```bash
python3.14 -m venv venv
venv/bin/pip install -r requirements-dev.txt
```

The development requirements include the voice stack for a checkout. For an
installed package, use the same explicit, visible step instead:

```bash
hermes-relay install voice
```

`hermes-relay install` installs all optional voice and household-appliance
dependencies. It does not download a speech model; `hermes-relay setup`
prepares the selected Faster-Whisper model separately so the first microphone
turn does not perform setup inside the TUI.

### Homebrew install

The public Homebrew tap is ready:

```bash
brew tap achappell/hermes-relay
brew install achappell/hermes-relay/hermes-relay-tui
hermes-relay install voice
hermes-relay --help
```

Homebrew installs the small typed client first. `hermes-relay install voice`
then installs microphone capture and local speech-to-text while pip's progress
remains visible. Use `hermes-relay install` when this machine is also a
household appliance and needs the wake-word stack.

On a new computer, use the guided setup before launching the client:

```bash
hermes-relay setup
hermes-relay
```

It asks for the direct Hermes WebSocket endpoint, bearer token, and client/device
names, session name. It writes editable connection
defaults to `~/.hermes-relay-tui/config.yaml` and keeps the token in the
private `~/.hermes-relay-tui/.env`. Those credentials are for the direct
legacy/Standard path only; they are not the Home Device-credential flow. Use
`hermes-relay setup` again to change them. See [`docs/packaging/jensen-trial.md`](docs/packaging/jensen-trial.md)
for the server-side setup and smoke-test steps.

### Pair this TUI with Home

Install the current client with `keyring`, then run `hermes-relay pair --profile household`. Paste Home’s `hermes-home://pair?home=…&code=…` link at the hidden prompt, or use `hermes-relay pair --home https://home.example --profile household` and enter its short code privately. `hermes-relay setup --transport home` starts the same flow. Compare the displayed device label and confirmation code on Home’s pairing page before approving and granting Profiles. The client waits up to five minutes; pending owner grants remain unavailable until their owner approves them.

Credentials and interrupted renewal request IDs live only in macOS Keychain or Linux Secret Service, keyed by the canonical Home address. Null, plaintext, and fallback keyrings are refused. YAML holds public Home/profile settings and the selected grant label or disambiguating grant ID. No ordinary Device credential, conversation handle, or pairing code belongs in YAML, environment variables, shell history, or logs. Pairing a different Home never reuses another Home’s credential. Existing local relay profiles are preserved.

```bash
hermes-relay --profile household                         # new conversation
hermes-relay --profile household --continue              # most recent session
hermes-relay --profile household --home-grant 'Amanda'    # approved Profile
hermes-relay unpair --home https://home.example          # local forgetting
```

Unpair forgets local access for that Home. Close existing TUI windows as well. It does **not** revoke the device on the server: use Home’s device/pairing page to revoke it. Saved public settings and intentional local history remain. If the credential was saved but public configuration was interrupted or could not be written, restore the missing local profile without enrolling again: `hermes-relay profile add household --transport home --url wss://home.example/api/v1/bridge/ws --home-grant '<approved-selection-id>'`. Use the approved selection ID shown during pairing, or a unique approved label; add `--config <path>` when using another config file. If credential saving itself failed or its outcome is unknown, check secure storage and Home’s page before enrolling again; revoke any issued but unused device.

Inside Home mode, `/home grants` lists labelled grants and selection IDs, `/home select <label-or-id>` deliberately opens a new conversation for one available grant, `/new` creates a conversation, `/continue` selects the most recent, and `/sessions` or `/resume` opens a picker. The picker shows titles, start dates, message counts and busy state using local selection keys; Home session references remain in memory. An explicit `--resume <session-ref>` is also supported for a reference obtained for that same Home/grant. `/title <text>` runs only when Home advertises its title command. Unsupported commands are reported locally.

`/home pending` and `/home holders` show Profile owner information. `/home approve <grant-id>` and `/home reject <grant-id>` send only the decision explicitly requested. Pending/revoked/unavailable grants cannot claim a conversation. Multiple grants with the same label can be selected by their listed IDs.

Session and Profile changes wait until active turns, prompts and capture have finished. Remove unsent queued prompts or attachments before switching. After an uncertain turn, `/reconnect` recovers the same claim’s transport without replay. It does not consume the earlier turn’s events or resolve its uncertain outcome; the UI says so and continues to block new turns and conversation changes. `/home leave` is required to explicitly leave that uncertainty behind before a deliberate next action. A failed replacement preserves the previous transcript on screen. Home restores Hermes context on resume, but does not expose a history retrieval API: earlier messages are **not** loaded. Local prompt history and default saved artifacts are isolated by canonical Home and granted identity, with no automatic migration from older identity scopes.

Quit and switching attempt a bounded claim close while preserving the Standard session for later resume. Network loss keeps the claim for recovery within Home’s configured grace (NW-17 defaults to 120 seconds); loss of the process loses this in-memory recovery binding. Claim expiry, revocation, and failed release stay explicit. Before a new claim the credential renews in its final 14 days, under a per-Home lock shared by windows, and configuration is fetched again. Renewal on Home can invalidate older-generation claims in other windows; those windows must report failed recovery and make a deliberate session choice.

Live prerequisites: deploy compatible Home NW-17 HTTP and bridge routes behind a valid HTTPS/WSS certificate, configure unmodified Standard Hermes and its session directory, and enable enrollment/approval on Home. The implementation was inspected against Home commit `d2447f684a143817f7b5688b597c11aa053bb672`. Secure-store operation, pairing approvals, text/voice, stop, concurrent windows, renewal, revocation, and disconnect recovery still require live acceptance. This implementation does not change a Home deployment or retire legacy clients.

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
The browser default is the DOM-first Svelte surface: it starts the normalized
`DisplayBridge`, renders observed state and streamed responses accessibly, and
shows direct-use prompt buttons only when the current snapshot advertises
`prompt.choose`. Build it without an Emscripten installation:

```bash
npm --prefix home_display/web install
npm --prefix home_display/web test -- --run
npm --prefix home_display/web run check
npm --prefix home_display/web run build
venv/bin/python -m build
```

The optional shared C/LVGL WebAssembly target remains available for the native
display experiment and its independent reducer/canvas tests. If that target
is needed, build it separately before packaging:

```bash
source build/display-wasm/emsdk/emsdk_env.sh
bash scripts/build_display_wasm.sh --check
bash scripts/build_display_wasm.sh
```

If the optional target is included in the package, rerun the browser build after
these commands and before `venv/bin/python -m build` so Vite copies the generated
WASM files into the static bundle. The direct-use DOM package needs none of this.

It uses Emscripten `6.0.5` and LVGL `8.3.11`; see the [shared display target
notes](shared/display/README.md) for emsdk setup and path overrides. The
direct-use browser page does not load or require those generated files.

Node, Svelte, Vite, TypeScript, and browser test packages are build-time tools,
not appliance runtime dependencies. Follow the
[HOME-03 kiosk display smoke procedure](docs/testing/home-03-kiosk-display.md)
to validate the local fake-state display after building.

The display shell now renders the shared ESP32 C/LVGL surface in the browser,
including state snapshots, prompt touch actions, browser voice, and streamed
audio. Web and iPad are one W/K browser voice-plus-display surface; iPad is a
deployment target, not a separate product surface. The physical ESP32 touch
unit is a separate Epic 1 voice-plus-display doorway: it must capture voice,
render its own response, and deliver response audio. Its current firmware
foundation implements the display snapshot/action path; the bounded
microphone/audio transport remains a dedicated implementation slice. Photo
playback and YouTube/video remain part of the HOME-16 work.

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
- The base Homebrew keg is intentionally separate from optional voice support.
  After a Homebrew upgrade, rerun `hermes-relay install voice` (or
  `hermes-relay install` for the appliance) if the new keg needs its optional
  packages rebuilt.
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
| `~/.hermes-relay-tui/history.jsonl`, `history/` | prompt-only history, per endpoint/profile; voice transcripts included, raw audio and assistant replies excluded |
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
Hermes gateway. Each launch mints a unique Hermes Session identity, even when
multiple TUI doorways use the same profile. Set `HERMES_VOICE_SESSION_URL` or
use `--url` when connecting to a remote gateway:

```bash
venv/bin/python app.py \
  --url ws://example.internal:8792/voice-session \
  --session-id my-session
```

The endpoint must be reachable from the machine running the TUI, and the server must accept the supplied bearer token. Use `/new` or `/resume` inside the TUI when you deliberately want to create or resume a server-side conversation.

### Standard Hermes transport (opt-in)

Standard mode is an explicit migration path; the fork's `voice-session` route
remains the default and rollback path. Select it before a turn, with a Standard
`/api/ws` URL:

```bash
VOICE_SESSION_TOKEN='redacted-token' venv/bin/python app.py \
  --transport gateway \
  --url wss://example.internal/api/ws \
  --hermes-profile amanda
```

This adapter is pinned to Standard Hermes `0.21.1`
(`2237be355906fbe6065ce1815711eee52b2d646e`). The pin describes the boundary
this client implements; selecting `gateway` does not change the default fork
or switch an active turn.

The client waits for `gateway.ready`, creates or resumes a runtime session, and
uses the returned runtime identity for live requests. An explicitly supplied
`--session-id` is a durable resume key; an ordinary launch creates a fresh
doorway session. Standard text events remain behind `SessionProtocol`.

Response speech uses the separate `/api/audio/speak-stream` sidecar. Its signed
16-bit PCM is validated and passed through the existing playback path; if the
sidecar fails, completed text remains readable and the prompt is not replayed.
Timing is shown only when the sidecar supplies a verified playback-clock or
duration contract. The current gateway slice deliberately leaves structured
prompts, command dispatch, attachments, and Home's public bridge envelope
unsupported; it reports those boundaries instead of collecting sensitive input
or inventing another Hermes authority.

Gateway authentication currently uses the endpoint's legacy `?token=` query
parameter. Bearer values are redacted from diagnostics, but query credentials
can still be visible to local process or proxy inspection. No live Standard
endpoint evidence is implied by the automated tests; run the approved text,
voice, interrupt, and disconnect checks only when such an endpoint is
configured.

The guided setup accepts the same explicit choice without rewriting the legacy
defaults: `hermes-relay setup --transport gateway --hermes-profile amanda`.
Named profiles can store it with `hermes-relay profile create NAME
--transport gateway --hermes-profile amanda`. Use `/api/ws` for the profile's
endpoint; the fork remains the reversible default.

## Named relay profiles

Use profiles when this client talks to more than one Hermes account or backend.
The profile catalog is stored in `~/.hermes-relay-tui/config.yaml`; only the
environment-variable name is stored there. Bearer tokens stay in the private
`.env` file named by `profile_env`, with mode `0600`.

The terminal configuration surface is deliberately separate from the live TUI:

```bash
hermes-relay profile list
hermes-relay profile create amanda
hermes-relay profile edit amanda
hermes-relay profile select amanda
hermes-relay profile delete amanda --yes
```

Create and edit prompt for a bearer token without echoing it. `delete` requires
`--yes`; deleting the final profile is refused. `hermes-relay profile migrate`
converts an existing single-profile YAML plus `.env` into a `default` profile,
moving a legacy literal token into the private env file before removing it from
YAML. `profile list` shows the display name, endpoint, identity, session, and
whether its private token is configured; it never prints the token.

The launch target comes from `--profile`, then `VOICE_SESSION_PROFILE`, then
`active_profile` in YAML. For example:

```bash
hermes-relay amanda
hermes-relay --profile jensen
VOICE_SESSION_PROFILE=jensen hermes-relay
```

The bare first argument is a profile shorthand, so flags can follow it as in
`hermes-relay amanda --no-play`. The `setup`, `install`, and `profile`
subcommands remain reserved.

The equivalent editable shape is:

```yaml
active_profile: amanda
profile_env: ~/.hermes-relay-tui/.env
profiles:
  amanda:
    display_name: Amanda
    wake_phrase: "hey missy"
    url: wss://amanda.example/voice-session
    token_env: VOICE_SESSION_TOKEN_AMANDA
    client_id: amanda-laptop
    device_id: amanda-mac
    session_id: amanda-session
  jensen:
    display_name: Jensen
    wake_phrase: "hey skippy"
    url: wss://jensen.example/voice-session
    token_env: VOICE_SESSION_TOKEN_JENSEN
    client_id: jensen-laptop
    device_id: jensen-mac
    session_id: jensen-session
  spark:
    display_name: Spark
    wake_phrase: "hey spark"
    url: wss://spark.example/voice-session
    token_env: VOICE_SESSION_TOKEN_SPARK
    client_id: spark-laptop
    device_id: spark-mac
    session_id: spark-session
```

The `session_id` values in configuration are retained legacy/config labels,
not the active Hermes Session for ordinary startup. Each TUI launch and named
profile selection mints a unique Hermes Session. Use `/new` or `/resume` when
you deliberately want to create or select a server-side conversation.

When `profiles:` is present, it is canonical for relay connection settings.
The root-level `url`, `token`, `client_id`, `device_id`, `session_id`,
`display_name`, and `model` keys are ignored for named profiles; a missing
profile field uses its built-in/profile-name default instead of inheriting from
another target. `profile_env` and `active_profile` remain global profile
catalog settings. A profile's `wake_phrase` or `wake_phrases` is loaded into
the TUI automatically at launch and after `/profile select`; explicit
`--wake-phrases` or `VOICE_SESSION_WAKE_PHRASES` still overrides it.
Explicit command-line connection flags and their environment variables still
act as launch-time overrides.

Without `profiles:`, the root-level connection keys continue to support the
legacy single-profile configuration.

Inside the TUI, `/profile list` inspects the catalog and `/profile select
<name>` switches deliberately. The old session closes before the new one
connects; a current turn, capture, or structured prompt blocks the switch.
The composer draft survives, while the old visible transcript and queued
prompts are discarded so an uncertain prompt cannot cross accounts. A failed
target remains selected and visibly disconnected; the client does not silently
fall back to the old relay. `/reload` applies the same replacement when the
selected profile or its endpoint identity changes.

Prompt history, default transcript exports, and response-audio fallbacks live
under a profile namespace once named profiles are active, so local continuity
cannot mix Amanda's and Jensen's prompts. Prompt history retains only bounded,
de-duplicated prompt text, including successful voice transcripts; it never
archives assistant responses or raw audio. When a named profile is first used,
an older flat or endpoint-scoped prompt history is copied oldest-first into its
profile file without deleting the source.

Richer gateway-style events are normalized when the relay sends them. Thinking
deltas accumulate into one replaceable detail line while a turn is active and
become a short elapsed summary only when `/details show` is enabled. If the
relay supplies reasoning only with `message.complete`, the client surfaces that
fallback through the same lane. Tool progress uses the same activity lane,
repeated status updates are suppressed, and the final assistant text starts on
its own configured Profile label.
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

For the speech-alignment rollout gate, run the deterministic fixture suite:

```bash
venv/bin/python speech_benchmark.py --json
```

The same runner can inspect one or more content-safe live traces without
retaining prompts, response text, or audio:

```bash
venv/bin/python speech_benchmark.py --strict \
  --log local=/tmp/hermes-relay-local.log \
  --log media=/tmp/hermes-relay-media.log
```

Alignment remains disabled until the fixture gate and the local/media smoke
checks pass. See the [AUDIO-01 benchmark and rollout gate](docs/testing/audio-01-speech-alignment-benchmark.md)
for the exact procedure and rollback switch.

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
| `/reconnect` | Reconnect with a fresh Hermes session without sending a prompt |
| `/retry` | Retry a prompt only when it was proven not to reach Hermes |
| `/undo` | Remove an unsent local prompt from the queue |
| Mouse drag | Select transcript text; release to copy it automatically and show a brief toast |
| `Ctrl+C` | Copy the current selection; without one, interrupt the active turn or clear/quit when idle |
| `F1` | Open keyboard help |
| `Ctrl+Q` | Quit |

Shutdown is explicit: `Ctrl+C` during a turn aborts response audio, while
`Ctrl+Q` cancels active capture/turn workers, aborts any response or earcon,
and closes the microphone before the process exits. Normal completed playback
still drains its final buffer so a successful answer is not clipped.

Typed text is sent as-is unless it contains an explicitly staged or referenced
local file, or an opted-in `{!command}` interpolation. During an active response, ordinary prompts follow
the configured `--busy-mode`: `queue` preserves them for later, `steer`
replaces the active response, and `interrupt` stops the active response without
sending the new message.

When prompts are waiting, a compact queue shelf above the composer shows the
pending count and previews without ordinal labels; it disappears as the queue
drains. Queueing is automatic; `/undo` removes the last unsent local prompt.

Slash commands are routed before ordinary prompts. Typing `/` and a command
name works like any other text — a compact, non-blocking suggestion line
above the composer lists matching commands and their args/description as you
type, and disappears once you've typed a space or the text no longer looks
like a command. `Tab` fills in a uniquely-matching command name without
moving focus out of the composer. The initial commands
are `/help`, `/clear`, `/status`, `/profile`, `/busy`, `/details`, `/voice`, `/wake`, `/audio`, `/image`, `/history`, `/save`, `/copy`, `/logs`, `/reconnect`, `/retry`, `/undo`, `/usage`, `/compress`, and `/quit`;
`/busy [queue|steer|interrupt]` changes the mode for the current
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

`/profile` lists the configured relay targets; `/profile select <name>` changes
the active target after the current work is idle. Use `hermes-relay profile
create|edit|delete` before launch for the configuration operations that need
hidden token input or deletion confirmation.

`/help` opens a temporary overlay; press Escape to return to the composer.
`/save` and `/copy` use the exact visible transcript projection, so hidden
thinking and tool detail is excluded while `/details show` includes it. `/save`
defaults to `hermes-transcript-YYYYMMDD-HHMMSS.txt` in the current directory and
never overwrites an existing file. `/retry` refuses a turn that may have reached
Hermes and can resend only a prompt proven never to have been sent. `/reconnect`
is the separate recovery action: it closes the failed session, creates a fresh
verified session, leaves partial text visible, and leaves queued prompts in FIFO
order without sending or replaying any prompt. After it succeeds, submit a
fresh prompt explicitly. `/undo` only removes a prompt that is still local and
unsent.

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
it. Use `/reconnect` to perform a reconnect-only recovery; it does not drain
that queue or reopen wake mode. A turn that may already have reached Hermes is
never replayed automatically.

## Useful options

| Option | Purpose |
| --- | --- |
| `--url URL` | Override the voice-session WebSocket URL |
| `--transport {voice-session,gateway}` | Select the channel; `voice-session` remains the default |
| `--profile NAME` | Select a named relay profile for this launch |
| `--hermes-profile NAME` | Select the Hermes server profile in gateway mode; also `HERMES_PROFILE` |
| `--token TOKEN` | Supply the bearer token explicitly |
| `--session-id ID` | Configure the legacy/session label used as launch input; the TUI still mints a unique Session per launch |
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
| `--wake-barge-in-min-speech-duration SECONDS` | Energy-window duration before immediate interruption; local STT decides whether to follow up; default `0.30` |
| `--mic-input-device DEVICE` | Microphone name or index; `default` uses the system default |
| `--audio-output-device DEVICE` | Speaker name or index; `default` uses the system default |
| `--stt-model NAME` | Select the local Faster-Whisper model |

The installed package also provides `hermes-relay-benchmark`, which accepts
the same benchmark and trace-analysis options as `speech_benchmark.py`.

Run `venv/bin/python app.py --help` for the full option list.

### Guided setup

Use `hermes-relay setup` on a new computer. It asks for the server endpoint,
token, and client identity, then saves the editable YAML and private token
file under `~/.hermes-relay-tui/`, and prepares the local `base`
Faster-Whisper model. Add `--stt-model NAME` to choose another model, or
`--no-check` to save the answers without probing the server. The model is still
prepared when `--no-check` is used.

## Audio output

By default, the app plays supported 16-bit PCM as it arrives. If playback is unavailable, it reports `audio unavailable`, keeps the completed text response readable, and continues collecting audio for an optional WAV fallback. Use `--audio-output-device` or `/audio output <device>` to select a speaker, and `--no-play --output response.wav` to capture audio without using one.

When `--output` is set, the first turn uses that path and later turns use numbered suffixes such as `response-1.wav`. Without `--output`, audio that was not played live is written to the current directory as `hybrid-tui-<turn-id>.wav`.

## Hands-free wake word

The home unit can listen continuously for a spoken phrase instead of waiting
for a keypress. It is **off by default** and needs an optional extra, because a
terminal install should not pull an ONNX runtime onto a laptop that will never
hear a wake word:

```bash
# On the household appliance — installs everything the home unit needs, with
# progress visible in the terminal.
hermes-relay install

# Then run the appliance: wake phrase in, spoken answer out, display in step.
hermes-relay-home --wake-enabled

# From a checkout, with no install, the same thing:
venv/bin/python -m home_display.appliance --wake-enabled

# On a laptop, install all optional support if you really want to experiment
# with wake detection.
hermes-relay install
python scripts/wake_check.py

# In the terminal client, wake mode is still opt-in. Configure it for launch,
# or omit it and type /wake on after the client connects.
hermes-relay --wake-enabled
```

`hermes-relay-home` is the whole unit: it opens one microphone stream for the
listener to hear the room, captures a turn when the phrase fires, plays the
reply, and serves the kiosk display on a loopback URL that reflects what is
actually happening. `hermes-relay-home-demo` still serves the display alone,
driven by a scripted fake, for working on the browser shell with no relay and
no hardware. Use `--display-port` to pin the display to a fixed port so a kiosk
browser can be pointed at it. For the ESP display, set an explicit LAN address
and opt in to the remote bind, for example
`--display-host 192.168.1.20 --display-remote --display-port 8765`; the ESP
client then connects to `ws://192.168.1.20:8765/state`. The [HOME-09 smoke procedure](docs/testing/home-09-appliance-loop.md)
is how the real loop gets validated — including
`scripts/fake_relay.py`, a stand-in server that lets the whole appliance be
tested with no Hermes at all.

The browser and iPad tab are one W/K surface. Pass `--browser-voice` with the
remote display options; the served page owns microphone permission, browser
speech recognition, and speaker playback, while the appliance receives only
recognized turn text and does not open a local audio device. The default
`legacy` browser transport uses the configured per-profile bearer sessions and
is the rollback path. A recognized wake phrase selects that profile, the
browser discards ambient speech, and a phrase-plus-question is sent as one
turn. After each completed answer it opens an eight-second wake-free follow-up
window and reopens it after every non-empty follow-up. Exactly `stop` is a
silent local cancel. A disconnect, server error, or recognition failure turns
hands-free off; it never replays an uncertain transcript.

STD-8 adds an explicit Home bridge transport for the same browser/iPad surface.
It keeps the Device credential and opaque conversation handle on the appliance
side of the same-origin proxy; neither is sent to the browser, put in a URL, or
written into the display snapshot. Configure it only when the approved Home
route is deployed:

```bash
hermes-relay-home --browser-voice \
  --browser-transport home \
  --home-bridge-url wss://home.example/api/v1/bridge/ws \
  --home-device-credential-file ~/.hermes-relay-tui/home-device-credential \
  --home-conversation-handle household-browser \
  --display-host 192.168.1.20 --display-remote --display-port 8765 \
  --display-tls-cert ~/.hermes-relay-tui/certs/display-cert.pem \
  --display-tls-key ~/.hermes-relay-tui/certs/display-key.pem
```

The credential file must be private; `HOME_DEVICE_CREDENTIAL` and
`HOME_CONVERSATION_HANDLE` in the private profile env are an alternative to
the file and handle flags. Home mode accepts choice/clarify prompt buttons via
`prompt.respond`, reports secret/sudo prompts as unavailable to this browser,
and advertises timing as explicitly absent. It never falls back to a direct
bearer session when the route or pairing is missing. The approved Home route is
currently an opt-in deployment gate; the existing Caddy/systemd example below
continues to describe the legacy rollback until that route is live.

After the display is connected and idle in the legacy path, tap **Enable
hands-free** to grant permission and listen for the configured profile catalog.
For Home mode, the configured Home conversation owns account routing; local
wake phrases only gate capture and no profile identifier crosses the bridge.
The browser reconnects to the same-origin state channel after an ops/container
restart:

```bash
hermes-relay-home --browser-voice \
  --display-host 192.168.1.20 --display-remote --display-port 8765 \
  --display-tls-cert ~/.hermes-relay-tui/certs/display-cert.pem \
  --display-tls-key ~/.hermes-relay-tui/certs/display-key.pem
```

Replace `192.168.1.20` with the ops machine's LAN address; the browser must
open the same address so the display server's same-origin check accepts the
WebSocket and action requests. Safari speech recognition requires a secure
origin, so the certificate must include that LAN IP as an IP subject-alternate
name and its local CA must be trusted on the iPad. The complete local
certificate and iPad trust procedure is in the [HOME-09 smoke procedure](docs/testing/home-09-appliance-loop.md).
The private key stays on the ops Mac; transfer only the public CA certificate
to the iPad. For this story, validate the page in that Safari tab under Guided
Access. Home Screen/PWA packaging is not included until it has passed a
physical iPad gate.

### Ops deployment behind Caddy

The repeatable legacy W/K deployment targets the ops Linux box at
`https://hermes-home.chappell-home.dev`. The appliance binds to loopback on
the ops host; Caddy owns HTTPS and proxies the page, `/state` WebSocket, and
`/action` route. The per-profile Hermes bearer tokens stay in the ops systemd
environment and are never sent to the browser. The Home bridge transport is
not silently substituted here: it requires the approved `/api/v1/bridge/ws`
route and its separate Device pairing.

Run the one-time bootstrap after adding the documented Caddy import and creating
`/etc/hermes-relay/home.env` on ops:

```bash
OPS_HOST=ops.example ./scripts/deploy_ops_web.sh bootstrap \
  --service-user hermes-home
```

Then deploy from a clean worktree with:

```bash
OPS_HOST=ops.example \
  ./scripts/deploy_ops_web.sh deploy \
  --profile-config /secure/ops/hermes-home-profile-config.yaml \
  --profile-env-source /secure/ops/home.env
```

Each deploy builds and verifies an isolated `HEAD` snapshot, installs a
versioned remote runtime and matching non-secret profile catalog, atomically
switches the active release, restarts the service, validates/reloads Caddy, and
checks the public page plus both browser transport routes. Roll back the
previous installed release with:

```bash
OPS_HOST=ops.example ./scripts/deploy_ops_web.sh rollback
```

See the [ops deployment runbook](docs/ops-web-deployment.md) for SSH/sudo
prerequisites, the service environment, DNS/TLS, failure recovery, and the
physical browser voice gate.

**A plain install does not include this.** `pip install hermes-relay-tui` and
`brew install hermes-relay-tui` give you the typed client and the
`hermes-relay-home` entry point, but no microphone, speech-to-text, or wake-word
runtime. That is deliberate: those packages are large and the ONNX runtime is
irrelevant to a laptop running text mode. Run `hermes-relay install voice` for
local voice, or `hermes-relay install` for the full household appliance.

Detection is entirely on-device. No audio leaves the machine to decide whether
the phrase was spoken.

**It is self-contained.** Everything openWakeWord needs ships in the package —
the trained "hey hermes" model plus the two shared feature-extraction models
that openWakeWord's own wheel omits and downloads on first use. There is no
Hermes install to read models out of and no download at first wake, so the unit
works on a clean machine and on a network that is not up yet when it boots.

| Flag | Default | What it does |
|---|---|---|
| `--wake-enabled` | off | Opt in to continuous listening. The TUI arms it after the initial connection; the appliance arms it as part of its startup. |
| `--wake-model` | bundled `hey_hermes` | Path to a `.onnx` model, or a built-in openWakeWord name. |
| `--wake-threshold` | `0.6` | Per-frame score above which the phrase counts as present. |
| `--wake-confirmation-frames` | `3` | Consecutive over-threshold frames required to fire. |
| `--wake-refractory-seconds` | `2.0` | Minimum gap between two fires. |
| `--wake-listen-timeout` | `8.0` | How long to wait for speech to begin after the phrase. |
| `--wake-followup-seconds` | `8.0` | How long to wait in each wake-free follow-up window after a completed response; every non-empty follow-up opens another window. |
| `--wake-barge-in` | off | Let calibrated local speech energy interrupt the active response; no second wake phrase is needed. See the warning below. |
| `--no-earcons` | tones on | Silence the acknowledgement tones. Does not disable the wake word. |

**Barge-in uses the Hermes full-duplex shape.** It calibrates the quiet room
before response audio begins, holds that floor while the speaker is active,
and requires a majority of a short energy window rather than one loud sample.
Playback gets a brief onset grace period and a higher floor so speaker bleed
does not immediately trip the detector. The energy callback interrupts
playback first; local STT then decides whether the captured audio is a real
follow-up or should be discarded.

If the initial microphone calibration is already loud (for example, children
watching a movie in the same room), the detector keeps that measured room floor
but uses reachable headroom instead of allowing the normal multiplier to hit
the absolute ceiling. Background audio must still stay below the speaking
voice; headphones or reducing the nearby speaker volume remain the reliable
fix when the room is louder than the speaker's voice.

**The listening timeout is not a recording limit.** Silence endpointing already
decides when you have *stopped* talking. This setting answers a different
question: did anyone ever *start*? It covers the case where the detector fired
at an extractor fan and nobody is in the room. The window is cancelled the
instant speech is detected, so it never cuts anyone off mid-sentence; if no
speech arrives, the unit discards the capture and returns to idle silently. It
never announces a misfire.

### Hands-free in the terminal client

`hermes-relay` keeps wake mode off by default. Set `wake_enabled: true` in the
YAML config, pass `--wake-enabled`, or turn it on inside the session. A
configured launch arms the microphone only after the initial connection:

| Command | What happens |
|---|---|
| `/wake on` | Starts wake mode without freezing the TUI. The status line and transcript show wake-model loading and microphone opening; once ready, saying the phrase runs a turn and opens an 8-second wake-free follow-up window after each successful answer. Every non-empty follow-up reopens it without another wake phrase. |
| `/wake off` | Stops the listener **and closes the stream**, so the system microphone indicator clears and other applications get the device back. |
| `/wake` or `/wake status` | Whether it is armed, and the model and threshold in use. |

During each follow-up window, the wake detector is paused while the same local
capture path waits for speech. Silence returns to wake-word listening; spoken
text starts one normal turn, and completed response playback opens another
follow-up window. Say exactly `stop` to close the conversation silently;
matching ignores case and surrounding whitespace, plus normal terminal
punctuation from transcription, while longer phrases such as `stop the timer`
remain ordinary turns. The initial wake capture also treats `stop` as a local
cancel; `Ctrl+R` remains an ordinary voice turn. Set each window with
`--wake-followup-seconds` or `VOICE_SESSION_WAKE_FOLLOWUP_SECONDS`. Failed or
interrupted turns do not invite another window. The normal TUI silence endpoint
is 1.5 seconds, so it no longer waits three seconds after the user stops
talking.

The Home appliance follows the same continuous contract, using the same
`--wake-followup-seconds` setting. It shows Listening without another wake tone
and retains the answer while waiting; each successful follow-up response opens
the next bounded window. Silence or exact spoken `stop` returns to wake
detection. Failed or interrupted turns do not invite another window. The
shared microphone remains open for wake detection while the appliance runs;
shutdown cancels capture before releasing the recorder.

With `--wake-barge-in`, the armed TUI also taps the same microphone stream while
Hermes is generating, buffering, or speaking. A calibrated, windowed energy
trigger closes local playback and sends one explicit remote interrupt before
local STT finishes. Raw microphone PCM never crosses the WebSocket. Saying
exactly `stop` ends the answer without submitting a new turn. If local STT
returns no usable transcript, the interruption is kept but no replacement turn
is sent.
Any other transcript becomes one new turn, without a second wake phrase. This
remains opt-in because a normal laptop speaker route can still feed Hermes'
voice back into the microphone. Playback-phase transcripts that closely match
the current assistant text are discarded as likely echo, but echo cancellation
or headphones are still the reliable fix.

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

Quitting the client cancels capture and response workers, aborts response audio
and earcons, and releases the microphone whether or not wake mode was on. The
native PortAudio close calls are guarded so a backend hang cannot hold the TUI
inside interpreter shutdown; normal completed response playback still drains
its final buffer.

Wake mode is deliberately session-local. A successful `/reload` disarms it so
new wake settings take effect only after an explicit `/wake on`; a connection
loss also releases the microphone and reconnecting never re-arms it. The
transcript reports both transitions. A malformed reload is not applied, so an
already-armed listener remains unchanged while the error is shown.

This remains an explicit opt-in rather than a default. The TUI reports its
startup stages and keeps the microphone closed when the setting is absent. A
successful reload, connection loss, or reconnect does not silently re-arm it;
use `/wake on` when you want to resume listening. The household appliance uses
the same opt-in flag as part of its always-listening startup.

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
hermes-relay install

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
| `VOICE_SESSION_ID` | Retained legacy/config label; each launch/profile selection mints a unique Hermes Session |
| `VOICE_SESSION_MIC_MAX_SECONDS` | `15.0` |
| `VOICE_SESSION_MIC_SILENCE_DURATION` | `1.5` |
| `VOICE_SESSION_MIC_SILENCE_THRESHOLD` | `200` |
| `VOICE_SESSION_WAKE_FOLLOWUP_SECONDS` | `8.0` seconds of silence after a wake-triggered reply |
| `VOICE_SESSION_WAKE_BARGE_IN_MIN_SPEECH_DURATION` | `0.30` seconds of windowed energy before interruption; local STT decides whether to follow up |
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

For a Homebrew or package install, run `hermes-relay install voice` and wait
for pip to finish. From a checkout, refresh the development environment with
`venv/bin/pip install -r requirements-dev.txt`. `voice.py` needs `sounddevice`,
`numpy`, and `faster-whisper` in the TUI's own Python environment.

On macOS, also grant microphone access to the app that launches the TUI (Terminal, iTerm, VS Code, or your IDE) under **System Settings → Privacy & Security → Microphone**, then fully restart that app. `Error querying device -1` means PortAudio cannot see an accessible default input device; check the selected input in **System Settings → Sound → Input** as well.

Use `/audio list` to find device indexes, then `/audio input <index>` to select
one for the current session. Press `Ctrl+C` while `● listening…` is shown to
cancel capture without leaving the TUI.

### Audio is buffered instead of played

The PCM stream must be signed 16-bit audio, and `sounddevice` must be able to open the selected output device. Use `--output response.wav` to preserve the response while diagnosing local audio.

### A turn times out

The default timeout is 195 seconds. Check the endpoint and server-side model health, then use `/reconnect` to establish a fresh unique Session before starting a new prompt; a timed-out turn is not replayed automatically because the remote side may already have processed it. Use `--turn-timeout 0` only when an unbounded wait is genuinely wanted.

## Smart Display & Embedded Hardware

The repository includes firmware and desktop simulators for dedicated household smart display appliances (Waveshare ESP32-S3-Touch-LCD-7B):

- **Physical Hardware Firmware (`firmware/esp32-s3-touch-lcd-7/`):** ESP-IDF & PlatformIO build targets driving the 1024×600 RGB LCD, GT911 capacitive touch controller, 8MB Octal PSRAM, and dual I2S audio pipeline.
- **Native macOS Simulator (`./scripts/simulate_native.sh`):** Compiles the exact C / LVGL UI codebase natively with Clang and SDL2 for desktop interaction and testing without physical hardware.

## Project layout

```text
app.py        Textual UI and executable entry point
client.py     Hermes WebSocket protocol and streamed events
config.py     CLI and environment configuration
audio.py      PCM playback and WAV writing
mic.py        Hermes microphone loader
transcript.py Typed message records and Markdown rendering
firmware/     ESP32-S3 smart display firmware and native SDL2 simulator
home_display/ Household appliance server, state channel, and Web kiosk
tests/        Automated tests
docs/         Design and implementation notes
```
