# Product Brief Addendum: Decision Ledger and Parked Detail

This addendum preserves detail that would make the executive brief a second specification. The append-only `.memlog.md` remains the audit trail; this file is the readable handoff for downstream product, architecture, and implementation work.

## Memlog audit

The memlog contains 144 entries: 61 decisions, 20 acceptance checks, 19 open questions, 11 scope notes, 6 security notes, 5 assumptions, 4 risks, 3 metrics, 2 architecture notes, 2 rationale notes, 1 insight, 1 constraint, 3 changes, and 1 event. Meaningful product decisions are distilled into `brief.md`; detailed validation scenarios and unresolved implementation questions are retained below. Repeated process entries remain in the memlog as audit history and are not duplicated here.

## Decision ledger

### Identity, sessions, and routing

- The working title is **Hermes Home Assistant Platform**. Missy is one Hermes voice profile, not the product identity.
- Photon, iOS, TUI, puck, and display-owned voice endpoints use independent Hermes sessions. A reconnect starts a fresh session; there is no forced daily rollover in v1.
- A shared device may recognize multiple explicit wake-word/profile mappings. Each phrase maps to exactly one profile, and duplicate or ambiguous mappings are rejected before deployment.
- The selected profile is fixed before capture is submitted. If it is revoked or unavailable, the endpoint fails closed: no capture, no Hermes submission, and only local status.
- The closest device wins. An effective proximity tie resolves through configured per-device priority; losers remain silent.

### Administration and privacy

- iOS is the sole physical-device control plane: discovery, approval, room assignment, profile mapping, credential issuance, revocation, and re-enrollment.
- New devices discovered over the LAN are unconfigured and inert until explicit iOS approval. QR/manual pairing is the fallback when discovery is blocked.
- Every approved device has an individual revocable credential. A device cannot restore access after revocation without re-enrollment.
- Hermes/vault owns agent/profile context, the shared family calendar, household home, and travel estimates. iOS owns room presentation policy: Immich filters and departure thresholds.
- Raw audio is home-LAN-only and transient. The media-server may buffer it for transcription, then discards it. Diagnostic recording is explicit opt-in.
- The media-server is not a transcript store. iOS and TUI may retain deliberate local history; puck and displays retain only active interaction state.
- Active response text is room-local. Household-wide calendar departure cards are the deliberate cross-room exception.

### Displays and calendar context

- First release supports both the ESP32-S3/LVGL display and a Safari/Guided Access iPad browser kiosk. The native macOS simulator is development tooling.
- Idle displays show Immich photos selected by per-room face filters. No matching photos produce a neutral ambient background rather than a widened filter or setup prompt.
- The shared family calendar is evaluated per event. A location and usable travel time are required. Departure is calculated from event start, route duration from the household home, and the configured family buffer.
- A live route is preferred. A configured vault estimate may be used when live routing is unavailable and is labeled estimated. If neither is usable, no leave-time alert is shown.
- The household default departure threshold applies unless an event override exists. The effective card is visual-only, replaces ambient photos on every display while actionable, and clears at event start.
- Cancellation clears the card. Time or location changes recompute it immediately across displays.

### Voice behavior and hardware

- The puck’s TFT is a wake/turn status surface, not a transcript. Wake acknowledgement and status should appear in roughly one second; roughly four seconds to first spoken Hermes audio is acceptable for v1.
- After every response, the active device opens a bounded follow-up window without another wake phrase. “Stop” during capture or follow-up closes it silently. Active-playback barge-in waits for an echo-safe route.
- When the media-server or Hermes is unavailable, the puck fails quiet and the display keeps useful ambient/calendar content with a persistent unavailable indicator. Verified recovery clears the indicator but never silently reopens capture or submits a turn.
- The first puck is a ReSpeaker Lite prototype with a salvaged Google Home speaker driver in a printed enclosure. Exact board variant, host ESP32, USB/I²S mode, firmware, amplifier/impedance path, enclosure acoustics, TFT controller, and thermal/safety behavior remain hardware validation items.

## Downstream validation inventory

- Complete the dinner-in-kitchen journey without keyboard interaction.
- Exercise two wake mappings on one device and verify profile isolation before transcript submission.
- Revoke a device and verify immediate rejection while it remains powered.
- Trigger two devices together and verify one winner with no duplicate Hermes turn.
- Drop the relay, verify fresh session creation after reconnect, then require a fresh wake.
- Disable Hermes/media-server and verify no puck capture or fallback speech; verify displays retain useful state.
- Confirm raw audio and media-server transcripts leave no default archive.
- Cross, cancel, move, and start a calendar event; verify all display promotion, recomputation, clearing, and return to ambient behavior.
- Verify room-local conversation mirroring and household-wide calendar propagation separately.

## Parked implementation questions

- Proximity signal, arbitration window, and configured priority semantics.
- Device credential storage, rotation, expiry, offline revocation behavior, and iOS re-enrollment flow.
- LAN discovery service, QR/manual fallback, and kiosk authentication for the iPad URL.
- Media-server audio framing, backpressure, bounded buffer lifetime, and cleanup on cancellation/disconnect.
- Immich face-filter representation, exclusions, cache freshness, and the neutral-background asset.
- Calendar synchronization cadence, missed-update recovery, route refresh, stale estimate rules, and event-threshold editing UX.
- Exact follow-up duration and any future barge-in qualification.
- Product naming and readiness criteria for use beyond the private household pilot.

## Source ledger

- `docs/superpowers/specs/2026-08-31-home-03-kiosk-display-design.md`
- `docs/superpowers/specs/2026-09-01-home-02-wake-word-design.md`
- `shared/display/README.md`
- `firmware/esp32-s3-touch-lcd-7/README.md`
- `home_display/appliance.py`
- `docs/testing/home-09-appliance-loop.md`
- `docs/testing/voice-08-home-10-manual-plan.md`
- `../hermes-relay-ios/README.md`
- `../hermes-relay-ios/docs/architecture.md`
- `../hermes-relay-ios/docs/superpowers/specs/2026-08-30-ios-voice-interface-design.md`
- `../hermes-relay-ios/docs/superpowers/specs/2026-09-05-ios-13-relay-profiles-design.md`
- Official ReSpeaker Lite documentation and current Google Home/Gemini, Home Assistant Voice, and Espressif ESP-SR references.
