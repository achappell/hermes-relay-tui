# Input Reconciliation — Hermes Relay iOS

## Input

The separate `../hermes-relay-ios` repository, including `README.md`, `docs/architecture.md`, the voice-interface design, and the relay-profile design.

## Coverage

The PRD carries forward the independent native iOS/macOS doorway, tap-to-speak interaction, listening/thinking/speaking state, streamed response text, local transcript history, secure profile storage, reconnect honesty, and the separate-repository boundary.

## Boundary preserved

- The Media Server transcription requirement applies to Puck audio on the ESP32 home-LAN path. The iOS Client may use its existing local push-to-talk transcription path; the PRD does not require iOS microphone bytes to pass through the Media Server.
- The existing iOS server-confirmed interrupt capability is not the same as hands-free active-playback barge-in. The PRD defers automatic barge-in while leaving explicit iOS controls available to the client implementation where supported.
- Keychain-backed relay/profile storage remains an iOS implementation concern. The PRD’s Device Credential requirement governs physical household Devices, not a shared bearer token model for the iOS Client.

## Gap for downstream work

The PRD does not yet define the exact iOS profile-switching UX or the mapping between a Hermes Profile and the physical-device Wake Mapping editor. Those are phase-appropriate follow-ups for UX and architecture, not blockers for this private-pilot product boundary.
