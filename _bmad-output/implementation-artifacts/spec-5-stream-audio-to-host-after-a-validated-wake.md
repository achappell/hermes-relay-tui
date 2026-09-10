---
title: 'Stream audio to host after a validated wake'
type: 'feature'
created: '2026-09-09'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '3227c95bec24f29655ddccba0601a80015f88996'
context:
  - '{project-root}/_bmad-output/planning-artifacts/prds/prd-hermes-relay-tui-2026-09-07/prd.md'
  - '{project-root}/_bmad-output/specs/spec-hermes-relay-tui/stories/5-stream-audio-to-host-after-a-validated-wake.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Puck's on-device wake detection (story 3) fires cleanly but nothing carries the moment forward — no host receiver, no transport, no turn.

**Approach:** Add a standalone host-side bridge (the PRD's "Media Server" role) that accepts one bounded, VAD-gated audio upload per wake, transcribes it locally with the existing `voice.py:transcribe()`, and drives a real Hermes turn through `session.py`'s `SessionProtocol` via a directly-constructed `handsfree.HandsFreeCoordinator` (not `build_hands_free()`, which assumes a local wake engine the Puck's on-device wake makes redundant). Firmware wires `on_wake_word_detected:` to a new VAD-gated, single-shot, no-re-arm capture+upload adapted from `pcm_capture.h`'s proven chunked-upload pattern. Response plays on the host machine's own speakers; identity is a hardcoded shared token standing in for the still-blocked Story 4 credential system.

## Boundaries & Constraints

**Always:** Raw Puck audio stays transient and home-LAN-only (PRD NFR3) — nothing persisted beyond what's needed to transcribe. The bridge is a standalone process, not wired into `app.py`/`home_display/appliance.py`. Firmware upload keeps `pcm_capture.h`'s existing safety machinery: the heap-watermark reboot circuit breaker, the 2-consecutive-failure abandonment, and the 30ms inter-chunk delay. The host receiver MUST set `protocol_version = "HTTP/1.1"` on its handler (`tools/receiver.py`'s own docstring: ESP-IDF's `http_request` component depends on connection reuse; `http.server`'s default HTTP/1.0 close-per-request silently defeats it).

**Never:** No Story 4 credential system, no DEVICE-01 iOS UI, no Puck-side response playback (tracked separately, `docs/friction-log.md` 2026-09-09). No changes to `wake.py`/`handsfree.py`'s core contracts. No continuous rolling capture — one wake-triggered upload only.

</frozen-after-approval>

## Code Map

- `firmware/respeaker-lite/pcm_capture.h` -- add a VAD-gated single-shot capture variant: reuse `start()`/`write()`/the chunked-upload loop from `upload_and_restart()` (lines 93-203) but (a) size the buffer for ~8s of audio, not the current fixed 2s `CAPTURE_BYTES` (line 38), (b) end the window via `id(mww).get_vad_state()` (declared `micro_wake_word.h:100`) going false for a debounce period instead of filling the fixed buffer, (c) do NOT call `start()` again at the end (no re-arm, unlike `upload_and_restart`).
- `firmware/respeaker-lite/respeaker-lite.yaml` -- add `on_wake_word_detected:` (currently absent) under the `micro_wake_word:` block (~line 259) to call the new capture-start function; existing `vad:` block (line 273, `probability_cutoff: 0.05`) already proven responsive, reuse as-is.
- New `puck_bridge/` package (exact module names TBD by implementer) -- chunked-upload HTTP receiver matching `tools/receiver.py`'s wire shape (`POST /upload?seq=N&chunk=C&total=T`, `UPLOAD_CHUNK_BYTES=16000`-sized bodies, `pcm_capture.h:88`) plus a hardcoded-token header check via `config.py`'s existing `token_env` indirection (`config.py:296-330`), WAV reassembly using the Q31->Q25->gain->16-bit conversion already validated in `tools/label_captures.py:process_frame_sample()`, then `voice.py:transcribe()` (`voice.py:686`, unchanged).
- `session.py` -- `SessionProtocol` (lines 39-91), `HermesSession.connect()`/`send_turn()` (lines 151, 268) consumed unchanged.
- `handsfree.py` -- construct `HandsFreeCoordinator(session, capture=..., send=...)` (lines 65-105) directly; do NOT use `build_hands_free()` (line 357) -- it unconditionally builds a local wake engine this pipeline doesn't need.
- `home_display/appliance.py:741-764` -- reference pattern only for the sync->async bridge (`asyncio.run_coroutine_threadsafe`); do not import from it.
- `audio.py` -- `PCMPlayer` (line 110: `start(fmt)`, `write(chunk)`, `close()`) for host-speaker playback of the response.

## Tasks & Acceptance

**Execution:**
- [x] `puck_bridge/` -- chunked-upload receiver (HTTP/1.1 keep-alive), token check, WAV reassembly, `transcribe()` call
- [x] `puck_bridge/` -- turn runner: submit transcript via a directly-constructed `HandsFreeCoordinator`, play response with `PCMPlayer`
- [x] `config.py` -- add a `PUCK_DEVICE_TOKEN` env-indirected token alongside the existing per-profile pattern
- [x] `firmware/respeaker-lite/pcm_capture.h` -- VAD-gated single-shot capture+upload variant
- [x] `firmware/respeaker-lite/respeaker-lite.yaml` -- wire `on_wake_word_detected:` to the new capture function
- [x] `firmware/respeaker-lite/README.md` -- document the wake-to-upload behavior and the hardcoded-token stand-in

**Acceptance Criteria:**
- Given a validated on-device wake, when the Puck's utterance ends (VAD-gated, not a fixed timer), then exactly one bounded upload reaches the bridge.
- Given a valid hardcoded token, when the bridge receives a complete capture, then it produces a WAV and transcript without modifying `voice.py:transcribe()`.
- Given a produced transcript, when handed to the directly-constructed `HandsFreeCoordinator`, then exactly one real Hermes turn is submitted and its response is audible on the host machine's speakers.
- Given a missing or invalid token, when an upload is attempted, then the bridge rejects it (401) and no turn is submitted.

## Implementation Notes

### Live hardware smoke test (2026-09-10)

Ran the live smoke test against a real Puck. Found and fixed three real,
pre-existing firmware defects along the way -- none introduced by this
story's own diff, but none had ever been exercised together before,
because story 5 is the first thing that actually drives the Puck's WiFi
API log connection, `micro_wake_word`, and a real outbound HTTP upload
concurrently for more than a few seconds:

1. **A leftover story-3 diagnostic was still wired and firing on every
   boot.** `respeaker-lite.yaml` had a 200ms `interval:` unconditionally
   calling `pcm_capture::dump_over_serial()` -- up to 15 full ~256KB
   captures, base64-encoded, over a 115200 baud serial link. That
   saturates the main loop for several minutes after every boot, starving
   WiFi/API and making `micro_wake_word` appear to silently stop with no
   crash marker. Removed the interval wiring (the function itself stays
   defined, unused, as evidence -- see `pcm_capture.h`).
2. **`micro_wake_word` had no self-recovery.** Once stopped (by the above,
   or by ordinary WiFi/API churn on a weak signal), nothing ever called
   `micro_wake_word.start` again -- the device needed a manual reboot.
   Added a lightweight watchdog to the existing 2s diagnostic interval:
   if `is_running()` is false, log a warning and call `id(mww).start()`.
   This does not fix the underlying instability; it keeps wake detection
   available while that instability is a known, separate condition (see
   below).
3. **ESP-IDF's `esp_http_client_write()` aborts the whole POST the instant
   a single `write()` call inside the body-send loop returns `<=0` -- it
   never retries that write** (`http_request_idf.cpp:139-153`, upstream
   ESPHome code, not this repo's). On this device's actual WiFi signal
   (observed -89 to -90 dB throughout this session), a 16KB chunk had a
   real chance of a write stalling mid-transfer. A live `tcpdump` capture
   confirmed the mechanism directly: TCP handshake completes normally, a
   small partial write lands and is ACKed, then silence -- the next
   `write()` call fails outright with no retry, matching the device's own
   `ESP_FAIL` log. Reduced `UPLOAD_CHUNK_BYTES` from 16000 to 2000 in both
   `pcm_capture.h` and `puck_bridge/receiver.py` (the Python side only
   uses it as a log hint, not a protocol assumption) so a single write has
   far less time to survive a hiccup before completing. This measurably
   improved reliability (most chunks now succeed) but did not eliminate
   stalls on longer transfers -- see below.

**What was proven on real hardware, with direct evidence:**
- Wake detection: `Hey Jarvis` and `Okay Nabu` both fire reliably at 0.99+
  sliding-average / 1.00 max probability.
- The VAD-gated capture correctly starts on `on_wake_word_detected` and
  ends cleanly on debounced VAD silence (`wake capture ended on VAD
  silence (N bytes)`), not a fixed timer.
- The chunked upload transport works: a short capture (8840 bytes, 5
  chunks) completed in full (`Uploaded wake capture 1 (8840 bytes, 5
  chunks)`).
- The entire downstream pipeline works when a capture completes: that
  same 5-chunk capture reached `puck_bridge/receiver.py`, converted to a
  WAV, and was processed by `faster-whisper` successfully (empty
  transcript only because the captured audio was itself extremely short
  -- 69ms, essentially a noise blip, not real speech).

**What remains unverified:** a full round-trip Hermes turn from a real
spoken utterance. Every capture large enough to plausibly contain real
speech (hundreds of chunks, matching several seconds of audio -- the
device's room was not fully silent, so the VAD's 800ms silence-debounce
kept extending capture windows well past the literal utterance) stalled
partway through upload and was evicted by the receiver's TTL cleanup
before completing. This is not a code gap surfaced by this session's
evidence -- it is the device's current physical WiFi signal strength,
independently confirmed by the `tcpdump` trace above and by the fact that
short captures *do* complete reliably on the same link. The device could
not be physically relocated closer to the AP during this session.

**Recommendation:** re-run the live smoke test once the Puck can be
positioned with a stronger WiFi signal (closer to the AP, or with
improved coverage at its current location). Based on everything proven
above, no further code changes are expected to be needed for that retest
to succeed -- but this remains open, unverified evidence, not a
completed acceptance criterion.

**One additional defect found live, not yet fixed:** `puck_bridge/
server.py`'s `build_session_args()` (added by the fix-round patch for
finding #5 below) only defaults `session_args.session_id` when it is
falsy -- but `config.build_arg_parser()`'s own profile-config loading
already populates a non-empty `session_id` from the selected relay
profile's YAML (e.g. `amanda-kiosk`) before that check ever runs. In
practice this means the bridge silently reuses the *same* session id as
the TUI's own normal use of that profile, defeating the "own distinct
Hermes session" intent the code comment describes, and risking a real
session collision if the TUI is active on the same profile at the same
time. Recorded in `deferred-work.md` rather than fixed here, since it
needs a design decision (an explicit `--session-id` flag default, or a
suffix applied unconditionally) rather than a one-line correction, and
this session's remaining time went to the hardware smoke test itself.

## Review Triage Log

Review pass 1 (blind-hunter, edge-case-hunter, verification-gap; diff = baseline_commit..pre-fix tree):

| # | Source | Finding | Verdict | Evidence | Route |
|---|--------|---------|---------|----------|-------|
| 1 | blind-hunter | Compiled `.pyc` files listed as "NEW FILE" in the diff | false | `.gitignore:6-7` already ignores `__pycache__/` and `*.pyc`; `git status --porcelain` confirms they are not untracked-and-stageable -- the diff-generation script's own `find` (not `git`) walked past the ignore rule. | reject |
| 2 | blind-hunter | `_post_chunk()` opens a fresh `HTTPConnection` per chunk, so the module's `protocol_version = "HTTP/1.1"` connection-reuse rationale is never exercised by a test | low | Confirmed by reading `tests/test_puck_bridge.py`'s `_post_chunk()` helper: no connection object is shared across the two `_post_chunk` calls in the multi-chunk tests. | patch |
| 3 | blind-hunter + edge-case-hunter (#4, #9-claim) | `_PendingCapture` entries for an abandoned/incomplete `seq` are never evicted from `captures`, growing unbounded and holding raw audio indefinitely | medium | Confirmed in `receiver.py`: `captures` is a plain dict with no TTL/expiry path; the frozen spec's own "Always: Raw Puck audio stays transient" is violated for any capture that never completes (device reboot, dropped chunk, network blip). | patch |
| 4 | blind-hunter | `TurnRunner._send()`'s `future.result()` has no timeout, unlike `stop()`'s `timeout=10.0` | high | Confirmed in `turn.py`: a hung `send_turn()` blocks the receiving thread forever; because `HandsFreeCoordinator` is single-flight, this permanently wedges the bridge (no later wake can ever complete) until process restart. | patch |
| 5 | blind-hunter | `build_session_args()` unconditionally overwrites `session_args.session_id`, discarding any operator-supplied `--session-id` | low | Confirmed in `server.py`: `session_args.session_id = f"..."` runs unconditionally after `parse_args`. | patch |
| 6 | blind-hunter | `server.py` only handles `KeyboardInterrupt`, no `SIGTERM` -- can't shut down cleanly as a background service | medium | Confirmed: `main()`'s only exception handling around `serve_forever()` is `except KeyboardInterrupt`. Real, but the spec's Intent frames this bridge as a standalone proof-of-pipeline test harness, not a production service; graceful-shutdown hardening is outside what this story's Tasks & Acceptance ask for. | defer |
| 7 | blind-hunter | `on_wake_word_detected:`'s new wiring doesn't filter by `wake_word`, so an internal `stop` model detection would also start a wake capture | medium (not currently reachable) | Traced `micro_wake_word.cpp:526`: `wake_word_detected_trigger_.trigger()` fires for any detected model regardless of `internal_only` (that flag only gates `get_wake_words()`'s external listing). However `respeaker-lite.yaml` never calls `micro_wake_word.enable_model: stop`, and only the first-listed model defaults enabled (`hey_jarvis`) -- so `stop` cannot currently fire. Real latent gap for whichever future story enables `stop` for real FR-5 behavior. | defer |
| 8 | blind-hunter | `wake_capture::write()` truncates an over-8s utterance with only a log, no signal to the host distinguishing truncated vs. complete | low | Confirmed intentional bounded-buffer behavior (matches `upload_and_restart`'s precedent); fix would need a new wire-protocol field. Unlikely in everyday use (spoken household questions), and the fix is more than a direct correction. | reject |
| 9 | blind-hunter | `raw_stereo32_to_wav()` silently drops a trailing partial frame with no diagnostic | low | Confirmed: `len(raw) // BYTES_PER_FRAME` truncates; no `logger` call notes a non-multiple length. | patch |
| 10 | blind-hunter | `UPLOAD_CHUNK_BYTES` duplicated in `pcm_capture.h` and `receiver.py` with nothing enforcing parity | false | `receiver.py`'s own reassembly (`_PendingCapture.assemble()`) joins by declared chunk index, not by assuming a fixed chunk byte size -- a mismatch between the two constants has no functional effect on reassembly. | reject |
| 11 | blind-hunter | Token comparison in `receiver.py` is not constant-time | out of scope | The frozen spec and this story's own README/YAML comments explicitly state the hardcoded token "is not a security boundary" -- timing-attack hardening is excluded by the intent itself, not merely by the scope section. | reject |
| 12 | blind-hunter | `tempfile.mkdtemp()` work dir is never removed | low | Confirmed, but `make_handler()` (and its `mkdtemp` call) runs once per process lifetime in the real entry point (`server.py:main`), not once per capture -- one harmless empty leftover directory per run. Unlikely to matter in everyday use, and a correct fix (coordinating a `TemporaryDirectory` context manager with server shutdown) is more than a direct correction. | reject |
| 13 | blind-hunter | No test exercises `puck_bridge/server.py`'s `main()` (missing-token exit path, wiring) | low | Confirmed via `tests/test_puck_bridge.py`: coverage stops at the receiver/handler-factory/turn-runner layers. Thin entry-point wiring; the specialized verification-gap layer traced this area and did not flag it independently. | defer |
| 14 | blind-hunter | Friction-log's `PUCK-01.7` candidate not yet filed as a GitHub Project card | n/a | Administrative tracking gap, not a code defect; already correctly captured in `docs/friction-log.md`'s 2026-09-09 entry per this repo's own friction-log convention. | defer |
| 15 | edge-case-hunter (#1, #7-claim) | `wake_capture::upload()` computes `total_chunks == 0` when `write_pos == 0` (VAD silence with zero audio captured), so no POST is ever sent | low | Confirmed via the chunk-count arithmetic in `pcm_capture.h`. No differing observable outcome either way (an empty-audio upload would also produce an empty transcript and no turn, per `receiver.py`'s existing empty-transcript handling) -- but the fix is a direct 3-line guard, so it is not rejected on low+nontrivial-fix grounds. | patch |
| 16 | edge-case-hunter (#2) | `int(self.headers.get("Content-Length", 0) or 0)` runs before the token check and raises an unhandled `ValueError` on a non-numeric header | medium | Confirmed: this parse happens ahead of the `X-Puck-Token` check in `do_POST`, so any LAN peer (not just an authenticated Puck) can trip it. | patch |
| 17 | edge-case-hunter (#3) | A later chunk declaring a different `total` than the first chunk for the same `seq` is silently ignored (`captures.setdefault` only uses `total` on first creation) | low | Confirmed. Unlikely with the actual firmware (always sends one consistent `total` per `sample_index`), and a correct fix needs new validation/response-code state -- more than a direct correction. | reject |
| 18 | edge-case-hunter (#5) | `TurnRunner.submit_transcript()` writes `self._pending_transcript` without synchronization; two near-simultaneous calls can race | medium | Confirmed: no lock guards the pending-transcript-set + `on_wake()` pairing in `turn.py`. Plausible via duplicate/retried uploads even though the firmware itself is single-shot/no-re-arm. | patch |
| 19 | edge-case-hunter (#6) | If `TurnRunner.start()`'s `connect()` call raises, `_loop_thread` stays set and a later `start()` would no-op forever | low (not currently reachable) | Confirmed the guard exists, but `server.py:main()` calls `start()` exactly once with no retry path -- a `connect()` failure currently propagates out of `main()` and exits the process rather than leaving it in the described stuck state. Speculative for the current call pattern. | reject |
| 20 | verification-gap | `do_POST`'s `chunk >= total` (and negative/`total<=0`) boundary has no test; a regression there would silently truncate reassembled audio with no test failing | high (pre-verified by the reviewing layer) | Layer confirmed via search of `tests/test_puck_bridge.py` for `400`/`qs.get`/`bad chunk` -- no match; filed disposition `patch`. | patch |

Fix round 1 (patches 2, 3, 4, 5, 9, 15, 16, 18, 20 from the triage log above): all nine applied. Re-verified independently: full suite `915 passed` (bare `pytest -q`), `esphome compile` reached "Compiling app..." codegen again before the same pre-existing ESP-IDF-toolchain sandbox segfault (not a regression -- reproduced identically on baseline). One incidental scope-creep caught and reverted: the fix pass's environment work pulled an unrelated ~894-line `esphome`/`aioesphomeapi` dependency tree into `uv.lock`; `uv.lock` was checked out back to baseline, keeping only `pyproject.toml`'s intended one-line `packages.find` addition. One new residual finding from this round (`TurnRunner`'s timeout doesn't cancel the abandoned coroutine) recorded in `deferred-work.md` rather than looped -- low-likelihood, and a correct fix needs more care than a one-line patch.

Findings 1, 6, 7, 8, 10, 11, 12, 13, 14, 17, 19 were rejected/deferred per the table above and require no code change.

## Verification

**Commands:**
- `venv/bin/pytest tests/test_puck_bridge* -v` -- expected: all host-bridge unit tests pass using fakes (no live Hermes endpoint, no hardware)
- `../../venv-firmware/bin/esphome compile firmware/respeaker-lite/respeaker-lite.yaml` -- expected: clean compile

**Manual checks (if no CLI):**
- Live hardware smoke: speak "hey jarvis" near the physical Puck; confirm one upload, a correct transcript, a completed Hermes turn, and an audible response on the host speakers -- this is the real acceptance evidence for the hardware-dependent tasks, not test-suite passage alone.

**Live hardware smoke test result (2026-09-10): partially complete, not a full pass.**
See Implementation Notes above for the full session. Confirmed on real hardware: wake
detection (`Hey Jarvis`/`Okay Nabu`, 0.99+ confidence), VAD-gated capture start/end, a
complete chunked upload reaching the bridge, and the bridge's receive -> WAV ->
`faster-whisper` pipeline all working. **Not confirmed:** a full turn from real
spoken content -- every capture large enough to hold real speech stalled mid-upload
on the device's current WiFi signal (-89 to -90 dB) before reaching the bridge.
Independently confirmed via a live `tcpdump` trace to be a link-quality issue (a
stalled `esp_http_client_write()` mid-body, not a routing/firewall/application bug).
Fixed three real pre-existing firmware defects found along the way (see
Implementation Notes: a leftover story-3 serial-dump diagnostic saturating the boot
sequence, a missing wake-engine self-heal, and a too-large upload chunk size for this
link). Tracked as open follow-up work in `deferred-work.md`: re-run this smoke test
once the Puck can be positioned with a stronger signal.
