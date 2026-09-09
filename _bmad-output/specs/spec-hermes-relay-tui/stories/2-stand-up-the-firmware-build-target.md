---
title: 'Stand up the Puck firmware build target'
type: 'chore'
created: '2026-09-08'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '78429b6182f657c9a817f7890c75c678ff6d8c56'
context:
  - _bmad-output/specs/spec-hermes-relay-tui/SPEC.md
  - firmware/esp32-s3-touch-lcd-7/platformio.ini
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Nothing in the repo targets the reSpeaker Lite as a build artifact. `firmware/esp32-s3-touch-lcd-7/` is a bespoke ESP-IDF/PlatformIO C + LVGL project — a different framework family from what story 1 committed to for the Puck.

**Approach:** Story 1 chose ESPHome's `micro_wake_word` specifically because Seeed ships a working ESPHome reference firmware for this exact board. `micro_wake_word` is an ESPHome component tied to ESPHome's own YAML-to-C++ build pipeline (which wraps ESP-IDF or Arduino internally) — it is not usable as a standalone ESP-IDF component the way `firmware/esp32-s3-touch-lcd-7` builds LVGL directly. So this story's build target is an ESPHome project, not a `platformio.ini`/`CMakeLists.txt` project matching the touch-LCD firmware's shape. `firmware/esp32-s3-touch-lcd-7` remains useful only as an organizational precedent (a dedicated subdirectory per hardware target, its own board-specific config, a README documenting pinout/specs) — its actual build tooling does not carry over.

Get a minimal ESPHome YAML config for the reSpeaker Lite compiling successfully (`esphome compile`), landing at `firmware/respeaker-lite/`.

**Decision:** `/dev/cu.usbmodem101` is the reSpeaker Lite, confirmed by the human. This story includes flashing the compiled config to that device and confirming it boots — not compile-only.

## Boundaries & Constraints

**Always:** Follow Seeed's own reSpeaker Lite ESPHome reference (identified in story 1: `respeaker/ReSpeaker_Lite` GitHub repo, "optimized for micro wake word" variant) as the starting config rather than writing one from scratch. Keep secrets (WiFi credentials, API keys) out of the committed YAML, matching the existing `-D HERMES_DISPLAY_WS_URI` pattern in `firmware/esp32-s3-touch-lcd-7/platformio.ini` of never committing installation-specific values.

**Never:** No wake-word model integration, no credential/identity logic, no audio-streaming-to-host logic in this story — those are stories 3, 4, and 5. Do not port any LVGL/display code, CMake/PlatformIO build config, or C source from `firmware/esp32-s3-touch-lcd-7` — the two targets sit on incompatible build systems (raw ESP-IDF/CMake/LVGL vs. ESPHome's YAML+codegen) and different peripherals (parallel RGB LCD + GT911 touch + CH422G vs. mic array + XU316 DSP), so no source-level sharing is realistic. What does carry over is convention only: the turn-phase vocabulary (UX-DR7) both surfaces must speak truthfully — the Puck's own status story (story 6) is a much smaller surface than the Display's (UX-DR5: one phase + ack tone, never a transcript) and does not consume `shared/display/`'s reducer, which was built for the Display's richer state model.

</frozen-after-approval>

## Code Map

- `firmware/esp32-s3-touch-lcd-7/` — organizational precedent only (subdirectory-per-target, board-specific config, README with pinout/specs); its ESP-IDF/PlatformIO/CMake/LVGL content does not apply.
- `_bmad-output/specs/spec-hermes-relay-tui/SPEC.md` (Constraints) — carries the `micro_wake_word`/ESPHome decision this story builds on.
- No `esphome` CLI is currently installed in this environment (`pip show esphome` found nothing) — this story's first real task is installing it (Python venv extra, matching this repo's existing pattern of keeping hardware-target tooling out of the base install).

## Tasks & Acceptance

**Execution:**
- [x] `firmware/respeaker-lite/` -- create the directory with a minimal ESPHome YAML config adapted from Seeed's reSpeaker Lite reference (WiFi, API, and board platform sections only — no wake-word model yet) -- establishes the build target
- [x] `firmware/respeaker-lite/README.md` -- document the board (XMOS XU316 + XIAO ESP32-S3), the ESPHome toolchain choice and why (per SPEC.md's story-1 decision), and build/flash commands -- matches `firmware/esp32-s3-touch-lcd-7/README.md`'s precedent
- [x] ESPHome tooling -- install into this repo's existing venv pattern (optional extra, not base dependency) -- keeps hardware tooling out of the TUI install per `AGENTS.md`
- [x] `esphome compile firmware/respeaker-lite/respeaker-lite.yaml` -- run and confirm it succeeds -- proves the build target is real, not just files on disk
- [x] `esphome upload firmware/respeaker-lite/respeaker-lite.yaml --device /dev/cu.usbmodem101` -- flash the compiled config to the confirmed reSpeaker Lite -- proves the target hardware boots this build without a crash loop. Only the no-crash-loop half is verified: the device runs on placeholder WiFi credentials (`secrets.yaml`'s `placeholder-ssid`) and has never actually joined WiFi/the API. Joining real household WiFi/API is not yet verified and requires real credentials.

**Acceptance Criteria:**
- Given the new ESPHome config, when `esphome compile` runs, then it completes without error and produces a firmware binary.
- Given the compiled binary, when flashed to `/dev/cu.usbmodem101`, then the device boots without a crash loop. **Not yet met:** the device coming up on WiFi/API is unverified — flashing so far has only used placeholder WiFi credentials, which the device correctly fails to join; this half of the criterion remains open until real household credentials are supplied and a successful WiFi/API join is observed.

## Implementation Notes

## Verification

**Commands:**
- `esphome compile firmware/respeaker-lite/respeaker-lite.yaml` -- expected: build succeeds, binary produced
- `esphome upload firmware/respeaker-lite/respeaker-lite.yaml --device /dev/cu.usbmodem101` -- expected: flash succeeds, device boots

**Manual checks (if no CLI):**
- After flashing, the device should be observable on the network (ESPHome API/mDNS) or via `esphome logs` over the same serial port, confirming it booted rather than crash-looping.

## Review Triage Log

- **medium, patch** — the "device boots and comes up on WiFi/API" acceptance criterion and its execution tasks are checked `[x]` complete, but only the no-crash-loop half was actually verified; the device runs on placeholder WiFi credentials and never joins WiFi or the API. Confirmed independently by two review layers and by the implementation report itself. Fix: the story's own bookkeeping should say so, not just the README.
- **medium, patch** — `respeaker-lite.yaml` uses the generic `esp32-s3-devkitc-1` board id instead of ESPHome's dedicated `seeed_xiao_esp32s3` entry for this exact MCU module (confirmed via ESPHome/Seeed's own documentation: `board: seeed_xiao_esp32s3` is the correct id). No GPIO-specific config exists yet so nothing is currently broken, but this is the foundation stories 3–6 build GPIO config on top of — worth correcting now rather than after pin-mapping bugs appear later.
- **low, patch** — the story's own `## Verification` section still has the planning-time placeholder `<config>.yaml` instead of the real filename `respeaker-lite.yaml` used everywhere else (README, YAML header).
- **false** — "`esphome>=2025.9.0` has no upper bound, risking a future breaking release." Disproof: checked `pyproject.toml`'s existing `voice`/`wake` extras (`sounddevice>=0.4.6`, `numpy>=2.0`, `openwakeword>=0.6`, etc.) — none pin an upper bound either. The new extra matches established house style, not a deviation from it.
- **low, reject** — "`esp32.framework.version: recommended` should be pinned to an exact IDF version for reproducibility." Real concern in isolation, but pinning it alone while `esphome` itself stays unbounded (matching house style, see above) wouldn't actually fix reproducibility — a future ESPHome upgrade could still shift the toolchain regardless. Not worth a partial fix that doesn't close the actual gap.
- **low, reject** — "AP fallback password minimum length (8 chars for WPA2) isn't documented." The actual `secrets.yaml` value in use (`respeaker-fallback`, 19 chars) and the `.example` placeholder are both already well over the minimum; documentation-only nicety for a constraint nothing currently violates.
- **low, reject** — "the ESPHome-generated `.gitignore` boilerplate wasn't trimmed to repo-specific wording." Matches ESPHome's own default output; `firmware/esp32-s3-touch-lcd-7`'s terser `.gitignore` isn't an established convention the new file was supposed to follow.
- **defer** — "no forward-note on PSRAM configuration for the DSP/audio work landing in stories 3–5." Real and worth remembering, but explicitly out of this story's scope per its own Never boundary (no audio/DSP work yet); belongs to story 3's spec, not a fix to this one.
- **low, reject** — "the `-D HERMES_DISPLAY_WS_URI`-pattern justification is copy-pasted verbatim across README, YAML header, and story Boundaries." Real repetition, but consolidating it cleanly touches three files for a purely stylistic gain — more than the smallest fix, and no one is likely to hit inconsistency from it in practice.
- **false** — "`firmware/respeaker-lite/` should be registered in an AGENTS.md firmware-targets index." Checked `AGENTS.md`: its `firmware/esp32-s3-touch-lcd-7` references are scoped to describing the shared LVGL display engine specifically (a different architecture the reSpeaker Lite firmware explicitly does not participate in, per this story's own Boundaries) — there is no generic firmware-target manifest to register into.
- **false** — "the README's claimed build-output path (`firmware.factory.bin`/`firmware.ota.bin`) is unverified in the diff." Checked directly: both files exist exactly as claimed at `firmware/respeaker-lite/.esphome/build/respeaker-lite/build/`.
