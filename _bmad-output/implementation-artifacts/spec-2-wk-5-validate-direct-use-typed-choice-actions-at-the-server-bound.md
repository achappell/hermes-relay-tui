---
title: 'Validate direct-use typed-choice actions at the server boundary'
type: 'feature'
created: '2026-10-10'
status: 'in-review'
baseline_commit: 'f620071d31dc180ba4f1f1e3f454aa6030907784'
route: 'dispatch'
review_loop_iteration: 0
source_story: '2-WK-5'
story_key: '2-wk-5-validate-direct-use-typed-choice-actions-at-the-server-bound'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-e-5-render-and-submit-native-choose-explore-actions.md'
  - '{project-root}/_bmad-output/implementation-artifacts/surface-coverage-matrix.md'
  - '{project-root}/shared/display/README.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Home browser appliance hands a typed `choose`/`explore` action to its per-socket context, which checks it against current state before writing to Home. Those checks exist, but a request that fails them is dropped silently, so the page keeps showing "Waiting for Home to update this choice." with nothing to tell the user the request was not accepted. Concurrent, replaced-in-flight, and disconnected-in-flight requests were also never exercised.

**Approach:** Treat the context's `handle_action` as the server boundary for the typed choice. It accepts a request only for the current pending object (action id, object id, freshness), an operation both advertised and offered, and an option the object lists. One request is in flight per socket, and its result is evaluated against the state at completion. A refused request for the current object is surfaced through the existing snapshot path (no new frame type), never resent.

**Success:** Every refusal is either invisible by design (the replacement snapshot already tells the page) or visible as a non-accepted status; nothing is dispatched twice; a stale in-flight request cannot touch a replacement or a closed socket; and the production-unavailable state stays explicit.

## Boundaries & Constraints

**Always:** Use the existing snapshot (`state: "prompt"`, same `prompt`, sequence advance, `status_text`, `prompt.choose`/`prompt.explore` withdrawn from `capabilities`). Leave the published object unchanged on refusal. Preserve the legacy `{action_id, choice}` path and approval/clarify/secret behavior.

**Never:** Add a wire frame type or a shared-contract field; change the production transport default; resend a refused or uncertain action; create a `prompt.submit` or new turn from a choice; let a legacy tap answer a typed choice; claim live support (typed choices are not advertised to a `client_claim` browser until Home and Standard support them).

| Case | Required behavior |
|---|---|
| Current, advertised, listed option | One normalized callback; actions withdrawn; `Choose requested` / `Explore requested` |
| Option not listed, operation unadvertised or not offered, unknown operation | No dispatch; non-accepted snapshot for the current object |
| Stale freshness, other object, unknown action id, legacy tap | No dispatch; no snapshot; the replacement snapshot owns the page |
| Home or session refuses | Non-accepted snapshot; not retried |
| Delivery uncertain (exception) | `… not confirmed` snapshot; not retried |
| Duplicate or concurrent request | One dispatch per socket in flight; later ones dropped |
| Replaced, retired, or disconnected in flight | Result ignored; replacement and closed state untouched |
| `POST /action` in browser-context mode | `200 {}`, no dispatch (pinned) |

</frozen-after-approval>

## Code Map

- `home_display/appliance.py` — `_BrowserSessionContext.handle_action` and its helpers `_publish_typed_choice_outcome`, `_typed_choice_is_current`, `_reject_typed_choice`.
- `puck_bridge/home_session.py` — `send_prompt_response` (unchanged): re-checks the pending Home prompt and typed identity under `_prompt_response_lock`.
- `home_display/server.py` — `_parse_websocket_action` drops malformed typed frames before dispatch; `_handle_action_request` is inert in browser-context mode.
- `home_display/web/src/surfaces/PromptOverlay.svelte`, `App.svelte` — unchanged; the overlay already unmounts when `can_choose` and `can_explore` are both false and the surface shows `status_text`.
- `tests/test_home_appliance.py`, `tests/test_home_display_server.py`, `home_display/web/src/App.test.ts`, `shared/display/README.md`.

## Tasks & Acceptance

**Execution:**
- [x] Boundary tests: valid choose/explore, refused-for-current-object, stale, Home/session refusal, uncertain delivery, concurrent duplicates, replacement in flight, disconnect in flight, post-acceptance requests.
- [x] Fix the defects those tests exposed: concurrent requests each reached the session; an in-flight result overwrote a replacement's snapshot and pending id; a result published into a closed socket.
- [x] Surface a refusal of the current object through the snapshot path; pin that the unchanged web client renders it.
- [x] Pin `POST /action` inertness and document it, and the boundary, in `shared/display/README.md`.
- [ ] Real-Home smoke (B3): a real Home advertises the browser, one `choose` is accepted once, stale and duplicate actions are rejected, production shows no controls when the grant is off. Blocked on Home B1/B2 and a Standard that supports typed choices.

**Acceptance:**
- Every row of the table above is covered by a focused test.
- No refusal path leaves "Waiting for Home to update this choice." with no state change; the page either receives the replacement snapshot or the non-accepted status.
- No refused or uncertain action is resent; no turn or `prompt.submit` is created.
- Typed choices remain unadvertised in production; this story does not claim live support.

## Verification

- `venv/bin/pytest -q tests/test_home_appliance.py tests/test_home_display_server.py`
- `venv/bin/pytest`
- `npm --prefix home_display/web test && npm --prefix home_display/web run check && npm --prefix home_display/web run build`
- Embedded smoke: an `Appliance` with a `HomeBrowserSession` factory behind a real `DisplayServer` and `scripts/fake_home_bridge.py`, driven by a WebSocket client (valid, unlisted option, stale freshness, `--reject-once`, duplicate).

## Status

Software-complete, production-unavailable. Implementation is not closure: per Amanda's 2026-10-09 decision (Q2) the story stays at `review` until the B3 real-Home smoke proves production advertising. A fake-bridge run alone does not close it.

Known gaps, deliberately outside this slice:

- A refused object stays read-only until Home replaces or retires it; there is no in-page retry. A control that re-enables selection needs the 2-WK-6 overlay work.
- Appliance `_on_action` (legacy transport, `POST /action` with an `on_action` callback) keeps its silent drops; it is not the production browser path.
- A frame `_parse_websocket_action` rejects as malformed cannot be correlated to a prompt and so gets no feedback; the shipped client cannot produce one.
