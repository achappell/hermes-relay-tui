---
title: "Polish the TUI conversation surface"
slug: tui-ux-batch
type: feature
status: done
created: "2026-09-11"
baseline_commit: "06e89b387463fa969c3fb16b658da376b7c9157d"
route: dispatch
---

# TUI UX batch

## Context

The live UX review found that the TUI currently presents implementation
mechanics as if they were conversation: thinking summaries remain in the
transcript, help is appended there, queue entries are numbered, and responses
are labelled `hermes:` instead of with the active Hermes Profile. Short
terminals then lose most of their useful conversation area to supporting
panels. The shared experience contract calls for a Profile header, inline
streaming, honest phases, and diagnostics that do not become the household
journey.

## Frozen intent

Keep the existing turn, queue, voice, wake, and session behavior while making
the default TUI feel like a direct conversation with the selected Profile.
Make help temporary, keep diagnostic detail opt-in, make queue state ambient
and non-calculated, identify the responding Profile, and give the transcript
priority in compact terminal sizes.

## Boundaries

Always preserve inline streamed responses, FIFO queueing, `/undo`, busy modes,
continuous wake follow-ups, explicit stop behavior, `/details show|hide`, and
keyboard access to every retained control. Keep protocol parsing and session
behavior in the existing core modules.

Never change the Hermes wire protocol, replay an uncertain turn, remove the
queue itself, add a second source of profile identity, or make core modules
depend on Textual. `/queue` is a public command removal; automatic queueing
and idle `Ctrl+C` clearing remain.

## User-visible behavior

| Scenario | Expected result |
|---|---|
| Normal text or voice turn | User prompt and streamed response remain inline; assistant label is the configured Profile display name, with a safe generic fallback. Completed thinking/tool activity is absent by default. |
| `/details show` or configured detail visibility | Thinking/tool/status detail remains available without changing answer ordering. |
| F1 or `/help [filter]` | A focused, dismissible help overlay opens; no help block is added to the conversation. Escape returns focus to the composer. |
| More than one queued prompt | The queue shelf shows count and readable previews without ordinal prefixes; FIFO dispatch is unchanged and queue mechanics do not become transcript chatter. |
| `/queue` | It is no longer advertised or handled as a user command; the queue remains automatic and manageable through existing interruption/undo behavior. |
| 40x12 or similarly short terminal | Transcript retains usable height and visual priority while essential connection/voice state and prompt submission remain available. |

## Code map

- `app.py`: transcript construction, Profile/header status, help routing,
  queue shelf/notifications, compact CSS, and modal integration.
- `transcript.py`: configurable assistant/Profile label and detail projection.
- `commands.py`: public command registry and help output.
- `tests/test_app.py`: help, queue, label, detail, and compact-layout behavior.
- `tests/test_transcript.py`: label and default/explicit detail rendering.
- `README.md` and `AGENTS.md`: user-facing and operational command guidance.

## Implementation tasks

1. [x] Use the configured `display_name` as the active Profile presentation, update
   the TUI header and transcript response label, and retain a generic fallback.
2. [x] Make the default detail projection non-persistent for completed activity;
   keep explicit detail visibility and existing streamed-answer semantics.
3. [x] Add a reusable Textual help modal and route F1 and `/help` through it.
4. [x] Remove `/queue` from the public registry/dispatch and simplify automatic
   queue copy and shelf rendering so no ordinal prefixes are shown.
5. [x] Rebalance compact CSS and add focused regression tests, then update the
   command documentation.

## Validation

Run focused app/transcript tests, the complete `venv/bin/pytest` suite, and
`git diff --check`. Review the staged diff for generated files, credentials,
and accidental edits outside this slice.

## Review Triage Log

- `patch` — The Profile-label test originally checked only the plain-text projection; Rich rendering now has an explicit custom-label test.
- `patch` — Profile switching originally lacked a post-switch response check; the profile app test now verifies the new Profile label.
- `patch` — `/help` filtering originally had only a direct command-helper test; the app route now tests `/help voice` in the modal.
- `patch` — Help dismissal originally did not verify focus; the app test now confirms Escape restores the composer.
- `patch` — Default detail hiding originally checked only the projection; the app test now checks the rendered widget projection as well.
- `patch` — Compact queue sizing originally had no boundary test; a 40×12 test now verifies compact styling, usable transcript height, and unnumbered previews.
- `patch` — History hydration referenced nonexistent `self.show_details`; it now uses the canonical `show_transcript_details` flag.
- `patch` — Compact queue and prompt panels were vulnerable to clipped content; their compact limits now allow more rows and scroll overflow.
- `patch` — Compact connection status was hidden for every state; disconnected, connecting, and retrying states now remain visible.
- `patch` — Help content was a non-scrollable Static; it now lives inside a focusable VerticalScroll.
- `patch` — Help omitted prompt-history and mouse-selection controls; the modal binding summary now includes both.
- `patch` — Profile labels accepted embedded control/newline whitespace; label normalization now collapses whitespace before rendering.
- `false` — The blind finding that `hide_thinking` became ineffective describes the intentional new default: detail is hidden unless `/details show` is explicitly selected, while `--hide-thinking` still guarantees hidden detail.

## Sources

- `_bmad-output/planning-artifacts/ux-designs/ux-hermes-relay-tui-2026-09-07/EXPERIENCE.md`
- `_bmad-output/planning-artifacts/ux-designs/ux-hermes-relay-tui-2026-09-07/DESIGN.md`
- `AGENTS.md`
