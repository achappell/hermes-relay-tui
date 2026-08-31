# Release distribution

Hermes Streaming TUI is distributed through several complementary channels:

- GitHub Releases receive the Python wheel and source distribution for every
  `v*` tag.
- PyPI publishing is available through a Trusted Publisher when the repository
  variable `PYPI_PUBLISHING` is set to `enabled`. That supports `pip`, `pipx`,
  and `uv tool install`.
- Homebrew remains the easiest clean-Mac path. When the repository variable
  `HOMEBREW_TAP_AUTOMATION` is set to `enabled`, a release commits the generated
  formula directly to `main` in `achappell/homebrew-hermes-relay` after the
  packages finish building.

## One-time PyPI setup

Create the `hermes-relay-tui` project on PyPI and configure a Trusted
Publisher for:

- owner: `achappell`
- repository: `hermes-relay-tui`
- workflow: `.github/workflows/release.yml`

Then set the repository variable:

```bash
gh variable set PYPI_PUBLISHING --repo achappell/hermes-relay-tui --body enabled
```

## One-time Homebrew automation setup

Create a fine-grained token or GitHub App token with Contents write access to
`achappell/homebrew-hermes-relay`, owned by a tap administrator so it can push
to the protected `main` branch. Store it as `HOMEBREW_TAP_TOKEN` in the source
repository, then enable the workflow:

```bash
gh variable set HOMEBREW_TAP_AUTOMATION --repo achappell/hermes-relay-tui --body enabled
```

The tap's protected branch and `CODEOWNERS` file continue to protect manual
pull requests; release automation is the deliberate administrator bypass for
the generated formula commit.

## Why there are no native binaries

OpenUsage can ship standalone binaries because it is a Go application. Hermes
Streaming TUI is a Python client whose voice path needs Python 3.14, PortAudio,
Faster-Whisper, and a local Hermes checkout. A wheel/source distribution plus
Homebrew's isolated Python environment is the honest package boundary; native
binary bundling is a separate project if that runtime boundary changes.
