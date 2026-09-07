"""Unit tests for the SessionPickerModal component."""

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList

from session_picker import SessionPickerModal


class DummyApp(App):
    def compose(self) -> ComposeResult:
        return []


async def test_session_picker_renders_sessions():
    sessions = [
        {
            "session_id": "s-alpha",
            "title": "Alpha Research",
            "preview": "Discussing quantum physics",
            "model": "qwen2.5:7b",
            "message_count": 8,
            "last_active": "2m ago",
        },
        {
            "session_id": "s-beta",
            "title": "Beta Fix",
            "preview": "Fixing the audio buffer issue",
            "model": "qwen2.5:7b",
            "message_count": 3,
            "last_active": "1h ago",
        },
    ]
    modal = SessionPickerModal(sessions, current_session_id="s-alpha")
    app = DummyApp()
    async with app.run_test() as pilot:
        app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#session-picker-list", OptionList)
        assert option_list.option_count == 2
        assert modal.filtered_sessions == sessions


async def test_session_picker_navigation_and_selection():
    sessions = [
        {"session_id": "s-1", "title": "First Session"},
        {"session_id": "s-2", "title": "Second Session"},
        {"session_id": "s-3", "title": "Third Session"},
    ]
    modal = SessionPickerModal(sessions)
    app = DummyApp()
    chosen = []
    async with app.run_test() as pilot:
        app.push_screen(modal, callback=lambda res: chosen.append(res))
        await pilot.pause()

        # Input is focused by default; pressing down moves selection in option list
        await pilot.press("down")
        await pilot.pause()
        opt_list = modal.query_one("#session-picker-list", OptionList)
        assert opt_list.highlighted == 1

        # Pressing Enter submits highlighted option
        await pilot.press("enter")
        await pilot.pause()

        assert chosen == ["s-2"]
        assert len(app.screen_stack) == 1


async def test_session_picker_filtering():
    sessions = [
        {"session_id": "s-auth", "title": "OAuth Flow Implementation", "preview": "Token exchange"},
        {"session_id": "s-audio", "title": "PCM Streaming", "preview": "Audio buffers"},
        {"session_id": "s-chat", "title": "General Chat", "preview": "Hello world"},
    ]
    modal = SessionPickerModal(sessions)
    app = DummyApp()
    chosen = []
    async with app.run_test() as pilot:
        app.push_screen(modal, callback=lambda res: chosen.append(res))
        await pilot.pause()

        # Type filter query
        await pilot.press("a", "u", "d")
        await pilot.pause()

        opt_list = modal.query_one("#session-picker-list", OptionList)
        assert len(modal.filtered_sessions) == 1
        assert modal.filtered_sessions[0]["session_id"] == "s-audio"

        await pilot.press("enter")
        await pilot.pause()
        assert chosen == ["s-audio"]


async def test_session_picker_empty_matches_state():
    sessions = [
        {"session_id": "s-auth", "title": "OAuth Flow"},
    ]
    modal = SessionPickerModal(sessions)
    app = DummyApp()
    async with app.run_test() as pilot:
        app.push_screen(modal)
        await pilot.pause()

        await pilot.press("z", "z", "z")
        await pilot.pause()

        assert len(modal.filtered_sessions) == 0
        opt_list = modal.query_one("#session-picker-list", OptionList)
        assert opt_list.option_count == 1
        assert opt_list.get_option_at_index(0).disabled


async def test_session_picker_escape_cancels():
    sessions = [{"session_id": "s-1", "title": "First"}]
    modal = SessionPickerModal(sessions)
    app = DummyApp()
    chosen = []
    async with app.run_test() as pilot:
        app.push_screen(modal, callback=lambda res: chosen.append(res))
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert chosen == [None]
        assert len(app.screen_stack) == 1


async def test_session_picker_cancel_button():
    sessions = [{"session_id": "s-1", "title": "First"}]
    modal = SessionPickerModal(sessions)
    app = DummyApp()
    chosen = []
    async with app.run_test() as pilot:
        app.push_screen(modal, callback=lambda res: chosen.append(res))
        await pilot.pause()

        cancel_btn = modal.query_one("#session-picker-cancel")
        cancel_btn.press()
        await pilot.pause()

        assert chosen == [None]
        assert len(app.screen_stack) == 1


async def test_session_picker_jk_keys_on_option_list():
    sessions = [
        {"session_id": "s-1", "title": "First"},
        {"session_id": "s-2", "title": "Second"},
        {"session_id": "s-3", "title": "Third"},
    ]
    modal = SessionPickerModal(sessions)
    app = DummyApp()
    async with app.run_test() as pilot:
        app.push_screen(modal)
        await pilot.pause()

        opt_list = modal.query_one("#session-picker-list", OptionList)
        opt_list.focus()
        await pilot.pause()

        assert opt_list.highlighted == 0
        await pilot.press("j")
        await pilot.pause()
        assert opt_list.highlighted == 1

        await pilot.press("j")
        await pilot.pause()
        assert opt_list.highlighted == 2

        await pilot.press("k")
        await pilot.pause()
        assert opt_list.highlighted == 1
