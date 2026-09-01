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
