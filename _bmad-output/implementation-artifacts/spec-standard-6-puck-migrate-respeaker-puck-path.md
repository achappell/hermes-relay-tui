---
id: STANDARD-6-PUCK
title: Migrate the ReSpeaker Puck path to the Standard Home boundary
type: feature
created: 2026-09-14
status: in-progress
baseline_commit: ea54552dc65e327fb264e161f2d25bff8d3feb90
github_issue: https://github.com/achappell/hermes-relay-tui/issues/183
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/surface-coverage-matrix.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
warnings:
  - 'The public Home bridge route is not live in the current Home revision; deterministic fake-bridge evidence is the only available integration evidence.'
deferred:
  - summary: 'Run the approved Home-route and physical Puck round trip after Home NW-01, NW-02, and NW-03 are delivered.'
    evidence: 'Home bridge contract and Home tracker show the endpoint route as planned; this checkout has no approved route or paired production credential.'
    location: 'puck_bridge/home_session.py; firmware/respeaker-lite/README.md'
    severity: high
---

# Standard-6 — Puck migration

## Scope

Move the Puck voice path behind the paired Home bridge and pinned Standard
Hermes boundary. Puck remains an audio and status surface, not a control plane.

## Acceptance

- The Home-side Puck adapter sends only its paired Device credential and
  opaque conversation binding to Home; the Puck firmware never receives the
  personal Hermes bearer.
- Standard response audio, bounded follow-up, exact `stop`, interruption,
  reconnect, and no-replay behavior are preserved.
- Raw PCM diagnostics remain explicitly opt-in and bounded.
- Hardware evidence covers wake, capture, playback, failed-closed identity,
  and clean shutdown.

## Dependencies

HOME-NW-01, HOME-NW-02, HOME-NW-03, and the existing Puck audio hardening
stories.

## Intent

The Puck bridge must be able to use the Home-owned Standard boundary without
turning the Puck into a control plane or exposing a Hermes bearer credential.
The existing direct Hermes bridge remains the default rollback path until the
Home route and live evidence are available.

## Boundaries & Constraints

**Always:** use the planned `wss://.../api/v1/bridge/ws` route; authenticate
with `Authorization: Device <credential>`; send the opaque conversation handle
and current prompt through Home JSON-RPC `schema: 1`; give the socket one read
owner; validate route readiness, turn identity, and signed 16-bit little-endian
PCM metadata; preserve no-replay behavior after uncertain delivery; keep
capture/playback and local wake/stop policy on the Puck side.

**Never:** put the Home credential in a URL or JSON body; send a Hermes bearer
from this process; invent a direct-Hermes fallback when Home mode is selected;
replay an uncertain prompt; let a global or stale event complete the active
turn; treat an interrupt acknowledgement as the terminal outcome; claim live
Home or hardware evidence from fake fixtures.

## I/O & Edge-Case Matrix

| Scenario | Input / state | Expected behavior | Failure handling |
| --- | --- | --- | --- |
| CONNECT | Home mode with paired credential and opaque handle | Open the pinned route, send `conversation.open` or `conversation.reconnect`, and accept only a ready result with an approved route | Missing pairing, insecure/wrong URL, unavailable result, or malformed readiness fails closed |
| PROMPT | Fresh non-empty Puck transcript | Send one `prompt.submit` and require Home's `turn_id` before consuming response frames | Typed `request_rejected` remains known non-delivery; transport failure is uncertain and is never replayed |
| AUDIO | `audio.frame` start, binary PCM, end | Validate schema, turn binding, mono signed-16 little-endian metadata, sample boundaries, and preserve ordered chunks | PCM before start, after end, duplicate start, invalid metadata, fallback, or incomplete sample becomes unavailable |
| STALE | Foreign handle, foreign turn, or global event | Ignore it; only the active turn can produce terminal completion | No stale or global event can retarget or complete the turn |
| INTERRUPT | Active Home turn | Send `session.interrupt` when advertised; wait for the matching terminal event in the stream | An acknowledgement alone is not completion; unsupported interruption stays typed and local |
| DISCONNECT | Prompt may have been accepted | Mark delivery uncertain and reconnect with `conversation.reconnect` | Require a fresh Puck capture; never submit the old prompt again |
| ROLLBACK | Legacy transport selected before a turn | Preserve the existing direct Hermes bridge | No transport switch occurs during an active or uncertain turn |
| DIAGNOSTICS | Debug logging enabled | Log method names, keys, sizes, and safe status only | Never log credential, conversation text, raw PCM, or bearer material |

## Code Map

- `puck_bridge/home_session.py` — Home Device-header authentication, one-reader
  JSON-RPC client, opaque conversation open/reconnect, prompt submission,
  ordered event/audio normalization, interruption, and no-replay state.
- `puck_bridge/server.py` — explicit `--transport legacy|home` selection,
  private credential/handle resolution, and fail-closed Home startup while
  retaining the local firmware upload boundary.
- `config.py` — private environment resolution for
  `HOME_DEVICE_CREDENTIAL` and `HOME_CONVERSATION_HANDLE`.
- `tests/test_puck_home_session.py`, `tests/test_puck_bridge.py`,
  `tests/test_config.py` — fake Home socket, protocol/audio edge cases,
  reconnect/no-replay, parser, and private-config coverage.
- `firmware/respeaker-lite/README.md` — opt-in operator path and the explicit
  live-route/hardware evidence gate.

## Tasks & Acceptance

- [x] Add a single-reader Home bridge adapter behind the existing Puck
  `SessionProtocol`-shaped turn seam.
- [x] Add explicit Home transport selection and private credential/opaque
  handle resolution without changing the legacy default.
- [x] Preserve typed audio framing, terminal-event ownership, interruption
  acknowledgement semantics, reconnect, and no-replay behavior in fake tests.
- [x] Document the Home route, credential boundary, rollback, and evidence
  limitation without claiming a live deployment.
- [ ] **Deferred external gate:** after HOME-NW-01/02/03, exercise one approved
  Home text/audio round trip on physical Puck hardware, including wake,
  capture, playback, failed-closed identity, interruption, reconnect, exact
  `stop`, bounded follow-up, and clean shutdown.

## Verification Record

- `venv/bin/pytest -q` — **1,371 passed**, 6 warnings.
- `venv/bin/pytest -q tests/test_puck_home_session.py tests/test_puck_bridge.py` — **164 passed**.
- `venv/bin/python -m compileall -q puck_bridge config.py tests/test_puck_home_session.py` — passed.
- `git diff --check` — passed.
- Live Home route, production credential, and physical Puck evidence — **deferred**; no approved endpoint is available in this checkout.

## Review Triage Log

The blind, edge-case, and verification-gap review ran against the complete
implementation diff, including the new untracked adapter and tests. Each
finding is retained here; overlapping findings remain separate so the review
record is auditable.

| ID | Finding | Disposition |
| --- | --- | --- |
| BL-01 | Home JSON schema was not validated on every frame. | **Patched:** `HomeBridgeClient` validates the top-level schema; readiness, prompt, event, audio, interrupt, and ping results validate their Home schema. |
| BL-02 | Readiness could replace the configured opaque conversation handle. | **Patched:** readiness must return the exact configured handle; no retargeting is accepted. |
| BL-03 | Prompt results lacked complete schema, handle, status, and turn validation. | **Patched:** `_validate_prompt_result` requires all four; malformed results close the ready binding. |
| BL-04 | Event and audio frames could omit or change conversation identity. | **Patched:** events require the configured handle and foreign events are ignored; audio identity is required and foreign audio fails closed. |
| BL-05 | Payload turn IDs could be confused with the Home envelope turn ID. | **Patched:** correlation uses only the Home event envelope and rejects conflicting envelope identities. |
| BL-06 | Binary PCM split at a transport boundary could be rejected as odd-sized. | **Patched:** one-byte remainders are buffered across binary frames and rejected only at audio end; split and incomplete-sample tests cover it. |
| BL-07 | Sample rate had no upper bound. | **Patched:** audio accepts positive rates through 384 kHz, matching the Home audio boundary; higher rates are typed failures. |
| BL-08 | Audio fallback could end the turn before later text arrived. | **Patched:** fallback/unavailable audio yields `audio_abort`, keeps consuming text, and still requires the terminal event. |
| BL-09 | Standard event types and final message semantics were being dropped or collapsed. | **Patched:** normalization preserves message completion, reasoning, prompt, tool, notification, background, and unknown event shapes while retaining the existing SessionProtocol vocabulary. |
| BL-10 | Cumulative rendered previews could duplicate already-emitted text. | **Patched:** suffix/replacement logic mirrors the Standard client; a cumulative-preview regression test asserts only the new suffix. |
| BL-11 | Structured prompts were advertised despite the Puck having no response path. | **Patched:** Home Puck reports `supports_structured_prompts = False`; the capability is asserted in tests. |
| BL-12 | Interrupt could be sent without an advertised capability. | **Patched:** `interrupt_active_turn` gates on `supports_interrupt` and validates the acknowledgement; the capability/ack path is tested. |
| BL-13 | RPC delivery classification could replay an uncertain prompt. | **Patched:** uncertain transport codes close the binding and raise a transport error; only known `request_rejected` stays connected, with no replay test. |
| BL-14 | A malformed prompt result could leave the session appearing ready. | **Patched:** protocol failure closes the client and marks reconnect required; dedicated test covers the wrong-handle result. |
| BL-15 | The notification queue was unbounded. | **Patched:** the single-reader queue is capped at 128 frames and turns queue overflow into a protocol failure. |
| BL-16 | No Home application ping was exposed. | **Patched:** `HomePuckSession.ping()` sends `bridge.ping` with the opaque handle and validates the response; tested with a fake reply. |
| BL-17 | URL validation allowed credentials, query data, fragments, or an arbitrary route. | **Patched:** Home URLs require `wss`, the exact bridge path, and no userinfo/query/fragment. |
| BL-18 | The verification record did not yet prove the full suite. | **Verified:** the final full-suite run passes 1,325 tests; the provisional focused count is replaced above. |
| EC-01 | URL userinfo/query/fragment acceptance repeated BL-17. | **Covered by the same patch and URL test; retained as a duplicate review finding.** |
| EC-02 | Readiness accepted malformed or unapproved route objects. | **Patched:** route class is limited to `home`, `tailscale`, or `public`, and route identity must be a non-empty string; malformed-route cases are tested. |
| EC-03 | Home mode could resolve a Hermes bearer through the legacy profile path. | **Patched:** Home mode uses private Home pairing resolution and never calls `build_session_args`; the server wiring test makes a legacy resolution call fail. |
| EC-04 | Malformed prompt results needed explicit cleanup evidence. | **Patched and tested:** the malformed-result fixture proves the session is no longer connected. |
| EC-05 | Reconnect after uncertain prompt delivery might resend the prompt. | **Patched and tested:** reconnect uses `conversation.reconnect` only; the fresh socket receives no `prompt.submit`. |
| EC-06 | A global event might omit a handle. | **Rejected as a protocol mismatch:** the Home endpoint record always carries `conversation_handle`; only `turn_id` is optional for global events. The adapter ignores a handle-bound event without a turn ID and cannot let it complete a turn. |
| EC-07 | An audio frame might omit a handle. | **Rejected as a safe relaxation:** the Home audio record requires the conversation handle; missing identity is a protocol/audio failure, not a frame to guess into the active turn. |
| EC-08 | Binary audio after a foreign audio control frame cannot be safely attributed. | **Accepted as fail-closed:** binary frames carry no identity, so a foreign audio control frame closes the turn rather than silently merging bytes. |
| EC-09 | Unsupported interruption might still send a request. | **Patched:** no request is sent without the advertised interrupt capability. |
| EC-10 | An interrupt acknowledgement might be treated as completion. | **Patched by ownership:** the acknowledgement method only returns a boolean; the turn stream returns only on its matching interrupted/terminal event. |
| EC-11 | Concurrent `send_turn` calls could consume one another’s ordered frames. | **Patched:** Home Puck turns are single-flight under an async lock; a concurrent turn is rejected and tested. |
| VG-01 | A valid Home-mode server startup path was not verified. | **Patched and tested:** the server wiring fixture starts the runner, constructs `HomePuckSession` with the paired credential/handle, and stops cleanly. |
| VG-02 | Outbound Home schema was not asserted. | **Patched and tested:** open, ping, and request fixtures assert top-level schema and the open handle-only body. |
| VG-03 | Readiness rejection paths lacked deterministic coverage. | **Patched and tested:** unavailable, missing handle, unapproved route, and malformed capabilities are exercised. |
| VG-04 | Foreign/stale event behavior lacked coverage. | **Patched and tested:** foreign-turn and global events are ignored; the active turn alone controls completion. |
| VG-05 | Audio metadata and ordering lacked coverage. | **Patched and tested:** endianness, channels, width, rate bound, duplicate start, end ordering, post-end PCM, split samples, and foreign binding are covered. |
| AR-01 | The adapter was said to conflict with AD-22’s transparent Standard boundary. | **Rejected as false:** the Home bridge contract explicitly defines its versioned JSON-RPC envelope while preserving Standard event type/payload semantics; this adapter implements that planned Home endpoint, not a second Hermes wire parser. |

### Review Findings

- [x] [Review][Patch] Fail closed on missing or unknown RPC delivery metadata [puck_bridge/home_session.py:391-405,660-672] — missing or unrecognized delivery metadata now invalidates the binding instead of treating the prompt as known non-delivery.
- [x] [Review][Patch] Classify every Standard terminal status before returning [puck_bridge/home_session.py:1107-1153] — completion, failure, timeout, and interruption statuses are normalized before terminal ownership is applied.
- [x] [Review][Patch] Preserve `text_delta.delta` when `text` is absent [puck_bridge/home_session.py:1154-1175] — the adapter now accepts the pinned delta-only text shape.
- [x] [Review][Patch] Reject unsupported structured prompts instead of waiting [puck_bridge/home_session.py:530-534,859-860,1268-1326] — Puck emits a typed error and closes the turn when Home asks for unsupported structured input.
- [x] [Review][Patch] Reconnect an unavailable binding when Home requests it [puck_bridge/home_session.py:568-572,923-926] — an unavailable binding with `reconnect_required` now selects `conversation.reconnect` on the next attempt.
- [x] [Review][Patch] Require capabilities in a ready result [puck_bridge/home_session.py:936-951] — readiness now requires a capabilities object.
- [x] [Review][Patch] Normalize connection-entry transport failures [puck_bridge/home_session.py:197-217] — supported WebSocket entry failures now surface as `HomeBridgeTransportError`.
- [x] [Review][Patch] Close the Home binding when a submitted turn is cancelled [puck_bridge/home_session.py:650-680,694-804] — cancellation marks delivery uncertain and requires a reconnect without replay.
- [x] [Review][Patch] Invalidate the binding after a malformed application ping [puck_bridge/home_session.py:841-857] — malformed ping results now close the session.
- [x] [Review][Patch] Validate Home schema types strictly [puck_bridge/home_session.py:366-370,1025-1027] — boolean schema values are rejected rather than accepted as integer `1`.
- [x] [Review][Patch] Reject empty or hostless Home authorities [puck_bridge/home_session.py:105-118] — URL preflight now requires a real hostname and rejects userinfo authorities.
- [x] [Review][Patch] Exercise default Home device playback wiring [tests/test_puck_bridge.py:847-943] — the startup fixture now verifies the default `ResponseStream` reaches both runner and HTTP handler.
- [x] [Review][Patch] Test same-turn foreign-handle event rejection [puck_bridge/home_session.py:746-761; tests/test_puck_home_session.py:377-413] — a foreign terminal event carrying the active turn ID is ignored.
- [x] [Review][Patch] Prove terminal ownership after `audio_end` [puck_bridge/home_session.py:717-793; tests/test_puck_home_session.py:192-227] — the stream is held open until the matching terminal event arrives.
- [x] [Review][Patch] Test interrupt acknowledgement against a live turn stream [puck_bridge/home_session.py:806-839; tests/test_puck_home_session.py:552-580] — the acknowledgement leaves the stream live until its matching interruption event.
- [x] [Review][Patch] Retain close ownership when a Home reader outlives its timeout [puck_bridge/home_session.py:299-337,559-612] — deferred reader cleanup remains owned and blocks replacement connections until it finishes.

- [x] [Review][Defer] Complete the live Home-route and physical-Puck acceptance gate [spec-standard-6-puck-migrate-respeaker-puck-path.md:106-117] — deferred: HOME-NW-01/02/03 and an approved paired production route are not present; fake fixtures cannot prove wake, capture, playback, identity, interruption, reconnect, follow-up, or shutdown.
- [x] [Review][Defer] Wire the advertised Home interrupt into the Puck production path [puck_bridge/home_session.py:806-839; puck_bridge/server.py:240-245] — deferred: no receiver or firmware ingress currently invokes `interrupt_active_turn`; choosing the Puck stop-to-remote-interrupt path is part of the deferred hardware/Puck integration gate.
- [x] [Review][Defer] Resolve the `audio_abort` drain contract between Home and `TurnRunner` [puck_bridge/home_session.py:717-793; puck_bridge/turn.py:383-392] — deferred: Home continues toward text and terminal frames after fallback, while the audio-only Puck runner returns immediately; the correct drain/reset policy needs an integration decision and live evidence.

- [x] [Review][Patch] Validate `reconnect_required` before selecting `conversation.reconnect` [puck_bridge/home_session.py:1056-1065; tests/test_puck_home_session.py:522-551] — missing flags now mean a fresh `conversation.open`; present values must be booleans, with malformed values rejected without poisoning the fresh-open path.
- [x] [Review][Patch] Require the Home RPC error envelope before classifying delivery [puck_bridge/home_session.py:478-507; tests/test_puck_home_session.py:554-576] — `error.data.schema`, string `code`, and `known`/`uncertain` `delivery` are required; malformed envelopes close the binding, while valid known errors retain typed handling.
- [x] [Review][Patch] Close an unsupported structured-prompt binding before yielding its error [puck_bridge/home_session.py:890-917; tests/test_puck_home_session.py:346-363] — all five structured-prompt event types are covered through an early consumer, and the binding closes before the error is yielded.
- [x] [Review][Patch] Reject unknown or non-terminal statuses on terminal-looking events [puck_bridge/home_session.py:1246-1252,1282-1298; tests/test_puck_home_session.py:283-343,974-999] — terminal-looking events now require an absent or recognized terminal status; failed and interrupted statuses remain normalized before completion ownership.
- [x] [Review][Patch] Cover cancellation while `prompt.submit` is still awaiting its reply [puck_bridge/home_session.py:766-788; tests/test_puck_home_session.py:944-971] — a delayed-submit fixture proves cancellation closes the binding and reconnect does not replay the prompt.
- [x] [Review][Patch] Assert deferred Home context closure after the reader is released [puck_bridge/home_session.py:395-410; tests/test_puck_home_session.py:1027-1080] — the ownership test now asserts the original WebSocket context eventually exits after the reader releases.

#### Rejected

- [Review][Rejected] Stale correlation IDs on malformed prompt events — not actionable in this Puck path: structured prompts are unsupported and the Home contract requires correlation on prompt events.
- [Review][Rejected] Nested prompt payload turn ID is not cross-checked — no active Puck consumer uses the emitted prompt, and the envelope turn ID still controls completion and filtering.
- [Review][Rejected] Interrupt acknowledgements must echo handle and turn ID — false: the contract requires those values on the request; the acknowledgement is matched by its JSON-RPC request ID and may contain only status.
- [Review][Rejected] Interrupt requests need local deduplication — no production caller or contract requirement demonstrates duplicate requests; adding state would be speculative.
- [Review][Rejected] `unresolved_turn` is discarded — false: the complete readiness result is returned unchanged and no old prompt is replayed.
- [Review][Rejected] The adapter must emit a normalized terminal event — false: it consumes the matching terminal frame and only then ends the iterator; the Puck runner uses iterator completion as its boundary.
- [Review][Rejected] Generic audio-unavailable text loses a useful reason — not worth fixing in this audio/status-only surface; the typed `audio_abort` outcome is preserved and the reason is safe, not user-facing content.
- [Review][Rejected] `rendered: null` append-only text corruption — false for the pinned source: the Home Standard bridge rejects a non-string rendered field before it becomes an endpoint event.
- [Review][Rejected] Ping results must echo the conversation handle — false: the contract binds the request with the opaque handle and defines the response as the Standard liveness result.
- [Review][Rejected] Contradictory interrupt `accepted: false` plus `status: accepted` — malformed acknowledgement with no current production caller; not worth adding a second speculative guard before the live contract exists.
- [Review][Rejected] Home interrupt capabilities are advertised only as `commands` — false: `_capability_names()` already maps `session.interrupt` to `interrupt`, and `supports_interrupt` reads that normalized set.
- [Review][Rejected] Preserve a generic `prompt.request` structured event — false for this Home boundary: the contract fixes `approval.request`, `clarify.request`, `secret.request`, and `sudo.request`; the Puck adapter already rejects the listed types.
- [Review][Rejected] Add `message.interim` normalization for the Puck turn — false for this surface: Home uses the event to drive its audio sidecar, while the Puck consumer ignores text and the adapter preserves an unknown event payload rather than completing or retargeting a turn.
- [Review][Rejected] Reject non-string or `text: null` delta payloads in the Puck adapter — false for the pinned producer: Home's Standard bridge validates text updates before emitting them, and the Puck has no text presentation consumer.
- [Review][Rejected] Close the socket immediately on reader transport loss — false: the reader has already observed socket closure, while lifecycle owners close the adapter on reconnect or shutdown; `wait_for_disconnect()` is intentionally observation-only.
- [Review][Rejected] Surface `unresolved_turn` from `TurnRunner.start()` — false: `HomePuckSession.connect()` returns the complete readiness result, but `SessionProtocol` startup does not require a presentation for an unresolved old turn and never replays it.
- [Review][Rejected] Recover an outer RPC error code when `error.data` omits `code` — false: the current code deliberately reads the nested Home code when `data` is an object; malformed nested data is covered by the new envelope-validation patch instead.
- [Review][Rejected] Correct stale review line references — rejected by workflow: the proposed fix edits the spec under review rather than a product or test defect.
