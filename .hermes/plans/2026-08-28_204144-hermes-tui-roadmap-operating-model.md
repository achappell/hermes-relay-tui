# Hermes Streaming TUI Roadmap Operating Model

## Goal

Make feature planning easy to steer while keeping product intent, UX quality,
relay constraints, implementation work, and validation connected.

## Current context

The repository currently has three planning documents with overlapping jobs:

- `docs/superpowers/specs/2026-08-28-hermes-streaming-tui-design.md` is the
  original v1 design and should be treated as historical scope unless updated.
- `docs/plans/2026-08-28-hermes-streaming-tui-implementation.md` is a detailed
  bootstrap execution script. It is already stale relative to the codebase and
  should not be the roadmap.
- `docs/plans/2026-08-28-hermes-tui-parity-backlog.md` is the strongest current
  product/capability map, but it combines priority, implementation status, UX,
  and relay dependencies.

## Proposed planning layers

### 1. Roadmap: why and when

Keep a short `docs/roadmap.md` with three horizons:

- **Now** — the next vertical slice that should become usable.
- **Next** — capabilities that follow it and their prerequisites.
- **Later** — worthwhile ideas with no current commitment.

Each entry should describe a user outcome, not a module or protocol event.
Keep this to roughly 10–15 entries.

### 2. Backlog: what

Split the parity backlog into capability-sized items. Give every item an ID,
for example `UX-01`, `TURN-02`, `VOICE-03`, or `RELAY-01`.

Use separate fields for:

- `Priority`: must / should / later
- `Status`: idea / ready / building / blocked / verified
- `Layer`: client / relay / both
- `Depends on`: item IDs or a named protocol contract
- `Outcome`: observable user behavior
- `Acceptance`: one or two testable statements
- `Polish`: the quality bar for the interaction
- `Validation`: focused tests plus a manual smoke scenario

Do not use P0/P1 as a combined priority-and-completeness label. A P0 relay
feature can be high priority and still be blocked while client-only work moves
forward.

### 3. Slice plan: how

Keep only one active slice plan in `docs/plans/active/`. It should contain the
smallest implementation steps, exact files, focused tests, and a demo script.
Archive it when the slice is verified. The existing 1,000-line implementation
plan should be labelled as the bootstrap history or split into these slices;
do not keep extending it indefinitely.

### 4. Decision log: why this way

Record decisions that would otherwise keep reopening:

- keyboard ownership for `Ctrl+R`, history, voice, and `Ctrl+C`;
- what interruption means without a remote interrupt operation;
- which UI states are local versus relay-confirmed;
- event names and required payloads for message, tool, prompt, and audio lanes.

### 5. Friction log: what hurts

Keep `docs/friction-log.md` for observed usability problems and rough edges.
When a friction item is selected, promote it into the backlog with an ID and
acceptance criteria. Do not use the friction log as a task queue.

## Recommended delivery sequence

1. **Conversation loop:** composer, slash commands, palette, queue, busy modes,
   draft preservation, and idle/interrupt behavior.
2. **Turn rendering:** normalized event controller, typed message records,
   inline streaming, Markdown, thinking/tool activity, and unknown-event
   diagnostics.
3. **Voice and recovery:** listening/transcribing/speaking states, complete
   audio lifecycle, barge-in, reconnect behavior, and WAV fallback.
4. **Session administration:** new/list/resume and transcript hydration once
   the relay contract exists.
5. **Daily usability:** history, copy/save, external editor, device selection,
   retry/undo, and clearer diagnostics.
6. **Polish pass:** visual hierarchy, spacing, focus transitions, terminal
   resizing, empty/loading/error states, status language, and streaming
   smoothness.

Attach a small UX acceptance section to every slice; keep the final polish pass
for cross-cutting consistency rather than discovering basic interaction needs
at the end.

## Work item template

```md
### UX-00 Short capability name

- Priority: must
- Status: ready
- Layer: client
- Depends on: —
- Outcome: Amanda can ...
- Acceptance:
  - ...
- Polish:
  - ...
- Tests: `tests/test_app.py::test_...`
- Manual validation: ...
```

## Immediate cleanup

1. Keep the design spec as the v1 historical reference.
2. Convert the parity backlog into the capability backlog using the fields
   above, preserving its relay-boundary analysis.
3. Mark implemented items from the current `app.py` and tests as `verified`.
4. Choose one next vertical slice and create its active plan only.
5. Add a dedicated UX polish item rather than hiding polish in miscellaneous
   implementation tasks.

## Risks and tradeoffs

- A separate roadmap, backlog, and slice plan adds documents, but each remains
  short and has one job; this is cheaper than maintaining another giant plan.
- Relay-blocked work should remain visible, but never occupy the next client
  sprint by accident.
- “Polish” must be testable through screenshots, keyboard scenarios, and manual
  streaming checks, not only described as “make it nicer.”
