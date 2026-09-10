# Deferred work

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md`
  summary: Harden the pre-existing reSpeaker diagnostic capture before it is enabled in a normal hardware build.
  evidence: The current dirty firmware configuration automatically captures four seconds of household PCM, emits it through serial logs, captures pre-processed microphone bytes rather than the wake model input, and shares capture state across the audio callback and interval task without synchronization. This work predates Story 1.3 and is outside its frozen intent; disable or make it explicitly opt-in before shipping.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md`
  summary: Add repeatable host and target verification for the pre-existing vendored reSpeaker microphone/DSP path.
  evidence: The local firmware component hard-codes a stereo 32-bit, 48 kHz FIR/decimation path while its schema exposes broader formats, uses unchecked signed byte shifts, leaves no coefficient generator or DSP fixture, and has no repository build or output test. The component and diagnostics were already dirty before this story and are not part of the TUI follow-up slice.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md`
  summary: Audit pre-existing reSpeaker lifecycle and audio-output error handling before relying on the vendored component in production.
  evidence: The dirty firmware tree leaves some configuration fields uninitialized or effectively dead and does not consistently handle I2S callback registration, channel-enable, preload, and partial-write failures. These findings concern the pre-existing hardware work, not the TUI adapter changed by this story.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md`
  summary: Reconcile generated BMad indexes and the older on-device wake-word story's status and provenance.
  evidence: The dirty generated index omits the existing firmware story, that story remains marked done despite its own unresolved detection notes, and its local-vendor documentation needs a single authoritative provenance/license record. This is historical firmware/planning reconciliation outside Story 1.3.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`
  summary: Give the standalone puck_bridge process graceful SIGTERM shutdown so it can run as a background/launchd service.
  evidence: server.py's main() only catches KeyboardInterrupt around serve_forever(); real, but this story's Intent frames the bridge as a proof-of-pipeline test harness, not a production service, so production-shutdown hardening is outside its Tasks & Acceptance.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`
  summary: Guard on_wake_word_detected against firing wake_capture for the internal `stop` model once a future story enables it.
  evidence: micro_wake_word.cpp:526 fires wake_word_detected_trigger_ for any detected model regardless of internal_only (that flag only gates get_wake_words()'s external listing). Not currently reachable -- respeaker-lite.yaml never enables the `stop` model -- but real and latent for whichever story wires FR-5's real stop behavior.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`
  summary: Add a test covering puck_bridge/server.py's main() (missing-PUCK_DEVICE_TOKEN exit path, ThreadingHTTPServer/TurnRunner wiring).
  evidence: tests/test_puck_bridge.py stops at the receiver/handler-factory/turn-runner layers; main() itself is thin entry-point wiring with no direct coverage.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`
  summary: Create the PUCK-01.7 GitHub Project card (Puck-side response playback) once the GitHub API rate limit clears.
  evidence: docs/friction-log.md's 2026-09-09 entry names PUCK-01.7 as the candidate card but notes it was not yet created due to a GitHub API rate limit at the time; per this repo's own convention the friction log is not itself a task source, so this needs manual promotion to the board.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`
  summary: TurnRunner._send()'s new SEND_TIMEOUT_SECONDS guard (fix round 1) does not cancel the abandoned `_run_turn` coroutine on timeout, so it keeps running in the background loop and can still write to the shared PCMPlayer after `_send` has already returned False.
  evidence: `future.result(timeout=...)` only stops waiting on the caller's side; the coroutine itself is not cancelled. A second turn starting while the first's orphaned `_run_turn` is still draining `send_turn()` could interleave writes to the same `self._player`. Real but low-likelihood (requires an actual Hermes hang exceeding 10s, already an anomalous condition), and a correct fix needs careful cross-thread cancellation (`future.cancel()` plus confirming the async generator actually unwinds) rather than a one-line change -- deferred rather than rushed into this fix round.
