# P-10 internal wake routing — validation

Date: 2026-10-18. Worktree `.worktrees/p10-internal-wake-routing`; branch `feat/p10-internal-wake-routing`; fresh `origin/main` baseline `95809e14c83f0e343a4d730d96405b39fe844e7e`. This story is independent of the P-8/P-9 microphone stack; no P-8/P-9 commits are included. Routine implementation/spec checkpoints were delegated by the user; no new human product-policy approval is claimed.

No real microphone, physical hardware, live service/host, deployment, pairing, flashing/rebooting or production credentials were accessed. Only `tui-p7-pcm-diagnostics` owns hardware. Raw PCM diagnostics stayed off for every firmware variant.

## Observed executable evidence

- Final focused routing/firmware regression: `venv/bin/python -m pytest -q tests/test_respeaker_wake_routing.py tests/test_puck_firmware.py -rs` — **22 passed**, 3.75 s, including ESPHome config validation.
- Real-config role check creates an isolated, credential-free ESPHome configuration with public `hey_missy`, internal `stop`, and an arbitrary additional internal `hey_bestie` declaration. Actual `esphome config` validates/normalizes it and preserves false/true/true roles. No source-text wording pin is used.
- Native test compiles the production `detection_event.h` and real `pcm_capture.h` under ASan/UBSan. The production model-to-event handoff executes on public/internal model fixtures; the event is byte-copied using the FreeRTOS queue contract, then dispatched into actual admission/capture/upload logic with synthetic samples and a fake HTTP boundary. Internal/default/missing-word/not-detected/VAD-blocked events do not reach the public callback or upload. A public model starts real capture and uploads the full synthetic buffer. Internal events cannot disturb that active public capture.
- Mutation evidence: removing `event.internal_only = model.get_internal_only()` from the production handoff makes `test_internal_events_cannot_reach_real_capture_or_upload` fail `!event.internal_only`; this was observed, not inferred. The assignment was restored. Log: `/tmp/puck-p10-provenance-mutation.log` (`artifact://3067`). The initial test fixture incorrectly replied `allowed:` rather than existing `admitted:`; fixing the fixture, not admission policy, resolved that earlier failure.
- Beyond-test changed-path smoke: `clang++ -std=c++17 -fsanitize=address,undefined -fno-sanitize-recover=all -I /tmp/puck-p10-smoke-headers -I firmware/respeaker-lite /tmp/puck-p10-routing-smoke.cpp -o /tmp/puck-p10-routing-smoke && /tmp/puck-p10-routing-smoke` — **PASS**, no sanitizer report. It independently runs the production model-to-event handoff and routing into real capture, closes on actual VAD debounce and uploads 4000 synthetic bytes. Output: `production routing+capture: internal detections=200 callbacks=0; public callbacks=1 VAD-close=1 uploads=1 synthetic_bytes=4000; PASS`.
- Final actual firmware compiles ran serially: `venv-firmware/bin/esphome compile firmware/respeaker-lite/respeaker-lite.yaml && venv-firmware/bin/esphome -s puck_home_transport true compile firmware/respeaker-lite/respeaker-lite.yaml` — **both success**, ESPHome 2026.9.1 / ESP-IDF 5.5.5. Default RAM **117031 B**, flash **1860607 B**, config hash `0x0a8335a7`, build time `2026-10-18 22:48:58 -0500`; Home RAM **117031 B**, flash **1860611 B**, config hash `0x9338bdbf`, build time `2026-10-18 22:49:12 -0500`. Log saved at `/tmp/puck-p10-final-firmware-compiles.log` (`artifact://3077`). An earlier successful compile predates the review-driven handoff extraction and is not substituted for these final builds.
- Existing GPIO3-strapping and OTA-password-cost warnings remain. Synthetic nonzero compile-only examples were used, never installation secrets. Example images must never be deployed. All checks in this workstream are serialized and use installed venv executables.
- Final complete suite, after final compiles and without concurrent checks: `env PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin venv/bin/python -m pytest -q -rs` — **2198 passed, 2 skipped, 6 warnings**, 345.44 s. Skips: ESP-IDF cJSON unavailable; optional Sherpa wake extra unavailable. Existing deprecation warnings only. ESPHome config validation passed without startup-timeout flake. Supported bash avoids known macOS bash3.2 BASHPID failures. Log saved at `/tmp/puck-p10-full-suite.log` (`artifact://3099`).

## Acceptance mapping

1. **Internal stop cannot initiate a turn:** declared internal role travels from model through the queued event; dispatch fails closed before the public callback. Native checks prove no capture preparation, admission request, pending upload or HTTP request. Because Hermes/Profile selection is downstream of that public wake ingress, it is not entered. No alternative internal control action is introduced.
2. **Public path preserved:** public provenance survives actual production handoff and queue byte-copy; native dispatch reaches the existing real authorization/admission/capture/upload logic. Separate smoke confirms VAD debounce and a complete synthetic upload. Physical acoustic recognition is not inferred.
3. **Diagnostics:** the engine emits an explicit internal-control suppression diagnostic without the detected word, PCM or transcript. Public VAD/probability diagnostics remain separate. Internal control skips the public stop-after-detection branch.
4. **Changed internal list:** actual ESPHome configuration preserves the roles of existing stop and arbitrary additional internal declaration. Shared role predicate excludes internal public entities; routing is metadata-based, not a name allowlist. Default/unspecified event role remains internal. Model thresholds and schema policy are unchanged.
5. **Focused/build checks and exact stop:** native/config checks and both actual firmware variants pass without Hermes or a microphone. P-3 spoken exact-stop transcription implementation is unchanged. Acoustic/public-wake/internal-control hardware acceptance remains open.

## Independent review and fixes

- Independent spec reviewer found no gaps against exact P-10 epic acceptance.
- Blind-hunter code review found no substantiated issue and declined to fabricate its numeric finding floor; edge-case review returned `[]`.
- Verification-gap reviewer found a real medium test gap: manually public test events could hide lost producer provenance. Accepted and fixed by extracting the production handoff into `make_model_detection`, using it in the actual inference producer and native queued-event tests. Mutation failed as expected; independent reviewer re-read the fix and explicitly confirmed the gap resolved with no remaining actionable gap.

## Controlled hardware handoff — open

Only the hardware owner may use the reviewed SHA with installation-owned configuration, never these synthetic example images. Keep `puck_pcm_diagnostics=false` and its URL empty. Record exact build/device identity; verify public wake → acknowledgement → VAD capture/upload → audible response → next wake, and controlled internal stop/control detection that logs suppression but starts no public capture/admission/upload/turn/Profile and does not stop the public detector. Keep P-3 exact spoken-stop transcription acceptance separate. Native fixtures do not prove real acoustic detection. The locked calibrated trusted-proximity evidence requirement is unchanged and its missing production provider remains a separate rollout blocker; no fixed-score, confidence or touch substitute is implemented.

Software disposition is **done-with-deferred-gate**; supported spec/tracker values remain `in-review` / `review`, following P-7 while physical acceptance is open. No issue is auto-closed.

Temporary synthetic compile secrets and throwaway smoke source/binary/header scaffolds were removed before commit. Permanent production-header regression tests and observed logs remain.

## Main/P-8 reconciliation (2026-10-19)

Normal merge of `origin/main` at `cce15704457a51ed587b30bd6d780e106da629f5`, without rebase/force. Manual conflicts were `CHANGELOG.md`, `deferred-work.md` and `surface-coverage-matrix.md`; retained both P-8 and P-10 delivery evidence and open physical gates. Runtime files did not conflict. Existing untracked `venv` / `venv-firmware` entries were preserved.

Independent firmware-owner review read the complete merge diff and actual producer/queue/consumer/capture source: no substantiated integration regression. P-8 decimator pending bytes/frame phase and signed stereo32LE16k format remain intact; P-10 assigns declared role before queueing, defaults unspecified provenance closed, drops internal/ignored events before public callbacks and limits public stop-after-detection to public routing. Home admission, channel1/gain4 conversion and default diagnostics-off remain unchanged. Reviewer ran no checks and granted no hardware authority.

- Focused `python -m pytest -q tests/test_respeaker_wake_routing.py tests/test_respeaker_pcm.py tests/test_puck_firmware.py`: **24 passed** (3.83s).
- Full `python -m pytest -q` with exactly the two previously reported macOS Bash 3.2 deployment cases deselected: **2198 passed, 2 skipped, 2 deselected**, six existing websockets warnings (334.13s).
- Actual default and `-s puck_home_transport true` ESPHome compiles both passed under **2026.9.1 / ESP-IDF 5.5.5**. RAM **117031 bytes** both; flash **1860867 / 1860871 bytes**. Config hashes **0x77d1d0f0 / 0xbfd81cc0**, build times **2026-10-19 11:55:43 / 11:55:57 -0500**. Existing GPIO3/OTA-password warnings remain. `git diff --check` passed.
- Temporary nonzero synthetic example secrets were removed afterward; generated images must never be deployed. No live credentials, microphone, host or hardware action was used.

Original standalone routing/capture smoke above remains historical evidence, not a newly rerun smoke. The current merged real-source native regressions, signed P-8 fixture, configuration and actual firmware builds are the new merge evidence. Physical acceptance remains OPEN.

Latest main fb1fe6f (254 landed): independent paired-consumer/P10 coexistence review CLEAN. Focused192passed6.39s; full2343passed/2skipped/2knownBashdeselected/6warnings353.16s; default/Home ESPHome2026.9.1 compile PASS RAM117063,flash1861595/1861591. Synthetic secrets removed; no hardware actions. diff-check passed.
