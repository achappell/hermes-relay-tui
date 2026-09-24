---
id: TUI-HOME-01
title: Pair the TUI with a Home and run CLI-style sessions through it
status: backlog
github_issue: https://github.com/achappell/hermes-relay-tui/issues/205
depends_on: HOME-NW-17 (https://github.com/achappell/hermes-relay-home/issues/52)
---

> **Approved correction (2026-09-23):** [Current delivery contract](course-correction-2026-09-23.md) governs mode separation, required voice in Home mode, session recovery and retirement. TUI-HOME-01 remains Epic 1; direct setup is TUI-STD-01 in Epic 2.

# TUI-HOME-01 — Pair with Home and own the session lifecycle

## Problem

Home now runs in paired mode, and the TUI cannot use it on its own. The TUI's `transport: home` expects a Device credential and a fixed `HOME_CONVERSATION_HANDLE` pasted into the private profile env. A conversation handle is created only by a granted claim, expires 90 seconds after issue if it is not opened, and closes 8 seconds after playback, so a saved handle stops working within minutes. The TUI has no pairing flow, no claim, no credential renewal, and no way to choose sessions through Home.

Verified on 2026-09-23: the legacy direct voice-session path (profiles `amanda`, `jensen`, `spark`) completes a hello and a full text-and-audio turn, which is historical migration evidence; it is not the supported post-cutover configuration.

## Outcome

A person pairs the TUI with a particular Home once, using one pairing link and one approval on the Home pairing page. The TUI then stays paired, renews its own credential, and manages sessions like a regular CLI: new, continue, resume, list, and rename, across every surface that talks to the same Profile.

## Scope

- **Pairing.** `hermes-relay pair <link>` accepts the `hermes-home://pair?...` link, or `--home <url> --code <code>` when typed by hand. It submits the enrollment request with `type: tui` and `client_claim`, shows the confirmation code, waits through `approval_pending`, and stores the credential. `hermes-relay unpair [--home <url>]` removes it locally and revokes it when Home is reachable.
- **Credential storage.** The credential goes in the platform secure store: macOS Keychain, or Secret Service on Linux, through `keyring`. The TUI refuses to pair when no secure store is available. No credential or handle is written to YAML, `.env`, history, diagnostics, or logs.
- **Per-Home pairings.** Pairings are keyed by Home, so one TUI can pair with more than one household. A TUI profile names its Home and its Profile grant by label; config never holds a credential, Profile ID, or Session ID.
- **Profiles.** `--profile` and the in-app Profile switcher choose among the Home's `client_grants` by label. A grant that is `pending_owner` is shown as waiting for the owner's approval.
- **Claim lifecycle.** On launch, the TUI makes a client claim for the selected grant and opens the bridge. On quit, it sends `conversation.close`. A network drop within the reconnect grace uses `conversation.reconnect`; an uncertain turn is reported and never replayed. `claim_limit`, `client_claim_unavailable`, `profile_unavailable`, and `unauthorized` are shown as plain, specific states.
- **Sessions, CLI-style.** A launch starts a new session by default. `--continue` resumes the most recent session and `--resume <ref>` resumes a specific one. In the app, `/sessions` lists the Profile's conversations from every surface (Puck, Touch panel, W/K, other clients), marking ones another device holds; `/new`, `/resume`, and `/title` act on the current connection. `session_busy` explains that another device is using that conversation.
- **Owner approvals.** `/approvals` lists pending grants for the Profiles this TUI holds and approves or rejects them. `/devices` lists the devices holding each Profile.
- **Renewal.** On each connect inside the renewal window, the TUI renews its credential. An expired credential prompts `hermes-relay pair` with the Home named.
- **Setup and migration.** `hermes-relay setup` offers pairing for Home transport. The `HOME_CONVERSATION_HANDLE` requirement is removed. Direct Standard `gateway` remains an explicitly supported setup choice under TUI-STD-01. Legacy `voice-session` is removed under TUI-RETIRE-01 at the cross-surface cutover.

## Out of scope

- Home-side routes and the pairing page: HOME-NW-17.
- Home-network (non-Tailscale) routes: HOME-NW-04 roaming follow-up.
- iOS and Android pairing: owned by their repositories.

## Acceptance

- A new TUI pairs using one pairing link and one page approval, with the confirmation code shown on both sides.
- The credential is stored only in the platform secure store; pairing fails clearly when none is available.
- A paired TUI keeps working past the original 90-day expiry through automatic renewal, without re-pairing.
- Launch, `--continue`, `--resume`, `/sessions`, `/new`, `/resume`, and `/title` work through Home. `/sessions` shows conversations started on other surfaces for the same Profile.
- Pausing with the TUI open never ends the conversation; quitting closes the claim; a crash releases it after the reconnect grace.
- Two TUI windows on one laptop hold independent sessions.
- `/approvals` and `/devices` work for an owned Profile.
- No credential, handle, Profile ID, or Standard Session ID appears in config, history, diagnostics, logs, or the transcript.
- The legacy `voice-session` path still passes its hello and turn check.
- A live check through the deployed Home records a typed turn, a voice turn with response audio, `--continue`, resume of a session started on another surface, and reconnect without replay. Any gate that cannot be exercised live is recorded as deferred, not passed.
- Full suite, `tests/test_core_boundary.py`, and a fake-Home test covering pairing, claims, session operations, renewal, and denials pass.

## Code map

- `config.py`: per-Home pairing records, profile-to-Home and grant-label mapping, removal of the `HOME_CONVERSATION_HANDLE` requirement.
- New core module for Home client operations (enrollment, consume polling, client claims, grants, renewal, approvals): no Textual import.
- Home transport session (currently `puck_bridge/home_textual_session.py` and `puck_bridge/home_session.py`): claim on connect, `conversation.close`, session operations, and `session_ref` handling.
- `app.py`, `session_picker.py`: `/sessions`, `/new`, `/resume`, `/title`, `/approvals`, `/devices`, and state presentation.
- `setup_wizard.py`, `profile_cli.py`: `pair`, `unpair`, and setup integration.
- `scripts/fake_home_bridge.py`: extend with enrollment, client claims, session operations, and denial cases for tests.

## Dependencies

- HOME-NW-17 merged and deployed on the household Home, with the device-facing routes published on the tailnet.
- Tailscale on the client machine for now.
