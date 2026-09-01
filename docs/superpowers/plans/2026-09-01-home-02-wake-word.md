# HOME-02 Wake-Word Listener and Hands-Free Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The home unit wakes on a spoken phrase and hands the resulting turn to the shared session core, with no keyboard involved.

**Architecture:** `AudioRecorder` already keeps one persistent `sounddevice.InputStream` open and discards frames between recordings. A frame observer at that discard point feeds a detection worker (`wake.py`), which fires a callback consumed by a state machine (`handsfree.py`) that drives the existing capture path and `session.SessionProtocol`. No second audio device handle is ever opened.

**Tech Stack:** Python 3.14, openWakeWord (ONNX) behind an injected engine interface, `sounddevice`, `faster-whisper`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-01-home-02-wake-word-design.md`

## Global Constraints

- `wake.py` and `handsfree.py` are **core modules**: they must not import `textual`, must not assume a terminal, a keyboard, or a human watching a screen. Enforced by `tests/test_core_boundary.py`.
- `openwakeword` and `onnxruntime` go in the `wake` optional-dependency extra, never base dependencies. A TUI install must not pull an ONNX runtime.
- All openwakeword imports are **lazy** (inside functions), matching `voice.py`'s `faster_whisper` handling. The absent-dependency path must produce an explicit message, never a silent failure or a bare traceback.
- The frame observer runs on the real-time audio callback thread. It may only do a non-blocking queue push. **Inference never runs on the audio thread.**
- Default listening window is **8.0 seconds** (confirmed by Amanda, 2026-09-01).
- Default confirmation frames is **3**, clamped to 1–10.
- Default fire cooldown (refractory) is **2.0 seconds**.
- Default wake threshold is **0.6**.
- Barge-in defaults to **off** (`--wake-barge-in` absent) until HOME-05.
- Wake listener defaults to **off** (`--wake-enabled` absent).
- Tests use fakes only. No test may require a microphone, a model file, or the `wake` extra to be installed.
- Existing suite is 300 tests passing. Every task ends green.
- Commit after every task. Never push to `main`; this work lands via a PR.

---

### Task 1: Frame observer hook in `voice.py`

**Files:**
- Modify: `voice.py:54-75` (`AudioRecorder.__init__`), `voice.py:97-102` (the stream callback)
- Test: `tests/test_voice_frame_observer.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `AudioRecorder.set_frame_observer(observer: Callable[[Any], None] | None) -> None`. The observer is called with the raw `indata` frame **only when the recorder is not recording**. Exceptions raised by the observer are swallowed and logged, never propagated into the audio callback.

- [ ] **Step 1: Write the failing tests**

```python
"""The wake-word listener taps AudioRecorder's persistent stream rather than
opening a second device handle, so these tests pin the tap's contract."""

import voice


class _FakeFrame:
    def __init__(self, tag):
        self.tag = tag


def _recorder():
    return voice.AudioRecorder()


def test_observer_receives_frames_while_idle():
    recorder = _recorder()
    seen = []
    recorder.set_frame_observer(seen.append)

    recorder._dispatch_frame(_FakeFrame("a"))

    assert [frame.tag for frame in seen] == ["a"]


def test_observer_is_silent_while_recording():
    """During capture the frames belong to the recorder. The listener is deaf
    by construction, which is what stops a detection stacking a second turn."""
    recorder = _recorder()
    seen = []
    recorder.set_frame_observer(seen.append)
    recorder._recording = True

    recorder._dispatch_frame(_FakeFrame("a"))

    assert seen == []


def test_observer_can_be_cleared():
    recorder = _recorder()
    seen = []
    recorder.set_frame_observer(seen.append)
    recorder.set_frame_observer(None)

    recorder._dispatch_frame(_FakeFrame("a"))

    assert seen == []


def test_observer_exception_never_escapes_the_audio_callback():
    """A raising observer must not kill the audio thread and stop recording
    for the whole process."""
    recorder = _recorder()

    def boom(frame):
        raise RuntimeError("detector exploded")

    recorder.set_frame_observer(boom)

    recorder._dispatch_frame(_FakeFrame("a"))  # must not raise
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_voice_frame_observer.py -v`
Expected: FAIL with `AttributeError: 'AudioRecorder' object has no attribute 'set_frame_observer'`

- [ ] **Step 3: Implement the hook**

In `AudioRecorder.__init__`, alongside the other instance attributes, add:

```python
        self._frame_observer: Any = None
```

Add these methods to `AudioRecorder`:

```python
    def set_frame_observer(self, observer) -> None:
        """Receive frames the recorder would otherwise discard.

        The wake-word listener subscribes here instead of opening its own
        InputStream: two input streams on one device is unreliable across
        platforms, and this stream is deliberately kept open for the process
        lifetime because reopening it can hang on macOS CoreAudio.
        """
        self._frame_observer = observer

    def _dispatch_frame(self, indata) -> None:
        """Hand an idle frame to the observer. Called from the audio thread."""
        if self._recording:
            return
        observer = self._frame_observer
        if observer is None:
            return
        try:
            observer(indata)
        except Exception:
            # The audio callback must survive a broken consumer: raising here
            # would stop the stream and take recording down with it.
            logger.debug("wake frame observer failed", exc_info=True)
```

In the stream callback (`voice.py:100`), replace:

```python
            if not self._recording:
                return
```

with:

```python
            if not self._recording:
                self._dispatch_frame(indata)
                return
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_voice_frame_observer.py -v`
Expected: 4 passed

- [ ] **Step 5: Run the full suite**

Run: `venv/bin/python -m pytest -q`
Expected: 304 passed

- [ ] **Step 6: Commit**

```bash
git add voice.py tests/test_voice_frame_observer.py
git commit -m "feat: let AudioRecorder hand idle frames to an observer"
```

---

### Task 2: `wake.py` detection core

**Files:**
- Create: `wake.py`
- Test: `tests/test_wake.py`

**Interfaces:**
- Consumes: nothing from Task 1 at import time.
- Produces:
  - `class WakeEngine(Protocol)` with `score(frame) -> float`.
  - `class WakeDetector` — `WakeDetector(engine, *, threshold: float = 0.6, confirmation_frames: int = 3, cooldown_seconds: float = 2.0, now: Callable[[], float] = time.monotonic)`; method `feed(frame) -> bool` returns `True` exactly on the frame that fires.
  - `class SilentStreamMonitor` — `SilentStreamMonitor(*, peak_threshold: int = 10, alert_seconds: float = 10.0, now=time.monotonic)`; method `observe(peak: int) -> bool` returns `True` the first time the stream has been continuously silent for `alert_seconds`.
  - `MissingWakeDependency(RuntimeError)`.
  - `load_openwakeword_engine(model_path: str | None = None) -> WakeEngine` (lazy import; raises `MissingWakeDependency` with an install hint).
  - `DEFAULT_THRESHOLD`, `DEFAULT_CONFIRMATION_FRAMES`, `DEFAULT_COOLDOWN_SECONDS`, `DEFAULT_SILENCE_PEAK`, `DEFAULT_SILENCE_ALERT_SECONDS`.

- [ ] **Step 1: Write the failing tests**

```python
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
    kwargs.setdefault("clock", FakeClock())
    clock = kwargs.pop("clock")
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


def test_missing_dependency_names_the_extra():
    with pytest.raises(wake.MissingWakeDependency) as excinfo:
        wake.load_openwakeword_engine(_import_module=_raise_import_error)

    message = str(excinfo.value)
    assert "hermes-relay-tui[wake]" in message


def _raise_import_error():
    raise ImportError("No module named 'openwakeword'")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_wake.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wake'`

- [ ] **Step 3: Implement `wake.py`**

```python
"""Wake-word detection for the hands-free home unit.

Detection only: scoring frames and deciding when a phrase has been spoken.
Orchestration - what to do about it - belongs to `handsfree.py`, so this
module stays drivable by scripted scores with no model and no microphone.

The engine is an injected interface with one implementation. HOME-08 may add
sherpa-onnx keyword spotting for an open-vocabulary phrase, and that should be
a second implementation rather than a rewrite.

Core module: no user-interface framework, no assumed terminal.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)

__all__ = [
    "WakeEngine",
    "WakeDetector",
    "SilentStreamMonitor",
    "MissingWakeDependency",
    "load_openwakeword_engine",
    "DEFAULT_THRESHOLD",
    "DEFAULT_CONFIRMATION_FRAMES",
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_SILENCE_PEAK",
    "DEFAULT_SILENCE_ALERT_SECONDS",
]

DEFAULT_THRESHOLD = 0.6

# openWakeWord scores one ~80ms frame at a time, and a stray phoneme in
# background conversation can spike a single frame over the threshold. A real
# utterance holds the score high across several consecutive frames, so N-in-a-row
# is required before firing. This is the primary lever against triggering on
# ambient talk - stronger than raising the threshold, which only makes the
# phrase harder to say.
DEFAULT_CONFIRMATION_FRAMES = 3
_MIN_CONFIRMATION_FRAMES = 1
_MAX_CONFIRMATION_FRAMES = 10

# Minimum gap between fires, so one utterance cannot retrigger while the
# caller is still reacting to the first.
DEFAULT_COOLDOWN_SECONDS = 2.0

# A stream can be open and alive but all zeros: a dead microphone reads as a
# device that is present and working. On an unattended appliance that is the
# more likely failure and nobody is watching to notice it.
DEFAULT_SILENCE_PEAK = 10
DEFAULT_SILENCE_ALERT_SECONDS = 10.0

_INSTALL_HINT = (
    "Wake-word support needs the optional 'wake' extra. "
    "Install it with: pip install 'hermes-relay-tui[wake]'"
)


class MissingWakeDependency(RuntimeError):
    """The optional wake-word dependencies are not installed."""


class WakeEngine(Protocol):
    """Scores one audio frame for the wake phrase."""

    def score(self, frame: Any) -> float: ...


class WakeDetector:
    """Turns a stream of per-frame scores into wake events."""

    def __init__(
        self,
        engine: WakeEngine,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        confirmation_frames: int = DEFAULT_CONFIRMATION_FRAMES,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._engine = engine
        self._threshold = threshold
        self._confirmation_frames = min(
            max(int(confirmation_frames), _MIN_CONFIRMATION_FRAMES),
            _MAX_CONFIRMATION_FRAMES,
        )
        self._cooldown_seconds = cooldown_seconds
        self._now = now
        self._streak = 0
        self._last_fire = 0.0
        self._has_fired = False

    def feed(self, frame: Any) -> bool:
        """Score one frame. Returns True exactly on the frame that fires."""
        score = self._engine.score(frame)
        if score < self._threshold:
            self._streak = 0
            return False

        self._streak += 1
        if self._streak < self._confirmation_frames:
            return False

        self._streak = 0
        now = self._now()
        if self._has_fired and now - self._last_fire < self._cooldown_seconds:
            return False

        self._last_fire = now
        self._has_fired = True
        return True

    def reset(self) -> None:
        """Drop any partial streak - used when the listener is paused."""
        self._streak = 0


class SilentStreamMonitor:
    """Flags a stream that is open but carrying no audio at all."""

    def __init__(
        self,
        *,
        peak_threshold: int = DEFAULT_SILENCE_PEAK,
        alert_seconds: float = DEFAULT_SILENCE_ALERT_SECONDS,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._peak_threshold = peak_threshold
        self._alert_seconds = alert_seconds
        self._now = now
        self._silent_since = now()
        self._alerted = False

    def observe(self, peak: int) -> bool:
        """Returns True the first time the stream has been silent too long."""
        now = self._now()
        if peak > self._peak_threshold:
            self._silent_since = now
            self._alerted = False
            return False

        if self._alerted:
            return False
        if now - self._silent_since < self._alert_seconds:
            return False

        self._alerted = True
        return True


def load_openwakeword_engine(
    model_path: str | None = None,
    *,
    _import_module: Callable[[], Any] | None = None,
) -> WakeEngine:
    """Build the openWakeWord engine, importing it lazily.

    The import is deferred because openwakeword and onnxruntime live in the
    optional 'wake' extra: a terminal install must not pull an ONNX runtime.
    """
    def _default_import() -> Any:
        from openwakeword.model import Model  # noqa: PLC0415

        return Model

    importer = _import_module or _default_import
    try:
        model_factory = importer()
    except ImportError as error:
        raise MissingWakeDependency(_INSTALL_HINT) from error

    return _OpenWakeWordEngine(model_factory, model_path)


class _OpenWakeWordEngine:
    """Adapts openWakeWord's Model to the WakeEngine interface."""

    def __init__(self, model_factory: Any, model_path: str | None) -> None:
        kwargs = {"wakeword_models": [model_path]} if model_path else {}
        self._model = model_factory(**kwargs)

    def score(self, frame: Any) -> float:
        predictions = self._model.predict(frame)
        if not predictions:
            return 0.0
        return float(max(predictions.values()))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_wake.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add wake.py tests/test_wake.py
git commit -m "feat: add wake-word detection with confirmation frames"
```

---

### Task 3: `wake.py` listener thread

**Files:**
- Modify: `wake.py`
- Test: `tests/test_wake_listener.py`

**Interfaces:**
- Consumes: `WakeDetector`, `SilentStreamMonitor` from Task 2; `AudioRecorder.set_frame_observer` from Task 1.
- Produces: `class WakeListener` — `WakeListener(detector, *, on_wake: Callable[[], None], on_silent_stream: Callable[[], None] | None = None, queue_size: int = 32, peak_of: Callable[[Any], int] | None = None)`; methods `submit(frame) -> None` (non-blocking, drops oldest when full), `run_pending() -> None` (drains and scores the queue on the caller's thread), `start()`, `stop()`, `pause()`, `resume()`, and property `dropped_frames`.

`run_pending()` exists so tests drive the worker deterministically without threads. `start()` spawns a daemon thread that loops on `run_pending()`.

- [ ] **Step 1: Write the failing tests**

```python
"""The listener owns the queue and the worker. Tests drive it synchronously
via run_pending() so nothing depends on thread timing."""

import wake


class FakeEngine:
    def __init__(self, scores):
        self.scores = list(scores)

    def score(self, frame):  # noqa: ARG002
        return self.scores.pop(0) if self.scores else 0.0


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
    class Clock:
        def __init__(self):
            self.value = 0.0

        def __call__(self):
            return self.value

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_wake_listener.py -v`
Expected: FAIL with `AttributeError: module 'wake' has no attribute 'WakeListener'`

- [ ] **Step 3: Implement `WakeListener` in `wake.py`**

Add these imports at the top of `wake.py`:

```python
import queue
import threading
```

Append to `wake.py`, and add `"WakeListener"` to `__all__`:

```python
DEFAULT_QUEUE_SIZE = 32


class WakeListener:
    """Owns the frame queue and the detection worker.

    Frames arrive from the audio callback thread via `submit`, which must never
    block. Scoring happens on the worker thread, never on the audio thread.
    """

    def __init__(
        self,
        detector: WakeDetector,
        *,
        on_wake: Callable[[], None],
        on_silent_stream: Callable[[], None] | None = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        peak_of: Callable[[Any], int] | None = None,
        silence_monitor: SilentStreamMonitor | None = None,
    ) -> None:
        self._detector = detector
        self._on_wake = on_wake
        self._on_silent_stream = on_silent_stream
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._peak_of = peak_of
        self._silence_monitor = silence_monitor
        self._paused = False
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self.dropped_frames = 0

    def submit(self, frame: Any) -> None:
        """Enqueue a frame. Called on the audio thread; never blocks."""
        if self._paused:
            return
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            # Drop the oldest rather than the newest: the freshest audio is
            # the audio most likely to contain the phrase.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(frame)
            except (queue.Empty, queue.Full):
                pass
            self.dropped_frames += 1

    def run_pending(self) -> None:
        """Score everything currently queued, on the calling thread."""
        while True:
            try:
                frame = self._queue.get_nowait()
            except queue.Empty:
                return
            self._process(frame)

    def _process(self, frame: Any) -> None:
        if self._paused:
            return

        if self._silence_monitor is not None and self._peak_of is not None:
            try:
                if self._silence_monitor.observe(self._peak_of(frame)):
                    self._notify(self._on_silent_stream)
            except Exception:
                logger.debug("silent-stream check failed", exc_info=True)

        try:
            fired = self._detector.feed(frame)
        except Exception:
            logger.debug("wake scoring failed", exc_info=True)
            return

        if fired:
            self._notify(self._on_wake)

    def _notify(self, callback: Callable[[], None] | None) -> None:
        if callback is None:
            return
        try:
            callback()
        except Exception:
            # A broken consumer must not take the listener down with it.
            logger.debug("wake callback failed", exc_info=True)

    def pause(self) -> None:
        """Stop scoring - used while a voice turn holds the microphone."""
        self._paused = True
        self._detector.reset()

    def resume(self) -> None:
        self._detector.reset()
        self._paused = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stopping.clear()
        thread = threading.Thread(target=self._loop, name="wake-listener", daemon=True)
        self._thread = thread
        thread.start()

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                frame = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            self._process(frame)

    def stop(self) -> None:
        self._stopping.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=2.0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_wake_listener.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add wake.py tests/test_wake_listener.py
git commit -m "feat: add the wake listener worker and bounded frame queue"
```

---

### Task 4: `handsfree.py` state machine

**Files:**
- Create: `handsfree.py`
- Test: `tests/test_handsfree.py`

**Interfaces:**
- Consumes: `session.SessionProtocol`.
- Produces:
  - `HandsFreeState` string constants: `IDLE`, `CAPTURING`, `SENDING`, `SPEAKING`.
  - `class HandsFreeCoordinator` — constructor:

```python
HandsFreeCoordinator(
    session,
    *,
    capture: Callable[[], str],
    send: Callable[[str], None],
    listen_timeout: float = 8.0,
    speech_detected: Callable[[], bool] | None = None,
    stop_playback: Callable[[], None] | None = None,
    barge_in: bool = False,
    on_state_change: Callable[[str], None] | None = None,
    is_hallucination: Callable[[str], bool] | None = None,
    now: Callable[[], float] = time.monotonic,
)
```

  - Methods: `on_wake() -> bool` (returns whether a capture was started), `tick() -> None` (drives the listening-window timeout), `playback_started()`, `playback_finished()`, and property `state`.

`capture` is injected rather than reaching into `session.capture_voice` directly so the window timeout is testable without a recorder.

- [ ] **Step 1: Write the failing tests**

```python
"""The state machine, driven by a fake session and a fake capture. No audio,
no model, no network."""

import handsfree


class FakeSession:
    def __init__(self):
        self.turns = []

    def send_turn(self, text, *, stt_source="local"):
        self.turns.append((text, stt_source))


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def _coordinator(transcript="what is the weather", **kwargs):
    session = FakeSession()
    clock = kwargs.pop("clock", Clock())
    captures = []

    def capture():
        captures.append(True)
        return transcript

    kwargs.setdefault("capture", capture)
    kwargs.setdefault("send", lambda text: session.send_turn(text))
    coordinator = handsfree.HandsFreeCoordinator(session, now=clock, **kwargs)
    return coordinator, session, captures, clock


def test_a_detection_produces_exactly_one_capture_and_one_turn():
    coordinator, session, captures, _ = _coordinator()

    assert coordinator.on_wake() is True

    assert len(captures) == 1
    assert session.turns == [("what is the weather", "local")]
    assert coordinator.state == handsfree.IDLE


def test_detections_during_a_capture_do_not_stack_turns():
    """Repeated detections during an active capture must be dropped, not
    queued: queuing them is how a single utterance becomes three turns."""
    session = FakeSession()
    captures = []

    def capture():
        captures.append(True)
        # A second detection arriving mid-capture must be refused.
        assert coordinator.on_wake() is False
        return "hello"

    coordinator = handsfree.HandsFreeCoordinator(
        session, capture=capture, send=lambda text: session.send_turn(text)
    )

    coordinator.on_wake()

    assert len(captures) == 1
    assert len(session.turns) == 1


def test_an_empty_transcript_is_dropped_and_never_sent():
    coordinator, session, _, _ = _coordinator(transcript="")

    coordinator.on_wake()

    assert session.turns == []
    assert coordinator.state == handsfree.IDLE


def test_a_whitespace_transcript_is_dropped():
    coordinator, session, _, _ = _coordinator(transcript="   \n ")
    coordinator.on_wake()
    assert session.turns == []


def test_a_hallucinated_transcript_is_dropped():
    """A misfire on an extractor fan transcribes as 'Thank you.' - voice.py
    already knows how to recognise that."""
    coordinator, session, _, _ = _coordinator(
        transcript="Thank you.", is_hallucination=lambda text: text == "Thank you."
    )

    coordinator.on_wake()

    assert session.turns == []


def test_the_listening_window_expires_and_never_calls_the_session():
    """The product rule: a misfire at 2am must not wake the house."""
    session = FakeSession()
    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=lambda: "ignored",
        send=lambda text: session.send_turn(text),
        listen_timeout=8.0,
        speech_detected=lambda: False,
        now=(clock := Clock()),
    )
    coordinator._begin_capture_for_test()

    clock.advance(9.0)
    coordinator.tick()

    assert session.turns == []
    assert coordinator.state == handsfree.IDLE


def test_speech_before_the_window_expires_disarms_it():
    session = FakeSession()
    clock = Clock()
    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=lambda: "ignored",
        send=lambda text: session.send_turn(text),
        listen_timeout=8.0,
        speech_detected=lambda: True,
        now=clock,
    )
    coordinator._begin_capture_for_test()

    clock.advance(9.0)
    coordinator.tick()

    assert coordinator.state == handsfree.CAPTURING


def test_state_changes_are_reported():
    seen = []
    coordinator, _, _, _ = _coordinator(on_state_change=seen.append)

    coordinator.on_wake()

    assert seen == [handsfree.CAPTURING, handsfree.SENDING, handsfree.IDLE]


def test_barge_in_is_off_by_default():
    coordinator, _, captures, _ = _coordinator()
    coordinator.playback_started()

    assert coordinator.state == handsfree.SPEAKING
    assert coordinator.on_wake() is False
    assert captures == []


def test_barge_in_stops_playback_then_captures():
    stopped = []
    coordinator, session, captures, _ = _coordinator(
        barge_in=True, stop_playback=lambda: stopped.append(True)
    )
    coordinator.playback_started()

    assert coordinator.on_wake() is True

    assert stopped == [True]
    assert len(captures) == 1
    assert len(session.turns) == 1


def test_playback_finished_returns_to_idle():
    coordinator, _, _, _ = _coordinator()
    coordinator.playback_started()
    coordinator.playback_finished()
    assert coordinator.state == handsfree.IDLE


def test_a_capture_failure_returns_to_idle_silently():
    def capture():
        raise RuntimeError("transcription exploded")

    session = FakeSession()
    coordinator = handsfree.HandsFreeCoordinator(
        session, capture=capture, send=lambda text: session.send_turn(text)
    )

    assert coordinator.on_wake() is False
    assert session.turns == []
    assert coordinator.state == handsfree.IDLE
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_handsfree.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'handsfree'`

- [ ] **Step 3: Implement `handsfree.py`**

```python
"""Hands-free turn orchestration for the home unit.

Turns a wake event into exactly one captured turn on the shared session core.
Detection lives in `wake.py`; this module decides what to do about it.

Playback is not owned here. The appliance loop injects `stop_playback` and
calls `playback_started` / `playback_finished`, so barge-in is testable without
this module growing an audio dependency. With nothing injected the coordinator
never enters SPEAKING.

Core module: no user-interface framework, no assumed terminal.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = [
    "IDLE",
    "CAPTURING",
    "SENDING",
    "SPEAKING",
    "HandsFreeCoordinator",
    "DEFAULT_LISTEN_TIMEOUT",
]

IDLE = "idle"
CAPTURING = "capturing"
SENDING = "sending"
SPEAKING = "speaking"

# How long to wait, after the wake phrase, for the speaker to actually start
# talking. Not a recording limit: it answers "did anyone start speaking at
# all", which is the question only hands-free capture has to ask. Confirmed at
# 8s by Amanda on 2026-09-01 - long enough to turn off a tap and turn round.
DEFAULT_LISTEN_TIMEOUT = 8.0


class HandsFreeCoordinator:
    """Wake event in, at most one session turn out."""

    def __init__(
        self,
        session: Any,
        *,
        capture: Callable[[], str],
        send: Callable[[str], None],
        listen_timeout: float = DEFAULT_LISTEN_TIMEOUT,
        speech_detected: Callable[[], bool] | None = None,
        stop_playback: Callable[[], None] | None = None,
        barge_in: bool = False,
        on_state_change: Callable[[str], None] | None = None,
        is_hallucination: Callable[[str], bool] | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session = session
        self._capture = capture
        self._send = send
        self._listen_timeout = listen_timeout
        self._speech_detected = speech_detected
        self._stop_playback = stop_playback
        self._barge_in = barge_in
        self._on_state_change = on_state_change
        self._is_hallucination = is_hallucination
        self._now = now
        self._state = IDLE
        self._capture_started = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, state: str) -> None:
        self._state = state
        if self._on_state_change is None:
            return
        try:
            self._on_state_change(state)
        except Exception:
            logger.debug("hands-free state callback failed", exc_info=True)

    def playback_started(self) -> None:
        with self._lock:
            if self._state != IDLE:
                return
            self._set_state(SPEAKING)

    def playback_finished(self) -> None:
        with self._lock:
            if self._state != SPEAKING:
                return
            self._set_state(IDLE)

    def on_wake(self) -> bool:
        """Handle a detection. Returns whether a capture was started."""
        with self._lock:
            if self._state == SPEAKING:
                if not self._barge_in:
                    return False
                if self._stop_playback is not None:
                    try:
                        self._stop_playback()
                    except Exception:
                        logger.debug("stopping playback failed", exc_info=True)
            elif self._state != IDLE:
                # Single-flight: a detection during CAPTURING or SENDING is
                # dropped rather than queued. Queuing is how one utterance
                # becomes several turns.
                return False

            self._begin_capture()

        try:
            transcript = self._capture()
        except Exception:
            # A misfire must be silent and cheap. Never announce a failure the
            # user did not ask for.
            logger.debug("hands-free capture failed", exc_info=True)
            self._finish()
            return False

        self._deliver(transcript)
        return True

    def _begin_capture(self) -> None:
        self._capture_started = self._now()
        self._set_state(CAPTURING)

    def _begin_capture_for_test(self) -> None:
        """Enter CAPTURING without running a capture, for window tests."""
        with self._lock:
            self._begin_capture()

    def _deliver(self, transcript: str) -> None:
        text = (transcript or "").strip()
        if not text:
            self._finish()
            return
        if self._is_hallucination is not None:
            try:
                if self._is_hallucination(text):
                    self._finish()
                    return
            except Exception:
                logger.debug("hallucination check failed", exc_info=True)

        self._set_state(SENDING)
        try:
            self._send(text)
        except Exception:
            logger.debug("hands-free send failed", exc_info=True)
        finally:
            self._finish()

    def _finish(self) -> None:
        self._set_state(IDLE)

    def tick(self) -> None:
        """Expire the listening window if nobody ever started speaking."""
        with self._lock:
            if self._state != CAPTURING:
                return
            if self._speech_detected is not None:
                try:
                    if self._speech_detected():
                        return
                except Exception:
                    logger.debug("speech check failed", exc_info=True)
            if self._now() - self._capture_started < self._listen_timeout:
                return
            self._set_state(IDLE)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_handsfree.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add handsfree.py tests/test_handsfree.py
git commit -m "feat: add the hands-free turn coordinator"
```

---

### Task 5: Configuration and packaging

**Files:**
- Modify: `config.py` (after the existing `--mic-*` arguments, around `config.py:284`)
- Modify: `pyproject.toml`
- Modify: `tests/test_core_boundary.py:20-31`
- Test: `tests/test_config.py` (append), `tests/test_packaging.py` (append)

**Interfaces:**
- Consumes: defaults from `wake.py` and `handsfree.py`.
- Produces: parsed args `wake_enabled: bool`, `wake_model: Optional[str]`, `wake_threshold: float`, `wake_confirmation_frames: int`, `wake_refractory_seconds: float`, `wake_listen_timeout: float`, `wake_barge_in: bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_wake_word_defaults_are_off_and_conservative():
    """The listener and barge-in are both opt-in: barge-in without echo
    cancellation makes the unit interrupt its own sentence."""
    args = config.build_arg_parser().parse_args([])

    assert args.wake_enabled is False
    assert args.wake_barge_in is False
    assert args.wake_threshold == 0.6
    assert args.wake_confirmation_frames == 3
    assert args.wake_refractory_seconds == 2.0
    assert args.wake_listen_timeout == 8.0
    assert args.wake_model is None


def test_wake_word_settings_are_overridable():
    args = config.build_arg_parser().parse_args(
        [
            "--wake-enabled",
            "--wake-model",
            "/models/hey_idris.onnx",
            "--wake-threshold",
            "0.8",
            "--wake-confirmation-frames",
            "5",
            "--wake-listen-timeout",
            "12",
            "--wake-barge-in",
        ]
    )

    assert args.wake_enabled is True
    assert args.wake_model == "/models/hey_idris.onnx"
    assert args.wake_threshold == 0.8
    assert args.wake_confirmation_frames == 5
    assert args.wake_listen_timeout == 12.0
    assert args.wake_barge_in is True
```

Append to `tests/test_packaging.py`:

```python
def test_wake_dependencies_live_in_an_optional_extra():
    """HOME-02: a terminal install must not pull an ONNX runtime."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = metadata["project"]["optional-dependencies"]
    base = " ".join(metadata["project"]["dependencies"])

    wake_extra = " ".join(extras["wake"])
    assert "openwakeword" in wake_extra
    assert "onnxruntime" in wake_extra
    assert "openwakeword" not in base
    assert "onnxruntime" not in base
```

Modify `tests/test_core_boundary.py`, adding to `CORE_MODULES` in alphabetical position:

```python
    "handsfree",
```

and

```python
    "wake",
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_config.py -k wake tests/test_packaging.py -k wake -v`
Expected: FAIL with `AttributeError: 'Namespace' object has no attribute 'wake_enabled'` and `KeyError: 'wake'`

- [ ] **Step 3: Add the arguments and the extra**

In `config.py`, after the `--mic-input-device` argument, add:

```python
    parser.add_argument(
        "--wake-enabled",
        action="store_true",
        default=_cfg_bool(cfg, "wake_enabled"),
        help="listen continuously for the wake phrase (needs the 'wake' extra)",
    )
    parser.add_argument(
        "--wake-model",
        default=_cfg_str(cfg, "wake_model"),
        help="path to a wake-word .onnx model, or a built-in openWakeWord name",
    )
    parser.add_argument(
        "--wake-threshold",
        type=float,
        default=cfg.get("wake_threshold", 0.6),
        help="per-frame score above which the wake phrase is considered present",
    )
    parser.add_argument(
        "--wake-confirmation-frames",
        type=int,
        default=cfg.get("wake_confirmation_frames", 3),
        help=(
            "consecutive over-threshold frames required to fire; the main "
            "defence against triggering on background conversation"
        ),
    )
    parser.add_argument(
        "--wake-refractory-seconds",
        type=float,
        default=cfg.get("wake_refractory_seconds", 2.0),
        help="minimum gap between two wake fires",
    )
    parser.add_argument(
        "--wake-listen-timeout",
        type=float,
        default=cfg.get("wake_listen_timeout", 8.0),
        help="how long to wait after the wake phrase for speech to begin",
    )
    parser.add_argument(
        "--wake-barge-in",
        action="store_true",
        default=_cfg_bool(cfg, "wake_barge_in"),
        help=(
            "allow the wake phrase to interrupt playback; needs echo "
            "cancellation or the unit retriggers on its own voice"
        ),
    )
```

In `pyproject.toml`, add:

```toml
[project.optional-dependencies]
wake = [
  "openwakeword>=0.6",
  "onnxruntime>=1.17",
]
```

If `[project.optional-dependencies]` already exists, add the `wake` key to it rather than creating a second table.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_config.py tests/test_packaging.py tests/test_core_boundary.py -q`
Expected: all passed

- [ ] **Step 5: Run the full suite**

Run: `venv/bin/python -m pytest -q`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add config.py pyproject.toml tests/
git commit -m "feat: add wake-word configuration and the optional wake extra"
```

---

### Task 6: Wiring helper and documentation

**Files:**
- Modify: `handsfree.py`
- Modify: `README.md`
- Test: `tests/test_handsfree_wiring.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `build_hands_free(session, args, *, on_state_change=None) -> tuple[WakeListener, HandsFreeCoordinator] | None` — returns `None` when `args.wake_enabled` is false, and raises `wake.MissingWakeDependency` when the extra is absent.

- [ ] **Step 1: Write the failing test**

```python
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
    def __init__(self):
        self.turns = []

    def capture_voice(self):
        return "hello"

    def send_turn(self, text, *, stt_source="local"):
        self.turns.append((text, stt_source))


def test_disabled_configuration_builds_nothing():
    assert handsfree.build_hands_free(FakeSession(), _args(wake_enabled=False)) is None


def test_a_missing_extra_raises_a_message_naming_the_extra():
    def _no_engine(*args, **kwargs):
        raise wake.MissingWakeDependency(
            "Wake-word support needs the optional 'wake' extra. "
            "Install it with: pip install 'hermes-relay-tui[wake]'"
        )

    with pytest.raises(wake.MissingWakeDependency) as excinfo:
        handsfree.build_hands_free(
            FakeSession(), _args(), _load_engine=_no_engine
        )

    assert "hermes-relay-tui[wake]" in str(excinfo.value)


def test_the_built_loop_turns_a_detection_into_a_turn():
    class AlwaysEngine:
        def score(self, frame):  # noqa: ARG002
            return 1.0

    session = FakeSession()
    listener, coordinator = handsfree.build_hands_free(
        session, _args(wake_confirmation_frames=1), _load_engine=lambda path: AlwaysEngine()
    )

    listener.submit(object())
    listener.run_pending()

    assert session.turns == [("hello", "local")]
    assert coordinator.state == handsfree.IDLE
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_handsfree_wiring.py -v`
Expected: FAIL with `AttributeError: module 'handsfree' has no attribute 'build_hands_free'`

- [ ] **Step 3: Implement the helper**

Add to `handsfree.py`, and add `"build_hands_free"` to `__all__`:

```python
def build_hands_free(
    session: Any,
    args: Any,
    *,
    on_state_change: Callable[[str], None] | None = None,
    _load_engine: Callable[[str | None], Any] | None = None,
):
    """Assemble the hands-free loop for a front end, or None when disabled.

    Raises wake.MissingWakeDependency when the optional extra is absent, so the
    caller can report it plainly instead of dying on an import.
    """
    if not getattr(args, "wake_enabled", False):
        return None

    import wake  # noqa: PLC0415 - core module, cheap, but keep the seam explicit
    from voice import is_whisper_hallucination  # noqa: PLC0415

    loader = _load_engine or wake.load_openwakeword_engine
    engine = loader(getattr(args, "wake_model", None))

    detector = wake.WakeDetector(
        engine,
        threshold=getattr(args, "wake_threshold", wake.DEFAULT_THRESHOLD),
        confirmation_frames=getattr(
            args, "wake_confirmation_frames", wake.DEFAULT_CONFIRMATION_FRAMES
        ),
        cooldown_seconds=getattr(
            args, "wake_refractory_seconds", wake.DEFAULT_COOLDOWN_SECONDS
        ),
    )

    coordinator = HandsFreeCoordinator(
        session,
        capture=session.capture_voice,
        send=session.send_turn,
        listen_timeout=getattr(args, "wake_listen_timeout", DEFAULT_LISTEN_TIMEOUT),
        barge_in=getattr(args, "wake_barge_in", False),
        on_state_change=on_state_change,
        is_hallucination=is_whisper_hallucination,
    )

    listener = wake.WakeListener(detector, on_wake=coordinator.on_wake)
    return listener, coordinator
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_handsfree_wiring.py -v`
Expected: 3 passed

- [ ] **Step 5: Document it**

Add a `## Hands-free wake word` section to `README.md` covering: the `wake` extra install command, that the listener and barge-in are both off by default, the meaning of each `--wake-*` flag, that the listening window answers "did anyone start speaking" rather than limiting the recording, and that barge-in needs echo cancellation before it is turned on.

- [ ] **Step 6: Run the full suite**

Run: `venv/bin/python -m pytest -q`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add handsfree.py README.md tests/test_handsfree_wiring.py
git commit -m "feat: add the hands-free wiring helper and document the flags"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| Frame-observer hook at the discard point | 1 |
| Confirmation frames | 2 |
| Fire cooldown | 2 |
| Silent-stream detection | 2, 3 |
| Lazy import naming the extra | 2, 5 |
| Injected engine seam for HOME-08 | 2, 6 |
| Bounded queue, drop oldest, never block | 3 |
| pause/resume | 3 |
| Exactly one capture per detection | 4 |
| Listening window, disarmed by speech | 4 |
| Empty and hallucinated transcripts dropped | 4 |
| Barge-in built, off by default | 4, 5 |
| Playback injected, not owned | 4 |
| Config surface | 5 |
| Optional extra, not base deps | 5 |
| Core boundary enforcement | 5 |

**Not covered by this plan, deliberately:** copying `hey_hermes.onnx` into the repo, and the manual kitchen validation. The model is a binary artifact whose vendoring Amanda should approve explicitly, and the kitchen test needs a human with ears. Both are recorded on the project item instead.

**Placeholder scan:** none present; every code step carries real content.

**Type consistency:** `WakeDetector.feed` returns `bool` and is called only by `WakeListener._process`. `WakeListener` is constructed with `on_wake=coordinator.on_wake`, which returns `bool`; `_notify` ignores the return value, which is intended. `SilentStreamMonitor.observe` takes `int` and `peak_of` produces `int`. `build_hands_free` returns `tuple[WakeListener, HandsFreeCoordinator] | None`.
