# Hermes Streaming TUI — Design

## Purpose

Rebuild the existing `hermes-hybrid-tui.py` (a `prompt_toolkit`-based CLI
client for the Hermes voice-session websocket) as a real Textual TUI
application. Same functionality, visual upgrade: scrolling transcript
widget, status line, and an input box, instead of raw stdout printing.

Reference script:
`~/Documents/Vaults/Personal Vault/scripts/hermes-hybrid-tui.py`

## Scope

- Visual upgrade only. No new protocol features. One Hermes
  voice-session connection open at a time, same as today — the TUI
  does not show or manage multiple sessions concurrently (no tabs, no
  split view).
- Creating/resuming a session is in scope, but at launch time only:
  `--session-id` (flag or `VOICE_SESSION_ID` env var) picks the
  session to connect to, exactly like the CLI today. Reconnecting
  later with the same `session_id` resumes that chat (session history
  lives server-side, keyed by `session_id`, per the existing `hello`
  handshake). No in-app session picker/list in v1 — that's a
  reasonable follow-up once the core TUI exists, not a blocker for it.
- Text turns and `/voice` microphone turns both in scope for v1.
- Streaming stays fully live: text deltas append to the transcript as
  they arrive, PCM audio plays via `sounddevice` as chunks arrive —
  matching current CLI behavior, not a buffer-then-render simplification.
- Same connection defaults as the reference script: `DEFAULT_URL`
  (`ws://REDACTED-PRIVATE-ENDPOINT:8792/voice-session`), `DEFAULT_CHECKOUT`
  (`~/.hermes/hermes-agent`), `DEFAULT_PROFILE_ENV`
  (`~/.hermes/profiles/amanda/.env`), same env var names
  (`VOICE_SESSION_TOKEN`, `VOICE_SESSION_URL`, etc.).

## Non-goals

- No in-app session picker or multi-session tabbed/split view for v1
  (see Scope above — launch-time `--session-id` covers create/resume).
- No changes to the Hermes voice-session server protocol.
- No automated test suite (the reference script has none either;
  validation is a manual run against the real endpoint).

## Architecture

Modular port. The reference script already has clean function
boundaries internally; this gives each a home instead of one 450-line
file, and keeps the Textual layer as a thin rendering shell on top of
ported protocol logic.

### Files

- **`config.py`** — ports `_env_float`, `_env_int`, `_resolve_token`,
  `_connect_factory`, `_connection_kwargs`, the `argparse` setup, and
  all defaults (URL, checkout path, profile-env path, mic tuning
  params, turn timeout). Logic unchanged from the reference script.

- **`audio.py`** — `PCMPlayer` class, ported as-is: `start()` opens a
  `sounddevice.RawOutputStream`, `write()` pushes PCM chunks, `close()`
  tears it down. Same fallback behavior on failure (buffers instead of
  crashing, exposes `.failure` for status display).

- **`mic.py`** — ports `_load_microphone` (dynamic import of
  `LocalMicrophone` from the Hermes checkout's
  `scripts/voice-session-client.py`) plus a thin wrapper exposing
  `.capture()` (blocking, run in a worker thread) and `.close()`.

- **`client.py`** — the websocket session logic, restructured from
  print-driven to event-driven:
  - `connect_and_hello(args)` — opens the websocket, sends `hello`,
    awaits `hello_ack`, returns the open connection + hello payload.
  - `send_turn(ws, args, index, text)` — ported from `_send_turn` /
    `_send_turn_with_timeout`, but instead of `print()`-ing, it's an
    async generator that yields typed events as they occur:
    `TextDelta`, `TextFinal`, `Status`, `AudioStart`, `AudioChunk`,
    `TurnEnd`, `Error`. This is the one real rewrite in the port — the
    CLI script conflates "receive frame" and "render to stdout"; the
    TUI needs those separated so `app.py` can push updates into
    widgets instead of stdout.
  - Turn timeout wrapping (`asyncio.wait_for`) stays at this layer,
    same semantics as today (0 disables, default 195s).

- **`app.py`** — the Textual `App`:
  - `RichLog` (scrolling, auto-scroll) for the chat transcript —
    appends text as `TextDelta` events arrive, matching the CLI's
    incremental `print()`.
  - `Input` widget for the `you>` prompt; `Input.Submitted` sends a
    text turn.
  - A Textual key binding (e.g. `ctrl+r`, shown as a discoverable
    footer hint) triggers mic capture in a worker
    (`self.run_worker(..., thread=True)`), same flow as the CLI's
    `/voice`: listening → transcript → send as a turn. A key binding
    is used instead of parsing `/voice` out of typed input — mode
    switches belong on keys, not as text commands, so the `Input`
    handler stays a plain "submit this as a turn" path.
  - A footer/status widget reflecting connection state, `[audio
    streaming]` / `[audio buffering: ...]`, and mic listening state —
    replacing the CLI's inline `print(f" [...]")` annotations.
  - Websocket connection is opened once on `App.on_mount` in a worker
    that owns the `client.py` event loop for the session's lifetime;
    UI callbacks (`Input.Submitted`, voice binding) enqueue turns onto
    that worker rather than opening new connections per turn.
  - `/help` and `/quit` become key bindings too (e.g. `f1` / `ctrl+q`),
    each shown in the footer, rather than typed commands — consistent
    with the voice binding above.

### Data flow

```
Input.Submitted / voice binding
        │
        ▼
  client.send_turn() (async generator)
        │  yields TextDelta / Status / AudioStart / AudioChunk / TurnEnd / Error
        ▼
  app.py event loop consumes each event:
    - TextDelta/TextFinal → RichLog.write(...)
    - Status              → update footer status reactive
    - AudioStart          → audio.PCMPlayer.start(format), update footer
    - AudioChunk          → audio.PCMPlayer.write(chunk) (off main thread)
    - TurnEnd             → close out player, write WAV if requested
    - Error               → RichLog.write(error, style="bold red")
```

### Error handling

- Missing token: shown as a startup error (Textual can display this in
  an initial screen or exit with a printed message before the app
  loop starts — CLI's `SystemExit` behavior is preserved pre-mount).
  Once TAB started, no fatal exit; errors surface as
  transcript/status messages.
- Connection errors (`ConnectionError`, `OSError`, `ConnectionClosed`,
  `EOFError`) caught the same way as the CLI's `main()` — reported as
  a status/transcript message with the same retry guidance ("Retry
  with a fresh --session-id..."), app stays open rather than exiting
  the process, since a Textual app closing on connection loss is a
  worse experience than in a CLI.
- Turn timeout: same `RuntimeError` message as today, surfaced in the
  transcript instead of raised to a bare traceback.

### Testing / validation

No automated tests (matches the reference script). Validate by running
the TUI against the real Hermes voice-session endpoint:
1. Text turn — confirm streaming text renders live in the transcript.
2. `/voice` turn — confirm mic capture, transcript echo, and streamed
   response text + audio playback all work.
3. Disconnection/error path — confirm a dropped connection is reported
   without crashing the app.

### Dependencies to add to the project venv

`textual` is already installed. Need to add: `websockets`,
`sounddevice`, `python-dotenv` (optional — the reference script has a
manual fallback parser for `.env` if `dotenv` isn't installed, ported
as-is).
