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
import threading
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Protocol

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, OptionList, Static, TextArea
from textual.widgets.option_list import Option

import config
from audio import PCMPlayer, audio_device_list, audio_path, read_wav, write_wav
from client import send_hello, send_turn
from commands import (
    COMMAND_REGISTRY,
    Command,
    CommandInvocation,
    complete_slash_command,
    help_text,
    parse_slash_command,
)
from diagnostics import logger as diagnostic_logger, summarize_payload, summarize_text
from history import PromptHistory, history_path_for_url
from mic import cancel_microphone, load_microphone_class, make_recorder_factory
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

    class CommandPaletteRequested(Message):
        """Open the command palette when a slash starts a draft."""

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
        if event.character == "/" and not self.text:
            event.stop()
            event.prevent_default()
            self.post_message(self.CommandPaletteRequested(self))
            return
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


class CommandPalette(ModalScreen[Optional[Command]]):
    """Claude-style searchable command chooser for the local registry."""

    CSS = """
    CommandPalette {
        align: center middle;
        background: transparent;
    }

    #command-palette {
        width: 72;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }

    #command-filter {
        margin: 1 0;
    }

    #command-options {
        height: auto;
        max-height: 16;
        min-height: 3;
    }

    #command-details {
        height: 2;
        margin-top: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [("escape", "close_palette", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self._commands: list[Command] = []

    def compose(self) -> ComposeResult:
        with Container(id="command-palette"):
            yield Static("Commands", id="command-title")
            yield Input(placeholder="Filter commands…", id="command-filter")
            yield OptionList(id="command-options")
            yield Static("↑↓ navigate · Enter select · Esc close", id="command-details")

    def on_mount(self) -> None:
        self._refresh_options("")
        self.set_focus(self.query_one("#command-filter", Input))

    def _refresh_options(self, filter_text: str) -> None:
        needle = filter_text.strip().lower()
        self._commands = [
            command
            for command in COMMAND_REGISTRY
            if not needle
            or needle in command.name.lower()
            or needle in command.description.lower()
        ]
        options = [
            Option(self._option_label(command), id=command.name)
            for command in self._commands
        ]
        option_list = self.query_one("#command-options", OptionList)
        option_list.set_options(options)
        if options:
            option_list.highlighted = 0
            self._update_details(0)
        else:
            self.query_one("#command-details", Static).update(
                "No matching commands. Press Esc to close."
            )

    @staticmethod
    def _option_label(command: Command) -> str:
        args = f" {command.args_hint}" if command.args_hint else ""
        return f"/{command.name}{args} — {command.description}"

    def _update_details(self, index: int) -> None:
        if not 0 <= index < len(self._commands):
            return
        command = self._commands[index]
        args = f" {command.args_hint}" if command.args_hint else ""
        self.query_one("#command-details", Static).update(
            f"/{command.name}{args}: {command.description}"
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "command-filter":
            self._refresh_options(event.value)

    def on_key(self, event: events.Key) -> None:
        if event.key not in {"up", "down"}:
            return
        command_filter = self.query_one("#command-filter", Input)
        if self.focused is not command_filter:
            return
        option_list = self.query_one("#command-options", OptionList)
        if not option_list.option_count:
            return
        event.stop()
        event.prevent_default()
        self.set_focus(option_list)
        option_list.highlighted = (
            0 if event.key == "down" else option_list.option_count - 1
        )

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._update_details(event.option_index)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self._commands):
            self.dismiss(self._commands[event.option_index])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        option_list = self.query_one("#command-options", OptionList)
        if option_list.highlighted is not None and option_list.highlighted < len(self._commands):
            self.dismiss(self._commands[option_list.highlighted])

    def action_close_palette(self) -> None:
        self.dismiss(None)


class SessionProtocol(Protocol):
    """What `app.py` needs from a session — implemented by `HermesSession`
    and by the test doubles, so there is exactly one code path here."""

    turn_index: int

    async def connect(self) -> dict[str, Any]: ...

    def is_connected(self) -> bool: ...

    def send_turn(self, text: str, *, stt_source: str = "local") -> AsyncIterator[dict[str, Any]]: ...

    def capture_voice(self) -> str: ...

    def cancel_voice(self) -> None: ...

    async def set_input_device(self, device: int | str | None) -> None: ...

    async def close(self) -> None: ...


class HermesSession:
    """Owns one open websocket connection and turn history for the app's lifetime."""

    def __init__(self, args) -> None:
        self.args = args
        self.ws: Any = None
        self._connect_cm: Any = None
        self.turn_index = 0
        self.microphone: Any = None
        self.input_device = getattr(args, "mic_input_device", None)
        self._voice_cancel_requested = threading.Event()

    async def connect(self) -> dict[str, Any]:
        if self._connect_cm is not None or self.ws is not None:
            await self.close()
        connect = config.connect_factory()
        token = config._resolve_token(self.args.token, self.args.profile_env)
        if not token:
            raise RuntimeError("No voice-session token found. Set VOICE_SESSION_TOKEN or use the profile .env.")
        kwargs = config._connection_kwargs(connect, token)
        diagnostic_logger.debug(
            "connect.start url=%s session_id=%s client_id=%s device_id=%s",
            self.args.url.split("?", 1)[0],
            self.args.session_id,
            self.args.client_id,
            self.args.device_id,
        )
        try:
            self._connect_cm = connect(self.args.url, **kwargs)
            self.ws = await self._connect_cm.__aenter__()
            hello = await send_hello(
                self.ws,
                client_id=self.args.client_id,
                device_id=self.args.device_id,
                session_id=self.args.session_id,
                display_name=self.args.display_name,
            )
            diagnostic_logger.debug(
                "connect.hello_ack keys=%s chat_id_present=%s",
                ",".join(sorted(str(key) for key in hello)),
                bool(hello.get("chat_id")),
            )
            return hello
        except BaseException as exc:
            diagnostic_logger.error("connect.failed type=%s", type(exc).__name__)
            try:
                await self.close()
            except Exception:
                pass
            raise

    def is_connected(self) -> bool:
        return self.ws is not None

    async def close(self) -> None:
        self.cancel_voice()
        microphone = self.microphone
        self.microphone = None
        if microphone is not None:
            await asyncio.to_thread(microphone.close)
        if self._connect_cm is not None:
            try:
                await self._connect_cm.__aexit__(None, None, None)
            finally:
                self._connect_cm = None
                self.ws = None

    def send_turn(self, text: str, *, stt_source: str = "local"):
        # turn_index stays 0-based for the first turn, matching the reference
        # script's `index` — _audio_path only adds a suffix from index 1 on.
        self.turn_index += 1
        diagnostic_logger.debug(
            "session.turn index=%d stt_source=%s %s",
            self.turn_index,
            stt_source,
            summarize_text(text),
        )
        return send_turn(self.ws, session_id=self.args.session_id, text=text, stt_source=stt_source)

    def capture_voice(self) -> str:
        self._voice_cancel_requested.clear()
        if self.microphone is None:
            microphone_class = load_microphone_class(self.args.checkout)
            self.microphone = microphone_class(
                max_seconds=self.args.mic_max_seconds,
                silence_duration=self.args.mic_silence_duration,
                silence_threshold=self.args.mic_silence_threshold,
                model=self.args.stt_model,
                recorder_factory=make_recorder_factory(
                    self.input_device,
                    self._voice_cancel_requested,
                ),
            )
        return self.microphone.capture()

    def cancel_voice(self) -> None:
        self._voice_cancel_requested.set()
        if self.microphone is not None:
            cancel_microphone(self.microphone)

    async def set_input_device(self, device: int | str | None) -> None:
        """Select the input device for subsequent microphone captures."""
        if self.input_device == device:
            return
        self.cancel_voice()
        microphone = self.microphone
        self.microphone = None
        self.input_device = device
        if microphone is not None:
            await asyncio.to_thread(microphone.close)


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
        self._active_turn_task: Optional[asyncio.Task[None]] = None
        self._voice_capture_task: Optional[asyncio.Task[str]] = None
        self._voice_capture_cancelled = False
        self._needs_reconnect = False
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
        yield Composer(placeholder="you>", id="composer")
        yield Footer()

    # --- transcript rendering -------------------------------------------------

    @property
    def transcript_text(self) -> str:
        """Plain-text projection retained for diagnostics and test assertions."""
        return self.transcript.plain_text

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

    # --- lifecycle ------------------------------------------------------------

    async def on_mount(self) -> None:
        self.session = self._session_factory() if self._session_factory else HermesSession(self.args)
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
        event.composer.load_text("")
        self._history_index = None
        self._history_draft = ""
        if not text:
            return
        invocation = parse_slash_command(text)
        if invocation is not None:
            self.run_worker(
                self._handle_command(invocation),
                name=f"command /{invocation.name or 'help'}",
                group="interaction",
                exit_on_error=False,
            )
            return
        self._history.append(text)
        self.run_worker(
            self._submit_text(text),
            name="chat turn",
            group="interaction",
            exit_on_error=False,
        )

    async def on_composer_completion_requested(self, event: Composer.CompletionRequested) -> None:
        candidates = complete_slash_command(event.text)
        if not candidates:
            return
        if len(candidates) == 1:
            event.composer.load_text(f"{candidates[0]} ")
            event.composer.move_cursor((0, len(event.composer.text)))
            return
        self._append_block("commands: " + ", ".join(candidates))

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

    def on_composer_command_palette_requested(
        self, event: Composer.CommandPaletteRequested
    ) -> None:
        event.composer.load_text("/")
        self.push_screen(CommandPalette(), self._command_palette_closed)

    def _command_palette_closed(self, command: Optional[Command]) -> None:
        composer = self.query_one("#composer", Composer)
        self.set_focus(composer)
        if command is None:
            return
        composer.load_text(f"/{command.name} ")
        composer.move_cursor((0, len(composer.text)))

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
            if invocation.name == "steer":
                self._append_block(
                    "[deprecated] /steer is no longer a command; set "
                    "--busy-mode steer and submit the replacement normally."
                )
                return
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
        elif command.name == "history":
            self._handle_history_command(invocation.args)
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
        self._queued_prompts.append(text)
        self._append_block(f"queued[{len(self._queued_prompts)}]: {self._queue_preview(text)}")

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
            self._append_block(f"cleared {count} queued prompt(s).")
            return
        if action in {"drop", "delete"}:
            if len(parts) != 2:
                self._append_block("usage: /queue drop <number>")
                return
            index = self._queue_index(parts[1])
            if index is not None:
                removed = self._queued_prompts.pop(index)
                self._append_block(f"dropped: {self._queue_preview(removed)}")
            return
        if action == "edit":
            if len(parts) != 3:
                self._append_block("usage: /queue edit <number> <replacement>")
                return
            index = self._queue_index(parts[1])
            if index is not None:
                self._queued_prompts[index] = parts[2]
                self._append_block(f"edited[{index + 1}]: {self._queue_preview(parts[2])}")
            return

        self._enqueue_prompt(args.strip())
        if not self._turn_in_flight:
            next_text = self._queued_prompts.pop(0)
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
        if composer.text:
            composer.load_text("")
            self._append_block("draft cleared.")
            return
        if self._queued_prompts:
            count = len(self._queued_prompts)
            self._queued_prompts.clear()
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
        self.player.close()
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

    async def _submit_text(self, text: str) -> None:
        """Apply the configured busy-turn policy to an ordinary message."""
        current_task = asyncio.current_task()
        while self._busy_transition_owner is not None:
            await asyncio.sleep(0)

        if not self._turn_in_flight:
            if self._queued_prompts:
                self._enqueue_prompt(text)
                next_text = self._queued_prompts.pop(0)
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
                    self._append_block(
                        f"queued until connection recovers: {self._queue_preview(next_text)}"
                    )
                    break
                if not self._queued_prompts:
                    break
                next_text = self._queued_prompts.pop(0)
                next_stt_source = "local"
                self._append_block(f"dequeued: {self._queue_preview(next_text)}")
        finally:
            self._turn_in_flight = False
            if self._active_turn_task is current_task:
                self._active_turn_task = None

    async def _run_single_turn(self, text: str, *, stt_source: str) -> bool:
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
        if stt_source != "local-faster-whisper":
            self._set_voice_state(VOICE_THINKING)
        timeout = getattr(self.args, "turn_timeout", 0) or 0
        try:
            events = self.session.send_turn(text, stt_source=stt_source)
            if timeout > 0:
                await asyncio.wait_for(self._consume_turn(events, index), timeout)
            else:
                await self._consume_turn(events, index)
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
            self.player.close()
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

    async def _consume_turn(self, events: AsyncIterator[dict[str, Any]], index: int) -> None:
        audio = bytearray()
        audio_format: Optional[tuple[int, int, int]] = None
        audio_file = bytearray()
        audio_file_format: Optional[tuple[int, int, int]] = None
        played_live = False
        playback_failed = False
        assistant_started = False
        last_status: Optional[str] = None

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
                set_activity("thinking…", role="thinking")
            elif kind == "reasoning_available":
                self._set_voice_state(VOICE_THINKING)
                set_activity("reasoning available", role="thinking")
            elif kind == "status":
                status_text = str(event.get("text") or "").strip()
                if status_text and status_text != last_status:
                    last_status = status_text
                    self._set_voice_state(status_text)
                    if assistant_started:
                        self._append_block(f"[{status_text}]", role="status")
                    else:
                        set_activity(status_text, role="status")
            elif kind == "notification":
                self._append_block(f"notification: {event['text']}", role="notification")
            elif kind == "notification_clear":
                set_activity("notification cleared", role="notification")
            elif kind == "tool_start":
                self._set_voice_state(VOICE_THINKING)
                set_activity(f"tool: {event.get('name') or 'tool'}…", role="tool")
            elif kind == "tool_progress":
                self._set_voice_state(VOICE_THINKING)
                name = event.get("name") or "tool"
                preview = str(event.get("preview") or "working…").strip()
                set_activity(f"tool: {name} — {preview}", role="tool")
            elif kind == "tool_complete":
                name = event.get("name") or "tool"
                set_activity(
                    f"tool: {name} {'✗' if event.get('error') else '✓'}", role="tool"
                )
            elif kind == "background_complete":
                text = str(event.get("text") or "background task complete").strip()
                self._append_block(f"background: {text}", role="background")
            elif kind == "unknown_event":
                event_type = event.get("event_type") or "missing"
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
                self.player.close()
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
                    self.player.close()
                elif self.player.failure:
                    self._set_voice_state(VOICE_BUFFERING)
            elif kind == "error":
                self._set_voice_state(VOICE_ERROR)
                self._append_block(f"[error] {event['error']}", role="error")
            elif kind == "turn_end":
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
