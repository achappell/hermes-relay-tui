"""The single place a front end calls to get a working hands-free loop."""

import types

import pytest

import handsfree
import wake


def _args(**overrides):
    defaults = dict(
        wake_enabled=True,
        wake_model=None,
        wake_threshold=0.6,
        wake_confirmation_frames=3,
        wake_refractory_seconds=2.0,
        wake_listen_timeout=8.0,
        wake_barge_in=False,
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


class FakeSession:
    def __init__(self, transcript="hello"):
        self.turns = []
        self._transcript = transcript

    def capture_voice(self):
        return self._transcript

    def send_turn(self, text, *, stt_source="local"):
        self.turns.append((text, stt_source))


class AlwaysEngine:
    def score(self, frame):  # noqa: ARG002
        return 1.0


def test_disabled_configuration_builds_nothing():
    assert handsfree.build_hands_free(FakeSession(), _args(wake_enabled=False)) is None


def test_a_missing_extra_raises_a_message_naming_the_extra():
    def _no_engine(_path):
        raise wake.MissingWakeDependency(
            "Wake-word support needs the optional 'wake' extra. "
            "Install it with: hermes-relay install"
        )

    with pytest.raises(wake.MissingWakeDependency) as excinfo:
        handsfree.build_hands_free(FakeSession(), _args(), _load_engine=_no_engine)

    assert "hermes-relay install" in str(excinfo.value)


def _frames(count):
    """Enough samples to complete one openWakeWord-sized chunk."""
    import numpy as np

    return [np.zeros(wake.OPENWAKEWORD_CHUNK_SAMPLES, dtype="int16") for _ in range(count)]


def test_the_built_loop_turns_a_detection_into_a_turn():
    session = FakeSession()
    listener, coordinator = handsfree.build_hands_free(
        session,
        _args(wake_confirmation_frames=1),
        _load_engine=lambda path: AlwaysEngine(),
    )

    for frame in _frames(1):
        listener.submit(frame)
    listener.run_pending()

    assert session.turns == [("hello", "local")]
    assert coordinator.state == handsfree.IDLE


def test_the_built_loop_drops_a_hallucinated_misfire():
    """voice.py's filter is wired in by default, so a fan trigger that
    transcribes as 'Thank you.' never reaches the session."""
    session = FakeSession(transcript="Thank you.")
    listener, _ = handsfree.build_hands_free(
        session,
        _args(wake_confirmation_frames=1),
        _load_engine=lambda path: AlwaysEngine(),
    )

    for frame in _frames(1):
        listener.submit(frame)
    listener.run_pending()

    assert session.turns == []


def test_the_model_path_reaches_the_engine_loader():
    seen = []
    handsfree.build_hands_free(
        FakeSession(),
        _args(wake_model="/models/hey_hermes.onnx"),
        _load_engine=lambda path: seen.append(path) or AlwaysEngine(),
    )

    assert seen == ["/models/hey_hermes.onnx"]
