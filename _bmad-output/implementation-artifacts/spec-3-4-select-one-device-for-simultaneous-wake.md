---
title: 'Select one Device for a simultaneous wake (shared contract)'
type: feature
created: '2026-09-12'
status: 'in_progress'
route: 'architecture'
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/implementation-artifacts/surface-coverage-matrix.md'
  - '{project-root}/_bmad-output/specs/spec-hermes-relay-tui/SPEC.md'

<frozen-after-approval reason="human-owned shared contract recorded during the 2026-09-12 architecture walkthrough">

## Intent

Multiple wake-capable Devices may hear the same household wake trigger. The
house needs one canonical configuration and one arbitration authority so that
one wake produces at most one acknowledgement, capture, Hermes turn, and
response.

The initial architecture is one local Home service with two internal roles:

- a durable canonical household configuration store;
- a low-latency wake-arbitration engine.

iOS and Android administer the configuration. ESP32 Touch, web Hands-Free
Home, and iPad Hands-Free Home may all act as wake claimants. The Home service
owns the decision; no client surface becomes a second live arbiter.

## Approved contract decisions

- A `WakeClaim` contains a unique `claim_id`, an authenticated `device_id`, an
  opaque canonical wake-trigger ID, observation metadata, and acoustic
  proximity evidence. It contains no Profile ID, wake phrase, prompt,
  transcript, or audio. Credentials are established out of band.
- The first valid claim opens a 250 ms arbitration window. The Home service
  compares eligible claims using acoustic proximity evidence; configured
  Device priority resolves an effective tie. Each claim receives a grant or
  denial tied to its own claim ID.
- Arbitration uses the Home service's monotonic receive clock, never an
  untrusted Device wall-clock timestamp. Wi-Fi RSSI is not physical
  proximity.
- Priority is a positive integer on a Device within a Room; `1` is highest.
  Missing, invalid, or duplicate priorities make the configuration invalid.
- A denied, missing, expired, revoked, unavailable, malformed, or late claim
  fails closed. If the winner fails before upload, no loser is promoted; a new
  wake is required.
- The canonical mapping ID identifies the household wake trigger. Hermes
  Profile assignment remains per Device, so the winning Device resolves its
  own configured Profile after arbitration.
- The Home service owns canonical mappings, Rooms, Device capabilities,
  priorities, and monotonic configuration revisions. Clients publish a full
  household snapshot with an expected revision; stale writes are rejected and
  a valid snapshot becomes active atomically.
- The first transport is versioned JSON/HTTP for reads, atomic writes, and
  claim request/response. Push notifications may follow; they are not the
  source of truth.

## Acceptance criteria

- Given a household configuration, when a mobile client reads or publishes it,
  then the snapshot includes the server revision, canonical wake-trigger IDs,
  per-Device Profile assignments, Rooms, and unique positive per-Room
  priorities.
- Given a stale expected revision, when a client publishes, then the Home
  service rejects the write and the client retains the verified newer state.
- Given multiple eligible Devices claim the same canonical mapping within the
  arbitration window, when the window closes, then exactly one claimant is
  granted ownership and all other claims are denied.
- Given a claimant lacks a valid mapping, credential, availability, or Profile,
  when arbitration evaluates it, then it is excluded before acknowledgement
  or capture.
- Given a denied or failed winner, when the event settles, then no Device
  submits audio or a Hermes turn unless it received the grant; a failed winner
  does not promote a loser.
- Given iOS, Android, ESP32 Touch, or web Hands-Free Home detects a wake,
  when it submits a claim, then it uses the same claim/grant contract and the
  Home service remains the sole arbitration authority.

## Surface ownership

- `hermes-relay-ios`: mobile configuration UI, local projection, secure
  credentials, and optional iOS Hands-Free Home claimant.
- `hermes-relay-android`: the corresponding Android administration surface.
- `hermes-relay-tui`: the local Home service/bridge contract and runtime
  arbitration implementation, plus TUI and household-surface integration.
- ESP32 Touch and web/iPad Hands-Free Home: wake detection, claim submission,
  grant handling, and fail-closed capture behavior.

The TUI repository owns this shared contract because it is the current home
for the local Home service and cross-surface bridge work. Surface repositories
retain their own delivery records and implementation evidence; those records
must reference this contract rather than fork it.

## Open questions

- Exact acoustic evidence encoding, calibration, normalization, and effective
  tie band require the wake-capable hardware contract.
- Device-scoped credential issuance, revocation propagation, and Home-service
  authentication require the shared Device contract.
- Live configuration update notifications can follow the versioned HTTP path;
  polling is sufficient for the first implementation seam.

## Current evidence

The iOS foundation adds canonical mapping references, per-Room priority
validation, revisioned snapshots, and a typed Home-service client seam. Its
focused and full simulator tests pass, and the macOS target builds. The
production Home-service transport, live arbitration engine, credential
handshake, and hardware smoke evidence remain open.

</frozen-after-approval>
