---
title: 'Choose the on-device wake-word engine for the Puck'
type: 'chore'
created: '2026-09-08'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '78429b6182f657c9a817f7890c75c678ff6d8c56'
context:
  - _bmad-output/specs/spec-hermes-relay-tui/SPEC.md
  - _bmad-output/planning-artifacts/architecture/architecture-hermes-relay-tui-2026-09-08/ARCHITECTURE-SPINE.md
  - docs/superpowers/specs/2026-09-01-home-02-wake-word-design.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** SPEC.md carries an open question: which embedded wake-word engine the Puck (Seeed reSpeaker Lite, XMOS XU316 + XIAO ESP32-S3) uses on-device, since the host-side `wakewords/*.onnx` (openWakeWord-style) assets target a Python/ONNX runtime and do not run on a microcontroller.

**Approach:** Adopt Seeed's own reference path — ESPHome's `micro_wake_word` component — rather than Espressif ESP-SR or a from-scratch port. Seeed publishes a reSpeaker Lite firmware variant explicitly built and tuned for `micro_wake_word` on this exact board, which de-risks story 2 (firmware bring-up) against a known-working combination instead of a first-of-its-kind integration. ESPHome's Assist Satellite architecture also already solves WiFi provisioning and a wake-then-stream-to-host audio pipeline, which stories 4 and 5 would otherwise have to build from nothing.

This choice also directly serves FR7 (multiple Wake Mappings per Device, each mapped to one Profile): `micro_wake_word` v2 runs several independently-trained models concurrently on one device and reports which model fired, rather than supporting only one active phrase at a time. Training goes through `OHF-Voice/micro-wake-word` (TensorFlow, synthetic-sample generation, the same conceptual approach as the existing `hey_hermes.onnx` pipeline); the project's own docs describe training a model that performs well as "still very difficult," so per-phrase training effort — not a platform limit — is the real cost of adding each Wake Mapping.

Per-phrase training pipeline, concretely: Piper TTS synthesizes ~30,000 positive samples plus confusable near-misses from an IPA pronunciation (no real recordings needed, same trick as `hey_hermes.onnx`); samples are augmented for pitch/noise/room variability; audio converts to 40-feature spectrograms via the `micro_speech` preprocessor; the model trains non-streaming then converts to streaming form; weights are selected in two passes (minimize false-accepts on background noise, then maximize accuracy — the same ordering HOME-05 already found for confirmation-frame tuning); the result is quantized to a TFLite-Micro model plus an ESPHome model JSON. `alfiedennen/microwakeword-trainer` wraps this as a self-driving Colab notebook, no local GPU required, but budget hours-with-iteration per phrase, not a single run — "trains a good model" and "runs the pipeline once" are not the same claim.

Explicitly ruled out: sherpa-onnx (`wakewords/sherpa/`), the open-vocabulary engine used for flexible host-side wake words previously. Its KWS models run into the millions of parameters and target embedded Linux/mobile-class hardware (Raspberry Pi, Android, RISC-V Linux boards) via a full streaming ASR transducer — not a bare-metal microcontroller with no OS or MMU like the XIAO ESP32-S3. It does not run on-device on the Puck; its "type any phrase, no training" convenience does not carry over.

Consequence to record plainly: the existing `hey_hermes.onnx` model does not carry over as-is. `micro_wake_word` uses its own model format; keeping the "hey hermes" phrase means retraining it for that pipeline, not reusing the current file. This is the same class of effort the host-side wake-word design doc already describes for changing the phrase (a synthetic-sample training pass, not a research project) — just against a different toolchain.

## Boundaries & Constraints

**Always:** Record the decision as a resolved constraint in `_bmad-output/specs/spec-hermes-relay-tui/SPEC.md`, replacing the open question it answers. Keep the existing host-side wake-word stack (`wake.py`, `wakewords/*.onnx`) untouched — this story does not touch HOME-05's appliance path.

**Never:** No firmware code in this story. Do not commit to the Arduino vs. ESP-IDF build framework choice beyond noting what Seeed's `micro_wake_word` firmware variant targets today — that belongs to story 2. Do not retrain or fetch a wake-word model in this story.

</frozen-after-approval>

## Code Map

- `_bmad-output/specs/spec-hermes-relay-tui/SPEC.md` — carries the open question this story resolves (Constraints section) and the constraint it becomes.
- `wakewords/*.onnx`, `wake.py` — the host-side openWakeWord stack this decision explicitly does not touch or replace.
- `docs/superpowers/specs/2026-09-01-home-02-wake-word-design.md` — prior art: confirmation frames, fire cooldown, silent-stream detection, and the "changing the phrase later" section this story's consequence note mirrors.
- `firmware/esp32-s3-touch-lcd-7/` — structural precedent only for story 2, not this one.

## Tasks & Acceptance

**Execution:**
- [x] `_bmad-output/specs/spec-hermes-relay-tui/SPEC.md` -- replace the "which on-device wake-word engine" open question with a resolved constraint naming `micro_wake_word` and the `hey_hermes.onnx` non-portability consequence -- closes story 1's actual open question
- [x] `_bmad-output/specs/spec-hermes-relay-tui/.memlog.md` -- append the decision and rationale -- keeps the append-only record consistent with how the rest of this spec was derived

**Acceptance Criteria:**
- Given SPEC.md's prior open question on the wake-word engine, when this story completes, then that question is gone and replaced by a constraint naming the chosen engine and its consequence for the existing ONNX assets.
- Given the GitHub board item PUCK-01.1, when this story completes, then its Workflow can move from `Ready` to `Done` without inventing new scope beyond the decision.

## Implementation Notes

## Verification

**Manual checks (if no CLI):**
- `_bmad-output/specs/spec-hermes-relay-tui/SPEC.md` no longer lists the wake-word-engine open question, and instead states the `micro_wake_word` decision under Constraints.

## Review Triage Log

- **low, patch** — SPEC.md's new constraint bullet omits the sherpa-onnx exclusion the memlog records as its own decision entry; SPEC.md is the canonical kernel a future reader consults, so the exclusion rationale should be reachable there, not only in append-only memlog history. Smallest fix: one added clause.
- **false** — "diff renames files instead of diffing the same path." Disproof: the real files (`SPEC.md`, `.memlog.md`, `stories/1-choose-the-on-device-wake-word-engine.md`) were edited in place under their original names; the apparent rename is an artifact of the before/after reconstruction method used only to produce a reviewable diff for untracked files, not a property of the actual change.
- **false** — "`review_loop_iteration` should have incremented." Disproof: `spec-template.md` defines it as "incremented by step-04 before each review loopback" — this is the first review pass and (pending this triage) has not triggered a loopback, so `0` is correct, not stale.
- **false** — "checkboxes need a completion timestamp / memlog line back-reference." Disproof: no such convention exists in `spec-template.md`'s Tasks & Acceptance format (`- [ ]/[x] FILE -- ACTION -- RATIONALE`) or anywhere else in this spec; this proposes a new convention, not a defect.
- **false** — "constraint bullet is a long compound sentence, less scannable than neighbors." Disproof: the immediately preceding constraint bullet (the on-device-wake-detection decision) is an equally long compound sentence; this matches established local style.
- **false** — "`baseline_commit` should also appear on SPEC.md/memlog for provenance parity." Disproof: `baseline_commit` is a field of the bmad-build story-spec template only; SPEC.md and `.memlog.md` follow the separate bmad-spec kernel/memlog format, which has no such field. Different document types, different schemas, by design.
- **false** — "memlog pass-2 entry references FR7 / 'Never boundary' without restating them, unverifiable in isolation." Disproof: matches the memlog's own established, intentional shorthand convention used across its prior 60+ entries; memlog is explicitly not a standalone deliverable.
- **false** — "replacement constraint addresses the runtime incompatibility only indirectly, dropping the original question's 'Python/ONNX host runtime' framing." Disproof: the constraint states the more precise, technically correct reason (incompatible model format requiring retraining) rather than the open question's looser framing — a precision improvement, not an omission.
