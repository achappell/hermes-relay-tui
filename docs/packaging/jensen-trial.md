# Jensen Homebrew trial

This is the near-term install path for trying the Hermes Streaming TUI on a
clean Mac. The formula is currently a draft in this repository rather than a
published Homebrew tap: the GitHub repository is private, and a stable formula
still needs a tagged release and checksum.

## Install from the repository

The trial machine needs GitHub access to the private repository and a working
Homebrew installation:

```bash
git clone git@github.com:achappell/hermes-streaming-tui.git
cd hermes-streaming-tui
brew tap-new --no-git achappell/hermes-streaming
tap_dir="$(brew --repository)/Library/Taps/achappell/homebrew-hermes-streaming"
mkdir -p "$tap_dir/Formula"
cp packaging/homebrew/hermes-streaming-tui.rb "$tap_dir/Formula/"
brew install --build-from-source --HEAD achappell/hermes-streaming/hermes-streaming-tui
hermes-streaming-tui --help
```

The formula installs Python 3.14, PortAudio, the Python dependencies, and the
`hermes-streaming-tui` command into an isolated Homebrew-managed environment.
Homebrew requires formulas to live in a tap, which is why the commands stage
this draft in a local tap first.
The Faster-Whisper model may download on the first microphone turn.

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

1. Create a dedicated private Homebrew tap repository.
2. Tag a release and pin the formula to its immutable source checksum.
3. Add a short upgrade/uninstall path and verify the formula on Jensen's Mac.
