# Shared display contract

This directory is the wire-independent contract for the ESP display, Web
Canvas, and TUI adapters. Rendering, WebSocket connections, touch/keyboard
events, and platform capability checks remain outside this contract.

## Snapshot

`display_snapshot.schema.json` describes schema version 1. A snapshot always
has `type`, `schema`, `sequence`, `state`, and `response_text`. The existing
`home_display/server.py` payload remains valid: `status_text`, `media`,
`account`, `prompt`, and `capabilities` are optional at the top level. A
missing `capabilities` value means no advertised optional actions or features.

The nine states are `idle`, `heard`, `listening`, `thinking`, `speaking`,
`buffering`, `error`, `disconnected`, and `prompt`. A `prompt` state must carry
a prompt; every other state must carry `prompt: null` or omit it. Prompt text
and choices are bounded for the embedded target, with one to four options.

Unknown top-level and prompt fields are forward-compatible and must be ignored
by adapters that do not understand them. Malformed known fields still reject
the snapshot. This lets the server add data without making older displays
collapse in a heap beside the toaster.

`sequence` is monotonic per display channel. A snapshot can be structurally
valid but stale when its sequence is less than the last accepted sequence;
staleness is an ordering decision for the reducer, not a schema error. The
`fixtures/sequences/stale.json` case records that distinction.

## Actions

`display_action.schema.json` defines the normalized action emitted by a front
end. The current browser transport encodes the same fields as
`POST /action?action_id=...&choice=...`; that transport detail belongs to the
Web adapter and may differ on ESP or TUI.

Capability names are deliberately small and explicit. `prompt.choose` means a
front end can submit a selected option; `prompt.dismiss` means it can close a
prompt without choosing. A target must not emit an action it has not
advertised or that the current snapshot does not permit.

## Fixtures

- `fixtures/snapshots/` contains valid state examples, including a legacy
  payload without capabilities and a payload with an unknown future field.
- `fixtures/invalid/` contains malformed or invariant-breaking snapshots.
- `fixtures/actions/` and `fixtures/invalid-actions/` cover normalized action
  shapes.
- `fixtures/sequences/` covers ordering cases such as stale snapshots.

The fixtures are the conformance seed for the reducer and all three adapters.
