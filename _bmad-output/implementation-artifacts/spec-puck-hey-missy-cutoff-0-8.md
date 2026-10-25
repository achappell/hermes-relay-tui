---
title: 'Puck: raise hey_missy probability_cutoff to 0.8'
type: 'bugfix'
created: '2026-10-25'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Living Room Puck's "Hey Missy" model runs at the manifest default `probability_cutoff` 0.5 and woke about 5–7 times a day on ordinary household conversation and TV (2026-10-22 to 2026-10-24). With working follow-ups, each false wake now produces spoken answers, so Amanda unplugged the Puck.

**Approach:** Owner-approved (Amanda, 2026-10-25): set a per-model `probability_cutoff: 0.8` for `hey_missy` in `firmware/respeaker-lite/respeaker-lite.yaml`. Leave hey_skippy, every `sliding_window_size`, `stop`, VAD and the bridge follow-up policy unchanged. The firmware is built from main, so the only other firmware delta relative to the deployed `3c003ef` is #269's already-approved `pb_longest_underrun_at_ms` telemetry. Document the change; claim no new physical proof.

</frozen-after-approval>

## Implementation Notes

- Changed `firmware/respeaker-lite/respeaker-lite.yaml`: added per-model `probability_cutoff: 0.8` on `hey_missy` only.
- No new test. Under the project's test policy, the proof for this configuration edit is the ESPHome render/build plus the physical smoke test, not a source-pinning test. A source test that was briefly added has been removed again.
- Docs: added a paragraph to `firmware/respeaker-lite/README.md` under Wake Models, and a `CHANGELOG.md` Unreleased bug-fix entry. Neither claims physical proof.
- Base: origin/main `e70f5cb8b807c5f15682575debb8ecfdd18fce13`. Its firmware/ diff relative to the deployed `3c003ef` is #269's telemetry plus this cutoff; #270 and #271 touch no firmware.
- ESPHome 2026.9.1 `config` passes for the Direct and Home builds, and the rendered config shows `probability_cutoff: 0.8` on hey_missy.

## Review Triage Log

- Blind Hunter: the test did not check the manifest defaults it claims to preserve. Verdict: moot. The source-pinning test was removed under the test policy; the ESPHome render is the evidence.
- Blind Hunter: there is no measured acceptance plan or fallback value for 0.8. Verdict: low. Rejected for this change: the value is an owner decision, and physical acceptance is a separate, explicit gate. Deferred.
- Blind Hunter: the 0.8 value is duplicated across files, and the test compared it as a string. Verdict: low. The test has been removed; the duplication in the docs is intentional.
- Blind Hunter: the spec file was left unfinished. Verdict: process. Finalized here.
- Blind Hunter: the docs do not say a reflash is needed. Verdict: false. The CHANGELOG lists Unreleased firmware changes and claims no deployment.
