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
