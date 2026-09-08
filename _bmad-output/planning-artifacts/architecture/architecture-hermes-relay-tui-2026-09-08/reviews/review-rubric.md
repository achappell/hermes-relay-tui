# Reviewer Gate — Rubric

Date: 2026-09-08

## Verdict

PASS after the sequence-epoch clarification applied to AD-4.

## Coverage

- The spine names a coherent paradigm and maps it to the actual Python, C, TUI, appliance, firmware, and Web/WASM boundaries.
- AD-1 through AD-10 cover dependency direction, state ownership, protocol authority, shared data shapes, propagation scope, process topology, recovery, secrets, dependency isolation, and validation.
- Every AD has Binds, Prevents, and an enforceable Rule.
- The operational envelope is explicit: local fake-based validation, separate entry points, loopback-by-default display serving, runtime configuration, bounded reconnect, and fresh initiation after recovery.
- The PRD capability map distinguishes repository-owned capabilities from device, calendar, provisioning, and iOS work outside this spine.
- Deferred items include the dimensions that the current repository cannot honestly decide: device identity, LAN production security, arbitration, media-server boundaries, calendar providers, iOS coordination, hardware pinning, and centralization.

## Findings

No critical or high findings remain.

The only material ambiguity found during review was whether display sequence numbers survive reconnects. AD-4 now defines a channel epoch: the first valid snapshot after attach/reconnect establishes the baseline, strict increase applies within the epoch, and numbers are not compared across epochs.

The TUI was also explicitly distinguished from display-capable front ends so the spine does not claim that the current terminal transcript already consumes the appliance display contract.

## Evidence

- Architecture lint: zero findings.
- Python suite: 833 passed.
- Web suite: 126 passed.
- Svelte diagnostics: zero errors and zero warnings.
- Vite production build: passed.
