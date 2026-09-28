---
id: TUI-DEFECT-102
status: in-review
product_epic: 1
created: 2026-09-23
---

# TUI-DEFECT-102 — Resolve first-turn wake failure

## Approved scope

Reproduce GitHub #102 on the supported target, apply a fix or document supersession with evidence. Do not close solely because related wake code merged.

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

The original report concerns capture failing after the first spoken response. During this acceptance run, a real listener/UI lock cycle first blocked wake submission entirely; T-5's correction removes it. Amanda then confirmed the candidate captured and spoke the first turn, followed by a complete second request and spoken response without another wake phrase. This is physical evidence on macOS in Home mode with Sherpa, not closure inferred from related unit tests. See [T-5 validation](validation-1-t-5-nonblocking-wake-callback.md). Candidate delivery and final regression verification are pending; retain the original issue identity.

Candidate full regression suite passed 1670 tests with one ESPHome environment skip. Local status is review pending delivery; the original GitHub issue was not closed.
