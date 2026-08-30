# Manual Smoke Test: COMMAND-01 Inline Command Suggestions

Hands-on check for the removal of the blocking slash-command palette in favor
of typing commands directly with a live, non-blocking suggestion line. Use
the app normally and judge what appears on screen. If anything looks wrong,
stop and tell me what you saw.

## Start the app

```bash
venv/bin/python app.py --debug --log-file /tmp/hermes-relay-tui-command01-smoke.log
```

## 1. Typing `/` no longer opens an overlay

1. With the composer empty, type `/`.

Expect: the `/` appears as ordinary text in the composer. No modal/overlay
opens, focus stays in the composer, and you can keep typing immediately.

## 2. Live suggestions appear and narrow as you type

1. Continue typing `bu` (so the composer reads `/bu`).

Expect: a suggestion line appears above the composer listing commands whose
name starts with `bu` (e.g. `/busy [queue|steer|interrupt] — Show or set
active-turn behavior`). Typing further narrows or clears the list live,
without ever taking focus away from the composer.

## 3. Suggestions narrow to usage for a command that takes arguments

1. Type `/busy ` (a space after `busy`).

Expect: the suggestion line narrows to just `/busy [queue|steer|interrupt]
— Show or set active-turn behavior` — it does not disappear, since `/busy`
still needs an argument.
2. Keep typing `interrupt`.

Expect: the same usage line stays visible while you type the argument.
3. Press `Enter`.

Expect: `/busy interrupt` submits normally and changes the busy-mode, same
as before, and the suggestion line disappears once the composer clears.

## 3a. Suggestions disappear for a command that takes no arguments

1. Type `/quit ` (a space after `quit`).

Expect: the suggestion line disappears — `/quit` takes no arguments, so
there's nothing left to hint at.

## 4. Tab still completes a unique match in place

1. Type `/sta` and press `Tab`.

Expect: the composer fills in `/status ` (trailing space), cursor at the
end, focus still in the composer — no overlay, no transcript noise.

## 4a. Tab-completing a command that takes arguments keeps the hint visible

1. Clear the composer, type `/bu`, and press `Tab`.

Expect: the composer fills in `/busy ` and the suggestion line narrows to
`/busy [queue|steer|interrupt] — Show or set active-turn behavior` instead
of disappearing — this is the original complaint: Tab used to silently drop
the hint the moment it filled in a command that still needed an argument.

## 5. Suggestions stay out of the way for ordinary prompts

1. Clear the composer and type an ordinary sentence that doesn't start with
   `/`.

Expect: no suggestion line ever appears.

## 6. Regression check

Send one ordinary prompt and one slash command (e.g. `/status`) normally.

Expect: both work exactly as before — this is a pure input-flow change, not
a change to what commands do.

## If something is wrong

Leave the log file in place and tell me what appeared, expected vs. actual.
Do not commit the log file.
