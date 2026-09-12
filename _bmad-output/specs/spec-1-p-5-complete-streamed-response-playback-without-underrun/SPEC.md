---
id: SPEC-1-p-5-complete-streamed-response-playback-without-underrun
companions:
  - failure-modes.md
  - validation-plan.md
  - ../../implementation-artifacts/epic-1-context.md
  - ../../implementation-artifacts/spec-1-p-2-status-and-response-audio-delivery.md
  - ../../implementation-artifacts/deferred-work.md
  - ../../implementation-artifacts/surface-coverage-matrix.md
  - ../../planning-artifacts/prds/prd-hermes-relay-tui-2026-09-07/prd.md
  - ../../planning-artifacts/architecture/architecture-hermes-relay-tui-2026-09-08/ARCHITECTURE-SPINE.md
  - ../../planning-artifacts/ux-designs/ux-hermes-relay-tui-2026-09-07/DESIGN.md
  - ../../planning-artifacts/ux-designs/ux-hermes-relay-tui-2026-09-07/EXPERIENCE.md
sources:
  - ../../planning-artifacts/epics.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability.

# Complete streamed Puck response playback without underrun

## Why

The Puck's P-1/P-2 path can now wake, capture, reach Hermes through the bridge, and fetch response audio through the authenticated `/response?seq=N` stream. At normal live pacing, the device can nevertheless return cleanly to `IDLE` after consuming only part of a valid response while the bridge still has audio available. The room then hears a truncated answer even though the upstream response completed. P-5 closes this reliability gap in the primary room journey while preserving the Puck's audio/status-only role.

## Capabilities

- **CAP-1**
  - **intent:** The Puck can play one authenticated Hermes response continuously to EOF at normal live pace, regardless of whether the response uses fixed-length or chunked transfer framing. The P-5 conformance fixture is at least 20 seconds of 24 kHz mono signed 16-bit PCM spanning at least two Hermes audio segments; its producer follows a recorded live trace and the consumer drains at real-time rate.
  - **success:** Hermes completion is recorded, every expected PCM byte reaches the decoder, and the response queue is empty before successful EOF; there is no unclassified gap or premature `IDLE`; the concatenated Hermes PCM source and bridge-delivered PCM payload have matching byte counts and SHA-256 fingerprints before device resampling, with duration calculated at 24 kHz mono signed 16-bit; and a controlled hardware run confirms the response is audible to completion.

- **CAP-2**
  - **intent:** The Puck can report an honest unavailable or error outcome when a response cannot continue, then remain usable for a later response.
  - **success:** An induced producer gap, connection failure, or playback failure never claims successful completion; before headers it produces an HTTP error, and after streaming begins the authenticated `GET /response-status?seq=N` reports explicit `unavailable` for the same sequence. The Puck checks that status after media-player idle, aborts any remaining playback, leaves the output quiet, reports the error locally, returns to a reusable state, and does not corrupt or replay the following response.

- **CAP-3**
  - **intent:** An operator can distinguish complete playback, underrun, stream failure, and silent truncation from bounded delivery evidence.
  - **success:** Host tests and a controlled hardware run record source and delivered byte counts, first-audio time, producer/consumer timing, buffer high-water mark, stall duration, and terminal outcome for normal, accelerated, and failing streams.

## Constraints

- Preserve the authenticated `/response?seq=N` handoff, one-consumer response ownership, Hermes session authority, response sequence isolation, and no automatic replay of an uncertain turn.
- Keep response audio transient and home-LAN-only. Do not retain raw audio, create a Media Server transcript archive, or substitute local fallback speech.
- Keep the Puck audio/status-only: no full response text, touch choices, or second Hermes authority on the device.
- Preserve the proven response format boundary: 24 kHz mono signed 16-bit PCM carried as a streaming WAV, with both fixed-length and chunked framing supported.
- Send the WAV header promptly and terminate the body definitively. The device reader treats a zero-length read as a timeout, not EOF, and abandons a stream after about 30 seconds without a successful read. For an active sequence, a gap under 20 seconds without successful PCM progress is recoverable and must not emit EOF; at 20 seconds without progress, mark the response `unavailable`. Successful EOF is allowed only after Hermes completion, delivery of all expected PCM, and queue drain; a failure after streaming begins must use the device-visible `unavailable` status path rather than masquerading as EOF.
- Keep the response terminal status sequence-scoped and authenticated: `GET /response-status?seq=N` returns `complete` or `unavailable` for that response, carries no audio or transcript text, and expires after the next sequence or a bounded short TTL. A stale or duplicate query must not report completion for another sequence.
- Bound response buffering to at most 480,000 bytes of queued PCM (10 source-seconds at 24 kHz mono signed 16-bit), including every queued byte. No PCM may be dropped or replayed. When full, the producer applies asynchronous backpressure and waits for consumer progress; if no progress occurs within the 20-second stall budget, it marks the response `unavailable` and stops. Incoming chunks are split as needed to respect the cap. The fix must not trade an underrun for unbounded bridge memory or silent truncation.
- Measure before tuning. Increasing the prebuffer alone is not an accepted solution: two seconds did not help the observed run and eight seconds made delivery worse.
- Keep speaker startup asynchronous and playback on the media-player audio task; do not busy-wait in firmware automation or write audio synchronously from the main loop.
- Preserve wake detection, the delivered wake-time acknowledgement and non-overlapping capture ordering, capture/upload behavior, speaker ownership, post-playback wake readiness, and the existing roughly four-second first-spoken-audio working target where the chosen solution permits it.

## Non-goals

- Implementing the Puck's bounded follow-up or exact `stop` behavior; that is P-3.
- Implementing transport recovery and no-replay session behavior; that is P-4, except for verifying that a failed response does not poison the next response.
- Bridge process shutdown, raw-PCM privacy diagnostics, audio-format conversion, I2S lifecycle cleanup, internal wake-model routing, or detailed runtime output-failure propagation; those are P-6 through P-11.
- Changing Hermes generation, TTS content, the voice-session protocol, the Puck capture/upload transport, or the device's wake-word engine.
- Adding active-playback barge-in or buffering the entire response as a prerequisite for ordinary playback.

## Success signal

At normal live pace, a representative full response reaches the Puck speaker and EOF without premature `IDLE`, with fixed-length and chunked framing both complete. A real wake round trip is audible on the Puck rather than the Mac, a later wake remains clean, and controlled failure tests produce an explicit error or unavailable outcome with no stale bytes. Focused host/firmware tests and the full repository suite pass.

## Assumptions

- P-1 and P-2 are the delivery baseline; their owning story artifacts and the local sprint tracker record them done.
- The existing authenticated response endpoint and ESPHome `audio_http` playback path remain the implementation boundary unless measurement proves a coordinated bridge/device change necessary.
- The current defect is primarily pacing or consumer backpressure, because the response body, WAV structure, and both transfer-framing variants have already passed controlled probes.

## Open Questions

- What bounded response-queue and backpressure policy keeps a slower Puck consumer supplied without unbounded memory, dropped audio, or replay?
- Does the reliable fix belong in bridge producer pacing, the ESPHome device buffering path, or a coordinated change across both?
- What measured silence interval distinguishes a recoverable producer gap from a genuine stream failure without cutting off a valid response?
- What controlled hardware evidence is sufficient to declare the response audible to completion, beyond the decoder reaching EOF and returning to `IDLE`?
