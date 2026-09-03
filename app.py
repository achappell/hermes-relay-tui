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
import copy
import inspect
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from rich.protocol import is_renderable
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual import events
from textual.app import App, ComposeResult, ScreenStackError
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.selection import Selection
from textual.strip import Strip
from textual.visual import RenderOptions, RichVisual, Visual, VisualType, visualize
from textual.widgets import Footer, Header, Static, TextArea

import config
import earcons as earcons_module
import handsfree
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
    crash_log_file,
    logger as diagnostic_logger,
    install_crash_logging,
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


class SelectableRichVisual(RichVisual):
    """Rich rendering with the selection behavior RichVisual lacks."""

    def __init__(self, widget: Static, renderable: Any) -> None:
        super().__init__(widget, renderable)
        self._last_strips: list[Strip] = []

    def render_strips(
        self, width: int, height: int | None, style: Any, options: RenderOptions
    ) -> list[Strip]:
        strips = self._add_selection_offsets(
            super().render_strips(width, height, style, options)
        )
        self._last_strips = strips
        if options.selection is None or options.selection_style is None:
            return strips

        # ``Style.rich_style`` resolves a transparent foreground against the
        # selection background. Applying that as a post-style makes the text
        # itself the same color as the highlight. Keep only the background so
        # the transcript's existing foreground remains readable.
        selection_style = RichStyle(
            bgcolor=options.selection_style.background.rich_color
        )
        selected_strips: list[Strip] = []
        for line_number, strip in enumerate(strips):
            span = options.selection.get_span(line_number)
            if span is None:
                selected_strips.append(strip)
                continue
            start, end = span
            if end < 0:
                end = strip.cell_length
            selected_strips.append(
                Strip.join(
                    (
                        strip.crop(0, start),
                        self._apply_selection_style(
                            strip.crop(start, end), selection_style
                        ),
                        strip.crop(end),
                    )
                )
            )
        return self._add_selection_offsets(selected_strips)

    @staticmethod
    def _add_selection_offsets(strips: list[Strip]) -> list[Strip]:
        """Add Textual's character-position metadata to Rich segments."""
        positioned_strips: list[Strip] = []
        for line_number, strip in enumerate(strips):
            character_offset = 0
            positioned_segments: list[Segment] = []
            for segment in strip._segments:
                if segment.text:
                    offset_style = RichStyle(
                        meta={"offset": (character_offset, line_number)}
                    )
                    segment_style = (segment.style or RichStyle.null()) + offset_style
                    positioned_segments.append(
                        Segment(segment.text, segment_style, segment.control)
                    )
                    character_offset += len(segment.text)
                else:
                    positioned_segments.append(segment)
            positioned_strips.append(
                Strip(positioned_segments, strip.cell_length)
            )
        return positioned_strips

    @staticmethod
    def _apply_selection_style(strip: Strip, selection_style: Any) -> Strip:
        """Overlay selection styling on top of the transcript's Rich styling."""
        return Strip(
            list(Segment.apply_style(strip._segments, post_style=selection_style)),
            strip.cell_length,
        )

    def get_selection(
        self, selection: Selection, fallback_text: str = ""
    ) -> tuple[str, str]:
        """Extract from the rendered lines, including wrapped Rich output."""
        if self._last_strips:
            rendered_text = "\n".join(strip.text for strip in self._last_strips)
        else:
            rendered_text = fallback_text
        return selection.extract(rendered_text), "\n"


class TranscriptStatic(Static):
    """Static transcript widget that makes Rich-rendered text selectable."""

    def __init__(self, content: VisualType = "", **kwargs: Any) -> None:
        super().__init__(content, **kwargs)
        self._transcript_content = content
        self._transcript_visual: Visual | None = None
        self._transcript_plain_text = ""

    def _make_transcript_visual(self, content: VisualType) -> Visual:
        if isinstance(content, Visual):
            return content
        if is_renderable(content) and not isinstance(content, str):
            return SelectableRichVisual(self, content)
        return visualize(self, content, markup=self._render_markup)

    @property
    def visual(self) -> Visual:
        if self._transcript_visual is None:
            self._transcript_visual = self._make_transcript_visual(
                self._transcript_content
            )
        return self._transcript_visual

    @property
    def content(self) -> VisualType:
        return self._transcript_content

    @content.setter
    def content(self, content: VisualType) -> None:
        self._transcript_content = content
        self._transcript_visual = self._make_transcript_visual(content)
        self.clear_cached_dimensions()
        self.refresh(layout=True)

    def update(
        self,
        content: VisualType = "",
        *,
        layout: bool = True,
        plain_text: str = "",
    ) -> None:
        self._transcript_content = content
        self._transcript_plain_text = plain_text
        self._transcript_visual = self._make_transcript_visual(content)
        self.refresh(layout=layout)

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        visual = self.visual
        if isinstance(visual, SelectableRichVisual):
            return visual.get_selection(selection, self._transcript_plain_text)
        return super().get_selection(selection)


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

    class SelectionCopyRequested(Message):
        """Copy a mouse-selected transcript range instead of interrupting."""

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
            if self.app.screen.get_selected_text():
                self.post_message(self.SelectionCopyRequested(self))
                return
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
REMOTE_INTERRUPT_TIMEOUT = 2.0
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

# A fact about the device, not about a feature. It appears whenever the input
# stream is open — a Ctrl+R capture, a wake capture, or wake mode holding it
# between turns — so one physical condition always looks the same. The state
# word beside it describes the phase; this describes the microphone.
#
# Gating this on wake mode alone was the first cut, and it was wrong: a name
# promising device state cannot be driven by feature state, or the same open
# microphone renders two different ways depending on which path opened it.
MIC_OPEN_LABEL = "mic open"
PROMPT_NOT_SENT = "not-sent"
PROMPT_AMBIGUOUS = "ambiguous"
PROMPT_COMPLETED = "completed"
PROMPT_UNDONE = "undone"
VOICE_GATEWAY_COMMANDS = frozenset({"on", "off", "tts", "status"})


def _write_new_text_file(path: Path, text: str) -> None:
    """Create a UTF-8 text file and fail safely if it already exists."""
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)


class HermesStreamingApp(App):
    """A Textual TUI for a Hermes voice-session chat."""

    TITLE = "Hermes Relay"
    SUB_TITLE = "disconnected"

    CSS = """
    # The transcript is the work surface. Keep the controls visually quiet so
    # a long answer remains the thing the eye lands on first.
    #transcript-scroll {
        height: 1fr;
        margin: 0 1;
        padding: 1 2;
        border: round $panel-lighten-1;
        background: $surface;
    }

    #transcript {
        width: 100%;
    }

    #empty-state {
        width: 100%;
        height: 1fr;
        min-height: 3;
        padding: 1 2;
        color: $text-muted;
        content-align: center middle;
    }

    #connection-status {
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }

    #connection-status.-connected {
        color: $success;
    }

    #connection-status.-connecting,
    #connection-status.-retrying {
        color: $warning;
    }

    #connection-status.-disconnected {
        color: $error;
    }

    #voice-status {
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }

    #voice-status.-ready,
    #voice-status.-speaking {
        color: $success;
    }

    #voice-status.-connecting,
    #voice-status.-reconnecting,
    #voice-status.-listening,
    #voice-status.-transcribing,
    #voice-status.-thinking,
    #voice-status.-buffering,
    #voice-status.-interrupted {
        color: $warning;
    }

    #voice-status.-disconnected,
    #voice-status.-error {
        color: $error;
    }

    #composer {
        height: 5;
        max-height: 10;
        margin: 0 1;
        padding: 0 1;
        border: round $panel-lighten-1;
        background: $surface;
    }

    #composer:focus {
        border: round $accent;
    }

    #composer-hint {
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }

    #queue-shelf {
        height: auto;
        max-height: 6;
        margin: 0 1;
        padding: 0 1;
        border-top: solid $panel-lighten-1;
        color: $text-muted;
    }

    #command-suggestions {
        height: auto;
        max-height: 6;
        margin: 0 1;
        padding: 0 1;
        border-top: solid $accent;
        color: $accent;
    }

    #transcript-scroll.-compact {
        padding: 0;
        border: none;
    }

    #empty-state.-compact {
        min-height: 1;
        padding: 0 1;
    }

    #composer.-compact {
        height: 3;
    }

    #composer-hint.-compact {
        display: none;
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
        build_hands_free: Optional[Callable[..., Any]] = None,
        recorder_factory: Optional[Callable[[], Any]] = None,
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
        # Wake mode is off at every launch and only ever armed by /wake on.
        # An always-open microphone is not something a configuration file or a
        # command-line flag gets to decide on the user's behalf.
        self.wake_armed = False
        self._build_hands_free = build_hands_free or handsfree.build_hands_free
        self._recorder_factory = recorder_factory
        self._wake_listener: Any = None
        self._wake_coordinator: Any = None
        self._wake_recorder: Any = None
        self._wake_loop: Optional[asyncio.AbstractEventLoop] = None
        self._earcons = earcons_module.EarconPlayer(
            enabled=getattr(args, "earcons", True) and not (args and args.no_play),
            output_device=getattr(args, "audio_output_device", None),
        )
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
        yield Header(icon="◈")
        with VerticalScroll(id="transcript-scroll"):
            yield Static("Connecting to Hermes…", id="empty-state", markup=False)
            # markup=False so a literal "[error] ..." isn't eaten as Rich markup.
            yield TranscriptStatic("", id="transcript", markup=False)
        yield Static("◌ connecting · session", id="connection-status", markup=False)
        yield Static("● ready", id="voice-status")
        yield Static("", id="queue-shelf", markup=False)
        yield Static("", id="command-suggestions", markup=False)
        yield Composer(placeholder="you>", id="composer")
        yield Static("Enter send · Shift+Enter newline", id="composer-hint", markup=False)
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
        self._refresh_empty_state()
        self.query_one("#transcript", TranscriptStatic).update(
            self.transcript.render(show_details=self.show_transcript_details),
            plain_text=self._visible_transcript_text(),
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
        self._refresh_voice_status()

    def _set_connection_state(self, state: str) -> None:
        self.connection_state = state
        self._refresh_connection_status()

    def _refresh_empty_state(self) -> None:
        try:
            widget = self.query_one("#empty-state", Static)
        except (NoMatches, ScreenStackError):
            return
        if self.transcript.messages:
            widget.display = False
            return
        messages = {
            CONNECTION_CONNECTING: "Connecting to Hermes…",
            CONNECTION_RETRYING: "Reconnecting to Hermes…",
            CONNECTION_DISCONNECTED: (
                "Hermes is disconnected. Prompts stay queued until it returns."
            ),
        }
        widget.update(
            messages.get(self.connection_state, "No messages yet — type below to begin.")
        )
        widget.display = True

    def _refresh_compact_layout(self, height: int) -> None:
        """Trade decoration for usable space in short terminal windows."""
        compact = height <= 15
        for selector in (
            "#transcript-scroll",
            "#empty-state",
            "#composer",
            "#composer-hint",
        ):
            try:
                self.query_one(selector).set_class(compact, "-compact")
            except (NoMatches, ScreenStackError):
                return

    def _refresh_connection_status(self) -> None:
        session_id = getattr(self.args, "session_id", None) or "session"
        symbol = {
            CONNECTION_CONNECTED: "●",
            CONNECTION_CONNECTING: "◌",
            CONNECTION_RETRYING: "◌",
            CONNECTION_DISCONNECTED: "○",
        }.get(self.connection_state, "○")
        line = f"{symbol} {self.connection_state} · session {session_id}"
        self.sub_title = f"{self.connection_state} · session {session_id}"
        try:
            widget = self.query_one("#connection-status", Static)
        except (NoMatches, ScreenStackError):
            return
        widget.update(line)
        for state in (
            CONNECTION_CONNECTED,
            CONNECTION_CONNECTING,
            CONNECTION_RETRYING,
            CONNECTION_DISCONNECTED,
        ):
            widget.set_class(state == self.connection_state, f"-{state}")

    @property
    def microphone_is_open(self) -> bool:
        """Whether the input device is open right now, for any reason.

        Two ways it can be: a capture is running (Ctrl+R, or the wake path's
        own capture), or wake mode is armed and holding the stream between
        turns. The user does not care which; they care that the microphone is
        on.
        """
        return bool(self.wake_armed or self._voice_capture_task is not None)

    def _refresh_voice_status(self) -> None:
        """Repaint the status line: the turn's phase, and whether the
        microphone is held.

        Called on arming and disarming as well as on state changes. Arming
        while idle leaves `voice_state` untouched, so a surface that only
        repainted on a state change would say nothing at all about an open
        microphone — which is the failure this indicator exists to prevent.
        """
        line = f"● {self.voice_state}"
        if self.microphone_is_open:
            line += f"   [$warning]◉ {MIC_OPEN_LABEL}[/]"
        try:
            widget = self.query_one("#voice-status", Static)
            widget.update(line)
            for state in (
                VOICE_READY,
                VOICE_CONNECTING,
                VOICE_RECONNECTING,
                VOICE_DISCONNECTED,
                VOICE_LISTENING,
                VOICE_TRANSCRIBING,
                VOICE_THINKING,
                VOICE_SPEAKING,
                VOICE_BUFFERING,
                VOICE_INTERRUPTED,
                VOICE_ERROR,
            ):
                widget.set_class(state == self.voice_state, f"-{state.rstrip('…')}")
        except (NoMatches, ScreenStackError):
            # A state change can still be in flight during teardown.
            pass

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
        self._refresh_compact_layout(self.size.height)
        self._set_connection_state(CONNECTION_CONNECTING)
        self._set_voice_state(VOICE_CONNECTING)
        self._refresh_empty_state()
        # In a worker so a hanging endpoint can't freeze the UI (or block ctrl+q).
        self.run_worker(self._connect(force=True), exclusive=True)

    def on_resize(self, event: events.Resize) -> None:
        """Rebuild wrapped Rich content after the terminal changes shape."""
        self._refresh_compact_layout(event.size.height)
        try:
            self._refresh_transcript()
        except (NoMatches, ScreenStackError):
            # Resize events can arrive while the app is mounting or tearing
            # down; there is no transcript to refresh in either case.
            pass

    async def _connect(self, *, force: bool = False) -> bool:
        """Establish a session with bounded exponential-backoff retries."""
        async with self._connection_lock:
            if self.wake_armed and not self.session.is_connected():
                self._disarm_wake(
                    "wake mode off — connection lost; microphone released. "
                    "Run /wake on after reconnect."
                )
            if self.session.is_connected() and not force:
                self._set_connection_state(CONNECTION_CONNECTED)
                self._set_voice_state(VOICE_READY)
                return True

            retries = max(0, int(getattr(self.args, "connect_retries", 3)))
            retry_delay = max(0.0, float(getattr(self.args, "connect_retry_delay", 1.0)))
            attempts = retries + 1
            reconnecting = self._needs_reconnect
            last_error: Exception = RuntimeError("unknown connection failure")

            for attempt in range(attempts):
                if attempt == 0:
                    self._set_connection_state(CONNECTION_CONNECTING)
                    self._set_voice_state(
                        VOICE_RECONNECTING if reconnecting else VOICE_CONNECTING
                    )
                    if reconnecting:
                        self._append_block("reconnecting…")
                else:
                    self._set_connection_state(CONNECTION_RETRYING)
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
                    self._set_connection_state(CONNECTION_DISCONNECTED)
                    self._set_voice_state(VOICE_DISCONNECTED)
                    raise
                except Exception as exc:
                    last_error = exc
                    self._set_connection_state(CONNECTION_DISCONNECTED)
                    self._set_voice_state(VOICE_DISCONNECTED)
                    try:
                        await self.session.close()
                    except Exception:
                        pass
                    self._append_block(
                        f"[connection attempt {attempt + 1}/{attempts} failed: {exc}]"
                    )
                    continue

                self._set_connection_state(CONNECTION_CONNECTED)
                self._set_voice_state(VOICE_READY)
                self._needs_reconnect = False
                session_id = getattr(self.args, "session_id", "session")
                self._append_block(f"Connected to {session_id} (chat {hello.get('chat_id')}).")
                return True

            self._set_connection_state(CONNECTION_DISCONNECTED)
            self._set_voice_state(VOICE_DISCONNECTED)
            self._append_block(
                f"[error] {last_error}; unable to connect after {attempts} attempt(s)"
            )
            self._append_block(RETRY_HINT)
            return False

    async def on_unmount(self) -> None:
        # Release the device before anything else. A quit that leaves the
        # microphone open is the worst possible way to end a session.
        self._disarm_wake()
        if self.session is not None:
            await self.session.close()

    # --- wake mode ------------------------------------------------------

    async def _handle_wake_command(self, args: str) -> None:
        """/wake [on|off|status] — hands-free listening, armed on purpose."""
        choice = args.strip().lower()
        if choice in ("", "status"):
            self._report_wake_status()
        elif choice == "on":
            self._arm_wake()
        elif choice == "off":
            if not self.wake_armed:
                self._append_block("wake mode is already off")
                return
            self._disarm_wake()
            self._append_block("wake mode off — microphone released")
        else:
            self._append_block("usage: /wake [on|off|status]")

    def _report_wake_status(self) -> None:
        if not self.wake_armed:
            self._append_block(
                "wake mode: off — the microphone is closed. Turn it on with /wake on."
            )
            return
        model = getattr(self.args, "wake_model", None) or "bundled hey_hermes"
        threshold = getattr(self.args, "wake_threshold", 0.6)
        self._append_block(
            f"wake mode: on — listening · model: {model} · threshold: {threshold}"
        )

    def _arm_wake(self) -> None:
        if self.wake_armed:
            self._append_block("wake mode is already on")
            return

        # The builder reads --wake-* settings off args, but wake_enabled is
        # refused at launch for this front end, so arm it here instead of
        # asking the user to have set a flag they are not allowed to pass.
        args = copy.copy(self.args)
        args.wake_enabled = True

        try:
            built = self._build_hands_free(
                self.session,
                args,
                capture=self._capture_wake_voice,
                follow_up_capture=self._capture_wake_follow_up,
                send=self._send_wake_turn,
                speech_detected=self._wake_speech_detected,
                stop_playback=self.player.close,
                acknowledge=self._acknowledge_wake,
                capture_finished=self._acknowledge_capture,
                on_state_change=self._wake_state_changed,
            )
        except Exception as error:
            self._append_block(f"[error] wake mode: {self._wake_failure_text(error)}")
            return
        if built is None:
            self._append_block("[error] wake mode could not be started")
            return

        listener, coordinator = built
        factory = self._recorder_factory
        if factory is None:
            from voice import create_audio_recorder

            factory = create_audio_recorder
        recorder = factory()

        self._wake_loop = asyncio.get_running_loop()
        self._wake_listener = listener
        self._wake_coordinator = coordinator
        self._wake_recorder = recorder
        self.session.use_shared_recorder(recorder)

        # Start the worker before opening the stream. Reversed, frames pile
        # into a bounded queue with nothing draining it and the entire warm-up
        # is dropped audio — measured at 96 frames on the appliance.
        listener.start()
        recorder.set_frame_observer(listener.submit)
        recorder.open_for_listening()

        self.wake_armed = True
        self._refresh_voice_status()
        self._set_wake_listening(busy=self._turn_in_flight)
        self._append_block(
            "wake mode on — say the phrase. The microphone stays open until "
            "/wake off."
        )

    def _wake_failure_text(self, error: Exception) -> str:
        """Turn an arming failure into the one sentence that fixes it."""
        import wake  # noqa: PLC0415 - the optional-dependency seam

        if isinstance(error, wake.MissingWakeDependency):
            return (
                "the wake-word engine is not installed. "
                "Install it with: pip install 'hermes-relay-tui[wake]'"
            )
        return str(error)

    def _disarm_wake(self, message: Optional[str] = None) -> None:
        """Stop listening and give the device back. Safe to call when off."""
        listener, recorder = self._wake_listener, self._wake_recorder
        self._wake_listener = None
        self._wake_coordinator = None
        self._wake_recorder = None
        self._wake_loop = None
        was_armed = self.wake_armed
        self.wake_armed = False
        self._refresh_voice_status()
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                diagnostic_logger.debug("stopping the wake listener failed", exc_info=True)
        if recorder is not None:
            try:
                # shutdown() closes the input stream on a guarded timeout, so
                # the microphone indicator clears and other applications get
                # the device back. Pausing the detector would not do either.
                recorder.shutdown()
            except Exception:
                diagnostic_logger.debug("closing the wake recorder failed", exc_info=True)
        if message and was_armed:
            self._append_block(message)

    def _set_wake_listening(self, *, busy: bool) -> None:
        """Listen only when nothing else holds the microphone.

        A turn or a Ctrl+R capture owns the input stream, and pausing resets
        the detector's rolling buffer. Without this the client wakes itself on
        the tail of the phrase it has just recorded.
        """
        listener = self._wake_listener
        if listener is None:
            return
        if busy:
            listener.pause()
        else:
            listener.resume()

    def _wake_state_changed(self, state: str) -> None:
        """Keep detection and the TUI honest while the worker owns capture.

        ``HandsFreeCoordinator`` runs on the wake listener thread. Pausing the
        listener there is intentional: the shared recorder keeps producing
        frames while local transcription runs, and those frames must not pile
        up to be scored as a stale wake after the turn. Textual repainting is
        handed back to its event loop.
        """
        self._set_wake_listening(busy=state != handsfree.IDLE)
        loop = self._wake_loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._apply_wake_state, state)
        except RuntimeError:
            # Teardown can close the loop between reading the reference and
            # scheduling the repaint. Disarm already refreshed the surface.
            return

    def _apply_wake_state(self, state: str) -> None:
        """Apply a worker-reported wake phase on Textual's event loop."""
        if not self.wake_armed:
            return
        if state == handsfree.CAPTURING and not self._turn_in_flight:
            self._set_voice_state(VOICE_LISTENING)
        elif (
            state == handsfree.IDLE
            and not self._turn_in_flight
            and self._voice_capture_task is None
        ):
            self._set_voice_state(VOICE_READY)

    def _capture_wake_voice(self) -> str:
        """Capture the utterance after the wake phrase with a real bound."""
        timeout = getattr(
            self.args, "wake_listen_timeout", handsfree.DEFAULT_LISTEN_TIMEOUT
        )
        return self.session.capture_voice(wait_timeout=float(timeout))

    def _capture_wake_follow_up(self) -> str:
        """Give a speaker one quiet, wake-word-free conversational window."""
        timeout = getattr(self.args, "wake_followup_seconds", 8.0)
        return self.session.capture_voice(wait_timeout=float(timeout))

    def _wake_speech_detected(self) -> bool:
        return bool(getattr(self._wake_recorder, "has_detected_speech", False))

    def _acknowledge_wake(self) -> None:
        self._earcons.play(earcons_module.WAKE)

    def _acknowledge_capture(self) -> None:
        self._earcons.play(earcons_module.CAPTURE_DONE)

    def _send_wake_turn(self, text: str) -> None:
        """Run one wake turn on the event loop, blocking the listener thread.

        Blocking is the point: the coordinator is single-flight, so while this
        is outstanding a second detection is dropped instead of becoming an
        overlapping turn.
        """
        loop = self._wake_loop
        if loop is None:
            return
        future = asyncio.run_coroutine_threadsafe(
            self._run_turn(text, stt_source="local"), loop
        )
        future.result()

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
            self._refresh_composer_hint(event.text_area.text)
            self._update_command_suggestions(event.text_area.text)

    def _refresh_composer_hint(self, text: Optional[str] = None) -> None:
        try:
            widget = self.query_one("#composer-hint", Static)
        except (NoMatches, ScreenStackError):
            return
        if text is None:
            text = self.query_one("#composer", Composer).text
        prefix = "Draft ready · " if text.strip() else ""
        widget.update(f"{prefix}Enter send · Shift+Enter newline")

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

    def _selected_transcript_text(self) -> str | None:
        """Return a selection only when it belongs solely to the transcript."""
        transcript_widget = self.query_one("#transcript", TranscriptStatic)
        if set(self.screen.selections) != {transcript_widget}:
            return None
        selected_text = self.screen.get_selected_text()
        return selected_text or None

    async def on_text_selected(self, event: events.TextSelected) -> None:
        selected_text = self._selected_transcript_text()
        if selected_text is None:
            return
        try:
            await copy_text(selected_text)
        except (ClipboardError, OSError) as exc:
            self.notify(f"Copy failed: {exc}", severity="error", timeout=3.0)
            self._append_block(f"[error] copy selection: {exc}")
        else:
            self.notify("Copied to clipboard", timeout=1.5)
            if self.is_running:
                self.screen.clear_selection()

    async def on_composer_selection_copy_requested(
        self, event: Composer.SelectionCopyRequested
    ) -> None:
        selected_text = self.screen.get_selected_text()
        if not selected_text:
            return
        try:
            await copy_text(selected_text)
        except (ClipboardError, OSError) as exc:
            self._append_block(f"[error] copy selection: {exc}")
        else:
            self._append_block("copied selected transcript text")

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
            voice_args = invocation.args.strip().lower()
            if not voice_args or voice_args in VOICE_GATEWAY_COMMANDS:
                await self._run_turn(invocation.raw, stt_source="command")
            else:
                self._append_block("usage: /voice [on|off|tts|status]")
        elif command.name == "wake":
            await self._handle_wake_command(invocation.args)
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
        debug_path = active_log_file()
        crash_path = crash_log_file()
        if debug_path is None:
            debug_state = "disabled"
        else:
            state = "present" if debug_path.exists() else "missing"
            debug_state = f"{state} at {debug_path}"
        crash_state = "present" if crash_path.exists() else "not created"
        self._append_block(
            f"logs: debug trace {debug_state}; crash log {crash_state} at {crash_path}"
        )

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

        if self.wake_armed:
            self._disarm_wake(
                "wake mode off — config reloaded; microphone released. "
                "Run /wake on to arm again."
            )
        self.args = new_args
        self._refresh_connection_status()
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
        if self.wake_armed:
            coordinator = self._wake_coordinator
            if coordinator is not None and coordinator.state != handsfree.IDLE:
                self._append_block("[a wake turn is already in flight]")
                return
        self._voice_capture_cancelled = False
        wake_was_armed = self.wake_armed
        if wake_was_armed:
            self._set_wake_listening(busy=True)
        resume_wake = wake_was_armed
        try:
            capture_task = asyncio.create_task(asyncio.to_thread(self.session.capture_voice))
            # Assigned before the repaint below: `_set_voice_state` reads
            # `microphone_is_open`, and the one state that most obviously means
            # "the microphone is on" would otherwise render without the marker.
            self._voice_capture_task = capture_task
            self._set_voice_state(VOICE_LISTENING)
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
                self._refresh_voice_status()
            if self.voice_state == VOICE_INTERRUPTED:
                return
            if not transcript_text:
                self._set_voice_state(VOICE_READY)
                self._append_block("no speech detected.")
                return
            self._set_voice_state(VOICE_TRANSCRIBING)
            # Keep the detector paused through transcription and the whole
            # turn. `_run_turn` owns the matching resume after the reply.
            await self._run_turn(transcript_text, stt_source="local-faster-whisper")
            resume_wake = False
        finally:
            if resume_wake and self.wake_armed:
                self._set_wake_listening(busy=False)

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
            coordinator = self._wake_coordinator
            if not (
                self.wake_armed
                and coordinator is not None
                and coordinator.state == handsfree.CAPTURING
            ):
                return False

            # Wake captures run on the listener worker rather than through a
            # Textual task. Cancel the shared recorder so that worker can
            # leave its bounded capture and return to wake-only listening.
            self._set_voice_state(VOICE_INTERRUPTED)
            cancel = getattr(self.session, "cancel_voice", None)
            if callable(cancel):
                await asyncio.to_thread(cancel)
            return True

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
        """Interrupt the remote turn, falling back to reconnect if needed."""
        if not self._turn_in_flight:
            return False

        self._set_voice_state(VOICE_INTERRUPTED)
        await self._close_player()
        active_task = self._active_turn_task
        current_task = asyncio.current_task()

        interrupt = getattr(self.session, "interrupt_active_turn", None)
        remote_interrupt_sent = False
        if callable(interrupt):
            try:
                result = interrupt()
                if inspect.isawaitable(result):
                    result = await result
                remote_interrupt_sent = bool(result)
            except Exception as exc:
                diagnostic_logger.error(
                    "app.interrupt.send_failed type=%s", type(exc).__name__
                )

        if remote_interrupt_sent:
            if active_task is None or active_task is current_task:
                self._append_block("[interrupted]")
                self._turn_in_flight = False
                return True
            try:
                # The active task owns the one websocket reader. Let it
                # consume Hermes' turn_interrupted/audio_abort confirmation
                # before considering the connection stale.
                await asyncio.wait_for(
                    asyncio.shield(active_task), REMOTE_INTERRUPT_TIMEOUT
                )
            except asyncio.TimeoutError:
                diagnostic_logger.warning("app.interrupt.confirmation_timeout")
            except asyncio.CancelledError:
                pass
            if active_task.done():
                return True

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
        self._set_connection_state(CONNECTION_DISCONNECTED)
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
            "drag transcript text = copy selection; ctrl+c = copy an existing "
            "selection or interrupt when none is selected, "
            "ctrl+r = voice turn, f1 = help, ctrl+q = quit. "
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
        self._set_wake_listening(busy=True)
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
            self._set_wake_listening(busy=False)

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
            self._set_connection_state(CONNECTION_DISCONNECTED)
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
        self._disarm_wake(
            "wake mode off — connection lost; microphone released. "
            "Run /wake on after reconnect."
        )
        self._set_connection_state(CONNECTION_DISCONNECTED)
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
            elif kind == "audio_abort":
                # An abort is an intentional end to the remote audio stream,
                # not a failed voice turn. The following turn_interrupted
                # event owns the transcript boundary.
                await self._close_player()
                self._set_voice_state(VOICE_INTERRUPTED)
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
                        # Hermes sends a file copy alongside the PCM it has
                        # already streamed. Failing to decode the spare copy
                        # is not a failed turn when the answer already
                        # arrived — whether or not a device could play it.
                        if not audio:
                            self._append_block(
                                "[error] unsupported audio file fallback"
                            )
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
            elif kind == "turn_interrupted":
                await self._close_player()
                complete_thinking()
                self.transcript.finish_stream()
                self._append_block("[interrupted]")
                self._set_voice_state(VOICE_INTERRUPTED)
                return
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
    install_crash_logging()
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        from setup_wizard import run_setup

        return run_setup(sys.argv[2:])
    parser = config.build_arg_parser()
    args = parser.parse_args()
    config.ensure_default_config_file(args.config)
    if args.log_file is not None:
        args.debug = True
    if getattr(args, "wake_enabled", False):
        # The flag used to parse here and do nothing whatsoever: app.py had no
        # reference to wake or handsfree, so only the appliance honoured it.
        # Refusing is honest. Silently ignoring a flag about the microphone is
        # not, and it is the microphone.
        print(
            "hermes-relay does not arm hands-free listening at launch.\n"
            "Start the client, then turn it on in-session with: /wake on\n"
            "For the always-on household unit, use: hermes-relay-home "
            "--wake-enabled",
            file=sys.stderr,
        )
        return 2
    log_path = config.configure_logging(debug=args.debug, log_file=args.log_file)
    if log_path is not None:
        diagnostic_logger.info("app.start url=%s", args.url.split("?", 1)[0])
    app = HermesStreamingApp(args=args)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
