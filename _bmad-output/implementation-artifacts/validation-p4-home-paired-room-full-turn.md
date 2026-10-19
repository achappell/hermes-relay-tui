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
