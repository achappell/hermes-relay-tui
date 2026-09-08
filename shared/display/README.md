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

The ESP adapter sends the same normalized object as a text action frame on its
state WebSocket. The display server accepts those frames alongside the
browser's HTTP action path, so a reducer-validated touch choice reaches the
same appliance callback regardless of front end.

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
The Python contract tests validate the JSON corpus and action shapes, the
native conformance test compiles the portable reducer and compares its
normalized view for every valid snapshot, and the Web tests feed the same
valid/invalid snapshots through the browser parser. This keeps the corpus
executable before the TUI adapter is migrated in UI-CORE-06.

## Reducer

`display_rules.h` and `display_rules.c` contain the portable business-rules
reducer. It has no rendering, transport, device, or clock dependency and can
be compiled as native C or WebAssembly.

- The first valid snapshot establishes state; later snapshots must advance
  `sequence` strictly or return `STALE` without mutation.
- Normal hands-free conversation follows idle → heard → listening → thinking
  → speaking → buffering/speaking → idle. Browser voice may begin at thinking
  because capture happens outside the appliance's wake-word phases. Error and
  disconnected states are explicit recovery paths rather than hidden transport
  side effects.
- The reducer derives `is_busy`, `connection_healthy`, `can_choose`, and
  `can_dismiss` for renderers and adapters.
- Prompt choices require an active prompt, the matching `action_id`, an
  advertised choice capability, and an option present in the prompt. Dismiss
  is independently capability-gated. Validation never mutates reducer state.
- Every failure is a typed result so a renderer cannot accidentally treat a
  stale snapshot or rejected action as accepted state.

## Browser adapter

`home_display/web/src/state/channel.ts` is the browser transport edge: it owns
the same-origin WebSocket, reconnect ladder, complete-message parsing, and
sequence filtering. `home_display/web/src/state/bridge.ts` feeds accepted
snapshots to the reducer and validates normalized prompt actions before sending
the browser-specific `POST /action` request. The canvas host in
`home_display/web/src/state/canvas.ts` pumps LVGL, copies its framebuffer to an
HTML canvas, maps CSS-space pointer events to the 1024x600 display, and drains
the action queue. Surfaces do not receive a socket or parse wire JSON.

The reducer port is injected into `DisplayBridge`, so a generated WebAssembly
binding can replace the browser implementation without changing transport or
surface code. Browser WebSocket APIs deliver protocol-fragmented frames as one
complete message; an incomplete application payload is rejected atomically and
cannot replace the last accepted view.

## WebAssembly display target

`display_wasm.c` and `display_wasm.h` expose the shared reducer and the LVGL
surface through version 2 of a small C ABI. The browser binding in
`home_display/web/src/state/wasm.ts` loads the Emscripten module and feeds it
normalized snapshots. `WasmCanvas.svelte` is only the lifecycle shell around
that host; the visible state and prompt rendering come from the same LVGL
objects used by the ESP32 target.

The ABI exports the 1024x600 framebuffer, a millisecond LVGL tick pump, a
pointer input setter, connection-state transitions, and a validated
single-action queue. LVGL's 32-bit framebuffer is laid out BGRA in
WebAssembly memory; the browser host converts it to the RGBA order required by
`ImageData`. The host scales the backing canvas for device pixel ratio while
mapping touch coordinates from `getBoundingClientRect()`, so a high-DPI iPad
does not turn a button into a nearby suggestion.

The reproducible build pins Emscripten `6.0.5` and LVGL `8.3.11`, and uses
`shared/display/wasm/` for the browser's board and LVGL configuration shims:

```bash
git clone --depth 1 https://github.com/emscripten-core/emsdk.git build/display-wasm/emsdk
build/display-wasm/emsdk/emsdk install 6.0.5
build/display-wasm/emsdk/emsdk activate 6.0.5
source build/display-wasm/emsdk/emsdk_env.sh
bash scripts/build_display_wasm.sh --check
bash scripts/build_display_wasm.sh
npm --prefix home_display/web run build
```

The first build fetches LVGL into the ignored `build/display-wasm/` cache. It
writes `display_core.js` and `display_core.wasm` to
`home_display/web/public/wasm/`; Vite copies them into the packaged
`home_display/static/wasm/` directory. Set `EMCC`, `LVGL_DIR`,
`DISPLAY_WASM_BUILD_DIR`, or `DISPLAY_WASM_OUTPUT_DIR` when a build machine
uses different paths. A kiosk started without the generated module shows an
actionable setup error instead of opening a display with an unvalidated
JavaScript-only reducer.
