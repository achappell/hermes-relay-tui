---
title: 'Complete streamed Puck response playback without underrun'
type: 'feature'
created: '2026-09-12'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '960c646643142a4999ae42cad9be01214f98d48c'
context:
  - '{project-root}/_bmad-output/specs/spec-1-p-5-complete-streamed-response-playback-without-underrun/SPEC.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Puck can receive a valid streamed answer, yet the bridge queue is unbounded and a stall or failed delivery can look like successful EOF. The result can be underrun, early idle, truncation, and no honest failure signal.

**Approach:** Make the handoff sequence-scoped and bounded: apply asynchronous backpressure within 480,000 queued PCM bytes, distinguish `complete` from `unavailable`, and expose that result through an authenticated status endpoint. Keep live `/response` chunked, add firmware post-idle confirmation with bounded retry/refusal behavior, and preserve Hermes, capture, wake, and acknowledgement contracts.

## Boundaries & Constraints

**Always:** Preserve one response owner and no automatic replay. Split writes as needed; never drop or duplicate PCM. Gaps under 20 seconds remain recoverable; 20.0 seconds or more becomes unavailable. Serialize final PCM with terminal selection: successful EOF requires Hermes completion, all source PCM delivered, and queue drain, and only it emits the chunk terminator. Status is authenticated and sequence-scoped: active `409`, terminal `200` with `{"seq": N, "status": "complete"}` or `{"seq": N, "status": "unavailable"}`, unknown/expired `404`, retained 60 seconds or until the next sequence. Record bounded content-safe evidence.

**Never:** Change Hermes/session authority, capture upload, wake acknowledgement, or the live chunked path into whole-response buffering. Do not modify `pcm_capture.h`, archive raw audio or response text, add fallback speech, enable Mac playback for device mode, or absorb P-11 speaker/DMA/output-failure work.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Normal response | `seq=N`, 20+ seconds of 24 kHz mono signed-16 PCM over two segments | Bytes arrive once, source/delivered counts and SHA-256 match, queue drains, body ends | Missing bytes prevent `complete` |
| Producer gap | Active stream, no PCM progress for 19.9, 20.0, or 20.1 seconds | 19.9 resumes without EOF | 20.0+ latches `unavailable` |
| Queue/framing/ownership failure | Full queue, progress stop, short/long fixed body, malformed chunks, or duplicate/stale/future/late `seq` | Backpressure stays bounded; never successful EOF or replay; next sequence reusable | Mark unavailable; close without terminator; reject/ignore excess and late bytes |
| Device handoff | Media player idle | Poll before wake restart; complete clears; unavailable clears/aborts and plays refusal once | Retry 409 every 250 ms for <=2 seconds; 404/timeout/auth failure is unavailable |

</frozen-after-approval>

## Code Map

- `puck_bridge/response.py:81-316` -- `ResponseStream`/WAV header; retain condition, single-reader, and prebuffer model, adding byte bounds, sequence lifecycle, progress, and terminal outcomes.
- `puck_bridge/receiver.py:68-74,177-385` -- authenticated response `Handler.do_GET` and `_write_chunk`; add `/response-status`, framing/terminal handling, and safe traces without changing upload reassembly.
- `puck_bridge/turn.py:88-620` -- `TurnRunner._run_turn`; reuse Hermes segment handling and `response_seq`, separating normal completion from every failure and recording source/progress metrics.
- `firmware/respeaker-lite/respeaker-lite.yaml:418-503,675-715` -- existing audio source/player/response trigger; add post-idle status polling, retry, clear/abort, refusal sound, and wake ordering.
- `tests/test_puck_bridge.py` and `tests/test_puck_firmware.py` -- extend fakes/source checks for pacing, bounds, terminal races, framing, status, ownership, and sequential reuse. Leave `pcm_capture.h` unchanged.

## Design Notes

- Plan facts: intent gaps none; no migration or data mutation; firmware compile/run is explicit validation; footprint is the mapped files plus only a narrow status helper if YAML cannot express retry state cleanly. Fixed-length conformance is a static decoder-boundary fixture; live `/response` remains chunked.

## Tasks & Acceptance

**Execution:**
- [x] `puck_bridge/response.py` -- implement bounded producer/consumer backpressure, sequence ownership, progress, and terminal API -- prevent growth, underrun misclassification, and replay.
- [x] `puck_bridge/receiver.py`, `puck_bridge/turn.py`, `puck_bridge/server.py`, and `diagnostics.py` -- connect outcomes, status, framing, accounting, and bounded traces -- make failure truthful.
- [x] `firmware/respeaker-lite/respeaker-lite.yaml` and any scoped helper -- confirm status after media-player idle, retry active status, clear failed playback, play one refusal, then resume wake.
- [x] `tests/test_puck_bridge.py` and `tests/test_puck_firmware.py` -- cover 20-second/two-segment cadence, both framings, gap boundaries, full queue, terminal races, ownership, and reuse.

**Acceptance Criteria:**
- Given the normal fixture and real-time consumer, when Hermes completes, then every normalized PCM byte arrives once, the queue is empty, safe metrics are recorded, and only then does `/response` emit successful EOF.
- Given a post-header failure or no-progress gap of at least 20 seconds, when the response stops, then no success terminator is sent and same-sequence status is `unavailable`; the next sequence starts clean.
- Given active, terminal, or unknown sequence requests, when the Puck polls or retries, then the endpoint returns defined 409/200/404 results and never replays or substitutes audio.
- Given media-player idle, when firmware checks status, then `complete` resumes wake, while `unavailable`, 404, timeout, or auth failure clears response state, plays `refused_sound` once, and resumes wake after bounded retries.
- Given the controlled fixture with Mac playback disabled, when the long response plays, then the Puck completes audibly, the external observer detects the defined marker once at correlation `>= 0.8` within +/-500 ms after measured latency, median first audio is at most 4 seconds from capture end, and a second wake works.

## Implementation Notes

- Host and firmware contract tests pass: the focused bridge/firmware run is 92 passed, and the complete repository suite is 1079 passed with one unrelated websockets deprecation warning.
- The P-5 firmware compile was attempted with output kept out of the trace. It is currently blocked by a pre-existing `last_capture_captured` reference in `firmware/respeaker-lite/pcm_capture.h`; P-5 leaves that file unchanged as required. The hardware gate remains pending.

## Spec Change Log

## Review Triage Log

- `verification-gap/live-truncated-response` — verdict `medium`, route `patch`: the reviewed handler already withheld `0\r\n\r\n` on a producer stall, but no live socket test proved it; `test_response_endpoint_closes_without_success_eof_when_producer_stalls` now asserts a closed post-header body and `unavailable` status.
- `verification-gap/generated-firmware-boundary` — verdict `medium`, route `patch`: YAML/source assertions and the isolated helper harness did not exercise ESPHome generation; `test_respeaker_yaml_passes_esphome_config_generation` now runs the installed config gate, while the helper harness covers idle, retry, complete, unavailable, and watchdog transitions.
- `verification-gap/terminal-expiry` — verdict `low`, route `patch`: retention had no boundary evidence; `test_response_status_expires_after_its_retention_window` now checks before, exactly at, and just after 60 seconds, including the HTTP 404 path.
- `verification-gap/reboot-sequence-epoch` — verdict `medium`, route `defer`: `pcm_capture.h` resets its volatile sequence counter on reboot while the bridge retains the last sequence; a boot epoch or reset authority is needed and is outside P-5's no-capture-file-change boundary.
- `verification-gap/refusal-recovery` — verdict `medium`, route `patch`: an erroring refusal media pipeline could miss `on_idle`; the response helper now has a bounded refusal watchdog and the YAML stops the failed playback before resuming wake.
- `blind-hunter/prebuffer-cap` — verdict `medium`, route `patch`: an unusual high-rate/multichannel format could demand more than the bounded queue and deadlock prebuffer; the target is capped at the queue limit and covered by `test_prebuffer_target_is_capped_at_the_response_queue_bound`.
- `blind-hunter/orphaned-complete-response` — verdict `medium`, route `patch`: a completed response left queued with no reader blocked the next capture; `expect()` now supersedes that stale, reader-free completion and the sequential-reuse test proves the queue resets.
- `blind-hunter/consumer-based-stall-clock` — verdict `medium`, route `patch`: the reviewed iterator measured a source stall from the last dequeue, so a slow socket could distort the producer budget; iteration now uses source progress, with buffered-gap coverage.
- `blind-hunter/backpressure-timestamps` — verdict `low`, route `patch`: the reviewed write reused its pre-wait timestamp for first PCM; source-gap timing now records event arrival while first-PCM timing records queue insertion.
- `blind-hunter/unvalidated-audio-format` — verdict `medium`, route `patch`: malformed dimensions could escape into WAV packing and leave an active response; format validation and expected receiver failure handling now reject them, covered by `test_invalid_audio_format_is_rejected_before_wav_packing`.
- `blind-hunter/unscoped-response-fetch` — verdict `medium`, route `patch`: an authenticated fetch without `seq` could select the current answer rather than the requested capture; `/response` now requires one non-negative sequence and existing device-shaped tests pass it explicitly.
- `blind-hunter/unencoded-query-token` — verdict `medium`, route `patch`: reserved characters in the audio/status URL credential could change query parsing; the firmware helper now percent-encodes the query token and the C++ harness covers it.
- `blind-hunter/exact-terminal-json` — verdict `false`: the claim treats whitespace/key-order tolerance as required, but the approved status contract explicitly requires the exact serialized body and the firmware compares that deliberate byte contract.
- `blind-hunter/status-content-type` — verdict `low`, route `patch`: terminal status was JSON without declaring its media type; successful status responses now include `Content-Type: application/json`.
- `blind-hunter/refusal-stuck-state` — verdict `medium`, route `patch`: same refusal-pipeline failure is real and is covered by the watchdog fix logged above; it is retained as a separate finding row per review protocol.
- `blind-hunter/post-delivery-speaker-failure` — verdict `medium`, route `defer`: bridge completion proves HTTP delivery, not decoder/DMA/output success; P-11 explicitly owns that low-level speaker failure propagation.
- `blind-hunter/file-fallback-buffer` — verdict `low`, route `defer`: the full `audio_file` bytearray predates P-5 and a bounded incremental decoder is a separate fallback-path design, not the live PCM queue.
- `blind-hunter/compile-blocker` — verdict `medium`, route `defer`: the current compile failure is the unchanged `pcm_capture.h` reference to undeclared `last_capture_captured`; P-5 cannot repair that file without violating the frozen boundary.
- `blind-hunter/implementation-checkboxes` — verdict `false`: execution checkboxes record implemented slices, while hardware verification is separately pending and explicitly documented in Implementation Notes; no acceptance gate was falsely marked complete.
- `blind-hunter/static-decoder-fixture` — verdict `medium`, route `defer`: the Python fixed/chunked fixture is the specified host decoder-boundary proxy, but the actual ESPHome decoder/audio path and acoustic gate require the unavailable physical validation run.
- `blind-hunter/test-count` — verdict `false`: the reviewed checkout's full suite was rerun after the diagnostics caplog fix and produced 1,079 passing tests plus one unrelated deprecation warning.
- `blind-hunter/build-identity-provenance` — verdict `maybe-false`, route `defer`: the trace identity is a configured deployment label, not an authenticated device claim; settling multi-firmware provenance requires a device-administration handshake outside P-5.
- `edge-case-hunter/producer-gap-with-buffered-tail` — verdict `medium`, route `patch`: the reviewed producer accepted PCM after a 20-second source gap when old PCM remained queued; `write()` now latches `unavailable` before accepting that late data and the boundary test covers it.
- `edge-case-hunter/prebuffer-cap` — verdict `medium`, route `patch`: same uncapped prebuffer deadlock as `blind-hunter/prebuffer-cap`; fixed once at the target calculation and covered once above.
- `edge-case-hunter/unfetched-completion` — verdict `medium`, route `patch`: same stale queued completion as `blind-hunter/orphaned-complete-response`; the next-sequence supersession fix and test cover it.
- `edge-case-hunter/reboot-sequence-epoch` — verdict `medium`, route `defer`: same unchanged capture-counter reset as `verification-gap/reboot-sequence-epoch`; deferred to the boot/capture ownership boundary.
- `edge-case-hunter/reader-setup-exception` — verdict `medium`, route `patch`: `settimeout()` ran outside the acquired-reader `try/finally`; timeout setup now sits inside it so any socket failure releases the slot and marks delivery unavailable.
- `edge-case-hunter/upload-ack-failure` — verdict `medium`, route `patch`: a broken final upload acknowledgement could leave `expecting` latched with no turn; the acknowledgement path now abandons the admitted sequence on `OSError`.
- `edge-case-hunter/format-validation` — verdict `medium`, route `patch`: same malformed PCM-dimension path as `blind-hunter/unvalidated-audio-format`; validation and receiver exception handling cover it.
- `edge-case-hunter/refusal-playback-error` — verdict `medium`, route `patch`: same missed-idle refusal path as the two refusal findings above; the bounded watchdog provides the recovery transition.
- `edge-case-hunter/none-returning-callback` — verdict `medium`, route `patch`: the handler contract allowed a callback returning `None` to leave an admitted response active; non-`True` delivery now abandons the sequence and is covered by a focused upload test.

## Verification

**Commands:**
- `venv/bin/pytest tests/test_puck_bridge.py tests/test_puck_firmware.py` -- expected: focused bridge and firmware contract tests pass.
- `venv/bin/pytest` -- expected: complete repository suite passes.
- `venv-firmware/bin/esphome compile firmware/respeaker-lite/respeaker-lite.yaml` -- expected: controlled build succeeds; no credential files are added.

**Manual checks (if no CLI):**
- Run the documented long-response hardware gate with Mac playback disabled, an independent temporary microphone, the defined marker, and a second wake; discard the observer capture after metrics and record trace/build identity.
