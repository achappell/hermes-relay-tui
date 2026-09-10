---
title: 'Serve the iPad display over HTTPS for Safari speech'
type: 'feature'
created: '2026-09-09'
status: 'done'
route: 'oneshot'
review_loop_iteration: 1
baseline_commit: '146f90840704e36a0e9c106a2d1ffb20158e407b'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/docs/testing/home-09-appliance-loop.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The iPad Safari display can load from the LAN, but the current plain-HTTP origin does not expose the browser speech-recognition capability needed by hands-free voice. The page therefore reports microphone unavailability before Safari can present a useful per-site permission flow.

**Approach:** Add an opt-in TLS mode to the existing display server so one HTTPS origin serves both the static page and its same-origin secure WebSocket. The appliance accepts explicit certificate and private-key paths, prints an `https://` URL, derives `wss://` for the browser channel, and keeps the current HTTP loopback behavior unchanged.

## Boundaries & Constraints

**Always:** Certificate and key paths are supplied at runtime and loaded by the local server; private keys stay on the Mac and outside Git. The HTTPS origin check must match the actual scheme, host, and port. Startup failures must be concise and actionable. The browser still receives only display snapshots, normalized text turns, and streamed audio; no bearer token or raw relay audio crosses into the page.

**Never:** Do not make TLS mandatory for existing loopback/demo users. Do not generate or commit certificates, keys, trust profiles, or secrets. Do not weaken origin validation, add a second server, proxy Hermes through the browser, or claim that iPad speech works until the certificate is trusted and the physical Safari check passes.

## Implementation Notes

- Use Python `ssl.SSLContext` passed as `ssl=` to the existing `websockets.asyncio.server.serve` call.
- Extend `DisplayServerInfo` with scheme-aware HTTP/WebSocket URLs and accept the matching HTTP or HTTPS origin only.
- Require certificate and key options together at the appliance CLI boundary; preserve plain HTTP when neither is supplied.
- Document local CA/IP-SAN certificate creation, iPad CA trust, HTTPS launch, and cleanup without placing certificate material in the repository.

</frozen-after-approval>

## Implementation Notes

- `DisplayServer` accepts an optional `ssl.SSLContext` and passes it to the
  existing WebSocket/HTTP listener, so the static page and `/state` channel
  remain one same-origin server.
- `DisplayServerInfo` preserves its existing properties while returning
  `https://` and `wss://` URLs in secure mode. Origin validation switches to
  HTTPS only when TLS is active and continues to require the bound host and
  port.
- The appliance exposes paired `--display-tls-cert` and
  `--display-tls-key` options. TLS is rejected for the physical display path,
  which remains plain WebSocket; malformed or incomplete TLS configuration
  fails before the appliance starts listening.
- Browser turns keep text deltas that arrive after `audio_start` in the
  `speaking` display state. This preserves the reducer's legal transition
  sequence while captions continue streaming during playback.
- The certificate recipe in the HOME-09 procedure uses a local CA and an
  IP-address SAN. Generated keys and trust material remain under the user's
  home directory, outside Git. Only the public CA certificate is transferred
  to the iPad.

## Review Triage Log

- The first blind-hunter pass inspected the primary checkout instead of this
  feature worktree and therefore had no feature content to review.
- A redirected blind-hunter pass was started against this worktree but did not
  return after two two-minute waits; it was closed without findings. No review
  result was treated as approval.
- Local triage inspected the complete diff, the server's HTTP and WebSocket
  paths, the appliance lifecycle, generated certificate SAN and permissions,
  and the live HTTPS harness. One documentation ordering defect was found and
  fixed: certificate creation now precedes the launch command. TLS loading was
  also hardened to wrap `ValueError` from invalid certificate/key material.
- The physical playback smoke exposed a second actionable defect: a late
  browser text delta was published as `thinking` after `speaking` began. Fix
  `938e639` keeps that delta in `speaking`; the regression test now covers the
  exact sequence.
- No unresolved actionable findings remain.

## Verification

- Python: `venv/bin/pytest` — 891 passed, one upstream deprecation warning.
- Focused TLS/server tests — 20 passed, one upstream deprecation warning.
- Focused late-caption regression — passed.
- Browser: `npm test` — 149 passed; `npm run check` — zero errors and zero
  warnings; `npm run build` succeeded with no generated bundle diff.
- Live harness: the HTTPS page returned 200, the secure state channel returned
  the initial `idle` snapshot, a plain-HTTP WebSocket origin was rejected, and
  a real browser turn delivered PCM chunks through `thinking` → `speaking` →
  `idle` without a protocol error.
- Physical iPad Safari trust, microphone permission, and Guided Access smoke
  remain the explicit Verify gate; this implementation does not claim those
  hardware/browser results yet.
