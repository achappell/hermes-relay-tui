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
The direct Standard endpoint is now live through the deployed Hermes Home
pilot boundary. The live closure below covers the TUI's direct Standard
adapter; it does not claim that the TUI uses the Home bridge route.

## Validation record — 2026-09-15 (live closure)

- Current main: `a38e033ec36612236c3ceddd92445b6ef01202e4`; PR #186 merge
  `6f0759c3882720e0efcb48b4d2b770ca008f8ea7` is present in its history.
- A live parser defect was found and fixed on this branch: Hermes' legitimate
  `session.title` event carries the runtime session ID in its envelope and the
  durable session ID in its payload. The client now preserves those as separate
  identities while continuing to reject conflicting identities on all other
  event types.
- Regression check for that boundary: **2 passed**; focused STD-3 suite:
  **465 passed in 50.62s**.
- Full repository suite: **1,371 passed, 1 skipped, 6 warnings in 205.09s**.
- Live route: direct Standard Hermes `/api/ws`, with the separate
  `/api/audio/speak-stream` sidecar, selected Profile `amanda`.
- Live text: streamed text reached a terminal `turn_end`.
- Live audio: **29,696 bytes** of signed-16 PCM arrived across five chunks,
  followed by `audio_end`; no speech-timing records were emitted.
- Live interruption: `session.interrupt` was accepted and a terminal
  `turn_interrupted` event was observed.
- Live profile/recovery: create, resume, and reconnect all reported Profile
  `amanda`; a deliberately disconnected in-flight turn resumed under the same
  durable session with no automatic replay, and an explicit post-resume turn
  completed.
- Live audio-failure fallback: an injected sidecar-open failure produced one
  typed `audio_unavailable` event while the real text turn still reached
  `turn_end`.
- Standard client pin remains `0.21.1` at commit
  `2237be355906fbe6065ce1815711eee52b2d646e`.

## Dependencies

HOME-NW-01 Standard compatibility gate.
