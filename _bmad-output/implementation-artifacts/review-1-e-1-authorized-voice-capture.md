# 1-E-1 specification review — 2026-09-21

Verdict: revised draft is suitable for approval; implementation and hardware evidence are still pending. Reviewed against baseline `7fad7b187f3a127eb3eef5801b8797a6a006579d`. Two independent reviewers inspected host and firmware behavior; the primary agent checked the findings against source and revised the specification and UART companion. This is a planning review, not a test pass.

| Finding | Evidence and consequence | Resolution in revised draft |
|---|---|---|
| P1: USB console would be switched to CAN | `firmware/esp32-s3-touch-lcd-7/main/src/bsp_io_expander.c:27` initializes EXIO outputs high. Official Waveshare 7B documentation assigns EXIO5 low=USB, high=CAN. | Explicit EXIO5-low initialization/preservation, board constant and expander task; verify console through startup. |
| P1: Audio failure can truncate text | `home_display/touch.py:659` handles `audio_abort` as terminal interruption. `puck_bridge/home_session.py:1426` normalizes ordinary audio fallback to that event while the turn can continue. | Distinguish audio-only failure from true turn termination; test subsequent text and `turn_end`, and fence late playback failures. |
| P1: No correlated completion signal | `home_display/state.py:230` snapshots have no capture ID. `touch.py:516,569` returns idle for empty/failed transcription; prior idle/complete snapshots cannot identify the current capture. | Add advertised, capture-scoped `mic_terminal`, emitted after cleanup; keep Talk locked until its matching completion or a fresh connection. Old hosts fail closed. |
| P1: Latest-state delivery conflicts with transition enforcement | `home_display/state.py:341–357` coalesces queued snapshots. `shared/display/display_rules.c:168` rejects skipped phases; synchronous error→idle→heard in `touch.py:781` loses the intermediate idle. | Accept validated forward sequence gaps, retaining stale and contiguous-transition validation; exercise actual publisher output through the native reducer. Record the approved shared policy in the canonical product hub before implementation. |
| P2: Startup could lose its lease | Proposed startup allowance was two seconds, but one-second lease renewal started only after STARTED. Cancel during hardware startup was also unspecified. | START opens the lease; renew during STARTING and draining; cancel fences late STARTED. Datasheet initial settling at this clock is 256 ms, not the 48-kHz example's 85 ms. |
| P2: Delayed START could reopen capture | Proposed duplicate protection covered active captures only; after terminal cleanup the C6 is idle again. | Require completed link handshake and strictly increasing capture numbers, preserving the last accepted number through cleanup. Test a delayed duplicate after ENDED. |
| P2: Trusted-local transport premise was not operational | `home_display/server.py:669` permits absent Origin; `appliance.py:2113` supplies the same configured Device identity to Touch connections. A reachable socket is not proof of physical-panel identity. | Bench guide must document an isolated trusted network and listener/firewall restrictions. No remote-access or physical-panel authentication claim is made. |

A follow-up pass confirmed the revisions and tightened one completion edge: early matching `mic_terminal` must stop every admitted active phase, not just Working. The 17-second capture-end watchdog explicitly stops at accepted `mic_end`, before transcription. These corrections are in the companion; no implementation behavior is claimed.

## Retained decisions

Amanda selected Talk → Finish with Cancel before Finish and a 15-second maximum. Preserve UART 921600 8N1, the selected pin map, host-owned admission/STT/session authority, no replay, transient PCM, and separate response-audio work. Cancel also works during admission/startup; after Finish the interface truthfully shows Working rather than promising that an already submitted turn can be discarded.

## Checks performed

- Read the live draft and companion, current host ingress/lifecycle/audio normalization, publisher coalescing, native reducer and expander initialization.
- Verified frame arithmetic: 16-byte header + 1024-byte payload + 4-byte CRC = 1044 decoded bytes; bounded COBS envelope including delimiter is 1050 bytes.
- Checked nominal wire load: 32000 PCM bytes/s × 1050/1024 ≈ 32813 bytes/s, below 921600/10 = 92160 UART bytes/s. This is capacity arithmetic, not measured throughput.
- Checked official hardware/I²S references; compile and bench validation remain necessary.
- Reviewed draft whitespace, paths and absence of installation secrets. No firmware build, automated implementation suite, flashing or live turn was performed.

## References

- [Waveshare 7B interfaces](https://docs.waveshare.com/ESP32-S3-Touch-LCD-7B) — EXIO5 USB/CAN selection and shared UART header.
- [Espressif C6 I²S, ESP-IDF 5.3.3](https://docs.espressif.com/projects/esp-idf/en/v5.3.3/esp32c6/api-reference/peripherals/i2s.html) — standard mode and sample/slot configuration.
- [INMP441 datasheet](https://invensense.tdk.com/wp-content/uploads/2015/02/INMP441.pdf?ref_disty=digikey) — 64 clocks/frame and startup clock counts.
