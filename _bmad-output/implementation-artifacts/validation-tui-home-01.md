# TUI-HOME-01 — implementation and acceptance record

Date: 2026-09-24. Status: implementation reviewed; final automated suite passed (**1637 passed, 2 skipped**); live pairing, text, actual microphone capture and spoken response playback, thinking-event rendering, concurrent-client recovery and explicit claim closure confirmed. Other live edge cases remain deferred as listed below. TUI-HOME-01 stays in review; its implementation PR merged into the Home PRD branch, pending later merge of that program branch to `main`.

## Contract evidence

The implementation targets the actual Home NW-17 API in sibling branch `feat/home-nw-17-client-pairing`, revision `d2447f684a143817f7b5688b597c11aa053bb672`. The live Home deployment exposes these endpoints; Amanda completed pairing during the authorized test session. TUI baseline: `81cfc0a16684b3dfdd51d5d51929f21b31f3c3bb`.

## Delivered scope under review

- Explicit pairing by Home link or address/code, approval confirmation, native secure credential storage, renewal, and local unpair.
- Granted Profile selection, personal claims, session list/new/continue/resume, advertised title command, and explicit owner approval/rejection actions.
- Same-claim reconnect, bounded claim retirement on quit/switch, and local history isolated by canonical Home and granted identity.
- Existing local microphone and response-audio adapters reused; no Hermes agent changes.

## Inspection performed

Source and diff inspection against Home enrollment, configuration, credential renewal, client claims, session listing, grant decisions, and bridge command handlers. Three independent static review layers completed; verified code findings were corrected and reinspected. Static syntax and whitespace inspection completed. Amanda subsequently requested testing. In the isolated Python 3.14 environment, the full suite passed: **1615 passed, 2 skipped, 6 warnings in 300.52s**. Thirteen new pairing/renewal tests cover interrupted persistence, duplicate windows, corrupt records, cross-Home isolation and public-config recovery. Two additional real loopback WebSocket tests passed in 0.93s: disconnect during thinking or partial reply settles within two seconds, preserves uncertain delivery, and reconnects without replay. These two tests were added after the full-suite run.

## Remaining runtime acceptance

- Live Home pairing succeeded with the local native credential store; Linux Secret Service live acceptance remains pending.
- Exercise pending/rejected/expired pairing, secure-store failure, renewal retry and simultaneous TUI windows.
- Confirm text and local voice turns, new/continue/resume/list/title, granted Profile changes and owner decisions against unmodified Standard Hermes.
- Confirm socket-loss recovery within Home grace, uncertain-turn no-replay behavior, failed switches, quit, revocation and multiple Home/Profile isolation.
- Home adapter title identity and close-acknowledgment fixes are deployed and verified separately. Live TUI adapter text/audio/turn completion and claim closure now pass; no user prompt was replayed.

## Known product limits

Home currently returns session summaries, not historical messages. Resume restores Hermes context but cannot load an earlier transcript. Local unpair forgets the credential on this computer; server device revocation remains on Home's page. Legacy transport retirement and broader Standard-only setup remain their separate approved stories.

## Review disposition

Code corrections cover grant ambiguity, corrupt-key removal, hidden-input fallback, stale picker keys, readable timestamps, failed-release connection state, cancellable secure-store reads, missing public-config recovery, and explicit unresolved-turn messaging. Existing cases and new pairing persistence/interrupted-renewal cases now pass. Full-suite verification also exposed an obsolete story-index assertion and a lost profile-switch notice; both were corrected, with 254 focused checks passing before the successful full run. A title-specific positive acknowledgment schema remains unverified because Home currently passes through Standard's command result.

Native backend error/probe behavior was checked against upstream [macOS Keychain](https://github.com/jaraco/keyring/blob/main/keyring/backends/macOS/__init__.py) and [Secret Service](https://github.com/jaraco/keyring/blob/main/keyring/backends/SecretService.py) implementations. A generic deletion error is not treated as proof of absence, and no synchronous service-priority probe runs in the UI path.

## Live stall investigation and repair

Standard Hermes completed Amanda's original message, but Home rejected its normal session.title event because the runtime envelope ID and durable payload ID differ. Home then silently stopped its upstream reader. A separate Home repair accepts that title shape, closes the client socket on genuine upstream loss, and preserves explicit-close acknowledgments. Deployed Home runtime revision: `e4838793943b2820c62cb8f68ecfb52cabfee196`; all 32 installed Python sources were verified, with 685 Home tests passing. No Standard Hermes modifications were made.

The TUI also assumed audio ended before text completion and did not emit the Textual turn_end boundary. It now waits for both streams, bounds audio inactivity without counting local rendering time, displays audio-unavailable notices, preserves already-completed text on audio loss, and retires recovered sockets that may contain an old audio tail. A fresh live adapter probe returned TEST, received PCM/audio_end/turn_end, and confirmed claim closure. Amanda later confirmed an actual TUI microphone turn completed with spoken playback.

The full suite with the initial completion fix passed **1630 tests, 2 skipped, 6 warnings in 307.85s**. Subsequent review hardening passed 120 focused tests; the final parent-run app/profile/Home/pairing selection passed **381 tests in 50.57s**. The final browser/Puck recovery parameterization separately passed **2 tests in 0.12s**. The earlier full 1615-pass result and pairing cases remain historical checkpoints.

## Follow-up from actual TUI acceptance

Amanda subsequently reported `home bridge receive failed (ConnectionClosedError)` in the restarted TUI. A live headless Textual run reproduced it; isolated runs could succeed, while two simultaneous Home connections reproduced failure. The earlier one-turn adapter proof did not cover this condition. Home diagnosis identified a concurrent authorization-refresh candidate, with its fix and final multi-client acceptance recorded in the separate Home validation. At that stage user-facing acceptance remained pending; the fix and successful retest are recorded below.

Home follow-up resolved: a deterministic authorization-refresh race rejected equal immutable grant snapshots while event polling and prompt submission overlapped. Home runtime `e2a8521aa100cd5c6ea58be2b5ce263f8a34eda7` now compares authority semantically, preserves known session persistence and rejects real authority changes; 698 Home tests pass. The exact two-client failure case now passes live. The actual Textual app also remained ready through 30 seconds with a second client connected, completed a fresh text/audio turn, returned prompt completed/voice ready, and closed both claims successfully. No TUI code change was required for this follow-up.

Amanda next reported `[unhandled server event: thinking.delta]`. The Home adapter accepted `text` but not Standard's `delta` field for `thinking.delta`/`reasoning.delta`; it now normalizes either field and ignores empty deltas. Regression coverage and the full Home session adapter module pass (109 tests). A fresh live Home probe emitted thinking events without unknown events, completed TEST through text/audio/turn_end, and closed its claim. TUI fix committed as `ea7d030`.

Amanda confirmed the updated terminal rendered thinking normally and completed an actual voice turn, including microphone capture and spoken response playback. Final suite on this branch: **1637 passed, 2 skipped, 6 warnings in 303.97s**. Live acceptance now covers pairing on macOS, Home text and voice, thinking events, claim closure, and multi-client/reconnect stability. Remaining live gates are Linux Secret Service, enrollment failure states and secure-store failure, real renewal/revocation, Home session/owner commands, multiple TUI windows, and unpair. Keep those gates explicitly deferred; automated coverage exists for portions, but no live acceptance is claimed. Story PR [#210](https://github.com/achappell/hermes-relay-tui/pull/210) merged into `feat/hermes-home-2026-09-23/prd`. Local story remains `review` until the deferred acceptance is dispositioned; the Home PRD branch has not yet merged to `main`.

## Additional live acceptance — 2026-09-25 (CDT)

On `feat/hermes-home-2026-09-23/prd`, the focused Home/profile regression selection passed **514 tests** across `test_home_client.py`, `test_home_pairing_cli.py`, `test_home_textual_session.py`, `test_puck_home_session.py`, `test_profile_app.py`, `test_history.py`, `test_home_disconnect.py`, `test_config.py`, `test_setup.py`, `test_profile_cli.py`, `test_commands.py`, and `test_app.py`. The first six modules passed 159 tests in 2.92 seconds; the remaining six passed 355 tests in 48.81 seconds.

Using the saved `home-refresh` profile and Amanda grant, a fresh TUI Home conversation accepted `Reply READY only` and rendered the Standard response `READY`. The run used `--no-play`; the TUI buffered 47,872 PCM bytes into its response WAV, which was removed after the check. `/title TUI-HOME-01 smoke 2026-09-25` succeeded with `Conversation title updated.` The earlier `request_rejected` result did not reproduce on this connection; the deployed Home/Standard revision was not independently identified.

A second launch requested `--continue` with the Amanda grant. From that connected TUI, `/reconnect` reported `Transport reconnected; no prompt was sent and queued prompts remain pending`, returned to ready, and Ctrl+Q exited with code 0. This exercised deliberate idle reconnect; it did not simulate a dropped socket during an uncertain turn. The smoke conversation remains in Home history under the test title because this client has no session-delete operation. Temporary local history and response audio were removed.

This pass did not exercise post-release switch failure, cross-Home/Profile isolation, Linux Secret Service, pairing failure states, owner approval/rejection, or real credential renewal. The local story remains `review` pending those gates and their disposition.

## Additional session and interruption checks — 2026-09-26 (CDT)

Using the saved `home-refresh` profile and Amanda grant, `/home grants`, `/home pending`, and `/home holders` completed. No owner requests were pending; owner-holder rows were returned. No other grant was selected. In the TUI, `/new` opened a new Home conversation, `/continue` resumed Home context, and `/sessions TUI-HOME-01 smoke 2026-09-25` filtered and resumed the prior QA conversation. The TUI explicitly stated that Home does not return the old transcript. The three default launches plus `/new` created four QA conversation entries: three received no prompt and one was used for the uncertain interruption. These server-side entries remain because the client has no delete command. All three TUI processes exited with code 0. After quitting, a fresh picker did not mark the prior QA row busy. The client-side picker evidence supports claim release; the Home API exposes no direct claim-status query.

For a controlled live interruption, a temporary QA-only Python startup hook observed one outgoing `prompt.submit`, then closed only that TUI's real Home bridge WebSocket with close code 1011 after 150 ms. The TUI reported `home bridge receive failed (ConnectionClosedError)` and disconnected; no response was observed. The hook log recorded exactly one `prompt.submit`, including across the attempted `/reconnect`; no prompt replay occurred. `/reconnect` displayed its request and reconnecting state, but completion was not observed before the TUI exited normally with code 0. Recovery therefore remains unverified, and the prompt outcome is uncertain. The Home conversation may remain in Home history; no delete operation exists. The isolated temporary history contained one QA prompt row; that history and the temporary hook/log were removed after inspection. No response audio was retained.

The focused loopback integration case `test_home_websocket_close_ends_thinking_preserves_uncertainty_and_never_replays` passed both parameter cases (**2 passed in 0.89s**), covering disconnect during thinking and partial reply, uncertainty preservation, and no replay. No product code changed. TUI-HOME-01 remains `review`; Linux Secret Service, enrollment and secure-store failures, cross-Home/Profile isolation, owner decisions, renewal/revocation, and post-release switch failure remain pending live acceptance.

## Additional acceptance checks — 2026-09-26 (CDT)

A second controlled live no-prompt recovery run supersedes the earlier unverified reconnect outcome. A temporary QA-only hook observed one Home claim request and two bridge socket opens, closed the first socket with code 1011, then `/reconnect` reported `Transport reconnected; no prompt was sent and queued prompts remain pending`. The Home session adapter reached ready again, and the TUI exited with code 0. No prompt was sent.

Two simultaneous TUI processes used `--continue` with the saved `home-refresh` profile and Amanda grant. The first connected; the second received `Another client controls that conversation.` and stayed disconnected. Both exited with code 0. No prompt was sent. This confirms Home blocks a second client from controlling the active conversation.

In a connected TUI, selecting a deliberately nonexistent grant ID displayed `Home conversation unchanged on screen: Select an active, available Profile with --home-grant or /home select <label>.` The existing Amanda conversation remained connected and ready, and the TUI exited with code 0. No other grant was used.

The focused Home/profile/app regression selection passed **345 tests in 59.15s**, with one `websockets.legacy` deprecation warning. Temporary in-memory acceptance probes passed **5 checks**: pending, rejected and expired enrollment; explicit owner approve/reject request shapes; and local-unpair wording that distinguishes local forgetting from server revocation. No permanent tests were added in this pass. Existing tests also cover secure-store preflight failure, interrupted renewal request recovery across restart, two-window renewal serialization, corrupt-record deletion, and cross-Home credential rejection.

A read-only secure-store inspection found the Amanda device credential at generation 1 with **88.0 days** until expiry and no pending renewal request. Home renews only in the final 14 days, so no live credential renewal was triggered. No owner request was pending during the live check; owner decisions and unpair were exercised only against fakes, and server-side revocation was not attempted. Linux Secret Service could not be tested on this macOS host. Live cross-Home/Profile isolation, a post-release Home grant-switch failure, a real credential renewal, and the deployed Home/Standard revision behind the successful title command remain unverified.

A separate early-shutdown failure was reproduced twice while the Home connection had not become ready and claim closure could not be confirmed. `on_unmount` called `_close_session_for_shutdown`, which appended a warning after the transcript widget had been removed; Textual raised `NoMatches` for `#transcript` and the process exited with code 1. The two failed app exits appended structural exception traces to the private crash log; the temporary startup hook and its log were removed, and the crash log was preserved.

The shutdown defect is fixed in commit `ef2bc57`: `_close_session_for_shutdown` logs an unconfirmed or failed Home claim release instead of writing into the unmounting transcript. The parameterized regression test covers both a `False` release and a raised `ConnectionError`. Against parent `a038a4f`, both cases failed with `NoMatches`; on the fix branch, both passed. The focused Home/profile/app selection passed **347 tests in 54.74s**. The full suite passed **1640 tests, 1 skipped, 6 deprecation warnings in 305.48s**. The post-fix checks used fake claim-release results; live Home was not re-exercised after the fix. TUI-HOME-01 remains `review` pending disposition of the other live acceptance gates listed above.

## Acceptance gate disposition — 2026-09-26 (CDT)

This section supersedes the earlier pending-test lists above. The six approved acceptance criteria are assessed using durable regression tests, real native credential stores, a disposable real Home service, and the recorded deployed Home/Standard checks. Acceptance does not require destructive renewal or revocation of Amanda's production device. The tested checkout is `fix/hermes-home-2026-09-23/tui-home-01-quit-release`, based on `ef2bc57`, with the HTTP error-classification correction and acceptance tests described below. Formal story status remains `review`; passing this test gate does not merge the follow-up changes. The remote-state correction below records the already completed PRD integration.

| Criterion | Result and evidence |
| --- | --- |
| AC1: approved pairing and granted Profile launch | PASS. Real disposable Home HTTP enrollment by code and link, actual pairing CLI and macOS Keychain persistence, public-config secret exclusion, plus prior deployed pairing and text/voice acceptance. |
| AC2: truthful enrollment and storage failures | PASS. Real Home pending/rejected/expired states; native Secret Service absence fails with `secure_store` and no fallback; malformed native records are rejected. Focused HTTP negatives cover redirects, TLS, deadline, malformed/schema-invalid/oversized responses, and sanitized errors. |
| AC3: Home/Profile/window isolation | PASS. Native two-origin credential separation, canonical history identity, cross-Profile reference and stale-revision refusal, claim limit, persisted renewal recovery after a lost response, and two concurrent clients sharing one renewal. Prior separate live TUI processes confirmed busy-claim enforcement. |
| AC4: supported operations and preservation guards | PASS. Prior deployed new/continue/list/resume/title checks; real disposable owner decisions and unauthorized refusal; Textual/adapter tests preserve transcript and history after post-release replacement failure and prevent changes with queued/uncertain work. Unsupported title, explicit new-session ID, and unknown resume reference fail before dispatch/replacement. |
| AC5: reconnect, honest failure, quit and retained conversation | PASS. Prior live same-claim recovery and no-replay evidence; loopback disconnect regressions; post-fix deployed ready quit confirms release and preserves the named QA conversation in the inactive session listing. Held-response early quit exits normally, logs unconfirmed release, and its accepted test claim is explicitly retired afterward. |
| AC6: local unpair versus server revocation | PASS. Actual unpair CLI deletes the disposable native credential and explains that this does not revoke it. The retained in-memory credential still works against Home until the disposable device is explicitly revoked; subsequent access fails with `unauthorized`. |

### Native and service execution

`scripts/qa_home01_secure_store.py` passed six named checks on macOS Keychain and six on Linux Secret Service through SSH alias `ops`: roundtrip, canonical origin, two-Home isolation, local deletion, corrupt-record deletion, and absent-record deletion. An additional Linux run without a Secret Service provider failed closed as expected. Linux used a temporary virtual environment and locally extracted gnome-keyring libraries inside an isolated D-Bus session; no system package or production service was changed. The temporary Linux lab was removed after execution. Only disposable `.invalid` records were used; final deletion was asserted.

`scripts/qa_home01_service.py` passed all 11 printed scenario groups, including a repeat after the final HTTP correction. It uses real Home HTTP/TLS, enrollment, SQLite authorization, renewal and revocation code from clean sibling Home source `b51d289a680229dfb14c6f2ae8f0f1396dadd430`, with temporary configuration and synthetic devices. Its Standard session-directory fixture is synthetic: this run does not prove Standard answer generation or bridge audio. Those behaviors retain the separately recorded deployed evidence. The concurrency check uses two clients in one process; the separate-process TUI busy check is the earlier live evidence. Temporary databases, native records, certificates, locks and server threads are cleaned up.

The service probe is opt-in and requires the sibling Home checkout and its dependencies. In this environment it ran with `PYTHONPATH="$HOME/Development/hermes-relay-home/.venv/lib/python3.14/site-packages" ../../venv/bin/python scripts/qa_home01_service.py` from the worktree. The native probe ran with the applicable platform Python and keyring backend; neither probe belongs in an ordinary unattended pytest run.

`scripts/qa_home01_live_quit.py --profile home-refresh --grant Amanda --qa-title 'TUI-HOME-01 smoke 2026-09-25'` passed against deployed Home after the final correction. It drives the real Textual app via `run_test()`, sends no prompt, and deliberately holds the early-quit claim response after Home accepts it. It verifies the saved conversation remains listed after normal closure; it does not claim Home supplies old transcript messages. Production renewal, unpair and revocation were not performed. The exact current deployed Home/Standard source revisions behind the historical title result remain a reproducibility limitation, not an additional acceptance criterion.

### Final regression correction

The new HTTP boundary regression exposed a misleading error classification: Python's `SSLCertVerificationError` also inherits `ValueError`, so certificate refusal was reported as malformed Home JSON. `HomeClient._request` now catches `ssl.SSLError` first and reports the existing secure-connection failure. Certificate verification was already enforced; no insecure fallback was introduced or removed. The regression failed before this correction and passed afterward. The focused `test_home_client.py`, `test_home01_acceptance.py`, and `test_home_textual_session.py` run passed **32 tests in 0.60s**.

The final complete suite passed **1656 tests, 1 skipped, 6 deprecation warnings in 293.85s**. The single skip is `tests/test_puck_firmware.py:311`, because the ESPHome firmware environment is not installed; no Home pairing or session acceptance test was skipped. Complete-suite results and the requirement-to-test mapping are recorded in the [traceability matrix](../test-artifacts/traceability-matrix.md). These results describe acceptance-criterion coverage, not measured line or branch coverage. No remaining acceptance-test blocker was identified; review and integration of the follow-up changes remain required before formal closure.


## PR preparation and remote-state correction — 2026-09-26 (CDT)

A fresh GitHub read confirmed that quit-fix PR #212 merged into the Home PRD branch at `dc60df9c664d512e9fa54c3ed12d8ed96c07052f`, and PR #211 merged the PRD branch into `main` at `f1807570bc3024bc150ffae30286b881a254f483`. Both merged on 2026-09-24; the remote PRD branch is gone. Earlier statements that those merges were pending were stale. This acceptance follow-up therefore targets `main` from `fix/tui-home-01-acceptance-closeout`, based on `77a4661`.

The 1656-pass run above remains evidence for its recorded pre-PR working tree. Moving the follow-up to current main added only the existing release metadata/changelog and additional pairing CLI tests; no tested application runtime changed. CI on the new PR is the verification of the final committed branch. Story status remains review until this follow-up is reviewed and merged.

## PR security-review follow-up — 2026-09-26 (CDT)

CodeQL flagged the disposable service harness because its server TLS context did not explicitly constrain protocol versions. The tested Python environment already reported a TLS 1.2 minimum, but the harness now sets `context.minimum_version = ssl.TLSVersion.TLSv1_2` before wrapping the socket, making that requirement explicit across environments. No production client or service TLS setting changed. The real disposable Home service probe passed all 11 scenario groups again after this change, including cleanup. The earlier full-suite and source-hash records retain their original run provenance.
