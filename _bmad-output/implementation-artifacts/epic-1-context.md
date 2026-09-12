# Epic 1 Context: Have a reliable Hermes conversation

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give every configured Hermes doorway one honest conversation path: authorization and Profile identity are settled before capture or submission, the request crosses one normalized SessionProtocol boundary, observed response phases remain consistent, and transport failure cannot duplicate or silently resume a turn. This includes the audio-only Puck, the voice-plus-display ESP32 Touch doorway, the W/K browser voice-plus-display surface, iOS, Android, and TUI. Passive room Displays consume the same visual semantics without becoming alternate Hermes doorways.

## Stories

- T-1: Authorized TUI initiation
- T-2: Honest TUI phases and response delivery
- T-3: Bounded TUI follow-up and exact `stop`
- T-4: TUI recovery without replay
- T-5: Non-blocking TUI voice-resource teardown
- T-6: Idle relay-loss detection and honest no-replay recovery
- P-1–P-4: ReSpeaker Puck conversation path
- E-1–E-5: ESP32 Touch Display conversation path
- WK-1: Shared Web/iPad voice-plus-display surface
- I-1–I-3: iOS conversation path
- A-1–A-3: Android conversation path

## Surface-specific story ownership — 2026-09-10; Android parity addendum 2026-09-11

Epic 1 is decomposed by delivery surface. The shared SessionProtocol, display
snapshot/reducer semantics, and bounded audio contracts are prerequisites, not
an unowned cross-surface story. A surface story closes only that surface's
acceptance criteria; evidence from another surface does not close it.

| Surface family | Epic 1 story set | Owns |
|---|---|---|
| iOS | `I-1` through `I-3` | Authorized initiation, honest phases with response/audio delivery, and fresh recovery without replay. |
| Android | `A-1` through `A-3` | Feature-parity mobile initiation, honest phases with response/audio delivery, and fresh recovery without replay. |
| ReSpeaker Puck | `P-1` through `P-4` | Authorized wake/capture, status and response audio, bounded follow-up/`stop`, and recovery. |
| ESP32 Touch Display | `E-1` through `E-5` | Authorized voice capture, native phase/response rendering, response audio delivery, bounded follow-up/`stop`, and recovery. |
| Web/iPad (`W/K`) | `WK-1` | One shared browser voice-plus-display surface for authorized capture, honest phases, streamed/completed response text, response audio, and delivery/error state. iPad is not a separate surface story. |
| TUI | T-1–T-6 | The current TUI-specific authorization, phase/delivery, follow-up, lifecycle, idle-liveness, and recovery slices. Numeric aliases remain stable for implementation history. |

The ESP32 Touch story set is not satisfied by the current display snapshot
plumbing alone. Its implementation must add or integrate a bounded microphone
and response-audio path while keeping Hermes response authority and session
semantics behind the owning adapter. `ui_display.c` owns native presentation;
the audio bridge/session boundary remains an explicit Epic 1 implementation
dependency.

## Existing local TUI stories

- T-1: Start an authorized Hermes turn
- T-2: Render honest turn phases and response delivery
- T-3: Continue with bounded follow-up and exact `stop`
- T-4: Recover without replaying an uncertain turn
- T-5: Shut down local voice resources without blocking the TUI
- T-6: Detect idle relay loss and present honest recovery without replaying an uncertain turn

## Requirements & Constraints

- Support an authorized Puck wake, an authorized ESP32 Touch voice initiation, or explicit iOS/Android Client or TUI initiation for a selected Hermes Profile (FR1).
- Fix the selected Profile before Puck, ESP32 Touch, or W/K browser capture or Hermes submission. Unapproved, revoked, unavailable, or unverified identity must fail closed before capture and must not select a fallback.
- Expose normalized session and turn events through the shared SessionProtocol. Front ends must not parse Hermes wire frames or invent assistant responses.
- Preserve one Active Turn per doorway and one initial submission per accepted initiation. A request that may have reached Hermes is never automatically replayed.
- Surfaces expose only observed phases: `heard`, `listening`, `transcribing`, `thinking`, `buffering`, `speaking`, `complete`, and honest Disconnected State. A doorway must not advance or regress before the corresponding event, and completed text remains available when audio is unavailable.
- Any wake-capable adapter uses a separately bounded wake-free follow-up window
  after each successful response; exact `stop` closes local capture silently
  without a replacement turn, and failures never replay. The current Puck
  bridge still accepts one already-transcribed upload and has no follow-up
  capture adapter; the ESP32 Touch transport still has no microphone/session
  path. Their owning stories must adopt the repeated-window contract when
  those adapters are delivered. Blocking capture/playback stays outside UI
  event loops.
- Credentials remain in the owning local process/profile. Raw Puck and ESP32 Touch audio plus shared-device transcripts are transient; only deliberate iOS/Android/TUI Local History may persist by default.
- Developer and CI validation uses fake Hermes sessions/WebSockets and local fixtures. Live text/voice smoke testing is an explicit runtime check, not a test fixture.

## Technical Decisions

- Use ports-and-adapters with a UI-independent Python functional core. `client.py` owns Hermes hello, streamed-event normalization, typed protocol errors, and diagnostics; `session.py` owns one connection and turn lifecycle.
- `HermesSession` is the owner of connection, capabilities, session identity, and active-turn protocol facts. Drafts, queues, presentation, and optional history remain surface-local.
- Keep one receive owner for each WebSocket. Liveness and recovery observe or signal that owner rather than creating competing `recv()` tasks.
- Classify close, timeout, and reader failure through an explicit transport boundary, including the supported legacy websockets compatibility path; unrelated programming exceptions are not network-loss claims.
- Transport loss is an explicit disconnected/error transition. Reconnects are bounded and observable; verified recovery creates a fresh Hermes Session and requires fresh user initiation.
- Runtime URL, identity, Profile token, audio devices, retry limits, and timeouts remain configuration. Do not introduce a shared database, broker, transcript store, or front-end dependency into the core.

## UX & Interaction Patterns

- Show the active Profile from `heard` through completion on the ESP32 Touch console, W/K browser surface, passive Room Display, and iOS/Android/TUI headers; identity explains routing, not answer correctness.
- Use readable child-friendly labels alongside technical phases. Color, motion, and sound support state text but never replace it. The Puck remains status-only; response text and transcript history do not belong on its TFT. The ESP32 Touch Display renders its own response and audio-delivery state.
- Stream the same Hermes response text on text-capable surfaces and play audio only when audio is actually available. If audio fails, preserve usable text and label audio as unavailable; `Retry` reconnects only and never resembles send or replay.
- Keep conversation text and active-turn state Room-local. A passive Display does not capture, speak, create a second Session, or expose touch actions for Hermes prompts in v1; the ESP32 Touch Display or W/K browser surface may capture and speak when it is the selected active doorway.

## Cross-Story Dependencies

- The shared authorization, SessionProtocol, display-state, and bounded-audio contracts establish the boundary consumed by each surface-specific story family.
- The existing local TUI Stories 1.1–1.4 preserve their implementation history; new iOS, Android, Puck, ESP32 Touch, and W/K work is tracked as surface-specific Epic 1 stories rather than inferred from TUI closure.
- T-5 owns local voice-resource lifecycle; T-6 owns relay liveness and transport classification while preserving T-4’s fresh-session/no-replay contract.
- Later room-context epics consume Epic 1’s normalized events and recovery semantics; they must not create alternate protocol paths. A passive Display may mirror an active touch doorway, but must not create a second Session.
- Physical-device credentials, provisioning, revocation, and wake arbitration belong to the separate device-administration work. This epic consumes an authorized configuration and does not invent that system.
