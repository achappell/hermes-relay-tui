"""Temporary keyboard help overlay for the Textual TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static


class HelpModal(ModalScreen[None]):
    """Show help without adding reference material to the conversation."""

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.65);
    }

    #help-dialog {
        width: 92;
        max-width: 94%;
        height: auto;
        max-height: 88%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }

    #help-title {
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }

    #help-scroll {
        height: auto;
        max-height: 1fr;
        padding: 0;
    }

    #help-content {
        height: auto;
        color: $text;
    }

    #help-footer {
        height: 1;
        margin-top: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, content: str) -> None:
        super().__init__()
        self.content = content

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("Keyboard help", id="help-title")
            with VerticalScroll(id="help-scroll"):
                yield Static(self.content, id="help-content", markup=False)
            yield Static("Esc close", id="help-footer", markup=False)

    def action_close(self) -> None:
        self.dismiss(None)
