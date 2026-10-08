---
id: WK-HOME-01
title: 'Migrate the production W/K browser and iPad appliance to HomeBridge with claim-based admission'
type: 'feature'
created: '2026-10-08'
status: draft
product_epic: 3
surface: 'W/K'
depends_on:
  - home:HOME-NW-17
  - home:HOME-NW-18
  - home:HOME-NW-17-browser-admission
  - tui:TUI-HOME-01
  - tui:STD-8
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/course-correction-2026-09-23.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-standard-8-wk-migrate-browser-ipad-routes.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-wk-concurrent-browser-session-isolation.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-ops-web-deployment-pipeline.md'
  - '{project-root}/docs/ops-web-deployment.md'
---

> **Status: draft.** `WK-1` and `WK-2` stay in `review` and this spec does not change them. The owner-approved decisions dated 2026-10-08 are recorded in [Owner decisions](#owner-decisions); every remaining design choice is still a numbered question with a `PROPOSED` default. No source, deploy or host change is made by this document.
>
> Evidence tags: **[FACT]** cites a file and line on `origin/main` (TUI `9afdd51`, Home `71539fc`). **[INFERENCE]** is my conclusion from facts. **UNKNOWN** is not established by any artifact I could read. Host facts come from the 2026-10-08 read-only Ops diagnosis (a session artifact, not committed here); they are tagged **[OPS]**.

# WK-HOME-01 — production W/K on HomeBridge

## Intent

**Problem.** The production browser surface still runs the legacy per-profile `/voice-session` transport, whose upstream listeners are gone, so `/state` closes `1011` and the household sees a silent "disconnected". The supported path for W/K (`Puck, Touch and shared W/K browser room surfaces use HomeBridge in this release`, `course-correction-2026-09-23.md:17`) exists in code but is opt-in, is not what is deployed, and cannot yet be run in production: it needs a static operator-minted conversation handle that Home retires, one Profile per process, and a credential file that never renews.

**Approach.** Pair the appliance with Home once as one Device holding grants for every Home-authorized Profile; add newly authorized Profiles when their grants are approved. There is no separate browser sign-in: anyone who can reach the appliance page can use those authorized Profiles. Each browser connection claims its own Home conversation for the Profile chosen by the household's configured wake phrase, opens it on the HomeBridge, and closes it when that browser leaves. Add an honest, user-visible "unavailable" state with a stable reason, and an Ops-visible health signal. Switch the managed deployment to the Home transport, then retire the legacy browser transport on the HOME-MIG-09 schedule.

**Success.** `WK-1` and `WK-2` can be accepted on the supported path: two real browsers (Mac Chrome and iPad Safari) hold independent Home conversations through the deployed appliance, an outage of Home or Hermes is shown to the user with a reason and is visible in Grafana within minutes, and nothing in the managed deployment depends on a modified agent or `voice-*.chappell-home.dev` gateways.

## Current state inventory

### What the production unit runs [FACT/OPS]

| Item | Fact | Source |
|---|---|---|
| Unit | `ExecStart=… hermes-relay-home --browser-voice --config …/profile-config.yaml --profile-env /etc/hermes-relay/home.env --display-host 127.0.0.1 --display-port … --display-public-origin …`; no `--browser-transport`, so `legacy` | `deploy/systemd/hermes-relay-home.service:12` |
| Default transport | `legacy` unless flag, `HERMES_RELAY_TUI_BROWSER_TRANSPORT` or config says `home` | `home_display/appliance.py:347,2860-2871,2957-2964` |
| Docs | "The managed service's `ExecStart` intentionally remains on `legacy` until the Home route has passed its deployment gate" | `docs/ops-web-deployment.md:14-17,134-138` |
| Deployed build | wheel `0.9.0`, commit `43abe8ae…`, 2026-09-13; predates STD-8 (`4165da7`, first released in `v0.11.0`) and PR #225 | [OPS]; `pyproject.toml:7` (`0.11.0` on main) |
| Legacy upstream | Caddy on Ops proxies `voice-{amanda,jensen,spark}.chappell-home.dev` to the Mac mini `:8792/8793/8794`; all three refuse TCP → HTTP 502 → `connect.failed type=InvalidStatus` → `/state` closes `1011` | [OPS] |
| Cause of the listeners being down | UNKNOWN. A 2026-09-27 gateway consolidation is a candidate; no artifact records the listeners being stopped on purpose | [OPS]; no vault or repo record |
| Health signal today | None. `/` returns `200` while every session fails; Prometheus has no `probe_success` for these hosts; the appliance logged nothing for `1011` before PR #225 | [OPS] |

### What `HomeBrowserSession` and the Home transport do today [FACT]

- **Selection is fail-closed.** `--browser-transport home` needs `--browser-voice`, an exact `wss://…/api/v1/bridge/ws` URL, a Device credential and a conversation handle; the process refuses to start without them and never falls back to a bearer profile (`appliance.py:1902-1935,2382-2394`; `puck_bridge/home_session.py:144-162`).
- **One static handle, shared by every browser.** `_create_browser_session` builds a fresh `HomeBrowserSession(url, credential, handle)` per socket but passes the same configured handle to all of them (`appliance.py:1997-1999`). STD-8 deferred exactly this question: "Define whether independent Home browser bindings may reuse one opaque handle and durable Standard Session while preserving concurrent W/K session isolation" (`deferred-work.md:266-270`; `spec-standard-8-…md:183`). **UNKNOWN** whether Home accepts two concurrent `conversation.open` calls on one handle; Home's claim store binds one claim to one Standard Session (`HOME-NW-17` spec `:54`; Home `production.py:296-306`), so the WK-2 isolation guarantee cannot be assumed.
- **Handle lifetime does not fit an appliance.** A claim that is never opened expires after 90 s (`production.py:52`, `NW-17 spec :53`). A wake or tap claim also ends 8 s after playback (`HOME-NW-16 spec :26`). An operator-minted handle in an env file is therefore a disposable test input, not a service credential. [INFERENCE] a restart, an idle hour or a Home restart (which closes every claim, `validation-home-mig-09-readiness.md:189`) leaves the appliance with a dead handle.
- **One Profile per process.** In Home mode `candidates = [self._active_profile]` (`appliance.py:2008-2009`), `_switch_profile` returns `False` ("Home owns browser profile routing", `:2167-2169`), and `route_profile` keeps the wake phrase only as a gate; it never selects a different conversation (`:2229-2257`). The three-phrase catalog (`hey missy`/`hey skippy`/`hey spark`) that production advertises is therefore not honoured by Home mode.
- **Credential never renews.** The Device credential is read from a file or env var once (`appliance.py:355-363,1914-1920`). Home credentials last 90 days and renew inside a 14-day window (Home `credentials.py:34-35`; TUI client renew logic at `home_client.py:335-350`). [INFERENCE] a static file credential stops working after 90 days with no warning.
- **Auth shape.** `Authorization: Device <credential>` on the bridge (`home_session.py:182`); the browser never sees it (`STD-8 spec :56-58`).
- **Capacity.** Admission is reserved per socket before any upstream work; at the cap the socket closes `1013 "browser session capacity reached"` and the page shows "All browser sessions are busy — retrying" (`server.py:48-53,693-701,1018-1025`; `web/src/state/channel.ts:151`; `web/src/surfaces/StateSurface.svelte:41-42`). Cap is `--display-max-browser-sessions`, default 8 (`appliance.py:3003-3009`).
- **Failure today.** A factory error closes the socket `1011 "browser session unavailable"` after logging only the exception type (`server.py:869-875`, PR #225; `appliance.py:2063-2085`). The page cannot tell this from any other close: every non-`1013` close renders "Display disconnected — check the host connection" (`channel.ts:151`; `StateSurface.svelte:29`; `App.svelte:203-210`). The reason string is not read.
- **No deep health.** `DisplayServer` serves `/state`, `/action` and static files only (`server.py:540-610`). The deploy smoke check requires a first snapshot (`scripts/check_ops_web.py:129-176`). [INFERENCE] in browser-context mode that snapshot is only sent after the upstream session connects (`appliance.py:2044-2053,2078-2086`; `server.py:750-754,869-875`), so a deploy while upstream is down fails the smoke check and rolls back (`deploy_ops_web.sh:1023-1063`).
- **Touch already uses claims, browser does not.** `TouchDoorway` claims over HTTP on the first `mic_start` and never holds a session before then (`appliance.py:2111-2144`; `touch.py:1-21,222-286`). `--touch-voice` and `--browser-voice` are mutually exclusive in one process (`appliance.py:2349-2354`).

### What Home offers [FACT]

- **Personal-client admission already exists and is deployed to the tailnet.** `POST /api/v1/client-claims` takes a paired Device and one of its `grant_id`s and returns an opaque handle; session choice `new`/`most_recent`/`resume`; no Room, no arbitration, no idle timer; per-device limit 8; reconnect grace 120 s; revoke closes claims (`HOME-NW-17 spec :51-57,97-148`; `production.py:246-348`). The route is among the paths Serve publishes (`hermes-relay-home/deploy/windows/README.md:316-319`).
- **`HOME-NW-18`** adds `GET /api/v1/client-claims` and `POST /api/v1/client-claims/close` so a device can list and release its own claims, written after an iPad refusal loop created seven unopened claims in 19 s and hit `claim_limit` (`HOME-NW-18 spec :23`).
- **The client kinds that may hold `client_claim` are `tui`, `ios`, `macos`, `android`** (`credentials.py:39,609-611`). A `client_claim` credential cannot also carry `wake_claim` or `touch_claim` (`:604-608`). There is no browser or display kind.
- **Pairing requires `secure_storage == "platform_secure_store"`** (`credentials.py:38,407,678`). The TUI refuses to pair without macOS Keychain or Linux Secret Service (`home_client.py:145-160`; `README.md:102`).
- **Owned Profiles need owner approval.** A grant to an owned Profile that another live device already holds is `pending_owner` until a holder approves it (`credentials.py:1180-1215`; `NW-17 spec :48`). Any device holding an active grant for the Profile can approve others, with no device-type check (`credentials.py:1029-1062`).
- **Device capabilities are deny-by-default.** `sensitive_entry` and `consequence_confirm` must be granted in both credential scope and device configuration (`HOME-NW-10 spec :20,41-50`). The browser UI cannot collect secret/sudo values (`docs/ops-web-deployment.md:35-38`).
- **Health read exists but is Room-bound.** `GET /api/v1/devices/{id}/health` reports route, authorization, bridge and Standard readiness without opening a conversation, but needs `health_view` and a target device whose `room_id` is in the caller's scope rooms (Home `application.py:695-736`; `HOME-NW-09 spec :19-27`). A client device has `rooms: []` (`NW-17 spec :78`). **UNKNOWN** whether a client device appears in `configuration["devices"]` at all.
- **Home has no browser-admission story.** No browser, display or W/K kind appears in `src/hermes_home` (grep of the repository for `browser`/`kiosk` returns only an Origin check at `api/pairing.py:427`).

### Reuse candidates in this repo [FACT]

`home_client.py` (`HomeClient`: `credential()` with renewal, `configuration()` → grants, `claim()`; `:264-376`), `home_pairing_cli.py` (pairing; hardcodes `type: "tui"`, `:47`), `puck_bridge/home_session.py` (`HomeBrowserSession`, `close_claim`, `retire_uncertain_claim`, `:1352-1431,2181-2222`). Missing: a file-backed pairing store with renewal for a headless service, claim list/close calls, and the per-connection grant routing.

## Target design

### 1. Admission model (Q3, Q4, Q5)

- **APPROVED 2026-10-08:** pair one appliance Device once, not one Device per browser. It holds `client_claim` and grants for all Home-authorized Profiles, including Profiles authorized later once their grants are approved. Browsers hold no Home credential; the appliance remains the trusted adapter (`STD-8 spec :47-52`). No separate browser sign-in exists: anyone who reaches the page may use the appliance's authorized Profiles. Browser access is restricted to the household Tailscale network only, not the public Internet; this is a network boundary, not per-user authentication.
- **PROPOSED Home change** (draft stub `HOME-NW-17-browser-admission`, Home repo): add a `browser` endpoint kind that may hold `client_claim` (today `CLIENT_ENDPOINT_TYPES`, credentials.py:39); a `browser` device never counts as an owner approver or holder-list viewer for owned Profiles; define how a service-hosted appliance attests its credential store (Q5); keep `sensitive_entry`/`consequence_confirm` omitted. The minimal alternative with no Home change is to pair as `tui`; that is not recommended because the shared display would then be an owner approver for every Profile it holds.
- **Pairing procedure:** the operator pairs the appliance once on Ops against Home's `/pair` page (`NW-17 spec :150-152`), approves it on the page, and approves owned Profile grants from an existing holder (`/approvals` in the TUI, `NW-17 spec :286`). The result is a private pairing record readable only by the service user. No credential or `grant_id` is placed in YAML, a unit file, a URL or a log.
- **Credential record and renewal (PROPOSED Q5):** a private file under a systemd `StateDirectory`, same record shape as the TUI's (`home_client.py:129-143`), written atomically under the same cross-process lock pattern (`:203-223`); the appliance renews inside the 14-day window on start and on a daily timer. A renewal that fails inside the window turns the health signal `degraded` with reason `credential_expiring` (see Health) long before the 90-day expiry. Secret Service is not used: availability on the headless Ops host is **UNKNOWN**, and the TUI refuses insecure fallbacks (`home_client.py:146`), so the appliance needs its own explicit, owner-approved store.

### 2. Profile mapping (Q6, Q7)

- The local catalog represents all Profiles Home authorizes for this appliance, not a fixed list of three. It keeps each Profile's `display_name` and appliance-local `wake_phrases` and replaces `url`/`token_env`/`client_id`/`device_id`/`session_id` with one field naming the Home grant by label (for example `home_grant: Amanda`). Labels resolve to Home-minted opaque `grant_id`s from device configuration at connect (`home_client.py:352-357`). Newly authorized Profiles become available once their grants are approved and the appliance refreshes its configuration. Duplicate or missing labels fail closed for that Profile.
- A wake phrase selects the grant for the next conversation. A Profile ID never crosses the bridge (`STD-8 spec :66`); a `grant_id` is sent only on the Home HTTP claim route (`home_client.py:359-376`).
- Switching Profile while idle closes the current claim, then claims the new grant; during an active turn the existing `active_turn` rejection stays (`appliance.py:2246-2253,2264-2300`). A Profile whose grant is `pending_owner`, revoked or unavailable is reported as unavailable for that Profile only; other Profiles keep working (reuse the "Profile unavailable: X" status, `appliance.py:2196-2199`).
- Wake phrases stay appliance-local configuration for this migration. Home-owned custom wake phrases are `HOME-NW-13`, `backlog`, `scope-decision` (`validation-home-mig-09-readiness.md:96`).
- The deploy validator currently demands exactly the three legacy profiles and their token bindings (`scripts/validate_ops_profile_config.py:15-20,50-70`); it needs a Home-mode schema (slice S6).

### 3. Per-connection lifecycle (Q8, Q9)

1. **Accept socket.** Existing slot reservation and `1013` at the cap, unchanged (`server.py:693-702`).
2. **Preflight (PROPOSED).** Renew the credential if due, read device configuration, resolve grants. No claim yet. Failure ends the connection with a typed reason (below). Success publishes `idle` with the existing catalog capabilities so the smoke check and the page behave as today.
3. **First routed turn or wake-only route.** Make one client claim for the selected grant with `session: {mode: "new"}`, then open it with `HomeBrowserSession` (`conversation.open`, `home_session.py:704-741`). Never `most_recent` or `resume`: a browser reload must not inherit another conversation (WK-2 "fresh no-replay reconnects").
4. **Browser leaves.** Cancel the turn, `close_claim()` (`home_session.py:1352-1370`); if unconfirmed, `retire_uncertain_claim()` (`:1372-1431`); otherwise Home's 120 s reconnect grace reclaims the slot (`NW-17 spec :53`). The stored Standard session is untouched.
5. **Appliance start.** Sweep: list this device's own claims and close them by `claim_ref` (`HOME-NW-18`), so a crash or restart does not hold the per-device limit for up to about 240 s (`HOME-NW-18 spec :57`).
6. **At most one claim attempt per user action, no automatic claim retry.** The NW-18 incident was a client refusal loop (`HOME-NW-18 spec :23`).

PROPOSED rationale for claim-at-first-turn rather than at connect: an idle kiosk page then holds no Home claim and no Standard session, the 90 s first-open expiry cannot leak slots, and it matches the Touch doorway (`appliance.py:2116-2119`). The cost is added latency on the first turn, **UNKNOWN** until measured.

### 4. Capacity and `1013` (Q10)

- `1013` keeps one meaning: the appliance's own browser cap (`server.py:693-701`). Default stays 8, which equals Home's default per-device claim limit 8 (`production.py:53`; Home `runtime.py:232`). Claims never exceed live browser sockets because close precedes re-claim.
- A Home `claim_limit` (or `profile_unavailable`, `grant_pending`) denial is a typed turn-time unavailable state, never `1013`: the page retries `1013` automatically and an automatic retry is how NW-18's loop happened.
- The appliance cap must be less than or equal to Home's per-device claim limit; Home does not expose that limit to the device (**UNKNOWN**), so it is a documented deploy-time check (slice S6).

### 5. No-replay reconnect

Unchanged guarantees, now stated against Home: a browser socket reconnect is a new connection, a new claim and a new Standard session; no prior prompt or uncertain turn is replayed (`spec-wk-concurrent-browser-session-isolation.md:44,145`). A bridge drop inside Home's parking grace uses `conversation.reconnect` on the same claim and marks the turn uncertain (`home_session.py:719,735-741`; `STD-8 spec :79`). A drop beyond the grace ends the claim; the next turn needs a new claim and the page says so.

### 6. Honest "unavailable" (Q11)

Allowlisted reason tokens, produced by the appliance from typed errors, never from upstream text:

| Token | Meaning | User-visible sentence (PROPOSED) |
|---|---|---|
| `home_unreachable` | TCP/TLS/timeout/5xx talking to Home (`home_client.py` `transport`, `service_unavailable`) | "Hermes Home can't be reached. Retrying." |
| `home_unauthorized` | Credential revoked, expired or rejected (`unauthorized`) | "This display needs to be paired again." |
| `hermes_unavailable` | Home is up but its Standard Hermes is not (Home bridge status `unavailable`/`hermes_unavailable`, Home `bridge/endpoint.py:972,173-183`) | "Hermes isn't responding. Retrying." |
| `profile_unavailable` / `grant_pending` | Per-Profile grant not usable | "<Name> isn't available on this display." |
| `claim_limit` | Home's per-device limit | "Too many conversations are open. Try again in a moment." |
| `at_capacity` | Existing `1013` | existing text (`StateSurface.svelte:41-42`) |

- **Delivery.** Close code stays `1011` for unavailable; the close reason carries the token (a WebSocket close reason allows 123 bytes). `channel.ts` reads `event.reason`; an unknown token falls back to today's generic text. A turn-time failure publishes a snapshot with `status_text` instead of closing.
- **Server logs.** One structured line per failed admission: `browser.admission.failed reason=<token> exc=<type> connection=<short id>`, at WARNING (unavailable) or ERROR (`home_unauthorized`), rate-limited per reason. No credential, handle, `grant_id`, `claim_ref`, URL or upstream message is ever logged (`HOME-NW-18 spec :37` forbids logging these identifiers on the Home side; the appliance follows the same rule). This extends PR #225, which logs only the exception type (`server.py:869-872`; `appliance.py:2065-2084`).

### 7. Ops-observable health (Q12)

- **PROPOSED `GET /healthz`** on the display server, exposed only over the household Tailscale network (never the public Internet): `200 {"status":"ok"}` or `503 {"status":"degraded","reason":"<token>"}`. The backend listener must not be directly reachable in a way that bypasses the tailnet-facing proxy boundary. It reflects a cached background check every 30 s (credential valid and not inside its renewal window unrenewed; Home reachable; at least one grant usable) plus the age and reason of the last real admission failure. It never creates a claim or a Standard session. The Origin check is not applied; the body carries a token only.
- **Prometheus/Grafana.** A blackbox HTTP probe of the tailnet-only health URL `https://<appliance tailnet host>/healthz` yields `probe_success` and an alert, which detects an outage with no user traffic. The probe must run from the household Tailscale network and must not require a public route. The Ops diagnosis shows why logs alone are not enough: Loki had no refusal lines until someone connected (`[OPS]`). A Loki alert on `{unit="hermes-relay-home.service"} |= "browser.admission.failed"` complements it; Alloy already ships that unit's journal (`[OPS]`). Whether a blackbox exporter exists on Ops is **UNKNOWN**.
- **Deeper Standard-readiness check (optional, depends on Home).** Home's device health read already checks Standard readiness without a session, but needs a Room-bound target (`application.py:695-736`). The Home stub lists extending it to a self-targeting roomless client device as optional work (Q4).

## Deployment changes

| Area | Change | Evidence |
|---|---|---|
| Unit | `ExecStart` adds `--browser-transport home --home-bridge-url wss://<home tailnet host>/api/v1/bridge/ws`; adds `StateDirectory=` for the pairing record; drops the legacy `--profile-env` token source; sets the display origin to a household-Tailscale-only hostname and ensures the backend listener cannot be reached directly around the proxy. `After=`/`Wants=tailscaled.service` so a boot with no tailnet starts degraded rather than failing | `deploy/systemd/hermes-relay-home.service:3-5,11-12` |
| Home host name | The Home tailnet name is not recorded in either repo (only the example `caticornqueen.example.ts.net`, Home `NW-17 spec :65`). UNKNOWN | — |
| Env file | `/etc/hermes-relay/home.env` currently holds the legacy session variables and three profile tokens (names only, [OPS]); the Home transport needs none of them. They are removed at retirement (R7(b)), not at switch | `docs/ops-web-deployment.md:55-71` |
| Profile catalog | New schema: `display_name`, `wake_phrases`, `home_grant`; support all Profiles authorized to the appliance, including new ones after grant approval. Validator and example replaced for Home mode | `deploy/ops/hermes-home-profile-config.yaml.example`; `validate_ops_profile_config.py:15-70` |
| Deploy script | `deploy` currently requires `--profile-config` and `--profile-env-source` and merges the three token bindings into the service env; Home mode needs a catalog without tokens, no env merge, and the pairing record preserved across releases | `scripts/deploy_ops_web.sh:68-69,202,596-631` |
| Smoke check | Still requires the three wake phrases and a first snapshot (`check_ops_web.py:129-176`); add a `/healthz` check. A deploy while Home is unreachable fails the preflight and rolls back by design; the runbook must say so | `deploy_ops_web.sh:1023-1063` |
| Network boundary | Browser page, display WebSocket, and all appliance backend routes must be reachable only over the household Tailscale network, never the public Internet. Protect the backend listener from direct/public access that bypasses any tailnet-facing proxy rule; there is no separate browser sign-in. | Approved owner decision, 2026-10-08 |
| Caddy | Keep the browser-serving route tailnet-only; no public-origin path to the page or its WebSocket/backend. Preserve backend bypass protection when proxying from Tailscale. The `voice-*` site blocks are Ops-owned and not in this repo; they are removed at retirement | [OPS] |
| Ordering | Home runs on CaticornQueen (Windows), not on Ops (`validation-home-mig-09-readiness.md:41-62`), so there is no systemd ordering against Home. The dependency is tailnet reachability from Ops to the Serve route; the `tag:ops` → CaticornQueen grant is **UNKNOWN** (only `tag:home` → `tag:ops tcp:3100` is recorded, Home `validation-home-nw-06-diagnostics-exporter.md:140`) | — |
| Rollback | Release rollback (`deploy_ops_web.sh rollback`, `docs/ops-web-deployment.md:154-167`) restores code, catalog and env, but the previous release is the legacy build whose upstream is dead. Per the course correction the fork is not restored as the product: "If no compatible recovery build exists, pause the rollout and leave the affected surface explicitly unavailable" (`course-correction-2026-09-23.md:71`). PROPOSED: rollback target is the previous Home-mode release; if none, the surface shows the honest unavailable state | — |
| Legacy default | See [Legacy retirement](#legacy-retirement) | — |

### Legacy retirement

- `HOME-MIG-09` owns the order: R3 gate, R4 pilot (room devices after personal clients, `OD-12`), R5 runbook, R6 switch the default, a 24-hour bake, then R7 stop services, invalidate credentials, and remove code in a separate PR (`validation-home-mig-09-readiness.md:111-115,257`).
- **PROPOSED mapping for W/K.** Switching the *managed unit* to Home is slice S6/S7 and is the R4 pilot for this surface. The code default changes from `legacy` to `home` at R6. The `legacy` transport, the `voice-*` Caddy blocks, the three profile tokens and the legacy catalog schema are removed at R7(c) under `TUI-RETIRE-01` ("Inventory/remove old voice-session pairing, fork adapters, config, launch scripts and docs across TUI/Puck/Touch/WK", `spec-tui-retire-01.md:12`). `TUI-RETIRE-01` stays `backlog` and is not edited by this spec; its W/K inventory row is satisfied by slice S8 here.
- No rollback to legacy is a supported recovery target (`course-correction-2026-09-23.md:27,71`; `validation-home-mig-09-readiness.md:189`).

## Owner decisions

All defaults are **PROPOSED** unless marked approved below. Approved owner decisions dated 2026-10-08:

- **Q3 (approved):** one paired appliance Device, not a Device per browser.
- **Q6 (approved):** grants cover every Home-authorized Profile, including new Profiles after grant approval; not a hardcoded three.
- **Q9 (approved):** reload/reconnect starts a fresh conversation with no automatic replay; browser tabs are independent.
- **Q16 (approved):** household Tailscale access only, not public; include WebSocket/backend bypass protection. No separate browser sign-in: anyone who reaches the page can use the appliance's authorized Profiles.

1. **Interim for the live outage.** Do nothing to the legacy path, or restore the Mac-mini listeners as a time-boxed exception? **PROPOSED:** do not restore the fork gateways as a supported product (`course-correction-2026-09-23.md:27,71`); ship the honest-unavailable state in S4 first and the health signal in S5 after S1/S2 prerequisites, leaving the surface "unavailable" until S7. A restore, if wanted, is a recorded owner exception and does not count toward WK-1/WK-2 acceptance.
2. **Acceptance path.** Are `WK-1` and `WK-2` accepted only on the Home path with real-browser evidence? **PROPOSED:** yes. The code is transport-agnostic, but their live gates cannot run on a dead legacy upstream.
3. **Trust model (approved).** One paired appliance Device, not one Home Device per browser. This appliance is the trust boundary.
4. **Home device kind.** Add a `browser` kind in Home (new stub `HOME-NW-17-browser-admission`: kind allowed to hold `client_claim`, never an owner approver, optional roomless self-health) or pair as `tui` with no Home change? **PROPOSED:** add `browser`.
5. **Credential storage on Ops.** Home requires the attestation `platform_secure_store` (`credentials.py:407,678`). **PROPOSED:** a systemd `StateDirectory` file (mode 0600, service user) with renewal write-back, and a Home attestation value for service-hosted private-file storage accepted only for `browser`. Alternative: Secret Service on Ops if it exists.
6. **Which Profiles and who approves (approved).** Use all Home-authorized Profiles, including new Profiles once their owned grants are approved by existing holders through `/pair` and the TUI `/approvals`; do not hardcode the current three.
7. **Wake phrase to Profile mapping.** **PROPOSED:** keep wake phrases as appliance-local config mapped to grant labels; do not wait for `HOME-NW-13`.
8. **Claim timing.** At socket accept or at the first routed turn? **PROPOSED:** first routed turn, with a connect-time preflight.
9. **Session per browser connection (approved).** Reload/reconnect starts a fresh conversation; no automatic replay; tabs remain independent.
10. **Capacity.** **PROPOSED:** keep the appliance cap at 8, document that it must not exceed Home's per-device claim limit, and map Home `claim_limit` to a typed message, not `1013`.
11. **Reason vocabulary and wording** in the table above, and whether they may name Home/Hermes in household-visible text. **PROPOSED:** as tabled.
12. **Health signal.** `/healthz` plus a blackbox probe plus a Loki alert, or metrics only? **PROPOSED:** `/healthz` plus probe plus Loki alert; Standard-readiness depth deferred to the Home stub.
13. **Legacy removal timing.** **PROPOSED:** default flips at R6, code removal at R7(c) under `TUI-RETIRE-01` after a 24-hour bake (`OD-12`); managed unit switches in S7.
14. **Naming.** TUI story `WK-HOME-01` (epic 3) and Home story `HOME-NW-17-browser-admission`, versus a new `NW-19` number. **PROPOSED:** the names used here.
15. **Release source for the deploy.** Deploy a tagged release (`v0.11.0` or later) rather than a working-tree commit. **PROPOSED:** a release tag, so the deployed wheel matches an auditable artifact (today's `43abe8ae` appears in no repo I could read).
16. **Network boundary and browser access (approved).** Household Tailscale only, not public; protect WebSocket and backend routes from direct access or proxy bypass. No separate browser sign-in; anyone reaching the page can use authorized Profiles.

## Acceptance criteria

Not accepted until the real-browser rows have dated evidence from the named build. Fake-bridge runs are evidence of code behaviour only (`STD-8 spec :67-68`).

- **AC-1 Pairing.** Pair the appliance once through Home's pairing page and approval; the record is private to the service user; no credential or `grant_id` appears in a URL, log, unit file or browser bundle. Revoking the device on Home makes the next admission show `home_unauthorized`. No per-browser pairing or browser sign-in is required; anyone admitted by the household Tailscale boundary can use the authorized Profiles.
- **AC-2 Per-connection isolation.** Two browser tabs hold two Home claims bound to two Standard sessions; overlapping turns, prompts and audio stay with their owner; one tab leaving closes only its claim. (Supersedes the deferred item at `deferred-work.md:266-270`.)
- **AC-3 Profile routing.** Every Profile Home authorizes for the appliance is available after its grant is approved, including Profiles authorized later; configured wake phrases select the corresponding Profile. An unusable grant reports that Profile as unavailable and leaves the others working; no Profile ID crosses the bridge.
- **AC-4 No replay.** Each browser page reload or socket reconnect starts a fresh claim and conversation; tabs remain independent. A transport loss after submit marks the turn uncertain and nothing is resent.
- **AC-5 Capacity.** Admission beyond the cap closes `1013` with the capacity message; Home `claim_limit` shows its own message and causes no automatic claim retry.
- **AC-6 Honest unavailable.** With Home unreachable, Home up but Hermes down, and the credential revoked, the page shows the matching sentence from the table, never only "check the host connection", and the appliance logs one `browser.admission.failed` line with the reason token and no secret.
- **AC-7 Health.** `/healthz` is `503` within 60 s of Home becoming unreachable or the credential being revoked, and returns to `200` after recovery; a Grafana alert fires from `probe_success` without any browser connecting; `credential_expiring` appears before expiry.
- **AC-8 Lifecycle.** Restarting the appliance or Home leaves no leaked claim after the startup sweep; a Home restart is recovered by a fresh claim on the next turn.
- **AC-9 Real browsers.** Mac Chrome and iPad Safari (Guided Access) complete over household Tailscale only: page load, microphone permission, a wake-phrase turn and a typed turn with streamed text and response audio, a clarify/choice prompt, interrupt, and two overlapping independent tabs. Verify the page, WebSocket, and backend listener cannot be reached directly from the public Internet or via a proxy/backend bypass. The Samsung browser gate stays under `WK-1` (`spec-1-wk-1-…:137-140`).
- **AC-10 Deploy and rollback.** The managed unit runs the Home transport from a tagged wheel; deploy and rollback complete with the smoke check; the rollback target and unavailable behaviour match the PROPOSED rule above; page and all backend paths remain tailnet-only with bypass protection.
- **AC-11 Legacy.** After the bake window the legacy transport, `voice-*` Caddy blocks, three profile tokens and legacy catalog schema are removed (S8) and a scan finds no supported path that needs them.

## Slices

| # | Slice | Repo | Depends on | Size | Needs Ops access / hardware |
|---|---|---|---|---|---|
| S1 | Home stub `HOME-NW-17-browser-admission` decided and implemented: `browser` kind, no owner-approver role, storage attestation, optional self-health | Home | Q3-Q5 | S (tens of lines plus tests; own spec review) | None to build. Deploy to CaticornQueen needs Windows host access |
| S2 | Appliance Home client: file-backed pairing record with renewal, pairing command, claim list/close, startup sweep | TUI | S1; Q5 | M | None to build; pairing on Ops needs Ops shell |
| S3 | Per-connection grant routing and claim lifecycle in the browser path; catalog v2; replaces the static handle | TUI | S2; Q6-Q10 | L | None to build |
| S4 | Honest unavailable: reason tokens, close reason, browser UI mapping and text, structured logs | TUI | Q11 (independent of Home; also improves legacy while it lives) | S-M | None to build; real-browser check needs Mac and iPad |
| S5 | `/healthz`, background probe, metrics-free tokens; Ops blackbox probe and Grafana/Loki alerts | TUI + Ops | S2; Q12 | S (code); alerts Ops-side | Alerts and blackbox need Ops/Grafana access |
| S6 | Deploy changes: unit, catalog validator, deploy script Home mode, smoke check, runbook, rollback rule | TUI | S3, S5 | M | Dry run needs Ops access |
| S7 | Ops rollout: Home deploy of S1, pair and approve, deploy release, real-browser gates AC-1…AC-10, record evidence, owner acceptance | Ops + TUI | S1, S3-S6; tailnet grant Ops → Home | M | **Ops (SSH, sudo), CaticornQueen/Home admin, Mac Chrome, iPad Safari** |
| S8 | Retirement: flip default, remove legacy transport and catalog schema; Ops removes `voice-*` blocks and tokens | TUI + Ops | S7 accepted, bake, `TUI-RETIRE-01`, `HOME-MIG-09` R6/R7 | S-M | Ops for Caddy/tokens |

Order: S4 and S1 first; S2 follows S1; S3 and S5 follow S2; then S6, S7; S8 last. S3 and S5 may proceed in parallel after S2.

## Risks

- **R1 Home `conversation.open` semantics for one handle.** Moot once each connection has its own claim, but if S3 slips and the static handle is used, isolation is unproven (`deferred-work.md:266-270`).
- **R2 Owner-approver exposure.** A shared display holding an owned Profile can approve other devices' grants (`credentials.py:1029-1062`). Mitigated only by S1.
- **R3 Credential expiry is silent without renewal.** 90 days, 14-day window (`credentials.py:34-35`). Mitigated by S2 and the `credential_expiring` health reason.
- **R4 Claim leakage and refusal loops.** Seven unopened claims hit the limit in 19 s on iOS (`HOME-NW-18 spec :23`). Mitigated by lazy claims, one attempt per action, startup sweep, close-before-claim.
- **R5 Reachability from Ops to Home.** Tailnet grant and Serve route from Ops are **UNKNOWN**; the Serve list publishes `client-claims`, `devices`, `enrollment/requests` and the bridge but not `touch-claims` (Home `deploy/windows/README.md:316-319`).
- **R6 Home is a single Windows host.** A Home or Hermes outage takes W/K down; this spec makes that visible, not impossible. Deployment recovery rule applies (`course-correction-2026-09-23.md:71`).
- **R7 Deploy-time rollback loop.** A deploy while Home is down fails smoke and rolls back (`check_ops_web.py:129-176`); the runbook must separate "deploy" from "Home healthy".
- **R8 Network boundary, not browser identity.** No separate browser sign-in exists: anyone reaching the page can use the appliance's Home-authorized Profiles. Household Tailscale is the only access path; public access to the page, WebSocket, or backend listener is prohibited, including direct access that bypasses the proxy. The tailnet boundary is not per-user authentication.
- **R9 Touch claim payload mismatch (separate finding, not fixed here).** `HttpTouchClaimClient` sends `config_revision` (string) and `observed_at` (ISO string) (`touch.py:241-249`); Home's `_touch_claim_values` requires an integer `configuration_revision` and `initiation: {kind, observed_at_ms}` (Home `application.py:2427-2441`). [INFERENCE] a real Home rejects the current Touch claim. STD-7's own review notes that `HttpTouchClaimClient._post` has no test and every admission test injects a fake claim client (`spec-standard-7-esp32-touch-audio-session-adapter.md:193`). UNKNOWN whether it was ever run against a real Home. Recommend a separate ticket.
- **R10 Second appliance on Ops.** A developer copy of `home_display.appliance` runs on the Ops host against the dead `:8792` [OPS]; it is outside this spec and Ops should decide whether to stop it.
- **R11 First-turn latency** from claim-at-first-turn is unmeasured (UNKNOWN).

## Unknowns

- Whether anything listens on the Mac-mini ports and why they stopped (Ops/mini access).
- Home tailnet hostname and the Ops → CaticornQueen tailnet grant.
- Whether Secret Service exists on the Ops host, and whether Ops has a Prometheus blackbox exporter.
- Whether Home accepts two concurrent opens of one handle; whether client devices appear in Home device configuration.
- Whether the deployed Home on CaticornQueen includes `HOME-NW-18` routes (the validation records say deployed; this was not re-read on the host).

## Out of scope

Browser-to-appliance authentication; kiosk login; Departure Card and render stories (`2-WK-*`, `4-WK-*`); resuming prior conversations from a browser; custom wake phrases; Touch fixes (R9); restoring the fork gateways.

## Spec Change Log

- 2026-10-08: Drafted from the Ops diagnosis and the web-migration review. Status `draft`; `WK-1`/`WK-2` unchanged.
