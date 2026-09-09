# Input Reconciliation — PRD/iOS Client

## Input

`_bmad-output/planning-artifacts/prds/prd-hermes-relay-tui-2026-09-07/reconcile-ios-client.md`

## UX decisions carried forward

- iOS/macOS remains an independent Hermes doorway with typed and tap-to-speak turns, listening/thinking/speaking feedback, streamed transcript, Local History, and secure profile handling.
- iOS remains the physical-Device control plane for discovery, approval, Room assignment, Wake Mappings, credentials, revocation, and re-enrollment. The active profile is visible in the iOS conversation header.
- The Media Server requirement stays specific to Puck audio; iOS’s local push-to-talk path is not forced through it. Explicit iOS interrupt semantics remain distinct from deferred hands-free barge-in.

## Intentionally not duplicated or dropped

- Keychain storage, relay protocol mechanics, and repository architecture are not duplicated in the UX contract.
- No iOS doorway capability was dropped. The undefined details of profile switching and physical Wake Mapping editing are intentionally left as UX work rather than guessed.

## Open item / ambiguity

The exact profile-switching and profile-to-Wake-Mapping editing flow is open, as are publication of Room/mapping/credential changes and safe last-known behavior while a Device is offline. Detailed macOS companion behavior also remains unspecified.
