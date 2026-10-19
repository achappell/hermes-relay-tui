---
title: 'P-3 amendment: quiet follow-up closes without PCM upload or silent media playback'
type: 'bugfix'
created: '2026-10-19'
status: 'done'
disposition: 'done-with-deferred-gate'
physical_acceptance: 'open'
route: 'dispatch'
review_loop_iteration: 0
reconciled_main: 'b3aba782abdfd32151562218855b09bbe98af474'
verified_source_commit: '0f81c3b4cf8219c43dc1920abe92e9d70534e416'
baseline_commit: '5311eb32a446d108a45d49c48f1a945638cca6e5'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-p-3-bounded-follow-up-and-exact-stop.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-p4-home-fresh-startup.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The accepted paired-room turn's automatic follow-up reached the eight-second PCM buffer limit, uploaded audio, and produced no usable phrase. The receipt does not prove whether Amanda was quiet or whether VAD detected echo/noise. Independently, source proves that the full-buffer callback uploads a follow-up even when no speech was detected: its eight-second capacity races the identical no-speech deadline. A locally empty completion also unnecessarily opens the media source against a silent HTTP 204 response.

**Approach:** Repair existing P-3 without changing its owner-chosen eight-second no-speech window, eight-second maximum utterance buffer, or 800 ms end-of-speech debounce. Discard no-speech PCM whether the buffer callback or window deadline wins, acknowledge it using the existing empty final capture POST, then confirm the matching silent status without starting audio playback. Retain P-4/STD-6 authorization and recovery invariants.

## Boundaries & Constraints

**Always:** Fresh Home admission precedes capture. Follow-up retains the admitted Session/Profile and verifies existing mapping authority. Preserve exact `stop`, identity rejection, refusal, timeout/recovery, sequence isolation, no replay, P-8 timing, P-9 channel lifecycle, and P-10 internal-model routing. Nonempty speech retains the existing eight-second maximum and 800 ms end-of-speech debounce. Silence produces no PCM transfer, STT invocation, Hermes turn, TTS request, audible refusal, or new unavailable indication. One zero-byte control completion POST remains necessary to settle the existing bridge mailbox. A later physical wake still needs its own fresh grant.

**Never:** Tune VAD threshold/gain, infer calibration or actual acoustic content, add Home/protocol fields or endpoints, change other frontends' timeout, erase recovery state, auto-close Home claims under a new policy, alter upstream decoder/DMA recovery speculatively, or claim physical acceptance. No live actions, recording, flashing, or secret reads. Hardware reproduction requires parent GO plus Amanda and the sole firmware custodian.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Quiet deadline | Admitted follow-up, VAD false throughout | Stop at the existing 8 s bound; discard PCM; one empty completion; matching silent status returns to wake | No normal media fetch or refusal |
| Buffer callback wins | No speech detected; capacity fills before main-loop tick | Same zero-PCM outcome, never classified as a full speech upload | No false buffer-limit warning |
| Speech starts within window | VAD becomes active before no-speech deadline | Existing speech path, max 8 s captured PCM and 800 ms silence end | No new gain/threshold policy |
| Exactly stop / empty STT | Real speech upload yields exact stop or no usable phrase | Existing silent outcome; no new Hermes turn | Local known-empty optimization does not falsely label speech silent |
| Completion pending or denied | Empty control POST accepted; matching terminal status not ready or authority fails | Existing bounded status/rejection behavior and fail-closed capture | Never accept stale sequence, wrong body, or mere HTTP 200 |
| Later wake | Quiet follow-up returned to IDLE | Existing prior-claim retirement and new verified Home grant before capture | Unconfirmed close remains latched across restart |

</frozen-after-approval>

## Code Map

- `firmware/respeaker-lite/pcm_capture.h` — discard on write-before-tick boundary, preserve eight-second deadline, expose whether delivered capture was locally empty.
- `firmware/respeaker-lite/puck_response.h` and `respeaker-lite.yaml` — existing response-status confirmation may start directly for a known-empty completion; preserve normal media and admission paths. Accept only matching silent JSON on this path, never matching complete as permission for another follow-up.
- `puck_bridge/receiver.py`, `turn.py`, `response.py` — existing empty capture → silent mailbox → coordinator finish; tests must exercise these production callbacks.
- `tests/test_puck_firmware.py`, `tests/test_puck_bridge.py` — existing native-header and real HTTP fixtures; no source-wording tests.
- Existing P-3 spec, `sprint-status.yaml`, `story-index.yaml`, firmware README and CHANGELOG — record narrow amendment and verification after runtime smoke, preserving historical acceptance and open physical gates.

## Tasks & Acceptance

**Execution:**
- [x] Make quiet completion discard PCM on write-before-tick boundary using existing capture ownership and unchanged eight-second deadline.
- [x] Add status-only known-empty completion without constructing a media request or a second response state machine.
- [x] Test quiet/boundary/speech/sequence/refusal cases with the real headers and production bridge callbacks.
- [x] Run isolated loopback bridge + native firmware-header smoke, focused/full checks, and both firmware builds with example-only configuration.
- [x] Obtain independent spec/code review from the firmware custodian; fix actual findings and update existing docs/tracking with physical gates explicitly open.

**Publication requirement:** Normal push and a non-draft PR remain mandatory under the owner's authorization, with exact local/remote/PR head equality and observed CI. No merge or physical action is authorized; this delivery step is separate from local implementation acceptance.

**Acceptance Criteria:**
- Given no detected speech, the follow-up returns to wake listening at the existing eight-second bound plus scheduling/status polling latency, without PCM upload or a new turn.
- Given real speech, repeated follow-up and exact stop retain the existing single-Session/Profile semantics and eight-second maximum capture behavior.
- Given silent completion, no audio media source is opened for the locally known empty capture; genuine media failures must not be suppressed.
- Given authority loss or uncertain retirement, no new capture/turn/replay occurs until the existing verified recovery flow permits it.

## Implementation Notes

Approved by parent technical direction on 2026-10-19: implement only the deterministic no-speech discard and known-silent status path; preserve all eight-second timing and claim lifecycle. Proposed three-second shortening is OUT OF SCOPE and remains an unanswered product question for Amanda, not an implementation prerequisite.

Implemented one-shot atomic capture finalization and immutable byte-count publication shared by deadline/buffer completion; upload never re-reads a late mutable cursor. Existing YAML consumes `last_delivered_empty` to select status-only confirmation, with strict silent-only response validation. Bridge production code needs no change; its actual mailbox/HTTP callbacks are exercised by new coverage.

## Spec Change Log

## Review Triage Log

- Independent custodian SPEC review: fixed the YAML path and exact status-body description. Require known-empty matching-complete/wrong-sequence/non-200 regression coverage. The cached VAD-high restart case is a preexisting limitation outside the approved `!speech_seen` fix, not acoustic proof or permission to change the model.
- Custodian CODE review `high`, fixed: deadline preemption inside microphone `memcpy` could leave late cursor bytes for upload. Winner-only finalized snapshot and shared atomic control/cursor flags prevent that leak; real-header ASan/UBSan small/full-buffer preemption regressions passed. Independent re-review confirmed resolution and no new blocking runtime finding.
- Custodian CODE review `low`, fixed: a Python-only HTTP recorder could not prove firmware avoided media fetch. Removed that tautological recorder/assert; actual configured-YAML/header tests and native-to-HTTP smoke provide consumer evidence.
- Build-workflow blind and edge-case reviewers reported no actionable finding. Verification reviewer observation `false` as a defect: a speech frame copied but not yet committed to `write_pos` is outside the finalized capture boundary. The snapshot includes every committed byte at close and deliberately excludes an in-flight frame; the 800 ms silence end remains unchanged. No contract requires delaying closure or reading a concurrently mutating tail, so no production correction is justified.

## Design Notes

Inspected installed firmware `21223b44dffb5df773760073bea11e460716d85c` and fresh main `5311eb32a446d108a45d49c48f1a945638cca6e5`; their capture/response headers match. Current `NO_QUESTION_OR_AUDIO` is a receipt classification, not a firmware error enum. A bridge silent terminal yields HTTP 204 and exact HTTP 200 JSON `{"seq": <seq>, "status": "silent"}` from `/response-status`; the latter releases wake without refusal/LED mutation. Local coordinator cleanup disarms the follow-up mailbox, but does not itself retire the Home claim: retirement remains owned by existing next-wake/shutdown/recovery paths.

A source-backed candidate for the unattributed speaker error is intentional silent 204 handling: the linked micro-decoder cannot determine a file type from a headerless 204 at extensionless `/response`, reports reader failure, and the speaker-source player can log an announcement-source error. The receipt retained no exact error line, so this does not establish attribution or a DMA/teardown race. Broad output fault handling remains P-11; no speculative driver change belongs here. A content-free, parent-authorized hardware observation can later distinguish these causes.

`get_vad_state()` retains its last model result across stop/start. A stale/current true result can still set `speech_seen` and retain the speech path; this change does not diagnose or fix that preexisting freshness limitation. Quiet physical behavior and the actual eight-second event therefore remain unproven until controlled observation.

## Verification

**OBSERVED:** Eight targeted native-header/HTTP edge cases passed (156 deselected, 5.24 s), including ASan/UBSan callback-preemption cases. Independent custodian spec/code review fixes are applied. A throwaway native-header/configured-YAML/libcurl → production bridge HTTP/mailbox smoke passed both deadline and buffer-first cases: one control POST, zero PCM/STT/new turn/media fetch, native IDLE and unchanged claim lifecycle. See [validation](validation-p4-home-paired-room-full-turn.md#p-3-deterministic-no-speech-completion-repair--2026-10-19).

**FINAL OBSERVED CHECKS AFTER MAIN RECONCILIATION:** Focused bridge/firmware/Home/shutdown/I2S modules: **368 passed, 168.80 s**. Full Python suite: **2370 passed, 2 skipped, 2 explicitly known Bash 3.2 cases deselected, 6 existing warnings, 397.17 s**. Both actual Direct/Home firmware builds passed again on ESPHome2026.9.1 / ESP-IDF5.5.5 after normal merge of main's browser fallback; only CHANGELOG conflicted, and no Puck runtime resolution was needed. Temporary synthetic secrets/toolchain link and the throwaway smoke runner were removed. Independent custodian and all three build-workflow review layers completed as recorded above. Exact commands, skip reasons, firmware hashes, matrix mapping and the unexecuted flash/rollback plan are in [validation](validation-p4-home-paired-room-full-turn.md#p-3-deterministic-no-speech-completion-repair--2026-10-19). Physical quiet/follow-up and speaker-error attribution remain OPEN.
