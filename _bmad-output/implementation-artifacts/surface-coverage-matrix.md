---
title: Surface coverage index across BMad epics
type: traceability
status: active
updated: 2026-09-10
sources:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/implementation-artifacts/sprint-status.yaml
  - _bmad-output/implementation-artifacts/epic-1-context.md
  - _bmad-output/implementation-artifacts/spec-5-stream-audio-to-host-after-a-validated-wake.md
  - _bmad-output/implementation-artifacts/deferred-work.md
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
| P | ReSpeaker Puck | ESP32-based audio/status doorway without a touch display; physical wake, capture, local status, and response audio. |
| E | ESP32 Touch Display | Waveshare ESP32-S3/LVGL voice-plus-display doorway. It captures voice, renders its own response, and delivers response audio. |
| W/K | Web and iPad voice/display | One Python/Svelte browser surface; iPad is a Safari/Guided Access deployment, not a separate renderer. |
| T | TUI | Textual terminal conversation surface. |

The surface relationship is:

```text
Python host / DisplaySnapshot contract
             ├── Svelte DOM renderer ──► W/K (web and iPad kiosk)
             └── native LVGL renderer + voice adapter ──► E (ESP32 touch)
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
  phase rules, room ownership, capability rules, and normalized actions are.

## Epic 1 — Have a reliable Hermes conversation

| Surface | Story IDs | Owner | Evidence or dependency |
|---|---|---|---|
| I | `I-1`–`I-3` | `hermes-relay-ios` | Implementation and device-validation evidence exists in the sibling repository. |
| P | `P-1`–`P-4` | Puck delivery work | The audio bridge has real-device evidence for wake, VAD-gated capture, chunked upload, host transcription, and host response playback. A full spoken Hermes round trip remains unverified at the observed -89 to -90 dB Wi-Fi signal; Puck-side response playback, distinct bridge session identity, and the remaining bounded/recovery validation stay open in the implementation record. |
| E | `E-1`–`E-5` | `hermes-relay-tui` / firmware | Native display/reducer evidence exists for parts of E-2/E-5; voice capture and response-audio adapter work remains. |
| W/K | `WK-1` | `hermes-relay-tui` / web | Browser voice/display foundation exists; kiosk, accessibility, device, and delivery validation remain. |
| T | `T-1`–`T-4` | `hermes-relay-tui` | Local implementation artifacts and regression evidence exist; formal status remains in the TUI tracker. |

## Epic 2 — See and trust what the room is doing

| Surface | Story IDs | Owner | Evidence or dependency |
|---|---|---|---|
| I | `2-I-1`, `2-I-2` | `hermes-relay-ios` | iOS participant implementation evidence exists in the sibling repository. |
| P | `2-P-1`, `2-P-2` | Puck delivery work | Puck status-only doorway work remains open. |
| E | `2-E-1`–`2-E-4` | `hermes-relay-tui` / firmware | Shared snapshot, reducer, and native renderer are foundation; surface story validation remains. |
| W/K | `2-WK-1`–`2-WK-4` | `hermes-relay-tui` / web | DOM renderer and shared state are foundation; browser surface validation remains. |
| T | `2-T-1`, `2-T-2` | `hermes-relay-tui` | Existing TUI/appliance behavior is foundation for the direct doorway and separate room mirrors. |

Shared `DisplaySnapshot`, reducer, Room filtering, and normalized event feeds
are prerequisites. They do not become an unowned closure story.

## Epic 3 — Control household doorway identity and access

| Surface | Story IDs | Owner | Evidence or dependency |
|---|---|---|---|
| I | `3-I-1`–`3-I-6` | `hermes-relay-ios` | iOS is the pilot control plane; discovery evidence exists and the remaining administration slices are separate work. |
| P | `3-P-1`–`3-P-6` | Puck delivery work | Device-side identity, mapping, arbitration, and fail-closed enforcement remain paired Puck work. |
| E, W/K, T | N/A in current pilot | — | No administration boundary is assigned to these surfaces. Do not infer one from the iOS or Puck stories. |

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
| T | `5-T-1` | `hermes-relay-tui` | Existing TUI is substantial foundation; the local story still needs its own BMad workflow. |

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
