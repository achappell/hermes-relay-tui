---
id: STANDARD-3-TUI
title: Close the TUI migration to the Standard Hermes boundary
status: in-review
github_issue: https://github.com/achappell/hermes-relay-tui/issues/182
---

# Standard-3 — TUI migration

## Scope

Close the implemented TUI migration to the pinned Standard Hermes gateway,
session, and audio boundary. Keep the fork path explicit and rollback-only
until the cross-surface retirement gate.

## Acceptance

- Standard JSON events, cumulative text, signed-16 little-endian PCM, prompt
  correlation, interruption, reconnect, and explicit timing absence retain
  their existing semantics.
- One live profile-ownership check proves the selected Profile is fixed before
  capture and survives reconnect without replay.
- Content-safe diagnostics identify route, version, phase, timing, and typed
  failure without recording conversation content.
- The branch is reviewed and ready to merge.

## Evidence

The implementation is merged in PR #186. Local validation and the complete
suite are recorded in the [TUI validation record](../test-artifacts/automation-summary.md).
The approved direct Standard endpoint needed for live closure is not available
in this environment, so issue #182 remains open in Verify.

## Validation record — 2026-09-15

- Current main: `a38e033ec36612236c3ceddd92445b6ef01202e4`; PR #186 merge
  `6f0759c3882720e0efcb48b4d2b770ca008f8ea7` is present in its history.
- Focused STD-3 suite: **464 passed in 53.88s**.
- Full repository suite: **1,370 passed, 1 skipped, 6 warnings in 220.85s**.
- Required live endpoint: approved direct Standard Hermes `/api/ws` plus
  `/api/audio/speak-stream`.
- Available endpoint configuration: legacy `/voice-session` only; no approved
  direct Standard URL or Hermes Profile routing value is configured.
- Live text, voice/audio, confirmed interrupt, disconnect/reconnect without
  replay, timing absence, audio-failure behavior, and Profile ownership across
  create/resume/reconnect were not run. No live result is claimed.

## Dependencies

HOME-NW-01 Standard compatibility gate.
