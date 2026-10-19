# P-9 fail-safe ReSpeaker RX lifecycle — validation

Date: 2026-10-18. Worktree `.worktrees/p9-i2s-lifecycle`, branch `feat/p9-i2s-lifecycle`. Exact parent/base is P-8 commit `208573c4a6190f2fe098e15376412a0fac1324b1` on `feat/p8-audio-format` (PR #248), itself based on `origin/main` `95809e14c83f0e343a4d730d96405b39fe844e7e`. P-9's PR is stacked on P-8 to review only lifecycle changes to the shared microphone source/contract, without duplicating P-8 commits in its diff.

Checkpoint authority is **delegated unattended implementation**, not newly fabricated human spec approval. Hardware belongs only to `tui-p7-pcm-diagnostics`; this work used no microphone, hardware, live host/service, flashing/reboots/deployment/pairing or production credentials. Raw PCM diagnostics remain off.

## Observed native evidence

- Closest actual-source lifecycle check initially passed one test. While extending coverage, an initial harness-only compile error exposed protected fake-base state; that test setup was corrected. The added pending-task regression then compiled and **failed its real call-sequence assertion**. `loop()` was retrying a parent lock and tearing down the channel while a created mic task had not published TASK_RUNNING. The production STATE_STARTING guard fixes that lifecycle race.
- `venv/bin/python -m pytest -q tests/test_respeaker_i2s.py tests/test_respeaker_pcm.py -rs` — **3 passed**, 0.77 s. The lifecycle harness includes the actual production microphone `.cpp` and shared header, compiling against narrow IDF/FreeRTOS/ESPHome stubs; it does not reproduce the implementation in a fake lifecycle model. ASan/UBSan are enabled. Driver injection records allocation/init/enable/disable/delete and parent-lock operations plus actual formatted logs.
- Separate changed-path smoke: `clang++ -std=c++17 -DUSE_ESP32 -DSOC_I2S_SUPPORTS_PDM_RX=0 -Wall -Wextra -Wno-unused-const-variable -Wno-unused-variable -fsanitize=address,undefined -fno-sanitize-recover=all -I /tmp/puck-p9-smoke-headers -I . -I tests/firmware /tmp/puck-p9-lifecycle-smoke.cpp -o /tmp/puck-p9-lifecycle-smoke && /tmp/puck-p9-lifecycle-smoke` — **PASS**, no sanitizer report. It includes the actual production microphone source and runs an independently written 12-cycle alternating init-failure/success scenario with repeated teardown. Output: `actual RX source: 12 alternating init-fault/success cycles; locks=12 unlocks=12 deletes=12 disables=6; repeated teardown quiet; PASS`.

## Observed build and regression evidence

- `venv/bin/python -m pytest -q tests/test_respeaker_i2s.py tests/test_respeaker_pcm.py tests/test_puck_firmware.py -rs` — **23 passed**, 3.99 s, including ESPHome configuration generation.
- `venv-firmware/bin/esphome compile firmware/respeaker-lite/respeaker-lite.yaml` — **success**, ESPHome 2026.9.1 / ESP-IDF 5.5.5; RAM **117039 B**, flash **1860899 B**, config hash `0x7110dac6`, build time `2026-10-18 22:31:11 -0500`. Full tool log `artifact://2998`, saved at `/tmp/puck-p9-default-compile.log`.
- `venv-firmware/bin/esphome -s puck_home_transport true compile firmware/respeaker-lite/respeaker-lite.yaml` — **success**, RAM **117039 B**, flash **1860903 B**, config hash `0xad9a6c7e`, build time `2026-10-18 22:32:52 -0500`.
- Both builds keep `puck_pcm_diagnostics=false` and the URL empty. GPIO3-strapping and OTA-password-cost warnings remain unchanged. Compile-only nonzero synthetic example credentials are temporary and removed before commit; these example images must never be deployed.
- Complete suite, serialized after all builds/focused checks: `env PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin venv/bin/python -m pytest -q -rs` — **2199 passed, 2 skipped, 6 warnings**, 344.79 s. Skips: ESP-IDF cJSON unavailable and optional Sherpa wake extra unavailable. Existing deprecation warnings only. ESPHome config generation passed, with no startup-timeout flake. Modern bash avoids the known macOS bash3.2 BASHPID failure. Log saved at `/tmp/puck-p9-full-suite.log` (`artifact://3024`).

## Acceptance mapping

1. **Partial startup unwind:** allocation (including an error with a partially returned handle), initialization and enable fault injection checks immediate channel cleanup before startup returns, null handle, false enabled/owned flags, exactly one parent unlock, and typed original failure operation/error. The caller's subsequent cleanup changes no call count.
2. **Before-lock failure:** busy parent produces only the lock attempt, no channel call or unowned unlock. Teardown on a default-constructed microphone is a no-op.
3. **Cleanup faults:** disable, delete and combined faults each retain contextual operation/RX-port log output, still attempt deletion/unlock, clear local ownership, and do not reuse the failed handle. Initialization plus deletion error preserves the initialization error as primary. This checks software ownership and safe cleanup attempts, **not successful physical resource release when IDF itself fails**.
4. **Initialized shared config:** harness checks default bus pins, invert flags, port and all shared stream/lifecycle fields before configuration setters. Generated setters retain actual configured values. RX owns its channel and controller-parent mutex; TX uses the separately configured output parent. The intentionally pristine `components_stock` comparison fixture is unchanged.
5. **Retry/preserved paths:** remove each injected startup error and start/stop successfully with fresh handles and balanced ownership. Pending-task test proves no duplicate driver start/cleanup before TASK_RUNNING. Speaker output/pacing source and wake/admission policy are unchanged; inherited P-8 signed conversion fixture still passes. Physical wake/capture/playback regression remains an open gate.

## Independent reviews

- Independent spec review: no findings; exact epic P-9 acceptance, lifecycle semantics, defaults and actual-source fault coverage checked.
- Independent blind-hunter code review: no actionable new defect; reviewer declined to fabricate six findings to reach a numerical floor.
- Edge-case review returned `[]`; verification-gap review reported no gaps, explicitly checking actual-source execution and honest treatment of underlying cleanup failures.

## Controlled hardware handoff — open

Only the hardware-owning session may deploy a reviewed commit with installation-owned configuration; never deploy the generated synthetic-example image. Keep `puck_pcm_diagnostics=false` and its URL empty. Record exact build/device identity, verify normal boot/wake/VAD/upload/full audible response/clean next wake, and observe contextual RX lifecycle state during a controlled stop/start. Any hardware fault injection must remain under that owner's procedure. No low-level fault-injection hardware result is claimed here. Calibrated trusted-proximity evidence remains locked and its missing provider remains a separate rollout blocker; no confidence/fixed-score/touch substitute was introduced.

Disposition: **done-with-deferred-gate** for software, with spec/tracker deliberately `in-review` / `review` while controlled physical acceptance is open. Temporary compile secrets and throwaway smoke source/binaries were removed; observed logs and permanent real-source regression remain.

## Main/P-8 reconciliation (2026-10-19)

Normal merge of `origin/main` at `cce15704457a51ed587b30bd6d780e106da629f5`, without rebase/force. Manual conflicts were `CHANGELOG.md`, `deferred-work.md`, `sprint-status.yaml`, `surface-coverage-matrix.md` and the firmware README; kept delivered P-9 evidence and main's P-8 evidence together. The merged I2S runtime source is byte-identical to the pre-merge P-9 source, which already inherited P-8. Existing untracked `venv` / `venv-firmware` entries were preserved.

Independent firmware-owner semantic review read the complete merge diff and actual source: no substantiated regression. Verified P-8 per-task decimator pending bytes and 0/3/6 frame phase, strict external48k/stereo32/no-DC format, signed magnitude and default diagnostics-off; verified P-9 stage/error retention, enabled-channel cleanup, single owned-lock release and pending-task guard. Reviewer ran no checks and granted no hardware authority.

- Focused `python -m pytest -q tests/test_respeaker_i2s.py tests/test_respeaker_pcm.py tests/test_puck_firmware.py`: **23 passed** (3.75s).
- Full `python -m pytest -q` with exactly the two known macOS Bash 3.2 deployment cases deselected: **2197 passed, 2 skipped, 2 deselected**, six existing websockets warnings (333.23s).
- Actual default and `-s puck_home_transport true` ESPHome compiles both passed under **2026.9.1 / ESP-IDF 5.5.5**. RAM **117039 bytes** both; flash **1860899 / 1860903 bytes**. Config hashes **0x7110dac6 / 0xad9a6c7e**, build times **2026-10-19 11:49:29 / 11:49:44 -0500**. Existing GPIO3 and OTA-password warnings remain. `git diff --check` passed.
- Initial focused attempt: **22 passed, 1 failed** because ESPHome 2026.9 rejects the public all-zero example API key. Replaced only the temporary example key with an explicit nonzero synthetic value; no product/test change or suppression. Full/build chain did not run on the failed attempt. Temporary example secrets were removed after successful checks; generated images must never be deployed.

The earlier actual-source standalone lifecycle smoke remains applicable to the unchanged runtime source; it was not represented as a new smoke run. Physical acceptance remains OPEN; no live action occurred.
