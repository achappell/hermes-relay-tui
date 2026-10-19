---
title: 'Fail-safe ReSpeaker RX I2S lifecycle'
type: 'bugfix'
created: '2026-10-18'
status: 'in-review'
route: 'dispatch'
review_loop_iteration: 0
story_key: '1-p-9-make-respeaker-i2s-channel-startup-and-teardown-fail-safe'
baseline_commit: '208573c4a6190f2fe098e15376412a0fac1324b1'
context: []
---

<frozen-after-approval reason="existing P-9 acceptance; engineering checkpoint delegated by user, not new human spec approval">

## Intent

**Problem:** Microphone startup failures can return holding a parent lock or partially allocated RX channel; the handle and several shared configuration fields are uninitialized. Caller cleanup partly masks this but cannot make direct startup ownership deterministic.

**Approach:** Initialize every driver-bound field, make each failed startup unwind before returning, disable only an enabled channel, always attempt safe deletion, clear the handle and release the owned parent lock exactly once. Report the original startup operation/error structurally and log cleanup operations with RX port context. Retain retry and pacing behavior.

## Boundaries & Constraints

**Always:** Preserve P-8's supported microphone format and converter; own the parent lock from successful acquisition until cleanup finishes. Preserve the original failure separately from cleanup errors. Cleanup is idempotent even before acquisition, after partial allocation, and after repeated stop. A new start never reuses a stale handle. Driver cleanup failures remain explicit, not claimed as successful hardware resource release.

**Never:** Change speaker/DMA timing or P-5 response pacing, admission/proximity/evidence policy, wake models, default-off diagnostic PCM, or hardware configuration. Do not modify `components_stock`, the intentionally untouched upstream comparison fixture. No deployment, flashing, reboot, real audio or credential access.

## I/O & Edge-Case Matrix

| Scenario | Input/state | Expected behavior | Error handling |
|---|---|---|---|
| Busy parent | lock not acquired | no channel call, no unlock | existing caller retry |
| Allocate failure | owned lock; no RX or partially returned RX | delete allocated RX if present, clear handle, release once | structured allocate failure |
| Initialize failure | RX allocated, never enabled | no disable; delete and release once | structured initialize failure |
| Enable failure | initialized RX, never running | delete and release once | structured enable failure |
| Successful start/stop | RX enabled | disable then delete then unlock, clear flags | subsequent stop no-op |
| Disable/delete fault | teardown reports failure | log operation/port/code, attempt remaining safe cleanup, clear local ownership | do not overwrite startup failure |
| Retry after failed start | injection removed | new handle, usable start/stop and balanced lock | no stale ownership |
| Omitted shared settings | default construction | deterministic pins/port/format/lifecycle values | no uninitialized driver fields |

</frozen-after-approval>

## Code Map

- `firmware/respeaker-lite/components/i2s_audio/microphone/i2s_audio_microphone.h`: initialize RX handle/DC flag, enabled state and typed startup failure accessor.
- `firmware/respeaker-lite/components/i2s_audio/microphone/i2s_audio_microphone.cpp`: `start_driver_`, `stop_driver_`, `loop` caller. Preserve stream/capture/pacing; maintain the created task's driver ownership while awaiting TASK_RUNNING. Cleanup immediately on each driver failure; existing caller cleanup remains harmless.
- `firmware/respeaker-lite/components/i2s_audio/i2s_audio.h`: initialize shared pins and format fields; document parent mutex ownership for one controller, not an imagined shared RX/TX handle.
- `tests/test_respeaker_i2s.py`, `tests/firmware/`: compile the actual production microphone `.cpp` and shared header with narrow ESPHome/FreeRTOS/IDF stubs. Fault injection controls driver return values and records actual calls; not source-text tests or copied lifecycle logic.
- P-8 spec/validation supplies inherited conversion and firmware contract. P-9 PR stacks on P-8 at the exact baseline above, avoiding duplicate P-8 changes in its diff.

## Tasks & Acceptance

**Execution:**
- [x] Initialize shared and RX fields; add typed startup failure and enabled ownership; unwind before every failed return, idempotent contextual cleanup.
- [x] Native real-source mocked-driver regression for allocation/init/enable/disable/delete, pre-lock teardown, repeated cleanup, retry, defaults and primary-error preservation.
- [x] Run focused firmware/format/lifecycle tests, separate actual-source native smoke, default/Home firmware compiles and full suite using installed tool environments and modern bash, serialized.
- [x] Independent spec and code reviews; fix findings; after smoke update README/changelog, story index/tracker/coverage/deferred and validation; prepare the non-draft stacked PR handoff. Publication and local/remote/PR SHA identity are reported separately to the director.

**Acceptance Criteria:**
- Given RX allocation followed by init/enable failure, when startup returns, then applicable channel cleanup has run, handle is clear, lock released once and structured failure reports the original operation.
- Given startup fails before locking, when teardown runs, then no unowned unlock or invalid-handle operation occurs.
- Given disable/delete fails, when cleanup proceeds, then operation/RX port is logged and all remaining safe cleanup executes without retaining local stale ownership.
- Given generated shared-bus config, when pins/port/lifecycle fields initialize, then no uninitialized field reaches IDF and input/output ownership is explicit.
- Given lifecycle changes, when mocked-driver checks and actual firmware builds exercise failure/retry paths, then software recovery is deterministic and wake capture/P-5 pacing remain unchanged; physical fault behavior is not inferred.

## Implementation Notes

No unresolved product intent gap or irreversible action. User delegated routine engineering/spec checkpoint decisions, not locked evidence policy. Hardware remains exclusively owned by tui-p7-pcm-diagnostics; raw PCM diagnostics remain off. Shared Mac checks are serialized and use existing venv executables, not uv dependency resolution.

Actual-source harness additionally exposed a pending-task ownership race: before a newly created task publishes TASK_RUNNING, another component loop could retry startup, fail its own parent lock and tear the live channel down. Added the real regression, observed its assertion fail, then guarded STATE_STARTING while a task handle exists. Combined lifecycle/format checks pass (3 tests). The initial harness-only compile failure (protected fake-base state) was corrected before observing that red regression. No copied lifecycle logic is tested.

## Spec Change Log

## Review Triage Log

- Independent P-9 spec review: no findings; exact acceptance, cleanup semantics, ownership/default initialization and actual-source fault harness were checked.
- Blind-hunter code review found no actionable patch-introduced defects (no fabricated six-finding floor); edge-case review returned `[]`; verification-gap review reported no gaps. Default-port assertion was added to the actual-source harness after review to explicitly cover omitted port initialization.

## Verification

Observed: lifecycle/format native checks 3 passed, final focused firmware/format/lifecycle 23 passed; separate actual-source ASan/UBSan smoke passed 12 alternating failure/success cycles; actual default/Home firmware compiles succeeded. Full suite under supported bash: 2199 passed, 2 skipped, 6 warnings in 344.79 s, including ESPHome config generation with no timeout flake. See [validation](validation-1-p-9-fail-safe-i2s-lifecycle.md) for commands, exact sizes/counts/reviews and open physical gate. Software is done-with-deferred-gate; spec/tracker remain in-review/review, not falsely hardware-accepted.
