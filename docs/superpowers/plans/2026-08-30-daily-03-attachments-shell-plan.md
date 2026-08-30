# DAILY-03 Attachments and Safe Shell Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Telegram-shaped local attachment model and explicit, bounded shell-command preprocessing without inventing an unsupported Hermes websocket payload.

**Architecture:** `attachments.py` owns local file descriptors, `@` reference discovery, path completion, and previews. `shell.py` owns opt-in command execution and interpolation. `app.py` owns staged attachments and preparation gating; ordinary text still reaches the unchanged `client.send_turn()` path, while attachment-bearing turns stop visibly because the current relay accepts text only.

**Tech Stack:** Python 3.14, Textual, `pathlib`, `mimetypes`, `shlex`, async subprocesses, pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-daily-03-attachments-shell-design.md`

## Global Constraints

- Do not add an attachment field to the current Hermes websocket payload.
- Keep file bytes out of prompt text and do not silently drop an attachment.
- Shell execution is disabled by default and requires `--allow-shell`, `HERMES_RELAY_TUI_ALLOW_SHELL`, or YAML `allow_shell: true`.
- Shell execution uses `shlex.split()`, `shell=False`, no shell operators, a 10-second timeout, and a 64 KiB combined output limit.
- Child commands do not receive `VOICE_SESSION_TOKEN`, `GH_TOKEN`, or `GITHUB_TOKEN`.
- Preparation failures preserve the composer draft and never become model input.
- Run focused tests before `venv/bin/pytest`.

---

### Task 1: Local attachment descriptors and path completion

**Files:**
- Create: `attachments.py`
- Create: `tests/test_attachments.py`
- Modify: `pyproject.toml` module list

**Interfaces:**
- `Attachment` is a frozen dataclass with `path`, `filename`, `mime_type`, and `size_bytes`.
- `AttachmentError` is the user-facing validation exception.
- `resolve_attachment(raw_path, *, cwd=None, image_only=False) -> Attachment` expands `~`, resolves relative paths, requires a readable regular file, records metadata, and optionally requires an image MIME type.
- `find_inline_attachments(text, *, cwd=None) -> tuple[Attachment, ...]` finds explicit `@path` references while leaving ordinary unresolved `@name` mentions alone.
- `complete_path_reference(text, *, cwd=None) -> list[str]` returns complete-text replacements for final `@path` matches.
- `format_attachment_preview(attachment) -> str` exposes metadata without reading file contents.

- [x] **Step 1: Write the failing metadata test.**

```python
def test_resolve_attachment_records_metadata(tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(b"png bytes")
    attachment = resolve_attachment("photo.png", cwd=tmp_path)
    assert attachment.path == image.resolve()
    assert attachment.filename == "photo.png"
    assert attachment.mime_type == "image/png"
    assert attachment.size_bytes == 9
```

- [x] **Step 2: Run the test and confirm it fails because the module is absent.**

Run: `venv/bin/pytest tests/test_attachments.py::test_resolve_attachment_records_metadata -q`

- [x] **Step 3: Implement the frozen descriptor and resolver minimally.**

Use `Path.expanduser().resolve(strict=False)`, `is_file()`, `os.access(path, os.R_OK)`, `stat().st_size`, and `mimetypes.guess_type() or "application/octet-stream"`. Raise one actionable `AttachmentError` for each invalid state.

- [x] **Step 4: Run the metadata test and confirm it passes.**

Run: `venv/bin/pytest tests/test_attachments.py::test_resolve_attachment_records_metadata -q`

- [x] **Step 5: Add failing tests for inline references, unique completion, image-only rejection, and metadata-only previews.**

The tests must prove `@notes.txt` resolves when it exists, `@Amanda` remains ordinary text when no file exists, `look at @pho` becomes `look at @photo.png`, a text file fails `image_only=True`, and preview output contains filename/MIME/size but not file contents.

- [x] **Step 6: Run the attachment tests to observe the expected failures, implement the parsing/completion helpers, add `attachments` to `pyproject.toml`, and rerun the suite.**

Run: `venv/bin/pytest tests/test_attachments.py -q`

Expected: all attachment unit tests pass.

### Task 2: Bounded local shell execution and interpolation

**Files:**
- Create: `shell.py`
- Create: `tests/test_shell.py`
- Modify: `pyproject.toml` module list

**Interfaces:**
- `ShellPolicy(enabled=False, timeout_seconds=10.0, output_limit=64 * 1024)` is immutable and bounds custom values.
- `ShellExecutionError` is the user-facing shell failure.
- `parse_command(command) -> list[str]` rejects empty input, NUL/newline, shell operators, and malformed quoting using `shlex.split()`.
- `async run_command(command, *, policy, cwd=None) -> ShellResult` uses `asyncio.create_subprocess_exec`, `shell=False`, merged output, filtered credentials, bounded reads, and explicit child termination on error, timeout, or cancellation.
- `async interpolate_commands(text, *, policy, cwd=None) -> str` replaces `{!command}` only after successful execution.
- `standalone_command(text) -> str | None` recognizes a single submitted line beginning with `!`.

- [x] **Step 1: Write failing tests for the disabled gate and operator rejection.**

Assert that `await run_command("printf hello", policy=ShellPolicy())` raises an error containing `disabled`, and that `parse_command("printf hello | cat")` raises an error containing `operator`.

- [x] **Step 2: Run those tests and confirm they fail because `shell.py` is absent.**

Run: `venv/bin/pytest tests/test_shell.py -q`

- [x] **Step 3: Implement policy validation and command parsing.**

Reject `|`, `&`, `;`, `<`, `>`, backticks, `$(`, NUL, and newline before `shlex.split()`. Keep the enabled check in the process execution path.

- [x] **Step 4: Run the focused tests and confirm they pass.**

Run: `venv/bin/pytest tests/test_shell.py -q`

- [x] **Step 5: Add failing execution tests using real `sys.executable -c` subprocesses.**

Cover successful `{!print}` interpolation, non-zero exit, timeout, output over 64 KiB, credential filtering, standalone-command recognition, and no shell expansion. Use a temporary directory and never use a user token.

- [x] **Step 6: Run the shell tests to observe the expected execution failures, then implement async bounded reads and interpolation.**

Read output in chunks, merge stderr into stdout, kill and await the child on every failure path, decode with replacement, and trim only the final newline for interpolation.

- [x] **Step 7: Run the complete shell unit suite.**

Run: `venv/bin/pytest tests/test_shell.py -q`

Expected: all shell tests pass without warnings.

### Task 3: Configuration and `/image` command registration

**Files:**
- Modify: `config.py`
- Modify: `commands.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_commands.py`
- Modify: `config.example.yaml`

- [x] **Step 1: Add failing tests for the default-disabled parser, environment opt-in, and `/image list` registration.**

The parser test must assert `build_arg_parser().parse_args([]).allow_shell is False`; an environment test must set `HERMES_RELAY_TUI_ALLOW_SHELL=true`; the command test must resolve `/image list` to the `image` command.

- [x] **Step 2: Run the focused tests and confirm they fail.**

Run: `venv/bin/pytest tests/test_config.py tests/test_commands.py -q`

- [x] **Step 3: Implement `--allow-shell`, `HERMES_RELAY_TUI_ALLOW_SHELL`, YAML `allow_shell`, and the `/image <path>|list|clear` registry entry using the existing precedence helpers.**

- [x] **Step 4: Run the complete config and command modules.**

Run: `venv/bin/pytest tests/test_config.py tests/test_commands.py -q`

Expected: all tests pass.

### Task 4: Textual integration and draft preservation

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

**Interfaces and behavior:**
- `HermesStreamingApp` owns `self._staged_attachments: list[Attachment]`.
- `/image <path>` stages an image and prints a metadata preview; `/image list` prints previews; `/image clear` removes all and reports the count.
- `Tab` attempts unique final `@path` completion before slash-command completion.
- Ordinary submissions perform shell interpolation and inline attachment discovery before clearing the composer or appending history.
- Attachment-bearing submissions preserve the draft and staged files, print previews plus an explicit text-only relay error, and never call `session.send_turn()`.
- Successful ordinary submissions preserve existing queue/steer/interrupt behavior.
- Idle `Ctrl+C` clears staged attachments along with the existing draft-clearing behavior.

- [x] **Step 1: Add failing app tests for `/image` stage/list/clear and non-image rejection.**

Use a temporary PNG and assert the staged list, preview text, clear count, and visible validation error.

- [x] **Step 2: Add failing app tests proving an inline attachment is not sent and its composer draft remains intact.**

Submit `summarize @<temporary file>`, assert `FakeSession.sent_turns == []`, assert the composer retains the exact text, and assert the transcript names the text-only relay limitation.

- [x] **Step 3: Add failing app tests for unique `@` completion, disabled shell preservation, successful `{!printf ok}` expansion, standalone `!printf ok` local-only execution, and idle `Ctrl+C` staged-attachment clearing.**

- [x] **Step 4: Run the app tests and observe the expected failures.**

Run: `venv/bin/pytest tests/test_app.py -q`

- [x] **Step 5: Implement the integration in vertical slices.**

Add state and `/image` first; then path completion; then move ordinary-prompt preparation/history/composer clearing into `_submit_text(text, composer=None)`. Keep `client.py` and the `FakeSession` turn signature unchanged.

- [x] **Step 6: Run the focused app suite.**

Run: `venv/bin/pytest tests/test_app.py -q`

Expected: all existing and new app tests pass.

### Task 5: Documentation and validation

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `config.example.yaml`
- Modify: `tests/test_packaging.py` only if module metadata assertions require it
- Modify: `docs/friction-log.md` only for a newly discovered deferred snag

- [x] **Step 1: Document the exact attachment and shell surfaces.**

Document `/image <path>`, `/image list`, `/image clear`, `@path`, `!command`, `{!command}`, the opt-in flag/environment/config key, the 10-second/64 KiB bounds, credential filtering, and the current relay text-only error. State that no attachment bytes are sent until Hermes exposes upload/capability operations.

- [x] **Step 2: Run package, config, command, and attachment/shell focused checks.**

Run: `venv/bin/pytest tests/test_packaging.py tests/test_config.py tests/test_commands.py tests/test_attachments.py tests/test_shell.py -q`

- [x] **Step 3: Run the complete suite.**

Run: `venv/bin/pytest`

Expected: all tests pass with no warnings or unhandled task errors.

- [x] **Step 4: Run a sandboxed smoke test with temporary `photo.png` and `notes.txt` files.**

Verify image staging/list/clear, visible attachment rejection with draft preservation, disabled shell rejection, enabled standalone local execution, successful interpolation, no shell expansion, output-limit termination, and timeout termination.

- [ ] **Step 5: Review the final diff and reconcile state.**

Run `git diff --check`, `git status --short`, and `git diff --stat`. Confirm no credentials, audio captures, generated files, or unrelated edits are present. Record evidence in the Daily Note and move DAILY-03 through Verify; mark it Done only after validation and merge.
