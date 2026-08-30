# DAILY-03 Attachments and Safe Shell Commands

**Date:** 2026-08-30  
**Project item:** DAILY-03 Attachments and safe shell-command features  
**Status:** Design approved by Amanda

## Goal

Give the TUI a Telegram-shaped local attachment model and an explicit, bounded
local shell-command path without inventing an unsupported Hermes websocket
payload.

## Design summary

An outgoing turn is conceptually `text + attachments`, like Telegram's message
plus media model. The client resolves local paths into metadata descriptors and
keeps file bytes out of the text field. The current Hermes voice-session channel
advertises no attachment upload capability, so any turn containing attachments
is previewed and rejected visibly before it reaches `client.send_turn()`.

Shell execution is a separate local preprocessing feature. It requires explicit
opt-in, uses `shlex.split()` with `shell=False`, runs outside the Textual event
loop, has fixed timeout and output limits, and never sends failed or timed-out
command results to Hermes. A standalone `!command` is local-only; `{!command}`
substitutes successful stdout into an otherwise ordinary text turn.

## Components

| File | Responsibility |
| --- | --- |
| `attachments.py` | Immutable local attachment descriptors, safe path resolution, inline `@path` discovery, path completion, and human-readable previews. It does not upload or embed bytes. |
| `shell.py` | Shell opt-in policy, command parsing/execution, timeout/output bounds, environment filtering, standalone execution, and interpolation. |
| `commands.py` | Register `/image` with `add`, `list`, and `clear` behavior. |
| `config.py` | Add the opt-in `--allow-shell` flag, `HERMES_RELAY_TUI_ALLOW_SHELL`, and YAML `allow_shell` setting using existing precedence. |
| `app.py` | Own staged attachments, route `/image`, offer `@` completion, prepare ordinary submissions, preserve drafts on preparation failure, and enforce the current relay capability boundary. |
| `tests/test_attachments.py` | Unit coverage for path resolution, type/metadata classification, inline references, completion, and previews. |
| `tests/test_shell.py` | Unit coverage for parsing, opt-in behavior, bounds, failures, and interpolation. |
| `tests/test_app.py` | Integration-style coverage for `/image`, attachment rejection, shell routing, draft preservation, and normal prompt behavior. |
| `README.md`, `config.example.yaml` | Document syntax, safety gate, current unsupported attachment behavior, and limits. |

## User-visible behavior

### Attachments

- `/image <path>` resolves and stages one local image, then prints a metadata
  preview containing the resolved path, filename, MIME type, and byte size.
- `/image list` prints the staged attachment previews.
- `/image clear` cancels all staged attachments and reports how many were
  removed.
- `@path` in an ordinary prompt identifies a local regular file when the path
  resolves. `@./path`, `@../path`, `@~/path`, and paths containing a separator
  are unambiguous; ordinary `@name` mentions remain text unless they resolve to
  a file.
- `Tab` completes a unique final `@path` token from the local filesystem. It
  never reads file contents and does nothing when there are multiple matches.
- A prompt with staged or inline attachments is displayed with its attachment
  previews, then rejected with an explicit relay-capability error because the
  current channel accepts text only. The composer draft and staged files stay
  available for correction or `/image clear`.
- Attachment preparation rejects missing paths, directories, unreadable paths,
  and non-image paths supplied to `/image` with an actionable error. No file is
  silently discarded.

### Shell commands

- Shell execution is disabled by default and enabled only by
  `--allow-shell`, `HERMES_RELAY_TUI_ALLOW_SHELL`, or YAML `allow_shell: true`.
- A submitted line beginning with `!` runs locally, shows the command and
  bounded output in the transcript, and does not create a Hermes turn.
- `{!command}` runs the command and replaces the expression with stdout. A
  command error, timeout, malformed command, or output-limit violation leaves
  the composer draft intact and prevents the Hermes turn.
- Commands are parsed with `shlex.split()` and executed with `shell=False`;
  shell operators, pipelines, redirections, and empty commands are rejected.
- Each command has a 10-second timeout and a 64 KiB combined stdout/stderr
  limit. Child processes do not receive `VOICE_SESSION_TOKEN`, `GH_TOKEN`, or
  `GITHUB_TOKEN`.
- Shell execution uses an async subprocess process so child execution and
  bounded output reads never stall Textual's event loop; timeout and task
  cancellation terminate the child before returning.

## Data flow

```text
composer submit
      │
      ├─ standalone !command ──> local shell worker ──> transcript only
      │
      └─ ordinary text
           │
           ├─ {!command} ──> local shell worker ──> expanded text
           ├─ @path / staged files ──> Attachment descriptors + preview
           └─ RelayCapabilities(attachments=False)
                    │
                    ├─ attachments present: visible error, do not call client
                    └─ text only: existing `client.send_turn(text=...)` path
```

The internal descriptor shape is deliberately ready for a future relay:

```python
@dataclass(frozen=True)
class Attachment:
    path: Path
    filename: str
    mime_type: str
    size_bytes: int
```

When Hermes eventually exposes capabilities and upload operations, the local
descriptor can feed an upload step that returns an opaque server attachment ID;
the subsequent turn can carry text plus IDs. That future protocol work is out
of scope for DAILY-03.

## Error and cancellation rules

- Preparation happens before a normal prompt is removed from the composer.
- Any preparation error leaves the draft intact, reports one clear error, and
  never turns the error text into model input.
- `/image clear` is the explicit staged-attachment cancellation path. `Ctrl+C`
  continues to clear the draft/queue according to existing idle behavior and
  also clears staged attachments when no active turn is present.
- A shell worker cannot be silently abandoned: timeout and cancellation are
  reported, output already produced is bounded, and no partial interpolation is
  sent.
- Ordinary text with no attachments and no shell syntax follows the existing
  queue, steer, interrupt, history, and reconnect behavior unchanged.

## Testing and validation

- Unit tests exercise real path and subprocess behavior through injectable
  filesystem/runner seams; no live Hermes endpoint is required.
- App tests verify that successful ordinary prompts still call the fake session,
  attachment-bearing prompts do not, `/image` previews/list/clear work, and
  failed shell preparation preserves the composer draft.
- A sandboxed smoke test uses a temporary directory and commands such as
  `printf`, a non-zero exit, and a sleep beyond the timeout. It verifies visible
  output, opt-in enforcement, output bounds, and no shell expansion.
- The existing focused tests and complete `venv/bin/pytest` suite remain the
  release gate. Live attachment sending is not claimed until a Hermes relay
  contract exists.

## Explicit non-goals

- No attachment bytes are sent over the current websocket.
- No provisional Hermes attachment JSON schema is added.
- No arbitrary shell interpreter, pipes, redirections, background processes,
  or unbounded output is supported.
- No unrelated relay command dispatch, session browsing, or visual redesign is
  included.
