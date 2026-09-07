"""Interactive session picker modal for the Textual TUI.

Provides a search-filterable, keyboard-navigable list of Hermes sessions
for switching and resuming conversations.
"""

from __future__ import annotations

from typing import Any, Optional

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option


class SessionPickerModal(ModalScreen[Optional[str]]):
    """Interactive modal dialog for selecting and resuming past Hermes sessions."""

    DEFAULT_CSS = """
    SessionPickerModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.65);
    }

    #session-picker-dialog {
        width: 86;
        max-width: 92%;
        height: 24;
        max-height: 85%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }

    #session-picker-title {
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }

    #session-picker-filter {
        margin-bottom: 1;
        border: tall $panel-lighten-1;
        background: $panel;
    }

    #session-picker-list {
        height: 1fr;
        border: none;
        background: $surface;
        padding: 0;
    }

    #session-picker-footer {
        height: auto;
        margin-top: 1;
        align: right middle;
    }

    #session-picker-help {
        width: 1fr;
        color: $text-muted;
    }

    #session-picker-cancel {
        min-width: 10;
        height: 1;
        border: none;
        background: $panel-lighten-1;
        color: $text;
    }

    #session-picker-cancel:hover {
        background: $error-darken-1;
        color: $text;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        sessions: list[dict[str, Any]],
        *,
        current_session_id: str = "",
        initial_search: str = "",
    ) -> None:
        super().__init__()
        self.sessions = sessions
        self.current_session_id = current_session_id
        self.initial_search = initial_search
        self.filtered_sessions: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="session-picker-dialog"):
            yield Label("Resume Session", id="session-picker-title")
            yield Input(
                placeholder="Filter sessions by title, ID, model, preview...",
                id="session-picker-filter",
                value=self.initial_search,
            )
            yield OptionList(id="session-picker-list")
            with Horizontal(id="session-picker-footer"):
                yield Static(
                    "[↑/↓/j/k] Navigate  [Enter] Resume  [Esc] Cancel",
                    id="session-picker-help",
                )
                yield Button("Cancel", id="session-picker-cancel")

    def on_mount(self) -> None:
        self.apply_filter(self.initial_search)
        self.query_one("#session-picker-filter", Input).focus()

    def on_key(self, event: events.Key) -> None:
        option_list = self.query_one("#session-picker-list", OptionList)
        filter_input = self.query_one("#session-picker-filter", Input)

        if filter_input.has_focus:
            if event.key == "down":
                option_list.action_cursor_down()
                event.stop()
                event.prevent_default()
            elif event.key == "up":
                option_list.action_cursor_up()
                event.stop()
                event.prevent_default()
            elif event.key == "pageup":
                option_list.action_page_up()
                event.stop()
                event.prevent_default()
            elif event.key == "pagedown":
                option_list.action_page_down()
                event.stop()
                event.prevent_default()
        elif option_list.has_focus:
            if event.key == "j":
                option_list.action_cursor_down()
                event.stop()
                event.prevent_default()
            elif event.key == "k":
                option_list.action_cursor_up()
                event.stop()
                event.prevent_default()

    def apply_filter(self, query: str) -> None:
        terms = [t for t in query.strip().lower().split() if t]
        self.filtered_sessions = []
        option_list = self.query_one("#session-picker-list", OptionList)
        option_list.clear_options()

        for s in self.sessions:
            sid = str(s.get("session_id") or s.get("id") or "")
            title = str(s.get("title") or "").strip()
            preview = str(
                s.get("preview") or s.get("last_message") or s.get("snippet") or ""
            ).strip()
            model = str(s.get("model") or "").strip()
            msg_count = s.get("message_count") or s.get("messages") or s.get("turn_count") or 0
            last_active = str(
                s.get("last_active") or s.get("updated_at") or s.get("timestamp") or ""
            ).strip()

            searchable = f"{sid} {title} {preview} {model} {last_active}".lower()
            if terms and not all(t in searchable for t in terms):
                continue

            self.filtered_sessions.append(s)

            is_active = bool(sid and sid == self.current_session_id)
            prefix = "▶ " if is_active else "  "
            title_str = title if title else sid
            time_str = f" · {last_active}" if last_active else ""
            count_str = f"({msg_count} msgs)" if msg_count else ""
            model_str = f" · {model}" if model and model != title else ""

            text = Text()
            if is_active:
                text.append(prefix, style="bold green")
                text.append(title_str, style="bold white")
            else:
                text.append(prefix, style="dim")
                text.append(title_str, style="bold")

            if title and sid != title:
                text.append(f"  [{sid}]", style="cyan")
            elif not title:
                text.append(f"  [{sid}]", style="cyan")

            if count_str:
                text.append(f"  {count_str}", style="dim")
            if time_str:
                text.append(f"{time_str}", style="dim italic")
            if model_str:
                text.append(f"{model_str}", style="dim")

            if preview:
                preview_clean = " ".join(preview.split())
                if len(preview_clean) > 75:
                    preview_clean = preview_clean[:72] + "…"
                text.append(f"\n    {preview_clean}", style="bright_black")

            option_list.add_option(Option(prompt=text, id=sid))

        if self.filtered_sessions:
            option_list.highlighted = 0
        else:
            option_list.add_option(
                Option(
                    prompt=Text("No matching sessions found", style="dim italic"),
                    disabled=True,
                )
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "session-picker-filter":
            self.apply_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "session-picker-filter":
            self._submit_highlighted()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id and not event.option.disabled:
            self.dismiss(str(event.option_id))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "session-picker-cancel":
            self.dismiss(None)

    def _submit_highlighted(self) -> None:
        option_list = self.query_one("#session-picker-list", OptionList)
        if (
            option_list.highlighted is not None
            and 0 <= option_list.highlighted < len(self.filtered_sessions)
        ):
            s = self.filtered_sessions[option_list.highlighted]
            sid = str(s.get("session_id") or s.get("id") or "")
            self.dismiss(sid)

    def action_cancel(self) -> None:
        self.dismiss(None)
