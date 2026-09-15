---
id: STANDARD-7-ESP32
title: Add the ESP32 Touch audio and session adapter
status: ready-for-dev
github_issue: https://github.com/achappell/hermes-relay-tui/issues/184
---

# Standard-7 — ESP32 Touch adapter

## Scope

Give the first-class ESP32 Touch voice-plus-display surface a bounded Home and
Standard session adapter while keeping display rendering and session authority
separate.

## Acceptance

- Microphone capture, response PCM, phase state, interruption, reconnect, and
  no-replay behavior use the stable session seam.
- The shared display snapshot remains presentation-only; firmware does not
  invent Hermes events, expose credentials, or become a second Session.
- Native simulator evidence and physical hardware evidence identify exactly
  what each proves.
- The adapter fails closed when identity, route, or Home readiness is absent.

## Dependencies

HOME-NW-01, HOME-NW-02, HOME-NW-03, and the existing ESP32 display reducer.
