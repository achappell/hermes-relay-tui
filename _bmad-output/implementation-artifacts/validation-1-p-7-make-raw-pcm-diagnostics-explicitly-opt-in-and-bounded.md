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

## Review follow-up (2026-10-18)

- Added `test_raw_pcm_diagnostic_export_drops_a_claimed_window_after_identity_loss`: the exporter claims a `READY` window after a 403 with no intervening callback. The window is dropped with no POST, counted, and left `IDLE`, and it stays stopped until reboot.
- Added `test_raw_pcm_diagnostics_reach_the_bound_when_every_upload_fails`: with every POST returning 500, each window is abandoned after 2 chunks and still counts. The device reaches `COMPLETE` after 15 windows (30 POSTs), and identity is unaffected.
- Mutation check: removing the exporter-discard `captures_exported++` fails only the first new test, and removing the post-upload increment fails only the second. The header was restored afterwards.
- README/spec wording: after authorization loss, the window is dropped and never exported. PSRAM is not zeroed, only overwritten later, and diagnostics stay stopped until reboot.
- Reran `venv/bin/pytest -q tests/test_puck_firmware.py -rs`: **20 passed**, including the ESPHome config gate. `esphome compile` passed for both the default and the opt-in variants, with no `pcm_capture.h` warnings (flash 1,860,467 / 1,860,827 B).

## Partial hardware evidence (2026-10-18)

Physical Puck: XIAO ESP32-S3, 8 MB flash, USB-Serial/JTAG on `/dev/cu.usbmodem101`. All logs, the build and the flash backup are kept privately outside the repository, with SSIDs and keys redacted.

- **Before flashing:** the device ran ESPHome 2026.8.2, compiled 2026-09-12. Its boot log showed `Allocated 256000 bytes of PSRAM for PCM capture`, which is the pre-P-7 always-on buffer. The whole 8 MB flash was read back over USB (`esptool --no-stub read-flash`) and checksummed (sha256 prefix `c5a12279`). A second read of the app region matched it byte for byte. The original credentials were not recoverable, so the device was re-keyed with newly generated private secrets.
- **Flashed:** a private build of 3-P-5 source `21223b44` (PR #249). That source contains merged P-7 (`95809e1`). The build was compiled with ESPHome 2026.9.1, `puck_home_transport=true`, `puck_pcm_diagnostics=false` and bridge `192.168.0.4:8766`. factory.bin is 1,926,784 B (sha256 prefix `0794019a`). The USB write reported 1,926,784 bytes written and `Hash of data verified`.
- **First boot, 45 s serial capture** (step A of the gate, partial):
  - `ESPHome version 2026.9.1 compiled on 2026-10-18 22:37:58`
  - `raw PCM diagnostics disabled (default) -- no capture buffer allocated`
  - no `256000`-byte allocation; only the wake buffer (`Allocated 1024000 bytes of PSRAM for wake capture`)
  - 0 `PCMDUMP` lines and 0 `/upload` requests
  - Wi-Fi joined (`IP Address: 192.168.0.184`) after two `Connecting to network failed` retries
  - API port 6053 and web port 80 accept TCP from ops and from this Mac.
- **Not yet done:**
  - The step A wake round trip. It is blocked: no Puck bridge is deployed (P-HOME-01, PR #250), Home has no room-device pairing route, and the P-4 calibrated proximity provider is missing. Under 3-P-5 the Home-mode build refuses before capture while admission is absent.
  - Step B (opt-in bounded capture) was deliberately not run. It records ambient microphone audio and needs the owner present.
  - Step C will be a reflash only if an opt-in build is ever installed. The device is not on an opt-in build.

The P-7 hardware gate remains open. Status stays `review`.
