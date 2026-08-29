import asyncio
import types
import wave
from io import BytesIO

import pytest
from textual.widgets import Input, OptionList, Static, TextArea

from app import CommandPalette, Composer, HermesSession, HermesStreamingApp
from client import ProtocolError
from commands import parse_slash_command

DEFAULT_EVENTS = [
    {"type": "text_delta", "text": "ok"},
    {"type": "turn_end", "turn_id": "t0"},
]


class FakeSession:
    """Test double implementing `app.SessionProtocol`.

    `send_turn` is a real async generator, so the tests drive the same
    `async for` path the live websocket client does — the old stub double
    short-circuited that loop entirely and let the streaming-render bug
    through.
    """

    def __init__(self, events=None, hello=None, connected=True, gate=None):
        self.turn_index = 0
        self.sent_turns = []
        self.closed = False
        self.connect_calls = 0
        self.capture_calls = 0
        self.capture_result = "spoken words"
        self.connected = connected
        self.hello = hello if hello is not None else {"chat_id": "chat-1"}
        self.events = DEFAULT_EVENTS if events is None else events
        # When set, the generator waits on this event before its last item,
        # which lets a test hold a turn open and try to start a second one.
        self.gate = gate

    async def connect(self):
        self.connect_calls += 1
        return self.hello

    def is_connected(self):
        return self.connected

    def send_turn(self, text, *, stt_source="local"):
        self.sent_turns.append((text, stt_source))
        self.turn_index += 1
        return self._stream(self.events)

    async def _stream(self, events):
        for position, event in enumerate(events):
            if self.gate is not None and position == len(events) - 1:
                await self.gate.wait()
            await asyncio.sleep(0)
            yield event

    def capture_voice(self):
        self.capture_calls += 1
        return self.capture_result

    async def close(self):
        self.closed = True


class FlakyConnectSession(FakeSession):
    """A session that becomes usable after a controlled number of failures."""

    def __init__(self, failures_before_success, **kwargs):
        super().__init__(connected=False, **kwargs)
        self.failures_remaining = failures_before_success

    async def connect(self):
        self.connect_calls += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise ConnectionError("endpoint unavailable")
        self.connected = True
        return self.hello


def transcript_of(app) -> str:
    """The text the transcript widget is actually rendering."""
    content = app.query_one("#transcript", Static).content
    # The widget must hold the whole accumulated buffer, not just the last write.
    assert content == app.transcript_text
    return str(content)


def make_args(**overrides):
    args = types.SimpleNamespace(
        no_play=True,
        output=None,
        session_id="s1",
        turn_timeout=0,
        busy_mode="queue",
        connect_retries=0,
        connect_retry_delay=0,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


# --- mounting and wiring ----------------------------------------------------


async def test_app_mounts_with_transcript_and_input():
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: FakeSession())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#transcript", Static) is not None
        assert app.query_one("#composer", Composer) is not None


async def test_connect_banner_is_appended_from_the_worker():
    session = FakeSession(hello={"chat_id": "chat-42"})
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert session.connect_calls == 1
        assert "Connected to s1 (chat chat-42)." in transcript_of(app)


async def test_connect_failure_is_reported_not_raised():
    session = FakeSession()

    async def boom():
        raise RuntimeError("no token")

    session.connect = boom
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "[error] no token" in transcript_of(app)


async def test_connect_retries_then_reports_connected():
    session = FlakyConnectSession(2)
    app = HermesStreamingApp(
        args=make_args(connect_retries=2, connect_retry_delay=0),
        session_factory=lambda: session,
    )
    async with app.run_test() as pilot:
        await pilot.pause()

        assert session.connect_calls == 3
        assert app.connection_state == "connected"
        assert "connection attempt 1/3 failed" in transcript_of(app)
        assert "Connected to s1" in transcript_of(app)


async def test_connect_exhaustion_keeps_app_open_and_reports_bound():
    session = FlakyConnectSession(99)
    app = HermesStreamingApp(
        args=make_args(connect_retries=2, connect_retry_delay=0),
        session_factory=lambda: session,
    )
    async with app.run_test() as pilot:
        await pilot.pause()

        assert session.connect_calls == 3
        assert app.connection_state == "disconnected"
        assert "unable to connect after 3 attempt(s)" in transcript_of(app)


async def test_prompt_is_kept_in_queue_when_recovery_is_exhausted():
    session = FlakyConnectSession(99)
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._run_turn("keep this prompt")

        assert session.sent_turns == []
        assert app._queued_prompts == ["keep this prompt"]
        assert "prompt kept in queue" in transcript_of(app)


async def test_new_prompt_waits_behind_a_retained_prompt():
    session = FlakyConnectSession(99)
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._run_turn("first prompt")

        session.failures_remaining = 0
        await app._submit_text("second prompt")

        assert session.sent_turns == [
            ("first prompt", "local"),
            ("second prompt", "local"),
        ]
        assert app._queued_prompts == []


async def test_dropped_turn_is_not_replayed_but_next_prompt_recovers():
    class DropOnceSession(FakeSession):
        async def connect(self):
            self.connect_calls += 1
            self.connected = True
            return self.hello

        def send_turn(self, text, *, stt_source="local"):
            self.sent_turns.append((text, stt_source))
            self.turn_index += 1

            async def stream():
                if text == "first":
                    yield {"type": "text_delta", "text": "partial"}
                    self.connected = False
                    raise ConnectionResetError("socket went away")
                yield {"type": "text_delta", "text": "second answer"}
                yield {"type": "turn_end", "turn_id": "second"}

            return stream()

    session = DropOnceSession()
    app = HermesStreamingApp(
        args=make_args(connect_retries=1, connect_retry_delay=0),
        session_factory=lambda: session,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._run_turn("first")

        assert session.sent_turns == [("first", "local")]
        assert app.connection_state == "disconnected"
        assert "partial" in transcript_of(app)

        await app._submit_text("second")

        assert session.sent_turns == [("first", "local"), ("second", "local")]
        assert transcript_of(app).count("you> first") == 1
        assert "hermes: second answer" in transcript_of(app)
        assert app.connection_state == "connected"


async def test_submitting_input_sends_a_turn_and_clears_input():
    session = FakeSession()
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        composer = app.query_one("#composer", Composer)
        composer.text = "hello hermes\nsecond paragraph"
        composer.move_cursor((1, len("second paragraph")))
        await pilot.press("enter")
        await pilot.pause()
        assert session.sent_turns == [("hello hermes\nsecond paragraph", "local")]
        assert composer.text == ""
        assert "you> hello hermes\nsecond paragraph" in transcript_of(app)


async def test_modified_enter_inserts_newlines_without_submitting():
    session = FakeSession()
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        composer = app.query_one("#composer", Composer)
        composer.text = "first line"
        composer.move_cursor((0, len("first line")))

        await pilot.press("shift+enter")
        await pilot.press("alt+enter")
        await pilot.pause()

        assert composer.text == "first line\n\n"
        assert session.sent_turns == []


async def test_slash_help_is_handled_without_sending_a_turn():
    session = FakeSession()
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        composer = app.query_one("#composer", Composer)
        composer.text = "/help"
        await pilot.press("enter")
        await pilot.pause()

        assert session.sent_turns == []
        assert "/voice" in transcript_of(app)
        assert "/help" in transcript_of(app)


async def test_unknown_slash_command_uses_dispatcher_instead_of_model_turn():
    session = FakeSession()
    dispatched = []

    async def dispatch(invocation):
        dispatched.append((invocation.name, invocation.args))
        return "gateway handled it"

    app = HermesStreamingApp(
        args=make_args(),
        session_factory=lambda: session,
        command_dispatcher=dispatch,
    )
    async with app.run_test() as pilot:
        composer = app.query_one("#composer", Composer)
        composer.text = "/plugin-command --flag"
        await pilot.press("enter")
        await pilot.pause()

        assert dispatched == [("plugin-command", "--flag")]
        assert session.sent_turns == []
        assert "gateway handled it" in transcript_of(app)


async def test_tab_completes_a_unique_slash_command_and_keeps_draft_local():
    session = FakeSession()
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        composer = app.query_one("#composer", Composer)
        composer.text = "/sta"
        composer.move_cursor((0, len(composer.text)))
        await pilot.press("tab")
        await pilot.pause()

        assert composer.text == "/status "
        assert session.sent_turns == []


async def test_slash_opens_command_palette_and_enter_hands_command_to_composer():
    session = FakeSession()
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        composer = app.query_one("#composer", Composer)
        await pilot.press("/")
        await pilot.pause()

        assert isinstance(app.screen, CommandPalette)
        command_filter = app.screen.query_one("#command-filter", Input)
        assert app.focused is command_filter

        await pilot.press("b", "u")
        await pilot.pause()

        options = app.screen.query_one("#command-options", OptionList)
        assert options.option_count == 1
        assert "/busy" in str(options.get_option_at_index(0).prompt)

        await pilot.press("down")
        await pilot.pause()
        assert app.focused is options
        assert options.highlighted == 0

        await pilot.press("enter")
        await pilot.pause()

        assert composer.text == "/busy "
        assert app.focused is composer
        assert session.sent_turns == []


async def test_escape_closes_command_palette_and_preserves_slash_draft():
    session = FakeSession()
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        composer = app.query_one("#composer", Composer)
        await pilot.press("/")
        await pilot.pause()
        assert isinstance(app.screen, CommandPalette)

        await pilot.press("escape")
        await pilot.pause()

        assert not isinstance(app.screen, CommandPalette)
        assert composer.text == "/"
        assert app.focused is composer


# --- the bug this suite previously could not see ----------------------------


async def test_text_deltas_render_inline_as_one_flowing_line():
    # Regression guard for the review's top finding: the transcript used to be
    # a RichLog, and every write() started a new line, so a streamed sentence
    # arrived as one token per line. Each delta must now extend the same line.
    session = FakeSession(
        events=[
            {"type": "text_delta", "text": "Hello"},
            {"type": "text_delta", "text": " there,"},
            {"type": "text_delta", "text": " Amanda."},
            {"type": "turn_end", "turn_id": "t1"},
        ]
    )
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._run_turn("hi")

        transcript = transcript_of(app)
        assert "hermes: Hello there, Amanda." in transcript
        # And the deltas occupy exactly one line — no token-per-line splitting.
        reply_line = [line for line in transcript.splitlines() if line.startswith("hermes: ")]
        assert reply_line == ["hermes: Hello there, Amanda."]


async def test_status_and_error_events_render_on_their_own_lines():
    session = FakeSession(
        events=[
            {"type": "text_delta", "text": "working"},
            {"type": "status", "text": "thinking"},
            {"type": "error", "error": "model hiccup"},
            {"type": "turn_end", "turn_id": "t2"},
        ]
    )
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._run_turn("hi")

        lines = transcript_of(app).splitlines()
        assert "hermes: working" in lines
        assert "[thinking]" in lines
        assert "[error] model hiccup" in lines


async def test_repeated_activity_updates_replace_one_line_before_final_text():
    session = FakeSession(
        events=[
            {"type": "status", "text": "thinking"},
            {"type": "status", "text": "thinking"},
            {"type": "status", "text": "thinking"},
            {"type": "text_delta", "text": "polished answer"},
            {"type": "turn_end", "turn_id": "activity-1"},
        ]
    )
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._run_turn("hi")

        lines = transcript_of(app).splitlines()
        assert lines.count("[thinking]") == 1
        assert "hermes: polished answer" in lines


async def test_tool_progress_replaces_activity_line_instead_of_spamming_transcript():
    session = FakeSession(
        events=[
            {"type": "tool_start", "tool_id": "tool-1", "name": "search"},
            {"type": "tool_progress", "tool_id": "tool-1", "name": "search", "preview": "reading"},
            {"type": "tool_progress", "tool_id": "tool-1", "name": "search", "preview": "parsing"},
            {"type": "tool_complete", "tool_id": "tool-1", "name": "search"},
            {"type": "text_delta", "text": "done"},
            {"type": "turn_end", "turn_id": "tool-1"},
        ]
    )
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._run_turn("search")

        lines = transcript_of(app).splitlines()
        assert [line for line in lines if line.startswith("[tool:")] == ["[tool: search ✓]"]
        assert "hermes: done" in lines


async def test_activity_updates_do_not_replace_an_intervening_notification():
    session = FakeSession(
        events=[
            {"type": "status", "text": "thinking"},
            {"type": "notification", "text": "heads up"},
            {"type": "tool_start", "name": "search"},
            {"type": "text_delta", "text": "done"},
            {"type": "turn_end", "turn_id": "activity-2"},
        ]
    )
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._run_turn("hi")

        lines = transcript_of(app).splitlines()
        assert "notification: heads up" in lines
        assert "[tool: search…]" in lines
        assert "hermes: done" in lines


async def test_unknown_server_events_are_visible_in_the_transcript():
    session = FakeSession(
        events=[
            {"type": "unknown_event", "event_type": "approval.request", "payload": {}},
            {"type": "text_delta", "text": "answer"},
            {"type": "turn_end", "turn_id": "unknown-1"},
        ]
    )
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._run_turn("hi")

        assert "[unhandled server event: approval.request]" in transcript_of(app)
        assert "hermes: answer" in transcript_of(app)


async def test_voice_turn_streams_with_the_voice_stt_source():
    session = FakeSession()
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.action_voice_turn()

        assert session.capture_calls == 1
        assert session.sent_turns == [("spoken words", "local-faster-whisper")]
        assert "you> spoken words" in transcript_of(app)


async def test_voice_turn_with_no_speech_sends_nothing():
    session = FakeSession()
    session.capture_result = ""
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.action_voice_turn()

        assert session.sent_turns == []
        assert "no speech detected." in transcript_of(app)


async def test_voice_capture_failure_is_reported_without_crashing():
    session = FakeSession()

    def fail_capture():
        raise RuntimeError("voice dependencies are not installed")

    session.capture_voice = fail_capture
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.action_voice_turn()

        assert "[error] microphone: voice dependencies are not installed" in transcript_of(app)
        assert session.sent_turns == []


# --- guards -----------------------------------------------------------------


async def test_second_turn_is_queued_while_one_is_in_flight():
    # Two concurrent turns would both call ws.recv() and raise
    # websockets.ConcurrencyError; the second is queued instead.
    gate = asyncio.Event()
    session = FakeSession(gate=gate)
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        first = asyncio.create_task(app._run_turn("one"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert app._turn_in_flight

        await app._run_turn("two")
        assert session.sent_turns == [("one", "local")]
        assert app._queued_prompts == ["two"]
        assert "queued[1]: 'two'" in transcript_of(app)

        gate.set()
        await first
        assert not app._turn_in_flight
        assert app._queued_prompts == []
        assert session.sent_turns == [("one", "local"), ("two", "local")]


async def test_composer_remains_submitable_while_a_turn_is_responding():
    gate = asyncio.Event()
    session = FakeSession(gate=gate)
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        composer = app.query_one("#composer", Composer)
        composer.text = "first"
        first_press = asyncio.create_task(pilot.press("enter"))
        await asyncio.sleep(0.05)
        assert app._turn_in_flight

        composer.text = "second"
        second_press = asyncio.create_task(pilot.press("enter"))
        await asyncio.sleep(0.05)

        assert composer.text == ""
        assert app._queued_prompts == ["second"]
        assert session.sent_turns == [("first", "local")]

        gate.set()
        await asyncio.wait_for(first_press, 1)
        await asyncio.wait_for(second_press, 1)
        await pilot.pause()
        assert session.sent_turns == [("first", "local"), ("second", "local")]


async def test_steer_busy_mode_applies_to_an_ordinary_message():
    started = asyncio.Event()
    release = asyncio.Event()

    class ReconnectableSession(FakeSession):
        async def connect(self):
            self.connect_calls += 1
            self.connected = True
            return self.hello

        async def close(self):
            self.closed = True
            self.connected = False

        def send_turn(self, text, *, stt_source="local"):
            self.sent_turns.append((text, stt_source))
            self.turn_index += 1

            async def stream():
                if text == "first":
                    started.set()
                    await release.wait()
                yield {"type": "text_delta", "text": text}
                yield {"type": "turn_end", "turn_id": text}

            return stream()

    session = ReconnectableSession()
    app = HermesStreamingApp(args=make_args(busy_mode="steer"), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        first = asyncio.create_task(app._run_turn("first"))
        await asyncio.wait_for(started.wait(), 1)

        await app._submit_text("corrected")

        assert first.done()
        assert session.sent_turns == [("first", "local"), ("corrected", "local")]
        assert session.connect_calls == 2
        assert "hermes: corrected" in transcript_of(app)


async def test_interrupt_busy_mode_stops_an_active_turn_without_sending_message():
    gate = asyncio.Event()
    session = FakeSession(gate=gate)
    app = HermesStreamingApp(args=make_args(busy_mode="interrupt"), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        first = asyncio.create_task(app._run_turn("first"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert app._turn_in_flight

        await app._submit_text("do not send")

        assert first.done()
        assert session.sent_turns == [("first", "local")]
        assert app._queued_prompts == []
        assert not app._turn_in_flight


async def test_steer_slash_command_explains_busy_mode_migration():
    session = FakeSession()
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        composer = app.query_one("#composer", Composer)
        composer.text = "/steer corrected"
        await pilot.press("enter")
        await pilot.pause()

        assert session.sent_turns == []
        assert "set --busy-mode steer" in transcript_of(app)


async def test_status_reports_the_selected_busy_mode():
    session = FakeSession()
    app = HermesStreamingApp(args=make_args(busy_mode="interrupt"), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        invocation = parse_slash_command("/status")
        assert invocation is not None
        await app._handle_command(invocation)

        assert "busy-mode: interrupt" in transcript_of(app)


async def test_busy_command_changes_mode_for_the_current_session():
    session = FakeSession()
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        composer = app.query_one("#composer", Composer)
        composer.text = "/busy steer"
        await pilot.press("enter")
        await pilot.pause()

        assert app.busy_mode == "steer"
        assert "busy-mode set to steer" in transcript_of(app)

        composer.text = "/busy"
        await pilot.press("enter")
        await pilot.pause()
        assert "busy-mode: steer" in transcript_of(app)


async def test_busy_command_rejects_unknown_modes():
    session = FakeSession()
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        composer = app.query_one("#composer", Composer)
        composer.text = "/busy chaos"
        await pilot.press("enter")
        await pilot.pause()

        assert app.busy_mode == "queue"
        assert "usage: /busy [queue|steer|interrupt]" in transcript_of(app)


async def test_ctrl_c_interrupts_active_turn_and_preserves_partial_transcript():
    gate = asyncio.Event()
    session = FakeSession(
        events=[
            {"type": "text_delta", "text": "partial answer"},
            {"type": "turn_end", "turn_id": "stalled"},
        ],
        gate=gate,
    )
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        first = asyncio.create_task(app._run_turn("runaway"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert app._turn_in_flight
        assert "partial answer" in transcript_of(app)

        await app.action_interrupt()

        assert first.done()
        assert not app._turn_in_flight
        assert session.closed
        assert "partial answer" in transcript_of(app)
        assert "[interrupted]" in transcript_of(app)


async def test_ctrl_c_clears_an_idle_draft_before_any_exit():
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: FakeSession())
    async with app.run_test() as pilot:
        await pilot.pause()
        composer = app.query_one("#composer", Composer)
        composer.text = "unfinished thought"

        await app.action_interrupt()

        assert composer.text == ""
        assert "draft cleared." in transcript_of(app)


async def test_composer_ctrl_c_reaches_the_app_interrupt_action():
    gate = asyncio.Event()
    session = FakeSession(gate=gate)
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        composer = app.query_one("#composer", Composer)
        composer.text = "first"
        first_press = asyncio.create_task(pilot.press("enter"))
        await asyncio.sleep(0.05)
        assert app._turn_in_flight

        await pilot.press("ctrl+c")
        await pilot.pause()
        await asyncio.sleep(0.05)

        assert not app._turn_in_flight
        assert "[interrupted]" in transcript_of(app)
        await asyncio.wait_for(first_press, 1)


async def test_queue_command_lists_edits_and_drops_prompts():
    session = FakeSession()
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        app._queued_prompts = ["first", "second"]
        composer = app.query_one("#composer", Composer)

        composer.text = "/queue"
        await pilot.press("enter")
        assert "1. 'first'" in transcript_of(app)
        assert "2. 'second'" in transcript_of(app)

        composer.text = "/queue edit 2 revised second"
        await pilot.press("enter")
        assert app._queued_prompts == ["first", "revised second"]

        composer.text = "/queue drop 1"
        await pilot.press("enter")
        assert app._queued_prompts == ["revised second"]
        assert "dropped: 'first'" in transcript_of(app)
        assert session.sent_turns == []


async def test_voice_turn_is_refused_while_a_turn_is_in_flight():
    session = FakeSession()
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._turn_in_flight = True

        await app.action_voice_turn()

        assert session.capture_calls == 0
        assert session.sent_turns == []
        assert "[a turn is already in flight]" in transcript_of(app)


async def test_turn_is_refused_when_the_session_is_not_connected():
    session = FakeSession(connected=False)
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._run_turn("hi")

        assert session.sent_turns == []
        assert "[error] not connected" in transcript_of(app)
        assert not app._turn_in_flight


async def test_a_failing_stream_reports_the_error_and_clears_the_flag():
    session = FakeSession()

    def exploding_send_turn(text, *, stt_source="local"):
        session.sent_turns.append((text, stt_source))

        async def stream():
            raise ConnectionResetError("socket went away")
            yield  # pragma: no cover - makes this an async generator

        return stream()

    session.send_turn = exploding_send_turn
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._run_turn("hi")

        assert "[error] socket went away" in transcript_of(app)
        assert not app._turn_in_flight


async def test_a_stalled_turn_hits_the_configured_timeout():
    session = FakeSession()

    def stalling_send_turn(text, *, stt_source="local"):
        async def stream():
            await asyncio.sleep(30)
            yield {"type": "turn_end", "turn_id": "never"}

        return stream()

    session.send_turn = stalling_send_turn
    app = HermesStreamingApp(args=make_args(turn_timeout=0.05), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._run_turn("hi")

        assert "exceeded 0.05s without completing" in transcript_of(app)
        assert not app._turn_in_flight


# --- audio output -----------------------------------------------------------


async def test_turn_audio_is_written_to_a_wav_when_playback_is_off(tmp_path):
    output = tmp_path / "reply.wav"
    session = FakeSession(
        events=[
            {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
            {"type": "audio_chunk", "data": b"\x00\x01\x02\x03"},
            {"type": "turn_end", "turn_id": "t3"},
        ]
    )
    app = HermesStreamingApp(
        args=make_args(output=output), session_factory=lambda: session
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._run_turn("hi")

        assert output.exists()
        with wave.open(str(output), "rb") as handle:
            assert handle.getnchannels() == 1
            assert handle.getsampwidth() == 2
            assert handle.getframerate() == 24000
        assert f"audio: {output}" in transcript_of(app)


async def test_audio_end_closes_playback_before_turn_end():
    class RecordingPlayer:
        active = False
        failure = None

        def __init__(self):
            self.close_states = []

        def start(self, audio_format):
            self.active = True

        def write(self, chunk):
            pass

        def close(self):
            self.close_states.append(self.active)
            self.active = False

    session = FakeSession(
        events=[
            {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
            {"type": "audio_chunk", "data": b"\x00\x01"},
            {"type": "audio_end"},
            {"type": "turn_end", "turn_id": "audio-end"},
        ]
    )
    app = HermesStreamingApp(args=make_args(no_play=False), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        player = RecordingPlayer()
        app.player = player
        await app._run_turn("hi")

        assert player.close_states == [True, False]


async def test_audio_status_gets_its_own_line_before_assistant_response():
    class ActivePlayer:
        active = False
        failure = None

        def start(self, audio_format):
            self.active = True

        def close(self):
            self.active = False

    session = FakeSession(
        events=[
            {"type": "thinking_delta", "text": "thinking"},
            {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
            {"type": "text_delta", "text": "Good. One of me is plenty."},
            {"type": "turn_end", "turn_id": "audio-status"},
        ]
    )
    app = HermesStreamingApp(args=make_args(no_play=False), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.player = ActivePlayer()
        await app._run_turn("hi")

        transcript = transcript_of(app)
        assert "[audio streaming]\nhermes: Good. One of me is plenty." in transcript
        assert "[audio streaming]hermes:" not in transcript


async def test_audio_file_fallback_is_recovered_as_wav(tmp_path):
    source = BytesIO()
    with wave.open(source, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x01\x02\x03")

    output = tmp_path / "fallback.wav"
    session = FakeSession(
        events=[
            {"type": "audio_file_start", "mime_type": "audio/wav"},
            {"type": "audio_file_chunk", "data": source.getvalue()},
            {"type": "audio_file_end"},
            {"type": "turn_end", "turn_id": "file-fallback"},
        ]
    )
    app = HermesStreamingApp(
        args=make_args(output=output), session_factory=lambda: session
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._run_turn("hi")

        with wave.open(str(output), "rb") as handle:
            assert handle.getframerate() == 16000
            assert handle.readframes(2) == b"\x00\x01\x02\x03"


async def test_help_binding_prints_the_bindings_line():
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: FakeSession())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.action_show_help()
        assert "ctrl+r = voice turn" in transcript_of(app)
        assert "ctrl+c = interrupt" in transcript_of(app)
        assert "busy-mode = queue" in transcript_of(app)


# --- session lifecycle ------------------------------------------------------


class FakeConnectContextManager:
    """Stands in for the object `connect(...)` returns before entering it."""

    def __init__(self):
        self.aexit_called_with = None

    async def __aenter__(self):
        return "fake-ws"

    async def __aexit__(self, exc_type, exc, tb):
        self.aexit_called_with = (exc_type, exc, tb)


async def test_session_connect_closes_a_half_open_context_after_handshake_failure(monkeypatch):
    class BadHelloWebSocket:
        async def send(self, data):
            pass

        async def recv(self):
            return '{"type": "unexpected"}'

    class BadHelloContextManager(FakeConnectContextManager):
        async def __aenter__(self):
            return BadHelloWebSocket()

    fake_cm = BadHelloContextManager()

    def fake_connect(url, **kwargs):
        return fake_cm

    monkeypatch.setattr("config.connect_factory", lambda: fake_connect)
    monkeypatch.setattr("config._resolve_token", lambda explicit, env_path: "token")
    session = HermesSession(
        args=make_args(
            token=None,
            profile_env=None,
            url="ws://test",
            client_id="client",
            device_id="device",
            display_name="test",
        )
    )

    with pytest.raises(ProtocolError, match="voice-session hello failed"):
        await session.connect()

    assert fake_cm.aexit_called_with == (None, None, None)
    assert session._connect_cm is None
    assert session.ws is None


async def test_session_close_exits_the_connect_context_manager():
    session = HermesSession(args=None)
    fake_cm = FakeConnectContextManager()
    session._connect_cm = fake_cm
    session.ws = "fake-ws"
    assert session.is_connected()

    await session.close()

    assert fake_cm.aexit_called_with == (None, None, None)
    assert session._connect_cm is None
    assert not session.is_connected()


async def test_app_unmount_closes_the_websocket_session():
    # Reproduces the reviewer's finding: ctrl+q (mapped to Textual's built-in
    # `quit` action) tore the app down without closing the websocket, because
    # HermesSession.connect() never kept the context manager needed to close
    # it. on_unmount now calls session.close() for whatever session is set.
    # We mount with a FakeSession (so on_mount doesn't attempt a real network
    # connection), then swap in a HermesSession wired to a fake connect
    # context manager and drive on_unmount directly, since Pilot doesn't
    # expose a bare unmount hook independent of app.run_test()'s teardown.
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: FakeSession())
    async with app.run_test() as pilot:
        await pilot.pause()
        real_session = HermesSession(args=None)
        fake_cm = FakeConnectContextManager()
        real_session._connect_cm = fake_cm
        app.session = real_session

        await app.on_unmount()

        assert fake_cm.aexit_called_with == (None, None, None)
        assert real_session._connect_cm is None


async def test_app_unmount_closes_a_protocol_session():
    session = FakeSession()
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: session)
    async with app.run_test() as pilot:
        await pilot.pause()
    assert session.closed


async def test_voice_binding_is_registered():
    # NOTE: app._bindings is Textual's internal BindingsMap. In the
    # installed version (8.2.8) iterating it yields (key, Binding) tuples,
    # not bare Binding objects, so the brief's `binding.key for binding in
    # app._bindings` would raise AttributeError on the tuple. We unpack the
    # tuple and read Binding.action to prove ctrl+r is actually wired to
    # the voice-turn action (not just present as a key).
    app = HermesStreamingApp(args=make_args(), session_factory=lambda: FakeSession())
    async with app.run_test():
        bindings_by_key = {key: binding for key, binding in app._bindings}
        assert "ctrl+r" in bindings_by_key
        assert bindings_by_key["ctrl+r"].action == "voice_turn"
        assert "ctrl+c" in bindings_by_key
        assert bindings_by_key["ctrl+c"].action == "interrupt"
