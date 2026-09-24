# TUI-HOME-01 — implementation and acceptance record

Date: 2026-09-23. Status: implementation reviewed; runtime acceptance pending. Local tracker remains review, not done.

## Contract evidence

The implementation targets the actual Home NW-17 API in sibling branch `feat/home-nw-17-client-pairing`, revision `d2447f684a143817f7b5688b597c11aa053bb672`. This is implementation evidence, not confirmation that a running Home deployment exposes these endpoints. TUI baseline: `81cfc0a16684b3dfdd51d5d51929f21b31f3c3bb`.

## Delivered scope under review

- Explicit pairing by Home link or address/code, approval confirmation, native secure credential storage, renewal, and local unpair.
- Granted Profile selection, personal claims, session list/new/continue/resume, advertised title command, and explicit owner approval/rejection actions.
- Same-claim reconnect, bounded claim retirement on quit/switch, and local history isolated by canonical Home and granted identity.
- Existing local microphone and response-audio adapters reused; no Hermes agent changes.

## Inspection performed

Source and diff inspection against Home enrollment, configuration, credential renewal, client claims, session listing, grant decisions, and bridge command handlers. Three independent static review layers completed; verified code findings were corrected and reinspected. Existing obsolete test cases were maintained without adding new cases. Static syntax and whitespace inspection completed. No tests added or run, and no live API, enrollment, Keychain, microphone, or session calls performed in this task.

## Remaining runtime acceptance

- Deploy or otherwise expose the NW-17 implementation and pair through its approval page using macOS Keychain or Linux Secret Service.
- Exercise pending/rejected/expired pairing, secure-store failure, renewal retry and simultaneous TUI windows.
- Confirm text and local voice turns, new/continue/resume/list/title, granted Profile changes and owner decisions against unmodified Standard Hermes.
- Confirm socket-loss recovery within Home grace, uncertain-turn no-replay behavior, failed switches, quit, revocation and multiple Home/Profile isolation.
- Run focused and repository test coverage when explicitly authorized; this task did not establish regression coverage.

## Known product limits

Home currently returns session summaries, not historical messages. Resume restores Hermes context but cannot load an earlier transcript. Local unpair forgets the credential on this computer; server device revocation remains on Home's page. Legacy transport retirement and broader Standard-only setup remain their separate approved stories.

## Review disposition

Code corrections cover grant ambiguity, corrupt-key removal, hidden-input fallback, stale picker keys, readable timestamps, failed-release connection state, cancellable secure-store reads, missing public-config recovery, and explicit unresolved-turn messaging. Six existing test cases were updated for the changed contract; none were executed. Dedicated pairing persistence and interrupted-renewal regression cases remain to be added when requested. A title-specific positive acknowledgment schema remains unverified because Home currently passes through Standard's command result.

Native backend error/probe behavior was checked against upstream [macOS Keychain](https://github.com/jaraco/keyring/blob/main/keyring/backends/macOS/__init__.py) and [Secret Service](https://github.com/jaraco/keyring/blob/main/keyring/backends/SecretService.py) implementations. A generic deletion error is not treated as proof of absence, and no synchronous service-priority probe runs in the UI path.
