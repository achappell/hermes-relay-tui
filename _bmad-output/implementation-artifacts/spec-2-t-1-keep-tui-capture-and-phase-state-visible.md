---
title: 'Keep TUI capture and phase state visible'
type: 'feature'
created: '2026-09-10'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
baseline_commit: '64ee9b73d83abc3dcaf14c3bbe8601cfef106fdc'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-hermes-relay-tui-2026-09-07/EXPERIENCE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The direct TUI doorway exposes its local capture state, but an explicit `Ctrl+R` turn currently jumps from `ready` directly to `listening`. That hides the accepted-turn acknowledgement that the shared experience requires before the microphone opens, making the TUI's phase presentation less consistent with wake capture and with a Room Display that may mirror it separately.

**Approach:** Add the TUI's `heard` milestone to explicit voice initiation before the off-loop capture task starts. Keep the existing `TuiDomain` guard, microphone-open marker, normalized response phases, inline transcript, and separate Room Display boundary unchanged; prove the ordering and hardware-state distinction with a fake blocking capture.

</frozen-after-approval>

## Implementation Notes

- Added the explicit `heard` milestone in `app.py` before the off-loop microphone task is created, preserving the existing listening marker and normalized turn lifecycle.
- Added a blocking fake-session regression in `tests/test_app.py` proving `heard` renders before the microphone opens and `listening` renders with the open-mic marker.

## Review Triage Log

- `app.py:3134` — medium / patch — without an event-loop yield, `heard` was overwritten by `listening` before Textual could paint the acknowledgement; the new yield gives the status surface a render turn.
- `tests/test_app.py:440` — low / patch — the first regression observed method calls and only checked the widget after capture began; it now waits for and asserts the visible `heard` widget state before the mic opens.
- `tests/test_app.py:426` — low / patch — the first regression exercised only empty capture; it now completes a successful voice turn, while the existing empty-capture test remains in place.
- `spec-2-t-1-keep-tui-capture-and-phase-state-visible.md:17` — false — this is an intentional one-shot artifact; the active BMad workflow explicitly removes acceptance/task/code-map sections for a small change with no intent gaps or irreversible effects.
