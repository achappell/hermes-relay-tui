# Manual Smoke Tests: Transcript Streaming

This is the small, hands-on check for the current TUI changes. Use the app
normally and judge what appears on screen. If anything looks wrong, stop and
tell me what you saw; the optional log command below lets me debug the exact
session.

## Start the app

From the repository root, run:

```bash
venv/bin/python app.py --debug --log-file /tmp/hermes-streaming-tui-smoke.log
```

The app uses the configured Hermes profile and endpoint. Keep the app open
while testing.

## 1. Ordinary text turn

Type a short prompt and press `Enter`, for example:

```text
Reply with one short sentence confirming the smoke test.
```

Expect:

- your prompt appears once with `you>`;
- the response streams inline under one `hermes:` message;
- the response appears once when it finishes;
- the status returns to ready and the composer still accepts input.

## 2. Check the duplicate-response fix

Run two or three ordinary prompts, including one short answer and one longer
answer. Watch the response while it is streaming.

Expect:

- one assistant response per prompt;
- if the visible draft changes while streaming, it updates in the same assistant message;
- the final answer does not appear again on a new line;
- there is no second `hermes:` header for the same turn.

A response changing slightly while it streams is acceptable. Seeing the
completed answer repeated is not.

## 3. Markdown transcript

Ask Hermes:

```text
Respond with a short heading, a two-item bullet list, and a fenced code block.
```

Expect one assistant message with the heading, bullets, and code block visibly
formatted. It should not become a token-per-line transcript or a second copy
of the answer.

## 4. Thinking and tool activity (when available)

Run a prompt that normally causes Hermes to think or use a tool.

Expect:

- thinking/status/tool progress updates in the activity area;
- repeated updates replacing the current activity instead of spamming lines;
- the final answer starting as one clean assistant message;
- no activity line containing a second copy of the answer.

If that prompt does not produce activity, that is not a failure; just test the
final transcript behavior.

## 5. Optional detail toggle

Use the existing command palette to run these commands:

1. `/details` — expect the current shown/hidden state.
2. `/details hide` — expect activity detail to disappear while the answer remains.
3. `/details show` — expect activity detail to return.

The command palette interaction itself is a separate UX issue already recorded
in the friction log.

## 6. Optional voice turn

Press `Ctrl+R`, speak one short sentence, and wait for the turn to finish.

Expect one transcribed user turn, one assistant response, and normal audio or a
clear buffering/fallback message.

## If something is wrong

Leave the log file in place and tell me what appeared twice or looked wrong. If
you want to show the relevant trace yourself, run:

```bash
rg -n 'turn.send|frame.recv.*kind=(text_delta|message\\.delta|text_final|message\\.complete)|normalize|app.event kind=(text_delta|text_replace)|turn.end|app.turn.finish' /tmp/hermes-streaming-tui-smoke.log
```

The trace contains event order, lengths, and hashes—not prompts, responses,
tokens, or audio. Do not commit the log file.
