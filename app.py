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
import math
import os
import sys
import time
import uuid
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
from textual.widgets import Footer, Header, Input, Static, TextArea
from websockets.exceptions import ConnectionClosed

import config
from client import TransportError
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
    trace_monotonic_ms,
)
from domain import TuiDomain, TurnPhase, decide_busy
from history import (
    PromptHistory,
    artifact_path_for_profile,
    legacy_history_path_for_profile,
    history_path_for_profile,
)
from help_screen import HelpModal
from prompts import PendingPrompt
from session import HermesSession, SessionNotReadyError, SessionProtocol
from session_picker import SessionPickerModal
from shell import (
    ShellExecutionError,
    ShellPolicy,
    interpolate_commands,
    interpolation_commands,
    run_command,
    standalone_command,
)
from transcript import TranscriptBuffer
from timing import (
    SpeechTiming,
    duration_visible_text,
    fallback_visible_text,
    longest_valid_prefix,
    visible_text,
)


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

    class PromptOptionSelected(Message):
        """A digit key picked a numbered option on a pending structured prompt."""

        def __init__(self, composer: "Composer", option_id: str) -> None:
            super().__init__()
            self.composer = composer
            self.option_id = option_id

    async def _on_key(self, event: events.Key) -> None:
        if len(event.key) == 1 and event.key.isdigit() and event.key != "0":
            pending = getattr(self.app, "_pending_prompt", None)
            if pending is not None and not pending.awaiting_response and pending.options:
                option = pending.option_at(int(event.key))
                if option is not None:
                    event.stop()
                    event.prevent_default()
                    self.post_message(self.PromptOptionSelected(self, option.id))
                    return
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
SHUTDOWN_TASK_TIMEOUT = 3.0
HANDSHAKE_TIMEOUT = 30.0
RETRY_HINT = (
    "The app remains open; run /reconnect when the endpoint recovers, "
    "then submit a fresh prompt."
)
VOICE_READY = "ready"
VOICE_STARTING = "starting…"
VOICE_CONNECTING = "connecting…"
VOICE_RECONNECTING = "reconnecting…"
VOICE_DISCONNECTED = "disconnected"
VOICE_HEARD = "heard"
VOICE_LISTENING = "listening…"
VOICE_TRANSCRIBING = "transcribing…"
VOICE_THINKING = "thinking…"
VOICE_SPEAKING = "speaking…"
VOICE_BUFFERING = "buffering…"
VOICE_AUDIO_UNAVAILABLE = "audio unavailable"
VOICE_INTERRUPTED = "interrupted"
VOICE_ERROR = "error"


def _is_transport_error(error: BaseException) -> bool:
    """Return whether a failed turn indicates that the relay stream is gone."""
    return isinstance(
        error,
        (
            TransportError,
            ConnectionClosed,
            ConnectionError,
            EOFError,
            asyncio.IncompleteReadError,
            asyncio.TimeoutError,
        ),
    )

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
    path.parent.mkdir(parents=True, exist_ok=True)
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

    #voice-status.-starting,
    #voice-status.-connecting,
    #voice-status.-reconnecting,
    #voice-status.-listening,
    #voice-status.-transcribing,
    #voice-status.-thinking,
    #voice-status.-buffering,
    #voice-status.-heard,
    #voice-status.-interrupted {
        color: $warning;
    }

    #voice-status.-audio-unavailable {
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
        max-height: 4;
        margin: 0 1;
        padding: 0 1;
        border-top: solid $panel-lighten-1;
        color: $text-muted;
    }

    #command-suggestions {
        height: auto;
        max-height: 4;
        margin: 0 1;
        padding: 0 1;
        border-top: solid $accent;
        color: $accent;
    }

    #prompt-panel {
        height: auto;
        max-height: 6;
        margin: 0 1;
        padding: 0 1;
        border: round $warning;
        color: $text;
    }

    #prompt-input {
        margin: 0 1;
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

    #queue-shelf.-compact,
    #command-suggestions.-compact {
        max-height: 4;
        padding: 0 1;
        overflow-y: auto;
    }

    #prompt-panel.-compact {
        max-height: 6;
        padding: 0 1;
        overflow-y: auto;
    }

    #connection-status.-compact {
        display: none;
    }

    #connection-status.-compact.-connecting,
    #connection-status.-compact.-retrying,
    #connection-status.-compact.-disconnected {
        display: block;
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
        session_factory: Optional[Callable[..., Any]] = None,
        command_dispatcher: Optional[Callable[[CommandInvocation], Awaitable[str] | str]] = None,
        argv: Optional[list[str]] = None,
        build_hands_free: Optional[Callable[..., Any]] = None,
        recorder_factory: Optional[Callable[[], Any]] = None,
        barge_listener_factory: Optional[Callable[..., Any]] = None,
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
        self._active_profile_name = (
            getattr(args, "profile_name", None)
            or getattr(args, "profile", None)
            or "default"
        )
        self._active_profile_display_name = self._profile_display_name_for_args(args)
        self._profiles_configured = bool(getattr(args, "profiles_configured", False))
        self._profile_names = tuple(
            getattr(args, "profile_names", ())
            or (self._active_profile_name,)
        )
        self.player = PCMPlayer(
            enabled=not (args and args.no_play),
            output_device=getattr(args, "audio_output_device", None),
        )
        self.audio_input_device = getattr(args, "mic_input_device", None)
        self.transcript = TranscriptBuffer(
            assistant_label=self._active_profile_display_name
        )
        self.domain = TuiDomain()
        # Diagnostic activity is available on demand, but the default surface
        # should read like a conversation rather than a worker log.
        self.show_transcript_details = False
        self.voice_state = VOICE_READY
        self._audio_unavailable_reason: Optional[str] = None
        self._turn_in_flight = False
        self._queued_prompts: list[str] = []
        self._pending_prompt: Optional[PendingPrompt] = None
        self._staged_attachments: list[Attachment] = []
        self._active_turn_task: Optional[asyncio.Task[None]] = None
        self._caption_task: Optional[asyncio.Task[Any]] = None
        self._voice_capture_task: Optional[asyncio.Task[str]] = None
        self._voice_capture_cancelled = False
        self._shutting_down = False
        self._cleanup_tasks: set[asyncio.Task[Any]] = set()
        self._session_cleanup_tasks: dict[int, asyncio.Task[Any]] = {}
        self._session_generation = 0
        self._connection_watch_task: Optional[asyncio.Task[Any]] = None
        self._connection_watch_key: tuple[int, int] | None = None
        self._expected_close_keys: set[tuple[int, int]] = set()
        self._loss_handled_keys: set[tuple[int, int]] = set()
        self._loss_in_flight_keys: set[tuple[int, int]] = set()
        self._connection_loss_in_flight = False
        self._recovery_session_ready = False
        # Wake mode remains off unless the user explicitly opts in through
        # configuration or --wake-enabled. A configured launch arms it only
        # after the initial connection; reconnects and reloads never reopen a
        # microphone silently.
        self.wake_armed = False
        self._launch_wake_attempted = False
        self._build_hands_free = build_hands_free or handsfree.build_hands_free
        self._recorder_factory = recorder_factory
        self._barge_listener_factory = barge_listener_factory
        self._wake_listener: Any = None
        self._wake_coordinator: Any = None
        self._wake_recorder: Any = None
        self._barge_listener: Any = None
        self._barge_recorder_observer: Any = None
        self._barge_capture_active = False
        self._barge_was_playing = False
        self._barge_interrupt_task: Optional[asyncio.Task[bool]] = None
        self._barge_result_task: Optional[asyncio.Task[None]] = None
        self._last_tts_text = ""
        self._wake_loop: Optional[asyncio.AbstractEventLoop] = None
        self._preserve_wake_terminal_state = False
        self._wake_starting = False
        self._wake_start_cancelled = False
        self._wake_opening = False
        self._wake_open_task: Optional[asyncio.Task[Any]] = None
        self._wake_start_task: Optional[asyncio.Task[Any]] = None
        self._wake_cleanup_tasks: set[asyncio.Task[Any]] = set()
        self._wake_unavailable_reported = False
        self._earcons = earcons_module.EarconPlayer(
            enabled=getattr(args, "earcons", True) and not (args and args.no_play),
            output_device=getattr(args, "audio_output_device", None),
        )
        self._needs_reconnect = False
        self._reconnect_in_flight = False
        self._last_prompt: Optional[str] = None
        self._last_prompt_status: Optional[str] = None
        self.connection_state = CONNECTION_DISCONNECTED
        self._connection_lock = asyncio.Lock()
        self.busy_mode = getattr(args, "busy_mode", "queue")
        if self.busy_mode not in config.BUSY_MODES:
            self.busy_mode = "queue"
        self._busy_transition_owner: Optional[asyncio.Task[None]] = None
        self._history = self._prompt_history_for_args(args)
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
        yield Static("", id="prompt-panel", markup=False)
        yield Input(placeholder="", id="prompt-input")
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
        result = self.domain.observe_voice_state(state)
        if not result.accepted:
            diagnostic_logger.debug(
                "app.voice.state_rejected state=%s reason=%s",
                state,
                result.reason or "unknown",
            )
            return
        self.voice_state = state
        self._refresh_voice_status()

    def _sync_voice_state_from_domain(self, phase: TurnPhase) -> None:
        """Render an accepted domain phase without trusting event wording."""
        labels = {
            TurnPhase.IDLE: VOICE_READY,
            TurnPhase.HEARD: VOICE_HEARD,
            TurnPhase.LISTENING: VOICE_LISTENING,
            TurnPhase.TRANSCRIBING: VOICE_TRANSCRIBING,
            TurnPhase.THINKING: VOICE_THINKING,
            TurnPhase.BUFFERING: VOICE_BUFFERING,
            TurnPhase.SPEAKING: VOICE_SPEAKING,
            TurnPhase.COMPLETE: VOICE_READY,
            TurnPhase.INTERRUPTED: VOICE_INTERRUPTED,
            TurnPhase.ERROR: VOICE_ERROR,
            TurnPhase.DISCONNECTED: VOICE_DISCONNECTED,
        }
        label = labels.get(phase)
        if label is None:
            # Prompt presentation owns its own panel and must not erase the
            # phase that led to it.
            return
        if self._audio_unavailable_reason and phase in {
            TurnPhase.BUFFERING,
            TurnPhase.SPEAKING,
        }:
            self._refresh_voice_status()
            return
        if phase is TurnPhase.SPEAKING and not self._player_is_playing():
            if self._playback_is_disabled():
                self._mark_audio_unavailable("playback disabled")
            elif self.player.failure:
                self._mark_audio_unavailable("playback failed")
            else:
                self._set_voice_state(VOICE_BUFFERING)
            return
        self._set_voice_state(label)

    def _clear_audio_unavailable(self) -> None:
        if self._audio_unavailable_reason is None:
            return
        self._audio_unavailable_reason = None
        self._refresh_voice_status()

    def _mark_audio_unavailable(self, reason: str) -> None:
        if self._audio_unavailable_reason is None:
            self._audio_unavailable_reason = reason
            diagnostic_logger.debug("app.audio.unavailable reason=%s", reason)
        self._refresh_voice_status()

    def _player_is_playing(self) -> bool:
        """Return true only when the output port reports audible playback."""
        playing = getattr(self.player, "playing", None)
        if playing is not None:
            return bool(playing)
        return bool(getattr(self.player, "active", False))

    def _playback_is_disabled(self) -> bool:
        return not bool(getattr(self.player, "enabled", True))

    def _set_connection_state(self, state: str) -> None:
        self.connection_state = state
        self.domain.set_connection_state(state)
        self._refresh_connection_status()
        # The empty-state copy is the recovery explanation when there is no
        # transcript to carry the context. Refresh it with the status line so
        # an idle disconnect cannot leave "Connecting" painted underneath a
        # disconnected connection.
        self._refresh_empty_state()

    def _connection_is_ready(self) -> bool:
        """Return true only when the selected profile has a verified session."""
        return (
            self.connection_state == CONNECTION_CONNECTED
            and self.session.is_connected()
            and not self._needs_reconnect
        )

    def _refresh_empty_state(self) -> None:
        try:
            widget = self.query_one("#empty-state", Static)
        except (NoMatches, ScreenStackError):
            return
        if self.transcript.messages:
            has_conversation = any(
                message.role in {"user", "assistant"}
                and message.text.strip()
                and (self.show_transcript_details or not message.detail)
                for message in self.transcript.messages
            )
            if has_conversation:
                widget.display = False
                return
        if self.connection_state == CONNECTION_CONNECTED:
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
            "#connection-status",
            "#queue-shelf",
            "#command-suggestions",
            "#prompt-panel",
            "#composer",
            "#composer-hint",
        ):
            try:
                self.query_one(selector).set_class(compact, "-compact")
            except (NoMatches, ScreenStackError):
                return

    @staticmethod
    def _profile_target_tuple(args: Any) -> tuple[Any, ...]:
        """Return connection identity without ever rendering its token."""
        configured = bool(getattr(args, "profiles_configured", False))
        if not configured:
            # Legacy reload deliberately retains its existing in-memory
            # session behavior; TUI-02 reconnects only when a named catalog is
            # actually in play.
            return (False,)
        return (
            True,
            getattr(args, "profile_name", None) or getattr(args, "profile", None),
            getattr(args, "url", None),
            getattr(args, "token", None),
            getattr(args, "client_id", None),
            getattr(args, "device_id", None),
            getattr(args, "session_id", None),
            getattr(args, "display_name", None),
        )

    def _history_path_for_args(self, args: Any) -> Path:
        profile_name = (
            getattr(args, "profile_name", None)
            or getattr(args, "profile", None)
            or "default"
        )
        configured_path = getattr(args, "history_path", None)
        return history_path_for_profile(
            getattr(args, "url", None),
            profile_name,
            configured_path=configured_path,
            legacy=not bool(getattr(args, "profiles_configured", False)),
        )

    def _prompt_history_for_args(self, args: Any) -> PromptHistory:
        """Open profile-local prompt history and migrate its old local file."""
        path = self._history_path_for_args(args)
        legacy_paths: tuple[Path, ...] = ()
        if bool(getattr(args, "profiles_configured", False)):
            legacy_path = legacy_history_path_for_profile(
                getattr(args, "url", None),
                getattr(args, "profile_name", None)
                or getattr(args, "profile", None)
                or "default",
                configured_path=getattr(args, "history_path", None),
            )
            if legacy_path != path:
                legacy_paths = (legacy_path,)
        return PromptHistory(path, legacy_paths=legacy_paths)

    @staticmethod
    def _doorway_session_args(args: Any) -> Any:
        """Mint one remote Session identity for this launch/profile doorway."""
        if args is None:
            return args
        session_args = copy.copy(args)
        session_args.session_id = uuid.uuid4().hex
        return session_args

    @staticmethod
    def _profile_display_name_for_args(args: Any) -> str:
        """Return the configured Hermes Profile identity for presentation."""
        display_name = str(getattr(args, "display_name", "") or "").strip()
        if display_name:
            return display_name
        return "assistant"

    def _sync_profile_metadata(self, args: Any) -> None:
        self._active_profile_name = (
            getattr(args, "profile_name", None)
            or getattr(args, "profile", None)
            or "default"
        )
        self._active_profile_display_name = self._profile_display_name_for_args(args)
        self.transcript.set_assistant_label(self._active_profile_display_name)
        self._profiles_configured = bool(getattr(args, "profiles_configured", False))
        self._profile_names = tuple(
            getattr(args, "profile_names", ()) or (self._active_profile_name,)
        )

    def _new_session(self, args: Any) -> SessionProtocol:
        """Build a session while retaining the repository's zero-arg test seam."""
        if self._session_factory is None:
            return HermesSession(args)
        factory = self._session_factory
        try:
            parameters = inspect.signature(factory).parameters.values()
        except (TypeError, ValueError):
            return factory(args)
        positional = [
            parameter
            for parameter in parameters
            if parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters):
            return factory(args)
        if positional and any(parameter.default is inspect.Parameter.empty for parameter in positional):
            return factory(args)
        return factory()

    def _install_session(self, session: SessionProtocol) -> SessionProtocol:
        """Install a session and give its callbacks a new identity generation."""
        self.session = session
        self._session_generation += 1
        self._recovery_session_ready = False
        return session

    def _session_key(
        self, session: SessionProtocol | None = None, generation: int | None = None
    ) -> tuple[int, int] | None:
        session = self.session if session is None else session
        if session is None:
            return None
        return (id(session), self._session_generation if generation is None else generation)

    def _session_is_current(
        self, session: SessionProtocol | None, generation: int | None
    ) -> bool:
        return (
            session is not None
            and session is self.session
            and generation == self._session_generation
        )

    def _expect_session_close(
        self, session: SessionProtocol | None, generation: int | None = None
    ) -> None:
        key = self._session_key(session, generation)
        if key is not None:
            self._expected_close_keys.add(key)

    async def _stop_connection_watcher(
        self,
        session: SessionProtocol | None = None,
        generation: int | None = None,
        *,
        expected_close: bool = False,
    ) -> None:
        """Retire the old observer before an app-owned session replacement."""
        watcher = self._connection_watch_task
        watcher_key = self._connection_watch_key
        if watcher is None:
            if expected_close:
                self._expect_session_close(session, generation)
            return
        if expected_close and watcher_key is not None:
            self._expected_close_keys.add(watcher_key)
        if watcher is asyncio.current_task():
            return
        if not watcher.done():
            watcher.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(watcher),
                    SHUTDOWN_TASK_TIMEOUT,
                )
            except asyncio.TimeoutError:
                diagnostic_logger.warning("app.connection_watch.cancel_timeout")
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                diagnostic_logger.debug(
                    "app.connection_watch.cancel_failed type=%s",
                    type(exc).__name__,
                )
        if self._connection_watch_task is watcher:
            self._connection_watch_task = None
            self._connection_watch_key = None

    def _start_connection_watcher(
        self, session: SessionProtocol, generation: int
    ) -> None:
        """Observe close completion without becoming a second websocket reader."""
        if self._shutting_down or not self._session_is_current(session, generation):
            return
        wait_for_disconnect = getattr(session, "wait_for_disconnect", None)
        # Older test doubles and third-party session adapters can still drive
        # the TUI; the concrete HermesSession enforces this capability before
        # hello_ack, so a missing method here is never a live supported path.
        if not callable(wait_for_disconnect):
            diagnostic_logger.debug("app.connection_watch.unsupported_adapter")
            return
        existing = self._connection_watch_task
        if existing is not None and not existing.done():
            if self._connection_watch_key == (id(session), generation):
                return
            diagnostic_logger.error("app.connection_watch.duplicate_suppressed")
            return
        try:
            watcher = asyncio.create_task(
                self._watch_connection(session, generation),
                name=f"watch relay connection {generation}",
            )
        except Exception as exc:
            diagnostic_logger.debug(
                "app.connection_watch.create_failed type=%s",
                type(exc).__name__,
            )
            return
        self._connection_watch_task = watcher
        self._connection_watch_key = (id(session), generation)
        self._track_cleanup_task(watcher)

    async def _watch_connection(
        self, session: SessionProtocol, generation: int
    ) -> None:
        """Turn a verified close into one idempotent app-owned loss signal."""
        key = (id(session), generation)
        try:
            wait_for_disconnect = getattr(session, "wait_for_disconnect", None)
            if not callable(wait_for_disconnect):
                raise TypeError("session adapter lacks wait_for_disconnect()")
            result = wait_for_disconnect()
            if not inspect.isawaitable(result):
                raise TypeError("wait_for_disconnect() must be awaitable")
            await result
        except asyncio.CancelledError:
            return
        except TransportError:
            if self._session_is_current(session, generation) and key not in self._expected_close_keys:
                await self._mark_connection_lost(
                    session=session,
                    generation=generation,
                )
        except Exception as exc:
            if self._session_is_current(session, generation) and key not in self._expected_close_keys:
                diagnostic_logger.error(
                    "app.connection_watch.failed type=%s",
                    type(exc).__name__,
                )
                self._append_block(
                    "[error] connection liveness monitoring failed "
                    f"({type(exc).__name__}); connection state unchanged.",
                    role="error",
                )
        else:
            if self._session_is_current(session, generation) and key not in self._expected_close_keys:
                await self._mark_connection_lost(
                    session=session,
                    generation=generation,
                )
        finally:
            self._expected_close_keys.discard(key)
            if self._connection_watch_task is asyncio.current_task():
                self._connection_watch_task = None
                self._connection_watch_key = None

    def _refresh_connection_status(self) -> None:
        session_id = (
            getattr(self.session, "session_id", None)
            or getattr(self.args, "session_id", None)
            or "session"
        )
        symbol = {
            CONNECTION_CONNECTED: "●",
            CONNECTION_CONNECTING: "◌",
            CONNECTION_RETRYING: "◌",
            CONNECTION_DISCONNECTED: "○",
        }.get(self.connection_state, "○")
        model_part = (
            f" · {self.session.confirmed_model}"
            if getattr(self.session, "confirmed_model", None)
            else ""
        )
        profile_part = (
            f" · Profile: {self._active_profile_display_name}"
            if self._active_profile_display_name
            else ""
        )
        line = f"{symbol} {self.connection_state}{profile_part} · session {session_id}{model_part}"
        self.sub_title = f"{self.connection_state}{profile_part} · session {session_id}{model_part}"
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

    def _hydrate_transcript(self, history: list[dict[str, Any]]) -> None:
        """Populate the visible transcript with historical turns from the relay."""
        if not history:
            return
        for item in history:
            role = str(item.get("role") or "assistant").lower()
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                self.transcript.add("user", content)
            elif role in ("assistant", "system"):
                self.transcript.add(role, content)
            elif role in ("thinking", "tool", "status"):
                if self.show_transcript_details:
                    self.transcript.add(role, content, detail=True)
        self._refresh_transcript()

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
        unavailable = self._audio_unavailable_reason is not None
        display_state = (
            VOICE_AUDIO_UNAVAILABLE
            if unavailable and self.voice_state in {VOICE_BUFFERING, VOICE_SPEAKING}
            else self.voice_state
        )
        line = f"● {display_state}"
        if unavailable and display_state != VOICE_AUDIO_UNAVAILABLE:
            line += f" · {VOICE_AUDIO_UNAVAILABLE}"
        if self.microphone_is_open:
            line += f"   [$warning]◉ {MIC_OPEN_LABEL}[/]"
        try:
            widget = self.query_one("#voice-status", Static)
            widget.update(line)
            for state in (
                VOICE_READY,
                VOICE_STARTING,
                VOICE_CONNECTING,
                VOICE_RECONNECTING,
                VOICE_DISCONNECTED,
                VOICE_HEARD,
                VOICE_LISTENING,
                VOICE_TRANSCRIBING,
                VOICE_THINKING,
                VOICE_SPEAKING,
                VOICE_BUFFERING,
                VOICE_INTERRUPTED,
                VOICE_ERROR,
            ):
                widget.set_class(state == display_state, f"-{state.rstrip('…')}")
            widget.set_class(
                unavailable and display_state == VOICE_AUDIO_UNAVAILABLE,
                "-audio-unavailable",
            )
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
        entries = [self._queue_preview(text) for text in self._queued_prompts]
        widget.update(f"Queue ({len(self._queued_prompts)} queued):\n" + "\n".join(entries))
        widget.display = True

    def _refresh_prompt_panel(self) -> None:
        try:
            panel = self.query_one("#prompt-panel", Static)
            prompt_input = self.query_one("#prompt-input", Input)
        except (NoMatches, ScreenStackError):
            return
        prompt = self._pending_prompt
        if prompt is None:
            panel.update("")
            panel.display = False
            prompt_input.display = False
            prompt_input.value = ""
            prompt_input.password = False
            return
        panel.display = True
        panel.update("\n".join(prompt.render_lines()))
        prompt_input.display = prompt.accepts_free_text
        prompt_input.password = prompt.masked
        prompt_input.disabled = prompt.awaiting_response
        if prompt.accepts_free_text:
            prompt_input.placeholder = (
                "masked value — Enter to submit, never shown"
                if prompt.masked
                else "type an answer — Enter to submit"
            )
            if prompt.masked and not prompt.awaiting_response:
                prompt_input.focus()

    # --- lifecycle ------------------------------------------------------------

    async def on_mount(self) -> None:
        self._install_session(
            self._new_session(self._doorway_session_args(self.args))
        )
        self._refresh_queue_shelf()
        self._refresh_prompt_panel()
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

    async def _prepare_fresh_recovery_session(self) -> bool:
        """Replace a lost session once, before its bounded verified handshake."""
        if self._recovery_session_ready:
            return True

        old_session = self.session
        old_generation = self._session_generation
        if old_session is not None:
            self._expect_session_close(old_session, old_generation)
            await self._stop_connection_watcher(
                old_session,
                old_generation,
                expected_close=True,
            )
            await self._close_player(abort=True)
            await self._close_session_for_reconnect(old_session)

        # Replacement preserves the visible partial answer, but the old
        # stream and prompt ownership must not remain live in the new session.
        self.transcript.finish_stream()
        self._refresh_transcript()
        if self._pending_prompt is not None:
            self._pending_prompt = None
            self._refresh_prompt_panel()

        try:
            recovery_args = self._doorway_session_args(self.args)
            fresh_session = self._new_session(recovery_args)
        except Exception as exc:
            diagnostic_logger.debug(
                "app.recovery.new_session_failed type=%s",
                type(exc).__name__,
            )
            self._recovery_session_ready = False
            self._append_block(f"[error] reconnect session setup failed: {exc}")
            return False

        self._install_session(fresh_session)
        self._recovery_session_ready = True
        if self._audio_input_touched:
            setter = getattr(self.session, "set_input_device", None)
            try:
                if callable(setter):
                    result = setter(self.audio_input_device)
                    if inspect.isawaitable(result):
                        await result
                else:
                    setattr(self.session, "input_device", self.audio_input_device)
            except Exception as exc:
                diagnostic_logger.debug(
                    "app.recovery.audio_input_restore_failed type=%s",
                    type(exc).__name__,
                )
                self._append_block(
                    f"[warning] audio input selection was not restored: {exc}"
                )
        return True

    async def _connect(
        self, *, force: bool = False, hydrate_history: bool = True
    ) -> bool:
        """Establish a session with bounded exponential-backoff retries."""
        # A prompt-triggered recovery and the explicit command use the same
        # guard. The first caller owns the fresh-session ladder; other prompts
        # remain FIFO-queued until that verified session exists.
        owns_recovery = (
            self._needs_reconnect
            and not force
            and not self._reconnect_in_flight
        )
        if owns_recovery:
            self._reconnect_in_flight = True
        try:
            async with self._connection_lock:
                if self.wake_armed and (
                    self._needs_reconnect or not self.session.is_connected()
                ):
                    self._disarm_wake(
                        "wake mode off — connection lost; microphone released. "
                        "Run /wake on after reconnect."
                    )
                reconnecting = self._needs_reconnect
                if reconnecting and not self._recovery_session_ready:
                    if not await self._prepare_fresh_recovery_session():
                        self._set_connection_state(CONNECTION_DISCONNECTED)
                        self._set_voice_state(VOICE_DISCONNECTED)
                        return False
                if self.session.is_connected() and not force and not reconnecting:
                    self._set_connection_state(CONNECTION_CONNECTED)
                    self._set_voice_state(VOICE_READY)
                    self._start_connection_watcher(
                        self.session,
                        self._session_generation,
                    )
                    return True

                retries = max(0, int(getattr(self.args, "connect_retries", 3)))
                retry_delay = max(0.0, float(getattr(self.args, "connect_retry_delay", 1.0)))
                attempts = retries + 1
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
                            self._append_block(
                                f"reconnecting… attempt {attempt + 1}/{attempts}"
                            )

                    try:
                        session = self.session
                        async with asyncio.timeout(HANDSHAKE_TIMEOUT):
                            hello = await session.connect()
                        if not session.is_connected():
                            raise ConnectionError("session did not establish a connection")
                    except asyncio.CancelledError:
                        self._set_connection_state(CONNECTION_DISCONNECTED)
                        self._set_voice_state(VOICE_DISCONNECTED)
                        raise
                    except Exception as exc:
                        last_error = exc
                        self._set_connection_state(CONNECTION_DISCONNECTED)
                        self._set_voice_state(VOICE_DISCONNECTED)
                        await self._close_session_with_timeout(
                            session,
                            event="app.connect.session_close",
                            timeout_message=(
                                "[warning] failed session cleanup timed out; continuing."
                            ),
                        )
                        self._append_block(
                            "[connection attempt "
                            f"{attempt + 1}/{attempts} failed: "
                            f"{self._connection_error_text(exc)}]"
                        )
                        continue

                    session_generation = self._session_generation
                    session_id = (
                        getattr(session, "session_id", None)
                        or getattr(self.args, "session_id", "session")
                    )
                    self._set_connection_state(CONNECTION_CONNECTED)
                    self.domain.reset_session(str(session_id) if session_id else None)
                    self._set_voice_state(VOICE_READY)
                    self._needs_reconnect = False
                    self._recovery_session_ready = False
                    self._start_connection_watcher(session, session_generation)
                    conn_details = []
                    if self._profiles_configured:
                        conn_details.append(f"profile {self._active_profile_name}")
                    chat_id = getattr(session, "confirmed_chat_id", None) or hello.get("chat_id")
                    if chat_id:
                        conn_details.append(f"chat {chat_id}")
                    if getattr(session, "confirmed_model", None):
                        conn_details.append(f"model {session.confirmed_model}")
                    elif getattr(self.args, "model", None):
                        conn_details.append(f"model {self.args.model} (unconfirmed)")
                    if getattr(session, "confirmed_server_version", None):
                        conn_details.append(f"relay v{session.confirmed_server_version}")
                    detail_suffix = f" ({', '.join(conn_details)})" if conn_details else ""
                    self._append_block(f"Connected to {session_id}{detail_suffix}.")
                    if (
                        hydrate_history
                        and not reconnecting
                        and getattr(session, "initial_history", None)
                    ):
                        self._hydrate_transcript(session.initial_history)
                    if (
                        not reconnecting
                        and not self._reconnect_in_flight
                        and not self._needs_reconnect
                        and not self._launch_wake_attempted
                        and getattr(self.args, "wake_enabled", False)
                    ):
                        self._launch_wake_attempted = True
                        await self._arm_wake()
                    return True

                self._recovery_session_ready = False
                self._set_connection_state(CONNECTION_DISCONNECTED)
                self._set_voice_state(VOICE_DISCONNECTED)
                self._append_block(
                    "[error] "
                    f"{self._connection_error_text(last_error)}; unable to connect "
                    f"after {attempts} attempt(s)"
                )
                self._append_block(RETRY_HINT)
                return False
        finally:
            if owns_recovery:
                self._reconnect_in_flight = False

    @staticmethod
    def _connection_error_text(error: BaseException) -> str:
        """Describe a connection failure without leaving timeout errors blank."""
        if isinstance(error, asyncio.TimeoutError):
            return f"hello handshake timed out after {HANDSHAKE_TIMEOUT:g}s"
        message = str(error).strip()
        return message or type(error).__name__

    async def _handle_reconnect_command(self, args: str) -> None:
        """Recover the transport with a fresh session and no prompt replay."""
        if args.strip():
            self._append_block("usage: /reconnect")
            return
        if self._reconnect_in_flight:
            self._append_block("reconnect is already in progress")
            return
        if self._profile_switch_is_busy():
            self._append_block(
                "[busy] Cannot reconnect while a turn, prompt, or voice capture is active."
            )
            return

        self._reconnect_in_flight = True
        try:
            if self.wake_armed:
                self._disarm_wake(
                    "wake mode off — reconnect released the microphone. "
                    "Run /wake on after reconnect."
                )

            async with self._connection_lock:
                self._needs_reconnect = True
                self._set_connection_state(CONNECTION_DISCONNECTED)
                self._set_voice_state(VOICE_DISCONNECTED)
                self._append_block(
                    "reconnect requested — starting a fresh Hermes session."
                )
                if not await self._prepare_fresh_recovery_session():
                    self._append_block(
                        "reconnect failed; no prompt was sent and queued prompts remain pending."
                    )
                    return

            # The handshake remains bounded and observable through the normal
            # connection ladder. A recovered session must not hydrate or drain
            # anything from the uncertain turn while the old transcript stays
            # visible to the user.
            connected = await self._connect(force=True, hydrate_history=False)
            if connected:
                self._append_block(
                    "reconnected; no prompt was sent and queued prompts remain pending."
                )
            else:
                self._append_block(
                    "reconnect failed; no prompt was sent and queued prompts remain pending."
                )
        finally:
            self._reconnect_in_flight = False

    async def _close_session_with_timeout(
        self,
        session: SessionProtocol,
        *,
        event: str,
        timeout_message: Optional[str] = None,
    ) -> None:
        """Run session cleanup with a bounded wait and safe late-task logging."""
        session_key = id(session)
        close_task = self._session_cleanup_tasks.get(session_key)
        if close_task is None or close_task.done():
            try:
                close_task = asyncio.create_task(session.close())
            except Exception as exc:
                diagnostic_logger.debug(
                    "%s.create_failed type=%s", event, type(exc).__name__
                )
                return
            self._session_cleanup_tasks[session_key] = close_task
            self._track_cleanup_task(close_task)
        try:
            await asyncio.wait_for(
                asyncio.shield(close_task),
                SHUTDOWN_TASK_TIMEOUT,
            )
        except asyncio.TimeoutError:
            diagnostic_logger.warning("%s.timeout", event)
            if timeout_message:
                self._append_block(timeout_message)
        except Exception as exc:
            diagnostic_logger.debug(
                "%s.failed type=%s", event, type(exc).__name__
            )

    async def _close_session_for_reconnect(self, session: SessionProtocol) -> None:
        """Bound old-session cleanup so a dead transport cannot trap recovery."""
        await self._close_session_with_timeout(
            session,
            event="app.reconnect.old_session_close",
            timeout_message=(
                "[warning] previous session cleanup timed out; continuing with a fresh session."
            ),
        )

    async def on_unmount(self) -> None:
        # Release the device before anything else. A quit that leaves the
        # microphone open is the worst possible way to end a session.
        if self._shutting_down:
            return
        self._shutting_down = True
        self._expect_session_close(self.session, self._session_generation)
        await self._stop_connection_watcher(
            self.session,
            self._session_generation,
            expected_close=True,
        )
        await self._cancel_shutdown_tasks()
        await self._abort_earcon()
        self._disarm_wake()
        await self._wait_for_cleanup_tasks()
        await self._close_player(abort=True)
        if self.session is not None:
            await self._close_session_for_shutdown()

    def _track_cleanup_task(self, task: asyncio.Task[Any]) -> None:
        """Retain cleanup work that outlives the command that started it."""
        self._cleanup_tasks.add(task)

        def finished(done: asyncio.Task[Any]) -> None:
            self._cleanup_tasks.discard(done)
            self._wake_cleanup_tasks.discard(done)
            for session_key, tracked in tuple(self._session_cleanup_tasks.items()):
                if tracked is done:
                    self._session_cleanup_tasks.pop(session_key, None)
            try:
                done.result()
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                diagnostic_logger.debug(
                    "app.shutdown.cleanup_failed type=%s", type(exc).__name__
                )

        task.add_done_callback(finished)

    async def _wait_for_cleanup_tasks(self) -> None:
        tasks = [task for task in self._cleanup_tasks if not task.done()]
        if not tasks:
            return
        gathered = asyncio.gather(*tasks, return_exceptions=True)
        try:
            await asyncio.wait_for(
                asyncio.shield(gathered),
                SHUTDOWN_TASK_TIMEOUT,
            )
        except asyncio.TimeoutError:
            diagnostic_logger.warning(
                "app.shutdown.cleanup_timeout count=%d", len(tasks)
            )

    async def _wait_for_wake_cleanup(self) -> bool:
        """Keep a new listener from racing the old stream's native close."""
        tasks = [task for task in self._wake_cleanup_tasks if not task.done()]
        if not tasks:
            return True
        gathered = asyncio.gather(*tasks, return_exceptions=True)
        try:
            await asyncio.wait_for(
                asyncio.shield(gathered),
                SHUTDOWN_TASK_TIMEOUT,
            )
        except asyncio.TimeoutError:
            diagnostic_logger.warning(
                "app.wake.cleanup_timeout count=%d", len(tasks)
            )
            self._append_block(
                "[error] previous microphone cleanup is still in progress; "
                "wake mode remains off."
            )
            return False
        return True

    async def _close_session_for_shutdown(self) -> None:
        """Give session cleanup a budget so quit cannot wait on a dead socket."""
        await self._close_session_with_timeout(
            self.session,
            event="app.shutdown.session_close",
        )

    async def _cancel_shutdown_tasks(self) -> None:
        """Stop app-owned workers before their resources are torn down."""
        current_task = asyncio.current_task()
        task_attributes = (
            "_voice_capture_task",
            "_active_turn_task",
            "_caption_task",
            "_barge_interrupt_task",
            "_barge_result_task",
            "_wake_start_task",
        )
        tasks = []
        for attribute in task_attributes:
            task = getattr(self, attribute)
            if task is None or task is current_task:
                continue
            done = getattr(task, "done", None)
            cancel = getattr(task, "cancel", None)
            if callable(done) and callable(cancel) and not done():
                tasks.append(task)

        for task in tasks:
            task.cancel()
        if not tasks:
            return

        gathered = asyncio.gather(*tasks, return_exceptions=True)
        try:
            await asyncio.wait_for(
                asyncio.shield(gathered),
                SHUTDOWN_TASK_TIMEOUT,
            )
        except asyncio.TimeoutError:
            diagnostic_logger.warning(
                "app.shutdown.task_timeout count=%d", len(tasks)
            )

    async def _abort_earcon(self) -> None:
        """Stop a courtesy tone before waiting for the wake worker to exit."""
        abort = getattr(self._earcons, "abort", None)
        if callable(abort):
            await asyncio.to_thread(abort)

    # --- wake mode ------------------------------------------------------

    async def _handle_wake_command(self, args: str) -> None:
        """/wake [on|off|status] — hands-free listening, armed on purpose."""
        choice = args.strip().lower()
        if choice in ("", "status"):
            self._report_wake_status()
        elif choice == "on":
            await self._arm_wake()
        elif choice == "off":
            if self._wake_starting:
                self._wake_start_cancelled = True
                self._disarm_wake()
                self._append_block(
                    "wake mode off — startup cancelled; microphone released"
                )
                return
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
        engine = getattr(self.args, "wake_engine", "openwakeword")
        phrases = getattr(self.args, "wake_phrases", None)
        if engine == "sherpa" or phrases:
            detail = f"engine: sherpa · phrases: {phrases or 'hey hermes'}"
        else:
            model = getattr(self.args, "wake_model", None) or "bundled hey_hermes"
            threshold = getattr(self.args, "wake_threshold", 0.6)
            detail = f"model: {model} · threshold: {threshold}"
        self._append_block(f"wake mode: on — listening · {detail}")

    async def _arm_wake(self) -> None:
        if self._reconnect_in_flight:
            return
        if self.wake_armed:
            self._append_block("wake mode is already on")
            return
        if self._wake_starting:
            self._append_block("wake mode startup is already in progress")
            return
        if not await self._wait_for_wake_cleanup():
            return

        start_task = asyncio.current_task()
        self._wake_start_task = start_task
        self._wake_starting = True
        self._wake_start_cancelled = False
        self._wake_unavailable_reported = False
        self._set_voice_state(VOICE_STARTING)
        self._append_block("wake mode starting — loading wake model…")

        # Keep the builder's complete wake configuration, while ensuring this
        # path always requests an active hands-free listener.
        args = copy.copy(self.args)
        args.wake_enabled = True

        try:
            stage_started = time.perf_counter()
            diagnostic_logger.debug("wake.start stage=model begin")
            built = await asyncio.to_thread(
                self._build_hands_free,
                self.session,
                args,
                capture=self._capture_wake_voice,
                follow_up_capture=self._capture_wake_follow_up,
                send=self._send_wake_turn,
                is_ready=self._connection_is_ready,
                speech_detected=self._wake_speech_detected,
                stop_playback=self._abort_player,
                acknowledge=self._acknowledge_wake,
                capture_finished=self._acknowledge_capture,
                on_state_change=self._wake_state_changed,
                on_unavailable=self._wake_unavailable,
            )
            diagnostic_logger.debug(
                "wake.start stage=model complete elapsed=%.3f",
                time.perf_counter() - stage_started,
            )
            if self._wake_start_cancelled or self._reconnect_in_flight:
                self._disarm_wake()
                return
            if built is None:
                self._set_voice_state(VOICE_ERROR)
                self._append_block("[error] wake mode could not be started")
                return

            listener, coordinator = built
            self._wake_loop = asyncio.get_running_loop()
            self._wake_listener = listener
            self._wake_coordinator = coordinator
            if self._wake_start_cancelled or self._reconnect_in_flight:
                self._disarm_wake()
                return

            factory = self._recorder_factory
            if factory is None:
                from voice import create_audio_recorder

                factory = create_audio_recorder
            recorder = await asyncio.to_thread(factory)
            self._wake_recorder = recorder
            if self._wake_start_cancelled:
                self._disarm_wake()
                return

            self.session.use_shared_recorder(recorder)

            barge_listener = None
            if getattr(args, "wake_barge_in", False):
                barge_listener = self._make_barge_listener(recorder)
                self._barge_listener = barge_listener

            # Start the worker before opening the stream. Reversed, frames
            # pile into a bounded queue with nothing draining it and the
            # entire warm-up is dropped audio — measured at 96 frames on the
            # appliance.
            listener.start()
            if barge_listener is not None:
                barge_listener.start()
            recorder.set_frame_observer(listener.submit)
            if barge_listener is not None:
                add_observer = getattr(recorder, "add_frame_observer", None)
                if callable(add_observer):
                    add_observer(barge_listener.submit)
                    self._barge_recorder_observer = barge_listener.submit
                else:
                    # Keep compatibility with an injected recorder that only
                    # predates shared taps. The real AudioRecorder supports
                    # add/remove, so this fallback is test and plugin glue.
                    def dispatch_frame(frame):
                        listener.submit(frame)
                        barge_listener.submit(frame)

                    recorder.set_frame_observer(dispatch_frame)
                    self._barge_recorder_observer = dispatch_frame
            self._append_block("wake mode starting — opening microphone…")
            stage_started = time.perf_counter()
            diagnostic_logger.debug("wake.start stage=microphone begin")
            self._wake_opening = True
            opening = asyncio.create_task(
                asyncio.to_thread(recorder.open_for_listening)
            )
            self._wake_open_task = opening
            try:
                await asyncio.shield(opening)
            except asyncio.CancelledError:
                if not opening.done():
                    self._disarm_wake()
                else:
                    self._wake_opening = False
                    self._disarm_wake()
                raise
            except Exception:
                self._wake_opening = False
                raise
            self._wake_opening = False
            if self._wake_open_task is opening:
                self._wake_open_task = None
            diagnostic_logger.debug(
                "wake.start stage=microphone complete elapsed=%.3f",
                time.perf_counter() - stage_started,
            )
            if self._wake_start_cancelled or self._reconnect_in_flight:
                self._disarm_wake()
                return

            self.wake_armed = True
            self._set_voice_state(VOICE_READY)
            self._refresh_voice_status()
            self._set_wake_listening(busy=self._turn_in_flight)
            self._append_block(
                "wake mode on — say the phrase. The microphone stays open until "
                "/wake off."
            )
        except asyncio.CancelledError:
            self._disarm_wake()
            raise
        except Exception as error:
            self._wake_opening = False
            self._disarm_wake()
            self._set_voice_state(VOICE_ERROR)
            self._append_block(f"[error] wake mode: {self._wake_failure_text(error)}")
        finally:
            self._wake_starting = False
            self._wake_start_cancelled = False
            if self._wake_start_task is start_task:
                self._wake_start_task = None
            if (
                self._wake_open_task is not None
                and self._wake_open_task.done()
            ):
                self._wake_open_task = None

    def _finish_cancelled_wake_open(self, recorder: Any, opening: Any) -> None:
        """Close a recorder whose native open outlived a cancelled task."""
        self._schedule_wake_cleanup(
            session=self.session,
            listener=None,
            recorder=recorder,
            barge_listener=None,
            barge_observer=None,
            opening=opening,
        )

    def _wake_failure_text(self, error: Exception) -> str:
        """Turn an arming failure into the one sentence that fixes it."""
        import wake  # noqa: PLC0415 - the optional-dependency seam

        if isinstance(error, wake.MissingWakeDependency):
            return (
                "the wake-word engine is not installed. "
                "Install it with: hermes-relay install"
            )
        return str(error)

    def _schedule_wake_cleanup(
        self,
        *,
        session: Any,
        listener: Any,
        recorder: Any,
        barge_listener: Any,
        barge_observer: Any,
        opening: Any,
    ) -> Optional[asyncio.Task[Any]]:
        """Finish detached wake resources without using the Textual loop."""
        if not any(
            resource is not None
            for resource in (listener, recorder, barge_listener, opening)
        ):
            return None

        async def invoke(label: str, operation: Any) -> None:
            if not callable(operation):
                return
            try:
                await asyncio.to_thread(operation)
            except Exception:
                diagnostic_logger.debug(
                    "app.wake.%s_failed type=%s", label, type(operation).__name__
                )

        async def finish() -> None:
            # Cancellation must reach an active capture before the listener
            # joins. Capture and native audio are both blocking operations,
            # hence every call below stays in the worker thread pool.
            await invoke("cancel_voice", getattr(session, "cancel_voice", None))
            if recorder is not None and barge_observer is not None:
                await invoke(
                    "remove_barge_observer",
                    lambda: recorder.remove_frame_observer(barge_observer),
                )
            await invoke("listener_stop", getattr(listener, "stop", None))
            await invoke("barge_listener_stop", getattr(barge_listener, "stop", None))
            if opening is not None:
                try:
                    await asyncio.shield(opening)
                except BaseException:
                    pass
            await invoke("recorder_shutdown", getattr(recorder, "shutdown", None))

        task = asyncio.create_task(finish(), name="wake resource cleanup")
        self._wake_cleanup_tasks.add(task)
        self._track_cleanup_task(task)
        return task

    def _disarm_wake(self, message: Optional[str] = None) -> Optional[asyncio.Task[Any]]:
        """Detach wake resources now; join and native close them off-loop."""
        was_starting = self._wake_starting
        if was_starting:
            self._wake_start_cancelled = True
        listener, recorder = self._wake_listener, self._wake_recorder
        barge_listener = self._barge_listener
        opening = self._wake_open_task
        self._wake_open_task = None
        session = self.session
        barge_observer = self._barge_recorder_observer
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None
        for task in (self._barge_interrupt_task, self._barge_result_task):
            if task is not None and task is not current_task and not task.done():
                task.cancel()
        self._barge_interrupt_task = None
        if self._barge_result_task is not current_task:
            self._barge_result_task = None
        # This is the non-blocking logical shutdown boundary. The real
        # listener's quiesce() only flips its admission gate and drops no
        # native resource; the bounded join remains in the tracked cleanup.
        quiesce = getattr(listener, "quiesce", None)
        if callable(quiesce):
            try:
                quiesce()
            except Exception:
                diagnostic_logger.debug(
                    "quiescing the wake listener failed", exc_info=True
                )
        deactivate = getattr(barge_listener, "deactivate", None)
        if callable(deactivate):
            try:
                deactivate()
            except Exception:
                diagnostic_logger.debug(
                    "deactivating the barge-in listener failed", exc_info=True
                )
        self._wake_listener = None
        self._wake_coordinator = None
        self._wake_recorder = None
        self._barge_listener = None
        self._barge_capture_active = False
        self._barge_was_playing = False
        self._wake_loop = None
        self._wake_opening = False
        was_armed = self.wake_armed
        self.wake_armed = False
        self._refresh_voice_status()
        if was_starting and not self._turn_in_flight:
            self._set_voice_state(VOICE_READY)
        self._barge_recorder_observer = None
        cleanup = self._schedule_wake_cleanup(
            session=session,
            listener=listener,
            recorder=recorder,
            barge_listener=barge_listener,
            barge_observer=barge_observer,
            opening=opening,
        )
        if message and was_armed:
            self._append_block(message)
        return cleanup

    def _make_barge_listener(self, recorder: Any) -> Any:
        """Build the local speech tap used during an active remote turn."""
        factory = self._barge_listener_factory
        if factory is None:
            from voice import BargeInListener

            factory = BargeInListener
        return factory(
            on_speech_start=self._on_barge_speech_start,
            on_transcript=self._on_barge_transcript,
            silence_duration=getattr(self.args, "mic_silence_duration", 1.5),
            silence_threshold=getattr(self.args, "mic_silence_threshold", 200),
            max_seconds=getattr(self.args, "mic_max_seconds", 15.0),
            min_speech_duration=getattr(
                self.args, "wake_barge_in_min_speech_duration", 0.30
            ),
            sample_rate=getattr(
                recorder,
                "sample_rate",
                getattr(recorder, "_sample_rate", 16000),
            ),
            is_playing=lambda: self.player.active,
            model=getattr(self.args, "stt_model", None),
        )

    def _set_barge_listening(self, *, active: bool) -> None:
        listener = self._barge_listener
        if listener is None:
            return
        if active:
            listener.activate()
        else:
            listener.deactivate()

    def _on_barge_speech_start(self) -> None:
        """Interrupt promptly; local STT only decides whether to follow up."""
        if not self._turn_in_flight or self._barge_capture_active:
            return
        self._barge_capture_active = True
        self._barge_was_playing = bool(self.player.active)
        self._begin_barge_interrupt()

    def _begin_barge_interrupt(self) -> None:
        if not self._barge_capture_active or not self._turn_in_flight:
            return
        if self._barge_interrupt_task is not None and not self._barge_interrupt_task.done():
            return
        self._barge_interrupt_task = asyncio.create_task(
            self._interrupt_active_turn(),
            name="spoken barge-in interrupt",
        )

    def _on_barge_transcript(self, transcript: str) -> None:
        loop = self._wake_loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._handle_barge_transcript, transcript)
        except RuntimeError:
            return

    def _handle_barge_transcript(self, transcript: str) -> None:
        """Use local STT to decide whether an interruption becomes a new turn."""
        if not self._barge_capture_active:
            return
        # The remote confirmation can finish the active turn before Whisper's
        # worker posts its transcript. Keep that one already-triggered
        # interruption alive long enough to decide whether a follow-up exists.
        if not self._turn_in_flight and self._barge_interrupt_task is None:
            self._set_barge_listening(active=False)
            self._barge_capture_active = False
            self._barge_was_playing = False
            self._set_wake_listening(busy=self._turn_in_flight)
            return
        if not (transcript or "").strip():
            self._set_barge_listening(active=False)
            self._barge_capture_active = False
            self._barge_was_playing = False
            self._set_wake_listening(busy=self._turn_in_flight)
            return
        self._begin_barge_interrupt()
        self._queue_barge_transcript(transcript)

    def _queue_barge_transcript(self, transcript: str) -> None:
        if not self._barge_capture_active:
            return
        if self._barge_result_task is not None and not self._barge_result_task.done():
            return
        self._barge_result_task = asyncio.create_task(
            self._complete_barge_in(transcript),
            name="spoken barge-in transcript",
        )

    async def _complete_barge_in(self, transcript: str) -> None:
        history = self._history
        try:
            interrupt_task = self._barge_interrupt_task
            if interrupt_task is None and self._turn_in_flight:
                self._begin_barge_interrupt()
                interrupt_task = self._barge_interrupt_task
            if interrupt_task is not None:
                try:
                    await interrupt_task
                except asyncio.CancelledError:
                    return

            self._set_barge_listening(active=False)
            self._barge_capture_active = False
            self._set_wake_listening(busy=self._turn_in_flight)
            if self._barge_was_playing:
                from voice import is_tts_echo

                if is_tts_echo(transcript, self._last_tts_text):
                    diagnostic_logger.debug("app.barge.echo_suppressed")
                    transcript = ""
            if handsfree.is_local_stop_command(transcript or ""):
                if not self._turn_in_flight:
                    self._set_voice_state(VOICE_READY)
                return
            text = (transcript or "").strip()
            if not text:
                if not self._turn_in_flight:
                    self._set_voice_state(VOICE_READY)
                return
            self._set_voice_state(VOICE_TRANSCRIBING)
            await asyncio.to_thread(history.append, text)
            await self._run_turn(text, stt_source="local-faster-whisper")
        finally:
            if self._barge_result_task is asyncio.current_task():
                self._barge_result_task = None
            if self._barge_interrupt_task is not None and self._barge_interrupt_task.done():
                self._barge_interrupt_task = None
            self._barge_was_playing = False

    async def _cancel_active_barge_capture(self) -> bool:
        if not self._barge_capture_active:
            return False
        listener = self._barge_listener
        if listener is not None:
            cancel = getattr(listener, "cancel_capture", None)
            if callable(cancel):
                cancel()
        self._barge_capture_active = False
        self._barge_was_playing = False
        result_task = self._barge_result_task
        if result_task is not None and not result_task.done():
            result_task.cancel()
            try:
                await result_task
            except asyncio.CancelledError:
                pass
        interrupt_task = self._barge_interrupt_task
        if interrupt_task is not None and not interrupt_task.done():
            try:
                await interrupt_task
            except asyncio.CancelledError:
                pass
        elif self._turn_in_flight:
            await self._interrupt_active_turn()
        self._set_barge_listening(active=False)
        self._set_wake_listening(busy=self._turn_in_flight)
        return True

    def _set_wake_listening(self, *, busy: bool) -> None:
        """Listen only when nothing else holds the microphone.

        A turn or a Ctrl+R capture owns the input stream, and pausing resets
        the detector's rolling buffer. Without this the client wakes itself on
        the tail of the phrase it has just recorded. A successful wake turn
        also keeps the coordinator busy while it hands the microphone to the
        next wake-free follow-up; do not reopen detection in that small gap.
        """
        listener = self._wake_listener
        if listener is None:
            return
        coordinator = self._wake_coordinator
        conversation_busy = (
            coordinator is not None and coordinator.state != handsfree.IDLE
        )
        if busy or self._barge_capture_active or conversation_busy:
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
        if state in {
            handsfree.ACKNOWLEDGING,
            handsfree.CAPTURING,
            handsfree.SENDING,
        }:
            self._preserve_wake_terminal_state = False
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

    def _wake_unavailable(self) -> None:
        """Move a listener that lost authorization onto the recovery path."""
        loop = self._wake_loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._handle_wake_unavailable)
        except RuntimeError:
            # Teardown can close the loop between reading the reference and
            # scheduling the recovery repaint.
            return

    def _handle_wake_unavailable(self) -> None:
        """Report one wake readiness failure and release its microphone."""
        if not self.wake_armed or self._wake_unavailable_reported:
            return
        self._wake_unavailable_reported = True
        self._track_cleanup_task(asyncio.create_task(self._mark_connection_lost()))

    def _apply_wake_state(self, state: str) -> None:
        """Apply a worker-reported wake phase on Textual's event loop."""
        if not self.wake_armed:
            return
        if state == handsfree.ACKNOWLEDGING and not self._turn_in_flight:
            self._set_voice_state(VOICE_HEARD)
        elif state == handsfree.CAPTURING and not self._turn_in_flight:
            self._set_voice_state(VOICE_LISTENING)
        elif state == handsfree.SENDING and not self._turn_in_flight:
            self._set_voice_state(VOICE_TRANSCRIBING)
        elif (
            state == handsfree.IDLE
            and not self._turn_in_flight
            and self._voice_capture_task is None
            and not (
                self._preserve_wake_terminal_state
                and self.voice_state
                in {VOICE_ERROR, VOICE_INTERRUPTED, VOICE_DISCONNECTED}
            )
        ):
            self._set_voice_state(VOICE_READY)

    def _capture_wake_voice(self) -> str:
        """Capture the utterance after the wake phrase with a real bound."""
        if not self._connection_is_ready():
            return ""
        timeout = getattr(
            self.args, "wake_listen_timeout", handsfree.DEFAULT_LISTEN_TIMEOUT
        )
        return self.session.capture_voice(wait_timeout=float(timeout))

    def _capture_wake_follow_up(self) -> str:
        """Give a speaker one bounded, wake-word-free conversational window."""
        if not self._connection_is_ready():
            return ""
        timeout = getattr(self.args, "wake_followup_seconds", 8.0)
        return self.session.capture_voice(wait_timeout=float(timeout))

    def _wake_speech_detected(self) -> bool:
        return bool(getattr(self._wake_recorder, "has_detected_speech", False))

    def _acknowledge_wake(self) -> None:
        self._earcons.play(earcons_module.WAKE)

    def _acknowledge_capture(self) -> None:
        self._earcons.play(earcons_module.CAPTURE_DONE)

    def _send_wake_turn(self, text: str) -> bool:
        """Run one wake turn on the event loop, blocking the listener thread.

        Blocking is the point: the coordinator is single-flight, so while this
        is outstanding a second detection is dropped instead of becoming an
        overlapping turn.
        """
        loop = self._wake_loop
        if loop is None:
            return False
        if not (text or "").strip():
            return False
        history = self._history
        future = asyncio.run_coroutine_threadsafe(
            self._run_turn(text, stt_source="local"), loop
        )
        try:
            return bool(future.result())
        finally:
            # This callback runs on the wake worker, not Textual's event loop.
            # Persist after the turn is underway so a local fsync cannot delay
            # the first playback frame or the wake coordinator's timing.
            history.append(text)

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
        if self._pending_prompt is not None:
            # A structured prompt is waiting on the composer's own input
            # widget, not this one. Treat this as an ordinary message that
            # would otherwise become an accidental second turn.
            event.composer.load_text("")
            self._enqueue_prompt(text)
            return
        history = self._history
        self.run_worker(
            self._submit_text(text, composer=event.composer, history=history),
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
        elif len(path_candidates) > 1:
            common = os.path.commonprefix(path_candidates)
            if len(common) > len(event.text):
                event.composer.load_text(common)
                event.composer.move_cursor((0, len(event.composer.text)))
                return

        candidates = complete_slash_command(event.text)
        if len(candidates) == 1:
            event.composer.load_text(f"{candidates[0]} ")
            event.composer.move_cursor((0, len(event.composer.text)))
        elif len(candidates) > 1:
            common = os.path.commonprefix(candidates)
            if len(common) > len(event.text):
                event.composer.load_text(common)
                event.composer.move_cursor((0, len(event.composer.text)))
            elif any(c.lower() == event.text.lower() for c in candidates):
                exact = next(c for c in candidates if c.lower() == event.text.lower())
                event.composer.load_text(f"{exact} ")
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

    async def on_composer_prompt_option_selected(
        self, event: Composer.PromptOptionSelected
    ) -> None:
        self.run_worker(
            self._answer_prompt(option_id=event.option_id, value=None),
            name="prompt response",
            group="interaction",
            exit_on_error=False,
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "prompt-input":
            return
        prompt = self._pending_prompt
        if prompt is None or prompt.awaiting_response:
            return
        value = event.value
        event.input.value = ""
        self.run_worker(
            self._answer_prompt(option_id=None, value=value),
            name="prompt response",
            group="interaction",
            exit_on_error=False,
        )

    def _prompt_is_current(self, prompt: PendingPrompt) -> bool:
        """Bind legacy untagged doubles, then reject crossed generations."""
        prompt_session = getattr(prompt, "session_identity", None)
        prompt_generation = getattr(prompt, "session_generation", None)
        if prompt_session is None:
            prompt.session_identity = self.session
            prompt.session_generation = self._session_generation
            return True
        return self._session_is_current(prompt_session, prompt_generation)

    async def _answer_prompt(self, *, option_id: Optional[str], value: Optional[str]) -> None:
        """Send exactly one response for the currently pending prompt.

        `value` is never logged or appended to the transcript — sudo/secret
        answers reuse this path and must never surface anywhere but the
        websocket write in session.send_prompt_response.
        """
        prompt = self._pending_prompt
        if prompt is None or prompt.awaiting_response:
            return
        if not self._prompt_is_current(prompt):
            diagnostic_logger.debug("app.prompt.stale_response_rejected")
            if self._pending_prompt is prompt:
                self._pending_prompt = None
                self._refresh_prompt_panel()
            return
        prepared = self.domain.prepare_prompt_action(option_id=option_id, value=value)
        if not prepared.accepted or prepared.action is None:
            diagnostic_logger.debug(
                "app.prompt.rejected reason=%s", prepared.reason or "unknown"
            )
            return
        action = prepared.action
        prompt.awaiting_response = True
        prompt.rejection_reason = None
        self._refresh_prompt_panel()
        try:
            sent = await prompt.session_identity.send_prompt_response(
                prompt_id=action.prompt_id,
                prompt_kind=action.prompt_kind,
                option_id=action.option_id,
                value=action.value,
            )
        except Exception as exc:
            if _is_transport_error(exc):
                await self._mark_connection_lost(
                    session=prompt.session_identity,
                    generation=prompt.session_generation,
                )
            if (
                self._pending_prompt is prompt
                and self._prompt_is_current(prompt)
            ):
                self.domain.prompt_response_failed(str(exc))
                prompt.awaiting_response = False
                self._append_block(f"[error] prompt response: {exc}", role="error")
                self._refresh_prompt_panel()
                if _is_transport_error(exc):
                    self._append_block(RETRY_HINT)
            return
        if not sent and self._pending_prompt is prompt and self._prompt_is_current(prompt):
            self.domain.prompt_response_failed("structured prompts unsupported")
            prompt.awaiting_response = False
            self._append_block(
                "[error] endpoint does not support structured prompts; response not sent",
                role="error",
            )
            self._refresh_prompt_panel()

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
            await self.action_show_help(invocation.args)
        elif command.name == "clear":
            self.transcript.clear()
            self._refresh_transcript()
        elif command.name == "status":
            session_id = (
                getattr(self.session, "session_id", None)
                or getattr(self.args, "session_id", "session")
            )
            model = getattr(self.session, "confirmed_model", None) or getattr(self.args, "model", None) or "default"
            model_label = f"{model} (confirmed)" if getattr(self.session, "confirmed_model", None) else f"{model} (unconfirmed)"
            chat_id = getattr(self.session, "confirmed_chat_id", None)
            chat_label = f" · chat: {chat_id}" if chat_id else ""
            version = getattr(self.session, "confirmed_server_version", None)
            ver_label = f" · relay: v{version}" if version else ""
            caps = sorted(getattr(self.session, "capabilities", ()))
            caps_label = f" · caps: {','.join(caps)}" if caps else ""
            config_path = getattr(self.args, "config", None)
            endpoint = str(getattr(self.args, "url", "")).split("?", 1)[0] or "-"
            self._append_block(
                f"profile: {self._active_profile_name} · endpoint: {endpoint} · "
                f"session: {session_id} · {self.connection_state} · model: {model_label}{chat_label}{ver_label}{caps_label} "
                f"· busy-mode: {self.busy_mode} · queued: {len(self._queued_prompts)} "
                f"· history: {self._history.path} · config: {config_path}"
            )
        elif command.name == "profile":
            await self._handle_profile_command(invocation.args)
        elif command.name == "session":
            await self._handle_session_command(invocation.args)
        elif command.name == "sessions":
            await self._handle_session_list_command(invocation.args)
        elif command.name == "resume":
            await self._handle_session_resume_command(invocation.args)
        elif command.name == "new":
            await self._handle_session_new_command(invocation.args)
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
        elif command.name == "reconnect":
            await self._handle_reconnect_command(invocation.args)
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

    def _load_profile_catalog(self) -> list[config.RelayProfile]:
        config_path = getattr(self.args, "config", None)
        document = config.load_config_file(config_path) if config_path else {}
        profile_env = getattr(self.args, "profile_env", None)
        profile_args = copy.copy(self.args)
        if profile_env is not None:
            profile_args.profile_env = profile_env
        return config.load_relay_profiles(document, profile_args)

    def _profile_switch_is_busy(self) -> bool:
        if self._turn_in_flight or self._wake_starting or self._barge_capture_active:
            return True
        capture = self._voice_capture_task
        if capture is not None and not capture.done():
            return True
        return self._pending_prompt is not None

    def _profile_switch_busy_message(self) -> str:
        if self._turn_in_flight:
            return "[busy] Cannot switch profile while a turn is active."
        if self._pending_prompt is not None:
            return (
                "[busy] Cannot switch profile while a structured prompt is awaiting an answer."
            )
        return "[busy] Cannot switch profile while voice capture is active."

    async def _switch_to_args(self, new_args: Any, *, reason: str) -> bool:
        """Replace the relay session only after the old target is closed."""
        if self._profile_switch_is_busy():
            self._append_block(self._profile_switch_busy_message())
            return False

        old_args = self.args
        old_name = self._active_profile_name
        new_name = (
            getattr(new_args, "profile_name", None)
            or getattr(new_args, "profile", None)
            or "default"
        )
        old_endpoint = str(getattr(old_args, "url", "")).split("?", 1)[0] or "-"
        new_endpoint = str(getattr(new_args, "url", "")).split("?", 1)[0] or "-"
        dropped_queue = len(self._queued_prompts)
        dropped_attachments = len(self._staged_attachments)
        async with self._connection_lock:
            if self.wake_armed or self._wake_starting:
                self._disarm_wake(
                    "wake mode off — profile switching released the microphone. "
                    "Run /wake on after switching if needed."
                )
            old_session = self.session
            if old_session is not None:
                old_generation = self._session_generation
                self._expect_session_close(old_session, old_generation)
                await self._stop_connection_watcher(
                    old_session,
                    old_generation,
                    expected_close=True,
                )
                await self._close_player(abort=True)
                await self._close_session_with_timeout(
                    old_session,
                    event="app.profile.old_session_close",
                    timeout_message=(
                        "[warning] previous session cleanup timed out; continuing with a fresh session."
                    ),
                )

            self.args = new_args
            self._sync_profile_metadata(new_args)
            self._install_session(
                self._new_session(self._doorway_session_args(new_args))
            )
            self.domain.reset_session(
                getattr(self.session, "session_id", None)
                or getattr(new_args, "session_id", None)
            )
            self._needs_reconnect = False
            self._history = self._prompt_history_for_args(new_args)
            self._queued_prompts.clear()
            self._staged_attachments.clear()
            self._pending_prompt = None
            self._last_prompt = None
            self._last_prompt_status = None
            self._refresh_queue_shelf()
            self._refresh_prompt_panel()
            self.transcript.clear()
            self._refresh_transcript()
            self._set_connection_state(CONNECTION_CONNECTING)
            self._set_voice_state(VOICE_CONNECTING)
            detail = (
                f"{reason}: switching profile {old_name} → {new_name}; "
                f"closed {old_endpoint}, connecting to {new_endpoint}."
            )
            if dropped_queue:
                detail += f" Discarded {dropped_queue} queued prompt(s); none were replayed."
            if dropped_attachments:
                detail += f" Cleared {dropped_attachments} staged attachment(s)."
            self._append_block(detail)

        # Keep the lock free while the new hello handshake waits on the relay.
        return await self._connect(force=True)

    async def _handle_profile_command(self, args: str) -> None:
        """List profiles or deliberately replace the active relay target."""
        parts = args.strip().split(maxsplit=1)
        action = parts[0].lower() if parts else "list"
        sub_args = parts[1].strip() if len(parts) > 1 else ""
        if action in {"list", "ls", "status", "show"}:
            try:
                profiles = self._load_profile_catalog()
            except (OSError, UnicodeDecodeError, ValueError, SystemExit) as exc:
                self._append_block(f"[error] /profile: {exc}")
                return
            if action in {"status", "show"} and not sub_args:
                sub_args = self._active_profile_name
            lines = ["Relay profiles:"]
            for profile in profiles:
                if sub_args and profile.name != sub_args.lower():
                    continue
                marker = "*" if profile.name == self._active_profile_name else " "
                state = "token configured" if profile.token_configured else "token missing"
                endpoint = profile.url.split("?", 1)[0]
                lines.append(
                    f"{marker} {profile.name} — {profile.display_name} · {endpoint} · "
                    f"client {profile.client_id} · session {profile.session_id} · {state}"
                )
            if len(lines) == 1:
                self._append_block(f"[error] unknown relay profile: {sub_args}")
            else:
                self._append_block("\n".join(lines))
            return

        if action in {"select", "use", "switch"}:
            if not sub_args or " " in sub_args:
                self._append_block("usage: /profile [list|select <name>]")
                return
            try:
                target = config.validate_profile_name(sub_args)
                profiles = self._load_profile_catalog()
                profile = next(profile for profile in profiles if profile.name == target)
            except (OSError, UnicodeDecodeError, ValueError, SystemExit, StopIteration) as exc:
                self._append_block(f"[error] /profile select: {exc}")
                return
            if profile.name == self._active_profile_name:
                self._append_block(f"profile already active: {profile.name}")
                return
            if self._profile_switch_is_busy():
                self._append_block(self._profile_switch_busy_message())
                return
            config_path = getattr(self.args, "config", None)
            if config_path is not None:
                try:
                    profile = config.select_relay_profile(config_path, profile.name)
                except (OSError, UnicodeDecodeError, ValueError, SystemExit) as exc:
                    self._append_block(f"[error] /profile select: {exc}")
                    return
            new_args = config.make_profile_args(self.args, profile)
            new_args.profile_names = tuple(item.name for item in profiles)
            new_args.profiles_configured = True
            new_args.profile_legacy = False
            await self._switch_to_args(new_args, reason="profile selection")
            return

        if action in {"create", "edit", "delete", "remove", "migrate"}:
            self._append_block(
                "Use the terminal configuration surface before launch: "
                "hermes-relay profile create|edit|delete|migrate."
            )
            return

        self._append_block("usage: /profile [list|select <name>]")

    async def _handle_session_command(self, args: str) -> None:
        parts = args.strip().split(maxsplit=1)
        subcommand = parts[0].lower() if parts else "list"
        sub_args = parts[1] if len(parts) > 1 else ""
        if subcommand in ("list", "ls"):
            await self._handle_session_list_command(sub_args)
        elif subcommand in ("new", "create"):
            await self._handle_session_new_command(sub_args)
        elif subcommand in ("resume", "switch", "open"):
            await self._handle_session_resume_command(sub_args)
        elif subcommand in ("info", "status"):
            session_id = (
                getattr(self.session, "session_id", None)
                or getattr(self.args, "session_id", "session")
            )
            model = getattr(self.session, "confirmed_model", None) or getattr(self.args, "model", None) or "default"
            model_info = f"{model} (confirmed)" if getattr(self.session, "confirmed_model", None) else f"{model} (unconfirmed)"
            title = getattr(self.session, "confirmed_title", None) or "-"
            chat_id = getattr(self.session, "confirmed_chat_id", None) or "-"
            version = getattr(self.session, "confirmed_server_version", None)
            caps = ", ".join(sorted(getattr(self.session, "capabilities", ()))) or "none"
            limit = getattr(self.session, "confirmed_context_limit", None)
            lines = [
                f"Active session: {session_id}",
                f"  Title: {title}",
                f"  Model: {model_info}",
                f"  Chat ID: {chat_id}",
                f"  Capabilities: {caps}",
            ]
            if limit is not None:
                lines.append(f"  Context Limit: {limit:,} tokens")
            if version:
                lines.append(f"  Relay Version: {version}")
            lines.append(f"  Connection: {self.connection_state}")
            self._append_block("\n".join(lines))
        else:
            self._append_block("usage: /session [list|new|switch|resume|info]")

    async def _handle_session_list_command(self, args: str) -> None:
        if self._turn_in_flight:
            self._append_block("[busy] Cannot list sessions while a turn is active.")
            return
        if not self.session.is_connected():
            self._append_block("[error] Not connected to relay.")
            return
        search = args.strip()
        await self._open_session_picker(initial_search=search)

    async def _handle_session_new_command(self, args: str) -> None:
        if self._turn_in_flight:
            self._append_block("[busy] Cannot start a new session while a turn is active.")
            return
        if not self.session.is_connected():
            self._append_block("[error] Not connected to relay.")
            return
        sid = args.strip() or None
        try:
            res = await self.session.new_session(session_id=sid)
        except Exception as exc:
            self._append_block(f"[error] Failed to start new session: {exc}")
            return
        self.transcript.clear()
        self.domain.reset_session(getattr(self.session, "session_id", None))
        self._refresh_transcript()
        self._refresh_connection_status()
        new_sid = self.session.session_id
        self._append_block(f"Started new session {new_sid}.")

    async def _handle_session_resume_command(self, args: str) -> None:
        if self._turn_in_flight:
            self._append_block("[busy] Cannot resume a session while a turn is active.")
            return
        sid = args.strip()
        if not sid:
            await self._open_session_picker(initial_search="")
            return
        await self._resume_session(sid)

    async def _open_session_picker(self, initial_search: str = "") -> None:
        if self._turn_in_flight:
            self._append_block("[busy] Cannot select a session while a turn is active.")
            return
        if not self.session.is_connected():
            self._append_block("[error] Not connected to relay.")
            return
        try:
            sessions = await self.session.list_sessions(limit=100)
        except Exception as exc:
            self._append_block(f"[error] Failed to list sessions: {exc}")
            return

        active_sid = getattr(self.session, "session_id", None) or ""

        def _on_session_picked(chosen_sid: str | None) -> None:
            if chosen_sid:
                self.run_worker(self._resume_session(chosen_sid))

        self.push_screen(
            SessionPickerModal(
                sessions=sessions,
                current_session_id=active_sid,
                initial_search=initial_search,
            ),
            callback=_on_session_picked,
        )

    async def _resume_session(self, sid: str) -> None:
        if self._turn_in_flight:
            self._append_block("[busy] Cannot resume a session while a turn is active.")
            return
        if not self.session.is_connected():
            self._append_block("[error] Not connected to relay.")
            return
        try:
            res = await self.session.switch_session(sid)
        except Exception as exc:
            self._append_block(f"[error] Failed to resume session {sid}: {exc}")
            return
        self.transcript.clear()
        self.domain.reset_session(getattr(self.session, "session_id", None))
        history = res.get("history") or []
        if history:
            self._hydrate_transcript(history)
        self._refresh_transcript()
        self._refresh_connection_status()
        self._append_block(f"Resumed session {self.session.session_id} ({len(history)} message(s)).")

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
        self._refresh_queue_shelf()

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
        path = Path(raw_path).expanduser() if raw_path else Path.cwd() / (
            f"hermes-transcript-{datetime.now():%Y%m%d-%H%M%S}.txt"
        )
        path = artifact_path_for_profile(
            path,
            self._active_profile_name,
            legacy=not self._profiles_configured,
        ) or path
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

        if self._profile_target_tuple(self.args) != self._profile_target_tuple(new_args):
            if self._profile_switch_is_busy():
                self._append_block(
                    "[busy] Cannot reload to a different relay profile while a turn "
                    "or voice capture is active. The current profile remains active."
                )
                return
            self.run_worker(
                self._reload_profile_after_config(new_args),
                name="profile reload",
                group="interaction",
                exit_on_error=False,
            )
            return

        self._apply_reload_settings(new_args)

    def _apply_reload_settings(self, new_args: Any) -> None:
        """Apply non-session settings after a config parse has succeeded."""
        if self.wake_armed or self._wake_starting:
            self._disarm_wake(
                "wake mode off — config reloaded; microphone released. "
                "Run /wake on to arm again."
            )
        self.args = new_args
        self._sync_profile_metadata(new_args)
        self._refresh_connection_status()
        skipped: list[str] = []

        new_busy_mode = getattr(new_args, "busy_mode", "queue")
        if new_busy_mode not in config.BUSY_MODES:
            new_busy_mode = "queue"
        if self._busy_mode_touched:
            skipped.append("busy-mode")
        else:
            self.busy_mode = new_busy_mode

        new_show_details = False
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

    async def _reload_profile_after_config(self, new_args: Any) -> None:
        """Apply a config-selected profile by replacing its session."""
        connected = await self._switch_to_args(new_args, reason="config reload")
        # `_switch_to_args` installs the new args even when its handshake fails;
        # apply the ordinary reload rules in both cases and report the actual
        # connection state through the normal connection banner.
        self._apply_reload_settings(new_args)
        if not connected:
            self._append_block(
                f"config reloaded from {new_args.config}; profile "
                f"{self._active_profile_name} remains selected but disconnected."
            )

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
        history = self._history
        self.run_worker(
            self._capture_voice_turn(history=history),
            name="voice turn",
            group="interaction",
            exit_on_error=False,
        )

    async def _capture_voice_turn(self, *, history: Optional[PromptHistory] = None) -> None:
        history = self._history if history is None else history
        if self._turn_in_flight:
            self._append_block("[a turn is already in flight]")
            return
        if self.wake_armed:
            coordinator = self._wake_coordinator
            if coordinator is not None and coordinator.state != handsfree.IDLE:
                self._append_block("[a wake turn is already in flight]")
                return
        if not self._connection_is_ready():
            if not await self._connect():
                self._append_block(
                    "[error] voice turn not started; microphone remains closed"
                )
                return
            if not self._connection_is_ready():
                self._append_block(
                    "[error] voice turn not started; microphone remains closed"
                )
                return
        self._voice_capture_cancelled = False
        wake_was_armed = self.wake_armed
        if wake_was_armed:
            self._set_wake_listening(busy=True)
        resume_wake = wake_was_armed
        try:
            # An explicit turn has been accepted, but the microphone is not
            # open yet. Keep that acknowledgement distinct from listening so
            # the TUI's doorway phase agrees with the wake path and any
            # separate Room Display mirror.
            self._set_voice_state(VOICE_HEARD)
            # Give Textual one event-loop turn to paint the acknowledgement
            # before the capture worker can replace it with listening.
            await asyncio.sleep(0)
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
            if not transcript_text or not transcript_text.strip():
                self.domain.apply_event({"type": "capture_empty"})
                self._set_voice_state(VOICE_READY)
                self._append_block("no speech detected.")
                return
            self._set_voice_state(VOICE_TRANSCRIBING)
            await asyncio.to_thread(history.append, transcript_text)
            # Keep the detector paused through transcription and the whole
            # turn. `_run_turn` owns the matching resume after the reply.
            await self._run_turn(transcript_text, stt_source="local-faster-whisper")
            resume_wake = False
        finally:
            if resume_wake and self.wake_armed:
                self._set_wake_listening(busy=False)

    async def action_interrupt(self) -> None:
        if await self._cancel_active_barge_capture():
            return
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
            self._queued_prompts.clear()
            self._refresh_queue_shelf()
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
        await self._close_player(abort=True)
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

        closing_session = self.session
        closing_generation = self._session_generation
        self._expect_session_close(closing_session, closing_generation)
        await self._stop_connection_watcher(
            closing_session,
            closing_generation,
            expected_close=True,
        )
        try:
            await closing_session.close()
        except Exception as exc:
            self._append_block(f"[error] interrupt cleanup: {exc}")
        self._set_connection_state(CONNECTION_DISCONNECTED)
        self._needs_reconnect = True
        return True

    def _shell_policy(self) -> ShellPolicy:
        return ShellPolicy(enabled=bool(getattr(self.args, "allow_shell", False)))

    async def _submit_text(
        self,
        text: str,
        *,
        composer: Optional[Composer] = None,
        history: Optional[PromptHistory] = None,
    ) -> None:
        """Prepare local references, then apply the busy-turn policy."""
        history = self._history if history is None else history
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
        await asyncio.to_thread(history.append, history_text)

        if self._reconnect_in_flight or self._connection_loss_in_flight:
            self._enqueue_prompt(text)
            return

        current_task = asyncio.current_task()
        while self._busy_transition_owner is not None:
            await asyncio.sleep(0)

        decision = decide_busy(
            mode=self.busy_mode,
            turn_in_flight=self._turn_in_flight,
            has_queued_prompts=bool(self._queued_prompts),
        )
        if decision.action == "start_queued":
            self._enqueue_prompt(text)
            next_text = self._queued_prompts.pop(0)
            self._refresh_queue_shelf()
            await self._run_turn(next_text)
            return
        if decision.action == "start":
            await self._run_turn(text)
            return
        if decision.action == "queue":
            self._enqueue_prompt(text)
            return

        # Interrupt and steer both need to reset the stream before another
        # reader can touch the socket. The owner guard closes the tiny window
        # between canceling the old task and starting the replacement.
        self._busy_transition_owner = current_task
        try:
            await self._interrupt_active_turn()
            if decision.action == "steer":
                await self._run_turn(text)
        finally:
            if self._busy_transition_owner is current_task:
                self._busy_transition_owner = None

    async def action_show_help(self, filter_text: str = "") -> None:
        """Open temporary help without polluting the conversation."""
        bindings = (
            "Bindings: Enter send · Shift+Enter/Alt+Enter newline · "
            "Up/Down history · drag transcript to copy · "
            "Ctrl+C copy/interrupt/clear · Ctrl+R voice · Ctrl+Q quit · "
            "F1 help · Esc close\n\n"
        )
        self.push_screen(
            HelpModal(bindings + help_text(filter_text)),
            callback=self._restore_composer_focus,
        )

    def _restore_composer_focus(self, _result: object = None) -> None:
        try:
            self.query_one("#composer", Composer).focus()
        except (NoMatches, ScreenStackError):
            return

    # --- the turn loop --------------------------------------------------------

    async def _run_turn(self, text: str, *, stt_source: str = "local") -> bool:
        if self._reconnect_in_flight or self._connection_loss_in_flight:
            self._last_prompt = text
            self._last_prompt_status = PROMPT_NOT_SENT
            self._enqueue_prompt(text)
            return False
        if self._turn_in_flight:
            # Keep one websocket reader while preserving text submitted during
            # a response. The active turn drains this FIFO after it completes.
            self._last_prompt = text
            self._last_prompt_status = PROMPT_NOT_SENT
            self._enqueue_prompt(text)
            return False
        current_task = asyncio.current_task()
        self._active_turn_task = current_task
        self._turn_in_flight = True
        self._set_barge_listening(active=True)
        self._set_wake_listening(busy=True)
        initial_prompt_status: Optional[str] = None
        if self._busy_transition_owner is current_task:
            self._busy_transition_owner = None
        try:
            next_text: Optional[str] = text
            next_stt_source = stt_source
            while next_text is not None:
                turn_was_sent, turn_status = await self._run_single_turn(
                    next_text, stt_source=next_stt_source
                )
                if initial_prompt_status is None:
                    # `_run_single_turn` snapshots this before its awaited
                    # cleanup. A prompt submitted during that cleanup may
                    # update the shared last-prompt fields, but it must not
                    # change the outcome reported for the initiating wake
                    # turn.
                    initial_prompt_status = turn_status
                if not turn_was_sent:
                    self._queued_prompts.insert(0, next_text)
                    self._refresh_queue_shelf()
                    break
                if turn_status != PROMPT_COMPLETED or not self._queued_prompts:
                    break
                next_text = self._queued_prompts.pop(0)
                self._refresh_queue_shelf()
                next_stt_source = "local"
        finally:
            self._turn_in_flight = False
            if self._active_turn_task is current_task:
                self._active_turn_task = None
            if not self._barge_capture_active:
                self._set_barge_listening(active=False)
            self._set_wake_listening(busy=self._barge_capture_active)
        return initial_prompt_status == PROMPT_COMPLETED

    async def _run_single_turn(
        self, text: str, *, stt_source: str
    ) -> tuple[bool, str]:
        session = self.session
        session_generation = self._session_generation
        self._last_prompt = text
        self._last_prompt_status = PROMPT_NOT_SENT
        turn_status = PROMPT_NOT_SENT
        turn_was_sent = False
        self._last_tts_text = ""
        diagnostic_logger.debug(
            "app.turn.start index=%s stt_source=%s %s",
            getattr(session, "turn_index", "?"),
            stt_source,
            summarize_text(text),
        )
        if not self._connection_is_ready():
            if not await self._connect():
                self._append_block(f"you> {text}")
                self._append_block("[error] not connected; prompt kept in queue")
                return False, turn_status
            session = self.session
            session_generation = self._session_generation

        index = session.turn_index
        self._clear_audio_unavailable()
        self._append_block(text, role="user")
        timeout = getattr(self.args, "turn_timeout", 0) or 0
        try:
            # Admission and send creation are one event-loop-critical section:
            # loss handling cannot begin between the readiness check and the
            # one operation that creates the receive-owned stream.
            async with self._connection_lock:
                if (
                    self._reconnect_in_flight
                    or self._connection_loss_in_flight
                    or not self._connection_is_ready()
                    or not self._session_is_current(session, session_generation)
                ):
                    self._last_prompt_status = PROMPT_NOT_SENT
                    return False, PROMPT_NOT_SENT

                domain_turn = self.domain.begin_turn(
                    generation=index,
                )
                if not domain_turn.accepted:
                    rejection = (
                        "domain rejected turn start: "
                        + (domain_turn.reason or "unknown")
                    )
                    turn_status = PROMPT_NOT_SENT
                    self._last_prompt_status = turn_status
                    self.domain.apply_event(
                        {"type": "error", "error": rejection},
                        generation=index,
                    )
                    self._set_voice_state(VOICE_ERROR)
                    self._append_block(f"[error] {rejection}")
                    return False, turn_status

                # send_turn may have placed the request on the wire before its
                # async stream reports an error, so every post-admission
                # failure is intentionally ambiguous and never auto-replayed.
                self._last_prompt_status = PROMPT_AMBIGUOUS
                turn_status = PROMPT_AMBIGUOUS
                turn_was_sent = True
                self._set_voice_state(VOICE_THINKING)
                events = session.send_turn(text, stt_source=stt_source)
                bound_turn = self.domain.bind_turn_id(
                    getattr(session, "active_turn_id", None)
                )
                if not bound_turn.accepted:
                    raise RuntimeError(
                        "domain rejected turn identity: "
                        + (bound_turn.reason or "unknown")
                    )
            if timeout > 0:
                turn_completed = await asyncio.wait_for(
                    self._consume_turn(
                        events,
                        index,
                        generation=index,
                        session=session,
                        session_generation=session_generation,
                    ),
                    timeout,
                )
            else:
                turn_completed = await self._consume_turn(
                    events,
                    index,
                    generation=index,
                    session=session,
                    session_generation=session_generation,
                )
            if not self._session_is_current(session, session_generation):
                diagnostic_logger.debug(
                    "app.turn.result_stale_session generation=%s",
                    session_generation,
                )
                return turn_was_sent, PROMPT_AMBIGUOUS
            turn_status = (
                PROMPT_COMPLETED if turn_completed else PROMPT_AMBIGUOUS
            )
            self._last_prompt_status = turn_status
            self._preserve_wake_terminal_state = turn_status == PROMPT_AMBIGUOUS
        except SessionNotReadyError:
            if not self._session_is_current(session, session_generation):
                return turn_was_sent, turn_status
            turn_was_sent = False
            turn_status = PROMPT_NOT_SENT
            await self._mark_connection_lost(
                session=session,
                generation=session_generation,
            )
            self._last_prompt_status = turn_status
            self._append_block("[error] not connected; prompt kept in queue")
            return turn_was_sent, turn_status
        except asyncio.CancelledError:
            if not self._session_is_current(session, session_generation):
                raise
            self._preserve_wake_terminal_state = True
            self._set_voice_state(VOICE_INTERRUPTED)
            self._append_block("[interrupted]")
            self._set_connection_state(CONNECTION_DISCONNECTED)
            self._needs_reconnect = True
            raise
        except (asyncio.TimeoutError, TimeoutError):
            if not self._session_is_current(session, session_generation):
                return turn_was_sent, turn_status
            turn_status = PROMPT_AMBIGUOUS
            self._last_prompt_status = turn_status
            self._preserve_wake_terminal_state = True
            self._set_voice_state(VOICE_ERROR)
            await self._mark_connection_lost(
                session=session,
                generation=session_generation,
            )
            self._append_block(
                f"[error] voice turn exceeded {timeout:g}s without completing; "
                "the remote model may be stalled. Start a fresh session and retry."
            )
        except Exception as exc:
            if not self._session_is_current(session, session_generation):
                return turn_was_sent, turn_status
            turn_status = PROMPT_AMBIGUOUS
            self._last_prompt_status = turn_status
            self._preserve_wake_terminal_state = True
            if _is_transport_error(exc):
                await self._mark_connection_lost(
                    session=session,
                    generation=session_generation,
                )
            else:
                # A protocol, rendering, or programming failure is not proof
                # that the socket died. Keep the verified connection state
                # honest and reserve recovery presentation for transport loss.
                self.domain.apply_event(
                    {"type": "error", "error": str(exc)},
                    generation=index,
                )
                self._set_voice_state(VOICE_ERROR)
            self._append_block(f"[error] {exc}")
            if _is_transport_error(exc):
                self._append_block(RETRY_HINT)
        finally:
            # Always tear the stream down; leaving it open leaked a
            # sounddevice stream per failed turn. Interrupted/error turns
            # discard immediately; a completed turn may drain its tail.
            if self._session_is_current(session, session_generation):
                await self._close_player(
                    abort=self.voice_state
                    in {VOICE_INTERRUPTED, VOICE_ERROR, VOICE_DISCONNECTED}
                )
                await self._stop_caption_clock()
                self.transcript.finish_stream()
                if self._pending_prompt is not None and self._prompt_is_current(
                    self._pending_prompt
                ):
                    # Timeout, disconnect, cancellation, or an exception from
                    # a dead socket all end the turn without a prompt_resolved
                    # ever arriving. Whatever the cause, the prompt it
                    # belonged to is gone with it.
                    self._pending_prompt = None
                    self._refresh_prompt_panel()
            else:
                diagnostic_logger.debug(
                    "app.turn.cleanup_stale_session generation=%s",
                    session_generation,
                )
            diagnostic_logger.debug(
                "app.turn.finish index=%s transcript_chars=%d connection=%s",
                index,
                len(self.transcript_text),
                self.connection_state,
            )
        return turn_was_sent, turn_status

    async def _mark_connection_lost(
        self,
        *,
        session: SessionProtocol | None = None,
        generation: int | None = None,
    ) -> None:
        """Close one failed stream so the next turn cannot reuse its socket."""
        session = self.session if session is None else session
        generation = self._session_generation if generation is None else generation
        key = self._session_key(session, generation)
        if key is None or not self._session_is_current(session, generation):
            diagnostic_logger.debug("app.connection_loss.stale_signal")
            return
        if key in self._loss_handled_keys or key in self._loss_in_flight_keys:
            return
        self._loss_in_flight_keys.add(key)
        self._connection_loss_in_flight = True
        try:
            async with self._connection_lock:
                if not self._session_is_current(session, generation):
                    diagnostic_logger.debug("app.connection_loss.stale_after_wait")
                    return
                if key in self._loss_handled_keys:
                    return
                self._loss_handled_keys.add(key)
                watcher = self._connection_watch_task
                if watcher is not asyncio.current_task():
                    await self._stop_connection_watcher(session, generation)
                self._disarm_wake(
                    "wake mode off — connection lost; microphone released. "
                    "Run /wake on after reconnect."
                )
                self._set_connection_state(CONNECTION_DISCONNECTED)
                self._set_voice_state(VOICE_DISCONNECTED)
                self._needs_reconnect = True
                await self._close_player(abort=True)
                if not self._turn_in_flight:
                    self._append_block(RETRY_HINT)
                await self._close_session_with_timeout(
                    session,
                    event="app.turn.session_close",
                    timeout_message=(
                        "[warning] failed session cleanup timed out; continuing recovery."
                    ),
                )
        finally:
            self._loss_in_flight_keys.discard(key)
            self._connection_loss_in_flight = bool(self._loss_in_flight_keys)

    async def _close_player(self, *, abort: bool = False) -> None:
        """Stop playback without blocking Textual's event loop.

        sounddevice's ``stop`` may wait for the device buffer to drain. That
        wait must not prevent transcript refreshes, especially the reasoning
        preview that is meant to remain visible while a reply is spoken.
        """
        if (
            not (abort or self._shutting_down)
            and not getattr(self.player, "active", False)
        ):
            return
        if abort or self._shutting_down:
            close = getattr(self.player, "abort", None)
            if not callable(close):
                close = self.player.close
        else:
            close = self.player.close
        await asyncio.to_thread(close)

    async def _stop_caption_clock(self) -> None:
        task = self._caption_task
        self._caption_task = None
        if task is None or task is asyncio.current_task() or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _abort_player(self) -> None:
        """Stop local response audio immediately from a synchronous callback."""
        abort = getattr(self.player, "abort", None)
        if callable(abort):
            abort()
        else:
            self.player.close()

    async def _consume_turn(
        self,
        events: AsyncIterator[dict[str, Any]],
        index: int,
        *,
        generation: int | None = None,
        session: SessionProtocol | None = None,
        session_generation: int | None = None,
    ) -> bool:
        session = self.session if session is None else session
        session_generation = (
            self._session_generation
            if session_generation is None
            else session_generation
        )
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
        assistant_text = ""
        visible_assistant_text = ""
        speech_timings: dict[str, SpeechTiming] = {}
        audio_started = False
        audio_duration_final = False
        fallback_playback_origin: Optional[float] = None
        audio_segment_index = -1
        audio_chunk_index = 0
        audio_bytes_received = 0
        last_playback_trace_ms = -250
        turn_completed = False
        turn_failed = False
        turn_id_for_audio = str(
            getattr(session, "active_turn_id", None)
            or getattr(self.domain.state, "turn_id", None)
            or ""
        )
        failed_turn_finalized = False

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

        def ensure_assistant_stream() -> None:
            nonlocal assistant_started
            if assistant_started:
                return
            complete_thinking()
            self.transcript.start_stream("assistant")
            assistant_started = True

        def audio_duration() -> Optional[float]:
            if audio_format is None:
                return None
            sample_rate, channels, sample_width = audio_format
            bytes_per_second = sample_rate * channels * sample_width
            if bytes_per_second <= 0:
                return None
            return len(audio) / bytes_per_second

        def playback_position() -> Optional[float]:
            position = getattr(self.player, "playback_position", None)
            if callable(position):
                position = position()
            try:
                position = float(position)
            except (TypeError, ValueError):
                return None
            return position if math.isfinite(position) and position >= 0 else None

        def playback_snapshot() -> dict[str, Any]:
            snapshot = getattr(self.player, "playback_snapshot", None)
            if callable(snapshot):
                try:
                    value = snapshot()
                except Exception:  # pragma: no cover - defensive diagnostics path
                    value = {}
                if isinstance(value, dict):
                    return value
            position = playback_position()
            return {
                "active": bool(getattr(self.player, "active", False)),
                "playing": bool(getattr(self.player, "active", False)),
                "playback_position": position if position is not None else -1.0,
                "scheduled_audio": 0.0,
                "pending_audio": 0.0,
                "queued_audio": 0.0,
            }

        def snapshot_ms(snapshot: dict[str, Any], key: str) -> int:
            try:
                value = float(snapshot.get(key, 0.0))
            except (TypeError, ValueError):
                return -1
            return round(value * 1000) if math.isfinite(value) and value >= 0 else -1

        def log_playback_sample(*, force: bool = False) -> None:
            nonlocal last_playback_trace_ms
            if not audio_started:
                return
            now_ms = trace_monotonic_ms()
            if not force and now_ms - last_playback_trace_ms < 250:
                return
            last_playback_trace_ms = now_ms
            snapshot = playback_snapshot()
            diagnostic_logger.debug(
                "audio.playback mono_ms=%d turn_index=%s segment_index=%d "
                "received_audio_ms=%d playback_position_ms=%d "
                "scheduled_audio_ms=%d pending_audio_ms=%d queued_audio_ms=%d "
                "active=%s playing=%s",
                now_ms,
                index,
                audio_segment_index,
                round((audio_duration() or 0.0) * 1000),
                snapshot_ms(snapshot, "playback_position"),
                snapshot_ms(snapshot, "scheduled_audio"),
                snapshot_ms(snapshot, "pending_audio"),
                snapshot_ms(snapshot, "queued_audio"),
                bool(snapshot.get("active", False)),
                bool(snapshot.get("playing", False)),
            )

        def first_word_prefix(text: str) -> str:
            index = 0
            while index < len(text) and not text[index].isspace():
                index += 1
            while index < len(text) and text[index].isspace():
                index += 1
            return text[:index]

        def render_assistant(*, complete: bool = False) -> None:
            nonlocal fallback_playback_origin, visible_assistant_text
            if not assistant_text:
                return
            ensure_assistant_stream()
            if not assistant_text.startswith(visible_assistant_text):
                visible_assistant_text = ""

            candidate: Optional[str]
            if complete or not audio_started or not self.player.active:
                candidate = assistant_text
            else:
                position = playback_position()
                candidate = None
                if position is not None:
                    if fallback_playback_origin is None:
                        fallback_playback_origin = position
                    timed_candidate = visible_text(
                        assistant_text,
                        speech_timings.values(),
                        position,
                    )
                    if speech_timings:
                        # Match the iOS rail: an aligned record uses its word
                        # spans, while a duration fallback still supplies the
                        # real segment clock. The late record is safe here
                        # because longest_valid_prefix prevents retraction.
                        candidate = timed_candidate
                    elif audio_duration_final:
                        candidate = duration_visible_text(
                            assistant_text,
                            position,
                            audio_duration() or 0,
                        )
                    else:
                        # Before the relay's late duration record arrives,
                        # keep a smooth conservative bridge from the playback
                        # clock rather than waiting for the timing event.
                        candidate = fallback_visible_text(
                            assistant_text,
                            position - fallback_playback_origin,
                        )
                candidate = longest_valid_prefix(
                    assistant_text,
                    [visible_assistant_text, candidate],
                )
                if not candidate:
                    candidate = first_word_prefix(assistant_text)

            safe_candidate = longest_valid_prefix(
                assistant_text,
                [visible_assistant_text, candidate],
            ) or visible_assistant_text
            if safe_candidate == visible_assistant_text:
                return
            visible_assistant_text = safe_candidate
            self.transcript.replace_stream(visible_assistant_text)
            self._refresh_transcript()

        async def caption_clock() -> None:
            while self.player.active and self._session_is_current(
                session, session_generation
            ):
                await asyncio.sleep(0.05)
                if self.player.active and self._session_is_current(
                    session, session_generation
                ):
                    log_playback_sample()
                    render_assistant()

        def start_caption_clock() -> None:
            if self._caption_task is None or self._caption_task.done():
                self._caption_task = asyncio.create_task(caption_clock())

        def finalize_failed_turn() -> None:
            """Commit received text and audio before the failure cleanup runs."""
            nonlocal failed_turn_finalized
            if failed_turn_finalized:
                return
            failed_turn_finalized = True
            if not self._session_is_current(session, session_generation):
                diagnostic_logger.debug(
                    "app.turn.finalize_stale_session generation=%s",
                    session_generation,
                )
                return
            render_assistant(complete=True)
            self._save_turn_audio(
                bytes(audio),
                audio_format,
                index,
                turn_id_for_audio,
                played_live,
                playback_failed,
            )

        async def guarded_events() -> AsyncIterator[dict[str, Any]]:
            """Finalize an accumulated response if the event stream raises."""
            try:
                async for event in events:
                    yield event
            except BaseException:
                finalize_failed_turn()
                raise

        async for event in guarded_events():
            if not self._session_is_current(session, session_generation):
                diagnostic_logger.debug(
                    "app.event.stale_session generation=%s",
                    session_generation,
                )
                await self._close_player(abort=True)
                return False
            event_turn_id = event.get("turn_id")
            if event_turn_id and not turn_id_for_audio:
                turn_id_for_audio = str(event_turn_id)
            kind = event["type"]
            diagnostic_logger.debug(
                "app.event kind=%s %s",
                kind,
                summarize_payload(event),
            )
            domain_event = event
            session_id = getattr(session, "session_id", None)
            if session_id and "session_id" not in event:
                domain_event = dict(event)
                domain_event["session_id"] = str(session_id)
            domain_result = self.domain.apply_event(domain_event, generation=generation)
            if not domain_result.accepted:
                diagnostic_logger.debug(
                    "app.domain.event_rejected kind=%s reason=%s",
                    kind,
                    domain_result.reason or "unknown",
                )
                if domain_result.reason not in {
                    "late_turn_event",
                    "stale_turn_event",
                    "stale_session_event",
                    "stale_prompt",
                }:
                    error_text = (
                        "invalid turn event: "
                        + (domain_result.reason or "rejected")
                    )
                    self.domain.apply_event(
                        {"type": "error", "error": error_text},
                        generation=generation,
                    )
                    turn_failed = True
                    self._set_voice_state(VOICE_ERROR)
                    self._append_block(
                        f"[error] {error_text}",
                        role="error",
                    )
                    finalize_failed_turn()
                    return False
                continue
            if kind in {"connection_lost", "disconnected"}:
                turn_failed = True
                finalize_failed_turn()
                await self._mark_connection_lost(
                    session=session,
                    generation=session_generation,
                )
                return False
            if kind not in {"audio_start", "turn_end"}:
                self._sync_voice_state_from_domain(domain_result.state.phase)
            if kind in {"text_delta", "text_replace"}:
                ensure_assistant_stream()
                if kind == "text_replace":
                    assistant_text = str(event.get("text") or "")
                else:
                    text_delta = str(event.get("text") or "")
                    assistant_text += text_delta
                render_assistant()
                if self.player.active:
                    self._last_tts_text = assistant_text
            elif kind == "prompt_request":
                self._pending_prompt = PendingPrompt.from_event(event)
                self._pending_prompt.session_identity = session
                self._pending_prompt.session_generation = session_generation
                self._refresh_prompt_panel()
            elif kind == "prompt_resolved":
                if (
                    self._pending_prompt is not None
                    and self._pending_prompt.prompt_id == event.get("prompt_id")
                ):
                    self._pending_prompt = None
                    self._refresh_prompt_panel()
            elif kind == "prompt_response_rejected":
                if (
                    self._pending_prompt is not None
                    and self._pending_prompt.prompt_id == event.get("prompt_id")
                ):
                    self._pending_prompt.awaiting_response = False
                    self._pending_prompt.rejection_reason = str(event.get("reason") or "")
                    self._refresh_prompt_panel()
            elif kind == "thinking_delta":
                if not assistant_started:
                    update_thinking(event.get("text"))
            elif kind == "reasoning_available":
                if not assistant_started:
                    update_thinking(event.get("text"))
            elif kind == "status":
                status_text = str(event.get("text") or "").strip()
                if status_text and status_text != last_status:
                    last_status = status_text
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
                thinking_activity_active = False
                set_activity(f"tool: {event.get('name') or 'tool'}…", role="tool")
            elif kind == "tool_progress":
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
                audio_segment_index += 1
                audio_chunk_index = 0
                was_active = bool(self.player.active)
                before = playback_snapshot()
                audio_started = True
                audio_duration_final = False
                self._last_tts_text = assistant_text
                audio_format = (event["sample_rate"], event["channels"], event["sample_width"])
                # Hermes may split one answer into several PCM segments. Keep
                # one output stream, and therefore one continuous playback
                # clock, across those boundaries.
                if not self.player.active:
                    self.player.start(audio_format)
                after = playback_snapshot()
                diagnostic_logger.debug(
                    "audio.segment.start mono_ms=%d turn_index=%s segment_index=%d "
                    "playback_position_ms=%d sample_rate=%d channels=%d sample_width=%d "
                    "active_before=%s active_after=%s",
                    trace_monotonic_ms(),
                    index,
                    audio_segment_index,
                    snapshot_ms(before, "playback_position"),
                    audio_format[0],
                    audio_format[1],
                    audio_format[2],
                    was_active,
                    bool(after.get("active", False)),
                )
                if not was_active:
                    diagnostic_logger.debug(
                        "audio.stream.started mono_ms=%d turn_index=%s "
                        "sample_rate=%d channels=%d sample_width=%d active=%s",
                        trace_monotonic_ms(),
                        index,
                        audio_format[0],
                        audio_format[1],
                        audio_format[2],
                        bool(after.get("active", False)),
                    )
                if self.player.active:
                    start_caption_clock()
                playback_failed = playback_failed or bool(self.player.failure)
                played_live = played_live or self.player.active
                if self._player_is_playing():
                    self._set_voice_state(VOICE_SPEAKING)
                elif self._playback_is_disabled():
                    self._mark_audio_unavailable("playback disabled")
                elif self.player.failure:
                    self._mark_audio_unavailable("playback failed")
                else:
                    self._set_voice_state(VOICE_BUFFERING)
            elif kind == "audio_chunk":
                chunk = event["data"]
                audio_chunk_index += 1
                audio_bytes_received += len(chunk)
                before = playback_snapshot()
                diagnostic_logger.debug(
                    "audio.chunk.received mono_ms=%d turn_index=%s segment_index=%d "
                    "chunk_index=%d bytes=%d received_bytes=%d received_audio_ms=%d "
                    "playback_position_ms=%d queued_audio_ms=%d active=%s",
                    trace_monotonic_ms(),
                    index,
                    audio_segment_index,
                    audio_chunk_index,
                    len(chunk),
                    audio_bytes_received,
                    round((audio_duration() or 0.0) * 1000),
                    snapshot_ms(before, "playback_position"),
                    snapshot_ms(before, "queued_audio"),
                    bool(before.get("active", False)),
                )
                audio.extend(chunk)
                if self.player.active:
                    if not self._session_is_current(session, session_generation):
                        await self._close_player(abort=True)
                        return False
                    await asyncio.to_thread(self.player.write, chunk)
                    if self._session_is_current(session, session_generation):
                        render_assistant()
                    else:
                        await self._close_player(abort=True)
                        return False
                after = playback_snapshot()
                diagnostic_logger.debug(
                    "audio.chunk.scheduled mono_ms=%d turn_index=%s segment_index=%d "
                    "chunk_index=%d bytes=%d received_bytes=%d received_audio_ms=%d "
                    "playback_position_ms=%d scheduled_audio_ms=%d pending_audio_ms=%d "
                    "queued_audio_ms=%d active=%s playing=%s",
                    trace_monotonic_ms(),
                    index,
                    audio_segment_index,
                    audio_chunk_index,
                    len(chunk),
                    audio_bytes_received,
                    round((audio_duration() or 0.0) * 1000),
                    snapshot_ms(after, "playback_position"),
                    snapshot_ms(after, "scheduled_audio"),
                    snapshot_ms(after, "pending_audio"),
                    snapshot_ms(after, "queued_audio"),
                    bool(after.get("active", False)),
                    bool(after.get("playing", False)),
                )
                playback_failed = playback_failed or bool(self.player.failure)
                if self.player.failure:
                    self._mark_audio_unavailable("playback failed")
                elif self._player_is_playing():
                    self._set_voice_state(VOICE_SPEAKING)
                elif not self._playback_is_disabled():
                    self._set_voice_state(VOICE_BUFFERING)
            elif kind == "audio_end":
                # This closes one PCM segment, not necessarily the response.
                # Keep playback and the caption clock alive until turn_end so
                # the next segment does not appear as a sentence-sized jump.
                render_assistant()
                snapshot = playback_snapshot()
                diagnostic_logger.debug(
                    "audio.segment.end mono_ms=%d turn_index=%s segment_index=%d "
                    "received_bytes=%d received_audio_ms=%d playback_position_ms=%d "
                    "queued_audio_ms=%d active=%s",
                    trace_monotonic_ms(),
                    index,
                    audio_segment_index,
                    audio_bytes_received,
                    round((audio_duration() or 0.0) * 1000),
                    snapshot_ms(snapshot, "playback_position"),
                    snapshot_ms(snapshot, "queued_audio"),
                    bool(snapshot.get("active", False)),
                )
            elif kind == "audio_abort":
                # An abort is an intentional end to the remote audio stream,
                # not a failed voice turn. The following turn_interrupted
                # event owns the transcript boundary.
                await self._close_player(abort=True)
                self._set_voice_state(VOICE_INTERRUPTED)
            elif kind == "audio_file_start":
                audio_started = True
                audio_duration_final = False
                self._last_tts_text = assistant_text
                audio_file.clear()
                metadata = tuple(
                    event.get(field)
                    for field in ("sample_rate", "channels", "sample_width")
                )
                if all(value is not None for value in metadata):
                    audio_file_format = (int(metadata[0]), int(metadata[1]), int(metadata[2]))
                else:
                    audio_file_format = None
                if self._playback_is_disabled():
                    self._mark_audio_unavailable("playback disabled")
                else:
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
                            self._mark_audio_unavailable(
                                "audio fallback unavailable"
                            )
                        continue
                    file_audio, file_format = bytes(audio_file), audio_file_format
                audio.extend(file_audio)
                audio_format = file_format
                audio_duration_final = True
                if not self._session_is_current(session, session_generation):
                    await self._close_player(abort=True)
                    return False
                self.player.start(file_format)
                playback_failed = playback_failed or bool(self.player.failure)
                played_live = played_live or self.player.active
                if self.player.active:
                    if not self._session_is_current(session, session_generation):
                        await self._close_player(abort=True)
                        return False
                    await asyncio.to_thread(self.player.write, file_audio)
                    if not self._session_is_current(session, session_generation):
                        await self._close_player(abort=True)
                        return False
                    playback_failed = playback_failed or bool(self.player.failure)
                    if self.player.failure:
                        self._mark_audio_unavailable("playback failed")
                    elif self._player_is_playing():
                        self._set_voice_state(VOICE_SPEAKING)
                    elif not self._playback_is_disabled():
                        self._set_voice_state(VOICE_BUFFERING)
                    await self._close_player()
                elif self._playback_is_disabled():
                    self._mark_audio_unavailable("playback disabled")
                elif self.player.failure:
                    self._mark_audio_unavailable("playback failed")
                else:
                    self._set_voice_state(VOICE_BUFFERING)
                render_assistant(complete=not self.player.active)
            elif kind == "speech_timing":
                try:
                    timing = SpeechTiming.from_event(event)
                except (TypeError, ValueError):
                    timing = None
                if timing is not None and timing.segment_id:
                    speech_timings[timing.segment_id] = timing
                    snapshot = playback_snapshot()
                    diagnostic_logger.debug(
                        "audio.speech_timing mono_ms=%d turn_index=%s segment_id=%s "
                        "offset_ms=%d duration_ms=%d source=%s words=%d fallback=%s "
                        "received_audio_ms=%d playback_position_ms=%d queued_audio_ms=%d",
                        trace_monotonic_ms(),
                        index,
                        summarize_text(timing.segment_id),
                        round(timing.audio_offset * 1000),
                        round(timing.duration * 1000),
                        timing.timing_source,
                        len(timing.words),
                        timing.fallback_reason or "none",
                        round((audio_duration() or 0.0) * 1000),
                        snapshot_ms(snapshot, "playback_position"),
                        snapshot_ms(snapshot, "queued_audio"),
                    )
                    render_assistant()
            elif kind == "error":
                turn_failed = True
                self._set_voice_state(VOICE_ERROR)
                thinking_activity_active = False
                self._append_block(f"[error] {event['error']}", role="error")
                finalize_failed_turn()
                if self._pending_prompt is not None:
                    self._pending_prompt = None
                    self._refresh_prompt_panel()
                return False
            elif kind == "turn_interrupted":
                finalize_failed_turn()
                await self._close_player(abort=True)
                complete_thinking()
                self.transcript.finish_stream()
                self._append_block("[interrupted]")
                self._set_voice_state(VOICE_INTERRUPTED)
                if self._pending_prompt is not None:
                    self._pending_prompt = None
                    self._refresh_prompt_panel()
                return False
            elif kind == "turn_end":
                turn_completed = True
                complete_thinking()
                log_playback_sample(force=True)
                # turn_end can arrive while the final PCM is still queued in
                # the output device. Drain it before committing the complete
                # caption, otherwise the last duration-fallback clause jumps
                # onto the screen at the remote turn boundary.
                await self._close_player()
                if not self._session_is_current(session, session_generation):
                    await self._close_player(abort=True)
                    return False
                playback_failed = playback_failed or bool(self.player.failure)
                if playback_failed and audio_started:
                    self._mark_audio_unavailable("playback failed")
                render_assistant(complete=True)
                self.transcript.finish_stream()
                self._save_turn_audio(
                    bytes(audio),
                    audio_format,
                    index,
                    event.get("turn_id", ""),
                    played_live,
                    playback_failed,
                )
                turn_completed = True
                continuous_wake = (
                    self.wake_armed
                    and self._wake_coordinator is not None
                    and self._wake_coordinator.state != handsfree.IDLE
                )
                if continuous_wake:
                    # The coordinator is about to open the next configured
                    # wake-free capture window. The domain is at COMPLETE now,
                    # so this is a valid transition and avoids painting the
                    # pre-wake `ready` state between conversational turns.
                    self._set_voice_state(VOICE_LISTENING)
                else:
                    self._set_voice_state(VOICE_READY)

        if not turn_completed and not turn_failed:
            if (
                not self._session_is_current(session, session_generation)
                or self.connection_state == CONNECTION_DISCONNECTED
            ):
                await self._close_player(abort=True)
                return False
            error_text = "turn ended without a completion event"
            self.domain.apply_event(
                {"type": "error", "error": error_text},
                generation=generation,
            )
            self._set_voice_state(VOICE_ERROR)
            self._append_block(f"[error] {error_text}", role="error")
            finalize_failed_turn()
            turn_failed = True

        return turn_completed and not turn_failed

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
        if base is not None:
            base = artifact_path_for_profile(
                Path(base),
                self._active_profile_name,
                legacy=not self._profiles_configured,
            )
        elif self._profiles_configured:
            base = artifact_path_for_profile(
                Path.cwd() / "hermes-audio" / "response.wav",
                self._active_profile_name,
            )
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
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        from installer import run_install

        return run_install(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "profile":
        from profile_cli import run_profile_command

        return run_profile_command(sys.argv[2:])
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
