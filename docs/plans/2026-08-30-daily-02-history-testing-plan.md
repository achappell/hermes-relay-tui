# Manual Smoke Test: DAILY-02 Prompt History

Hands-on check for the persistent-history slice of DAILY-02 (prompt history,
`/history`, and the honest `/reasoning` / `/fast` / `/status` model line).
Use the app normally and judge what appears on screen. If anything looks
wrong, stop and tell me what you saw.

## Start the app

From the repository root, run against whichever `--url` you'd normally use
(e.g. the media-server endpoint):

```bash
venv/bin/python app.py --debug --log-file /tmp/hermes-relay-tui-daily02-smoke.log
```

History is scoped per connection host under `~/.hermes-relay-tui/history/<host>.jsonl`
(see step 7), so this session's prompts land in a file specific to whatever
`--url` you're pointed at — they won't mix with a different backend's
history. If you'd rather not touch that file for this test at all, add
`--history-path /tmp/hermes-relay-tui-daily02-history` to every command
below.

## 1. Record a few prompts

Send three ordinary prompts, one at a time, waiting for each reply:

```text
Reply with the word one.
Reply with the word two.
Reply with the word three.
```

Expect: each is sent and answered normally, no change in existing behavior.

## 2. Up/Down recall

With the composer empty:

1. Press `Up`. Expect the composer fills with `Reply with the word three.`
2. Press `Up` again. Expect `Reply with the word two.`
3. Press `Up` again. Expect `Reply with the word one.`
4. Press `Up` again. Expect **no change** — you're at the oldest entry, this
   is a no-op, not an error.
5. Press `Down` twice. Expect `Reply with the word two.`, then
   `Reply with the word three.`.
6. Press `Down` once more. Expect the composer goes **empty** (back to a
   fresh draft, not another history entry).

## 3. Draft preservation

1. Type `unsent draft, do not lose me` but don't send it.
2. Press `Up`. Expect it recalls `Reply with the word three.`.
3. Press `Down` until you cycle back past the newest entry.

Expect: your original `unsent draft, do not lose me` reappears exactly as
typed — Up/Down never throws away an unsent draft.

## 4. Multi-line drafts don't fight history recall

1. Type a two-line prompt using `Shift+Enter` for the newline, e.g.:
   ```text
   line one
   line two
   ```
2. Move the cursor into the middle of `line two` (not the first character).
3. Press `Up`.

Expect: the cursor moves up within the draft (normal text-editor behavior),
**not** a history recall — the two-line draft stays intact. Recall should
only fire when the cursor is on the very first line (pressing `Up` there) or
the very last line (pressing `Down` there).

## 5. `/history` search

1. Submit `/history`. Expect a numbered listing of your recent prompts,
   newest last, including the three "Reply with the word ..." prompts.
2. Submit `/history two`. Expect only `Reply with the word two.` in the
   listing — not the `one` or `three` prompts, and not the `/history`
   command itself.
3. Submit `/history nonsense-that-wont-match`. Expect `history: no matches`.

## 6. Cross-launch persistence

1. Quit the app (`Ctrl+Q` or `/quit`).
2. Relaunch it with the same command as step 0 (same `--history-path` if you
   used one).
3. Press `Up` immediately, before sending anything new.

Expect: the most recent prompt from the previous launch (`Reply with the
word three.`) appears — history survived the restart.

## 7. `/reasoning`, `/fast`, and visible model state

1. Submit `/reasoning high`. Expect:
   `[error] /reasoning needs Hermes gateway command dispatch; the
   voice-session channel does not expose it yet.`
2. Submit `/fast on`. Expect the same shape of honest unavailable message
   for `/fast`.
3. Submit `/status`. Expect a line containing `model: default` (or
   `model: <value>` if you launched with `--model <name>`), alongside the
   existing session/connection/busy-mode/queue fields, plus a trailing
   `history: <path>` field. Confirm that path is under
   `~/.hermes-relay-tui/history/` and its filename matches the host you connected to
   (e.g. `media-server.local_8792.jsonl`), not a generic shared file.

None of these should crash the TUI, hang, or silently do nothing — each
gets a clear, visible response.

## 7a. Backend isolation

1. Quit the app.
2. Relaunch pointed at a *different* `--url` host than step 0 used (any
   reachable Hermes endpoint — even just a different port is enough to
   prove the scoping).
3. Press `Up` before sending anything.

Expect: **no recall** — this is a fresh host, so it has no history yet. This
is the actual behavior driving today's fix: prompts sent to one Hermes
backend must never surface as recall/`/history` results when connected to a
different one.

## 8. Voice turn still works (regression check)

Press `Ctrl+R`, speak one short sentence, and wait for it to finish.

Expect: `Ctrl+R` still captures and sends a voice turn as before — the new
`Up`/`Down` bindings must not have touched it. The transcribed prompt should
also show up under `/history` afterward.

## If something is wrong

Leave the log file in place and tell me what appeared, expected vs. actual.
The optional trace command from the earlier smoke-test plans still applies
if you want to hand me the exact event order. Do not commit the log file or
your real `~/.hermes-relay-tui/` history files.
