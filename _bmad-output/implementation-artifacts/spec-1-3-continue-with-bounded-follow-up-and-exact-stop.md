---
title: 'Continue with bounded follow-up and exact stop'
type: 'feature'
created: '2026-09-09'
status: 'done'
route: 'dispatch'
review_loop_iteration: 1
baseline_commit: '164500d11922278a81466cf70dce351d4cfce65a'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-hermes-relay-tui-2026-09-08/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-hermes-relay-tui-2026-09-07/EXPERIENCE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The shared hands-free path already supports one bounded follow-up and
local `stop`, but the TUI wake adapter does not report whether its relay turn
actually completed. A failed or ambiguous response can therefore open a second
capture window, making an unsuccessful turn look ready for conversation.

**Approach:** Make the TUI wake sender return the outcome of the existing turn
worker, so the shared coordinator opens follow-up only after a completed response.
Retain the existing single-flight capture, selected session/profile, timeout,
local-stop, cancellation, and wake-listener ownership rules across the TUI and
appliance paths.

## Boundaries & Constraints

**Always:** Follow-up uses the configured `wake_followup_seconds` value (8 seconds
by default), requires no second wake phrase, and submits at most one non-empty
follow-up through the same session. Standalone `stop` is consumed locally during
initial or follow-up capture after trimming case and normal terminal punctuation;
it produces no turn, response, or capture-complete acknowledgement. Empty capture,
expiry, cancellation, interruption, connection loss, and an unsuccessful initial
turn return to wake/idle without inviting another turn. Blocking capture and
turn work remain off the Textual event loop, and uncertain relay requests are
never replayed.

**Never:** Change the Hermes wire protocol, invent a local response, reopen a
microphone after disarm/recovery, add a second follow-up window, or change
ordinary `Ctrl+R` voice-turn semantics. Firmware wake-word detection, profile
enrollment, and new audio hardware behavior are outside this slice.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|-----------------------------|----------------|
| SUCCESS | Wake turn completes; follow-up is non-empty | One bounded follow-up is captured and sent through the same session; listening then returns to wake detection | No third capture |
| FAILED_INITIAL | Initial wake turn errors, is interrupted, or becomes disconnected | No follow-up capture; existing error/disconnected state remains authoritative | Do not replay or claim completion |
| LOCAL_STOP | Initial or follow-up transcript is standalone `stop` with normal punctuation | Capture closes silently; no Hermes turn or capture-complete cue | Resume wake/idle locally |
| EMPTY_WINDOW | Follow-up expires or transcribes empty/whitespace text | No follow-up turn; prior response remains intact and listening closes | No error or empty submission |
| ORDINARY_TEXT | Follow-up contains more than `stop`, or `Ctrl+R` captures `stop` | Ordinary turn path is used | Preserve existing input behavior |

</frozen-after-approval>

## Code Map

- `handsfree.py` -- owns single-flight wake orchestration, the one optional follow-up, bounded capture deadlines, and standalone-stop normalization. Reuse its existing coordinator and send-result gate; do not add UI or transport parsing.
- `app.py` -- `_send_wake_turn`, `_capture_wake_voice`, `_capture_wake_follow_up`, and `_wake_state_changed` adapt the TUI to the coordinator. The wake sender must report completed versus failed turn work while remaining synchronous to the listener worker.
- `home_display/appliance.py` -- `_capture_follow_up`, `_send`, and `_build` are the appliance reference path. Preserve its existing same-session, playback-drained, failure, and shutdown behavior unless a regression is exposed.
- `tests/test_handsfree.py` -- existing coverage proves one follow-up, timeout selection, empty capture, punctuation-tolerant stop, and unsuccessful-send suppression.
- `tests/test_app_wake.py` -- existing TUI success/stop/cancellation coverage; add the missing failed-response case proving no follow-up capture is opened.
- `tests/test_home_appliance.py` -- existing appliance coverage proves success, silence, stop, failed turns, capture failure, and shutdown. Use it as regression evidence rather than duplicating the path.

## Tasks & Acceptance

**Execution:**
- [x] `app.py` -- return a boolean from `_send_wake_turn` based on the current wake turn's completion status -- prevent failed or ambiguous TUI responses from opening follow-up.
- [x] `tests/test_app_wake.py` -- add a fake failed-response wake scenario -- prove no second capture, no second turn, and honest disarm/error behavior.
- [x] `tests/test_handsfree.py` -- preserve and, if needed, tighten the coordinator outcome tests -- prove a false send result never opens follow-up while successful sends remain one-follow-up-only.

**Acceptance Criteria:**
- Given a wake-triggered response completes successfully, when the coordinator receives the sender outcome, then it opens exactly one configured follow-up window and submits at most one non-empty follow-up to the same session.
- Given the initial wake response errors, is interrupted, times out, or loses its connection, when the sender returns, then no follow-up capture starts and the existing failure/recovery state remains visible.
- Given initial or follow-up transcription is standalone `stop` after normal punctuation is ignored, when capture completes, then no Hermes turn or capture-complete acknowledgement is emitted and wake listening can resume.
- Given follow-up capture expires, is empty, or is cancelled, when the window closes, then no empty turn is sent and the prior response is not replaced.
- Given a longer phrase contains `stop`, or `Ctrl+R` captures `stop`, when it is submitted, then it remains ordinary user content.

## Implementation Notes

- 2026-09-09: `_send_wake_turn` now returns `True` only when the existing
  `_run_turn` completes with `PROMPT_COMPLETED`; a missing wake loop and
  ambiguous or unsent outcomes return `False`. This feeds the coordinator's
  existing follow-up gate without changing the Hermes wire protocol or adding
  replay behavior.
- 2026-09-09: Added TUI regression coverage for a failed streamed response:
  the initial turn is recorded once, the wake listener disarms through the
  existing connection-loss path, and no follow-up capture or second turn is
  opened. Existing coordinator tests already cover the false-send gate,
  successful one-follow-up path, stop normalization, empty capture, timeout,
  and ordinary longer phrases, so `handsfree.py` required no code change.
- 2026-09-09 review repair: `_run_turn` now returns the initiating prompt's
  completion outcome before draining queued prompts, and `_consume_turn`
  requires a clean `turn_end`; protocol errors, interruptions, and streams
  that end without completion remain ambiguous and cannot invite follow-up.
  Added TUI coverage for protocol error, timeout, cancellation, and queued
  prompt interleaving. The coordinator and appliance contracts remain
  unchanged.
- 2026-09-09: Focused verification passed before review repair: 206 tests in
  9.51 seconds. The four new review-path tests pass after repair; the full
  suite is rerun below before handoff.

## Review Triage Log

- `medium / patch` — blind-hunter: `_send_wake_turn` read mutable `_last_prompt_status`; `_run_turn` now returns the initiating turn's result before queued prompts can overwrite it.
- `medium / patch` — edge-case-hunter: the same queued-prompt outcome race was independently reported and is covered by the interleaving regression test.
- `medium / patch` — verification-gap: timeout and cancellation lacked adapter-level no-follow-up assertions; targeted tests now cover timeout and cancellation, alongside the existing connection failure case.
- `medium / patch` — verification-gap: protocol `error` and `turn_interrupted` streams were classified as completed; `_consume_turn` now returns success only for a clean `turn_end`, with regression coverage for protocol error.
- `high / defer` — verification-gap: automatic raw PCM capture in the dirty reSpeaker firmware emits household audio to serial logs; verified in the pre-existing firmware diff and recorded in `deferred-work.md`, outside this TUI story.
- `medium / defer` — blind-hunter: the firmware amplitude/PCM diagnostic samples pre-processed input rather than the wake model's post-processing path; this is pre-existing hardware diagnostic work and is deferred.
- `medium / defer` — blind-hunter: the dirty firmware leaves `stop_after_detection` at its component default; this concerns the older on-device wake-word story and is deferred.
- `medium / defer` — blind-hunter: the vendored microphone FIR assumes stereo 32-bit frames although the component schema exposes other formats; pre-existing firmware scope, deferred.
- `medium / defer` — blind-hunter: the vendored microphone path assumes 48 kHz input and a factor-three decimation while its schema accepts other rates; pre-existing firmware scope, deferred.
- `low / defer` — blind-hunter: the dirty component exposes an internal ADC configuration that final validation rejects; pre-existing firmware scope, deferred.
- `medium / defer` — blind-hunter: the vendored microphone's `rx_handle_` is not explicitly initialized before failure cleanup; pre-existing firmware lifecycle work, deferred.
- `medium / defer` — blind-hunter: the dirty PCM capture flags are shared between callback and interval contexts without synchronization; pre-existing diagnostic work, deferred.
- `medium / defer` — blind-hunter: the dirty SPDIF setup continues after a preload failure; pre-existing firmware output handling, deferred.
- `medium / defer` — blind-hunter: the dirty SPDIF write callback does not reject partial writes; pre-existing firmware output handling, deferred.
- `low / defer` — blind-hunter: a generated story index omits the older firmware story; historical BMad index reconciliation is deferred.
- `medium / defer` — blind-hunter: the older firmware story remains marked done despite unresolved detection notes; historical story-status reconciliation is deferred.
- `medium / defer` — blind-hunter: the aggregate dirty diff contains firmware changes explicitly outside this frozen TUI intent; those changes are pre-existing and deferred rather than folded into Story 1.3.
- `low / defer` — blind-hunter: local-vendored firmware provenance/license documentation needs reconciliation; pre-existing hardware documentation, deferred.
- `low / patch` — blind-hunter: the story record did not yet contain the actual full-suite evidence; this log and the verification notes are being completed as part of this review.
- `low / defer` — blind-hunter: the dirty FIR coefficients have no checked-in generator or host-side DSP fixture; pre-existing firmware verification, deferred.
- `medium / defer` — edge-case-hunter: unsupported microphone format combinations can be mis-framed by the dirty FIR path; this is the same pre-existing firmware format boundary as the two microphone-schema findings above.
- `low / defer` — edge-case-hunter: signed byte shifts in the dirty firmware conversion code can overflow on negative PCM samples; pre-existing firmware arithmetic, deferred.
- `low / defer` — edge-case-hunter: the dirty YAML amplitude diagnostic can overflow while taking absolute values of signed samples; pre-existing firmware diagnostics, deferred.
- `medium / defer` — edge-case-hunter: dirty PCM capture publication lacks a synchronization boundary; this is the same pre-existing diagnostic race recorded above.
- `medium / defer` — edge-case-hunter: optional dirty I2S clock-pin configuration is not validated before pin construction; pre-existing firmware configuration, deferred.
- `medium / defer` — edge-case-hunter: dirty standard-speaker callback registration failures are not handled; pre-existing firmware output handling, deferred.
- `medium / defer` — edge-case-hunter: dirty SPDIF preload short/error handling can leave setup partially initialized; same pre-existing firmware output root cause as the preload finding above.
- `medium / defer` — edge-case-hunter: dirty SPDIF callback registration and channel-enable failures are ignored; pre-existing firmware output handling, deferred.

### Review Findings

No decision-needed findings remain after triage.

#### Patch findings

- [x] [Review][Patch] Snapshot the initiating wake outcome before queued submissions can overwrite it [app.py:3366-3368; tests/test_app_wake.py:786-830] — `_run_single_turn` now returns the local turn status captured before awaited cleanup, so a prompt queued during cleanup cannot suppress the initiating wake turn's one follow-up window.
- [x] [Review][Patch] Complete adapter-level fail-closed wake coverage for interruption and clean stream EOF [app.py:4052-4202; tests/test_app_wake.py:678-710] — adapter tests now prove `audio_abort`/`turn_interrupted` and a stream without `turn_end` each produce one capture, one relay turn, no follow-up capture, and preserve the expected error/interrupted state; protocol-error assertions cover the same state boundary.
- [x] [Review][Patch] Lock the missing wake-loop handoff to an unsuccessful send [app.py:1914-1927; tests/test_app_wake.py:619-710] — the teardown case now proves a listener reaching delivery after `_wake_loop` is cleared cannot open a follow-up window.

#### Review repair

- 2026-09-10: `_run_single_turn` now returns both its sent/not-sent decision and a prompt outcome captured before awaited cleanup; `_run_turn` uses that immutable per-call outcome for the initiating wake sender. The wake state projection also preserves `error` and `interrupted` after a failed wake turn while allowing local capture cancellation to return to `ready`.
- 2026-09-10: Added adapter-level coverage for protocol error state, remote interruption with `audio_abort`, clean stream EOF, wake-loop teardown, and queue submission during turn cleanup.

#### Deferred findings

- [x] [Review][Defer] Wake-listener shutdown can join on the Textual event loop during connection recovery [app.py:3495-3507; wake.py:440-445] — deferred: this is a pre-existing lifecycle concern requiring a separate non-blocking listener-stop design, outside the frozen follow-up slice.
- [x] [Review][Defer] Pre-existing reSpeaker diagnostic, format, lifecycle, output, and provenance findings remain outside the TUI slice [firmware/respeaker-lite/respeaker-lite.yaml:38-40; _bmad-output/implementation-artifacts/deferred-work.md:3-17] — deferred: the existing deferred-work entries already record the firmware guard and verification work; none of it is part of Story 1.3.

#### Rejected

- `false` — The claim that a stream without `turn_end` strands the active turn is refuted by `app.py:4191-4202` and `app.py:3382-3389`: EOF is converted to an error, the domain turn closes, and the outer turn finally clears `_turn_in_flight`; the remaining issue is coverage, recorded above.
- `false` — Non-stale domain event rejection already fails closed at `app.py:3818-3847`, appending an error and returning before a later `turn_end` can invite follow-up.
- `false` — Normalized `connection_lost`/`disconnected` events already take the recovery path at `app.py:3848-3852`; the current implementation disarms wake mode and closes the session.
- `false` — Draining independent prompts after an ambiguous turn is the existing FIFO queue policy at `app.py:3369-3381`; it does not replay the uncertain prompt or act as the hands-free follow-up gate.
- `false` — The broad `send` annotation in `handsfree.py:306-331` is not an observed TUI defect: both TUI and appliance adapters return booleans, and the coordinator deliberately treats only literal `False` as delivery failure.
- `low` — Requiring IDs, owners, statuses, and exit criteria for every prose entry in `deferred-work.md` has no repository contract and would be process polish rather than a Story 1.3 correction.
- `workflow` — `review_loop_iteration: 0` and the pre-review story status are workflow metadata; the review workflow updates them when disposition and status synchronization complete, rather than changing frozen story intent as a code patch.
- `environment` — Live wake smoke was not run because this worktree has no configured Hermes endpoint or bearer token; the limitation is already recorded in Verification and is not a code defect.
- `scope` — The commit-claims observation about an unrelated repository-boundary description is not a defect in the reviewed TUI implementation or acceptance behaviour.

#### Review execution

- 2026-09-10: The blind-hunter, edge-case-hunter, verification-gap, and acceptance-auditor passes timed out before returning reports. No automated reviewer findings were collected; the local focused and full-suite gates passed, and this limitation remains explicit rather than being presented as a clean adversarial review.

## Verification

**Commands:**
- `venv/bin/pytest -q tests/test_app.py tests/test_app_wake.py tests/test_handsfree.py` -- passed: 283 tests in 47.30 seconds.
- `venv/bin/pytest` -- passed: 935 tests in 71.80 seconds, with one pre-existing `websockets.legacy` deprecation warning.
- `git diff --check` -- passed with no whitespace errors.

**Manual checks (if no CLI):**
- Run the existing TUI wake smoke against a configured endpoint: wake once, receive a successful answer, speak one follow-up, then confirm silence/standalone `stop` returns to wake listening without a third capture. Confirm a failed response does not open follow-up.
- Live endpoint smoke was not run in this environment; no configured Hermes endpoint or bearer token was used. The fake-session integration tests cover the success, stop, empty, timeout, cancellation, protocol-error, and failed-response paths without replaying an uncertain turn.
