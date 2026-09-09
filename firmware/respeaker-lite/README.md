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

This story's `respeaker-lite.yaml` is intentionally minimal — WiFi, API, and
board/platform sections only, adapted from Seeed's own reSpeaker Lite
ESPHome reference
([`formatBCE/Respeaker-Lite-ESPHome-integration`](https://github.com/formatBCE/Respeaker-Lite-ESPHome-integration),
credited from Seeed's own wiki tutorial for this board). No wake-word model,
identity/credential logic, or audio-streaming-to-host logic is included yet —
those land in later stories (3, 4, 5).

---

## Build & Flashing

ESPHome is an optional dependency extra (`firmware`), kept out of the base
TUI install per `AGENTS.md`'s convention of not dragging hardware toolchains
into a terminal-only install:

```bash
# from the repo root
venv/bin/pip install -e ".[firmware]"
```

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
venv/bin/esphome compile firmware/respeaker-lite/respeaker-lite.yaml
```

Flash (device confirmed as the reSpeaker Lite at this port):

```bash
venv/bin/esphome upload firmware/respeaker-lite/respeaker-lite.yaml --device /dev/cu.usbmodem101
```

Watch logs over the same serial port to confirm boot/WiFi status:

```bash
venv/bin/esphome logs firmware/respeaker-lite/respeaker-lite.yaml --device /dev/cu.usbmodem101
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
