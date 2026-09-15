---
id: STANDARD-8-WK
title: Migrate the shared W/K browser and iPad route to Standard Hermes
status: ready-for-dev
github_issue: https://github.com/achappell/hermes-relay-tui/issues/185
---

# Standard-8 — W/K migration

## Scope

Move the single shared web/iPad deployment surface behind Home and the pinned
Standard Hermes boundary. iPad is a deployment target, not another surface.

## Acceptance

- Browser bootstrap uses an approved route and endpoint credential without
  putting secrets in URLs or browser history.
- Text, response audio, prompts, interruption, reconnect, and explicit timing
  behavior match Standard semantics.
- Concurrent W/K sessions remain isolated, and passive display mode creates no
  second turn.
- Physical Safari/iPad, safe-channel, audio, touch, kiosk, and concurrent
  session validation are recorded.

## Dependencies

HOME-NW-01, HOME-NW-02, HOME-NW-03, and the existing W/K session-isolation
foundation.
