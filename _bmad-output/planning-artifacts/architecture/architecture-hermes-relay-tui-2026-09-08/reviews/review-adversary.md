# Reviewer Gate — Adversarial Divergence Review

Date: 2026-09-13

## Verdict

PASS after tightening the Home session-bridge contract with AD-22 and the
diagnostics boundary with AD-23.

## Hypothetical independent units

### Unit A — a paired TUI or phone doorway

It presents a Home device credential, claims a Wake Mapping, opens a session,
and consumes the ordinary Hermes JSON/PCM/prompt stream. AD-14, AD-15, AD-16,
AD-17, and AD-22 prevent it from choosing an arbitrary Profile, retaining a
revoked credential, inventing a Hermes dialect, or replaying an uncertain
turn.

### Unit B — a display and Watch adapter

It renders the owning room's snapshot, accepts only current structured actions,
and may watch another session. AD-4, AD-5, AD-17, AD-18, and AD-22 prevent it
from comparing sequence numbers across epochs, receiving raw audio or secret
prompts, controlling the watched session, or treating redacted observation as
a session stream.

### Unit C — a notification or artifact backend

It delivers a category-scoped alert or proposes/applies a file change. AD-17,
AD-18, and AD-21 keep notifications from creating hidden sessions and keep
artifact mutation explicit, revision-checked, and owned by the backend rather
than Home.

### Unit D — a TUI diagnostics and incident-review adapter

It emits automatic telemetry and starts an explicit capture. AD-8, AD-14,
AD-17, and AD-23 keep automatic events content-safe, require Home authorization
for capture, preserve the separate encrypted path, and prevent collector
failure from blocking or replaying a live turn.

## Findings

The earlier version left the endpoint side of the Home bridge loose enough for
two clients to obey the ownership rules while defining incompatible Hermes
event dialects. AD-22 closes that seam: session-bearing endpoints use the
existing Hermes voice-session shapes through an authenticated, versioned
bridge; Watch and notifications use separate redacted events.

No remaining critical or high pair can choose incompatible ownership, session
authority, privacy boundaries, or recovery behavior while obeying the spine.
Exact wire schemas, expiry values, and backend-specific details remain
implementation-slice work and are explicitly deferred rather than silently
left to each client.
