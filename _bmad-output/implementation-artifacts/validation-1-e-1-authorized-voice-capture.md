# 1-E-1 authorized Touch voice capture — validation

Date: 2026-09-22, review loop 1. Scope: host adapter, portable UART protocol/state, C6 microphone firmware and S3 7B display/network/capture integration. Independent software review is complete. Story is in **review** with physical acceptance outstanding. No flashing, real microphone capture, live Home turn or deployment was performed.

## Implemented behavior

- Portable fixed-capacity COBS/CRC framing, capture identities, sequence/byte bounds, leases and deterministic signed microphone conversion remain in `shared/touch_audio/`.
- C6 copies each completed DMA block into a sixteen-entry owned PCM queue before IDF can reuse the buffer. Finish stops sampling, checks overflow after disable, drains accepted blocks in order and sends ENDED only after the queue is empty. Cancellation discards staging. No IDF read follows disable. The unused SDK read queue contains duplicate DMA pointers; its overflow is distinct from owned-queue overflow. Partial startup teardown tracks whether the channel is running, and worker scratch storage does not exceed the existing main-task stack.
- C6 and S3 enforce the duration/byte bounds independently. A matching END crossing an autonomous C6 finish is harmless during draining and does not reset the drain deadline; END after completion repeats the cached acknowledgement. Same-generation HELLO repeats READY only while idle. Bounded HELLO retries allow boot recovery with at most one hardware reset.
- S3 processes one control and at most one UART frame per worker iteration, servicing deadlines and keepalives between sends. UART event/byte scanning is also bounded. Slow or overflowing forwarding fails closed. Connection/UI publication is synchronized; stale epoch notifications and sends cannot reach a replacement socket. Capture IDs remain owned through terminal acknowledgement. Matching Cancel survives admission/start/listening transitions, but cannot cancel accepted Finish.
- Host deadlines and correlated cleanup remain intact. Late started/end/PCM during transcription or an owned Home turn cannot emit an early terminal or release ownership. The turn task stays busy through terminal delivery, and late audio failure during that finalizer preserves completed text/state.
- Wi-Fi accepts full-capacity 32-byte SSIDs and 64-byte keys without truncation, rejects oversized values, keeps configuration private and uses reconnect backoff. WebSocket retries also back off. Legacy action sends use the socket lifetime mutex and epoch check.
- Hardware now declares the same LVGL 8.3.11 version as the simulator. LVGL and main/UI sources share `main/include/lv_conf.h`, including PSRAM allocation and the ESP timer tick. CMake rejects `CONFIG_LV_CONF_SKIP`; Touch compilation fails if LVGL is absent. Capture buttons refresh enabled state even when a discarded stale command leaves the visible phase unchanged.
- EXIO5-low USB selection, 7B pin allocation, legacy display actions, coalesced snapshots, native answer text and explicit unavailable response audio remain. Touch prompt actions and response playback remain outside this slice.

## Executable evidence

| Check | Result and evidence |
|---|---|
| Focused Python and native C | Initial re-derived scope: **212 passed**, one existing deprecation warning. Final review patches: **78 passed**, `/tmp/touch-review-patches-focused-final.log`. `pytest -q tests/test_touch_capture_firmware.py tests/test_home_display_touch.py tests/test_firmware_ui_core.py tests/test_display_contract.py tests/test_home_appliance.py`; `/tmp/touch-focused-loop1-final.log` |
| Full product Python suite | **1521 passed, 1 skipped, 6 deprecation warnings**, 220.79 seconds. `pytest -q -ra`; `/tmp/touch-full-tests-patch-final.log`. The sole skip is `tests/test_puck_firmware.py:91`, because its separate ESPHome environment is absent. No Touch/cJSON source check skips. |
| Native simulator | Clean build passes: `make -C firmware/esp32-s3-touch-lcd-7/simulator clean`, then `make -C firmware/esp32-s3-touch-lcd-7/simulator`; `/tmp/touch-simulator-review-loop1-final.log`. Two upstream LVGL warnings remain (unused variable and signed comparison). Final incremental recheck passes: `/tmp/touch-simulator-patch-final.log`. No simulator session was used as hardware evidence. |
| C6 target | Pinned ESP-IDF 5.3.3 build passes after the drain/END correction; `/tmp/touch-c6-build-review-loop1-verified.log`. Existing main-task stack configuration remains 3584 bytes. Final incremental recheck also passes: `/tmp/touch-c6-patch-final.log`. |
| S3 legacy/default mode | Post-patch LVGL-enabled 7B build passes with Touch voice disabled; `/tmp/touch-s3-legacy-patch-final.log`. |
| S3 Touch voice mode | Post-patch LVGL-enabled 7B build passes with `CONFIG_TOUCH_VOICE=y`; `/tmp/touch-s3-voice-patch-restored.log`. Private configuration was preserved in memory and restored before this final build. |
| LVGL configuration | Preprocessed actual compiler commands for `main.c`, `lv_timer.c` and `lv_hal_tick.c` agree on `LV_COLOR_DEPTH=16`, `LV_MEM_CUSTOM=1`, `LV_TICK_CUSTOM=1` and `((uint32_t)(esp_timer_get_time() / 1000))`. Main reports `HAVE_LVGL=1`. ELF contains `lvgl_ui_task`, `network_task`, `touch_capture_init`, `touch_capture_worker_step` and `lv_tick_get`. |
| Whitespace | `git diff --cached --check` passes. Two file-specific `.gitattributes` exceptions preserve upstream cJSON header trailing whitespace and the license final blank line byte-for-byte; product files retain normal checks. |

The repository environment is `~/Development/hermes-relay-tui/venv`. S3 verification uses its `pio` executable, `PLATFORMIO_CORE_DIR=~/.cache/hermes-touch-build/platformio`, the preserved native CMake override `~/.cache/hermes-touch-build/platformio-native.ini`, and the unchanged `espressif32 ~6.6.0` target. C6 uses `~/.cache/hermes-touch-build/c6-env.sh`, IDF v5.3.3 commit `6db3dc25df7325c1c81b7cd7d4e42babff7a818e` and isolated tools. No shared tool installation was replaced.

## Actual-source test mapping

`tests/test_touch_capture_firmware.py` runs seven compiled native harnesses with `-Wall -Wextra -Werror`:

1. Portable protocol/reducer: CRC reference, maximum frame and every split point, concatenated frames, delimiter loss/resynchronization, CRC corruption, decoded invalid version/length/generation, odd/oversized payload, signed conversion endpoints, admission fence, stale/duplicate START, idle/active HELLO behavior, startup/drain leases, duration/byte bounds and cached END.
2. Actual S3 `touch_capture.c`: host-ready/start/PCM/end ordering; actual bounded worker steps feeding emitted controls into the real C6 reducer across repeated one-second leases; delayed sends, overflow, startup/drain deadlines, cancellation across phase transitions, Finish exclusion, malformed terminal identity, HELLO retries/reset cap, old-epoch publication, disconnect during STARTED and fresh-tap recovery. A repeated RNG value cannot reuse the previous link generation.
3. Actual C6 `main.c`: callback staging, pending blocks and an additional completed block during disable, overflow injected during disable, owned-queue overflow, cancellation, transport failure, startup/drain lease expiry, byte/duration bounds, millisecond wrap, partial startup teardown, autonomous finish crossed by END, and cached terminal acknowledgement. These tests do not call a fake replacement finish routine.
4. Actual `ui_transport.c`: lifetime mutex ownership, stale epoch rejection after replacement while waiting for the send lock, protected legacy action sends, stale callbacks, stale invalidation, control demultiplexing and binary response drain.
5. Actual `network.c`: exact 32-byte SSID and 64-byte key copies, oversized/empty SSID rejection and repeated reconnect backoff with a deterministic clock.
6. Actual `ui_display.c`: immediate button feedback, re-enabling Talk when a stale queued command is discarded without a visible phase change, and disabled Finish/Cancel during draining, using minimal LVGL object stubs.

7. Actual `touch_uart.c` together with the capture worker: all four hardware error events take priority over buffered PCM, clear input/events/parser state, and invalidate capture; partial frames, CRC corruption, bounded reads/events, reset timing and short writes are covered.

Host tests cover admission/close/deadline races, stale aborts, slow transcription, unexpected mic controls/PCM during transcription and response, paused terminal delivery with a competing start, late audio fallback during finalization, text after audio-only abort and terminal-delivery failure. `tests/test_display_contract.py` feeds real coalesced publisher JSON through the compiled C reducer. Existing server/appliance/state regressions remain in the full suite.

The cJSON source/header/MIT license are pinned under `tests/vendor/cjson/` and independently match upstream v1.7.17 byte-for-byte. Tests require no developer PlatformIO package. `pytest.ini` confines product collection to `tests/`; all tracked non-tooling Python tests are there. This avoids importing generated SDK dependency suites and creating `__pycache__` inside immutable managed components.

## Superseded evidence and toolchain repairs

The initial 2026-09-21 S3 build success, and the first review-loop build before LVGL wiring, **do not prove the physical integration compiled**. The manifest omitted LVGL, so `__has_include` selected the no-LVGL branch and excluded display/network/capture startup. The builds above supersede that evidence. The real LVGL compile also exposed an existing diagnostic `snprintf` buffer warning; its buffer now fits the maximum formatted message.

Two intermediate legacy/voice builds failed before source compilation because the generated websocket component hash had changed. The preserved earlier component contains pytest-created `tests/autobahn-testsuite/__pycache__`. The generated component was preserved in the task cache and restored through the component manager; restricting pytest collection prevents that dependency-directory mutation. The subsequent builds pass. These are dependency/tooling failures, recorded separately from source results.

The simulator's old `make -B` invocation tried to clone LVGL into its existing source directory. Explicit clean/build succeeds without touching the checkout of the pinned dependency. None of these repairs flashed a board or sent a Home prompt.

## Review patches — focused verification

The subsequent local review corrections were checked with `pytest -q tests/test_home_display_touch.py tests/test_touch_capture_firmware.py --tb=short`: **78 passed**, one existing websockets deprecation warning, 2.66 seconds. Evidence: `/tmp/touch-review-patches-focused-final.log`. `git diff --check` also passes. The root agent subsequently inspected the corrections and completed the final full suite, both S3 modes, C6 and simulator checks shown above. No confirmed software review finding was deferred.

The host checks now cover immediate transient cleanup before invalidation awaits, new admission waiting for terminal delivery and ownership release (including a terminal already visible to the peer while send yields), cancellation of a locked finalizer, and playback-started → audio-abort → subsequent text without a false Speaking state. Transport harnesses exercise voice and legacy behavior for malformed framing/types and a valid 5002-byte frame delivered in multiple IDF buffer events, all with FIN set. The audio-start worker test validates all four acknowledgement fields, escaping, once-per-turn behavior and failure at each allocation without a partial send or consumed acknowledgement. Network checks cover both known NVS initialization errors without erase/reboot and LOST_IP/GOT_IP readiness changes.

A new harness executes production `touch_uart.c` together with the capture worker. It feeds FIFO overflow, buffer-full, frame and parity events ahead of buffered valid PCM, verifies no PCM is accepted, checks input/event/parser cleanup and recovery, and exercises partial frames, CRC failure, bounded delimiter-free input/event scanning, reset timing and partial UART writes. Production C6 teardown was not changed.

## Physical/live acceptance — outstanding

Automated checks prove behavior with fake clocks, transports, DMA callbacks and LVGL objects, plus real compiler targets. They do not prove pin routing, analog microphone alignment, reset/USB timing, sustained UART throughput or display responsiveness under real LCD/Wi-Fi/capture load.

Run the bench checklist in [C6 capture README](../../firmware/esp32-c6-audio/README.md) on the selected S3 7B/C6 installation: authorization denial with no pre-grant clocks/PCM; one finished utterance, one final transcript and exactly one Home turn; native answer text with unavailable response audio; cancellation during admission/startup/recording; 15-second/byte limits; unplug/reconnect; C6 reset; UART/queue failure; sample ordering; and fresh-tap recovery without replay.

The installation must use an isolated trusted S3-to-host network and host listener/firewall restrictions. The local socket is not panel authentication; a shared/untrusted LAN is not passing authorization evidence. Physical acceptance remains outstanding, and automated results do not justify moving the story to done.
