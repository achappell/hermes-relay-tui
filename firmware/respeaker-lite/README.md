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
   currently unverified** — see Known Limitation below; do not assume it
   passes without running it yourself.

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
above). **Spoken-word detection was attempted 4 times (with a human
physically present, "hey jarvis" spoken near the device, live log capture)
across two builds — the base config and one with an added `vad:` block
(also present in Seeed's reference tutorial, initially missing here). Every
attempt produced zero detections and zero audio-pipeline log activity of
any kind, even at maximum log verbosity.** This is inconclusive rather than
a confirmed failure — some ESPHome audio components stay silent in their
processing loop by design, and there's no confirmed-working baseline of
this exact config on this exact board to compare against. Real
possibilities: a mic wiring/gain issue specific to this board's assembly, a
remaining software gap, or verbal-test methodology defeating a working
pipeline. Resolving this needs either deliberate audio-level
instrumentation or physical hardware inspection — tracked as this story's
one open follow-up, not silently declared working. See the story file's
Implementation Notes for the full attempt-by-attempt record.

**If you raise `logger: level:` above `DEBUG` while debugging this:**
`VERY_VERBOSE` logs the configured WiFi password in cleartext (found and
reverted during this story's own debugging). Never leave the device
flashed at that log level with real household credentials in
`secrets.yaml` — drop back to `DEBUG` before shipping any build.
