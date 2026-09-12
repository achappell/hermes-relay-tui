# Changelog

## 0.11.0 (2026-09-12)

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Other Changes
* docs: formalize Android as an iOS-parity surface by @achappell in https://github.com/achappell/hermes-relay-tui/pull/152
* feat(tui): polish conversation surface by @achappell in https://github.com/achappell/hermes-relay-tui/pull/151
* fix(puck): bound turn responsiveness, not turn duration (1-p-2 task 6) by @achappell in https://github.com/achappell/hermes-relay-tui/pull/150
* docs(bmad): reconcile post-merge sprint status by @achappell in https://github.com/achappell/hermes-relay-tui/pull/154
* fix(puck): bound playback writes and surface dropped turns by @achappell in https://github.com/achappell/hermes-relay-tui/pull/155
* fix(tui): keep disconnect recovery presentation honest by @achappell in https://github.com/achappell/hermes-relay-tui/pull/157
* feat(puck): the Puck speaks Hermes' answers (1-p-2 tasks 3-5) by @achappell in https://github.com/achappell/hermes-relay-tui/pull/156
* fix(tui): close disconnect recovery review findings by @achappell in https://github.com/achappell/hermes-relay-tui/pull/159
* fix(puck): close the remaining code-review findings by @achappell in https://github.com/achappell/hermes-relay-tui/pull/158
* feat: make TUI an independent voice gateway by @achappell in https://github.com/achappell/hermes-relay-tui/pull/160
* fix(puck): prevent phantom playback stops and recover failed turns by @achappell in https://github.com/achappell/hermes-relay-tui/pull/161
* fix(tui): shut down voice resources off the event loop by @achappell in https://github.com/achappell/hermes-relay-tui/pull/162
* docs(home): add shared wake arbitration contract by @achappell in https://github.com/achappell/hermes-relay-tui/pull/164
* feat(puck): harden wake-to-response audio delivery by @achappell in https://github.com/achappell/hermes-relay-tui/pull/163
* docs: move home service ownership out of tui by @achappell in https://github.com/achappell/hermes-relay-tui/pull/165
* docs: amend FR5 to describe continuously reopening follow-up windows by @achappell in https://github.com/achappell/hermes-relay-tui/pull/167
* feat(tui): detect idle relay loss without replay by @achappell in https://github.com/achappell/hermes-relay-tui/pull/166


**Full Changelog**: https://github.com/achappell/hermes-relay-tui/compare/v0.10.0...v0.11.0

## 0.10.0 (2026-09-11)

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Dependencies
* ci(deps-dev): bump vitest from 3.2.7 to 5.0.0 in /home_display/web by @dependabot[bot] in https://github.com/achappell/hermes-relay-tui/pull/114
* ci(deps): bump @vitest/mocker and vitest in /home_display/web by @dependabot[bot] in https://github.com/achappell/hermes-relay-tui/pull/113
### Other Changes
* feat(firmware): Waveshare ESP32-S3-Touch-LCD-7B board bring-up, 1024x600 RGB LCD, and GT911 touch (ESP-01) by @achappell in https://github.com/achappell/hermes-relay-tui/pull/95
* fix(firmware): correct ESP-01 Waveshare 7B hardware mapping by @achappell in https://github.com/achappell/hermes-relay-tui/pull/97
* feat(firmware): connect ESP-02 display to state channel by @achappell in https://github.com/achappell/hermes-relay-tui/pull/98
* feat: add named relay profiles and profile wake phrases by @achappell in https://github.com/achappell/hermes-relay-tui/pull/99
* fix(tui): honor configured wake mode at launch by @achappell in https://github.com/achappell/hermes-relay-tui/pull/101
* test(ui-core): add cross-target display conformance by @achappell in https://github.com/achappell/hermes-relay-tui/pull/103
* feat(ui-core): route ESP display through shared reducer by @achappell in https://github.com/achappell/hermes-relay-tui/pull/105
* feat(home-display): render shared LVGL surface in browser by @achappell in https://github.com/achappell/hermes-relay-tui/pull/106
* feat(home-16): add browser voice bridge by @achappell in https://github.com/achappell/hermes-relay-tui/pull/107
* docs(architecture): ratify architecture spine by @achappell in https://github.com/achappell/hermes-relay-tui/pull/108
* PUCK-01.1: choose the Puck's on-device wake-word engine by @achappell in https://github.com/achappell/hermes-relay-tui/pull/110
* Docs/arch 01 architecture spine by @achappell in https://github.com/achappell/hermes-relay-tui/pull/109
* feat: adapt TUI to shared domain contract by @achappell in https://github.com/achappell/hermes-relay-tui/pull/111
* feat: gate Hermes turns on verified authorization by @achappell in https://github.com/achappell/hermes-relay-tui/pull/116
* PUCK-01.2: stand up the Puck's ESPHome firmware build target by @achappell in https://github.com/achappell/hermes-relay-tui/pull/115
* PUCK-01.3: add on-device wake-word detection to the Puck firmware by @achappell in https://github.com/achappell/hermes-relay-tui/pull/117
* docs: define Hermes Home repository boundary by @achappell in https://github.com/achappell/hermes-relay-tui/pull/118
* fix(tests): remove flaky fixed-delay sync in composer-submit test by @achappell in https://github.com/achappell/hermes-relay-tui/pull/119
* feat: render honest turn phases and response delivery by @achappell in https://github.com/achappell/hermes-relay-tui/pull/120
* feat: gate wake follow-up on completed turns by @achappell in https://github.com/achappell/hermes-relay-tui/pull/121
* feat: add explicit TUI reconnect recovery by @achappell in https://github.com/achappell/hermes-relay-tui/pull/122
* Puck 01/3 onboard wake detection by @achappell in https://github.com/achappell/hermes-relay-tui/pull/123
* Feat/web epic 1 https lan by @achappell in https://github.com/achappell/hermes-relay-tui/pull/124
* docs: add surface coverage workflow by @achappell in https://github.com/achappell/hermes-relay-tui/pull/125
* feat: restore DOM-first home display by @achappell in https://github.com/achappell/hermes-relay-tui/pull/126
* fix: close Story 1.1 review gaps by @achappell in https://github.com/achappell/hermes-relay-tui/pull/127
* docs: define surface-specific stories across epics by @achappell in https://github.com/achappell/hermes-relay-tui/pull/128
* docs: make surface coverage index non-authoritative by @achappell in https://github.com/achappell/hermes-relay-tui/pull/130
* PUCK-01.5: stream audio to host after a validated wake by @achappell in https://github.com/achappell/hermes-relay-tui/pull/129
* docs: reconcile surface-specific story tracking by @achappell in https://github.com/achappell/hermes-relay-tui/pull/131
* docs: mark Epic 1 iOS Stories 1.1/1.2 done in sprint status by @achappell in https://github.com/achappell/hermes-relay-tui/pull/132
* fix: resolve Story 1.2 review findings by @achappell in https://github.com/achappell/hermes-relay-tui/pull/134
* docs: mark Epic 1 iOS Story I-3 as review by @achappell in https://github.com/achappell/hermes-relay-tui/pull/133
* feat(puck): swap pretrained wake models for trained hey_missy/bestie/skippy by @achappell in https://github.com/achappell/hermes-relay-tui/pull/135
* Delete CLAUDE.md by @achappell in https://github.com/achappell/hermes-relay-tui/pull/137
* fix(web): repair W/K browser audio delivery by @achappell in https://github.com/achappell/hermes-relay-tui/pull/136
* fix(tui): harden explicit reconnect recovery by @achappell in https://github.com/achappell/hermes-relay-tui/pull/140
* fix(puck): always mint a distinct bridge session id by @achappell in https://github.com/achappell/hermes-relay-tui/pull/138
* fix(puck): keep wake detection running so VAD-gated capture can work by @achappell in https://github.com/achappell/hermes-relay-tui/pull/139
* feat(web): show W/K transcription and retain responses by @achappell in https://github.com/achappell/hermes-relay-tui/pull/141
* docs(bmad): reconcile merged story statuses by @achappell in https://github.com/achappell/hermes-relay-tui/pull/142
* fix(tui): close Story 1.3 review findings by @achappell in https://github.com/achappell/hermes-relay-tui/pull/143
* feat(puck): give the Puck a speaker and stream audio to it (1-p-2 tasks 1-2) by @achappell in https://github.com/achappell/hermes-relay-tui/pull/144
* feat(tui): show explicit capture acknowledgement by @achappell in https://github.com/achappell/hermes-relay-tui/pull/145
* chore(puck): drop the boot-time streaming proof once verified by @achappell in https://github.com/achappell/hermes-relay-tui/pull/147
* docs: record the upload-TTL defect and move 1-p-1 to review by @achappell in https://github.com/achappell/hermes-relay-tui/pull/148
* fix: keep wake conversations listening across follow-ups by @achappell in https://github.com/achappell/hermes-relay-tui/pull/146
* fix(puck): make long captures deliverable, and report delivery honestly by @achappell in https://github.com/achappell/hermes-relay-tui/pull/149


**Full Changelog**: https://github.com/achappell/hermes-relay-tui/compare/v0.9.0...v0.10.0

## 0.9.0 (2026-09-07)

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Other Changes
* Feat/home 08 sherpa wake by @achappell in https://github.com/achappell/hermes-relay-tui/pull/86
* feat: household account profiles routed by wake word (HOME-13) by @achappell in https://github.com/achappell/hermes-relay-tui/pull/87
* feat(home-display): interactive prompt overlay and gateway notice handling (HOME-15) by @achappell in https://github.com/achappell/hermes-relay-tui/pull/89
* feat(session): session browser, commands, and transcript hydration (SESSION-01) by @achappell in https://github.com/achappell/hermes-relay-tui/pull/91
* feat(session): surface confirmed server metadata, capabilities, and status (SESSION-02) by @achappell in https://github.com/achappell/hermes-relay-tui/pull/92
* feat(app): interactive session picker selection modal (SESSION-03) by @achappell in https://github.com/achappell/hermes-relay-tui/pull/93
* ci(actions): bump actions/setup-node from 4.4.0 to 7.0.0 by @dependabot[bot] in https://github.com/achappell/hermes-relay-tui/pull/94


**Full Changelog**: https://github.com/achappell/hermes-relay-tui/compare/v0.8.0...v0.9.0

## 0.8.0 (2026-09-06)

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Other Changes
* feat: add wake follow-up and visible optional installs by @achappell in https://github.com/achappell/hermes-relay-tui/pull/73
* feat(voice): align captions with streamed playback by @achappell in https://github.com/achappell/hermes-relay-tui/pull/78
* feat(audio): add speech alignment benchmark gate by @achappell in https://github.com/achappell/hermes-relay-tui/pull/80
* feat(voice-session): add structured prompt client contract by @achappell in https://github.com/achappell/hermes-relay-tui/pull/82
* feat(home-display): segment-aware audio captions and deterministic shutdown by @achappell in https://github.com/achappell/hermes-relay-tui/pull/83
* feat(app): structured-prompt TUI (approval/confirm/clarify/sudo/secret) by @achappell in https://github.com/achappell/hermes-relay-tui/pull/84
* feat(wake): add Sherpa-ONNX keyword spotting engine and multi-phrase routing (HOME-08) by @achappell in https://github.com/achappell/hermes-relay-tui/pull/85


**Full Changelog**: https://github.com/achappell/hermes-relay-tui/compare/v0.7.0...v0.8.0

## 0.7.0 (2026-09-05)

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Other Changes
* VOICE-11: show a standing marker while the microphone is held open by @achappell in https://github.com/achappell/hermes-relay-tui/pull/53
* VOICE-12: disarm wake mode across reload and reconnect by @achappell in https://github.com/achappell/hermes-relay-tui/pull/55
* UX-01: polish TUI state and layout surfaces by @achappell in https://github.com/achappell/hermes-relay-tui/pull/56
* feat: use voice-session interrupt events by @achappell in https://github.com/achappell/hermes-relay-tui/pull/57
* feat: stop wake follow-up locally by @achappell in https://github.com/achappell/hermes-relay-tui/pull/58
* VOICE-15: make wake startup non-blocking by @achappell in https://github.com/achappell/hermes-relay-tui/pull/59
* feat: add spoken barge-in to wake mode by @achappell in https://github.com/achappell/hermes-relay-tui/pull/60
* fix: make audio shutdown deterministic by @achappell in https://github.com/achappell/hermes-relay-tui/pull/70


**Full Changelog**: https://github.com/achappell/hermes-relay-tui/compare/v0.6.2...v0.7.0

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
