---
title: 'Keep Home browser turns alive when Standard reports audio fallback'
type: 'bugfix'
created: '2026-10-12'
status: 'in-review'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/AGENTS.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Observed in the B3 live run (pinned Standard 0.21.1 `2237be3`, Home `3fb9936`, TUI `638e1bc`; `/tmp/hermes-b3-proof-evidence.json`): Home forwarded `audio.frame` `kind=fallback` before any prompt. `HomeBrowserSession` yielded `audio_abort`, `BrowserSession.send_turn` treated every `audio_abort` as fatal (`hermes_unavailable`), retired the claim, and the `clarify.request` never rendered. A Standard with no streaming TTS provider (text-only or local TTS) therefore cannot use the Home browser at all.

**Approach:** In the browser session only, turn Home's explicit audio `fallback`/`unavailable` frame into a non-fatal `audio_unavailable` event (the vocabulary the Textual and gateway sessions already use). The browser turn keeps text, prompts and the terminal event, closes any open browser audio stream, and shows an honest "Audio unavailable" status.

## Boundaries & Constraints

**Always:** Keep failing closed on everything that is not that explicit frame. No fake PCM. After a fallback no later PCM or audio frame reaches the browser. The browser audio stream is closed exactly once (abort if open, never abort plus end). A pending prompt is never replaced by a status republish.

**Never:** Change `HomePuckSession`, Puck, the Textual/Home TUI session, Home or Standard. Add broad `except` suppression. Treat `audio_abort`, `error`, `turn_interrupted` or timeouts as benign. Change web assets (status text already renders).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fallback before any text (observed) | `audio.frame` kind `fallback`/`unavailable`, then `message.start`, clarify/typed prompt, answer, terminal | `audio_unavailable`, then prompt and terminal delivered; page shows the prompt, then idle with "Audio unavailable"; claim kept | N/A |
| Unavailable after audio started | `audio_start`, PCM, then `unavailable`, then text and terminal | Browser stream aborted once; later PCM dropped; text and terminal delivered | N/A |
| Frame while a prompt is pending | Prompt shown, then `fallback` | Prompt overlay untouched; status applied once the turn finishes | N/A |
| Malformed audio frame | Wrong handle or turn, bad metadata, duplicate start, end before start, PCM outside a frame, unknown kind | Unchanged: `HomeBridgeAudioError`, error event, `hermes_unavailable` | Fatal as today |
| Audio tail lost after text completed | Completion timeout or transport loss (`audio_abort` with `text_completed`) | Unchanged: `audio_abort`, fatal in the browser | Fatal as today |
| Home error or protocol failure | `error` event, protocol error, transport error | Unchanged | Fatal as today |
| Puck / Textual consumers | Same frames | Unchanged (Puck still yields `audio_abort`; Textual still maps to `audio_unavailable`) | N/A |

</frozen-after-approval>

## Code Map

- `puck_bridge/home_session.py` -- `HomeBrowserSession` (subclass, browser-only); `HomePuckSession._audio_event` maps `fallback`/`unavailable` to `audio_abort`; `_send_turn_locked` already latches `audio_failed` and continues to the text terminal.
- `home_display/home_admission.py` -- `BrowserSession.send_turn` raises on `error`/`audio_abort`; must keep doing so, passes `audio_unavailable` through.
- `home_display/appliance.py` -- `_run_browser_turn` has no `audio_unavailable` branch; `audio_abort` ends the turn with "Response interrupted". `abort_audio`, `_publish`, `_pending_prompt_action_id`, touch's `AUDIO_UNAVAILABLE_STATUS` pattern (`home_display/touch.py`) are the reference.
- `tests/test_puck_home_session.py` (`_FakeConnect`, `_ready_socket`, `_audio`, `_event`), `tests/test_browser_home_admission.py`, `tests/test_home_clarify_browser.py`, `tests/test_home_appliance.py` -- fixtures and existing audio-failure coverage to keep green.

## Tasks & Acceptance

**Execution:**
- [ ] `puck_bridge/home_session.py` -- override `HomeBrowserSession._audio_event`: when the base returns the `fallback`/`unavailable` `audio_abort`, return `{"type": "audio_unavailable", "reason": <same text>}`; delegate everything else, including raises -- the exact frame kinds are the only distinction.
- [ ] `home_display/appliance.py` -- handle `audio_unavailable` in `_run_browser_turn`: close an open stream via `abort_audio`, set a turn flag, drop further audio, publish "Audio unavailable" (shared constant) unless a prompt is pending, keep that status on later response publishes and the final idle.
- [ ] `tests/` -- regressions below; each new browser regression fails before the fix.
- [ ] `CHANGELOG.md` -- Unreleased bug-fix entry.

**Acceptance Criteria:**
- Given a real `HomeBrowserSession` behind `BrowserSession` and frames fallback, `message.start`, prompt, terminal, when the turn runs, then events include `audio_unavailable`, `prompt_request` and `turn_end` and no `error` event; the claim stays.
- Given `audio_start` then `unavailable` through `_run_browser_turn`, then `send_audio_abort` is called once, no `send_audio_end`, no chunk after it, the response completes idle with "Audio unavailable".
- Given each malformed-frame, completion-timeout, transport-loss and `error` case above, the existing fatal results still hold (tests retained or added).
- `HomePuckSession` event streams are byte-for-byte unchanged (existing Puck tests untouched and green).

## Implementation Notes

- Approved 2026-10-12 with review additions: the superclass `audio_failed` latch keys on any audio event that is not start/end, so the renamed `audio_unavailable` still drops later audio; an informative rejection or unsupported-prompt status outranks "Audio unavailable"; the status is per turn and clears when the next turn starts.
- Files: `puck_bridge/home_session.py` (`HomeBrowserSession._audio_event`), `home_display/appliance.py` (`_run_browser_turn`), `tests/test_home_browser_audio_fallback.py` (21 tests; 7 fail on the pre-fix source, including the real `HomeBrowserSession` behind `BrowserSession` admission), `CHANGELOG.md`.
- `home_display/home_admission.py` needed no change: it already passes `audio_unavailable` through and keeps `audio_abort`/`error` fatal.

## Design Notes

Decision for review: an `unavailable` frame after playback began is non-fatal (stream aborted, text continues), matching the Textual session. Only the timeout and transport-loss endings after text completion stay fatal. The first fix point is the browser subclass override, not `BrowserSession`'s filter, so the explicit frame is identified by the exact `kind` check inside `_audio_event` rather than by inferring from event fields.

## Verification

**Commands:**
- `python -m pytest tests/test_puck_home_session.py tests/test_browser_home_admission.py tests/test_home_clarify_browser.py tests/test_home_appliance.py tests/test_home_textual_session.py tests/test_home_disconnect.py` -- expected: pass
- `python -m pytest` -- expected: full suite passes
- `cd home_display/web && npm ci && npm run check && npm test` -- expected: pass; no source or tracked asset change (`npm run build` is not run)
- `python scripts/smoke_home_browser.py` (isolated, pinned Standard, scripted model) -- expected: B3 reaches a rendered typed choice with no `audio_abort`
