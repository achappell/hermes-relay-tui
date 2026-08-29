# Hermes TUI Parity Backlog

Status: proposed backlog for the laptop-side Textual client.

This backlog compares `hermes-streaming-tui` with the current Hermes Ink TUI.
It defines the smallest useful parity target for a voice-session client; it is
not a request to duplicate every administrative and debugging surface in the
full Hermes TUI.

Reference implementation: `~/.hermes/hermes-agent/ui-tui/`.

## Current baseline

The streaming client already provides:

- authenticated voice-session connection and `hello` handshake;
- typed turns;
- local microphone capture and STT;
- streamed text deltas;
- streamed signed 16-bit PCM playback and WAV fallback;
- explicit session create/resume through `--session-id`;
- connection, timeout, and turn-error reporting.

The current UI has a multiline composer, one accumulated transcript widget, a
FIFO busy-turn queue, local slash-command routing, and a `Ctrl+R` voice path.
Session administration commands still require a gateway-dispatch seam.

## P0 — basic Hermes TUI parity

These are required before calling the client a Hermes TUI rather than a thin
voice-session demo.

### P0.1 Multiline composer

- Replace the single-line `Input` with a multiline composer.
- `Enter` submits; `Shift+Enter` / `Alt+Enter` inserts a newline.
- Preserve pasted newlines and support normal cursor and word-editing keys.
- Keep the draft intact when focus moves to a picker or prompt.
- Add an external-editor escape hatch for long prompts when practical.

Acceptance: a multi-paragraph prompt can be composed, edited, pasted, and sent
without flattening or losing text.

### P0.2 Slash-command routing and completion

- Parse slash commands before treating input as a chat turn.
- Add a registry with aliases, help text, and `Tab` completion.
- Start with `/help`, `/new`, `/clear`, `/status`, `/model`, `/sessions`,
  `/resume`, `/queue`, `/voice`, and `/quit`.
- Route unknown commands to Hermes' gateway command dispatcher rather than
  silently sending them to the model as prose.

Acceptance: `/voice` changes voice behavior, `/model` does not become a model
prompt, and `/help` lists commands and key bindings.

### P0.3 Busy-turn queue

- Queue ordinary text submitted while a turn is active.
- Show a queue preview and allow queued-message editing.
- Drain the queue automatically after the active turn completes.
- Execute slash commands immediately while a turn is active.
- Preserve the single-reader WebSocket invariant; no concurrent `recv()` calls.

Acceptance: typing the next question while Hermes is speaking never loses it,
and it is sent in order after the current turn.

### P0.4 Interrupt and redirect

- Give `Ctrl+C` an explicit busy-turn meaning: interrupt the active turn.
- Add `/steer` or equivalent replacement-message behavior.
- Stop remote generation and local audio playback together.
- Preserve the partial transcript and make the next prompt immediately usable.
- Define clear idle behavior: clear draft first, exit only when nothing is
  pending.

Acceptance: Amanda can interrupt a runaway answer, speak/type a correction,
and receive the correction without restarting the TUI.

Current implementation: `Ctrl+C` cancels local stream consumption, stops local
audio, closes the current connection, and reconnects before the next turn.
`/steer <prompt>` uses the same replacement path. Full server-side cancellation
remains deferred until the voice-session protocol exposes an explicit interrupt
operation.

### P0.5 Session lifecycle and recovery

- Add `/new` and `/clear`.
- Add `/resume` / `/sessions` with a session list picker.
- Hydrate visible transcript and session metadata when a session is resumed.
- Show active session, title, model, and connection state.
- Reconnect and resume after a socket or gateway failure, with a bounded retry
  policy and an honest failure message when recovery is exhausted.

Acceptance: the TUI can start a fresh chat, browse existing chats, resume one,
and recover from a transient connection drop without manual process restart.

### P0.6 Structured turn/event controller

Handle the event families the current Hermes TUI renders:

- message start/delta/complete;
- thinking and reasoning deltas;
- status updates and notifications;
- tool start, progress, and completion;
- background activity and errors.

The current client silently ignores most unknown event types. Unknown events
should be logged or surfaced diagnostically, not discarded without a trace.

Acceptance: a tool-running turn has a live activity lane, a stable final
assistant message, and a useful error if the tool or gateway fails.

### P0.7 Structured prompts

Implement blocking prompt modes for:

- approval: once, session, always, deny;
- clarify: numbered choices or free text;
- sudo: masked input;
- secret: masked input with expiry/cancellation.

Acceptance: a tool requiring approval or a missing secret pauses visibly,
accepts the correct response, and resumes the same turn.

### P0.8 Message-aware transcript rendering

- Store messages as typed records rather than one ever-growing string.
- Distinguish user, assistant, system, tool, status, and error messages.
- Render Markdown: headings, lists, block quotes, tables, links, inline code,
  and fenced code blocks.
- Keep the transcript scrollable and auto-following while streaming.
- Collapse or hide thinking/tool detail according to a display setting.

Acceptance: a resumed transcript and a live transcript look the same, streamed
Markdown does not produce token-per-line noise, and code remains copyable.

### P0.9 Complete voice/audio lifecycle

- Handle `audio_start`, binary PCM chunks, and `audio_end`.
- Handle whole-file fallback events (`audio_file_start` / `audio_file_end`).
- Drain the final PCM tail before marking a turn complete.
- Stop playback on interrupt and avoid leaking an audio stream.
- Show listening, transcribing, thinking, speaking, buffering, and interrupted
  states.

Acceptance: a voice turn is audible from first chunk to final sample, remains
recoverable when live playback fails, and can be barged in on cleanly.

## P1 — useful parity and daily usability

Add these after the P0 interaction loop is solid:

- model/provider picker and session-scoped `/model`;
- `/reasoning`, `/fast`, `/voice`, and visible profile/model state;
- configuration refresh without restarting the client;
- persistent input history at `~/.hermes/.hermes_history`;
- `/history`, `/save`, `/copy`, `/logs`, and `/usage`;
- `/retry`, `/undo`, `/steer`, and `/compress`;
- paste text, image, and path attachments, including `/image`;
- optional `!command` execution and `{!command}` interpolation behind a safety
  gate;
- microphone cancellation, input/output-device selection, and audio status;
- external-editor support for long drafts;
- clearer gateway diagnostics and reconnect status.

## P2 — full Hermes TUI surfaces, deliberately deferred

These exist in the official TUI but are not basic requirements for the laptop
voice-session client:

- skills, plugins, and MCP browsing/configuration;
- browser control;
- background tasks, subagent panels, and replay/diff;
- rollback checkpoints;
- billing, credits, and subscription controls;
- setup/update handoff;
- heap and memory diagnostics;
- themes, skins, density, mouse tracking, and terminal setup.

## Voice-session protocol work

P0 is not client-only work. The voice-session adapter needs a small control and
event contract while keeping Hermes as the owner of sessions, tools, models,
and TTS routing.

Client-to-server operations will eventually include:

- `interrupt`;
- `steer`;
- command dispatch;
- structured prompt responses;
- new/list/resume session operations;
- model/config changes.

Server-to-client events will need normalized forms for:

- session info and transcript hydration;
- message/thinking/reasoning/tool/status events;
- approval, clarify, sudo, and secret prompts;
- notifications and recovery state;
- complete audio lifecycle, including file fallback.

The client must continue to use one WebSocket reader and must not call Qwen or
Chat Completions directly. Those remain internal Hermes seams.

## Recommended delivery slices

1. Composer, persistent history, slash parser, and completion.
2. Busy queue, interrupt/redirect, and audio barge-in.
3. Session picker, transcript hydration, and reconnect/resume.
4. Structured event controller and message-aware rendering.
5. Approval/clarify/secret prompt flows.
6. Model/config controls, attachments, and remaining P1 commands.

Each slice should add focused fake-protocol tests before a live smoke test.
