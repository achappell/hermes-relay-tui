"""VOICE-10: wake mode as something the TUI is told to do, never assumes.

The whole point of this card is that an open microphone is always the result
of a deliberate act. These tests drive that with fakes: no wake engine, no
audio device, no relay.
"""

import asyncio
import logging
import threading
import types

import pytest

import app as app_module
import handsfree
from app import HermesStreamingApp

from tests.test_app import FakeSession as BaseFakeSession, make_args


class FakeSession(BaseFakeSession):
    """The base double predates the shared recorder the wake path installs."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.shared_recorder = None

    def use_shared_recorder(self, recorder) -> None:
        self.shared_recorder = recorder


class FakeListener:
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

    def submit(self, frame) -> None:  # pragma: no cover - fakes never feed frames
        pass


class FakeRecorder:
    """The always-open input stream, and whether it is actually open."""

    def __init__(self) -> None:
        self.observer = None
        self.observers = []
        self.listening = False
        self.shutdowns = 0
        self.has_detected_speech = False

    def set_frame_observer(self, observer) -> None:
        self.observer = observer
        self.observers = [] if observer is None else [observer]

    def add_frame_observer(self, observer) -> None:
        self.observers.append(observer)

    def remove_frame_observer(self, observer) -> None:
        self.observers = [current for current in self.observers if current != observer]

    def emit(self, frame) -> None:
        for observer in list(self.observers):
            observer(frame)

    def open_for_listening(self) -> None:
        self.listening = True

    def shutdown(self) -> None:
        self.shutdowns += 1
        self.listening = False


class WakeFakes:
    """Stands in for handsfree.build_hands_free and the recorder factory."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.listener: FakeListener | None = None
        self.coordinator = None
        self.recorders: list[FakeRecorder] = []
        self.builds = 0
        self.build_args = []
        self.build_kwargs = []
        self.barge_listener = None

    def build(self, session, args, **kwargs):
        self.builds += 1
        self.build_args.append(args)
        self.build_kwargs.append(kwargs)
        if not self.available:
            import wake

            raise wake.MissingWakeDependency("openwakeword is not installed")
        listener = FakeListener()
        coordinator = handsfree.HandsFreeCoordinator(
            session,
            capture=kwargs.get("capture") or session.capture_voice,
            send=kwargs.get("send") or session.send_turn,
            follow_up_capture=kwargs.get("follow_up_capture"),
            speech_detected=kwargs.get("speech_detected"),
            stop_playback=kwargs.get("stop_playback"),
            acknowledge=kwargs.get("acknowledge"),
            capture_finished=kwargs.get("capture_finished"),
            on_state_change=kwargs.get("on_state_change"),
        )
        self.listener = listener
        self.coordinator = coordinator
        return listener, coordinator

    def recorder_factory(self) -> FakeRecorder:
        recorder = FakeRecorder()
        self.recorders.append(recorder)
        return recorder

    def barge_listener_factory(self, **kwargs):
        listener = FakeBargeListener(**kwargs)
        self.barge_listener = listener
        return listener


class FakeBargeListener:
    def __init__(self, *, on_speech_start, on_transcript, **kwargs) -> None:
        self.on_speech_start = on_speech_start
        self.on_transcript = on_transcript
        self.kwargs = kwargs
        self.started = False
        self.active = False
        self.stopped = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def activate(self) -> None:
        self.active = True

    def deactivate(self) -> None:
        self.active = False

    def cancel_capture(self) -> None:
        self.cancelled = True
        self.active = False

    def stop(self) -> None:
        self.stopped = True
        self.active = False

    def submit(self, frame) -> None:  # pragma: no cover - callback wiring only
        pass

    def speak(self) -> None:
        self.on_speech_start()

    def transcribe(self, text: str) -> None:
        self.on_transcript(text)


class SlowWakeFakes(WakeFakes):
    """Hold model construction long enough to observe the startup surface."""

    def __init__(self) -> None:
        super().__init__()
        self.build_started = threading.Event()
        self.build_release = threading.Event()

    def build(self, session, args, **kwargs):
        self.build_started.set()
        self.build_release.wait(1.0)
        return super().build(session, args, **kwargs)


class SlowOpenRecorder(FakeRecorder):
    def __init__(self) -> None:
        super().__init__()
        self.open_started = threading.Event()
        self.open_release = threading.Event()

    def open_for_listening(self) -> None:
        self.open_started.set()
        self.open_release.wait(1.0)
        super().open_for_listening()


class SlowOpenWakeFakes(WakeFakes):
    def __init__(self) -> None:
        super().__init__()
        self.recorder_created = threading.Event()

    def recorder_factory(self) -> SlowOpenRecorder:
        recorder = SlowOpenRecorder()
        self.recorders.append(recorder)
        self.recorder_created.set()
        return recorder


class FailingOpenRecorder(FakeRecorder):
    def open_for_listening(self) -> None:
        raise RuntimeError("input device unavailable")


class FailingOpenWakeFakes(WakeFakes):
    def recorder_factory(self) -> FailingOpenRecorder:
        recorder = FailingOpenRecorder()
        self.recorders.append(recorder)
        return recorder


def make_app(*, fakes=None, session=None, argv=None, **arg_overrides):
    fakes = fakes if fakes is not None else WakeFakes()
    session = session if session is not None else FakeSession()
    app = HermesStreamingApp(
        args=make_args(**arg_overrides),
        session_factory=lambda: session,
        build_hands_free=fakes.build,
        recorder_factory=fakes.recorder_factory,
        barge_listener_factory=fakes.barge_listener_factory,
        argv=argv,
    )
    return app, fakes, session


def transcript_text(app) -> str:
    return app.transcript_text


# ---- the microphone is closed until told otherwise --------------------


async def test_the_tui_launches_with_wake_mode_off():
    """No configuration, no flag, and no accident arms the microphone."""
    app, fakes, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()

        assert app.wake_armed is False
        assert fakes.builds == 0
        assert fakes.recorders == []


async def test_wake_status_reports_disarmed_before_anything_happens():
    app, _, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("status")

        assert "off" in transcript_text(app).lower()


# ---- arming and disarming --------------------------------------------


async def test_wake_on_opens_the_stream_and_starts_the_listener():
    app, fakes, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

        assert app.wake_armed is True
        assert fakes.listener.started is True
        assert fakes.recorders[-1].listening is True
        assert fakes.recorders[-1].observer == fakes.listener.submit


async def test_wake_on_repaints_startup_while_model_load_is_running():
    fakes = SlowWakeFakes()
    app, _, _ = make_app(fakes=fakes)

    async with app.run_test() as pilot:
        await pilot.pause()
        startup = asyncio.create_task(app._handle_wake_command("on"))

        assert await asyncio.to_thread(fakes.build_started.wait, 1.0)
        assert app.voice_state == app_module.VOICE_STARTING
        assert "wake mode starting — loading wake model" in transcript_text(app)

        fakes.build_release.set()
        await asyncio.wait_for(startup, 1.0)
        assert app.wake_armed is True


async def test_wake_off_cancels_startup_before_the_microphone_opens():
    fakes = SlowWakeFakes()
    app, _, _ = make_app(fakes=fakes)

    async with app.run_test() as pilot:
        await pilot.pause()
        startup = asyncio.create_task(app._handle_wake_command("on"))
        await asyncio.sleep(0.05)

        await app._handle_wake_command("off")
        fakes.build_release.set()
        await asyncio.wait_for(startup, 1.0)

        assert app.wake_armed is False
        assert fakes.recorders == []
        assert "startup cancelled" in transcript_text(app)


async def test_wake_on_repaints_startup_while_microphone_opens():
    fakes = SlowOpenWakeFakes()
    app, _, _ = make_app(fakes=fakes)

    def release_opening_stream() -> None:
        fakes.recorder_created.wait(1.0)
        if fakes.recorders:
            fakes.recorders[0].open_started.wait(1.0)
            threading.Event().wait(0.2)
            fakes.recorders[0].open_release.set()

    threading.Thread(target=release_opening_stream, daemon=True).start()

    async with app.run_test() as pilot:
        await pilot.pause()
        startup = asyncio.create_task(app._handle_wake_command("on"))
        await asyncio.sleep(0.05)

        assert fakes.recorders
        recorder = fakes.recorders[0]
        assert recorder.open_started.is_set()
        assert app.voice_state == app_module.VOICE_STARTING
        assert "wake mode starting — opening microphone" in transcript_text(app)

        await asyncio.wait_for(startup, 1.0)
        assert app.wake_armed is True


async def test_wake_startup_logs_timed_model_and_microphone_stages(caplog):
    caplog.set_level(logging.DEBUG, logger="hermes_relay_tui")
    app, _, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

    messages = [record.message for record in caplog.records]
    assert any("wake.start stage=model complete elapsed=" in message for message in messages)
    assert any(
        "wake.start stage=microphone complete elapsed=" in message
        for message in messages
    )


async def test_failed_microphone_startup_releases_partial_resources():
    fakes = FailingOpenWakeFakes()
    app, _, _ = make_app(fakes=fakes)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

        assert app.wake_armed is False
        assert app.microphone_is_open is False
        assert fakes.listener.stopped is True
        assert fakes.recorders[0].shutdowns == 1
        assert app.voice_state == app_module.VOICE_ERROR


async def test_reload_cancels_wake_startup():
    fakes = SlowWakeFakes()
    app, _, _ = make_app(fakes=fakes, argv=[])

    async with app.run_test() as pilot:
        await pilot.pause()
        startup = asyncio.create_task(app._handle_wake_command("on"))
        await asyncio.sleep(0.05)

        app._handle_reload_command()
        fakes.build_release.set()
        await asyncio.wait_for(startup, 1.0)

        assert app.wake_armed is False
        assert fakes.recorders == []


async def test_connection_loss_cancels_wake_startup():
    fakes = SlowWakeFakes()
    session = FakeSession()
    app, _, _ = make_app(fakes=fakes, session=session)

    async with app.run_test() as pilot:
        await pilot.pause()
        startup = asyncio.create_task(app._handle_wake_command("on"))
        await asyncio.sleep(0.05)

        await app._mark_connection_lost()
        fakes.build_release.set()
        await asyncio.wait_for(startup, 1.0)

        assert app.wake_armed is False
        assert fakes.recorders == []
        assert session.closed is True
        assert app.connection_state == app_module.CONNECTION_DISCONNECTED


async def test_wake_off_releases_the_microphone():
    """Pausing the detector is not enough: the device must be given back, or
    the indicator stays lit and other applications stay locked out."""
    app, fakes, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        recorder = fakes.recorders[-1]
        await app._handle_wake_command("off")

        assert app.wake_armed is False
        assert fakes.listener.stopped is True
        assert recorder.shutdowns == 1
        assert recorder.listening is False


async def test_arming_twice_does_not_open_a_second_stream():
    """Two input streams on one device is unreliable across platforms."""
    app, fakes, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        await app._handle_wake_command("on")

        assert len(fakes.recorders) == 1
        assert app.wake_armed is True


async def test_disarming_when_already_off_is_harmless():
    app, fakes, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("off")

        assert app.wake_armed is False
        assert fakes.recorders == []


async def test_arming_again_after_disarming_opens_a_fresh_stream():
    """The risky path on real hardware, and the one worth having a test for:
    CoreAudio has been observed hanging on a reopened input stream."""
    app, fakes, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        await app._handle_wake_command("off")
        await app._handle_wake_command("on")

        assert len(fakes.recorders) == 2
        assert fakes.recorders[0].listening is False
        assert fakes.recorders[1].listening is True


# ---- the listener never competes for the microphone -------------------


async def test_the_listener_is_deaf_while_a_turn_holds_the_microphone():
    """Without this the client wakes itself on the tail of its own phrase."""
    app, fakes, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        fakes.listener.paused.clear()

        app._set_wake_listening(busy=True)

        assert fakes.listener.paused[-1] is True

        app._set_wake_listening(busy=False)

        assert fakes.listener.paused[-1] is False


async def test_a_wake_turn_is_announced_with_the_same_tones_as_the_appliance():
    app, fakes, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

        assert fakes.coordinator._acknowledge is not None
        assert fakes.coordinator._capture_finished is not None


async def test_wake_mode_wires_a_bounded_follow_up_capture():
    app, fakes, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

        assert callable(fakes.build_kwargs[0]["capture"])
        assert callable(fakes.build_kwargs[0]["follow_up_capture"])
        assert callable(fakes.build_kwargs[0]["on_state_change"])


async def test_wake_capture_uses_the_initial_and_follow_up_timeouts():
    app, fakes, session = make_app(wake_listen_timeout=6.0, wake_followup_seconds=5.0)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

        fakes.build_kwargs[0]["capture"]()
        fakes.build_kwargs[0]["follow_up_capture"]()

        assert session.capture_wait_timeouts == [6.0, 5.0]


async def test_wake_turn_can_send_a_follow_up_without_a_second_wake():
    app, fakes, session = make_app()
    session.capture_results = iter(["what is the weather", "and tomorrow"])
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

        completed = await asyncio.wait_for(
            asyncio.to_thread(fakes.coordinator.on_wake), 1.0
        )
        assert completed is True
        await pilot.pause()
        await pilot.pause()

        assert session.sent_turns == [
            ("what is the weather", "local"),
            ("and tomorrow", "local"),
        ]
        assert session.capture_wait_timeouts == [8.0, 8.0]


async def test_wake_follow_up_stop_is_silent_and_resumes_wake_listening():
    app, fakes, session = make_app()
    session.capture_results = iter(["what is the weather", "  STOP  "])
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

        completed = await asyncio.wait_for(
            asyncio.to_thread(fakes.coordinator.on_wake), 1.0
        )
        assert completed is True
        await pilot.pause()
        await pilot.pause()

        assert session.sent_turns == [("what is the weather", "local")]
        assert fakes.listener.paused[-1] is False
        assert app.wake_armed is True
        assert "stop" not in transcript_text(app).lower()


async def test_wake_initial_stop_is_silent_and_resumes_wake_listening():
    app, fakes, session = make_app()
    session.capture_result = " Stop "
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

        completed = await asyncio.wait_for(
            asyncio.to_thread(fakes.coordinator.on_wake), 1.0
        )
        assert completed is True
        await pilot.pause()
        await pilot.pause()

        assert session.sent_turns == []
        assert fakes.listener.paused[-1] is False
        assert app.wake_armed is True
        assert "stop" not in transcript_text(app).lower()


async def test_ctrl_r_stop_remains_an_ordinary_voice_turn():
    app, _, session = make_app()
    session.capture_result = " STOP "
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._capture_voice_turn()

        assert session.sent_turns == [(" STOP ", "local-faster-whisper")]


async def test_coordinator_states_pause_the_detector_during_capture():
    app, fakes, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        fakes.listener.paused.clear()

        fakes.coordinator._set_state(handsfree.CAPTURING)
        await pilot.pause()
        assert fakes.listener.paused[-1] is True
        assert app.voice_state == app_module.VOICE_LISTENING

        fakes.coordinator._set_state(handsfree.IDLE)
        await pilot.pause()
        assert fakes.listener.paused[-1] is False
        assert app.voice_state == app_module.VOICE_READY


async def test_ctrl_r_does_not_compete_with_an_active_wake_capture():
    app, fakes, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        fakes.coordinator._begin_capture_for_test()

        await app._capture_voice_turn()

        assert app._voice_capture_task is None
        assert "wake turn is already in flight" in transcript_text(app)


async def test_ctrl_r_keeps_the_wake_detector_paused_until_its_turn_finishes():
    app, fakes, session = make_app()
    session.gate = asyncio.Event()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        fakes.listener.paused.clear()

        capture = asyncio.create_task(app._capture_voice_turn())
        for _ in range(20):
            await pilot.pause()
            if app._turn_in_flight:
                break

        assert app._turn_in_flight is True
        assert fakes.listener.paused
        assert False not in fakes.listener.paused

        session.gate.set()
        await asyncio.wait_for(capture, 1.0)
        assert fakes.listener.paused[-1] is False


class BargeInterruptSession(FakeSession):
    def __init__(self, *, spoken_text="partial answer"):
        super().__init__()
        self.release = asyncio.Event()
        self.interrupt_calls = 0
        self.spoken_text = spoken_text

    def send_turn(self, text, *, stt_source="local"):
        self.sent_turns.append((text, stt_source))
        self.turn_index += 1
        if len(self.sent_turns) > 1:
            return self._stream(DEFAULT_EVENTS)

        async def stream():
            yield {"type": "text_delta", "text": self.spoken_text}
            yield {
                "type": "audio_start",
                "sample_rate": 24000,
                "channels": 1,
                "sample_width": 2,
            }
            yield {"type": "audio_chunk", "data": b"\x00\x01"}
            await self.release.wait()
            yield {
                "type": "audio_abort",
                "turn_id": "turn-1",
                "session_id": "s1",
                "error": "client interrupt",
            }
            yield {
                "type": "turn_interrupted",
                "turn_id": "turn-1",
                "session_id": "s1",
            }

        return stream()

    async def interrupt_active_turn(self):
        self.interrupt_calls += 1
        self.release.set()
        return True


async def test_spoken_stop_interrupts_active_response_without_a_new_turn():
    fakes = WakeFakes()
    session = BargeInterruptSession()
    app, _, _ = make_app(fakes=fakes, session=session, wake_barge_in=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        first = asyncio.create_task(app._run_turn("first"))
        for _ in range(20):
            await pilot.pause()
            if "partial answer" in transcript_text(app):
                break

        fakes.barge_listener.speak()
        await pilot.pause()
        fakes.barge_listener.transcribe("  STOP  ")
        await asyncio.wait_for(first, 1.0)
        await pilot.pause()

        assert session.interrupt_calls == 1
        assert session.sent_turns == [("first", "local")]
        assert "stop" not in transcript_text(app).lower()
        assert fakes.barge_listener.active is False


async def test_barge_in_uses_its_configured_minimum_speech_duration():
    fakes = WakeFakes()
    app, _, _ = make_app(
        fakes=fakes,
        wake_barge_in=True,
        wake_barge_in_min_speech_duration=0.8,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

        assert fakes.barge_listener.kwargs["min_speech_duration"] == 0.8
        assert callable(fakes.barge_listener.kwargs["is_playing"])


async def test_spoken_follow_up_interrupts_then_starts_exactly_one_new_turn():
    fakes = WakeFakes()
    session = BargeInterruptSession()
    app, _, _ = make_app(fakes=fakes, session=session, wake_barge_in=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        first = asyncio.create_task(app._run_turn("first"))
        for _ in range(20):
            await pilot.pause()
            if "partial answer" in transcript_text(app):
                break

        fakes.barge_listener.speak()
        await pilot.pause()
        fakes.barge_listener.transcribe("what about Dawn soap?")
        await asyncio.wait_for(first, 1.0)
        for _ in range(20):
            await pilot.pause()
            if len(session.sent_turns) == 2:
                break

        assert session.interrupt_calls == 1
        assert session.sent_turns == [
            ("first", "local"),
            ("what about Dawn soap?", "local-faster-whisper"),
        ]


async def test_spoken_barge_in_interrupts_live_playback_before_transcription():
    class RecordingPlayer:
        failure = None

        def __init__(self):
            self.active = False
            self.close_calls = 0

        def start(self, audio_format):
            self.active = True

        def write(self, chunk):
            pass

        def close(self):
            self.close_calls += 1
            self.active = False

    fakes = WakeFakes()
    session = BargeInterruptSession()
    app, _, _ = make_app(
        fakes=fakes,
        session=session,
        wake_barge_in=True,
        no_play=False,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        app.player = RecordingPlayer()
        await app._handle_wake_command("on")
        first = asyncio.create_task(app._run_turn("first"))
        for _ in range(20):
            await pilot.pause()
            if app.player.active:
                break

        assert app.player.active is True
        fakes.barge_listener.speak()
        await pilot.pause()

        assert app.player.close_calls >= 1
        assert app.player.active is False
        assert session.interrupt_calls == 1
        fakes.barge_listener.transcribe("STOP")
        await asyncio.wait_for(first, 1.0)
        assert app.player.close_calls >= 1


async def test_unrecognized_barge_candidate_does_not_start_a_follow_up_turn():
    fakes = WakeFakes()
    session = BargeInterruptSession()
    app, _, _ = make_app(fakes=fakes, session=session, wake_barge_in=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        first = asyncio.create_task(app._run_turn("first"))
        for _ in range(20):
            await pilot.pause()
            if "partial answer" in transcript_text(app):
                break

        fakes.barge_listener.speak()
        await pilot.pause()
        assert session.interrupt_calls == 1

        fakes.barge_listener.transcribe("")
        await pilot.pause()
        assert session.interrupt_calls == 1
        assert session.sent_turns == [("first", "local")]

        session.release.set()
        await asyncio.wait_for(first, 1.0)


async def test_playback_echo_is_discarded_after_immediate_barge_interrupt():
    class RecordingPlayer:
        failure = None

        def __init__(self):
            self.active = False

        def start(self, audio_format):
            self.active = True

        def write(self, chunk):
            pass

        def close(self):
            self.active = False

    fakes = WakeFakes()
    session = BargeInterruptSession(
        spoken_text="I checked the kitchen and the dishes are ready for dinner."
    )
    app, _, _ = make_app(
        fakes=fakes,
        session=session,
        wake_barge_in=True,
        no_play=False,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        app.player = RecordingPlayer()
        await app._handle_wake_command("on")
        first = asyncio.create_task(app._run_turn("first"))
        for _ in range(20):
            await pilot.pause()
            if "dishes are ready" in transcript_text(app):
                break

        fakes.barge_listener.speak()
        await pilot.pause()
        fakes.barge_listener.transcribe("the dishes are ready")
        await asyncio.wait_for(first, 1.0)
        await pilot.pause()

        assert session.interrupt_calls == 1
        assert session.sent_turns == [("first", "local")]


async def test_ctrl_c_cancels_spoken_barge_in_and_cannot_submit_a_late_transcript():
    fakes = WakeFakes()
    session = BargeInterruptSession()
    app, _, _ = make_app(fakes=fakes, session=session, wake_barge_in=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        first = asyncio.create_task(app._run_turn("first"))
        for _ in range(20):
            await pilot.pause()
            if "partial answer" in transcript_text(app):
                break

        fakes.barge_listener.speak()
        await pilot.pause()
        await app.action_interrupt()
        await asyncio.wait_for(first, 1.0)
        fakes.barge_listener.transcribe("do not send this")
        await pilot.pause()

        assert fakes.barge_listener.cancelled is True
        assert session.sent_turns == [("first", "local")]


async def test_spoken_barge_in_uses_reconnect_fallback_without_claiming_remote_cancel():
    class LegacySession(BargeInterruptSession):
        async def interrupt_active_turn(self):
            self.interrupt_calls += 1
            return False

        async def close(self):
            self.closed = True
            self.connected = False

        async def connect(self):
            self.connect_calls += 1
            self.connected = True
            return self.hello

    fakes = WakeFakes()
    session = LegacySession()
    app, _, _ = make_app(fakes=fakes, session=session, wake_barge_in=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        first = asyncio.create_task(app._run_turn("first"))
        for _ in range(20):
            await pilot.pause()
            if "partial answer" in transcript_text(app):
                break

        fakes.barge_listener.speak()
        await pilot.pause()
        fakes.barge_listener.transcribe("what about Dawn soap?")
        for _ in range(30):
            await pilot.pause()
            if len(session.sent_turns) == 2:
                break

        assert first.done()
        assert session.interrupt_calls == 1
        assert session.closed is True
        assert session.connect_calls == 2  # initial connection plus fallback reconnect
        assert session.sent_turns == [
            ("first", "local"),
            ("what about Dawn soap?", "local-faster-whisper"),
        ]


async def test_ctrl_c_cancels_a_wake_follow_up_capture():
    class BlockingFollowUpSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.capture_started = threading.Event()
            self.capture_release = threading.Event()
            self.cancel_voice_calls = 0

        def capture_voice(self, *, wait_timeout=None):
            self.capture_calls += 1
            self.capture_wait_timeouts.append(wait_timeout)
            if self.capture_calls == 1:
                return "what is the weather"
            self.capture_started.set()
            self.capture_release.wait(1.0)
            return ""

        def cancel_voice(self):
            self.cancel_voice_calls += 1
            self.capture_release.set()

    session = BlockingFollowUpSession()
    app, fakes, _ = make_app(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        wake = asyncio.create_task(asyncio.to_thread(fakes.coordinator.on_wake))
        await asyncio.to_thread(session.capture_started.wait, 1.0)

        await app.action_interrupt()
        await asyncio.wait_for(wake, 1.0)

        assert session.cancel_voice_calls == 1
        assert app.wake_armed is True
        assert app.voice_state == app_module.VOICE_READY


# ---- failures say what to do -----------------------------------------


async def test_a_missing_wake_extra_names_the_install_command():
    """A traceback is not a message. Tell the user the one thing that fixes
    it."""
    app, fakes, _ = make_app(fakes=WakeFakes(available=False))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

        text = transcript_text(app)
        assert "hermes-relay-tui[wake]" in text
        assert app.wake_armed is False


async def test_wake_can_retry_after_startup_failure():
    fakes = WakeFakes(available=False)
    app, _, _ = make_app(fakes=fakes)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

        assert app._wake_starting is False
        fakes.available = True
        await app._handle_wake_command("on")

        assert app.wake_armed is True
        assert fakes.builds == 2


async def test_an_unknown_argument_shows_usage():
    app, _, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("sideways")

        assert "usage: /wake" in transcript_text(app)


# ---- teardown ---------------------------------------------------------


async def test_quitting_releases_the_microphone():
    app, fakes, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        recorder = fakes.recorders[-1]

    assert recorder.shutdowns == 1


# ---- reload and reconnect are explicit microphone boundaries ----------


async def test_reload_disarms_wake_mode_and_releases_the_microphone(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("wake_threshold: 0.8\n")
    app, fakes, _ = make_app(argv=["--config", str(config_path)])

    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        recorder = fakes.recorders[-1]

        app._handle_reload_command()

        assert app.wake_armed is False
        assert fakes.listener.stopped is True
        assert recorder.shutdowns == 1
        assert recorder.listening is False
        assert "wake mode off — config reloaded" in transcript_text(app)
        assert "config reloaded from" in transcript_text(app)


async def test_rearming_after_reload_uses_the_new_wake_settings(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("wake_threshold: 0.8\n")
    app, fakes, _ = make_app(argv=["--config", str(config_path)])

    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        app._handle_reload_command()
        await app._handle_wake_command("on")

        assert len(fakes.build_args) == 2
        assert fakes.build_args[-1].wake_threshold == 0.8


async def test_malformed_reload_keeps_active_wake_mode(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(":\n  - not: [valid\n")
    app, fakes, _ = make_app(argv=["--config", str(config_path)])

    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        recorder = fakes.recorders[-1]

        app._handle_reload_command()

        assert app.wake_armed is True
        assert fakes.listener.stopped is False
        assert recorder.shutdowns == 0
        assert recorder.listening is True
        assert "[error] /reload:" in transcript_text(app)


async def test_connection_loss_disarms_wake_mode_and_releases_the_microphone():
    app, fakes, session = make_app()

    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        recorder = fakes.recorders[-1]

        await app._mark_connection_lost()

        assert app.wake_armed is False
        assert fakes.listener.stopped is True
        assert recorder.shutdowns == 1
        assert recorder.listening is False
        assert session.closed is True
        assert "wake mode off — connection lost" in transcript_text(app)


async def test_reconnect_disarms_wake_mode_before_opening_a_new_session():
    class ReconnectingSession(FakeSession):
        async def connect(self):
            self.connect_calls += 1
            self.connected = True
            return self.hello

    session = ReconnectingSession()
    app, fakes, _ = make_app(session=session)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        recorder = fakes.recorders[-1]
        session.connected = False

        assert await app._connect() is True

        assert app.wake_armed is False
        assert fakes.listener.stopped is True
        assert recorder.shutdowns == 1
        assert recorder.listening is False
        assert "wake mode off — connection lost" in transcript_text(app)


# ---- the launch flag stops lying --------------------------------------


def test_the_launch_flag_refuses_and_points_at_the_command(monkeypatch, capsys):
    """`--wake-enabled` parsed and did nothing at all: app.py contained no
    reference to wake or handsfree. Refusing is honest; silently ignoring is
    not."""
    monkeypatch.setattr(app_module.sys, "argv", ["hermes-relay", "--wake-enabled"])
    started = []
    monkeypatch.setattr(
        app_module.HermesStreamingApp, "run", lambda self: started.append(True)
    )

    code = app_module.main()

    assert code == 2
    assert started == []
    assert "/wake on" in capsys.readouterr().err
