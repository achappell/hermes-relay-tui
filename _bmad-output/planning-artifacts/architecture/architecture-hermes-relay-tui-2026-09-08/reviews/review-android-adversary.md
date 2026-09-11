# Reviewer Gate — Android Adversarial Divergence Review

Date: 2026-09-11

## Verdict

PASS. Two independently built native Clients cannot silently change the
ownership, recovery, credential, or capability contract while obeying the
updated architecture decisions.

## Hypothetical independent units

### Unit A — iOS Client

It owns platform lifecycle, permissions, audio, secure profile storage, local
history, presentation, and a typed Hermes session adapter. AD-3, AD-7, AD-8,
and AD-12 prevent it from parsing protocol frames in presentation code,
leaking credentials, replaying uncertain turns, or claiming Android closure.

### Unit B — Android Client

It owns the corresponding Android lifecycle, permissions, audio, secure
profile storage, local history, presentation, and typed session/device
adapters. AD-6, AD-9, and AD-12 keep it independently deployable and prevent it
from importing this repository's Python UI/core assumptions or reducing the
surface to conversation-only behavior.

## Remaining boundary

The production physical-Device administration transport remains a shared
product prerequisite rather than an invented Android or iOS wire protocol.
The story map requires both Clients to implement the capability once that
contract exists; until then, repository-local fakes and unavailable adapters
must remain explicit.
