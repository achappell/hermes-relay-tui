# Input Reconciliation — Product Brief

## Input

`_bmad-output/planning-artifacts/briefs/brief-hermes-relay-tui-2026-09-07/brief.md` and its `addendum.md`.

## Coverage

The PRD carries forward the brief’s core thesis, six product surfaces, single-room pilot boundary, Hermes authority, Missy profile identity, local-vs-household display privacy, calendar Departure Card behavior, per-Device security, visual-only outage behavior, eight-second follow-up, and no-diagnostic MVP boundary.

## Reconciled gaps

- The brief left the follow-up duration as a working assumption; PRD discovery confirmed eight seconds for v1.
- The brief described the TUI as a diagnostics surface; discovery narrowed the validated TUI journey to voice chat, with diagnostics remaining an engineering capability.
- The brief’s high-level statement that iOS/TUI retain local history is expanded into UJ-5 and FR-20/FR-21.
- The brief’s detailed implementation and acceptance material remains in its own addendum and memlog rather than being duplicated in the PRD.

## No unresolved product conflict

No brief decision contradicts the current PRD. The PRD adds testable detail where discovery resolved an open point and preserves the brief’s remaining open questions for downstream work.
