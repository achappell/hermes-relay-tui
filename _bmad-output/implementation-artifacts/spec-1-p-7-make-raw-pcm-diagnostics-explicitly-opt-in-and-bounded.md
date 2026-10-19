---
title: 'Make raw PCM diagnostics explicitly opt-in and bounded'
type: 'bugfix'
created: '2026-10-18'
status: 'review'
route: 'dispatch'
review_loop_iteration: 0
story_key: '1-p-7-make-raw-pcm-diagnostics-explicitly-opt-in-and-bounded'
baseline_commit: '638e1bca7dc85d670568f37b17e246d54b20971e'
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/implementation-artifacts/deferred-work.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Puck's story-3 training-data capture still allocated a 256,000-byte PSRAM buffer at every boot and copied pre-processed microphone audio into it from the real-time callback. Nothing exported it by default, but the buffer was retained, `dump_over_serial()` (base64 PCM over `ESP_LOGI`) and `upload_and_restart()` remained callable, and the callback/export hand-off used plain unsynchronized flags.

**Approach:** Make raw PCM capture an explicit build-time operator choice that is off by default. Default builds allocate nothing and capture nothing. Opt-in requires a flag and an export URL, warns at boot, and stops after a fixed per-boot limit. An atomic ownership state separates callback writes from export. Remove the serial/base64 dump path.

## Boundaries & Constraints

**Always:** Keep default household firmware free of diagnostic PCM retention or export. Keep the identity gate on the diagnostic path, so revocation drops the in-progress or finished window without exporting it (PSRAM bytes are not zeroed, only overwritten by a later window) and diagnostics stay stopped until reboot. Keep the content-safe `mic_diag` amplitude and `mww_diag` status logs separate from raw PCM. Allocate once and never free while the callback may run.

**Never:** Change wake capture, VAD endpointing, wake upload, follow-up, response playback, bridge or Hermes behavior. Do not write raw or base64 PCM to logs or serial. Do not flash, deploy or touch production configuration as part of this implementation.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected behavior | Error handling |
|---|---|---|---|
| Default build | `puck_pcm_diagnostics: "false"` | No allocation, no capture, no export; callback is one atomic load | — |
| Flag without URL | `true`, empty URL | Stays disabled; error log | No allocation |
| Explicit opt-in | `true` + URL | Boot `RAW MICROPHONE PCM DIAGNOSTICS ENABLED` warning; capture and export 2 s windows | Allocation failure stays disabled |
| Bound reached | 15 windows exported or abandoned | `COMPLETE`; no further capture until reboot | Abandoned/discarded windows count toward the limit |
| Concurrent callback/export | Mic task writes while main loop exports | Export reads only a window it claimed `READY -> EXPORTING`; writer touches buffer only in `CAPTURING` | No torn window, overrun or use-after-reset |
| Identity revoked | 4xx from wake upload | Capturing or ready window dropped by the callback or the exporter and never exported; no re-arm until reboot (identity fails closed) | PSRAM bytes not zeroed, only overwritten later |

</frozen-after-approval>

## Code Map

- `firmware/respeaker-lite/pcm_capture.h`: the top-level `pcm_capture` namespace holds the diagnostic capture; `wake_capture` holds the wake path.
- `firmware/respeaker-lite/respeaker-lite.yaml`: substitutions, on_boot setup/start, mic `on_data` write, interval export.
- `firmware/respeaker-lite/tools/collect_serial_dumps.py`: host parser for the removed `PCMDUMP` log path.
- `tests/test_puck_firmware.py`: compiled host harnesses with ESP-IDF/ESPHome stubs.

## Tasks & Acceptance

**Execution:**
- [x] `pcm_capture.h`: `setup(opted_in, url)`, atomic `DiagState` (`DISABLED/IDLE/CAPTURING/READY/EXPORTING/COMPLETE`), `MAX_DIAGNOSTIC_CAPTURES = 15`, boot warning, identity checks, and export from claimed windows only. Remove `dump_over_serial()`.
- [x] `respeaker-lite.yaml`: `puck_pcm_diagnostics: "false"` and `puck_pcm_diagnostics_url: ""` substitutions; pass them to setup; a 2 s interval calls the export no-op unless enabled; update the stale comments.
- [x] Remove `tools/collect_serial_dumps.py`; document opt-in in `firmware/respeaker-lite/README.md`; add CHANGELOG entry.
- [x] Tests: static default/no-base64/content-safe-separation checks; harnesses for default-off, URL requirement, warning, bound, identity revocation and concurrent ownership (ThreadSanitizer when available).
- [x] Tracker `review`; validation record `validation-1-p-7-make-raw-pcm-diagnostics-explicitly-opt-in-and-bounded.md`.

**Acceptance Criteria:**
- Given the default firmware configuration, when the Puck boots and receives microphone data, then no diagnostic PCM buffer is allocated or started, and no raw or base64 PCM is written to logs, serial or the network.
- Given explicit opt-in, when capture is enabled, then the build substitution makes the choice visible, the device warns at boot, and capture/export stops after 15 two-second windows (3,840,000 bytes) per boot.
- Given active diagnostic capture, when the callback and export or reset paths run concurrently, then ownership passes through atomic state transitions and no partial read, data race, overrun or use-after-reset occurs.
- Given the normal wake path, when diagnostics are disabled or complete, then wake detection, VAD-gated capture, upload and playback are unchanged.
- Given the diagnostic boundary, when host/build checks and a controlled hardware check run, then they prove default-off and bounded opt-in, with amplitude/status diagnostics separate from raw PCM export. **Host and build checks pass; the controlled hardware check is open.**

## Implementation Notes

- The training buffer was never exported by the default YAML. Default builds no longer allocate it, which removes the retained-audio concern in `deferred-work.md`.
- The opt-in is a substitution passed into the setup lambda: `esphome -s puck_pcm_diagnostics true -s puck_pcm_diagnostics_url http://<host>:8765/upload`. It is visible in the rendered config (`pcm_capture::setup(true, "...")`) and in the boot warning.
- The writer owns `write_pos`/`buffer` only in `CAPTURING`, then publishes with a release store of `READY`. The exporter claims `READY -> EXPORTING` with compare-exchange and resets only in `IDLE`/`EXPORTING`. Identity revocation from the callback uses compare-exchange on `READY`, so either revocation or export wins. The buffer is never freed.
- Export does not feed `puck_identity::note_upload_status`; the diagnostic receiver is not an identity authority.

## Spec Change Log

## Review Triage Log

## Verification

See [validation-1-p-7](validation-1-p-7-make-raw-pcm-diagnostics-explicitly-opt-in-and-bounded.md). Open gate: controlled hardware check (default build boots with no `pcm_capture` allocation and an unchanged wake round trip; opt-in build warns and stops after 15 uploads). No device was flashed for this implementation.
