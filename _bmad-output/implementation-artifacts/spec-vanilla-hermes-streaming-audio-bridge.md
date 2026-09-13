---
title: 'Stream standard gateway audio with playback-paced TUI captions'
type: 'feature'
created: '2026-09-13'
status: 'done'
baseline_commit: '38b3e68106fac312acb0cdc82d9614b4d9cb3ae6'
route: 'dispatch'
review_loop_iteration: 1
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/surface-coverage-matrix.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-vanilla-hermes-connection-foundation.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The opt-in standard Hermes gateway transport now proves streamed text, but it does not deliver spoken replies. `gateway_client.py` is JSON-only and the TUI therefore cannot prove the product's essential loop: speak into the laptop, hear a response while it is generated, and see the response revealed in step with playback.

**Approach:** Keep `/api/ws` as the session and text lane, and open the existing `/api/audio/speak-stream` WebSocket as a separate per-turn audio sidecar. Feed normalized text deltas into that sidecar, translate its signed 16-bit PCM frames into the TUI's existing audio events, and let the current playback clock pace the visible assistant prefix. The local microphone and Faster-Whisper path remain unchanged: voice input becomes the same `prompt.submit` text turn.

## Boundaries & Constraints

**Always:** Keep the current `voice-session` transport as the default; derive the sidecar URL from the selected gateway URL, replacing its token and adding the selected Hermes profile; use the gateway's existing authentication without logging credentials; give each WebSocket exactly one reader; keep raw audio transient; bound sidecar queues and teardown waits; preserve no-replay behavior; degrade to readable text when the audio sidecar is unavailable; keep the Hermes fork untouched.

**Never:** Invent a new Hermes agent method or alter the `/api/ws` contract; send raw microphone PCM through the gateway in this slice; require server word-alignment metadata; make gateway mode the default; let audio-sidecar failure turn a successful text response into a lost turn.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| STREAMING_TURN | Gateway text deltas and an open audio sidecar | PCM begins before `message.complete`; the TUI plays it and reveals a monotonic text prefix from the playback clock | Preserve text if the sidecar fails |
| AUDIO_DRAIN | Gateway emits `message.complete` while PCM remains | Keep feeding playback; emit `turn_end` only after `audio_end` and the player has drained | Bound the drain wait and mark audio unavailable if it stalls |
| AUDIO_FALLBACK | Sidecar returns `fallback`, cannot open, or sends invalid start metadata | Text turn completes normally; audio is marked unavailable | Do not replay or fail the gateway turn |
| INTERRUPT | User interrupts while PCM is queued or playing | Send sidecar stop/close, abort local playback, and wait for the gateway's terminal interruption | Cancel the reader and discard late audio |
| AUDIO_LANE_LOSS | The sidecar closes while the gateway remains healthy | Complete the text turn honestly and report audio unavailable | Do not mark the prompt uncertain |
| GATEWAY_LOSS | The `/api/ws` lane closes during a turn | Preserve partial text and mark the turn uncertain | Close the sidecar; never resubmit the prompt |
| AUDIO_PROTOCOL | Sidecar sends empty/malformed frames or binary before `start`/after `end` | Ignore invalid late data and keep the text path usable | Mark audio unavailable without crashing the turn |

</frozen-after-approval>

## Code Map

- `gateway_client.py` -- preserve the JSON-RPC reader and token URL helper; do not teach it to consume audio frames.
- `gateway_audio.py` -- new core adapter for one `/api/audio/speak-stream` connection, its single reader, bounded event queue, text feeder, signed-16-bit PCM events, fallback, format validation, bounded waits, stop, and redacted diagnostics.
- `gateway_session.py` -- coordinate gateway events and the per-turn audio adapter; feed each normalized text delta once, interleave PCM events with gateway events, distinguish audio-lane loss from gateway loss, and hold `turn_end` until audio drains.
- `app.py` -- reuse the existing `audio_start`, `audio_chunk`, `audio_end`, interruption, and playback-clock caption path; present a truthful audio-unavailable state while preserving completed text.
- `audio.py`, `timing.py` -- existing PCM playback clock and duration-based caption fallback; preserve their current transport behavior.
- `tests/test_gateway_audio.py`, `tests/test_gateway_session.py`, `tests/test_app.py` -- fake sidecar/gateway timing, fallback, cancellation, and caption-prefix coverage.
- `AGENTS.md`, `pyproject.toml`, `README.md` -- register the core module, package it, and document the opt-in gateway voice boundary and its approximate (not word-aligned) caption timing.

## Tasks & Acceptance

**Execution:**
- [x] `gateway_audio.py` and `tests/test_gateway_audio.py` -- implement and test the authenticated streaming sidecar with one reader, bounded buffering, int16 format validation, timeouts, fallback, and safe teardown.
- [x] `gateway_session.py` and `tests/test_gateway_session.py` -- feed each text delta once, interleave PCM events, hold terminal completion through audio drain, and keep text/no-replay semantics independent of audio-sidecar failure.
- [x] `app.py` and `tests/test_app.py` -- verify the existing playback clock reveals only a monotonic assistant prefix until playback drains, and keeps text visible when audio is unavailable.
- [x] `AGENTS.md`, `pyproject.toml`, and `README.md` -- record the new core boundary, install surface, configuration, and deliberate alignment limitation.

**Acceptance Criteria:**
- Given gateway mode and a valid sidecar, when a turn streams, then audio begins before the gateway's terminal completion and the visible response advances from the playback clock without retracting text.
- Given `message.complete` arrives while audio remains queued, when the sidecar reaches `end`, then `turn_end` follows the audio drain rather than cutting off playback.
- Given a local microphone transcript, when it is submitted in gateway mode, then it uses the same text/audio turn path as a typed prompt.
- Given sidecar fallback or audio-lane failure, when the turn resolves, then text remains readable, audio is marked unavailable, and the prompt is not made uncertain.
- Given gateway interruption or gateway-lane loss, when the turn resolves, then audio is stopped, the terminal state is interruption or disconnection, and no uncertain prompt is replayed.
- Given an invalid or missing sidecar start frame, when audio setup completes, then the adapter rejects playback safely and the text turn continues.
- Given either transport is closed, when the session shuts down, then its reader and socket are released without blocking the Textual loop.
- Given `--no-play` or `--output`, when a gateway turn streams, then the sidecar is still drained and the existing WAV behavior remains available.
- Given the existing default transport, when it runs, then its wire frames and response audio behavior remain unchanged.

## Design Notes

The intended turn flow is:

```text
gateway /api/ws:  prompt.submit → message.delta* → message.complete
                         │                │
audio sidecar:    open/start ← text deltas → PCM* → end
                         │                         │
TUI:               audio_start → audio_chunk* → audio_end → turn_end
```

The sidecar is optional. Gateway text remains authoritative; audio is a second
delivery path. Captions use the existing playback clock and therefore remain
monotonic but are not guaranteed word-aligned.

## Verification

**Commands:**
- `uv run --no-project --with pytest --with pytest-asyncio --with textual --with websockets --with python-dotenv --with PyYAML --with jsonschema --with sounddevice --with numpy --with faster-whisper python -m pytest tests/test_gateway_audio.py tests/test_gateway_session.py tests/test_app.py tests/test_core_boundary.py` -- expected: focused gateway/audio/caption suite passes.
- `venv/bin/pytest` -- expected: complete suite passes.
- `git diff --check` -- expected: no whitespace errors.

**Manual checks (if no CLI):**
- Against a local dashboard, submit a short typed turn and a `Ctrl+R` turn with playback enabled; confirm the first PCM arrives before generation completes, the answer is audible, and the visible assistant text never runs ahead of the playback clock.
- Repeat with `--no-play --output response.wav`; confirm PCM is drained and the WAV fallback is written without opening a speaker.

## Validation Notes

- Focused gateway/audio/caption/core-boundary suite: 284 passed.
- Complete suite: 1158 passed, 1 skipped; one existing `websockets.legacy` deprecation warning.
- Live local dashboard probe through `GatewaySession`: 2,290 streamed text characters and 2,928,640 PCM bytes; first text at 10.9 seconds, first PCM at 12.0 seconds, and `audio_end` immediately before `turn_end` at 59.1 seconds, with no audio-unavailable event.
- The TUI connected to the same standard gateway using the opt-in `gateway` transport. The live probe used `--no-play`; actual speaker output remains a device-level check.

## Review Triage Log

The review layers identified the following findings. Each has one verdict; duplicate findings are retained here so the record shows how each was handled.

| Finding | Verdict | Evidence and route |
|---|---|---|
| V1 | medium | Patched. A stalled sidecar now emits `audio_unavailable` and then `turn_end`; the focused session test covers the bounded drain. |
| V2 | medium | Patched. Sidecar-open failure is tested with exactly one `prompt.submit` and a readable completed text turn. |
| V3 | medium | Patched. The sidecar stop test asserts the `{"stop": true}` wire frame and context closure. |
| V4 | low | Patched. A real `fallback` frame is normalized to `audio_unavailable`. |
| V5 | medium | Patched. Gateway loss after a partial delta preserves that delta, closes audio, and never emits a replay or terminal success. |
| B1 | medium | Patched. Gateway mode is conservative before `audio_start`; the app test proves only a short prefix is visible while the sidecar is pending. |
| B2 | medium | Patched. Existing URL query parameters, including `profile`, are preserved unless the caller explicitly selects a replacement profile. |
| B3 | medium | Patched. Odd PCM byte boundaries are carried into the next frame; incomplete final samples become unavailable rather than malformed audio. |
| B4 | medium | Patched. An `end` frame without PCM is unavailable, while a valid PCM stream still reaches `audio_end`; late frames are discarded. |
| B5 | medium | Patched. Sidecar text, finish, and stop sends have bounded waits, so a wedged audio socket cannot hold the gateway lane indefinitely. |
| B6 | low | Patched. Reader cancellation and context teardown are both bounded by the close timeout. |
| B7 | low | Deferred. Sidecar setup is bounded to three seconds and keeps the text turn correct; opening both lanes concurrently is a latency refinement for a later slice, not a correctness requirement for this proof. |
| B8 | false | The existing sidecar contract emits `end` after the gateway turn is complete; the adapter therefore cannot legitimately stop consuming audio before later text in the current server protocol. |
| B9 | medium | Patched. A valid gateway-audio app test holds the full response until audio starts, then confirms the complete text is committed after playback. |
| B10 | low | Patched. The existing WAV-output test now explicitly marks the fake session as gateway-audio-enabled, covering `--no-play`/output sidecar draining without hardware. |
| B11 | false | This was a stale validation snapshot, not a product defect; the final focused and full counts above were refreshed after the review fixes. |
| E1 | medium | Patched with B2. The duplicate profile-query finding has the same URL-preservation test and implementation fix. |
| E2 | medium | Patched. The audio reader returns immediately after a terminal frame, so late binary data cannot be delivered after `end` or fallback. |
| E3 | medium | Patched. A full event queue evicts one stale frame to reserve the close sentinel, preventing a blocked consumer after reader shutdown. |
| E4 | medium | Patched with B5. All sidecar sends use the same bounded send path. |
| E5 | low | Patched with B6. Reader shutdown is cancelled and awaited with a bounded timeout. |
| E6 | medium | Patched. Start metadata now requires exact positive integers within safe bounds and signed 16-bit width. |
| E7 | medium | Patched. Interruption stops the sidecar only after gateway cancellation is confirmed; request failure still tears audio down before propagating. |
| E8 | medium | Patched with B1. The same pre-`audio_start` caption gate prevents a gateway text event from revealing the full answer early. |
| E9 | false | The current Hermes sidecar sends its start frame on connection and the live probe observed PCM before `turn_end`; no alternate server behavior is supported by this slice. |
