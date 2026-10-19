# 3-P-5 — fail closed for revoked or unavailable identities

Date: 2026-10-18. Owning spec: [3-P-5](spec-3-p-5-fail-closed-identity.md).
Branch: `feat/3-p-5-fail-closed-identity`.
Worktree: `.worktrees/3-p-5-fail-closed-identity` under the main repository.
Baseline: `95809e14c83f0e343a4d730d96405b39fe844e7e` (`origin/main` when created).

## Scope and disposition

Existing Story 3.5 and surface 3-P-5 only; all five original criteria remain intact. Local implementation/evidence is distinct from household rollout. No flashing, deployment, pairing, household reboot, live credential inspection or real microphone capture occurred in this workstream. The separate hardware owner must use reviewed source and legitimately provisioned configuration; the example-secret compilation artifact is **not** a household flashing artifact.

Local disposition: **done-with-deferred-gate**. Spec implementation is complete and independently reviewed; sprint tracker remains **review**, not hardware-complete.

Home mode requires a current mapping-bound wake grant, its existing `configuration_revision`, and a ready Home session. An operator-supplied handle has no proven grant revision and cannot authorize capture by inferred freshness. Revision mismatch, including same-ID Profile repoint, retires the old claim. Fresh admission still requires P-4's trusted calibrated provider; production wiring intentionally has none. No Home protocol fields, admission policy, fallback Profile or confidence/fixed-score/touch substitute were added. Direct P-1 degraded policy is unchanged.

## Original acceptance mapping

| Original criterion | Observable local evidence | Remaining gate |
|---|---|---|
| AC1: revoked/unavailable mapped Profile shows visible Unavailable/Disconnected before capture | Actual identity/response/capture headers invoke the solid-Unavailable indicator before denied dispatch. Native harness proves LED on, capture false, zero bytes/uploads for mapping denial, stale sequence, missing response and absent bridge. Actual Home-mode firmware compiles the GPIO21 sink. | Physical orange LED appearance and visibility in assembled Puck unverified. Audio/logs are not substituted for this visual gate. |
| AC2: unverifiable mapped Profile produces no capture/audio payload/Hermes turn | Native real-header capture/write/upload paths remain closed. Loopback bridge smoke feeds actual admission responses into that compiled harness and attempts denied dispatch: zero captured bytes, upload attempts and Home prompts in every denied scenario. | Real Home credential/enrollment and physical capture acceptance remain external gates. |
| AC3: other valid mappings are never substituted | Unavailable Missy request creates no Other claim. An intentional later Other wake obtains its own verified mapping-bound handle. Mapping removal/repoint is denied at wake, follow-up and turn-dispatch boundaries. | Full 3-P-3 mapping propagation/version-isolation acceptance is separate; this story does not close it. |
| AC4: powered revoked credential remains denied despite reachability | Confirmed Device-authorized 401/unauthorized persists a private digest-only rejection. Same credential remains denied after runner/bridge restart and restored Home reachability, with no new Home request or prompt. | Actual household revocation/physical operation not exercised. |
| AC5: potential availability does not silently reactivate before verified recovery | Restart, upload 200 and restored configuration do not clear refusal/admit capture. Re-enrolled-credential fixture without trusted admission remains denied. Only explicit fresh configuration/grant/ready-session flow clears Home unavailable indication. An old generic bridge-handle unauthorized error with a valid Device credential does not revoke that credential. | Home-owned enrollment UX remains 3-P-6; no production calibrated provider exists. |

Home 403 forbidden/claim denial, stale mapping/configuration, 503 and transport failure do not permanently revoke credentials. Only confirmed invalid/revoked Device credential errors create a credential-scoped marker. Generic bridge `unauthorized` is cross-checked through the existing Device-authorized configuration endpoint because a handle mismatch can use the same code. Home's documented expiry policy requires re-enrollment; valid renewal-window credentials are not retired merely for entering that window.

## Observed deterministic checks

- **Final reviewed focused suite:** same three Puck modules, `--basetemp=/tmp/hermes-3p5-final-focused` — **277 passed**, 158.16s.
- **Final required repository suite:** `venv/bin/pytest -q --deselect=tests/test_ops_web_deployment.py::test_bootstrap_renders_and_installs_the_managed_service_and_caddy_site --deselect=tests/test_ops_web_deployment.py::test_bootstrap_rejects_a_caddy_directory_only_mentioned_in_a_comment --basetemp=/tmp/hermes-3p5-final-full` — **2223 passed, 2 skipped, 2 deselected, 6 existing websockets deprecation warnings**, 351.39s. No failures in the exercised suite; the two known Bash cases remain explicitly excluded. Final focused/full/build/`git diff --check` log: `artifact://3007` (combined 525.30s).
- Initial focused Puck suite: `venv/bin/pytest tests/test_puck_home_session.py tests/test_puck_bridge.py tests/test_puck_firmware.py -q --basetemp=/tmp/hermes-3p5-focused` — **266 passed**, 164.65s.
- Revision-bound focused suite, same modules with `--basetemp=/tmp/hermes-3p5-revision-focused` — **272 passed**, 163.15s, including same-ID Profile-repoint and operator-handle denial.
- Final added consumer cases: Home bridge-unauthorized confirmation (four credential responses), production startup with/without persisted rejection, actual-header absent-bridge refusal, and semantic board/pin configuration — **8 passed**, 1.10s.
- Required full repository invocation, with only the two user-reported macOS Bash 3.2 bootstrap cases deselected: **2217 passed, 2 skipped, 2 deselected, 1 failed, 6 warnings**, 539.54s. The sole failure was the existing ESPHome config-generation subprocess timing out at 180s after its version banner; standalone actual Home-mode config and compile succeeded separately. This invocation is **not all green**. Full log: `artifact://2942`.
- Environment diagnosis after that earlier failure: isolated config test also timed out with `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` (`artifact://2948`). A 15-second faulthandler trace located the hang while loading PyYAML's native C extension under Python 3.13, before firmware configuration parsing. Recreated only the ignored firmware environment with repository-documented Python **3.12.15**; PyYAML 6.0.3 C-extension import, Home-mode config, the existing config-generation test inside both final suites, and actual firmware compilation then passed. No product code or test was changed to hide the tooling failure.

Known Bash cases were not rerun merely to reconfirm the user's observation:

- `tests/test_ops_web_deployment.py::test_bootstrap_renders_and_installs_the_managed_service_and_caddy_site`
- `tests/test_ops_web_deployment.py::test_bootstrap_rejects_a_caddy_directory_only_mentioned_in_a_comment`

Both hit existing `${BASHPID}` in `scripts/deploy_ops_web.sh` under `/bin/bash` 3.2; the fixtures explicitly invoke `/bin/bash`, so merely changing PATH cannot supply supported Bash. No unrelated deployment code or tests were changed.

## Runtime smoke beyond tests

Throwaway isolated loopback fixture used actual `make_handler`, `TurnRunner`, `HomePuckSessionFactory`, Device-authorized HTTP requests and Home session/claim parsing. Its outputs drove a compiled executable including the actual `pcm_capture.h`, `puck_identity.h` and `puck_response.h`; only ESP-IDF/ESPHome peripheral/HTTP stubs were used. Granted paths used 32 synthetic zero bytes, never a microphone. This is contract-fixture evidence, not a real Home pairing or hardware round trip.

**17 scenarios passed:** provider absent; verified claim ready; powered reachable credential revocation; same credential after bridge restart/network restore; new Home-approved credential without verified admission; new credential plus verified fresh claim; mapped Profile unavailable; mapping restored without verified recovery; independent mapping's own claim; same-ID Profile repoint; repoint without fresh claim; repoint with verified fresh claim; insufficient scope without credential revocation; scope reachability without recovery; bridge-handle denial with valid Device credential; verified handle recovery; absent loopback bridge startup.

All denied cases: Unavailable indicator true, capture false, zero captured bytes and zero upload attempts. Every smoke scenario recorded zero Home prompts; permitted header-path checks deliberately sent only synthetic bytes to the firmware HTTP stub. The smoke therefore proves denial/no-submission, not a successful real spoken conversation.

Evidence directory: `/var/folders/cb/3pkc1ncx58j1xq63ktd8xftw0000gn/T/hermes-3p5-smoke-oca1i03d/` — `observed.json` (17 scenario records) and `compile.log` (native harness compilation). The throwaway runner is not product code and is not committed.

## Actual firmware compilation and hardware source

`venv-firmware/bin/esphome -s puck_home_transport true config firmware/respeaker-lite/respeaker-lite.yaml` followed by the matching `compile` succeeded using ESPHome **2026.8.2**, ESP-IDF **5.5.5**, isolated Python **3.13.16**, and example-only secrets. `puck_pcm_diagnostics` remained **false** and export URL empty. RAM **117071 / 341760 bytes**; flash **1946603 / 3932160 bytes**. Factory/OTA/ELF files were generated; no upload/flash command ran. Log: `artifact://2861`, 116.08s.

Final supported-environment Home-mode compilation also passed under Python **3.12.15** after the final suites, with the same RAM/flash measurements, ESPHome/ESP-IDF versions and diagnostics-off substitution (`artifact://3007`). Temporary example `secrets.yaml` and the throwaway smoke runner were removed after verification. Compilation artifacts remain example-only and must not be flashed as household configuration.

Exact configured target: `seeed_xiao_esp32s3`, variant ESP32-S3, 8MB flash — not the Plus target. Seeed's [official XIAO ESP32-S3 pin map and Blink note](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/) identify orange `USER_LED` as **GPIO21, active-low** (LOW lights, HIGH extinguishes). Existing firmware allocation is I2S **7/8/9/43/44**, I2C **5/6**, reset **2**, button **3**; semantic parsed configuration confirms GPIO21 has exactly one assignment. Physical board/enclosure appearance remains unverified; no hardware inspection is inferred from the official target mapping.

## Independent specification review

Independent reviewer found two non-frozen specification omissions: explicit operator-handle/revision recovery behavior and the verified exact LED mapping. Both were corrected without changing the original five AC or Home policy. Final independent disposition: **correct**, no remaining substantive acceptance or locked-policy gap. Detailed triage is in the owning spec.

## Independent code review

All three build-workflow layers ran against the complete tracked/new-file diff. Edge-case review found no issues; verification-gap review found no gaps. Blind review initially suspected that a failed identity-marker write could restore capture on restart, then independently retracted that finding after tracing the persisted-claim startup path: saved handles never reopen active, and fresh claims still require trusted evidence and full verified admission. Final blind verdict: **correct**. No code finding survived triage. The spec records each individual finding/disposition.

## Open rollout gates

1. Trusted production calibrated proximity provider and settled hardware qualification/provenance contract; no substitute is enabled.
2. Real Home enrollment/issued credential, authorized room/mapping configuration and real claim/ready integration.
3. Physical LED appearance/visibility and denied-capture/zero-upload observation on the assembled Puck.
4. Required physical voice/capture/playback/recovery acceptance belongs to the designated hardware owner. Raw diagnostics remain OFF while the user sleeps.

These gates prevent a hardware-ready/household-conversation claim. They do not turn contract fixtures into production policy or reduce original acceptance.
