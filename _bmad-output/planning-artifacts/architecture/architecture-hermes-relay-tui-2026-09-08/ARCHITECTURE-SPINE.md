---
name: Hermes Relay Multi-Front-End
type: architecture-spine
purpose: build-substrate
altitude: initiative
paradigm: ports-and-adapters with functional cores
scope: "The hermes-relay-tui repository: Python Hermes session core and TUI, household appliance, shared display contract and reducer, native LVGL firmware/simulator, and Web/WASM kiosk."
status: final
created: 2026-09-08
updated: 2026-09-08
binds:
  - FR-1 through FR-6
  - FR-10 through FR-12
  - FR-19
  - FR-21 through FR-22
sources:
  - AGENTS.md
  - pyproject.toml
  - shared/display/README.md
  - shared/display/display_snapshot.schema.json
  - shared/display/display_action.schema.json
  - _bmad-output/planning-artifacts/prds/prd-hermes-relay-tui-2026-09-07/prd.md
  - _bmad-output/planning-artifacts/briefs/brief-hermes-relay-tui-2026-09-07/brief.md
  - docs/superpowers/specs/2026-08-31-home-03-kiosk-display-design.md
  - docs/superpowers/specs/2026-09-01-home-02-wake-word-design.md
  - https://pypi.org/project/textual/
  - https://websockets.readthedocs.io/en/stable/
  - https://svelte.dev/docs/svelte/overview
  - https://vite.dev/blog/announcing-vite6
  - https://v3.vitest.dev/guide/
  - https://docs.lvgl.io/8.3/
  - https://emscripten.org/docs/tools_reference/emsdk.html
companions:
  - _bmad-output/planning-artifacts/prds/prd-hermes-relay-tui-2026-09-07/prd.md
---

# Architecture Spine — Hermes Relay Multi-Front-End

## Design Paradigm

Use ports-and-adapters with functional cores.

- The Python core owns Hermes protocol normalization, session and turn lifecycle, configuration, and reusable local I/O ports. It must not import a UI framework or assume a terminal.
- The portable C core in shared/display/ owns bounded display-state and action rules. It has no rendering, transport, device, or clock dependency.
- Adapters compose those cores with WebSocket transports, microphones, speakers, Textual widgets, the household display server, ESP-IDF, native SDL, browser APIs, and WebAssembly.
- Renderers consume adapter state and emit platform actions. They do not become alternate protocol or display-rule implementations.

~~~mermaid
flowchart TB
    providers["Hermes endpoint, OS audio, LAN, browser, ESP hardware"]
    tui["TUI adapter<br/>app.py, transcript.py, prompts.py"]
    appliance["Appliance adapter<br/>home_display/"]
    native["Native display adapter<br/>firmware/"]
    web["Web/WASM adapter<br/>home_display/web/"]
    pycore["Python functional core<br/>client.py, session.py, config.py,<br/>audio/mic/wake/handsfree"]
    ccore["Portable display functional core<br/>shared/display/"]

    providers --> tui
    providers --> appliance
    providers --> native
    providers --> web
    tui --> pycore
    appliance --> pycore
    appliance --> ccore
    native --> ccore
    web --> ccore
~~~

## Invariants & Rules

### AD-1 — Core policy is framework- and surface-independent [ADOPTED]

- **Binds:** All core modules and all front ends.
- **Prevents:** Terminal, browser, appliance, or hardware assumptions leaking into reusable behavior.
- **Rule:** Core modules must not import Textual or another front-end framework, and must not assume a terminal, keyboard, scrollback transcript, or human observer. Every front end depends on SessionProtocol; display-capable front ends additionally depend on the shared display contract. Core modules never import app.py, home_display/, browser code, or firmware.

### AD-2 — Each state domain has one owner [ADOPTED]

- **Binds:** FR-1 through FR-6, FR-10 through FR-12, FR-19, FR-21, and FR-22.
- **Prevents:** Competing mutable state, stale copies, accidental transcript fan-out, and unclear recovery behavior.
- **Rule:** HermesSession owns connection, capabilities, and active-turn protocol facts. A display-capable front-end coordinator owns its local device lifecycle and maps events to its published snapshot. shared/display owns reducer-accepted view, stale-sequence rejection, and action validation. DisplayStatePublisher owns only the latest immutable transport snapshot and sequence. Drafts, queues, presentation state, and optional local history remain surface-local; appliance/display paths do not archive transcripts.

### AD-3 — Hermes wire behavior has one adapter boundary [ADOPTED]

- **Binds:** FR-1 through FR-6, FR-19, FR-21, and FR-22.
- **Prevents:** Front ends parsing incompatible wire frames, inventing assistant behavior, or replaying turns after uncertain delivery.
- **Rule:** client.py owns hello, streamed turn-event normalization, interrupt/prompt-response frames, unknown-event diagnostics, and typed protocol errors. session.py orchestrates one connection and turn lifecycle. Front ends consume normalized events through SessionProtocol; they do not parse Hermes frames or invent wire payloads. A turn that may have reached Hermes is never automatically replayed after transport failure.

### AD-4 — Display semantics cross targets through the versioned contract [ADOPTED]

- **Binds:** FR-3, FR-4, FR-10 through FR-12, FR-19, and FR-22.
- **Prevents:** ESP, native simulator, Web/WASM, appliance, and future TUI adapters accepting different states or actions.
- **Rule:** display_snapshot.schema.json, display_action.schema.json, and their fixtures define the cross-target shapes. The portable C reducer is the semantic authority for bounded display state and action validation; a language port may exist for platform boot or tests only if it conforms to the same fixtures and adds no policy. Unknown fields are ignored; malformed known fields are rejected. A display channel has an epoch: after attach or reconnect, the first valid snapshot establishes the reducer baseline; within that epoch sequence must increase strictly, and numeric sequence is never compared across epochs. An action must be capability-advertised, current-state-valid, and reducer-accepted before transport.

### AD-5 — Room-local conversation is not household-wide state [ADOPTED]

- **Binds:** FR-4, FR-10 through FR-12, and FR-22.
- **Prevents:** A response or prompt appearing on unrelated displays or becoming a second assistant conversation.
- **Rule:** Active response text, turn phases, and interactive prompts are published only to the owning appliance/display channel. Household-wide propagation is reserved for an explicitly defined future shared state such as a Departure Card; it must not be inferred from a local turn snapshot.

### AD-6 — Doorways are independently deployable processes [ADOPTED]

- **Binds:** All repository front ends and runtime environments.
- **Prevents:** Premature centralization, shared-process failure coupling, and a hidden cross-front-end state store.
- **Rule:** hermes-relay, hermes-relay-home, the browser kiosk, and ESP/native display targets remain separate deployment units. Hermes is the external session/model/speech authority. This repository does not introduce a shared database, broker, or transcript store. The appliance serves the local display channel; Web/WASM and ESP/native clients connect to it.

### AD-7 — Recovery and shutdown are explicit state transitions [ADOPTED]

- **Binds:** FR-2 through FR-6 and FR-19.
- **Prevents:** Stuck thinking states, duplicate turns, leaked microphone ownership, UI freezes, and silent capture after recovery.
- **Rule:** Blocking capture and playback run outside a UI event loop. Transport loss becomes an honest disconnected/error state and uses bounded reconnect. Shutdown and interruption cancel active capture/turn workers before releasing audio. Recovery starts a fresh session and requires fresh user initiation; it never silently reopens capture or resubmits an unconfirmed turn.

### AD-8 — Secrets stop at the owning process [ADOPTED]

- **Binds:** Configuration, diagnostics, display transport, and local deployment.
- **Prevents:** Bearer-token leakage into displays, logs, snapshots, audio paths, or browser state.
- **Rule:** Hermes credentials remain in the owning local process/profile. Snapshots, actions, diagnostics, and display clients carry no bearer tokens and no unbounded prompt, response, or audio contents beyond their explicit display contract. The display server binds to loopback by default; remote LAN binding is explicit opt-in under the private-pilot trusted-LAN assumption.

### AD-9 — Front-end dependency isolation is the default [ADOPTED]

- **Binds:** Packaging, entry points, development environments, and repository boundaries.
- **Prevents:** A TUI installation dragging in appliance hardware or wake-word dependencies, and speculative repository extraction.
- **Rule:** The base Python install contains the core/TUI path. Voice, wake, hardware, browser, and firmware dependencies remain in optional extras or target-specific build environments, with separate entry points per front end. Keep one repository until a demonstrated package or platform conflict makes an installable hermes-relay-core split cheaper.

### AD-10 — Contract changes require cross-target evidence [ADOPTED]

- **Binds:** shared/display/, all display adapters, and CI/release validation.
- **Prevents:** A schema or reducer change passing in one target while another silently interprets it differently.
- **Rule:** Every shared contract change updates schemas and fixtures together, then runs Python contract tests, portable/native C reducer tests, Web/TypeScript parser or reducer tests, target adapter tests, and the core import-boundary test. A target may add presentation behavior only after the shared contract and reducer semantics are conformant.

## Consistency Conventions

| Concern | Convention |
| --- | --- |
| Naming | Preserve Hermes wire event names in client.py; use normalized snake_case event keys and typed results at the core boundary; use DisplaySnapshot/DisplayAction names for the shared contract; keep UI wording and labels out of the cores. |
| Data & formats | Display JSON uses type, schema, sequence, bounded state values, and explicit capability-gated actions. Prompt options are bounded for embedded targets. turn_id correlates streamed audio and interruption. Unknown future fields are ignored; known malformed fields fail closed. |
| State & mutation | Mutate state only at its owning boundary. Cross-boundary data is an immutable event, snapshot, or validated action. Reducer validation does not mutate on rejection. |
| Errors & recovery | Core code returns normalized events or typed errors; adapters choose wording. Connection loss, stale state, rejected actions, interrupted audio, and failed playback remain distinguishable. Diagnostics are content-safe and never include credentials or message/audio contents. |
| Dependencies | A front end may depend on core contracts and its own platform libraries; a core module may not depend on a front end. Optional extras and target builds isolate microphones, wake engines, firmware, and browser tooling. |
| Validation | Fake sessions and WebSockets cover core behavior without a live Hermes endpoint. Shared fixtures are the conformance seed. Focused tests run before the complete Python suite; Web/WASM and native simulator checks run when their targets change. |

## Stack

| Name | Version |
| --- | --- |
| Python | 3.14.7 |
| Textual | 8.2.8 |
| websockets | 17.1 |
| Svelte | 5.57.0 |
| TypeScript | 5.9.3 |
| Vite | 6.4.3 |
| Vitest | 3.2.7 |
| C display core / LVGL | 8.3.11 |
| Emscripten SDK | 6.0.5 |
| PlatformIO espressif32 | 6.6.0 |

These are brownfield runtime/build baselines observed or pinned on 2026-09-08. They are not permission to upgrade a target without its focused compatibility checks.

## Structural Seed

~~~text
hermes-relay-tui/
  client.py, session.py, config.py, diagnostics.py, audio.py, mic.py,
  wake.py, handsfree.py                 # Python functional core and I/O ports
  app.py, transcript.py, prompts.py,
  session_picker.py                     # Textual TUI adapter/rendering
  home_display/
    appliance.py, server.py, state.py   # household process and display channel
    web/src/                             # Svelte/WebSocket/WASM adapter and surfaces
  shared/display/
    display_*.[ch], *.schema.json,
    fixtures/                            # portable rules and conformance contract
  firmware/esp32-s3-touch-lcd-7/
    main/, simulator/                    # ESP-IDF and native LVGL adapters
  tests/                                 # core, contract, adapter, and integration fakes
  scripts/build_display_wasm.sh         # reproducible WebAssembly build
~~~

~~~mermaid
flowchart LR
    hermes["Hermes endpoint<br/>remote authority"]
    tui["hermes-relay<br/>TUI process"]
    home["hermes-relay-home<br/>appliance process"]
    web["Web/WASM kiosk<br/>same-origin browser client"]
    esp["ESP32 or native simulator<br/>LVGL client"]

    hermes <-->|voice-session WebSocket| tui
    hermes <-->|voice-session WebSocket| home
    home -->|/state snapshots and /action| web
    home -->|LAN state channel and actions| esp
~~~

## Operational Envelope

- Developer and CI validation uses fake Hermes sessions/WebSockets and local contract fixtures; a live endpoint is required only for the explicit text/voice smoke path.
- Desktop TUI and household appliance are installed through separate console entry points. The appliance may hold local microphone and playback resources; the TUI may borrow or own them through the core ports.
- The household display server is loopback-only by default. ESP or remote-browser use requires explicit LAN binding and remains within the trusted private-pilot assumption.
- Hermes URL, client/device identity, profile token, audio devices, reconnect limits, and turn timeouts are runtime configuration. No machine credential or token is part of the repository artifact.
- Reconnects are bounded and observable. A process restart or transport loss returns to a safe idle/disconnected state and requires a fresh user action.

## Capability → Architecture Map

| Capability / Area | Lives in | Governed by |
| --- | --- | --- |
| FR-1–FR-6: voice doorway, turn phases, response, follow-up, clean reconnect | client.py, session.py, voice.py, mic.py, wake.py, handsfree.py, app.py, home_display/appliance.py | AD-1, AD-2, AD-3, AD-7 |
| FR-10–FR-12: ambient/display state, room-local mirroring, disconnected state | home_display/state.py, home_display/server.py, shared/display/, home_display/web/, firmware/ | AD-2, AD-4, AD-5, AD-6, AD-8 |
| FR-19: recovery without a silent turn | session.py, home_display/appliance.py, display adapters | AD-2, AD-6, AD-7 |
| FR-21: TUI as a direct Hermes doorway | app.py, transcript.py, prompts.py, session_picker.py | AD-1, AD-3, AD-7 |
| FR-22: voice-only prompt mirroring and response | client.py, session.py, home_display/appliance.py, shared display contract | AD-3, AD-4, AD-5, AD-8 |
| FR-7–FR-9, FR-13–FR-18, FR-20: device provisioning/arbitration, calendar, physical-device administration, and iOS doorway | Outside this repository or deferred | Revisit when the corresponding cross-repository or device-control boundary is implemented |

## Deferred

- Per-device credentials, provisioning, revocation, authentication, and encrypted display transport. The pilot uses explicit LAN trust; revisit before wider deployment.
- Wake arbitration and proximity signals when multiple physical devices hear the same phrase.
- Media-server ownership, audio framing, backpressure, retention, and transcription boundaries.
- Calendar routing, Immich policy, Departure Card computation, and household-wide context providers.
- iOS profile/device UX and the contract between this repository and the separate iOS client.
- Exact ESP-IDF framework pin and hardware release/CI matrix; PlatformIO currently provides the firmware build seed.
- A central household service, shared database, cross-front-end transcript store, repository rename, or hermes-relay-core extraction. Revisit only after a demonstrated coordination or dependency conflict requires it.
