---
title: 'Render and submit native Choose/Explore actions on ESP32 Touch'
type: 'feature'
created: '2026-09-17'
status: 'in-review'
baseline_commit: 'a197548f571244e660ffe218e5c54ebfe3b0a1e6'
route: 'dispatch'
review_loop_iteration: 0
source_story: '2-E-5'
story_key: '2-e-5-render-and-submit-native-choose-explore-actions-for-current'
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-t-3-render-typed-choice-objects-with-keyboard-choose-explore-actions.md'
  - '{project-root}/_bmad-output/implementation-artifacts/surface-coverage-matrix.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The ESP32 Touch renderer can show generic prompt buttons, but it cannot distinguish inspection from commitment or pass Home's freshness-bound choice identity. A tap can therefore lose the meaning and safety checks of an Interactive Choice Object.

**Approach:** Extend the shared display snapshot/action contract and the existing Home browser-session adapter so an active Touch display renders every bounded option with separate `Choose` and `Explore` controls. Each accepted tap returns once through the current Home prompt correlation; Home remains authoritative for freshness, expiry, resolution, and consequences.

## Boundaries & Constraints

**Always:** Use Home NW-07's existing normalized `prompt_request` with `prompt_kind: "choice"`; preserve the Home-minted `choice.object_id` and `choice.freshness`, advertised `choose`/`explore` operations, option IDs, and labels. Bound objects and freshness to 64 characters, options to 32, labels to 256, and explanation text to 1,024. Advertise and render an action only when both the object and current session capability allow it. Show the active Profile and Hermes' text. Bind an action to the current prompt correlation and Home-owned turn; do not put Hermes Session IDs in the display action. After one accepted response, disable that prompt until Home sends a new state.

**Never:** Convert a choice into free text or a new `prompt.submit`; invent an option, consequence, Profile, or freshness token; replay an uncertain action; expose controls when the snapshot does not advertise them; allow a stale/replaced/duplicate action to reach Home; or claim physical microphone/audio validation from simulator evidence.

| Case | Required behavior |
|---|---|
| Current typed choice | Show explanation, Profile, all options, and each supported `Choose`/`Explore` action. |
| Valid action | Send one normalized action with correlation, operation, option, object, and freshness; Home receives one `prompt.respond`. |
| Missing capability or malformed/stale identity | Show no unsupported control or reject the action without a Home write. |
| Accepted action | Keep the object unresolved and controls disabled until Home replaces or resolves it. |
| Legacy approval/clarify prompt | Preserve its current option path and payload. |

</frozen-after-approval>

## Code Map

- `shared/display/`: snapshot/action JSON schemas and conformance fixtures.
- `home_display/state.py`, `home_display/appliance.py`, and `home_display/server.py`: bounded prompt projection, capability gate, and action dispatch.
- `puck_bridge/home_session.py`: validate typed choice context against the currently pending Home prompt and send the existing `prompt.respond` method without another reader.
- `firmware/esp32-s3-touch-lcd-7/main/`: parse choice metadata, validate actions in the shared reducer, render a scrollable option list, and send the normalized action.
- `tests/test_display_contract.py`, `tests/test_home_display_server.py`, `tests/test_home_appliance.py`, `tests/test_puck_home_session.py`, and `tests/test_firmware_ui_core.py`: contract, authorization, freshness, duplicate, legacy, and native reducer checks.

## Tasks & Acceptance

**Execution:**
- [ ] Extend the v1 display contract compatibly for freshness-bound choices and paired operation actions.
- [ ] Preserve and validate typed choice metadata through `HomeBrowserSession`; dispatch exactly one Home-owned response.
- [ ] Render up to 32 options with explicit supported controls on LVGL and validate before transport.
- [ ] Verify malformed, stale, unadvertised, duplicate, and legacy actions; record simulator/build evidence separately from hardware evidence.

**Acceptance:**
- Every accepted current option is visible with its Hermes label and supported actions; no response is authored locally.
- A valid tap carries `action_id`, `operation`, `option_id`, `object_id`, and `freshness`; Home binds it to its pending correlation and turn.
- Explore requests detail without resolving the object; Choose submits one structured choice; the screen waits for Home's next state.
- Unsupported, malformed, replaced, expired, or duplicate actions produce no Home write and cannot trigger a local consequence.
- Existing generic prompts and snapshots remain compatible; physical device acceptance is reported only after a device run.

## Verification

- `venv/bin/pytest -q tests/test_display_contract.py tests/test_home_display_server.py tests/test_home_appliance.py tests/test_puck_home_session.py tests/test_firmware_ui_core.py`
- `venv/bin/pytest`
- `./scripts/simulate_native.sh`
- `venv/bin/pio run -d firmware/esp32-s3-touch-lcd-7 -e esp32-s3-touch-lcd-7b`
