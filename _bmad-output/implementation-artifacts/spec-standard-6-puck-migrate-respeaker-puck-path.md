---
id: STANDARD-6-PUCK
title: Migrate the ReSpeaker Puck path to the Standard Home boundary
type: feature
created: 2026-09-14
status: done
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

- `venv/bin/pytest` — **1,325 passed**, 6 warnings.
- `venv/bin/pytest -q tests/test_puck_home_session.py` — **25 passed**.
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
