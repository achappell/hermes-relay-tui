---
title: 'Isolate concurrent W/K browser voice sessions'
type: 'feature'
created: '2026-09-12'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'bf60893'
story_id: 'WK-2'
source_story: 'WK-2'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/surface-coverage-matrix.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-wk-1-one-shared-w-k-browser-voice-plus-display-surface-for-author.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-hermes-relay-tui-2026-09-08/ARCHITECTURE-SPINE.md'
  - '{project-root}/home_display/server.py'
  - '{project-root}/home_display/appliance.py'
  - '{project-root}/home_display/web/src/state/channel.ts'
---

<frozen-after-approval reason="human-owned intent — pending Amanda approval">

## Intent

**Problem:** The browser appliance currently has one Hermes session and one
display publisher. Every state WebSocket receives that shared snapshot and
response audio, so a second browser can connect but cannot have an independent
conversation: its turn collides with the first turn, and both browsers see
each other's thinking, answer, and PCM.

**Approach:** Treat each accepted browser state WebSocket as its own temporary
voice/display doorway. The host creates a distinct Hermes session, state
publisher, turn admission guard, prompt-action route, and audio sender for that
connection. The browser remains credential-free; the host reuses the configured
household profile and allowlisted client/device identity while generating a
unique session id. Existing physical-appliance behavior keeps its current
single doorway ownership model.

**Success:** Two or more browsers can stay connected and submit turns at the
same time. Each browser receives only its own snapshots, prompt updates, and
response audio. A turn failure or disconnect in one browser cannot change the
other browser's state, cancel its turn, or deliver its PCM. Reconnecting starts
a fresh verified session and never replays an uncertain turn.

## Boundaries & Constraints

**Always:** Keep the existing same-origin WebSocket frame shapes for
`voice_turn`, audio events, and normalized `{type: "action", schema: 1, ...}`
prompt actions. Give every browser connection one in-flight turn, cancel and
close its Hermes session when the socket goes away, and use per-connection
sequence numbers. Keep bearer tokens and upstream credentials on the host.
Route browser prompt actions through the owning WebSocket; retain the HTTP
action route only for compatibility with surfaces that do not have a
connection-scoped bridge. Bound admission with a configurable maximum (default
eight) so a new client cannot exhaust the host. When the limit is full, close
the new WebSocket with close code `1013` (Try Again Later) and the safe reason
`browser session capacity reached`; the browser reports a capacity state and
uses its existing bounded reconnect delays.

**Ownership:** `Appliance` owns the registry of browser contexts, each
context's `HermesSession`, profile credentials, response/prompt state, and
turn tasks. `DisplayServer` owns sockets, admission slots, per-connection
snapshot/audio/action routing, and transport cleanup; it must not construct or
share Hermes sessions. A slot is reserved before a context's upstream
handshake begins and released on every failed admission or disconnect.

**Never:** Do not broadcast browser snapshots or PCM between connections. Do
not accept a browser-supplied bearer token, upstream session id, or replay
request. Do not add a shared broker, database, cross-process session store,
Hermes wire-event variant, or `DisplaySnapshot` session-id field. Do not make
the current trusted-network pilot an authentication system; per-browser
conversation isolation is the scope here, not household identity or access
control. Do not change the physical/local wake path to use browser session
machinery.

</frozen-after-approval>

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| FIRST_BROWSER | First browser opens `/state` | Host admits it, creates one fresh Hermes session, and sends its own idle snapshot | Failed upstream connect affects only that browser and is retryable by reconnect |
| SECOND_BROWSER | Another browser opens while the first is idle or speaking | Host creates a second independent context; each receives only its own state and audio | Existing context remains untouched if admission or connect fails |
| CONCURRENT_TURNS | Two admitted browsers submit `voice_turn` frames together | Both turns may run concurrently on their respective Hermes sessions | A second turn from one browser is rejected or reported without affecting the other |
| OWNER_ACTION | A browser chooses a displayed prompt option | The action is validated and dispatched to that browser's context/session | A stale or malformed action is ignored/rejected; another prompt remains unchanged |
| OWNER_DISCONNECT | Browser closes during capture, turn, or playback | Its turn is cancelled, its audio route is stopped, and its Hermes session closes | No replay on reconnect; other browsers continue |
| UPSTREAM_FAILURE | One browser's Hermes session fails or returns an error | Only that browser gets the terminal error/disconnected state and audio abort | The uncertain turn is never resent automatically |
| RECONNECT | Browser state channel reconnects after close or refresh | A new temporary context and fresh verified Hermes session are created | Previous conversation and uncertain turn are not resumed |
| AT_CAPACITY | New browser arrives at the configured maximum, including while other handshakes are pending | New WebSocket closes with code `1013` and the safe capacity reason; the browser reports capacity and retries with its existing bounded backoff | No Hermes context is created; admitted clients remain live |
| LEGACY_APPLIANCE | Physical/local appliance path runs without browser voice | Existing single-session publisher, wake, and audio behavior remains unchanged | Browser isolation code is not loaded into the local wake path |

## Code Map

- `home_display/server.py` — socket admission, per-connection state/audio
  routing, receive-loop ownership, cleanup, and HTTP compatibility route.
- `home_display/appliance.py` — `WK-2` context registry, unique session
  creation, per-context lifecycle, and unchanged physical path.
- `home_display/web/src/state/channel.ts`, `bridge.ts`, and `App.svelte` —
  WebSocket action transport and `1013` capacity presentation.
- `tests/test_home_display_server.py`, `test_home_appliance.py`, and the web
  `channel`/`bridge`/`App` tests — isolation, interleaving, cleanup, capacity,
  and regression coverage.
- `epics.md` and `sprint-status.yaml` — formal `WK-2` ownership/status.

## Tasks & Acceptance

**Execution:**

- [x] Add an `Appliance`-owned per-browser context and registry with isolated
  publisher, sender, input tasks, Hermes session, and admission slot; keep
  `DisplayServer` transport/admission-only.
- [x] Create a fresh Hermes session per admitted browser connection using the
  configured household profile without exposing credentials to the browser.
- [x] Move browser response state, PCM, errors, and prompt actions onto the
  owning connection; preserve the physical appliance and compatibility HTTP
  route.
- [x] Add the configurable browser-session limit, WebSocket close code `1013`,
  safe reason, and browser capacity presentation/retry behavior.
- [x] Add fake/integration coverage for two connected clients, simultaneous
  turns, audio unicast, per-owner actions, upstream failure, disconnect
  cleanup, fresh reconnects, and the unchanged local path.
- [x] Add browser transport coverage and run the production web checks.
- [x] Exercise two real browser tabs against the configured Ops endpoint before
  deployment; record the result without recording tokens or user content.

**Acceptance Criteria:**

- Given two browsers connected to the same deployed origin, when both submit
  voice turns concurrently, then both turns can progress independently and
  each browser renders only its own response.
- Given one browser is receiving response PCM, when another browser submits a
  turn, then the PCM header, chunks, end/abort event, and state snapshots are
  delivered only to the owning browser.
- Given one browser has an active turn, when it submits a second turn, then
  only that browser receives the busy/error result; another admitted browser
  can still submit and complete a turn.
- Given a prompt is visible in one browser, when that browser submits a valid
  action, then only its context handles it; an action or stale prompt from a
  different browser cannot answer it.
- Given one browser disconnects or its upstream turn fails, when cleanup runs,
  then its Hermes session, tasks, and audio route are closed without changing
  any other browser's state or cancelling its turn.
- Given a browser reconnects, when the new state socket is admitted, then it
  receives a new session and no prior prompt or uncertain turn is replayed.
- Given the configured browser-session limit is reached, when another browser
  connects, then the new connection closes with code `1013` and does not create
  a Hermes context; existing connections remain unaffected and the browser
  reports capacity while applying bounded retry.
- Given the physical/local appliance path, when it connects and runs a wake
  turn, then its existing session, publisher, wake, and audio tests continue
  to pass.

## Open Questions

None. Browsers use configured household profile and allowlisted
identity in the room, each socket gets a session, and admission defaults to
eight. Live Hermes concurrency is a verification gate; rejection
stops deployment and reopens that contract.

## Review Triage Log

- `high` / `patch` — replaced pseudo-story `WK-1 boundary correction` with
  formal `WK-2`; `WK-1` closure remains unchanged.
- `high` / `patch` — defined `Appliance` as Hermes context owner and
  `DisplayServer` as transport owner, including pending-handshake slots.
- `medium` / `patch` — defined capacity as WebSocket close `1013`, safe reason,
  browser capacity state, and bounded retry.
- `medium` / `patch` — strengthened tests to interleave named A/B fakes, assert
  exact targeted frames and distinct IDs, cancel A, and complete B.
- [blind-hunter B1] A simultaneous factory completion and socket close could
  leak a newly-created browser context — verdict: medium / patch; evidence:
  the close-race branch now closes a completed binding, while the finalizer
  cancels a still-pending factory and the appliance registry removes the
  context only after child cleanup.
- [blind-hunter B2] A stalled browser factory could hold an admission slot
  indefinitely — verdict: medium / patch; evidence: setup is bounded by
  `BROWSER_CONTEXT_SETUP_TIMEOUT`, closes with `1011`, and the timeout test
  verifies the reserved slot is released.
- [blind-hunter B3] A handler cancellation could leave its factory task
  running — verdict: medium / patch; evidence: `factory_task` is initialized
  before the handler `try` block and is cancelled and gathered in the common
  finalizer.
- [blind-hunter B4] Incoming browser frames could create an unbounded task
  flood — verdict: medium / patch; evidence: each connection now caps pending
  callback tasks at `MAX_CONNECTION_TASKS` and closes or cancels the rejected
  awaitable.
- [blind-hunter B5] Timed context shutdown could orphan a child after removing
  it from the registry — verdict: medium / patch; evidence: context cleanup is
  shielded and retained when it exceeds the shutdown budget, and registry
  removal occurs in the context's `finally` block after `child.aclose()`.
- [blind-hunter B6] Stop could arrive before the browser wait event existed —
  verdict: medium / patch; evidence: `run()` creates the event before build and
  honours a pre-existing stop, while `aclose()` also sets it.
- [blind-hunter B7] An injected context-capable server could be mistaken for
  the legacy shared path — verdict: medium / patch; evidence: `DisplayServer`
  exposes `browser_contexts_enabled`, and `_build()` selects isolated mode or
  constructs the legacy session according to that capability.
- [blind-hunter B8] A custom session factory could retain a colliding session
  identity — verdict: medium / patch; evidence: browser-created factory
  sessions receive the generated connection id on the session and exposed
  args object; the real constructor already receives unique profile args.
- [blind-hunter B9] Browser turns omitted structured prompts and gateway setup
  notices — verdict: medium / patch; evidence: `_run_browser_turn()` now
  classifies both event forms, preserves the prompt state, and the browser
  prompt/notice tests exercise the path.
- [blind-hunter B10] Generic prompt actions were dismissed before dispatch was
  known to succeed — verdict: medium / patch; evidence: the owning context now
  dismisses only after a successful or non-false session response; refused
  responses leave the overlay and pending action intact.
- [blind-hunter B11] A same-browser second turn could publish an error over an
  active turn — verdict: medium / patch; evidence: the busy result now retains
  an active display phase and response text, with an exact owner test proving
  the other context remains unaffected.
- [blind-hunter B12] Browser turns lacked the configured timeout — verdict:
  medium / patch; evidence: the context wraps each child browser turn in the
  configured finite timeout and turns a timeout into a terminal error followed
  by owner-only transport closure.
- [blind-hunter B13] A capacity close immediately after `onopen` reset retry
  backoff — verdict: medium / patch; evidence: backoff resets only after the
  first valid hydrated snapshot, and the web test distinguishes a second
  unhydrated `1013` retry from a fresh connection.
- [blind-hunter B14] The legacy HTTP action route could return `200` without
  an isolated owner — verdict: false / reject; evidence: the finding treats
  the deliberately ownerless compatibility endpoint as the browser action
  path; isolated browser actions use the owning WebSocket, while HTTP remains
  available only for legacy callbacks as captured in the approved intent.
- [blind-hunter B15] Isolated audio end/abort and disconnect cleanup lacked
  direct coverage — verdict: low / patch; evidence: server tests now assert
  owner-only `audio_end` and `audio_abort`, and appliance tests cancel an
  active owner turn while the other socket continues.
- [blind-hunter B16] The real Ops task was marked complete although overlapping
  turns were not sent to the deployed service — verdict: medium / defer;
  evidence: the current deployed service predates WK-2, the validation note
  explicitly says the overlap was not attempted, and the required live gate is
  recorded in `deferred-work.md`.
- [blind-hunter B17] `Open Questions: None` conflicted with the live gate —
  verdict: false / reject; evidence: the live test is a verification gate, not
  an unresolved design question, and the approved contract has no remaining
  choice to make.
- [blind-hunter B18] Sprint status was still `in-progress` while the spec was
  in review — verdict: false / reject; evidence: this is the intentional
  pre-Step-5 workflow state; the presentation step synchronizes the tracker to
  `review` after triage.
- [blind-hunter B19] Generated party memory appeared in the product diff —
  verdict: low / patch; evidence: the transient `.memlog.md` was removed from
  the worktree before staging, leaving no party cache in the delivery commit.
- [edge-case-hunter E1] A never-settling browser context setup could consume a
  slot forever — verdict: medium / patch; evidence: same setup-timeout root
  cause as B2; the bounded factory test now proves release.
- [edge-case-hunter E2] A factory that completed in the same turn as socket
  closure could leak its result — verdict: medium / patch; evidence: same
  close-race root cause as B1; completed bindings are explicitly closed.
- [edge-case-hunter E3] Stop could miss an uninitialized browser event —
  verdict: medium / patch; evidence: same lifecycle initialization fix as B6;
  the event exists before startup can yield and is set by shutdown.
- [edge-case-hunter E4] A callback task ignoring cancellation could delay slot
  release — verdict: medium / patch; evidence: connection callback tasks are
  cancelled under a bounded shield and any cleanup that outlives the budget is
  retained rather than blocking admission release.
- [edge-case-hunter E5] Audio sending could continue after its socket had
  disappeared — verdict: medium / patch; evidence: every connection-scoped
  audio method now treats a failed send as a connection error, allowing the
  owning turn to abort instead of silently draining.
- [edge-case-hunter E6] A failed generic prompt response could lose the prompt
  — verdict: medium / patch; evidence: same dispatch-before-dismiss fix as
  B10; both `False` and raised transport failures preserve the pending prompt.
- [edge-case-hunter E7] A voice frame could strand a visible prompt — verdict:
  medium / patch; evidence: an owning context rejects browser turns while a
  prompt action is pending, so the prompt cannot be overwritten by a new turn.
- [edge-case-hunter E8] An injected context server could miss its isolated
  lifecycle — verdict: medium / patch; evidence: same capability-based build
  selection as B7, covered by the context-capable server contract.
- [edge-case-hunter E9] A stale protocol error could mask retryable capacity —
  verdict: medium / patch; evidence: `App.svelte` clears the protocol error on
  `capacity`, and App, surface, and channel tests assert the capacity message.
- [edge-case-hunter E10] Legacy HTTP actions were accepted without a socket
  owner — verdict: false / reject; evidence: this duplicates B14 and describes
  an intentional compatibility route that is not used for isolated browser
  ownership.
- [edge-case-hunter E11] Factory-created browser sessions might share an id —
  verdict: medium / patch; evidence: same returned-session identity correction
  as B8; generated ids are applied to both the adapter and its args when
  writable.
- [verification-gap V1] Session uniqueness was not observed through the real
  server connection — verdict: medium / patch; evidence: the two-browser
  appliance integration now records the server-generated context ids on both
  factory sessions and compares them with the registry.
- [verification-gap V2] Appliance responses were asserted internally rather
  than at the browser socket — verdict: medium / patch; evidence: the
  integration now reads each socket's response snapshot and its owner-only PCM
  frames through the real `DisplayServer`.
- [verification-gap V3] Isolated `audio_end` and `audio_abort` were not tested
  — verdict: medium / patch; evidence: the server isolation test now receives
  exact owner-only end and abort frames and checks the other socket remains
  quiet.
- [verification-gap V4] Prompt actions were not tested through the real server
  route — verdict: medium / patch; evidence: a two-socket integration sends a
  normalized action through the owning WebSocket and proves the other socket
  cannot answer the prompt.
- [verification-gap V5] Busy-state coverage used `any()` across contexts —
  verdict: medium / patch; evidence: the test now identifies each context by
  its session and asserts the busy status belongs to the active owner while
  the other state is not busy/error.
- [verification-gap V6] Failed admission cleanup lacked a slot-release gate —
  verdict: medium / patch; evidence: the factory-failure test waits for zero
  reserved slots and admits a subsequent socket.
- [verification-gap V7] Capacity coverage only exercised pending handshakes —
  verdict: medium / patch; evidence: a fully admitted first socket remains live
  while the second receives `1013`, and the factory is called only once.
- [verification-gap V8] Active browser disconnect cleanup lacked coverage —
  verdict: medium / patch; evidence: a blocked owner turn is cancelled and its
  session closes while the other admitted browser completes a turn.
- [verification-gap V9] Browser `1013` retry and presentation lacked an
  end-to-end assertion — verdict: medium / patch; evidence: channel backoff,
  App stale-error clearing, and the capacity surface message now have focused
  tests.
- [verification-gap V10] Isolated `Appliance.run()` lifecycle was not tested —
  verdict: medium / patch; evidence: a run/stop integration starts the real
  context-capable `DisplayServer` without constructing a shared session and
  verifies clean shutdown.
- [verification-gap V11] Closed bindings remained in the server binding map —
  verdict: medium / patch; evidence: `_forget_connection()` now removes the
  connection binding as part of transport cleanup, while binding close remains
  owned by the handler finalizer.

## Validation Plan

- Run focused Python server/appliance tests and focused web transport tests.
- Assert close code `1013` and no context creation when active or pending
  admissions consume the configured limit.
- Run `npm test -- --run`, `npm run check`, and `npm run build` from
  `home_display/web`.
- Run `../../venv/bin/pytest` from this worktree root.
- Review the diff for tokens, audio captures, generated files, and unrelated
  worktree changes.
- Run the two-tab Ops smoke: connect both tabs, submit overlapping text
  turns, verify independent text/audio, disconnect one tab, and verify the
  other remains usable.

Ops gate record (2026-09-12): the public health probe passed, and two fresh
Chrome tabs both loaded the deployed display in `Ready` state with the expected
browser voice controls. Overlapping voice turns were not sent to the currently
deployed pre-`WK-2` service; the local two-client interleaving, audio-unicast,
failure, busy-turn, prompt-owner, reconnect, and full Python/web checks passed.

## Spec Change Log

- 2026-09-12 — Created after the browser surface exposed shared
  session/state/audio ownership; party review added formal `WK-2`
  traceability, ownership rules, the `1013` capacity contract, and interleaved
  lifecycle test oracles.

## Design Notes

- `WK-2` keeps W/K one Python/Svelte boundary while correcting doorway
  semantics. Fresh sockets follow no-replay; separate conversations are not
  an authentication boundary.
