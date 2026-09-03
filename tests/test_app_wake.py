"""VOICE-10: wake mode as something the TUI is told to do, never assumes.

The whole point of this card is that an open microphone is always the result
of a deliberate act. These tests drive that with fakes: no wake engine, no
audio device, no relay.
"""

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
        self.listening = False
        self.shutdowns = 0
        self.has_detected_speech = False

    def set_frame_observer(self, observer) -> None:
        self.observer = observer

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

    def build(self, session, args, **kwargs):
        self.builds += 1
        self.build_args.append(args)
        if not self.available:
            import wake

            raise wake.MissingWakeDependency("openwakeword is not installed")
        listener = FakeListener()
        coordinator = handsfree.HandsFreeCoordinator(
            session,
            capture=session.capture_voice,
            send=kwargs.get("send") or session.send_turn,
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


def make_app(*, fakes=None, session=None, argv=None, **arg_overrides):
    fakes = fakes if fakes is not None else WakeFakes()
    session = session if session is not None else FakeSession()
    app = HermesStreamingApp(
        args=make_args(**arg_overrides),
        session_factory=lambda: session,
        build_hands_free=fakes.build,
        recorder_factory=fakes.recorder_factory,
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
