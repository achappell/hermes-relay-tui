# 2-E-5 native Choose/Explore — delivery reconciliation

Date: 2026-09-22. Status: **review**. Software is merged; native interaction and physical acceptance remain outstanding. Hardware assembly is pending, as reported by Amanda. This record reconciles delivery evidence; it does not claim a new renderer run or physical test.

## Verified evidence

- [PR #196](https://github.com/achappell/hermes-relay-tui/pull/196) merged on 2026-09-20 as `33ef14f8f374a473d9239a4e0a9c6c5ce0b509ef`. Its changes include display schemas/reducer, Home prompt correlation and validation, LVGL choice rendering and transport, regression tests, and `scripts/fake_home_bridge.py`.
- GitHub checks for PR #196 pass, including [Test and package](https://github.com/achappell/hermes-relay-tui/actions/runs/35351831400/job/105621556614). The PR reports 235 focused tests passed and 1,422 full-suite tests passed with two skips.
- The PR reports a full real `HomeBrowserSession` client round trip over TLS to the fake Home bridge. This proves the exercised socket/client path against a stub, not a real Home authorization service or a native tap.
- Later [1-E-1 validation](validation-1-e-1-authorized-voice-capture.md) records native simulator and LVGL-enabled S3 builds on the descendant code. Those builds provide compilation evidence, not interactive Choose/Explore acceptance.

## Outstanding acceptance

- Exercise the native renderer with the fake Home bridge: bounded option visibility, separate supported Choose/Explore controls, a tap producing one correlated response, pending-control disabling, and authoritative replacement/resolution. Record renderer evidence separately from the stub's semantics.
- Verify actual Home behavior for Explore without resolution, Choose, stale/replaced identity rejection, capability gating, and no replay after uncertain delivery. A fake bridge cannot establish Home's authority semantics.
- Once assembled, verify physical touch interaction, readability/scrolling and the same action lifecycle on the selected S3 installation. No physical acceptance has been performed.

## Scheduling

Keep `2-E-5` in review, not in progress or done. Keep `1-E-1` physical acceptance pending as well. Hardware availability prevents physical verification but does not block selecting an independent software slice. Preserve the original story identity and acceptance criteria; do not infer closure from the PR body's “Closes 2-E-5” wording.
