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
  - **intent:** The Puck can play one authenticated Hermes response continuously to EOF at normal live pace, regardless of whether the decoder receives fixed-length or chunked transfer framing. The live `/response` path remains chunked and streamed; fixed-length conformance uses a static controlled fixture at the Puck decoder boundary. The P-5 conformance fixture is at least 20 seconds of 24 kHz mono signed 16-bit PCM spanning at least two Hermes audio segments; its producer follows a recorded live trace and the consumer drains at real-time rate.
  - **success:** Hermes completion is recorded. Every expected PCM byte reaches the decoder, and the response queue is empty before successful EOF. There is no unclassified gap or premature `IDLE`. Before device resampling, the concatenated Hermes PCM source and bridge-delivered PCM payload have matching byte counts and SHA-256 fingerprints; duration is calculated at 24 kHz mono signed 16-bit. With Mac playback disabled, a controlled hardware run uses a temporary external microphone and deterministic fixture end marker to confirm audible completion. Median first spoken audio from capture end is at or below four seconds for the normal fixture.

- **CAP-2**
  - **intent:** The Puck can report an honest `unavailable` or error outcome when a response cannot continue, then remain usable for a later response.
  - **success:** An induced producer gap, bridge or connection failure, or response underrun never claims successful completion. Before headers, it produces an HTTP error; after streaming begins, authenticated `GET /response-status?seq=N` reports `unavailable` for that same sequence. Immediately after media-player idle and before wake detection resumes, the Puck checks that status. `complete` clears response state; `unavailable` aborts and clears remaining response playback, plays `refused_sound` once as the local error report, and resumes wake detection. The Puck retries 409 every 250 ms for up to 2 seconds. It treats 404, timeout, or authentication failure as `unavailable` and does not corrupt or replay the following response.

- **CAP-3**
  - **intent:** An operator can distinguish complete playback, underrun, stream failure, and silent truncation from bounded delivery evidence.
  - **success:** Host tests and a controlled hardware run record one bounded, content-safe trace per sequence. Each trace contains framing, source and delivered PCM byte counts and SHA-256 fingerprints, time to first PCM, producer gaps, consumer progress and rate, queue high-water bytes, stall duration, terminal outcome, and device build identity. The traces cover normal, accelerated, and failing streams.

## Constraints

- Preserve the authenticated `/response?seq=N` handoff, one-consumer response ownership, Hermes session authority, response sequence isolation, and no automatic replay of an uncertain turn.
- Enforce sequence ownership: while `seq=N` is active, duplicate, stale, and future fetches cannot replace its reader or queue; after `N` reaches a terminal state, fetching its response never replays it; `N+1` starts only after reader release with empty state; and late producer writes for `N` are rejected or ignored.
- Keep response audio transient and home-LAN-only. Do not retain raw audio, create a Media Server transcript archive, or substitute local fallback speech.
- Keep the Puck audio/status-only: no full response text, touch choices, or second Hermes authority on the device.
- Preserve the proven response format boundary: 24 kHz mono signed 16-bit PCM carried as a streaming WAV. The live `/response` path uses chunked framing; both chunked streaming and fixed-length decoder framing must be validated without buffering the entire live response.
- Validate framing integrity before declaring completion: a fixed-length body shorter or longer than its declared `Content-Length`, malformed or early-terminated chunked framing, and any bytes after the chunk terminator must become `unavailable` and never produce successful EOF. Release the active `seq=N` reader and queue, reject or ignore late bytes from `N`, and leave the next `N+1` response clean.
- Send the WAV header promptly and terminate the body definitively. The device reader treats a zero-length read as a timeout, not EOF, and abandons a stream after about 30 seconds without a successful read. For an active sequence, a gap under 20 seconds without successful PCM progress is recoverable and must not emit EOF; at 20 seconds without progress, mark the response `unavailable`. Successful EOF is allowed only after Hermes completion, delivery of all expected PCM, and queue drain. A failure after streaming begins must use the device-visible `unavailable` status path rather than masquerading as EOF.
- Serialize PCM writes with terminal transitions. `complete` and `unavailable` are distinct latched outcomes: only a normal, validated completion may latch `complete`, while every failure path latches `unavailable`. The consumer drains a final queued PCM write before accepting successful EOF, and a completed stream cannot be downgraded by a concurrent stall check. Emit the chunk terminator only for `complete`; close an `unavailable` post-header delivery as failed and leave the status endpoint authoritative. After either outcome, reject or ignore late writes and leave the next sequence empty.
- Keep the response terminal status sequence-scoped and authenticated. `GET /response-status?seq=N&token=...` returns HTTP 200 with exactly `{"seq": N, "status": "complete"}` or `{"seq": N, "status": "unavailable"}` for a known terminal response, HTTP 404 for an unknown or expired sequence, and HTTP 409 while that sequence is still active. Retain terminal status for 60 seconds or until the next sequence begins; never fall back to the latest sequence. The endpoint carries no audio, transcript text, prompt, or error detail.
- After media-player idle, query `/response-status` before resuming wake detection. Treat `complete` as a clean handoff; treat `unavailable`, 404, timeout, or authentication failure as a local error, with no remaining response PCM and one `refused_sound`; retry 409 every 250 ms for no more than 2 seconds.
- Bound response buffering to at most 480,000 bytes of queued PCM (10 source-seconds at 24 kHz mono signed 16-bit), including every queued byte. No PCM may be dropped or replayed. When full, the producer applies asynchronous backpressure and waits for consumer progress; if no progress occurs within the 20-second stall budget, it marks the response `unavailable` and stops. Incoming chunks are split as needed to respect the cap. The fix must not trade an underrun for unbounded bridge memory or silent truncation.
- Measure before tuning. Increasing the prebuffer alone is not an accepted solution: two seconds did not help the observed run and eight seconds made delivery worse.
- Keep speaker startup asynchronous and playback on the media-player audio task; do not busy-wait in firmware automation or write audio synchronously from the main loop.
- Preserve wake detection, the delivered wake-time acknowledgement and non-overlapping capture ordering, capture/upload behavior, speaker ownership, post-playback wake readiness, and the existing four-second median first-spoken-audio working target for the normal fixture. Record response-admission-to-first-PCM separately; any latency exception must identify whether Hermes, the bridge, the network, or device playback caused it.

## Non-goals

- Implementing the Puck's bounded follow-up or exact `stop` behavior; that is P-3.
- Implementing transport recovery and no-replay session behavior; that is P-4, except for verifying that a failed response does not poison the next response.
- Bridge process shutdown, raw-PCM privacy diagnostics, audio-format conversion, I2S lifecycle cleanup, internal wake-model routing, and low-level speaker callback, preload, channel-enable, queue, DMA, or output-state failure propagation are P-6 through P-11. P-5 owns response-stream failures and verifies they are not reported as complete; P-11 owns speaker-path failure semantics.
- Changing Hermes generation, TTS content, the voice-session protocol, the Puck capture/upload transport, or the device's wake-word engine.
- Adding active-playback barge-in or buffering the entire response as a prerequisite for ordinary playback.

## Success signal

At normal live pace, a representative full response reaches the Puck speaker and EOF without premature `IDLE`, with fixed-length and chunked framing both complete. A real wake round trip is audible on the Puck rather than the Mac, a later wake remains clean, and controlled failure tests produce an explicit error or `unavailable` outcome with no stale bytes. Focused host/firmware tests and the full repository suite pass.

## Assumptions

- P-1 and P-2 are the delivery baseline; their owning story artifacts and the local sprint tracker record them done.
- The existing authenticated response endpoint and ESPHome `audio_http` playback path remain the implementation boundary unless measurement proves a coordinated bridge/device change necessary.
- The leading hypothesis is producer/consumer pacing or backpressure. Controlled probes have ruled out the observed response-body, WAV-structure, and framing failures, but P-5 measurement must still test reader, CPU, and playback-task starvation before selecting the fix.

## Remaining implementation decisions

- None. Implementation must preserve the accepted marker and detection contract in the validation companion.
