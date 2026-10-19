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

## Open physical and integration gates

1. Reviewed Home paired-room implementation deployed through the coordinator's approved recovery plan; exact policy published through Home's revision-checked API.
2. Distinct legitimate Puck token and existing paired credential applied privately; no operator conversation handle.
3. Real Home→unmodified Standard Amanda capability and actual TTS PCM metadata/bytes/terminal evidence.
4. Awake physical Hey Missy → capture/upload → intelligible local STT → authorized Amanda turn → audible Puck response.
5. Repeated wake, bounded follow-up, exact stop, revocation/recovery and clean shutdown evidence where required by the owning stories.

No physical gate is marked done by local fixtures. Raw diagnostic capture remains OFF.
