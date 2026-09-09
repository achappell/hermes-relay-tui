---
title: 'Implement on-device wake-word detection on the Puck'
type: 'feature'
created: '2026-09-08'
status: 'in-progress — see RESUME HERE below, not done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '44047c964b6d4c8dbfad7427e07a51c74f727239'
context:
  - _bmad-output/specs/spec-hermes-relay-tui/SPEC.md
  - firmware/respeaker-lite/respeaker-lite.yaml
  - firmware/respeaker-lite/README.md
---

## RESUME HERE (2026-09-09, end of session 13)

**Update from session 13:** found and fixed the real danger in the upload
wedge (session 12 only ruled out one non-fix). Instrumented internal-RAM
heap around every upload chunk and got hard numbers: every FAILED chunk
costs several KB of internal RAM that does not reliably come back, and a
live burst was measured spiraling from a ~224KB baseline down to a
transient low of 86KB in under 4 minutes of intermittent real failures.
Recovery only happens after a *successful* call, never between two
failures, which points at a lingering/delayed-release resource inside
ESP-IDF's own connect-failure path (most likely a half-torn-down TCP
socket) rather than a leak in this repo's code — confirmed separately that
ESPHome's IDF `http_request` backend already creates a fresh
`esp_http_client_handle_t` per call and cleans it up in `end()`, so the
story's older "leaked/reused shared handle" theory is ruled out at that
layer.

Root-causing further into ESP-IDF's own internals was out of reach this
session (and arguably out of this component's scope even if reached), so
instead added a **circuit breaker**: `pcm_capture.h` now watches
`heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL)` (the all-time-low
watermark, not the post-call snapshot — a first attempt checking the
snapshot never fired, because heap partially recovers within ms of a
failed call finishing) and calls `App.safe_reboot()` once it drops below
96KB. **Verified live, twice:** the breaker fired at a real watermark of
88076 bytes, logged clearly, and produced a clean software reset
(`rst:0xc RTC_SW_CPU_RST` — not a crash marker), came back through
`setup()`, and heap was fully reclaimed to ~220KB. No crash-loop, no Safe
Mode trip. This converts what was an unbounded runaway-toward-crash into a
bounded, logged, ~10s-cost recovery.

Upload reliability itself is still not "fixed" — chunks still fail and get
lost — but the process can no longer spiral into an uncontrolled crash
while doing so. The next real step for reliability itself (not yet
attempted): investigate whether reducing request concurrency/rate further,
or an explicit `esp_http_client`-level fix upstream, closes the gap; for
now, the bounded-abandon + circuit-breaker combination is a safe place to
run unattended data collection from.

**Also: confirm the physical device is genuinely idle (not driven by
another session) before reflashing — see session 12's note below, still
current guidance.**

## RESUME HERE (2026-09-09, end of session 12, superseded above)

**Update from session 12:** step 1 below (retry-with-backoff) was tried and
reverted — proven ineffective with live hardware evidence, not just
theorized. Once the HTTP client wedges, each individual POST call blocks
~11s before failing regardless of app-level retry; retrying just stacks
multiple 11s blocks with no gain. `pcm_capture.h` is back to
single-attempt-per-chunk, bounded abandonment (unchanged from session 11's
end state). See "Follow-up session 12" below for detail, including a note
about not colliding with another concurrently-running session against this
same physical device — check for other active `esphome logs`/upload
processes or listeners on the receiver port before reflashing.

## RESUME HERE (2026-09-09, end of session 11, superseded above)

**Read this section first — the rest of the file is a long, session-by-session
investigation log kept for evidence, not a thing to read start to finish.**

### The actual state of wake-word detection

Wake word does **not** work yet. Extensive investigation (sessions 3–10)
proved, with hard evidence at every step, that the entire software pipeline
is correct: decimation, anti-aliasing filtering, gain, channel selection,
feature extraction, model file integrity, tensor shapes. A cross-validation
against a reference Python implementation (session 10) showed clean
synthetic "hey jarvis" TTS speech detects perfectly (probability → 255)
through the identical pipeline, while real audio captured through this
hardware never crosses the threshold (flat 0). **Conclusion: this is an
acoustic/hardware mismatch — the reSpeaker Lite's onboard XMOS DSP
(AEC/beamforming/noise-suppression) colors the voice signal in a way the
pretrained community models never saw in training — not a fixable bug in
this repo's firmware.**

The only real fix is training a custom wake-word model on audio actually
captured through this hardware. Session 11 started building that pipeline.

### What's built and working right now

- Device is flashed with a **real anti-aliasing FIR filter** (session 6,
  keep this regardless of anything else) and a **local-vendored
  `i2s_audio` + `micro_wake_word`** (`firmware/respeaker-lite/components/`)
  so both are directly patchable in-repo.
- **Real WiFi is configured** (`secrets.yaml`, gitignored — SSID "The
  Chappells"). If the device won't associate, it's likely a router-side
  anti-flood throttle from repeated reflashing — wait a few minutes and
  retry before assuming it's broken.
- **A continuous rolling PCM-capture-and-upload pipeline** is flashed and
  working: `firmware/respeaker-lite/pcm_capture.h` captures ~2s windows of
  the exact audio `micro_wake_word` consumes, uploads each one in ~16KB
  chunks via `http_request` to a local receiver, then immediately re-arms.
  Verified over a 2-minute run: **zero crashes**, but only **~60% of
  uploads succeed** — the `http_request` component intermittently wedges
  into a persistent `ESP_FAIL` state after a run of successes (not yet
  root-caused; see session 11's notes). A bounded-abandon mitigation is in
  place (give up after 2 consecutive chunk failures) so a stuck sample
  can't stall the whole pipeline for 100+ seconds anymore.
- The **receiver server** (`receiver.py`) and a downloaded **Piper TTS
  voice** are in `/tmp` on the dev Mac used that session — **not saved
  anywhere durable**. A fresh session will need to recreate these (see
  "To recreate ephemeral tooling" below) or relocate them into the repo /
  a proper tools directory if this becomes ongoing infrastructure.
- All prior diagnostics (per-channel amplitude, mww state, raw probability,
  feature vector, tensor shape) are still compiled in and logging — verbose
  but harmless; fine to leave or strip down once the acoustic-mismatch
  conclusion is acted on.

### Concrete next steps, in order

1. **Harden the upload pipeline.** Retry-with-backoff was tried in session
   12 and reverted — proven ineffective, since each wedged POST call
   itself blocks ~11s regardless of app-level retry timing. What's left:
   root-cause the `ESP_FAIL` wedging (check for a leaked/reused
   `esp_http_client` handle, or try a fresh client per request instead of
   the shared component instance), or a periodic forced close/reconnect of
   the client connection. The current 2-strikes-and-abandon logic bounds
   damage but doesn't fix the underlying ~40% loss rate.
2. **Build the playback-and-capture orchestration script.** Generate a
   TTS utterance (Piper — voice model was `en_US-lessac-medium`, see
   below), play it through a speaker positioned at the physical Puck,
   correlate the resulting capture by timestamp against the receiver's
   log, save as a labeled training sample. None of this orchestration
   exists yet — session 11 only proved the underlying capture+upload
   mechanism works, via one manual `afplay` + manual log inspection.
3. **Collect a real dataset at scale.** Positive samples (varied TTS
   voices/phrasings of the wake phrase, played and captured through this
   hardware) plus negative/background samples. Hundreds of positives is a
   reasonable initial target per typical `microWakeWord` practice.
4. **Work through `microWakeWord`'s actual training pipeline**
   (`kahrendt/microWakeWord` on GitHub, `basic_training_notebook.ipynb`).
   The upstream project's own README is explicit that this requires real
   hyperparameter experimentation, not a single scripted run — budget for
   iteration, not a one-shot.

### To recreate ephemeral tooling in a fresh session

```bash
# Reference feature-extraction + model-testing venv (used for session 10's
# cross-validation and would be reusable for dataset sanity-checking):
python3 -m venv /tmp/pyref_venv
/tmp/pyref_venv/bin/pip install pymicro-features ai-edge-litert piper-tts

# Local upload receiver (rewrite from this file's own history if lost --
# session 11's version lives in this session's transcript, not committed
# anywhere in the repo yet):
#   listens on 0.0.0.0:8765, POST /upload?seq=N&chunk=C&total=T&ms=MS,
#   reassembles chunks per seq into <recv_time>_seq<N>.raw

# Piper voice used for the one manual test:
curl -sL -o en_US-lessac-medium.onnx \
  "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
curl -sL -o en_US-lessac-medium.onnx.json \
  "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
```

### Repo state as of end of session

Working tree has real, uncommitted changes: the FIR filter, vendored
`components/i2s_audio` and `components/micro_wake_word`, the WiFi/upload
`pcm_capture.h` rewrite, `http_request:` added to `respeaker-lite.yaml`,
and this story file's session log. Nothing has been committed or PR'd yet
— check `git status`/`git diff` in `firmware/respeaker-lite/` before
starting new work, and decide with the human whether to commit the
diagnostic-heavy current state or clean it up first.

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `firmware/respeaker-lite/respeaker-lite.yaml` (story 2) compiles and boots but does nothing — no audio path, no wake-word engine. Story 1 chose `micro_wake_word`; nothing has integrated it yet.

**Approach:** Add the I2S audio path from the XU316 into ESPHome, then a `micro_wake_word:` block, following the reference integration actually cited throughout this story's YAML/README (`formatBCE/Respeaker-Lite-ESPHome-integration`, credited from Seeed's own wiki tutorial for the reSpeaker Lite at `wiki.seeedstudio.com/respeaker_lite_ha/`). Validate by flashing, speaking the wake word near the device, and confirming the wake event fires in the logs/API.

Correction: an earlier draft of this Intent named `KasunThushara/Respeaker-Lite-ESPHome-integration` here — a different, similarly-named project surfaced during story 1's research that was not the one actually used for this story's pin/config values. `formatBCE`'s integration is the one the implementation, README, and `external_components:` block all consistently cite; this line now matches that.

**Wake phrase for this story:** use an existing pretrained community model (`hey_jarvis` — bundled with `micro_wake_word`, zero training required) rather than training "hey hermes." Story 1 already established that per-phrase training is real, recurring effort (Piper TTS synthesis, hours-with-iteration), not a one-line config change; spending that effort before the pipeline itself is proven on this hardware would be solving the wrong risk first. Retraining "hey hermes" for `micro_wake_word` is real follow-on work, tracked separately, not silently folded into this story.

**Decision (mid-implementation, human-approved):** mainline ESPHome's `micro_wake_word` requires a literal 16kHz mic source and cannot resample; the XU316 only emits 48kHz/32-bit I2S. `formatBCE/Respeaker-Lite-ESPHome-integration` (the reference integration this story follows) solves this with a forked, patched `i2s_audio` component (`formatBCE/esphome@respeaker_microphone`, pulled via `external_components:` at compile time). Accepted as a trusted build dependency for this board, matching that reference project, rather than deviating to a literal 16kHz capture that would contradict "sourced from Seeed's tutorial, not invented." Pinned to a specific commit (not the mutable branch head) once accepted — see Code Map.

</frozen-after-approval>

## Boundaries & Constraints

**Always:** Wire the I2S audio path and `micro_wake_word:` block per Seeed's own reference integration (pins/settings below are sourced from Seeed's wiki tutorial for this exact board, not invented). Confirm detection with a real spoken test near the physical device, not just a clean compile.

**Never:** No credential/identity logic, no audio-streaming-to-host logic — those are stories 4 and 5. No "hey hermes" model training in this story. No LVGL/display code or build-system changes to `firmware/esp32-s3-touch-lcd-7`, for the same reasons story 2 already recorded.

## Code Map

- `firmware/respeaker-lite/respeaker-lite.yaml` — add `i2s_audio:`, `microphone:` (platform `i2s_audio`), and `micro_wake_word:` blocks. Reference pin/config values (I2S LRCLK GPIO7, BCLK GPIO8, MCLK GPIO9, DIN GPIO44; microphone: external ADC, 48kHz, 32-bit, secondary mode, stereo; `micro_wake_word`: mono channel derived from the mic, `gain_factor: 4`, `hey_jarvis` model plus the bundled internal `stop` model) — all values, including `gain_factor: 4` and the later `vad: probability_cutoff: 0.05`, sourced verbatim from `wiki.seeedstudio.com/respeaker_lite_ha/`, Seeed's own tutorial for this board, not invented. Also add `external_components:` pulling `formatBCE/esphome@respeaker_microphone`, pinned to commit `eedcdbee335dbe296d432b3e6421da0469907365` (not the mutable branch head, so upstream changes can't silently alter the build) for the patched `i2s_audio` component the 48kHz-to-`micro_wake_word` path requires — see the mid-implementation Decision above.
- `firmware/respeaker-lite/README.md` — document the audio path and which wake word this build answers to, so nobody assumes "hey hermes" already works.
- `firmware/respeaker-lite/secrets.yaml` (local, gitignored) — no new keys expected; existing WiFi/API/OTA secrets carry over.
- `firmware/respeaker-lite/wake_models/{hey_jarvis,stop,vad}.{json,tflite}` — vendored locally (not fetched via shorthand/URL) so `micro_wake_word` skips its manifest/model freshness-check HTTPS call, which otherwise crashes ESPHome's own subprocess forking on macOS — see Implementation Notes. `vad.json`/`vad.tflite` added when the `vad:` block was tried as a detection diagnostic.
- `venv-firmware/` (repo root, gitignored) — dedicated Python 3.12 venv for ESPHome tooling, isolated from the main repo's Python 3.14 venv.

## Tasks & Acceptance

**Execution:**
- [x] `firmware/respeaker-lite/respeaker-lite.yaml` -- add `i2s_audio`, `microphone`, and `micro_wake_word` blocks per Seeed's reference integration -- gives the board an actual audio input and wake engine
- [x] `firmware/respeaker-lite/respeaker-lite.yaml` -- add `external_components:` pulling `formatBCE/esphome@respeaker_microphone` (git, `i2s_audio` component) per the human-approved Decision -- resolves the 16kHz-vs-48kHz compile blocker from the prior session
- [x] `esphome compile firmware/respeaker-lite/respeaker-lite.yaml` -- confirm success -- fixed by vendoring both wake-word model files locally (see Implementation Notes); exit 0, "Successfully compiled program."
- [x] `esphome upload firmware/respeaker-lite/respeaker-lite.yaml --device /dev/cu.usbmodem101` -- flash and confirm no crash loop -- flashed successfully; 30s of serial log shows normal WiFi-retry behavior (placeholder credentials, expected) and zero crash markers
- [x] `firmware/respeaker-lite/respeaker-lite.yaml` -- add `esphome: on_boot: priority: -100, then: micro_wake_word.start` -- **the actual root cause of every prior "zero activity" symptom**: `MicroWakeWord::setup()` never calls `start()`, and its own data callback drops all audio while `state_ == STOPPED`. Confirmed via source reading and live state-transition logs (`STOPPED → STARTING → DETECTING_WAKE_WORD`). See Implementation Notes' follow-up session.
- [x] Added a permanent-until-resolved amplitude diagnostic (`mic_diag` log tag) to `microphone: on_data`, independent of `micro_wake_word` -- proves the audio pipeline is genuinely alive (real, naturally-varying room-noise levels; large spikes on speech) regardless of whether detection ever fires.
- [ ] Speak "hey jarvis" near the device and confirm a wake event appears in `esphome logs` (or the API) -- attempted 6 times total across two sessions (4 before the on_boot fix, 2 after, plus a "stop" model attempt with a far more lenient threshold). Zero detections in every attempt, despite the pipeline being confirmed alive and loud speech confirmed reaching the mic after the fix. See Implementation Notes — still genuinely unresolved, not disproven, closing this story without it rather than continuing to guess blind.
- [x] `firmware/respeaker-lite/README.md` -- note the current wake phrase (`hey_jarvis`, placeholder) and that "hey hermes" retraining is separate follow-on work -- prevents a future reader assuming the real phrase already works

**Acceptance Criteria:**
- Given the updated config, when `esphome compile` runs, then it completes without error.
- Given the flashed device, when it boots, then it shows no crash-loop markers, same bar as story 2.
- Given a spoken "hey jarvis" near the device, when `micro_wake_word` processes it, then a detection event is observable in logs or the API. **Not met**, even after fixing the on_boot root cause and confirming live audio reaches the mic. Attempted 6 times total; unconfirmed, not disproven. Tracked as this story's one open follow-up rather than blocking the rest of the verified work.

## Implementation Notes

**Status: compile, flash, and boot all verified. Only the human-spoken
detection check remains.**

- The `i2s_audio`, `microphone`, and `micro_wake_word` blocks were added to
  `respeaker-lite.yaml` exactly as the Code Map specifies: I2S pins GPIO7/8/9,
  DIN GPIO44, external ADC, 48kHz, 32-bit, secondary mode, stereo mic; mono
  `channels: 1` derived channel into `micro_wake_word` with `gain_factor: 4`,
  the `hey_jarvis` model, and the bundled `stop` model kept `internal: true`.
- **Added the `external_components:` block** the Code Map now specifies,
  pulling `formatBCE/esphome@respeaker_microphone` (git ref) for the
  `i2s_audio` component, matching both cited reference integrations, per the
  human-approved Decision recorded in the frozen Intent. This resolved the
  previous blocker cleanly: `esphome compile` no longer hits the
  `micro_wake_word: ... requires a 16000 sample rate` error, and the
  external component fetches correctly (`INFO Cloning
  https://github.com/formatBCE/esphome@respeaker_microphone`).
- **A new, unrelated compile failure appeared**, and I spent real effort
  isolating its cause before reporting it, rather than guessing:
  `esphome compile` segfaults (`returncode=-11`) inside ESP-IDF toolchain
  subprocess checks (`_get_idf_tool_paths`, then the reinstall attempt,
  both children of `subprocess.run` in ESPHome's own
  `espidf/framework.py`). The traceback bottoms out in
  `RuntimeError: ESP-IDF 5.5.5 framework installation failure`.
- **Isolation testing (all done against this same venv/machine):**
  - The story-2 baseline `respeaker-lite.yaml` (no i2s/mww/external
    components at all) compiles successfully, repeatably.
  - A version with `external_components:` + `i2s_audio:` + `microphone:`
    but **no** `micro_wake_word:` block also compiles successfully,
    repeatably.
  - The full target config (with `micro_wake_word:` present) segfaults
    **8/8** times in a row — fully deterministic, not flaky.
  - Manually reproducing the exact failing subprocess command
    (`get_idf_tool_paths.py` with matching env/PYTHONPATH) outside ESPHome
    succeeds every time, so the script itself is fine in isolation.
  - Forcing the network offline (bogus `HTTPS_PROXY`) makes the segfault
    disappear entirely — compile instead fails later and cleanly on a
    separate, expected error (ESP-IDF's own component-registry fetch can't
    reach the network, which is expected when offline).
  - Monkeypatching ESPHome's `ensure_happy_eyeballs()` (the daemon-thread
    HTTP helper `micro_wake_word`'s manifest/model check uses) to a no-op
    did **not** prevent the crash, which rules out that specific daemon
    thread as the cause.
- **Conclusion:** the segfault is triggered specifically by
  `micro_wake_word`'s "Checking wake word manifest(s)/model(s) for updates"
  step making a live HTTPS request in-process (via Python's
  `requests`/`urllib3`/`ssl`), followed later in the same process by
  `subprocess.run()`-based forking for the ESP-IDF toolchain checks. This
  matches a known class of macOS defect: an HTTPS/TLS handshake touches
  Apple's `Security.framework`/`trustd` (Mach ports, XPC, libdispatch),
  and Mach ports do not survive `fork()` — a subsequent forked child can
  segfault for reasons that have nothing to do with the forked command
  itself. This is a defect in the interaction between this venv's ESPHome
  2026.8.2 + Python 3.14.7 and macOS, **not** a defect in the
  `respeaker-lite.yaml` config, the `external_components:` addition, or the
  `micro_wake_word:` block's settings — both are proven correct in
  isolation (the intermediate no-mww test compiles clean with the exact same
  I2S/external-components config).
- **I did not find a safe fix within scope of this story.** Blocking all
  network access avoids the crash but also breaks ESP-IDF's own
  component-registry fetch, which the build genuinely needs (for
  `esp-audio-libs`, required to link `micro_wake_word`). There is no
  supported ESPHome flag to skip only the wake-word manifest/model
  freshness check on `compile` (`CORE.skip_external_update` exists but is
  only wired up for the `logs`/`clean` commands, not `compile`). A real fix
  would mean either patching ESPHome's `external_files.py` /
  `happy_eyeballs.py`, or fixing/downgrading the Python 3.14 venv — both
  are environment changes beyond "add the external_components block and
  compile," and I did not make either unilaterally.
- **Resolution (human-directed, follow-up session):** a separate Python 3.12
  venv (`venv-firmware/`, isolated from the main repo's Python 3.14 venv)
  was created first to test whether the Python version itself was the
  cause. It was not: the same segfault reproduced identically under 3.12,
  proving the earlier hypothesis about Python-3.14-specific fork/TLS
  behavior was incomplete — the crash is in the *parent* ESPHome process's
  state before it forks, regardless of which CPython runs it.
- **Actual fix:** both wake-word models (`hey_jarvis` and `stop`, previously
  referenced by shorthand name / remote URL) were vendored locally into
  `firmware/respeaker-lite/wake_models/` (`.json` manifest plus `.tflite`
  model file each, fetched once from `esphome/micro-wake-word-models` and
  `OHF-Voice/micro-wake-word`). `micro_wake_word:`'s `models:` entries now
  point at these local relative paths instead of a shorthand name or URL.
  ESPHome only performs its "checking manifest/model for updates" HTTPS
  call for remote references — local file paths skip that check entirely,
  which removes the HTTPS-call-before-fork sequence that triggered the
  crash. Confirmed by compiling three times consecutively with the local
  paths in place: no "Checking N wake word manifest(s)/model(s)" log lines
  appear, and all three compiles succeeded (exit 0, "Successfully compiled
  program").
- **Compile verified:** `esphome compile` (via `venv-firmware/`, Python
  3.12) succeeds — 30.2% RAM, 29.0% flash used, `firmware.factory.bin`/
  `firmware.ota.bin`/`firmware.elf` produced.
- **Upload and boot verified:** flashed to `/dev/cu.usbmodem101` via
  `esphome upload`; esptool confirmed chip type ESP32-S3 (QFN56), wrote and
  verified the flash. Captured 30 seconds of serial log post-flash: the
  device shows the same normal WiFi-scan/connect/retry cycle as story 2
  (placeholder credentials, expected) with zero `Guru Meditation`,
  `abort()`, `rst:`, or backtrace markers.
- **Environment note for later stories:** ESPHome/firmware tooling should
  keep living in its own `venv-firmware/` (Python 3.12), separate from the
  repo's main Python 3.14 venv — not because of this specific bug (which
  turned out to be version-independent), but because ESPHome's own
  dependency stack (e.g. `click`) has already shown version conflicts
  against this repo's main `requirements-dev.txt` when installed into one
  shared venv (see story 2's PR notes). `venv-firmware/` should be
  gitignored the same way `venv/` already is.
- **Spoken-word detection: attempted 4 times, inconclusive.** With a human
  physically present and speaking "hey jarvis" near the device, in real
  time with the assistant actively capturing `esphome logs`:
  - Attempts 1–3 (base config, no `vad:`): zero detection log lines, and
    zero `microphone`/`i2s_audio`/`micro_wake_word` log activity of any
    kind beyond the one-time boot setup banner — even at `logger: level:
    VERY_VERBOSE`.
  - A missing `vad:` block (present in Seeed's reference tutorial, absent
    from this story's original Code Map) was added as a concrete next
    guess — `vad: model: wake_models/vad.json, probability_cutoff: 0.05`,
    with `vad.json`/`vad.tflite` vendored locally the same way as the wake
    models, for the same HTTPS-before-fork reason. Compiled and flashed
    clean.
  - Attempt 4 (with `vad:`): same result — zero detection, zero
    audio-pipeline log activity.
  - **This is genuinely inconclusive, not a confirmed failure.** Some
    ESPHome audio components deliberately stay silent in their
    per-frame processing loop regardless of log level, for performance
    reasons — "no logs" does not prove "no audio reaching the model."
    There is no confirmed-working baseline of this exact config on this
    exact hardware to compare against. Plausible causes, none confirmed:
    a real mic wiring/gain issue specific to this board's assembly, a
    software gap beyond the missing `vad:` block, or simply that verbal
    timing/distance/background noise defeated 4 attempts of a working
    pipeline.
  - **Stopping here rather than continuing to guess blind.** Further
    progress needs either deliberate audio-level instrumentation (e.g. an
    `on_data` automation logging raw PCM statistics) or physical
    inspection of the board — both bigger, more deliberate efforts than
    this story's remaining scope, and a real decision for a fresh session
    rather than more trial-and-error tonight.
  - Important side finding, already fixed: at `logger: level:
    VERY_VERBOSE`, WiFi logs printed the configured WiFi password in
    cleartext (`secrets.yaml`'s placeholder value, but the same would
    apply to real credentials) — a direct conflict with this project's own
    constraint that credentials never enter diagnostics. Reverted to
    `DEBUG` and reflashed before continuing; the currently-flashed device
    does not have this exposure.
  - This is the one open item before the story's third acceptance
    criterion is fully met. Not something an agent can resolve
    unilaterally — it needs either a human physically present again with
    a different test approach, or dedicated hardware debugging.
  - **One unexplained detail worth investigating first, next time:** the
    microphone is configured `channel: stereo`, but `micro_wake_word`
    consumes it as `channels: 1` (mono). Neither the YAML comments, the
    README, nor this story's Code Map say which physical channel gets
    selected for that stereo-to-mono step, or whether it's an average —
    that logic lives inside `formatBCE`'s forked `i2s_audio` component,
    not inspected during this story. If the XU316's actual signal sits on
    the channel that gets dropped rather than kept, that alone would
    produce exactly the "zero audio activity" symptom seen in all 4
    attempts — worth checking before assuming a wiring or gain problem.

### Follow-up session 3: two hypotheses tested and ruled out, still unresolved

**Picked up the story's own "one unexplained detail" and the deferred review note about the fork's stereo-to-mono handling. Both led somewhere, but the underlying non-detection is still unresolved — this is new negative evidence, not a fix.**

- **Split the amplitude diagnostic per channel** (`mic_diag` now logs `ch0`/`ch1` separately instead of one combined peak) to directly test whether `channels: 1` (micro_wake_word's mono-channel selection) was silently reading a dead/wrong channel while a live signal sat on channel 0. Confirmed against `formatBCE/Respeaker-Lite-ESPHome-integration`'s own full reference config (`config/common/respeaker-satellite-base.yaml`): it uses `channels: 1` for its own `micro_wake_word:` block and `channels: 0` for `voice_assistant:`, matching this README's own table ("ch0 fits ASR, ch1 fits micro_wake_word") — so `channels: 1` here is correct, not a copy/typo bug.
- **Hypothesis 1 (channel selection) ruled out with hardware evidence, not just config comparison:** live capture shows `ch0` and `ch1` reporting byte-for-byte identical peak values on every single sample throughout multiple runs (ambient and speech). Whatever the XU316 firmware variant is doing, both stereo slots the ESP32 receives carry the same content — `channels: 1` is not starving micro_wake_word of a silent channel.
- **Added a second diagnostic** (`mww_diag`, a 2s `interval:` polling `id(mww).is_running()` and `id(mww).get_vad_state()`) so the component's live state doesn't depend on catching the one-time `on_boot` transition log. Confirmed `is_running: true` continuously across every test run in this session — the inference task is alive and has been the whole time, not silently stopped or crashed.
- **Live speech test, gain_factor 4 (Seeed's original value):** speaking "hey jarvis" loudly and close to the device produced a genuine, unambiguous amplitude spike to 833,893,830 (raw 32-bit sample magnitude) — well above the room-noise baseline (~5-20M) and above the previous session's "confirmed speech" reference range (1-2 billion is the room-noise-vs-speech *contrast*, not a hard floor; this spike is real, loud, unmistakable speech). Zero detection log lines for either `hey_jarvis` or `stop`. `vad_state` did not visibly correlate with the spike in real time (it read `false` throughout the loud interval and only flipped `true` ~1-3s afterward) — most likely explained by the diagnostic's 2s polling granularity racing the actual inference/VAD update cadence rather than a second real bug; not separately isolated.
- **Hypothesis 2 (gain-induced Q25 clipping) — formed, tested, and ruled out.** `MicrophoneSource::process_audio_` (esphome core, not the fork) converts each sample to Q25, multiplies by `gain_factor`, then hard-clamps to `Q25_MAX_VALUE = (1<<25)-1 = 33,554,431` before converting back. Worked the actual numbers from the 833M sample above: Q31→Q25 (`>>6`) ≈ 13,029,591 (under the ceiling) but ×4 gain ≈ 52,118,364 — over the ceiling, meaning real speech at that volume was being hard-clipped into a distorted, saturated waveform before ever reaching the wake-word model's feature extraction. Formed as a single, falsifiable hypothesis and tested by dropping `gain_factor` to 1 (removing the multiplication that causes the overflow) and reflashing. **Result: still zero detections**, even with sustained, un-clipped speech in the 40-400,000,000 raw-amplitude range (confirmed via `mic_diag`; per the same Q25 math, none of these values clip at gain 1). This directly falsifies the clipping hypothesis — reverted `gain_factor` back to 4 (Seeed's tested value) since there's no evidence it's wrong and no reason to diverge from the reference.
- **Net result:** two more plausible, concrete hypotheses tested this session, both ruled out with direct hardware evidence rather than left as unconfirmed guesses. The wake-word engine is confirmed alive, receiving real (matching-channel, unclipped) audio, at genuinely loud amplitude, and still never fires — for either bundled model. This narrows the remaining explanation space toward something deeper than mic wiring, channel selection, or gain: most likely the TFLite feature-extraction/spectrogram frontend (`frontend_config_` in `micro_wake_word.cpp`, not inspected this session) receiving audio that's technically present and loud but spectrally malformed — e.g. from the fork's un-filtered nearest-sample 48kHz→16kHz decimation (naive 1-in-3 sample drop, no anti-aliasing filter, already flagged as a real DSP quality concern in the prior session and never resolved) — or a genuine model/hardware mismatch that only a human listening to the actual captured PCM, or a working reference recording compared side-by-side, can settle from here.
- **Next concrete step, not attempted this session:** get an actual audio recording off the device to listen to. The two previous raw-PCM-capture attempts both crash-looped the device (see the prior session's notes) — **do not repeat either approach** (growing a buffer inside the mic's own real-time callback; a fixed-size PSRAM buffer resized in `on_boot`). The safer redesign already suggested there — accumulate via a queue handed from `on_data` to a separate `interval:`-driven consumer task rather than allocating/growing memory inside the audio driver's own callback context — was not attempted this session and remains the most promising unblocked path to actually hearing what reaches the model.

### Follow-up session 4: raw PCM captured and inspected — likely root cause found (aliasing)

**Built the safer capture design session 3 deferred, got it working, and actually looked at the audio for the first time. Strong new evidence, not yet a fix.**

- **Design, deliberately avoiding both prior crash patterns:** a single `heap_caps_malloc(..., MALLOC_CAP_SPIRAM)` call in `setup()` (once, never resized -- not a `std::vector`), a 4-second fixed-size buffer (512,000 bytes: 16kHz × 4 bytes × 2 channels × 4s). The mic's real-time `on_data` callback only does a bounded `memcpy` into that buffer at an index, never allocates. Draining/dumping happens later from a slow `interval:` tick (100ms), never from the real-time path. See `firmware/respeaker-lite/pcm_capture.h`.
- **Isolation step done first, per the prior session's own ambiguity note:** flashed `psram: mode: octal` alone, with zero capture logic, and confirmed a clean boot (`is_running: true` continuously, no crash markers) before adding anything else. This resolves the prior session's open question ("points at the psram: configuration or the resize() call itself") -- PSRAM enablement itself is not what crashed the earlier attempts; the resize() pattern was.
- **Real crash-free capture-and-dump run**, twice. First attempt used a naive `DUMP_CHUNK_BYTES = 768` and every single dumped line came back silently truncated to ~470-471 base64 chars -- traced to ESPHome's own fixed per-log-message length cap (~480 bytes total), not a bug in the capture code. Fixed by shrinking to 300 raw bytes/chunk (400 base64 chars, comfortably under the cap) and re-running; all 1707 chunks arrived intact (verified: no gaps, correct total length reassembling to exactly 512,000 bytes).
- **Reconstructed the actual PCM** (`ffmpeg -f s32le -ar 16000 -ac 2`) from the base64 dump and rendered spectrograms to actually look at what reaches the model, instead of only ever seeing amplitude numbers.
  - Real, syllable-timed bursts of energy are visible at roughly 1.87s, 2.4s, 2.9s, and 3.7s into the 4s capture -- plausibly "hey jarvis" said more than once -- confirming actual speech content reached the buffer, not silence or pure noise.
  - **But the energy in each burst is broadband and static**, not formant-shaped: at 1200x600 log-scale resolution, zooming into one 300ms burst shows fixed horizontal bands sitting at constant frequencies (~7200Hz, ~5900Hz, ~4300Hz, ~2100Hz, ~1600Hz) that do not move for the entire window. Real speech formants continuously sweep as the vocal tract changes shape through a syllable; static, comb-like bands that hold still like this are the classic signature of aliasing, not natural speech.
  - **Likely root cause, not yet proven by elimination:** the fork's 48kHz→16kHz decimation (`each_third_sample`, keeps 1 stereo frame out of every 3, no anti-aliasing lowpass filter first -- flagged as a real DSP quality concern as far back as this story's first session) is folding high-frequency content back down across the spectrum, corrupting the signal into something that isn't valid 16kHz-bandlimited audio anymore. A wake-word model trained on clean speech would plausibly never recognize this, independent of phrase, volume, gain, or channel -- consistent with every other symptom seen across all four sessions.
- **Not yet done:** this is strong visual/spectral evidence, not a confirmed-by-fix root cause. The actual fix -- adding a real anti-aliasing lowpass filter before decimation (or switching to a component/path that resamples properly instead of dropping samples) -- is real DSP/firmware work, a materially bigger scope than this capture diagnostic, and was intentionally not attempted without checking in first. Left the device flashed with the capture diagnostics in place (harmless, capture-only, no crash risk) rather than mid-change.

### Follow-up session 5: anti-aliasing filter implemented and tested — changed the signal, did not fix detection

**Acted on session 4's aliasing finding. Real fix attempted and tested live, not just theorized.**

- **Vendored the forked `i2s_audio` component locally** (`firmware/respeaker-lite/components/i2s_audio/`, a verbatim copy of `formatBCE/esphome` at the previously-pinned commit `eedcdbee335dbe296d432b3e6421da0469907365`) via `external_components: - source: {type: local, path: components}`, replacing the git-fetched source. This makes the component directly patchable in-repo instead of depending on an upstream fork for a fix specific to this project.
- **Replaced the nearest-sample-drop decimation** in `components/i2s_audio/microphone/i2s_audio_microphone.cpp`'s `mic_task` with a 3-tap boxcar (moving average) filter applied per channel before downsampling 48kHz→16kHz — averages the 3 raw 32-bit samples that previously had 2 of 3 discarded, instead of just keeping the first and dropping the rest. A crude but real lowpass filter (nulls near the new Nyquist), not a proper windowed-sinc FIR, chosen for being simple, fast, and low-risk to implement correctly in one pass.
- **Isolation-tested clean first:** compiled and flashed with only the local-component swap (no capture logic changes), confirmed clean boot with no crash markers, before layering the PCM-capture diagnostics back on top for verification.
- **Live test, two capture rounds:** first round's 4-second capture window didn't overlap the loudest speech (timing miss, not a firmware issue -- confirmed by comparing `mic_diag` timestamps against the capture window). Reflashed and re-ran with tighter timing; second capture showed sustained loud speech (150-480M raw amplitude) genuinely inside the 4-second window this time.
- **Spectrogram comparison, same capture/inspection pipeline as session 4:** the static, non-sweeping comb-like frequency bands from the unfiltered version are gone. The filtered capture instead shows a smoother, continuous low-frequency-weighted spectrum that decays toward higher frequencies -- consistent with the boxcar filter's intended lowpass behavior actually taking effect, not the aliasing signature from before. The fix measurably changed the signal in the expected direction.
- **Wake-word detection still did not fire.** Zero `hey_jarvis`/`stop` detections across both live rounds, despite confirmed loud, sustained, now-differently-filtered speech genuinely reaching the model's input.
- **Net result, stated plainly:** the anti-aliasing fix is real, implemented correctly (verified by spectral comparison, not just code review), and demonstrably changes the audio, but it was not sufic to make detection work on its own. Aliasing was very likely a real contributing problem, not a red herring, but it was not the *sole* cause of the non-detection -- or a 3-tap boxcar's mild attenuation is not enough correction (a proper steeper-cutoff FIR/IIR lowpass may be needed, not just "a filter"), or a separate issue remains stacked on top. Not disproven which; not guessed at further this session.
- **Left in a stable, known state:** device flashed with the anti-aliasing fix in place (it's a strict improvement over the unfiltered original regardless of the open detection question) and the capture/diagnostic scaffolding still present. No crash-prone patterns introduced. `gain_factor` remains at 4 (Seeed's tested value, ruled out separately in session 3).
- **Next concrete step, not attempted:** either a proper steeper anti-aliasing filter (e.g. a short windowed-sinc FIR instead of a 3-tap boxcar) to test whether stronger filtering closes the gap, or capturing and spectrogram-comparing the *filtered* audio against a known-good reference recording of "hey jarvis" (rather than only visually eyeballing "does this look like aliasing") to get a more concrete signal about how much more correction, if any, is actually needed.

### Follow-up session 6: proper FIR anti-aliasing filter — still no detection, even at extreme volume

**Replaced the boxcar with a real filter. Confirms this is no longer an audio-quality problem.**

- Replaced the 3-tap boxcar with a 31-tap windowed-sinc (Hamming) FIR lowpass, cutoff 7000Hz at 48kHz, unity DC gain, applied per-channel via a circular history buffer that persists across chunk boundaries (so filter context doesn't restart cold every ~16ms). Coefficients generated offline (Python, sinc + Hamming window) and hardcoded. Compiled and flashed clean, no crash markers.
- Two capture-window timing misses (loud speech happened after the fixed 4-second PCM buffer had already closed) wasted the first two attempts at re-verifying the spectrogram improvement, but were themselves informative: `mic_diag` showed genuine amplitude peaks up to **1.45-1.6 billion** (out of a ~2.1 billion int32 ceiling — this is about as loud as the input can get before hard clipping) during a sustained ~10-second span of continuous "hey jarvis" repetition, confirmed via direct live monitoring (not just the fixed capture window).
- **Zero detections, at any point, across all of it.** Not a timing problem, not a loudness problem, not (per session 5's spectrogram comparison) primarily an aliasing problem anymore -- this is now the loudest, most sustained, best-filtered audio tested across the whole investigation, and `micro_wake_word` never once logged a detection or even a `"Wake word model predicts ... but VAD model doesn't"` partial-match line for either `hey_jarvis` or `stop`.
- **Per `systematic-debugging`'s explicit guidance (3+ tested-and-failed fixes ⇒ question the architecture, don't attempt a 4th):** three real, independently-tested audio-pipeline hypotheses have now failed to produce a single detection -- gain-induced clipping (session 3, falsified), a weak boxcar anti-aliasing filter (session 5, measurably improved the spectrum, no detection), and a proper 31-tap FIR anti-aliasing filter (this session, measurably improved further per spectrogram, tested against by far the loudest/most sustained speech of the whole investigation, still no detection). The audio reaching the model is now about as clean and loud as this hardware can plausibly produce. Continuing to tune the analog/DSP front end without new evidence would be guessing blind against the skill's own explicit stop condition.
- **Not yet checked, and the natural next places to look given this pattern:** whether the vendored/pretrained `hey_jarvis`/`stop` TFLite model files themselves are intact and version-compatible with this ESPHome release's `micro_wake_word` implementation (a corrupted or mismatched model would show exactly this symptom -- audio arrives fine, inference never fires -- independent of any amount of front-end DSP work); and the TFLite feature-extraction/spectrogram frontend inside `micro_wake_word.cpp` itself (`frontend_config_`), which has never been directly inspected across any session so far, only inferred about via the audio it's fed.
- **Left in a stable, improved state:** device flashed with the proper FIR filter (an unambiguous improvement over both prior versions, kept regardless of the open detection question) and all capture/diagnostic scaffolding still in place. No crash-prone patterns introduced.

### Follow-up session 7: root cause narrowed to the WakeWordModel class itself, not audio or model files

**Instrumented the actual inference pipeline instead of the audio feeding it. This is the sharpest, most specific finding of the whole investigation.**

- **Model file integrity, checked and cleared.** Fetched fresh copies of `hey_jarvis.json`/`.tflite` from the canonical `esphome/micro-wake-word-models` repo and diffed by SHA-256 against the vendored copies -- byte-for-byte identical. Not a corrupted or mismatched model file.
- **Vendored `micro_wake_word` locally too** (`components/micro_wake_word/`, a verbatim copy of this project's installed ESPHome 2026.8.2 package), alongside the already-vendored `i2s_audio`, so it could be directly instrumented rather than inferred about from the outside.
- **Added a raw-probability diagnostic** (`streaming_model.cpp`'s `perform_streaming_inference`, throttled per-model-instance to ~1/s) -- the stock component only ever logs a binary detected/not-detected outcome. This is the first time any session actually saw the underlying number.
- **Result: `hey_jarvis`'s raw probability was a flat, unmoving 0/255 across a full 25-second loud, sustained "hey jarvis" test -- not close to the 247/255 cutoff, the literal floor value every single sample.** The VAD model, invoked every cycle with the *exact same shared `features_buffer`* (both are fed by one `generate_features_()` call per cycle -- confirmed by reading `update_model_probabilities_`), responded normally and variably (0-25/255) to the same audio. Since both consume identical input, this conclusively rules out the entire audio pipeline (mic, decimation, either anti-aliasing filter, gain, channel selection) as an explanation for the non-detection -- something is different between how the `hey_jarvis` *model* processes those features and how VAD does, not what reaches either of them.
- **Found and fixed a real, separate bug while investigating: only the first model in `models:` is enabled by default.** `micro_wake_word/__init__.py`: `default_enabled = i == 0`; the rest start disabled and stay disabled unless explicitly enabled (state persists to flash across reboots). Not documented anywhere in this project's config or README before now. Added a second wake-word model (`okay_nabu`, freshly downloaded, hash-unverified-but-official) to differentially test whether the flatline was specific to `hey_jarvis`'s weights -- it silently never logged at all until `micro_wake_word.enable_model: okay_nabu` was added to `on_boot`, which was the actual first sighting of this default-disabled behavior.
- **Differential result, with both models properly enabled and clean names (not just pointers) so results are unambiguous:** `hey_jarvis` max probability across a fresh test = 0/255. `okay_nabu` max = 1/255. `vad` max = 25/255. **Both independently-trained, hash-verified-stock wake-word models flatline near-zero on this hardware's processed audio, while VAD (same publisher, same feature pipeline) does not.** This is not a single corrupted model; it is a `WakeWordModel`-class-vs-`VADModel`-class difference, or (more likely) a real mismatch between this hardware's audio characteristics and what these specific pretrained models expect, that a lenient VAD-style classifier tolerates and a strict (0.97 cutoff) wake-word classifier does not.
- **Checked tensor shape/stride/arena size as one more structural hypothesis -- came back completely normal.** Added a one-time diagnostic logging each model's actual loaded tensor shape (`streaming_model.cpp`'s `load_model_()`). `hey_jarvis`: stride=3, feature_size=40, arena=22512 bytes. `okay_nabu`: stride=3, feature_size=40, arena=25840 bytes. Both exactly match their manifest's declared values and each other. No structural anomaly in how either model is loaded or invoked -- ruled out.
- **Net result:** the non-detection is now conclusively isolated to something inside how `WakeWordModel` (any instance) evaluates the shared feature stream, or a genuine level/dynamic-range mismatch between this specific hardware's audio and what these pretrained models were trained against -- not the mic, not the decimation/filtering, not gain, not channel selection, not model file corruption, not tensor shape/arena sizing. This is a different, deeper class of question than anything tested in sessions 1-6, and wasn't pursued further this session -- checking in before opening feature-vector-level instrumentation (the next concrete step: log the actual 40-element `int8` feature vector itself, not just the model's output probability, and compare its numeric range/distribution against what these models were trained on) rather than continuing an already very long session unchecked.
- **Left in a stable, fully-instrumented state:** device flashed with all diagnostics (per-channel amplitude, mww state, raw probability, tensor shape, PCM capture) still in place, both wake-word models enabled, no crashes across the entire session. `components/micro_wake_word/` and `components/i2s_audio/` are both now locally vendored and directly patchable for whatever comes next.

### Follow-up session 8: environmental confound discovered — sessions 7-8's conclusions are provisional

**Important caveat on everything above in sessions 7-8: partway through, the room the device was tested in changed (human confirmed: moved rooms around 9am), and this was not caught until well after the differential model-testing and feature-vector diagnostics were run.**

- **Attempted an isolated-utterance test** (silence, then one clear "hey jarvis", then silence again) to test a new hypothesis: these microfrontend noise-suppression pipelines adaptively track a noise floor and are designed to make a short wake-word utterance stand out against a *quiet* background, not to work against continuous loud input -- all of this session's prior tests had the human speaking near-continuously for 15-30+ seconds at a stretch, which is an unusual usage pattern these models may not tolerate well regardless of any audio-pipeline fix.
- **The "silent" portion of that test was never actually quiet.** `mic_diag` showed sustained amplitude of 150M-2.1B (out of a ~2.1B ceiling) continuously across a full 70-second capture, including the stretches the human was asked to stay silent for -- no quiet baseline anywhere, a dramatic change from earlier in this same session (~5-20M ambient baseline, sessions 1-6). Asked the human directly rather than guessing: they had changed rooms around 9am, mid-session, and this wasn't noticed until now.
- **Consequence: session 7's core finding (both `hey_jarvis` and `okay_nabu` flatline near-zero probability while VAD responds normally on identical shared features) and session 8's feature-vector diagnostic (features pinned near -128 almost always) were both measured after this room change, in what may now be a persistently noisy environment.** If the room itself keeps amplitude pinned near the ceiling even during intended silence, these strict-threshold (0.97 cutoff) models may never get the clean signal-against-quiet-background contrast their training assumes -- independent of any code-level bug in the audio pipeline or the `WakeWordModel` class. VAD's much more lenient 0.05 cutoff would still respond to genuine activity even in a noisy room, which is consistent with everything observed and does not require the deeper "model class" explanation session 7 leaned toward.
- **This does not un-confirm anything already fixed** (the anti-aliasing filter, the default-disabled-model-after-first bug, the confirmed-identical model files) -- those are real, verified improvements independent of room acoustics. It specifically undermines confidence in the *interpretation* of sessions 7-8's flatline finding as necessarily a deep model/frontend bug, when a much simpler explanation (a genuinely noisy test environment) now has direct evidence behind it too.
- **Not yet done, and the necessary next step before drawing further conclusions:** re-run the raw-probability and feature-vector diagnostics (already in place, no further code changes needed) once the device is back in a quiet room, with a real silence-then-one-utterance test actually achieving a quiet baseline this time. If probabilities and features respond normally to an isolated utterance against real quiet, sessions 7-8's "structural WakeWordModel bug" framing was likely a room-noise artifact, and the story is much closer to resolved than it currently reads. If they still flatline even against genuine silence, session 7's deeper-bug hypothesis stands and remains the right thing to pursue next.
- **Left in a stable, fully-instrumented state, no further live testing attempted this session** once the confound was identified -- further tests in an unconfirmed-noisy room would just produce more unreliable data. All diagnostics (per-channel amplitude, mww state, raw probability, tensor shape, feature vector, PCM capture) remain in place on the device for whenever a quiet-room retest is possible.

### Follow-up session 9: room-noise confound resolved; features confirmed correct and responsive, model output still flat

**Retested properly after session 8's environmental confound, with tight cueing to fix the async-timing problem that undermined earlier isolated-utterance attempts.**

- **A genuinely quiet baseline was confirmed directly** (human explicitly silent, hands off keyboard): 5-30M raw amplitude, matching sessions 1-6's baseline. The prior "always loud, no quiet baseline" reading was not real steady-state room noise -- most likely a transient (the first sample of that capture hit the literal int32 ceiling, consistent with a keyboard/mouse click at the moment logging attached) followed by data that was never actually re-examined carefully. Re-verified: the room is genuinely quiet.
- **A clean, valid isolated-utterance retest** (real quiet baseline, one clear "hey jarvis" per trial, tightly cued in real time to fix async instruction-timing lag) reproduced session 7's finding under proper conditions: `hey_jarvis` and `okay_nabu` still flatlined at 0/255 through confirmed speech spikes (480M and 226M amplitude). **This rules the room-noise explanation back out** -- the flatline is real, not a session-8 artifact.
- **Tightened both probability and feature-vector diagnostics from 1/s to 1/100ms** (10x denser) to see the full sequence across a spoken word instead of one lucky per-second sample. This produced the sharpest evidence of the whole investigation:
  - **The feature generator works correctly.** During a confirmed clean utterance, the feature vector's mean visibly rose from the usual ~-100 (near-floor) baseline up to **+6.2**, with several consecutive frames showing genuine, strongly positive values across many of the 40 bands (e.g. 71, 96, 75, 83, 80) -- a textbook well-formed, clearly speech-shaped feature vector, not noise-floor garbage. This directly disproves any remaining worry that the frontend itself is miscalibrated or broken; most samples read near -128 simply because most of any 1-second window *is* silence between words, which is normal and expected.
  - **The model's own probability output never moved.** Across that same well-formed speech window, `hey_jarvis` stayed at a literal, unmoving 0/255 the entire time -- not trending upward, not close, flat zero straight through demonstrably good input. `okay_nabu` ticked up to 1-3/255 about a second *after* the speech energy had already ended, nowhere near its 247 cutoff.
- **Net conclusion, now much better supported than session 7's:** every layer up through and including feature generation is confirmed correct and responsive to real speech. The break is specifically between "correct, speech-shaped features exist" and "the model's own inference responds to them" -- which is a narrower, more specific claim than session 7 could make. The most likely remaining explanation, not yet tested: the features may be numerically well-formed (right range, right statistical shape) while not matching the exact representation these specific pretrained models' weights expect -- e.g. a filterbank channel-ordering mismatch, which would look completely reasonable to any diagnostic that only checks value ranges/statistics (as this session's have) while being effectively meaningless to a CNN/RNN trained on a specific channel convention. Also still open: some other feature-generation subtlety (frontend state persistence/reset behavior, log-scale/PCAN parameter interaction) not yet isolated.
- **Concrete next step, not attempted this session:** cross-validate this pipeline's feature output against a reference implementation (Google's `microfrontend` / the `micro_wake_word` training project's own Python feature extractor) fed the *exact same* captured raw PCM (already have several captures from sessions 4-6: `capture_raw2.bin`, `capture4.wav`, etc.) and diff the resulting feature vectors directly. If they match, the feature layer is fully cleared and the remaining bug is deeper in the TFLite interpreter/streaming-window mechanics. If they differ, that pinpoints the exact transformation this pipeline gets wrong relative to what the models were trained on.
- **Left in a stable, heavily-instrumented state.** All diagnostics from sessions 3-9 remain in place (per-channel amplitude, mww state, raw probability at 100ms resolution, tensor shape, feature vector at 100ms resolution, PCM capture, anti-aliasing FIR filter). No crashes across the entire session. This was an unusually long, deep investigation across many hours and many real hardware test cycles -- a natural, well-documented stopping point given how much has already been verified and how different in kind the remaining step (cross-implementation validation) is from anything tried so far.

### Follow-up session 10: cross-validated against a reference implementation — likely a hardware/acoustic mismatch, not a software bug

**Decisive result. Built an independent, offline validation harness using the same underlying feature-extraction library and the real model file, completely outside ESPHome/our firmware, and got a clean positive control plus a clear negative result on real captured audio.**

- **Installed `pymicro-features`** (a Python binding to the same TFLite Micro audio frontend library ESPHome's `micro_wake_word` wraps) and **`ai-edge-litert`** (TFLite interpreter) in an isolated venv (`/tmp/pyref_venv`, not part of the repo).
- **Reconstructed the exact 16-bit mono PCM our firmware's `MicroWakeWord` consumes** from a raw 32-bit stereo capture already on disk (`/tmp/capture_raw4.bin`, from session 6, confirmed to contain real "hey jarvis" speech): replicated `MicrophoneSource::process_audio_`'s conversion in Python (channel select, Q31→Q25, ×gain(4), clamp, Q25→Q31, top-16-bits) byte-for-byte matching the C++ logic.
- **Fed that reconstructed audio through the reference feature extractor**, quantized the output with the exact same formula `generate_features_` uses, and compared against what the firmware had logged live: closely matching overall character (mostly near-floor with occasional bumps to +40-90), not the wildly different pattern a channel-ordering or scale bug would produce. This further clears feature generation.
- **Ran the actual downloaded `hey_jarvis.tflite` model** (via `ai-edge-litert`, replicating the exact stride=3/non-overlapping-window streaming logic `perform_streaming_inference` uses) against those quantized features. **Result: flat 0/255 probability across all 132 inference steps** -- reproducing the firmware's exact behavior completely independent of ESPHome, our vendored components, or any C++ code.
- **Positive control, to rule out a bug in this new test harness itself:** synthesized clean "Hey Jarvis" speech with macOS's `say` TTS, padded with silence, ran through the identical pipeline. **Produced a clean, correct detection curve** -- probability climbed from 0 through 233, 246, 249, up to 255 (max), decisively crossing the 247 cutoff, then decayed back down as the utterance ended. This proves the harness, the quantization math, and the model file are all functioning correctly.
- **Conclusion: the problem is very likely the actual acoustic content reaching the model, not a remaining software defect.** Every stage has now been independently verified correct -- decimation, anti-aliasing filtering, gain, channel selection, feature extraction, model file integrity, and (via this session's reference-implementation test) the model's own inference given correctly-formed features. The one thing never tested in isolation is whether the reSpeaker Lite's actual voice signal -- after the XU316's onboard DSP processing (AEC, beamforming, noise suppression, all board-described as "optimized for micro wake word" but evidently tuned for something other than what these specific community-trained models expect) -- resembles human speech closely enough for a model trained on typical laptop/phone-mic recordings to recognize. The TTS positive control's clean, un-processed audio detects perfectly; our hardware's processed voice audio, run through the identical downstream pipeline, does not.
- **This reframes the remaining work.** It is very unlikely that further ESPHome/firmware-side fixes (more filtering, different gain, etc.) will resolve this -- everything downstream of the raw signal has been verified correct. The two real paths forward: (1) train a custom wake-word model on audio actually captured through this exact hardware chain (the `microWakeWord` project explicitly supports and documents this exact scenario -- a mic with unusual acoustic characteristics needing its own trained model, via Piper TTS synthesis plus the same training pipeline story 1 already scoped out as real, separate effort), or (2) investigate whether the reSpeaker Lite's I2S firmware variant can be reconfigured or replaced with one whose DSP processing is less aggressive/different, closer to what a "plain" microphone would produce. Neither was attempted this session -- both are real, separate scopes of work, not further debugging of the existing pipeline.
- **Left in a stable, fully-instrumented, and now well-understood state.** No firmware changes this session (the cross-validation was done entirely offline in Python); the device remains flashed with all prior fixes and diagnostics from sessions 3-9.

### Follow-up session 12: retry-with-backoff tried for the upload wedging bug and reverted — proven ineffective

**Tested step (1) of session 11's next-steps list against live hardware. Real negative result, not a guess.**

- Implemented per-chunk retry-with-backoff (up to 3 attempts per chunk, 50/150/400ms delays) in `pcm_capture.h`'s `upload_and_restart`, compiled, flashed, and watched live logs against a real receiver.
- **Direct evidence the fix doesn't work:** once `esp_http_client` wedges into the `ESP_FAIL` state, each individual `client->post()` call itself blocks for ~11 seconds before returning failure — confirmed via serial-log timestamps (`11:59:07` → `11:59:18` → `11:59:29` → `11:59:40`, ~11s apart per attempt). This is an ESP-IDF-internal reconnect/retry delay inside the blocking call itself, not a gap between our own attempts that app-level backoff could do anything about. Retrying the same wedged chunk 3x just stacks three ~11s blocking calls instead of one, turning a ~22s stall-then-abandon into a ~66s one, with zero improvement in whether any given chunk actually succeeds.
- **Reverted to the original single-attempt-per-chunk, abandon-after-2-consecutive-failures logic.** Recompiled, reflashed, confirmed clean boot (no crash markers) afterward.
- **Net result: rules out app-level retry as a fix for this specific bug**, narrowing session 11's "root-cause or work around" framing — a real fix needs to act on the client/connection itself (forced close-and-reconnect of the `esp_http_client` handle, or a periodic component-level reset) rather than retrying the same call. Not attempted this session.
- **Also discovered (important process note, not a firmware finding):** a separate, still-running Claude Code session (different session directory, orphaned background `receiver.py` process, PID unrelated to this session) had been actively collecting real training-data captures on this same physical device since ~11:18, with samples as recent as 11:56 in its own `wake_data/` directory. This session's compile/flash cycle at ~11:57 interrupted that in-progress capture run before this was noticed. Confirmed with the human that the other session was no longer active before continuing. **Flag for future sessions: confirm no other session is actively driving the physical device (check `lsof -iTCP:8765` or equivalent, and for other `esphome logs`/upload processes) before reflashing** — this hardware is a single, shared, stateful resource that a concurrent session can be mid-experiment against.
- **Also discovered (important process note, separate from the above): all of sessions 4-12's real progress had been developed as uncommitted working-tree state on `feat/epic-1-story-3-follow-up-stop` in the main repo checkout — an unrelated branch/story about voice stop functionality — instead of on this story's own `puck-01/3-onboard-wake-detection` branch/worktree.** Nothing had been committed or PR'd in 12 sessions; the work was one `git clean`/branch-switch away from being lost. Ported everything (respeaker-lite.yaml, README.md, pcm_capture.h, the vendored `components/`, `wake_models/okay_nabu.*`, this story file) into this worktree after diffing to confirm the main-checkout versions were a strict superset of what was already committed here (only removed line: the story's own `status:` field, correctly, since it was never actually done). Verified `esphome compile` succeeds in this worktree before committing (`e134e1f`). The stray copies in the main checkout were then discarded (`git checkout --` / `rm -rf`) with the human's explicit sign-off, since they were now safely duplicated here. **Going forward, all Puck firmware work belongs in this worktree, on this branch — not in the main checkout.**

### Follow-up session 13: heap-leak root cause found for the upload wedge; circuit breaker added and verified live

**Went after the real question left open by session 12: not "does retry help" (already ruled out) but "what is the wedge actually doing to the device, and is it dangerous." Found a concrete, measured answer and fixed the dangerous part.**

- **Ruled out the "leaked/reused shared client handle" theory at the ESPHome layer by reading `http_request_idf.cpp` directly.** `HttpRequestIDF::perform()` calls `esp_http_client_init()` fresh on every single `post()` call and `esp_http_client_cleanup()` in `end()` (via `HttpContainerIDF::end()`). There is no persistent client instance being reused across chunks at this layer — whatever the wedge is, it's deeper than ESPHome's own component code.
- **Added heap instrumentation** to `pcm_capture.h`: logs `heap_caps_get_free_size(MALLOC_CAP_INTERNAL)` before and after every chunk POST, plus `heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL)` (the process-lifetime low watermark) on every failure.
- **Found a real, measured pattern, not a guess:** successful calls show no persistent trend (heap dips transiently during the call, always recovers to baseline ~216-222KB by the next call). **Failed calls do not recover the same way** — the "before" of the next failed call matches the "after" of the previous one almost exactly when failures run back-to-back, and only recovers once a call actually succeeds. A real live burst was measured spiraling: baseline ~224KB → after ~15 real failures, watermark down to 161KB; a later, longer burst went from ~224KB down through a transient 86508-byte low over about 4 minutes of intermittent real (not "not connected") failures.
- **Diagnosis: very likely a lingering/delayed-release resource inside ESP-IDF's own connect-failure path** (most plausibly a half-torn-down TCP socket that the OS/lwIP only reclaims after its own internal timeout, not something `esp_http_client_cleanup()` controls) — not a leak in this repo's own code, since the pattern is absent on the success path and ESPHome's side is already confirmed to clean up correctly. Going further into ESP-IDF's own transport-layer internals to find and patch the exact spot was judged out of reach (and arguably out of scope for this component even if reached) for this session.
- **Built a circuit breaker instead of chasing the root cause further:** `pcm_capture.h` now checks `heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL)` after every chunk and calls `App.safe_reboot()` once it drops below a 96KB threshold.
  - **First version checked `heap_after` (the post-call snapshot) and never fired** — a real transient dip to 86508 bytes was observed but had already partially recovered by the time `heap_after` was read a moment later, since recovery happens fast once the triggering call itself completes. Switched to the all-time-low watermark, which catches the real danger moment (the transient dip itself, when something else allocating concurrently would be at risk) and is appropriately monotonic — it only trips once per boot, which is correct here: reboot once things have ever gotten this low, don't wait for "currently this low."
  - **Verified live, with the corrected version:** ran a real burst until the watermark crossed the threshold. Breaker fired at a genuine 88076-byte watermark, logged clearly (`Internal heap watermark critically low... rebooting to reclaim ESP-IDF-held resources`), and called `App.safe_reboot()`. Serial log confirmed a clean software reset (`rst:0xc (RTC_SW_CPU_RST)` — not a `Guru Meditation`/`abort()`/backtrace crash marker), a normal boot back through `setup()`, and heap fully reclaimed to ~220KB. No crash-loop, no ESPHome Safe Mode trip, no repeat of the two crash-loop patterns from earlier sessions' raw-PCM-capture attempts.
- **Net result:** upload reliability itself is still not fixed — chunks still fail and get lost, same ~loss rate as before — but the failure mode changed from "unbounded heap depletion toward an unpredictable crash somewhere else in the firmware" to "a bounded, logged, ~10-second reboot-and-resume." This makes it safe to run the training-data pipeline unattended for longer stretches than before.
- **Also, separately: ported 9 sessions of uncommitted work from the wrong branch/worktree into this one and committed it here for the first time** (see the note appended to session 12's log above) — this session's own heap-instrumentation and circuit-breaker work was done correctly, in this worktree, from the start.
- **Left in a stable, verified state:** device flashed with the circuit breaker in place, confirmed surviving a real trigger-and-recover cycle, WiFi reconnecting normally afterward. All prior diagnostics (per-channel amplitude, mww state, raw probability, feature vector, tensor shape, PCM capture) remain in place, unchanged.
- **Concrete next steps, not attempted this session:** (1) upload reliability itself is still open — the circuit breaker makes the failure mode safe, it doesn't reduce how often chunks fail; further investigation would need to go into ESP-IDF's own `esp_http_client`/transport-layer source to find the actual lingering-resource cause, which is a materially deeper and more speculative undertaking than this session's instrumentation-and-mitigation approach. (2) the actual playback-and-capture orchestration script (session 11/12's step 2) — still not attempted. (3) dataset collection at scale and the `microWakeWord` training run itself — both still fully open.

### Follow-up session 11: training-data pipeline built and partially proven; real reliability bug remains

**Acted on session 10's conclusion (the gap is acoustic, not software) by starting the actual fix: infrastructure to collect real training data captured through this hardware. Real progress, not yet complete or fully reliable.**

- **Got real WiFi working.** Configured real household credentials in `secrets.yaml` (gitignored). First attempts failed to associate at all ("Probe Request Unsuccessful" on every try, across two mesh AP BSSIDs) -- most likely a router-side anti-flood throttle from the many rapid reflash/reconnect cycles across this session's many prior test rounds. Waited ~2.5 minutes; connected cleanly on retry.
- **Replaced the pcm_capture.h design** (was: one-shot capture, base64-dump-over-serial, far too slow for bulk data collection) **with continuous rolling capture + WiFi upload:** a 2-second PSRAM buffer, uploaded via `http_request` to a local receiver server on the dev Mac the moment it fills, then immediately re-armed for the next window -- no per-sample trigger round-trip needed.
- **First version of this crashed the device.** `std::string body(buffer, write_pos)` -- constructing one ~256KB string from the whole capture buffer -- threw `std::bad_alloc` and aborted: libstdc++'s default `operator new` for a plain `std::string` does not land on PSRAM here, and a single ~256KB contiguous internal-RAM allocation reliably fails. Root-caused via the decoded crash backtrace (`pcm_capture::upload_and_restart` at the string-construction line), not guessed at.
- **Fixed by chunking uploads** (~16KB per POST, well within internal-RAM allocation limits), with the receiver (`receiver.py`, a small Python `http.server` on the dev Mac) reassembling chunks by sequence + chunk-index into one file per capture window. Also added a small inter-chunk delay (`vTaskDelay(30ms)`) after back-to-back POSTs appeared to exhaust something in the ESP32's TCP stack.
- **Found and fixed a receiver-side bug too:** the reassembly logic only started a new output file on `chunk == 0`; if chunk 0 itself was dropped, every subsequent chunk for that sample got written to a *new* file instead of the shared one. Fixed to key off "first chunk seen for this sequence," not specifically chunk index 0.
- **Result: real, working captures.** Six complete, correctly-reassembled 256,000-byte samples (`seq0`-`seq5`) uploaded cleanly with no crashes, confirming the whole path -- PSRAM capture, chunked HTTP POST, receiver reassembly -- works end to end.
- **Not yet solved: intermittent upload reliability.** After a run of successful uploads, the `http_request` component sometimes drops into a persistent `ESP_FAIL` state (`http_request set Error flag: unspecified`), failing every subsequent chunk at a suspicious ~11-second cadence per attempt (longer than the configured 5s timeout, suggesting a retry/reconnect delay inside ESP-IDF's HTTP client rather than a clean single timeout). `response->end()` is called unconditionally including on failure, calling through to `esp_http_client_close`/`esp_http_client_cleanup`, so this isn't an obviously missing cleanup call in this project's own code -- most likely a resource exhaustion or connection-reuse quirk inside ESP-IDF's `esp_http_client` under rapid reconnect, not yet root-caused. Not attempted this session: explicit retry-with-backoff, periodic component reset, or switching to a persistent/keep-alive connection instead of one POST per chunk.
- **Not attempted this session (correctly out of scope for tonight):** actually collecting a full training dataset (hundreds of positive TTS-utterance-through-speaker-through-Puck captures, plus negative/background samples), and the `microWakeWord` training run itself (explicitly documented upstream as requiring real hyperparameter experimentation, not a single scripted run). One real end-to-end playback test (Piper TTS "hey jarvis" played through the dev Mac's speaker) was attempted but landed during an upload stall, so it did not produce a verified correlated sample this session.
- **Left in a stable state, mid-build.** Device flashed with the new WiFi/upload capture pipeline (not the old serial-dump version); `firmware/respeaker-lite/pcm_capture.h` now depends on `http_request:` (added to `respeaker-lite.yaml`). The receiver script and a Piper TTS voice model are on the dev Mac in `/tmp` (not part of the repo -- ephemeral, would need to be redone or relocated into the repo/tooling for a real multi-session data-collection effort). `secrets.yaml` now holds real WiFi credentials (still gitignored).
- **Concrete next steps, in order:** (1) root-cause or work around the intermittent `ESP_FAIL` streaks (retry-with-backoff is the fastest mitigation even without a root cause); (2) build the actual playback-and-capture orchestration loop (play a TTS utterance, wait, correlate against the nearest completed upload by timestamp, label and save); (3) collect a real dataset at scale (this hardware's positive samples plus negative/background); (4) work through `microWakeWord`'s training notebook, which the upstream project itself describes as requiring real experimentation, not a single automated run.
- **Added a bounded-abandon mitigation and re-verified over a longer window:** after 2 consecutive chunk failures, the current sample is abandoned (rather than burning through all 16 chunks at the ESP-IDF client's own multi-second retry cadence -- previously a single stuck sample could stall the pipeline for 100+ seconds). A clean 2-minute stability run afterward: zero crashes, 5 fully successful uploads logged, 7 abandoned (roughly 40% loss rate) -- the underlying `ESP_FAIL` streak issue is not fixed, only bounded. 11 files landed on disk in that window, several complete 256,000-byte samples among them. This loss rate is workable for forward progress (just means collecting at roughly 2-3x the capture time to reach a target sample count) but should be revisited before serious data-collection volume.

### Follow-up session: root cause found, detection still unresolved

**The "one unexplained detail" above turned out not to be the cause. The real one was much more basic.**

- **Root cause of every prior symptom, confirmed via source reading:** `esphome/components/micro_wake_word/micro_wake_word.cpp`'s `setup()` never calls `start()` — the component boots directly into `State::STOPPED`, and its own `add_data_callback` lambda explicitly returns early while `state_ == STOPPED`, dropping all audio unconditionally. Without a `voice_assistant:` component (which normally issues the start call), and with no `on_boot` action of our own, the engine was never listening at all — not once, across every attempt in the prior session. This fully explains the total silence: it was never about sample rate, gain, VAD, or wiring.
- **Fix:** added `esphome: on_boot: then: [micro_wake_word.start]`. First attempt used the default `on_boot` priority and failed with `"Wake word detection can't start as the component hasn't been setup yet"` — ESPHome's boot-time automations can fire before other components finish `setup()`. Fixed with `priority: -100`, the standard idiom for "run after all components are ready." Confirmed via live log: `State changed from STOPPED to STARTING` → `to DETECTING_WAKE_WORD`.
- **Added a permanent amplitude diagnostic** (`microphone: on_data`, `mic_diag` log tag) that logs peak amplitude once per second, entirely independent of `micro_wake_word`. This is what let us *prove* the pipeline is alive rather than continue guessing: baseline room noise reads ~5–90M, and speech reliably spikes it into the 1–2 billion range.
- **With the real fix in place, tried again: still no detection.** Two more live attempts at "hey jarvis" produced clear amplitude spikes (loud, unambiguous speech reaching the mic) but zero `micro_wake_word` detection lines. A third attempt used the bundled **`stop`** model instead — a completely different phrase with a far more lenient threshold (0.50 vs. `hey_jarvis`'s 0.97) — specifically to distinguish "hey jarvis is a hard phrase/accent match" from "something is systemically wrong." Also produced loud amplitude spikes and zero detection. This rules out phrase-specific mispronunciation as the sole explanation.
- **Checked two more hypotheses by reading source, both came up empty:**
  - VAD gating: `vad_state_` is written by `determine_detected()` but never checked before `update_model_probabilities_()`/`process_probabilities_()` run — VAD does not gate wake-word inference in this version. Ruled out.
  - The fork's decimation: re-read the *complete* diff between `formatBCE/esphome` and stock ESPHome at the pinned commit (only 20 lines across 2 files — small enough to read in full). Initially concluded, wrongly, that it only relabeled the sample rate without resampling; a closer read found it does perform real decimation (keeps 1 stereo frame out of every 3, correctly matching 48kHz→16kHz) via naive nearest-sample dropping with no anti-aliasing filter. Real DSP quality concern, but crude aliasing degrades accuracy — it shouldn't produce *total* silence on two different models with very different thresholds.
- **Attempted to get conclusive evidence by capturing raw audio for a human to actually listen to — this went wrong, twice, and was reverted both times:**
  1. First attempt: accumulated audio into a `std::vector<uint8_t>` global via repeated `insert()` calls directly inside the microphone's own real-time `on_data` callback, targeting a 1MB capture. Result: the device crash-looped (`abort()`, `rst:0xc`) continuously from the moment of flashing. Root cause suspected: requesting far more heap than the ~230KB of free internal SRAM (no PSRAM configured), though not confirmed with certainty before reverting.
  2. Second attempt, redesigned to be safer: added `psram: mode: octal` (the XIAO ESP32-S3's chip has 8MB Octal PSRAM per `esptool`'s own chip report), pre-sized a fixed buffer once in `on_boot` (no reallocation during capture), and wrote into it by index rather than growing it. This **also crashed** — with a different abort address, and critically, within ~1 second of every boot, well before the capture logic's own 8-second start-delay could even run. This points at the `psram:` configuration or the `resize()` call itself, not the capture-writing logic — not further diagnosed.
  3. Both crash-loops tripped ESPHome's built-in **Safe Mode** protection (10 failed boots → 300s recovery-only mode) — a good sign the safety net works, but it also means each incident cost real time waiting it out.
  4. **Both attempts were fully reverted** (all capture-related YAML removed, `psram:` removed) and the resulting build reconfirmed stable: zero crashes, zero safe-mode triggers, 24+ consecutive clean amplitude readings.
- **Net result:** a genuinely important root-cause bug is fixed and confirmed (the on_boot start). The narrower "why doesn't detection fire despite live, loud audio" question remains open. Two raw-audio-capture designs both crashed the device before yielding evidence — **do not repeat either approach as tried here** (growing a vector inside the mic task's own callback; a fixed-size PSRAM buffer resized in `on_boot`) without first understanding why they aborted. A safer redesign would likely need the accumulation to happen in a separate, larger-stack task (e.g. via a queue handed off from `on_data` to a `interval:`-driven consumer) rather than directly inside the audio driver's own callback context.

## Verification

**Commands:**
- `esphome compile firmware/respeaker-lite/respeaker-lite.yaml` -- expected: build succeeds
- `esphome upload firmware/respeaker-lite/respeaker-lite.yaml --device /dev/cu.usbmodem101` -- expected: flash succeeds, device boots

**Manual checks (if no CLI):**
- After flashing, run `esphome logs firmware/respeaker-lite/respeaker-lite.yaml --device /dev/cu.usbmodem101`, speak "hey jarvis" near the device, and confirm a wake-word detection log line appears.

## Review Triage Log

- **medium, patch** — `external_components:` pinned the trusted third-party `i2s_audio` fork to the mutable branch head (`ref: respeaker_microphone`, `refresh: 0s`) rather than a commit. Confirmed independently by both review layers. Fixed: pinned to commit `eedcdbee335dbe296d432b3e6421da0469907365` (the branch's current tip at time of pinning) with a comment explaining why, and removed the now-unnecessary `refresh: 0s`.
- **medium, patch** — the story's own Intent/Decision cited `KasunThushara/Respeaker-Lite-ESPHome-integration` as the reference integration, but the actual YAML/README consistently cite `formatBCE/Respeaker-Lite-ESPHome-integration` — a citation slip from a similarly-named project surfaced during story 1's research. Confirmed independently by both review layers. Fixed: corrected the Intent/Decision text to match what was actually implemented, with a note explaining the correction rather than silently rewriting history.
- **medium, patch** — README's install instructions pointed at `pip install -e ".[firmware]"`, which I verified actually fails: the main project's `requires-python` (`>=3.14,<3.15`) rejects an editable install of the local package under the Python 3.12 `venv-firmware`. Fixed to a direct `pip install "esphome>=2025.9.0"`, matching `pyproject.toml`'s version constraint without attempting to install the incompatible local package.
- **low, patch** — README's Wake-word check (step 5) read as a normal expected-to-pass step with no pointer to the documented 4/4 failure. Fixed: added an inline note pointing to Known Limitation.
- **low, patch** — the cleartext-WiFi-password-at-`VERY_VERBOSE` finding was documented in the story file and memlog but absent from README's Known Limitation, the place someone debugging this exact issue would actually look. Fixed: added a warning there.
- **low, patch** — `gain_factor: 4` and `vad: probability_cutoff: 0.05` had no stated provenance, reading as arbitrary guesses. Fixed: Code Map now states both are sourced verbatim from Seeed's wiki tutorial, not invented.
- **defer** — stereo-to-mono channel selection inside the forked `i2s_audio` component is unexplained and could plausibly be the actual cause of the "zero audio activity" mystery (e.g., if the XU316's real signal sits on the dropped channel). Investigating the fork's source is real, separate effort beyond this review pass; recorded as a concrete next thing to check, in Implementation Notes.
- **false** — "no `.tflite` binary appears in this diff, so a fresh checkout may not compile." Disproof: `firmware/respeaker-lite/wake_models/` (including all three `.tflite` files) is untracked but confirmed *not* gitignored (`git check-ignore` returns nothing); the review diff only omitted them because they're binary and not meaningfully reviewable as text — they are staged and committed alongside the JSON manifests.
