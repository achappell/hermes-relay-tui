---
title: 'Deterministic ReSpeaker microphone format boundary'
type: 'bugfix'
created: '2026-10-18'
status: 'in-review'
route: 'dispatch'
review_loop_iteration: 0
story_key: '1-p-8-make-the-vendored-respeaker-audio-format-boundary-determinis'
baseline_commit: '95809e14c83f0e343a4d730d96405b39fe844e7e'
context: []
---

<frozen-after-approval reason="existing P-8 acceptance; implementation checkpoint delegated by user, not human spec approval">

## Intent

**Problem:** The vendored microphone schema advertises formats that its unconditional three-to-one decimation cannot support. Callback boundaries discard trailing frames, and amplitude diagnostics use signed shifts and overflow on INT32_MIN.

**Approach:** Enforce the proven external, non-PDM, 48 kHz/32-bit/stereo secondary-I2S format, and give its existing nearest-frame conversion a stateful, allocation-free contract. Keep the first stereo frame of each three globally, preserving both signed little-endian words unchanged, producing 16 kHz per channel. Use a common safe decoder for diagnostic amplitude. Keep a deterministic fixture and compiled native regression harness.

## Boundaries & Constraints

**Always:** Preserve channel order (ch0 ASR; ch1 wake), byte width, nearest-frame/no-filter behavior, VAD capture, upload, playback, default-off raw diagnostics, identity and admission gates. The consumer still receives stereo signed 32-bit words at 16 kHz; its existing channels selector chooses channel 1. Carry incomplete frames and decimation phase across driver reads and reset on a new microphone task.

**Never:** Introduce a FIR, tune wake models/confidence, invent trusted proximity, change Home policy, enable raw PCM, access real microphones, flash or deploy. P-9 lifecycle and P-11 playback failures remain separate. Reject optional DC correction because the proven path is unfiltered, rather than silently promising an untested conversion.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected behavior | Error handling |
|---|---|---|---|
| Proven format | external, non-PDM, 48000 Hz, 32-bit, stereo, secondary | Accepted; stereo 16000 Hz stream metadata | — |
| Unsupported format | other rate/width/channel/mode, PDM/internal ADC, DC correction | Rejected before code generation | Clear ReSpeaker contract reason |
| Signed boundaries | INT32_MIN/MAX, -1, 0, positive/negative words | Exact unchanged retained words; magnitude 0..2147483648 | No signed overflow/shifts |
| Split driver reads | arbitrary byte boundaries | Same output as one contiguous read; retained frames 0,3,6... | Incomplete frame held, never emitted |
| New task | previous stream ends part-frame or phase | New stream retains its own frame 0 | State reset |

</frozen-after-approval>

## Code Map

- `firmware/respeaker-lite/components/i2s_audio/microphone/__init__.py`: schema/defaults and output stream limits; restrict only the vendored microphone, not generic speaker support.
- `firmware/respeaker-lite/components/i2s_audio/microphone/i2s_audio_microphone.cpp`: `configure_stream_settings_`, `mic_task`; replace per-callback vector decimation, reuse reserved read vector.
- `firmware/respeaker-lite/components/i2s_audio/microphone/respeaker_pcm.h`: new small production conversion/decoder header, used directly by native harness and YAML diagnostic.
- `firmware/respeaker-lite/respeaker-lite.yaml`: `mic_diag` decoder and unsigned magnitude logging; capture callbacks remain ordered and unchanged.
- `tests/test_puck_firmware.py`: existing native-harness convention. New format tests use executable production header and real ESPHome configuration validation, not source-text pins.

## Tasks & Acceptance

**Execution:**
- [x] Add byte-safe decoder/magnitude and persistent nearest-frame converter; integrate into mic task and diagnostics without per-callback allocation.
- [x] Restrict schema and align defaults/metadata; cover supported and rejected configurations with real validator.
- [x] Keep signed stereo fixture and independently specified expected output; test counts, duration, channel identity, boundaries, fragmentation, reset and sanitizer safety.
- [x] Run focused tests, real-header native smoke beyond tests, default and Home-mode ESP32 firmware compiles, complete suite with supported bash; obtain independent review and fix findings.
- [x] After smoke, update README/changelog, index, tracker and validation evidence; preserve open physical acceptance honestly.

**Acceptance Criteria:**
- Given an unsupported format, when configuration validation runs, then it fails clearly and does not imply unsupported conversion combinations.
- Given signed stereo fixture words including negative and extreme values, when microphone conversion and diagnostics decode them, then output is defined, 16 kHz/channel and free of signed shift/overflow behavior.
- Given the supported format and deterministic fixture, when conversion runs, then exact frame count, channel order, duration and representative words match the documented contract independent of callback boundaries.
- Given current wake and response paths, when exercised through regression/build checks, then existing wake/VAD/capture/upload/playback behavior remains unchanged; physical regression is a separately open gate.
- Given the implemented contract, when host and firmware checks run, then they repeat without Hermes and retain fixture/expected output for future changes.

## Implementation Notes

Planning facts: no unresolved user-visible intent gaps; no irreversible action; footprint is the vendored microphone, YAML diagnostic, native fixture/tests and delivery records. Existing P-8 epic/deferred acceptance is authoritative; unattended implementation and routine checkpoint decisions were delegated, not newly human-approved product policy. No dependency is listed for P-8..P-11 in the story index. P-7 is merged at the baseline. Physical hardware belongs exclusively to `tui-p7-pcm-diagnostics` and raw diagnostics remain off.

Independent spec review found missing named regression evidence for unchanged wake/capture/upload/playback. Accepted: run `tests/test_puck_firmware.py` (real-header wake/follow-up capture and response-state harnesses), `tests/test_puck_bridge.py` (upload/response pacing), and `tests/test_puck_home_session.py` (Home admission/session integration), plus the full suite. Native fixture output is the same byte-format contract delivered to existing wake consumers; live acoustic wake recognition remains an open physical gate, never inferred from compilation.

## Spec Change Log

## Review Triage Log

- Spec review P2 (regression mapping): accepted and resolved by naming the existing executable firmware/bridge/Home regression modules above. No intent change.
- Independent code review: no actionable patch-introduced correctness defect; converter capacity, fragmentation, metadata and schema checked.
- Required blind-hunter layer: no substantiated patch-introduced issue (reviewer declined to fabricate five findings). Edge-case layer returned `[]`; verification-gap layer reported no gaps.

## Verification

Observed: focused 249 passed/1 skipped before the environment link; full suite 2198 passed/2 skipped/6 warnings in 335.36 s under bash 5.3.20, including successful ESPHome config generation. Native production-header smoke passed ASan/UBSan; actual default and Home-mode firmware compiled successfully. See [validation](validation-1-p-8-deterministic-respeaker-audio-format.md) for commands, exact counts, build sizes, reviews and physical handoff. Implementation is done-with-deferred-gate; spec/tracker stay in-review/review because controlled acoustic acceptance is open.
