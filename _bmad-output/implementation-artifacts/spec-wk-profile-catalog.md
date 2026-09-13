---
title: 'Route browser hands-free turns through a three-profile wake-word catalog'
type: 'feature'
created: '2026-09-12'
status: 'done'
route: 'dispatch'
review_loop_iteration: 4
baseline_commit: 'acc531bbee2a468d5a1e403e572c47af65cb628c'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/surface-coverage-matrix.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-wk-concurrent-browser-session-isolation.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-hermes-relay-tui-2026-09-08/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Ops browser surface currently loads one household profile. It cannot use the existing three-profile catalog, so a browser hands-free session cannot route `hey missy`, `hey skippy`, and `hey spark` to their intended Hermes identities.

**Approach:** Load all configured household profiles on Ops and advertise their non-secret wake phrases to each browser connection. The browser sends the exact configured phrase it matched. A phrase-plus-question is carried on one `voice_turn`; a wake-only phrase uses a route request and waits for an acknowledgement before question capture begins. The browser connection owns a serialized profile switch and Hermes session, so selecting a profile changes only that tab. The selected profile remains active through bounded wake-free follow-ups and until that connection disconnects or is deliberately reset.

## Boundaries & Constraints

**Always:** Profile names, display names, wake phrases, endpoints, and session identities come from the household profile configuration; bearer tokens remain in the private Ops environment. Wake phrases must resolve to exactly one profile after trimming, collapsing internal whitespace, and case-folding. The browser sends a canonical configured phrase, never raw recognition text, and phrase extraction requires a complete phrase boundary. Profile routing, target-session connection, and turn submission are serialized per browser context. A target becomes active only after its Hermes `hello_ack`; a failed switch leaves the previously usable profile active and does not retry or replay a turn. Existing concurrent-session isolation, one-turn ownership, bounded browser admission, no-replay recovery, and the text-only browser/Hermes boundary remain intact.

**Catalog:** The initial Ops catalog is `amanda` / `hey missy`, `jensen` / `hey skippy`, and `spark` / `hey spark`, sourced from the existing household configuration.

**Deployment:** The approved Ops setup maps `amanda` to `VOICE_SESSION_TOKEN_AMANDA`, `jensen` to `VOICE_SESSION_TOKEN_JENSEN`, and `spark` to `VOICE_SESSION_TOKEN_SPARK`. The deployment pipeline extracts only those three bindings from the existing private local environment and merges them into `/etc/hermes-relay/home.env` without printing values. The non-secret catalog is versioned with each release at `current/profile-config.yaml`, while the service reads the private environment through `--profile-env /etc/hermes-relay/home.env`.

**Never:** Do not expose tokens or upstream credentials in snapshots, browser messages, logs, or the catalog. Do not let a browser choose an arbitrary endpoint or client/device identity. Do not add web-side credential entry, remote config editing, a shared transcript/session store, or a second Hermes protocol implementation. Physical appliance wake routing and the iOS/Puck administration control plane remain unchanged.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| UNIQUE_WAKE | Armed browser hears one configured phrase plus a question | The browser sends one `voice_turn` with the canonical `wake_phrase`; the server switches and submits under that profile; the snapshot shows its display name | No other browser context changes |
| WAKE_ONLY | Armed browser hears a configured phrase without a question | The browser sends `profile_route`, waits for `profile_route_ack`, then captures the question under the acknowledged profile | A rejected route starts no capture and returns to wake-ready |
| UNKNOWN_OR_AMBIGUOUS | Recognition or a direct client frame produces no unique normalized match | No profile changes and no Hermes turn is submitted | Return a safe routing status; never fall back |
| ACTIVE_TURN | A different wake phrase arrives while the context is capturing, processing, speaking, or showing a structured prompt | The active profile and turn remain authoritative; no route or turn frame is accepted | Drop the candidate and preserve no-replay semantics |
| MISSING_TOKEN_OR_CONNECT | A catalog entry has no resolved private token or its target cannot complete `hello_ack` | That profile is unavailable; the current usable profile and other browser contexts remain usable | Show a safe unavailable status without selecting another profile |
| INVALID_CATALOG | Config is malformed, empty, or has duplicate normalized phrases | The new release is not activated; the last valid release remains live | Fail preflight with a redacted diagnostic |
| FOLLOW_UP | A non-empty follow-up arrives inside the wake-free window | The follow-up uses the currently selected profile without another route request | Window expiry returns to wake-ready while retaining the selected profile for the next explicit wake |
| LEGACY_TURN | A compatible client sends `voice_turn` without `wake_phrase` | The turn uses that connection's current profile, preserving the existing single-profile behavior | No implicit default-profile switch |
| CONCURRENT_TABS | Two browser connections recognize different catalog phrases concurrently | Each connection switches and submits only through its own profile/session/publisher/audio path | One connection's failure does not mutate the other |

</frozen-after-approval>

## Implementation Notes

### Browser protocol contract

- `voice_turn` keeps schema `1` and accepts an optional bounded `wake_phrase`. When present, the server validates it against the connection's catalog, performs the profile switch, and only then forwards the text. When absent, the current connection profile is used for compatibility.
- Wake-only capture uses `profile_route` schema `1` with a bounded `request_id` and canonical `wake_phrase`. The server returns `profile_route_ack` with the request ID, an accepted flag, a safe reason when rejected, and the selected display name only when accepted. Route acknowledgements are sent on the same browser WebSocket; snapshots remain the display-state channel.
- Unknown, ambiguous, malformed, or overlong routing fields mutate no state and submit no turn. Browser recognition ignores unconfigured phrases; server validation remains authoritative for untrusted frames.

### State ownership and failure policy

- The parent appliance owns the immutable catalog. Each admitted browser context receives all catalog entries but owns its active profile, Hermes session, display publisher, audio sender, and routing lock. It must not mutate the parent's active profile or another context's state.
- A switch prepares and connects the target session before committing the active profile and account snapshot. After commit, the old session is closed. If preparation or `hello_ack` fails, the old usable session remains active; the target is marked unavailable and no automatic fallback or turn replay occurs.
- The selected profile remains the source for typed turns and wake-free follow-ups on that connection. A disconnect, explicit reset, or configuration change starts the next connection from the catalog's first profile and rehydrates the full phrase list.

### Ops delivery contract

- `scripts/deploy_ops_web.sh` accepts `--profile-config PATH` for a non-secret YAML catalog and `--profile-env-source PATH` for a private local env file. It uploads the catalog into the versioned release, allowlists only the three named token variables, validates both inputs without echoing values, and activates the release only after service health checks.
- `deploy/systemd/hermes-relay-home.service` starts with `--config @BASE_DIR@/current/profile-config.yaml --profile-env /etc/hermes-relay/home.env`, so rollback restores code and catalog together. Missing token variables stop a full-catalog deployment before activation; a later runtime loss marks only the affected profile unavailable.
- The committed example catalog contains placeholders, not endpoints or credentials. The actual Ops catalog is supplied as an ignored or external file and must contain exactly the approved profile names and wake phrases.

## Code Map

- `config.py` -- reuse `HouseholdProfile`, `load_household_profiles`, token indirection, and profile-specific session argument construction; do not add browser credentials or weaken private-token resolution.
- `home_display/appliance.py` -- extend browser context creation, route-and-turn serialization, capabilities, and switch commit/rollback so each child owns all profiles while retaining its private publisher/session.
- `home_display/server.py` -- parse and validate optional `wake_phrase`, implement `profile_route` and `profile_route_ack`, and preserve compatibility actions and old `voice_turn` frames.
- `home_display/web/src/state/voice.ts` -- return the exact canonical match, await wake-only route acknowledgement, and preserve wake stripping, bounded follow-up, stop handling, and recognition recovery.
- `home_display/web/src/state/channel.ts`, `bridge.ts`, and `protocol.ts` -- transport bounded routing fields and acknowledgements without exposing credentials.
- `tests/test_household_profiles.py`, `tests/test_home_appliance.py`, `tests/test_home_display_server.py`, and `home_display/web/src/state/*.test.ts` -- cover normalization, duplicate rejection, route acknowledgement, atomic failure, compatibility, switch isolation, and browser recognition behavior.
- `deploy/systemd/hermes-relay-home.service`, `scripts/deploy_ops_web.sh`, `tests/test_ops_web_deployment.py`, and `deploy/ops/hermes-home-profile-config.yaml.example` -- make the versioned catalog and private env handoff repeatable without committing secrets.

## Tasks & Acceptance

**Execution:**
- [x] Add the per-connection catalog, normalized routing, route acknowledgement, and atomic profile switching across the Python server/context and browser voice transport.
- [x] Extend focused Python and browser tests for every matrix case, including malformed frames, duplicate phrases, legacy frames, failed target sessions, and concurrent tabs.
- [x] Add the versioned profile-config deployment input, allowlisted private-env handoff, service flags, preflight validation, rollback pairing, and deployment-script tests.
- [x] Update the README with the browser catalog and repeatable Ops command without including endpoints or bearer values.
- [x] Run focused tests, web checks/build, and the complete Python suite. The deployed Ops page, state channel, action route, and three-phrase capability gate now pass; physical three-phrase/two-tab verification remains deferred.

**Acceptance Criteria:**
- Given three valid named profiles with unique wake phrases, when a browser recognizes any configured phrase, then exactly one profile is selected for that browser context before its turn is submitted and the selected account is visible.
- Given a phrase plus a question, when the browser sends `voice_turn` with the canonical `wake_phrase`, then routing completes before exactly one Hermes submission and the snapshot's `account` is the selected profile display name.
- Given a wake-only phrase, when the browser sends `profile_route`, then it captures no question until an accepted `profile_route_ack` arrives.
- Given two browser contexts using different wake phrases at the same time, when both turns complete, then each receives only its own response, audio, and account state.
- Given an unknown or ambiguous phrase, when recognition completes, then no Hermes turn is submitted and no other profile is selected.
- Given the target profile is unavailable, when its wake phrase is recognized, then the browser reports a safe unavailable state, keeps the current usable profile, and does not disturb other profiles.
- Given an active browser turn, when another catalog wake phrase is recognized, then the active turn remains authoritative and no route, profile switch, or duplicate submission occurs.
- Given a successful switch, when a non-empty follow-up arrives inside the bounded window, then it uses the selected profile without another wake phrase.
- Given a legacy `voice_turn` without `wake_phrase`, when it arrives on a compatible connection, then it uses that connection's current profile without changing profile state.
- Given malformed config, duplicate normalized phrases, or an incomplete required deployment env, when the release is prepared, then activation stops and the prior valid release remains live.
- Given the Ops service is deployed from the repeatable pipeline, when the private environment contains the three named profile token variables, then all three profiles load without any credential appearing in browser payloads, logs, committed files, or deployment output.

## Verification

**Commands:**
- `venv/bin/pytest tests/test_household_profiles.py tests/test_home_appliance.py tests/test_home_display_server.py` -- expected: all focused Python tests pass.
- `venv/bin/pytest tests/test_ops_web_deployment.py` -- expected: deployment argument validation, allowlisting, service-template flags, and catalog pairing tests pass without reading real secrets.
- `npm --prefix home_display/web ci && npm --prefix home_display/web test -- --run && npm --prefix home_display/web run check && npm --prefix home_display/web run build` -- expected: browser tests pass, Svelte check is clean, and the production bundle builds.
- `bash -n scripts/deploy_ops_web.sh && scripts/deploy_ops_web.sh help` -- expected: the repeatable profile-config and profile-env-source options are documented and shell syntax is valid.
- `venv/bin/pytest` -- expected: complete repository suite passes.
- `scripts/deploy_ops_web.sh deploy --ops-host ops --origin https://hermes-home.chappell-home.dev --caddyfile /srv/ops/caddy/Caddyfile --caddy-site-dir /srv/ops/caddy/sites-enabled --profile-config /secure/path/ops-home-profile-config.yaml --profile-env-source ~/.hermes-relay-tui/.env` plus `scripts/check_ops_web.py --origin https://hermes-home.chappell-home.dev --require-wake-phrase "hey missy" --require-wake-phrase "hey skippy" --require-wake-phrase "hey spark"` -- expected: the active release serves the catalog and no credential value appears in deployment output.
- A redacted remote catalog check -- expected: `amanda`, `jensen`, and `spark` are present with their three wake phrases, all three token variable names are present, and no token values are printed.

This shared worktree has no local `venv/`; the equivalent verified commands used
`../../venv/bin/pytest` and `../../venv/bin/python`. A clean checkout can use the
`venv/bin/...` paths shown above.

**Manual checks (if no CLI):**
- Open two fresh browser tabs on the Ops origin, enable hands-free in both, say `hey missy` in one and `hey skippy` in the other, and confirm each tab shows the matching profile while both remain connected. Exercise `hey spark` in a third turn, then test a wake-only phrase followed by a question. Confirm a failed target does not replace a usable tab and that a wake-free follow-up stays on the selected profile.

## Review Triage Log

Review layers were run against the unified diff from `acc531bbee2a468d5a1e403e572c47af65cb628c`, including untracked files. The final blind, edge-case, and verification-gap reports arrived after the initial collection pass and were triaged below. The local full-suite, browser gates, corrected Ops deployment, and redacted public catalog check are the independent evidence for the current tree.

| Source finding | Verdict / route | Evidence and disposition |
|---|---|---|
| Browser route rejection had no safe visible status. | medium / patch | Server route acknowledgements now carry bounded safe reasons, and the browser returns to wake-ready with an error/idle presentation; route rejection tests pass. |
| Active-turn profile switching lacked executable coverage. | medium / patch | Per-context route and turn locks reject a competing route; active-turn tests pass. |
| Concurrent tabs using different profiles lacked executable coverage. | medium / patch | A two-socket appliance/server test verifies isolated sessions, publishers, accounts, and responses. |
| Three-profile catalog wiring lacked executable coverage. | medium / patch | Browser/App tests cover `hey missy`, `hey skippy`, and `hey spark`; catalog and routing tests pass. |
| Wake-only rejection, acknowledgement timeout, and socket-close behavior lacked coverage. | medium / patch | Same-socket acknowledgement, timeout, rejection, and close settlement are implemented and tested. |
| The Ops health gate was not catalog-aware. | medium / patch | The public check now validates `browser_hands_free` and the exact three wake phrases; the corrected deployment passed that gate. |
| Profile preflight malformed-catalog and missing-token cases lacked coverage. | medium / patch | Validator and deployment tests cover malformed YAML, strict schema/version checks, duplicate phrases, and all required token bindings. |
| Rollback could activate a release without its required catalog. | high / patch | First catalog deployment backfills the prior release and rollback validates catalog presence before activation; pairing tests pass. |
| Staged private environment permissions were not explicitly enforced after upload. | high / patch | Remote deploy applies mode `0600` to the staged and installed environment; deployment tests assert the protection step. |
| The documented deployment test filename did not match the repository file. | low / patch | The verification text now names `tests/test_ops_web_deployment.py`, the actual test module. |
| Duplicate normalized wake phrases were not fail-closed. | high / patch | Normalized collisions—including duplicates within one profile—disable hands-free routing and validator activation; duplicate tests pass. |
| A missing catalog could leave browser routing with an unsafe fallback. | high / patch | Browser capabilities advertise hands-free only for a valid catalog, while multi-profile no-phrase routing rejects; fallback tests pass. |
| Failure of the first profile could prevent other catalog entries from admitting a browser. | high / patch | Admission tries the ordered catalog entries independently and accepts a later usable profile; isolation tests pass. |
| App-level route/send wiring was not executable-tested. | medium / patch | `App.test.ts` verifies phrase-plus-question transport and wake-only route transport through the three-profile catalog. |
| A real two-browser profile-routing integration check was missing. | high / patch | Local WebSocket integration now drives two independent browser connections with different phrases and verifies isolated completion. |
| Selected-profile wake-free follow-up behavior was not executable-tested. | medium / patch | Browser hands-free tests verify follow-up submission without another route request after a profile switch. |
| Unknown and ambiguous recognition behavior was not executable-tested. | medium / patch | Voice tests cover partial, unknown, and duplicate/ambiguous phrases without submission or selection. |
| Structured-prompt route rejection was not executable-tested. | medium / patch | Appliance tests verify routing is rejected while a structured prompt is authoritative. |
| Tokenless target routing was not executable-tested. | medium / patch | Missing-token tests preserve the current usable profile and leave other browser contexts unaffected. |
| Invalid-catalog rollback/preflight behavior was not executable-tested. | high / patch | Deployment tests exercise invalid catalog rejection, prior-release preservation, and catalog pairing. |
| Activation failure could leave code and environment pairing unverified. | high / patch | Deployment tests exercise restart failure recovery and restoration of both release pointers and the previous environment. |
| Malformed route acknowledgements lacked parser coverage. | medium / patch | Protocol tests reject malformed, overlong, non-boolean, and wrong-schema acknowledgements. |
| Physical two-tab/three-phrase speech verification was not run. | medium / defer | The corrected Ops release and redacted public capability check passed; real browser speech, wake-only capture, and live Hermes turns still require the supported browser/device gate. |
| Rollback recovery of the filtered environment could lose unrelated runtime settings. | high / patch | The staged rollback artifact now retains the complete merged environment rather than only the allowlisted token subset; rollback tests pass. |
| The previous profile session could hang an otherwise successful switch. | medium / patch | Old-session close is bounded and tracked for deferred cleanup; hanging-close tests pass. |
| Legacy callback handling could accept a wake-bearing frame as an ordinary turn. | high / patch | The legacy callback path accepts only wake-free `voice_turn` frames; compatibility tests pass. |
| YAML boolean/float versions could compare equal to integer version `1`. | medium / patch | Catalog validation requires `type(version) is int`; strict-version tests pass. |
| A prompt overlay could drop the active account and browser catalog. | high / patch | `_publish_prompt` now carries the same account and capabilities as ordinary snapshots; prompt tests cover the catalog-bearing browser state. |
| A failed first admission candidate could close the shared browser socket. | high / patch | Candidate children defer browser-socket ownership until after `hello_ack`; fallback admission coverage verifies the socket remains open. |
| A profile target close could hold a route acknowledgement indefinitely. | medium / patch | Target-session cleanup is bounded, tracked, and cancellation-safe; the existing timeout coverage remains green. |
| Three bounded candidate attempts could outlive the browser admission deadline. | high / patch | The admission deadline now covers the three-profile connect/cleanup sequence; later healthy candidates remain reachable. |
| A synchronous route adapter could restart recognition before the previous browser recognizer released. | high / patch | Release state is tracked and both synchronous and asynchronous route paths wait when needed; regression coverage passes. |
| A malformed route with a safe request id could leave the browser waiting for ten seconds. | medium / patch | The server returns a bounded `malformed_request` acknowledgement, and route transport coverage verifies it. |
| A saturated connection task set could drop a route without an acknowledgement. | medium / patch | Route admission now returns a bounded `busy` acknowledgement when the connection task budget is exhausted. |
| Manual rollback could pair an old release with the newest private environment. | high / patch | Each catalog release records a mode-0600 environment snapshot on Ops; manual and automatic rollback restore the matching release snapshot. |
| The public smoke gate did not verify the advertised catalog. | medium / patch | `check_ops_web.py` can require the exact three wake phrases and `browser_hands_free`; the deployment invokes that gate. |
| The catalog source could change between validation and upload. | medium / patch | Deployment snapshots the catalog before validation and uploads that immutable build input. |
| Physical three-phrase/two-tab speech and in-flight route cancellation remain unverified. | medium / defer | The corrected public gate proves serving and capability advertisement; physical browser speech, live Hermes routing, and cancellation on disarm require a supported device/session and remain outside this handoff. |
