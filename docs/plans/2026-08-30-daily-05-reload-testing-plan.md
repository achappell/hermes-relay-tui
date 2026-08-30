# Manual Smoke Test: DAILY-05 /reload

Hands-on check for `/reload` — picking up config-file/environment changes in
a running session without restarting. Use the app normally and judge what
appears on screen. If anything looks wrong, stop and tell me what you saw.

## Start the app

Point `--config` at a scratch file so you don't touch your real
`~/.hermes-relay-tui/config.yaml`:

```bash
cp config.example.yaml /tmp/hermes-relay-tui-reload-smoke.yaml
venv/bin/python app.py --config /tmp/hermes-relay-tui-reload-smoke.yaml \
  --debug --log-file /tmp/hermes-relay-tui-daily05-smoke.log
```

Separately, confirm the new auto-create behavior: if you don't already have
`~/.hermes-relay-tui/config.yaml`, running the app with no `--config` flag at
all should create it from `config.example.yaml` on this first launch. Check
`ls ~/.hermes-relay-tui/config.yaml` after a normal (no `--config`) launch.

## 1. An untouched setting picks up a live edit

1. With the app running, in another terminal edit
   `/tmp/hermes-relay-tui-reload-smoke.yaml` and add or change:
   ```yaml
   hide_thinking: true
   ```
2. Back in the app, submit `/reload`.

Expect: a `config reloaded from ...` line, and thinking/tool detail stops
showing in the transcript on the next turn (same effect as `/details hide`,
but picked up from the file). `/status` shows the `config:` path you passed.

## 2. A session-touched setting survives reload

1. Submit `/busy interrupt` — confirm `busy-mode set to interrupt`.
2. Edit the scratch config file: add `busy_mode: steer`.
3. Submit `/reload`.

Expect: the reload message includes `kept session-set: busy-mode`, and
`/busy` (with no args) still reports `interrupt` — your interactive choice
was not clobbered by the file.

## 3. Malformed config file fails safely

1. Corrupt the scratch config file, e.g. append a stray `:` on its own line.
2. Submit `/reload`.

Expect: an `[error] /reload: ...` line in the transcript. The TUI keeps
running — it does not crash, hang, or exit.

## 4. Regression check

Send one ordinary prompt after all of the above.

Expect: it sends and answers normally — `/reload` did not disturb the
active connection or transcript.

## If something is wrong

Leave the log file in place and tell me what appeared, expected vs. actual.
Do not commit the log file or the scratch config file.
