---
title: '1-E-1: Authorized physical Touch voice capture'
type: feature
created: '2026-09-21'
status: done
route: dispatch
review_loop_iteration: 1
baseline_commit: 7fad7b187f3a127eb3eef5801b8797a6a006579d
source_story: 1-E-1
story_key: 1-e-1-authorized-voice-capture
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/docs/contracts/touch-capture-uart-v1.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-standard-7-esp32-touch-audio-session-adapter.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** STD-7 supplies the host adapter, but the physical Touch display cannot record an utterance. Its firmware lacks Wi-Fi initialization, capture controls, and an S3/C6 audio transport.

**Approach:** Tap Talk to request capture, tap Finish to send, or Cancel before Finish to discard. Auto-finish at 15 seconds. Connect Home readiness to C6 capture, bounded PCM forwarding, and one host-transcribed Home turn; preserve native response text. Amanda selected explicit Finish on 2026-09-21.

## Boundaries & Constraints

**Always:** Use the selected 7B and C6 hardware and the companion UART contract. Open the microphone only after matching host `mic_ready` advertising terminal acknowledgements; report `mic_capture_started` only after actual I²S startup. Keep one capture/turn active until matching `mic_terminal` or connection invalidation. Carry 16 kHz mono signed-16 LE PCM, chunks ≤4096 bytes, total ≤480000 bytes, duration ≤15 seconds. Cancel or transport failure discards capture; reconnect requires a new tap. Keep credentials/session authority and STT on the host; audio remains transient. Use private installation Wi-Fi configuration and a trusted local host connection.

**Never:** Add wake detection, follow-up, speaker playback, Profile selection, firmware STT, automatic prompt replay, or a setup application. Do not claim hardware acceptance from a simulator. Response playback remains 1-E-3: drain incoming audio and explicitly report unavailable audio.

## I/O & Edge-Case Matrix

| Scenario | Expected behavior |
|---|---|
| Talk accepted | Request readiness; start C6 only after matching grant; send started before PCM. |
| Denied, late grant, unavailable C6 | No capture; visible unavailable state; fresh tap required. |
| Capture ends | Drain ordered PCM, send one `mic_end`, observe host transcript/response. |
| Cancel, corrupt/gapped UART, overflow, disconnect | Stop I²S, discard queued audio, abort or close host connection; no submission/replay. |
| Response audio | Send matching `audio_playback_failed` once per turn; drain binary safely; retain text. |

</frozen-after-approval>

## Code Map

- `home_display/touch.py`, `home_display/server.py`: existing `/state` readiness/PCM contract; add real deadline enforcement and matching abort identity, preserving session ownership.
- `firmware/esp32-s3-touch-lcd-7/main/src/{main,ui_transport,ui_display}.c`: current snapshot/action transport and LVGL task; extend without blocking rendering; preserve legacy display mode.
- `shared/touch_audio/` and `firmware/esp32-c6-audio/`: new portable framing/state code and standalone C6 ESP-IDF target; no existing C6 audio implementation.

## Tasks & Acceptance

**Execution:**
- [x] `shared/touch_audio/{capture_protocol,capture_state}.{c,h}` — implement the companion framing, identities, bounds, deadlines, and deterministic PCM conversion with portable interfaces.
- [x] `firmware/esp32-c6-audio/{CMakeLists.txt,sdkconfig.defaults,main/CMakeLists.txt,main/main.c}` — add pinned ESP-IDF capture target; bounded I²S/UART workers, start/stop acknowledgements, lease expiry, no radio initialization.
- [x] S3 `main/src/{touch_capture,touch_uart,network}.c` and matching `main/include/` headers — compose capture, UART/reset and Wi-Fi; keep private configuration untracked.
- [x] S3 `main/src/{main,ui_transport,ui_display}.c` and corresponding headers — wire capture controls, matched terminal acknowledgements, `/state` demultiplexing, ordered sends and reconnect fences; disable unsupported prompt actions and drain audio.
- [x] S3 `main/include/board_config.h`, `main/{CMakeLists.txt,idf_component.yml,Kconfig.projbuild}`, `CMakeLists.txt`, `sdkconfig.defaults`, `platformio.ini`, root `.gitignore` — register sources, pinned LVGL/shared configuration, installation configuration, pin allocation and USB console; add EXIO5-low initialization/preservation in `main/src/bsp_io_expander.c` and its header; preserve simulator portability.
- [x] `home_display/touch.py`, `tests/test_home_display_touch.py` — add correlated terminal cleanup and deadlines, reject stale aborts, distinguish audio fallback from turn termination, and test late-event fencing.
- [x] `shared/display/display_rules.c`, `tests/test_display_contract.py` — accept valid sequence gaps from coalesced snapshots while rejecting stale/invalid state; verify host-publisher-to-C-reducer integration.
- [x] `tests/test_touch_capture_firmware.py`, `tests/test_firmware_ui_core.py` — compile/run C harnesses for the matrix and protocol boundary cases; exercise UI queueing and host-order integration.
- [x] `firmware/esp32-c6-audio/README.md`, `_bmad-output/implementation-artifacts/validation-1-e-1-authorized-voice-capture.md` — document builds, wiring and bench evidence; synchronize tracker/coverage only to verified scope.

**Acceptance Criteria:**
- Given an admitted physical display, when one utterance is finished, then exactly one final transcript reaches Home and its answer appears on that display.
- Given denied readiness, cancellation, lost transport or damaged audio, when the path is exercised, then no partial utterance is submitted and reconnect cannot capture or replay automatically.
- Given capture load, when snapshots arrive, then LVGL remains responsive; legacy display-mode actions remain unchanged and unsupported Touch voice prompt controls are disabled (2-E-5 owns that integration).
- Given only automated evidence, when recording delivery status, then physical acceptance remains explicitly outstanding.

## Implementation Notes

Implemented the automated software scope on 2026-09-21 and re-derived it after review on 2026-09-22. The portable protocol/reducer, pinned C6 capture target, S3 network/UART/controls, correlated host cleanup/deadlines and snapshot-gap handling are present. The [validation record](validation-1-e-1-authorized-voice-capture.md) maps executable evidence and separates toolchain repair from source compilation. Physical/live acceptance remains outstanding; execution checkboxes record implementation, not hardware acceptance. The software build/review workflow is complete; story status is review pending physical/live acceptance.

### Review loop 1 implementation requirements

- C6 completion must stop sampling, preserve every completed accepted PCM block in a bounded owned buffer, drain in sequence, and check overflow after sampling stops before ENDED. Do not read IDF after disable: IDF 5.3.3 resets the read cursor and requires RUNNING. Keep bounds of 480000 bytes and 15 seconds; cancellation discards staging. Track teardown ownership including partial startup. Test actual C6 orchestration with pending data and overflow injected during stop.
- Add a deterministic S3 worker-step seam. Bound UART work per step; service controls, deadlines and keepalives between sends; fail when forwarding cannot keep up. Test repeated lease intervals by feeding emitted controls to real C6 reducer, delayed sends, overflow, startup/drain deadlines and disconnect/reconnect fencing.
- Synchronize coherent connection and UI state across tasks. Stale epochs must not send into a replacement WebSocket. Preserve single capture ownership; protect legacy action sends with the transport lifetime mutex.
- UI button enablement must recover after a discarded stale command even when the UI observes the same phase before and after reconnect. Do not rely solely on phase-change caching to undo immediate click disabling.
- Matching Cancel survives admission/start/listening transitions, never accepted Finish. Malformed recognized host controls invalidate connection. Retry HELLO for bounded boot recovery; same-generation HELLO repeats READY only while idle, never resets active capture. At most one hardware reset per recovery.
- Stale mic controls and unexpected PCM during transcription/turn must not release capture ownership. Keep task busy through terminal finalization. Test duplicate end/started, unexpected PCM, and admission with paused terminal send.
- Back off network reconnects. Accept full-capacity valid SSID/key with length validation and byte copies; keep configuration private.
- The physical S3 build must actually include LVGL 8.3.11 and compile the enabled voice/network/UI branch. Wire its component dependency and fail compilation if voice is configured without its UI dependency; a successful fallback/no-UI binary is not feature verification.
- Actual-source tests must execute on clean CI without developer PlatformIO. Provide pinned licensed cJSON test source or explicit CI prerequisite; no silent skip.

KEEP: Preserve approved intent, protocol bounds, COBS/CRC tests, host admission, text-only audio fallback, coalesced snapshots, 7B pin/USB expander setup, legacy display mode, private configuration and passing regression behavior. No flashing/live Home submission. Physical acceptance remains pending.

Reviewed candidate source is preserved outside Git at `~/.cache/hermes-touch-build/review-loop-1/` with `manifest.json` and `candidate.diff`. Source was reverted to baseline for re-derivation under these requirements; selectively restore candidate files as a starting point then implement corrections. Do not overwrite planning/tracker artifacts. Toolchains remain in `~/.cache/hermes-touch-build/`; native PlatformIO and C6 environments are described in validation. After code is stable run focused/full Python verification and firmware/simulator builds; update validation evidence.

## Spec Change Log

- 2026-09-22, loop 1: B1/B3/B4/B6/B9/V2 exposed missing stop/drain, synchronized ownership and executable worker verification detail. Added requirements outside frozen intent to prevent lost samples, continuing cancelled capture and untested lease failures. KEEP instructions preserve validated surfaces during re-derivation. Other confirmed patches are included. Grouped duplicate B7/E5, B9/V2 and B10/V1 only after individual verdicts; other roots remain separate.

- 2026-09-22, verification corrections: R5 added the actual LVGL dependency and compile gate; R6 restricted product test discovery to avoid mutating generated SDK components; R7 made END during autonomous draining idempotent. Re-derived implementation review found only direct code/test patches, recorded individually below; approved intent remains unchanged.

## Review Triage Log

### Implementation review — 2026-09-22

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| B1 | high | bad_spec | finish deletes the channel before reading completed DMA buffers. IDF disable resets read pointers and reads require RUNNING; bounded owned PCM staging/drain is required. |
| B2 | false | reject | Pinned IDF disable fails only for an invalid/non-running channel; the single owner disables a running channel before delete. Partial startup permits non-running teardown. No reachable live-handle loss demonstrated; revised stop will still track teardown ownership explicitly. |
| B3 | high | bad_spec | Overflow callback can run after finish checks its flag and before disable stops DMA. Check overflow after stopping sampling before success. |
| B4 | high | bad_spec | worker drains UART until empty; each send can take 200 ms including mutex wait. A nonempty queue can starve keepalive and Cancel beyond the 1 s lease. |
| B5 | medium | patch | Manual WebSocket retries can repeat every 100 ms after immediate failure. Add backoff. Permanent retry cap is not required: contract bounds C6 reset attempts, not all network reconnections. |
| B6 | high | bad_spec | connected, epoch, phase and capture cross callback/UI/worker tasks without synchronization; connected is published before new epoch. Publish coherent state and fence stale sends. |
| B7 | high | patch | After mic_end, _capture is None while _turn_task still owns identity. Duplicate end/started or PCM emits terminal no_turn without stopping that task. Ignore these stale inputs during the owned turn. |
| B8 | medium | patch | Recognized terminal with invalid ID is silently dropped; Working has no deadline. Malformed recognized controls must invalidate the connection. |
| B9 | high | bad_spec | Harness calls input and uart_frame directly; its task stub never invokes worker. Scheduling/failure paths require worker-step coverage. |
| B10 | high | patch | Actual-source checks skip without cJSON in a developer PlatformIO directory that normal CI does not provision. Require a reproducible pinned dependency. |
| E1 | high | patch | Strict requested_phase rejects Cancel across valid admission/start transitions. Permit same-capture Cancel in all cancellable phases, retaining epoch/capture fences and Finish exclusion. |
| E2 | medium | patch | HELLO follows reset release immediately, before C6 UART startup. Add bounded boot handshake retries and idempotent idle HELLO response. |
| E3 | medium | patch | strlcpy truncates valid 32-byte SSID or 64-byte hex key in fixed ESP Wi-Fi arrays. Validate and copy full lengths. |
| E4 | high | patch | Legacy send_action uses client outside stop/destroy mutex. Route it through the lifetime-protected send path. |
| E5 | high | patch | Duplicate mic_end during STT/turn finishes capture while task remains active; same root as B7. |
| V1 | high | patch | Preverified: CI provisions no cJSON source required by the sole S3 source harness, so admission fencing regressions can pass CI. |
| V2 | high | bad_spec | Preverified: no test executes worker; deleting keepalive leaves tests green. Exercise iterations with controlled clock/UART and real C6 reducer. |
| R6 | medium | patch | Verification audit confirmed pytest recursively imported a generated websocket conftest and wrote __pycache__ into the managed component, breaking subsequent IDF hash checks. Product tests live under tests/; scope collection there and verify full suite/builds coexist. |
| R7 | high | patch | Final delta audit: asynchronous C6 auto-finish enters TC_DRAINING before the later S3 automatic END; reducer accepts END only while capturing or after ended, so it aborts valid queued PCM. Ignore matching END while already draining without extending the deadline; test automatic drain plus late END. |
| R5 | high | bad_spec | Target audit: hardware component manifest/CMake omit LVGL, so __has_include disables actual UI/network/capture startup despite voice configuration. Pin and wire LVGL 8.3.11, require the physical voice integration at compile time, and rebuild the actual enabled target. |
| R4 | high | patch | Re-derivation audit: C6 main task configured 3584 bytes; worker frame/block plus nested send_frame frame/wire and encoder raw arrays total over 4600 bytes before other calls. Use single-owner static scratch or an explicitly sized task, then verify target configuration. |
| R3 | medium | patch | Re-derivation audit: C6 ISR stores start milliseconds in atomic_uint, but reducer time is uint64. Direct widening expires captures after 32-bit uptime wrap; reconstruct elapsed time with unsigned wrap arithmetic and test it. |
| R2 | medium | patch | Root audit: capture_click disables every button, but capture_update restores only on phase change. A stale queued command discarded across a fast reconnect can leave UI observing idle both times and Talk permanently disabled. Refresh enablement from current state or explicitly acknowledge command resolution. |
| R1 | medium | patch | Root audit: _capture_turn clears task before terminal send completes. Retain busy ownership through finalization; test start while terminal send is paused. |

### Re-derived implementation review — 2026-09-22

Each finding was classified individually before grouping. Confirmed corrections are local patches with no new public surface; rejected claims are recorded separately.

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| L1-B1 | false | reject | Pinned IDF 5.3.3 disable rejects only null/non-running channels; the sole worker sets rx_running only after successful enable and alone disables it. Delete follows disable or partial READY startup. No reachable running-handle loss was demonstrated. |
| L1-B2 | low | patch | Invalidation sets closed before normal close can clear transient transcript/response/identity fields. Directly clear the same fields before awaiting cleanup. |
| L1-B3 | false | reject | Production sender delegates to websockets close with its bounded close_timeout; HomeBrowserSession inherits HomePuckSession close and the bridge client bounds reader cancellation and context exit with HOME_BRIDGE_CLOSE_TIMEOUT. The alleged indefinite production close is not supported by these callers. |
| L1-B4 | medium | patch | Malformed or oversized WebSocket text only resets assembly and reports an error; losing mic_terminal can leave Working indefinitely. In voice mode invalidate the connection on malformed framing/envelopes. |
| L1-B5 | medium | patch | Missing/non-string type is passed to snapshot parsing and merely rejected, bypassing capture-control fail-closed handling. Require a typed envelope in voice mode. |
| L1-B6 | medium | patch | Unchecked cJSON field allocations can serialize a partial audio_playback_failed message and consume its one acknowledgement. Check each insertion before send or acknowledgement state change. |
| L1-B7 | medium | patch | NVS init uses ESP_ERROR_CHECK, so recoverable storage errors reboot the new network startup repeatedly. Return the error to main, preserving NVS and the already-created unavailable UI. |
| L1-B8 | medium | patch | Readiness subscribes only to GOT_IP. IDF DHCP handling can emit LOST_IP while Wi-Fi remains associated; clear readiness on LOST_IP and restore on GOT_IP. |
| L1-B9 | false | reject | Capture initialization is called once by app_main under ESP_ERROR_CHECK. Failure resets the MCU; no in-process retry can inherit the alleged half-created resources. |
| L1-B10 | medium | patch | Terminal can become visible before the sender await returns; a prompt next mic_start sees the old turn busy. Serialize final terminal delivery and task release with the ingress lock so new admission waits for cleanup. |
| L1-E1 | false | reject | Independently checked the same disable claim against IDF state checks and single-worker ownership as L1-B1; no reachable disable failure with a still-running owned channel. |
| L1-E2 | medium | patch | audio_abort marks audio unavailable but leaves playback_started true, so subsequent text can remain Speaking. Clear playback state on abort and test text after a previously-started playback. |
| L1-V1 | high | patch | Preverified: tests inject adapter failure through a stub, never execute production touch_uart.c. Add an actual adapter harness for UART overflow/buffer-full/frame/parity errors, partial frames and parser flush/reset. |
| L1-V2 | medium | patch | Preverified: tests do not execute firmware audio_start dispatch through audio_playback_failed generation. Exercise actual control/worker code and validate identity, schema, reason and duplicate suppression. |
| R8 | medium | patch | IDF dispatches each receive-buffer chunk with the same frame FIN flag; the existing assembler treats FIN on a partial chunk as truncation. Newly wired voice handling exposes this on valid larger snapshots. Wait for expected bytes before parsing and test a multi-event frame with FIN true on each event. |

All confirmed re-derived review patches are implemented and independently inspected; focused patch verification passes (78 tests), the final full suite passes (1521 passed, one unrelated skip), and S3 legacy/voice, C6 and simulator builds pass. No software finding was deferred. Physical/live acceptance remains explicitly outstanding.

No survivor shares a root cause requiring merged handling; related transport fixes share a file but retain distinct outcomes. L1-B1 and L1-E1 are separately rejected, not silently deduplicated.

The earlier [spec review](review-1-e-1-authorized-voice-capture.md) records planning findings. Implementation review verdicts are above; executable results and outstanding physical acceptance are in the [validation record](validation-1-e-1-authorized-voice-capture.md).

## Design Notes

One goal spans network startup, two microcontrollers and the host. Branch: `feat/1-e-1-touch-capture`. Host and firmware implementation with automated verification; no flashing or live turns. The companion defines the correlated completion extension and snapshot-gap policy.

## Verification

- Run focused Python/compiled-C tests, then the full Python suite and native simulator build.
- Build the existing S3 PlatformIO target and a pinned ESP-IDF 5.3.3 C6 target. Record toolchain failures separately from source failures; host compiles do not replace firmware builds.
- Bench: authorization denial, real utterance, cancel, 15-second limit, unplug/reconnect, C6 reset, queue failure and text-only answer. Record absence of capture clocks/PCM before readiness, sample order and exactly one Home turn. Physical/live checks require the connected installation and available authorization; leave them pending when unavailable.
