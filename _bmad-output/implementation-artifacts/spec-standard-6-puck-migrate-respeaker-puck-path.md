---
id: STANDARD-6-PUCK
title: Migrate the ReSpeaker Puck path to the Standard Home boundary
status: ready-for-dev
github_issue: https://github.com/achappell/hermes-relay-tui/issues/183
---

# Standard-6 — Puck migration

## Scope

Move the Puck voice path behind the paired Home bridge and pinned Standard
Hermes boundary. Puck remains an audio and status surface, not a control plane.

## Acceptance

- Puck sends only its paired Device credential and opaque conversation binding
  to Home.
- Standard response audio, bounded follow-up, exact `stop`, interruption,
  reconnect, and no-replay behavior are preserved.
- Raw PCM diagnostics remain explicitly opt-in and bounded.
- Hardware evidence covers wake, capture, playback, failed-closed identity,
  and clean shutdown.

## Dependencies

HOME-NW-01, HOME-NW-02, HOME-NW-03, and the existing Puck audio hardening
stories.
