# W/K Home browser integration — repository validation

## Scope and authoritative inputs

- Implementation branch: `feat/wk-home-browser-integration`, isolated worktree `.worktrees/wk-home-browser-implementation`.
- Spec dependency: TUI PR [226](https://github.com/achappell/hermes-relay-tui/pull/226), `docs/wk-home-browser-migration-spec`, head `760da1865991009b57bb1e73784525b34afdd486`. PR 226 was OPEN when the implementation branch was selected; implementation is a separate stacked PR, not a push to that docs branch.
- Actual fetched Home `origin/main`: `3a0eec0b9739524e2a8c54fd5a3308b3c3abb90b`, used through the detached sibling checkout `.worktrees/browser-integration-smoke`. Home PR 102/103 merge status was accepted as user ground truth, not rechecked.
- Authorized work: S2/S3/S4, repository-local S5 admission health, and S6 supported integration/deployment tooling. No production deployment, SSH, live grant changes, R6 default switch/bake, R7 shutdown/retirement, optional H5, or new Ops monitoring.
- `WK-HOME-01` remains in progress; `WK-1` and `WK-2` are not marked done/deployed. Production and hardware acceptance remain open.

## Implemented consumer path

| Boundary | Implementation |
| --- | --- |
| Pair once, private durable authority | `home_display/home_pairing.py`, `home_display/home_store.py`, existing `home_pairing_cli.py` and `HomeClient` enrollment/renewal. Service-owned 0700 directory/0600 record outside checkout; atomic replace/fsync; durable renewal request ID; single-process lease. |
| Dynamic Profiles | `home_display/home_admission.py`, appliance capabilities and browser selector. Home configuration/grants are authoritative; later grants need no wake phrase; browser uses per-tab opaque tokens; local shortcuts bind only stable grant IDs. |
| Independent fresh conversations | Lazy per-connection `mode=new` claims; no claim for idle tabs; one attempt for each admission action; no auto prompt replay. `HomeBrowserSession` explicitly disables the base Puck uncertain-turn resume behavior. |
| Cleanup and capacity | Bound close when healthy; actual NW18 list/close on startup and uncertain/lost paths; unresolved refs remain capacity-accounted; sweep excludes live tabs. |
| Failure and renewal | Typed Home/Hermes/authorization/Profile/stale/renewal/capacity errors, authenticated authority reconciliation after ambiguous bridge loss, and old-generation retirement before renewal. |
| Same-page recovery | An explicit action remains possible after a recoverable Home bridge error; browser reducer starts fresh only for that deliberate action, keeping wire sequence enforcement. Revoked/no-usable-Profile input remains disabled. |
| Admission health | Local page starts before first Home HTTP refresh; `/healthz` is 200/503 admission-only, not an upstream generation/audio/hardware probe. |
| Supported deployment | `scripts/deploy_home_browser.py`: isolated tagged Home unit/release, exact household Tailscale Serve origin, loopback-only backend, Funnel refusal, no legacy env/token dependency, Home-only rollback with saved unit. No host commands were executed. |

## Automated verification exercised

Commands used `PATH=/opt/homebrew/bin:$PATH`, Python 3.14, and the isolated worktree venv.

- Full repository `python -m pytest -q`: **1754 passed, 3 skipped**, six existing websockets deprecation warnings.
- `npm --prefix home_display/web run check`: **0 errors, 0 warnings**.
- `npm --prefix home_display/web test`: **224 passed**, 12 test files.
- `npm --prefix home_display/web run build`: **passed**; bundled assets `index-DuN2xGL_.js` and `index-BTquQKuK.css`.
- Shared display contract/conformance/WASM-target rerun after the new Profile fixture gained explicit `prompt: null`: **20 passed, 1 skipped**. The ESP-IDF cJSON-dependent contract is an optional local skip; no ESP32 hardware acceptance is inferred.
- Actual merged Home admission/claim/grant suites (`test_browser_admission`, `test_client_claims_api`, `test_client_claim_list_close_api`, `test_client_claim_schema`, `test_client_claim_store`, `test_client_claim_close_bridge`, `test_client_grants`): **138 passed**.
- `python -m build --sdist --wheel`: **passed**, producing `hermes_relay_tui-0.11.0.tar.gz` and `hermes_relay_tui-0.11.0-py3-none-any.whl` locally. These are validation builds, not a released tag.
- Focused Home deployment validator suite: **9 passed**. No SSH/deployment action was used by these tests.

The first full run found two retained legacy deploy tests using macOS Bash 3.2 (`BASHPID` unavailable). Installing local Homebrew Bash 5.3.20 resolved the test environment without modifying the legacy deployment script. Old browser-resume expectations were updated to the approved fresh/no-replay contract. A new fixture's missing `prompt: null` caused one TypeScript test-union error and was corrected before the passing frontend/contracts run.

## Real local process HTTP/WS smoke

`python scripts/smoke_home_browser.py` passed against the actual Home runtime SHA above and an actual appliance subprocess, each with temporary private state outside the repository. Enrollment offer, browser enrollment/approval/consume, configuration, H6 grant append, claim minting, HomeBridge, NW18 cleanup, and revocation used real Home APIs. Only the external Standard gateway and silent PCM sidecar were controlled protocol fixtures; this is not real Hermes inference or hardware audio evidence.

Observed final result:

```json
{"smoke":"passed","independent_tabs":2,"prompt_count":5,"dynamic_later_grant":true,"fresh_bridge_and_browser_conversations":true,"revocation_health":503,"cleanup_before_revocation":0,"automatic_replays":0}
```

The run paired a service-private 0600 record, admitted two independent tabs, added/selectably refreshed `Later` with an empty local shortcut catalog, interrupted an active controlled Standard turn, delivered one typed error, admitted a fresh explicit action, closed/reopened the browser connection without automatic claim/prompt replay, confirmed zero remaining claims before revocation, then observed Device revocation and `503 home_unauthorized`.

`--serve` adds loopback-only fixture controls (`status`, `add-profile`, `drop-bridge`, `restart-appliance`, `revoke`) for repeatable actual-browser inspection. They are test harness routes, not appliance or Home production APIs. Restart reuses the same private pairing and Home state on the same local UI port.

## Actual browser and independent review evidence

Managed Chromium exercised the built application with independent reviewer `browser-homebridge-implementation-review`:

- H6 add-profile made `Later` selectable without a local wake phrase. Tabs had different lowercase 32-hex selector tokens; grants and Device credentials did not appear in the browser protocol/UI.
- Two tabs selected different Profiles and concurrent explicit typed turns displayed only their own responses. Counter evidence reached 3 prompts / 2 Standard sessions / 0 resumes, including an earlier single-tab action.
- Page reload changed the selector token. One deliberate next turn changed counts from 3/2/0 to 4/3/0: a fresh conversation, no replay.
- Allowed local Origin with a deliberately incomplete WS handshake produced 426; wrong/null Origin produced 403. Malformed local `/action` requests were 400; wrong/null Origin requests were 403. These are local exact-Origin tests, not production tailnet ACL acceptance.
- Dropping Standard left `/healthz` at 200 while admission remained healthy; no background prompt was generated. This demonstrates the health endpoint's intentionally limited scope.
- An active `hold` turn followed by a Standard drop displayed “Hermes isn't responding. This conversation was not replayed.” The reviewer found a sticky disabled-input defect; after the fix and bundle rebuild, typed input remained enabled and one same-page explicit action succeeded without reloading. Counters changed 3 prompts / 2 sessions / 0 resumes to 5/4/0 for exactly the held action plus the fresh action.
- Actual appliance process restart preserved pairing. The same page reconnected with a fresh selector token and READY; one explicit action changed counts 5/4/0 to 6/5/0. No credentials were read or retained by the reviewer.
- Temporary Device revocation showed the explicit pairing-required error and disabled input, with `/healthz` 503 `home_unauthorized`.
- Implementation-agent Chromium observation independently saw First/Later selector options, then “This display needs to be paired again.” with disabled controls after revocation. Browser local and session storage were both empty. No browser console errors were observed in that inspection.

## Review corrections incorporated

- NW18 close confirmation accepts actual `not_open`, not invented `not_found`.
- Stale-configuration refresh uses the same duplicate-label normalization as regular refresh.
- Selection rechecks active-turn ownership after waiting for the admission lock; a deterministic queued-select/active-turn race regression protects the existing bridge/claim.
- Bridge failures reconcile Home authority, so explicit revocation is not misreported as a Hermes outage.
- Startup refresh is asynchronous so a slow/unreachable Home cannot prevent the local unavailable page from listening.
- Dynamic Profile fields survive prompt capability copies; supported actions reflect the bound bridge.
- Same-page explicit recovery after an active-turn error remains usable without an automatic replay.
- Static handle/environment instructions were replaced with the actual supported pairing and deployment path.
- A reviewer concern that the inherited Puck resume default still applied was withdrawn after checking the explicit browser subclass override.

## Unresolved acceptance gates — not repository completion claims

1. Authorize and perform S7 production deployment; verify actual household Tailscale ACLs, Funnel disabled, public proxy removal, and direct-backend bypass denial for page/WS/actions/health.
2. Real Home/Standard/Hermes operation and physical Safari/iPad microphone, speech recognition, speaker, touch, kiosk/Guided Access, and playback recovery evidence.
3. Existing external monitoring obligations (including credential-expiry signal/probe coverage) remain open acceptance dependencies. This work provides admission health and safe service logging, not new monitoring deployment.
4. Independently authorize R6 default switch and bake, followed by R7 legacy retirement. The retained legacy path is not an eligible Home rollback.
5. Implementation PR and its spec dependency require normal human review/merge; no merge, CI watch, release tagging, production grant mutation, or host action was performed in this task.

## Final local check and review closure

- Ruff `--select F` on the new admission/store/pairing/deploy/smoke modules and their new Python tests: **all checks passed** after deleting two unused imports.
- Final admission regression rerun after that import cleanup: **20 passed**.
- Final sdist/wheel rebuild after cleanup: **passed**.
- Independent reviewer final verdict: **no blocking defect found** in the corrected repository S2/S3/S4 and local S5/S6 paths. The reviewer ran actual Chromium/process checks but did not rerun the test/build suite.
- Real-process forced renewal, stale-configuration injection, failed-close tombstones, and separate Home claim-limit fault injection were not performed. Those boundaries have unit/contract coverage; local smoke must not be represented as fault-injection evidence.
- Installed-wheel package smoke: installed the built wheel and its declared dependencies into a fresh isolated venv, launched its appliance interpreter **outside the checkout** via `scripts/smoke_home_browser.py --appliance-python ...`, and repeated the full actual-Home HTTP/WS smoke. **Passed** with the same 2 independent tabs / 5 explicit prompts / dynamic later grant / fresh reconnects / revocation503 / cleanup0 / automatic replay0 result. This verifies the packaged modules, entry path, declared base dependencies, and bundled assets rather than importing the appliance from source.
- Cleanup: both owned interactive fixture processes exited normally (code 0), removing their temporary private Home/pairing state; the package-smoke venv and owned Chromium tab were removed/closed. Repository source, built distributions, test logs, screenshots, and this evidence remain retained.
