---
title: 'P-4 / STD-6 — Real Home-paired Living Room Puck turn'
type: feature
created: '2026-10-19'
status: done
disposition: done-with-deferred-gate
physical_acceptance: open
route: dispatch
review_loop_iteration: 0
story_id: P-4
source_spec: _bmad-output/implementation-artifacts/spec-1-p-4-recovery-without-replay.md
related_stories: [STD-6, 3-P-2, 3-P-4, 3-P-5]
baseline_commit: f44e32bf918a3d6f6c04613d6926ee39a92de741
stacked_dependency: 'PR #249, feat/3-p-5-fail-closed-identity; still open at fresh inspection'
origin_main_observed: cce15704457a51ed587b30bd6d780e106da629f5
approval_source: 'Explicit owner approval, canonical product decision 2026-10-19; parent accepted conservative coexistence and Home consumer contract.'
live_execution_gate: 'No host/hardware mutation without explicit custody transfer; firmware custodian owns Puck operations.'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/course-correction-2026-09-23.md'
---

# Existing P-4 / STD-6 full-turn delivery

Existing story ownership is preserved; this is not a new epic or closure of all ordered setup/arbitration criteria.

<frozen-after-approval reason="owner explicitly renegotiated admission policy on 2026-10-19">

## Intent

**Problem:** Paired Home startup requires an illegitimate operator handle, while the installed strict path has no qualified proximity provider. The owner approved this Living Room Puck responding to Hey Missy without proximity qualification, including wakes outside its Room.

**Approach:** Deliver genuine physical wake → authorized capture/upload → local STT → Home → unmodified Standard Hermes under Amanda → TTS → audible Puck. Start session-less. Use Home's explicitly approved paired-room admission, real fresh grant and verified session; retain strict calibrated admission for other Devices.

## Boundaries & Constraints

**Always:** Apply this Puck's distinct real Home Device credential and upload token privately. Approved binding is Device `c9dd86cfa9634330bf412e560969b7a9`, endpoint `ops-hermes-puck-bridge`, Room `living-room`, mapping `hey-missy` → Amanda. Home owns policy, scope, sole eligibility and handle creation. Verify current revision, matching claim and admission mode, then Home readiness before capture. Preserve durable credential rejection, saved-claim retirement, mapping isolation, no replay and existing strict path.

**Never:** Fake acoustic evidence, inject a production test provider, disable gates globally, reuse browser credentials, use a touch workaround or direct-Standard fallback, erase recovery records, expose secrets/audio in logs, or claim a fixture proves physical acceptance. Live mutation requires custody transfer. No unneeded renewal feature; retain explicit renewal/physical gates until exercised.

## I/O & Edge-Case Matrix

| Scenario | Input/state | Behavior | Failure |
|---|---|---|---|
| START | Paired, no saved claim | Session-less, no active-marker write | Missing settings fail closed |
| STRICT | No approved mode | Existing calibrated provider required | Missing/invalid evidence denies |
| PAIRED | Explicit eligible policy/current mapping | New paired-room claim with no acoustic fields | Malformed/mismatched policy denies |
| GRANT | Matching grant/mode/revision | Persist real handle; open/verify session before capture | No ready/grant means no capture |
| RECOVERY | Saved or failed-first-open claim | Control-only retirement, then fresh admission | Unconfirmed close stays denied |
| CHANGE | Revocation, policy removal/repoint, competitor | Home/consumer deny and retire old authority | No fallback or silent restart recovery |
| TURN | Admitted physical wake | Real STT/Home/Standard/TTS audible response | Uncertain turn never replayed |
| SHUTDOWN | Session-less or active | Release owned resources within deadline | Preserve unresolved cleanup ownership |

</frozen-after-approval>

## Home consumer contract

`GET /api/v1/devices/{id}/configuration` retains `{schema:1,snapshot:{revision,wake_mappings}}`. Only explicitly eligible policy adds `snapshot.wake_admission:{mode:'paired_room',room_id,wake_mapping_ids}`. Omission means strict; invalid configured approval returns403, not silent downgrade. Changes/removal advance revision and invalidate affected claims.

Paired `POST /api/v1/paired-room-claims` body is exactly `{schema:1,claim_id,device_id,wake_mapping_id,configuration_revision,initiation:{kind:'wake_word'}}`. Grant retains existing wake fields plus `admission_mode:'paired_room'`; require exact integer schema/revision (not bool), own claim ID and nonempty fresh handle. No acoustic fields. Home denies if any other configured and currently credential-authorized wake Device in any Room can use the same mapping; different-mapping strict Devices are unaffected. Errors retain `{schema:1,error:{code}}`:401unauthorized,403forbidden,409stale_configuration/conversation_active,400invalid_request,503service_unavailable. Only confirmed credential refusal retires credential authority.
`409 duplicate_claim` also denies without replaying that claim or retiring the credential; it preserves the existing no-replay requirement.

Recovery contract addition approved by parent: `POST /api/v1/paired-room-claims/close` with `{schema:1,conversation_handle}` confirms only a known own persisted paired row. Require exact `200` receipt `{schema:1,conversation_handle:<same>,admission_mode:'paired_room',status:'closed'}` before recording confirmed retirement. Generic stale/404/403 is never proof; never delete uncertain state. Current credential scope/authentication still applies; healthy ready connections reuse existing `conversation.close`. New physical paired wakes retire the prior logical claim; bounded follow-ups do not create another claim.

## Code Map

- `puck_bridge/server.py`, `config.py`: remove Puck operator-handle/bootstrap-mapping inputs; no startup session/marker; private credential application remains separate from personal frontend storage.
- `puck_bridge/home_admission.py`: validate explicit policy, select exact Home route, validate mode-bound grant; strict path unchanged without explicit policy.
- `puck_bridge/turn.py`, `home_session.py`: session-less cleanup, saved-claim retirement, exact mapping/revision rechecks and verified turn/audio lifecycle.
- `receiver.py`, `voice.py`, `response.py`: reuse real upload/STT/audio path; fix only demonstrated full-turn defects.
- `tests/test_config.py`, `test_puck_bridge.py`, `test_puck_home_session.py`: deterministic consumer edges, no source-wording tests.
- Firmware README, owning specs/validation, CHANGELOG: update after smoke. Firmware changes only if physical evidence demonstrates necessity, coordinated with custodian.

## Tasks & Acceptance

- [x] Implement session-less startup and clean Puck CLI/env cutover.
- [x] Implement exact paired-mode consumer and strict-mode preservation; retain private credential application without exposing secrets. Actual service application remains a rollout gate.
- [x] Cover matrix, real CLI/HTTP and contract fixtures; run focused/full required checks.
- [x] Independently review full spec/code and fix findings before PR; parent read core diff and local API evidence.
- [ ] With custody authorization, prove actual gateway path and physical wake/STT/Amanda/TTS/playback; report precise remaining gates if unavailable.
- [ ] After smoke update docs/changelog/validation; commit exact paths, normal push/non-draft PR and SHA equality. No automatic merge.

**Acceptance:** Given approved paired-room policy, when Hey Missy is spoken, then only a verified Home grant/ready session permits capture and one genuine Amanda response is audible. Given strict/malformed/removed policy, revoked identity or competing eligibility, when operation is attempted, then there is no unauthorized capture/turn or fallback. Given failed first connect/restart, when a later wake occurs, then saved authority is retired before a fresh verified grant. Given no session, when stopped, then cleanup completes.

## Implementation Notes

Independent startup edits precede dependent mode edits under parent authorization. Canonical decision was recorded first; Home owner supplied final consumer nesting/semantics directly. No live mutation authorized yet.

- Demonstrated cold recovery gap: reconnect of an already closed claim cannot prove retirement. Added the Home-approved owned HTTP close receipt as a fallback after unconfirmed control retirement, including saved records without mode. Exact receipt gates existing atomic confirmed-retirement transition.

## Spec Change Log

- Owner renegotiated frozen narrow intent to full-turn delivery; paired-room exception is explicit and Home-owned, not invented calibration. Startup-only completion is insufficient.

## Review Triage Log

- Independent spec review: error inventory omitted `duplicate_claim`; clarified non-frozen contract notes. Runtime already preserves the code and denies without credential latch or retry.
- Independent code review, patched: default HTTP helper discarded success status, allowing a non-200 matching close body to confirm retirement. Require actual HTTP200; real loopback HTTP200/201/202 regressions passed (3 cases), with non-200 remaining unconfirmed.
- Independent verification review, patched: real factory return lacked a semantic mode assertion, while runner tests supplied the mode themselves. Assert returned paired/strict session mode so deleting the production mode handoff breaks coverage; existing runner test proves its fresh-wake consequence.
- Independent code review, patched: after a real grant failed first open and both retirement paths failed, pristine runner state lost the granted control owner and could request another claim. The existing factory now retains the actual pending session before persistence/open, gates every later admission on confirmed retirement, and clears ownership only after verified handoff/close. Actual-session regression proves second wake issues no fresh claim while unconfirmed and permits the next grant only after an exact close receipt; durable unconfirmed state remains intact.
- Independent code review, patched: failed healthy close RPC did not release the local client before HTTP-confirmed replacement. Existing `HomePuckSession.close()` now owns teardown on the failed close path; actual-session regression observes context closed/client absent before owned HTTP confirmation.
- Independent documentation review, patched: `config.example.yaml` still required an operator handle; replaced with Puck Device ID/session-less startup instructions.
- Independent observation, not a blocking defect: replacement handoff retirement has no immediate HTTP fallback, but the next physical wake already invokes authoritative retirement fallback and remains capture-closed meanwhile; no extra branch added.

## Verification — OBSERVED LOCAL CHECKS; GATEWAY / PHYSICAL PLANNED

- Focused startup selection:13passed,178deselected,0.21s. Actual CLI twice: denied:1/denied:2, no claim records, SIGTERM exit0. Evidence `/var/folders/cb/3pkc1ncx58j1xq63ktd8xftw0000gn/T/hermes-p4-startup-smoke-6d5ytw9j/`.
- Further observed local consumer checks: focused config/bridge/Home324passed; new paired/late-authority edges29passed; strict/paired first-open failure2passed; latest owned-retirement plus paired suite36passed,262deselected. Final full verification remains planned after independent code review and actual Home API smoke.
- Latest pre-review-fix focused config/bridge/Home suite:359passed,154.78s. Exact-status and mode-handoff review fixes require the subsequent verification run; this earlier count is not labeled final-reviewed.
- Superseded sequential verification job was cancelled after the critical pending-owner finding; it is not final evidence. Targeted pending-owner/first-open/status/mode fixes:8passed,157deselected,1.64s.
- Latest targeted final resource/status/mode/pending-owner fixes:7passed,159deselected,1.64s. Final repaired focused/full checks run sequentially after all independent findings; no result claimed until completion.
- Final repaired sequential verification: focused364passed156.32s; full2268passed,3environment-skipped,2knownBashcasesdeselected,6existingwarnings348.31s; diffcheckpassed. Combined505.57s, `artifact://3510`. Exact skip reasons and commands are in [validation](validation-p4-home-paired-room-full-turn.md).
- Independent amended code review confirms every fix, all four layers complete and no substantiated finding outstanding. Final actual Home API smoke rerun passed seven scenarios, `artifact://3481`, evidence `.../hermes-puck-paired-api-smoke-ekcns3pt/observed.json`.
- Actual cross-repository local Home API smoke: seven scenarios passed through HomeApplication, SQLite credential enrollment/approval/consume, configuration and persistent grant store over loopback HTTP. Verified real paired grant, idempotent exact owned-close receipt, unknown-handle non-confirmation, duplicate-claim denial, policy-removal strict refusal and close after policy removal. Evidence `/var/folders/cb/3pkc1ncx58j1xq63ktd8xftw0000gn/T/hermes-puck-paired-api-smoke-o2sjowb9/observed.json`. No Standard or physical audio exercised.
- Remaining required rollout evidence: real gateway capabilities/actual TTS PCM format and physical wake/STT/Amanda/TTS/playback through the designated live custodians. Code publication is authorized with this gate OPEN, not full-goal closure.
- No full turn, gateway, firmware change/compile, host mutation or new PR claimed yet.
