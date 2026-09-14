---
name: Hermes Relay Multi-Front-End
type: architecture-spine
purpose: build-substrate
altitude: initiative
paradigm: ports-and-adapters with functional cores
scope: "The hermes-relay-tui repository and its cross-repository doorway boundaries: Python Hermes session core and TUI, household appliance, shared display contract and reducer, native LVGL firmware/simulator, Web/WASM kiosk, and native mobile Client integration."
status: final
created: 2026-09-08
updated: 2026-09-13
binds:
  - FR-1 through FR-6
  - FR-7 through FR-9
  - FR-10 through FR-12
  - FR-16 through FR-20
  - FR-19
  - FR-21 through FR-23
  - FR-24 through FR-50
  - FR-51 through FR-53
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
  - ../hermes-relay-ios/_bmad-output/implementation-artifacts/epic-1-context.md
  - ../hermes-relay-ios/_bmad-output/implementation-artifacts/spec-5-1-ios-independent-conversation-doorway.md
  - ../hermes-relay-home/docs/architecture.md
  - ../hermes-relay-home/docs/contracts/v1/README.md
  - ../hermes-relay-home/_bmad-output/planning-artifacts/architecture/architecture-hermes-relay-home-2026-09-12/ARCHITECTURE-SPINE.md
  - ../hermes-relay-home/_bmad-output/specs/spec-profile-mapping-conversation-claims/SPEC.md
  - ../hermes-relay-home/_bmad-output/specs/spec-profile-mapping-conversation-claims/state-machine.md
  - ../hermes-relay-home/_bmad-output/specs/spec-home-bridge-route-roaming/SPEC.md
  - ../hermes-relay-home/_bmad-output/specs/spec-home-bridge-route-roaming/route-session-state.md
  - ../hermes-relay-home/_bmad-output/specs/spec-household-diagnostics-incident-review/SPEC.md
  - ../hermes-relay-home/_bmad-output/specs/spec-household-diagnostics-incident-review/diagnostics-contract.md
  - ../hermes-relay-home/_bmad-output/specs/spec-standard-hermes-compatibility-migration/SPEC.md
  - ../hermes-relay-home/_bmad-output/specs/spec-standard-hermes-compatibility-migration/surface-migration-matrix.md
  - ../hermes-relay-home/_bmad-output/specs/spec-standard-hermes-compatibility-migration/compatibility-and-rollout.md
  - ../hermes-agent-relay-v0.21.0-minimal/plugins/platforms/voice_session/README.md
  - '~/Documents/Vaults/Personal Vault/projects/hermes-home/sources/prds/prd-hermes-home-next-wave-2026-09-13/prd.md'
  - '~/Documents/Vaults/Personal Vault/projects/hermes-home/slices/next-feature-slate-2026-09-13.md'
  - https://pypi.org/project/textual/
  - https://websockets.readthedocs.io/en/stable/
  - https://svelte.dev/docs/svelte/overview
  - https://vite.dev/blog/announcing-vite6
  - https://v3.vitest.dev/guide/
  - https://docs.lvgl.io/8.3/
  - https://emscripten.org/docs/tools_reference/emsdk.html
companions:
  - _bmad-output/planning-artifacts/prds/prd-hermes-relay-tui-2026-09-07/prd.md
  - '~/Documents/Vaults/Personal Vault/projects/hermes-home/sources/prds/prd-hermes-home-next-wave-2026-09-13/prd.md'
  - '~/Documents/Vaults/Personal Vault/projects/hermes-home/slices/next-feature-slate-2026-09-13.md'
  - '~/Documents/Vaults/Personal Vault/projects/hermes-home/sources/prds/prd-hermes-home-next-wave-2026-09-13/.memlog.md'
  - ../hermes-relay-home/_bmad-output/specs/spec-profile-mapping-conversation-claims/SPEC.md
  - ../hermes-relay-home/_bmad-output/specs/spec-profile-mapping-conversation-claims/state-machine.md
  - ../hermes-relay-home/_bmad-output/specs/spec-home-bridge-route-roaming/SPEC.md
  - ../hermes-relay-home/_bmad-output/specs/spec-home-bridge-route-roaming/route-session-state.md
  - ../hermes-relay-home/_bmad-output/specs/spec-household-diagnostics-incident-review/SPEC.md
  - ../hermes-relay-home/_bmad-output/specs/spec-household-diagnostics-incident-review/diagnostics-contract.md
  - ../hermes-relay-home/_bmad-output/specs/spec-standard-hermes-compatibility-migration/SPEC.md
  - ../hermes-relay-home/_bmad-output/specs/spec-standard-hermes-compatibility-migration/surface-migration-matrix.md
  - ../hermes-relay-home/_bmad-output/specs/spec-standard-hermes-compatibility-migration/compatibility-and-rollout.md
---

# Architecture Spine — Hermes Relay Multi-Front-End

## Design Paradigm

Use ports-and-adapters with functional cores.

- The Python core owns Hermes protocol normalization, session and turn lifecycle, configuration, and reusable local I/O ports. It must not import a UI framework or assume a terminal.
- The portable C core in shared/display/ owns bounded display-state and action rules. It has no rendering, transport, device, or clock dependency.
- Adapters compose those cores with WebSocket transports, microphones, speakers, Textual widgets, the household display server, ESP-IDF audio/display I/O, native SDL, browser APIs, and WebAssembly.
- Renderers consume adapter state and emit platform actions. They do not become alternate protocol or display-rule implementations.

~~~mermaid
flowchart TB
    endpoint["Paired endpoints<br/>TUI, phone, display, W/K, ESP"]
    home["Household Home authority + bridge<br/>identity, mappings, grants, arbitration,<br/>redacted observation"]
    hermes["Hermes authority<br/>sessions, model, answers, speech"]
    pycore["Python functional core<br/>client.py, session.py, config.py,<br/>audio/mic/wake/handsfree"]
    ccore["Portable display functional core<br/>shared/display/"]
    render["Surface adapters and renderers<br/>Textual, browser, LVGL, mobile"]

    endpoint -->|device credential| home
    home -->|ordinary Hermes WebSocket<br/>server-held Hermes token| hermes
    hermes -->|JSON, PCM, timing, prompts| home
    home -->|authorized events and redacted views| endpoint
    endpoint --> render
    render --> pycore
    render --> ccore
~~~

## Invariants & Rules

### AD-1 — Core policy is framework- and surface-independent [ADOPTED]

- **Binds:** All core modules and all front ends.
- **Prevents:** Terminal, browser, appliance, or hardware assumptions leaking into reusable behavior.
- **Rule:** Core modules must not import Textual or another front-end framework, and must not assume a terminal, keyboard, scrollback transcript, or human observer. Every front end depends on SessionProtocol; display-capable front ends additionally depend on the shared display contract. Core modules never import app.py, home_display/, browser code, or firmware.

### AD-2 — Each state domain has one owner [ADOPTED]

- **Binds:** FR-1 through FR-6, FR-10 through FR-12, FR-19, and FR-21 through FR-23.
- **Prevents:** Competing mutable state, stale copies, accidental transcript fan-out, and unclear recovery behavior.
- **Rule:** HermesSession owns connection, capabilities, and active-turn protocol facts. Home owns paired-device configuration, credential lifecycle, Wake Mapping/Profile bindings, capability grants, route identity, and wake arbitration, plus bounded ephemeral observation state. A display-capable front-end coordinator owns its local device lifecycle and maps events to its published snapshot. shared/display owns reducer-accepted view, stale-sequence rejection, and action validation. DisplayStatePublisher owns only the latest immutable transport snapshot and sequence. Drafts, queues, presentation state, and optional local history remain surface-local; Home and appliance/display paths do not archive transcripts or raw audio.

### AD-3 — Hermes wire behavior has one adapter boundary [ADOPTED]

- **Binds:** FR-1 through FR-6, FR-19, FR-21, FR-22, and FR-23.
- **Prevents:** Front ends parsing incompatible wire frames, inventing assistant behavior, or replaying turns after uncertain delivery.
- **Rule:** client.py owns hello, streamed turn-event normalization, interrupt/prompt-response frames, unknown-event diagnostics, and typed protocol errors for the Hermes channel. session.py orchestrates one connection and turn lifecycle. The Home bridge may authenticate a device and forward existing Hermes frames, but it does not invent assistant semantics or become a session authority. Front ends consume normalized events through SessionProtocol; they do not parse Hermes frames or invent wire payloads. A turn that may have reached Hermes is never automatically replayed after transport failure.

### AD-4 — Display semantics cross targets through the versioned contract [ADOPTED]

- **Binds:** FR-3, FR-4, FR-10 through FR-12, FR-19, FR-22, and FR-23.
- **Prevents:** ESP, native simulator, Web/WASM, appliance, and future TUI adapters accepting different states or actions.
- **Rule:** display_snapshot.schema.json, display_action.schema.json, and their fixtures define the cross-target shapes. The portable C reducer is the semantic authority for bounded display state and action validation; a language port may exist for platform boot or tests only if it conforms to the same fixtures and adds no policy. Unknown fields are ignored; malformed known fields are rejected. A display channel has an epoch: after attach or reconnect, the first valid snapshot establishes the reducer baseline; within that epoch sequence must increase strictly, and numeric sequence is never compared across epochs. An action must be capability-advertised, current-state-valid, object/turn-fresh, and reducer-accepted before transport. The first choice proof uses the existing structured-prompt contract; any later native `choose`/`explore` extension remains a versioned schema/fixture change, not a renderer-local convention.

### AD-5 — Room-local conversation is not household-wide state [ADOPTED]

- **Binds:** FR-4, FR-10 through FR-12, FR-22, and FR-23.
- **Prevents:** A response or prompt appearing on unrelated displays or becoming a second assistant conversation.
- **Rule:** Active response text, turn phases, and interactive prompts are published only to the owning appliance/display channel by default. An explicitly authorized Watch View may receive one redacted Safe Preview followed by transcript and status for the current session; it cannot receive microphone/audio streams or controls. Household-wide propagation remains reserved for explicitly defined shared state such as a Departure Card; it must not be inferred from a local turn snapshot.

### AD-6 — Doorways are independently deployable processes [ADOPTED]

- **Binds:** All repository front ends and runtime environments.
- **Prevents:** Premature centralization, shared-process failure coupling, and a hidden cross-front-end state store.
- **Rule:** hermes-relay, hermes-relay-home, the browser kiosk, ESP/native display targets, and native iOS/Android Clients remain separate deployment units. Hermes is the session/model/speech authority; Home is the household identity/configuration/authorization authority and may host the edge bridge. This repository does not own a shared household database, broker, or durable transcript store. The legacy appliance adapter remains a migration path while Web/WASM, ESP/native, and mobile Clients adopt the Home service contract.

### AD-7 — Recovery and shutdown are explicit state transitions [ADOPTED]

- **Binds:** FR-2 through FR-6 and FR-19.
- **Prevents:** Stuck thinking states, duplicate turns, leaked microphone ownership, UI freezes, and silent capture after recovery.
- **Rule:** Blocking capture and playback run outside a UI event loop. Transport loss becomes an honest disconnected/error state and uses bounded reconnect. Shutdown and interruption cancel active capture/turn workers before releasing audio. Recovery starts a fresh session and requires fresh user initiation; it never silently reopens capture or resubmits an unconfirmed turn.

### AD-8 — Secrets stop at the owning process [ADOPTED]

- **Binds:** Configuration, diagnostics, display transport, and local deployment.
- **Prevents:** Bearer-token leakage into displays, logs, snapshots, audio paths, or browser state.
- **Rule:** Personal Hermes bearer tokens remain in the Home bridge or other owning server process and never reach paired endpoints. Home-issued device credentials are opaque, per-endpoint, independently revocable, and never enter snapshots, actions, diagnostics, prompts, Watch Views, or audio. The display server binds to loopback by default; remote LAN binding and public routing are explicit configuration, and every route must prove the same paired Household Server identity.

### AD-9 — Front-end dependency isolation is the default [ADOPTED]

- **Binds:** Packaging, entry points, development environments, and repository boundaries.
- **Prevents:** A TUI installation dragging in appliance hardware or wake-word dependencies, and speculative repository extraction.
- **Rule:** The base Python install contains the core/TUI path. Voice, wake, hardware, browser, firmware, and native mobile dependencies remain in optional extras or target-specific repositories/build environments, with separate entry points per front end. Keep one repository until a demonstrated package or platform conflict makes an installable hermes-relay-core split cheaper; do not force native iOS/Android UI, lifecycle, audio, or secure-storage code into this Python repository.

### AD-10 — Contract changes require cross-target evidence [ADOPTED]

- **Binds:** shared/display/, all display adapters, and CI/release validation.
- **Prevents:** A schema or reducer change passing in one target while another silently interprets it differently.
- **Rule:** Every shared contract change updates schemas and fixtures together, then runs Python contract tests, portable/native C reducer tests, Web/TypeScript parser or reducer tests, target adapter tests, and the core import-boundary test. A target may add presentation behavior only after the shared contract and reducer semantics are conformant.

### AD-11 — The ESP32 touch unit is a voice-capable doorway [ADOPTED]

- **Binds:** FR-1 through FR-6, FR-19, and the ESP32 Touch surface stories in Epic 1.
- **Prevents:** Treating the touch unit as a passive display and forgetting its microphone, response-audio, cancellation, or recovery contract.
- **Rule:** The ESP32-S3/LVGL touch unit is a first-class voice-plus-display surface. It captures voice only after authorization is verified, renders its own observed phases and streamed/completed response, and delivers response audio through an explicit bounded audio path. The same ownership rule applies to the W/K browser voice surface when `browser_voice` is advertised: its browser capture and playback bridge may own presentation I/O, but not Hermes answer authority or replay policy. The shared DisplaySnapshot contract governs visual state; audio ingress/egress is a separate contract and must not be smuggled into display JSON. Hermes answer authority and session semantics remain behind the owning session adapter—firmware and browser presentation code do not invent responses, parse Hermes wire frames, or replay uncertain turns. The current ESP32 snapshot/action transport is foundation only until the touch audio path is implemented and validated.

### AD-12 — Native mobile Clients are capability-parity peers [ADOPTED]

- **Binds:** FR-1 through FR-9, FR-16 through FR-20, and the iOS/Android surface stories across Epics 1–3 and 5.
- **Prevents:** Android becoming a reduced conversation-only doorway, iOS silently remaining the only mobile control plane, or the two native Clients drifting on authorization, recovery, device administration, and Local History guarantees.
- **Rule:** iOS and Android are co-equal mobile Client surfaces with parity in user capability and safety behavior: typed and tap-to-speak conversation, observed phases and response audio, profile-bound secure storage, deliberate per-profile Local History, recovery without replay, Device discovery/setup, Room and Wake Mapping configuration, verification, revocation, and explicit re-enrollment. Each native Client owns its platform lifecycle, permissions, accessibility, audio, secure storage, presentation, and local state in its own repository. Both consume the canonical Hermes session/event semantics and shared product contracts through typed adapters; neither parses Hermes wire frames in presentation code, invents unsupported operations, shares credentials or Local History with the other, or claims the other Client's story closure. Exact Android toolchain and repository bootstrap remain deferred until the Android delivery repository is initialized.

### AD-13 — Interactive agent objects are staged and explicit [ADOPTED]

- **Binds:** FR-22 and FR-23, UX-DR18, UX-DR21, and UX-DR23.
- **Prevents:** Treating a Hermes response as arbitrary renderer instructions, allowing a passive mirror or Puck to commit a choice, and confusing exploration with mutation.
- **Rule:** The first proving slice uses a side-loaded Hermes skill and the existing `clarify`/structured-prompt path for bounded harmless selections. It does not claim native per-option `explore`/`choose` semantics. If the proof earns a native choice contract, active ESP32 Touch, direct-use W/K, and TUI surfaces may render it; passive Room Displays mirror read-only and the Puck exposes no choice UI. Any promoted action must be one structured, transcript-visible event bound to Session, turn, object, option, advertised capability, and freshness context; consequence-bearing policy remains separately gated.

### AD-14 — Home is the household authority and the bridge preserves Hermes authority [ADOPTED]

- **Binds:** FR-25 through FR-50, Home contracts, all paired endpoint adapters.
- **Prevents:** A client, display, or household service becoming a competing source of truth for identity, Profiles, sessions, answers, or speech.
- **Rule:** Home owns paired endpoint identity, device credentials, capability grants, Wake Mapping to Profile bindings, route identity, wake arbitration, and bounded authorization fan-out. Hermes owns sessions, model routing, answer content, speech generation, and the voice-session protocol. A Home bridge authenticates the endpoint, validates the Home-owned context, selects the server-side Profile/session context, opens the ordinary Hermes channel with a server-held Hermes token, and forwards existing events without inventing assistant semantics.

### AD-15 — Pairing and roaming prove one logical Household Server [ADOPTED]

- **Binds:** FR-25 through FR-30 and all endpoint route selection.
- **Prevents:** A valid credential being accepted by the wrong household, QR scanning granting access by itself, or a route change silently changing household identity.
- **Rule:** A QR contains only a short-lived, single-use enrollment code. Scanning creates a pending request; explicit approval by a trusted phone or TUI causes Home to issue an opaque per-endpoint credential. Local, Tailscale, and explicitly configured public routes are interchangeable only after they prove the same paired Home identity. Re-enrollment creates a new credential; route loss never replays an uncertain turn.

### AD-16 — Wake claims create one immutable conversation binding [ADOPTED]

- **Binds:** FR-31 through FR-33, wake arbitration, continuous follow-up, and custom wake.
- **Prevents:** Devices choosing arbitrary Profiles, two devices answering one wake, a new wake stealing an active conversation, or a failed detector widening authorization.
- **Rule:** A device submits only a Wake Mapping ID. Home resolves and authorizes that mapping to a Profile, chooses at most one eligible device per wake event, and grants a short-lived claim. The active conversation binds device, mapping, Profile, and Hermes Session until close; follow-ups reuse it, a different wake cannot retarget it, and later wakes start fresh. Custom detectors are endpoint-local, explicitly enabled, and fail closed when unavailable. Home does not promote a loser for the same utterance after a winner fails.

### AD-17 — Capabilities and revocation are checked before every action [ADOPTED]

- **Binds:** FR-34 through FR-36, FR-44, FR-47, FR-50, and endpoint lifecycle.
- **Prevents:** A broad permission silently granting future powers, revoked devices retaining live control, or stale confirmations mutating household state.
- **Rule:** Endpoint permissions are an additive allow-list with no full-access shortcut. Conversation, Watch, notification categories, choice operations, sensitive replacement, and artifact proposal/apply are separate grants. Revocation hard-stops new capture, follow-up, Watch, and notification access and interrupts the active turn when reachable; late frames are ignored and reconnect requires fresh authorization. Consequence-bearing actions require a fresh action-bound confirmation or passcode with current revision/freshness checks.

### AD-18 — Observation and notification fan-out is redacted and ephemeral [ADOPTED]

- **Binds:** FR-37 through FR-44 and all cross-device live-state delivery.
- **Prevents:** Home becoming a transcript archive, private content leaking to a shared display, or notifications creating an unobserved second session.
- **Rule:** The Home bridge may hold a bounded in-memory view of the current session. A permitted Watch View receives one Safe Preview followed by transcript and status only; it receives no microphone, response audio, prompt, interrupt, Profile, or endpoint-control authority. Notifications are separately opted in and category-scoped, never interrupt an active conversation, use household-safe bounded content on shared displays, and expire when stale. Home persists neither Watch transcript nor raw audio.

### AD-19 — Audio/text synchronization follows the playback clock [ADOPTED]

- **Binds:** FR-23 and FR-24, every voice-capable endpoint, streamed response rendering.
- **Prevents:** Text outrunning or lagging behind speech because a client used network arrival or guessed wall-clock pacing.
- **Rule:** Hermes or its timing sidecar owns PCM segment offsets and durations. Each endpoint advances visible response text against audio actually played; validated word spans are optional precision data. Segment timing remains the safe contract through buffering, interruption, reconnect, and fallback. Arrival time is never synchronization authority.

### AD-20 — Sensitive entry stays on the existing structured-prompt path [ADOPTED]

- **Binds:** FR-35, Hermes voice-session clients, TUI and phone secret entry.
- **Prevents:** Secret values becoming ordinary transcript turns, clipboard/history entries, Watch content, or a new security-sensitive channel.
- **Rule:** Reuse Hermes `prompt_request` and `prompt_response` frames with `sensitive=true`. TUI and opted-in phones render masked replacement input; displays and Watch Views cannot answer it. Home forwards the value without storing, logging, or rendering it, and prompt/session/freshness, disconnect, and revocation checks reject stale or duplicate responses.

### AD-21 — Artifact mutation is proposal-first and revision-guarded [ADOPTED]

- **Binds:** FR-49 and FR-50, future file backends.
- **Prevents:** A conversational suggestion silently changing a file or two surfaces applying incompatible edits.
- **Rule:** An artifact proposal names an explicit target, type, current revision, bounded change, visible diff, and apply token. `artifact.propose` and `artifact.apply` are separate permissions; Apply requires explicit confirmation and a matching revision. Home transports authorization and status but does not become the file owner or persist file contents. Each backend is delivered and validated as its own ticket.

### AD-22 — The Home session bridge stays transparent and versioned [ADOPTED]

- **Binds:** FR-24 through FR-36 and all session-bearing paired endpoints.
- **Prevents:** Endpoint-specific Hermes dialects, Home-owned assistant semantics, and a Watch or notification channel accidentally gaining session controls.
- **Rule:** A session-bearing endpoint speaks the existing Hermes voice-session JSON, binary PCM, advertised timing, and structured-prompt shapes through an authenticated Home bridge. Home may add only a versioned authentication/route envelope and enforce Home-owned grants and mapping before opening Hermes; it does not rename Hermes events or invent a second assistant protocol. Watch and notifications use separate redacted Home events and cannot reuse the session stream for controls. Any new bridge frame requires explicit contract and fixture evidence.

### AD-23 — Client diagnostics are safe by default and separate from live turns [ADOPTED]

- **Binds:** FR-51 through FR-53, `diagnostics.py`, endpoint diagnostics adapters, and TUI incident controls.
- **Prevents:** Automatic telemetry becoming a content-export path, a diagnostics outage blocking a conversation, or an incident action replaying an uncertain turn.
- **Rule:** The TUI and other endpoints emit only the versioned Home safe-event envelope automatically, using one correlation ID for endpoint, Home, and Hermes phases. Automatic events may carry timings, route, versions, byte counts, health results, and typed failures, but never prompts, transcripts, audio, credentials, keys, Sensitive Entry values, or private notification content. Explicit incident capture, preview, preservation, and deletion are Home-authorized controls for one device and current task or Session; they use the separate encrypted bundle path and bounded pre-failure ring buffer. The diagnostics path is best-effort and cannot block, mutate, or replay the live Hermes turn.

### AD-24 — Standard Hermes adoption is staged and surface-owned [ADOPTED]

- **Binds:** `SPEC-standard-hermes-compatibility-migration`, FR-23 through FR-27, the TUI transport seam, and the T/P/E/W-K delivery surfaces.
- **Prevents:** A fork removal that silently changes surface behavior, loses local state, or leaves one doorway dependent on an unproved server capability.
- **Rule:** The Standard Hermes Channel is the target. The TUI, Puck, ESP32 Touch, and W/K adapters preserve their existing normalized/session contracts while migrating authentication, route selection, timing capability, and recovery one surface at a time. The legacy fork path remains an explicit rollback path until all required surfaces pass their own conformance and live-smoke gates. No active or uncertain turn changes transport, and absent optional timing remains an honest compatibility state.

## Consistency Conventions

| Concern | Convention |
| --- | --- |
| Naming and identity | Preserve Hermes wire event names in client.py; use normalized snake_case event keys and typed results at the core boundary; use opaque endpoint, Wake Mapping, Profile, session, turn, prompt, object, notification, and revision IDs; a device never supplies an arbitrary Profile ID. |
| Data and formats | Display JSON uses type, schema, sequence, bounded state values, and explicit capability-gated actions. Prompt options are bounded for embedded targets. Existing Hermes JSON/PCM/timing/prompt frames remain the transport seed. Unknown future fields are ignored; known malformed fields fail closed. `turn_id` correlates streamed audio and interruption. |
| State and mutation | Mutate state only at its owning boundary. Cross-boundary data is an immutable event, snapshot, or validated action. Reducer and freshness validation do not mutate on rejection. Proposals never mutate artifacts; Apply requires a current revision. |
| Auth and privacy | Device credentials, Home admin credentials, and Hermes bearer tokens are distinct. Credentials never enter snapshots, actions, logs, Watch Views, notifications, or ordinary transcripts. Sensitive values are masked and replacement-only. |
| Errors and recovery | Core code returns normalized events or typed errors; adapters choose wording. Connection loss, stale state, rejected actions, interrupted audio, and failed playback remain distinguishable. A failed or unavailable route, mapping, detector, capability, or health probe is reported honestly and never broadened by fallback. |
| Dependencies | A front end may depend on core contracts and its own platform libraries; a core module may not depend on a front end. Optional extras and target builds isolate microphones, wake engines, firmware, and browser tooling. |
| Validation | Fake sessions and WebSockets cover core behavior without a live Hermes endpoint. Shared fixtures are the conformance seed. Focused tests run before the complete Python suite; Web/WASM and native simulator checks run when their targets change. Cross-repository contract tests cover pairing, mapping, capability, revocation, timing, and redaction before a new client claims parity. |

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
  ../hermes-relay-home/                   # household authority and Hermes bridge
  ../hermes-relay-ios/                    # native Apple Client boundary
  ../hermes-relay-android/                # future native Android Client boundary
  tests/                                 # core, contract, adapter, and integration fakes
  scripts/build_display_wasm.sh         # reproducible WebAssembly build
~~~

~~~mermaid
flowchart LR
    endpoint["Paired endpoints<br/>TUI, phone, display, W/K, ESP"]
    home["hermes-relay-home<br/>household authority + bridge"]
    hermes["Hermes endpoint<br/>sessions, model, answers, speech"]
    legacy["home_display appliance<br/>migration adapter"]
    surfaces["Surface adapters<br/>TUI, browser, LVGL, mobile"]

    endpoint -->|Home device credential<br/>mapped actions| home
    home -->|ordinary voice-session WebSocket<br/>server-held Hermes token| hermes
    hermes -->|JSON, PCM, timing, prompts| home
    home -->|authorized events and redacted views| endpoint
    endpoint --> surfaces
    legacy -->|migration state/actions| surfaces
~~~

## Operational Envelope

- Developer and CI validation uses fake Hermes sessions/WebSockets and local contract fixtures; a live endpoint is required only for the explicit text/voice smoke path.
- Desktop TUI and household appliance remain separate console entry points during migration. The expanded paired-device path terminates at the Home service, which owns household configuration, authorization, and the ordinary Hermes bridge; the legacy appliance may continue to hold local microphone and playback resources until its doorway adapter is moved behind that contract.
- The household display server is loopback-only by default. ESP or remote-browser use requires explicit LAN binding and remains within the trusted private-pilot assumption. Local, Tailscale, and explicitly configured public routes must prove the same paired Home identity before they are treated as one household server.
- Personal Hermes bearer tokens stay in the Home bridge or another owning server process. Paired endpoints receive only opaque, per-device Home credentials. Hermes URL, client/device identity, Profile routing, audio devices, reconnect limits, and turn timeouts remain runtime configuration; no machine credential or token is part of the repository artifact.
- Home observation and notification fan-out is bounded and ephemeral. Watch receives one redacted Safe Preview followed by transcript/status only; raw audio, response audio, credentials, and durable transcript history remain outside that path.
- Response text that is intended to track speech advances from the playback clock and validated timing data, never from JSON arrival time. A timing sidecar is an adapter fallback, not a second answer or session authority.
- Native iOS and Android Clients store their own profile-bound credentials and Local History locally, use platform permission and audio services, and validate their adapters with deterministic fakes plus platform simulator/device checks. Mobile parity is validated by capability and failure-path evidence, not pixel identity or shared source files.
- Reconnects are bounded and observable. A process restart or transport loss returns to a safe idle/disconnected state and requires a fresh user action.
- Diagnostics are bounded and best-effort. The TUI can expose safe status and
  Home-authorized incident controls, but it never sends automatic content,
  credentials, or raw audio to the review path and never waits for telemetry
  before advancing or recovering a live turn.

## Capability → Architecture Map

| Capability / Area | Lives in | Governed by |
| --- | --- | --- |
| FR-1–FR-6: voice doorway, turn phases, response, follow-up, clean reconnect | client.py, session.py, voice.py, mic.py, wake.py, handsfree.py, app.py, home_display/appliance.py, ESP32 Touch audio adapter | AD-1, AD-2, AD-3, AD-7, AD-11 |
| FR-1–FR-9, FR-16–FR-20: native mobile conversation, recovery, Profiles, Local History, Device administration, and mobile control-plane behavior | `hermes-relay-ios` and future `hermes-relay-android` adapters | AD-2, AD-3, AD-6, AD-7, AD-8, AD-9, AD-12 |
| FR-10–FR-12: ambient/display state, room-local mirroring, disconnected state | home_display/state.py, home_display/server.py, shared/display/, home_display/web/, firmware/ | AD-2, AD-4, AD-5, AD-6, AD-8 |
| 3-I-4: canonical household configuration and simultaneous-wake arbitration | `hermes-relay-home` contract, store, and arbitration engine; TUI compatibility adapter during migration | AD-2, AD-6, AD-8, AD-10 |
| FR-19: recovery without a silent turn | session.py, home_display/appliance.py, display adapters | AD-2, AD-6, AD-7 |
| FR-21: TUI as a direct Hermes doorway | app.py, transcript.py, prompts.py, session_picker.py | AD-1, AD-3, AD-7 |
| FR-22–FR-23: prompt mirroring and typed choice actions | client.py, session.py, home_display/appliance.py, shared display contract, prompts.py | AD-2, AD-3, AD-4, AD-5, AD-8, AD-13 |
| FR-24: text/audio synchronization | Hermes timing frames or timing sidecar adapter, client.py/session.py normalization, audio.py playback clock, TUI/mobile/display response renderers | AD-3, AD-10, AD-19, AD-22 |
| Paired session bridge transport: existing Hermes JSON/PCM/timing/prompt shapes through Home | `hermes-relay-home` bridge and endpoint adapters | AD-3, AD-14, AD-17, AD-22 |
| FR-25–FR-30: route roaming, QR pairing, endpoint credentials, revocation, and re-enrollment | `hermes-relay-home` enrollment/credential/route contract and endpoint pairing adapters | AD-14, AD-15, AD-17 |
| FR-31–FR-33: Wake Mapping to Profile, continuous follow-up, and custom wake | Home mapping/claim/arbitration engine plus endpoint wake adapters | AD-2, AD-14, AD-16 |
| FR-34–FR-36: capability grants, sensitive replacement, and confirmation boundaries | Home grant checks, existing Hermes structured prompts, TUI/phone prompt adapters, endpoint policy | AD-3, AD-17, AD-20 |
| FR-37–FR-39: current-session Watch View and redacted observation | Home ephemeral observation fan-out, display/TUI/mobile Watch adapters | AD-5, AD-14, AD-18 |
| FR-40–FR-41: single-device health check and honest failure reporting | Home health endpoint plus endpoint-local route, credential, session, audio, and display probes | AD-2, AD-7, AD-17 |
| FR-42–FR-44: category-scoped notifications and device-specific delivery rules | Home notification policy/fan-out and platform delivery adapters | AD-5, AD-14, AD-17, AD-18 |
| FR-45–FR-48: bounded typed choices and harmless first proof | Side-loaded Hermes skill using existing `clarify` path first; later native choice contract across active surfaces | AD-3, AD-4, AD-13, AD-17 |
| FR-49–FR-50: proposal-first shared artifacts | Home authorization/status transport plus independently delivered Markdown/calendar/file backends | AD-14, AD-17, AD-21 |
| FR-51–FR-53: automatic safe diagnostics and explicit incident review | `diagnostics.py`, TUI/admin adapters, Home observability and ops sinks | AD-8, AD-14, AD-17, AD-23 |
| FR-7–FR-9, FR-13–FR-18, FR-20: older device provisioning/arbitration, calendar, physical-device administration, and mobile doorway requirements | Outside this repository or deferred | Revisit when the corresponding cross-repository or device-control boundary is implemented |
| FR-13–FR-15: calendar, Departure Card computation, and household-wide context | Outside this repository or deferred | Revisit when the corresponding provider and display boundary is implemented |

## Deferred

- Home credential enrollment, rotation, expiration, revocation propagation, route identity proof, and encrypted transport policy. The authority and credential boundary are settled; the pilot still needs the implementation and failure-path evidence before wider deployment.
- Home-service wake arbitration implementation, acoustic evidence calibration, proximity signals, and the exact custom-detector adapter when multiple physical devices hear the same phrase.
- Media-server/audio-bridge ownership, audio framing, backpressure, retention, and transcription boundaries for Puck and ESP32 Touch.
- Calendar routing, Immich policy, Departure Card computation, and household-wide context providers.
- Native mobile profile/device UX and the contracts between this repository, the separate iOS client, and the future Android client; Android repository bootstrap and exact toolchain remain open until that delivery boundary is initialized.
- Native `explore`/`choose` schema, capability names, freshness/idempotency token, server-side action authority, and consequence-bearing confirmation policy. The first harmless proof remains side-loaded and uses existing `clarify`.
- Notification category taxonomy, delivery acknowledgements, quiet-hours policy, stale TTL, and platform-specific delivery adapters.
- Household Diagnostics implementation details: the Home collector/log/bundle
  stores, trusted capture surfaces, retention enforcement, and endpoint
  preview UI remain in the Slice D specification and owning adapters. The
  safe boundary and no-blocking rule are settled here.
- Health-check vocabulary, safe probe budget, and which endpoint-local checks may run without waking or recording.
- Artifact backend tickets for vault Markdown, calendar, and arbitrary files; each backend needs its own revision and apply evidence.
- iOS profile/device UX and the contract between this repository and the separate iOS client.
- Exact ESP-IDF framework pin and hardware release/CI matrix; PlatformIO currently provides the firmware build seed.
- Further extraction of display/firmware repositories, a repository rename, or a hermes-relay-core package. Revisit only after independent build, hardware CI, release cadence, or dependency evidence requires it.
