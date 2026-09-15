---
id: STANDARD-3-TUI
title: Close the TUI migration to the Standard Hermes boundary
status: done
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

The implementation is merged in PR #186. The remaining live Profile check is
recorded as follow-up evidence rather than a reason to reopen the migration.

## Dependencies

HOME-NW-01 Standard compatibility gate.
