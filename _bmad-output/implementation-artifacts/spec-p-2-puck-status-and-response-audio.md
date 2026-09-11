---
title: 'P-2: Puck status and response audio'
type: 'feature'
created: '2026-09-10'
status: 'in-progress'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'be3958fec3554abaae019fc22412eb0fbb8e4437'
context:
  - '{project-root}/_bmad-output/planning-artifacts/prds/prd-hermes-relay-tui-2026-09-07/prd.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Identifier reconciliation

This spec was first drafted as `PUCK-01.7`, a candidate label proposed in `docs/friction-log.md`'s 2026-09-09 entry. That predates the **2026-09-10 surface decomposition** of Epic 1 in `epic-1-context.md`, which assigns the ReSpeaker Puck the story set `P-1`–`P-4` and gives **`P-2`** ownership of "status and response audio". `PUCK-01.7` is superseded and was never filed as a board item; this is `P-2`.

Scope note: `P-2` owns **both** halves of Puck audio output. The original `PUCK-01.7` framing covered only the response half. Status audio is added as task 7 below rather than left to be discovered later.

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
3. **Bridge: serve the response stream.** Add `GET /response?seq=N`, token-checked, that holds the connection until TTS begins and then streams WAV as chunks arrive. *Acceptance:* `curl` against it yields playable audio; a second request for the same `seq` does not duplicate a turn.
4. **Bridge: move playback off the Mac.** `_run_turn` publishes `audio_chunk` data to the response stream instead of `self._player`. *Acceptance:* answer is audible on the Puck, not the Mac.
5. **Firmware: trigger playback after upload.** On upload completion, call `media_player.play_media` with the templated `/response?seq=N` URL. *Acceptance:* full hands-free round trip — wake, speak, hear the answer from the Puck.
6. **Reshape the turn timeout.** `SEND_TIMEOUT_SECONDS = 10.0` currently bounds the *entire* turn including playback, so it fires on every real answer (observed 2026-09-10). Re-bound it to time-to-first-audio, with a separate stall guard for a mid-stream gap. Fix deferred item #36 in the same pass: a timeout must cancel the orphaned `_run_turn` coroutine, which can otherwise still write to a shared sink behind a later turn. *Acceptance:* a long answer completes; a genuinely unresponsive Hermes still returns to idle.

7. **Status audio: acknowledge the wake out loud.** Epic 1's UX rules require the Puck to stay *status-only* — "response text and transcript history do not belong on its TFT" — so on an audio-only device, status is carried by sound. `HOME-10` ("Wake acknowledgement and the silence before the answer") established this for the home-display appliance; the Puck has had no way to do it until task 1 gave it a speaker. Play a short acknowledgement on `on_wake_word_detected`, before capture completes, so a person knows they were heard during the several seconds before any answer arrives. *Acceptance:* a wake produces an audible acknowledgement within ~200ms; it does not leak into the captured audio (see the echo risk below) and does not delay or truncate capture.

## Constraints discovered during tasks 1-2 (binding on the rest)

- **Stream format must be declared before `start()`.** `AudioStreamInfo` defaults to `(16-bit, 1ch, 16000Hz)`. In secondary/slave mode the I2S speaker cannot reconfigure the bus and hard-rejects a mismatched **sample rate** with `Incompatible stream settings`. Bit depth may differ; sample rate may not. Everything therefore routes through the resampler to 48000.
- **`speaker->start()` is asynchronous and must not be busy-waited.** The state transition happens in the component's `loop()`, so blocking inside an automation lambda deadlocks it — loop never runs, state never advances. Use ESPHome's `delay:`, which yields.
- **Never write audio synchronously from the main loop.** Task 1's blocking tone helper starved the loop for 354ms, tripped `"a scheduled task took a long time"`, dropped WiFi mid-boot, and left `play_media` firing into a dead network. Playback belongs to `media_player`'s own task. This is the concrete reason this story does not hand-roll the audio path.
- **The resampler is wired but not yet exercised.** The task-2 test WAV was already 48kHz mono. Real 24kHz TTS will be its first genuine workout in task 3.

## Risks & Open Questions

- **Streaming WAV length is the main unknown.** A live WAV has no known length at header time. Either emit a header with a sentinel/oversized data length and rely on `micro_wav`'s tolerance, or use chunked transfer encoding. **Prototype this first** — if `micro_wav` rejects it, fall back to FLAC (the stock config's own choice for announcements, and the least CPU-intensive per its comment) or buffer-then-serve at the cost of latency.
- **Acoustic echo / self-triggering.** The Puck will now hear its own voice. `micro_wake_word` could self-trigger on Missy speaking, and `wake_capture` could capture playback. The XMOS XU316's AEC is precisely why this board was chosen, but this is unproven here. Mitigation if needed: gate wake detection during playback.
- **Bus split regression risk.** Task 1 touches the input path that story 3 spent many sessions stabilising. Wake detection must be re-verified after the split, not assumed.
- **Latency budget.** `audio_http`'s 50KB default buffer is ~1.5s at 32 KB/s before first sound. Tune `buffer_size` against real speech; smaller buffers start faster but underrun sooner.

## Verification

Hardware test, bridge and serial logs attached: wake the Puck, ask a question that takes several seconds to answer, and confirm (a) the answer is audible from the Puck with no stutter, (b) the Mac stays silent, (c) `micro_wake_word` still detects a following wake, and (d) no `Stopping wake word detection`, heap-watermark reboot, or upload abandonment appears in the serial log.

## Flashing hazard (applies to every hardware task here)

`esphome compile` can emit a transient `Failed to create factory.bin`; `esphome upload --device` will then silently flash the **stale** `firmware.factory.bin` from an earlier build while still reporting `Successfully uploaded program`. Observed 2026-09-10 — an entire test round measured hour-old firmware. Check `.esphome/build/respeaker-lite/build/firmware.factory.bin`'s mtime before trusting a serial flash.
