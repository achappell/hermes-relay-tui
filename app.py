"""Textual TUI for the Hermes voice-session channel.

Consumes normalized events from client.py (message text, activity, audio, turn_end)
and renders them into a scrolling transcript, replacing the print()
calls in hermes-hybrid-tui.py's turn loop.

The transcript is a single accumulated string rendered into a `Static`
inside a `VerticalScroll`. That mirrors the reference CLI's
`print(..., end="")`: each delta grows the buffer and re-renders, so
streamed tokens flow inline. A `RichLog` cannot do this — every
`write()` starts a new line, which turned a streamed sentence into a
token-per-line list.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from textual import events
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Footer, Header, Static, TextArea

import config
from attachments import (
    Attachment,
    AttachmentError,
    complete_path_reference,
    find_inline_attachments,
    format_attachment_preview,
    resolve_attachment,
)
from audio import PCMPlayer, audio_device_list, audio_path, read_wav, write_wav
from clipboard import ClipboardError, copy_text
from commands import (
    COMMAND_REGISTRY,
    CommandInvocation,
    complete_slash_command,
    help_text,
    parse_slash_command,
)
from diagnostics import (
    active_log_file,
    logger as diagnostic_logger,
    summarize_payload,
    summarize_text,
)
from history import PromptHistory, history_path_for_url
from session import HermesSession, SessionProtocol
from shell import (
    ShellExecutionError,
    ShellPolicy,
    interpolate_commands,
    interpolation_commands,
    run_command,
    standalone_command,
)
from transcript import TranscriptBuffer


class Composer(TextArea):
    """Multiline prompt editor with explicit submit/newline key semantics."""

    class Submitted(Message):
        def __init__(self, composer: "Composer") -> None:
            super().__init__()
            self.composer = composer
            self.text = composer.text

    class CompletionRequested(Message):
        def __init__(self, composer: "Composer") -> None:
            super().__init__()
            self.composer = composer
            self.text = composer.text

    class InterruptRequested(Message):
        """Ctrl+C must reach the app even while the TextArea has focus."""

        def __init__(self, composer: "Composer") -> None:
            super().__init__()
            self.composer = composer

    class HistoryPrevRequested(Message):
        """Up at the top line: recall the previous history entry."""

        def __init__(self, composer: "Composer") -> None:
            super().__init__()
            self.composer = composer

    class HistoryNextRequested(Message):
        """Down at the bottom line: recall the next history entry."""

        def __init__(self, composer: "Composer") -> None:
            super().__init__()
            self.composer = composer

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "ctrl+c":
            event.stop()
            event.prevent_default()
            self.post_message(self.InterruptRequested(self))
            return
        if event.key == "tab":
            event.stop()
            event.prevent_default()
            self.post_message(self.CompletionRequested(self))
            return
        if event.key == "up" and self.cursor_location[0] == 0:
            event.stop()
            event.prevent_default()
            self.post_message(self.HistoryPrevRequested(self))
            return
        if event.key == "down" and self.cursor_location[0] == self.document.line_count - 1:
            event.stop()
            event.prevent_default()
            self.post_message(self.HistoryNextRequested(self))
            return
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted(self))
            return
        if event.key.endswith("+enter") or event.key == "ctrl+j":
            # Ghostty (and other terminals without the Kitty keyboard protocol)
            # send Shift+Enter as a bare linefeed, which Textual reports as
            # "ctrl+j" rather than a distinguishable "shift+enter".
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        await super()._on_key(event)


CONNECTION_DISCONNECTED = "disconnected"
CONNECTION_CONNECTING = "connecting"
CONNECTION_RETRYING = "retrying"
CONNECTION_CONNECTED = "connected"
MAX_CONNECT_RETRY_DELAY = 8.0
RETRY_HINT = "The app remains open; retry when the endpoint recovers."
VOICE_READY = "ready"
VOICE_CONNECTING = "connecting…"
VOICE_RECONNECTING = "reconnecting…"
VOICE_DISCONNECTED = "disconnected"
VOICE_LISTENING = "listening…"
VOICE_TRANSCRIBING = "transcribing…"
VOICE_THINKING = "thinking…"
VOICE_SPEAKING = "speaking…"
VOICE_BUFFERING = "buffering…"
VOICE_INTERRUPTED = "interrupted"
VOICE_ERROR = "error"
PROMPT_NOT_SENT = "not-sent"
PROMPT_AMBIGUOUS = "ambiguous"
PROMPT_COMPLETED = "completed"
PROMPT_UNDONE = "undone"


def _write_new_text_file(path: Path, text: str) -> None:
    """Create a UTF-8 text file and fail safely if it already exists."""
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)


class HermesStreamingApp(App):
    """A Textual TUI for a Hermes voice-session chat."""

    CSS = """
    #voice-status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }

    #composer {
        height: 5;
        max-height: 10;
    }

    #queue-shelf {
        height: auto;
        max-height: 6;
        padding: 0 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("ctrl+r", "voice_turn", "Voice turn"),
        ("ctrl+c", "interrupt", "Interrupt"),
        ("f1", "show_help", "Help"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(
        self,
        args=None,
        session_factory: Optional[Callable[[], Any]] = None,
        command_dispatcher: Optional[Callable[[CommandInvocation], Awaitable[str] | str]] = None,
        argv: Optional[list[str]] = None,
    ) -> None:
        super().__init__()
        self.args = args
        # The argv used to resolve `args` at startup, kept so /reload can
        # re-resolve config-file/env-var defaults with the same CLI flags
        # still applied on top, instead of guessing at sys.argv again.
        self._argv = list(sys.argv[1:] if argv is None else argv)
        self._session_factory = session_factory
        self._command_dispatcher = command_dispatcher
        self.session: SessionProtocol = None  # type: ignore[assignment]
        self.player = PCMPlayer(
            enabled=not (args and args.no_play),
            output_device=getattr(args, "audio_output_device", None),
        )
        self.audio_input_device = getattr(args, "mic_input_device", None)
        self.transcript = TranscriptBuffer()
        self.show_transcript_details = not bool(getattr(args, "hide_thinking", False))
        self.voice_state = VOICE_READY
        self._turn_in_flight = False
        self._queued_prompts: list[str] = []
        self._staged_attachments: list[Attachment] = []
        self._active_turn_task: Optional[asyncio.Task[None]] = None
        self._voice_capture_task: Optional[asyncio.Task[str]] = None
        self._voice_capture_cancelled = False
        self._needs_reconnect = False
        self._last_prompt: Optional[str] = None
        self._last_prompt_status: Optional[str] = None
        self.connection_state = CONNECTION_DISCONNECTED
        self._connection_lock = asyncio.Lock()
        self.busy_mode = getattr(args, "busy_mode", "queue")
        if self.busy_mode not in config.BUSY_MODES:
            self.busy_mode = "queue"
        self._busy_transition_owner: Optional[asyncio.Task[None]] = None
        history_path = getattr(args, "history_path", None) or history_path_for_url(
            getattr(args, "url", None)
        )
        self._history = PromptHistory(history_path)
        self._history_index: Optional[int] = None
        self._history_draft = ""
        # Set when the user changes these interactively this session, so a later
        # /reload leaves the deliberate choice alone instead of clobbering it
        # with whatever the config file currently says.
        self._busy_mode_touched = False
        self._show_details_touched = False
        self._audio_input_touched = False
        self._audio_output_touched = False

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="transcript-scroll"):
            # markup=False so a literal "[error] ..." isn't eaten as Rich markup.
            yield Static("", id="transcript", markup=False)
        yield Static("● ready", id="voice-status")
        yield Static("", id="queue-shelf", markup=False)
        yield Static("", id="command-suggestions", markup=False)
        yield Composer(placeholder="you>", id="composer")
        yield Footer()

    # --- transcript rendering -------------------------------------------------

    @property
    def transcript_text(self) -> str:
        """Plain-text projection retained for diagnostics and test assertions."""
        return self.transcript.plain_text

    def _visible_transcript_text(self) -> str:
        """Return the same plain-text projection currently shown in the UI."""
        return self.transcript.plain_text_for(show_details=self.show_transcript_details)

    def _refresh_transcript(self) -> None:
        self.query_one("#transcript", Static).update(
            self.transcript.render(show_details=self.show_transcript_details)
        )
        self.query_one("#transcript-scroll", VerticalScroll).scroll_end(animate=False)

    def _append(self, text: str) -> None:
        """Append a streamed delta to the current typed message."""
        if not text:
            return
        self.transcript.append_stream(text)
        self._refresh_transcript()

    def _append_block(self, text: str, *, role: str = "system", detail: bool = False) -> None:
        """Append a complete typed message to the transcript."""
        self.transcript.add(role, text, detail=detail)
        self._refresh_transcript()

    def _set_voice_state(self, state: str) -> None:
        self.voice_state = state
        self.query_one("#voice-status", Static).update(f"● {state}")

    def _refresh_queue_shelf(self) -> None:
        try:
            widget = self.query_one("#queue-shelf", Static)
        except NoMatches:
            return
        if not self._queued_prompts:
            widget.update("")
            widget.display = False
            return
        entries = [
            f"{index}. {self._queue_preview(text)}"
            for index, text in enumerate(self._queued_prompts, start=1)
        ]
        widget.update(f"Queue ({len(self._queued_prompts)} queued):\n" + "\n".join(entries))
        widget.display = True

    # --- lifecycle ------------------------------------------------------------

    async def on_mount(self) -> None:
        self.session = self._session_factory() if self._session_factory else HermesSession(self.args)
        self._refresh_queue_shelf()
        self.query_one("#command-suggestions", Static).display = False
        self.set_focus(self.query_one("#composer", Composer))
        self._set_voice_state(VOICE_CONNECTING)
        # In a worker so a hanging endpoint can't freeze the UI (or block ctrl+q).
        self.run_worker(self._connect(force=True), exclusive=True)

    async def _connect(self, *, force: bool = False) -> bool:
        """Establish a session with bounded exponential-backoff retries."""
        async with self._connection_lock:
            if self.session.is_connected() and not force:
                self.connection_state = CONNECTION_CONNECTED
                self._set_voice_state(VOICE_READY)
                return True

            retries = max(0, int(getattr(self.args, "connect_retries", 3)))
            retry_delay = max(0.0, float(getattr(self.args, "connect_retry_delay", 1.0)))
            attempts = retries + 1
            reconnecting = self._needs_reconnect
            last_error: Exception = RuntimeError("unknown connection failure")

            for attempt in range(attempts):
                if attempt == 0:
                    self.connection_state = CONNECTION_CONNECTING
                    self._set_voice_state(
                        VOICE_RECONNECTING if reconnecting else VOICE_CONNECTING
                    )
                    if reconnecting:
                        self._append_block("reconnecting…")
                else:
                    self.connection_state = CONNECTION_RETRYING
                    self._set_voice_state(VOICE_RECONNECTING)
                    delay = min(retry_delay * (2 ** (attempt - 1)), MAX_CONNECT_RETRY_DELAY)
                    if delay:
                        self._append_block(
                            f"reconnecting… attempt {attempt + 1}/{attempts} in {delay:g}s"
                        )
                        await asyncio.sleep(delay)
                    else:
                        self._append_block(f"reconnecting… attempt {attempt + 1}/{attempts}")

                try:
                    hello = await self.session.connect()
                    if not self.session.is_connected():
                        raise ConnectionError("session did not establish a connection")
                except asyncio.CancelledError:
                    self.connection_state = CONNECTION_DISCONNECTED
                    self._set_voice_state(VOICE_DISCONNECTED)
                    raise
                except Exception as exc:
                    last_error = exc
                    self.connection_state = CONNECTION_DISCONNECTED
                    self._set_voice_state(VOICE_DISCONNECTED)
                    try:
                        await self.session.close()
                    except Exception:
                        pass
                    self._append_block(
                        f"[connection attempt {attempt + 1}/{attempts} failed: {exc}]"
                    )
                    continue

                self.connection_state = CONNECTION_CONNECTED
                self._set_voice_state(VOICE_READY)
                self._needs_reconnect = False
                session_id = getattr(self.args, "session_id", "session")
                self._append_block(f"Connected to {session_id} (chat {hello.get('chat_id')}).")
                return True

            self.connection_state = CONNECTION_DISCONNECTED
            self._set_voice_state(VOICE_DISCONNECTED)
            self._append_block(
                f"[error] {last_error}; unable to connect after {attempts} attempt(s)"
            )
            self._append_block(RETRY_HINT)
            return False

    async def on_unmount(self) -> None:
        if self.session is not None:
            await self.session.close()

    # --- input paths ----------------------------------------------------------

    async def on_composer_submitted(self, event: Composer.Submitted) -> None:
        text = event.text.strip()
        self._history_index = None
        self._history_draft = ""
        if not text:
            return
        invocation = parse_slash_command(text)
        if invocation is not None:
            event.composer.load_text("")
            self.run_worker(
                self._handle_command(invocation),
                name=f"command /{invocation.name or 'help'}",
                group="interaction",
                exit_on_error=False,
            )
            return
        self.run_worker(
            self._submit_text(text, composer=event.composer),
            name="chat turn",
            group="interaction",
            exit_on_error=False,
        )

    async def on_composer_completion_requested(self, event: Composer.CompletionRequested) -> None:
        path_candidates = complete_path_reference(event.text)
        if len(path_candidates) == 1:
            event.composer.load_text(path_candidates[0])
            event.composer.move_cursor((0, len(event.composer.text)))
            return
        candidates = complete_slash_command(event.text)
        if len(candidates) != 1:
            return
        event.composer.load_text(f"{candidates[0]} ")
        event.composer.move_cursor((0, len(event.composer.text)))

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "composer":
            self._update_command_suggestions(event.text_area.text)

    def _update_command_suggestions(self, text: str) -> None:
        try:
            widget = self.query_one("#command-suggestions", Static)
        except NoMatches:
            # A Changed message can still be in flight during app teardown,
            # after the widget it targets has already been unmounted.
            return
        if not text.startswith("/"):
            widget.display = False
            return
        body = text[1:]
        if any(character.isspace() for character in body):
            # Past the command name and into its arguments — narrow to that
            # one command's usage instead of hiding, so a command that takes
            # arguments (e.g. /busy) doesn't lose its hint the moment you've
            # typed the space.
            head_parts = body.split(None, 1)
            head = head_parts[0].lower() if head_parts else ""
            command = next(
                (
                    c
                    for c in COMMAND_REGISTRY
                    if c.name == head or head in c.aliases
                ),
                None,
            )
            if command is None or not command.args_hint:
                widget.display = False
                return
            widget.update(f"/{command.name} {command.args_hint} — {command.description}")
            widget.display = True
            return

        prefix = body.lower()
        matches = [
            command
            for command in COMMAND_REGISTRY
            if command.name.startswith(prefix)
            or any(alias.startswith(prefix) for alias in command.aliases)
        ]
        if not matches:
            widget.display = False
            return
        shown, overflow = matches[:6], matches[6:]
        lines = [
            f"/{command.name}{f' {command.args_hint}' if command.args_hint else ''}"
            f" — {command.description}"
            for command in shown
        ]
        if overflow:
            lines.append(f"… {len(overflow)} more")
        widget.update("\n".join(lines))
        widget.display = True

    def on_composer_history_prev_requested(self, event: Composer.HistoryPrevRequested) -> None:
        if not self._history.entries:
            return
        if self._history_index is None:
            self._history_draft = event.composer.text
            self._history_index = len(self._history.entries)
        if self._history_index == 0:
            return
        self._history_index -= 1
        self._load_history_entry(event.composer)

    def on_composer_history_next_requested(self, event: Composer.HistoryNextRequested) -> None:
        if self._history_index is None:
            return
        self._history_index += 1
        if self._history_index >= len(self._history.entries):
            self._history_index = None
            event.composer.load_text(self._history_draft)
            event.composer.move_cursor(event.composer.document.end)
            return
        self._load_history_entry(event.composer)

    def _load_history_entry(self, composer: "Composer") -> None:
        composer.load_text(self._history.entries[self._history_index])
        composer.move_cursor(composer.document.end)

    async def on_composer_interrupt_requested(self, event: Composer.InterruptRequested) -> None:
        self.run_worker(
            self.action_interrupt(),
            name="interrupt",
            group="interaction",
            exit_on_error=False,
        )

    async def _handle_command(self, invocation: CommandInvocation) -> None:
        command = invocation.command
        if command is None:
            await self._dispatch_command(invocation)
            return
        if command.name == "help":
            self._append_block(help_text(invocation.args))
        elif command.name == "clear":
            self.transcript.clear()
            self._refresh_transcript()
        elif command.name == "status":
            session_id = getattr(self.args, "session_id", "session")
            model = getattr(self.args, "model", None) or "default"
            config_path = getattr(self.args, "config", None)
            self._append_block(
                f"session: {session_id} · {self.connection_state} · model: {model} "
                f"· busy-mode: {self.busy_mode} · queued: {len(self._queued_prompts)} "
                f"· history: {self._history.path} · config: {config_path}"
            )
        elif command.name == "queue":
            await self._handle_queue_command(invocation.args)
        elif command.name == "busy":
            await self._handle_busy_command(invocation.args)
        elif command.name == "details":
            self._handle_details_command(invocation.args)
        elif command.name == "voice":
            if invocation.args:
                self._append_block("usage: /voice (capture one microphone turn)")
            else:
                await self._capture_voice_turn()
        elif command.name == "audio":
            await self._handle_audio_command(invocation.args)
        elif command.name == "image":
            await self._handle_image_command(invocation.args)
        elif command.name == "history":
            self._handle_history_command(invocation.args)
        elif command.name == "save":
            await self._handle_save_command(invocation.args)
        elif command.name == "copy":
            await self._handle_copy_command(invocation.args)
        elif command.name == "logs":
            self._handle_logs_command(invocation.args)
        elif command.name == "usage":
            self._handle_relay_unavailable(command.name, invocation.args)
        elif command.name == "retry":
            await self._handle_retry_command(invocation.args)
        elif command.name == "undo":
            self._handle_undo_command(invocation.args)
        elif command.name == "compress":
            self._handle_relay_unavailable(command.name, invocation.args)
        elif command.name == "reload":
            self._handle_reload_command()
        elif command.name == "quit":
            self.exit()
        else:
            await self._dispatch_command(invocation)

    async def _dispatch_command(self, invocation: CommandInvocation) -> None:
        if self._command_dispatcher is None:
            self._append_block(
                f"[error] /{invocation.name} needs Hermes gateway command dispatch; "
                "the voice-session channel does not expose it yet."
            )
            return
        try:
            result = self._command_dispatcher(invocation)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            self._append_block(f"[error] /{invocation.name}: {exc}")
            return
        if result:
            self._append_block(str(result))

    @staticmethod
    def _queue_preview(text: str) -> str:
        preview = " ↵ ".join(text.splitlines())
        if len(preview) > 80:
            preview = preview[:77] + "…"
        return repr(preview)

    def _enqueue_prompt(self, text: str) -> None:
        self._last_prompt = text
        self._last_prompt_status = PROMPT_NOT_SENT
        self._queued_prompts.append(text)
        self._append_block(f"queued[{len(self._queued_prompts)}]: {self._queue_preview(text)}")
        self._refresh_queue_shelf()

    def _queue_listing(self) -> str:
        if not self._queued_prompts:
            return "queue empty."
        entries = [
            f"{index}. {self._queue_preview(text)}"
            for index, text in enumerate(self._queued_prompts, start=1)
        ]
        return "Queued prompts:\n" + "\n".join(entries)

    def _queue_index(self, raw_index: str) -> Optional[int]:
        try:
            index = int(raw_index)
        except ValueError:
            self._append_block(f"invalid queue item: {raw_index!r}")
            return None
        if not 1 <= index <= len(self._queued_prompts):
            self._append_block(f"queue item must be between 1 and {len(self._queued_prompts)}")
            return None
        return index - 1

    async def _handle_queue_command(self, args: str) -> None:
        parts = args.strip().split(maxsplit=2)
        if not parts:
            self._append_block(self._queue_listing())
            return

        action = parts[0].lower()
        if action == "clear":
            count = len(self._queued_prompts)
            self._queued_prompts.clear()
            self._refresh_queue_shelf()
            self._append_block(f"cleared {count} queued prompt(s).")
            return
        if action in {"drop", "delete"}:
            if len(parts) != 2:
                self._append_block("usage: /queue drop <number>")
                return
            index = self._queue_index(parts[1])
            if index is not None:
                removed = self._queued_prompts.pop(index)
                self._refresh_queue_shelf()
                self._append_block(f"dropped: {self._queue_preview(removed)}")
            return
        if action == "edit":
            if len(parts) != 3:
                self._append_block("usage: /queue edit <number> <replacement>")
                return
            index = self._queue_index(parts[1])
            if index is not None:
                self._queued_prompts[index] = parts[2]
                self._refresh_queue_shelf()
                self._append_block(f"edited[{index + 1}]: {self._queue_preview(parts[2])}")
            return

        self._enqueue_prompt(args.strip())
        if not self._turn_in_flight:
            next_text = self._queued_prompts.pop(0)
            self._refresh_queue_shelf()
            self._append_block(f"starting queued: {self._queue_preview(next_text)}")
            await self._run_turn(next_text)

    async def _handle_busy_command(self, args: str) -> None:
        parts = args.strip().lower().split()
        if not parts:
            self._append_block(
                f"busy-mode: {self.busy_mode} (queue / steer / interrupt)"
            )
            return
        if len(parts) != 1 or parts[0] not in config.BUSY_MODES:
            self._append_block("usage: /busy [queue|steer|interrupt]")
            return
        previous = self.busy_mode
        self.busy_mode = parts[0]
        self._busy_mode_touched = True
        if previous == self.busy_mode:
            self._append_block(f"busy-mode already {self.busy_mode}.")
        else:
            self._append_block(f"busy-mode set to {self.busy_mode} (was {previous}).")

    def _handle_details_command(self, args: str) -> None:
        """Show or hide replaceable thinking and tool activity."""
        parts = args.strip().lower().split()
        if not parts:
            state = "shown" if self.show_transcript_details else "hidden"
            self._append_block(f"transcript details: {state}")
            return
        if len(parts) != 1 or parts[0] not in {"show", "hide"}:
            self._append_block("usage: /details [show|hide]")
            return
        self.show_transcript_details = parts[0] == "show"
        self._show_details_touched = True
        self._refresh_transcript()
        state = "shown" if self.show_transcript_details else "hidden"
        self._append_block(f"transcript details: {state}")

    def _handle_history_command(self, args: str) -> None:
        """Show or search persistent prompt history, most recent first."""
        needle = args.strip().lower()
        entries = list(enumerate(self._history.entries, start=1))
        if needle:
            entries = [(index, text) for index, text in entries if needle in text.lower()]
        if not entries:
            self._append_block("history: no matches" if needle else "history: empty")
            return
        recent = entries[-20:]
        heading = f"Prompt history matching {args.strip()!r}:" if needle else "Prompt history:"
        lines = [f"{index}. {self._queue_preview(text)}" for index, text in recent]
        self._append_block(heading + "\n" + "\n".join(lines))

    async def _handle_save_command(self, args: str) -> None:
        """Save the current visible transcript without overwriting a file."""
        if args.strip().count("\n"):
            self._append_block("usage: /save [path]")
            return
        text = self._visible_transcript_text()
        if not text:
            self._append_block("[error] /save: transcript is empty")
            return
        raw_path = args.strip()
        path = (
            Path(raw_path).expanduser()
            if raw_path
            else Path.cwd() / f"hermes-transcript-{datetime.now():%Y%m%d-%H%M%S}.txt"
        )
        try:
            await asyncio.to_thread(_write_new_text_file, path, text)
        except FileExistsError:
            self._append_block(
                f"[error] /save: {path} already exists; refusing to overwrite"
            )
        except OSError as exc:
            self._append_block(f"[error] /save {path}: {exc}")
        else:
            self._append_block(f"saved visible transcript to {path}")

    async def _handle_copy_command(self, args: str) -> None:
        """Copy the current visible transcript through the local clipboard."""
        if args.strip():
            self._append_block("usage: /copy")
            return
        text = self._visible_transcript_text()
        if not text:
            self._append_block("[error] /copy: transcript is empty")
            return
        try:
            await copy_text(text)
        except (ClipboardError, OSError) as exc:
            self._append_block(f"[error] /copy: {exc}")
        else:
            self._append_block("copied visible transcript to the system clipboard")

    def _handle_logs_command(self, args: str) -> None:
        """Show local diagnostic logging state without exposing log contents."""
        if args.strip():
            self._append_block("usage: /logs")
            return
        path = active_log_file()
        if path is None:
            self._append_block(
                "logs: debug logging is disabled; restart with --debug or --log-file PATH"
            )
            return
        state = "present" if path.exists() else "missing"
        self._append_block(f"logs: debug trace {state} at {path}")

    def _handle_relay_unavailable(self, command: str, args: str) -> None:
        """Report relay-owned commands that this protocol cannot provide."""
        if args.strip():
            self._append_block(f"usage: /{command}")
            return
        self._append_block(
            f"[error] /{command} is not exposed by the voice-session protocol; "
            "no request was sent."
        )

    def _remove_last_queued_prompt(self, prompt: str) -> bool:
        """Remove the newest matching queued prompt, preserving FIFO order."""
        for index in range(len(self._queued_prompts) - 1, -1, -1):
            if self._queued_prompts[index] == prompt:
                del self._queued_prompts[index]
                self._refresh_queue_shelf()
                return True
        return False

    async def _handle_retry_command(self, args: str) -> None:
        """Retry only a prompt proven not to have reached Hermes."""
        if args.strip():
            self._append_block("usage: /retry")
            return
        if self._turn_in_flight:
            self._append_block("[error] /retry unavailable while a turn is in flight")
            return
        prompt = self._last_prompt
        status = self._last_prompt_status
        if prompt is None or status is None:
            self._append_block("retry: no safely retryable prompt")
            return
        if status == PROMPT_AMBIGUOUS:
            self._append_block(
                "[error] /retry refused: the last prompt may have reached Hermes; "
                "it will not be replayed automatically."
            )
            return
        if status != PROMPT_NOT_SENT:
            self._append_block("retry: no safely retryable prompt")
            return
        self._remove_last_queued_prompt(prompt)
        self._append_block(f"retrying: {self._queue_preview(prompt)}")
        await self._run_turn(prompt)

    def _handle_undo_command(self, args: str) -> None:
        """Remove an unsent prompt locally; never imply remote undo."""
        if args.strip():
            self._append_block("usage: /undo")
            return
        if self._turn_in_flight:
            self._append_block("[error] /undo unavailable while a turn is in flight")
            return
        prompt = self._last_prompt
        status = self._last_prompt_status
        if status == PROMPT_NOT_SENT and prompt and prompt in self._queued_prompts:
            self._remove_last_queued_prompt(prompt)
            self.transcript.remove_last("user", prompt)
            self._refresh_transcript()
            self._last_prompt_status = PROMPT_UNDONE
            self._append_block(f"removed unsent prompt: {self._queue_preview(prompt)}")
            return
        if status == PROMPT_AMBIGUOUS:
            self._append_block(
                "[error] /undo unavailable: the last prompt may have reached Hermes; "
                "the relay exposes no undo operation."
            )
            return
        if status == PROMPT_COMPLETED:
            self._append_block(
                "[error] /undo unavailable: the last turn was sent and the relay "
                "exposes no undo operation."
            )
            return
        self._append_block(
            "undo: no unsent local prompt; the relay exposes no undo operation."
        )

    def _handle_reload_command(self) -> None:
        """Re-read the config file/environment without restarting the client."""
        try:
            new_args = config.build_arg_parser(self._argv).parse_args(self._argv)
        except SystemExit as exc:
            self._append_block(f"[error] /reload: {exc}")
            return

        self.args = new_args
        skipped: list[str] = []

        new_busy_mode = getattr(new_args, "busy_mode", "queue")
        if new_busy_mode not in config.BUSY_MODES:
            new_busy_mode = "queue"
        if self._busy_mode_touched:
            skipped.append("busy-mode")
        else:
            self.busy_mode = new_busy_mode

        new_show_details = not bool(getattr(new_args, "hide_thinking", False))
        if self._show_details_touched:
            skipped.append("show-details")
        else:
            if new_show_details != self.show_transcript_details:
                self.show_transcript_details = new_show_details
                self._refresh_transcript()

        if self._audio_input_touched:
            skipped.append("audio-input")
        else:
            self.audio_input_device = getattr(new_args, "mic_input_device", None)

        if self._audio_output_touched:
            skipped.append("audio-output")
        else:
            self.player.output_device = getattr(new_args, "audio_output_device", None)
        self.player.enabled = not bool(getattr(new_args, "no_play", False))

        message = f"config reloaded from {new_args.config}."
        if skipped:
            message += " kept session-set: " + ", ".join(skipped) + "."
        self._append_block(message)

    async def _handle_audio_command(self, args: str) -> None:
        """Show and change local input/output devices for this session."""
        parts = args.strip().split(maxsplit=1)
        action = parts[0].lower() if parts else "status"
        if action == "status":
            if len(parts) > 1:
                self._append_block("usage: /audio [list|status|input|output]")
                return
            self._append_block(
                "audio: "
                f"input={self._audio_device_label(self.audio_input_device)} · "
                f"output={self._audio_device_label(self.player.output_device)} · "
                f"state={self.voice_state}"
            )
            return
        if action == "list":
            if len(parts) > 1:
                self._append_block("usage: /audio list")
                return
            try:
                devices = audio_device_list()
            except Exception as exc:
                self._append_block(f"[error] audio devices: {exc}")
                return
            if not devices:
                self._append_block("audio devices: none detected")
                return
            lines = ["Audio devices:"]
            for device in devices:
                capabilities = []
                if device["inputs"]:
                    capabilities.append(f"input {device['inputs']}")
                if device["outputs"]:
                    capabilities.append(f"output {device['outputs']}")
                lines.append(
                    f"{device['index']}: {device['name']} ({', '.join(capabilities) or 'no I/O'})"
                )
            self._append_block("\n".join(lines))
            return
        if action not in {"input", "output"} or len(parts) != 2:
            self._append_block(
                "usage: /audio [list|status|input <device>|output <device>]"
            )
            return

        selector = config._device_selector(parts[1])
        if action == "input":
            setter = getattr(self.session, "set_input_device", None)
            try:
                if callable(setter):
                    result = setter(selector)
                    if inspect.isawaitable(result):
                        await result
                else:
                    setattr(self.session, "input_device", selector)
            except Exception as exc:
                self._append_block(f"[error] audio input device: {exc}")
                return
            self.audio_input_device = selector
            self._audio_input_touched = True
        else:
            self.player.output_device = selector
            self._audio_output_touched = True
        self._append_block(f"audio {action} device: {self._audio_device_label(selector)}")

    async def _handle_image_command(self, args: str) -> None:
        """Stage, inspect, or clear local image attachments."""
        parts = args.strip().split(maxsplit=1)
        if not parts:
            self._append_block("usage: /image <path>|list|clear")
            return

        action = parts[0].lower()
        if action == "list" and len(parts) == 1:
            if not self._staged_attachments:
                self._append_block("Staged attachments: none")
                return
            lines = ["Staged attachments:"]
            lines.extend(f"- {format_attachment_preview(item)}" for item in self._staged_attachments)
            self._append_block("\n".join(lines))
            return
        if action == "clear" and len(parts) == 1:
            count = len(self._staged_attachments)
            self._staged_attachments.clear()
            self._append_block(f"cleared {count} staged attachment(s).")
            return

        raw_path = args.strip()
        try:
            attachment = resolve_attachment(raw_path, image_only=True)
        except AttachmentError as exc:
            self._append_block(f"[error] image: {exc}")
            return
        if any(item.path == attachment.path for item in self._staged_attachments):
            self._append_block(f"image already staged: {format_attachment_preview(attachment)}")
            return
        self._staged_attachments.append(attachment)
        self._append_block(f"staged image: {format_attachment_preview(attachment)}")

    @staticmethod
    def _audio_device_label(device: int | str | None) -> str:
        return "default" if device is None else str(device)

    def action_voice_turn(self) -> None:
        """Start voice capture off the Textual message-pump path."""
        self.run_worker(
            self._capture_voice_turn(),
            name="voice turn",
            group="interaction",
            exit_on_error=False,
        )

    async def _capture_voice_turn(self) -> None:
        if self._turn_in_flight:
            self._append_block("[a turn is already in flight]")
            return
        self._set_voice_state(VOICE_LISTENING)
        self._voice_capture_cancelled = False
        capture_task = asyncio.create_task(asyncio.to_thread(self.session.capture_voice))
        self._voice_capture_task = capture_task
        try:
            transcript_text = await capture_task
        except asyncio.CancelledError:
            if self._voice_capture_cancelled:
                return
            raise
        except Exception as exc:
            self._set_voice_state(VOICE_ERROR)
            self._append_block(f"[error] microphone: {exc}")
            return
        finally:
            if self._voice_capture_task is capture_task:
                self._voice_capture_task = None
            self._voice_capture_cancelled = False
        if self.voice_state == VOICE_INTERRUPTED:
            return
        if not transcript_text:
            self._set_voice_state(VOICE_READY)
            self._append_block("no speech detected.")
            return
        self._set_voice_state(VOICE_TRANSCRIBING)
        await self._run_turn(transcript_text, stt_source="local-faster-whisper")

    async def action_interrupt(self) -> None:
        if await self._cancel_active_voice_capture():
            return
        if await self._interrupt_active_turn():
            return

        composer = self.query_one("#composer", Composer)
        if composer.text or self._staged_attachments:
            had_draft = bool(composer.text)
            attachment_count = len(self._staged_attachments)
            composer.load_text("")
            self._staged_attachments.clear()
            if had_draft and attachment_count:
                self._append_block(
                    f"draft and {attachment_count} staged attachment(s) cleared."
                )
            elif had_draft:
                self._append_block("draft cleared.")
            else:
                self._append_block(f"cleared {attachment_count} staged attachment(s).")
            return
        if self._queued_prompts:
            count = len(self._queued_prompts)
            self._queued_prompts.clear()
            self._refresh_queue_shelf()
            self._append_block(f"cleared {count} queued prompt(s).")
            return
        self.exit()

    async def _cancel_active_voice_capture(self) -> bool:
        """Stop microphone capture without treating Ctrl+C as an idle exit."""
        capture_task = self._voice_capture_task
        if capture_task is None or capture_task.done():
            return False

        self._voice_capture_cancelled = True
        self._set_voice_state(VOICE_INTERRUPTED)
        cancel = getattr(self.session, "cancel_voice", None)
        if callable(cancel):
            await asyncio.to_thread(cancel)
        else:
            capture_task.cancel()
        try:
            await capture_task
        except asyncio.CancelledError:
            pass
        return True

    async def _interrupt_active_turn(self) -> bool:
        """Cancel local consumption and reset the stream before reuse.

        The current voice-session protocol has no interrupt operation. Closing
        the connection is the safe client-side fallback: it prevents late
        events from the canceled turn being consumed as the next turn's data.
        """
        if not self._turn_in_flight:
            return False

        self._set_voice_state(VOICE_INTERRUPTED)
        await self._close_player()
        active_task = self._active_turn_task
        current_task = asyncio.current_task()
        if active_task is not None and active_task is not current_task and not active_task.done():
            active_task.cancel()
            try:
                await active_task
            except asyncio.CancelledError:
                pass
        elif self._turn_in_flight:
            self._append_block("[interrupted]")
            self._turn_in_flight = False

        try:
            await self.session.close()
        except Exception as exc:
            self._append_block(f"[error] interrupt cleanup: {exc}")
        self.connection_state = CONNECTION_DISCONNECTED
        self._needs_reconnect = True
        return True

    def _shell_policy(self) -> ShellPolicy:
        return ShellPolicy(enabled=bool(getattr(self.args, "allow_shell", False)))

    async def _submit_text(self, text: str, *, composer: Optional[Composer] = None) -> None:
        """Prepare local references, then apply the busy-turn policy."""
        history_text = text
        local_command = standalone_command(text)
        try:
            if local_command is not None:
                result = await run_command(
                    local_command,
                    policy=self._shell_policy(),
                    cwd=Path.cwd(),
                )
                output = result.output.rstrip("\r\n") or "(no output)"
                if result.returncode != 0:
                    raise ShellExecutionError(
                        f"{local_command!r} exited with status {result.returncode}: {output}"
                    )
                self._append_block(f"shell: {local_command}\n{output}")
                if composer is not None:
                    composer.load_text("")
                return

            attachments = list(self._staged_attachments)
            attachments.extend(
                item
                for item in find_inline_attachments(text, cwd=Path.cwd())
                if item.path not in {staged.path for staged in attachments}
            )
            if attachments:
                lines = ["Attachments prepared:"]
                lines.extend(f"- {format_attachment_preview(item)}" for item in attachments)
                lines.append("[error] relay does not support attachments; prompt not sent.")
                self._append_block("\n".join(lines))
                return

            shell_commands = interpolation_commands(text)
            prepared_text = await interpolate_commands(
                text,
                policy=self._shell_policy(),
                cwd=Path.cwd(),
            )
            if shell_commands:
                self._append_block(
                    "shell interpolation: "
                    + ", ".join(f"{{!{command}}}" for command in shell_commands)
                )
        except AttachmentError as exc:
            self._append_block(f"[error] attachment: {exc}")
            return
        except ShellExecutionError as exc:
            self._append_block(f"[error] shell: {exc}")
            return

        text = prepared_text
        if composer is not None:
            composer.load_text("")
        self._history.append(history_text)

        current_task = asyncio.current_task()
        while self._busy_transition_owner is not None:
            await asyncio.sleep(0)

        if not self._turn_in_flight:
            if self._queued_prompts:
                self._enqueue_prompt(text)
                next_text = self._queued_prompts.pop(0)
                self._refresh_queue_shelf()
                self._append_block(f"starting queued: {self._queue_preview(next_text)}")
                await self._run_turn(next_text)
                return
            await self._run_turn(text)
            return
        if self.busy_mode == "queue":
            self._enqueue_prompt(text)
            return

        # Interrupt and steer both need to reset the stream before another
        # reader can touch the socket. The owner guard closes the tiny window
        # between canceling the old task and starting the replacement.
        self._busy_transition_owner = current_task
        try:
            await self._interrupt_active_turn()
            if self.busy_mode == "steer":
                await self._run_turn(text)
        finally:
            if self._busy_transition_owner is current_task:
                self._busy_transition_owner = None

    async def action_show_help(self) -> None:
        self._append_block(
            "Bindings: enter = send, shift+enter / alt+enter = newline, "
            "up/down at the top/bottom line = prompt history, "
            "ctrl+r = voice turn, ctrl+c = interrupt, f1 = help, ctrl+q = quit. "
            f"busy-mode = {self.busy_mode} (queue / steer / interrupt); "
            "use /busy to change it."
        )

    # --- the turn loop --------------------------------------------------------

    async def _run_turn(self, text: str, *, stt_source: str = "local") -> None:
        if self._turn_in_flight:
            # Keep one websocket reader while preserving text submitted during
            # a response. The active turn drains this FIFO after it completes.
            self._last_prompt = text
            self._last_prompt_status = PROMPT_NOT_SENT
            self._enqueue_prompt(text)
            return
        current_task = asyncio.current_task()
        self._active_turn_task = current_task
        self._turn_in_flight = True
        if self._busy_transition_owner is current_task:
            self._busy_transition_owner = None
        try:
            next_text: Optional[str] = text
            next_stt_source = stt_source
            while next_text is not None:
                turn_was_sent = await self._run_single_turn(next_text, stt_source=next_stt_source)
                if not turn_was_sent:
                    self._queued_prompts.insert(0, next_text)
                    self._refresh_queue_shelf()
                    self._append_block(
                        f"queued until connection recovers: {self._queue_preview(next_text)}"
                    )
                    break
                if not self._queued_prompts:
                    break
                next_text = self._queued_prompts.pop(0)
                self._refresh_queue_shelf()
                next_stt_source = "local"
                self._append_block(f"dequeued: {self._queue_preview(next_text)}")
        finally:
            self._turn_in_flight = False
            if self._active_turn_task is current_task:
                self._active_turn_task = None

    async def _run_single_turn(self, text: str, *, stt_source: str) -> bool:
        self._last_prompt = text
        self._last_prompt_status = PROMPT_NOT_SENT
        diagnostic_logger.debug(
            "app.turn.start index=%s stt_source=%s %s",
            getattr(self.session, "turn_index", "?"),
            stt_source,
            summarize_text(text),
        )
        if not self.session.is_connected():
            if not await self._connect():
                self._append_block(f"you> {text}")
                self._append_block("[error] not connected; prompt kept in queue")
                return False

        index = self.session.turn_index
        self._append_block(text, role="user")
        # send_turn may have placed the request on the wire before its async
        # stream reports an error, so every post-user-display failure is
        # intentionally treated as ambiguous and is never auto-replayed.
        self._last_prompt_status = PROMPT_AMBIGUOUS
        if stt_source != "local-faster-whisper":
            self._set_voice_state(VOICE_THINKING)
        timeout = getattr(self.args, "turn_timeout", 0) or 0
        try:
            events = self.session.send_turn(text, stt_source=stt_source)
            if timeout > 0:
                await asyncio.wait_for(self._consume_turn(events, index), timeout)
            else:
                await self._consume_turn(events, index)
            self._last_prompt_status = PROMPT_COMPLETED
        except asyncio.CancelledError:
            self._set_voice_state(VOICE_INTERRUPTED)
            self._append_block("[interrupted]")
            self.connection_state = CONNECTION_DISCONNECTED
            self._needs_reconnect = True
            raise
        except (asyncio.TimeoutError, TimeoutError):
            self._set_voice_state(VOICE_ERROR)
            await self._mark_connection_lost()
            self._append_block(
                f"[error] voice turn exceeded {timeout:g}s without completing; "
                "the remote model may be stalled. Start a fresh session and retry."
            )
        except Exception as exc:
            # ConnectionClosed, ConcurrencyError, AttributeError from a dead
            # socket — none of them should take the whole app down.
            await self._mark_connection_lost()
            self._set_voice_state(VOICE_ERROR)
            self._append_block(f"[error] {exc}")
            self._append_block(RETRY_HINT)
        finally:
            # Always tear the stream down; leaving it open leaked a
            # sounddevice stream per failed turn.
            await self._close_player()
            diagnostic_logger.debug(
                "app.turn.finish index=%s transcript_chars=%d connection=%s",
                index,
                len(self.transcript_text),
                self.connection_state,
            )
        return True

    async def _mark_connection_lost(self) -> None:
        """Close a failed stream so the next turn cannot reuse a dead socket."""
        self.connection_state = CONNECTION_DISCONNECTED
        self._set_voice_state(VOICE_DISCONNECTED)
        self._needs_reconnect = True
        try:
            await self.session.close()
        except Exception as exc:
            self._append_block(f"[error] reconnect cleanup: {exc}")

    async def _close_player(self) -> None:
        """Stop playback without blocking Textual's event loop.

        sounddevice's ``stop`` may wait for the device buffer to drain. That
        wait must not prevent transcript refreshes, especially the reasoning
        preview that is meant to remain visible while a reply is spoken.
        """
        await asyncio.to_thread(self.player.close)

    async def _consume_turn(self, events: AsyncIterator[dict[str, Any]], index: int) -> None:
        audio = bytearray()
        audio_format: Optional[tuple[int, int, int]] = None
        audio_file = bytearray()
        audio_file_format: Optional[tuple[int, int, int]] = None
        played_live = False
        playback_failed = False
        assistant_started = False
        last_status: Optional[str] = None
        thinking_started_at: Optional[float] = None
        thinking_preview = ""
        thinking_preview_truncated = False
        thinking_activity_active = False
        thinking_summary_added = False

        def update_thinking(text: Optional[str] = None) -> None:
            nonlocal thinking_started_at, thinking_preview
            nonlocal thinking_preview_truncated, thinking_activity_active
            if thinking_started_at is None:
                thinking_started_at = time.monotonic()
            chunk = str(text or "")
            if chunk.strip():
                combined = thinking_preview + chunk
                thinking_preview = combined[:160]
                thinking_preview_truncated = len(combined) > len(thinking_preview)
            preview = thinking_preview.strip()
            if preview:
                if thinking_preview_truncated:
                    preview += "…"
                set_activity(f"thinking: {preview}", role="thinking")
            else:
                set_activity("thinking…", role="thinking")
            thinking_activity_active = True

        def complete_thinking() -> None:
            nonlocal thinking_summary_added, thinking_activity_active
            if thinking_started_at is None or thinking_summary_added:
                return
            elapsed = max(0, int(time.monotonic() - thinking_started_at + 0.5))
            summary = f"thought for {elapsed}s"
            if thinking_activity_active:
                set_activity(summary, role="thinking")
            else:
                self._append_block(f"[{summary}]", role="thinking", detail=True)
            thinking_summary_added = True
            thinking_activity_active = False

        def set_activity(text: str, *, role: str = "status") -> None:
            if not text:
                return
            rendered = f"[{text}]"
            self.transcript.set_activity(rendered, role=role)
            self._refresh_transcript()

        async for event in events:
            kind = event["type"]
            diagnostic_logger.debug(
                "app.event kind=%s %s",
                kind,
                summarize_payload(event),
            )
            if kind in {"text_delta", "text_replace"}:
                if not assistant_started:
                    complete_thinking()
                    self._set_voice_state(VOICE_THINKING)
                    self.transcript.start_stream("assistant")
                    assistant_started = True
                if kind == "text_replace":
                    self.transcript.replace_stream(event["text"])
                    self._refresh_transcript()
                else:
                    self._append(event["text"])
            elif kind == "thinking_delta":
                self._set_voice_state(VOICE_THINKING)
                if not assistant_started:
                    update_thinking(event.get("text"))
            elif kind == "reasoning_available":
                self._set_voice_state(VOICE_THINKING)
                if not assistant_started:
                    update_thinking(event.get("text"))
            elif kind == "status":
                status_text = str(event.get("text") or "").strip()
                if status_text and status_text != last_status:
                    last_status = status_text
                    self._set_voice_state(status_text)
                    if assistant_started:
                        self._append_block(f"[{status_text}]", role="status")
                    elif not (
                        thinking_activity_active
                        and status_text.lower() in {"thinking", "thinking…", "reasoning"}
                    ):
                        thinking_activity_active = False
                        set_activity(status_text, role="status")
            elif kind == "notification":
                thinking_activity_active = False
                self._append_block(f"notification: {event['text']}", role="notification")
            elif kind == "notification_clear":
                thinking_activity_active = False
                set_activity("notification cleared", role="notification")
            elif kind == "tool_start":
                self._set_voice_state(VOICE_THINKING)
                thinking_activity_active = False
                set_activity(f"tool: {event.get('name') or 'tool'}…", role="tool")
            elif kind == "tool_progress":
                self._set_voice_state(VOICE_THINKING)
                thinking_activity_active = False
                name = event.get("name") or "tool"
                preview = str(event.get("preview") or "working…").strip()
                set_activity(f"tool: {name} — {preview}", role="tool")
            elif kind == "tool_complete":
                name = event.get("name") or "tool"
                thinking_activity_active = False
                set_activity(
                    f"tool: {name} {'✗' if event.get('error') else '✓'}", role="tool"
                )
            elif kind == "background_complete":
                text = str(event.get("text") or "background task complete").strip()
                self._append_block(f"background: {text}", role="background")
            elif kind == "unknown_event":
                event_type = event.get("event_type") or "missing"
                thinking_activity_active = False
                self._append_block(
                    f"[unhandled server event: {event_type}]", role="error"
                )
            elif kind == "audio_start":
                audio_format = (event["sample_rate"], event["channels"], event["sample_width"])
                self.player.start(audio_format)
                playback_failed = playback_failed or bool(self.player.failure)
                played_live = played_live or self.player.active
                if self.player.active:
                    self._set_voice_state(VOICE_SPEAKING)
                elif self.player.failure:
                    self._set_voice_state(VOICE_BUFFERING)
                else:
                    self._set_voice_state(VOICE_BUFFERING)
            elif kind == "audio_chunk":
                audio.extend(event["data"])
                if self.player.active:
                    await asyncio.to_thread(self.player.write, event["data"])
                playback_failed = playback_failed or bool(self.player.failure)
            elif kind == "audio_end":
                # Each prior chunk has completed its worker-thread write when
                # this event arrives, so closing here drains the final tail
                # before turn_end is processed.
                await self._close_player()
            elif kind == "audio_file_start":
                audio_file.clear()
                metadata = tuple(
                    event.get(field)
                    for field in ("sample_rate", "channels", "sample_width")
                )
                if all(value is not None for value in metadata):
                    audio_file_format = (int(metadata[0]), int(metadata[1]), int(metadata[2]))
                else:
                    audio_file_format = None
                self._set_voice_state(VOICE_BUFFERING)
            elif kind == "audio_file_chunk":
                audio_file.extend(event["data"])
            elif kind == "audio_file_end":
                if event.get("data"):
                    audio_file.extend(event["data"])
                try:
                    file_audio, file_format = read_wav(bytes(audio_file))
                except ValueError:
                    if audio_file_format is None:
                        self._append_block("[error] unsupported audio file fallback")
                        continue
                    file_audio, file_format = bytes(audio_file), audio_file_format
                audio.extend(file_audio)
                audio_format = file_format
                self.player.start(file_format)
                playback_failed = playback_failed or bool(self.player.failure)
                played_live = played_live or self.player.active
                if self.player.active:
                    self._set_voice_state(VOICE_SPEAKING)
                    await asyncio.to_thread(self.player.write, file_audio)
                    playback_failed = playback_failed or bool(self.player.failure)
                    await self._close_player()
                elif self.player.failure:
                    self._set_voice_state(VOICE_BUFFERING)
            elif kind == "error":
                self._set_voice_state(VOICE_ERROR)
                thinking_activity_active = False
                self._append_block(f"[error] {event['error']}", role="error")
            elif kind == "turn_end":
                complete_thinking()
                self.transcript.finish_stream()
                self._save_turn_audio(
                    bytes(audio),
                    audio_format,
                    index,
                    event.get("turn_id", ""),
                    played_live,
                    playback_failed,
                )
                self._set_voice_state(VOICE_READY)

    def _save_turn_audio(
        self,
        audio: bytes,
        audio_format: Optional[tuple[int, int, int]],
        index: int,
        turn_id: str,
        played_live: bool,
        playback_failed: bool,
    ) -> None:
        """Write the turn's PCM out as a WAV when asked to, or as a safety net
        when playback never went live — same rule as the reference script."""
        base = getattr(self.args, "output", None)
        if not (audio and audio_format and (base or not played_live or playback_failed)):
            return
        output = audio_path(base, index, turn_id or "turn")
        try:
            write_wav(output, audio, audio_format)
        except OSError as exc:
            self._append_block(f"[error] could not write {output}: {exc}")
            return
        self._append_block(f"audio: {output} ({len(audio)} PCM bytes)")


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        from setup_wizard import run_setup

        return run_setup(sys.argv[2:])
    parser = config.build_arg_parser()
    args = parser.parse_args()
    config.ensure_default_config_file(args.config)
    if args.log_file is not None:
        args.debug = True
    log_path = config.configure_logging(debug=args.debug, log_file=args.log_file)
    if log_path is not None:
        diagnostic_logger.info("app.start url=%s", args.url.split("?", 1)[0])
    app = HermesStreamingApp(args=args)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
