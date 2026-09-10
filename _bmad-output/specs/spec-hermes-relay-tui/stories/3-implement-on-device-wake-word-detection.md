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

## RESUME HERE (2026-09-09, end of session 17, fourth update -- loose ends closed)

**Fourth update, same session: closed both loose ends from the third
update.**

- **`okay_nabu` verified working.** A fresh hard reset was needed first
  -- the device had been sitting idle through ~15 minutes of
  documentation/commit work between the third update's test and this
  one, and came back with `mww is_running: false` (not a crash marker,
  just a stale/idle state; a hard reset via `esptool.py --after
  hard_reset chip_id` immediately restored `is_running: true`). With a
  fresh boot, 10 "okay nabu" TTS plays produced 21 high-confidence
  readings (166-255/255 against cutoff 247), each correlated with a
  simultaneous VAD spike and clean returns to baseline between
  utterances -- same clean, reliable pattern as `hey_jarvis`. Both
  pretrained wake-word models work.
- **Wired the XMOS DFU update permanently into the production
  `respeaker-lite.yaml`** (`i2c:` bus + `respeaker_lite:` block, matching
  the already-vendored, already-fixed component from earlier this
  session), rather than leaving it a one-time manual step specific to
  this physical unit. Reasoning: this firmware is meant to be flashed
  onto *a* reSpeaker Lite, not only the one unit already updated tonight
  -- a fresh unit would ship with whatever XMOS firmware Seeed's factory
  process put on it (1.0.8 on this unit), and without this wired in,
  wake-word detection would silently fail again on that unit with no
  obvious cause pointing back to firmware version. The DFU check is
  idempotent (compares current vs. expected version, only flashes on a
  real mismatch), confirmed on this already-updated unit: `DFU version:
  1.1.0` logged with no `Updating...` step, clean boot, zero crash
  markers.
- **Re-verified the fully integrated production firmware end-to-end**:
  compiled, flashed, fresh boot, DFU no-op confirmed, then 6 more
  wake-word plays (5x "hey jarvis" + 1x "okay nabu") all produced clean
  255/255 (and 246/255) readings with zero crashes. This is the actual
  shipped firmware now, not a separate test config.
- Also corrected a now-stale comment in `respeaker-lite.yaml` that still
  claimed the vendored `i2s_audio` has "a real anti-aliasing filter" --
  updated to explain the revert and point at the decimation loop's own
  comment for the full story.
- **Net: PUCK-01.3 is complete.** Both loose ends from the third update
  are closed with real hardware verification, not just asserted. The
  shipped `respeaker-lite.yaml` now: flashes the correct XMOS firmware
  automatically on any unit, uses stock (unfiltered) decimation, and
  reliably detects both `hey_jarvis` and `okay_nabu` on real speech with
  proper rejection of non-wake phrases.

## RESUME HERE (2026-09-09, end of session 17, third update -- SOLVED)

**Third update, same session: wake-word detection works. This is the
resolution of this story's core, months-long blocker.**

- The user directly challenged the second update's negative result:
  "supposedly ESPHome works out of the box on this device," pointing at
  Seeed's own official wiki (`wiki.seeedstudio.com/respeaker_lite_ha/`).
  Fetched it directly -- it specifies the exact same XMOS firmware
  version (1.1.0), `gain_factor: 4`, and VAD `probability_cutoff: 0.05`
  already tested. Nothing new there on its own, but the user asked for
  the complete stock config to be built and tested as faithfully as
  possible, not just the XMOS DFU piece layered onto this project's own
  pipeline -- and that turned out to be exactly the right call.
- **Built formatBCE's actual full reference config**
  (`respeaker-lite-stock-test.yaml`, copied from
  `config/common/respeaker-satellite-base.yaml` almost verbatim -- only
  added `esphome.name`, `wifi.ssid/password`, `api.encryption.key` via
  secrets, and a lab-only supplementary `micro_wake_word.start` trigger
  at `priority: -300` since the stock trigger requires a live Home
  Assistant connection this lab doesn't have). Critically, used a
  **freshly vendored, byte-for-byte unmodified copy of `i2s_audio`**
  (`components_stock/i2s_audio/`, cloned fresh from
  `formatBCE/esphome@respeaker_microphone`) instead of this story's own
  `components/i2s_audio/`, because that one has a deliberate anti-
  aliasing FIR filter improvement from session 6 -- reusing it would have
  tested this project's own pipeline again, not the actual out-of-the-
  box reference.
- **Hit and fixed the same class of environment crash again, more
  generally this time.** The stock config's ~12 remote files (sound
  effects, `okay_nabu`/`kenobi`/`hey_mycroft`/`stop` model downloads)
  each independently trigger `external_files.download_content()`, and
  ESPHome's own mainline version of that function (unlike the
  respeaker_lite-specific one patched earlier this session) always
  attempts a live network call regardless of cache state -- so the same
  SIGSEGV recurred via 11+ other call sites the earlier, narrower fix
  didn't cover. Pre-importing `requests` earlier in the same process did
  *not* help (directly falsifies the "first import" theory from the
  first update -- the real trigger is calling `download_content()`
  itself, not importing its dependency). Fixed properly this time with a
  general monkeypatch (`external_files.download_content` skips the
  network call whenever the cache file already exists) applied via a
  small wrapper script, rather than patching every individual call site.
- **Result: `hey_jarvis` fires cleanly and repeatedly** -- 255/255
  against a cutoff of 247, correlated exactly with 10 "hey jarvis" TTS
  plays, with proper return to near-zero baseline between utterances
  (real temporal discrimination, not a stuck-high fault). **VAD showed a
  genuine, clean speech-detection curve for the first time in this
  story's entire history** -- climbing from a baseline of ~1-14/255 to
  200+/255 during speech and decaying back down, where every previous
  session (including this same session's second update, on this
  project's own pipeline) saw it pinned near zero regardless of
  confirmed loud audio reaching the mic. **Negative control confirmed
  real discrimination, not just voice-activity triggering**: three
  plays of "what time is it" produced a real VAD response (climbing to
  184/255) but `hey_jarvis`/`okay_nabu` correctly stayed at 0/255
  throughout.
- **Root cause, found by diffing the stock and patched `i2s_audio`
  microphone implementations: session 6's 31-tap windowed-sinc anti-
  aliasing FIR filter -- not the naive nearest-sample-drop decimation it
  replaced -- was the actual cause of every non-detection result across
  sessions 3-17.** The naive decimation is textbook aliasing and was a
  real, correctly-diagnosed problem (confirmed by spectrogram inspection
  in session 4); fixing it was reasonable engineering. But the fix itself
  broke the very thing it was meant to help: the FIR's steeper 7kHz
  cutoff most likely removes spectral content (plausibly 7-8kHz energy,
  or reshapes formant-adjacent frequencies) that this specific pretrained
  model actually relies on. Mathematically more correct anti-aliasing;
  empirically worse for this model. Nobody re-verified live wake-word
  detection immediately after adding the steeper filter in session 6 in
  a way that isolated it from the other simultaneous changes -- by the
  time detection was retested, several other variables had also changed.
- **Reverted `components/i2s_audio`'s decimation back to the stock naive
  nearest-sample-drop** (with a detailed comment explaining why, so a
  future session doesn't reintroduce the same regression without
  re-verifying on real hardware first) and **re-verified on the actual
  production `respeaker-lite.yaml`** (not just the stock-test config):
  same clean, repeated 255/255 detections, zero crashes. This is the
  real firmware this story ships, now actually working.
- **Net effect on the story: PUCK-01.3's actual goal -- on-device
  wake-word detection -- is achieved**, using the pretrained community
  `hey_jarvis` model, formatBCE's XMOS firmware (1.1.0), and stock
  (unfiltered) 48kHz->16kHz decimation. The custom-training pipeline from
  steps 1-3 (data collection, 30-clip dataset, first trained `.tflite`)
  remains fully working and committed, but is no longer required for
  basic detection -- it's future work for improving accuracy/vocabulary/
  false-accept rate, not a blocker.
- **What's not yet done:** `okay_nabu` never produced a high-confidence
  reading in this session's tests (stayed in the 1-6/255 range even
  during clear speech) -- worth a dedicated test with that exact phrase
  before assuming it also works. The `respeaker-lite-stock-test.yaml`/
  `components_stock/` artifacts are kept as committed reference/evidence
  for this finding, not meant for ongoing use. The real remaining
  question for closing out this story is whether to keep the
  `respeaker_lite:`/XMOS-DFU component wired into the shipped
  `respeaker-lite.yaml` permanently (recommended -- it's what makes the
  firmware match a known-working reference) or leave it as a one-time
  manual step, and whether `okay_nabu` needs its own verification pass.

## RESUME HERE (2026-09-09, end of session 17, second update -- the decisive test)

**Second update, same session: tested whether the corrected XMOS firmware
actually fixes wake-word detection. It doesn't. This is a real, well-
controlled negative result -- not a retreat to the old untested
assumption, but the same experiment sessions 3-10 never got to run,
now actually run.**

- Skipped debugging the mic_task boot-loop bug in the minimal DFU-test
  config entirely -- it wasn't needed. The XMOS firmware upgrade to
  1.1.0 is permanent, independent of whatever's flashed to the ESP32, so
  reflashed the already-proven `respeaker-lite.yaml` (confirmed working
  in the first update) and tested wake-word detection directly with it,
  since it already has `hey_jarvis`/`okay_nabu`/`vad` wired in.
- **Played "hey jarvis" via macOS TTS near the device 18 times total
  across two rounds** (3 then 15 more), watching the live raw-probability
  diagnostic the whole time. Confirmed real, strong audio was reaching
  the mic throughout via the existing `mic_diag` amplitude log (ch0 in
  the hundreds of millions, ch1 in the low millions -- consistent with
  the documented ch0-loud/ch1-quieter split, not silence or a dead
  channel).
- **Result: `hey_jarvis` and `okay_nabu` stayed flat at 0/255 through
  every single reading, and -- more tellingly -- so did `vad`, sitting
  at 0-2/255 against a cutoff of 12 throughout, despite being described
  in this story's own prior sessions as "much more lenient" and expected
  to react to almost any loud sound.** VAD not responding at all to
  confirmed strong audio is a stronger signal than the wake-word models
  themselves staying flat -- it suggests whatever's wrong isn't specific
  to `hey_jarvis`/`okay_nabu`'s learned weights, but to the audio
  characteristics on the channel micro_wake_word consumes, full stop.
- **Conclusion: the XMOS firmware version was a real, confirmed gap
  (this unit genuinely was running the wrong version, and updating it
  works), but it was not the cause of the wake-word detection failure.**
  Sessions 3-10's "acoustic mismatch" theory is now on much firmer
  ground than before this session -- not because it went untested again,
  but because the one major untested confound (firmware version vs. a
  known-working reference) has now actually been eliminated, with
  hardware evidence, rather than assumed away.
- **What's still open:** *why* the XU316's processed audio doesn't
  suit these models is still not root-caused at the signal level (only
  proven-not-caused-by: audio pipeline math, model files, tensor shapes,
  feature generation, and now firmware version). A genuinely deeper dig
  would compare a captured ch1 spectrogram against what these models
  were actually trained on, but that's a new investigation, not a
  quick follow-up.
- **Net effect on the story's direction: back to steps 1-3's custom-
  training path as the real way forward, now with much stronger
  confidence that it's actually necessary** (not just the untested
  default when a simpler theory hadn't been fully checked). The
  mic_task boot-loop bug in the DFU-test config remains unfixed and
  low-priority -- it blocks nothing now that the firmware-version
  question is settled either way.
- **Device left in its known-good state**: `respeaker-lite.yaml`
  flashed and running normally, XMOS firmware permanently at 1.1.0.

## RESUME HERE (2026-09-09, end of session 17 -- major finding, read first)

**Session 17's premise, raised directly by the user: sessions 3-10's
"acoustic mismatch, unfixable" conclusion was reached entirely by
*internal* cross-validation (synthetic vs. real audio through this
project's own pipeline) -- never by testing against an actual
known-working reference, despite this project's own firmware being
closely modeled on one (`formatBCE/Respeaker-Lite-ESPHome-integration`).
That gap turned out to be real and significant.**

- **Found the real gap:** formatBCE's actual reference config
  (`config/common/respeaker-satellite-base.yaml`) does something this
  project's firmware never did -- flashes **custom firmware onto the
  reSpeaker Lite's onboard XMOS XU316 DSP itself** (a `respeaker_lite:`
  ESPHome component, I2C-based DFU, independent of whatever's flashed to
  the ESP32) via `respeaker_lite_i2s_dfu_firmware_48k_v1.1.0.bin`. Every
  session's diagnosis was implicitly comparing against whatever XMOS
  firmware this specific unit shipped with -- never verified to match
  the version the "it works on other people's units" evidence (the
  videos the user watched) was actually produced with.
- **Confirmed on real hardware: this unit's shipped XMOS firmware was
  version 1.0.8, not 1.1.0.** Vendored `formatBCE`'s `respeaker_lite`
  component locally (`components/respeaker_lite/`, pinned at commit
  `3136cf7`, same pattern as this story's existing `i2s_audio`/
  `micro_wake_word` vendoring) and built a standalone experiment config
  (`respeaker-lite-xmos-test.yaml`) reusing this story's already-proven
  audio path plus the DFU block, deliberately not merged into the main
  `respeaker-lite.yaml` until the result was known.
- **A long, genuinely difficult environment bug blocked compiling this
  for most of the session -- fully root-caused, not worked around
  blindly.** Every compile attempt that included the `firmware:` block
  crashed the ESP-IDF toolchain subprocess with a native SIGSEGV
  (`_yaml`'s C extension, per a macOS crash report), 100% reproducible,
  regardless of firmware size (even truncated to 200 bytes), swap/memory
  pressure (ruled out: freed 25GB disk, still crashed), or a full OS
  restart (also ruled out: 0 swap used, 60GB free disk, still crashed
  identically). **Actual root cause: `external_files.download_content()`
  does a deferred `import requests` on every call, even when a
  correctly-cached copy already exists on disk** -- isolated by testing
  every combination (bare component, +i2c, +respeaker_lite-without-
  firmware, +firmware truncated to 200 bytes) until only the presence of
  that one call correlated with the crash. Fixed in the vendored
  component by skipping `download_content()` entirely when
  `_compute_local_file_path()`'s cache file already exists on disk --
  the file was already downloaded and MD5-verified earlier in the
  session, so this isn't a coverage gap, just avoiding a redundant
  network round-trip that happens to trigger a real crash in this
  environment. Root cause of *why* that import specifically segfaults
  was not chased further (plausibly a memory-layout collision with a
  later subprocess's shared-library load) -- the fix avoids it
  regardless of the deeper mechanism.
- **A second, unrelated real bug found and fixed the same way: a null
  pointer dereference.** `respeaker_lite.cpp`'s `dfu_get_version_()`
  unconditionally calls `this->firmware_version_->publish_state(...)`,
  but that pointer is only set when the optional `firmware_version:`
  text_sensor is configured -- crashed with `Guru Meditation Error
  (LoadProhibited)` in a genuine boot loop on real hardware the moment
  DFU version-checking ran. Fixed with the same null-guard pattern
  already used for `mute_state_` elsewhere in the same file.
- **With both fixes, the DFU update ran for real on the physical device
  and succeeded:** `Expected XMOS version: 1.1.0; found: 1.0.8.
  Updating...` -> progress to 100% -> `DFU version: 1.1.0` -> `Update
  complete`. The XMOS chip's own firmware is now permanently at 1.1.0
  (independent of whatever's flashed to the ESP32 afterward).
- **A third, still-unresolved bug appeared immediately after: the
  minimal test config's `mic_task` hangs and trips ESPHome's own
  loopTask watchdog on every subsequent boot**, landing the device in a
  boot loop that correctly escalated into ESPHome's built-in Safe Mode
  after 10 failed attempts (not bricked -- a designed, recoverable
  failure mode: 300s safe window, OTA/API still reachable). Not
  root-caused this session.
- **Critical, reassuring check performed before ending the session:
  reflashed the actual proven `respeaker-lite.yaml` (this story's real
  serial-dump/training-capture firmware) and confirmed it boots and
  runs completely normally against the now-permanently-updated XMOS
  1.1.0 firmware** -- real `PCMDUMP` output streaming, zero crash
  markers, exactly as before. **The mic_task hang is specific to
  something in the minimal `respeaker-lite-xmos-test.yaml` test config,
  not a general incompatibility between this story's existing
  microphone driver and XMOS firmware 1.1.0.** The device is left in a
  known-good, working state -- not blocked, not bricked -- with the XMOS
  firmware upgrade already banked as a permanent hardware-side change.
- **What this means for the story's overall direction:** the
  "acoustic mismatch, unfixable, must train a custom model" conclusion
  from sessions 3-10 is now genuinely uncertain rather than settled --
  this unit really was running different XMOS firmware than the
  reference implementation the "it works" evidence is based on, which is
  exactly the kind of confound that theory never ruled out. **Next real
  step, not attempted: once the mic_task hang in the DFU-test config is
  fixed, actually test whether the pretrained community models
  (`hey_jarvis`, `okay_nabu`, already wired into this story's firmware)
  detect real speech now that this device has the same XMOS firmware
  version as the reference.** If they do, the custom-training path
  (steps 1-3, still fully working and banked) becomes optional
  polish/fallback rather than the only path forward. If they still
  don't, that's much stronger evidence for the original acoustic-
  mismatch theory than anything sessions 3-10 established alone.

## RESUME HERE (2026-09-09, end of session 16, sixth update -- step 3 done)

**Sixth update, same session: ran microWakeWord's training pipeline
end-to-end against the 30-clip dataset from step 2 and got a real
quantized streaming .tflite artifact out. This is the first time this
story has produced an actual trained model file, not just infrastructure
around one.**

- Reused session 15's training environment (`/tmp/mww_train_venv`,
  `/tmp/microwakeword_src` -- both survived on disk). Import-verified
  in session 15 but never actually exercised training until now.
- **Two real dependency gaps found and fixed, neither specific to this
  project:** (1) `microwakeword.audio.clips.Clips` loads audio via
  HuggingFace `datasets`' `Audio` feature, which in the installed
  `datasets` version requires `torchcodec`, which itself requires an
  ffmpeg build matching one of a few pinned major versions --
  homebrew's installed ffmpeg (9.x) was too new, and getting a
  compatible older one felt like more dependency wrangling than
  warranted. Fixed by bypassing `Clips` entirely: since the training
  clips are already clean 16kHz mono 16-bit PCM WAVs, loaded them
  directly with the stdlib `wave` module and called
  `generate_features_for_clip()` (the actual feature-extraction
  function `Clips` would have called anyway) directly. (2)
  `model_train_eval.py`'s training loop calls `tf.summary.scalar`,
  which needs the `tensorboard` package -- not pulled in as a
  dependency by default; `pip install tensorboard` fixed it.
- **One upstream default-value bug found:** `mixednet`'s own
  `--residual_connection` CLI default is `"0,0,0,0,0"` (5 values) while
  its other list-shaped hyperparameters (`pointwise_filters`,
  `repeat_in_block`, `mixconv_kernel_sizes`) default to 4 values each --
  `mixednet.py`'s `model()` raises `ValueError: all input lists have to
  be the same length` with the tool's own defaults. Not a bug in
  anything this story touched; worked around by passing
  `--residual_connection "0,0,0,0"` explicitly.
- **Built `firmware/respeaker-lite/tools/build_training_features.py`**
  (new committed tool): generates ragged-mmap spectrogram features from
  `label_captures.py`'s WAV output and writes a `training_parameters.yaml`,
  skipping augmentation and the HuggingFace negative-dataset downloads
  the notebook normally uses (would add real value for a serious
  training run, but weren't needed to prove the pipeline works).
- **Ran the actual training** (`microwakeword.model_train_eval`,
  `mixednet` architecture, 200 steps, batch size 16, our 30-clip
  90/10/10-ish train/validation/testing split): converged to near-zero
  training loss within 50 steps (expected overfitting on 11 training
  clips per class), and **produced a genuine 57KB quantized streaming
  TFLite model** at
  `tflite_stream_state_internal_quant/stream_state_internal_quant.tflite`
  -- the exact artifact format `micro_wake_word:`'s ESPHome component
  expects per the story's own README.
- **The model itself is not usable and was not flashed to the device.**
  ROC/false-accept-rate numbers came back degenerate (AUC `nan`, `faph`
  `nan` at every cutoff) because there's no real ambient/background
  negative set and only 2 held-out test clips per class -- exactly the
  outcome microWakeWord's own README warns is normal for a first run
  with too little data. **Flashing this model would be a wasted reflash
  cycle for a near-certainly-broken detector; don't do it.**
- **Net: the full step 1 -> step 2 -> step 3 pipeline (serial capture ->
  labeled dataset -> trained artifact) is now proven working end-to-end
  on real hardware and real data, for the first time in this story's
  history.** What's missing for an actually usable model is purely
  *more and better data* -- more collection sessions (the pipeline
  scales by repetition, no new engineering needed), and ideally the
  HuggingFace ambient-negative datasets (`dinner_party`, `no_speech`,
  `speech` from `kahrendt/microwakeword`) for realistic false-accept
  evaluation, which `build_training_features.py` deliberately skipped
  this run.
- **Next real step: scale up data collection** (more sessions like
  step 2's, ideally hundreds of positive/negative clips, not 15/15),
  then retrain and evaluate before ever considering a flash-to-device
  test.

## RESUME HERE (2026-09-09, end of session 16, fifth update -- step 2 done)

**Fifth update, same session: actually collected a real, correlated,
labeled training dataset over the serial path -- the "step 2" this story
has never completed across sessions 11-16. No firmware reflash needed;
reused the already-flashed 15-capture firmware from the fourth update.**

- **First attempt failed silently and taught a real lesson about backgrounding
  processes across Bash tool calls in this harness:** launching
  `collect_serial_dumps.py` via `(cmd &)` in the same compound shell
  command as a later `esptool` reset and a second `(cmd &)` for
  `collect_samples.py` caused the dumps collector to die within ~2
  minutes with no error, producing 0 samples -- while the *device itself*
  correctly ran its full 15-capture series into the void (confirmed
  because a diagnostic re-run immediately after found `dumps_done` already
  at its bound, i.e. a full run had genuinely completed, just unobserved).
  **Fix: launch each long-running background process in its own Bash tool
  call with explicit `nohup ... < /dev/null & disown`, and verify the
  process is still alive and actually producing output a few seconds
  later before starting anything that depends on it.** This worked
  cleanly for both runs that followed.
- **Ran two full collection sessions, each a fresh hard-reset boot, no
  reflash between them:**
  - Positive: `collect_serial_dumps.py` capturing to `/tmp/pcm_train_positive`
    concurrently with `collect_samples.py --count 78 --gap-seconds 3.5
    --session-tag positive` (continuous "hey jarvis" TTS across 7 macOS
    voices/4 rates, replayed near the device for ~7.5 minutes). Result:
    15/15 full captures saved, all 78 utterances logged, session window
    written.
  - Negative: same pattern, `--negative --count 70 --session-tag
    negative` (10 everyday non-wake phrases). Result: 15/15 full captures
    saved, all 70 utterances logged, session window written.
  - Chunk-decode failures stayed in the same ~0.05-0.1%/1280 range seen
    in the earlier pure-transport tests (1-3 chunks per capture,
    zero-filled by the tool as designed) -- no change under real
    TTS-playback conditions vs. the earlier idle-room tests.
- **Ran the real `tools/label_captures.py --session-mode` against both
  directories** (this script needed zero changes -- it already keyed off
  the `<recv_time>_seq<N>.raw` filename convention that
  `collect_serial_dumps.py` already matches, since it was written
  against `receiver.py`'s WiFi-path output using the identical
  convention). **Result: 30 labeled 2-second 16kHz mono WAV clips** in
  `/tmp/training_clips/{positive,negative}/`, 15 each, correctly
  converted through the same Q31->Q25->gain->Q31->16-bit pipeline that
  matches what `micro_wake_word`'s `MicrophoneSource` actually sees.
- **Sanity-checked amplitude on a sample of clips (not just file
  presence): real, varied peak/RMS levels across both classes (peaks
  frequently near full-scale, consistent with real speech through this
  gain_factor 4 setup), not silence or corrupted zero-fill noise.**
- **Net: one full pass of steps 1-2 across this story is now complete on
  real hardware.** 30 samples (15/15 balanced) is far more than session
  15's WiFi-path yield of 1 in a full day, but still small by
  microWakeWord training standards (typically wants hundreds-thousands).
  Scaling this further (more sessions, longer TTS runs, more voices/
  phrases) is straightforward now that the pipeline is proven -- it's
  pure repetition of what just worked, not new engineering. Training
  data currently lives only in `/tmp/pcm_train_positive`,
  `/tmp/pcm_train_negative`, and `/tmp/training_clips` -- **not
  persisted anywhere durable yet**; a future session should either copy
  it somewhere permanent before running more collection passes that
  might reuse those tmp dirs, or fold accumulation logic into the
  collection scripts.
- **Next real step (step 3, not attempted): actually train a
  microWakeWord model** on this data using the training environment
  session 15 already set up (`/tmp/mww_train_venv`, `microwakeword`
  installed and import-verified, but the training run itself never
  attempted since there was never data until now). 30 samples is likely
  too few for a good model but enough to prove the training pipeline
  itself runs end-to-end -- worth trying now, then deciding whether to
  scale up data collection before investing in a "real" training run.

## RESUME HERE (2026-09-09, end of session 16, fourth update)

**Fourth update, same session: scaled the bounded repeat from 3 to 15
captures. Clean across the board -- this answers the "does corruption
rate grow with more captures" question the third update left open.**

- Raised `MAX_DUMPS` from 3 to 15, flashed, then ran the real
  `tools/collect_serial_dumps.py` against a fresh boot for the whole
  series (~6.5 minutes: 15 x (2s capture + ~20s dump)).
- **Result: 15/15 full 256000-byte captures saved, zero crash markers
  anywhere in the run's full log** (`esphome logs` output the tool wraps
  internally -- checked explicitly for abort/panic/task_wdt/Unsuccessful
  boot, found none), device still logging `mww_diag`/`mww_prob` normally
  15s after the tool exited.
- **Chunk-corruption rate across the whole run: 9 zero-filled chunks out
  of 19200 total (15 x 1280) -- about 0.05%,** not worse than (if
  anything slightly better than) the smaller earlier runs this session.
  One capture (seq=10) also came out 96 bytes short of the expected
  256000 -- most likely a corrupted `PCMDUMP begin` header line itself
  (which carries the declared total_bytes), the same class of occasional
  serial-line noise as the individual chunk failures, not a new failure
  mode. **No evidence the corruption rate grows with a longer bounded
  run.**
- **Net: the transport is now proven safe and stable at 15 consecutive
  full-size captures in one boot.** Genuinely open questions remaining:
  indefinite (no upper bound) operation specifically, and whether
  anything changes over dozens/hundreds of captures rather than 15. Given
  today's device has now been reflashed 5 times, further live scaling
  should wait for a fresh session (router anti-flood caution, on record
  since session 11).

## RESUME HERE (2026-09-09, end of session 16, third update)

**Third update, same session: proved bounded, re-armed repeat capture
works -- three full 2s/1280-chunk captures back-to-back, no hang, no
crash, via the real `collect_serial_dumps.py` tool producing three real
`.raw` training samples.**

- Changed `dump_over_serial()`'s single-shot `already_dumped` flag to a
  bounded counter (`MAX_DUMPS = 3`): after each dump completes, if the
  count hasn't been reached, it calls `start()` to re-arm the next 2s
  capture; once reached, it stops permanently and logs "series complete."
  Deliberately NOT an indefinite loop -- this tests whether *repeated*
  captures survive before ever reconsidering continuous operation.
- **Verified twice on real hardware:** once watching raw `esphome logs`
  output directly (seq=0/1/2 each began, ran their full ~20s dump, and
  ended cleanly; series-complete message logged; device kept running
  mww/mic diagnostics normally 45+s afterward with zero crash markers),
  and once through the real `tools/collect_serial_dumps.py` against a
  fresh boot, which produced three genuine 256000-byte `.raw` files
  (`_seq0.raw`, `_seq1.raw`, `_seq2.raw`) with no manual intervention.
- **Chunk loss observed:** 2 out of 1280 chunks failed base64 decode in
  one of the six total dumps run across both verification passes (both
  times consistent with the ~1-2/1280 rate the tool's own docstring
  already anticipated as normal serial-line corruption from session 4);
  zero-fill handling covered it transparently in both the ad hoc verifier
  and the real tool. Not a regression, not new behavior.
- **This resolves the transport-safety question entirely for repeated
  captures within a bounded series.** What's still genuinely untested:
  indefinite/continuous re-arming (no upper bound), and whether the
  occasional chunk-corruption rate holds steady or grows over a much
  longer run (dozens+ of captures, not 3). Given today's device has now
  been reflashed multiple times, further live testing should wait for a
  fresh session per the router-anti-flood caution already on record.

## RESUME HERE (2026-09-09, end of session 16, continued)

**Second update, same session: root-caused session 15's serial-dump hang
and proved a full single 2s/1280-chunk capture dumps cleanly end-to-end,
including through the real `collect_serial_dumps.py` tool. This was the
actual blocker on the WiFi-vs-serial transport decision -- it's resolved.**

- **Root cause of session 15's hang, found by scaling incrementally
  instead of jumping straight back to 1280 chunks:** at `DUMP_MAX_CHUNKS =
  300` (~60KB), the very first live test tripped ESPHome's own loopTask
  task watchdog (`task_wdt: Aborting`) partway through the dump -- a real
  crash marker this time, not session 15's silent no-marker hang. Cause:
  `dump_over_serial()` runs entirely inside one `interval:` callback, and
  ESPHome only feeds its own watchdog once per `loop()` iteration --
  `vTaskDelay()` between chunks yields the CPU but does not feed a task
  explicitly subscribed to ESP-IDF's TWDT. Below ~400ms (the 25-chunk
  test) this never mattered; past roughly a couple seconds of blocking it
  does. This is almost certainly what actually hung the device in session
  15's full-size attempt too, not the unconfirmed "host-side reader can't
  drain fast enough" theory that session logged as the leading
  hypothesis -- that theory is now most likely wrong, or at least not the
  primary cause.
- **Fix: added `esphome::App.feed_wdt()` inside the per-chunk loop** in
  `pcm_capture.h`. This is ESPHome's own public, rate-limited watchdog-feed
  API -- the same one `http_request`'s component calls internally around
  its own long-running operations (`http_request.h`'s `App.feed_wdt()`
  calls) -- not a raw ESP-IDF watchdog bypass or anything resembling
  session 14's dangerous `esp_http_client_perform()` deviation. Safe,
  well-precedented fix.
- **Verified incrementally on real hardware, one flash per step, watching
  full `esphome logs` output for crash markers and post-dump survival
  each time:** 300 chunks after the fix -> clean, no watchdog trip, ~4.8s
  dump, 300/300 chunks reassembled with zero gaps. Then straight to the
  full 1280 chunks (256000 bytes, the exact size that hung session 15) ->
  also clean, ~20s dump, 1280/1280 chunks reassembled with zero gaps,
  device still logging normally 40+s later.
- **Ran the real, committed `tools/collect_serial_dumps.py` against a
  fresh device boot** (not just the ad hoc verification script used for
  the two chunk-count checks above) -- it correctly parsed live
  `esphome logs` output end-to-end and wrote a genuine 256000-byte
  `.raw` file (`1788984616_seq0.raw`) with zero missing chunks reported.
  The full pipeline -- firmware dump -> serial -> host parser -> `.raw`
  file -- is now proven working on real hardware, not just in isolation.
- **Still NOT done, deliberately not attempted this session:** the dump
  still fires exactly once per boot (`already_dumped` static, no
  re-arm/`start()` call after dumping) -- this proves the transport is
  safe at full capture size, but not yet that *repeated* captures are
  safe back-to-back. Re-arming for continuous/rolling capture (the actual
  requirement for collecting a real training dataset across many
  utterances) is the next real step, and should itself be tested
  incrementally (e.g. a bounded N-capture loop, watching for the same
  class of watchdog-starvation or resource-exhaustion issue across
  repeated dumps, before ever going back to an indefinite loop).

## RESUME HERE (2026-09-09, end of session 16)

**Update from session 16: the bounded serial-dump safety test session 15
recommended was run, and it succeeded cleanly -- serial-dump transport is
no longer an open hang risk at small scale, but is not yet proven at full
capture size.**

- **Before touching anything**, checked for other active sessions on the
  shared device: no serial port holders (`lsof`/`ps` clean), and a stale
  `/tmp/simple_receiver.py` from session 15 was still listening on
  `:8765` but idle 17+ minutes with connection-reset errors in its log --
  killed as harmless leftover debris, not an active session.
- **Rewrote `pcm_capture::dump_over_serial()`** (was fully reverted out of
  the committed firmware after session 15's hang) as a deliberately small,
  single-shot test: capped to `DUMP_MAX_CHUNKS = 25` (~5KB / ~20ms of
  audio, not the full ~256KB/1280-chunk capture that hung the device
  last time), guarded by a static `already_dumped` flag so it fires
  exactly once and never re-arms `start()` afterward. Wired into
  `respeaker-lite.yaml`'s existing 200ms poll interval in place of
  `upload_and_restart` (WiFi path untouched in `pcm_capture.h`, just not
  called from the yaml right now).
- **Compiled clean, flashed over USB, and forced a fresh reset
  (`esptool.py --after hard_reset chip_id`) while `esphome logs` was
  already attached**, specifically to catch the full boot sequence
  including the dump (the first flash+attach missed it -- on_boot fires
  before `esphome logs` finishes attaching, a recurring theme in this
  story).
- **Result: `PCMDUMP begin seq=0 total_bytes=5000 total_chunks=25` through
  `PCMDUMP end seq=0` in ~400ms, then the device kept logging
  `mww_diag`/`mww_prob`/`mic_diag` continuously for 30+ more seconds with
  no crash, no watchdog trip, no silence.** Reassembled all 25 chunks
  host-side (ad hoc script, same parsing logic as `tools/
  collect_serial_dumps.py`): zero gaps, exact expected byte count (5000),
  clean base64 decode throughout.
- **Deliberately did not scale up to the full 1280-chunk dump this
  session.** The small dump proves the serial-dump *mechanism itself*
  (chunked ESP_LOGI + base64, single-shot, no re-arm) doesn't hang the
  device, which was the open question after session 15. It does not yet
  prove the *volume* that hung session 15's attempt is safe -- that
  requires a separate test, and this session already did one reflash
  cycle; per session 11's documented router anti-flood throttle from
  repeated reflashing, stacking more reflash cycles in the same session
  was judged not worth the risk for an already-successful checkpoint.
- **Concrete next step, not attempted this session:** raise
  `DUMP_MAX_CHUNKS` incrementally (e.g. a few hundred, then the full 1280)
  across separate sessions/reflashes rather than all at once, confirming
  survival at each step, until a full single 2s capture dumps cleanly.
  Only after a full single dump is proven safe should continuous/
  re-arming operation (the original goal, for actually collecting a
  training dataset) be reconsidered -- and even then, watch for the same
  host-side-reader-can't-drain-fast-enough risk session 15 flagged as
  unconfirmed, now less likely at 25 chunks/dump but still open at 1280.
  `tools/collect_serial_dumps.py` (host-side parser) remains untested
  against live firmware output but its parsing logic was just validated
  ad hoc against this session's real device output, so it should work
  unchanged once given a firmware build that emits the `PCMDUMP` lines
  it expects (in-progress on this branch).

## RESUME HERE (2026-09-09, end of session 15)

**Update from session 15: pivoted to actually collecting training data and
attempting a real training run. Real infrastructure built, but the WiFi
upload path's yield was far too low to be usable, and a second live-hang
was hit and reverted. Net: still no custom model, no on-device detection.
Read this before touching firmware again.**

- **Built the full orchestration/labeling toolchain** (`tools/
  collect_samples.py`, `tools/label_captures.py`) -- generates "hey
  jarvis" TTS across 7 natural macOS voices, plays it near the device,
  and correlates the WiFi-uploaded captures against playback timestamps,
  replicating `MicrophoneSource::process_audio_`'s exact channel-select/
  gain/Q31↔Q25 conversion in Python so the output WAV genuinely matches
  what the wake-word model sees (not an approximation -- verified against
  `esphome/components/microphone/microphone_source.cpp`'s actual source).
- **The WiFi upload path's real yield, measured across a full day: 1
  genuine correlated positive sample.** Not a typo. Out of ~150 played
  utterances (spread across per-utterance and "flood" back-to-back
  collection strategies), only one raw capture's timestamp landed close
  enough to a playback window to correlate. This is a materially worse
  number than session 13's "~40% chunk loss" framing suggested --
  most *capture cycles themselves* never complete successfully, not just
  most *chunks within* a cycle. The pipeline is not currently viable for
  building a training dataset in any practical timeframe.
- **Attempted a fix: swapped the receiver for a non-threaded, non-keep-
  alive one to rule out session 14's tooling change as the cause.** No
  improvement -- still near-100% failure in a live 45s window
  (`Upload 20 chunk 0/1 failed`, heap otherwise healthy at ~121KB, well
  above the circuit-breaker threshold). The low yield is not obviously
  caused by anything this session touched; most likely today's WiFi/
  router conditions (see session 11's own documented router anti-flood
  throttle from repeated reflashing) compounded by many reflash cycles
  across sessions 13-15.
- **Pivoted to a different transport: serial (session 4's already-proven-
  safe chunked-base64-over-`ESP_LOGI` technique), to sidestep WiFi/HTTP
  entirely.** Added `pcm_capture::dump_over_serial()` (200 bytes/chunk,
  base64, ~1280 log lines per 2s sample) and `tools/
  collect_serial_dumps.py` to parse `esphome logs` output and reconstruct
  samples host-side. **This hung the device on first live test** --
  identical symptom to session 14's connection-reuse hang (device stays
  enumerated over USB but produces zero further serial output, not even
  the normal boot banner content on a fresh `esphome logs` attach).
  Recovered via `esptool.py --after hard_reset chip_id` (same recovery as
  session 14). **Reverted `pcm_capture.h` and `respeaker-lite.yaml` to
  the exact session-13 committed state** (`git checkout HEAD --`),
  recompiled, reflashed, and confirmed a clean boot with a real
  successful upload chunk logged (`Upload 0 chunk 12 ok`) -- device is
  back in its known-good, verified-stable configuration.
- **The serial-dump hang was not root-caused.** Plausible causes, none
  confirmed: the USB-Serial/JTAG TX path blocking indefinitely under
  sustained ~1280-lines/2s volume if the host-side reader can't drain
  fast enough (session 4's original serial dump was a one-shot debug
  capture, never run in this continuous, high-volume, indefinitely-
  repeating form); or watchdog starvation from the tight loop despite the
  5ms per-line `vTaskDelay`. **Do not retry the continuous version of
  this as tried here** without first testing a much smaller, bounded
  burst (e.g., one 2s sample, not an indefinite loop) and confirming the
  device survives before scaling up.
- **Net result: two real, working pieces of infrastructure exist now**
  (`collect_samples.py`/`label_captures.py` for WiFi-based collection,
  proven correct in its audio-processing math even though yield is too
  low to be useful; `collect_serial_dumps.py`'s *host-side* parser, which
  is safe and ready whenever a working serial-dump firmware path exists)
  **but neither produced a usable dataset.** Total real, verified-correct
  training data collected today: 1 positive clip. microWakeWord (cloned
  to `/tmp/microwakeword_src`, installed into a dedicated `/tmp/
  mww_train_venv` Python 3.12 venv, imports verified working) was never
  actually run -- there was never enough data to feed it.
- **Concrete recommendation for next steps, not attempted this session:**
  (1) Do not keep reflashing/experimenting live against this one physical
  device in the same session as trying to collect data -- session 11
  already documented that repeated reflashing triggers a real router-side
  anti-flood throttle, and today's very low WiFi yield may partly be a
  symptom of that same pattern compounding across sessions 13-15's many
  flash cycles. (2) If continuing the WiFi path: let the device run
  *completely undisturbed* (no reflashing, no other `esphome logs`
  attaches) for a long unattended stretch with periodic playback, and see
  whether yield improves once the router/WiFi conditions have had time to
  settle. (3) If pursuing serial dump instead: test a single bounded
  capture (not an indefinite loop) in isolation first, and only build up
  to continuous operation once that's confirmed safe. (4) Either way, the
  actual `microwakeword` training environment is ready and waiting in
  `/tmp/mww_train_venv` -- reproducible via `pip install -e
  /tmp/microwakeword_src` if that ephemeral venv doesn't survive to a
  future session.

## RESUME HERE (2026-09-09, end of session 14, superseded above)

**Update from session 14:** attempted the natural next step on upload
reliability -- reuse one `esp_http_client` connection across all 16 chunks
of a sample (via `esp_http_client_perform()`, which ESP-IDF's own docs
confirm supports connection reuse across sequential calls on the same
handle) instead of a fresh TCP connect/teardown per chunk, directly
targeting session 13's TIME_WAIT-style-churn hypothesis. Also added
`firmware/respeaker-lite/tools/receiver.py` (a proper, committed,
HTTP/1.1-keep-alive-capable receiver, replacing the "ephemeral, lives in
/tmp, redo it every session" tooling from before).

**Result: a real, dangerous regression, caught and reverted, not shipped.**
Bypassing ESPHome's `http_request` component to call `esp_http_client_perform()`
directly dropped a protection that component provides internally
(`watchdog::WatchdogManager` + explicit `feed_wdt()` calls around every
HTTP stage) -- first live test produced a *worse* failure mode than
session 13's heap spiral: task-watchdog panics (`task_wdt: Aborting`)
roughly every 30-90 seconds. A first fix (wrapping the `perform()` call in
the same `WatchdogManager` RAII pattern, 16000ms matching
`http_request`'s own derivation) stopped the watchdog panics, but the very
next live test produced something worse still: **the device went
completely silent on serial with no crash, no watchdog trip, and no
further log output at all** -- consistent with a genuine deadlock/hang in
the connection-reuse path, not yet root-caused. Recovered the physical
device via `esptool.py --after hard_reset chip_id` (the device does not
have `run_at_exit` behavior otherwise -- see later story dependencies).

**Reverted `pcm_capture.h` and `respeaker-lite.yaml` to the exact
session-13 committed state (`git checkout HEAD --`)** rather than
continuing to debug a proven-hang-risk approach live against the one
physical device. Recompiled, reflashed, and confirmed a clean, stable boot
with no crash/hang markers over a 30s window. `tools/receiver.py` was kept
(harmless, backward-compatible dev tooling regardless of which upload
approach is used).

**Net result: connection reuse across chunks is a real, still-open idea
for fixing upload reliability, but this session's specific implementation
is unsafe and must not be reused as-is.** Any future attempt needs, at
minimum: watchdog feeding proven correct *before* the first live test (not
after a first crash), and a bounded, provably-terminating retry/backoff
around any reused-connection reconnect attempt -- the hang is most likely
in ESP-IDF's own reconnect-on-a-stale-kept-alive-connection path inside
`esp_http_client_perform()`, given it appeared only after a keep-alive
receiver was introduced and the client began attempting to reuse
connections. Root-causing that hang was not attempted this session (the
device was recovered and reverted instead of used for further live
debugging of an already-demonstrated-dangerous state).

**Current state of the actual training pipeline: unchanged from session
13's end** -- single-attempt-per-chunk via ESPHome's `http_request`
component, bounded abandonment, and the verified heap-watermark circuit
breaker. Safe to run unattended. Upload reliability itself (~40% chunk
loss) remains open.

## RESUME HERE (2026-09-09, end of session 13, superseded above)

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

### Follow-up session 14: connection-reuse attempt for upload reliability — caused a real hang, reverted

**Went after session 13's own next-step (1): reduce upload chunk-failure rate, not just make failures safe. Real regression, caught before being left in a shippable state.**

- **Approach:** bypass ESPHome's `http_request` component/YAML entirely and manage one `esp_http_client_handle_t` directly in `pcm_capture.h`, reused via `esp_http_client_perform()` across every chunk of every sample for the life of the device, per ESP-IDF's own documented support for connection reuse across sequential calls on the same handle. Directly targets session 13's diagnosis (repeated fresh TCP connect/teardown cycles, one per 16KB chunk, most plausibly leaving sockets in TIME_WAIT and starving the device of internal RAM). Also added `firmware/respeaker-lite/tools/receiver.py`, a proper committed receiver with `protocol_version = "HTTP/1.1"` (keep-alive) — the client-side reuse is pointless if the server closes the connection after every request, which Python's `http.server` does by default under HTTP/1.0.
- **First live test: real regression, worse than what it was trying to fix.** Task-watchdog panics (`task_wdt: Aborting`, printing a CPU backtrace) roughly every 30-90 seconds, each followed by a reset. Root cause: ESPHome's `http_request_idf.cpp` wraps every stage of a request (`open`, `write`, `fetch_headers`) in a `watchdog::WatchdogManager` RAII guard plus explicit `feed_wdt()` calls specifically to prevent this; calling `esp_http_client_perform()` directly, bypassing that component, silently dropped all of that protection.
- **Fix attempted:** wrapped the `esp_http_client_perform()` call in the same `esphome::watchdog::WatchdogManager` pattern, with a 16000ms timeout matching `http_request`'s own derivation (`timeout * 3 stages + 1000ms margin`, from `http_request/__init__.py`'s `default_watchdog_timeout`). This did stop the watchdog panics.
- **Second live test: something worse.** The device went **completely silent on serial** — no crash marker, no watchdog trip, no further log lines of any kind for the rest of the observation window (checked with fresh `esphome logs` re-attaches up to 30s later, still nothing). This is consistent with a genuine deadlock/hang somewhere in the reused-connection reconnect path inside `esp_http_client_perform()` (most likely trying to reconnect over a stale/half-dead kept-alive connection and blocking on something the watchdog widening doesn't cover, e.g. a lower-level lock), but this was not root-caused — the device was recovered instead of used for further live debugging of an already-demonstrated-dangerous state.
- **Recovered the physical device** via `esptool.py --port /dev/cu.usbmodem101 --after hard_reset chip_id` (confirmed the device was still enumerated/reachable at the USB level, just not producing application-level serial output; a plain hard reset via the RTS pin was sufficient — no need to hold BOOT or do a full erase).
- **Reverted, did not ship:** `git checkout HEAD -- firmware/respeaker-lite/pcm_capture.h firmware/respeaker-lite/respeaker-lite.yaml`, restoring the exact session-13 committed state byte-for-byte. Recompiled, reflashed, and confirmed a clean boot with zero crash/hang markers over a 30-second observation window. Kept `tools/receiver.py` — it's harmless and backward-compatible with the reverted fresh-connection-per-chunk approach too (HTTP/1.1 keep-alive on the server side doesn't require the client to actually reuse anything).
- **Net result:** connection reuse across chunks remains a real, plausible fix for the underlying reliability problem — the theory itself wasn't disproven, only this session's specific implementation was shown unsafe. **Do not repeat this approach as tried here** (bypassing `http_request`'s wrapper and calling raw `esp_http_client_perform()` in a loop reusing one handle) without first: (a) proving watchdog feeding is correct *before* the first live test, not discovering the gap via a live crash, and (b) understanding and bounding whatever `esp_http_client_perform()` does internally when reconnecting a stale kept-alive connection, since that path is the leading suspect for the hang and was not inspected this session.
- **Current state, unchanged from session 13's end:** `pcm_capture.h` uses ESPHome's `http_request` component, single-attempt-per-chunk, bounded abandonment, and the verified heap-watermark circuit breaker. Device confirmed stable on this exact configuration at the end of this session.

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
