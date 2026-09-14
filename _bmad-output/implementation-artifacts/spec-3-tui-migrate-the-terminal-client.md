---
title: 'Story 3: Migrate the TUI to the Standard Hermes boundary'
type: 'feature'
created: '2026-09-14'
status: 'done'
baseline_commit: '18b7596e4c674d47430f6d4514fddb1e81245dde'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/surface-coverage-matrix.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
warnings: []
deferred:
  - summary: >-
      Verify that an approved Standard endpoint cannot resume a session under a different Hermes profile than the one requested by the TUI.
    evidence: |-
      The pinned Standard session response does not expose an authoritative profile-ownership field in the local contract or source checkout. The TUI sends the selected profile in session.create/session.resume context, but a live approved endpoint is needed to establish whether the response echoes or otherwise proves that ownership.
    location: >-
      gateway_session.py: _session_context and _apply_session_result
    severity: medium
---

<intent-contract>

## Intent

**Problem:** The TUI still treats the fork's `/voice-session` protocol as its
transport authority. The next-wave Standard Hermes migration needs the terminal
client to use the pinned Standard boundary without losing its existing
presentation, local identity, history, or safe recovery behavior.

**Approach:** Add an explicitly selected Standard gateway adapter behind the
existing `SessionProtocol`. Use `/api/ws` for JSON session traffic and the
separate `/api/audio/speak-stream` sidecar for response PCM, while retaining the
fork path as an explicit rollback/default until the surface gate is proven.

## Boundaries & Constraints

**Always:** Pin behavior to Standard Hermes 0.21.1 at commit
`2237be355906fbe6065ce1815711eee52b2d646e`; keep protocol parsing in core
adapters; give each socket one receive owner; preserve cumulative text,
verified PCM metadata, Profile/device identity, prompt-only local history, and
no-replay recovery; wait for terminal interruption state; expose timing as
absent unless a verified playback-clock/duration contract is used; redact
credentials; choose the path before a turn.

**Never:** Make Standard the default in this story; change the fork wire
contract; invent a Home public envelope or a second Hermes authority; switch
transport during an active or uncertain turn; replay an uncertain prompt;
smuggle commands into model text; expose bearer tokens to logs, history, or
endpoint-facing state; claim live evidence that was not run.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| CONNECT | Standard path selected | Wait for `gateway.ready`, then create/resume a runtime session and expose verified readiness | Fail closed before turns if readiness or session setup fails |
| TEXT_AND_AUDIO | `prompt.submit`, streamed text, sidecar PCM | Preserve normalized text events and feed verified signed-16 PCM through existing playback | Audio failure leaves readable text and marks audio unavailable |
| INTERRUPT | Active Standard turn | Send `session.interrupt` and finish only on matching cancelled/interrupted terminal state | Request acknowledgement alone is not completion |
| DISCONNECT | Prompt may have reached Hermes | Preserve partial output and classify delivery as uncertain | Reconnect without resubmitting; require fresh user action |
| UNSUPPORTED | Prompt/command/timing capability absent | Show a typed unavailable state before collecting or claiming the capability | Never invent a fork replacement or collect sensitive input as ordinary text |
| ROLLBACK | User selects legacy path before a turn | Preserve the existing `/voice-session` behavior | No mid-turn path change |

</intent-contract>

## Code Map

- `config.py`, `config.example.yaml`, `setup_wizard.py`, `profile_cli.py` -- select `voice-session` or Standard explicitly, preserve Profile/device identity, and keep legacy token/config migration reversible.
- `client.py` -- existing fork parser and normalized event semantics; preserve as the rollback adapter rather than teaching the app a second wire dialect.
- `gateway_client.py` -- Standard JSON-RPC `/api/ws` reader, `gateway.ready`, request correlation, liveness, redacted URL handling, and bounded close; the unmerged gateway spike is a read-only implementation reference.
- `gateway_session.py` -- Standard `SessionProtocol` adapter for create/resume, text turns, terminal interrupts, unsupported prompt/command states, stale-session filtering, and no-replay reconnect behavior.
- `gateway_audio.py` -- `/api/audio/speak-stream` sidecar, one reader, signed-16 PCM validation, bounded queues/teardown, audio failure isolation, and `audio_start`/`audio_chunk`/`audio_end` normalization.
- `session.py`, `app.py` -- retain the session seam and existing presentation; expose target/timing capability and preserve ambiguity handling, reload guards, playback-clock captions, and shutdown ownership.
- `history.py`, `audio.py`, `timing.py` -- keep local prompt history and playback timing independent of remote Standard session identity; prevent legacy and Standard paths from colliding in history scope.
- `pyproject.toml`, `AGENTS.md`, `README.md` -- register/document the core adapter and opt-in migration boundary without adding a heavy dependency.
- `tests/test_gateway_client.py`, `tests/test_gateway_audio.py`, `tests/test_gateway_session.py`, plus focused config/session/app/history/timing tests -- fake Standard sockets and regression coverage for the matrix above.

## Tasks & Acceptance

**Execution:**
- `gateway_client.py`, `gateway_session.py`, `gateway_audio.py` and their tests -- bring the Standard JSON, session, interrupt, and sidecar adapters into this branch behind `SessionProtocol` -- keep wire parsing out of presentation and preserve one-reader ownership.
- `config.py`, `config.example.yaml`, `setup_wizard.py`, `profile_cli.py`, `history.py` and tests -- add explicit target/profile migration behavior and path-aware history scoping -- preserve local identity, rollback, and non-destructive history.
- `session.py`, `app.py`, `audio.py`, `timing.py` and tests -- consume the normalized Standard events -- preserve text on audio failure, wait for confirmed interruption, expose timing absence honestly, and never replay after uncertain delivery.
- `pyproject.toml`, `AGENTS.md`, `README.md` -- document the opt-in Standard path and its remaining Home-route/live-evidence boundary -- keep the fork default operational.

**Acceptance Criteria:**
- Given the default configuration, when the TUI connects and completes a turn, then it uses the unchanged fork transport and existing tests remain green.
- Given Standard mode, when the socket emits `gateway.ready` and session creation/resume succeeds, then the TUI reports ready through `SessionProtocol` and uses the returned runtime identity for live requests.
- Given a Standard text turn with sidecar PCM, when deltas and audio arrive, then the existing transcript and playback paths receive normalized events, audio metadata is validated, and timing is either an explicit absence or a verified playback-clock/duration capability.
- Given sidecar failure, when the Standard turn completes, then text remains readable, audio is unavailable, and the submitted prompt is not replayed.
- Given interruption or connection loss, when the event sequence resolves, then cancellation is reported only after terminal confirmation, uncertain delivery remains uncertain, and reconnect requires fresh user initiation.
- Given a path or credential reload while capture, a turn, or a structured prompt is active, then the reload is refused or deferred without switching transport or changing local history.
- Given the focused and complete test commands, when they run in this worktree, then they pass with no whitespace errors; live evidence is recorded only if an approved endpoint is available.

## Spec Change Log

## Review Triage Log

### 2026-09-14 — Review pass
- verdicts: 39 findings — high 4, medium 19, low 4, false 11, maybe-false 1
- findings:
  - `[medium]` `[patch]` Gateway RPC requests could wait forever when a reply never arrived — added a bounded request timeout that fails the connection with a typed transport error and never resubmits the request.
  - `[medium]` `[patch]` A matching JSON-RPC reply with neither `result` nor `error` left its future pending — malformed replies now fail the matching request with `GatewayProtocolError`.
  - `[medium]` `[patch]` A reader that outlived the close timeout lost task ownership — the gateway and audio adapters retain unfinished reader tasks and refuse to open a replacement gateway over one still shutting down.
  - `[high]` `[patch]` Missing or conflicting session identity could admit foreign events — session events now require the active session identity, and conflicting runtime IDs are rejected.
  - `[high]` `[patch]` Delayed events had no ordering guard — the adapter now enforces the pinned Standard per-session sequence and ignores stale lower-sequence frames; the pinned source has no separate server turn ID.
  - `[false]` `[reject]` Runtime/durable ID selection was reported as silently preferring the wrong ID — the two runtime aliases are now checked for conflict, while `stored_session_id` and `session_key` are distinct durable fields by the Standard response contract.
  - `[maybe-false]` `[defer]` Resumed or created sessions were not proven to belong to the requested Hermes profile — the local Standard response has no authoritative profile-ownership field; a live approved endpoint response is required, recorded in `deferred`.
  - `[false]` `[reject]` Standard session context was reported as losing client/device identity — the pinned gateway contract accepts the TUI source, Hermes profile, and title; legacy `client_id`/`device_id` belong to the fork hello contract and adding them would invent Standard parameters.
  - `[false]` `[reject]` Gateway session listing was reported to omit usable search/profile behavior — the TUI asks the Standard gateway for the session list without a search term and the existing picker performs local filtering; the pinned `session.list` surface does not define a profile parameter.
  - `[medium]` `[patch]` `GatewaySession.send_prompt_response` did not match the full `SessionProtocol` signature — added the optional operation, object, and freshness fields while retaining the explicit unsupported result.
  - `[medium]` `[patch]` The gateway had only WebSocket control pings — added the Standard `gateway.ping` application heartbeat to the disconnect observer.
  - `[false]` `[reject]` Capabilities were reported as being discarded — the pinned `gateway.ready` source exposes heartbeat/replay metadata rather than a capability set, and `session.interrupt` is part of the selected Standard boundary; no unsupported capability claims are fabricated.
  - `[false]` `[reject]` Optional speech timing was reported as accepted without verification — timing records are structurally validated and unsafe alignment degrades to explicit duration fallback; absent timing produces no timing event, matching the pinned baseline’s honest absence rule.
  - `[medium]` `[patch]` Audio metadata ignored byte order — non-little-endian sidecar PCM is now rejected as unavailable.
  - `[false]` `[reject]` A terminal audio frame without PCM was reported as valid playable audio — the sidecar contract requires usable signed 16-bit PCM or a fallback; an empty stream is correctly unavailable.
  - `[false]` `[reject]` Standard text deltas were reported to use a missing `delta` field — the pinned source emits `message.delta` payload `text`; `text_delta` is the normalized client event, not a second Standard wire shape.
  - `[medium]` `[patch]` `/voice` controls could be smuggled into Standard `prompt.submit` — gateway mode now reports the controls as unsupported locally without sending model input.
  - `[medium]` `[patch]` Switching transports could retain the previous known endpoint path — setup normalization and profile editing now translate `/voice-session` and `/api/ws` when the selected transport changes.
  - `[false]` `[reject]` Explicit prompt rejection was reported as incorrectly ambiguous — post-admission failures remain deliberately non-retryable because no replay is safe; the conservative ambiguity state is the no-replay contract.
  - `[medium]` `[patch]` The gateway request timeout finding was independently reported by the edge reviewer — the same bounded request path and typed failure fix covers it.
  - `[medium]` `[patch]` Closing the audio sidecar could strand a consumer awaiting `next_event` — close now queues the transport sentinel after setting the closed state.
  - `[medium]` `[patch]` Closing the gateway could discard a still-running reader — unfinished reader ownership is retained and a replacement connection is refused until it exits.
  - `[medium]` `[patch]` Closing the audio sidecar could discard a still-running reader — the sidecar retains the unfinished reader task through the same bounded teardown.
  - `[high]` `[patch]` A late same-session event could be attributed to a new turn — missing identity is rejected and monotonic per-session sequence filters delayed frames.
  - `[high]` `[patch]` Interrupt could race ahead of `prompt.submit` — a pre-submission interrupt now cancels the local generator before any prompt is sent; once submission begins, the typed remote interrupt path remains authoritative.
  - `[medium]` `[patch]` A legacy configured history path could be shared by fork and gateway turns — gateway launches now use the gateway-scoped destination and may migrate the old fork path without mixing future entries.
  - `[medium]` `[patch]` Profile edit could store gateway transport with `/voice-session` — edit now normalizes the retained endpoint for the selected transport.
  - `[medium]` `[patch]` The edge reviewer repeated the prompt-response signature concern — the full protocol signature is now accepted and deliberately returns unsupported.
  - `[false]` `[reject]` Gateway search was reported as ignored in a user-visible path — the app’s session picker deliberately retrieves the list and filters it locally; no gateway search request is needed.
  - `[false]` `[reject]` Standard session creation was reported to lose configured client/device identity — those fields are not part of the pinned Standard create/resume context, and the TUI does not invent an unapproved wire extension.
  - `[low]` `[patch]` Default transport routing lacked a real no-factory seam assertion — added a test proving ordinary args construct `HermesSession`, not `GatewaySession`.
  - `[medium]` `[patch]` Reload lacked an app-level transport-switch assertion — added coverage proving `/reload` replaces the old session and installs gateway-targeted args.
  - `[low]` `[patch]` Gateway session switching lacked direct adapter coverage — added a test proving durable resume ID, runtime identity, and returned history are applied.
  - `[low]` `[patch]` Root gateway configuration lacked a parser round-trip assertion — added coverage for root `transport` and `hermes_profile` values.
  - `[medium]` `[patch]` Standard setup probing was only covered through `--no-check` — added fake-socket success and missing-runtime failure coverage for the gateway probe.
  - `[medium]` `[patch]` Pending RPC behavior during socket loss lacked an assertion — added coverage that the pending request fails with `GatewayTransportError`.
  - `[low]` `[patch]` Profile CLI bare-host normalization lacked coverage — added gateway create coverage asserting `/api/ws` is persisted.
  - `[medium]` `[patch]` Gateway audio failure pacing lacked an app-level assertion — added coverage proving a sidecar failure releases text held behind the first-word bridge.
  - `[false]` `[reject]` Intent alignment questioned the selected surface and process — repository evidence maps next-wave Story 3 to `[TUI] Migrate the terminal client`; the fresh worktree, latest-main baseline, and rendered `bmad build auto` workflow were verified during execution, while the diff correctly contains fake-only tests because no approved live endpoint was available.

## Auto Run Result

Status: done.

Summary: Implemented the next-wave Standard Hermes migration for the terminal TUI behind an explicit `gateway` transport. The fork `/voice-session` transport remains the default and rollback path. The new adapter owns one-reader JSON-RPC gateway traffic, session create/resume/list/switch, typed interruption, sequence and identity filtering, and the separate Standard audio sidecar. Configuration, setup, profile editing, history isolation, app routing, timing fallback, and audio-failure presentation now consume the adapter without changing the existing `SessionProtocol` boundary.

Files changed:

- `gateway_client.py`, `gateway_session.py`, `gateway_audio.py` — Standard gateway, session, and sidecar adapters.
- `config.py`, `setup_wizard.py`, `profile_cli.py`, `history.py` — opt-in transport/profile setup, endpoint migration, and history isolation.
- `app.py`, `pyproject.toml`, `README.md`, `AGENTS.md`, `config.example.yaml` — TUI routing, packaging, operational documentation, and contract notes.
- `tests/test_gateway_*.py`, `tests/test_app.py`, `tests/test_config.py`, `tests/test_setup.py`, `tests/test_profile_cli.py`, `tests/test_history.py`, `tests/test_core_boundary.py`, `tests/test_relay_profiles.py` — focused Standard and regression coverage.
- `_bmad-output/implementation-artifacts/spec-3-tui-migrate-the-terminal-client.md` — story specification, verification, and review record.

Review findings breakdown: 27 findings patched (4 high, 19 medium, 4 low), 1 medium finding deferred pending approved live profile-ownership evidence, and 11 findings rejected as false with the contract/source refutation recorded above. No bad-spec or intent-gap loopback was required.

Follow-up review recommendation: true. This first pass patched high-severity event-ordering and interrupt-race findings. The specific remaining risk is the deferred live verification that a Standard endpoint cannot resume a session under a different requested Hermes profile.

Verification performed:

- `venv/bin/pytest -q tests/test_gateway_client.py tests/test_gateway_audio.py tests/test_gateway_session.py tests/test_setup.py tests/test_profile_cli.py tests/test_config.py tests/test_app.py` — passed.
- `venv/bin/pytest -q` — `1276 passed, 1 skipped`.
- `git diff --check` — passed.
- No approved live Standard endpoint was available, so live text, voice, interrupt, and reconnect checks remain documented manual follow-up rather than invented evidence.

Residual risks: the approved Home credential and route remain outside this TUI-owned slice; live Standard endpoint behavior and profile ownership still require the shared Home bridge contract and an approved endpoint.

## Design Notes

The existing `feat/vanilla-hermes-connection-spike` contains useful adapter
work, but its direct query-token gateway is proof of the pinned Standard wire,
not permission to invent a Home endpoint. Port only the TUI-owned seams. The
Home bridge and device-credential route remain an explicit future integration
boundary until the Home route contract is delivered.

## Verification

**Commands:**
- `venv/bin/pytest -q tests/test_gateway_client.py tests/test_gateway_audio.py tests/test_gateway_session.py tests/test_config.py tests/test_session.py tests/test_app.py tests/test_history.py tests/test_timing.py tests/test_core_boundary.py` -- expected: focused Standard adapter and regression suite passes.
- `venv/bin/pytest -q` -- expected: complete TUI suite passes.
- `git diff --check` -- expected: no whitespace errors.

**Manual checks (when the approved endpoint is available):**
- Run one Standard text turn, one voice turn, one confirmed interrupt, and one disconnect/reconnect scenario; verify route selection, timing capability, audio failure wording, and no-replay behavior without exposing the token.
