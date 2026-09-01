"""The listener owns the queue and the worker. Tests drive it synchronously
via run_pending() so nothing depends on thread timing."""

import wake


class FakeEngine:
    def __init__(self, scores):
        self.scores = list(scores)

    def score(self, frame):  # noqa: ARG002
        return self.scores.pop(0) if self.scores else 0.0


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def _listener(scores, **kwargs):
    detector = wake.WakeDetector(
        FakeEngine(scores), confirmation_frames=1, cooldown_seconds=0.0
    )
    fired = []
    listener = wake.WakeListener(detector, on_wake=lambda: fired.append(True), **kwargs)
    return listener, fired


def test_a_detection_invokes_the_callback():
    listener, fired = _listener([0.9])
    listener.submit(object())
    listener.run_pending()
    assert fired == [True]


def test_frames_below_threshold_invoke_nothing():
    listener, fired = _listener([0.1, 0.1])
    listener.submit(object())
    listener.submit(object())
    listener.run_pending()
    assert fired == []


def test_submit_never_blocks_and_drops_oldest_when_full():
    """submit() runs on the real-time audio callback thread. Blocking there
    stutters recording for the whole process, and an unbounded queue grows
    without limit on an appliance that runs for months."""
    listener, _ = _listener([], queue_size=4)
    for _ in range(10):
        listener.submit(object())

    assert listener.dropped_frames == 6


def test_a_paused_listener_ignores_frames():
    listener, fired = _listener([0.9])
    listener.pause()
    listener.submit(object())
    listener.run_pending()
    assert fired == []


def test_resume_restores_detection():
    listener, fired = _listener([0.9])
    listener.pause()
    listener.resume()
    listener.submit(object())
    listener.run_pending()
    assert fired == [True]


def test_a_raising_callback_does_not_kill_the_worker():
    detector = wake.WakeDetector(
        FakeEngine([0.9, 0.9]), confirmation_frames=1, cooldown_seconds=0.0
    )
    calls = []

    def boom():
        calls.append(True)
        raise RuntimeError("consumer exploded")

    listener = wake.WakeListener(detector, on_wake=boom)
    listener.submit(object())
    listener.run_pending()
    listener.submit(object())
    listener.run_pending()

    assert len(calls) == 2


def test_a_silent_stream_notifies_once():
    clock = Clock()
    detector = wake.WakeDetector(FakeEngine([0.0, 0.0]), confirmation_frames=1)
    alerts = []
    listener = wake.WakeListener(
        detector,
        on_wake=lambda: None,
        on_silent_stream=lambda: alerts.append(True),
        peak_of=lambda frame: 0,
        silence_monitor=wake.SilentStreamMonitor(alert_seconds=10.0, now=clock),
    )

    listener.submit(object())
    listener.run_pending()
    clock.value = 11.0
    listener.submit(object())
    listener.run_pending()

    assert alerts == [True]


def test_the_worker_thread_starts_and_stops_cleanly():
    listener, fired = _listener([0.9])
    listener.start()
    try:
        listener.submit(object())
        for _ in range(100):
            if fired:
                break
            import time

            time.sleep(0.01)
    finally:
        listener.stop()

    assert fired == [True]
