"""Detection is driven by scripted scores, so none of this needs a model,
a microphone, or the `wake` extra installed."""

import pytest

import wake


class FakeEngine:
    """Returns the next scripted score for each frame."""

    def __init__(self, scores):
        self.scores = list(scores)

    def score(self, frame):  # noqa: ARG002
        return self.scores.pop(0) if self.scores else 0.0


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def _detector(scores, **kwargs):
    clock = kwargs.pop("clock", FakeClock())
    detector = wake.WakeDetector(FakeEngine(scores), now=clock, **kwargs)
    return detector, clock


def _feed(detector, count):
    return [detector.feed(object()) for _ in range(count)]


def test_scores_below_threshold_never_fire():
    detector, _ = _detector([0.1, 0.2, 0.1, 0.0])
    assert _feed(detector, 4) == [False, False, False, False]


def test_consecutive_over_threshold_frames_fire_once():
    detector, _ = _detector([0.9, 0.9, 0.9])
    assert _feed(detector, 3) == [False, False, True]


def test_a_single_frame_spike_does_not_fire():
    """openWakeWord scores ~80ms at a time; a stray phoneme in background
    conversation can spike one frame. This is the ambient-rejection case."""
    detector, _ = _detector([0.1, 0.99, 0.1, 0.1])
    assert _feed(detector, 4) == [False, False, False, False]


def test_a_broken_streak_resets():
    detector, _ = _detector([0.9, 0.9, 0.1, 0.9, 0.9])
    assert _feed(detector, 5) == [False, False, False, False, False]


def test_confirmation_frames_of_one_restores_single_frame_behaviour():
    detector, _ = _detector([0.9], confirmation_frames=1)
    assert _feed(detector, 1) == [True]


def test_confirmation_frames_are_clamped_to_a_sane_range():
    assert wake.WakeDetector(FakeEngine([]), confirmation_frames=0)._confirmation_frames == 1
    assert wake.WakeDetector(FakeEngine([]), confirmation_frames=99)._confirmation_frames == 10


def test_a_sustained_plateau_fires_once_not_once_per_frame():
    detector, _ = _detector([0.9] * 8)
    assert _feed(detector, 8).count(True) == 1


def test_a_second_utterance_inside_the_cooldown_does_not_fire():
    detector, clock = _detector([0.9] * 6, confirmation_frames=1)
    assert detector.feed(object()) is True
    clock.advance(0.5)
    assert _feed(detector, 3) == [False, False, False]


def test_a_second_utterance_after_the_cooldown_fires_again():
    detector, clock = _detector([0.9] * 6, confirmation_frames=1)
    assert detector.feed(object()) is True
    clock.advance(2.5)
    assert detector.feed(object()) is True


def test_reset_clears_a_partial_streak():
    detector, _ = _detector([0.9, 0.9, 0.9])
    detector.feed(object())
    detector.reset()
    assert _feed(detector, 2) == [False, False]


def test_silent_stream_is_flagged_after_the_alert_window():
    clock = FakeClock()
    monitor = wake.SilentStreamMonitor(alert_seconds=10.0, now=clock)

    assert monitor.observe(0) is False
    clock.advance(11.0)
    assert monitor.observe(0) is True


def test_silent_stream_is_flagged_only_once_per_episode():
    clock = FakeClock()
    monitor = wake.SilentStreamMonitor(alert_seconds=10.0, now=clock)
    monitor.observe(0)
    clock.advance(11.0)
    assert monitor.observe(0) is True
    clock.advance(11.0)
    assert monitor.observe(0) is False


def test_audible_frames_clear_the_silent_stream_condition():
    """A stream that is open and alive but all zeros is a dead mic. Audible
    audio must clear the condition so it can be reported again later."""
    clock = FakeClock()
    monitor = wake.SilentStreamMonitor(alert_seconds=10.0, now=clock)
    clock.advance(11.0)
    assert monitor.observe(0) is True

    assert monitor.observe(5000) is False
    clock.advance(11.0)
    assert monitor.observe(0) is True


def _raise_import_error():
    raise ImportError("No module named 'openwakeword'")


def test_missing_dependency_names_the_extra():
    with pytest.raises(wake.MissingWakeDependency) as excinfo:
        wake.load_openwakeword_engine(_import_module=_raise_import_error)

    assert "hermes-relay-tui[wake]" in str(excinfo.value)


class ListChunker:
    """Concatenation for plain lists, so the chunker is testable without numpy."""

    @staticmethod
    def concat(frames):
        out = []
        for frame in frames:
            out.extend(frame)
        return out


def _chunker(size=4):
    return wake.FrameChunker(chunk_samples=size, concat=ListChunker.concat)


def test_a_short_frame_yields_nothing():
    """openWakeWord needs exactly 1280 samples per predict() call. PortAudio
    chooses its own block size, so frames must be re-chunked or the model
    scores garbage."""
    chunker = _chunker()
    assert chunker.push([1, 2]) == []


def test_frames_accumulate_into_a_full_chunk():
    chunker = _chunker()
    assert chunker.push([1, 2]) == []
    assert chunker.push([3, 4]) == [[1, 2, 3, 4]]


def test_a_long_frame_yields_several_chunks():
    chunker = _chunker()
    assert chunker.push([1, 2, 3, 4, 5, 6, 7, 8, 9]) == [[1, 2, 3, 4], [5, 6, 7, 8]]


def test_the_remainder_is_carried_forward():
    chunker = _chunker()
    chunker.push([1, 2, 3, 4, 5])
    assert chunker.push([6, 7, 8]) == [[5, 6, 7, 8]]


def test_an_exactly_sized_frame_passes_straight_through():
    chunker = _chunker()
    assert chunker.push([1, 2, 3, 4]) == [[1, 2, 3, 4]]


def test_the_detector_scores_every_full_chunk():
    """The engine sees fixed-size chunks even though frames arrive ragged."""
    engine = FakeEngine([0.9, 0.9])
    detector = wake.WakeDetector(engine, confirmation_frames=2, now=FakeClock())
    chunker = _chunker()

    fired = []
    for frame in ([1, 2, 3], [4, 5, 6, 7, 8]):
        for chunk in chunker.push(frame):
            fired.append(detector.feed(chunk))

    assert fired == [False, True]


class RecordingModel:
    """Stands in for openwakeword.model.Model."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.seen = []

    def predict(self, frame):
        self.seen.append(frame)
        return {"hey_hermes": 0.42}


def test_the_engine_flattens_channel_shaped_frames():
    """sounddevice delivers (samples, channels); openWakeWord wants 1-D."""
    import numpy as np

    model = RecordingModel()
    engine = wake.load_openwakeword_engine(_import_module=lambda: (lambda **kw: model))

    frame = np.zeros((1280, 1), dtype="int16")
    assert engine.score(frame) == 0.42
    assert model.seen[0].ndim == 1
    assert len(model.seen[0]) == 1280


def test_the_engine_reports_the_highest_scoring_model():
    engine = wake.load_openwakeword_engine(
        _import_module=lambda: (
            lambda **kw: type("M", (), {"predict": lambda self, f: {"a": 0.1, "b": 0.8}})()
        )
    )
    assert engine.score([0]) == 0.8


def test_the_engine_scores_zero_when_the_model_returns_nothing():
    engine = wake.load_openwakeword_engine(
        _import_module=lambda: (
            lambda **kw: type("M", (), {"predict": lambda self, f: {}})()
        )
    )
    assert engine.score([0]) == 0.0


# ---- resetting reaches the engine (HOME-10 / C3) ----------------------


class ResettableEngine:
    def __init__(self, scores):
        self.scores = list(scores)
        self.resets = 0

    def score(self, frame):  # noqa: ARG002
        return self.scores.pop(0) if self.scores else 0.0

    def reset(self) -> None:
        self.resets += 1


def test_resetting_the_detector_also_clears_the_engine():
    """The second beep, found on hardware 2026-09-02.

    openWakeWord keeps its own rolling melspectrogram and embedding buffers.
    Clearing only the detector's streak counter leaves the spoken phrase
    sitting in the engine, so once fresh frames resume it scores a window that
    still contains the phrase and fires again — measured at 2.2s after resume,
    twice, consistently.
    """
    engine = ResettableEngine([])
    detector = wake.WakeDetector(engine, confirmation_frames=1, cooldown_seconds=0.0)

    detector.reset()

    assert engine.resets == 1


def test_an_engine_without_reset_is_still_usable():
    """The WakeEngine protocol only promises `score`. A stub, a fake, or an
    older engine must not break the listener."""

    class BareEngine:
        def score(self, frame):  # noqa: ARG002
            return 0.0

    detector = wake.WakeDetector(BareEngine(), confirmation_frames=1)

    detector.reset()  # must not raise


def test_pausing_the_listener_clears_the_engine_buffer():
    """pause() and resume() are the only places this matters, and they are on
    the path a misfire takes."""
    engine = ResettableEngine([])
    detector = wake.WakeDetector(engine, confirmation_frames=1, cooldown_seconds=0.0)
    listener = wake.WakeListener(detector, on_wake=lambda: None)

    listener.pause()
    listener.resume()

    assert engine.resets == 2, "both directions have to clear it"
