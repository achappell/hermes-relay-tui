---
title: 'Household Home browser named-origin deployment support'
type: 'feature'
created: '2026-10-09'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The supported Home deployer only accepts a `.ts.net` HTTPS Serve origin. The owner approved the alternate `https://home.chappell-home.dev` URL, without changing the legacy `hermes-home` URL, legacy gateways, R6, or R7.

**Approach:** Stage A adds an explicit named-origin ingress mode, focused tests, and an operator runbook. Preserve the existing `.ts.net` mode and exact single-Origin policy. The alternate ingress uses household-only Tailscale Serve raw TCP443 to Caddy on `127.0.0.1:443`; the dedicated Caddy site uses existing wildcard DNS-01 TLS and denies non-loopback immediate peers on every path before proxying to the loopback appliance. Rollback restores HTTPS Serve to8875 and the saved `.ts.net` unit. Production changes require a published tagged release containing this support and separate Stage B authorization. Stage C adds a portal link only after Stage B verification; current portal work is read-only discovery. No production mutations, tags, PR merges, CI watching, re-pairing, or public/Funnel ingress are authorized in Stage A.

</frozen-after-approval>

## Implementation Notes

- Reuse `scripts/deploy_home_browser.py`: ingress remains an operator-prepared prerequisite, rather than introducing a second Caddy/Serve configuration owner. Keep Home's URL restricted to the existing tailnet contract.
- Add opt-in named ingress validation for the approved exact hostname, live raw-TCP Serve configuration, and the effective Caddy HTTP route. Validation must not print secret-bearing Caddy configuration.
- Compare a rollback target's saved unit against the requested origin/Home/backend before switching links or restarting; never reactivate legacy releases.
- Files: deployment script, focused deployment tests, a dedicated non-secret Caddy example, `docs/ops-web-deployment.md`, and `CHANGELOG.md`. No runtime session or pairing changes.
- Verify repository-local tests; do not exercise the host-mutating deployment command. Report Stage B's precise effects and outstanding live network/browser verification separately.
- Implemented strict SSH/SCP, an exact named-Origin opt-in, live on-host Caddy validation without exporting private configuration, raw TCP Serve validation, foreground Funnel/443-override rejection, and complete saved-unit rollback comparison.
- The Caddy example's native JSON shape was obtained with read-only `caddy adapt` using a synthetic TLS-internal snippet on the existing Ops binary. No Caddy reload/config write, credential access, or production deployment occurred.
- Read-only portal discovery found Homepage on Ops, tracked `homepage/config/services.yaml`, and the existing Agents/`mdi-robot` convention. Direct-LAN HTTPS with the portal Host/SNI returned200; the portal is not itself tailnet-only. Stage C adds only a link after Stage B verification, not unrequested portal hardening.
- Release policy: `.github/workflows/release-please.yml` creates the normal release PR; `.github/workflows/release.yml` packages published tags. The new helper is required in the selected tag. No new tag/version, release bypass, merge, or CI watch is part of this implementation.

## Review Triage Log

- **Medium — fixed:** named ingress inherited the generic backend-port override. The CLI now rejects any named backend other than8875 before SSH. Added a no-host-contact regression.
- **False — rejected:** requiring `AllowFunnel` to be present would reject valid disabled configurations. Tailscale's authoritative [`ServeConfig`](https://github.com/tailscale/tailscale/blob/main/ipn/serve.go) defines `AllowFunnel` as an `omitempty` map: an absent/empty map is the disabled set, not unknown state. Tests cover absence, explicit empty/false mappings, and rejection of malformed or true values.
- **Related boundary fixed:** the same authoritative schema permits foreground Serve configuration with its own Funnel state. Validate that state too, rejecting any active Funnel or foreground443 override rather than trusting only the background route. Added focused regressions.
- No runtime session, pairing, or legacy-gateway code changed. Production network/TLS/idle/pairing/browser acceptance remains the separate authorized Stage B gate; Stage A tests do not close it.

## Verification

- Python3.14 focused deployment/smoke/display-server/Home-admission tests: **154 passed**, six existing WebSocket deprecation warnings.
- Full Python suite: **1822 passed, 3 skipped, 6 warnings** in313.66seconds. Command: `uv run --no-project --python 3.14 --with-requirements requirements-dev.txt pytest -q`.
- Initial universal project dependency resolution failed on the unsupported macOS x86_64/Python3.14 optional onnxruntime combination. Using the existing requirements with `--no-project` resolves for the actual arm64 environment without changing dependencies. An initial combined run's300-second deadline interrupted the full suite; the standalone full suite above completed with a longer deadline.
- No web source changed; no new production build/deploy, Caddy reload, Serve change, pairing, or service restart was exercised. This specification's `done` status covers Stage A code and tests only, not Stage B/C rollout acceptance or any R6/R7 transition.
