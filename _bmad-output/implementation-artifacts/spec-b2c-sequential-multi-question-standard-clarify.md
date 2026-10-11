---
title: 'Sequential multi-question Standard clarify in the browser'
type: 'feature'
created: '2026-10-10'
status: 'done'
baseline_commit: '1f273067916b3e31c508f8fa326babc0ea1fbcaa'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-wk-5-validate-direct-use-typed-choice-actions-at-the-server-bound.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The browser currently rejects every multi-question Standard `clarify.request`, although it can collect a single-select question with listed choices. This prevents an otherwise supported Standard batch from completing in the browser.

**Approach:** For a batch whose questions are all valid single-select questions with choices, show and answer one question at a time, carrying that question's `question_id`; advance only when Home explicitly reports the expected remaining qids. Preserve the existing visible unsupported error for multi-select, free-text, and unknown shapes.

## Boundaries & Constraints

**Always:** Never replay an answered or uncertain question; dispatch at most one answer per qid. Evaluate late results against the currently pending prompt and connection before publishing or advancing. A rejected answer remains visibly not accepted and cannot be retried automatically; malformed or unexpected `remaining` is a protocol failure and must not prompt another question.

**Never:** Change approval, secret, sudo, typed-choice, legacy clarify, Puck, Textual TUI, or web UI behavior. Do not add multi-select or free-text input.

**Decisions (provisional, 2026-10-10):** The owner has not confirmed these; the director recommends yes and the owner corrects afterward. (1) Unexpected or divergent `remaining` closes the session without replay and nothing further is sent. (2) A rejected answer is never retried; because Home keeps the batch pending after a refusal, the turn is interrupted with a visible error rather than left waiting.

</frozen-after-approval>

## Code Map

- `puck_bridge/home_session.py` — `_clarify_sequence` and `_standard_clarify(sequential=)` admit a batch; `send_prompt_response`, `_reject_clarify_answer`, `_finish_clarify_answer`, `take_clarify_outcome` run it; `HomeBrowserSession` is the only opt-in (`_sequential_clarify`), the Puck base class is unchanged.
- `home_display/home_admission.py` — `BrowserSession.take_clarify_outcome` forwards to the claim's bridge.
- `home_display/appliance.py` — `_sequence_is_renderable` (admission), `_BrowserSessionContext.handle_action` and `_continue_clarify_sequence` (evaluate against current state, publish next / idle / stop), the turn loop's `stopped_status` keeps the rejection message.
- `home_display/web/src/App.svelte` — unchanged; it keys the overlay on the prompt JSON, so a new question under the same `action_id` remounts.
- `tests/test_home_clarify_browser.py`, `tests/test_browser_home_admission.py`.

## Tasks & Acceptance

**Execution:**
- [x] `puck_bridge/home_session.py` — browser-only sequence with position-namespaced option ids, dispatched-qid tracking, exact `remaining` check, advance only if the pending prompt is unchanged and connected, one-shot outcome handoff.
- [x] `home_display/home_admission.py` — forward `take_clarify_outcome`.
- [x] `home_display/appliance.py` — upfront renderability check, outcome handling against current state, rejection interrupt with a retained message.
- [x] `tests/test_home_clarify_browser.py`, `tests/test_browser_home_admission.py`, `CHANGELOG.md`, `README.md`.

**Acceptance Criteria:**
- Given a 2- or 3-question single-select batch, when each page answer is accepted with the exact `remaining`, then each `prompt.respond` carries that question's text choice and `question_id`, exactly once, in order, and the page ends idle.
- Given a stale or repeated tap for an answered question (including the first question's option id while question 2 is pending), when it arrives, then nothing is dispatched.
- Given Home replaces or resolves the prompt, or the connection drops, while an answer is in flight, then the late result publishes nothing and advances nothing.
- Given Home rejects an answer, then the page shows "Home did not accept that answer, so the question was cancelled", the turn is interrupted, no retry is sent, and the next question is not shown.
- Given `remaining` is missing before the last question, or is extra, reordered, malformed, or non-empty after the last question, then the session closes, nothing more is sent, and no next question is shown. An absent `remaining` on the last answer means nothing remains, as Home itself reads it.
- Given multi-select, free-text, malformed, duplicate-qid, or an unrenderable step in a multi-question batch, then the existing visible unsupported error and interrupt occur with no answer sent. Single-question, legacy, approval, and Puck behavior is unchanged.

## Implementation Notes

Rendered `bmad-build` workflow followed; the step-02 owner checkpoint was replaced by the director's review of the draft spec (owner-authorized), and the director added one condition: a rejected answer must not leave the page waiting indefinitely.

**Rejection decision.** Home's `_prompt_respond` (hermes-relay-home `endpoint.py`) returns a rejection without removing the pending prompt (it pops it only when `remaining` is empty), keeps sending `awaiting_input` keep-alives for it, and has no timeout of its own; the only end besides an answer is a Standard `clarify.expire` event (not verified here). So Home's own timeout cannot be relied on, and the page would hang. Chosen: the existing visible-error + `session.interrupt` path (as #241 does for unsupported prompts). The appliance sets an error snapshot with the rejection message, interrupts the turn, and the turn loop keeps that message however the turn then ends (interrupted, failed, or completed). If the interrupt is unavailable, refused, or fails, the appliance closes that browser connection instead (the page reconnects); the answered qid is never sent again either way. The session only records the refusal and marks the qid dispatched.

**Other choices.** Question text is prefixed `(n/total)`. Admission also requires unique qids and that every step classifies, so a later unrenderable question is refused before any answer. Single-question batches keep today's path, including ignoring `remaining` (pinned by test). Admitted limits are the appliance's (8 options, 256 characters); the shipped page parser is stricter (4 options, 48-character labels, 192-character body), an existing gap that also affects single questions and is not changed here.

## Spec Change Log

## Review Triage Log

Layers run: blind, edge-case, verification-gap (3 context-free reviewers).

| Finding | Verdict | Evidence / route |
|---|---|---|
| Turn can hang if the rejection interrupt returns False or raises (blind, edge, gap) | medium, patch | `interrupt()` result was ignored. Now falls back to closing the connection; test added. |
| Without interrupt support the rejection message is never shown (blind) | medium, patch | The session closed and cleared its outcome before the appliance read it. The session no longer closes or raises; the appliance owns the stop. |
| Rejection judged and session closed for a stale (replaced/resolved) prompt (blind, edge) | medium, patch | Same root cause as above; the session close was the only effect and is removed. |
| Stale accepted result could publish idle as if the batch finished (blind) | medium, patch | Outcome now carries `final`; idle only when `final`, otherwise nothing is shown. |
| Unrelated status update clears the overlay, so the next question is lost (edge) | medium, patch | Currency is now the batch's action id, not snapshot equality; test added. |
| Missing `remaining` on the last answer accepted (blind, edge) | false | Home's `_has_remaining_prompt_questions` and endpoint read an absent key as nothing remaining; requiring it risks real completion. AC wording clarified; test pins it. Missing before the last question is still refused. |
| Rejection status not cleared per turn; `error`/`turn_end` endings unpinned (gap) | medium, patch | Parametrized over interrupted/failed/completed plus a second clean turn; mutation of the reset fails the tests. |
| `abort_audio("unsupported prompt")` reason on rejection; `stopped` unused in the `error` branch; status literal not using the new constant (blind) | low, patch | Reason now says "answer rejected"; the two literals use `UNSUPPORTED_PROMPT_STATUS`. The `error` branch deliberately keeps Home's error text for the unsupported case. |

## Design Notes

The action id stays Home's correlation id; per-question binding comes from the option ids (`"2.1"`), which the snapshot check and the session's pending option set both enforce, so a double tap on question 1 cannot answer question 2. Home keeps the prompt pending until `remaining` is empty and resolves it after the last answer; the client never re-sends. A divergent `remaining` is judged only while the answered prompt is still the pending one; a replaced or resolved prompt is neither advanced nor judged. When the connection is lost the browser socket closes, which is how the page learns of it.

## Verification

**Commands:**
- `venv/bin/pytest tests/test_home_clarify_browser.py tests/test_browser_home_admission.py tests/test_home_appliance.py tests/test_puck_home_session.py` -- expected: pass
- `venv/bin/pytest` -- expected: ≥2149 passed, 3 skipped (rerun `tests/test_app.py::test_app_unmount_does_not_wait_past_shutdown_task_budget` alone if it flakes)

**Manual checks:**
- Embedded-Appliance smoke (real `DisplayServer`, WebSocket client, `HomeBrowserSession` over a fake Home socket): 3-question walk, rejection at question 2, divergent `remaining`.
