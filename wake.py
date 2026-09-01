"""Wake-word detection for the hands-free home unit.

Detection only: scoring frames and deciding when a phrase has been spoken.
Orchestration — what to do about it — belongs to `handsfree.py`, so this
module stays drivable by scripted scores with no model and no microphone.

The engine is an injected interface with one implementation. HOME-08 may add
sherpa-onnx keyword spotting for an open-vocabulary phrase, and that should be
a second implementation rather than a rewrite.

Core module: no user-interface framework, no assumed terminal.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)

__all__ = [
    "WakeEngine",
    "WakeDetector",
    "WakeListener",
    "SilentStreamMonitor",
    "FrameChunker",
    "OPENWAKEWORD_CHUNK_SAMPLES",
    "MissingWakeDependency",
    "load_openwakeword_engine",
    "DEFAULT_THRESHOLD",
    "DEFAULT_CONFIRMATION_FRAMES",
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_SILENCE_PEAK",
    "DEFAULT_SILENCE_ALERT_SECONDS",
    "DEFAULT_QUEUE_SIZE",
]

DEFAULT_THRESHOLD = 0.6

# openWakeWord scores one ~80ms frame at a time, and a stray phoneme in
# background conversation can spike a single frame over the threshold. A real
# utterance holds the score high across several consecutive frames, so N-in-a-row
# is required before firing. This is the primary lever against triggering on
# ambient talk — stronger than raising the threshold, which only makes the
# phrase harder to say.
DEFAULT_CONFIRMATION_FRAMES = 3
_MIN_CONFIRMATION_FRAMES = 1
_MAX_CONFIRMATION_FRAMES = 10

# Minimum gap between fires, so one utterance cannot retrigger while the
# caller is still reacting to the first.
DEFAULT_COOLDOWN_SECONDS = 2.0

# A stream can be open and alive but all zeros: a dead microphone reads as a
# device that is present and working. On an unattended appliance that is the
# more likely failure, and nobody is watching to notice it.
DEFAULT_SILENCE_PEAK = 10
DEFAULT_SILENCE_ALERT_SECONDS = 10.0

DEFAULT_QUEUE_SIZE = 32

# openWakeWord scores exactly 1280 samples (80ms at 16kHz) per predict() call.
# AudioRecorder opens its InputStream without a blocksize, so PortAudio picks
# the frame size and it need not match - frames must be re-chunked or the model
# is fed the wrong shape and scores meaningless numbers.
OPENWAKEWORD_CHUNK_SAMPLES = 1280

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
        """Drop any partial streak — used when the listener is paused."""
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


class FrameChunker:
    """Re-cuts ragged audio frames into fixed-size chunks for the engine."""

    def __init__(
        self,
        *,
        chunk_samples: int = OPENWAKEWORD_CHUNK_SAMPLES,
        concat: Callable[[list[Any]], Any] | None = None,
    ) -> None:
        self._chunk_samples = chunk_samples
        self._concat = concat
        self._pending: list[Any] = []
        self._pending_samples = 0

    def _join(self, frames: list[Any]) -> Any:
        if self._concat is not None:
            return self._concat(frames)
        import numpy as np  # noqa: PLC0415

        return np.concatenate(frames)

    def push(self, frame: Any) -> list[Any]:
        """Add a frame, returning every whole chunk it completes."""
        self._pending.append(frame)
        self._pending_samples += len(frame)
        if self._pending_samples < self._chunk_samples:
            return []

        buffer = self._join(self._pending)
        chunks = []
        offset = 0
        while self._pending_samples - offset >= self._chunk_samples:
            chunks.append(buffer[offset : offset + self._chunk_samples])
            offset += self._chunk_samples

        remainder = buffer[offset:]
        self._pending = [remainder] if len(remainder) else []
        self._pending_samples = len(remainder)
        return chunks

    def reset(self) -> None:
        self._pending = []
        self._pending_samples = 0


class WakeListener:
    """Owns the frame queue and the detection worker.

    Frames arrive from the audio callback thread via `submit`, which must never
    block. Scoring happens on the worker thread, never on the audio thread.
    """

    def __init__(
        self,
        detector: WakeDetector,
        *,
        on_wake: Callable[[], Any],
        on_silent_stream: Callable[[], Any] | None = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        peak_of: Callable[[Any], int] | None = None,
        silence_monitor: SilentStreamMonitor | None = None,
        chunker: FrameChunker | None = None,
    ) -> None:
        self._detector = detector
        self._on_wake = on_wake
        self._on_silent_stream = on_silent_stream
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._peak_of = peak_of
        self._silence_monitor = silence_monitor
        self._chunker = chunker
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
            # openWakeWord needs a fixed chunk size; PortAudio does not
            # promise one, so ragged frames are re-cut before scoring.
            chunks = self._chunker.push(frame) if self._chunker is not None else [frame]
            for chunk in chunks:
                if self._detector.feed(chunk):
                    self._notify(self._on_wake)
        except Exception:
            logger.debug("wake scoring failed", exc_info=True)

    def _notify(self, callback: Callable[[], Any] | None) -> None:
        if callback is None:
            return
        try:
            callback()
        except Exception:
            # A broken consumer must not take the listener down with it.
            logger.debug("wake callback failed", exc_info=True)

    def pause(self) -> None:
        """Stop scoring — used while a voice turn holds the microphone."""
        self._paused = True
        self._detector.reset()
        if self._chunker is not None:
            self._chunker.reset()

    def resume(self) -> None:
        self._detector.reset()
        if self._chunker is not None:
            self._chunker.reset()
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
        # sounddevice hands back (samples, channels); openWakeWord wants a flat
        # 1-D int16 array and silently misbehaves on the wrong shape.
        if getattr(frame, "ndim", 1) > 1:
            frame = frame.reshape(-1)
        predictions = self._model.predict(frame)
        if not predictions:
            return 0.0
        return float(max(predictions.values()))
