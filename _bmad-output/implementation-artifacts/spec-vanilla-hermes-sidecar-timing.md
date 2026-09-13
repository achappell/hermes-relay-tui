---
title: 'Carry speech timing through the standard gateway audio sidecar'
type: 'feature'
created: '2026-09-13'
status: 'done'
baseline_commit: '9d07232ba897c1d0d482da65e0bdcc0041bc12e6'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-vanilla-hermes-streaming-audio-bridge.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The existing Hermes audio sidecar streams usable PCM, but it sends no timing for the spoken segments. The TUI therefore reveals words at a fixed guessed rate, which drifts away from the actual voice as soon as speech is faster or slower than the guess.

**Approach:** Extend the existing `/api/audio/speak-stream` WebSocket with optional `speech_timing` JSON frames using the timing payload already used by Hermes' voice-session channel. A segment is one non-empty, markdown-cleaned, text-cap-split piece passed to the TTS provider. Emit a real PCM-duration record for every completed segment, and use validated word spans when the existing opt-in alignment path is enabled and available. The TUI will normalize those frames into its existing playback-clock caption path.

## Boundaries & Constraints

**Always:** Keep the existing sidecar URL, authentication, text input, `start`/binary PCM/`end` framing, and little-endian signed 16-bit PCM unchanged. Use the documented nested `speech_timing.payload` shape. IDs are monotonic within one reply (`speech-tts-0`, `speech-tts-1`, ...); `gateway_session.py` adds turn/session IDs to the TUI event. Each record has normalized text, an absolute offset from the first PCM sample, integer millisecond duration, a timing source, and either complete validated words or no words. Timing arrives before final `end`; word offsets use that same clock. Keep alignment opt-in with its current bounded timeout. Duration fallback is the normal path. Accumulate exact sample counts, emit no record for zero-byte or incomplete segments, and suppress queued work after stop/disconnect.

**Never:** Add a new WebSocket or change `/api/ws` or the voice-session protocol. Do not enable an aligner by default, switch providers to obtain alignment, derive timing from client wall-clock guesses, send partial or unvalidated word spans, claim a truncated segment is complete, or make an old desktop client depend on the new JSON frames.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Duration fallback | Complete non-empty, sample-aligned segment; alignment disabled or unsupported | Low-latency PCM; one nested fallback record follows it with byte-derived duration and cumulative offset, then later segments and `end` continue | TUI converts milliseconds to seconds and uses the real segment clock |
| Valid alignment | Opt-in alignment returns spans matching spoken text and PCM | Validated record precedes matching buffered PCM; words use the absolute clock | Bounded wait may delay one segment, not the whole turn |
| Failure or cancellation | Invalid/late alignment, zero bytes, partial synthesis, stop, or disconnect | No false record or clean `end` for incomplete work; earlier complete audio remains usable | Suppress late work; never send exception text |
| Legacy client | Client ignores timing JSON interleaved with PCM | Existing `start`, PCM, and `end` remain usable | No compatibility failure |

</frozen-after-approval>

## Code Map

- `gateway_audio.py` -- unwrap and validate `speech_timing.payload`; malformed timing is ignored, not an audio failure.
- `gateway_session.py` -- preserve audio ordering, turn/session decoration, drain deadlines, and terminal handling.
- `timing.py` and `app.py` -- existing millisecond conversion and playback-clock caption reveal; no WebSocket parsing belongs in `app.py`.
- `tests/test_gateway_audio.py`, `tests/test_gateway_session.py`, `tests/test_timing.py`, `tests/test_app.py` -- protocol, unit-conversion, late-event, no-timing, and prefix-safety coverage.
- `~/.hermes/hermes-agent/hermes_cli/web_routers/audio.py` -- current sidecar producer; add timing around its cleaned, cap-split provider pieces without changing auth or text input.
- `~/.hermes/hermes-agent/tools/tts_streaming.py` and `gateway/streaming_tts_consumer.py` -- provider config plus existing alignment/fallback contract; share the payload builder/validator so voice-session behavior does not fork.
- `~/.hermes/hermes-agent/tests/hermes_cli/test_web_server_speak_stream.py` -- raw sidecar ordering, offsets, alignment, failure, legacy, and unchanged PCM tests.

## Tasks & Acceptance

**Execution:**
- [x] `~/.hermes/hermes-agent/hermes_cli/web_routers/audio.py`, `~/.hermes/hermes-agent/tools/tts_streaming.py`, `~/.hermes/hermes-agent/gateway/streaming_tts_consumer.py` -- retain scoped config, share timing construction/validation, and emit one nested record per complete sidecar piece -- preserve voice-session behavior and cancellation safety.
- [x] `gateway_audio.py`, `gateway_session.py`, `tests/test_gateway_audio.py`, `tests/test_gateway_session.py` -- consume and forward nested timing safely -- keep parsing out of `app.py`.
- [x] `tests/test_timing.py`, `tests/test_app.py` -- verify unit conversion, late timing, no-timing fallback, and longest-valid-prefix behavior -- prevent caption retraction.
- [x] `~/.hermes/hermes-agent/tests/hermes_cli/test_web_server_speak_stream.py` -- cover raw order, cumulative offsets, alignment/fallback, partial failure, cancellation, legacy clients, and unchanged PCM.
- [x] `~/.hermes/hermes-agent/docs/streaming-tts.md` -- document that the standard sidecar now carries the same optional timing records -- keep the cross-surface contract discoverable.

**Acceptance Criteria:**
- Given a streamed reply split into two spoken segments, when the TUI receives the sidecar frames, then each segment's captions use its actual PCM duration and cumulative offset rather than the fixed words-per-second guess, with the first record's offset at zero and the second record's offset equal to the first segment's exact sample duration.
- Given valid opt-in alignment, when a segment is synthesized, then the TUI receives matching validated word spans and reveals the words against the playback clock.
- Given unavailable or invalid alignment, when a complete segment is synthesized, then PCM remains audible and the TUI receives a duration fallback with no partial word timing; given a truncated segment, then no timing record or clean `end` falsely declares it complete.
- Given timing arrives after PCM playback has begun, when the TUI applies it, then the visible assistant prefix never retracts and the final caption still follows the playback clock.
- Given an existing desktop client that ignores unknown JSON frames, when it uses the sidecar, then playback still receives the same PCM stream and `end` marker.

## Implementation Notes

Planning facts: there is no remaining user-visible intent gap because the existing Hermes alignment setting already defines the precision/latency choice; alignment stays opt-in and duration timing is always safe. There is no irreversible operation: this adds optional JSON frames and tests, with no migration, deployment, or profile change. The footprint is one TUI protocol-consumer slice plus the existing Hermes sidecar route, shared timing tests, and contract documentation; it introduces no new channel or runtime dependency.

## Spec Change Log


## Review Triage Log

- 2026-09-13 — Delegated blind, edge-case, and verification-gap reviewers remained running through bounded scheduler waits and were closed without reports. Local review of the combined TUI/Hermes diff covered sidecar ordering, exact PCM offsets, nested normalization, alignment timeout/fallback, incomplete PCM, stop/disconnect, legacy PCM, session terminal ordering, and caption-prefix safety; no verified findings or deferred work remained.

## Design Notes

The raw sidecar envelope is deliberately the same payload shape as voice-session timing, without pretending the sidecar has a server turn ID:

```json
{"type":"speech_timing","payload":{"segment_id":"speech-tts-0","text":"Hermes moves.","timing_source":"duration_fallback","fallback_reason":"disabled","audio_offset_ms":0,"duration_ms":640,"words":[]}}
```

The low-latency duration path sends its record after that segment's PCM. Alignment mode buffers one segment and sends either validated alignment or its fallback record before that segment's PCM. Both cases finish before `end`. Duration fallback paces words across the real segment duration; exact word reveal requires opt-in alignment.

## Verification

**Commands:**
- `venv/bin/pytest tests/test_gateway_audio.py tests/test_gateway_session.py tests/test_timing.py tests/test_app.py` -- expected: focused TUI protocol and caption suite passes.
- `venv/bin/pytest` -- expected: complete TUI suite passes.
- `scripts/run_tests.sh tests/hermes_cli/test_web_server_speak_stream.py tests/gateway/test_streaming_tts_consumer.py tests/tools/test_tts_streaming.py` (from the Hermes checkout) -- expected: server sidecar and shared timing tests pass.

**Observed:** the focused TUI suite passed 272 tests; the complete TUI suite passed 1,158 tests with 2 expected skips; the Hermes runner passed 36 tests with 1 expected skip. The full TUI run required the repository's NumPy and tqdm test dependencies in the temporary Python 3.14 environment.

**Manual checks (if no CLI):**
- Against a configured Hermes endpoint, run one multi-sentence TUI voice reply and confirm the sidecar emits timing records (duration fallback by default; word spans only when alignment is explicitly enabled), captions advance with the heard speech, and an interrupt or disconnect leaves the text turn usable.
