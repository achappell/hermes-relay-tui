# reSpeaker Lite Firmware (Puck)

Firmware baseline for the **Seeed reSpeaker Lite** — the Puck prototype hardware
for **Hermes** — combining the **XMOS XU316** onboard AI Sound/Audio DSP
(dual-mic array, echo cancellation, beamforming, noise suppression) with a
**Seeed XIAO ESP32-S3** host MCU.

---

## Hardware Specifications

| Component | Specification | Description |
|---|---|---|
| **DSP** | XMOS XU316 | Dual-mic array front-end: AEC, beamforming, noise suppression |
| **Host MCU** | XIAO ESP32-S3 | Dual-core Xtensa LX7, WiFi/BT, runs this ESPHome firmware |
| **Audio interface** | I2S / USB | I2S firmware variant used here; USB variant makes the board act as a plain USB sound card instead |
| **XMOS firmware variant** | I2S, "optimized for micro wake word" | ch0 fits ASR, ch1 fits `micro_wake_word` — see Seeed's `respeaker/ReSpeaker_Lite` repo |

---

## Toolchain Choice: ESPHome

Per `_bmad-output/specs/spec-hermes-relay-tui/SPEC.md`'s story-1 decision, the
Puck's on-device wake-word engine is ESPHome's `micro_wake_word` component,
following Seeed's own reSpeaker Lite firmware reference for this exact board.
`micro_wake_word` is tied to ESPHome's own YAML-to-C++ build pipeline (which
wraps ESP-IDF internally) rather than being usable as a standalone ESP-IDF
component. That makes this an ESPHome YAML project, not a
`platformio.ini`/`CMakeLists.txt` project like
[`firmware/esp32-s3-touch-lcd-7`](../esp32-s3-touch-lcd-7) — the two firmware
targets sit on incompatible build systems and different peripherals, so no
source-level sharing between them is realistic. What carries over from that
target is organizational convention only: a dedicated subdirectory per
hardware target, board-specific config kept out of committed secrets, and a
README documenting pinout/specs/build commands.

Story 2's `respeaker-lite.yaml` was intentionally minimal — WiFi, API, and
board/platform sections only, adapted from Seeed's own reSpeaker Lite
ESPHome reference
([`formatBCE/Respeaker-Lite-ESPHome-integration`](https://github.com/formatBCE/Respeaker-Lite-ESPHome-integration),
credited from Seeed's own wiki tutorial for this board,
[wiki.seeedstudio.com/respeaker_lite_ha/](https://wiki.seeedstudio.com/respeaker_lite_ha/)).
Story 3 (this one) adds the I2S audio path (`i2s_audio:`, `microphone:`) and
an on-device `micro_wake_word:` block on top of that base, following the
same reference. Identity/credential logic and audio-streaming-to-host logic
still aren't included — those land in stories 4 and 5.

---

## Wake Phrase (Story 3)

This build answers to **`hey_jarvis`** — a pretrained community model
bundled with ESPHome's `micro_wake_word` component, requiring zero
training. **It does not answer to "hey hermes."** The previous
openWakeWord-style `wakewords/hey_hermes.onnx` asset does not carry over:
`micro_wake_word` uses its own model format (the `OHF-Voice/micro-wake-word`
TensorFlow pipeline), so retraining "hey hermes" for this engine is real,
separate follow-on work — Piper TTS synthesis plus hours of
training-with-iteration, per Story 1's findings — not a config change. It is
tracked separately and intentionally not folded into this story, whose goal
was proving the on-device audio + wake-word pipeline works on this hardware
at all.

The bundled internal `stop` model is also enabled (kept `internal: true` so
it isn't independently exposed as a toggleable Home Assistant entity), per
Seeed's own reference integration.

---

## Build & Flashing

ESPHome lives in its own dedicated venv (`venv-firmware/`, Python 3.12),
separate from the repo's main Python 3.14 `venv/`. Two independent reasons:
this repo's own `pyproject.toml` keeps hardware toolchains out of the base
TUI install per `AGENTS.md`'s convention, and ESPHome's dependency stack
(e.g. `click`) has already shown version conflicts against
`requirements-dev.txt` when both share one venv.

```bash
# from the repo root
/path/to/python3.12 -m venv venv-firmware
venv-firmware/bin/pip install "esphome>=2025.9.0"
```

That version constraint matches `pyproject.toml`'s `firmware` extra —
keep the two in sync rather than letting them drift. `pip install -e
".[firmware]"` does *not* work here: the main project's `requires-python`
is pinned to `>=3.14,<3.15`, so editable-installing the whole local
package fails immediately under this venv's Python 3.12. Installing
`esphome` directly, without touching the local project, sidesteps that.

Secrets (WiFi credentials, API encryption key, OTA password) are never
committed, matching the `-D HERMES_DISPLAY_WS_URI` pattern in
`firmware/esp32-s3-touch-lcd-7/platformio.ini` of keeping installation-specific
values out of version control:

```bash
cd firmware/respeaker-lite
cp secrets.yaml.example secrets.yaml
# edit secrets.yaml with real WiFi/API/OTA values
```

Compile:

```bash
venv-firmware/bin/esphome compile firmware/respeaker-lite/respeaker-lite.yaml
```

Flash (device confirmed as the reSpeaker Lite at this port):

```bash
venv-firmware/bin/esphome upload firmware/respeaker-lite/respeaker-lite.yaml --device /dev/cu.usbmodem101
```

Watch logs over the same serial port to confirm boot/WiFi status:

```bash
venv-firmware/bin/esphome logs firmware/respeaker-lite/respeaker-lite.yaml --device /dev/cu.usbmodem101
```

---

## Validation Scenario

1. **Compile:** `esphome compile` completes without error and produces
   `firmware.factory.bin` / `firmware.ota.bin` under
   `.esphome/build/respeaker-lite/build/`.
2. **Flash:** `esphome upload --device /dev/cu.usbmodem101` completes and the
   device resets.
3. **Boot check:** serial logs show the ESPHome logger banner and a steady
   WiFi connect/retry state machine — no `Guru Meditation`, `abort()`, or
   repeated `rst:` boot markers, which would indicate a crash loop.
4. **WiFi/API check:** once `secrets.yaml` has the real household WiFi
   credentials, the device should join WiFi and become visible to Home
   Assistant/ESPHome via mDNS (`respeaker-lite.local`) and the `api:`
   component.
5. **Wake-word check (Story 3):** with `esphome logs` attached, speak
   "hey jarvis" clearly near the physical device. A `micro_wake_word`
   detection log line (wake word id `hey_jarvis`) should appear shortly
   after — this is the actual on-hardware proof that the I2S audio path and
   wake engine work, not just that the firmware compiles. **This step is
   now verified working** (session 17) — see Known Limitation below for
   the full resolution.

## Known Limitation

This story's `secrets.yaml` on the flashed device currently ships with
placeholder WiFi credentials (`placeholder-ssid`), since the actual household
WiFi credentials are not present in this repo/environment. The device boots
cleanly and retries WiFi indefinitely without crash-looping, proving the
build target and hardware are real, but it will not join the household
network or come up on the ESPHome API until `secrets.yaml` is updated with
real credentials and the device is reflashed (or the WiFi credentials are
changed via ESPHome's Improv/BLE provisioning if enabled in a future
iteration).

**Two build-time issues were found and resolved while bringing up
`micro_wake_word` (Story 3), both documented in full in the story file's
Implementation Notes:**

1. Mainline ESPHome's `micro_wake_word` requires a literal 16kHz microphone
   source and cannot resample; the XU316 only emits 48kHz/32-bit I2S. Fixed
   by accepting the same forked, patched `i2s_audio` component
   (`formatBCE/esphome@respeaker_microphone`, via `external_components:`)
   that both cited reference projects use — a deliberate, human-approved
   trust decision to pull third-party code at compile time, not an
   oversight.
2. With that fixed, `esphome compile` began segfaulting deterministically
   inside ESP-IDF toolchain subprocess checks. Root cause: `micro_wake_word`
   makes a live HTTPS call in-process (checking its two models for updates)
   immediately before ESPHome forks a subprocess — a known macOS hazard
   where a TLS handshake touches `Security.framework`/`trustd` in a way
   that doesn't survive `fork()`. Not a Python-version issue (reproduced
   identically under both 3.14 and 3.12). Fixed by vendoring both wake-word
   models locally (`wake_models/{hey_jarvis,stop}.{json,tflite}`) instead of
   referencing them by shorthand name/URL — local paths skip the
   update-check HTTPS call entirely.

Both compile and flash are now verified working (see Validation Scenario
above).

**A third, more fundamental issue was found in a follow-up session and is
now fixed:** `micro_wake_word` never starts listening on its own.
`MicroWakeWord::setup()` never calls `start()`, and its own audio callback
explicitly drops all data while stopped — without a `voice_assistant:`
component (which normally issues the start call) or an explicit action of
our own, the engine sat permanently in `STOPPED`. This fully explained
every "zero activity" symptom from the first debugging session — it was
never about sample rate, gain, or VAD. Fixed with `esphome: on_boot: then:
[micro_wake_word.start]` at `priority: -100` (must run after all
components finish `setup()`, or it fails with "hasn't been setup yet"). A
permanent amplitude diagnostic (`mic_diag` log tag, independent of
`micro_wake_word`) now confirms the pipeline is genuinely alive — baseline
room noise reads ~5–90M, speech spikes it to 1–2 billion.

**Spoken-word detection is still unconfirmed even with that fix in
place.** Two more live attempts at "hey jarvis," plus one at the bundled
`stop` model (a different phrase with a far more lenient threshold, used
specifically to rule out "hey jarvis is just a hard accent match") — all
three produced clear amplitude spikes but zero detection log lines. VAD
gating and the fork's decimation logic were both checked by reading the
actual source and ruled out as the sole explanation (the fork does perform
real, if crude/unfiltered, 48kHz→16kHz decimation — not just a metadata
relabel, an earlier conclusion in this file that was wrong and has been
corrected). Two attempts to capture raw audio for a human to actually
listen to both crash-looped the device (tripping ESPHome's Safe Mode
protection) and were fully reverted — **do not repeat either approach**
(growing a buffer inside the microphone's own real-time callback, or a
PSRAM-backed fixed buffer resized in `on_boot`) without first
understanding why they aborted. See the story file's Implementation Notes
for the complete, attempt-by-attempt record. Resolving this remains this
story's one open follow-up, not silently declared working.

**Follow-up session 3 ruled out two more hypotheses with direct hardware
evidence, still unresolved:** split the amplitude diagnostic per channel
and confirmed `ch0`/`ch1` are byte-for-byte identical on every sample —
`channels: 1` is not silently reading a dead channel. Also formed and
tested a gain-clipping hypothesis (`gain_factor: 4` overflowing the Q25
fixed-point range on loud speech, confirmed by the actual math on an
833M-amplitude live sample) by dropping gain to 1 and retesting with
un-clipped, still-loud speech — still zero detections, so that's ruled out
too and gain is back at 4. The wake-word engine is confirmed alive
(`is_running: true` throughout) and receiving real, matching-channel,
un-clipped, genuinely loud audio, and still never fires. See the story
file's Implementation Notes for the full record. The most promising
unblocked next step is still getting an actual PCM recording off the
device for a human to listen to, via a safer redesign (queue from
`on_data` to a separate `interval:`-driven consumer) than the two crashing
attempts above — not yet attempted.

**Follow-up session 4 built that safer capture and actually looked at the
audio:** a single `heap_caps_malloc` PSRAM buffer (no vector, no resize),
filled by a bounded `memcpy` in the real-time callback and drained via
base64 dump from a slow `interval:` tick. Crash-free. Reconstructing and
spectrogram-inspecting the captured PCM showed real, syllable-timed speech
energy, but broadband and static across the spectrum instead of the
smoothly-sweeping formant bands real speech should show — the signature of
severe aliasing from the fork's unfiltered 48kHz→16kHz decimation.

**Follow-up session 5 fixed that decimation** — vendored the `i2s_audio`
component locally (`components/i2s_audio/`, no longer pulled from git) and
replaced the nearest-sample-drop with a 3-tap boxcar anti-aliasing filter.
Spectrogram comparison confirmed the fix works as intended (the static
comb-banding is gone, replaced by a natural-looking low-frequency-weighted
decay) — but **wake-word detection still doesn't fire**, even with
confirmed loud, sustained, correctly-filtered speech reaching the model.
Aliasing was very likely real and worth fixing, but not the sole cause.
See the story file's Implementation Notes for the full record and the
concrete next step (a steeper filter, or a reference-recording
comparison).

**Follow-up session 6 tried the steeper filter** — a proper 31-tap
windowed-sinc FIR replacing the boxcar, verified via spectrogram to
further clean up the signal. Tested against the loudest, most sustained
speech of the whole investigation (confirmed amplitude peaks up to 1.45-
1.6 billion, near the hardware's clipping ceiling) via live monitoring,
not just the fixed capture window. **Still zero detections.** This is no
longer plausibly an audio-quality problem — three independently-tested
audio-pipeline fixes (gain, boxcar filter, proper FIR filter) have all
failed to produce a single detection against audio that is now about as
clean and loud as this hardware can produce. Per the project's own
debugging discipline, three failed fix attempts means stop tuning the
front end and question the architecture instead. Next places to look:
whether the vendored `hey_jarvis`/`stop` TFLite model files are intact and
version-compatible with this ESPHome release, and the TFLite
feature-extraction frontend inside `micro_wake_word.cpp` itself (never
directly inspected across any session so far). See the story file.

**Follow-up session 7 checked both.** Model files: fetched fresh from
upstream and diffed by SHA-256 -- byte-identical, not corrupted. The
inference pipeline: added a raw-probability diagnostic (never logged
before, only a binary detected/not-detected outcome) and found `hey_jarvis`
flatlined at a literal 0/255 across a full loud-speech test, while VAD
(fed the *same shared audio features*) responded normally. A second,
independently-trained wake-word model (`okay_nabu`) showed the same
near-zero flatline, ruling out a single corrupted model. Tensor
shape/stride/arena size for both models checked and came back completely
normal. **Net conclusion: this is no longer explainable by the audio
pipeline, model files, or tensor structure — something is different
between how `WakeWordModel`-class instances process the shared features
and how the lenient VAD model does**, most likely a level/dynamic-range
mismatch between this hardware's audio and what these strict-threshold
pretrained models expect. Also found and fixed a real, previously
undocumented bug along the way: only the first model in `models:` is
enabled by default (`default_enabled = i == 0` in ESPHome's own
`micro_wake_word/__init__.py`) — anything listed after it silently never
runs unless explicitly enabled. See the story file for the full record and
the next concrete step (logging the actual feature vector, not just the
model's output).

**Important caveat, found right after that (session 8):** the device's
test room changed mid-session (moved rooms), and a later attempted
silence-then-one-utterance test showed no quiet baseline at all —
amplitude stayed pinned at 150M-2.1B continuously, even during intended
silence, a dramatic change from the ~5-20M ambient baseline earlier in the
same session. **Session 7's "both wake-word models flatline while VAD
responds" finding was measured after this room change**, so it may
reflect a genuinely noisy test environment rather than a deep code/model
bug — these strict-threshold pretrained models need a real quiet-vs-speech
contrast that a persistently loud room may never provide, while VAD's much
more lenient threshold would still respond to any activity regardless. The
anti-aliasing fix and the default-disabled-model bug are real, verified
fixes independent of this; only the *interpretation* of session 7's
flatline finding is now uncertain.

**Session 9 redid it properly and got the sharpest result of the whole
investigation.** Confirmed a genuinely quiet baseline directly, then a
clean isolated-utterance retest reproduced session 7's flatline finding —
ruling the room-noise theory back out. Tightened the diagnostics 10x
(100ms instead of 1s) to see a full spoken word instead of one lucky
sample: **the feature generator works correctly** (mean visibly rose from
~-100 to +6.2 during real speech, a clearly well-formed feature vector,
not noise), but **the model's own probability output never moved off
0/255 through that same well-formed window.** The break is narrower now:
audio, model files, tensor shapes, and feature generation are all
confirmed correct — something specific to how the model's own weights
interpret otherwise-correct features is the remaining suspect (most
likely a representation mismatch like filterbank channel ordering, not
visible to a range/statistics check). Next step: diff this pipeline's
feature output against a reference Python implementation on identical
captured PCM. See the story file.

**Session 10 did exactly that, and it's decisive.** Built an independent
offline test harness (`pymicro-features` + `ai-edge-litert`, the same
underlying feature-extraction library and the actual `.tflite` model,
completely outside ESPHome) and reproduced the flat-zero result on real
captured Puck audio. Then ran a positive control — clean synthetic "Hey
Jarvis" TTS speech through the identical pipeline — which detected
correctly (probability climbed to 255, decisively over the 247 cutoff).
**This means every stage of the pipeline is now verified correct, and the
remaining problem is very likely the actual acoustic content the XU316's
onboard DSP produces** — not a fixable software bug in this repo. The two
real next steps are a genuinely different scope of work: training a
custom wake-word model on audio captured through this exact hardware (the
`microWakeWord` project explicitly supports this), or investigating
whether a different XMOS DSP firmware variant with less aggressive
processing is available for this board. See the story file for the full
record.

**Session 17 solved it. This conclusion was wrong** — not because the
reasoning at the time was unsound, but because it was never tested
against an actual known-working external reference, only validated
internally against this project's own pipeline. Two real findings:

1. **This unit's XMOS DSP firmware was version 1.0.8; the community
   reference this firmware is modeled on (`formatBCE/Respeaker-Lite-
   ESPHome-integration`) depends on 1.1.0.** Flashed the correct version
   via the `respeaker_lite:` component's DFU mechanism (now vendored at
   `components/respeaker_lite/`) — genuinely necessary, permanent, and
   worth keeping, but **on its own this did not fix detection.** A direct
   test immediately after (18 "hey jarvis" TTS plays against the upgraded
   firmware) still came back flat 0/255, VAD included.
2. **The actual cause: session 6's "proper" 31-tap windowed-sinc
   anti-aliasing FIR filter, not the naive decimation it replaced.**
   Built formatBCE's complete, faithful stock config side-by-side
   (`respeaker-lite-stock-test.yaml`, using their unmodified `i2s_audio`
   fork verbatim, vendored at `components_stock/`) and found `hey_jarvis`
   fires cleanly and repeatedly (255/255, cutoff 247) on real speech, with
   correct rejection of non-wake phrases and a real VAD curve (climbing
   to 200+/255 during speech, baseline ~1-14 otherwise) — the first time
   in this story's entire history any of that worked. Reverted
   `components/i2s_audio`'s decimation back to the naive nearest-sample-
   drop (no filtering) to confirm, then re-verified on the actual
   production `respeaker-lite.yaml`: same clean 255/255 detections.
   **The mathematically "more correct" anti-aliasing filter was
   measurably worse for this specific pretrained model** — most likely
   because its steeper cutoff removed spectral content (e.g. 7-8kHz
   energy) the model actually relies on, not because the naive decimation
   was somehow fine after all. Sessions 4-6's aliasing diagnosis (real,
   confirmed by spectrogram) was correct; the fix for it was the actual
   bug.

**Wake-word detection works on this hardware with the pretrained
`hey_jarvis` model, using formatBCE's stock XMOS firmware (1.1.0) and
formatBCE's stock (unfiltered) decimation.** The custom-training work
from steps 1-3 (data collection pipeline, 30-clip dataset, first trained
model) remains fully working and banked, but is no longer the only path
to on-device detection — it's now optional future work for improving
robustness/vocabulary, not a requirement. See the story file's session 17
entries for the complete investigation, including the real environment
bugs found and fixed along the way (an ESP-IDF toolchain segfault from a
redundant `requests` HTTP round-trip, and a null-pointer crash in the DFU
version-check code).

**If you raise `logger: level:` above `DEBUG` while debugging this:**
`VERY_VERBOSE` logs the configured WiFi password in cleartext (found and
reverted during this story's own debugging). Never leave the device
flashed at that log level with real household credentials in
`secrets.yaml` — drop back to `DEBUG` before shipping any build.

---

## Story 5: Wake-to-Upload and the Host Bridge

Story 3 got wake-word detection working; story 5 makes a validated wake
actually *do* something. `on_wake_word_detected:` (under `micro_wake_word:`)
now starts a bounded, VAD-gated, single-shot capture into a dedicated ~8s
PSRAM buffer (`pcm_capture::wake_capture`, in `pcm_capture.h`) — separate
from the pre-existing training-data capture buffer, which is unchanged.
A fast (100ms) `interval:` tick watches `micro_wake_word`'s own VAD state
(`id(mww).get_vad_state()`, already proven responsive by story 3's
`vad: probability_cutoff: 0.05`) and ends the capture window once VAD has
reported silence for 800ms — not a fixed timer. A slower (1s) `interval:`
tick then uploads the finished capture, chunked, over the same wire shape
`tools/receiver.py` already proved out for training data
(`POST /upload?seq=N&chunk=C&total=T`, 16KB chunk bodies) — reusing that
function's heap-watermark reboot circuit breaker, 2-consecutive-failure
abandonment, and 30ms inter-chunk delay unchanged. Unlike the training
pipeline's `upload_and_restart()`, this capture does **not** re-arm itself
when the upload finishes — one wake, one upload, then it waits for the next
`on_wake_word_detected` trigger. No continuous rolling capture.

Each chunk POST carries an `X-Puck-Token` header — the hardcoded shared
token (`puck_device_token` in `secrets.yaml`) standing in for Story 4's
still-blocked real per-device credential system (Epic 3's
`DEVICE-01`/`02`/`06` have not landed). **This is not a security boundary.**
Treat it like a shared household WiFi password, not an individually
revocable credential — Story 4 replaces it once it exists.

### The host bridge (`puck_bridge/`)

The upload's landing point is a new, standalone Python package,
`puck_bridge/`, at the repo root (not under `firmware/`) — deliberately its
own process, not wired into `app.py` or `home_display/appliance.py`, so it
cannot regress either existing front end:

- `puck_bridge/receiver.py` — the chunked-upload HTTP/1.1 receiver
  (`protocol_version = "HTTP/1.1"`, matching `tools/receiver.py`'s own
  documented reason: ESP-IDF's `http_request` component depends on
  connection reuse across chunks). Checks the `X-Puck-Token` header before
  touching any capture state (fail closed — a missing or wrong token never
  produces a turn, even a partial one), reassembles chunks per `seq`, then
  converts the raw stereo/32-bit/16kHz capture into a mono 16kHz WAV using
  the exact Q31→Q25→gain→16-bit conversion already validated in
  `tools/label_captures.py`'s `process_frame_sample()`, and calls
  `voice.py:transcribe()` unchanged.
- `puck_bridge/turn.py` — `TurnRunner`, which directly constructs
  `handsfree.HandsFreeCoordinator` (not `build_hands_free()`, which
  unconditionally builds a local wake-word engine this pipeline doesn't
  need — the Puck's own on-device wake already decided this moment
  happened) against a real `session.py:SessionProtocol`, and plays the
  response on **this host machine's own speakers** via `audio.PCMPlayer`
  (no Puck-side response playback yet — tracked separately, see the
  friction log's 2026-09-09 entry, candidate `PUCK-01.7`).
- `puck_bridge/server.py` — wires the two together, resolving the Hermes
  session's connection settings through this project's existing
  `config.py` relay-profile machinery (same profiles the TUI and household
  appliance already use) and the new `PUCK_DEVICE_TOKEN` env-indirected
  token alongside them.

Run it with:

```bash
export PUCK_DEVICE_TOKEN=choose-a-shared-puck-token  # or set it in ~/.hermes-relay-tui/.env
venv/bin/python -m puck_bridge --port 8766
```

Raw Puck audio stays transient end-to-end (NFR3): the receiver's in-memory
chunk buffer for a capture is discarded as soon as it is reassembled, and
the WAV file is deleted immediately after transcription, success or
failure — no audio or transcript archive by default.

### Verification

```bash
venv/bin/pytest tests/test_puck_bridge.py -v
../../venv-firmware/bin/esphome compile firmware/respeaker-lite/respeaker-lite.yaml
```

The pytest suite covers the conversion math, the token/reassembly wire
protocol (over a real loopback socket), and the turn runner, all against
fakes — no live Hermes endpoint or hardware required. The actual acceptance
evidence for the wake-to-upload firmware path and the audible response
remains a live hardware smoke test: speak "hey jarvis" near the physical
Puck with the bridge running, and confirm one upload, a correct transcript,
one completed Hermes turn, and an audible response on the host speakers.

#### Live smoke test status (2026-09-10)

A live session against real hardware confirmed wake detection (`Hey
Jarvis`/`Okay Nabu`, 0.99+ confidence), VAD-gated capture start/end, and a
complete short capture reaching the bridge and being processed by
`faster-whisper`. It did **not** confirm a full round-trip turn: on the
tested device's WiFi signal (-89 to -90 dB), every capture large enough to
hold real speech stalled mid-upload (`esp_http_client_write()` aborting a
body write with no retry — see `pcm_capture.h`'s `UPLOAD_CHUNK_BYTES`
comment) before reaching the bridge. Also found and fixed two other
real, pre-existing issues along the way: a leftover story-3 serial-dump
diagnostic that was saturating the boot sequence for minutes (removed),
and `micro_wake_word` having no self-recovery once stopped (added a
watchdog in the existing 2s diagnostic `interval:`). Retest once the
device can sit with a stronger signal — see this story's spec
Implementation Notes and `deferred-work.md` for the full record.
