---
title: 'Status and response audio delivery'
type: 'feature'
created: '2026-09-10'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'be3958fec3554abaae019fc22412eb0fbb8e4437'
context:
  - '{project-root}/_bmad-output/planning-artifacts/prds/prd-hermes-relay-tui-2026-09-07/prd.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## PARKED 2026-09-10 22:55

Tasks 1-2 are implemented and hardware-verified (PR #144); tasks 3-7 remain.
Deliberately parked to keep exactly one implementation slice active while
`1-p-1-authorized-wake-and-capture` runs. P-1 is the logically prior story --
these were started out of order -- and P-2's remaining tasks do not depend on
it, so this is a clean seam. Resume at task 3 (live-stream framing).

## Identifier reconciliation

This spec was first drafted as `PUCK-01.7`, a candidate label proposed in `docs/friction-log.md`'s 2026-09-09 entry. That predates the **2026-09-10 surface decomposition** of Epic 1 in `epic-1-context.md`, which assigns the ReSpeaker Puck the story set `P-1`–`P-4` and gives the Puck's **`1-p-2-status-and-response-audio-delivery`** ownership of "status and response audio" (the slug in `sprint-status.yaml`). `PUCK-01.7` is superseded and was never filed as a board item.

Note the epic prefix is load-bearing: `sprint-status.yaml` carries a `2-p-2` and a `3-p-2` as well, so a bare "P-2" is ambiguous. Always use the full slug.

Scope note: this story owns **both** halves of Puck audio output. The original `PUCK-01.7` framing covered only the response half. Status audio is added as task 7 below rather than left to be discovered later.

## Intent

**Problem:** Story 5 carries a wake all the way to a real Hermes turn, but the spoken answer comes out of the *Mac's* speakers (`puck_bridge/turn.py:159-162` writes TTS chunks to a local `PCMPlayer`). The Puck is capture-only: `respeaker-lite.yaml` declares a `microphone:` and no audio output at all. The household appliance cannot speak.

**Approach:** Give the Puck an output path built on ESPHome's own audio stack, not this project's hand-rolled `http_request` loop. Firmware gains an output `i2s_audio` bus, a `speaker: i2s_audio` on the board's DAC, an `audio_http` media source, and a `media_player: speaker_source`. The bridge stops playing TTS locally and instead serves it at an HTTP URL; the Puck plays that URL via `media_player.play_media`, and ESPHome handles buffering, decoding, and I2S timing.

**Why not the existing upload transport:** measured on hardware 2026-09-10, `pcm_capture.h`'s chunked POST loop runs at **25.3 KB/s** (314160 bytes in 12.14s; 77ms per 2KB chunk, because ESPHome's IDF `http_request` backend opens a fresh `esp_http_client` connection per `post()` call, plus a 30ms inter-chunk delay). Hermes TTS is 16-bit PCM (`audio.py:244` rejects other widths), so 16kHz mono needs 32 KB/s and 24kHz mono needs 48 KB/s. That transport runs at roughly half real-time and cannot stream speech. It also carries a documented defect history — `esp_http_client` wedging into persistent `ESP_FAIL`, ~11s ESP-IDF reconnect blocks, several KB of internal heap lost per failed call, and a reboot circuit breaker at 96KB to prevent an uncontrolled OOM. Those are survivable for an upload and audible for playback.

## Boundaries & Constraints

**Always:** Response audio stays transient and home-LAN-only (PRD NFR3) — served from memory, not persisted. Keep the `X-Puck-Token` shared-token check on the new endpoint, matching `/upload`. The bridge stays a standalone process. Firmware keeps `pcm_capture.h`'s existing safety machinery untouched — this story adds an output path beside it, it does not modify the capture/upload path. The host receiver keeps `protocol_version = "HTTP/1.1"`.

**Never:** No Story 4 credential system. No `voice_assistant:` component — the Puck's wake/capture path is already this project's own and must not be replaced by ESPHome's pipeline. No persisting raw audio. No rewrite of `pcm_capture.h`'s chunked upload.

</frozen-after-approval>

## Code Map

| Area | Path | Role |
|---|---|---|
| Firmware config | `firmware/respeaker-lite/respeaker-lite.yaml` | add output I2S bus, `speaker:`, `audio_http:`, `media_player:`, and the play trigger |
| Firmware reference | `firmware/respeaker-lite/respeaker-lite-stock-test.yaml:1144-1192` | proven speaker + dual-bus config for this exact board |
| Bridge turn | `puck_bridge/turn.py:143-180` | stop writing TTS to local `PCMPlayer`; publish to the response stream instead |
| Bridge server | `puck_bridge/server.py` | add the `/response` endpoint |
| Bridge receiver | `puck_bridge/receiver.py:246-280` | upload handler; response handoff point |
| Audio helpers | `audio.py` (`read_wav`, WAV writer at :28-32) | WAV framing for the served stream |

## Verified interface facts (ESPHome 2026.8.2, checked against `venv-firmware/`)

- `media_player:` has exactly one platform: **`speaker_source`**.
- `media_player.play_media`'s `media_url` is **templatable** (`media_player/__init__.py:325`) — a lambda can build the URL with a per-turn sequence number.
- **`audio_http`** is a first-class HTTP media source: single persistent connection read incrementally via `esp_http_client_read`, dedicated task, `buffer_size` default 50000 and configurable 5000–1000000, optional PSRAM task stack.
- Decoders available: **WAV, FLAC, MP3** (`audio/audio_decoder.h`).
- Speaker platforms: `i2s_audio`, plus `mixer` / `resampler` / `router` wrappers.
- The board's proven output block (stock reference): `i2s_dout_pin: GPIO43`, `dac_type: external`, `audio_dac: aic3204_dac`, `i2s_mode: secondary`, 48kHz/32-bit stereo, `timeout: never`, `buffer_duration: 100ms`.
- Input and output buses **share** GPIO7/8/9 (lrclk/bclk/mclk) via `allow_other_uses: true` on each pin — two `i2s_audio` entries, `i2s_input` (din GPIO44) and `i2s_output` (dout GPIO43).
- `respeaker_lite` exposes `mute_speaker()` / hardware mute — output must be explicitly unmuted.

## Tasks & Acceptance

1. **[DONE 2026-09-10] Firmware: make the Puck produce a sound at all.** Split `i2s_bus` into `i2s_input`/`i2s_output` sharing the clock pins with `allow_other_uses: true`; add `speaker: i2s_audio` per the stock block; unmute. *Acceptance:* a hardcoded test tone or short WAV plays from the Puck on demand, with `micro_wake_word` still detecting afterward (the mic path must survive the bus split).
2. **[DONE 2026-09-10] Firmware: wire the streaming media player.** Add `audio_http:` media source and `media_player: speaker_source`. *Acceptance:* `media_player.play_media` with a static URL served by the bridge plays end to end.
3. **[DONE 2026-09-11] Bridge: serve the response stream.** Add `GET /response?seq=N`, token-checked, that holds the connection until TTS begins and then streams WAV as chunks arrive. *Acceptance:* `curl` against it yields playable audio; a second request for the same `seq` does not duplicate a turn.
4. **[DONE 2026-09-11] Bridge: move playback off the Mac.** `_run_turn` publishes `audio_chunk` data to the response stream instead of `self._player`. *Acceptance:* answer is audible on the Puck, not the Mac.
5. **[DONE 2026-09-11] Firmware: trigger playback after upload.** On upload completion, call `media_player.play_media` with the templated `/response?seq=N` URL. *Acceptance:* full hands-free round trip — wake, speak, hear the answer from the Puck.
6. **[DONE 2026-09-11] Reshape the turn timeout.** `SEND_TIMEOUT_SECONDS = 10.0` currently bounds the *entire* turn including playback, so it fires on every real answer (observed 2026-09-10). Re-bound it to time-to-first-audio, with a separate stall guard for a mid-stream gap. Fix deferred item #36 in the same pass: a timeout must cancel the orphaned `_run_turn` coroutine, which can otherwise still write to a shared sink behind a later turn. *Acceptance:* a long answer completes; a genuinely unresponsive Hermes still returns to idle.

7. **[DONE 2026-09-11 — but NOT at the wake; see below] Status audio: acknowledge the captured question out loud.** Epic 1's UX rules require the Puck to stay *status-only* — "response text and transcript history do not belong on its TFT" — so on an audio-only device, status is carried by sound. `HOME-10` ("Wake acknowledgement and the silence before the answer") established this for the home-display appliance; the Puck has had no way to do it until task 1 gave it a speaker. Play a short acknowledgement on `on_wake_word_detected`, before capture completes, so a person knows they were heard during the several seconds before any answer arrives. *Acceptance:* a wake produces an audible acknowledgement within ~200ms; it does not leak into the captured audio (see the echo risk below) and does not delay or truncate capture.

## Constraints discovered during tasks 1-2 (binding on the rest)

- **Stream format must be declared before `start()`.** `AudioStreamInfo` defaults to `(16-bit, 1ch, 16000Hz)`. In secondary/slave mode the I2S speaker cannot reconfigure the bus and hard-rejects a mismatched **sample rate** with `Incompatible stream settings`. Bit depth may differ; sample rate may not. Everything therefore routes through the resampler to 48000.
- **`speaker->start()` is asynchronous and must not be busy-waited.** The state transition happens in the component's `loop()`, so blocking inside an automation lambda deadlocks it — loop never runs, state never advances. Use ESPHome's `delay:`, which yields.
- **Never write audio synchronously from the main loop.** Task 1's blocking tone helper starved the loop for 354ms, tripped `"a scheduled task took a long time"`, dropped WiFi mid-boot, and left `play_media` firing into a dead network. Playback belongs to `media_player`'s own task. This is the concrete reason this story does not hand-roll the audio path.
- **The resampler is wired but not yet exercised.** The task-2 test WAV was already 48kHz mono. Real 24kHz TTS will be its first genuine workout in task 3.

## Task 6 verification — 2026-09-11

First fully hands-free round trip: wake -> capture -> upload -> transcribe
-> Hermes -> spoken answer, nothing typed and no test harness.

```
puck bridge turn complete: 442 audio chunks spoken in 77.2s
```

**77.2 seconds of speech.** The previous bound killed every turn at 10s, so
this ran nearly 8x longer than the old ceiling and completed cleanly --
because the bound is now on responsiveness (gaps between events), not total
duration. Capture was a full 8.000s at 0.98 language confidence.

Delivered across #150 and #155. #150 reshaped the timeout and fixed
deferred #36 (an abandoned turn is now cancelled, not merely un-awaited).
#155 closed the gap #150 left: the per-event deadlines bound *fetching*
events from Hermes, not *processing* them, so a blocking `player.write` had
no timeout around it and one wedged turn poisoned the next.

Three silent-failure sites were closed along the way -- a successful turn
logged nothing, `player.failure` was never read, and a capture dropped by
the single-flight coordinator said nothing. Those were the reason the
underlying defects took as long to find as they did.

## Task 3 unknown RESOLVED — 2026-09-11 (read from source, no hardware needed)

The spec's headline risk was that a live WAV has no known length when the
header is written, and that `micro_wav` might reject a sentinel. **It does
not.** Read from the vendored decoder
(`.esphome/.espressif/.../esphome__micro-wav_0.2.0/src/wav_decoder.cpp`):

- The only header validation is `num_channels_ == 0 || sample_rate_ == 0`,
  plus `bits_per_sample_` divisibility. **`data_chunk_size_` is not
  validated at all** — it is copied straight into `data_bytes_remaining_`
  (`uint32_t`) and counted down.
- Decoding stops when the *input* runs out, independently of that counter
  (`count = min(input_avail, output_avail, data_avail)`).

So: declare a sentinel data size, stream, and close the connection when the
answer ends. **No FLAC encoder and no buffer-then-serve required** — both
fallbacks in the original risk list are unnecessary.

Two real constraints surfaced from `audio/audio_reader.cpp` instead, and
they shape the bridge endpoint more than the framing does:

- **The reader times out on silence.** It fails the stream when
  `millis() - last_data_read_ms_ > MAX_FETCHING_HEADER_ATTEMPTS *
  CONNECTION_TIMEOUT_MS` = **6 x 5000ms = 30s** since the last *successful*
  read. So `/response` cannot simply hold an idle connection open waiting
  for Hermes to start speaking — it must emit the WAV header promptly and
  must not stall more than ~30s at any point.
- **A zero-length read is treated as a timeout, not EOF.** End of stream is
  detected via `esp_http_client_is_complete_data_received()`, so the bridge
  must terminate the body definitively (correct chunked terminator, or
  close), or the Puck will keep waiting.

## Tasks 3-5 and 7 verification — 2026-09-11

All hardware-verified. Tests were driven by speaking to the device through
the host's own speakers, since nobody was in the room.

**The Puck speaks the answer itself:**

```
Detected language 'en' with probability 0.71
puck bridge turn complete: 27 audio chunks spoken in 4.7s
puck bridge response streamed 163584 bytes of PCM
```

`audio_http` only finishes once it has consumed the whole body, so the byte
count is evidence the device decoded and played it. **Not yet confirmed by
ear** -- a muted or misrouted output would look identical in the log.

### Task 7 changed shape: acknowledge at capture CLOSE, not at the wake

The spec called for acknowledging on `on_wake_word_detected`. Measured on
hardware, that destroys the capture. Same spoken question:

| | at wake | at close |
|---|---|---|
| captured | 4.2s | 2.8s |
| speech kept | **0.0s** | 1.7s |
| transcript | **EMPTY** (0.57) | good (0.75) |

The XMOS AEC suppresses the microphone while the speaker is active, so VAD
sees silence, the window closes early, and the question lands inside the
suppressed period. **Playing anything while recording costs the
recording.** Moved to the close of the capture window -- which also says
something more useful: not "I heard a wake word" but "I have your
question".

This is the echo risk the spec listed, and it bit in a way not predicted:
the danger was framed as self-triggering and capture pollution, but the
real cost was AEC *suppression* silently eating the question.

### Two defects found only by testing on hardware

- **The device waited for audio that was never coming.** It fetches
  `/response` as soon as its upload is confirmed, before the bridge knows
  whether the capture held a question. An empty transcript runs no turn.
  Measured 15s -> 0.04s once the bridge declared intent explicitly.
- **The device opened TWO connections for one response** (ports
  52539/52540). Two readers pop from the same queue, so the answer would be
  split between them and both play garbage -- observed as two resets and no
  delivery at all despite the turn producing 27 chunks. `/response` is now
  single-consumer, refusing a second fetch with 409.

## Risks & Open Questions

- **Streaming WAV length is the main unknown.** A live WAV has no known length at header time. Either emit a header with a sentinel/oversized data length and rely on `micro_wav`'s tolerance, or use chunked transfer encoding. **Prototype this first** — if `micro_wav` rejects it, fall back to FLAC (the stock config's own choice for announcements, and the least CPU-intensive per its comment) or buffer-then-serve at the cost of latency.
- **Acoustic echo / self-triggering.** The Puck will now hear its own voice. `micro_wake_word` could self-trigger on Missy speaking, and `wake_capture` could capture playback. The XMOS XU316's AEC is precisely why this board was chosen, but this is unproven here. Mitigation if needed: gate wake detection during playback.
- **Bus split regression risk.** Task 1 touches the input path that story 3 spent many sessions stabilising. Wake detection must be re-verified after the split, not assumed.
- **Latency budget.** `audio_http`'s 50KB default buffer is ~1.5s at 32 KB/s before first sound. Tune `buffer_size` against real speech; smaller buffers start faster but underrun sooner.

## Verification

Hardware test, bridge and serial logs attached: wake the Puck, ask a question that takes several seconds to answer, and confirm (a) the answer is audible from the Puck with no stutter, (b) the Mac stays silent, (c) `micro_wake_word` still detects a following wake, and (d) no `Stopping wake word detection`, heap-watermark reboot, or upload abandonment appears in the serial log.

## Flashing hazard (applies to every hardware task here)

`esphome compile` can emit a transient `Failed to create factory.bin`; `esphome upload --device` will then silently flash the **stale** `firmware.factory.bin` from an earlier build while still reporting `Successfully uploaded program`. Observed 2026-09-10 — an entire test round measured hour-old firmware. Check `.esphome/build/respeaker-lite/build/firmware.factory.bin`'s mtime before trusting a serial flash.

## Review Findings

Review scope: the committed P-2 slice from baseline
`be3958fec3554abaae019fc22412eb0fbb8e4437` through `HEAD`, excluding the
uncommitted P-1 worktree changes. The focused bridge and firmware tests passed
(`78 passed`) in the current worktree, and the scoped diff has no whitespace
errors. That test result is not yet a clean-checkout result: the current
worktree supplies the P-1 status WAVs and related test changes that are absent
from the reviewed commit. The Edge-Case Hunter timed out without a report;
Blind Hunter, Verification Gap, and Acceptance Auditor returned findings.

#### Decision needed

- [x] [Review][Decision] Choose the operational playback mode [puck_bridge/server.py:37-61,107-129; `spec-1-p-2`: Tasks 4-5] — selected (a): make device playback the default and expose host playback as an explicit fallback. Applied in `server.py` with `--host-playback` as the explicit escape hatch; the Puck launch instructions now exercise the default device path.
- [x] [Review][Decision] Decide whether the query-string response credential is acceptable for this pilot [puck_bridge/receiver.py:245-258; firmware/respeaker-lite/respeaker-lite.yaml:692-707] — selected (a): accept the documented hardcoded home-LAN pilot trade-off. Applied with headerless query-token coverage, wrong-token rejection coverage, redacted request logging, and an explicit LAN/proxy exposure warning; a future credential system remains outside P-2.
- [x] [Review][Decision] Reconcile the Task 7 acknowledgement contract [spec-1-p-2-status-and-response-audio-delivery.md:79,162-182] — selected (b): retain acknowledgement at wake time and redesign the audio/AEC timing so it no longer truncates capture. The current capture-close acknowledgement is not an acceptable implementation of the frozen acceptance; the patch must make the immediate acknowledgement and usable question capture coexist, with hardware verification required.

#### Patch findings

- [x] [Review][Patch] Bind each response stream to the capture that produced it [puck_bridge/turn.py:192-200,387-394; puck_bridge/server.py:126-129] — `make_handler()` now sets the runner sequence before submitting the transcript, so `ResponseStream.begin()` and the stale-fetch guard retain the upload identity. The receiver integration and stale-fetch tests cover the boundary.
- [x] [Review][Patch] Do not start a second Hermes turn when the response stream is busy [puck_bridge/receiver.py:448-467] — a failed `expect(seq)` now drops the completed capture before transcription and returns 503, preserving the active response. The status deliberately avoids 4xx so the firmware identity gate does not misclassify temporary capacity pressure as credential rejection.
- [x] [Review][Patch] Preserve PCM across Hermes audio segments [puck_bridge/turn.py:381-400; puck_bridge/response.py:159-183] — `ResponseStream.begin()` is now idempotent for the same sequence and format, while `expect()` remains the new-response reset. The runner test covers two Hermes segments in one Puck response.
- [x] [Review][Patch] Treat `audio_abort` and `turn_interrupted` as unsuccessful delivery [puck_bridge/turn.py:376-386] — both terminal event types now return failure after the normal stream cleanup; parametrized tests cover each one.
- [x] [Review][Patch] Make the first-audio deadline mean first audio, not first arbitrary event [puck_bridge/turn.py:358-428] — activity/tool events no longer switch to the mid-response stall budget; the switch occurs at audio start or non-empty file data. The long-answer fixture now runs for more than ten seconds, and a focused activity-before-audio test protects the distinction.
- [x] [Review][Patch] Align the response endpoint's format wait with the turn deadline [puck_bridge/response.py:34-42; tests/test_puck_bridge.py] — the response format budget now shares the runner's 20-second value, with a test preventing drift.
- [x] [Review][Patch] Bound a stalled response socket [puck_bridge/receiver.py:69-74,346-386] — response connections now have a bounded write timeout, catch socket timeout/reset failures, restore the prior timeout, and always release the reader; the loopback test proves a non-reading client cannot retain the slot.
- [x] [Review][Patch] Surface host playback failure after the player closes [puck_bridge/turn.py:346-351,509-520] — the runner tracks whether this turn started host playback and inspects `.failure` after normal close, returning failure when the output device rejected it. A failing-player test covers the path.
- [x] [Review][Patch] Ship the firmware assets referenced by the reviewed configuration [firmware/respeaker-lite/respeaker-lite.yaml:441-450; tests/test_puck_firmware.py:20-29] — the reproducible generator now creates the refusal and short acknowledgement WAVs in the current worktree, and the asset test validates both; these files still need to be included in the eventual P-1/P-2 delivery commit because they were absent from the review baseline.
- [x] [Review][Patch] Make the documented speaker-safety values and live configuration agree [firmware/respeaker-lite/respeaker-lite.yaml:466-470,493-494] — the active values now match the documented `0.25` initial volume and `0.80` ceiling, with a YAML invariant test.
- [x] [Review][Patch] Add missing boundary coverage [tests/test_puck_bridge.py; tests/test_puck_firmware.py] — added the device-default/host-fallback parser test, query-token acceptance/rejection, sequence handoff, multi-segment and abort tests, a real >10-second turn fixture, the firmware response URL invariant, and the short acknowledgement-duration invariant.
- [x] [Review][Patch] Keep the wake acknowledgement at wake time without overlapping capture [firmware/respeaker-lite/pcm_capture.h; firmware/respeaker-lite/respeaker-lite.yaml; firmware/respeaker-lite/tools/generate_sounds.sh] — the automation now prepares the authorized wake, plays an 80ms acknowledgement, waits for the local tone hand-off, and then opens the capture; the close-time acknowledgement path is removed. Source-level tests protect the ordering. Physical verification remains required to prove that the question is no longer lost to XMOS AEC suppression.

Host verification is complete: the focused bridge/firmware set passed 78 tests
and the full suite passed 1025 tests (one existing websockets deprecation
warning). The post-patch hardware gate passed on 2026-09-12:

- `venv-firmware/bin/esphome compile firmware/respeaker-lite/respeaker-lite.yaml`
  succeeded with ESPHome 2026.8.2; the image was 1,932,163 bytes (49.1% of
  flash and 33.8% of RAM) and carried build timestamp `2026-09-12 13:59:18
  -0500`.
- OTA upload to `respeaker-lite.local` succeeded in 17.96 seconds. Boot logs
  reported the same build timestamp, `AUTHORIZED`, a connected Wi-Fi/API
  session, and no crash loop or reboot marker.
- A wake detected as `Hey Missy` produced the acknowledgement before
  `wake capture started`; the following capture delivered 847,960 bytes in 53
  chunks. The bridge transcribed a 6.625-second capture and completed a real
  Hermes turn with 33 audio chunks / 208,640 PCM bytes. The Puck received HTTP
  200, finished the response reader and decoder, resumed wake detection, and
  returned the media player to `IDLE`.
- A subsequent post-playback wake was detected, acknowledged, captured, and
  uploaded successfully, proving that the response path returned the device
  to a reusable wake state.

The run emitted the known ring-buffer reset and long-upload interval warnings
while capture/upload was active, but no heap-watermark reboot, upload
abandonment, or crash occurred. P-2 is closed.

#### Deferred

- [x] [Review][Defer] Bound the response queue and define backpressure/underrun policy [puck_bridge/response.py:168-173,255-290] — the producer can append without a memory limit while the consumer is paced by the device. This belongs with the already-promoted P-5 streamed-response underrun/pacing slice, not as an isolated queue tweak in P-2.
- [x] [Review][Defer] Add direct `server.main()` lifecycle coverage — consolidated into the existing P-6 bridge shutdown and entry-point coverage item in `planning-artifacts/epics.md` and `deferred-work.md`.
- [x] [Review][Defer] Authenticate the pre-existing firmware web controls — the unauthenticated port-80 controls predate this P-2 slice and are outside its response-audio boundary; keep them separate from the response-token decision above.
- [x] [Review][Defer] Add the ESPHome schema/compile gate — consolidated into the existing P-1 firmware validation gap; the configured firmware toolchain is not installed on this host.

#### Rejected

- `false` — Destructive response-queue pops are not a P-2 defect by themselves: the bridge must not replay a response after an uncertain device connection, and automatic replay would violate the no-replay safety rule. The bounded-memory/backpressure concern is deferred to P-5.
- `false` — The boot-order concern that wake capture can run before identity setup is not demonstrated: `puck_identity::state` starts `UNAUTHORIZED`, and the capture start path is gated by `may_capture()`. An immediate wake could be missed, but it cannot capture while the identity gate is closed.
- `false` — The alleged mid-capture identity revocation race is unreachable in the reviewed wiring: identity state changes on upload responses after capture has closed, and no concurrent revocation path was found.
- `false` — `speaker_tone.h` is an unused helper scaffold, but no behavior or build failure follows from it; removing or wiring it is cleanup, not a P-2 review correction.
