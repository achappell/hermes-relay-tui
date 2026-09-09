# Spine Pair Review — hermes-relay-tui

## Overall verdict

Strong and finalizable as a bounded UX contract. Rechecked against the full UX validation rubric, the confirmed PRD review rubric, `.memlog.md`, all seven declared upstream sources, the reconciliation notes, and the four promoted mockups. The recent fixes close the prior load-bearing concerns around identity timing, state coverage, surface behavior, Active Turn precedence, shared-device history, FR traceability, accessibility commitments, and contrast. Finding count: **0 critical, 0 high, 0 medium, 0 low**.

## 1. Flow coverage — strong

Checked the source PRD's UJ-1 through UJ-6 and FR-1 through FR-22 against `EXPERIENCE.md`. Every named journey has a named protagonist or household context, numbered steps, a climax, and a failure path. UJ-1 carries the primary conversational loop and now includes the Prompt Mirror boundary at step 5 (`EXPERIENCE.md:297–310`). UJ-2 through UJ-6 retain the same step → climax → failure shape (`EXPERIENCE.md:312–370`).

The Product-requirement crosswalk covers every source requirement, FR-1 through FR-22, with a UX section, journey, or both (`EXPERIENCE.md:72–99`). FR-22 is explicitly anchored to UJ-1's prompt step rather than left as an unowned component edge.

### Findings

None.

## 2. Token completeness — strong

The DESIGN frontmatter contains complete six-digit hex values for all 20 color tokens, structured typography roles, dimensional rounded/spacing tokens, and 18 component token groups (`DESIGN.md:15–210`). Every prose token reference resolves to that graph; the dark-first direction is intentional and does not require a second light palette.

The contrast commitments are now internally coherent. Recomputed load-bearing pairs include `ink-primary` on `surface-console` at 16.43:1, `accent-identity-on` on `accent-identity` at 6.39:1, `border-emphasis` on `surface-panel` at 5.18:1, `status-unavailable` on `surface-panel` at 7.66:1, and `focus-ring` on `surface-panel` at 17.02:1. DESIGN states the WCAG 2.2 AA text targets and the non-text target, and explicitly prevents the 1.52:1 `border-subtle` pair from carrying grouping, focus, or state meaning alone (`DESIGN.md:227–234`).

### Findings

None.

## 3. Component coverage — strong

All 18 declared components have substantive visual rows in DESIGN and behavioral rows in EXPERIENCE: room/display surfaces, Puck status, identity, turn path, state label, visualizer, transcript, follow-up, ambience, departure, disconnection, retry, setup, history, prompt mirror, and TUI header (`DESIGN.md:270–289`; `EXPERIENCE.md:121–140`). The two spines keep the visual/behavioral ownership boundary explicit, while the rows retain enough local context for downstream extraction.

### Findings

None.

## 4. State coverage — strong

The state contract is now mechanically usable. State Patterns cover cold/ambient, unconfigured, connecting, all named Turn Phases, stopped, audio unavailable, disconnected, revoked/unavailable identity, Departure Card, and prompt waiting (`EXPERIENCE.md:142–163`). The presentation mapping covers the canonical/local states, including the previously missing `error` state, with child-readable copy, technical detail, cues, and assistive presentation (`EXPERIENCE.md:171–193`).

The per-surface matrix covers Puck, Room/iPad Display, iOS Client, iOS Settings, TUI, and Local History across cold/empty, active, offline/permission/failure, recovery, and persistence (`EXPERIENCE.md:195–206`). The requested trust boundaries are explicit:

- **Identity before capture:** Wake Mapping selects one Profile before Puck capture; the Room Display exposes it at `heard`, and iOS/TUI show it before capture (`EXPERIENCE.md:210–216`, `:297–303`).
- **Active Turn vs Departure:** the selected Room's Active Turn outranks the household-wide Departure Card until completed response plus follow-up close or `Stopped`; other Displays continue to show the Departure Card, and the selected Display promotes it after the turn (`EXPERIENCE.md:165–169`).
- **No-history lifecycle:** shared text is volatile, room-local, and cleared at follow-up close, `Stopped`, fresh session, reboot, Retry, or restart; it is never rehydrated from browser storage or a service worker. Intentional Local History is restricted to iOS/TUI (`EXPERIENCE.md:165–169`, `:201–206`).

### Findings

None.

## 5. Visual reference coverage — strong

All four files in `mockups/` are promoted and linked inline where their decisions are consumed: `direction-night-console.html`, `key-room-active-turn.html`, `key-ios-setup.html`, and `key-recovery.html`. The links name what each illustration demonstrates in DESIGN or EXPERIENCE (`DESIGN.md:219`, `:268`, `:272`, `:283`, `:285`; `EXPERIENCE.md:23`, `:60`, `:63`, `:134`). There are no files in `wireframes/` or `imports/`, hence no visual orphans. The spine-wins-on-conflict rule is stated in both orientation points (`DESIGN.md:219`; `EXPERIENCE.md:23`).

### Findings

None.

## 6. Bloat & overspecification — strong

The YAML token graph is doing real downstream work, and the prose is tied to visual decisions, state semantics, privacy, recovery, or surface ownership. The state mapping and surface matrix are complementary lookup axes rather than a second backlog; the named flows repeat selected rules only to show them in context. Visual direction history stays in DESIGN, while EXPERIENCE keeps behavioral anti-patterns and the decision ledger.

### Findings

None.

## 7. Inheritance discipline — strong

Both frontmatters declare the same seven resolvable upstream sources, and EXPERIENCE's `design: DESIGN.md` reference resolves. UJ and FR names retain the source PRD's wording, the shared vocabulary follows the PRD glossary, and the 18 component names remain aligned between frontmatter and both component tables (`DESIGN.md:7–14`, `:117–210`; `EXPERIENCE.md:6–14`, `:31–53`, `:121–140`).

The reconciliations preserve the source decisions without introducing a competing authority: Hermes owns answer content, the Puck/Display boundary remains room-local, iOS owns physical-device administration, and the open mechanics have owners and revisit gates. The Accessibility Floor is now a committed v1 behavior contract rather than an undifferentiated placeholder: readable state text, reduced motion, quiet/night suppression, identity timing, no-history behavior, iPad DOM mirroring, VoiceOver order/focus return, TUI equivalents, touch minimums, and child/room-distance validation are all named (`EXPERIENCE.md:246–261`).

### Findings

None.

## 8. Shape fit — strong

DESIGN follows the required canonical order: Brand & Style → Colors → Typography → Layout & Spacing → Elevation & Depth → Shapes → Components → Do's and Don'ts (`DESIGN.md:215–303`). EXPERIENCE contains the required Foundation, Information Architecture, Voice and Tone, Component Patterns, State Patterns, Interaction Primitives, Accessibility Floor, and Key Flows sections. Responsive & Platform and Inspiration & Anti-patterns are correctly present for a multi-surface product with selected and rejected visual directions (`EXPERIENCE.md:19–29`, `:263–293`).

### Findings

None.

## Mechanical notes

- The source PRD review is clean; the UX reconciliations carry forward its six journeys, FR-1–FR-22 contract, privacy/recovery rules, and owner/revisit gates. `.memlog.md:31–37` records the same finalization boundary and handoff decision.
- `EXPERIENCE.md` intentionally references DESIGN generically rather than duplicating token paths; no broken token reference is present. DESIGN's token references resolve recursively.
- The raw shared-display `prompt` state is presented to household users as the readable `prompt waiting` / Prompt Mirror behavior (`EXPERIENCE.md:163`, `:193`, `:139`); adapter work should preserve that distinction and the no-touch v1 boundary.
- macOS is named as a future/undefined companion rather than silently treated as a pilot surface (`EXPERIENCE.md:271`, `:384`). The current pilot contract remains Puck/Display, iOS, and TUI; downstream macOS stories should wait for that ledger gate.
- `border-subtle` remains a deliberately low-contrast structural separator. Its non-sole-signal restriction is the controlling accessibility commitment; implementation must keep labels, spacing, and stronger emphasis alongside it (`DESIGN.md:228–230`, `:301`).
- No Mermaid blocks or Mermaid syntax are present. Only this `review-rubric.md` was written for this re-review; DESIGN.md, EXPERIENCE.md, `.memlog.md`, and reconciliation files were not edited.
