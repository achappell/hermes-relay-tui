# Authorized Touch microphone capture

This is a capture-only ESP32-C6 target pinned to **ESP-IDF 5.3.3**. The S3 owns Wi-Fi, display controls and the trusted local host socket. The C6 initializes no radio and never receives Home credentials. Response playback is unavailable in this slice; S3 drains response PCM and preserves native answer text.

## Build

Install the exact C6 toolchain in a separate environment:

```sh
git clone --branch v5.3.3 --depth 1 --recursive https://github.com/espressif/esp-idf.git ~/esp/esp-idf-v5.3.3
cd ~/esp/esp-idf-v5.3.3
./install.sh esp32c6
. ./export.sh
cd ~/Development/hermes-relay-tui/firmware/esp32-c6-audio
idf.py set-target esp32c6
idf.py build
```

The CMake gate rejects a different IDF version. Build success does not prove microphone wiring or physical capture. Flashing and real Home turns are separate bench operations.

Keep the existing S3 PlatformIO platform (`espressif32 ~6.6.0`). Create **ignored** `firmware/esp32-s3-touch-lcd-7/sdkconfig.installation` locally:

```ini
CONFIG_TOUCH_VOICE=y
CONFIG_TOUCH_WIFI_SSID="installation SSID"
CONFIG_TOUCH_WIFI_PASSWORD="installation password"
CONFIG_TOUCH_HOST_URI="ws://trusted-local-host:8765/state"
```

Do not put real values in tracked files, shell arguments, logs, screenshots or this guide. CMake layers `sdkconfig.defaults;sdkconfig.installation` when the installation file exists. On a fresh configuration, the explicit invocation is:

```sh
cd ~/Development/hermes-relay-tui/firmware/esp32-s3-touch-lcd-7
SDKCONFIG_DEFAULTS='sdkconfig.defaults;sdkconfig.installation' pio run -e esp32-s3-touch-lcd-7b
```

An existing generated `sdkconfig.esp32-s3-touch-lcd-7b` takes precedence over defaults. Preserve it privately before regenerating configuration when changing installation values; a clean object build alone does not reload defaults. Generated sdkconfig, managed components and build directories are ignored because they may contain private configuration. The hardware dependency manifest pins LVGL 8.3.11, matching the simulator. Both LVGL and application sources use `main/include/lv_conf.h` (PSRAM allocation and the ESP timer tick); `CONFIG_LV_CONF_SKIP` must remain disabled, and CMake rejects it when enabled. Existing generated configurations from a dependency-free build may need that option disabled explicitly. A Touch build without LVGL fails compilation. Turn `CONFIG_TOUCH_VOICE` off for legacy snapshot/action display mode. Simulator builds do not initialize network or audio hardware.

On the current arm64 development Mac, the existing PlatformIO CMake package is Intel-only. Verification used a task-local native CMake 3.30.5 package override with the unchanged S3 platform/IDF, and a private copy of the existing IDF package. A symlinked framework package produces duplicate object target errors in PlatformIO because CMake resolves source paths through the symlink. No shared PlatformIO package was replaced.

## Wiring and USB

| S3 7B | C6 / microphone | Purpose |
|---|---|---|
| GPIO43 TX | GPIO19 RX | 921600 baud 8N1, no flow control |
| GPIO44 RX | GPIO18 TX | COBS/CRC capture link |
| GPIO6 open-drain | C6 reset/EN | Released normally; one 100 ms low recovery pulse |
| Common ground | Common ground | Logic reference |
| — | GPIO0 → microphone BCLK | 1.024 MHz during capture |
| — | GPIO1 → microphone WS | 16 kHz, stereo wire slots |
| — | GPIO2 ← microphone SD | Left-slot Philips I²S |
| — | Microphone L/R → ground | Select left slot |
| — | GPIO3 → amplifier DIN | Held low; no playback initialization |

Use the selected **7B** display, not the alternate 7A pin/display variant. Select native USB on the board switch. EXIO5 (`USB_SEL`) initializes low and remains low through LCD/touch expander writes; UART pins 43/44 carry no application console output. Confirm native USB is reachable after power-on and display initialization before relying on it for recovery.

The [INMP441 datasheet](https://invensense.tdk.com/wp-content/uploads/2015/02/INMP441.pdf) defines signed 24-bit Philips I²S with a one-clock delay. The [IDF standard I²S driver](https://docs.espressif.com/projects/esp-idf/en/v5.3.3/esp32c6/api-reference/peripherals/i2s.html) is configured for two 32-bit slots. The left sample occupies bits 31..8; the conversion takes bits 31..16 directly into signed-16 LE, with no gain or overflowing arithmetic. Fixtures include zero, maximum positive, minimum negative and minus one. Microphone alignment still requires bench confirmation. Every start discards 4096 stereo frames (256 ms / 2^18 clocks), conservatively using the initial-power allowance. STARTED follows successful initialization and settling; clocks and DMA are deleted on finish, abort, lease expiry or transport failure.

## Ownership and bounds

Talk requests host admission. A matching `mic_ready` with `capture_terminal: true` is required before UART START. Finish atomically moves the adapter into draining; Cancel is only offered before Finish. The S3 UI queues commands without waiting for network/UART, and capture ownership never derives from snapshots. New taps wait for matching `mic_terminal` or a new connection. Missing capability shows `Incompatible host`; a denied grant shows `Not admitted by Home`.

The C6 worker owns I²S startup/teardown and UART writes. The DMA completion callback copies each completed block into a bounded sixteen-entry owned queue (512 PCM bytes per entry); the worker sends one block between control/lease checks. Finish disables sampling, checks callback overflow after disable, drains all accepted owned blocks, then sends ENDED. Cancellation discards that queue. No read occurs after IDF disables the channel. The SDK read queue contains duplicate DMA pointers and is deliberately unused: its pointer-queue overflow does not indicate loss from our copied PCM queue. Exhausting the owned queue fails the whole utterance. Eight 256-frame DMA buffers hold 16 KiB of raw stereo samples. Worker scratch buffers use static single-owner storage so the existing main-task stack remains sufficient. The S3 UART ring holds at most sixteen maximum wire frames (16,800 bytes, carrying at most 16 KiB PCM), and forwarding uses one frame at a time. S3 control ingress is a fixed sixteen-entry queue. Queue exhaustion, invalid sequence/totals, CRC/COBS failure or partial transport writes abort; there is no retransmission. Both boards enforce 480,000 PCM bytes / 15 seconds. S3 processes one queued control and at most one UART frame per worker iteration, with deadlines/keepalives between sends; UART byte/event scanning is also bounded. A stalled/overflowing forwarding path fails closed. HELLO retries every 200 ms within each one-second boot window, with at most one hardware reset; matching idle HELLO is idempotent. Wi-Fi and WebSocket connection attempts back off to 30 seconds. Keepalives renew the one-second C6 lease during startup, recording and draining.

## Trusted installation requirement

The local `/state` socket is **not panel authentication**. The host accepts absent Origin and uses its configured paired Device identity. A passing deployment requires an isolated trusted S3-to-host network (dedicated IoT VLAN/AP) and host listener/firewall restrictions allowing only that trusted segment or the panel address. Do not expose this listener publicly or use a shared/untrusted LAN as authorization evidence. Home claim credentials and STT stay on the host. Raw PCM is transient and must not be saved for diagnostics.

## Physical acceptance — pending

No board was connected during implementation verification. The following remain mandatory on the actual installation:

- Confirm USB selection, GPIO routing, reset pulse/recovery, sample alignment and UART throughput while LCD/Wi-Fi are busy.
- Observe no capture clocks/PCM before matching host readiness; deny admission and confirm no microphone opens.
- Finish one real utterance; verify exact PCM ordering, one final transcript, exactly one Home turn and native answer text.
- Cancel during admission, startup and recording; verify no partial Home submission and no automatic replay on reconnect.
- Exercise 15-second/byte limit, UART corruption/queue failure, unplug/reconnect and C6 reset; verify capture stops and fresh Talk is required.
- Exercise response audio fallback followed by text completion; verify unavailable audio is explicit and final answer text remains.

Record bench observations in `validation-1-e-1-authorized-voice-capture.md`. Automated/simulator evidence must never be labelled physical acceptance.
