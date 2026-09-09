# Input Reconciliation — Product Brief Addendum

## Input

`_bmad-output/planning-artifacts/briefs/brief-hermes-relay-tui-2026-09-07/addendum.md`

## UX decisions carried forward

- Unique Wake Mappings, pre-capture profile selection, fail-closed identity, closest-device arbitration, iOS-owned administration, revocable credentials, and fresh sessions after reconnect define the trust boundary.
- Pucks and Displays retain only active state; iOS and TUI may retain deliberate Local History. Active conversation text stays room-local, while qualifying Departure Cards are the intentional household-wide exception.
- Displays use room-filtered Immich ambience, truthful turn/recovery states, and visual-only calendar context. The Puck remains a status surface rather than a transcript surface.
- The eight-second follow-up, silent exact “stop,” no fallback speech, and deferred echo-sensitive barge-in are preserved. The UX decisions add a follow-up sound cue, listening state, closing cue, and response-synchronized animation.

## Intentionally not duplicated or dropped

- The source ledger, validation inventory, and hardware/protocol specifics are retained as downstream evidence and constraints, not repeated as interaction prose.
- Parked mechanisms—proximity signal, credential storage, LAN pairing, buffering, Immich cache policy, and calendar synchronization—are intentionally deferred. The undefined “Photon” mention is excluded from the first-release UX surface list, not silently promoted.

## Open item / ambiguity

The addendum’s parked questions remain open for architecture or later UX: offline revocation and last-known configuration, discovery/QR and kiosk authentication, media cleanup, Immich freshness, calendar recovery, and pilot/naming gates. No conflict with the confirmed UX decisions was found.
