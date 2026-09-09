---
title: 'UI-CORE-06 Adapt the TUI to the shared domain contract'
type: 'feature'
created: '2026-09-08'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '1ebacd1'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-hermes-relay-tui-2026-09-08/ARCHITECTURE-SPINE.md'
  - '{project-root}/shared/display/README.md'
---

## Intent

**Problem:** `app.py` currently owns protocol-event interpretation, turn-phase transitions, structured-prompt state, and busy-mode decisions beside the Textual presentation. That makes the terminal doorway a second policy implementation and leaves it able to drift from the shared Hermes/display semantics.

**Approach:** Introduce a UI-free TUI domain adapter that consumes normalized `SessionProtocol` events plus local capture/playback milestones and returns typed state/effects. Route the TUI through that adapter while leaving transcript layout, wording, keyboard bindings, audio I/O, and local history at the terminal boundary.

## Boundaries & Constraints

**Always:** Preserve Hermes wire event names and the single-reader `SessionProtocol` boundary. Use the existing shared display fixtures and action rules as the compatibility reference. Keep TUI-only capabilities explicit, including richer `transcribing`/`complete` labels, free-text or masked prompt entry, queue/steer/interrupt controls, and diagnostic detail. Rejected or stale actions must not mutate state or write to the session.

**Never:** Import Textual, `app.py`, `home_display/`, browser code, or firmware into the domain adapter. Do not add a second Hermes protocol, display transport, transcript store, automatic replay, or invented fallback response. Do not expand the version-1 display schema merely to accommodate terminal-only phase labels; project those labels explicitly at the TUI boundary.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Normal voice turn | capture → transcription → normalized response/audio events → `turn_end` | States advance through the canonical phases without claiming completion before playback/turn completion; streamed text remains one assistant response | Invalid or incomplete milestones leave the last safe state and expose a typed failure |
| Structured prompt | `prompt_request`, then a valid or invalid option/free-text answer | Prompt state advertises only supported TUI capabilities; one valid answer produces one session response action | Invalid, duplicate, rejected, or unsupported answers produce no second write and retain retryable prompt state |
| Busy submission | Active turn plus `queue`, `steer`, or `interrupt` mode | Pure decision returns the selected action; queue preserves FIFO, steer replaces only after interruption, interrupt does not create a replacement | Missing session capability or failed interruption becomes an explicit error/disconnected outcome |
| Recovery | Active turn followed by transport loss and reconnect | Domain returns to disconnected/ready semantics and requires fresh explicit initiation | The ambiguous turn is never replayed; late events cannot mutate the new turn |

## Code Map

- `client.py` -- normalizes Hermes frames into the event stream the adapter consumes.
- `session.py` -- owns the session port, prompt writes, interruption, and connection facts.
- `app.py` -- remains the Textual shell, audio coordinator, transcript renderer, and command/key-binding owner; its policy decisions move behind the adapter.
- `prompts.py` -- retains terminal prompt rendering while sharing validated prompt/action semantics.
- `AGENTS.md`, `tests/test_core_boundary.py`, and `pyproject.toml` -- document, enforce, and package the new UI-free domain module.
- `shared/display/display_snapshot.schema.json`, `shared/display/display_action.schema.json`, and `shared/display/fixtures/` -- cross-target compatibility and conformance reference.
- `domain.py` -- new framework-independent turn state, prompt/action validation, capability declaration, and busy decision boundary.
- `tests/test_tui_domain.py`, `tests/test_app.py`, and display conformance tests -- fake-session replay and regression evidence.

## Tasks & Acceptance

**Execution:**
- [x] `domain.py` -- add immutable domain state, normalized lifecycle events, canonical phase transitions, explicit TUI capabilities, prompt/action validation, and pure busy-mode decisions -- centralize policy without importing a surface.
- [x] `app.py` and `prompts.py` -- consume domain state/effects and keep widgets responsible for presentation and input wiring -- remove duplicate transition and prompt policy without changing terminal behavior.
- [x] `AGENTS.md`, `tests/test_core_boundary.py`, and `pyproject.toml` -- classify and package `domain.py` as UI-free shared core -- keep the import boundary and installed entry point honest.
- [x] `tests/test_tui_domain.py`, `tests/test_app.py`, and shared-contract tests -- replay conversation/prompt fixtures plus queue, interrupt, reconnect, late-event, and rejection cases -- prove the adapter works with fakes and preserves existing behavior.

**Acceptance Criteria:**
- Given normalized fake-session events, when the TUI adapter replays a turn, then its accepted states and prompt actions conform to the shared contract and its terminal-only projections are explicit.
- Given a busy TUI, when a prompt is submitted, then the adapter alone selects queue, steer, or interrupt behavior and the UI only renders the result.
- Given a prompt or stale/late event, when the adapter receives it, then invalid input cannot mutate state, send twice, or affect a later turn.
- Given transport loss, when reconnection succeeds, then the TUI is visibly disconnected/recovered without replaying the ambiguous turn.
- Given the full existing Python suite, when it runs, then transcript, queue, interrupt, reconnect, prompt, and core-boundary tests remain green.

## Implementation Notes

- Added `TuiDomain` with immutable snapshots, explicit terminal capabilities, canonical lifecycle transitions, shared display projection, session/turn-generation guards, and single-shot prompt actions.
- Routed app busy-mode selection, prompt writes, connection/session resets, and normalized turn events through the adapter while retaining Textual widgets, transcript rendering, audio ownership, and keyboard behavior at the front end.
- Extended prompt rendering to consume validated domain prompt semantics and classified `domain.py` as a UI-free packaged core module.
- Added fake-session/domain coverage for normal replay, display projections, shared prompt actions, invalid milestones, duplicate/rejected responses, failed-write retry, reconnect recovery, session reset, and late-event rejection.
- Verification: focused suite `247 passed`; post-review targeted prompt/turn/connection rerun `51 passed`; full suite `849 passed` with one existing `websockets.legacy` deprecation warning; `git diff --check` is clean.

## Spec Change Log

## Review Triage Log

- B1 — patch — The original event gate accepted untagged late frames; the app now binds each `_consume_turn` stream to its turn-index generation, while `client.py` already discards mismatched wire turn IDs. The generation path is covered by stale-event tests.
- B2 — patch — The original adapter had no session boundary; `TuiDomain.reset_session()` now clears turn-local state and app profile/session switching calls it. The session-reset test proves old text and session-tagged events cannot cross the boundary.
- B3 — patch — `prompt_resolved` previously changed phase without an active matching prompt. It now requires a non-empty matching prompt ID and the stale-resolution test proves the later turn is unchanged.
- B4 — patch — Local interruption could be rejected from capture phases. `INTERRUPTED` is now allowed from heard/listening/transcribing phases, with terminal projection coverage.
- B5 — patch — The initial disconnected domain snapshot projected `idle`; `display_state` now projects disconnected whenever the connection is unhealthy and no turn is active.
- B6 — patch — Prompt requests already rejected missing IDs, but prompt resolution/rejection accepted missing IDs. Both response events now fail closed on missing or mismatched IDs.
- B7 — patch — Rejected non-stale domain events were previously silent. The app now surfaces a typed invalid-turn error while still silently dropping known stale events; invalid milestone tests cover the safe-state result.
- B8 — false — Busy selection is deliberately pure and session-independent. The existing interruption path already closes the stale socket and exposes disconnected/reconnect status when remote interruption is unavailable; changing the fallback would alter the established older-endpoint behavior without evidence of a new regression here.
- B9 — patch — Prompt IDs/options are now bounded to the shared action limits, and timeout parsing rejects non-positive or non-finite values before an action can be projected.
- B10 — patch — The snapshot test was tautological; it remains a schema-corpus check and now has direct terminal-only projection assertions plus a real shared prompt-action fixture replay.
- E1 — patch — Same stale-generation defect as B1; the app-side generation is now checked before any normalized event mutates state.
- E2 — patch — Same missing-turn-identity concern as B1; production event streams carry the generation from their owning turn even where normalized text/audio events omit wire IDs.
- E3 — patch — `turn_started` now passes through stale-event validation before it can open a turn, and the app does not synthesize it from late streams.
- E4 — patch — A repeated prompt request for the currently awaiting prompt is rejected without clearing the response gate.
- E5 — patch — Same stale prompt-resolution defect as B3; an inactive or mismatched prompt resolution is now rejected without changing phase.
- E6 — patch — A prompt rejection without a prompt ID is now rejected rather than clearing the current prompt’s awaiting state.
- E7 — patch — An old prompt write failure now resets domain state only if the UI prompt object is still the active one; a newer prompt cannot lose its retry gate.
- E8 — patch — Non-finite timeout values are rejected during domain prompt parsing.
- E9 — patch — Falsey malformed `options` values no longer collapse into an empty free-text prompt; only an absent value means no options.
- E10 — patch — Audio chunks/end markers before an audio start are rejected as typed invalid milestones and cannot reach playback through the domain-gated TUI path.
- E11 — false — `turn_end` is the normalized remote turn boundary; the TUI drains queued audio before rendering the completed transcript and ready status. The internal domain completion does not expose a premature terminal UI state.
- E12 — patch — A successful connection now resets a stale error phase to idle when no turn is active.
- E13 — patch — Domain turn admission now occurs before `send_turn`; the session-assigned ID is bound afterward, so a rejected admission cannot leave an already-sent untracked stream.
- E14 — patch — Unknown connection states now return a typed rejected `DomainResult` instead of raising from the adapter.
- E15 — patch — Prompt and option identifiers are checked against the shared action schema bounds before a display action is emitted.
- E16 — false — The TUI adapter intentionally has richer terminal-only phases and projections; the shared C reducer validates display snapshots, not the terminal’s internal `transcribing`/`complete`/`interrupted` event vocabulary. The spec explicitly preserves that distinction.
- E17 — false — `_pending_prompt`, `voice_state`, and transcript widgets are presentation projections retained by the approved boundary. Prompt acceptance, stale-event rejection, and busy selection are now domain-owned; no divergent policy outcome was demonstrated.
- E18 — patch — Same tautological fixture-test defect as B10; direct projection and action-fixture assertions now exercise the changed behavior.
- G1 — patch — Added explicit assertions for `transcribing → listening` and `interrupted → idle` projections.
- G2 — patch — Added an app-level fake-session test proving a failed prompt write releases the domain retry gate and a later valid answer is sent once.
- G3 — patch — Parameterized the existing masked-input app test for both `secret` and `password` prompt kinds, including the non-sensitive password case.
- O1 — carried patch — This is the same inactive/mismatched `prompt_resolved` defect recorded in B3/E5; the current implementation and stale-resolution test cover it.

## Design Notes

The display contract deliberately has a smaller nine-state surface than the TUI's engineering vocabulary. The adapter therefore shares accepted transition and action semantics with the display contract but keeps `transcribing`, `complete`, masked input, and diagnostic detail as declared terminal capabilities. This preserves cross-target conformance without making the room-display schema pretend to be a transcript UI.

## Verification

**Commands:**
- `venv/bin/pytest tests/test_tui_domain.py tests/test_display_contract.py tests/test_display_rules.py tests/test_display_conformance.py tests/test_app.py tests/test_app_wake.py tests/test_app_wake_indicator.py` -- expected: focused adapter, contract, and TUI regression tests pass.
- `venv/bin/pytest` -- expected: complete Python suite passes.
- `git diff --check` -- expected: no whitespace errors.

**Manual checks:**
- Replay the shared prompt and conversation fixtures through the fake-session adapter and inspect that terminal rendering remains inline, prompt answers remain single-shot, and reconnect never resubmits the interrupted turn.
