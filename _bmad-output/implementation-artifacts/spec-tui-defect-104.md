---
id: TUI-DEFECT-104
status: done
product_epic: 1
created: 2026-09-23
---

# TUI-DEFECT-104 — Resolve truncated microphone capture

## Approved scope

Reproduce GitHub #104 on the supported target, apply a fix or document supersession with evidence.

## Acceptance

- Deliver the owner-specific behavior above using unmodified Standard Hermes and the approved [delivery contract](course-correction-2026-09-23.md).
- Preserve existing story evidence and supported adapters; no automatic mode switch or replay of an uncertain turn.
- Record applicable setup, capability limits, privacy, failure and recovery behavior against the actual supported baseline.
- Record implementation, merge and physical/live acceptance separately; do not declare an unexercised gate complete.

## Dependencies

No additional story prerequisite; refine the implementation contract before development.

## Readiness

Candidate physical acceptance is recorded below against the supported Home path. The shared T-5 lock correction has focused, full-suite and independent-review evidence. This report remains in review until delivery; it requires no separate protocol or recorder change based on the observed candidate results.

## Candidate acceptance — 2026-09-27

Amanda exercised a sustained wake-captured utterance on the corrected macOS Home/Sherpa candidate and confirmed its complete distinctive ending, “purple umbrella beside the kitchen window,” appeared without truncation. This directly exercises the report's missing-tail reproduction on the supported path. No separate recorder/VAD correction is claimed; retain this as current supersession evidence, with candidate merge/release separate. See [T-5 validation](validation-1-t-5-nonblocking-wake-callback.md).

Candidate full regression suite passed 1670 tests with one ESPHome environment skip. Local status is review pending delivery; the original GitHub issue was not closed.

## Accepted closure — 2026-09-27

PR #216 merged as `457009b`, delivering the reviewed correction and acceptance evidence to main. Amanda confirmed that a tagged or published release is not a story-closure requirement. The completed physical checks and merged-tree regression result (1686 passed, 1 skipped, 6 warnings) satisfy this acceptance record; status is done. Earlier references to pending merge/release describe the pre-merge checkpoint and do not impose a release gate. Physical evidence is scoped to macOS Home mode with Sherpa; no additional Standard-mode physical run is claimed.
