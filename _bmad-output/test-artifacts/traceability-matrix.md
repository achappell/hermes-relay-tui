---
stepsCompleted: [step-01-load-context, step-02-discover-tests, step-03-map-criteria, step-04-analyze-gaps, step-05-gate-decision]
lastStep: step-05-gate-decision
lastSaved: 2026-09-26
coverageBasis: acceptance_criteria
oracleResolutionMode: formal_requirements
oracleConfidence: high
oracleSources: [_bmad-output/implementation-artifacts/spec-tui-home-01-pair-with-home-and-own-sessions.md]
externalPointerStatus: not_used
collectionStatus: COLLECTED
sourceSha: ef2bc57f228245b8172092fabf77ebb68adbd55a
tempCoverageMatrixPath: /tmp/tea-trace-coverage-matrix-20260926T192453Z.json
persistedCoverageMatrixPath: _bmad-output/test-artifacts/tui-home-01-coverage-matrix.json
---

# TUI-HOME-01 acceptance trace

## Testing gate: PASS

All six formal acceptance criteria have appropriate executable evidence: P0 5/5, P1 1/1. Requirement-mapping thresholds are met; no criterion relies only on a recorded live observation. This is a testing gate for the documented working tree, with review and branch integration still pending.

The oracle is the six acceptance criteria in the approved story. All six are classified FULL at the levels described below. The resulting 6/6 (100%) is requirement mapping, not code coverage. P0 covers five criteria; P1 covers one. P2/P3 have no criteria and their machine-readable percentages use the workflow’s empty-denominator convention.

## Execution evidence

- **focused_pytest:** 32 passed in 0.60s: tests/test_home_client.py, tests/test_home01_acceptance.py, tests/test_home_textual_session.py; confirmed by parent agent.
- **final_full_pytest:** 1656 passed, 1 skipped, 6 warnings in 293.85s on the tested working tree; confirmed by parent agent and /tmp/home01-final-pytest.log.
- **full_suite_skip:** tests/test_puck_firmware.py::test_respeaker_yaml_passes_esphome_config_generation (line 311): firmware ESPHome environment is not installed. Outside TUI-HOME-01; no mapped story test skipped.
- **native_secure_storage:** Six named storage checks passed on macOS native Keychain and six on Linux Secret Service at ops. Absent Secret Service failed closed. Synthetic origins were removed; temporary Linux lab removed and verified. Confirmed by parent agent.
- **isolated_home_service:** All 11 named groups passed again after the TLS error-classification fix: pending/reject/expire/code/link enrollment; cross-Profile reference; stale configuration; claim limit; owner approve/reject including non-owner denial; persisted renewal response-loss retry plus two concurrent clients; native unpair versus explicit server revocation. Home source b51d289a680229dfb14c6f2ae8f0f1396dadd430; synthetic Standard directory. Confirmed by parent agent.
- **deployed_quit:** Post-fix ready quit confirmed claim release and normal exit, saved QA conversation remained listed inactive, held-claim early quit exited normally without transcript exception, and cleanup explicitly retired the known claim. No prompt sent. Confirmed by parent agent.
- **historical_checkpoint:** Earlier unchanged source suite: 1640 passed, 1 skipped, 6 warnings. Earlier focused selection: 347 passed. These remain historical results, superseded by the current full run.
- **dated_live_context:** Validation records earlier deployed text/voice, new/continue/list/search/resume/title, reconnect with one claim and two sockets, and two-window busy behavior. They are historical narrative observations, not newly generated live-manifest records.

The source under test is commit `ef2bc57f228245b8172092fabf77ebb68adbd55a` plus the uncommitted TLS exception classification fix and acceptance additions. Runtime and test file hashes are persisted in the coverage matrix. No result is described as a clean-commit test.

## Criterion mapping

### AC1 — Approved link or Home+code pairing launches a granted Profile (P0, FULL)

Approved code and link enrollment exercise the actual disposable Home HTTP service, native persistence and public profile creation. Existing component tests cover launch configuration and private credential delegation; earlier deployed acceptance confirms text and voice use.

- `tests/test_home_pairing_cli.py::test_approved_pairing_saves_secure_record_and_launchable_profile_preserving_other_profiles` — component; pytest node.
- `tests/test_home_pairing_cli.py::test_saved_credential_can_recover_missing_public_config_without_reenrollment` — component; pytest node.
- `tests/test_profile_cli.py::test_create_home_profile_does_not_request_or_store_a_bearer_token` — component; pytest node.
- `tests/test_home_textual_session.py::test_textual_home_session_delegates_turns_and_keeps_pairing_private` — component; pytest node.
- `scripts/qa_home01_service.py::enrollment-code` — api; named opt-in script check, not a pytest node.
- `scripts/qa_home01_service.py::enrollment-link` — api; named opt-in script check, not a pytest node.

### AC2 — Unavailable secure storage and pending/rejected/expired enrollment fail truthfully (P0, FULL)

Service-backed pending/rejected/expired states complement unavailable native-store probes and deterministic consume/save failures. HTTP negatives cover TLS rejection, redirects, deadlines, invalid schemas, malformed/oversized bodies and sanitized errors.

- `tests/test_home_pairing_cli.py::test_secure_store_preflight_failure_stops_before_enrollment_or_consumption` — component; pytest node.
- `tests/test_home_pairing_cli.py::test_consume_and_save_failures_preserve_truthful_single_use_guidance[lost_consume_response]` — component; pytest node.
- `tests/test_home_pairing_cli.py::test_consume_and_save_failures_preserve_truthful_single_use_guidance[save_after_consume]` — component; pytest node.
- `tests/test_home_client.py::test_http_boundary_refuses_unsafe_responses_and_closes_connection[redirect-transport]` — unit; pytest node.
- `tests/test_home_client.py::test_http_boundary_refuses_unsafe_responses_and_closes_connection[tls-transport]` — unit; pytest node.
- `tests/test_home_client.py::test_http_boundary_refuses_unsafe_responses_and_closes_connection[deadline-transport]` — unit; pytest node.
- `tests/test_home_client.py::test_http_boundary_refuses_unsafe_responses_and_closes_connection[malformed-invalid_response]` — unit; pytest node.
- `tests/test_home_client.py::test_http_boundary_refuses_unsafe_responses_and_closes_connection[boolean-schema-invalid_response]` — unit; pytest node.
- `tests/test_home_client.py::test_http_boundary_refuses_unsafe_responses_and_closes_connection[string-schema-invalid_response]` — unit; pytest node.
- `tests/test_home_client.py::test_http_boundary_refuses_unsafe_responses_and_closes_connection[oversized-invalid_response]` — unit; pytest node.
- `tests/test_home_client.py::test_http_boundary_refuses_unsafe_responses_and_closes_connection[error-body-unauthorized]` — unit; pytest node.
- `scripts/qa_home01_service.py::enrollment-pending` — api; named opt-in script check, not a pytest node.
- `scripts/qa_home01_service.py::enrollment-reject` — api; named opt-in script check, not a pytest node.
- `scripts/qa_home01_service.py::enrollment-expire` — api; named opt-in script check, not a pytest node.
- `scripts/qa_home01_secure_store.py::unavailable_store` — component; named opt-in script check, not a pytest node.

### AC3 — Home/Profile/window selection and renewal preserve credentials, histories and claims (P0, FULL)

Native storage verifies origin separation; actual Home denies another Profile’s reference and stale configuration, enforces claim limits, and recovers a persisted renewal request. Two concurrent clients renew once. Component tests verify prompt-history identity and post-release replacement failure without replay. Earlier deployed two-window acceptance remains context.

- `tests/test_home_client.py::test_request_rejects_another_homes_credential_before_http` — unit; pytest node.
- `tests/test_home_client.py::test_two_windows_share_one_renewal_transaction` — unit; pytest node.
- `tests/test_home_client.py::test_interrupted_renewal_reuses_persisted_request_across_client_restart[cancelled_request]` — unit; pytest node.
- `tests/test_home_client.py::test_interrupted_renewal_reuses_persisted_request_across_client_restart[lost_response]` — unit; pytest node.
- `tests/test_home_client.py::test_interrupted_renewal_reuses_persisted_request_across_client_restart[failed_save]` — unit; pytest node.
- `tests/test_home01_acceptance.py::test_home_prompt_history_separates_origin_and_grant_and_canonicalizes_urls` — component; pytest node.
- `tests/test_home01_acceptance.py::test_home_replacement_failure_after_release_retains_transcript_without_replay[claim]` — component; pytest node.
- `tests/test_home01_acceptance.py::test_home_replacement_failure_after_release_retains_transcript_without_replay[bridge]` — component; pytest node.
- `scripts/qa_home01_secure_store.py::native-roundtrip-origin-isolation-delete` — component; named opt-in script check, not a pytest node.
- `scripts/qa_home01_service.py::cross-profile-reference` — api; named opt-in script check, not a pytest node.
- `scripts/qa_home01_service.py::stale-configuration` — api; named opt-in script check, not a pytest node.
- `scripts/qa_home01_service.py::claim-limit` — api; named opt-in script check, not a pytest node.
- `scripts/qa_home01_service.py::native-renewal-lost-response-retry-and-two-concurrent-clients` — api; named opt-in script check, not a pytest node.

### AC4 — Supported Home session operations execute and guards preserve busy/uncertain work (P1, FULL)

Home-specific guards cover uncertain/queued work, post-release claim/bridge failure and unsupported title/new/resume operations before dispatch. Actual service checks owner decisions and unauthorized access. Dated deployed acceptance covers new/continue/list/search/resume/title; generic Standard session tests are not counted as Home integration.

- `tests/test_home01_acceptance.py::test_home_change_guards_never_invoke_replacement[uncertain]` — component; pytest node.
- `tests/test_home01_acceptance.py::test_home_change_guards_never_invoke_replacement[queued]` — component; pytest node.
- `tests/test_home01_acceptance.py::test_home_replacement_failure_after_release_retains_transcript_without_replay[claim]` — component; pytest node.
- `tests/test_home01_acceptance.py::test_home_replacement_failure_after_release_retains_transcript_without_replay[bridge]` — component; pytest node.
- `tests/test_home01_acceptance.py::test_unsupported_home_operations_never_dispatch_or_replace[title]` — component; pytest node.
- `tests/test_home01_acceptance.py::test_unsupported_home_operations_never_dispatch_or_replace[explicit-new-id]` — component; pytest node.
- `tests/test_home01_acceptance.py::test_unsupported_home_operations_never_dispatch_or_replace[unknown-resume]` — component; pytest node.
- `tests/test_profile_app.py::test_profile_switch_is_refused_during_an_active_turn` — component; pytest node.
- `tests/test_puck_home_session.py::test_home_interrupt_requires_advertised_capability_and_returns_ack` — component; pytest node.
- `tests/test_puck_home_session.py::test_home_rejects_concurrent_puck_turns` — component; pytest node.
- `scripts/qa_home01_service.py::owner-approve-reject` — api; named opt-in script check, not a pytest node.

### AC5 — Reconnect recovers the same claim; quit retires it without replay or history loss (P0, FULL)

Loopback WebSocket tests check mid-turn loss and no replay; adapter tests check one recovered claim and explicit failures. Deployed ready and held-claim early quit pass. The saved QA conversation remains listed inactive after close. Historical message hydration remains a stated Home limitation.

- `tests/test_home_textual_session.py::test_textual_home_session_marks_recovery_as_reconnect` — component; pytest node.
- `tests/test_home_disconnect.py::test_home_websocket_close_ends_thinking_preserves_uncertainty_and_never_replays[while-thinking]` — api; pytest node.
- `tests/test_home_disconnect.py::test_home_websocket_close_ends_thinking_preserves_uncertainty_and_never_replays[during-reply]` — api; pytest node.
- `tests/test_app.py::test_quit_survives_an_unconfirmed_home_claim_release[False]` — component; pytest node.
- `tests/test_app.py::test_quit_survives_an_unconfirmed_home_claim_release[True]` — component; pytest node.
- `tests/test_puck_home_session.py::test_home_transport_failure_requires_reconnect_and_never_replays_prompt` — component; pytest node.
- `tests/test_puck_home_session.py::test_home_reconnects_an_unavailable_binding_when_requested` — component; pytest node.
- `tests/test_puck_home_session.py::test_unconfirmed_puck_claim_can_retry_control_close_once` — component; pytest node.
- `scripts/qa_home01_live_quit.py::live-ready-quit` — component; named opt-in script check, not a pytest node.
- `scripts/qa_home01_live_quit.py::live-early-quit` — component; named opt-in script check, not a pytest node.

### AC6 — Local unpair clearly distinguishes local forgetting from server revocation (P0, FULL)

Actual native local unpair removes the pairing and reports that it does not revoke access. The disposable Home service accepts the retained credential until explicit server revocation, then rejects it. Unit tests cover corrupt/absent records and real deletion failures.

- `tests/test_home_client.py::test_unpair_deletes_corrupt_records_but_reports_real_deletion_failure[corrupt]` — unit; pytest node.
- `tests/test_home_client.py::test_unpair_deletes_corrupt_records_but_reports_real_deletion_failure[absent]` — unit; pytest node.
- `tests/test_home_client.py::test_unpair_deletes_corrupt_records_but_reports_real_deletion_failure[delete_failure]` — unit; pytest node.
- `scripts/qa_home01_secure_store.py::native-roundtrip-origin-isolation-delete` — component; named opt-in script check, not a pytest node.
- `scripts/qa_home01_service.py::native-unpair-keeps-server-access-until-server-revocation` — api; named opt-in script check, not a pytest node.

## Inventory and gap disposition

The deduplicated mapped inventory contains 57 identities across 12 files. It includes parameter-expanded pytest nodes and named opt-in script check groups; this number is not a pytest execution total. None of these mapped cases is skipped, pending or fixme. The broader discovery catalog also retains unmapped contextual tests.

The earlier endpoint/auth/error-path findings are dispositioned by the service integration, eight HTTP boundary cases, three unsupported-operation cases and Home replacement tests. Native Linux evidence, renewal retry and post-fix live quit are complete. No critical/high testing gap remains within the six-criterion scope. Overlap between native/API probes and component failures is deliberate: persistence and service semantics need both successful integration and deterministic injected failures.

## Environment and evidence limits

- Coverage percentages count the six approved acceptance criteria only; no line, branch or exhaustive input coverage measurement was performed.
- Native Linux checks ran in an isolated unlocked Secret Service session on ops; the absent-service case also failed closed. This does not assert that an ordinary headless SSH login already has an unlocked keyring.
- Isolated Home HTTP checks use real Home source b51d289 with SQLite and native secure storage, but a synthetic Standard session-directory fixture; deployed Standard generation is supported by earlier text/voice observations.
- Deployed quit probes use the actual Textual app test driver and Amanda QA conversation; early quit deliberately holds the accepted claim response. The test verifies the saved conversation is still listed inactive after close and explicitly cleans up its known claim; it does not assert historical message loading, which Home does not supply.
- Historical text/voice/new/continue/list/resume/title/reconnect/two-window observations remain dated validation context. Deployed Home/Standard revision was not independently established; this is a provenance limitation, not an independent blocker for this TUI test gate.
- The formal story remains review/in-review. Testing PASS does not complete review, commit unpublished artifacts, merge the fix/program branch, or authorize release.

No `live-verification-results.json` manifest was supplied. Historical narrative observations are retained as dated context and are not relabeled as fresh manifest records. The new native, isolated service and deployed-quit checks have rerunnable script artifacts; no criterion is covered only by a one-time live observation.

## Workflow completion and remaining delivery work

Step 4 persisted the coverage JSON and recorded its exact temporary path before step 5 read it. A durable copy is `tui-home-01-coverage-matrix.json`; `e2e-trace-summary.json`, `gate-decision.json` and `tui-home-01-gate-report.json` carry the same decision. The story specification remains `in-review`, and its owning `sprint-status.yaml` remains `review`. Complete review and branch integration before formal closure.

**Gate summary: PASS for testing. P0 5/5, P1 1/1, six mapped criteria, no live-only criterion. Review and merge remain pending.**


## PR preparation provenance correction

GitHub subsequently confirmed PR #212 and PRD integration PR #211 already merged. This follow-up targets `main` from `fix/tui-home-01-acceptance-closeout`, based on `77a4661`. The recorded test counts and source hashes above retain their original run provenance; they are not a claim that the new PR commit was rerun locally. Relative to the tested base, current main adds release metadata/changelog and pairing CLI tests without application runtime changes. Review and merge of this follow-up remain pending.
