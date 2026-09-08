# Reviewer Gate — Adversarial Divergence Review

Date: 2026-09-08

## Verdict

PASS after tightening the display sequence epoch and the display-capable-front-end boundary.

## Hypothetical independent units

### Unit A — a future terminal session surface

It uses SessionProtocol, keeps a local draft and queue, translates normalized Hermes events into terminal transcript records, and reconnects without replaying an uncertain turn. AD-1, AD-2, AD-3, AD-7, and AD-9 prevent it from importing Textual into the core, owning server state, parsing wire frames, replaying a turn, or dragging in appliance dependencies.

### Unit B — a future wall-display adapter

It consumes the DisplaySnapshot contract, resets its reducer on reconnect, validates actions locally, and renders only the state accepted by the reducer. AD-4, AD-5, AD-6, AD-8, and AD-10 prevent it from inventing prompt semantics, comparing sequence values across reconnect epochs, receiving another room's transcript, centralizing state, or forwarding credentials.

## Findings

No remaining pair can choose incompatible ownership, contract semantics, or recovery behavior while obeying the spine.

The initial draft left two seams open:

1. A client could treat a reconnect as part of the old sequence domain while another reset its reducer. AD-4 now defines channel epochs.
2. The phrase "all front ends consume the shared display contract" would have overstated the current TUI migration. AD-1 now limits the display contract to display-capable front ends while keeping SessionProtocol universal.

The current rules still leave hardware arbitration, device credentials, calendar propagation, and central service design deferred, but those are explicitly outside this repository's present ownership rather than silent holes.
