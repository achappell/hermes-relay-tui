# P-4 / STD-6 — Home-paired Living Room Puck consumer

Date: 2026-10-19. Specification: [full-turn implementation](spec-p4-home-fresh-startup.md).
Branch: `feat/p4-home-fresh-startup`; worktree `.worktrees/p4-home-fresh-startup`.
Baseline/dependency: `f44e32bf918a3d6f6c04613d6926ee39a92de741`, PR #249 (still open at fresh inspection). Fresh observed `origin/main`: `cce15704457a51ed587b30bd6d780e106da629f5`. No rebase, merge, reset or unrelated-worktree edit.

## Approval, ownership and disposition

The owner explicitly approved this Home-paired Living Room Puck admitting Hey Missy without proximity qualification and accepted that it may respond outside its Room. The canonical product decision was recorded first. Home's separate revisioned `paired_room` policy, grant and owned-retirement contract implement that exception; it is not fabricated calibration, a fixed score or a global gate bypass. Strict endpoints still require qualified trusted evidence.

Existing P-4/STD-6 own lifecycle and supported transport; 3-P-2/3-P-4/3-P-5 retain their complete original acceptance and are not globally closed by this consumer. The intended production binding is the Home-issued Device `c9dd86cfa9634330bf412e560969b7a9`, endpoint `ops-hermes-puck-bridge`, Room `living-room`, mapping `hey-missy` → Amanda. Code trusts authenticated Home approval, not a hard-coded UUID allowlist.

Local disposition: **done-with-deferred-gate**. Production consumer implementation, independent spec/code review and required local checks are complete. Tracker remains **review**. **Physical full-turn acceptance remains OPEN**; publication does not claim the user's complete spoken-turn goal has been reached.

Home/ops deployment belongs exclusively to the Home coordinator after parent source/recovery approval and custody transfer. Puck hardware belongs exclusively to the firmware custodian. This worker performed no host mutation, deployment, pairing, flash, live secret inspection or real microphone recording.

## Acceptance mapping

| Behavior | Local consumer evidence | Remaining gate |
|---|---|---|
| Paired Home startup without operator handle | Actual CLI starts/restarts session-less; no active claim marker; missing provider/approval denies; SIGTERM exits0 | Production service uses reviewed artifact/private configuration |
| Exact explicit admission before capture | Authoritative configuration selects only paired-room route; request has wake-word initiation and no acoustic fields; exact grant/mode/revision/ready checks | Live Home policy publish and physical wake admission |
| Strict-mode preservation | Missing policy still requires trusted calibrated evidence; malformed/null/unknown policy denies | Qualification remains required for strict endpoints |
| New physical wake has fresh authority | Paired previous ready claim closes before the next real grant; bounded follow-ups retain their logical conversation | Repeated physical wake/follow-up acceptance |
| Cold/failed-first-open recovery | Existing control close or exact HTTP200 own paired `closed` receipt confirms retirement; unknown/stale/403/404 does not; pending actual session blocks new claims until confirmed | Same deployed Home/bridge restart acceptance |
| Late policy/revocation/repoint | Follow-up/dispatch revision check denies and retires; 401 credential refusal persists, 403 policy/scope denial does not revoke credential; no replay | Household revocation/restore test |
| Genuine speech through Standard Amanda and audible response | Existing real STT/response path retained; static installed212 producer/receiver wire agreement verified by custodian | Real Standard capabilities/PCM format and actual physical STT/TTS audibility **not yet exercised** |

## Runtime smoke beyond tests

### Actual CLI startup and process restart

Temporary isolated configuration used synthetic local fixture credentials and a private temporary HOME; no live credential file was read. Actual `python -m puck_bridge --transport home` listened over loopback. First and second process `/wake-admission` requests returned `denied:1` and `denied:2`; no claim-state JSON was created; both SIGTERM shutdowns exited0. No operator handle was supplied and no audio was captured/uploaded.

Evidence: `/var/folders/cb/3pkc1ncx58j1xq63ktd8xftw0000gn/T/hermes-p4-startup-smoke-6d5ytw9j/` — `observed.json`, `process-1.log`, `process-2.log`.

### Actual Home API plus actual Puck HTTP consumer

Standalone local smoke used actual HomeApplication, HTTP server, SQLite credential/configuration authority and persistent ConversationGrantStore from the Home owner's paired-room implementation. It performed genuine isolated enrollment request/approval/consume and revisioned configuration, then actual HTTP API calls and actual Puck factory owned-close/strict admission. No successful Standard readiness or audio was fabricated.

Seven observed scenarios passed:

1. Enrollment and authenticated policy projection200, revision2.
2. Fresh Home-issued paired grant200 with no acoustic evidence.
3. Exact owned paired close is idempotent.
4. Unknown handle close is not confirmation and does not latch credential rejection.
5. Repeated claim ID returns409, not replay.
6. Policy removal returns strict provider-absence denial.
7. Known closed own claim can still be authoritatively retired after policy removal.

Evidence: `/var/folders/cb/3pkc1ncx58j1xq63ktd8xftw0000gn/T/hermes-puck-paired-api-smoke-o2sjowb9/observed.json`; execution log `artifact://3399`. This smoke did not restart Home itself and did not exercise Standard speech or the physical Puck. The Home owner separately owns same-SQLite/root runtime-reopen evidence.

Final post-review-fix rerun passed the same seven actual API scenarios:
`/var/folders/cb/3pkc1ncx58j1xq63ktd8xftw0000gn/T/hermes-puck-paired-api-smoke-ekcns3pt/observed.json`,
log `artifact://3481`.

Initial smoke interpreter attempts failed before API execution because the TUI environment lacked Home's `cryptography`, then `segno`. Running an isolated no-project environment with the declared Home dependencies resolved this; no product code or live configuration was changed to hide those setup failures.

## Observed automated verification

- Initial startup selection:13 passed,178 deselected,0.21s.
- Earlier full focused config/bridge/Home suite:324 passed,154.41s.
- Pre-review-fix latest focused suite:359 passed,154.78s; not final-reviewed evidence.
- Actual HTTP200/201/202 owned-close receipt regression:3 passed,161 deselected,1.61s.
- Critical pending-owner/first-open/status/mode selection:8 passed,157 deselected,1.64s.
- Final targeted resource/status/mode/pending-owner selection:7 passed,159 deselected,1.64s.
- A superseded sequential verification job was cancelled after the critical pending-owner finding; it is not a final result.

**Final repaired verification, sequential:** focused `tests/test_config.py tests/test_puck_bridge.py tests/test_puck_home_session.py` — **364 passed**,156.32s; full repository with only the two named Bash cases deselected — **2268 passed,3 skipped,2 deselected,6 existing websockets deprecation warnings**,348.31s. `git diff --check` passed. Combined505.57s log: `artifact://3510`. Interpreter: the existing Python3.14 environment in the separately owned prior 3-P-5 worktree, invoked with `python -m pytest` from this worktree; no changes to that environment.

The two previously reported macOS `/bin/bash`3.2 BASHPID deployment tests are precisely deselected, not rerun merely to reconfirm:

- `tests/test_ops_web_deployment.py::test_bootstrap_renders_and_installs_the_managed_service_and_caddy_site`
- `tests/test_ops_web_deployment.py::test_bootstrap_rejects_a_caddy_directory_only_mentioned_in_a_comment`

The exact three environment skips were separately observed with `-rs` (3 skipped,0.07s): `test_display_contract.py::test_coalesced_host_publisher_snapshots_reach_c_reducer` — ESP-IDF cJSON unavailable; `test_puck_firmware.py::test_respeaker_yaml_passes_esphome_config_generation` — firmware ESPHome environment not installed; `test_wake_sherpa.py::test_load_sherpa_engine_initializes_with_bundled_models` — optional wake extra absent. No unrelated deployment fix or check suppression was introduced. Firmware code is unchanged. Static installed212 callback/upload is stereo32LE16k, matching the existing channel1/gain4 conversion to mono16bit16k WAV; P-8 did not change that wire. Static compatibility is not intelligible physical STT evidence.

## Independent reviews and actual fixes

Independent specification review (adversarial, edge and structure): one contract-inventory clarification, `409 duplicate_claim`, now explicitly denies without replay or credential retirement. No other substantiated spec finding.

Independent code review used blind, edge-case, verification-gap and acceptance layers. Grounded findings and fixes:

- Exact close receipt required HTTP200, but the HTTP helper previously discarded success status. Require200; actual loopback201/202 matching bodies now remain unconfirmed.
- Real factory mode handoff lacked semantic assertion while runner fixtures supplied the mode themselves. Assert the actual returned mode, linking production grant metadata to new-wake fresh-claim behavior.
- A failed first open plus unconfirmed retirement lost the actual pending control owner on session-less startup. The existing factory now retains that actual session before persistence/open and blocks later fresh claims until retirement is confirmed, including cancelled-result paths. Regression proves no second fresh claim while unconfirmed and eventual fresh grant only after exact close confirmation.
- Failed healthy close RPC did not release local client/context before HTTP-confirmed replacement. Existing bounded session cleanup now owns that teardown; actual client/context assertions precede HTTP confirmation.
- `config.example.yaml` retained obsolete operator-handle instructions. Cleaned up the Puck caller documentation.

Observation about replacement handoff lacking immediate HTTP fallback was nonblocking: a subsequent physical wake already invokes authoritative fallback while capture remains closed. No speculative extra branch was added. The independent reviewer reread the complete amended diff and confirmed every targeted fix; all four layers completed with **no substantiated finding outstanding**. The reviewer executed no checks. Parent separately read the core diff and actual local API evidence before publication.

## Original rollout gate inventory (first paired-room turn now accepted below)

1. Reviewed Home paired-room implementation deployed through the coordinator's approved recovery plan; exact policy published through Home's revision-checked API.
2. Distinct legitimate Puck token and existing paired credential applied privately; no operator conversation handle.
3. Real Home→unmodified Standard Amanda capability and actual TTS PCM metadata/bytes/terminal evidence.
4. Awake physical Hey Missy → capture/upload → intelligible local STT → authorized Amanda turn → audible Puck response.
5. Repeated wake, bounded follow-up, exact stop, revocation/recovery and clean shutdown evidence where required by the owning stories.

No physical gate is marked done by local fixtures. Raw diagnostic capture remains OFF.

## Bottom-up main reconciliation (2026-10-19)

Merged updated PR #249 branch at `c0b318f447abe14f5bf6119a3a897354d18886fe`, which incorporates `origin/main` at `cce15704457a51ed587b30bd6d780e106da629f5`. This is a normal merge, not a rebase. Manual conflicts were limited to `sprint-status.yaml`, `story-index.yaml` and `surface-coverage-matrix.md`: preserved historical accepted recovery, the current paired-room review/physical gates, main's P-8 deterministic PCM evidence and the separate P-HOME-01 backlog row. No runtime code conflicted.

- Focused `pytest -q tests/test_config.py tests/test_puck_bridge.py tests/test_puck_home_session.py tests/test_puck_firmware.py`: **385 passed, 1 skipped** (159.32s).
- Full `pytest -q` with exactly the two Bash 3.2 deselections named above: **2269 passed, 4 skipped, 2 deselected**, six existing websockets warnings (333.15s).
- `git diff --check` passed. The additional main/P-8 Python firmware-boundary test needs this worktree's absent firmware environment; the existing native signed PCM fixture ran in the full suite.

Earlier actual CLI/API smoke and independent implementation reviews above remain the behavior evidence; this source-only reconciliation adds no physical acceptance or live operations. The newly built exact-head wheel supersedes the earlier `d5cb6c5` deployment artifact; deployment still requires both exact-source CI success and the coordinator's approved plan.

## Real physical STT failure and dependency correction (2026-10-19)

User-reported ground truth: physical wake, fresh Home grant, capture and upload worked, then faster-whisper **1.2.1** / PyAV **19.0.1** failed in `decode_audio` because `av.open` rejected `metadata_errors`. No Standard turn/TTS followed that failed STT. The known failure was not rerun merely to confirm it; no physical audio/transcript was read, copied or replayed by this worker.

Upstream evidence:

- [Latest released faster-whisper v1.2.1](https://github.com/SYSTRAN/faster-whisper/releases/tag/v1.2.1), confirmed through its latest-release API; [released decoder](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/audio.py#L46) still passes `metadata_errors`.
- [Official PyAV 19 changelog](https://pyav.basswood.io/docs/stable/development/changelog.html#v19-0-0) explicitly removes `metadata_errors` / `metadata_encoding` from `av.open`; [PyAV 18 API](https://github.com/PyAV-Org/PyAV/blob/v18.0.0/av/container/core.pyi) accepts them.

Added `av<19` to the existing optional voice extra and direct requirements; retained faster-whisper's transitive minimum instead of inventing a new lower bound. No Python lock file is present. No runtime workaround, exception suppression, admission, gain, VAD or recovery change.

Observed fresh private **Python 3.14.8** environment: `uv pip install '.[voice]' -r requirements-dev.txt` resolved **faster-whisper 1.2.1 / av 18.1.0**. `uv pip check` passed.

- Focused `python -m pytest -q tests/test_mic.py tests/test_puck_bridge.py`: **153 passed** (156.79s), including the new real decoder test, not a skipped optional test.
- Full `python -m pytest -q` with only the same two Bash 3.2 cases named above deselected: **2270 passed, 4 skipped, 2 deselected**, six existing websockets deprecation warnings (336.49s). `git diff --check` passed. Combined install/check log: `artifact://3689`.
- Beyond-test actual production `raw_stereo32_to_wav` → real `faster_whisper.audio.decode_audio` smoke: **1600 source frames → 1600 float32 samples**, exact signed expected values, compatible av18.1.0/faster-whisper1.2.1. Synthetic channel-1/gain-4 input only; temporary WAV explicitly removed, no microphone or model loaded.
- Independent spec and actual-code review: **no substantiated findings**. Reviewer checked real WAV/sample assertions, absent-package-only skip and both dependency entry points; reviewer ran no checks.

Deployment must apply compatible **av18.1.0** as well as the new wheel: `--no-deps` on the wheel alone leaves an existing av19 installation broken. The live custodian owns targeted dependency application, old-environment backup, graceful stop/authoritative owned-close confirmation if needed, and the next explicitly authorized physical window. Never erase recovery state or use 404 as retirement proof. Physical full-turn acceptance remains OPEN.


## Accepted paired-room first physical full turn — 2026-10-19

Amanda confirmed a reasonable spoken answer from the Living Room Puck. The coordinator supplied the combined content-free receipt: fresh Home grant → 388,960-byte capture → upload → nonempty STT → unmodified Standard Amanda → 112 TTS chunks, 685,568 PCM bytes at 24kHz mono delivered/drained → firmware PLAYING → IDLE → authoritative owned-close HTTP200 → zero active claims. Deployed TUI source was `6b288939adf9bfdc2954301f53c8fec68080b681`, faster-whisper1.2.1 / av18.1.0, Home `831e55e730ab49f3774ecc55a5bd111c993d2f1a`, firmware `21223b44dffb5df773760073bea11e460716d85c`. This docs-only publication does not change those deployed identities.

**P-4 / STD-6 approved paired-room first-full-turn physical gate: CLOSED.** Audible acceptance is Amanda's confirmation, not an inference from HTTP byte delivery. No transcript or physical audio is included here.

**Open defect/limit — automatic follow-up is NOT accepted:** follow-up seq1 automatically captured until the 8-second buffer limit and ended `NO_QUESTION_OR_AUDIO`. This is not successful follow-up evidence. `speaker_E=1` was observed but remains unattributed; do not claim speaker-fault absence or invent its cause. Repeated wake, bounded follow-up, exact stop, physical revocation/recovery, interruption/reconnect and clean shutdown remain separate unexercised acceptance where required. Strict endpoints still require trusted calibrated proximity; this receipt closes no complete 3-P story, strict-provider gate or P-7 hardware check.

The original broader STD-6 deferred regression gate remains open for these remaining cases. Tracker review status is retained with the scoped successful gate identified. No runtime code, dependencies, deployment or hardware changed in this evidence commit; prior source checks remain historical and new documentation-head CI is recorded in PR #254.

## Reconciliation after foundation/deployment merged — 2026-10-19

Merged origin/main5f92cddba4c76a11e1fc1797efe037937b90d078 (249 and250 landed). PR254 base is now main. Independent actual-runtime conflict review CLEAN: retained paired session-less startup, pending-owner retirement, exact close receipts, strict-provider boundary and av<19; no semantic runtime difference from accepted consumer. Manual conflicts: CHANGELOG, sprint-status, firmware README, home_admission.py, home_session.py, test_puck_bridge.py. Focused388passed160.94s; full2339passed/4skipped/2sameknownBashdeselections/6existingwarnings346.46s; diff-check passed. Deployed source remains6b288939; merge is not a live upgrade. Accepted first paired turn and open follow-up8s defect remain unchanged.

## P-3 deterministic no-speech completion repair — 2026-10-19

Existing ownership: P-3, preserving P-4/STD-6 authorization/recovery. Parent approved only the deterministic `!speech_seen` repair; the original **8 s no-speech / 8 s maximum speech / 800 ms debounce remain unchanged**. A proposed 3 s quiet timeout is an unanswered product question for Amanda and is not implemented. No live service, host, microphone or hardware was accessed.

### Source findings and implemented boundary

- Installed firmware212 and main5311 shared the same capture/response headers. Buffer capacity and no-speech deadline both represented eight seconds. The buffer callback incorrectly scheduled PCM upload even when speech had never been seen.
- Independent custodian review found the callback/deadline overlap too: deadline completion during `memcpy` could be followed by a late cursor increment. One atomic completion owner now publishes the finalized byte count before readiness; upload length, chunking, outcome and logging use that snapshot, not the live cursor. Deterministic small/full-buffer preemption regressions run with ASan/UBSan.
- A confirmed locally empty capture sends the existing single empty final POST, then directly polls for exact HTTP200 matching `{"seq": <seq>, "status": "silent"}`. It never requests `/response` media. Unexpected matching `complete`, wrong sequence/body, non-200 status, timeout or authority failure cannot open another follow-up.
- Normal silent status returns to wake without a refusal or new Unavailable indication. Production mailbox cleanup disarms local follow-up but leaves Home claim retirement on existing next-wake/shutdown/recovery ownership.
- `NO_QUESTION_OR_AUDIO` is a receipt classification, not a firmware error enum. Headerless HTTP204 from extensionless `/response` is rejected as unknown format by the actual linked micro-decoder and can become an announcement-source error. This is a **source-backed candidate**, not attribution of the earlier `speaker_E=1`; the raw error operation/tag was not retained. No speculative DMA/P-11 fix is included.
- Cached VAD true across restart is preexisting and can still select the speech path. Real speech whose STT is empty or exact stop still uses existing silent media handling. Actual silence versus echo/noise in the accepted receipt remains unknown; physical acceptance is not inferred from this fix.

### Observed local runtime before final checks

- Red regression: real-header buffer-before-tick case failed on the old full-buffer path (1 failed, 1.36 s).
- Repaired focused edges: `python -m pytest -q tests/test_puck_firmware.py tests/test_puck_bridge.py -k 'follow_up_no_speech or no_speech_completion_snapshot or known_empty_response or follow_up_speech_retains or empty_follow_up_control'`: **8 passed, 156 deselected, 5.24 s**. This was before a later direct losing-finalizer assertion and removal of a redundant Python-only media recorder; final broader results are recorded separately.
- Beyond tests, a throwaway native C++ program executed actual headers and configured YAML handoff against the production bridge HTTP receiver/mailbox through real loopback libcurl. Both deadline and buffer-before-tick cases observed **1 control POST, 0 uploaded PCM bytes, 0 STT calls, 0 new follow-up turns, 0 media requests**, matching silent status and native IDLE, local mailbox disarmed and claim lifecycle unchanged. The existing initial synthetic Session turn remained exactly one.
- Smoke uses synthetic platform/Session fixtures and simulated `millis`; it is not Home/Standard, physical speech, acoustic silence or wall-clock timing proof. The native harness is compiled against the current worktree; HTTP/control handling is real production code. No captured audio/transcript is retained.

### Prepared physical retest / rollback plan — NOT AUTHORIZED OR EXECUTED

1. Parent obtains Amanda's flash/retest approval and assigns the sole firmware custodian; no parallel observer, recorder, hardware probe or deployment actor acts during that window.
2. Preserve the custodian's existing private installed212 Home-mode factory image/manifest and real configuration without reading/copying secrets here. Custodian-reported rollback factory SHA256: `0794019a7ce7c6cab693e22e2010aaf7b5e91f40ad45e6c44ac4632dc408bbaf`; source `21223b44dffb5df773760073bea11e460716d85c`. Never erase Home recovery records to obtain a fresh turn.
3. Candidate source is the final independently reviewed PR head. It integrates already-merged **P-8 deterministic microphone conversion, P-9 RX lifecycle, and P-10 internal-model routing**, which installed212 does not contain, as well as this P-3 repair. This integration is part of the requested approval, not a P-3-only flash.
4. Custodian privately compiles the exact approved source with actual preserved settings, `puck_home_transport=true` and raw diagnostics OFF, records fresh image/timestamp/hash, and checks image identity before upload. **The example-only images built for local compilation are never flash candidates.** Bridge/Home admission must be available and verified before capture; no dummy credentials, synthetic handles, provider changes or direct fallback.
5. Under the approved awake window, observe one genuine wake/answer and then a quiet follow-up. Record only stage/counter/status evidence: the unchanged eight-second bound, single zero-byte completion, no follow-up PCM/STT/Hermes/audio request, status-only IDLE/wake return, no new refusal/Unavailable. A cached/current high VAD or nonempty transcription path must not be relabeled as proven no-speech completion.
6. If authorized separately, exercise spoken follow-up/exact stop and later fresh physical wake with existing Session/Profile and fresh-grant rules. These remain separate gates. For any speaker error retain only the sanitized component/operation/error classification, not URLs/tokens/audio/transcripts, before attributing or changing P-11 behavior.
7. On regression, custodian restores the exact preserved private212 Home-mode image/configuration, verifies build/identity and fail-closed startup, and coordinates existing authoritative claim cleanup if needed. No state deletion, re-enrollment shortcut, policy bypass or replay is allowed.

Physical quiet/follow-up acceptance and exact speaker-error attribution remain **OPEN**. This source-only repair does not reopen or erase the already accepted first paired-room full turn.

### Final observed regression and target builds

- Focused: `python -m pytest -q tests/test_puck_bridge.py tests/test_puck_firmware.py tests/test_puck_home_session.py tests/test_puck_bridge_shutdown.py tests/test_respeaker_i2s.py` — **368 passed, 170.92 s**, including every new native-header, sanitizer and production-mailbox case.
- Full: `python -m pytest -q --deselect=tests/test_ops_web_deployment.py::test_bootstrap_renders_and_installs_the_managed_service_and_caddy_site --deselect=tests/test_ops_web_deployment.py::test_bootstrap_rejects_a_caddy_directory_only_mentioned_in_a_comment` — **2349 passed, 2 skipped, 2 deselected, 6 existing websockets deprecation warnings, 401.81 s**. The two already-known macOS Bash3.2 failures were not rerun or suppressed in code. No skipped case is used as acceptance proof.
- An earlier focused attempt had **367 passed / 1 failed** solely because ESPHome rejected the compilation fixture's all-zero API key; the `&&` full run did not execute. Only the ignored synthetic fixture was corrected to a public nonzero example value. The final counts above include successful configuration validation; no source bypass or live credential was used.
- Direct: `venv-firmware/bin/esphome compile firmware/respeaker-lite/respeaker-lite.yaml` — **success**, config hash `0x9b0d9cbf`, build `2026-10-19 15:39:59 -0500`.
- Home: `venv-firmware/bin/esphome -s puck_home_transport true compile firmware/respeaker-lite/respeaker-lite.yaml` — **success**, config hash `0xf9859758`, build `2026-10-19 15:42:33 -0500`. Generated executable setup has Home mode `true` and `pcm_capture::setup(false, \"\")`, not just a commented/default diagnostics declaration.
- Both builds used ESPHome **2026.9.1**, ESP-IDF **5.5.5**, RAM **117127 / 341760 B**, flash **1862439 / 3932160 B**; combined compile duration **183.15 s**. Existing GPIO3-strapping and OTA-password warnings remain, with no related configuration change. Temporary example-only secrets and the throwaway Python smoke runner were removed after verification.
- **Example-only Home output hashes, NOT flash candidates:** factory SHA256 `046d3793dfac85120c0b786602d5dffdfa077892f2b7c53ba1aecc5aa5f99ac5`; OTA SHA256 `d6ee685e917ad0e5ad4f4acc67364dc2a151b3de862db4db959427a601f58871`. Custodian must privately rebuild the final approved source with preserved real settings before any separately authorized flash.

### Matrix audit and independent review

| Existing/narrow criterion | Executed regression coverage |
|---|---|
| Eight-second no-speech deadline / buffer wins | `test_follow_up_no_speech_discards_buffered_pcm_before_empty_upload` (deadline and buffer-before-tick); real native-to-HTTP smoke both orderings |
| Deadline preempts microphone copy; only one completion | `test_no_speech_completion_snapshot_survives_inflight_microphone_write` (small/full buffer, ASan/UBSan, explicit late finalizer) |
| Speech maximum / 800 ms debounce / normal media | `test_follow_up_speech_retains_capture_limit_debounce_and_media` (both endings); actual YAML actions execute against real headers |
| Exact stop / empty STT / one Session and Profile | `test_exact_stop_capture_is_silent_without_a_hermes_turn`, `test_empty_transcript_produces_no_turn`, `test_turn_runner_reuses_one_session_for_followups_and_stops_silently` |
| Known-empty status / authority / no new follow-up | `test_known_empty_response_confirms_only_matching_silent_status`; production HTTP control completion test; existing live-session admission/revision checks |
| Later physical wake / restart / no replay | `test_paired_room_each_physical_wake_retires_previous_ready_claim`, `test_unconfirmed_home_claim_close_is_retried_after_restart`, `test_cold_saved_claim_needs_owned_receipt_before_fresh_admission`, existing uncertainty/no-replay tests |

All listed tests ran and passed in the final focused/full runs; no skipped test backs a row. Independent firmware custodian SPEC/CODE review found the real in-flight quiet-byte leak (fixed with winner-only snapshot publication) and a redundant Python-only media recorder (removed). Re-review confirmed no new blocking runtime finding. All three build-workflow review layers completed: blind/edge reported no actionable issue; verification noted that a copied-but-uncommitted speech tail can be excluded at close, correctly triaged as the intentional immutable committed-byte boundary rather than a requirement to delay closure or read a mutable tail. Preexisting cached-VAD freshness remains recorded in the deferred-work ledger; physical attribution and acceptance stay OPEN.

### Latest main reconciliation and final verification — 2026-10-19

Normal merge `0f81c3b4cf8219c43dc1920abe92e9d70534e416` incorporates main `b3aba782abdfd32151562218855b09bbe98af474` (browser audio fallback PR244), preserving implementation commit `a71e422`. Only CHANGELOG conflicted; both independent entries were retained. Puck capture/response headers and YAML remained byte-identical to the independently reviewed implementation. No browser branch or live host was edited.

Fresh serial verification on that reconciled source supersedes the earlier counts above:

- Both actual Direct/Home firmware compiles passed again with the same documented commands, config hashes and memory/flash sizes. Direct build time: **2026-10-19 15:59:37 -0500**; Home: **2026-10-19 16:00:01 -0500**.
- Focused command above: **368 passed, 168.80 s**.
- Full command above, adding `-ra` for explicit skip reporting: **2370 passed, 2 skipped, 2 deselected, 6 existing warnings, 397.17 s**. Skips: `tests/test_display_contract.py:163` — ESP-IDF cJSON unavailable; `tests/test_wake_sherpa.py:216` — optional `wake` extra absent. Neither backs this repair's acceptance. The same two known Bash3.2 ops cases were the only deselections.
- Current **synthetic-example-only, never-flash** Home hashes: factory `1c1e6a18d452f2bd18a86e47cf5fe96ff8baaccb0735ccfe4190bac02b820777`; OTA `c08107189bd7dc89ee2792181ea82a97ffde0e0678998c8e2c04473384645582`. All temporary secrets and the toolchain symlink were removed afterward.
- No runtime source changed after those checks; the subsequent evidence commit records these observations only. No PR merge/flash/deploy/retest approval is implied. The sole custodian must privately build the final approved PR source under the prepared plan before any Amanda-authorized hardware action.

## P-2/P-3 fresh output handoff repair — 2026-10-19

### Physical retest that motivated this repair — NOT acceptance

The subsequently authorized a47ded642f51db168ca9ea526379ca63bd7cdaeb flash/retest supersedes the earlier unexecuted-plan state, not the failed quiet gate. Amanda heard an answer but reported no initial wake beep/indicator, including on earlier firmware212. Content-free coordinator/custodian receipts recorded:

- Primary: real grant, 1,024,000 bytes at the eight-second buffer limit, nonempty STT, Standard response, 58 TTS chunks and 325,376 source/delivered PCM bytes (24kHz mono S16). Primary VAD did not end speech before the limit.
- Quiet follow-up: capture-start receipt 43.944s; external media-IDLE receipt 43.964s; cached VAD true and `i2s_audio.speaker` error at 43.974s; VAD close 44.876s; 115,376 bytes uploaded as seq1, STT invoked, EMPTY_TRANSCRIPT, one silent media GET, no second Standard turn. The E preceded upload/STT/204, so it is not evidence for the prior HTTP204 error candidate.
- VAD was true in 45/57 telemetry polls, including quiet periods. These are cached-Boolean polls, not 57 fresh inferences. Numeric saturation, acoustic echo and the exact speaker error site cannot be inferred. Event times are observer receipts; the 20ms ordering alone is not proof of acoustic overlap.
- Final native state was IDLE/MWW running. Host readback retained one ACTIVE claim; no zero-claim/owned-close or later fresh-wake acceptance is claimed. Observers/tunnels stopped; no further live operation accompanies this source work.

The already accepted first paired-room full turn remains accepted. Quiet follow-up and current wake acknowledgement remain **FAILED/OPEN**, not silently narrowed or marked done.

### Approved implementation and local evidence

Owning intent remains P-2/P-3. [Repair spec](spec-p2-p3-fresh-audio-handoff.md) records the parent's explicit scoped approval. New branch `fix/p2-p3-audio-handoff` starts at fresh main `5b0ca37efb91f19bb8797454bf0825deb34c80f3`; PR255 had already merged, so this is not a duplicate stack.

- Local ESPHome2026.9.1 resampler override records canonical wheel SHA, upstream commit `0b2b16e664ecfc0add37f3435db1c2140b8a687e`, unmodified member hashes and complete upstream license. Generated build output is not patched.
- Graceful EOF drains upstream before TX finish and actual DMA stop. An accepted-playback generation is completed only after clean drain with an unchanged downstream monotonic fault generation. Immediate stop, failure and an absent callback cannot fake success. A review-found prior-fault baseline ordering bug was fixed so later fresh playback can recover.
- Cue capture requires a positive completed-generation receipt, not queue submission or sampled ANNOUNCING. Follow-up waits actual stopped/empty output and 200ms stable settle, then existing admission. Five-second handoff watchdogs use existing bounded refusal/recovery, never capture.
- VAD snapshot publication is synchronized and actual-invocation/epoch-qualified. Stop/reset/in-flight failures invalidate it; a full fresh probability window and bounded age are required. PCM still buffers during warm-up. Repeated/stale results cannot latch speech or debit silence; hard eight seconds starts at capture begin and is never extended by late speech. Gain4/channel1/cutoff0.05/current cue/volume/800ms remain unchanged.
- One DEBUG-only capture summary reports unique fresh probabilities/counts and selected post-gain S16 rails, with explicit availability flags. Rail fraction is samples at digital limits, not calibrated distance or proof of acoustic clipping. DEBUG speaker diagnostics retain exact site and actual returned `esp_err_t`, or explicitly `not_provided`; no PCM/transcript/credential/VERBOSE logging is introduced.

Preliminary focused command: `python -m pytest -q tests/test_puck_firmware.py tests/test_respeaker_resampler.py tests/test_respeaker_vad.py tests/test_respeaker_speaker.py` — **86 passed, 21.45s**, before the additional configured-action/review regressions below. Actual-source native harnesses cover buffered EOF/short cue/24kHz TTS, pending start+finish, passthrough, forced stop/fault recovery, real speaker failure sites/counters, stale/in-flight/partial/nonprogressing VAD, capture boundaries and diagnostic availability.

Beyond tests, a throwaway native C++ executable used actual capture/response/handoff/VAD-store headers and the configured YAML response handoff over real libcurl to the production bridge HTTP receiver/mailbox. Both deadline and buffer-first cases observed **one control POST, zero uploaded PCM bytes, zero STT calls, zero new follow-up turns, zero media GETs**, matching silent status, native IDLE and disarmed mailbox; the existing initial synthetic Session turn remained exactly one. Runtime duration **1.90s**. Synthetic output/model/Session fixtures and simulated clock make this local contract proof, not hardware/Home/Standard/acoustic or wall-clock evidence. No raw microphone or real credentials were used.

### Final observed local verification and independent review

The final runtime diff passed independent blind-code, edge-case, verification and sole-custodian SPEC/CODE reviews with **no outstanding substantiated findings**. Fixed findings include prior-fault/start ordering, precise ring-buffer allocation attribution, valid generation zero, actual YAML/URL/status execution, IDLE-before-error ordering, late faults after SILENT/READY, stop-request versus actual cleanup acknowledgement, and undrained READY after follow-up ownership had already cleared. Cleanup now waits for both sources IDLE plus stopped/empty resampler/TX; five seconds without acknowledgement reports Unavailable once and remains capture-closed until actual later shutdown. A 30-second **lack-of-positive-output-progress** watchdog handles decoder/source failure or a missing IDLE; it does not cap valid long TTS. Matching authoritative SILENT stays quiet even after a legitimate exact-stop HTTP204 decoder failure; COMPLETE/unknown/unavailable cannot authorize follow-up on that failure path.

Final focused command, using an isolated worktree-owned Python3.14.8 environment installed from `requirements-dev.txt`:

```bash
env PYTHONPATH=. venv/bin/python -m pytest -q \
  tests/test_mic.py::test_faster_whisper_decodes_a_real_wav_when_voice_is_installed \
  tests/test_puck_firmware.py tests/test_puck_audio_wiring.py \
  tests/test_respeaker_resampler.py tests/test_respeaker_vad.py tests/test_respeaker_speaker.py
```

**123 passed, 33.81s**, including the real faster-whisper1.2.1 / av18.1.0 WAV decode, not a skip or mock. The five native/firmware modules alone had already passed **122 tests, 27.51s** on the same final source. The final standalone native/libcurl/production-bridge smoke again passed **both** deadline and buffer-first scenarios with the zero-audio/zero-STT/zero-new-turn/zero-media invariants above. Its clock/output/model/Session are isolated fixtures, not a real Home grant, Standard turn, wall-clock or acoustic proof.

```bash
env PYTHONPATH=. venv/bin/python -m pytest -q -ra \
  --deselect=tests/test_ops_web_deployment.py::test_bootstrap_renders_and_installs_the_managed_service_and_caddy_site \
  --deselect=tests/test_ops_web_deployment.py::test_bootstrap_rejects_a_caddy_directory_only_mentioned_in_a_comment
```

**2466 passed, 2 skipped, 2 deselected, 6 warnings, 392.38s.** Skips: `tests/test_display_contract.py:163` — ESP-IDF cJSON unavailable; `tests/test_wake_sherpa.py:216` — optional `wake` extra absent. Neither backs this repair's acceptance. The two deselections are the previously known macOS Bash3.2 deployment cases, not new failures; they were not rerun merely to reconfirm them. Existing warnings concern deprecated `websockets.legacy` / `ConnectionClosed` accessors. `uv pip check --python venv/bin/python` reported all 69 installed packages compatible. `venv/bin/python -m build --sdist --wheel` passed, producing the normal 0.13.1 distribution artifacts.

An immediately preceding full run using a reused older environment observed **1 failed, 2465 passed, 2 skipped, 2 deselected**: the existing real decoder regression exposed that environment's PyAV19, which violates current `av<19`. No dependency pin, production source, test or deselection was weakened. The separate clean environment resolved av18.1.0 and passed the decoder plus full suite above; no other worktree environment was modified. An earlier ESPHome8.2 attempt exposed the obsolete second-model-constructor assignment (removed) and incompatible framework StaticTask API; actual9.1 is now the explicit configuration/firmware-extra minimum. Those failed attempts are not reported as successful builds.

```bash
venv-firmware/bin/esphome compile firmware/respeaker-lite/respeaker-lite.yaml
venv-firmware/bin/esphome -s puck_home_transport true compile firmware/respeaker-lite/respeaker-lite.yaml
```

Both **actual ESPHome2026.9.1 / ESP-IDF5.5.5 builds passed** on the final reviewed source:

| Build | Config hash | Build time (−0500) | RAM | Flash |
|---|---|---|---|---|
| Direct | `0xd0336ad8` | 2026-10-19 17:58:05 | 117487 / 341760 B | 1867295 / 3932160 B |
| Home | `0x5447e3bd` | 2026-10-19 17:58:20 | 117487 / 341760 B | 1867299 / 3932160 B |

Generated executable setup confirms Home transport `true` and `pcm_capture::setup(false, "")`; raw PCM diagnostics were OFF. Existing GPIO3-strapping/OTA-password warnings remain. **Public synthetic-example Home images, NEVER flash:** factory SHA256 `08b4ca14cd83f6ca3df97ddd17cc846745e470e44746aef2feb2be860efb8420`; OTA `daf2c3b3719eea1b5391a7d24f505c5038a395fc21c1925b4c88ca6481e4db21`. Temporary example secrets, throwaway smoke runner and the toolchain symlink are removed after verification. No real credentials, microphone, host, live service, deployed bridge or hardware were accessed.

| Scoped acceptance | Exercised local consumer evidence | Still physical OPEN |
|---|---|---|
| Admitted wake cue before capture | Actual resampler source; configured fast-tick actions require positive completed generation, stopped source/TX and fresh VAD | Audible cue on the real speaker, prior to question capture |
| Follow-up after drain/settle | Actual configured 100/250ms actions, source/TX tail, detector stop and 200ms stable settle | Actual playback tail/echo and microphone transition |
| Fresh bounded speech/silence | Production invocation/window/snapshot helpers, concurrent epoch/reset, generation-zero/stalled/partial cases, hard-eight-second and 800ms capture regressions | Fresh real model probabilities/noise floor and primary end-of-speech |
| Quiet final without processing/media | Both real loopback HTTP/mailbox scenarios: one empty control, zero PCM/STT/new turn/media GET | Amanda-quiet follow-up on installed candidate |
| Content-free diagnostics and finite fault handling | Real speaker-source fault injection/site assertions; numerical summary/rail tests; real configured silent/fault/ack/no-ack/long-progress paths | Exact physical speaker fault attribution and numeric capture summaries |

No skip backs a scoped acceptance row. This is a locally complete, independently reviewed software repair with deferred physical acceptance, not a claim that a47's failed quiet-follow-up or absent wake acknowledgement passed.

### Next physical gate — requires parent GO, NOT executed here

The sole firmware custodian must preserve the current private a47 Home image/settings plus the existing212 recovery image, privately rebuild the final approved PR source with real preserved settings, Home transport true and raw diagnostics OFF, and report exact firmware/config/image hashes before any separately approved flash. The public example-only compile output is never a flash candidate. No other observer/host actor acts concurrently.

Under a later approved awake window, confirm fail-closed startup, genuine wake/grant, audible initial cue before capture, a question ending before the hard buffer limit when fresh VAD permits, full audible response, and quiet follow-up: actual drain/settle, fresh generations, no false speech, one empty control, no PCM/STT/new turn/media GET, and wake-listening. Retain only bounded numeric/site/status diagnostics to distinguish fresh-high VAD/rails from stale inference and attribute any speaker fault. Genuine follow-up/exact stop, later wake and revocation/recovery remain separate acceptance unless actually exercised. Rollback uses the custodian's preserved approved image/config; never erase Home state, bypass admission, use fixed scores or replay.

## P-2/P-3 audible cue, VAD end-of-speech and post-reboot upload repair — 2026-10-19

### Physical retest of 17a1eb1 that motivated this repair — NOT acceptance

Amanda heard nothing: no wake cue, no answer. Content-free receipts: Home grant 23.562 → cue drain gen1 23.860 → capture open 23.862 (the 17a1eb1 cue barrier worked). Fresh VAD during capture: 260 generations, mean 0.6087, max 0.9922, post-gain rail fraction 0; capture ran to the eight-second deadline. `pcm_capture` W1/E1 at 39.180, brief refusal tone, wake resumed, no speaker fault. Bridge journal (coordinator, matched to installed source): the receiver logged its busy-stream drop at `receiver.py:739` for this capture; no auth/timeout/size/reassembly warnings. The bridge process predated the reflash and had answered earlier captures.

### Root causes

1. **Inaudible cue/refusal (amplitude verified mathematically; not proven the sole acoustic cause).** `tools/generate_sounds.sh` applied gain 0.25 to lavfi `sine` (amplitude 1/8), so both assets peaked at −30.1 dBFS before the 0.40 media volume. Regenerated with gain 4.0: `heard.wav` 80 ms, peak −6.02 dBFS, RMS −10.5 dBFS; `refused.wav` 360 ms, peak −6.02 dBFS, RMS −9.3 dBFS. Frequencies, durations, fades and 16 kHz mono S16 are unchanged.
2. **Run-on capture.** With VAD `probability_cutoff: 0.05`, fresh VAD (whole-capture mean 0.61, max 0.99) latched speech until the deadline, so no 800 ms silence debounce completed before the deadline. The retained summary does not show a per-frame or quiet-only distribution. Restored the model default 0.5. Gain 4, channel 1, eight-second bounds and 800 ms debounce unchanged. Whether 0.5 ends real turns promptly in this room is a physical-retest question.
3. **Lost upload.** The Puck's wake sequence is a RAM counter that restarts at 0 on boot. `ResponseStream.expect()` refused any non-advancing sequence even on an idle stream, so the long-running bridge answered the final (64th) chunk of the post-flash capture with 503 and the misleading "previous answer is still streaming" log. The physical observer retained only `pcm_capture` W/E counts (W1/E1), not the numeric status or chunk; chunk 63 / HTTP 503 is the source-mapped guard reproduced in the native/libcurl harness below, consistent with those counts and the host drop log. Removed the sequence floor (every in-flight state is still refused); the drop log is now WARN with the exact busy reason and sequence. The firmware now emits a WARN summary naming the first failed chunk and HTTP status (−1 = no response).

### Local evidence

A throwaway native harness compiled the actual `pcm_capture.h` with a libcurl `http_request` stand-in against the real `make_handler` receiver over loopback, with a prior answered seq 7 delivered: base bridge → 64 POSTs, last 503, `Wake capture 0 FAILED at chunk 63/64 with HTTP status 503`, zero transcripts; fixed bridge → last 200, delivered, one transcript. Regressions: `test_a_rebooted_puck_restarting_its_sequence_is_answered_not_dropped` (seq 0 and equal seq; fails on the old guard), `test_busy_stream_still_refuses_a_new_capture_with_its_reason`, `test_full_capture_upload_failure_names_chunk_and_http_status_at_warn`. Custodian read-only review approved the runtime change after these evidence-wording fixes. The bridge fix only takes effect after a live bridge cutover; firmware alone cannot clear the deployed sequence floor. Physical cue audibility, VAD end-of-speech timing and full turn remain **OPEN** until a separately authorized retest.

## P-2/P-3 response re-fetch and admission-timeout repair — 2026-10-20

### PR257 (85cb984) physical retest — NOT acceptance

Amanda heard the wake cue (cue level fix confirmed). Ops journal (Mac/ops clocks within 0.2 s): 00:57:10.33Z a 70 ms sound and one `puck_response` W, wake resumed, no bridge INFO line; 00:57:21.93Z `Home claim admitted`; 00:57:32.76Z STT (5.08 s audio); 00:57:41.50Z second concurrent `/response` fetch refused 409; 00:57:42.88Z device closed after 0 bytes, first_pcm_seconds 8.93; 00:57:43.19Z ResponseStreamError, no replay.

### Root causes

1. **Lost answer (confirmed in source).** micro-decoder's `esp/http_client.cpp` (ESPHome 2026.9.1 `audio_http`) waits 5 s for response headers, then opens a fresh GET for the same URL. The bridge sends no headers until the first audio format exists (WAV header needs the rate), here ~8.9 s. Two fetches for one seq were waiting; when audio arrived, the stale one claimed the single reader and wrote into a socket the device had closed (0 bytes → terminal), and the live one got 409. Fix: each fetch registers a generation; only the newest may claim the reader, and superseded fetches close without a reply or abandoning the stream.
2. **Wake refused after the cue sound, no bridge INFO (inference from source and timing; the W text was not retained).** Device `http_request.timeout` was 5 s; the bridge's Home wake admission (retire previous claim + open a new one) is bounded at ~31 s and the only INFO line is on success. The 11.6 s gap from 10.33 to `Home claim admitted` at 21.93 matches a device-side 5 s admission timeout (`puck_response` W "admission service unreachable"), a short refusal sound, and a late grant the device never used. Fixes: device timeout 15 s (upload chunks share this bound); the bridge logs every admission result with seq and elapsed (WARN past the device timeout); the device W includes elapsed ms.
3. **8.9 s to first PCM** is measured from the bridge's expect at upload completion; STT finished at 32.76 and the first audio format arrived ~8.7 s later, i.e. Hermes answer + TTS latency. Not changed here.

Regressions: `test_a_device_re_fetch_before_first_audio_supersedes_the_waiting_fetch` (fails on the old code), `test_every_wake_admission_result_is_logged_with_elapsed_time`, `test_device_request_timeout_covers_the_bridge_admission_contract`. Physical answer playback remains **OPEN**.

## P-2/P-3 empty-wake repair: speech wait, silent resume, claim close — 2026-10-20

### PR258 (e31a406) physical retest — NOT acceptance

Admission 0.62 s (timeout fix held). STT received 1.077 s of audio, VAD-filtered to nothing; empty transcript → silent terminal (empty_capture). Afterwards media IDLE but micro_wake_word stopped (4/4 polls over 8 s, minutes later); paired_room claim opened 01:45:29.99Z still ACTIVE. No fetch/409.

### Root causes (from source; exact device log lines not retained)

1. **~1 s capture.** `wake_capture::tick` let pre-speech silence end an *initial* wake (only follow-ups waited for speech). With cutoff 0.5, 800 ms of breath after the cue ended the turn. Now both capture kinds require speech before the silence debounce; no speech ends empty at the 8 s deadline.
2. **Wake never resumed.** `/response` answered 204, the HTTP source failed before PLAYING, so ESPHome's speaker_source never made it the pipeline's active source. `media_player.stop` targets only active/last source, so the HTTP source stayed ERROR, `drained()` stayed false and READY_TO_RESUME could never restart wake. The old harness hid this by forcing sources IDLE. Cleanup now STOPs any errored source directly (micro-decoder `stop()` moves FAILED→IDLE).
3. **Claim left ACTIVE.** Paired-room claims were only retired at the next wake. An empty initial wake now closes its claim after the silent terminal is published, serialized with wake admission.

Regressions (all fail on e31a406): `test_initial_wake_waits_for_speech_before_silence_can_end_it[True/False]`, `test_configured_silent_204_source_error_is_stopped_directly_and_wake_resumes`, `test_paired_room_empty_wake_capture_closes_its_claim_after_silent_terminal`. Physical empty-wake recovery and full turn remain **OPEN**.

## P-2/P-3 follow-up echo guard, quiet unanswered follow-up, first-audio budget — 2026-10-20

### PR259 (da68ab5) physical retest — NOT acceptance

seq0: admission 0.53 s; capture waited through the pause and ended on VAD (381,616 B); STT 2.98 s; three superseded fetches (re-fetch fix held); first PCM 18.95 s; 231,680 B (4.827 s, 24 kHz mono S16) delivered, sha match; PLAYING 02:38:35.42 → IDLE 41.29 (5.87 s); COMPLETE confirmed. Amanda: slight crackle, unsure it finished. seq1 follow-up while Amanda stayed quiet: 742,744 B, STT 5.80 s (VAD removed 3.72 s), non-empty transcript (not retained); no first audio, turn abandoned at 20 s; device played the refusal. Wake resumed; claim closed.

### Findings

1. **Crackle at the start of the answer (Amanda) — likely cause, inferred from source.** No truncation: the "24 chunks / 4471 ms" figure is the seq0 *upload* line, playback lasted 5.87 s for 4.827 s of audio, delivered = source sha, COMPLETE. Superseded fetches are closed before any byte is written, so they cannot inject a stale header or partial samples, and each accepted fetch writes exactly one 44-byte WAV header followed by contiguous PCM (format 24 kHz mono S16 matched). The bridge however sent the WAV header *before* waiting for its 1.5 s prebuffer, so the Puck's decoder parsed the format and started the resampler/speaker with no PCM behind it: playback began by underrunning. Fix: the WAV header is now written together with the prebuffered audio. An amplifier pop on speaker enable is not ruled out (the cue shares the path without a reported crackle). Physical confirmation needed.
2. **Follow-up false capture / refusal.** The mic opens ~200 ms after the answer drains, and VAD treated short activity as speech. Follow-ups now require 300 ms of continuous VAD speech before they count as spoken (initial wakes unchanged). The 20 s first-audio budget was below observed Hermes latency (seq0 needed 17 s after transcription), so seq1 was most likely still being answered; the bridge first-audio budget is now 25 s (reader 28 s, under the Puck's 6 × 5 s header window). A follow-up turn that still produces no audio now ends with a silent terminal (`needs_home_admission`), and the firmware resumes wake without the refusal tone.
3. **19 s to first PCM.** Upload confirmed 02:38:15.36 → faster-whisper lazy model load + HF revision check 15.49–16.18 (~0.7 s, first capture after start only) → STT done ~17.2 → Hermes LLM + TTS first audio 34.26 (~17 s). Bridge-side cost ≈ 2 s; the rest is Hermes. Not changed beyond the budget.

Regressions (fail on da68ab5): `test_wav_header_is_held_until_the_prebuffer_is_ready`, `test_follow_up_needs_sustained_speech_not_an_echo_blip[100]`, `test_unanswered_follow_up_ends_silent_not_unavailable`, `test_silent_terminal_needing_home_admission_resumes_without_refusal`, `test_response_format_budget_covers_turn_budget_inside_device_header_window`. Physical acceptance remains **OPEN**.

## Home wake denials without a reason — 2026-10-20

After the #260 (88c6da3) deploy, two wakes (11:07:28.748Z, 11:40:10.477Z, seq 0) were denied in ~0.05 s with 0 active Home claims and no journal reason. Source review: with a confirmed `retired` marker the bridge starts with `home_claim_retired=True, close_confirmed=True` (server.py), so `_admit_home_wake` goes straight to `HomePuckSessionFactory.admit_wake`, which asks Home for the device configuration. #260's quiet follow-up path and the marker leave no local state that denies every wake. The only no-network denial is a concurrent admission holding the lock. A transport failure would have logged a WARN, and none was logged, so the cause was one of the factory's silent reasons, each of which follows a Home HTTP reply: a non-401/403 HTTP error (`home_service_unavailable`), `wake_mapping_unavailable`, `invalid_admission_policy`, `claim_denied` or `claim_handle_reused`. Which one is not recoverable from the existing journal. Every denial now logs `Puck Home wake admission denied (<reason>)` at WARN; factory reasons appear as `home:<reason>`, with the HTTP status and Home error code. The next denied wake will name its cause.

## PR260 retest #2: claim left active after empty follow-up; patchy playback — 2026-10-20

- **Claim not retired.** The paired-room claim was retired only for an empty *first* capture (#259) or at the next wake's admission. Every other conversation end (empty or silent follow-up, window expiry, failed turn, unanswered follow-up) left it active. eeuVbnKJ stayed `active`/`response_ready` for 30+ minutes. The earlier expiry case looked correct only because the next wake retired it. Fix: `submit_transcript_outcome` retires the claim as soon as `HandsFreeCoordinator.on_wake` returns, which happens only when the conversation is over. It is a no-op if the claim is already retired, and it is serialized with admission.
- **Follow-up guard vs bridge VAD.** Firmware VAD (micro_wake_word `vad.json`, 5-stride sliding window, cutoff 0.5, gain 4) saw at least 300 ms of continuous speech where faster-whisper's Silero VAD found none in 2.4 s. These are different models on different signal paths. Per-capture firmware probabilities for that capture were not retained, so the guard was **not** retuned blindly. A false positive now costs one upload and ends silent with the claim retired.
- **Patchy playback.** The bridge side (seq0: 21.5 s produced at ~1.02× real time, a 3.29 s producer gap, 1.5 s cushion) could run the Puck dry. The prebuffer is now 3.5 s; short answers are unaffected because the prebuffer releases when the source completes. On the device side (seq1: bridge sent faster than real time, yet PLAYING lasted 7.75 s for 6.08 s of audio), the radio ran ESPHome's default LIGHT Wi-Fi modem sleep, which batches streamed TCP delivery. It is now `power_save_mode: none`. About 1 s of the 1.7 s difference matches the start/stop overhead also seen for seq0 on PR259 (5.87 s for 4.83 s). The bridge now logs a DEBUG cadence line per chunk (bytes, gap since the previous chunk, bridge queue). Physical confirmation is needed.

## 6a15d68 retest: long answers refused, mapping denials — 2026-10-20

The short answer played smoothly. The long answer ("tell me about the planets") ended in the refusal tone.
- **Prebuffer stall counted from upload.** `ResponseStream` anchored the producer-stall clock at `expect()`, which is upload completion. STT plus Hermes thinking therefore consumed the 20 s prebuffer stall budget, so seq0 died with `prebuffer stalled` at source_bytes 0 while its format was already declared. The clock now starts when the answer's audio is announced (`begin`).
- **`audio_start` ended the first-audio budget.** The turn switched to the mid-stream stall budget on `audio_start` even if no PCM had arrived yet. It now keeps the 25 s first-audio budget until real PCM arrives.
- **Remaining limit (not fixed):** the Puck's audio reader gives up 30 s after its first `/response` fetch. An answer whose first 3.5 s of audio is not ready by then will still fail. A "thinking hold" would need the bridge to send the WAV header plus quiet keep-alive audio before the real answer, which reintroduces the start-of-answer underrun the #260 fix removed, so it needs a separate decision. Whether Hermes streams TTS per sentence cannot be seen from the bridge. The data (seq1 got no PCM within 25 s; the short seq2 got its first PCM at 6.77 s) suggests TTS of long replies is not sentence-streamed upstream [INFERENCE].
- **`home:wake_mapping_unavailable`.** Home denies with this reason when the device configuration has zero or more than one mapping whose NFKC-casefolded phrase equals the detected wake phrase (`home_admission.py` `_matching_mapping`). The Puck runs public A/B models "Hey Bestie" and "Hey Skippy" alongside "Hey Missy". A false or A/B detection of a phrase that Home does not map produces exactly this denial [INFERENCE: the phrase was not logged]. The reason now carries the normalized phrase and the match count.
- **Log level.** Set `PUCK_BRIDGE_LOG_LEVEL` (default INFO) to change the bridge's log level; DEBUG enables the per-chunk cadence lines.
- **Follow-up silence guard:** unchanged (low priority, no per-capture firmware probabilities retained).

### Producer-side evidence and the thinking hold — 2026-10-21

Read-only on the Home host (CaticornQueen): the Home runtime drives the Hermes turn and forwards text deltas to the streaming TTS sidecar. That sidecar is `qwen3_streaming_server.py` on :8767, `mode=stream format=pcm`, with sentence-sized requests of 37–84 characters. Its log (local time UTC−5) and Home's safe-event export show:

| Failure | Home turn started | First TTS request | Outcome |
|---|---|---|---|
| 22:26:52Z | 22:27:05Z | none before the bridge gave up | no text reached TTS |
| 22:36:29Z | 22:36:37Z | none before the bridge gave up | no text reached TTS |
| 02:00:05Z (planets) | 02:00:20Z | 02:00:44.7Z; first audio 0.68 s later | the bridge and Puck had already failed at 02:00:45.27; TTS logged `synthesis_aborted` / client disconnected |
| 02:00:53Z | 02:01:04Z | none before the 25 s abandonment at 02:01:30Z | no text reached TTS |

The TTS server was up throughout (health lines every 60 s, busy=0). When called, it streamed first audio in 0.38–0.68 s. **Streaming TTS is already in place and was not the gap.** The gap is the LLM: on these questions it took 25 s or more to yield its first speakable text. The bridge's 20–25 s first-audio budgets and the Puck's ~30 s header window then turned that slowness into a refusal. No TTS error was found, apart from the abort that followed the bridge giving up. The LLM's own logs are not on this host.

Fix in this branch (no duplicate TTS streaming):
- If the answer is not ready 2 s after a `/response` fetch, the bridge commits the response: a WAV header (24 kHz mono S16), a soft two-pulse "thinking" earcon (−20 dBFS, 0.32 s), then real-time silence until the answer's first PCM. The device's per-attempt header timeout is never reached.
- The first-audio budgets are now 60 s for the turn and 63 s for the reader. These are bounded by how long a person will wait, not by the device's header window.
- An answer that turns out silent ends the stream cleanly. A real failure still ends it without EOF, which plays the refusal.
