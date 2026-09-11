# BMAD upstream context

Hermes Home product planning is canonical in the Personal Vault hub:

`~/Documents/Vaults/Personal Vault/projects/hermes-home/hermes-home.md`

This repository is the downstream TUI/home-display implementation and the historical source of the imported product-planning snapshot. It owns terminal/home-display presentation and local interaction while respecting the shared Hermes protocol boundary. The planned native Android Client is a separate downstream delivery boundary with capability parity to the native iOS Client; it does not belong in this Python repository.

## Before planning or building

1. Read the Personal Vault hub and the linked upstream brief, PRD, epic, architecture, and UX notes relevant to the slice.
2. Inspect GitHub Project #3 for the card's priority, status, owner, dependencies, and current evidence:
   `https://github.com/users/achappell/projects/3/views/2`
3. Read this repository's `AGENTS.md` and the relevant local implementation notes.
4. Use this repository's local BMAD runtime for delivery work. Do not copy `_bmad/` or tool configuration from `hermes-relay-ios`.

The existing `_bmad-output/` documents remain useful historical implementation evidence. New cross-repository product decisions belong in the Personal Vault hub first; do not maintain a second, silently divergent PRD or epic set here.

## Traceability

Every substantive TUI item must have a Project #3 card with an outcome, acceptance criteria, UX expectation, validation scenario, and implementation evidence. Keep the upstream IDs in the card and in implementation artifacts. Product or shared-behaviour changes discovered during delivery flow back to the Personal Vault hub.

## Parallel work

`TUI-*`/`HOME-*` cards belong here; `IOS-*` cards belong in `hermes-relay-ios`; planned `ANDROID-*` cards belong in `hermes-relay-android`; shared Hermes protocol work belongs in its owning repository. One active slice is allowed per repository/workstream, so independent TUI, iOS, and Android slices may all be in `Building` when their shared behavior is settled and their files do not contend. Shared contract or protocol work remains a prerequisite when multiple clients depend on it.

## Current upstream baseline

The Personal Vault contains the imported planning snapshot from this repository at commit `e36e9b39d471f9e5e0e1c9e2e35b347b5ac7a9f2`. Treat that snapshot as historical evidence; record new durable product intent and reconciliation decisions in the hub.
