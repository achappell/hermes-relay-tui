# Validation Report — Hermes Home Assistant Platform

- **DESIGN.md:** `DESIGN.md`
- **EXPERIENCE.md:** `EXPERIENCE.md`
- **Run at:** 2026-09-07T22:45:58-05:00

## Final follow-up verdict

The current pair is safe to finalize as a UX contract. The follow-up verification closed the initial contrast, state coverage, identity timing, no-history, recovery, accessibility, traceability, structure, and prose findings. Current product disposition: 0 critical, 0 high, and 0 medium blockers. Remaining open questions are explicitly owned downstream and do not block the UX spine.

The delegated review runner could not accept a second pass because completed helper threads still occupied its thread limit. The reviewer files therefore retain the initial delegated findings plus a dated local follow-up verification; no fresh-agent result is being implied.

Follow-up evidence:

- `EXPERIENCE.md` now contains a 22-row FR crosswalk, a canonical-to-child-readable state mapping, and a per-surface cold/active/failure/recovery matrix.
- `DESIGN.md` now uses compliant identity and emphasis tokens: 6.39:1 for identity fill text and 5.18:1 for emphasis borders against the panel surface. Subtle borders are explicitly supplementary.
- Profile identity is visible before capture from `heard` through completion; Retry is iOS/TUI-only and reconnect-only; no shared-device text is persisted or rehydrated.
- Active Turn precedence, eight-second follow-up cues, reduced motion, quiet/night suppression, accessible iPad DOM mirroring, VoiceOver focus order, TUI equivalents, room-distance minimums, and child validation are explicit.
- Three load-bearing key screens were promoted: room active turn, iOS setup, and Client recovery.

## Final category verdicts

- Flow coverage — strong
- Token completeness — strong
- Component coverage — strong
- State coverage — strong
- Visual reference coverage — strong
- Bloat & overspecification — strong
- Inheritance discipline — strong
- Shape fit — strong

## Initial review baseline (before fixes)

The pair is a coherent, source-backed draft: all six named journeys have named protagonists, numbered steps, climax beats, and failure paths; all 18 declared components have substantive visual and behavioral rows; and the token graph and chosen mockup reference resolve.

The baseline was not yet safe as a final downstream contract. The identity foreground failed the stated contrast target, platform state coverage and accessibility behavior were incomplete, and several load-bearing interaction decisions were open. The accessibility review reinforced those gaps without challenging the Hermes answer-content boundary. Product findings in that baseline were 0 critical, 11 high, and 6 medium. Editorial findings were reported separately: 9 structure recommendations and 11 prose recommendations.

## Category verdicts

- Flow coverage — adequate
- Token completeness — adequate
- Component coverage — strong
- State coverage — thin
- Visual reference coverage — strong
- Bloat & overspecification — strong
- Inheritance discipline — adequate
- Shape fit — strong

## Findings by severity

### Critical (0)

None.

### High (11)

1. **[Rubric] Identity foreground fails the stated contrast promise** — DESIGN.md §Colors. The #F3F4FF foreground on #7C8CFF measures 2.72:1 while the document claims ordinary-text and large-text targets. **Fix:** choose a compliant pair or restrict identity color to non-text decoration.
2. **[Rubric] Supporting surfaces lack applicable state contracts** — EXPERIENCE.md §Information Architecture / §State Patterns. iOS Client, Settings, Device Discovery, Setup, Details, TUI, Local History, and Puck do not have complete applicable base, empty, permission, offline, error, or ready-state behavior. **Fix:** add a per-surface state matrix and visible recovery/action.
3. **[Rubric] Active Turn versus Departure Card precedence is unresolved** — EXPERIENCE.md §State Patterns / §Open Questions. Both can replace Ambient Surface, but protection, pausing, and replacement are undefined. **Fix:** commit priority and transition rules.
4. **[Rubric] Accessibility Floor is not sufficiently committed** — EXPERIENCE.md §Accessibility Floor. The decided child/readable-motion behaviors are mixed with unresolved screen-reader, caption, language, kiosk, quiet/night, focus, and touch behavior. **Fix:** commit the v1 floor per surface or give non-MVP items explicit owners and revisit gates.
5. **[Accessibility] Close the state-language contract** — EXPERIENCE.md §State Patterns. Child-facing labels do not map normatively to the shared protocol vocabulary, technical detail, visual cue, sound cue, or screen-reader announcement. **Fix:** add one protocol-to-presentation matrix.
6. **[Accessibility] Define assistive technology and focus behavior** — EXPERIENCE.md §Accessibility Floor. The canvas path and platform clients do not expose a complete changing-state, response, focus, or action contract. **Fix:** require an accessible DOM/status mirror, single state announcements, identity/recovery exposure, and platform focus equivalents.
7. **[Accessibility] Make contrast pairs compliant** — DESIGN.md §Colors. Identity, emphasis-border, and subtle-border pairs do not meet their claimed targets. **Fix:** reassign or change semantic pairs and test actual combinations.
8. **[Accessibility] Make room-distance readability testable** — DESIGN.md §Typography / §Layout. Dense small labels have no minimums or two-metre validation for state, Profile, response, error, and recovery text. **Fix:** add real-device distance tests and minimums.
9. **[Accessibility] Show Profile identity before capture** — EXPERIENCE.md UJ-1 / DESIGN.md §Brand & Style. The source fixes identity before capture, but the spines disagree about when it first appears. **Fix:** commit the earliest identity phase and keep it visible through completion.
10. **[Accessibility] Specify the no-history lifecycle** — EXPERIENCE.md §Privacy / §State Patterns. Clearing, browser storage, reboot, reconnect hydration, and partial-text purge boundaries are undefined. **Fix:** make shared conversation text volatile only and define terminal/purge boundaries.
11. **[Accessibility] Assign Retry and stale-context behavior to surfaces** — EXPERIENCE.md §Recovery / §Responsive & Platform. Retry is named but room Display capabilities and cached calendar freshness are unclear. **Fix:** make Retry iOS/TUI-only or define a Display capability, and distinguish disconnected, unavailable identity, generic error, and audio unavailable.

### Medium (6)

1. **[Rubric] Functional requirements are not mechanically traceable** — EXPERIENCE.md §Key Flows. FR-1 through FR-22 are represented but not cross-referenced, and FR-22 has no named flow. **Fix:** add an FR → UJ/section crosswalk or classify FR-22 as a state-only edge case with validation.
2. **[Rubric] iOS profile and Wake Mapping administration is only a capability promise** — EXPERIENCE.md §Information Architecture / §Open Questions. Switching, editing, publication, conflict, and offline behavior remain open. **Fix:** define first-story states or narrow scope to initial setup.
3. **[Accessibility] Close the cue and quiet/night contract** — EXPERIENCE.md §Interaction Primitives. Cue meaning, timing, volume, suppression, visual equivalents, and quiet/night behavior are open. **Fix:** add a cue table and quiet/night preference.
4. **[Accessibility] Make reduced motion an explicit static presentation** — DESIGN.md §Voice Visualizer / EXPERIENCE.md §Accessibility. The mock shortens animation but does not define the static replacement. **Fix:** state and test a no-animation rule for every active state.
5. **[Accessibility] Protect text over ambient media** — DESIGN.md §Ambient Surface / §Departure Card. Arbitrary imagery can compromise load-bearing text. **Fix:** require a controlled contrast treatment or opaque card and test bright/dark photos.
6. **[Accessibility] Validate child comprehension** — EXPERIENCE.md §Accessibility Floor. Technical labels have no comprehension test or language policy. **Fix:** test labels and recovery choices with representative child users and keep diagnostics secondary.

## Editorial structure recommendations

The structure pass found nine recommendations: six changes and three preserves. The measured corpus is 8,035 words; accepting all changes would reduce it by approximately 340–450 words, with another 170–230 words rehomed between the spines.

- **[MOVE]** Keep visual token bindings in DESIGN.md; move behavioral rules out of its Components section.
- **[CONDENSE]** Keep a short DESIGN.md visual checklist; move retry, departure, privacy, and routing rules to EXPERIENCE.md.
- **[MOVE]** Move breakpoint, kiosk-chrome, and platform-navigation notes from DESIGN.md to EXPERIENCE.md.
- **[MERGE]** Make EXPERIENCE.md §Open Questions the sole inventory of unresolved questions, owners, and revisit gates.
- **[MERGE]** Remove repeated global lifecycle and recovery invariants from EXPERIENCE.md Component Patterns.
- **[MOVE + CONDENSE]** Move visual-direction history to DESIGN.md and retain only a compact behavioral anti-pattern list in EXPERIENCE.md.
- **[PRESERVE]** Keep the token contract and Night Console mockup links.
- **[PRESERVE]** Keep all six named journeys and their step → climax → failure shape.
- **[PRESERVE]** Keep the Foundation, glossary, and Information Architecture overview.

## Editorial prose recommendations

The prose pass found eleven approximately word-neutral clarity edits. It preserves the dense instrument-panel voice, concise status copy, title-case concepts, tables, and named journey beats.

- Clarify “Hermes is the product relationship” as the shared relationship across doorways.
- Replace “a failure” with “failure information.”
- Clarify that the Profile Header must not imply answer correctness; Hermes owns answer content.
- Make follow-up opening and closing actions grammatically parallel.
- Split the unclear complete-state sentence into an expiry condition and return state.
- Use “The child-readable set includes…” for the accessibility list.
- Remove the meta-reference to a “captured decision” from accessibility prose.
- Prefer “shows” to “exposes” for reader-facing state behavior.
- Make `stop` an explicit user utterance.
- Clarify that transport loss moves the doorway to Disconnected State.
- Make “follow-up close” a natural parallel noun phrase.

## Reviewer files

- `review-rubric.md`
- `review-accessibility.md`
- `review-structure.md`
- `review-prose.md`

## Promoted visual references

- `mockups/direction-night-console.html`
- `mockups/key-room-active-turn.html`
- `mockups/key-ios-setup.html`
- `mockups/key-recovery.html`
