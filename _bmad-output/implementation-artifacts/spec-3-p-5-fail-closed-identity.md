---
title: '3-P-5 Fail closed for revoked or unavailable identities'
type: 'feature'
created: '2026-10-18'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '95809e14c83f0e343a4d730d96405b39fe844e7e'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/course-correction-2026-09-23.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-p-4-recovery-without-replay.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Existing Story 3.5 / surface 3-P-5 requires revoked or unavailable identity to stop the Puck before capture. Home rejection is only latched in memory, ordinary Home 403 denials are conflated with credential rejection, and production firmware has no visible unavailable indication.

**Approach:** Consume Home's existing credential, authorized configuration and claim contracts; durably retain confirmed credential rejection without recording credentials. Keep mapping/service unavailability separate and scoped, require verified recovery before reuse, and show solid Unavailable on verified on-board LED hardware before denied capture.

## Boundaries & Constraints

**Always:** Preserve all five original Story 3.5 criteria. Home owns identity, mapping-to-Profile routing, renewal, revocation and enrollment. Use the actual error code: confirmed unauthorized/revoked credentials remain rejected across restart; insufficient scope, lost arbitration, unavailable mappings and service failures do not revoke credentials. A different credential is not trusted until Home verifies it. A denied mapping cannot borrow another mapping's claim or Profile. Verify the current mapping before follow-up capture and turn dispatch. Recovery uses existing current configuration and fresh, ready claim/session; it never replays speech. Maintain P-4's trusted calibrated-provider gate, with no production provider installed. Preserve P-1's explicit Direct-mode degraded policy. Physical appearance remains unverified without hardware.

**Never:** Add an enrollment protocol, invented Home policy, broad new story, fallback Profile, wake-confidence/fixed-score/tap proximity workaround, live credential inspection, microphone diagnostic capture, deployment, service mutation or flashing. Store no raw credential in the rejection marker or logs. Do not claim renewal/reenrollment UI or hardware delivery from fixtures.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| CURRENT_MAPPING | Verified current claim and authorized matching mapping | Matching sequence admits capture; correct route only | Recheck mapping at dispatch |
| MAPPING_UNAVAILABLE | Mapped Profile absent/unavailable, stale or unverified configuration | Visible Unavailable before capture; no audio/upload/turn | Retire unusable current claim, require verified fresh admission |
| OTHER_MAPPING | Another mapping remains valid | Unavailable mapping never substitutes it; independent mapping remains eligible through its own Home claim | No global credential lockout |
| CREDENTIAL_REJECTED | Home confirms unauthorized/revoked credential | Durable credential-scoped rejection; no capture/turn across restart despite reachability | Fail closed on marker errors |
| NON_CREDENTIAL_DENIAL | Home forbidden/claim denial, 409, 503 or transport error | Capture closed for affected admission, not credential revocation | Verified recovery only; no fallback |
| RECOVERY | Potentially restored mapping/network/credential | Restart/reachability alone never admits; fresh verified configuration/claim/ready session required after unavailability | Trusted provider still required for fresh claims |
| FOLLOW_UP_OR_DISPATCH_CHANGE | Mapping becomes unverifiable after earlier admission | No follow-up capture or Hermes submission | End sequence, no replay |

</frozen-after-approval>

## Code Map

- `puck_bridge/home_admission.py`, `home_session.py`: retain the existing wake grant's `configuration_revision` on the mapping-bound session; compare current authorized configuration against that revision. Operator handles have no proven revision and cannot infer freshness from a new snapshot. Reuse private atomic records and Home error codes; no new Home protocol fields.
- `puck_bridge/turn.py`: physical/follow-up admission, mapping ownership, retirement and dispatch. Retire an unverifiable operator handle or changed-revision claim; later physical wake requires a fresh verified grant/ready session plus trusted provider. Same-ID Profile repoint must invalidate the old revision. Preserve unrelated Direct recovery and response delivery.
- `puck_bridge/server.py`: Home startup; load scoped rejection before connecting or serving capture grants.
- `firmware/respeaker-lite/puck_identity.h`, `puck_response.h`, `respeaker-lite.yaml`: sequence-bound capture gates and solid orange Unavailable on the configured XIAO ESP32-S3 `USER_LED`, GPIO21 active-low. Official Seeed pin-map/Blink polarity note confirms this exact target; current firmware's I2S uses 7/8/9/43/44, I2C 5/6, reset 2, button 3, with no GPIO21 conflict. Physical appearance/assembled visibility remains unverified. Preserve audible refusal.
- `tests/test_puck_home_session.py`, `test_puck_bridge.py`, `test_puck_firmware.py`: isolated Home contract fixtures and native real-header firmware harnesses.
- Home contract evidence: sibling `hermes-relay-home/docs/contracts/v1/README.md`; `src/hermes_home/api/application.py` Device configuration filters only authorized active available mappings; 401 unauthorized, 403 forbidden or claim_denied, 503 service_unavailable. Expired credentials must re-enroll; renewal window remains valid authority.

## Tasks & Acceptance

**Execution:**
- [x] `puck_bridge/home_admission.py` — preserve safe Home error codes and durable credential-scoped rejection; distinguish mapping/service denial and verify exact mapping identity.
- [x] `puck_bridge/turn.py`, `server.py`, `home_session.py` — enforce rejection on startup, physical/follow-up admission and dispatch; bind the existing grant revision, deny inferred operator-handle freshness and same-ID repoints, and require verified claim recovery without disabling independent mappings.
- [x] `firmware/respeaker-lite/puck_identity.h`, `puck_response.h`, `respeaker-lite.yaml` — drive the verified XIAO ESP32-S3 on-board orange GPIO21 active-low LED solid Unavailable before denied capture; test real-header transitions, compile firmware, preserve Direct policy, and leave physical appearance gated.
- [x] `tests/test_puck_home_session.py`, `test_puck_bridge.py`, `test_puck_firmware.py` — deterministic matrix and consumer boundary regressions including restarts, mapping isolation, recovery and visible state transitions.
- [x] Existing firmware documentation, story index and sprint tracker — update after local smoke; record acceptance mapping, commands/counts/logs and physical/deferred gates in validation.

**Acceptance Criteria (original Story 3.5, unchanged):**
- Given a recognized Wake Mapping points to a revoked or unavailable Hermes Profile, when the Device evaluates it, then the Device shows a visible Unavailable or Disconnected state before capture begins.
- Given the mapped Profile cannot be verified, when a wake is recognized, then the Device captures no audio, sends no audio payload, and submits no Hermes turn.
- Given other Wake Mappings on the Device point to valid Profiles, when an unavailable mapping is triggered, then the Device does not substitute another Profile or fall back silently.
- Given a powered Device has had its credential revoked, when it attempts to operate, then Hermes access remains denied even if the Device is still reachable.
- Given the Profile or credential later becomes potentially available, when the Device has not completed verified recovery or re-enrollment, then it remains unavailable and does not silently reactivate.

## Implementation Notes

Approval source: original user's “ok next” implementation delegation and parent technical review on 2026-10-18, with explicit instruction to proceed within existing acceptance and locked policy. This is not new human policy approval.

The user's subsequent explicit clarification requires unverifiable operator handles to stay capture-closed: only an existing Home wake grant supplies a verifiable `configuration_revision`. Current revision mismatch, including a same-ID Profile repoint hidden by the Device projection, retires the claim. A later physical wake needs fresh configuration/grant/ready session and trusted calibrated provider; this changes no Home wire field or policy. Bridge `unauthorized` can also mean handle mismatch, so durable credential refusal is confirmed against Home's Device-authorized configuration endpoint, not inferred from that generic bridge code alone.

Local verdict: **done-with-deferred-gate**, tracker **review**. Final focused checks: 277 passed. Final exercised full suite: 2223 passed, 2 skipped, 2 known Bash 3.2 bootstrap cases deselected, six existing warnings; actual Home-mode firmware compile and `git diff --check` passed. Runtime smoke: 17 scenarios, all denied paths zero capture/upload/Home prompts. See [validation](validation-3-p-5-fail-closed-identity.md) for the earlier tooling failure, supported Python 3.12 correction, exact evidence and open physical/real-Home/calibration gates.

## Spec Change Log

- 2026-10-18: Independent spec review found the authorized operator-handle/revision clarification absent from the Code Map. Added that implementation requirement and regression scope outside the frozen original acceptance. KEEP: all five original criteria, scoped credential rejection, mapping isolation, provider gate and visible refusal.

## Review Triage Log

- Spec review — medium / fixed: operator-handle freshness and same-ID Profile-repoint handling were underspecified in the non-frozen Code Map; added the explicitly authorized revision-bound behavior, with no Home protocol fields or policy changes.
- Spec review follow-up — medium / fixed: record the verified exact GPIO21 active-low orange USER_LED target and non-conflicting pin allocation in the Code Map/task, while preserving the physical visibility gate.
- Independent spec disposition after both corrections: correct; no remaining substantive gap against the original five criteria or locked decisions.
- Code blind hunter — false / rejected, independently retracted after path tracing: a failed rejection-marker write does not establish capture restored by restart/reachability. Saved handles are never reopened active; capture still requires fresh authorized configuration, trusted evidence, matching new grant, ready session and revision recheck. Startup storage-read errors fail closed; production has no evidence provider. Final blind disposition: correct.
- Code edge-case hunter — no findings.
- Code verification-gap reviewer — no verification gaps found.

## Verification

- Focused Puck bridge/Home/native firmware tests, then required full repository suite using supported Bash when available; do not rerun known macOS Bash 3.2 failures merely to confirm them.
- Throwaway isolated loopback Home contract smoke through actual bridge receiver/runner and compiled real-header firmware harness: revocation, unavailable mapping, no capture/upload/turn, restart, and verified recovery. Synthetic bytes only, no live services or microphone.
- ESPHome actual production firmware configuration and compile using example secrets only, remove temporary secrets afterward; never flash.
- Independent build-workflow review; record all findings and fixes, exact observed evidence and open physical visibility/calibration/real-Home enrollment gates.
