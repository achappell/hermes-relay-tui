# Jensen Homebrew trial

This is the near-term install path for trying the Hermes Streaming TUI on a
clean Mac. The public tap is `achappell/homebrew-hermes-streaming`.

## Install from the repository

The trial machine needs a working Homebrew installation:

```bash
brew tap achappell/hermes-streaming
brew install achappell/hermes-streaming/hermes-streaming-tui
hermes-streaming-tui --help
```

The formula installs Python 3.14, PortAudio, the Python dependencies, and the
`hermes-streaming-tui` command into an isolated Homebrew-managed environment.
It is pinned to source tag `v0.1.0`; the Faster-Whisper model may download on
the first microphone turn.

## First typed turn

Keep the bearer token in the shell environment or an ignored local profile
file. Do not put it in the repository or paste it into a shared issue.

```bash
export VOICE_SESSION_TOKEN='redacted-token'
hermes-streaming-tui \
  --profile-env "$HOME/.hermes/profiles/jensen/.env" \
  --no-play
```

If the profile file is not being used, the environment variable is sufficient.
The endpoint must be reachable from the trial Mac.

## Voice-turn smoke test

Voice turns still need a local Hermes checkout containing
`scripts/voice-session-client.py` and microphone permission for the app that
launches the terminal:

```bash
hermes-streaming-tui \
  --profile-env "$HOME/.hermes/profiles/jensen/.env" \
  --checkout "$HOME/.hermes/hermes-agent"
```

Use `Ctrl+R` for one microphone turn. On macOS, grant microphone access to
Terminal, iTerm, VS Code, or the launching IDE under **System Settings →
Privacy & Security → Microphone**, then restart that app.

## Trial checklist

- [ ] `brew install` completes on a clean Mac.
- [ ] `hermes-streaming-tui --help` opens without a Python traceback.
- [ ] A typed turn reaches Hermes and streams inline text.
- [ ] `Ctrl+R` captures speech after microphone permission is granted.
- [ ] A response plays, or `--no-play --output response.wav` saves valid audio.
- [ ] Missing token, checkout, and microphone permission produce actionable errors.
- [ ] Record any rough edges in `docs/friction-log.md` before promoting this to
      a published tap/release.

## What remains before the polished install

1. Convert the private Git source formula to a checksummed release archive if
   the tap is ever made public.
2. Add a short upgrade/uninstall path and verify the formula on Jensen's Mac.
