---
title: "Hermes Home Assistant Platform"
status: final
created: 2026-09-07
updated: 2026-09-07
---

# Product Brief: Hermes Home Assistant Platform

## Executive Summary

Build a household assistant that replaces the Google Home-like experience with a Hermes-agent-backed system the household can own and evolve. One interaction model should work through a room voice puck, touch displays, a separate native iOS/macOS client, and the existing terminal client. Hermes remains the authority for agent behavior and household knowledge; each doorway remains responsible for honest local capture, presentation, and recovery.

The first proof is simple: Amanda says “Hey Missy” in the kitchen and asks about dinner. The nearest approved device routes the wake word to the Missy Hermes profile, the trusted media-server transcribes the utterance, and Hermes answers from the authorized vault context. Missy is one Hermes voice profile, not the product identity. The product’s working title remains Hermes Home Assistant Platform until the first-room pilot gives it a name.

## Defining Experience: Dinner in the Kitchen

Amanda says, “Hey Missy.” The closest approved puck acknowledges the wake, captures one utterance, and sends it over the home LAN to the media-server for transcription. The transcript reaches Missy in a new, endpoint-owned Hermes session. Hermes decides the response; the puck speaks it, and the display in that room mirrors the active turn without capturing, speaking, or creating a second session.

After the answer, the active device keeps listening for a bounded follow-up without another wake phrase. Saying exactly “stop” closes that local window silently. The display returns to its ambient surface when the interaction ends. The iOS app and TUI provide full text/voice doorways, local history, setup, recovery, and diagnosis rather than competing assistant personas.

## The Problem

Vendor household assistants are convenient but opaque, coupled to someone else’s hardware and account model, and poor at preserving a household’s chosen agent and private knowledge across rooms. A family needs natural voice access to Hermes and its authorized vault context without routing every question through a phone or terminal.

The engineering risk is fragmentation: a puck, display, iOS app, and TUI can each invent different wake behavior, turn states, prompt handling, and recovery semantics. The system must feel like one assistant while remaining truthful about which device heard, captured, spoke, displayed, or failed.

## The Solution

The platform combines:

- **Household voice:** an ESP32 puck, initially prototyped with a ReSpeaker Lite, salvaged Google Home speaker driver, custom enclosure, and provisional 1.28-inch TFT for wake/turn status. ESP32 handles wake detection and capture; the trusted media-server performs speech-to-text.
- **Room displays:** an ESP32-S3/LVGL appliance and a browser/WASM kiosk running in Safari on an iPad. Both consume the same display contract, ambient Immich feed, room policy, calendar state, mirrored Hermes turn state, and recovery state. The native macOS simulator is development tooling, not a third household surface.
- **Companion doorways:** a separate native iOS/macOS client for device administration, typed and voice conversation, secure profile/device handling, local history, and recovery; and the existing TUI for direct conversation, diagnostics, and setup-adjacent recovery. The TUI is not the household configuration surface.
- **Shared household rules:** explicit wake-word/profile routing, closest-device arbitration, room-local conversation mirroring, and household-wide visual departure alerts. A shared device may recognize multiple mappings, but each wake phrase maps to exactly one profile.

The first release is a voice doorway into Hermes, not a second smart-home platform. Clients do not duplicate Hermes’ model, vault, timer, media, reminder, or smart-home integrations. Version one answers prompts by voice, keeps active-playback barge-in deferred until the audio route is echo-safe, and avoids touch-based prompt choices.

## What Makes This Different

- **One agent, several doorways:** Missy and future profiles remain in Hermes; hardware and clients do not invent alternate assistant personalities.
- **Household-owned behavior:** routing, credentials, room policy, and display rules remain inspectable rather than disappearing into vendor cloud machinery.
- **Honest degradation:** displays keep showing useful ambient and calendar context during Hermes outages; the puck fails quiet rather than fabricating a local answer.
- **One semantic contract:** ESP32, Web/WASM, display, and TUI adapters share normalized state and turn semantics without forcing identical presentation.

## Who This Serves

The primary users are household members using shared devices in kitchens, common rooms, and near-field spaces. They need fast voice interaction, clear acknowledgement, and confidence that a device is listening only when intended.

The secondary user is the household member maintaining Hermes, profiles, devices, and network connections. She needs iOS for physical-device administration and everyday portable access, and the TUI for power use and diagnosis.

## Success Criteria

The first-room pilot succeeds when:

- Amanda can complete the dinner question end to end without a phone, keyboard, or TUI, receiving the current answer from the authorized `media-server amanda` profile.
- A recognized wake word selects its unique Hermes profile before capture; unavailable or revoked profiles fail closed, and profile context never crosses routes.
- Multiple listening devices produce one winner: the closest device responds, configured priority resolves an effective tie, and losing devices create no duplicate turn.
- Wake acknowledgement appears in roughly one second, and first spoken Hermes audio arrives in roughly four seconds after speech ends.
- The room display mirrors the active response without speaking or capturing; other displays do not receive conversation text. iOS and TUI retain intentional local history; the puck, display, and media-server retain neither raw audio nor transcript archives by default.
- Idle displays show Immich photos selected by room-level face filters. A qualifying shared-calendar event replaces photos on every display with a visual time-to-leave card; the card uses the household default or event override, falls back to a configured estimate labeled estimated, and clears or recomputes when calendar data changes.
- Hermes outages leave displays useful and honest, with a discrete persistent unavailable indicator. The puck captures nothing and speaks no fallback; reconnection clears the indicator only after verified recovery and requires a fresh wake.
- iOS can discover a device over the LAN, keep it inert until explicit approval and room/profile assignment, and revoke its individual credential immediately. QR/manual pairing remains a fallback.

## Scope

### First release

Ship one complete single-room household pilot: one puck, its room-local display, the iPad browser kiosk, the separate iOS/macOS client, and the TUI. Keep contracts and configuration multi-room-ready, but do not make a multi-room hardware rollout a prerequisite.

In scope are Hermes voice/text turns, local wake and capture, media-server transcription over the home LAN, streamed PCM playback, acknowledgement/status feedback, bounded follow-up listening, room-local display mirroring, Immich ambient photos, shared family-calendar departure cards, device enrollment/revocation, recovery states, and shared schema/fixture/conformance tests.

Hermes/vault remains authoritative for agent/profile context, the shared family calendar, household home, and configured travel estimates. iOS is the sole authority for physical-device approval, room assignment, wake-word/profile mappings, per-device credentials, revocation, re-enrollment, Immich face filters, and departure-alert presentation thresholds.

### Explicitly out

- Hosting Hermes intelligence or a large model on ESP32.
- A general smart-home ecosystem, vendor-cloud migration, camera-history product, or media catalog.
- Full response text on the puck’s small TFT, unconstrained appliance transcript history, or chain-of-thought display.
- Touch-based Hermes prompt choices and active-playback barge-in before echo-safe audio is proven.
- Unsolicited spoken or audible departure alerts in version one.
- Repository splitting before a real dependency conflict requires it.

## Vision

If this succeeds, the house has a coherent assistant fabric rather than a drawer of clever prototypes: a puck answers naturally, displays show calm and useful context, iOS administers the physical doorways, and the TUI explains what happened when invisible machinery misbehaves. New surfaces join by consuming the shared contract instead of reimplementing household rules.

## Open Questions

- What proximity signal and tie window should the media-server use for closest-device arbitration?
- How should iOS publish mapping, room, and credential changes, and how should devices behave while offline?
- What exact per-device credential storage, rotation, expiry, and re-enrollment mechanism fits ESP32, iPad kiosk, and future targets?
- What media-server transport, bounded buffering, and cleanup behavior should transcription use for success, cancellation, and failure?
- Which people and exclusions define each room’s Immich face filter, and what freshness policy applies?
- Where are travel estimates keyed in the vault, how is staleness detected, and how are missed calendar updates recovered?
- What is the exact follow-up window (eight seconds is the current working default), and when does a future release earn barge-in?
- When does the private household pilot become ready for a wider demonstration or distribution?

## Evidence Consulted

Repository design history, the shared display contract, the ESP32-S3 firmware/simulator, the appliance and voice testing plans, the separate Hermes relay iOS repository, official ReSpeaker Lite documentation, and current Google Home/Gemini, Home Assistant Voice, and Espressif voice-platform references informed this brief. The detailed paths and decision ledger are preserved in the accompanying addendum and memlog.
