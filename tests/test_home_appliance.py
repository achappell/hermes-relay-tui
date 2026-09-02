"""The appliance loop, driven entirely by fakes.

No microphone, no speaker, no websocket, no wake-word engine: every seam the
real unit uses is injectable, so the whole wake-to-spoken-answer path can be
exercised in a test. What is being checked is that the display never claims a
state the hardware is not in.
"""

from __future__ import annotations

import asyncio
import threading
import types

import pytest

import config
import handsfree
from home_display.appliance import Appliance


class FakeSession:
    """A session whose turns are scripted event lists."""

    def __init__(self, script=None, *, connect_errors: int = 0) -> None:
        self.script = script if script is not None else [{"type": "turn_end"}]
        self.turns: list[str] = []
        self.connects = 0
        self.closes = 0
        self.cancels = 0
        self.shared_recorder = None
        self.connect_errors = connect_errors
        self.transcript = "what is the weather"
        self.turn_index = 0

    async def connect(self):
        self.connects += 1
        if self.connect_errors > 0:
            self.connect_errors -= 1
            raise ConnectionError("relay is down")
        return {"type": "hello_ack"}

    def is_connected(self) -> bool:
        return True

    def send_turn(self, text: str, *, stt_source: str = "local"):
        self.turns.append(text)
        script = self.script

        async def _events():
            for event in script:
                if isinstance(event, Exception):
                    raise event
                yield event

        return _events()

    def capture_voice(self) -> str:
        return self.transcript

    def cancel_voice(self) -> None:
        self.cancels += 1

    def use_shared_recorder(self, recorder) -> None:
        self.shared_recorder = recorder

    async def close(self) -> None:
        self.closes += 1


class FakePlayer:
    def __init__(self, *, can_play: bool = True) -> None:
        self.can_play = can_play
        self.stream = None
        self.failure = None
        self.playing = False
        self.written = bytearray()
        self.formats: list[tuple[int, int, int]] = []

    @property
    def active(self) -> bool:
        return self.stream is not None

    def start(self, audio_format) -> None:
        self.formats.append(audio_format)
        if self.can_play:
            self.stream = object()
        else:
            self.failure = "no output device"

    def write(self, chunk: bytes) -> None:
        self.written.extend(chunk)
        self.playing = True

    def close(self) -> None:
        self.stream = None
        self.playing = False


class FakeRecorder:
    """Stands in for the shared, always-open input stream."""

    def __init__(self) -> None:
        self.observer = None
        self.opened = False
        self.shutdowns = 0
        self.has_detected_speech = False

    def set_frame_observer(self, observer) -> None:
        self.observer = observer

    def open_for_listening(self) -> None:
        self.opened = True

    def shutdown(self) -> None:
        self.shutdowns += 1


class FakeListener:
    """Records lifecycle calls; wake events are fired by the test."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.paused: list[bool] = []

    def start(self) -> None:
        self.started = True

    def pause(self) -> None:
        self.paused.append(True)

    def resume(self) -> None:
        self.paused.append(False)

    def stop(self) -> None:
        self.stopped = True

    def submit(self, frame) -> None:  # pragma: no cover - never called by fakes
        pass


class FakeEarcons:
    """Records which tones were asked for, in order, and when."""

    def __init__(self, *, enabled: bool = True, log=None) -> None:
        self.enabled = enabled
        self.played: list[str] = []
        self.failure = None
        self._log = log

    def play(self, name: str) -> None:
        if not self.enabled:
            return
        self.played.append(name)
        if self._log is not None:
            self._log.append(f"earcon:{name}")


class FakeServer:
    def __init__(self) -> None:
        self.info = types.SimpleNamespace(http_url="http://127.0.0.1:9/")
        self.closed = False

    async def start(self):
        return self.info

    async def close(self) -> None:
        self.closed = True


def _args(**overrides):
    values = {
        "wake_enabled": True,
        "no_play": False,
        "audio_output_device": None,
        "mic_input_device": None,
        "wake_listen_timeout": 8.0,
        "wake_barge_in": False,
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


def _build(appliance_state: dict):
    """A `build_hands_free` that returns the fake listener and a real coordinator."""

    def build(
        session,
        args,
        *,
        on_state_change=None,
        send=None,
        speech_detected=None,
        stop_playback=None,
        acknowledge=None,
        capture_finished=None,
    ):
        listener = FakeListener()
        coordinator = handsfree.HandsFreeCoordinator(
            session,
            capture=session.capture_voice,
            send=send,
            speech_detected=speech_detected,
            acknowledge=acknowledge,
            capture_finished=capture_finished,
            listen_timeout=getattr(args, "wake_listen_timeout", 8.0),
            barge_in=getattr(args, "wake_barge_in", False),
            stop_playback=stop_playback,
            on_state_change=on_state_change,
            now=appliance_state.get("clock", None) or (lambda: 0.0),
        )
        appliance_state["listener"] = listener
        appliance_state["coordinator"] = coordinator
        return listener, coordinator

    return build


def make_appliance(
    script=None, *, player=None, session=None, args=None, state=None, earcons=None, **kwargs
):
    state = state if state is not None else {}
    session = session if session is not None else FakeSession(script)
    earcons = earcons if earcons is not None else FakeEarcons()
    state["earcons"] = earcons
    appliance = Appliance(
        args or _args(),
        session=session,
        earcons=earcons,
        player=player or FakePlayer(),
        recorder=FakeRecorder(),
        server=FakeServer(),
        build_hands_free=_build(state),
        tick_interval=0.01,
        **kwargs,
    )
    state["appliance"] = appliance
    state["session"] = session
    return appliance, state


async def _wait_for(predicate, *, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.005)
    return False


async def _run_until_idle(appliance, state, *, wake_after_connect=True, until=None):
    """Start the loop, fire one wake from a worker thread, then stop."""
    task = asyncio.create_task(appliance.run())
    ready = until or (
        lambda: state.get("coordinator") is not None and state["session"].connects
    )
    assert await _wait_for(ready), "the appliance never reached its starting state"
    if wake_after_connect:
        done = threading.Event()

        def fire():
            try:
                state["coordinator"].on_wake()
            finally:
                done.set()

        threading.Thread(target=fire, daemon=True).start()
        assert await _wait_for(done.is_set), "the wake turn never finished"
    appliance._stopping.set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return task


class RecordingPublisher:
    """The real publisher's interface, with a history the test can assert on."""

    def __init__(self) -> None:
        self.history: list[tuple[str, str, str | None]] = []

    def publish(self, *, state, response_text="", status_text=None, media=None):
        self.history.append((state, response_text, status_text))

    @property
    def sequence(self) -> list[str]:
        return [entry[0] for entry in self.history]


@pytest.mark.asyncio
async def test_wake_to_spoken_answer_walks_the_display_through_the_real_states():
    publisher = RecordingPublisher()
    script = [
        {"type": "text_delta", "text": "Sunny "},
        {"type": "text_delta", "text": "and warm."},
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "audio_end"},
        {"type": "turn_end"},
    ]
    player = FakePlayer()
    appliance, state = make_appliance(script, player=player, publisher=publisher)

    await _run_until_idle(appliance, state)

    assert state["session"].turns == ["what is the weather"]
    assert player.written == bytearray(b"\x01\x02")
    ordered = [entry for entry in publisher.sequence]
    assert ordered[0] == "disconnected"
    assert "listening" in ordered
    assert ordered.index("listening") < ordered.index("thinking")
    assert ordered.index("thinking") < ordered.index("speaking")
    assert ordered[-1] == "idle"
    spoken = [entry for entry in publisher.history if entry[0] == "speaking"]
    assert spoken[-1][1] == "Sunny and warm."


@pytest.mark.asyncio
async def test_the_appliance_starts_the_listener_before_opening_the_stream():
    """Reversed, the whole warm-up is dropped audio - 96 frames on a first run."""
    order: list[str] = []

    class OrderedRecorder(FakeRecorder):
        def open_for_listening(self) -> None:
            order.append("stream")
            super().open_for_listening()

    class OrderedListener(FakeListener):
        def start(self) -> None:
            order.append("listener")
            super().start()

    state: dict = {}

    def build(session, args, **kwargs):
        listener = OrderedListener()
        state["listener"] = listener
        state["coordinator"] = handsfree.HandsFreeCoordinator(
            session, capture=session.capture_voice, send=kwargs.get("send")
        )
        return listener, state["coordinator"]

    session = FakeSession()
    appliance = Appliance(
        _args(),
        session=session,
        player=FakePlayer(),
        recorder=OrderedRecorder(),
        server=FakeServer(),
        build_hands_free=build,
        tick_interval=0.01,
    )
    state["session"] = session

    await _run_until_idle(appliance, state, wake_after_connect=False)

    assert order == ["listener", "stream"]


@pytest.mark.asyncio
async def test_a_silent_misfire_says_nothing_and_returns_to_idle():
    publisher = RecordingPublisher()
    session = FakeSession()
    session.transcript = ""
    appliance, state = make_appliance(session=session, publisher=publisher)

    await _run_until_idle(appliance, state)

    assert session.turns == []
    assert publisher.sequence[-1] == "idle"
    assert "speaking" not in publisher.sequence


@pytest.mark.asyncio
async def test_playback_that_cannot_open_reports_buffering_not_speaking():
    publisher = RecordingPublisher()
    script = [
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_chunk", "data": b"\x01"},
        {"type": "audio_end"},
        {"type": "turn_end"},
    ]
    appliance, state = make_appliance(
        script, player=FakePlayer(can_play=False), publisher=publisher
    )

    await _run_until_idle(appliance, state)

    assert "buffering" in publisher.sequence
    assert "speaking" not in publisher.sequence


@pytest.mark.asyncio
async def test_a_relay_error_is_shown_rather_than_spoken():
    publisher = RecordingPublisher()
    script = [{"type": "error", "error": "model unavailable"}, {"type": "turn_end"}]
    appliance, state = make_appliance(script, publisher=publisher)

    await _run_until_idle(appliance, state)

    errors = [entry for entry in publisher.history if entry[0] == "error"]
    assert errors and errors[-1][2] == "model unavailable"


@pytest.mark.asyncio
async def test_a_connection_that_drops_mid_turn_shows_disconnected_and_reconnects():
    publisher = RecordingPublisher()
    session = FakeSession([ConnectionError("socket closed")])
    appliance, state = make_appliance(session=session, publisher=publisher)

    await _run_until_idle(appliance, state)
    assert await _wait_for(lambda: session.connects >= 2)

    assert publisher.sequence.count("disconnected") >= 2
    assert session.connects >= 2
    assert session.closes >= 1


@pytest.mark.asyncio
async def test_a_failed_connection_retries_and_the_display_never_claims_idle():
    publisher = RecordingPublisher()
    session = FakeSession(connect_errors=2)
    appliance, state = make_appliance(
        session=session, publisher=publisher, reconnect_delay=0.01
    )

    await _run_until_idle(
        appliance, state, wake_after_connect=False, until=lambda: session.connects >= 3
    )

    assert session.connects >= 3
    assert publisher.sequence[0] == "disconnected"
    assert publisher.sequence.count("idle") <= 1


@pytest.mark.asyncio
async def test_the_listener_only_runs_while_a_session_is_connected():
    session = FakeSession(connect_errors=1)
    appliance, state = make_appliance(session=session, reconnect_delay=0.01)

    await _run_until_idle(
        appliance,
        state,
        wake_after_connect=False,
        until=lambda: state.get("listener") is not None
        and False in state["listener"].paused,
    )

    listener = state["listener"]
    # Paused at startup, and resumed only once a connection exists.
    assert listener.paused[0] is True
    assert False in listener.paused


@pytest.mark.asyncio
async def test_the_session_captures_through_the_listeners_own_recorder():
    """Two input streams on one device is unreliable; there is only one."""
    appliance, state = make_appliance()

    await _run_until_idle(appliance, state, wake_after_connect=False)

    session = state["session"]
    assert session.shared_recorder is appliance._recorder
    assert session.shared_recorder.observer is not None


@pytest.mark.asyncio
async def test_a_wake_nobody_follows_with_speech_cancels_the_capture():
    clock = {"now": 0.0}
    state = {"clock": lambda: clock["now"]}
    session = FakeSession()
    appliance, state = make_appliance(session=session, state=state, args=_args(wake_listen_timeout=1.0))

    task = asyncio.create_task(appliance.run())
    assert await _wait_for(
        lambda: state.get("coordinator") is not None and session.connects
    )
    coordinator = state["coordinator"]
    coordinator._begin_capture_for_test()
    clock["now"] = 5.0
    assert await _wait_for(lambda: session.cancels >= 1)

    assert session.cancels >= 1
    assert coordinator.state == handsfree.IDLE

    appliance._stopping.set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_an_undecodable_file_fallback_after_speech_is_not_an_error():
    """Hermes sends a file fallback *as well as* the PCM it already streamed.
    Failing to decode the spare copy must not turn a turn that was spoken
    aloud into a red screen."""
    publisher = RecordingPublisher()
    script = [
        {"type": "text_delta", "text": "Potato."},
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "audio_end"},
        {"type": "audio_file_start"},
        {"type": "audio_file_chunk", "data": b"not a wav file at all"},
        {"type": "audio_file_end"},
        {"type": "turn_end"},
    ]
    appliance, state = make_appliance(script, publisher=publisher)

    await _run_until_idle(appliance, state)

    assert "error" not in publisher.sequence
    assert "speaking" in publisher.sequence
    assert publisher.sequence[-1] == "idle"


@pytest.mark.asyncio
async def test_an_undecodable_fallback_with_no_speech_at_all_reports_buffering():
    """Nothing was spoken and nothing can be. The answer is on screen but the
    room heard silence — that is what `buffering` means, not `error`."""
    publisher = RecordingPublisher()
    script = [
        {"type": "text_delta", "text": "Potato."},
        {"type": "audio_file_start"},
        {"type": "audio_file_chunk", "data": b"not a wav file at all"},
        {"type": "audio_file_end"},
        {"type": "turn_end"},
    ]
    appliance, state = make_appliance(script, publisher=publisher)

    await _run_until_idle(appliance, state)

    assert "error" not in publisher.sequence
    assert "buffering" in publisher.sequence


# --- the reasoning preamble -------------------------------------------------
#
# Hermes packs the model's chain-of-thought and the answer into one text frame:
# a "💭 **Reasoning:**" marker, a fenced block, then the reply. The transcript
# in the TUI can afford to show that. A kitchen display cannot: the speaker
# says one sentence while the wall shows four hundred words of deliberation.


def test_plain_text_is_left_exactly_as_it_arrived():
    from home_display.appliance import display_text

    assert display_text("Sunny and warm.") == "Sunny and warm."
    assert display_text("") == ""


def test_a_reasoning_preamble_is_stripped_down_to_the_answer():
    from home_display.appliance import display_text

    raw = (
        "\U0001f4ad **Reasoning:**\n```\nThe user wants a short sentence.\n"
        "I should keep it brief.\n```\n\nOnline. What's the situation?"
    )

    assert display_text(raw) == "Online. What's the situation?"


def test_an_unfinished_reasoning_block_shows_nothing_yet():
    """Mid-stream the fence has not closed. Showing the half-written thought
    is worse than showing nothing: the answer is seconds away."""
    from home_display.appliance import display_text

    raw = "\U0001f4ad **Reasoning:**\n```\nThe user wants a short sen"

    assert display_text(raw) == ""


def test_a_code_fence_in_the_answer_itself_survives():
    from home_display.appliance import display_text

    raw = "Run this:\n```\nbrew upgrade\n```\nThen restart."

    assert display_text(raw) == raw


@pytest.mark.asyncio
async def test_the_display_shows_the_answer_not_the_deliberation():
    publisher = RecordingPublisher()
    script = [
        {
            "type": "text_delta",
            "text": "\U0001f4ad **Reasoning:**\n```\nDeliberating at length.\n```\n\nOnline.",
        },
        {"type": "turn_end"},
    ]
    appliance, state = make_appliance(script, publisher=publisher)

    await _run_until_idle(appliance, state)

    shown = [entry[1] for entry in publisher.history if entry[1]]
    assert shown and all("Reasoning" not in text for text in shown)
    assert shown[-1] == "Online."


@pytest.mark.asyncio
async def test_text_arriving_after_the_answer_was_spoken_does_not_say_thinking():
    """This gateway sends the audio before the text. The reply landing after
    playback has finished must not push the display back to `thinking` — the
    unit is not thinking, it has already answered."""
    publisher = RecordingPublisher()
    script = [
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "audio_end"},
        {"type": "text_delta", "text": "Online."},
        {"type": "turn_end"},
    ]
    appliance, state = make_appliance(script, publisher=publisher)

    await _run_until_idle(appliance, state)

    order = publisher.sequence
    after_speaking = order[order.index("speaking") + 1 :]
    assert "thinking" not in after_speaking, order
    assert publisher.history[-1][1] == "Online."


# --- endpointing ------------------------------------------------------------
#
# The TUI waits 3s of silence before deciding you have finished, which is fine
# when you pressed a key on purpose and can see the screen. Standing in a
# kitchen it is an age: three seconds of nothing happening reads as broken.


def test_the_appliance_ends_an_utterance_sooner_than_the_terminal_client():
    from home_display import appliance

    hands_free = appliance.build_arg_parser().parse_args([])
    terminal = config.build_arg_parser().parse_args([])

    assert hands_free.mic_silence_duration == appliance.HANDS_FREE_SILENCE_DURATION
    assert hands_free.mic_silence_duration < terminal.mic_silence_duration


def test_an_explicit_silence_duration_still_wins(tmp_path, monkeypatch):
    """A hands-free default must not overrule someone who set the value."""
    from home_display import appliance

    configured = tmp_path / "config.yaml"
    configured.write_text("mic_silence_duration: 2.5\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_RELAY_TUI_CONFIG", str(configured))

    from_file = appliance.build_arg_parser().parse_args([])
    from_flag = appliance.build_arg_parser().parse_args(["--mic-silence-duration", "4"])

    assert from_file.mic_silence_duration == 2.5
    assert from_flag.mic_silence_duration == 4.0


@pytest.mark.asyncio
async def test_speaking_waits_for_audio_that_can_actually_be_heard():
    """`audio_start` is a header, not a sound. Against a live gateway the
    first audible sample arrived 2.2s after it. Showing "Speaking" over a
    silent room for two seconds is the exact lie this display must not tell."""
    publisher = RecordingPublisher()
    script = [
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "text_delta", "text": "Working on it."},
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "audio_end"},
        {"type": "turn_end"},
    ]
    appliance, state = make_appliance(script, publisher=publisher)

    await _run_until_idle(appliance, state)

    order = publisher.sequence
    # The text frame lands between the header and the first sample: at that
    # moment the unit is still thinking, not speaking.
    assert order.index("thinking") < order.index("speaking")
    thinking_entries = [e for e in publisher.history if e[0] == "thinking"]
    assert thinking_entries[-1][1] == "Working on it."


@pytest.mark.asyncio
async def test_a_dropped_turn_does_not_leave_half_an_answer_on_screen():
    """A completed answer stays up to be read. A partial one, from a turn the
    connection killed, is not an answer and must not sit there looking like
    one under a "Reconnecting" banner."""
    publisher = RecordingPublisher()
    session = FakeSession(
        [{"type": "text_delta", "text": "The oven is at four hundred and"},
         ConnectionError("socket closed")]
    )
    appliance, state = make_appliance(session=session, publisher=publisher)

    await _run_until_idle(appliance, state)

    dropped = [entry for entry in publisher.history if entry[0] == "disconnected"]
    assert dropped and dropped[-1][1] == ""


@pytest.mark.asyncio
async def test_the_listener_is_deaf_while_a_turn_holds_the_microphone():
    """Otherwise the unit wakes itself. Observed live: a misfire expired after
    8s, the detector still had the tail of the phrase in its rolling buffer,
    and it fired again the instant the microphone came free — two Listening
    windows from one spoken phrase. `pause()` resets that buffer."""
    state: dict = {}
    appliance, state = make_appliance(state=state)

    await _run_until_idle(appliance, state)

    # True is a pause, False a resume. Startup pause, resume once connected,
    # pause for the duration of the turn, resume when idle again — and a final
    # pause as the appliance shuts down.
    assert state["listener"].paused[:4] == [True, False, True, False]


@pytest.mark.asyncio
async def test_speech_is_announced_when_the_cushion_flushes_not_when_it_fills():
    """The player holds a cushion before its first sample. Announcing speech
    on the first write would put "Speaking" on screen while the buffer is
    still filling and the room is silent."""
    publisher = RecordingPublisher()

    class SlowToStart(FakePlayer):
        def write(self, chunk: bytes) -> None:
            self.written.extend(chunk)
            self.playing = len(self.written) >= 4  # cushion of 4 bytes

    script = [
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "text_delta", "text": "Half a cushion in."},
        {"type": "audio_chunk", "data": b"\x03\x04"},
        {"type": "audio_end"},
        {"type": "turn_end"},
    ]
    appliance, state = make_appliance(script, player=SlowToStart(), publisher=publisher)

    await _run_until_idle(appliance, state)

    order = publisher.sequence
    assert order.index("thinking") < order.index("speaking")


# ---- acknowledgement (HOME-10) ---------------------------------------


@pytest.mark.asyncio
async def test_the_wake_is_shown_and_sounded_before_the_unit_listens():
    """Four seconds of nothing is what this card exists to remove. The first
    of those seconds now has something in it."""
    publisher = RecordingPublisher()
    appliance, state = make_appliance(publisher=publisher)

    await _run_until_idle(appliance, state)

    ordered = publisher.sequence
    assert "heard" in ordered
    assert ordered.index("heard") < ordered.index("listening")
    assert state["earcons"].played[0] == "wake"


@pytest.mark.asyncio
async def test_the_wake_tone_finishes_before_the_microphone_opens():
    """The ordering guarantee, end to end: the unit must never record the
    sound it makes to say it is recording."""
    order: list[str] = []
    earcons = FakeEarcons(log=order)

    class LoggingSession(FakeSession):
        def capture_voice(self) -> str:
            order.append("capture")
            return self.transcript

    appliance, state = make_appliance(session=LoggingSession(), earcons=earcons)

    await _run_until_idle(appliance, state)

    assert order.index("earcon:wake") < order.index("capture")


@pytest.mark.asyncio
async def test_the_end_of_capture_is_sounded_for_a_real_question():
    appliance, state = make_appliance()

    await _run_until_idle(appliance, state)

    assert state["earcons"].played == ["wake", "capture_done"]


@pytest.mark.asyncio
async def test_a_silent_misfire_is_acknowledged_but_never_announces_work():
    """It chirps once to say it heard you, then withdraws in silence."""
    session = FakeSession()
    session.transcript = ""
    appliance, state = make_appliance(session=session)

    await _run_until_idle(appliance, state)

    assert state["earcons"].played == ["wake"]
    assert session.turns == []


@pytest.mark.asyncio
async def test_silenced_earcons_still_show_the_wake_on_screen():
    """The off switch quiets the room. It does not blind the display."""
    publisher = RecordingPublisher()
    appliance, state = make_appliance(
        earcons=FakeEarcons(enabled=False), publisher=publisher
    )

    await _run_until_idle(appliance, state)

    assert state["earcons"].played == []
    assert "heard" in publisher.sequence


@pytest.mark.asyncio
async def test_an_earcon_never_overlaps_the_spoken_response():
    """Earcons live in the gap between the question and the answer. If one
    ever lands during playback it is coming out over the reply."""
    order: list[str] = []
    earcons = FakeEarcons(log=order)
    script = [
        {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2},
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "audio_end"},
        {"type": "turn_end"},
    ]

    class LoggingPlayer(FakePlayer):
        def write(self, chunk: bytes) -> None:
            order.append("response-audio")
            super().write(chunk)

    appliance, state = make_appliance(script, player=LoggingPlayer(), earcons=earcons)

    await _run_until_idle(appliance, state)

    assert order == ["earcon:wake", "earcon:capture_done", "response-audio"]


@pytest.mark.asyncio
async def test_earcons_do_not_share_the_response_player():
    """Sharing would let a courtesy chirp close the stream mid-sentence."""
    appliance, state = make_appliance()

    await _run_until_idle(appliance, state)

    assert appliance._earcons is not appliance._player


@pytest.mark.asyncio
async def test_a_dead_speaker_costs_the_chirp_and_nothing_else():
    class BrokenEarcons(FakeEarcons):
        def play(self, name: str) -> None:
            raise RuntimeError("no output device")

    appliance, state = make_appliance(earcons=BrokenEarcons())

    await _run_until_idle(appliance, state)

    assert state["session"].turns == ["what is the weather"]
