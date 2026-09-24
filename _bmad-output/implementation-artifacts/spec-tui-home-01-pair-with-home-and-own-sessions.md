---
id: TUI-HOME-01
title: Pair the TUI with Home and use personal sessions
type: feature
created: 2026-09-23
status: in-review
route: dispatch
baseline_commit: 81cfc0a16684b3dfdd51d5d51929f21b31f3c3bb
review_loop_iteration: 0
github_issue: https://github.com/achappell/hermes-relay-tui/issues/205
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/course-correction-2026-09-23.md'
---

<frozen-after-approval reason="approved course-correction intent and user's explicit request to connect TUI">

## Intent

**Problem:** Home transport requires a pasted disposable handle and cannot pair or manage personal sessions. **Approach:** Implement TUI-HOME-01 against NW17's actual client HTTP/bridge contract. Reuse the existing conversation, local microphone and audio adapters.

## Boundaries & Constraints

**Always:** Per-Home platform-secure credentials; approved grants only; deliberate new/continue/resume; preserve uncertain turns without replay; separate history by canonical Home and granted identity. Show unavailable features honestly. Keep transport/framework separation.

**Never:** Modify Hermes or Home, silently switch modes, persist credentials/handles in YAML/env/history/logs, borrow another Home's credential, or assume session history retrieval. Legacy removal remains TUI-RETIRE-01. New broad direct-mode setup remains TUI-STD-01; preserve existing supported gateway functionality.

Home currently supports local forgetting but no device-authenticated self-revoke. Unpair removes local access and explicitly directs server revocation to Home's page. Resume restores Hermes context; absent a history API, never claim old transcript was loaded. Rename uses advertised title command only.

</frozen-after-approval>

## Code Map

- `home_client.py` (new): asynchronous bounded HTTP operations and per-Home secure pairing records; no Textual dependency. HTTPS only, reject credential/query-bearing Home URLs, prevent redirects leaking authorization.
- `home_pairing_cli.py` (new): pair/unpair entry points, confirmation display and bounded approval polling.
- `config.py`, `profile_cli.py`, `setup_wizard.py`: per-Home public configuration, grant labels, launch continue/resume and setup pairing; remove ordinary handle/env requirement.
- `puck_bridge/home_textual_session.py`: obtain/renew credential, refresh grants/configuration, claim and wrap `HomePuckSession`; supported session controls and owner approvals.
- `puck_bridge/home_session.py`: reuse single-reader bridge and bounded `close_claim`; preserve Puck behavior.
- `app.py`, `commands.py`, `session_picker.py`: local command routing, grant selection, opaque picker references, independent local display/history IDs and recovery binding.
- `pyproject.toml`, `requirements.txt`: package new core modules and `keyring`; trust only macOS Keychain/Linux Secret Service, refusing null/plaintext/fallback stores.

## Implemented Home contract

Source: sibling Home `.worktrees/home-nw-17`, revision `d2447f684a143817f7b5688b597c11aa053bb672`. All device calls use `Authorization: Device <credential>`.

Enrollment POST `/api/v1/enrollment/requests`: schema1, enrollment_code, endpoint_id, label, type=tui, requested_rooms=[], requested_capabilities=[client_claim], secure_storage=platform_secure_store. Show returned confirmation_code; POST request's `/consume` with schema/code/secure_storage until approval_pending resolves or expires/rejects. Response credential material includes device_id, credential, generation, expires_at and grants. Validate before saving; handle single-use consumption failures honestly.

GET `/api/v1/devices/{id}/configuration` returns `snapshot.revision` and `snapshot.client_grants` (grant_id,label,status,available). Only active/available grants can claim. Persist renewal request ID before POST `/api/v1/devices/{id}/credentials/renew` with schema/request_id/generation inside the final14days; retry same request after interruption. Renew before claims. Renewal lacks grants: refresh configuration.

POST `/api/v1/client-claims` carries schema, unique claim_id, device_id, configuration_revision, grant_id and session mode new/most_recent/resume (resume includes session_ref). Open returned opaque handle through existing bridge. List via POST `/api/v1/client-sessions/list` with schema,grant_id,limit1–50; map started_at/title/message_count/active to picker entries. Switching closes old claim before new claim/open; preserve transcript if replacement fails. Reconnect retains the same in-memory claim and latest credential; quitting closes it. Never serialize a claim into config.

GET `/api/v1/profile-grants/pending` and `/holders`; POST `/api/v1/profile-grants/{id}/approve|reject` with schema1. Only explicit user actions approve/reject. Title uses existing command.dispatch when advertised. Errors show bounded explanations for pending, stale config, busy, claim limit, revoked/unavailable identity and service failure without raw server bodies/secrets.

## Tasks & Acceptance

**Execution:**
- [x] `home_client.py`, `home_pairing_cli.py` — implement secure storage, pairing, renewal and typed HTTP API; bound response sizes/timeouts and sanitize errors.
- [x] `config.py`, `setup_wizard.py`, `profile_cli.py`, `app.py::main` — wire pair/unpair and Home setup; store only public Home/grant-label configuration, preserving unrelated profiles.
- [x] `puck_bridge/home_textual_session.py`, `puck_bridge/home_session.py` — claim on initial connect; reuse claim on recovery; close on explicit quit/switch; implement list/new/resume/advertised title/approvals.
- [x] `app.py`, `commands.py`, `session_picker.py` — expose commands and available grants, busy/uncertain guards, truthful resumed-history limit; isolate history without automatic cross-identity migration.
- [x] `pyproject.toml`, `requirements.txt`, `README.md` — package dependencies/modules and document setup, safe unpair and live-deployment prerequisites.
- [x] Owner story/tracker and validation record — describe implemented scope and remaining live acceptance accurately.

**Acceptance Criteria:**
- Given reachable NW17 and secure storage, when pairing by link or Home+code is approved, then launch uses a granted Profile without copied credentials/handles.
- Given absent secure storage or pending/rejected/expired enrollment, when setup runs, then it reports the state without insecure fallback.
- Given several Homes/Profiles/windows, when selecting or renewing, then credentials, histories and claims remain correctly scoped.
- Given an active session, when new/continue/resume/list/title is requested, then supported Home operations execute; busy/uncertain work is not discarded or replayed and unsupported commands are not sent.
- Given connection loss, when reconnecting within grace, then the same claim is recovered; failed recovery remains explicit. Given quit, its claim is closed while Standard history remains.
- Given local unpair, when credentials are removed, then the result clearly distinguishes local forgetting from server revocation.

## Implementation Notes

Proceed under the user's explicit implementation authorization and previously approved product scope. No new product decision or live credential/configuration mutation is implied. Existing Home deployment is not validated. Do not add or run tests: the session developer instruction requires an explicit user request for testing. Use code/diff inspection, and record runtime acceptance as unverified. Do not claim a fully verified story or mark it done.

## Spec Change Log

- 2026-09-23: Reconciled original draft with implemented HTTP session list/claim selection, command title, missing history retrieval and admin-only device revocation. Retained approved pairing/session goal and safe reduced capability behavior.

## Review Triage Log

| Finding | Verdict | Evidence and route |
| --- | --- | --- |
| Blind 1: duplicate grant label | medium | Pairing saves the sole usable label; `_select_grant` considers unavailable same-label rows too. Patch the existing selection to retain the resolved grant ID. |
| Blind 2: credential saved without public settings | medium | Cancellation/write failure after consume leaves secure material; `profile add` already creates Home settings without enrollment. Patch error guidance and documentation to expose that existing recovery path. |
| Blind 3: corrupt record blocks unpair | medium | `SecurePairings.delete` calls `load`, whose JSON/field validation fails before deletion. Patch direct canonical-key deletion. |
| Blind 4: hidden input fallback | medium | Default getpass warns and can echo when terminal control is unavailable. Patch warning handling to refuse that fallback. |
| Blind 5: reused picker keys | medium | Command handlers run as concurrent workers; a later listing replaces the shared `conversation-N` map before an older picker resolves. Patch unique keys per listing. |
| Blind 6: epoch dates | low | Home supplies numeric started_at and picker stringifies it. Everyday picker display warrants the direct timestamp-format correction. |
| Blind 7: failed Profile release looks connected | medium | release_claim clears hello verification; the failed-switch branch returns without setting disconnected state if is_connected is false. Patch existing failure presentation. |
| Blind 8: cancellation-shielded credential reads | medium | credential uses secure_call for load and its cancellation handler waits for the thread; release_claim timeout cannot complete while that read stalls. Patch reads to be cancellable, preserving write serialization. |
| Blind 9: title positive acknowledgment | maybe-false | Home standard.py dispatch_command returns the upstream result after rejecting known failures; endpoint.py adds schema/handle. No title-specific positive response schema was found. Defer as medium/unverified until the pinned Standard title response is captured; do not invent a new required field. |
| Blind 10: unresolved turn after reconnect | medium | Adapter disables uncertain-turn event resumption; app retains PROMPT_AMBIGUOUS and blocks new submissions. Preserving uncertainty is intentional, but successful reconnect lacks that explanation. Patch success wording to distinguish restored transport from unresolved turn and name the explicit leave action. |
| Edge 1: corrupt record blocks unpair | medium | Same verified delete-before-deserialization defect as Blind 3; grouped into that patch. |
| Edge 2: duplicate grant label | medium | Same verified label-resolution mismatch as Blind 1; grouped into that patch. |
| Edge 3: epoch dates | low | Same verified display conversion defect as Blind 6; grouped into that direct correction. |
| Gap 1: renewal recovery coverage | medium | Reviewer searched existing tests and found no persisted renewal-request recovery coverage. Acceptance deferred under the session developer prohibition on adding/running tests without explicit request; no coverage claim. |
| Gap 2: pairing persistence/config coverage | medium | Reviewer found only old environment-pairing setup coverage, not secure consumption and launchable config coverage. Acceptance deferred under the same developer constraint. |
| Gap other: obsolete test expectations | high | Read tests/test_home_textual_session.py:123 calling removed _get_home_session and tests/test_app.py:287 asserting home-amanda while code generates random IDs. Patched six existing cases to use the new pairing/session contract, without adding test cases or executing them. CI acceptance remains unverified. |

### Applied review corrections

Resolved exact grant IDs before retention; made corrupt-key deletion independent of parsing while confirming missing keys after native deletion errors; refused echoed secret input; made picker keys unique and dates readable; corrected failed-switch state and unresolved-turn wording; moved secure-store reads off the loop with cancellable delivery while retaining serialized writes; documented public-profile recovery. Maintained six existing test cases without adding or executing cases.

Additional static inspection found that native Secret Service priority probes may perform synchronous D-Bus work. Removed the redundant probe; explicit native backend selection and off-loop storage operations remain the authority for availability. All code patches were inspected after application.

## Verification

Inspect changed code, imports/packaging, contract shapes and secret handling. No tests or live calls without user authorization; list remaining acceptance explicitly.
