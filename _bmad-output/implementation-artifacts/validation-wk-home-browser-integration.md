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

1. S7 released typed-browser deployment is active from `v0.12.0`; the six-owner household boundary is owner-approved and all three Home Profiles are active. Independent real turns, tabs/reload, and restart persistence passed at the evidence scope below. External-WAN testing remains unperformed.
2. Physical Safari/iPad microphone, speech recognition, speaker, touch, kiosk/Guided Access, and playback recovery evidence remains outstanding; desktop typed-browser checks do not close hardware acceptance.
3. Existing external monitoring obligations (including credential-expiry signal/probe coverage) remain open acceptance dependencies. This work provides admission health and safe service logging, not new monitoring deployment.
4. Independently authorize R6 default switch and bake, followed by R7 legacy retirement. The retained legacy path is not an eligible Home rollback.
5. Implementation PR227 (user-confirmed) and spec PR226 (previous prerequisite inspection) are merged. No release PR merge, new tag, CI watch, production browser grant mutation, or browser cutover was performed during the deployment preflight below.

## Final local check and review closure

- Ruff `--select F` on the new admission/store/pairing/deploy/smoke modules and their new Python tests: **all checks passed** after deleting two unused imports.
- Final admission regression rerun after that import cleanup: **20 passed**.
- Final sdist/wheel rebuild after cleanup: **passed**.
- Independent reviewer final verdict: **no blocking defect found** in the corrected repository S2/S3/S4 and local S5/S6 paths. The reviewer ran actual Chromium/process checks but did not rerun the test/build suite.
- Real-process forced renewal, stale-configuration injection, failed-close tombstones, and separate Home claim-limit fault injection were not performed. Those boundaries have unit/contract coverage; local smoke must not be represented as fault-injection evidence.
- Installed-wheel package smoke: installed the built wheel and its declared dependencies into a fresh isolated venv, launched its appliance interpreter **outside the checkout** via `scripts/smoke_home_browser.py --appliance-python ...`, and repeated the full actual-Home HTTP/WS smoke. **Passed** with the same 2 independent tabs / 5 explicit prompts / dynamic later grant / fresh reconnects / revocation503 / cleanup0 / automatic replay0 result. This verifies the packaged modules, entry path, declared base dependencies, and bundled assets rather than importing the appliance from source.
- Cleanup: both owned interactive fixture processes exited normally (code 0), removing their temporary private Home/pairing state; the package-smoke venv and owned Chromium tab were removed/closed. Repository source, built distributions, test logs, screenshots, and this evidence remain retained.

## Initial authorized production preflight — 2026-10-09 (historical)

- Merged implementation source: `d7d1ede104ec010b198407a345367e423bc07aea`. Deployment is **not performed**: the latest published tag `v0.11.0` (`77a4661ef05d9d99a046278818558c9930ca8880`) lacks `home_display/home_admission.py`, so it cannot satisfy the documented tagged Home deployment gate.
- Release PR [214](https://github.com/achappell/hermes-relay-tui/pull/214) is open at `d303ef2dc75c671270b795b14ecea6930bf8c86d`. Its merge-base is the merged implementation commit above, its tree contains Home admission, and its notes explicitly include PR227. Its only diff is the manifest/version bump to `0.12.0` plus changelog; no release refresh is needed for PR227 at this inspected head.
- Next release action belongs to an authorized release approver: review/merge PR214 through the normal process. `.github/workflows/release-please.yml:3-23` runs on the resulting main push and creates the release/tag; `.github/workflows/release.yml:3-12,53-75` packages an existing `v*` tag and uploads the distributions. The configured dedicated release-token secret exists (name only inspected); future workflow success is not claimed. No manual tag, merge, dispatch, or CI watch was performed.
- Verified strict host-key/BatchMode SSH to Ops, noninteractive sudo, Python 3.14, Tailscale, `flock`, and existing `hermes-home` no-login service identity. The isolated Home-browser unit, release links, and pairing file are absent. Existing browser/Caddy service state and process IDs were unchanged during preflight; zero established browser-backend connections were observed at that instant, not a durable idle guarantee.
- Saved an exact root-owned `0700` rollback capture at `/var/backups/hermes-home-browser/preflight-20261009T020338Z-165g1r6n`: existing unit definitions/state, Caddy files and active configuration, Serve/Funnel configuration, and release-link inventory. All 11 saved-file hashes verified against its manifest; manifest SHA-256 `69e6f48bca75afac805fb0e74e0a4836f63a4020997825970dfa8ef4d8e9004c`. No configuration/private credentials were copied into this repository or this record.
- Serve and Funnel configurations are empty; the existing Caddy browser host still proxies only legacy loopback `8765`, not the new `8875` backend. No route, firewall, ACL, service, legacy gateway, monitoring, or media-server configuration was changed. Tailnet-only acceptance is still required before any real turn; a later rollout must not forward a public legacy route to the new appliance.
- The independent browser reviewer was explicitly told production is not deployed/paired and not to send a turn. No production browser, actual-Hermes, multi-tab, reconnect, restart-persistence, physical voice/iPad, bake, or R7 acceptance is claimed by this preflight. Recheck Home readiness and idle state after an eligible release exists, then follow the isolated pairing/deployment and network-boundary gates.

## Resumed production preflight — 2026-10-09 (before owner boundary decision)

- PR214 is merged by user confirmation; merge status was not rechecked. Published release [`v0.12.0`](https://github.com/achappell/hermes-relay-tui/releases/tag/v0.12.0), published `2026-10-09T02:11:29Z`, resolves to `96efc1b3fcb508e7ba9d31168fa632cc85741226`. `git merge-base --is-ancestor` confirms PR227 source `d7d1ede104ec010b198407a345367e423bc07aea` is included.
- Downloaded the actual [release wheel](https://github.com/achappell/hermes-relay-tui/releases/download/v0.12.0/hermes_relay_tui-0.12.0-py3-none-any.whl). SHA-256 `901a19cb630de7302f790565a9cd626ed87c4e09128b10dd4616d38d4b143f0b` matches the GitHub asset digest. All 50 packaged Python files match tagged source byte-for-byte; Home admission, the browser-pair entry point, and five bundled static assets are present. Local artifact: `/tmp/hermes-browser-release-0.12.0/hermes_relay_tui-0.12.0-py3-none-any.whl`. No new tag, merge, workflow dispatch, CI watch, source build, or test-suite run.
- Fresh strict-SSH observations: legacy browser active; new browser unit inactive, pairing absent, no listener on8875, zero established backend connections on8765/8875; Serve and Funnel remain empty. The protected backup remains root-owned0700. Current Caddy configuration references legacy8765 and does not reference8875. No production mutation was performed.
- Home remains Running at `3a0eec0b9739524e2a8c54fd5a3308b3c3abb90b`; read-only SQLite integrity `ok`, active claims0. Host-local legitimate admin configuration returns200; `/pair` returns200. Configuration has three available Profiles, one shared. This is readiness, not Hermes generation or browser admission acceptance.
- **Exposure blocker:** authoritative effective Ops Tailscale packet filters currently allow TCP443 from15 visible peers belonging to6 distinct owners; the network map contains8 owners. These counts do not establish household membership. Existing deployment/product/homelab notes require private tailnet access but supply no approved household group-to-owner mapping. The Tailscale policy editor redirects to sign-in; no connected browser relay or Tailscale API environment credential is available. No private identity list is retained in this evidence.
- **One owner decision:** identify the exact approved household owners/group for this appliance. A tailnet administrator must then inspect/create the appropriate household group and authorize the narrow browser access policy, excluding any other currently permitted owners without disrupting unrelated Ops services. No group is presumed to exist; broad existing443 access is not accepted as household-only.
- `docs/ops-web-deployment.md:16-24,87-112` requires the verified boundary and pairing before deployment. Home `deploy/windows/README.md:306-333` preserves the legitimate local-admin/owner approval path; existing nonshared Profile holders must approve later grants through their native clients. No offer, pairing, grant, service, Serve, Funnel, firewall, ACL, legacy gateway, or media-server mutation occurred.
- The production witness was informed of the blocker and told not to open/send a turn. No deployed Home-browser URL or admission-health claim exists. Real browser/Hermes, dynamic Profiles, independent tabs, reconnect/no replay, restart persistence, exact Origin/off-tailnet checks, and physical iPad/voice remain unperformed. The backup above remains available; there is no compatible prior Home release and legacy is not a supported Home rollback.

## Owner-approved boundary and one-time pairing — initial approval handoff

- Owner explicitly confirmed all six owners already permitted on Ops TCP443 are household members and constitute the approved boundary. No ACL change is needed or performed.
- Fresh idle checks at `2026-10-09T02:24:23Z`: legacy active/new inactive, no listener8875 or established8765/8875 connections; Home Running with active claims0.
- Reverified the published wheel checksum on Ops and installed it in `/opt/hermes-home-browser/bootstrap-0.12.0/venv`. Created service-owned0700 state directory. Prepared Tailscale Serve HTTPS443 `/` → `http://127.0.0.1:8875`; status has no `AllowFunnel`. No Caddy/public route modification or legacy service/gateway/media-server action.
- Paired **once** using the installed `hermes-relay-browser-pair` CLI as `hermes-home`, hidden SSH TTY code entry, and legitimate Home host-loopback admin offer/approval endpoints. Confirmation codes matched in memory; all three available Profiles requested with no wake mappings. Pair CLI exited0 and saved one credential. No secrets or grant IDs are recorded here.
- Separate service-user configuration read verified persistence: file0600, correct owner, one hardlink, not symlink, parent0700; real Home device catalog returns Amanda `pending_owner`, Jensen `pending_owner`, Spark `active`. Admin approval cannot substitute for existing native Profile holders.
- **User action:** in an already-paired native owner client for Amanda, run `/home pending`, select **Household browser appliance**, then `/home approve <grant-id>` using the ID shown locally. Repeat as Jensen's existing native owner client. `README.md:115` documents these commands; `/approvals` is not the documented TUI command. No new enrollment code or re-pairing is needed. Home admin page remains `https://caticornqueen.taila59979.ts.net/pair`.
- Per explicit user instruction, stop at this owner-approval gate. The tagged deployment helper has not run; no new browser service/listener/UI or health result exists. Candidate origin `https://ops.taila59979.ts.net` is not readiness authorization. The independent witness was told to hold all probes/turns.
- After approvals, refresh the same saved Device catalog, repeat idle readiness, invoke `scripts/deploy_home_browser.py` with `v0.12.0`, then verify the complete boundary and browser behavior. Do not enroll again. Existing protected backup remains; there is no compatible prior Home browser release. The scoped Serve reversal is `tailscale serve --https=443 off` (not executed). Home's package rollback guard now correctly blocks pre-browser rollback while this browser credential exists.

## Active released Ops deployment — 2026-10-09

- Actual saved-Device catalog now confirms Amanda, Jensen, Spark `active`/usable after owner approvals. No re-pairing or second offer.
- Fresh predeploy Ops check `02:30:39Z` found no backend connections. Home had one other-Device claim; no Home restart/global cleanup occurred. Appliance-own claims baseline was0.
- Invoked documented `scripts/deploy_home_browser.py deploy --ops-host jensen@ops --origin https://ops.taila59979.ts.net --home https://caticornqueen.taila59979.ts.net --tag v0.12.0`; temporary transport wrappers enforced BatchMode and StrictHostKeyChecking=yes for every helper SSH/SCP call, then were removed.
- Tagged verification: **1726 Python tests passed,31 skipped,6 warnings**; **224 web tests passed**; Svelte check0errors/0warnings; web and wheel builds succeeded. New service installed and started. Helper final smoke exited1: its legacy expected400 body is `action_id and choice are required`, but the Home route's actual400 is `action_id is required`. This released checker mismatch was diagnosed, not suppressed or mistaken for a failed installation. No released source was patched.
- Active release `96efc1b3fcb508e7ba9d31168fa632cc85741226`; helper-built installed wheel digest `0018895cce4421c338433f76bf0c5171c643c47b3b655f588f16750d05b1d7b5`. All50 installed Python files and all5 static assets match published wheel content byte-for-byte. Published ZIP digest remains `901a19cb…`; the helper rebuild ZIP is not claimed to be the downloaded ZIP.
- URL **https://ops.taila59979.ts.net**. Loopback and tailnet health200 `{"status":"ok"}` (admission-only). Dedicated service active/enabled, sole listener127.0.0.1:8875, service user/group `hermes-home`, UMask0077, NoNewPrivileges, ProtectSystem=strict, ProtectHome, PrivateTmp. Pairing0600 in0700 directory, service-owned, single-link/not symlink; shortcut catalog empty.
- Fresh effective TCP443 owner set matches exactly the owner-approved six-owner snapshot (15 peers). Serve whole-origin→8875, no Funnel. Caddy live config has zero8875 references and retains legacy8765.
- Tailnet exact-Origin probes: allowed malformed action400; wrong/null action403; allowed WebSocket101 advertises all three available Profiles; wrong/null WS403. Missing-Origin WS101 is supported for native clients. Static page/health200 regardless Origin is consistent with the network authentication boundary.
- Direct8875 to Ops LAN/tailnet addresses refused; no IPv6 listener. Correct-hostname/SNI HTTPS directed to physical LAN IP fails TLS before HTTP: actual non-tailnet Caddy bypass denied, not merely inferred from tailnet success. No independent external-internet vantage was exercised.
- Legacy browser remained active with unchanged PID892928. No legacy gateway/media-server/monitoring changes. First Home release has no compatible previous rollback; protected backup remains. Home pre-browser package rollback guard now protects the active browser credential.
- Independent witness authorized for bounded real browser turns and coordinated idle-only restart. No physical iPad/voice, bake, R7 retirement or external-WAN acceptance is implied.

## Independent production browser and safe restart evidence

- First independent witness: three benign real typed turns across two isolated Chromium tabs, including reload then explicit fresh action. Replies stayed in their owning tabs; reloaded composer was empty and prior prompt absent before the next explicit action. Three dynamic enabled Profiles, disjoint per-tab opaque selector tokens, successful Profile switch; health200 before/after reload. Source: `local://browser-production-verification.md`.
- Second independent verifier completed three additional benign turns (two tabs, Profile switch), then explicitly closed both tabs. These browser observations show per-tab transcript/WebSocket isolation and no visible replay, not inspected internal Home session IDs. No conversation content or secrets retained in this record.
- Rollout-side idle Chromium observation also found empty local/session storage and no JavaScript errors. Unprivileged `nobody` cannot read the private pairing file.
- Before the single persistence restart: both verifiers confirmed tabs closed, appliance-own claims0, no established8875 connections. An earlier conservative socket gate prevented a restart while the second verifier was still connected; it did not interrupt that verifier.
- Exactly one new-service restart completed, PID2893857→2897313; legacy PID892928 unchanged. Private pairing bytes are identical to pre-turn baseline, permissions0600/0700 preserved, health200ok. Second verifier reopened a fresh tab: all three Profiles appeared without re-pairing, a benign Jensen turn succeeded, browser storage/cookies/URL/console stayed clean, then the tab closed.
- Final read-only Home DB aggregate for this appliance:8 claims,8 distinct session IDs,8 distinct claim refs,0active,3Profiles used; close reasons7`stopped`/1`client_closed`. IDs and conversation content not printed. This supports distinct session allocation across observed claim lifecycles, not packet-level replay counting.
- Two witnesses completed seven successful benign typed turns total (first3, second4 including post-restart). Witness2 independently verified same-Profile tab isolation, reload receiving only a snapshot/no voice-send before explicit action, browser credential absence, backend refusals and legacy-host separation. Final shared report `local://browser-production-verification.md` now contains witness2's report; the first report's completed results were preserved in the summary above before replacement.
- Witness2 observed one initial Spark Profile-switch error stating Hermes was not responding/no replay; a subsequent Spark selection and real turn succeeded. Cause undetermined. This observation and the deploy-checker400-wording defect remain explicit limitations, not hidden by healthy final admission.
- Final result: **released typed-browser rollout usable at https://ops.taila59979.ts.net, health200ok, no re-pair, no further owner action required**. No independent external-WAN, physical iPad/voice/hardware, bake, broader monitoring or R7 retirement acceptance claimed.

## Owner acceptance — 2026-10-09

Amanda explicitly accepted `WK-1` and `WK-2` as done on 2026-10-09, and the tracker moved `1-wk-1-one-shared-w-k-browser-voice-plus-display-surface-for-author` and `1-wk-2-concurrent-w-k-browser-session-isolation` from `review` to `done`. `WK-1`'s own spec status changed to `done` accordingly (`WK-2`'s spec already read `done`).

Evidence supporting the acceptance, all recorded above:

- Production: released `v0.12.0` (`96efc1b`) deployed on Ops at `https://ops.taila59979.ts.net`, Tailscale-only with no Funnel; Home on `main` `3a0eec0`. Merged PRs: TUI [#226](https://github.com/achappell/hermes-relay-tui/pull/226), [#227](https://github.com/achappell/hermes-relay-tui/pull/227), [#229](https://github.com/achappell/hermes-relay-tui/pull/229), [#231](https://github.com/achappell/hermes-relay-tui/pull/231); Home #102, #103, #104.
- Two independent witnesses ran seven real typed turns total; dynamic Profiles Amanda, Jensen and Spark; two-tab isolation; fresh reload with no replay; no browser credentials; wrong-Origin rejection; restart persistence (section "Independent production browser and safe restart evidence").
- Owner-reported: Amanda manually tested typed and real voice turns on her iPad in Safari. This is the owner's report; no instrumented capture of that session is recorded here.

Not claimed by this acceptance: external-WAN probing, Guided Access/kiosk, other-browser or other-hardware validation, broader monitoring, the unexplained one-time Spark Profile-switch error, or the deploy-checker `400` wording mismatch listed above (those limitations stand as written). `WK-HOME-01` stays `in-progress`: R6 default switch/bake and R7 legacy retirement are not done.
