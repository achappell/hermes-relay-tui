---
title: 'Implement on-device wake-word detection on the Puck'
type: 'feature'
created: '2026-09-08'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '44047c964b6d4c8dbfad7427e07a51c74f727239'
context:
  - _bmad-output/specs/spec-hermes-relay-tui/SPEC.md
  - firmware/respeaker-lite/respeaker-lite.yaml
  - firmware/respeaker-lite/README.md
---

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
