---
title: Surface coverage index across BMad epics
type: traceability
status: active
updated: 2026-09-12
sources:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/implementation-artifacts/sprint-status.yaml
  - _bmad-output/implementation-artifacts/epic-1-context.md
  - _bmad-output/implementation-artifacts/spec-continuous-wake-free-follow-ups.md
  - _bmad-output/implementation-artifacts/spec-1-wk-1-one-shared-w-k-browser-voice-plus-display-surface-for-author.md
  - _bmad-output/implementation-artifacts/spec-2-wk-2-render-active-capture-room-local-transcription-response-and.md
  - _bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md
  - _bmad-output/implementation-artifacts/deferred-work.md
  - _bmad-output/planning-artifacts/sprint-change-proposal-2026-09-10.md
  - docs/friction-log.md
  - shared/display/README.md
  - docs/bmad-upstream.md
  - ../hermes-relay-ios/_bmad-output/implementation-artifacts/epic-1-context.md
---

# Surface coverage index across BMad epics

This is a thin cross-repository planning and traceability index. It answers
which surfaces participate in an epic, which story IDs own that work, what
evidence or dependency is visible, and where to read the authoritative record.

It is not a backlog, a story specification, or a formal status tracker.

| Concern | Authority |
|---|---|
| Story IDs and acceptance scope | Surface-specific maps in `_bmad-output/planning-artifacts/epics.md` and the owning story specifications. |
| Delivery status and formal closure | The owning repository's story artifact, validation record, and `sprint-status.yaml`. |
| Cross-repository applicability, evidence, and dependencies | This index. |
| Durable product intent and reconciliation | `~/Documents/Vaults/Personal Vault/projects/hermes-home/hermes-home.md`. |

## Surfaces

| Code | Surface | Boundary |
|---|---|---|
| I | iOS app | Native SwiftUI conversation and device-administration client in the sibling repository. |
| A | Android app | Native Android conversation and device-administration client with feature parity to iOS; sibling repository bootstrap is pending. |
| P | ReSpeaker Puck | ESP32-based audio/status doorway without a touch display; physical wake, capture, local status, and response audio. |
| E | ESP32 Touch Display | Waveshare ESP32-S3/LVGL voice-plus-display doorway. It captures voice, renders its own response, and delivers response audio. |
| W/K | Web and iPad voice/display | One Python/Svelte browser surface; iPad is a Safari/Guided Access deployment, not a separate renderer. |
| T | TUI | Textual terminal conversation surface. |

The mobile and display relationships are:

```text
Python host / DisplaySnapshot contract
             ├── Svelte DOM renderer ──► W/K (web and iPad kiosk)
             └── native LVGL renderer + voice adapter ──► E (ESP32 touch)

Hermes session authority
             ├── native iOS Client + mobile control plane
             └── native Android Client + mobile control plane
```

## Working rules

- Start with this index when choosing cross-repository work, then follow the
  story ID to `epics.md` and the owning repository's story artifact.
- A surface row is evidence and planning context. It never changes the
  owning repository's status and never closes a sibling surface.
- Update this file only when applicability, ownership, implementation
  evidence, or a shared dependency changes. Do not copy acceptance criteria
  or maintain a second task list here.
- `Implemented`, `In review`, `Foundation`, `Open`, and `N/A` below describe
  evidence or applicability only. They are not formal story statuses.
- W/K is one implementation boundary for web and iPad. Passive Room Display
  is a role exercised by an applicable renderer, not another surface.
- The Puck has no touch display. ESP32 Touch is a separate full voice-plus-
  display doorway. Its visual `DisplaySnapshot` contract does not carry
  microphone or response PCM; voice capture and response audio require a
  bounded audio/session adapter.
- Exact visual parity between E and W/K is not required. Shared semantics,
  phase rules, room ownership, capability rules, normalized actions, and the
  typed-choice `choose`/`explore` meaning are.
- The approved first proving slice gives active ESP32 Touch, direct-use W/K,
  and TUI surfaces native choice actions. Passive Room Displays mirror the
  object read-only; the Puck remains status/audio-only. Exact schema and
  consequence-bearing policy are downstream dependencies, not this index's
  task queue.
- iOS and Android require capability and safety parity, not pixel or source
  parity. Each native Client owns its platform lifecycle, permissions, audio,
  secure storage, accessibility, and local history.

## Epic 1 — Have a reliable Hermes conversation

| Surface | Story IDs | Owner | Evidence or dependency |
|---|---|---|---|
| I | `I-1`–`I-3` | `hermes-relay-ios` | Implementation and device-validation evidence exists in the sibling repository. |
| A | `A-1`–`A-3` | `hermes-relay-android` | Delivered and verified in the sibling repository: `A-1` authorized typed/tap-to-speak initiation, `A-2` honest phases with response text/audio delivery, and `A-3` bounded recovery without replaying an uncertain turn. Unit and Android 16/API 36 instrumentation evidence is recorded in that repository's `spec-a-*` and `validation-a-*` artifacts. Live Hermes transport, credentials, microphone, and speaker work are deliberately absent and are proposed as `A-4`–`A-6` below. |
| P | `P-1`–`P-11` | Puck delivery work | P-1 and P-2 now have post-review compile/OTA and real-device evidence for authorized wake, acknowledgement-before-capture, VAD-gated capture, chunked upload, host transcription, distinct bridge session identity, streamed response delivery, Puck playback, and a full hands-free spoken Hermes round trip. The earlier weak-signal upload stall and VAD truncation findings are resolved; P-5 tracks the remaining streamed-playback pacing/underrun question, P-6 bridge-service lifecycle hardening, P-7 privacy-safe diagnostics, P-8 audio-format verification, P-9 I2S lifecycle safety, P-10 internal-model routing, and P-11 runtime output-failure propagation and recovery, while P-3 bounded follow-up and P-4 recovery validation remain open in the implementation record. |
| E | `E-1`–`E-5` | `hermes-relay-tui` / firmware | Native display/reducer evidence exists for parts of E-2/E-5; voice capture, response-audio adapter, and active typed-choice slice `2-E-5` remain. |
| W/K | `WK-1` | `hermes-relay-tui` / web | Browser voice/display foundation and verified PCM delivery exist; automated DOM checks now pass (178 tests, zero Svelte diagnostics, production build), while physical Safari/Guided Access, iPad permission, secure-channel, audio, and touch validation remain. Direct-use typed-choice rendering `2-WK-6` depends on server authority `2-WK-5`. |
| T | `T-1`–`T-6` | `hermes-relay-tui` | Local implementation artifacts and regression evidence now include the continuous wake-free follow-up slice; `T-5` records the remaining non-blocking voice-resource lifecycle work and `T-6` records idle relay liveness plus explicit legacy transport classification. Typed-choice presentation `2-T-3` is an approved backlog slice. Formal status remains in the TUI tracker. |

## Epic 2 — See and trust what the room is doing

| Surface | Story IDs | Owner | Evidence or dependency |
|---|---|---|---|
| I | `2-I-1`, `2-I-2` | `hermes-relay-ios` | iOS participant implementation evidence exists in the sibling repository. |
| A | `2-A-1`, `2-A-2` | `hermes-relay-android` (planned) | Android owns the same participant capture/transcription and disconnected-state capability as iOS; implementation and validation are pending. Both depend on the proposed `A-4` relay/credential adapter: every Android story delivered so far is verified against deterministic fakes, and participant timing cannot be honestly validated without a live relay. |
| P | `2-P-1`, `2-P-2` | Puck delivery work | Puck status-only doorway work remains open. |
| E | `2-E-1`–`2-E-5` | `hermes-relay-tui` / firmware | Shared snapshot, reducer, and native renderer are foundation; `2-E-5` is the approved active-doorway typed-choice slice, while passive prompt mirroring remains `2-E-3`. |
| W/K | `2-WK-1`–`2-WK-6` | `hermes-relay-tui` / web | DOM renderer and shared state are foundation; `2-WK-2` clarifies the optional browser-local `transcribing` interval alongside live/final user transcription and bounded response retention; `2-WK-5` is the server-authority prerequisite and `2-WK-6` owns direct-use choice rendering. |
| T | `2-T-1`–`2-T-3` | `hermes-relay-tui` | Existing TUI/appliance behavior is foundation for the direct doorway and separate room mirrors; `2-T-3` owns native keyboard choice actions and transcript-visible structured input. |

Shared `DisplaySnapshot`, reducer, Room filtering, and normalized event feeds
are prerequisites. They do not become an unowned closure story.

## Epic 3 — Control household doorway identity and access

| Surface | Story IDs | Owner | Evidence or dependency |
|---|---|---|---|
| I | `3-I-1`–`3-I-6` | `hermes-relay-ios` | iOS is one of the co-equal mobile control planes; discovery evidence exists and the remaining administration slices are separate work. |
| A | `3-A-1`–`3-A-6` | `hermes-relay-android` (planned) | Android mirrors the iOS Device administration capability: discovery, approval/setup, Wake Mapping validation, arbitration configuration, failed-closed verification, revocation, and explicit re-enrollment. Implementation and validation are pending, and all six depend on the proposed `A-4` adapter — a fail-closed revocation path cannot be validated against a port that was never open. `3-A-4` mirrors `3-I-4`, which has no iOS spec artifact either; both are open. |
| P | `3-P-1`–`3-P-6` | Puck delivery work | Device-side identity, mapping, arbitration, and fail-closed enforcement remain paired Puck work; `3-P-3` now records the firmware-to-bridge mapping propagation and bound-Profile dispatch gap. |
| E, W/K, T | N/A in current pilot | — | No administration boundary is assigned to these surfaces. Do not infer one from the mobile or Puck stories. |

## Epic 4 — Know when the household needs to leave

| Surface or prerequisite | Story IDs | Owner | Evidence or dependency |
|---|---|---|---|
| Shared evaluator | `4-C-1` | Shared product/implementation prerequisite | Calendar, route/estimate, family buffer, and effective-threshold qualification must be settled before renderer closure. |
| E | `4-E-1`, `4-E-2` | `hermes-relay-tui` / firmware | Native Departure Card promotion, recompute, and clear remain open. |
| W/K | `4-WK-1`, `4-WK-2` | `hermes-relay-tui` / web | Browser/iPad Departure Card promotion, recompute, and clear remain open. |

The product requirement is synchronized semantics, not synchronized pixels;
Departure Cards remain display-only and must not generate unsolicited audio.

## Epic 5 — Carry the Hermes relationship with you

| Surface | Story IDs | Owner | Evidence or dependency |
|---|---|---|---|
| I | `5-I-1` | `hermes-relay-ios` | Independent iOS conversation doorway evidence exists in the sibling repository. |
| A | `5-A-1` | `hermes-relay-android` (planned) | Android owns an independent full mobile conversation doorway with iOS capability and safety parity; implementation and validation are pending. `5-A-1` currently absorbs configuration, credentials, secure storage, transport, and doorway parity in one identity; the proposed `A-4` and `5-A-2` split that load. |
| T | `5-T-1` | `hermes-relay-tui` | Existing TUI is substantial foundation; the local story still needs its own BMad workflow. |

## Android/iOS capability parity — proposed identities

Story-ID parity between the mobile surfaces is already 1:1 (twelve identities
each, with Epic 4 correctly assigning no mobile row to either). A capability
audit recorded in the Android repository at
`_bmad-output/planning-artifacts/android-ios-parity-audit.md` found that
story-ID parity is not capability parity: iOS shipped relay configuration and
credential storage, hands-free capture and barge-in, turn interruption,
transcript export, prompt history, a visual design pass, and an app icon set,
none of which hold a story identity on either surface. `UX-DR21` names an
Android accessibility obligation — order `Profile → state →
response/Transcription → action` with focus restoration — that no Android story
owns.

These identities are **proposed, not accepted**. None is real until it is
written into `epics.md`.

| Proposed | Epic | Surface | Scope |
|---|---|---|---|
| `A-4` | 1 | Android | Configure the media-server relay over Tailscale and store its credential in the Android Keystore, with multi-profile add/delete/switch and honest off-tailnet unavailable state. |
| `A-5` | 1 | Android | Interrupt an active turn and stop response playback without a false phase claim. |
| `A-6` | 1 | Android | Hands-free continuation capture and echo-safe barge-in, matching shipped iOS behavior. |
| `5-A-2` | 5 | Android | Accessibility order and focus restoration, satisfying `UX-DR21`. |
| `I-4` | 1 | iOS | Retroactive: interrupt an active iOS turn (`IOS-26`). |
| `I-5` | 1 | iOS | Retroactive: iOS hands-free capture and barge-in (`IOS-16`), recorded as intended capability. |
| `5-I-2` | 5 | iOS | Retroactive: iOS accessibility order and focus restoration. |

Transcript export, prompt history, visual design, and app-icon work are
proposed as local repository tickets on both surfaces rather than upstream
story identities, matching how iOS already tracks `IOS-DESIGN-F1` and
`IOS-BRAND-F1`.

### `FR5` is stale, not the implementation

`FR5` grants a bounded follow-up window to the Puck and the W/K browser surface
and assigns none to a mobile Client, while iOS shipped hands-free regardless.
Decision recorded 2026-09-12: the hands-free behavior is correct and intended,
and the bounded follow-up window no longer applies in many cases. `FR5`
therefore needs an amendment stating where a bounded window still governs.
`A-6` and `I-5` depend on that amendment and should not be scheduled before it.

## Planning handoff

When this index identifies a gap:

1. Select the surface story from `epics.md`.
2. Read that surface's story specification, validation evidence, and local
   sprint status in the owning repository.
3. Check shared prerequisites and competing `In review` slices.
4. Keep one active vertical slice per repository/workstream.
5. Update this index only after the implementation or validation evidence
   changes.

This separation keeps the index useful without creating a second succession
crisis over which file is allowed to declare a story complete.
