---
title: 'Render typed choice objects with keyboard Choose/Explore actions'
type: 'feature'
created: '2026-09-12'
status: 'done'
baseline_commit: '6cfc7f63f43428322bee1c6e627b62acb090937b'
route: 'dispatch'
review_loop_iteration: 1
source_story: '2-T-3'
story_key: '2-t-3-render-typed-choice-objects-with-keyboard-choose-explore-act'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-hermes-relay-tui-2026-09-08/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-hermes-relay-tui-2026-09-07/EXPERIENCE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The TUI can display a generic numbered structured prompt, but it cannot distinguish inspecting an option from committing it or show those operations in the conversation trail. A person using the terminal therefore cannot complete the approved typed-choice journey with the same deliberate semantics as the other active surfaces.

**Approach:** Extend the existing normalized structured-prompt path into a bounded Interactive Choice Object projection. The TUI will show Hermes' explanation, the active Profile, every option, and native keyboard actions; it will send one session-bound `choose` or `explore` operation through the existing single-reader SessionProtocol and record each successfully written action request once.

**Decisions:** Reuse the existing normalized `prompt_request`/`prompt_response` path with bounded choice context and an explicit operation field; do not introduce a parallel choice wire event. A choice is identified by `prompt_kind: "choice"` and carries a `choice` object with a bounded `object_id`, an `operations` list containing only `choose` and/or `explore`, and an opaque non-empty `freshness` token. A choice response carries the selected `operation`, `object_id`, and `freshness`; legacy prompt responses do not carry those fields. Move option focus with `Up`/`Down` using clamped bounds and retain the existing number-key shortcuts; `Enter` chooses and `Right Arrow` explores.

## Boundaries & Constraints

**Always:** Hermes remains the answer and choice authority; the TUI renders bounded data rather than arbitrary UI. Choice actions are bound to the current Session, turn, object, option, advertised operation, and freshness context. The local `choose`/`explore` operation must also be supported by the TUI capability set (`prompt.choose`/`prompt.explore`). `choose` commits one option; `explore` requests detail without committing. Only one response may be in flight. A successful session-port write produces one visible action-request line before the current object advances or resolves; a later Hermes rejection updates that request's status and never triggers a replay or local consequence. Existing free-text, masked prompts, numeric shortcuts, profile identity, generation guards, and the single WebSocket reader remain intact.

**Never:** Add a second Hermes reader, invent a local answer or consequence, replay an uncertain action, expose choice controls for passive/Puck surfaces, or broaden this story into consequence-bearing confirmation policy. A locally rejected, stale, expired, replaced, unsupported, or duplicate action must not be written or create a new transcript action. If Hermes rejects a request after the write, the already-visible request is marked rejected once; the TUI must not add another line, resolve or replace the object locally, or retry it automatically.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| CHOICE_READY | Current normalized `prompt_request` has `prompt_kind: "choice"`, a bounded `choice` object, and at least one valid option | Existing connection status shows `Profile: <active profile>`; the panel shows Hermes' explanation, every option, the focused option, and an affordance for each operation advertised by the choice and supported by the TUI | Malformed choice data, an empty/invalid operation list, or an invalid freshness token is rejected without replacing the last safe state |
| CHOOSE | `Enter` on the focused option while `choose` is advertised and no response is pending | One response containing `operation: "choose"`, the current `object_id`, option ID, and `freshness` is written; `Choose requested: <label>` appears once after the write succeeds; the object waits for Hermes | A failed write releases the retry gate and creates no request line |
| EXPLORE | `Right Arrow` on the focused option while `explore` is advertised and no response is pending | One response containing `operation: "explore"`, the current `object_id`, option ID, and `freshness` is written; `Explore requested: <label>` appears once after the write succeeds; the object remains unresolved until Hermes sends the next state | An unsupported operation is rejected without changing the object or creating a request line |
| HERMES_REJECTS | Hermes later emits `prompt_response_rejected` for the written request as stale, expired, replaced, duplicate, or otherwise invalid | No replay, local consequence, or second transcript line; the existing request is marked rejected once and the current object changes only if Hermes separately sends a replacement or resolution | The rejection is retryable only when the current object remains valid and the app has cleared the in-flight gate |
| STALE_OR_DUPLICATE_LOCAL | Old session/turn/object/freshness context, unsupported operation, or response already pending | No response or new transcript action; the current choice remains visible | Show a safe rejection/status without mutating the current object |
| LEGACY_PROMPT | Existing approval, clarify, masked, numeric, or free-text prompt without `prompt_kind: "choice"` and `choice` context | Existing numeric and free-text behavior remains unchanged; no choice-only operation is offered or added to the payload | Legacy prompt behavior and payload shape remain compatible |

</frozen-after-approval>

## Code Map

- `domain.py` — extend `TUI_CAPABILITIES`, `PromptState`, and `PromptAction` validation with bounded choice identity, operation, capability, freshness, and single-shot rejection without importing Textual.
- `client.py` — preserve the existing normalized event boundary, normalize only the exact choice context, and carry the selected operation/context through the bounded prompt-response payload while preserving legacy fields.
- `session.py` — expose operation, object identity, and freshness through `SessionProtocol` and `HermesSession` without creating another receive owner.
- `prompts.py` — model clamped focused-option state and render the bounded explanation, options, supported action affordances, pending state, and rejection state.
- `app.py` — handle choice-only focus/action keys, refresh the prompt panel, enforce current session/turn/generation guards, append one successful-write request line, and mark later Hermes rejection without replay.
- `tests/test_tui_domain.py`, `tests/test_client.py`, `tests/test_session.py`, and `tests/test_app.py` — cover the exact normalized/response shape, capability/freshness/rejection policy, key semantics, transcript visibility, duplicate suppression, legacy prompts, and the existing full turn path.

## Tasks & Acceptance

**Execution:**
- [x] `domain.py` — add the bounded choice context and validated `choose`/`explore` action model; add `prompt.explore`; keep stale, unsupported, and duplicate actions side-effect free.
- [x] `client.py` and `session.py` — normalize the exact choice context and send one operation through the existing prompt-response port; include choice fields only for `prompt_kind: "choice"`, preserve legacy payloads, and retain single-reader ownership.
- [x] `prompts.py` — add clamped focused-option state and readable Choose/Explore rendering; keep free-text and masked prompt presentation intact.
- [x] `app.py` — route `Up`/`Down`, `Enter`, and `Right Arrow` only while a non-pending choice owns focus; retain number shortcuts, ordinary cursor/history behavior, session guards, pending state, and the connection-header Profile identity.
- [x] `tests/test_tui_domain.py`, `tests/test_client.py`, `tests/test_session.py`, and `tests/test_app.py` — exercise the matrix and regression paths before the complete suite, including write failure, late Hermes rejection, replacement, and no-replay behavior.

**Acceptance Criteria:**
- Given a normalized choice object with `prompt_kind: "choice"`, a valid `object_id`, `operations`, `freshness`, and options, when the TUI renders it, then the active Profile is visible in the existing connection header, Hermes' explanation and every option are visible, focus is visible, and each advertised operation supported by the TUI has a visible affordance.
- Given a focused option and no pending response, when `Enter` is pressed, then exactly one current-session `choose` response containing the current object identity and freshness is written, and `Choose requested: <label>` appears once after the write succeeds and before Hermes resolves or replaces the object.
- Given a focused option and no pending response, when `Right Arrow` is pressed, then exactly one current-session `explore` response containing the current object identity and freshness is written, `Explore requested: <label>` appears once after the write succeeds, and the choice remains unresolved until Hermes sends the next state.
- Given a stale, unsupported, expired, replaced, or duplicate action before it is written, when the domain or session boundary evaluates it, then no response is sent and no new transcript action is created; the current object remains unchanged.
- Given Hermes rejects a previously written request, when `prompt_response_rejected` arrives, then the existing request is marked rejected once, no replay or second action line occurs, no local consequence is taken, and only a Hermes replacement/resolution may change the current object.
- Given an existing approval, clarify, or masked prompt, when it is used, then its current numeric/free-text behavior and single-reader lifecycle remain unchanged.
- Given `Up`/`Down`, `Enter`, or `Right Arrow` is used without an active non-pending choice, when the key is handled, then ordinary composer cursor/history/submission behavior remains unchanged; number shortcuts continue to reach options beyond the first nine through focus.
- Given the focused and complete test suites run, when they finish, then all new choice tests and the existing baseline pass without a core module importing Textual.

## Implementation Notes

The exact normalized choice projection is:

```json
{
  "type": "prompt_request",
  "prompt_kind": "choice",
  "prompt_id": "prompt-123",
  "turn_id": "turn-123",
  "session_id": "session-123",
  "text": "What should Hermes do?",
  "options": [
    {"id": "inspect", "label": "Inspect it"},
    {"id": "commit", "label": "Commit it"}
  ],
  "choice": {
    "object_id": "choice-123",
    "operations": ["choose", "explore"],
    "freshness": "opaque-server-version"
  }
}
```

`object_id` and `freshness` are non-empty strings bounded to 64 characters; `operations` is a unique, non-empty list containing only `choose` and `explore`; choice options retain the existing option-ID limit and are capped at 32 entries with labels bounded to 256 characters. The client normalizes these fields and drops unrelated future fields. A choice response adds `operation`, `object_id`, and `freshness` to the existing `prompt_response` payload; approval, clarify, masked, numeric, and free-text responses retain their current shape and omit all three fields.

The choice response shape is:

```json
{
  "type": "prompt_response",
  "protocol_version": 1,
  "prompt_id": "prompt-123",
  "prompt_kind": "choice",
  "session_id": "session-123",
  "option_id": "inspect",
  "operation": "explore",
  "object_id": "choice-123",
  "freshness": "opaque-server-version"
}
```

The per-choice `operations` list is Hermes' advertised capability for that object. The TUI maps `choose` to `prompt.choose` and `explore` to `prompt.explore`, and renders or sends an operation only when both the object and local capability allow it. The opaque freshness token is echoed unchanged. Hermes remains authoritative for expiration, replacement, duplicate detection, and stale-session decisions; the TUI does not invent a wall-clock expiry or replay an action after an uncertain write.

`HermesSession.send_prompt_response()` returning successfully means that the current session port accepted the WebSocket write, not that Hermes has accepted the choice. The app therefore uses `Choose requested: <label>` or `Explore requested: <label>` as the honest local trail entry. A later `prompt_response_rejected` marks that request rejected once. The current object is resolved or replaced only by the corresponding Hermes event.

Choice-only key routing is scoped to the active prompt panel: `Up`/`Down` move a clamped focus index, `Enter` sends `choose`, and `Right Arrow` sends `explore`. When no choice is active or a response is pending, those keys retain their existing composer behavior; number keys remain a shortcut for options 1–9. Options beyond nine are reached with focus rather than by inventing multi-digit submission syntax.

## Spec Change Log

- 2026-09-12, review loop 1 — Pinned the normalized choice and response fields, preserved the legacy prompt payload, made Profile visibility rely on the existing connection header, scoped and clamped keyboard focus, added the session test seam, and resolved transcript wording around local write success versus later Hermes rejection.

## Review Triage Log

- Resolved — “accepted action” now means a successfully written action request; a later Hermes rejection marks that request without replay or a second transcript line.
- Resolved — choice identity, operation names, freshness handling, capability mapping, bounds, and legacy fallback are explicit in the implementation notes.

## Design Notes

The terminal keeps selection separate from the text composer: option focus is visible in the prompt panel, `Enter` commits it, and `Right Arrow` explores it. The action line is produced only after the session port accepts the write, so a network failure does not turn an attempted choice into a false user decision.

## Verification

**Commands:**
- `venv/bin/pytest -q tests/test_tui_domain.py tests/test_client.py tests/test_session.py tests/test_app.py` — expected: focused choice and regression tests pass.
- `venv/bin/pytest` — expected: complete repository suite passes.
- `git diff --check` — expected: no whitespace errors.
