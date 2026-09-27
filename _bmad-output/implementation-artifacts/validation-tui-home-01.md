# TUI-HOME-01 — implementation and acceptance record

Date: 2026-09-24. Status: implementation reviewed; latest full automated suite passed (**1645 passed, 6 warnings in 314.30s**); live pairing, text, actual microphone capture and spoken response playback, thinking-event rendering, concurrent-client recovery and explicit claim closure confirmed. Other live edge cases remain deferred as listed below. TUI-HOME-01 stays in review; its implementation PR merged into the Home PRD branch, pending later merge of that program branch to `main`.

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

- Live macOS checks now include pairing, text and voice turns, new/continue/resume/list, Home grant and owner listings, runtime grant selection, concurrent TUI windows, reconnect, and clean claim closure; Amanda's Sept 24 screenshots and reports confirm session listing, resume, continue, and audio.
- Linux Secret Service and pending/rejected/expired pairing and secure-store failure states remain untested live.
- No pending owner request existed, so owner approval and rejection decisions remain untested.
- The current Home credential is generation 1 and expires on 2026-12-23, about 89.7 days after this check. The 14-day renewal window has not started; real renewal and renewal retry remain untested.
- A live `/title` attempt was rejected by `command.dispatch` with `request_rejected`, despite Home advertising the command capability. Rename is not accepted until this mismatch is resolved.
- Amanda reports the server revocation and local unpair checks were already completed before this session; neither access-removal action was repeated here.
- The explicit `/reconnect` command was exercised from a fresh Home TUI session: it disconnected and restored the same Home claim/session, reported that no prompt was sent and queued prompts remain pending, and exited cleanly with code 0. A connected session also rejected `/home select __invalid_probe__` with an explicit “conversation unchanged” message. An attempted follow-up READY did not visibly return before the TUI was closed; that result is inconclusive. Neither check simulated a dropped socket or an uncertain in-flight turn; later-stage failed switches and multiple Home/Profile isolation still need live acceptance.
- Home adapter title identity and close-acknowledgment fixes are deployed and verified separately. Live TUI adapter text/audio/turn completion and claim closure now pass; no user prompt was replayed.

## Known product limits

Home currently returns session summaries, not historical messages. Resume restores Hermes context but cannot load an earlier transcript. Local unpair forgets the credential on this computer; server device revocation remains on Home's page. Legacy transport retirement and broader Standard-only setup remain their separate approved stories.

## Review disposition

Code corrections cover grant ambiguity, corrupt-key removal, hidden-input fallback, stale picker keys, readable timestamps, failed-release connection state, cancellable secure-store reads, missing public-config recovery, and explicit unresolved-turn messaging. Existing cases and new pairing persistence/interrupted-renewal cases now pass. Full-suite verification also exposed an obsolete story-index assertion and a lost profile-switch notice; both were corrected, with 254 focused checks passing before the successful full run. A title-specific positive acknowledgment schema remains unverified because Home passes through Standard's command result; the live rejection is recorded below.

Native backend error/probe behavior was checked against upstream [macOS Keychain](https://github.com/jaraco/keyring/blob/main/keyring/backends/macOS/__init__.py) and [Secret Service](https://github.com/jaraco/keyring/blob/main/keyring/backends/SecretService.py) implementations. A generic deletion error is not treated as proof of absence, and no synchronous service-priority probe runs in the UI path.

## Live stall investigation and repair

Standard Hermes completed Amanda's original message, but Home rejected its normal session.title event because the runtime envelope ID and durable payload ID differ. Home then silently stopped its upstream reader. A separate Home repair accepts that title shape, closes the client socket on genuine upstream loss, and preserves explicit-close acknowledgments. Deployed Home runtime revision: `e4838793943b2820c62cb8f68ecfb52cabfee196`; all 32 installed Python sources were verified, with 685 Home tests passing. No Standard Hermes modifications were made.

The TUI also assumed audio ended before text completion and did not emit the Textual turn_end boundary. It now waits for both streams, bounds audio inactivity without counting local rendering time, displays audio-unavailable notices, preserves already-completed text on audio loss, and retires recovered sockets that may contain an old audio tail. A fresh live adapter probe returned TEST, received PCM/audio_end/turn_end, and confirmed claim closure. Amanda later confirmed an actual TUI microphone turn completed with spoken playback.

The full suite with the initial completion fix passed **1630 tests, 2 skipped, 6 warnings in 307.85s**. Subsequent review hardening passed 120 focused tests; the final parent-run app/profile/Home/pairing selection passed **381 tests in 50.57s**. The final browser/Puck recovery parameterization separately passed **2 tests in 0.12s**. The earlier full 1615-pass result and pairing cases remain historical checkpoints.

## Follow-up from actual TUI acceptance

Amanda subsequently reported `home bridge receive failed (ConnectionClosedError)` in the restarted TUI. A live headless Textual run reproduced it; isolated runs could succeed, while two simultaneous Home connections reproduced failure. The earlier one-turn adapter proof did not cover this condition. Home diagnosis identified a concurrent authorization-refresh candidate, with its fix and final multi-client acceptance recorded in the separate Home validation. At that stage user-facing acceptance remained pending; the fix and successful retest are recorded below.

Home follow-up resolved: a deterministic authorization-refresh race rejected equal immutable grant snapshots while event polling and prompt submission overlapped. Home runtime `e2a8521aa100cd5c6ea58be2b5ce263f8a34eda7` now compares authority semantically, preserves known session persistence and rejects real authority changes; 698 Home tests pass. The exact two-client failure case now passes live. The actual Textual app also remained ready through 30 seconds with a second client connected, completed a fresh text/audio turn, returned prompt completed/voice ready, and closed both claims successfully. No TUI code change was required for this follow-up.

Amanda next reported `[unhandled server event: thinking.delta]`. The Home adapter accepted `text` but not Standard's `delta` field for `thinking.delta`/`reasoning.delta`; it now normalizes either field and ignores empty deltas. Regression coverage and the full Home session adapter module pass (109 tests). A fresh live Home probe emitted thinking events without unknown events, completed TEST through text/audio/turn_end, and closed its claim. TUI fix committed as `ea7d030`.

Amanda confirmed the updated terminal rendered thinking normally and completed an actual voice turn, including microphone capture and spoken response playback. Final suite on this branch: **1637 passed, 2 skipped, 6 warnings in 303.97s**. Live acceptance now covers pairing on macOS, Home text and voice, thinking events, claim closure, and multi-client/reconnect stability. Story PR [#210](https://github.com/achappell/hermes-relay-tui/pull/210) merged into `feat/hermes-home-2026-09-23/prd`. Local story remains `review` until the deferred acceptance is dispositioned; the Home PRD branch has not yet merged to `main`.

## Additional live acceptance — 2026-09-24 (CDT)

The current Home profile returned three active, available grants: Amanda, Jensen, and Spark. `/home pending` returned none; `/home holders` returned three active TUI grant-holder rows. Starting with an unmatched command-line grant produced the expected grant-selection error without opening a claim; `/home grants` still worked while disconnected, and `/home select Amanda` then created a new Home conversation. The profile's saved configuration remained unchanged with no grant selected.

Two separate TUI windows then connected concurrently using Amanda's Home grant, each sent `Reply with READY only`, and each returned `READY`. Both exited with code 0 after Ctrl+Q. Local playback was disabled for these text-only checks. No owner decision or renewal was performed in this session. Amanda reports server revocation and local unpair were checked earlier; those results were not independently repeated here.

A fresh TUI session also ran `/reconnect`. The client visibly disconnected, reconnected to the same session ID under the same Home claim, and reported that it sent no prompt and queued prompts remain pending. The TUI exited with code 0. This validates explicit reconnect only; an unexpected socket loss and an in-flight uncertain turn were not simulated.

A fresh TUI session then ran `/title TUI title smoke 2026-09-24`. Home returned `[error] Title: home bridge command.dispatch rejected (request_rejected)`; the session remained connected until it was closed with Ctrl+Q, but no rename was accepted. The available Standard Gateway source includes `/title` in its command catalog while its `command.dispatch` stages do not implement the local title handler, matching the live rejection. Confirm the deployed Standard revision before assigning the defect to that exact source tree; TUI-HOME-01 cannot claim live title acceptance yet.

A fresh connected Amanda session attempted `/home select __invalid_probe__`. The TUI reported `Home conversation unchanged on screen` and the grant-selection guidance while retaining the same `home-76f8bd57f0a2` session and Amanda grant. A subsequent `Reply with READY only` produced no visible response during observation; it was not retried, and Ctrl+Q closed the TUI with exit code 0. This validates the invalid-label rejection before a replacement claim is opened; post-release switch failure and cross-Profile isolation remain untested.

## Additional automated verification — 2026-09-24 (CDT)

The T-5 wake teardown modules (`tests/test_wake.py`, `tests/test_app_wake.py`) passed **92 tests**. This covers prompt return while cleanup is blocked, cancelled and late microphone opens, stale-frame rejection, repeated teardown, and re-arm serialization; it does not replace the live microphone acceptance listed above.

The Home, pairing, Profile, and history module selection passed **197 tests**. It includes a new regression in `tests/test_profile_app.py`: equivalent canonical Home addresses share a history path, while different grant IDs, different Home origins, and a same-named Voice Profile resolve to separate paths. No Home history contents were read and no live Profile switch was made.

Targeted checks for wake follow-up and microphone capture (`tests/test_handsfree.py`, `tests/test_app_wake.py`, `tests/test_mic.py`, and `tests/test_voice_recorder.py`) passed **24 tests**. These support the current simulated wake-follow-up and PCM capture paths, but do not reproduce the physical spoken-input reports in [#102](https://github.com/achappell/hermes-relay-tui/issues/102) or [#104](https://github.com/achappell/hermes-relay-tui/issues/104). The original reports require a wake phrase, a second spoken turn, and a sustained utterance. Neither was performed during this pass; both defect stories remain backlog.

The latest `venv/bin/pytest -q` run passed **1645 tests with 6 `websockets` deprecation warnings in 314.30s**. This supersedes the earlier 1637-pass checkpoint above; one new regression test was added during this pass, so the full count difference is not attributed to that test alone. `git diff --check` passed. Automated checks used fakes and loopback services; this pass sent no Home prompt and touched no Android repository.

## Acceptance continuation — 2026-09-27 (CDT)

The Home program branch is now merged through `f1807570bc3024bc150ffae30286b881a254f483`; this supersedes the earlier pending-main statements. This continuation starts from TUI `77a4661ef05d9d99a046278818558c9930ca8880` in `.worktrees/epic-1-tui-acceptance`. It preserves the prior local validation and history regression evidence. TUI-HOME-01 remains in review; physical and environment-specific acceptance is not inferred from automated checks.

Three review layers identified corrections to refused config reload, grant-scoped history on reload, retained transcript ownership after a failed destination connection, submission after explicitly leaving uncertainty, and text completion after audio transport loss. Focused regressions exercise the actual Textual and Home adapters. HTTP parser tests additionally execute the real response parser for error status, malformed/schema-invalid data, redirects and privacy-safe errors. A follow-up review identified the failed replacement handshake followed by successful reconnect guard case; it is included in this continuation's verification.

Live macOS checks used the existing paired `home-refresh` configuration and Amanda grant through the normal secure-store API. Credentials, opaque handles, response audio, and private history were not printed or saved. These probes created only synthetic acceptance conversations and did not replay any earlier prompt.

- Title dispatch succeeded; explicit claim closure succeeded. Sibling Home source contains the supported `session.title` repair at `b51d289a680229dfb14c6f2ae8f0f1396dadd430`. This is source evidence, not a newly verified deployed-revision claim.
- A fresh synthetic text turn emitted thinking, text, message completion, eleven PCM chunks, audio completion and exactly one normalized turn completion. Playback was disabled; this verifies live audio transport, not a new audible-playback or microphone acceptance.
- A deliberately closed idle WebSocket was reported lost. After normal session cleanup, reconnect retained the same Home claim, deliberate new created a different claim, and explicit closure succeeded. An initial adapter-only probe omitted normal cleanup and failed; it is not counted as recovery acceptance.
- A headless real Textual app disconnected its socket after the synthetic prompt was acknowledged. The app retained uncertain delivery, reconnected the same claim, and recorded exactly one original `prompt.submit`. After `/home leave`, an ordinary prompt stayed local. An initial replacement attempt became unavailable and its retirement was unconfirmed; this transient remains recorded, not erased by a retry.
- Fresh bounded adapter and Textual repetitions of that scenario both created a ready deliberate replacement and confirmed claim closure. The Textual repetition again recorded exactly one original submission. These checks establish the observed successful recovery path, while the earlier transient has no proven root cause.

Remaining gates: Linux Secret Service; live pending/rejected/expired enrollment and secure-store failures; owner decisions with an actual pending request; real renewal/retry when eligible; multiple Home origins; physical wake/second-turn/sustained-utterance acceptance for T-5 and defects 102/104. Existing renewal and isolation fake tests remain useful evidence but do not claim those live gates.

A fresh real Textual app then selected Spark from Amanda and returned to Amanda using approved grants. Each switch reached ready, created a distinct claim, and used a distinct temporary history path; returning restored Amanda's original history scope and grant. No prompt was sent on the alternate Profile, no existing private history was read, and final claim closure succeeded. This closes the live same-Home cross-Profile isolation check; multiple Home origins remain untested live.

A read-only live credential check confirms it is still outside the fourteen-day renewal window. The pending-owner endpoint now returns two requests, superseding the earlier no-pending-requests observation. Their identities and requested grants were not printed, and no real access decision was used as test data. Owner decision acceptance requires a designated test request or an explicitly intended real decision.

The physical runbook is [TUI Epic 1 physical voice acceptance](../../docs/testing/tui-epic-1-physical-acceptance.md); none of its physical steps was performed during this continuation.

Final automated verification for the continuation: `../../venv/bin/pytest -q -rs` passed **1667 tests, 1 skipped, 6 warnings in 306.94 seconds**. The skip is `tests/test_puck_firmware.py:311` because the ESPHome firmware environment is not installed; warnings are existing websockets deprecations. This run includes the replacement-handshake retry correction and supersedes the intermediate 1666-pass run. `git diff --check` passed. No physical voice result has yet been recorded.
