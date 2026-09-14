# Deferred work

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md`
  summary: PROMOTED 2026-09-11 as `P-7` in `planning-artifacts/epics.md`: make raw PCM diagnostics explicitly opt-in and bounded before relying on the path in a normal household firmware build.
  evidence: The current YAML still starts the training-data capture buffer and copies pre-processed microphone bytes into it, but the normal interval no longer calls `dump_over_serial`; the older note that the default build emits raw PCM is stale. The remaining concern is accidental retention or future export, plus unsynchronized callback/export ownership. This work predates Story 1.3 and remains outside the validated wake-capture path.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md`
  summary: PROMOTED 2026-09-11 as `P-8` in `planning-artifacts/epics.md`: make the vendored reSpeaker audio-format boundary deterministic and testable.
  evidence: The vendored schema accepts a broader format set than the proven ReSpeaker path, which currently consumes 48 kHz, 32-bit, stereo input and decimates by retaining one frame out of three. The YAML amplitude diagnostic also assembles signed samples with unchecked shifts. No deterministic host fixture, expected-output contract, or repeatable firmware/output check currently protects this boundary. The earlier FIR/coefficient wording is obsolete because the FIR was reverted to the board's upstream nearest-frame behavior.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md`
  summary: PROMOTED 2026-09-11 as `P-9` in `planning-artifacts/epics.md`: make ReSpeaker I2S channel startup and teardown fail-safe.
  evidence: The microphone startup path can return after channel allocation, initialization, or enable failure without cleaning a handle or releasing the parent I2S lock. Shared configuration also contains fields that require explicit initialization. Speaker output error semantics and pacing remain separate from this lifecycle slice; these findings concern pre-existing hardware work, not the TUI adapter.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md`
  summary: PROMOTED 2026-09-11 as `P-11` in `planning-artifacts/epics.md`: surface ReSpeaker runtime audio-output failures honestly and recoverably.
  evidence: The vendored speaker boundary already logs low-level event, partial-write, and lockstep failures, but the remaining slice must define how those failures propagate to the Puck media/player state and cleanly isolate the next response. P-5 pacing and P-9 startup/teardown ownership remain separate.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-continue-with-bounded-follow-up-and-exact-stop.md`
  summary: RESOLVED 2026-09-11 -- current generated index and the Story 3 record agree that on-device wake detection is not done; provenance and license findings are recorded in `firmware/respeaker-lite/THIRD_PARTY_NOTICES.md`.
  evidence: Cross-checked `_bmad-output/specs/spec-hermes-relay-tui/stories.yaml` (story 3 present, `done_checkpoint: false`) against `_bmad-output/specs/spec-hermes-relay-tui/stories/3-implement-on-device-wake-word-detection.md` (status: `in-progress -- see RESUME HERE below, not done`). No generated-index edit was necessary. The new notice identifies the vendored ESPHome/formatBCE sources, pinned commits or versions, model manifest authors and websites, SHA-256 fingerprints, explicit license sources, and artifacts whose per-file terms are not stated; it records uncertainty rather than inventing a license. This is historical firmware/planning reconciliation outside Story 1.3.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`
  summary: PROMOTED 2026-09-11 as `P-6` in `planning-artifacts/epics.md`: give the standalone `puck_bridge` process graceful signal shutdown and direct entry-point coverage.
  evidence: server.py's main() only catches KeyboardInterrupt around serve_forever(); real, but this story's Intent frames the bridge as a proof-of-pipeline test harness, not a production service, so production-shutdown hardening is outside its Tasks & Acceptance.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`
  summary: PROMOTED 2026-09-11 as `P-10` in `planning-artifacts/epics.md`: keep internal wake models out of ordinary capture routing.
  evidence: `micro_wake_word.cpp:526` fires `wake_word_detected_trigger_` for any detected model regardless of `internal_only`; that flag only gates external listing. `respeaker-lite.yaml` already enables the internal `stop` model, so this is an active routing gap, not a future-only concern. The callback currently sends every model name to `wake_capture::start()`; P-10 adds the fail-closed boundary without redefining spoken `stop` semantics.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`
  summary: DUPLICATE 2026-09-11 -- the `server.py main()` test is consolidated into `P-6` above because it covers the same process-lifecycle boundary.
  evidence: tests/test_puck_bridge.py stops at the receiver/handler-factory/turn-runner layers; main() itself is thin entry-point wiring with no direct coverage.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`
  summary: RESOLVED 2026-09-10 -- superseded by Epic 1's 2026-09-10 surface decomposition. The friction log's candidate `PUCK-01.7` is now `1-p-2-status-and-response-audio-delivery`, which is recorded in the local BMad artifacts. No GitHub Project card is required while Project #3 is paused.
  evidence: `spec-1-p-2-status-and-response-audio-delivery.md` owns the Puck status and response-audio scope; its tasks 1-7 are implemented or explicitly verified in the local delivery record.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`
  summary: RESOLVED 2026-09-11 in the local P-2 delivery work. A timed-out turn now cancels the abandoned `_run_turn` coroutine instead of merely stopping the caller's wait.
  evidence: P-2 task 6 was delivered across #150 and #155 and verified in `puck_bridge/turn.py`; the turn backstop calls `future.cancel()`, and the per-event processing guard prevents a wedged audio sink from poisoning the next turn. This is not a new ticket.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`
  summary: RESOLVED on main in #138 ("always mint a distinct bridge session id"), which landed before this branch's work began. build_session_args() now suffixes the resolved session_id unconditionally, except when --session-id is passed explicitly on the bridge's own command line, which is honored verbatim. Verified live on this branch: session_id=amanda-kiosk-puck-bridge, no longer the TUI's amanda-kiosk. A duplicate fix written here on 2026-09-10 was discarded in favour of main's during the merge -- it had been written against this stale entry without first checking main.
  evidence: Found live during this story's hardware smoke test. The fix-round patch for finding #5 (only default session_id when falsy) is correct against an explicit `--session-id` CLI override, but config.build_arg_parser() already populates a non-empty session_id from the profile's own YAML config (e.g. "amanda-kiosk") before that check runs -- so the "only set when unset" guard never actually fires for a normal profile-based invocation, and the bridge always inherits the TUI's own session id. Needs a design decision (unconditional distinct suffix, or a bridge-specific config key) rather than a one-line fix.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`
  summary: RESOLVED 2026-09-10 -- chunked upload confirmed reliable once the Puck was moved to a stronger WiFi signal; the mid-transfer stall was signal-related, not a code defect.
  evidence: A follow-up hardware session with the Puck relocated (Mac's own radio read -54 dBm at the new spot, versus -89/-90 dBm previously) completed six consecutive wake-triggered captures end to end -- every chunk of every upload (62-67 chunks each) landed with no failures, no stalls, no TTL evictions. This closes the specific defect this entry tracked; the full spoken Hermes round trip is now also recorded as verified in P-2.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`
  summary: RESOLVED 2026-09-10 -- `micro_wake_word.stop_after_detection: false` keeps the inference task and VAD alive while wake capture runs.
  evidence: In the same 2026-09-10 hardware session (strong WiFi, uploads all succeeding), six separate wake-triggered captures across multiple deliberate retries -- including one where the command was spoken with zero pause immediately after the wake phrase -- all landed within 123760-133280 bytes, matching faster-whisper's own reported duration of 0.946-1.041s almost exactly. `pcm_capture.h`'s `tick()` only closes the window after `VAD_SILENCE_DEBOUNCE_MS` (800ms) of *continuous* silence per `micro_wake_word`'s own VAD state, resetting on any `vad_active` reading -- so this consistent ~1s ceiling across every trial, independent of what was said afterward, means the on-device VAD is not recognizing sustained speech as active at all rather than the capture window being cut short by a pause. Every capture's transcript came back empty. `respeaker-lite.yaml`'s `vad: probability_cutoff: 0.05` is already permissive, so the likely culprit is audio level/gain into the shared `micro_wake_word` feature pipeline rather than the threshold itself. ROOT CAUSE (code read, no new hardware session needed): `components/micro_wake_word/__init__.py` declares `cv.Optional(CONF_STOP_AFTER_DETECTION, default=True)`, and `respeaker-lite.yaml` never overrode it. `micro_wake_word.cpp`'s `DETECTING_WAKE_WORD` case fires `wake_word_detected_trigger_` and then calls `stop()` in the same loop iteration, so the moment `wake_capture::start()` runs the inference task begins tearing down: `process_probabilities_()` stops writing `vad_state_`, `unload_models_()` clears the VAD sliding window, and `microphone_source_->stop()` drops the audio source. `get_vad_state()` therefore stops tracking reality the moment a capture starts. CORRECTED TIMING (measured 2026-09-10 against the unfixed build): the ~1s ceiling is NOT first-tick + 800ms debounce as first reasoned -- it is the self-heal gap. Serial logs show `Stopping wake word detection` at the same millisecond as the wake trigger, `mic_diag` going silent for 1.7s (26.14s -> 28.43s, exactly while the command was spoken), the 2s `mww stopped -- restarting` self-heal re-arming detection, and only then VAD reading real silence and closing the window 800ms later at 130560 bytes. The captured second is post-restart audio, not the question. Gain/threshold were never the problem. This also explains the self-heal firing on every wake, previously attributed to weak-signal instability. FIX: `stop_after_detection: false` added to the `micro_wake_word:` block. VERIFIED on hardware 2026-09-10 21:43: same wake phrase and position, `Stopping wake word detection` never fires, mic stays continuous, capture grew 130560 -> 314160 bytes (1.02s -> 2.45s, window tracking actual speech and closing 800ms after it stopped), and faster-whisper's VAD filter went from stripping 1.020s of 1.020s (all silence, empty transcript, language confidence 0.57) to stripping only 0.966s of 2.454s -- 1.49s of real speech retained, confidence 0.98, non-empty transcript. Firmware defect closed. The full spoken round trip is still unproven, now blocked on the pre-existing 10s SEND_TIMEOUT_SECONDS turn timeout (see the TurnRunner._send entry above), not on capture.
- source_spec: `_bmad-output/implementation-artifacts/spec-2-wk-2-render-active-capture-room-local-transcription-response-and.md`
  summary: RESOLVED 2026-09-11 as a `2-WK-2` refinement in `planning-artifacts/epics.md`: define an optional browser-local `transcribing` interval without adding a shared phase.
  evidence: W/K now has an explicit contract for delayed versus immediate SpeechRecognition finalization: paint `transcribing` only when a real local interval exists, retain final user text through submission, and keep the shared `DisplaySnapshot` and Hermes wire contracts unchanged. Focused browser timing coverage remains part of delivery validation.

- source_spec: `_bmad-output/implementation-artifacts/spec-web-epic-1-reliable-conversation.md`
  summary: PROMOTED 2026-09-11 as `2-WK-5` in `planning-artifacts/epics.md`: validate direct-use browser actions at the server boundary against the currently published prompt and advertised capability.
  evidence: `DisplayServer` currently treats `/action` as a same-origin transport callback and does not inspect the publisher's current prompt; the restored App validates actions through `DisplayBridge`, but a direct request can still reach the callback without that reducer gate. Implementing this safely requires a shared server-side action authority and is pre-existing transport behavior outside this DOM restoration.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md`
  summary: PROMOTED 2026-09-11 as `3-P-3` in `planning-artifacts/epics.md`: carry each detected wake mapping through capture and route it to its bound Hermes Profile.
  evidence: The `wake_word` automation variable micro_wake_word's on_wake_word_detected trigger provides is passed into `pcm_capture::wake_capture::start(wake_word)` (pcm_capture.h) but used only in log lines there -- it is never stored past that call, so `wake_capture::upload()` never sends it (only `seq`/`chunk`/`total`/`ms` in the query string and a shared `X-Puck-Token` header). On the host side, `puck_bridge/server.py` builds exactly one `HermesSession`/`TurnRunner` at startup against a single fixed `--profile`, and `receiver.py`'s `make_handler()` binds one hardcoded `on_transcript` callback with no per-request routing key at all. Needs, at minimum: (1) firmware change to carry `wake_word` into the upload request, (2) `receiver.py` to parse it per capture, (3) a dispatch layer above the current single-session wiring in `server.py` to route to a per-wake-word `HermesSession`/`TurnRunner` instead of one shared one.

- source_spec: `_bmad-output/implementation-artifacts/spec-web-epic-1-reliable-conversation.md`
  summary: VERIFY remains open 2026-09-11 -- the automated DOM gate passes, but the physical Safari/iPad HTTPS/WSS, permission, audio, and direct-touch gate still requires the target device.
  evidence: From `home_display/web`, `npm test` passed 12 files and 178 tests, `npm run check` found zero errors or warnings, and `npm run build` produced the production bundle. The available computer-use inventory exposed Chrome on the Mac but no Safari/iPad surface, so Guided Access, iPad certificate trust and secure-channel hydration, microphone permission, speaker playback, and physical touch-button operation remain unverified. The HOME-09 procedure remains the authoritative manual gate; the existing 2026-09-09 iPad follow-up recovery note covers that narrower recovery scenario, not this full kiosk gate.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-t-1-use-the-tui-as-an-independent-direct-voice-chat-gateway.md`
  summary: Define one-time ownership for migrating an unscoped legacy prompt-history file when more than one named profile is later used.
  evidence: The approved story requires copying an ownerless flat or endpoint-scoped source into the selected profile without deleting it, but does not say whether the same source may seed multiple profiles; a product decision or migration marker is needed to settle the privacy/continuity tradeoff.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-t-1-use-the-tui-as-an-independent-direct-voice-chat-gateway.md`
  summary: Make prompt-history writes safe across separate TUI processes sharing one profile file.
  evidence: `PromptHistory` serializes writes only within one instance; two simultaneous TUI processes can still read stale entries and atomically replace one another's file. This predates the story's per-instance lock and needs deliberate cross-process locking semantics.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-t-1-use-the-tui-as-an-independent-direct-voice-chat-gateway.md`
  summary: Run physical permission/authorization and first-response latency checks for the independent TUI doorway.
  evidence: Epic 5's broader context calls for fail-closed identity handling and roughly four-second first spoken response audio, but this slice changed no authorization or audio transport code and no live Hermes, microphone, or PortAudio environment was available for that evidence.

## Deferred from: code review of spec-1-4-recover-without-replaying-an-uncertain-turn (2026-09-10)

- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-recover-without-replaying-an-uncertain-turn.md`
  summary: PROMOTED 2026-09-11 as `T-5` in `planning-artifacts/epics.md`: move wake listener and recorder teardown off the Textual event loop.
  evidence: The new `/reconnect` handler calls synchronous `_disarm_wake`; that existing path joins the wake listener and calls `recorder.shutdown()` directly, even though both can wait on native audio/thread cleanup. The concern is real, but the fix requires refactoring the shared wake lifecycle and its synchronous callback callers rather than changing only recovery.
  reason: pre-existing lifecycle boundary; deferred outside the T-4 recovery slice. The duplicate review finding below is consolidated into the same ticket.

## Deferred from: code review of story-1-3-continue-with-bounded-follow-up-and-exact-stop (2026-09-10)

- DUPLICATE 2026-09-11 -- wake-listener `stop()` can join its worker for up to two seconds when connection recovery calls `_disarm_wake()` from the Textual event loop. Consolidated into `T-5` above.
- The review also re-confirmed the pre-existing reSpeaker diagnostic, format, lifecycle, output, and provenance findings already recorded at the top of this file. They remain outside the TUI follow-up slice and must not be folded into its implementation.

## Deferred from: code review of spec-continuous-wake-free-follow-ups (2026-09-11)

- source_spec: `_bmad-output/implementation-artifacts/spec-continuous-wake-free-follow-ups.md`
  summary: RESOLVED 2026-09-11 -- reconciled `AGENTS.md` so normal hands-free exits, remote failures, and transport disconnects have distinct documented outcomes.
  evidence: `AGENTS.md` now says silence, exact `stop`, and local capture/recognition failure return to wake detection; remote failure or interruption opens no follow-up and preserves its terminal state; transport failure or disconnect disarms wake mode, closes the microphone, and requires `/wake on` after reconnect. This matches the implemented `_disarm_wake()` and `_mark_connection_lost()` paths and removes the previous contradiction without changing code.

## Deferred from: code review of spec-2-t-2-keep-tui-disconnect-recovery-presentation-honest-without-replaying-an-uncertain-turn (2026-09-11)

- source_spec: `_bmad-output/implementation-artifacts/spec-2-t-2-keep-tui-disconnect-recovery-presentation-honest-without-replaying-an-uncertain-turn.md`
  summary: PROMOTED 2026-09-11 as `T-6` in `planning-artifacts/epics.md`: detect idle relay loss and classify transport failures honestly without replaying an uncertain turn.
  evidence: The current fallback avoids an import failure on websockets 13.x, but the diff does not establish whether that version's concurrent-reader `RuntimeError` should be classified as transport loss, and the one-reader guard makes the path unreachable in normal use. Settle with a supported 13.x test environment and an explicit classification decision before changing the broad `RuntimeError` boundary.

- source_spec: `_bmad-output/implementation-artifacts/spec-2-t-2-keep-tui-disconnect-recovery-presentation-honest-without-replaying-an-uncertain-turn.md`
  summary: CONSOLIDATED 2026-09-11 into `T-6` above: detect a relay drop while the TUI is idle.
  evidence: The client has no idle receive/liveness path, so a remote drop can remain visibly connected until the next operation. This is pre-existing and requires a separate liveness policy outside the reviewed presentation change.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-p-1-authorized-wake-and-capture.md`
  summary: RESOLVED 2026-09-11 on `main` in #149: long Puck captures now arrive before bridge eviction and delivery status is reported honestly.
  evidence: Observed live 2026-09-10 23:20-23:30, three consecutive captures lost. A full capture is WAKE_CAPTURE_SECONDS=8 at 128000 B/s = 1024000 bytes (512 chunks). Measured upload throughput is 25.3 KB/s (314160 bytes in 12.14s on 2026-09-10; ~77ms per 2KB chunk, dominated by per-POST TCP setup because ESPHome's IDF http_request backend opens a fresh esp_http_client connection per post() call, plus the deliberate 30ms inter-chunk delay). 1024000 / 25.3KB/s = ~39.5s, against `receiver.py`'s PENDING_CAPTURE_TTL_SECONDS = 30.0. The two limits are set against each other: the effective ceiling is ~759KB (~6.1s of audio) but the capture buffer is 8s, so any capture that runs to the buffer limit can never complete. Bridge logged `evicting abandoned capture seq=0` at 361/512, 151/512 and 370/512 chunks. Not a heap or stability problem -- device uptime climbed normally throughout and no heap-watermark warning fired. SECOND DEFECT, arguably worse: the failure is invisible from either side. `pcm_capture.h`'s `upload()` logs "Uploaded wake capture N (1024000 bytes, 512 chunks)" whenever no individual chunk POST returned non-2xx, which is true -- the bridge accepts every chunk and only discards the *reassembly* on TTL. So the firmware reports success, the bridge reports an eviction warning, and nothing anywhere says "this turn was lost". Also note every capture logged seq=0: `sample_index` is logged before it increments and only advances per completed upload call, so the id is not a reliable correlation key across the two sides. FIX NEEDS A DECISION, three non-equivalent options: (a) raise the TTL -- one line, but leaves a ~40s round trip, far too slow to hold a conversation; (b) shrink WAKE_CAPTURE_SECONDS to ~6 so the two limits agree and long questions fail honestly rather than silently, cheap stopgap but truncates real speech; (c) fix the transport -- a persistent connection or a single streaming upload would collapse the per-POST setup cost that is nearly all of the 77ms, which is the correct fix and the largest change. Whichever is chosen, the silent-success logging should be fixed independently, since it would hide the next transport regression just as effectively.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-p-2-status-and-response-audio-delivery.md`
  summary: PROMOTED 2026-09-11 as `P-5` in `planning-artifacts/epics.md`: deliver streamed Puck responses without underrun. The implementation is not yet complete.
  evidence: Reported by ear 2026-09-12 and narrowed considerably, but NOT solved. What is ruled OUT -- (a) the bridge: curl pulled 303148 bytes from the same /response endpoint, complete and well-formed, where the device stopped at 127232; (b) the framing: a controlled probe served the SAME 20s/960KB audio two ways, static-with-Content-Length and chunked-with-sentinel-0xFFFFFFFF, and the device consumed BOTH in full, so chunked encoding and the sentinel WAV length are fine; (c) the WAV itself: captured output is structurally perfect (RIFF/WAVE/fmt/data, 24kHz mono 16-bit) with real speech (peak 14335, 73% of samples above 200). What is ruled IN -- pacing. The probe that succeeded deliberately sent 100ms of audio every 90ms (~11% faster than real time) and never ran dry; the bridge forwards Hermes chunks as they arrive. The device stops CLEANLY (ANNOUNCING -> IDLE, no error), which is what an underrun looks like from outside. The cut point was 127232 bytes twice exactly, which is suspiciously deterministic for a pure underrun and remains unexplained. CAUTION for whoever picks this up: a 2s prebuffer did not help, 5s was not tested properly, and 8s made it WORSE (delivered 0 bytes -- the reader saw a format then no chunks for 20s and ended the body), so prebuffer size is not a simple dial. Measure before changing anything: the one fix that demonstrably helped this session came from measuring device log volume, not from reasoning. Related and already fixed: per-inference wake diagnostics were starving the audio tasks (47 log lines/sec -> 1, ring-buffer overflows ~40/30s -> 0).

## Deferred from: code review of spec-1-p-1-authorized-wake-and-capture (2026-09-12)

- source_spec: `_bmad-output/implementation-artifacts/spec-1-p-1-authorized-wake-and-capture.md`
  summary: RESOLVED 2026-09-12 -- the ReSpeaker firmware compile gate ran successfully as part of the post-P-2 hardware validation.
  evidence: `venv-firmware/bin/esphome compile firmware/respeaker-lite/respeaker-lite.yaml` succeeded with ESPHome 2026.8.2, followed by a successful OTA upload and clean boot on the physical Puck. The repository's YAML/source tests remain the fast host gate; the compiled image is the hardware validation evidence.

## Deferred from: code review of spec-1-p-2-status-and-response-audio-delivery (2026-09-12)

- source_spec: `_bmad-output/implementation-artifacts/spec-1-p-2-status-and-response-audio-delivery.md`
  summary: CONSOLIDATED into `P-5` in `planning-artifacts/epics.md`: bound the in-memory response queue and define backpressure/underrun behavior for a device consumer that is slower than the Hermes producer.
  evidence: `puck_bridge/response.py` appends response chunks without a memory limit while the HTTP consumer is paced by the Puck. The existing P-5 record already owns streamed-response pacing and underrun diagnosis; changing the queue policy in isolation could trade an underrun for unbounded memory or silent truncation.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-p-2-status-and-response-audio-delivery.md`
  summary: CONSOLIDATED into `P-6` in `planning-artifacts/epics.md`: direct `server.main()` lifecycle and entry-point coverage.
  evidence: `server.main()` remains thin wiring around the covered handler and runner layers; the missing direct invocation/interrupt cleanup test is the same process-lifecycle boundary already recorded for P-6.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-p-2-status-and-response-audio-delivery.md`
  summary: DEFERRED as pre-existing firmware-surface work: authenticate the port-80 web controls.
  evidence: The firmware exposes web controls without authentication, but that surface predates P-2 and is unrelated to the `/response` token handoff. Keep it separate from the P-2 response-authentication decision.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-p-5-complete-streamed-response-playback-without-underrun.md`
  summary: Define a reboot-safe response sequence epoch for the Puck capture counter.
  evidence: `pcm_capture.h` resets its in-memory `sample_index` to zero on reboot, while the long-lived bridge now rejects non-increasing response sequences. A reboot after a prior response can therefore reuse an old sequence; resolving that needs a capture/boot-epoch contract outside P-5, and P-5 leaves `pcm_capture.h` unchanged.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-p-5-complete-streamed-response-playback-without-underrun.md`
  summary: Propagate decoder, DMA, and speaker-output failure after bridge delivery completes.
  evidence: The bridge's `complete` status proves source accounting and HTTP delivery only. Detecting an output failure after the response drains belongs to the P-11 speaker path explicitly excluded from P-5.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-p-5-complete-streamed-response-playback-without-underrun.md`
  summary: Bound or stream the pre-existing Hermes `audio_file` fallback buffer.
  evidence: `TurnRunner._run_turn()` has accumulated the fallback in a `bytearray` since the original runner implementation; making that path incremental requires a decoder/format boundary not owned by the P-5 live PCM queue.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-p-5-complete-streamed-response-playback-without-underrun.md`
  summary: RESOLVED 2026-09-12 -- restore the pre-existing ESPHome compile blocker for `last_capture_captured`.
  evidence: Restored the declaration and both capture-close latches in `firmware/respeaker-lite/pcm_capture.h`, with a focused static contract test. `venv/bin/pytest -q tests/test_puck_firmware.py` passes with 12 tests and `venv/bin/pytest` passes with 1,090 tests plus the existing `websockets.legacy` deprecation warning. `venv-firmware/bin/esphome compile firmware/respeaker-lite/respeaker-lite.yaml` succeeds, and the resulting image was uploaded over OTA; the device booted and reported the `respeaker-lite-p5` build label.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-p-5-complete-streamed-response-playback-without-underrun.md`
  summary: VERIFIED 2026-09-12 -- the controlled physical P-5 gate passed.
  evidence: With Mac playback disabled, five controlled 24-second responses delivered 1,152,000 source and delivered PCM bytes with matching SHA-256 values, consumer gaps no larger than 0.001 seconds, and terminal `complete`; the device logged HTTP 200, HTTP read complete, decoder finish, media idle, terminal confirmation, and wake resumption. A temporary MacBook Air microphone observer detected the defined 240 ms 880/1320/1760 Hz marker exactly once at normalized correlation 0.842, with timing error -0.249 seconds against the expected marker position after logged output start (inside the +/-500 ms bound). Capture-end-to-first-response-audio measured 2.652 seconds median across five runs (under the 4-second bound), and the post-playback second wake completed successfully. Temporary observer audio and diagnostic logs were removed after metric extraction. The separate reboot sequence epoch, post-delivery decoder/DMA failure propagation, and fallback-buffer items remain deferred to their owning boundaries.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-p-5-complete-streamed-response-playback-without-underrun.md`
  summary: Exchange and authenticate the firmware build identity with the bridge.
  evidence: The bridge records the configured `respeaker-lite-p5` deployment label and the helper logs the same identity, but no P-5 protocol handshake proves which image is connected. A multi-firmware identity contract would expand the device-administration boundary beyond this story.
## Deferred from: code review of spec-1-t-6-detect-idle-relay-loss-and-present-honest-recovery-without-replaying-an-uncertain-turn (2026-09-12)

- source_spec: `_bmad-output/implementation-artifacts/spec-1-t-6-detect-idle-relay-loss-and-present-honest-recovery-without-replaying-an-uncertain-turn.md`
  summary: Carry wake and barge-in callback identity through session replacement.
  evidence: The T-6 review found that wake and barge callbacks still resolve app state dynamically. T-6 already disarms wake resources before recovery, but complete callback ownership requires the separate T-5 lifecycle slice and must not alter the frozen idle-loss contract.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-t-6-detect-idle-relay-loss-and-present-honest-recovery-without-replaying-an-uncertain-turn.md`
  summary: Bound interrupt-fallback session cleanup through the retained close helper.
  evidence: The fallback at `app.py:3681` directly awaits the retired session's close. That path predates T-6 and belongs with interrupt/shutdown cleanup rather than idle-loss detection.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-t-6-detect-idle-relay-loss-and-present-honest-recovery-without-replaying-an-uncertain-turn.md`
  summary: Do not reuse a session while a timed-out handshake close is still settling.
  evidence: The retry loop reuses the same session after bounded cleanup times out. This is pre-existing retry/transport-lifecycle behavior and needs a dedicated regression slice before changing session replacement policy.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-t-6-detect-idle-relay-loss-and-present-honest-recovery-without-replaying-an-uncertain-turn.md`
  summary: Separate the unrelated Puck reader-release test change from the T-6 delivery.
  evidence: `tests/test_puck_bridge.py` changed in the merged T-6 commit, but the hunk belongs to the Puck response-stream workstream and should be reviewed or split there rather than altered during TUI recovery closure.

## Deferred from: first Android device session against the live relay (2026-09-12)

- source_spec: `hermes-relay-android/_bmad-output/implementation-artifacts/spec-a-4-relay-configuration.md`
  summary: OPEN 2026-09-12 -- `A-4`'s honest off-tailnet unavailable state is unreachable for the endpoint actually in use. Candidate for an upstream story identity rather than a local ticket, because it is `A-4` acceptance scope.
  evidence: Detection depends on `UnknownHostException`. `voice-amanda.chappell-home.dev` resolves publicly to the Tailscale address `100.106.8.34`, confirmed against `8.8.8.8`, so DNS succeeds off the tailnet. The socket then waits out the 10 s connect timeout, which classifies as `Retryable`; the bounded ladder exhausts and the user sees a bare `Disconnected`. The criterion was met against the original `media-server.<magicdns>` endpoint, which resolved only through MagicDNS; the Caddy arrangement changed the hostname and silently invalidated the strategy. A connect timeout to `100.64.0.0/10` is a stronger signal than DNS failure.

- source_spec: `hermes-relay-android/_bmad-output/implementation-artifacts/spec-a-3-fresh-recovery.md`
  summary: OPEN 2026-09-12 -- the bounded reconnect ladder discards its retained reason, so the state users actually reach is the least informative one.
  evidence: `AndroidRecovery.recover()` tracks `lastReason` across every retry and drops it when the ladder exhausts. Surfacing it would have identified the off-tailnet defect above immediately rather than requiring a source read.

- source_spec: `hermes-relay-android/_bmad-output/implementation-artifacts/spec-a-8-response-audio-playback.md`
  summary: OPEN 2026-09-12 -- Android response audio arrives slower than real time and underruns during playback. Same territory as `P-5`.
  evidence: `AudioFlinger` logged `BUFFER TIMEOUT ... due to underrun` four times in a single response on a Pixel 6a, each followed by a track restart. Playback was audibly correct, so this is not a perceived-quality defect today. The underruns were nonetheless what made the drain guard's `playbackHeadPosition == framesWritten` condition unsatisfiable; that symptom is fixed by a stalled-playhead exit, but the streaming rate itself is untouched.

- source_spec: `hermes-relay-android/_bmad-output/implementation-artifacts/spec-a-2-honest-phases.md`
  summary: WATCH 2026-09-12 -- the phase can now be `Listening` with a null `binding`, because hands-free reopen starts a turn at the microphone rather than at the first relay event.
  evidence: Introduced deliberately to stop the UI reporting `Complete` over a live microphone. Nothing reads `binding` in that window today and `A-3`'s ladder keys off connection state, but recovery and interruption while hands-free is armed should be checked here first.

- source_spec: `hermes-relay-android/_bmad-output/implementation-artifacts/spec-a-6-hands-free.md`
  summary: OPEN 2026-09-12 -- echo and barge-in remain unverified on hardware; the last piece of `A-6`'s environment limitation.
  evidence: The Pixel 6a session confirmed continuation works and that reopen latency reads as a natural beat rather than a stall. Playback was audible through the device speaker, but no deliberate barge-in was attempted, so whether the speaker leaks into the next capture window is still unknown.

- source_spec: `hermes-relay-android/_bmad-output/implementation-artifacts/spec-5-a-2-accessibility.md`
  summary: OPEN 2026-09-12 -- `5-A-2` was validated without a screen reader or a contrast measurement, both named by `UX-DR21`.
  evidence: The semantics tree is correct and lint's accessibility checks pass, but TalkBack has never been enabled and no navigation pass has been performed; announcement wording, verbosity, and gesture navigation are unproven. No contrast ratio has been measured against the WCAG 2.2 AA target.

- source_spec: `hermes-relay-android/_bmad-output/implementation-artifacts/spec-a-1-authorized-initiation.md`
  summary: OPEN 2026-09-12 -- the Android client contains no application logging, which made every defect in this session slower to diagnose.
  evidence: There are zero `android.util.Log` call sites in `app/src/main`. Diagnosis rested entirely on platform `AudioFlinger` output. Keeping a privacy-sensitive client quiet by default is defensible, but a debug-only, opt-in record of phase transitions and transport outcomes would have found each of these faster. Worth a deliberate decision rather than remaining an accident.

- source_spec: `hermes-relay-android/_bmad-output/implementation-artifacts/spec-a-4-relay-configuration.md`
  summary: OPEN 2026-09-12 -- Android release engineering: the `versionCode` formula caps minor and patch at 99, and `v0.2.0` still publishes an uninstallable unsigned APK.
  evidence: `versionCode` is derived as `major * 10000 + minor * 100 + patch` and fails the build beyond 99 deliberately, because a silent rollover would produce a lower code than the previous release and break in-place upgrades; widen it before any `0.100.x`. The `v0.2.0` release predates signing, so its asset cannot be rebuilt from its own tree; the tag would have to move to produce a signed one.
## Deferred from: spec-vanilla-hermes-connection-foundation (2026-09-12)

- source_spec: `_bmad-output/implementation-artifacts/spec-vanilla-hermes-connection-foundation.md`
  summary: Defer standard structured-prompt parity for approval, clarify, secret, and sudo requests.
  evidence: The connection proof can establish ordinary JSON-RPC turns without expanding the prompt model. Full parity needs deliberate mapping for masked values, response rejection/expiry, and batch clarify instead of hiding those choices inside the first transport slice.

- source_spec: `_bmad-output/implementation-artifacts/spec-vanilla-hermes-connection-foundation.md`
  summary: Defer session-picker search parity over the standard `session.list` method.
  evidence: The standard method has no free-text search parameter, so matching the current picker requires bounded over-fetching and local title/preview filtering. That is useful product work, but it is not required to prove the gateway connection or plain text turn path.

## Deferred from: 5-A-3 Night Console visual design pass, first device pass (2026-09-12)

- source_spec: `hermes-relay-android/_bmad-output/implementation-artifacts/android-visual-design-pass.md`
  summary: OPEN 2026-09-13 -- `5-A-3` step 7 remains: hardware TalkBack/focus and rendered-appearance re-verification. Steps 1-6 are code-verified; large-font behavior now has emulator regression coverage.
  evidence: Steps 1-6 are delivered in `hermes-relay-android`: the doorway is decomposed into zones, the Night Console palette and its four state roles are in place with contrast coverage widened from 16 pairs to 56, the shell now uses a fixed Material 3 header, a scrolling conversation rail, and a bottom action surface with filled/outlined/text hierarchy, and the state owner explicitly renders no-Profile, unavailable, and ready conditions. The composer keeps disconnected drafts editable and persisted, explains disabled Send, groups recall under `Recent prompts`, and the Local History sheet keeps Profile scope, role/time metadata, newest-at-bottom ordering, and export behind `More`. Capture/playback activity has a restrained indicator that freezes under disabled Android animation scales, while streamed text and partial transcription are not live regions. `Retry` reconnects only, `Edit relay` opens configuration, and unconfirmed turns remain unavailable rather than looking ready. The Android build, 150 JVM tests, lint, APK metadata, and instrumentation APK compilation pass; the host-audio-enabled API 36 emulator passes all 34 non-live instrumentation tests at normal settings and again at `font_scale=1.3` with animation scales disabled. The AVD was restored afterward. The Pixel 6a remains locked, and no live relay profile is loaded, so hardware TalkBack, rendered appearance, and real-session microphone capture remain open; the emulator screenshot also leaves the fixed header's ellipsis as a hardware visual judgment rather than silently calling it a defect.

- source_spec: `hermes-relay-android/_bmad-output/implementation-artifacts/spec-a-1-authorized-initiation.md`
  summary: RESOLVED 2026-09-13 -- `ANDROID-BUG-F4`: Step 5 replaced the stale Android doorway bootstrap copy with neutral conversation copy and made the state card the owner of the current idle/recovery claim.
  evidence: The header now reads `Hermes conversation` and describes typed and spoken Hermes turns without assuming a selected Profile; it no longer claims transport is disconnected above a verified live Profile. The state card explicitly renders `No Profile selected`, `Unavailable`, or `Ready`, with recovery and configuration actions owned by the appropriate state. Hardware re-capture remains part of the open `5-A-3` visual/accessibility limitation.

- source_spec: `hermes-relay-android/_bmad-output/implementation-artifacts/spec-5-a-2-accessibility.md`
  summary: NOTE 2026-09-12 -- the contrast half of `5-A-2`'s environment limitation is closed, but measurement proved insufficient on its own and the two obligations should not be treated as substitutes.
  evidence: Contrast is now asserted across 56 pairs in both appearances, with each guard verified by deliberate regression rather than trusted because the suite was green. The `5-A-3` device pass nonetheless found a defect measurement could not catch: `surfaceVariant` and `errorContainer` held the same value, so Material's `contentColorFor` returned `onErrorContainer` for every ordinary `Card` and drew plain informational text in the unavailable colour. Every contrast pair involved was individually fine -- pink on panel measures 7.66:1. The defect was the mapping, not a ratio. TalkBack and font scaling remain entirely unproven.
- source_spec: `_bmad-output/implementation-artifacts/spec-ops-web-deployment-pipeline.md`
  summary: Add kiosk authentication or a stronger network access boundary before exposing the W/K hostname beyond the trusted household pilot.
  evidence: The display's exact Origin check is not authentication, and the Caddy site intentionally has no credential or ACL layer; upstream architecture keeps kiosk authentication open and describes the pilot as explicit LAN trust.

- source_spec: `_bmad-output/implementation-artifacts/spec-ops-web-deployment-pipeline.md`
  summary: Make remote dependency installation reproducible with a pinned, hashed lock or an uploaded wheelhouse.
  evidence: The published project requirements use lower bounds and the remote venv resolves dependencies from the live package index on each deploy, so identical commits can receive different dependency versions or fail offline.

- source_spec: `_bmad-output/implementation-artifacts/spec-ops-web-deployment-pipeline.md`
  summary: Add bounded release retention that protects `current` and `previous` while reclaiming older remote virtual environments.
  evidence: Each successful commit creates a new release directory and the current pipeline never removes older directories, so long-running ops use can consume the release volume.

- source_spec: `_bmad-output/implementation-artifacts/spec-ops-web-deployment-pipeline.md`
  summary: Add signal-safe recovery for interruption after activation but before the public smoke check completes.
  evidence: A locally delivered interrupt can terminate the wrapper between the successful remote activation and `run_public_check`; the current remote transaction handles command failures but not every local process interruption, and a correct trap must distinguish pre-activation upload from post-activation state.

- source_spec: `_bmad-output/implementation-artifacts/spec-ops-web-deployment-pipeline.md`
  summary: Decide whether an explicit rollback smoke failure should restore the release that was active before rollback.
  evidence: `rollback` leaves its selected release active when the subsequent public probe fails; the frozen intent requires reporting rollback and deploy failures but does not specify whether this health failure should trigger a second automatic rollback.

- source_spec: `_bmad-output/implementation-artifacts/spec-wk-concurrent-browser-session-isolation.md`
  summary: Run the overlapping-turn and owner-disconnect smoke against the newly deployed WK-2 service on Ops.
  evidence: The public Ops check and two-tab readiness smoke passed, but the currently deployed service predates WK-2, so sending overlapping turns there would not validate this implementation. The local two-client WebSocket, audio, failure, disconnect, prompt, reconnect, capacity, and full-suite checks pass; the deployed-branch gate needs an explicit operator deployment and live Hermes test.

- source_spec: `_bmad-output/implementation-artifacts/spec-wk-profile-catalog.md`
  summary: Complete the physical three-phrase/two-tab verification against the corrected Ops release.
  evidence: The catalog was deployed to Ops, the service is active, Caddy serves the origin, and the redacted public page/action/state probe verifies `browser_hands_free` plus `hey missy`, `hey skippy`, and `hey spark`. Real browser speech, wake-only capture followed by a live Hermes turn, two simultaneous tabs, and cancellation of an in-flight route still require the supported browser/device gate.
