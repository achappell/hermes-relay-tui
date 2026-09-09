# BMad Review — Editorial Prose

## Follow-up verification — 2026-09-07

The eleven copy edits were rechecked against the current spines. The ambiguous profile, follow-up, state-transition, stop, and recovery constructions have been clarified; the remaining open-question wording is parallel and owned. No high- or medium-severity prose issue remains. The delegated runner could not accept a second pass because its completed helper threads still occupied the thread limit, so this is a local verification pass.

Reader calibration: humans  
Style guide: Microsoft Writing Style Guide  
Scope: copy-editing only; product decisions and UX content are sacrosanct.

**Purpose and audience read:** These documents exist to help human product, design, and engineering readers apply one truthful visual and behavioral system across the household's Puck, Displays, Clients, and TUI.

**Structure model carried forward:** `DESIGN.md` uses a Reference/Database model with a short orientation layer. `EXPERIENCE.md` uses an Explanation/Conceptual model supported by reference tables and named journeys. The structure pass's `MERGE` guidance is honored below: repeated follow-up wording is attached to the surviving Interaction Primitives rule rather than treated as separate findings in the component table.

**Measured length:** `DESIGN.md` contains 2,384 words and `EXPERIENCE.md` contains 5,651 words, for a combined corpus of 8,035 words. The YAML preambles contain 426 and 32 words respectively.

**Intentional style to preserve:** The documents use dense instrument-panel language, concise friendly status copy, conceptual terms in title case, state labels in code formatting where behavior is specified, structured tables, and named journey climax/failure beats. Those choices support human scanning and should remain.

| Pass | Original Text | Revised Text | Changes |
|---|---|---|---|
| prose | `DESIGN.md §Brand & Style` — “Hermes is the product relationship.” | Consider: “Hermes is the shared relationship across doorways.”? | Clarifies the abstract noun phrase while preserving the distinction between the Hermes relationship and the Missy Profile. |
| prose | `EXPERIENCE.md §Voice and Tone` — “it must never obscure privacy, identity, or a failure.” | “it must never obscure privacy, identity, or failure information.” | Replaces the singular count noun with the intended category and removes an awkward parallel. |
| prose | `EXPERIENCE.md §Component Patterns > Profile Header` — “The header must not appear as proof that the answer content is correct; Hermes owns that.” | “The header must not imply that the answer is correct; Hermes owns the answer content.” | Removes the ambiguous pronoun “that” and states the ownership boundary directly. |
| prose | `EXPERIENCE.md §Component Patterns > Follow-up Window` / `§Interaction Primitives > Turn-taking and cues` — “The opening plays a sound cue and shows Listening again; the closing gives a cue when no new speech arrives.” | At the surviving Interaction rule: “When the window opens, play a sound cue and show Listening again; when it closes without new speech, play the closing cue.” | Gives the actions an explicit subject and makes the two timing conditions parallel. The component-table wording is a `MERGE` candidate and should point here. |
| prose | `EXPERIENCE.md §State Patterns > complete` — “Puck opens the eight-second follow-up; no follow-up ends with a closing cue and Ambient/idle state.” | “The Puck opens the eight-second follow-up. If no new speech arrives, play a closing cue and return to the Ambient/idle state.” | Repairs the unclear “no follow-up ends” construction and makes the expiry condition explicit. |
| prose | `EXPERIENCE.md §Accessibility Floor` — “The child-readable set is heard, listening, working, speaking, unavailable, and stopped; the canonical Turn Phase labels remain available for precise diagnosis.” | “The child-readable set includes heard, listening, working, speaking, unavailable, and stopped; the canonical Turn Phase labels remain available for precise diagnosis.” | Uses a complete construction for the list and preserves the distinction from the canonical vocabulary. |
| prose | `EXPERIENCE.md §Accessibility Floor` — “Sound cues remain available because the captured decision keeps them as a turn-taking aid.” | “Sound cues remain available as a turn-taking aid.” | Removes the meta-reference to a “captured decision,” which is unclear to a reader of the finished spine. |
| prose | `EXPERIENCE.md §Interaction Primitives > Turn-taking and cues` and `§Key Flows > UJ-1` — “The Puck/Client exposes the honest phase sequence...” / “The winning Puck exposes `heard` and then `listening`.” | “Each Puck or Client shows the honest phase sequence...” / “The winning Puck shows `heard` and then `listening`.” | Uses the reader-facing verb “shows” and replaces the slash compound with an explicit subject. |
| prose | `EXPERIENCE.md §Interaction Primitives > Turn-taking and cues`, with the same construction in `§Component Patterns > Follow-up Window`, `§State Patterns > Stopped`, and `§Key Flows > UJ-1` — “Exactly `stop` during capture or follow-up closes the local window silently.” | “When the user says exactly `stop` during capture or the follow-up window, close the local window silently.” | Makes clear that `stop` is the user's utterance and names the follow-up window. Apply the canonical wording at the surviving Interaction rule; the `MERGE` candidates should cross-reference it. |
| prose | `EXPERIENCE.md §Recovery and explicit actions` — “A transport loss during a turn enters `Disconnected State` or its equivalent honest local error.” | “A transport loss during a turn moves the doorway to `Disconnected State` or its equivalent honest local error.” | Gives the state transition a human actor and removes the impression that the loss itself enters a state. |
| prose | `EXPERIENCE.md §Open Questions and Deferred Decisions` — “What exact microcopy and cue timing should accompany unavailable identity, connection loss, follow-up opening, follow-up close, and audio-unavailable states?” | “What exact microcopy and cue timing should accompany an unavailable identity, connection loss, the opening and closing of the follow-up window, and audio-unavailable states?” | Adds the missing article and makes the list parallel; “follow-up close” becomes a natural noun phrase. |

## Summary

The prose pass records 11 recommendations: 10 definitive copy-edits and 1 wording option marked for consideration. No length target was provided. If accepted, the changes are approximately word-neutral—an estimated net reduction of 0 words, or 0.0% of the measured 8,035-word corpus—with a few added words deliberately improving subject clarity. No comprehension trade-off is expected.

The baseline review was not clean; the findings above are retained as an audit trail. The dated follow-up at the top records their resolution before the spines were marked final. No `CUT` passage was reviewed, and no source file was modified by the reviewer.
