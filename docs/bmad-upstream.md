# BMAD upstream context

Hermes Home product planning is canonical in the private product hub.

This repository is the downstream TUI/home-display implementation and the
historical source of the imported product-planning snapshot. It owns delivery
for the TUI, Puck, ESP32 Touch, and W/K surfaces registered in
`bmad-surface.yaml`; it does not own mobile or Home-service status.

## Before planning or building

1. Read the Personal Vault hub and the linked upstream brief, PRD, epic,
   architecture, and UX notes relevant to the slice.
2. GitHub Project #3 is an active mechanical mirror. Use the coordinator
   procedure for accepted TUI-owned items only; this repository's local story
   artifacts and tracker remain authoritative for TUI delivery.
3. Read this repository's `AGENTS.md` and the relevant local implementation
   notes.
4. Use this repository's local BMAD runtime for delivery work. Do not copy
   `_bmad/` or tool configuration from `hermes-relay-ios`.

The existing `_bmad-output/` documents remain useful historical implementation evidence. New cross-repository product decisions belong in the Personal Vault hub first; do not maintain a second, silently divergent PRD or epic set here.

## Traceability

Every substantive TUI item must have an entry in the local story map, a local
specification, an acceptance contract, a validation scenario, and
implementation evidence. The local `sprint-status.yaml` is the formal status
authority for registered TUI-owned surfaces. Product or shared-behaviour
changes discovered during delivery flow back to the Personal Vault hub.

## Parallel work

TUI, Puck, ESP32 Touch, and W/K stories belong here; iOS, Android, Home, and
shared Hermes protocol work belong in their owning repositories. One active
slice is allowed per repository/workstream, so independent TUI, iOS, and
Android slices may all be in `Building` when their shared behavior is settled
and their files do not contend. Shared contract or protocol work remains a
prerequisite when multiple clients depend on it.

## Current upstream baseline

The Personal Vault contains the imported planning snapshot from this repository at commit `e36e9b39d471f9e5e0e1c9e2e35b347b5ac7a9f2`. Treat that snapshot as historical evidence; record new durable product intent and reconciliation decisions in the hub.
