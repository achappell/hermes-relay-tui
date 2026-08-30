# DAILY-03 manual test runbook

This checks the local attachment and safe-shell features from the TUI. It
requires a reachable Hermes voice-session endpoint for the ordinary text-turn
checks. Attachments are intentionally not uploaded yet: the current relay is
text-only, so the expected attachment result is a visible rejection with the
draft preserved.

## 1. Prepare temporary test files

From the repository root, run:

```bash
TEST_DIR="$(mktemp -d /tmp/hermes-relay-tui-test.XXXXXX)"
printf 'fake image bytes for metadata-only testing\n' > "$TEST_DIR/photo.png"
printf 'local notes\n' > "$TEST_DIR/notes.txt"
printf '%s\n' "$TEST_DIR"
```

The test image does not need valid image contents for this feature; `/image`
checks the image MIME type from the `.png` path and records metadata without
reading the file. Keep the printed directory path handy. When typing paths in
the TUI, paste the actual path; do not type the shell variable `$TEST_DIR`.

## 2. Start the TUI with shell execution disabled

Use the normal profile token lookup, or provide a token through your
environment. Do not put a real token in this document.

```bash
venv/bin/python app.py --no-play --history-path "$TEST_DIR/history"
```

If the profile does not contain the token, use an environment variable for
this terminal only:

```bash
VOICE_SESSION_TOKEN='redacted-token' venv/bin/python app.py --no-play --history-path "$TEST_DIR/history"
```

First submit `hello` and confirm a normal text turn still works.

## 3. Test attachments

Paste the actual path printed in step 1 in place of `<test-dir>`.

1. Enter `/image <test-dir>/photo.png`.
   Expected: a `staged image` line showing `photo.png`, `image/png`, its byte
   size, and the resolved path.
2. Enter `/image list`.
   Expected: the same file appears under `Staged attachments:`.
3. Enter `summarize @<test-dir>/photo.png`.
   Expected: no Hermes turn is sent; the transcript shows
   `relay does not support attachments`; the exact prompt remains in the
   composer.
4. Press `Ctrl+C`.
   Expected: the draft and the staged attachment are cleared.
5. Stage the image again, then enter `/image clear`.
   Expected: the transcript reports `cleared 1 staged attachment(s)`.
6. Enter `/image <test-dir>/notes.txt`.
   Expected: a visible `attachment is not an image` error and no staged file.

## 4. Test path completion

Type this into the composer, replacing `<test-dir>` with the actual path:

```text
look at @<test-dir>/pho
```

Press `Tab`. Expected: the final token completes to
`@<test-dir>/photo.png`, and nothing is sent. Press `Ctrl+C` to clear the
draft.

## 5. Confirm the shell safety gate

With the first TUI instance still running, submit:

```text
show {!printf ok}
```

Expected: a visible shell-disabled error, no Hermes turn, and the draft stays
in the composer. A standalone `!printf ok` should be rejected the same way.

Exit with `Ctrl+Q`, then restart with the explicit opt-in:

```bash
venv/bin/python app.py --no-play --allow-shell --history-path "$TEST_DIR/history"
```

Run these checks:

| Input | Expected result |
| --- | --- |
| `!printf ok` | Shows `ok` locally; no Hermes turn is created. |
| `show {!printf ok}` | Sends `show ok` as the Hermes prompt. |
| `!printf '$HOME'` | Shows the literal `$HOME`; no shell expansion occurs. |
| `!venv/bin/python -c 'import os; print(os.getenv("VOICE_SESSION_TOKEN", "missing"))'` | Prints `missing`; the session token is not passed to children. |

Submit this line exactly, with an unescaped pipe:

```text
!printf nope | cat
```

Expected: a shell-operator error; nothing runs.

Optional bound checks:

```text
!venv/bin/python -c 'print("x" * 70000)'
```

Expected: an output-limit error, with no large transcript dump. This command
should time out after the fixed 10-second limit:

```text
!venv/bin/python -c 'import time; time.sleep(11)'
```

## 6. Run the automated suite

After closing the TUI, from the repository root run:

```bash
venv/bin/pytest
```

Expected: all tests pass. Clean up the temporary files afterward:

```bash
rm -rf "$TEST_DIR"
```

## What is not expected to work yet

The current Hermes voice-session protocol has no attachment capability or
upload operation. A prompt containing staged or inline files must therefore
stop locally with a clear error. Successful live attachment sending will need
an explicit relay protocol change first.
