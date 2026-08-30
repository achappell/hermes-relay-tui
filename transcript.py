"""Typed transcript state and Rich rendering for live Hermes conversations."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.text import Text


@dataclass
class TranscriptMessage:
    """One displayable transcript message with an explicit semantic role."""

    role: str
    text: str
    detail: bool = False


class TranscriptBuffer:
    """Keep typed messages while exposing a plain-text compatibility view.

    The compatibility view keeps existing diagnostics and tests readable, but
    rendering is driven by the records so streamed assistant text can be
    re-rendered as one Markdown message instead of one widget write per delta.
    """

    _LABELS = {"user": "you> ", "assistant": "hermes: "}
    _STYLES = {
        "user": "bold cyan",
        "assistant": "bold green",
        "thinking": "dim yellow",
        "tool": "dim cyan",
        "status": "dim",
        "notification": "magenta",
        "error": "bold red",
        "background": "blue",
        "system": "white",
    }

    def __init__(self) -> None:
        self.messages: list[TranscriptMessage] = []
        self._active_activity: TranscriptMessage | None = None
        self._streaming_message: TranscriptMessage | None = None

    def clear(self) -> None:
        self.messages.clear()
        self._active_activity = None
        self._streaming_message = None

    def add(self, role: str, text: str, *, detail: bool = False) -> TranscriptMessage:
        """Append a complete message and finalize replaceable activity."""
        self._active_activity = None
        message = TranscriptMessage(role=role, text=text, detail=detail)
        self.messages.append(message)
        return message

    def set_activity(self, text: str, *, role: str = "status") -> None:
        """Add or replace the current thinking/tool/status activity message."""
        if not text:
            return
        if self._active_activity is None:
            self._active_activity = TranscriptMessage(role=role, text=text, detail=True)
            self.messages.append(self._active_activity)
        else:
            self._active_activity.role = role
            self._active_activity.text = text

    def start_stream(self, role: str = "assistant") -> TranscriptMessage:
        """Start one streamed message, preserving any completed activity."""
        self._active_activity = None
        self._streaming_message = TranscriptMessage(role=role, text="")
        self.messages.append(self._streaming_message)
        return self._streaming_message

    def append_stream(self, text: str) -> None:
        """Append a delta to the current stream without creating a record."""
        if not text:
            return
        if self._streaming_message is None:
            self.start_stream()
        assert self._streaming_message is not None
        self._streaming_message.text += text

    def replace_stream(self, text: str) -> None:
        """Replace the active streamed message when a preview is revised."""
        if self._streaming_message is None:
            self.start_stream()
        assert self._streaming_message is not None
        self._streaming_message.text = text

    def finish_stream(self) -> None:
        self._streaming_message = None
        self._active_activity = None

    @property
    def plain_text(self) -> str:
        """Return the readable text projection used by diagnostics and tests."""
        if not self.messages:
            return ""
        blocks = [self._plain_message(message) for message in self.messages]
        return "\n".join(blocks)

    def _plain_message(self, message: TranscriptMessage) -> str:
        return f"{self._LABELS.get(message.role, '')}{message.text}"

    def render(self, *, show_details: bool = True) -> Group:
        """Build a Rich renderable for the current transcript snapshot."""
        renderables: list[RenderableType] = []
        for message in self.messages:
            if message.detail and not show_details:
                continue
            if not message.text:
                continue
            label = self._LABELS.get(message.role)
            if label:
                renderables.append(Text(label.rstrip(), style=self._STYLES[message.role]))
                if message.role == "user":
                    # Raw typed input: preserve literal newlines. Markdown
                    # treats a single "\n" as a soft break (renders as a
                    # space), which silently ate Shift+Enter line breaks.
                    renderables.append(Text(message.text))
                else:
                    renderables.append(Markdown(message.text))
            else:
                renderables.append(
                    Text(message.text, style=self._STYLES.get(message.role, "white"))
                )
        return Group(*renderables)
