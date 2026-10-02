---
id: TUI-STD-01
product_epic: 2
title: 'Offer explicit Standard-only terminal setup'
type: 'feature'
created: '2026-09-29'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: bec2aeb3d9184be9e9da4309aab78ffcf4e1e101
context:
  - '{project-root}/_bmad-output/implementation-artifacts/course-correction-2026-09-23.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-standard-3-tui-migrate-terminal-client.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** New setup silently selects the legacy route; Standard setup is only a flag. Direct Standard history and mode changes lack Home's isolation and uncertainty safeguards.

**Approach:** Ask users to choose HomeBridge or Standard Hermes, reuse the verified Standard adapter, and make mode, capabilities, credentials, history, and recovery clear. Preserve separate credentials and existing profiles.

## Boundaries & Constraints

**Always:** Standard means unmodified Hermes at `/api/ws`; the verified baseline is 0.21.1, commit `2237be355906fbe6065ce1815711eee52b2d646e`. Keep tokens out of YAML, logs, and history. Retain owner-only env storage for Standard and native secure storage for Home. Preserve prompt-only local history and its privacy/retention rules. Typed streaming works; local speech is optional; structured prompts are unsupported. Offer remote interrupt/audio only as verified for this baseline; local stop always applies to enabled capture/playback. Reconnect restores transport but does not resolve uncertainty.

**Never:** Never require Home enrollment or reuse Home credentials for Standard. Do not carry credentials, session references, or transcript contents into another mode or Standard identity; do not add automatic assistant-response or raw-audio archives. Preserve explicit `/save` export. Never silently change modes, fall back, suggest another mode as outage recovery, replay a prompt, or migrate prompt history across transports or identities. Do not change the Hermes wire protocol, retire the legacy adapter, or add Home grants/room access to Standard.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| FIRST_SETUP | No transport configured | Ask for HomeBridge or Standard; keep Home pairing and configure Standard directly. | Missing or invalid choice changes no config. |
| CAPABILITIES | Standard; voice dependencies absent or a structured prompt arrives | Keep typed chat; explain optional voice or unsupported prompt. Never treat a prompt as ordinary text. | Show failure; no fallback. |
| MODE_CHANGE | Active/pending or uncertain turn | Block active work. Reconnect preserves uncertainty; first leave it via `/session new` for Standard, or `/home leave` then a deliberate replacement for Home. | A blocked switch preserves session, transcript, and active profile; never replay. |
| HISTORY_SCOPE | Legacy, Home, or another Standard identity has history | Open only this transport/endpoint/Profile history; leave other files unchanged. | Never migrate across modes or identities. |

</frozen-after-approval>

## Code Map

- `setup_wizard.py`, `config.py`, `profile_cli.py` -- setup, endpoint validation, profiles, and token references. Ask for a first-run choice, preserve named catalogs/private token envs, keep the Standard `session.create` check (it creates a remote session), and retain `--transport`/`--no-check`.
- `gateway_client.py`, `gateway_session.py` -- `/api/ws`, redaction, normalized events, audio, and the pinned adapter. Reuse verified behavior; keep structured prompts unsupported and do not claim negotiation.
- `app.py` -- connection status, `/status`, `/profile list`, `_switch_to_args`, `_prompt_history_for_args`, and `/session new`. Show the mode, preflight before saving `active_profile`, and guard uncertainty across transports. A successful Standard `/session new` clears uncertainty; reconnect alone does not. Do not carry old session IDs or transcript text across the switch.
- `history.py` -- `history_path_for_profile` and `PromptHistory`. Scope by transport, endpoint, local profile, and Hermes Profile; do not migrate legacy/Home history into Standard.
- `tests/test_setup.py`, `tests/test_history.py`, `tests/test_profile_app.py`, `tests/test_app.py`, `tests/test_gateway_session.py`, `README.md` -- extend fake seams and document behavior.

## Dependencies

- `tui:TUI-HOME-01` -- done; retain its Home pairing, secure credential, and grant-scoped history path when adding the Standard choice.

## Tasks & Acceptance

**Execution:**
- [x] `setup_wizard.py`, `config.py`, `tests/test_setup.py` -- ask mode and save Standard profiles without overwriting others; retain private tokens and make speech-model preparation optional.
- [x] `app.py`, `gateway_session.py`, `tests/test_app.py`, `tests/test_gateway_session.py` -- show mode, explain limits, and guard changes during active or uncertain work.
- [x] `history.py`, `app.py`, `tests/test_history.py`, `tests/test_profile_app.py` -- isolate history and prove no cross-identity migration or replay.
- [x] `README.md` -- explain setup, token storage, baseline, voice/prompt limits, and recovery.
- [x] `_bmad-output/implementation-artifacts/validation-tui-std-01.md`, `story-index.yaml`, `sprint-status.yaml` -- record evidence and update only TUI status; separate implementation, merge, and live gates.

**Acceptance Criteria:**
- Given fresh setup, when no transport is configured, then it requires a HomeBridge or Standard choice and preserves other profiles and credentials.
- Given the supported Standard baseline, when connected, then typed streaming works; connection status, `/status`, and `/profile list` identify Standard and its Profile; verified audio/interrupt work; structured prompts stay disabled and safe.
- Given speech dependencies are absent, when Standard setup completes, then typed chat works, voice is marked optional, and no model download is forced.
- Given both modes are configured, when a user switches, then history and credentials stay isolated, no session ID or transcript crosses the boundary, and errors never trigger fallback or cross-mode migration.
- Given a turn may have reached Hermes, when reconnecting, then it is never replayed and the uncertain state remains. Before switching, Standard requires successful `/session new`; Home requires `/home leave` and deliberate replacement.
- Given setup or connection failure, when retrying, then the selected mode stays intact and only supported recovery is offered.

## Design Notes

Keep per-profile Standard bearer tokens in the owner-only env file; Home keeps its native credential store. Setup saves the selected profile and its existing check creates a remote session. No history/config deletion or deployment. Footprint: setup, status/switching, history, tests, docs, validation.

## Verification

**Commands:**
- `venv/bin/pytest tests/test_setup.py tests/test_history.py tests/test_profile_app.py tests/test_app.py tests/test_gateway_session.py` -- expected: all focused cases pass.
- `venv/bin/pytest` -- expected: full suite passes.
- Live Standard text, voice/audio, interrupt, unsupported-prompt, connection-failure, and recovery checks -- record each gate separately; do not claim unexercised gates complete.

## Review Triage Log

- **BH-01 — README.md:88 — low.** The setup paragraph says legacy `voice-session` is available only with an explicit transport, while an unconfigured launch still defaults to it for compatibility. **Route:** patch the wording to distinguish setup selection from launch defaults.
- **BH-02 — setup_wizard.py:440-449 — medium.** A named `voice-session` profile reuses its token based only on transport, so changing its endpoint can send the old bearer token to a different server. **Route:** patch; group CRED-ENDPOINT.
- **BH-03 — setup_wizard.py:505-522 — low.** Standard's gateway adapter ignores saved client and device IDs and uses the saved session ID only when explicitly supplied at launch, so the setup questions imply values that do not configure its `session.create` call. **Route:** patch; remove the unused Standard questions and use local defaults.
- **BH-04 — README.md:90,213 — low.** Explicit `--stt-model` prepares a model but cannot install the optional voice dependencies; the installation commands already describe them separately, but the flag's prerequisite should be stated beside its use. **Route:** patch; clarify the prerequisite.
- **BH-05 — README.md:90 — false.** The text identifies the verified upstream baseline and says features were verified for it; it does not claim setup enforces the remote server version. **Route:** reject.
- **BH-06 — history.py:149-159 — medium.** The new Standard identity components select a different history path and the old path is deliberately not imported because it cannot prove a Hermes Profile identity; users should be told their prior Standard prompts remain in the old file and are not loaded. **Route:** patch documentation; migration could mix identities.
- **BH-07 — tests/test_profile_app.py — medium.** Existing profile-switch tests cover legacy-to-legacy success and Standard rejection under uncertainty, but none asserts a successful Standard identity switch clears the old transcript and loads a distinct history file. **Route:** patch; add the consumer-path test.
- **BH-08 — tests/test_app.py — medium.** The reconnect test proves successful `/session new` clears ambiguity, but no test proves failed session creation leaves the old prompt uncertain and sending/switching blocked. **Route:** patch; add the failure-path test.
- **BH-09 — validation-tui-std-01.md — low.** The record reports a 155-test run with a temporary runner override but omits the command and override needed to reproduce it. **Route:** patch the validation record with the invocation.
- **BH-10 — setup_wizard.py:440-449 — medium.** This independently reported finding has the same verified outcome as BH-02: a changed `voice-session` endpoint reuses its prior token. **Route:** patch; grouped with CRED-ENDPOINT.
- **EC-01 — setup_wizard.py:103-106 — medium.** `access_token` query keys pass endpoint validation and are persisted in the YAML URL although the approved setup stores bearer credentials separately. **Route:** patch; reject credential query keys and cover the encoded key.
- **EC-02 — app.py:1311-1312; history.py:154-158 — low.** A whitespace-only `HERMES_PROFILE` is omitted from the gateway session request but renders blank and hashes to a different history identity than the server's default Profile. **Route:** patch by normalizing the effective Profile to `default`.
- **EC-03 — history.py:149-159 — low.** With `legacy=True`, the new endpoint and Hermes Profile suffixes still alter the old unscoped Standard path returned by `legacy_history_path_for_profile`; the exported helper no longer resolves the pre-change source. **Route:** patch by retaining the old path when resolving legacy history.
- **EC-04 — setup_wizard.py:550-583 — medium.** Reconfiguring a root-only legacy setup for Standard writes through `save_setup_files`, replacing the prior URL and shared token instead of retaining the usable legacy connection as a profile. The config layer already models this root connection as a default profile and migrates it when a named profile is saved. **Route:** patch; preserve it when adding a second transport.
- **VG-01 — setup_wizard.py:325-408 — low.** Tests cover invalid first-run choices, the Standard path, and Home setup only when `--transport home` bypasses choice mapping; none asserts that a fresh HomeBridge choice reaches pairing. **Route:** patch with a first-run HomeBridge pairing test.
- **VG-02 — setup_wizard.py:535-569 — low.** Tests cover optional Standard model preparation and legacy model preparation, but none invokes Standard setup with explicit `--stt-model` and observes preparation plus saved configuration. **Route:** patch with the opt-in Standard model test.
- **VG-03 — app.py:3145-3149 — medium.** The queued-prompt switch test does not exercise staged attachments, and no profile-switch test asserts an image remains staged when the guard rejects the switch. **Route:** patch with a staged-attachment profile-switch test.
- **VG-04 — app.py:2020-2029, 2575-2589, 2600-2622 — medium.** `/wake on` can start capture during Standard uncertainty, then `_run_turn` rejects the transcript while `_send_wake_turn` records it as history; that violates the same unresolved-turn guard applied to manual voice capture. **Route:** patch with an arming guard and a regression test.
