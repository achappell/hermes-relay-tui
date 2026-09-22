---
id: STANDARD-7-ESP32
title: Add the ESP32 Touch audio and session adapter
type: feature
created: 2026-09-17
baseline_commit: a197548f571244e660ffe218e5c54ebfe3b0a1e6
status: done
route: dispatch
review_loop_iteration: 0
github_issue: https://github.com/achappell/hermes-relay-tui/issues/184
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-standard-3-tui-migrate-terminal-client.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Touch firmware receives display snapshots and sends actions, but no bounded microphone-audio path reaches its Home session. The selected audio hardware uses a separate C6 controller.

**Approach:** After device admission and a ready Home conversation binding, the Media Server accepts bounded transient PCM, transcribes it locally, submits one final transcript through the bound `HomeBrowserSession`, and returns observed state and response PCM to that doorway. Hermes credentials and session authority stay behind Home. For this story, the Media Server is the trusted host proxy and stores the paired revocable Device credential only in approved local storage; its S3 link must be local/trusted or mutually authenticated, and the S3 never receives the credential or Home binding.

## Boundaries & Constraints

- Frame each capture as JSON `mic_start`, `mic_capture_started`, binary PCM chunks up to 4 KiB, then `mic_end` or `mic_abort`, all with one capture ID; `turn_stop` may stop the active capture or turn. PCM is 16 kHz mono signed-16 little-endian, at most 15 seconds or 480,000 bytes, one capture at a time.
- Keep PCM and transcripts transient; publish transcript separately from assistant response text; clear both on abort, malformed input, timeout, STT failure, or disconnect. Final transcript limit: 4,000 characters. Never log credentials, handles, transcripts, or PCM; never persist Hermes credentials, conversation handles, or raw audio. Fail closed if approved Device-credential storage is unavailable.
- The Media Server performs final in-memory STT and submits one final prompt through the bound Home session; Home does not receive PCM. Never retry an uncertain prompt. A confirmed accepted turn may resume only on its existing Home session. Firmware does not open Hermes sessions or parse Hermes events.
- Expose observed `heard`, `listening`, `transcribing`, `thinking`, `buffering`, `speaking`, and `complete` phases. Send response PCM only to the owning doorway and preserve sample metadata; convert for the mono speaker only at audio output. Do not report `speaking` before playback starts or `complete` before Home's terminal event.

## I/O & Edge Cases

| Case | Required behavior |
|---|---|
| Valid capture | Show capture/transcribing, then submit one non-empty transcript through the ready Home binding and show `complete` after Home is terminal. |
| Unauthorized, malformed, duplicate, late, or oversized input | Reject, clear transient data, and create no Home turn. |
| Abort, empty transcript, or STT failure | Clear audio and transcript; submit nothing. |
| Disconnect or uncertain submit | Discard unsubmitted capture; never replay a possibly accepted prompt. Resume only the accepted turn on the same Home session; a new device socket needs fresh initiation. |
| Stop or playback failure | Wait for Home's terminal event; preserve completed text, show `complete`, and report unavailable audio when playback fails. |

</frozen-after-approval>

## Scope

This slice delivers the Media Server side of the Touch doorway: Home admission,
bounded WebSocket PCM, final in-memory transcription, one Home turn, honest
state, private response audio, and no-replay cleanup. S3/C6 UART, firmware,
reset recovery, and physical audio acceptance are deferred.

`--touch-voice` loads the paired Device credential, device ID, and configuration
revision from approved local configuration. Socket frames cannot provide them,
and no `HomeBrowserSession` exists before Home returns a ready claim handle.

## Host Contract

`mic_start` carries `schema: 1` and a bounded `capture_id`. On the first start,
the host generates a claim ID and observation timestamp, calls
`POST /api/v1/touch-claims` with configured device ID/revision, opens the
returned handle, and sends `mic_ready` only after both succeed; otherwise it
sends `mic_reject`. A later start reuses the binding only after the Home turn
is terminal; a new socket claims again. The Device credential, Home claim ID,
revision, and conversation handle never cross to S3. The endpoint sends
`mic_capture_started` with the matching ID after its microphone opens; only
then does the host publish `listening` and accept PCM.

Accept only even-length binary PCM chunks up to 4 KiB and 480,000 bytes total.
`mic_end`/`mic_abort` must match the active capture; invalid, empty, duplicate,
late, or oversized input clears transient state and creates no turn. Keep one
active capture and Home turn per socket, with no WAV intermediate. In-memory STT
is capped at 4,000 final characters; publish it as `transcript_text`, separate
from `response_text`, and add `transcribing` and `complete`. Publish `complete`
only after Home's terminal event, including audio failure. Response PCM keeps the private
`audio_start`/binary/`audio_end`/`audio_abort` path. The endpoint reports
schema-1 `audio_playback_started` or `audio_playback_failed` with `turn_id`;
only the former permits `speaking`.

`turn_stop` aborts pre-submit capture; during submission it latches one Home
interrupt and applies it when the accepted turn ID is available. Wait for Home
terminal state, preserve completed text on audio failure, and discard without
retry after disconnect or uncertain submission.

## Dependencies and Split Boundary

HOME-NW-16 is implemented in Home main (`a15327b`, PR #50; status sync
`97dc3aa`, PR #51). Its route authenticates the Device, resolves the approved
Room/Profile binding, and returns the opaque handle. Origin validation is not
admission. UART/C6 and physical acceptance remain in `deferred-work.md`; `2-E-2`
owns partial transcription.

## Code Map

- `home_display/touch.py` (new), `home_display/appliance.py` -- Touch mode,
  config, claim HTTP, lazy binding, capture state, cleanup, fail closed.
- `home_display/server.py` -- Touch JSON/binary ingress, bounds, stop, playback
  acknowledgements, teardown; preserve browser/private audio.
- `puck_bridge/home_session.py` -- reuse its single reader, no-replay, response
  events, and interruption semantics.
- `voice.py`, `home_display/state.py` -- in-memory STT, `transcribing`, and
  separate `transcript_text`; preserve `response_text`.
- `shared/display/display_snapshot.schema.json`, `shared/display/display_rules.h`,
  `shared/display/display_rules.c`,
  `firmware/esp32-s3-touch-lcd-7/main/include/ui_snapshot.h`,
  `firmware/esp32-s3-touch-lcd-7/main/src/ui_snapshot.c`, and
  `firmware/esp32-s3-touch-lcd-7/main/src/ui_snapshot_json.c` -- carry approved
  visual fields/state; do not add UART or PCM here.
- `tests/test_home_display_server.py`, `tests/test_home_appliance.py`,
  `tests/test_home_display_state.py`, `tests/test_mic.py`, and new
  `tests/test_home_display_touch.py` -- cover authorization, bounds, isolation,
  cleanup, races, no-replay, audio failure, and browser regression.

## Tasks & Acceptance

**Execution:**
- [x] `voice.py`, `home_display/state.py` -- add in-memory STT, transcript
      state, and honest phases.
- [x] `shared/display/display_snapshot.schema.json`,
      `shared/display/display_rules.h`, `shared/display/display_rules.c`,
      `firmware/esp32-s3-touch-lcd-7/main/include/ui_snapshot.h`,
      `firmware/esp32-s3-touch-lcd-7/main/src/ui_snapshot.c`, and
      `firmware/esp32-s3-touch-lcd-7/main/src/ui_snapshot_json.c` -- carry the
      approved visual fields/state without UART or PCM handling.
- [x] `home_display/touch.py`, `home_display/appliance.py` -- add explicit
      Touch mode, claim, lazy binding, bounded capture, and fail-closed setup.
- [x] `home_display/server.py` -- add per-connection framing, bounds, stop,
      playback acknowledgements, teardown, and private response audio.
- [x] `tests/test_home_display_server.py`, `tests/test_home_appliance.py`,
      `tests/test_home_display_state.py`, `tests/test_mic.py`, and
      `tests/test_home_display_touch.py` -- cover malformed input,
      authorization, isolation, stop races, uncertain submission, no replay,
      and browser regression.

**Acceptance:**
- Given an unadmitted socket, when `mic_start` arrives, then it is rejected
  without a Home session or PCM acceptance.
- Given a granted ready handle, when one valid bounded capture ends, then one
  final transcript may produce at most one Home turn.
- Given a ready capture, when `mic_capture_started` is absent, then binary PCM
  is rejected; when it is present, then the host publishes `listening` and
  accepts only that capture's PCM.
- Given a terminal first turn on one socket, when another `mic_start` arrives,
  then the ready binding is reused; a new socket must claim independently.
- Given invalid, duplicate, stale, odd-length, oversized, empty, aborted, or
  failed input, then transient state clears and no turn is created.
- Given two sockets, one socket's capture/state/audio never reaches the other.
- Given disconnect or uncertain submission, cleanup never replays the prompt.
- Given response PCM, when the endpoint reports playback started, then the
  host may publish `speaking`; when it reports playback failure, then it must
  retain completed text without claiming speech.
- Given stop or playback failure, interruption remains pending until Home is
  terminal, completed text remains, and unavailable audio is explicit.

## Implementation Notes

Implemented 2026-09-21.

**In-memory STT.** `voice.transcribe_pcm` hands faster-whisper a float32 array built from the signed-16 bytes; `voice.pcm_to_float32` is the one conversion. No WAV is written at any point, and the final transcript is bounded at 4,000 characters inside `voice.py` as well as at the doorway, so neither layer depends on the other for the limit.

**State contract.** `transcribing` and `complete` are appended after `prompt` in `display_rules_state_t` on purpose: `tests/test_display_conformance.py` indexes the enum by position, and every existing target pins the earlier values. `DISPLAY_RULES_STATE_LAST` replaces the previous `<= DISPLAY_RULES_PROMPT` bound so a future append does not need a second edit. `transcribing` is a busy state; it may reach `thinking`, `heard` or `idle` and never a response phase, because nothing has been submitted yet.

**Transcript field.** `transcript_text` is always present in `DisplaySnapshot.to_dict()` and is never `response_text`. The firmware buffer is 256 bytes against the host's 4,000-character bound, so `ui_snapshot_json.c` truncates a long transcript rather than rejecting an otherwise valid snapshot — losing the tail of a confirmation line is better than losing the answer and the connection state with it.

**Serial Touch ingress.** Frames reach the doorway through one per-connection queue and one consumer task, not a task per frame. The existing `_track_connection_task` budget is 8, and a full capture is up to 117 chunks; a task per chunk would either exhaust that budget or reorder the audio, and a reordered capture is a corrupted one. A flooded queue is drained and replaced with a single overflow marker, which clears the capture — an explicit failure rather than a prompt with holes in it.

**Admission.** `TouchDoorway` holds no Home session until the first `mic_start`. The claim and the handle open must both succeed before `mic_ready`; either failure sends `mic_reject` with a classified reason (`unauthorized` only for 401/403) and leaves `_session` as `None`. The claim route is derived from the one configured `--home-bridge-url`, and `_validate_claim_url` refuses plaintext `http` unless the host is loopback. `TouchDeviceConfig.__repr__` is redacted so a traceback cannot print the credential.

**Speaking and complete.** `speaking` is published only on a matching schema-1 `audio_playback_started`; `audio_start` alone publishes `buffering`. `complete` is published only at Home's terminal event, `turn_end` or `turn_interrupted`, including when playback failed — in which case the completed text stays and `status_text` says the audio is unavailable. A playback report carrying another turn's id is ignored.

**Stop and no replay.** `turn_stop` before submission drops the capture; during submission it sets a latch that `_apply_pending_interrupt` spends once `_turn_id` exists, so a stop sent while transcription is still running is not lost and is not spent twice. `send_turn` is called at most once per capture. A transport failure mid-turn publishes `disconnected` and the prompt is discarded; `close()` cancels the turn task and closes the session without resubmitting anything.

**Verified surprise.** PlatformIO's bundled `cmake` in this checkout is an x86_64 binary on an arm64 Mac, so `pio run -d firmware/esp32-s3-touch-lcd-7` fails during CMake code-model generation before compiling any source. That is a pre-existing toolchain fault, not a code fault. The C changes are proved instead by the `-Werror` host compiles: `tests/test_firmware_ui_core.py` builds `ui_snapshot.c`, `ui_display.c` and `display_rules.c`, a new case there builds and exercises `ui_snapshot_json.c` against ESP-IDF's cJSON (skipped when those sources are absent), and the native SDL simulator clean-builds.

## Design Notes

Home admission is an HTTP operation followed by the existing opaque bridge
open. Keeping those phases explicit prevents `/state` origin trust from being
mistaken for device authorization and keeps the credential out of firmware
frames. The deferred UART/C6 story will consume the host control and PCM
messages without moving Home or STT authority onto the boards.

## Verification

- `venv/bin/pytest -q tests/test_home_display_server.py tests/test_home_appliance.py tests/test_home_display_state.py tests/test_mic.py tests/test_home_display_touch.py` -- expected: focused host and state tests pass.
- `venv/bin/pytest` -- expected: full Python suite passes.
- `./scripts/simulate_native.sh` -- expected: shared display reducer/rendering passes; this does not prove audio.
- `pio run -d firmware/esp32-s3-touch-lcd-7` -- expected: S3 display build passes; this does not prove C6 wiring or physical playback.

## Review Triage Log

Three layers reviewed the diff against baseline `a197548`: Blind Hunter (BH), Edge Case Hunter (EC), Verification Gap (VG). Every filed finding gets one row below.

- **VG1 (hallucination filter untested):** `medium`, real. No test in `tests/test_home_display_touch.py` feeds a known-hallucination phrase (e.g. `"thank you."`) through `_doorway()`; `_is_hallucination` is live and wired but unverified.
- **VG2 (`HttpTouchClaimClient._post` untested):** `medium`, real. Every admission test injects `FakeClaimClient`; the only code that speaks the real claim HTTP contract (401/403 classification, handle extraction) has zero coverage.
- **VG3 (`Appliance._open_touch_home_session` untested):** `medium`, real. Every touch test that reaches `mic_start` injects a fake `session_factory`; the only production path that turns a granted claim into a live `HomeBrowserSession` has zero coverage.
- **BH1 / EC5 (UTF-8 truncation in `optional_truncated_text`):** `low`, real — verified by reading `ui_snapshot_json.c:44-62`: truncation is a raw byte-offset `memcpy` with no continuation-byte check. Same defect, one entry.
- **BH2 (capture-bound constants duplicated in `touch.py`/`server.py`):** `low`, real. `MAX_PCM_CHUNK_BYTES`/`MAX_CAPTURE_ID_LENGTH` and `MAX_TOUCH_PCM_CHUNK_BYTES`/`MAX_TOUCH_CAPTURE_ID_LENGTH` currently agree but are independently defined, contradicting `touch.py`'s own docstring claim of one shared source.
- **BH3 (4000-char transcript bound defined three times):** `low`, real. `voice.py`, `touch.py`, and `state.py`'s `MAX_DISPLAY_TRANSCRIPT_LENGTH` currently agree; a future drift would raise inside `DisplaySnapshot.__post_init__`, silently swallowed by `_publish`'s `contextlib.suppress(Exception)`, freezing the display with no error surfaced.
- **BH4 (no rollback of an abandoned Home claim):** `maybe-false`. `_open_home_binding` never releases a successful claim if the subsequent session-open fails. Whether this strands the Room binding depends on HOME-NW-16's own claim-expiry/idle-tail behavior, implemented in the sibling `hermes-relay-home` repository and unverifiable from this checkout. Settling it needs that repository's claim-lifecycle code.
- **BH5 (broken session reused after mid-turn transport failure):** `medium`, real — verified at `home_display/touch.py`, `_run_home_turn`'s `except Exception:` branch: `self._session` is never cleared, so the next `mic_start` skips re-claiming and hands the dead session back to `send_turn`, which will keep failing until a full reconnect.
- **BH6 (two `pcm = b""` reassignments are dead code):** `low`, real but mostly cosmetic — verified: bytes are immutable and the reassignments are redundant with CPython's own refcounting at scope exit; the module docstring's "dropped the instant" claim holds regardless, but the lines overstate a deliberate scrub that isn't there.
- **BH7 (`_build()` can silently no-op if called twice):** `false`. Verified: `grep -n "self\._build()"` shows exactly one call site in the whole file. The hypothetical double-call never occurs.
- **BH8 (sprint-status.yaml vs spec frontmatter status mismatch):** `low`, real, but this is a build-orchestration bookkeeping gap (the tracker was synced to `in-progress` and never advanced to match this review step's `in-review`), not a code defect from the implementation subagent. Fixed directly rather than routed to patch dispatch.
- **BH9 (malformed frame while idle logs nothing):** `low`, real but marginal — verified at `handle_touch_malformed`: returns silently when `self._capture is None`, no log line, unlike every other rejection path in the file.
- **BH10 (spec's own focused-test command omits two touched test files):** rejected per the explicit rule against findings whose fix is to edit this build's spec.
- **BH11 (no local/non-wss dev path documented/tested):** rejected as redundant with VG2/VG3, which cover the same underlying gap (production HTTP/session wiring untested against anything but fakes) with concrete file:line evidence.
- **EC1 (session opened after `close()` is never closed):** `medium`, real — verified: `close()` snapshots and clears `self._session` without holding `self._lock`; a session opened by an in-flight `_on_mic_start` that outlives `close()`'s snapshot is assigned afterward and never cleaned up.
- **EC2 (`self._turn_id` read before Home assigns the real one):** `medium`, real — verified against `puck_bridge/home_session.py:740-806`: `send_turn()` is a plain method that returns an unstarted async generator; `active_turn_id` is only set once `_send_turn_locked` runs, on first iteration. `self._turn_id` in `touch.py` is read one line after calling `send_turn()`, before that happens, so it falls back to the deterministic `f"touch-{connection_id}"` on every turn — falsifying this spec's own Implementation Notes claim (line 167) that "a playback report carrying another turn's id is ignored," since every turn on one connection shares that id.
- **EC3 (`error` state never returns to `idle`):** `high`, real — verified against `shared/display/display_rules.c`'s `transition_allowed`/`display_rules_apply_snapshot`: every `_publish("error", ...)` call site is followed only by `return`; the next `mic_start` publishes `heard` directly, an illegal `ERROR`→`HEARD` transition that `display_rules_apply_snapshot` silently rejects, leaving the panel frozen on stale `error` display state until a full socket reconnect.
- **EC4 (`_session_factory` branch ignores the granted `handle`):** `low`, real but currently unreachable — verified: the only production `Appliance(...)` construction (`home_display/appliance.py:2824`) never sets `session_factory`, so this branch is dead in today's deployment; still a live landmine if that hook is ever wired for touch mode.

### Groups routed to patch

1. `error`-state stuck (EC3) — high
2. Broken session reused after transport failure (BH5) — medium
3. Stale/shared `turn_id` on reused bindings (EC2) — medium
4. Session leak on close/admission race (EC1) — medium
5. `_open_touch_home_session` untested (VG3) — medium
6. `HttpTouchClaimClient._post` untested (VG2) — medium
7. Hallucination filter untested (VG1) — medium
8. UTF-8 truncation at raw byte offset (BH1/EC5) — low
9. `_session_factory` branch ignores `handle` (EC4) — low
10. Duplicated capture-bound constants (BH2) — low
11. Duplicated transcript-length constant (BH3) — low
12. Dead `pcm = b""` reassignments (BH6) — low
13. Unlogged malformed-frame-while-idle (BH9) — low

### Deferred

- BH4 (abandoned-claim rollback) — recorded in `deferred-work.md`.
