---
title: 'Stream audio to host after a validated wake'
type: 'feature'
created: '2026-09-09'
status: 'not-started'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '8e6ed41e1eb0e9bac77854f2911932bb0524c0c4'
context:
  - '{project-root}/_bmad-output/specs/spec-hermes-relay-tui/SPEC.md'
  - '{project-root}/firmware/respeaker-lite/respeaker-lite.yaml'
  - '{project-root}/firmware/respeaker-lite/pcm_capture.h'
  - '{project-root}/session.py'
  - '{project-root}/handsfree.py'
  - '{project-root}/voice.py'
  - '{project-root}/config.py'
  - '{project-root}/home_display/server.py'
  - '{project-root}/firmware/respeaker-lite/tools/label_captures.py'
---

## Intent

**Problem:** Story 3 gave the Puck working on-device wake-word detection
(`hey_jarvis`/`okay_nabu` fire cleanly on real speech), but nothing carries
that moment forward. There is no host-side receiver, no transport from Puck
to host, and no wiring from a captured utterance into a real Hermes turn.
The Puck can hear its wake word and then does nothing with it.

**Approach:** Add a minimal host-side bridge that accepts one bounded,
VAD-gated audio upload per wake event from the Puck over WiFi, reassembles
it into a WAV using the exact `MicrophoneSource`-conversion math already
validated in `tools/label_captures.py`, transcribes it locally with the
existing `voice.py:transcribe()` (unchanged, already decoupled from
`sounddevice`), and feeds the resulting text into
`handsfree.build_hands_free()`'s `capture`/`send` closures against a real
`SessionProtocol` — the same downstream turn machinery the TUI and
household appliance already use, untouched. Firmware-side: on wake, record
into the already-proven PSRAM buffer (`pcm_capture.h`'s pattern), use the
now-working on-device VAD to end the capture window on actual silence
instead of a fixed timer, then do a single bounded chunked upload — the
same chunked-HTTP-POST shape already proven in this story's own training-
data pipeline, not new wire logic.

**Scope decision, human-approved:** this story deliberately does *not*
implement Story 4's real device-credential system. `stories.yaml`'s own
dependency note says Story 5 depends on Story 4 (network identity/
credential enforcement), which is blocked on Epic 3's `DEVICE-01`/`02`/`06`
landing first — none of which exist yet. Rather than wait, this story
stands in a **hardcoded shared token** (via `config.py`'s existing
`token_env`-indirection pattern — a variable name in config, the real
secret from environment/`.env`, never a literal in source) as an explicit,
temporary placeholder for Story 4's credential model. This is not a
security decision to keep; it exists so the audio-transport and turn-
pipeline design can be built and proven now, without waiting on an
unrelated epic. **Do not treat the hardcoded token as done-enough for a
real household deployment** — Story 4, once unblocked, replaces it.

Also out of scope: Epic 3's iOS discovery/pairing UI (`DEVICE-01`, never
actually part of this story to begin with) and playing Hermes's response
back through the Puck's own speaker (no story currently owns this — logged
in `docs/friction-log.md` 2026-09-09, candidate `PUCK-01.7`, not yet
created as a board item pending a GitHub API rate limit). For this story's
validation, the response plays on the **host machine's own speakers**,
mirroring the exact supervised-speaker-smoke pattern Epic 1 Story 1-1
already validated.

</frozen-after-approval>

## Boundaries & Constraints

**Always:** Raw Puck audio stays transient and home-LAN-only (NFR3) — no
audio persisted beyond what's needed to transcribe, no audio leaves the
LAN. The host bridge is a standalone process (not wired into `app.py` or
`home_display/appliance.py`), so this test harness cannot regress either
existing front end. Reuse `voice.py:transcribe()`, `handsfree.py`'s
`HandsFreeCoordinator`/`build_hands_free()`, and `session.py`'s
`SessionProtocol` unchanged — the capture/send contract is text-level
(`capture() -> str`, `send(str)`), proven decoupled from any particular
audio source in Story 1-1's own implementation.

**Never:** No changes to `wake.py` or `handsfree.py`'s core contracts —
research this session confirmed neither needs to change for a new capture
source. No real-time/streaming audio transport (defer — bounded
record-then-upload only, matching the already-proven chunked-upload
pattern). No Story 4 credential system, no `DEVICE-01` iOS UI, no Puck-side
response audio playback — all explicitly out of scope above. No changes to
`pcm_capture.h`'s existing WiFi-upload reliability characteristics beyond
what this story needs (a single wake-triggered upload, not continuous
rolling capture — a fundamentally different, much lower-frequency use
case than what earlier sessions found unreliable).

## Code Map

- `firmware/respeaker-lite/respeaker-lite.yaml` — wire
  `on_wake_word_detected:` (currently absent; wake is only diagnostically
  logged, never acted on) to start a bounded post-wake capture into the
  existing PSRAM buffer, gated on VAD state to end the window, then trigger
  one chunked upload. Reuses `micro_wake_word`'s own `vad:` block (already
  configured and proven responsive this session) rather than adding new
  audio-level silence detection.
- `firmware/respeaker-lite/pcm_capture.h` — adapt the existing
  chunked-upload function (currently `upload_and_restart`, used for
  training-data collection) into a single-shot, wake-triggered variant with
  no re-arm — closer to `dump_over_serial()`'s bounded, no-re-arm shape
  than the continuous rolling-capture path.
- New: a host-side bridge script (exact filename TBD during
  implementation, e.g. `puck_bridge.py`) — HTTP receiver matching
  `tools/receiver.py`'s chunked-upload shape, hardcoded-token check via
  `config.py`'s `token_env` pattern, WAV reassembly via the conversion math
  in `tools/label_captures.py`'s `process_frame_sample()`, then
  `voice.py:transcribe()` and `handsfree.build_hands_free()` wiring against
  a real `SessionProtocol` using an existing Hermes profile.
- `config.py` — add a `PUCK_DEVICE_TOKEN`-style env-indirected token
  alongside the existing per-profile token pattern; no changes to the
  existing resolution logic itself.
- `docs/friction-log.md` — already has the 2026-09-09 entry for the
  deferred Puck-response-playback gap; no further edits expected from this
  story unless new gaps surface.

## Tasks & Acceptance

**Execution:**
- [ ] `firmware/respeaker-lite/respeaker-lite.yaml`/`pcm_capture.h` — wire
  `on_wake_word_detected:` to a bounded, VAD-gated single-shot capture and
  upload — turns a detected wake into an actual outbound audio payload for
  the first time in this story's history.
- [ ] Host-side bridge script — chunked-upload receiver, hardcoded-token
  check, WAV reassembly, `transcribe()` call — gives the Puck's audio a
  real host-side landing point.
- [ ] Wire the bridge's transcript into `handsfree.build_hands_free()`'s
  `capture`/`send` closures against a real `SessionProtocol` — proves the
  existing turn machinery accepts a non-local-mic capture source
  unmodified.
- [ ] End-to-end live test: speak "hey jarvis" near the physical Puck,
  confirm the utterance streams to the host, transcribes correctly, and a
  real Hermes turn completes with the response audible on the host
  machine's speakers.
- [ ] `firmware/respeaker-lite/README.md` — document the new
  wake-to-upload behavior and the hardcoded-token stand-in for Story 4,
  matching this story's own documentation discipline.

**Acceptance Criteria:**
- Given a validated on-device wake (`hey_jarvis` or `okay_nabu`), when the
  Puck finishes capturing the resulting utterance (VAD-gated, not a fixed
  timer), then exactly one bounded upload reaches the host bridge.
- Given a valid hardcoded token on the upload, when the bridge receives a
  complete capture, then it produces a WAV file and a Whisper transcript
  without modifying `voice.py`'s `transcribe()`.
- Given a produced transcript, when it is handed to
  `handsfree.build_hands_free()`'s wiring, then exactly one real Hermes
  turn is submitted through the existing, unmodified `SessionProtocol`,
  and the response is audible on the host machine's speakers.
- Given a missing or invalid token, when an upload is attempted, then the
  bridge rejects it and no turn is submitted — the fail-closed principle
  from Epic 1 Story 1-1 applies here too, even with a hardcoded credential
  standing in for the real one.

## Implementation Notes

Not started.

## Verification

**Commands:** TBD once the bridge script and firmware changes exist —
expect a focused test run analogous to Story 1-1's
(`tests/test_*` covering the new bridge module with fakes, no live Hermes
endpoint required for those) plus a live hardware smoke (spoken wake →
transcript → turn → audible response) as the actual acceptance evidence,
matching this project's established pattern of not claiming success from
tests alone for hardware-dependent stories.
