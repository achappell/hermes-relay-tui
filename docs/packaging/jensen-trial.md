# Jensen Homebrew trial

This is the near-term install path for trying the Hermes Streaming TUI on a
clean Mac. The public tap is `achappell/homebrew-hermes-relay`.

## Install from the public Homebrew tap

The trial machine needs a working Homebrew installation:

```bash
brew tap achappell/hermes-relay
brew install achappell/hermes-relay/hermes-relay-tui
hermes-relay install voice
hermes-relay --help
```

The formula installs Python 3.14, PortAudio, and the typed client into an
isolated Homebrew-managed environment. `hermes-relay install voice` then adds
the microphone and speech-to-text dependencies with visible pip progress. The
Faster-Whisper model is a separate setup step and may download when
`hermes-relay setup` prepares it.

No local Hermes gateway installation or Hermes virtualenv is required for this
trial. The installed TUI is only a client; it connects to the configured
voice-session endpoint.

## Configure the client

On the trial Mac, run the guided setup. It keeps the token out of the editable
YAML file and puts the connection details in the app's own dotfolder:

```bash
hermes-relay setup
```

When prompted, enter the WebSocket endpoint and bearer token printed by the
Hermes server's `hermes gateway setup` flow. Choose a stable client ID that is
included in the server allowlist. The setup saves:

- editable defaults in `~/.hermes-relay-tui/config.yaml`;
- the bearer token in `~/.hermes-relay-tui/.env` with private permissions.

Then start the client:

```bash
hermes-relay
```

Run `hermes-relay setup` again whenever the endpoint, token, or local checkout
needs to change. Use `hermes-relay setup --no-check` only when the server is
temporarily offline.

## Optional microphone voice-turn smoke test

The local microphone path is owned by the installed client. It does not need a
Hermes source checkout or the gateway's virtualenv. Microphone permission still
belongs to the app that launches the terminal:

```bash
hermes-relay setup
# When asked for the Hermes checkout, enter:
#   $HOME/.hermes/hermes-agent
hermes-relay
```

Use `Ctrl+R` for one microphone turn. On macOS, grant microphone access to
Terminal, iTerm, VS Code, or the launching IDE under **System Settings →
Privacy & Security → Microphone**, then restart that app.

## Trial checklist

- [ ] `brew install` completes on a clean Mac without installing the optional
      voice or wake stack.
- [ ] `hermes-relay install voice` completes with visible pip progress.
- [ ] `hermes-relay --help` opens without a Python traceback.
- [ ] A typed turn reaches Hermes and streams inline text.
- [ ] *(Optional)* A Hermes checkout is saved by `hermes-relay setup`, and
      `Ctrl+R` captures speech after microphone permission is granted.
- [ ] A response plays, or `--no-play --output response.wav` saves valid audio.
- [ ] Missing token produces an actionable error; if the optional microphone
      path is tried, a missing checkout or microphone permission does too.
- [ ] Record any rough edges in `docs/friction-log.md` before promoting this to
      a published tap/release.

## What remains before the polished install

1. Convert the private Git source formula to a checksummed release archive if
   the tap is ever made public.
2. Add a short upgrade/uninstall path and verify the formula on Jensen's Mac.
