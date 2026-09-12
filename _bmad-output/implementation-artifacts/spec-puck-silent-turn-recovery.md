---
title: 'Restore Puck audio after phantom stops and failed turns'
type: 'bugfix'
created: '2026-09-12'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
---

<frozen-after-approval reason="human-owned intent">

## Intent

Restore spoken responses after a bridge turn fails. A send exception must produce a content-safe visible failure, finish its response stream, and return a failed delivery result. A later fresh question may reconnect; an uncertain failed question must never be replayed. Preserve the existing protocol and firmware audio settings.

</frozen-after-approval>

## Implementation Notes

- Live puck reachable, unmuted, volume 0.25; firmware reports compilation 2026-09-11 22:12:50. Latest bridge evidence contains response 504s without an INFO-level turn outcome.
- Fake-session investigation reproduced swallowed ConnectionError, reported acceptance, and a finished stream without audio. This is proven independently of the still-unconfirmed live exception.
- Isolated worktree preserves unrelated planning changes. Repair is confined to the bridge runner and focused regression tests; playback pacing remains a separate hardware question.
- Hardware investigation subsequently identified the actual playback cancellation: every silent response/delayed probe was preceded by a GPIO3 User button ON event while Amanda confirmed the device was untouched. The generated pin configuration had FLAG_INPUT without FLAG_PULLUP. Added an internal pull-up, preserving active-low polarity, debounce, and the stop action.
- Before the firmware fix, a static one-second 24 kHz WAV was audible; the same PCM served with a 1.5-second header-to-body gap was cancelled by a phantom button event. An immediate chunked/sentinel WAV played, while a delayed real-length WAV failed too. This disproves framing/sentinel length as the cause of these runs.
- OTA flashed the fresh application image (1,933,632 bytes); device API confirmed compilation 2026-09-12 06:28:14 -0500. Serial factory-image generation failed, so that stale artifact was not used.
- After flash Amanda confirmed both original probe tones played. A full spoken count from one to twenty completed: 113 chunks, 689,920 PCM bytes, 14.3 seconds. A later short answer was comfortable after changing the persisted player volume from 0.25 to 0.40.
- This is direct contrary evidence to attributing all earlier clean ANNOUNCING-to-IDLE transitions to underrun. A stop-button event is intentional cancellation to the media player and produces the same externally clean transition. Check the button timeline before interpreting future cut-offs as pacing defects. This repair does not formally close other Puck stories or unrelated format/lifecycle work.
- Bridge repair makes callback delivery failures truthful, logs only exception types, handles normalized remote errors, reconnects only for fresh questions, retains cancellation cleanup ownership, and drains that owner during shutdown. No failed question is automatically replayed.
- Focused tests: 59 passed. Initial full suite after the bridge changes: 1002 passed. Final suite encountered an unrelated one-second TUI scheduling assertion in test_app_wake (1005 passed); focused rerun and final result recorded below.
- Final validation: the TUI test passed in isolation; the complete suite then passed 1006 tests with the existing websockets legacy deprecation warning. Firmware compiled, fresh OTA succeeded, generated GPIO flags contain INPUT | PULLUP, and both short/delayed tones plus long speech were confirmed audibly on the device. Diff whitespace checks passed.

## Review Triage Log

- Patched: reconnect cancellation could overlap a newer connection. Retained the actual task and added a delayed-cleanup regression.
- Patched: receiver's former "never asked" message was false for uncertain failed sends. Replaced it with an explicit uncertain-delivery/no-replay message.
- Patched: normalized server error events were ignored. They now return failed delivery without logging payload content.
- Patched: shutdown could race retained reconnect cleanup. Added ordered deferred cleanup and a regression that stops during pending cancellation; final independent review found no further issue in this fix.
