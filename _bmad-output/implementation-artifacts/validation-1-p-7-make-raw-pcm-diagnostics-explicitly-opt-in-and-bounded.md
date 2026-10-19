# 1-P-7 raw PCM diagnostics opt-in and bounded — validation

Date: 2026-10-18. Scope: `firmware/respeaker-lite/pcm_capture.h`, `respeaker-lite.yaml`, removal of `tools/collect_serial_dumps.py`, and tests. The story is in **review**. The controlled hardware check remains open. No device was flashed and no deployed service or production configuration was touched.

## Executable evidence

| Check | Result |
|---|---|
| Focused firmware tests | `venv/bin/pytest -q tests/test_puck_firmware.py -rs`: **17 passed, 1 skipped** (the skip was the ESPHome config gate, before `venv-firmware` was installed in the worktree). |
| ESPHome config, default | `venv-firmware/bin/esphome config firmware/respeaker-lite/respeaker-lite.yaml` (ESPHome 2026.9.1, `secrets.yaml` built from the example file with a generated API key): valid; rendered `pcm_capture::setup(false, "");`. |
| ESPHome config, opt-in | `esphome -s puck_pcm_diagnostics true -s puck_pcm_diagnostics_url http://127.0.0.1:8765/upload config …`: valid; rendered `pcm_capture::setup(true, "http://127.0.0.1:8765/upload");`. |
| ESP32-S3 compile, default | `esphome compile firmware/respeaker-lite/respeaker-lite.yaml`: succeeded; RAM 117,031 B (34.2%), flash 1,860,467 B (47.3%); no compiler warnings referencing `pcm_capture.h`. |
| ESP32-S3 compile, opt-in | Same with both substitutions: succeeded; flash 1,860,827 B; no `pcm_capture.h` warnings. |
| Full suite | `venv/bin/python -m pytest -q -rs`: **2192 passed, 2 failed, 2 skipped**, 6 warnings, 377.55 s. The ESPHome config gate ran and passed. Both failures are in `tests/test_ops_web_deployment.py` (`scripts/deploy_ops_web.sh: line 331: BASHPID: unbound variable` under macOS `/bin/bash` 3.2). They fail identically on untouched `main` at `638e1bc` (2 failed, 26 passed in that module), so they predate this change. Skips: ESP-IDF cJSON unavailable; optional `wake` extra not installed. |

## Behavioural mapping

- **Default off** (`test_default_firmware_build_keeps_raw_pcm_diagnostics_off`, `test_raw_pcm_diagnostics_are_off_by_default_and_bounded_when_opted_in`): the substitutions default to `"false"` and `""`. In the compiled harness, `setup(false, …)` makes zero heap allocations, and 40 full callback windows plus export ticks produce zero POSTs and no warning. `dump_over_serial`, `base64_encode` and `PCMDUMP` are absent, and the host parser has been removed.
- **Explicit, visible and bounded:** `setup(true, "")` stays disabled. `setup(true, url)` allocates once and logs `RAW MICROPHONE PCM DIAGNOSTICS ENABLED`. An incomplete window is not exported. After 20 offered windows, exactly 15 × 16 chunks and 3,840,000 bytes are exported, the state is `COMPLETE`, and `start()` plus more windows export nothing further.
- **Ownership** (`test_raw_pcm_diagnostic_export_never_reads_a_window_being_written`): a real mic thread writes a strictly increasing counter while the main thread exports concurrently. All 15 windows are exactly 256,000 bytes and strictly sequential, with no torn or overwritten window. The harness is built with `-fsanitize=thread` when the toolchain supports it, as Apple clang does here, and passed with no ThreadSanitizer report.
- **Identity** (`test_raw_pcm_diagnostics_discard_buffered_audio_when_identity_is_revoked`): unauthorized boot does not start capture. A 401 after a window is `READY` discards it with no POST, and capture does not re-arm.
- **Wake path unchanged:** the existing wake/follow-up harness and YAML ordering tests still pass, and `pcm_capture::start()` does not appear in the wake automation. `mic_diag` and `mww_diag` logging is unchanged.

A throwaway demo built against the same stubs printed:

```
default (flag false)   enabled=0 heap_allocs=0 state=DISABLED posts=0 exported_bytes=0 (windows offered=30)
flag true, no URL      enabled=0 heap_allocs=0
explicit opt-in        enabled=1 heap_allocs=1 state=COMPLETE posts=240 exported_bytes=3840000 (windows offered=30)
```

## Open gate

Controlled hardware check, not performed:

1. Flash the default build. Confirm the boot log shows `raw PCM diagnostics disabled (default)`, shows no `PCMDUMP` line and makes no `/upload` traffic outside wake turns. Then complete one wake round trip.
2. Flash an opt-in build pointed at `tools/receiver.py`. Confirm the boot warning, exactly 15 received `.raw` captures and a `complete` log. Then reflash the default build.
