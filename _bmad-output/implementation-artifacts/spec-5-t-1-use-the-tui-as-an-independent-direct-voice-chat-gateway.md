---
title: 'Use the TUI as an independent direct voice-chat gateway'
type: 'feature'
created: '2026-09-11'
status: 'done'
baseline_commit: '4cb49f0c3a8a4bf04a41cff520fb8c7a8958fce1'
route: 'dispatch'
review_loop_iteration: 0
source_story: '5-T-1'
story_key: '5-t-1-use-the-tui-as-an-independent-direct-voice-chat-gateway-with'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-4-recover-without-replaying-an-uncertain-turn.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-t-2-keep-tui-disconnect-recovery-presentation-honest-without-replaying-an-uncertain-turn.md'

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The TUI already supports typed prompts and local voice turns, but Epic 5 requires a complete, independent direct doorway into Hermes. Its existing prompt history, profile/session isolation, and voice-to-history continuity are not yet specified or proved as one surface contract.

**Approach:** Formalize the existing `SessionProtocol`-based doorway and close only the gaps needed for a trustworthy TUI: preserve typed and voice prompt continuity in deliberate TUI-local history, prove profile/session/transcript isolation, and retain the established honest phase, response, diagnostics, and recovery behavior.

**Decisions:** Local History retains prompt text only, including transcribed voice prompts; assistant responses and raw audio are not archived. Each TUI launch and profile selection mints a unique Hermes Session identity so concurrent doorways cannot share remote session state. Legacy flat or endpoint-scoped prompt history is copied, oldest-first and de-duplicated, into the selected profile's history on first use; source files remain untouched.

## Boundaries & Constraints

**Always:** Use a unique TUI Hermes Session per launch/profile; show the selected Profile before capture or submission and through completion; keep blocking capture/playback off the Textual event loop; render streamed response text inline and keep it identical to Hermes audio; keep diagnostics content-safe and optional; retain only de-duplicated prompt text locally, including voice transcripts, without raw audio, assistant-response archives, or other-surface state; migrate legacy prompts without deleting their source; reconnect without replaying an uncertain turn.

**Never:** Change the Hermes wire protocol; create a shared database or cross-surface transcript store; import Puck, Display, Media Server, or another Client history; invent local response prose; add a second WebSocket reader; move TUI work into the appliance, mobile, browser, or firmware surfaces.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| VOICE_TURN | Authorized selected Profile; `Ctrl+R` or wake capture produces text | TUI uses its unique Session, shows canonical phases, renders Hermes response, and records the transcribed prompt in local history | Permission or capture failure sends no turn and leaves the UI honest |
| TYPED_TURN | Composer submits a prompt while idle or while another turn is active | Prompt follows the selected Session, streams as one inline response, and obeys the existing busy policy | Unsent prompts remain FIFO; ambiguous turns are never replayed |
| LOCAL_HISTORY | Completed TUI interaction is recalled or searched | Prompt text from typed and voice turns appears in the selected profile's bounded history; assistant responses and raw audio do not | Corrupt or unwritable history cannot expose credentials or crash the doorway |
| LEGACY_MIGRATION | Profile-scoped history is first used while a legacy flat/endpoint file exists | Legacy prompt strings are copied oldest-first into the selected profile, de-duplicated, and the source remains intact | Invalid entries are skipped; migration failure leaves the source and current history usable |
| MULTI_DOORWAY | TUI and another doorway are active simultaneously | Unique Sessions, transcripts, response state, and local history remain isolated | No cross-surface state is hydrated or displayed |

</frozen-after-approval>

## Code Map

- `app.py` -- `_submit_text`, `_capture_voice_turn`, `_send_wake_turn`, `_run_turn`, `_history_path_for_args`, `_switch_to_args`, `/history`, and `/save` own TUI initiation, history wiring, profile changes, rendering, and recovery; reuse these paths rather than adding a gateway layer.
- `history.py` -- `PromptHistory`, `history_path_for_profile`, and `artifact_path_for_profile` own bounded prompt persistence, profile/backend namespacing, safe de-duplication, and non-destructive legacy migration; keep this boundary free of UI concerns.
- `session.py` -- `SessionProtocol` and `HermesSession` own the verified Hermes Session, capture, cancellation, interruption, and cleanup boundary; do not duplicate protocol parsing in `app.py`.
- `client.py` -- `send_hello`, `send_turn`, normalized event filtering, multi-segment text, and audio/activity/error events remain the wire adapter and must stay unchanged unless a genuine invariant requires it.
- `config.py` -- `RelayProfile`, profile selection, token references, history-path configuration, CLI/env precedence, and configured session identity define the TUI's launch inputs; preserve credential redaction while deriving the unique doorway Session identity.
- `domain.py` -- `TuiDomain` remains the normalized phase/connection authority; reuse its stale-event and active-turn guards.
- `tests/test_history.py`, `tests/test_app.py`, `tests/test_profile_app.py`, `tests/test_config.py`, `tests/test_session.py`, and `tests/test_client.py` provide the focused persistence, voice, profile, session, and normalized-event seams to extend.

## Tasks & Acceptance

**Execution:**
- [x] `history.py` -- implement prompt-only voice/typed retention, bounded non-destructive legacy migration, strict string loading, and owner-safe persistence -- keep history deliberate, local, and credential-safe.
- [x] `app.py` -- record successfully transcribed voice prompts through the existing history path and derive unique launch/profile Session identity -- preserve canonical phases, inline response rendering, busy policy, and no-replay recovery.
- [x] `tests/test_history.py` and `tests/test_app.py` -- prove prompt-only retention, voice/typed continuity, legacy migration, profile isolation, and failure handling -- prevent regressions at the caller boundary.
- [x] `tests/test_session.py`, `tests/test_client.py`, and `tests/test_profile_app.py` -- extend lower-boundary and simultaneous-doorway assertions for unique Session identity -- keep Hermes and profile ownership explicit.
- [x] `README.md` -- document prompt-only voice history, legacy migration, and unique TUI Session behavior -- keep diagnostics and recovery guidance accurate.

**Acceptance Criteria:**
- Given valid TUI configuration and authorization, when Amanda starts a typed or voice turn, then the TUI uses its own verified Hermes Session and shows the selected Profile before and through the turn.
- Given a voice turn is active, when capture, transcription, processing, response, playback, and completion events arrive, then the TUI exposes canonical phases without blocking its event loop or advancing early.
- Given Hermes streams response text and audio, when both are delivered, then the TUI presents the same Hermes response with one coherent inline text stream and no local replacement prose.
- Given a typed or transcribed voice prompt completes local submission, when local history is updated, then only the prompt text is retained in the selected profile/backend history, raw audio and assistant-response archives are absent, and legacy prompts are migrated without deleting their source.
- Given diagnostics are enabled, when protocol or turn details are shown, then they are optional content-safe engineering detail and are not required for ordinary conversation.
- Given transport loss interrupts a turn, when the TUI reconnects, then recovery reconnects only, the unresolved turn is not replayed, and a fresh explicit initiation is required.
- Given the TUI and another doorway are active simultaneously, when both receive events, then their unique Sessions, transcripts, response states, and local history remain isolated.

## Implementation Notes

- `PromptHistory` now accepts only non-empty JSON strings, performs bounded oldest-first de-duplicated migration from the prior unscoped file, preserves migration sources, tolerates persistence failure, and writes owner-only files atomically.
- Typed, explicit voice, wake, and barge-in transcripts use the existing TUI history path; silence and failed capture do not create history entries. Launch, reconnect, and profile replacement all construct fresh UUID-backed doorway session arguments while retaining configured profile metadata for reload behavior.
- Existing normalized Hermes client filtering, phase authority, inline response rendering, diagnostics redaction, and reconnect/no-replay behavior remain the owning lower-boundary paths; focused regressions cover their story seams.

## Verification

**Commands:**
- `../../venv/bin/pytest -q -k 'typed_and_voice_prompts_share_prompt_only_history or voice_capture_silence_is_not_retained or wake_voice_prompt_is_recorded_in_prompt_history or named_profile_migrates_legacy_prompt_history or named_profile_migrates_endpoint_history_when_history_path_is_absent or each_tui_launch_gets_a_distinct_session_identity or profile_selection_mints_a_distinct_session_identity or session_hello_uses_the_doorway_session_identity or profile_history_migrates_old_prompts_oldest_first_without_touching_source or history_persistence_is_owner_only or failed_history_migration_keeps_entries_in_memory_and_source_usable or reconnect_mints_a_fresh_session_identity or load_deduplicates_non_adjacent_prompts_preserving_order or load_tightens_existing_history_to_owner_only_mode or load_keeps_readable_history_when_permission_tightening_fails or failed_history_save_closes_temp_descriptor or profile_switch_migrates_legacy_prompt_history_without_deleting_source or spoken_follow_up_interrupts_then_starts_exactly_one_new_turn or reload_command_picks_up_untouched_config_changes'` -- 19 passed.
- `../../venv/bin/pytest -q` -- 1012 passed, one pre-existing `websockets.legacy` deprecation warning.
- `git diff --check` -- passed.

**Manual checks (if no CLI):**
- Run two configured TUI doorways against separate Sessions and verify Profile identity, transcript, response state, and approved local history do not cross boundaries; exercise a typed turn, `Ctrl+R`, disconnect/reconnect, and diagnostics without exposing credentials.

## Review Triage Log

- `blind-hunter/B1` — `maybe-false`, `defer`: The same unscoped legacy source can seed more than one profile, but the approved intent does not define a global migration owner for an ownerless file; deciding that policy needs a later product decision.
- `blind-hunter/B2` — `medium`, `patch` (P1): `_send_wake_turn` appends through mutable `self._history` after its future completes, so a profile switch in that race window can attribute the prompt to the new profile.
- `blind-hunter/B3` — `medium`, `defer`: Separate TUI processes can still lose concurrent read-modify-write history updates; this is pre-existing file-level concurrency behavior, not introduced by the story.
- `blind-hunter/B4` — `medium`, `patch` (P2): Existing destination files retain non-adjacent duplicate strings because `_entries_from_lines` only filters invalid values; the approved local-history contract calls for de-duplicated prompt text.
- `blind-hunter/B5` — `medium`, `patch` (P3): An existing history file is not tightened to owner-only mode until a later save, so previously permissive prompt history remains exposed.
- `blind-hunter/B6` — `low`, `patch` (P4): New synchronous `fsync()` runs from typed and explicit voice submission paths on the Textual event loop; move the persistence calls off-loop while preserving the existing history object.
- `blind-hunter/B7` — `low`, `patch` (P5): The implementation intentionally ignores configured `session_id` for the launch Session, but `config.example.yaml` and the environment documentation still describe those values as active session identity; clarify the retained legacy-label semantics.
- `blind-hunter/B8` — `maybe-false`, `defer`: Fail-closed authorization and first-response latency evidence belong to the broader Epic 5 context and were pre-existing, environment-dependent concerns not changed by this TUI history/session slice.
- `blind-hunter/B9` — `medium`, `patch` (P6): The new barge-in history path lacks a regression proving that a successful barge-in transcript is retained; exact-stop, echo, and failed-wake behavior are existing seams and are not altered here.
- `blind-hunter/B10` — `false`: The app tests prove the generated UUID reaches the Session factory, while the HermesSession test proves its supplied identity is sent in `hello`; the two lower-boundary assertions cover the composition even without a live endpoint.
- `edge-case-hunter/E1` — `false`: `_complete_barge_in` visibly calls `self._history.append(text)` before `_run_turn`, so the claimed omission is disproved at the cited location.
- `edge-case-hunter/E2` — `medium`, `patch` (P3): Existing history mode is not repaired on load; this is the same owner-only permission defect as B5.
- `edge-case-hunter/E3` — `low`, `patch` (P7): If `fchmod()` or `fdopen()` fails after `mkstemp()`, the new save path can retain an open descriptor; close the descriptor in the failure path.
- `edge-case-hunter/E4` — `medium`, `defer`: Cross-process history writes can overwrite one another; this is the same pre-existing file-concurrency issue as B3.
- `edge-case-hunter/E5` — `medium`, `patch` (P8): The changed whitespace-only capture guard is not covered by a test, and reverting it would allow a blank voice turn.
- `edge-case-hunter/E6` — `medium`, `patch` (P11): After the connection-status preference change, the existing reload test expects the configured label rather than the actual active Session; align that test with the approved unique-Session behavior.
- `edge-case-hunter/E7` — `medium`, `patch` (P9): Migration is tested only with an explicit configured history path, leaving the default endpoint-scoped legacy source unproved.
- `edge-case-hunter/E8` — `medium`, `patch` (P10): Profile switching invokes the migration path but has no test proving legacy prompts are carried into the newly selected profile.
- `verification-gap/V1` — `medium`, `patch` (P8): The focused suite tests empty capture but not whitespace-only capture, so the new no-blank-turn behavior needs an explicit assertion.
- `verification-gap/V2` — `medium`, `patch` (P6): Successful barge-in history retention is a new behavior and needs a caller-boundary test.
- `verification-gap/V3` — `medium`, `patch` (P9): Default endpoint-derived legacy migration needs an app-level test that preserves the source file.
- `verification-gap/V4` — `medium`, `patch` (P10): Profile selection needs a migration assertion, not only startup migration coverage.
