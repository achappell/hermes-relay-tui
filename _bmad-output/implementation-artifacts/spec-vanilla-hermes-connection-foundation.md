---
title: 'Use the upstream Hermes gateway WebSocket as an opt-in TUI transport'
type: 'feature'
created: '2026-09-12'
status: 'done'
baseline_commit: 'd795303aa1142a013b6a269856c3dee8ccc01e7d'
route: 'dispatch'
review_loop_iteration: 1
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/surface-coverage-matrix.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-4-recover-without-replaying-an-uncertain-turn.md'

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The TUI currently depends on the fork's custom `/voice-session` hello/turn protocol. Upstream Hermes already exposes the standard `/api/ws` JSON-RPC gateway, so this slice must prove whether the TUI can use that channel without changing the agent fork.

**Approach:** Add an explicitly selected gateway transport that implements the existing `SessionProtocol`. It uses one JSON-RPC WebSocket reader, correlates replies by request ID, normalizes ordinary text-turn events into the existing TUI events, and leaves the current voice-session transport as the default. It reuses the existing token source through the gateway's legacy query-token mode with redacted logging.

**Decision:** In gateway mode, `/session new ARG` sends `ARG` as the standard session title. Hermes owns the runtime and durable session IDs.

## Boundaries & Constraints

**Always:** Require `gateway.ready` plus successful session create/resume before reporting ready; send `source: "tui"`; pass a Hermes profile only from a dedicated setting; keep parsing in core modules; preserve inline text, liveness, redaction, and no-replay recovery; keep gateway mode opt-in through `--transport gateway`; never log the token-bearing URL.

**Never:** Change the Hermes fork or invent a gateway method; change the voice-session wire contract; add a second WebSocket reader; replay a submitted prompt after loss; make gateway mode the default; implement structured-prompt parity, picker free-text search, ticket/cookie login, response audio, files, attachments, command dispatch, event replay, or mobile/appliance integration in this slice.

## I/O & Edge-Case Matrix

| Scenario | Expected behavior |
|---|---|
| CONNECT | Wait for `gateway.ready`; create a fresh doorway session or resume a requested durable session; use the returned runtime ID for live RPCs and returned `messages` for history. |
| TEXT_TURN | Send `prompt.submit`; normalize session-scoped `message.start`, `message.delta`, `message.interim`, reasoning/thinking, tool, status, and `message.complete` events. `complete` ends once; `cancelled`/ `interrupted` becomes `turn_interrupted`; `failed` becomes an error. Ignore other sessions. |
| INTERRUPT | Send `session.interrupt`, but wait for `message.complete` with `cancelled` or `interrupted` before ending the local turn. An acknowledgement alone is not cancellation. |
| CONNECTION_LOSS | Preserve partial output, mark the turn uncertain, reconnect without resubmitting it, and retain FIFO order for unsent prompts. |
| UNSUPPORTED_PROMPT | If a standard structured-prompt request appears, show a typed unsupported-capability error, do not collect or log a value, and interrupt the turn so it cannot remain blocked. If cancellation is not confirmed, classify the session as uncertain. |

</frozen-after-approval>

## Code Map

- `client.py` -- existing custom voice-session adapter; preserve it and its default wire behavior.
- `gateway_client.py` -- new framework-free JSON-RPC boundary: ready event, request/reply correlation, one receive task, event queue, close/liveness, and safe errors.
- `gateway_session.py` -- new `SessionProtocol` adapter for session create/resume/list, titled new sessions, text turns, interruption, and shared microphone lifecycle; keep runtime IDs live and durable keys for resume.
- `session.py`, `config.py`, `app.py` -- reuse the existing session contract and event consumer; add explicit `--transport {voice-session,gateway}` selection with the current transport as default. Gateway auth appends the existing token only in legacy query-token mode and redacts it.
- `AGENTS.md`, `tests/test_core_boundary.py`, and gateway/client/session tests -- register the new core modules and prove ordering, normalization, interruption, loss, defaults, and selection with fake sockets.
- `README.md` -- document the opt-in, text-first gateway proof and its deliberate feature boundaries.

## Tasks & Acceptance

**Execution:**

- [x] Implement the single-reader JSON-RPC client without touching the fork-specific client.
- [x] Implement the gateway `SessionProtocol` adapter: `source: "tui"`, titles, runtime/durable identity, history, text events, interruption, and safe unsupported-prompt cancellation.
- [x] Add explicit transport selection and gateway-only legacy query-token handling while preserving current defaults and recovery.
- [x] Update the core-boundary inventory and add fake-socket tests for the matrix plus relevant existing client/session regressions.
- [x] Document setup, authentication expectations, and the deferred prompt/search/audio boundaries.

**Acceptance Criteria:**

- Default configuration still uses the voice-session client and emits the same wire frames.
- Explicit gateway mode reaches ready only after `gateway.ready` and a successful standard session RPC, with no token in logs.
- Gateway session creation/resume uses the correct source/profile context, returns normalized history, and uses runtime IDs for live traffic; `/session new ARG` uses `ARG` as title.
- A typed gateway turn keeps streamed text inline, keeps activity replaceable, ignores unrelated sessions, and produces exactly one terminal event.
- Interrupt waits for standard cancelled/interrupted completion; connection loss preserves ambiguity and never resubmits the prompt.
- An unexpected structured prompt fails visibly, avoids value capture, and cannot leave the server turn silently blocked.
- Focused tests, the core-boundary test, and the complete suite pass; no agent-fork file changes exist.

## Implementation Notes

The gateway sends replies and events over the same socket, so only `gateway_client.py` reads it. The adapter keeps the runtime `session_id` for current traffic and the durable `stored_session_id`/`session_key` for later resume. Standard `session.list` is limited to basic listing in this slice; free-text picker filtering is deferred.

Gateway auth uses legacy `?token=` rather than the custom Authorization header. Ticket/cookie auth and `/api/audio/speak-stream` are later slices; the local relay profile is never silently reused as a Hermes server profile.

## Spec Change Log

- Review 1: corrected interruption and identity semantics, made transport/auth/core-boundary requirements explicit, then split prompt parity and picker search into deferred work.

## Review Triage Log

- Fixed: terminal/event identity and profile routing; deferred prompt parity and picker search to `deferred-work.md`.
- Review-runner limitation: blind, edge, and verification workers were attempted twice against a stable diff; the edge worker returned no analyzable input and the other workers timed out. No automated findings were available, so the local diff audit and complete test suite are the review evidence for this slice.

## Verification

- Focused gateway/core suite: `uv run --no-project --with pytest --with pytest-asyncio --with textual --with websockets --with python-dotenv --with PyYAML --with jsonschema --with sounddevice --with numpy --with faster-whisper python -m pytest tests/test_gateway_client.py tests/test_gateway_session.py tests/test_config.py tests/test_app.py tests/test_core_boundary.py tests/test_client.py tests/test_session.py` (87 passed)
- Complete suite: `uv run --no-project --with pytest --with pytest-asyncio --with textual --with websockets --with python-dotenv --with PyYAML --with jsonschema --with sounddevice --with numpy --with faster-whisper python -m pytest` (1101 passed, 1 skipped)
- `git diff --check`
- Not run: live `/api/ws` turn, interrupt, and disconnect against a configured Hermes endpoint; this requires a real endpoint and token.
