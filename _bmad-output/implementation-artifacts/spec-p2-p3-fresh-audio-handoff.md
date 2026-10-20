---
title: 'Puck wake acknowledgement and fresh post-playback capture'
type: 'bugfix'
created: '2026-10-19'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '5b0ca37efb91f19bb8797454bf0825deb34c80f3'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-p-2-status-and-response-audio-delivery.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-p-3-bounded-follow-up-and-exact-stop.md'
---

<frozen-after-approval reason="approved by parent delegation of Amanda's scoped P-2/P-3 repair; original owners and policy retained">

## Intent

**Problem:** On a47ded6 Amanda heard an answer but no initial wake cue; quiet follow-up latched VAD true and uploaded 115,376 bytes to STT. Source exposes cached cross-task VAD without freshness, treats source IDLE as output completion, and forwards resampler finish before upstream drain. Primary also reached the eight-second limit; genuine high fresh probabilities versus stale inference remains unproven.

**Approach:** Repair the existing P-2/P-3 audio handoff: finish all accepted resampler/TX audio, positively observe cue completion before capture, and start follow-up only after actual output drain and a short stable settle. Buffer question PCM while VAD warms, but make speech/end-of-speech decisions only from coherent fresh post-boundary model results.

## Boundaries & Constraints

**Always:** Home grant precedes cue/capture; preserve revision/revocation/no-replay and existing claim lifecycle. Keep eight-second bounds, 800 ms silence debounce, gain 4, channel 1, cutoff 0.05, current cue asset/volume, and diagnostics OFF for raw PCM. Keep strict admission for nonapproved modes. Vendor the ESPHome 2026.9.1 resampler locally with pinned provenance and minimal diff, never modify generated output. Provide bounded DEBUG-only per-capture generation/probability and selected post-gain clipping summaries, plus exact speaker error site/error code. Physical acceptance remains open until separately authorized retest; no flashing or host mutation in this implementation.

**Never:** Change Home protocol/policy, tune gain/cutoff/channel/earcon, implement the unapproved three-second window, infer calibration, add listening-LED policy, record PCM/transcripts/credentials, enable VERBOSE, or present a source-risk hypothesis as the observed speaker-error attribution.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Required behavior |
|---|---|---|
| Short cue | Cue starts/finishes between player samples | Positive accepted-audio/completed-drain receipt survives missing ANNOUNCING; no capture before that receipt. |
| Drain | Decoder EOF with upstream or TX bytes pending | Upstream drains gracefully before downstream finish; TX stops only after its DMA drain. Immediate stop remains immediate. |
| Follow-up | Source IDLE but output running/buffered | No follow-up admission/capture until output stopped/empty and stable settle completes. |
| Stale VAD | Pre-playback true, partial window, repeated generation or stopped inference | Cannot latch speech or debounce silence from stale history; PCM still buffers within eight-second bound. |
| Fresh speech | Complete new VAD window, then fresh silence | Normal bounded speech capture; 800 ms fresh silence ends once. |
| Quiet follow-up | No fresh detected speech by limit | Discard PCM, one existing zero-byte control final, status-only silent completion, no STT/turn/media fetch. |
| Fault | Cue/output fails or cannot drain | Bounded refusal/recovery, no capture/replay or fabricated cue completion. |

</frozen-after-approval>

## Code Map

- `firmware/respeaker-lite/components/resampler/` — new local override copied from installed ESPHome 2026.9.1; graceful worker drain precedes TX finish. Expose per-playback generation and successful drained generation for the single owned announcement pipeline, so a short cue does not depend on player polling.
- `firmware/respeaker-lite/components/micro_wake_word/{micro_wake_word,streaming_model}.{h,cpp}`, `vad_snapshot.h` — synchronized actual-invocation/window/epoch snapshots and selected post-gain diagnostics.
- `firmware/respeaker-lite/components/i2s_audio/speaker/` — monotonic fault generation and exact DEBUG site/code, without a guessed DMA fix.
- `firmware/respeaker-lite/{pcm_capture.h,puck_response.h,puck_audio_handoff.h,respeaker-lite.yaml}` — actual completion, acknowledged cleanup, progress/settle gates and fresh VAD; preserve empty-control mailbox/admission. `pyproject.toml` and YAML declare the demonstrated 2026.9.1 compatibility minimum.
- `tests/test_puck_firmware.py`, `test_puck_audio_wiring.py`, `test_respeaker_{resampler,speaker,vad}.py` — actual-source and configured-action native consumer regressions, not source-wording tests.

## Tasks & Acceptance

**Execution:**
- [x] Vendor/fix resampler and record upstream revision/license/file provenance; test pending start+finish, buffered EOF, faults, passthrough, and immediate stop.
- [x] Implement coherent generation-qualified VAD and bounded per-capture probability/rail diagnostics; test stale/reset/partial/stalled histories and actual fresh output.
- [x] Integrate cue/output completion and a 200 ms stable output settle before follow-up; no fixed-delay-only readiness or fake completion. Keep warm-up PCM and finite recovery.
- [x] Add exact speaker-site/code diagnostics without changing driver decisions.
- [x] Run focused/full suite, both Direct/Home actual firmware compiles with example secrets only, and a throwaway actual-header/HTTP smoke. Complete independent spec/code/custodian review, fix findings, and update docs/changelog/tracking for publication.

**Acceptance Criteria:**
- Given an admitted wake, when the short cue completes asynchronously, then capture starts only after its positively observed successful output drain; unavailable/cue failure captures nothing.
- Given playback completion, when output is still buffered/running or within settle, then follow-up remains closed; once safely stopped, a new bounded capture starts without another wake phrase.
- Given stale/partial/nonprogressing VAD, when capture buffers PCM, then no stale speech/silence decision occurs; genuine fresh speech and fresh 800 ms silence work normally.
- Given quiet follow-up, when eight seconds expires or fills, then exactly one empty control completion returns wake-listening with zero PCM/STT/new turn/media fetch.
- Given normal DEBUG firmware, when a capture completes or speaker fails, then bounded content-free numerical/site diagnostics are available without PCM, VERBOSE, credentials or transcripts.

## Implementation Notes

PR255 was already merged on fresh remote inspection; this branch starts directly at origin/main 5b0ca37efb91f19bb8797454bf0825deb34c80f3, not a stack. Approval source is the parent's explicit scoped implementation instruction, not invented new product policy. No irreversible side effects are needed.

Technical review clarifications (no policy change): both initial/follow-up hard eight-second limits start at `begin_capture`; speech near expiry does not restart/extend the clock. Each cue or output-drain/settle handoff has a five-second watchdog, then uses the existing refusal path (two-second refusal watchdog) with capture closed. The 200 ms settle is output-stable time, not a new no-speech policy. Provenance must list exact vendored files, upstream tag/commit and unmodified source hashes; tests cover stop/error versus successful completion. These resolve the independent spec review's timer/bound/provenance findings.

The approved custodian fixes also bound `WAITING_FOR_MEDIA_IDLE`: explicit HTTP-source/TX errors immediately start silent-only terminal confirmation and failed-media cancellation; otherwise 30 seconds without real positive-frame TX progress or the first announcement transition does so. Matching SILENT returns quietly (preserving exact stop/HTTP204); COMPLETE/unavailable/unknown status uses bounded existing refusal and cannot authorize follow-up. Cleanup precedes wake resume; errors after IDLE still reject COMPLETE. The inactivity budget matches existing device fetch/bridge first-audio bounds, not total TTS length. Repeated publications, polling and zero-frame padding never refresh it. A short stream missing player IDLE advances only through its successful drained receipt. Native integration executes configured boot/URL/100ms/250ms actions.

## Spec Change Log

- 2026-10-19, after the 17a1eb1 physical retest (owner heard nothing), parent-approved: cue and refusal assets regenerated at −6 dBFS peak (were −30 dBFS); VAD cutoff 0.05 → model default 0.5 (fresh VAD latched speech to the deadline in the retest); bridge accepts a restarted device's sequence on an idle response stream. These supersede the "cutoff 0.05, current cue asset" constraint above; all other bounds stay. Evidence: [validation](validation-p4-home-paired-room-full-turn.md).

## Review Triage Log

- Medium/spec — Timer origin and expiry ambiguity: clarified hard eight seconds from `begin_capture`, no extension for late speech; fixed/tested as existing policy.
- Medium/spec — Unmeasurable recovery bound: cue/post-output watchdogs are five seconds plus existing two-second refusal recovery; waiting media uses 30 seconds of inactivity, not total playback.
- Low/spec — Reproducible pin: exact upstream commit/package and member hashes plus license retained in the vendored header.
- Medium/code — Old downstream fault preempted new baseline snapshot: fixed start ordering and fault→fresh-recovery native regression.
- Medium/code — Ring allocation failure mislabeled as audio-source allocation: distinct site strings and exact runtime assertions.
- Low/code — Generation zero treated as unseen sentinel: separate seen flag and first-valid-zero regression.
- Medium/verification — Configured stop/request/gating was not executed: actual YAML semantic native integration added, rather than test-only media replacement.
- Medium/code — Decoder/source failure could remain waiting forever: explicit error and real-progress inactivity handling; valid long TTS is not capped.
- Medium/build — Second model constructor retained removed stride member: obsolete assignment removed after actual target compiler failure.
- Medium/code — Error check could be bypassed by IDLE before the periodic tick: on-idle and polling checks retain silent-only confirmation; follow-up rechecks the scoped fault, with real configured-order regressions.
- Medium/contract — Blindly refusing decoder errors would beep on legitimate HTTP204 exact stop: matching authoritative SILENT stays quiet, failed media is canceled before wake resumes, and COMPLETE never becomes success on the failure path.
- Medium/edge-v1 (carried) — Same IDLE-before-check fault as blind-v1; fixed by the same scoped polling/on-idle/follow-up checks, not dismissed.
- Medium/blind-v2 — Stop submission cleared cleanup before asynchronous teardown: request once, observe both sources IDLE and stopped/empty TX/resampler on a later tick; no successful receipt invented.
- Medium/edge-v2.1 (carried) — Same asynchronous cleanup defect; actual delayed-ack fixture proves no wake before confirmation.
- Medium/edge-v2.2 — Fault after SILENT but before wake was ignored: READY-state checks and the final wake guard now request/require cleanup.
- Medium/custodian-v2 (carried) — Same stop-request/ack defect; five-second missing acknowledgement reports Unavailable once and stays capture-closed until real later shutdown, without reboot or credential revocation.
- Low/custodian-v2 — Status GET/callback and resolved response URL assertions were incomplete: actual configured actions now execute and exact synthetic URLs are asserted.
- Medium/environment — Initial build selected ESPHome8.2, whose StaticTask API is incompatible; use actual9.1, declare its minimum in config/extra, and preserve the initial failed/nonexecuted checks rather than claiming green.
- Medium/custodian-v3 — Failed follow-up could clear response ownership while leaving undrained output in READY: after the existing two-second refusal grace, request the same acknowledged cleanup, retaining its five-second Unavailable bound. Executed configured-action regressions cover missing acknowledgement and an ordinary 360 ms refusal tail.
- Final review — Independent spec review, blind code review, edge-case review, verification review and the sole firmware custodian's final SPEC/CODE review have no outstanding substantiated finding on the frozen final runtime diff. This is software review, not flash approval or physical acceptance.

## Verification

**Observed local software validation complete; physical gate OPEN.** In an isolated Python3.14.8 environment resolved from current requirements (faster-whisper1.2.1 / av18.1.0), the five focused firmware/native modules plus the real unmocked WAV decoder regression passed **123 tests, 33.81s**. Full pytest passed **2466 tests, 2 skipped, 2 known macOS Bash3.2 ops cases deselected, 6 existing warnings, 392.38s**. Both actual ESPHome2026.9.1 / ESP-IDF5.5.5 Direct/Home compiles passed with public example-only settings. The native/libcurl/production-bridge loopback smoke passed both deadline/buffer scenarios: one empty control, zero uploaded PCM/STT/new follow-up turns/media GETs. Wheel and source distribution build passed. Commands, skip reasons, image hashes, superseded failed-environment attempts, review fixes and acceptance mapping are in [validation](validation-p4-home-paired-room-full-turn.md#p-2p-3-fresh-output-handoff-repair--2026-10-19).

`done` means this scoped software repair is implemented and reviewed with a deferred physical gate. P-2/P-3 remain in review. Audible cue, fresh quiet follow-up, real fresh-probability/noise behavior and speaker-error attribution still require the sole custodian's separately authorized flash/retest; none ran here. The already accepted paired-room first full turn remains accepted.
