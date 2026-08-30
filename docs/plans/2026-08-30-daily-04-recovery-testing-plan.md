# Manual Smoke Test: DAILY-04 Recovery and Daily Commands

Hands-on checks for the recovery, transcript-export, diagnostics, and honest
relay-boundary behavior added in DAILY-04. Run the normal-session checks against
the Hermes endpoint you usually use. The failure-path checks use a deliberately
unreachable localhost port, so they do not send anything to Hermes.

If anything looks wrong, stop and note the exact command, expected result, and
what appeared instead. Do not commit the temporary transcript, clipboard dump,
or log files.

## Start a normal session

From the repository root, launch the TUI with your existing token/profile setup:

```bash
venv/bin/python app.py --debug --log-file /tmp/hermes-relay-tui-daily04-smoke.log
```

If the token is not already available through the configured profile, set
`VOICE_SESSION_TOKEN` in the shell before launching. Do not put the real token
in this document or in the repository.

## 1. Command discovery and explicit routing

1. Type `/help` and press `Enter`.

Expect the help output to list `/history`, `/save`, `/copy`, `/logs`,
`/usage`, `/retry`, `/undo`, and `/compress`.

2. Submit each of these commands one at a time:

```text
/usage
/compress
```

Expect:

- `/usage` and `/compress` show that the current voice-session protocol does
  not expose the operation, and explicitly say that no request was sent.
- No command is silently turned into model prompt text.

## 2. Local debug-log inspection

1. Submit `/logs`.

Expect a line showing that the debug trace is active at
`/tmp/hermes-relay-tui-daily04-smoke.log`.

2. Send one ordinary prompt and wait for its response.
3. In another terminal, inspect only the shape of the trace:

```bash
rg -n 'app\.start|app\.turn\.start|app\.event|app\.turn\.finish' \
  /tmp/hermes-relay-tui-daily04-smoke.log
```

Expect event names, lengths, and hashes, but no prompt text, response text,
bearer token, or audio contents.

## 3. Save the visible transcript

1. Submit `/details hide`.
2. Send a prompt containing a unique marker, for example:

```text
Reply with one short sentence containing the marker DAILY04-VISIBLE.
```

3. Submit:

```text
/save /tmp/hermes-relay-tui-daily04-visible.txt
```

Expect a success message naming that file. In another terminal, inspect it:

```bash
sed -n '1,30p' /tmp/hermes-relay-tui-daily04-visible.txt
rg -n 'DAILY04-VISIBLE' /tmp/hermes-relay-tui-daily04-visible.txt
```

The file should contain the readable `you>` and `hermes:` transcript projection.
Thinking/tool detail hidden by `/details hide` must not be included.

4. Submit `/save /tmp/hermes-relay-tui-daily04-visible.txt` again.

Expect an error saying the file already exists and will not be overwritten.
Confirm the original file contents are unchanged.

## 4. Copy the same visible projection

1. Submit `/copy`.
2. On macOS, inspect the clipboard from another terminal:

```bash
pbpaste | sed -n '1,30p'
```

On another platform, paste into a temporary text editor instead.

Expect the clipboard to contain the visible transcript, including the prompt
and response, without hidden thinking/tool detail. If no native clipboard
helper is available, the TUI must show an actionable error naming the supported
helpers (`pbcopy`, `wl-copy`, or `xclip`).

## 5. Safe retry and undo failure path

Quit the normal session, then launch a second instance against an unreachable
localhost port. Reuse your configured token source; if no token is configured,
the placeholder below is safe because the endpoint is local and unreachable:

```bash
VOICE_SESSION_TOKEN='test-only-placeholder' \
  venv/bin/python app.py \
  --url ws://127.0.0.1:9/voice-session \
  --connect-retries 0 \
  --connect-retry-delay 0 \
  --no-play
```

1. Submit an ordinary prompt such as:

```text
DAILY04-UNSENT
```

Expect a visible connection failure and a message saying the prompt was kept
in the local queue. No remote turn can have been created.

2. Submit `/retry`.

Expect a visible `retrying` message and another local connection attempt. It
must not claim that a response was received.

3. Submit `/undo`.

Expect `removed unsent prompt` and an empty local queue. The command must not
claim to undo anything on the relay.

## 6. Ambiguous-turn protection and active-turn safety

Return to a normal session.

1. After a successful ordinary turn, submit `/retry`.

Expect `no safely retryable prompt`; the successful turn must not be silently
sent a second time.

2. Start a deliberately slow prompt and immediately submit `/retry` or
`/undo` while the response is active.

Expect an explicit “unavailable while a turn is in flight” message. No second
turn should start and the active turn should remain the only reader of the
connection.

3. If you can safely interrupt the network after a prompt is sent but before
the response completes, submit `/retry` after the failure.

Expect a refusal explaining that the prompt may have reached Hermes. It must
not replay the ambiguous turn. The automated failure-path test covers this
case deterministically if a live disconnect is impractical.

## 7. Voice regression

In the normal session, press `Ctrl+R`, speak one short sentence, and wait for
the turn to finish.

Expect the existing listening/transcribing/thinking/response flow to work
normally. `/save`, `/copy`, `/logs`, `/retry`, and `/undo` must not interfere
with microphone capture or ordinary prompt submission.

## Cleanup

After testing, remove only the temporary files created for this run if you no
longer need them:

```bash
rm -f /tmp/hermes-relay-tui-daily04-visible.txt \
  /tmp/hermes-relay-tui-daily04-smoke.log
```

The log and transcript are local test artifacts and should remain untracked.
