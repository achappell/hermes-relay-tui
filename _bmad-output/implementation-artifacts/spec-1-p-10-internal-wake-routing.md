---
title: 'Keep internal wake models out of public capture routing'
type: 'bugfix'
created: '2026-10-18'
status: 'in-review'
route: 'dispatch'
review_loop_iteration: 0
story_key: '1-p-10-keep-internal-wake-models-out-of-ordinary-capture-routing'
baseline_commit: '95809e14c83f0e343a4d730d96405b39fe844e7e'
context: []
---

<frozen-after-approval reason="existing P-10 acceptance; routine engineering checkpoint delegated, not new human spec approval">

## Intent

**Problem:** The engine hides internal models from public entity listing, but drops their role when queueing detections and invokes the public wake callback for every detected model. The active internal `stop` model can therefore enter wake capture/admission as though it were a public Profile phrase.

**Approach:** Carry the model's declared `internal_only` provenance with the queued event and enforce a fail-closed dispatch boundary before the public trigger. Share the same declared-role guard with entity listing; unspecified event provenance remains internal. Internal detection is logged as suppressed internal control without PCM/transcript content. Public detection keeps existing VAD and stop-after-detection behavior.

## Boundaries & Constraints

**Always:** Respect every configured internal model, regardless of name or list order; `internal: true` is the existing declaration authority, not a new hardcoded name list. Preserve that role across task-to-loop queue copying. Public listing and callback use the same role predicate. Keep the current `stop` model internal and preserve public wake capture, acknowledgement, VAD/upload, Home admission and Profile selection behind the public callback. No per-event allocation or model lookup.

**Never:** Redefine P-3 exact spoken-stop transcription or introduce an internal stop action, remote turn, Profile selection, fixed-confidence/proximity evidence, schema/model-threshold policy, raw PCM opt-in, deployment, real audio or hardware access. Unchanged schema already generates the constructor role from the boolean `internal` declaration; prove that with actual configuration generation rather than wording/source pins.

## I/O & Edge-Case Matrix

| Scenario | Input/state | Expected behavior | Error handling |
|---|---|---|---|
| Internal stop | detected internal event | diagnostic internal-control suppression; no public callback/capture/upload/admission/Profile | detector not stopped by public stop-after-detection |
| Other internal model | arbitrary configured model name/internal role | same exclusion from public entity/capture routing | independent of name/list order |
| Public model | detected, VAD allowed, explicit public provenance | existing callback runs once | existing authorized path unchanged |
| VAD-blocked public | detected but VAD blocked | no public callback | existing VAD diagnostic retained |
| Unspecified/invalid event | default provenance, absent wake word, or not detected | fail closed; no callback | no invented identity |
| Configuration | internal true/false declarations | real generated model metadata retains exact roles | public listing cannot override the role guard |

</frozen-after-approval>

## Code Map

- `firmware/respeaker-lite/components/micro_wake_word/streaming_model.h`: move the lightweight DetectionEvent into a production `detection_event.h` independent of TensorFlow headers, with default-internal role and initialized fields.
- `.../micro_wake_word.cpp`: stamp model role in `process_probabilities_` before queue send; `get_wake_words` shares role predicate; `loop` routes internal detection to bounded content-safe diagnostics, only public dispatch may stop-after-detection.
- `.../detection_event.h`: production dispatch guard used directly by engine and native regression/smoke, without copied routing implementation.
- `firmware/respeaker-lite/respeaker-lite.yaml`: existing `stop: internal: true` and public callback remain unchanged; no second allowlist or stop semantics.
- `tests/test_puck_firmware.py`: reuse its native capture/identity/network stubs. New `tests/test_respeaker_wake_routing.py` drives production dispatch into real `pcm_capture.h` preparation and synthetic upload; schema checks run real ESPHome code generation for actual model roles. No live endpoint.

## Tasks & Acceptance

**Execution:**
- [x] Carry initialized, fail-closed internal provenance from the model through the detection event; guard public trigger/entity listing consistently and distinguish internal-control diagnostics.
- [x] Production-header native tests for every matrix row, with actual capture/upload consequences; real ESPHome configuration role checks including additional arbitrary internal model.
- [x] Independent spec and code reviews; focused regressions, separate native changed-path smoke, default/Home actual firmware compiles, full suite under supported bash, serialized using installed venv tools.
- [x] After smoke update README/changelog, spec/validation, local tracking/coverage/deferred gates; prepare normal non-draft PR from main, then report verified publication SHA identity separately.

**Acceptance Criteria:**
- Given internal stop detection, when event dispatch executes, then capture/upload/Hermes turn/Profile selection cannot run through the public callback.
- Given a public model, when the same dispatch boundary executes, then existing authorized capture behavior is unchanged.
- Given internal detection diagnostics, when logged, then they are content-safe and explicitly distinguish internal control from public routing.
- Given a changed configured internal model list, when firmware validation/code generation runs, then role metadata remains internal and cannot bypass shared public entity/dispatch guards.
- Given focused checks for public/internal routing, when compiled firmware/configuration checks run, then both outcomes are verified without changing exact spoken-stop transcription ownership.

## Implementation Notes

No remaining product intent gap, irreversible action or evidence-policy change. Baseline is fresh origin/main; this story is independent of the P-8/P-9 microphone stack and its PR will not contain those commits. Only tui-p7-pcm-diagnostics owns hardware; raw PCM diagnostics remain off. Native tests cannot establish physical acoustic recognition and do not claim it.

Independent verification review found that initial tests manually marked the public event and could miss lost producer provenance. Accepted medium/patch: `make_model_detection` now owns the production model-to-event role copy, used by the inference producer and the native regression. Tests execute that handoff for public/internal model fixtures, byte-copy the trivially copyable event as FreeRTOS does, then exercise real capture/upload. Deleting the role assignment was observed failing `!event.internal_only`; the assignment was restored. Reviewer confirmed the gap closed. An earlier native fixture used `allowed:` instead of the existing `admitted:` reply contract; corrected the fixture, not production admission policy.

## Spec Change Log

## Review Triage Log

- Independent specification review: no findings.
- Blind-hunter code review: no actionable finding (reviewer declined to fabricate five issues); edge-case layer returned `[]`.
- Verification gap (producer role handoff), medium/patch: accepted and fixed as described above; native mutation failed as expected, restored production code passed, and independent reviewer confirmed no remaining actionable gap.

## Verification

Observed: final focused firmware/routing 22 passed; production model-provenance mutation failed as expected and was restored; separate production handoff/routing/capture smoke passed 200 internal events and one public VAD-close/4000-byte upload. Final actual default/Home firmware compiles both passed. Full suite under supported bash: 2198 passed, 2 skipped, 6 warnings in 345.44 s, including successful ESPHome config generation with no timeout flake. See [validation](validation-1-p-10-internal-wake-routing.md) for commands, exact build identity/counts/review fixes and open physical gate. Software is done-with-deferred-gate; spec/tracker remain in-review/review.
