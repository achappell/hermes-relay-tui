# Friction Log

This is a capture queue for problems noticed during use. An entry does not
automatically become the next task.

## Triage rules

- Log the symptom, impact, and a possible next action while it is fresh.
- Fix immediately only when it blocks the current task, risks data loss, or
  is small enough to remove safely in a few minutes.
- Otherwise leave it as `deferred` and keep working.
- Promote an item when it becomes blocking, repeats, or naturally matches the
  next parity slice.
- Mark it `resolved` with the change and verification when it is fixed.

## Entries

| Date | Area | Friction | Impact | Next action | Status |
| --- | --- | --- | --- | --- | --- |
| 2026-08-28 | Composer | Enter submissions waited behind the active response, making the TUI appear unable to accept the next prompt. | High: blocked the queue workflow. | Run submissions in a background worker while preserving one WebSocket reader. | resolved |
| 2026-08-28 | Voice protocol | The current voice-session channel has no explicit interrupt operation, so a client-side interrupt cannot guarantee that Hermes stops server-side generation. | Medium: interruption is safe locally but remote cancellation is best-effort. | Add and wire a server-side `interrupt` operation to the voice-session protocol. | deferred |
| 2026-08-28 | Voice UX | Audio state is now separated from the response header, but the transcript still carries too much lifecycle detail for a calm, polished voice experience. | Low: functional output is clear, but status presentation can feel noisy. | Give voice lifecycle state a dedicated compact status surface and refine speaking/buffering transitions. | deferred |
| 2026-08-28 | Transcript rendering | Thinking/status updates repeat as separate transcript lines, and the final response begins on one of those activity lines instead of a clean assistant-message boundary. | High: long turns become noisy and the answer is difficult to scan. | Render thinking/tool activity in a replaceable lane, suppress duplicate updates, and start the final response as its own polished message block. | resolved: normalized activity rendering and response boundaries; covered by app tests |
| 2026-08-28 | Interaction settings | Steering was modeled as its own `/steer` command, but it should be a setting that changes what an ordinary message does while a turn is active. | Medium: the old command shape did not match Hermes TUI behavior. | Add `queue`, `steer`, and `interrupt` busy modes; make ordinary submissions follow the selected mode; expose `/busy` for session changes; retain `/steer` only as a migration warning. | resolved |
| 2026-08-28 | Command completion | Current `Tab` completion edits the composer inline; it lacked the searchable visual command overlay used by Claude TUI. | Medium: commands were discoverable only if the user already knew the slash syntax. | Added `/`-triggered palette with live filtering, descriptions, argument hints, arrow-key selection, and Escape-to-close behavior; verified in the app suite and full suite. | resolved |
| 2026-08-28 | Homebrew packaging | Homebrew rejects a formula file supplied directly from a project checkout; formulas must be staged inside a tap. | Medium: the Jensen trial cannot use a single `brew install` command until a tap exists. | Publish a dedicated private tap, then pin the formula to a tagged release and checksum. | deferred |
