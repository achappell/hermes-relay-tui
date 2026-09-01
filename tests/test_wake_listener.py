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


def test_the_listener_rechunks_before_scoring_when_a_chunker_is_given():
    """Frames arrive at whatever size PortAudio chose; the engine must still
    see fixed-size chunks."""
    seen = []

    class RecordingEngine:
        def score(self, frame):
            seen.append(len(frame))
            return 0.0

    detector = wake.WakeDetector(RecordingEngine(), confirmation_frames=1)
    listener = wake.WakeListener(
        detector,
        on_wake=lambda: None,
        chunker=wake.FrameChunker(
            chunk_samples=4, concat=lambda frames: [x for f in frames for x in f]
        ),
    )

    listener.submit([1, 2, 3])
    listener.run_pending()
    listener.submit([4, 5, 6, 7, 8])
    listener.run_pending()

    assert seen == [4, 4]


def test_the_queue_is_bounded_by_audio_duration_not_frame_count():
    """PortAudio chooses the block size and it can be tiny - measured at ~15
    samples on a MacBook Air, over a thousand callbacks a second. A queue
    bounded only by frame count then holds milliseconds of audio, not seconds,
    and drops the middle of the phrase under the slightest stall."""
    listener, _ = _listener([], max_buffered_samples=1000)

    for _ in range(100):
        listener.submit([0] * 100)

    assert listener.buffered_samples <= 1000
    assert listener.dropped_frames > 0


def test_frames_without_a_length_still_respect_the_frame_cap():
    listener, _ = _listener([], queue_size=4)
    for _ in range(10):
        listener.submit(object())
    assert listener.dropped_frames == 6
