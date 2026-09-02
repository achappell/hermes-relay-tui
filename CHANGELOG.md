# Changelog

## 0.6.2 (2026-09-02)

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Other Changes
* HOME-02: wake-word listener and hands-free turn capture by @achappell in https://github.com/achappell/hermes-relay-tui/pull/44
* HOME-09: appliance loop — wire the session and listener into the display by @achappell in https://github.com/achappell/hermes-relay-tui/pull/46
* Stop the audio popping, and the TUI's bogus fallback error by @achappell in https://github.com/achappell/hermes-relay-tui/pull/47
* VOICE-08: stop the audio popping and overlapping streams by @achappell in https://github.com/achappell/hermes-relay-tui/pull/48
* HOME-10: wake acknowledgement and the silence before the answer by @achappell in https://github.com/achappell/hermes-relay-tui/pull/49
* VOICE-10: wake mode as an in-session toggle for the TUI by @achappell in https://github.com/achappell/hermes-relay-tui/pull/50
* TURN-03: keep every segment of a multi-segment answer by @achappell in https://github.com/achappell/hermes-relay-tui/pull/51
* HOME-10: stop the wake word re-firing on audio from before the turn by @achappell in https://github.com/achappell/hermes-relay-tui/pull/52


**Full Changelog**: https://github.com/achappell/hermes-relay-tui/compare/v0.6.1...v0.6.2

## 0.6.1 (2026-09-01)

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Other Changes
* fix: re-sign relinked venv dylibs in the Homebrew formula by @achappell in https://github.com/achappell/hermes-relay-tui/pull/42


**Full Changelog**: https://github.com/achappell/hermes-relay-tui/compare/v0.6.0...v0.6.1

## 0.6.0 (2026-09-01)

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Other Changes
* feat: derive device_id from hostname instead of prompting for it by @achappell in https://github.com/achappell/hermes-relay-tui/pull/32
* feat: always record content-safe crash reports by @achappell in https://github.com/achappell/hermes-relay-tui/pull/36
* feat: prepare the local speech model during setup by @achappell in https://github.com/achappell/hermes-relay-tui/pull/35
* feat: make transcript text selectable and copy on release by @achappell in https://github.com/achappell/hermes-relay-tui/pull/39
* Home 03 kiosk display by @achappell in https://github.com/achappell/hermes-relay-tui/pull/40
* fix: install Homebrew formula from a checksummed release archive by @achappell in https://github.com/achappell/hermes-relay-tui/pull/41


**Full Changelog**: https://github.com/achappell/hermes-relay-tui/compare/v0.5.0...v0.6.0

## 0.5.0 (2026-08-31)

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Other Changes
* Own local mic capture and STT instead of loading Hermes internals by @achappell in https://github.com/achappell/hermes-relay-tui/pull/26
* feat: own local mic capture and STT instead of loading Hermes internals by @achappell in https://github.com/achappell/hermes-relay-tui/pull/27


**Full Changelog**: https://github.com/achappell/hermes-relay-tui/compare/v0.4.0...v0.5.0

## 0.4.0 (2026-08-31)

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Other Changes
* CORE-01/CORE-02: extract session orchestration and define the core boundary by @achappell in https://github.com/achappell/hermes-relay-tui/pull/18
* deps(deps-dev): update build requirement from <2,>=1.2.2 to >=1.6.0,<2 by @dependabot[bot] in https://github.com/achappell/hermes-relay-tui/pull/19
* deps(deps-dev): update textual-dev requirement from >=1.7.0 to >=1.8.0 by @dependabot[bot] in https://github.com/achappell/hermes-relay-tui/pull/20
* ci(actions): bump pypa/gh-action-pypi-publish from 1.12.4 to 1.14.2 in the actions-minor-and-patch group by @dependabot[bot] in https://github.com/achappell/hermes-relay-tui/pull/21
* ci(actions): bump actions/setup-python from 5.6.0 to 7.0.0 by @dependabot[bot] in https://github.com/achappell/hermes-relay-tui/pull/22
* feat: add guided first-run setup by @achappell in https://github.com/achappell/hermes-relay-tui/pull/24
* feat: forward voice commands through relay by @achappell in https://github.com/achappell/hermes-relay-tui/pull/25


**Full Changelog**: https://github.com/achappell/hermes-relay-tui/compare/v0.3.1...v0.4.0

## 0.3.1 (2026-08-31)

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Other Changes
* Turn 02 thinking detail lane by @achappell in https://github.com/achappell/hermes-relay-tui/pull/14
* ci: target release tags in manual runs by @achappell in https://github.com/achappell/hermes-relay-tui/pull/15
* fix: align release packaging with relay rename by @achappell in https://github.com/achappell/hermes-relay-tui/pull/17


**Full Changelog**: https://github.com/achappell/hermes-relay-tui/compare/v0.3.0...v0.3.1

## 0.3.0 (2026-08-31)

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Other Changes
* fix: handle Shift+Enter as ctrl+j and preserve newlines in transcript by @achappell in https://github.com/achappell/hermes-relay-tui/pull/7
* feat: add /reload for live config refresh, auto-create default config file by @achappell in https://github.com/achappell/hermes-relay-tui/pull/9
* feat: replace blocking slash-command palette with inline suggestions by @achappell in https://github.com/achappell/hermes-relay-tui/pull/10
* feat: add visible queue shelf by @achappell in https://github.com/achappell/hermes-relay-tui/pull/12
* Turn 02 thinking detail lane by @achappell in https://github.com/achappell/hermes-relay-tui/pull/13


**Full Changelog**: https://github.com/achappell/hermes-relay-tui/compare/v0.2.0...v0.3.0

## 0.2.0 (2026-08-30)

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Other Changes
* deps(deps-dev): update pytest requirement from >=8.0 to >=9.1.1 by @dependabot[bot] in https://github.com/achappell/hermes-streaming-tui/pull/2
* deps(deps-dev): update pytest-asyncio requirement from >=0.24 to >=1.4.0 by @dependabot[bot] in https://github.com/achappell/hermes-streaming-tui/pull/1
* build: add multi-channel release packaging by @achappell in https://github.com/achappell/hermes-streaming-tui/pull/4
* Feat/multi channel packaging by @achappell in https://github.com/achappell/hermes-streaming-tui/pull/5
* Feat/multi channel packaging by @achappell in https://github.com/achappell/hermes-streaming-tui/pull/6

## New Contributors
* @dependabot[bot] made their first contribution in https://github.com/achappell/hermes-streaming-tui/pull/2
* @achappell made their first contribution in https://github.com/achappell/hermes-streaming-tui/pull/4

**Full Changelog**: https://github.com/achappell/hermes-streaming-tui/compare/v0.1.0...v0.2.0
