"""Standalone Textual app that prints every key event it receives.

Run this interactively to see exactly what `event.key` and `event.character`
your terminal sends for a given keypress. Use it to check whether Shift+Enter
produces a distinguishable key (e.g. "shift+enter") or arrives indistinguishable
from plain Enter — this depends on whether the terminal speaks the Kitty
keyboard protocol (CSI-u), not on anything in this app's Composer code.

Usage:
    python scripts/key_event_diagnostic.py

Press keys to see them logged live. Press Ctrl+C or Escape to quit.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import RichLog


class KeyEventDiagnostic(App):
    BINDINGS = [("escape", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield RichLog(highlight=True, markup=False)

    def on_mount(self) -> None:
        log = self.query_one(RichLog)
        log.write("Press keys to inspect them. Try Enter, Shift+Enter, Alt+Enter.")
        log.write("Press Escape to quit.\n")

    async def on_key(self, event) -> None:
        log = self.query_one(RichLog)
        log.write(
            f"key={event.key!r}  character={event.character!r}  "
            f"name={event.name!r}  is_printable={event.is_printable}"
        )
        if event.key == "ctrl+c":
            self.exit()


if __name__ == "__main__":
    KeyEventDiagnostic().run()
