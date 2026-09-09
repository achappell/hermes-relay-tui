"""Tests for Sherpa-ONNX keyword spotting and wake word routing.

Tests both mocked engine logic (fast unit tests that run without the optional
'wake' extra in CI) and real bundled model keyword detection when the extra
is installed.
"""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from unittest.mock import MagicMock
import numpy as np
import pytest

import handsfree
import wake
import wakewords

has_sherpa = (
    importlib.util.find_spec("sherpa_onnx") is not None
    and importlib.util.find_spec("sentencepiece") is not None
)


class FakeDetectEngine:
    """Fake engine implementing detect() for multi-phrase testing."""

    def __init__(self, phrases: list[str | None]):
        self.phrases = list(phrases)
        self.resets = 0

    def detect(self, frame) -> str | None:
        return self.phrases.pop(0) if self.phrases else None

    def reset(self) -> None:
        self.resets += 1

    def score(self, frame) -> float:
        return 1.0 if self.detect(frame) else 0.0


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds: float):
        self.value += seconds


class FakeSpotterFactory:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.resets = 0

    def create_stream(self):
        return "stream"

    def reset_stream(self, stream):
        self.resets += 1


class FakeSentencePiece:
    class SentencePieceProcessor:
        def load(self, model_file):
            pass

        def encode_as_pieces(self, text):
            return text.split()


def test_wake_detector_returns_detected_phrase():
    engine = FakeDetectEngine(["hey missy", None, "hey skippy"])
    clock = FakeClock()
    detector = wake.WakeDetector(engine, now=clock, cooldown_seconds=2.0)

    assert detector.feed(object()) == "hey missy"
    # Inside cooldown
    clock.advance(0.5)
    assert detector.feed(object()) is False
    # After cooldown
    clock.advance(2.5)
    assert detector.feed(object()) == "hey skippy"


def test_wake_detector_reset_delegates_to_engine():
    engine = FakeDetectEngine([])
    detector = wake.WakeDetector(engine)
    detector.reset()
    assert engine.resets == 1


def test_wake_listener_passes_phrase_to_on_wake():
    engine = FakeDetectEngine(["hey spark"])
    detector = wake.WakeDetector(engine)
    received = []

    def on_wake(phrase: str | None = None):
        received.append(phrase)

    listener = wake.WakeListener(detector, on_wake=on_wake)
    listener.submit(np.zeros(1280, dtype=np.int16))
    listener.run_pending()

    assert received == ["hey spark"]


def test_wake_listener_notifies_zero_arg_callback_without_error():
    engine = FakeDetectEngine(["hey missy"])
    detector = wake.WakeDetector(engine)
    fired = []

    def on_wake():
        fired.append(True)

    listener = wake.WakeListener(detector, on_wake=on_wake)
    listener.submit(np.zeros(1280, dtype=np.int16))
    listener.run_pending()

    assert fired == [True]


def test_handsfree_coordinator_records_last_wake_phrase():
    session = SimpleNamespace(
        send_turn=MagicMock(), capture_voice=MagicMock(), is_connected=lambda: True
    )
    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=lambda: "testing phrase",
        send=lambda text: True,
    )

    assert coordinator.last_wake_phrase is None
    coordinator.on_wake("hey missy")
    assert coordinator.last_wake_phrase == "hey missy"

    coordinator.on_wake("hey skippy")
    assert coordinator.last_wake_phrase == "hey skippy"

    coordinator.on_wake(True)
    assert coordinator.last_wake_phrase == "hey hermes"


def test_load_sherpa_engine_missing_dependencies_raises():
    def fail_import():
        raise ImportError("No module named sherpa_onnx")

    with pytest.raises(wake.MissingWakeDependency):
        wake.load_sherpa_engine(_import_modules=fail_import)


def test_load_sherpa_engine_missing_models_raises():
    with pytest.raises(wake.MissingWakeDependency):
        wake.load_sherpa_engine(_bundled=dict)


def test_load_sherpa_engine_with_mock_modules():
    engine = wake.load_sherpa_engine(
        ["hey missy", "hey skippy"],
        _import_modules=lambda: (FakeSpotterFactory, FakeSentencePiece),
    )
    assert isinstance(engine, wake._SherpaOnnxEngine)
    assert set(engine._keyword_map.keys()) == {"HEY MISSY", "HEY SKIPPY"}


def test_load_sherpa_engine_defaults_to_hey_hermes():
    engine = wake.load_sherpa_engine(
        _import_modules=lambda: (FakeSpotterFactory, FakeSentencePiece),
    )
    assert list(engine._keyword_map.values()) == ["hey hermes"]


def test_build_hands_free_selects_sherpa_when_configured():
    session = SimpleNamespace(
        send_turn=MagicMock(), capture_voice=MagicMock(), is_connected=lambda: True
    )
    args = SimpleNamespace(
        wake_enabled=True,
        wake_engine="sherpa",
        wake_phrases="hey missy, hey skippy, hey spark",
        wake_keywords_score=1.0,
        wake_keywords_threshold=0.25,
    )

    listener, coordinator = handsfree.build_hands_free(
        session,
        args,
        _load_sherpa_engine=lambda phrases, **kw: FakeDetectEngine(phrases),
    )
    assert listener is not None
    assert coordinator is not None
    assert isinstance(listener._detector._engine, FakeDetectEngine)


def test_build_hands_free_selects_sherpa_when_phrases_provided():
    session = SimpleNamespace(
        send_turn=MagicMock(), capture_voice=MagicMock(), is_connected=lambda: True
    )
    args = SimpleNamespace(
        wake_enabled=True,
        wake_engine="openwakeword",
        wake_phrases="hey missy",
    )

    listener, coordinator = handsfree.build_hands_free(
        session,
        args,
        _load_sherpa_engine=lambda phrases, **kw: FakeDetectEngine(phrases),
    )
    assert isinstance(listener._detector._engine, FakeDetectEngine)


@pytest.mark.skipif(not has_sherpa, reason="Requires optional 'wake' extra installed")
def test_load_sherpa_engine_initializes_with_bundled_models():
    """Verify loading the bundled models creates a working engine with custom phrases."""
    engine = wake.load_sherpa_engine(
        ["hey missy", "hey skippy", "hey spark"],
        keywords_score=1.0,
        keywords_threshold=0.25,
    )
    assert hasattr(engine, "detect")
    assert hasattr(engine, "reset")
    assert hasattr(engine, "score")

    # Feeds silent frame without error
    silence = np.zeros(1280, dtype=np.int16)
    assert engine.detect(silence) is None
    assert engine.score(silence) == 0.0

    engine.reset()
