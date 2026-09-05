"""Local microphone capture and speech-to-text, owned by relay-tui.

Previously this loaded Hermes' voice-session-client.py by file path and
imported its recorder/transcription helpers straight out of the Hermes
checkout's `tools/` package. That reached into an upstream fork's internal
tooling with no stability contract, so relay-tui now owns a minimal capture
+ transcribe stack instead: sounddevice for recording with silence-based
endpointing, faster-whisper (already a relay-tui dependency) for local
transcription.
"""

from __future__ import annotations

import difflib
import logging
import os
import queue
import re
import tempfile
import threading
import time
import wave
from collections import deque
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hermes_relay_tui.voice")

SAMPLE_RATE = 16000  # Whisper native rate
CHANNELS = 1
DTYPE = "int16"
SAMPLE_WIDTH = 2
SILENCE_RMS_THRESHOLD = 200
SILENCE_DURATION_SECONDS = 1.5
DEFAULT_STT_MODEL = "base"
_BLOCKING_READ_FRAMES = 256
_READER_POLL_SECONDS = 0.01
STREAM_CLOSE_TIMEOUT = 3.0

_TEMP_DIR = os.path.join(tempfile.gettempdir(), "hermes_relay_tui_voice")


def _call_with_timeout(
    operation,
    timeout: float,
    *,
    on_complete=None,
) -> tuple[bool, Exception | None]:
    """Run a native PortAudio operation without hanging the caller forever."""
    finished = threading.Event()
    errors: list[Exception] = []

    def run() -> None:
        error = None
        try:
            operation()
        except Exception as exc:  # pragma: no cover - backend-specific
            error = exc
            errors.append(exc)
        finally:
            if on_complete is not None:
                on_complete(error)
            finished.set()

    threading.Thread(
        target=run,
        name="hermes-microphone-teardown",
        daemon=True,
    ).start()
    if not finished.wait(timeout):
        return False, None
    return True, errors[0] if errors else None


def _import_audio():
    import numpy as np
    import sounddevice as sd

    return sd, np


class AudioRecorder:
    """Thread-safe microphone recorder with silence-based auto-stop.

    A persistent ``sounddevice.InputStream`` is opened on first use and kept
    alive across recordings, since closing/reopening it can hang on macOS
    CoreAudio. The stream uses sounddevice's blocking read mode: a normal
    Python worker owns ``read()`` and dispatches frames, so PortAudio never
    calls application Python through a real-time CFFI callback.
    """

    supports_silence_autostop = True

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stream_lock = threading.Lock()
        self._stream: Any = None
        self._reader_thread: threading.Thread | None = None
        self._reader_stop: threading.Event | None = None
        self._stream_close_in_progress: Any = None
        self._stream_poisoned = False
        self._late_close_thread: threading.Thread | None = None
        self._frames: List[Any] = []
        self._recording = False
        self._start_time = 0.0
        self._sample_rate = SAMPLE_RATE
        self._has_spoken = False
        self._speech_start = 0.0
        self._dip_start = 0.0
        self._min_speech_duration = 0.3
        self._max_dip_tolerance = 0.3
        self._silence_start = 0.0
        self._resume_start = 0.0
        self._resume_dip_start = 0.0
        self._on_silence_stop = None
        self._silence_threshold = SILENCE_RMS_THRESHOLD
        self._silence_duration = SILENCE_DURATION_SECONDS
        self._max_wait = 15.0
        self._max_recording_seconds = 0.0
        self._peak_rms = 0
        self._current_rms = 0
        self._frame_observers: list[Any] = []

    def set_frame_observer(self, observer) -> None:
        """Replace the frame taps that receive otherwise-discarded audio.

        The wake-word listener subscribes here instead of opening its own
        InputStream: two input streams on one device is unreliable across
        platforms, and this stream is deliberately kept open for the process
        lifetime because reopening it can hang on macOS CoreAudio. Use
        ``add_frame_observer`` when another local consumer needs to share the
        already-open stream.
        """
        with self._lock:
            self._frame_observers = [] if observer is None else [observer]

    def add_frame_observer(self, observer) -> None:
        """Add a local frame tap without opening another input stream."""
        if observer is None:
            return
        with self._lock:
            if observer not in self._frame_observers:
                self._frame_observers.append(observer)

    def remove_frame_observer(self, observer) -> None:
        """Remove one local frame tap, leaving other consumers intact."""
        with self._lock:
            self._frame_observers = [
                current for current in self._frame_observers if current != observer
            ]

    def open_for_listening(self) -> None:
        """Open the capture stream without starting a recording.

        Push-to-talk only ever needed the stream while recording. A wake-word
        listener needs it open the whole time it is idle, which is exactly when
        frames reach the observer.
        """
        self._ensure_stream()

    def _dispatch_frame(self, indata) -> None:
        """Hand an idle frame to observers from the reader worker."""
        if self._recording:
            return
        with self._lock:
            observers = tuple(self._frame_observers)
        if not observers:
            return
        # Keep ownership separate from the recorder and from every observer.
        # The blocking reader currently receives a fresh array from
        # sounddevice, but listeners queue frames and may retain or mutate
        # them after this method returns.
        frame = indata.copy() if hasattr(indata, "copy") else indata
        for observer in observers:
            try:
                observer(frame.copy() if hasattr(frame, "copy") else frame)
            except Exception:
                # A broken consumer must not stop the shared input stream.
                logger.debug("audio frame observer failed", exc_info=True)

    def _max_duration_reached(self, elapsed: float) -> bool:
        cap = self._max_recording_seconds
        return bool(cap and cap > 0 and elapsed >= cap)

    @property
    def elapsed_seconds(self) -> float:
        if not self._recording:
            return 0.0
        return time.monotonic() - self._start_time

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def has_detected_speech(self) -> bool:
        """Whether the current recording has heard anyone speak yet.

        Hands-free capture is the only caller: it has to tell "the user is
        still thinking about what to ask" apart from "the wake word misfired
        and nobody is there".
        """
        return self._recording and self._has_spoken

    def _ensure_stream(self) -> None:
        with self._stream_lock:
            if self._stream_poisoned:
                raise RuntimeError(
                    "microphone stream is unavailable after a failed shutdown"
                )
            if self._stream is not None:
                return

            sd, np = _import_audio()
            stream = None
            try:
                # No callback argument is intentional. A callback makes
                # sounddevice create a CFFI closure that invokes Python from
                # CoreAudio's real-time thread. Blocking reads keep all
                # application work on the reader worker instead.
                stream = sd.InputStream(
                    samplerate=self._sample_rate,
                    channels=CHANNELS,
                    dtype=DTYPE,
                )
                stream.start()
                reader_stop = threading.Event()
                reader = threading.Thread(
                    target=self._read_stream,
                    args=(stream, reader_stop, np),
                    name="hermes-microphone-reader",
                    daemon=True,
                )
                self._stream = stream
                self._reader_stop = reader_stop
                self._reader_thread = reader
                reader.start()
            except Exception as exc:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                raise RuntimeError(
                    f"Failed to open audio input stream: {exc}. "
                    "Check that a microphone is connected and accessible."
                ) from exc

    def _read_stream(self, stream: Any, stop: threading.Event, np: Any) -> None:
        """Read frames outside PortAudio's real-time thread."""
        while not stop.is_set():
            try:
                available = int(stream.read_available)
            except Exception:
                if not stop.is_set():
                    logger.debug("microphone availability check failed", exc_info=True)
                return

            if available <= 0:
                stop.wait(_READER_POLL_SECONDS)
                continue

            try:
                indata, overflowed = stream.read(
                    min(available, _BLOCKING_READ_FRAMES)
                )
            except Exception:
                if not stop.is_set():
                    logger.debug("microphone read failed", exc_info=True)
                return

            if stop.is_set():
                return
            if overflowed:
                logger.debug("sounddevice input overflowed")
            self._consume_frame(indata, np)

    def _consume_frame(self, indata: Any, np: Any) -> None:
        """Route one blocking-read frame to observers or an active capture."""
        with self._lock:
            if not self._recording:
                recording = False
                callback = None
            else:
                recording = True
                self._frames.append(indata.copy())

                rms = int(np.sqrt(np.mean(indata.astype(np.float64) ** 2)))
                self._current_rms = rms
                self._peak_rms = max(self._peak_rms, rms)
                callback = None

                if self._on_silence_stop is not None:
                    now = time.monotonic()
                    elapsed = now - self._start_time

                    if rms > self._silence_threshold:
                        self._dip_start = 0.0
                        if self._speech_start == 0.0:
                            self._speech_start = now
                        elif (
                            not self._has_spoken
                            and now - self._speech_start >= self._min_speech_duration
                        ):
                            self._has_spoken = True
                        if not self._has_spoken:
                            self._silence_start = 0.0
                        else:
                            self._resume_dip_start = 0.0
                            if self._resume_start == 0.0:
                                self._resume_start = now
                            elif now - self._resume_start >= self._min_speech_duration:
                                self._silence_start = 0.0
                                self._resume_start = 0.0
                    elif self._has_spoken:
                        if self._resume_start > 0:
                            if self._resume_dip_start == 0.0:
                                self._resume_dip_start = now
                            elif now - self._resume_dip_start >= self._max_dip_tolerance:
                                self._resume_start = 0.0
                                self._resume_dip_start = 0.0
                    elif self._speech_start > 0:
                        if self._dip_start == 0.0:
                            self._dip_start = now
                        elif now - self._dip_start >= self._max_dip_tolerance:
                            self._speech_start = 0.0
                            self._dip_start = 0.0

                    should_fire = False
                    if self._has_spoken and rms <= self._silence_threshold:
                        if self._silence_start == 0.0:
                            self._silence_start = now
                        elif now - self._silence_start >= self._silence_duration:
                            should_fire = True
                    elif not self._has_spoken and elapsed >= self._max_wait:
                        should_fire = True

                    if not should_fire and self._max_duration_reached(elapsed):
                        should_fire = True

                    if should_fire:
                        callback = self._on_silence_stop
                        self._on_silence_stop = None

        if not recording:
            self._dispatch_frame(indata)
            return

        if callback:
            def _safe_cb():
                try:
                    callback()
                except Exception:
                    logger.exception("Silence callback failed")

            threading.Thread(target=_safe_cb, daemon=True).start()

    def start(self, on_silence_stop=None) -> None:
        try:
            sd, _ = _import_audio()
        except OSError as exc:
            raise RuntimeError(
                "PortAudio system library not found -- install it first:\n"
                "  macOS:  brew install portaudio"
            ) from exc
        except ImportError as exc:
            raise RuntimeError(
                "Voice mode requires sounddevice and numpy."
            ) from exc

        with self._lock:
            if self._recording:
                return
            self._frames = []
            self._start_time = time.monotonic()
            self._has_spoken = False
            self._speech_start = 0.0
            self._dip_start = 0.0
            self._silence_start = 0.0
            self._resume_start = 0.0
            self._resume_dip_start = 0.0
            self._peak_rms = 0
            self._current_rms = 0
            self._on_silence_stop = on_silence_stop

        default_rate = getattr(sd.default, "samplerate", None)
        self._sample_rate = int(default_rate) if default_rate else SAMPLE_RATE
        self._ensure_stream()

        with self._lock:
            self._recording = True

    def _close_stream_with_timeout(self, timeout: float = 3.0) -> None:
        with self._stream_lock:
            stream = self._stream
            reader = self._reader_thread
            reader_stop = self._reader_stop
            if stream is None:
                return
            if reader_stop is not None:
                reader_stop.set()

        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=timeout)

        stream_aborted = False
        if reader is not None and reader.is_alive():
            # This is an abnormal device/backend hang. There is no Python
            # PortAudio callback left to race with abort, so use it only as a
            # last-resort wake-up before giving the reader another short
            # chance to exit.
            try:
                abort = getattr(stream, "abort", None)
                if callable(abort):
                    abort()
                else:
                    stream.stop()
                stream_aborted = True
            except Exception:
                logger.debug("aborting the microphone stream failed", exc_info=True)
            reader.join(timeout=0.5)

        if reader is not None and reader.is_alive():
            logger.warning(
                "microphone reader did not stop after abort; deferring close"
            )
            with self._stream_lock:
                self._stream_poisoned = True
                late_close = self._late_close_thread
                if late_close is None or not late_close.is_alive():
                    late_close = threading.Thread(
                        target=self._finish_late_stream_close,
                        args=(stream, reader),
                        name="hermes-microphone-late-close",
                        daemon=True,
                    )
                    self._late_close_thread = late_close
                    late_close.start()
            return

        if not stream_aborted:
            try:
                abort = getattr(stream, "abort", None)
                if callable(abort):
                    abort()
                else:
                    stream.stop()
            except Exception:
                logger.debug("aborting the microphone stream failed", exc_info=True)

        self._close_stream_native(stream)

    def _finish_late_stream_close(
        self,
        stream: Any,
        reader: threading.Thread,
    ) -> None:
        reader.join()
        with self._stream_lock:
            if self._stream is not stream:
                return
        self._close_stream_native(stream)

    def _close_stream_native(self, stream: Any) -> None:
        with self._stream_lock:
            if self._stream_close_in_progress is stream:
                return
            self._stream_close_in_progress = stream

        def finished(error: Exception | None) -> None:
            if error is not None:
                logger.debug("closing the microphone stream failed: %s", error)
            with self._stream_lock:
                if self._stream_close_in_progress is stream:
                    self._stream_close_in_progress = None
                if self._stream is stream:
                    self._stream = None
                    self._reader_thread = None
                    self._reader_stop = None

        completed, error = _call_with_timeout(
            stream.close,
            STREAM_CLOSE_TIMEOUT,
            on_complete=finished,
        )
        if error is not None:
            logger.debug("closing the microphone stream failed: %s", error)
            with self._stream_lock:
                self._stream_poisoned = True
        elif not completed:
            logger.warning("microphone stream close timed out")
            with self._stream_lock:
                if self._stream_close_in_progress is stream:
                    self._stream_poisoned = True

    def stop(self) -> Optional[str]:
        with self._lock:
            if not self._recording:
                return None
            self._recording = False
            self._current_rms = 0
            if not self._frames:
                return None

            _, np = _import_audio()
            audio_data = np.concatenate(self._frames, axis=0)
            self._frames = []

            min_samples = int(self._sample_rate * 0.3)
            if len(audio_data) < min_samples:
                return None
            if self._peak_rms < SILENCE_RMS_THRESHOLD:
                return None

            return self._write_wav(audio_data, sample_rate=self._sample_rate)

    def cancel(self) -> None:
        with self._lock:
            self._recording = False
            self._frames = []
            self._on_silence_stop = None
            self._current_rms = 0

    def shutdown(self) -> None:
        with self._lock:
            self._recording = False
            self._frames = []
            self._on_silence_stop = None
        self._close_stream_with_timeout()

    @staticmethod
    def _write_wav(audio_data, *, sample_rate: int = SAMPLE_RATE) -> str:
        os.makedirs(_TEMP_DIR, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        wav_path = os.path.join(_TEMP_DIR, f"recording_{timestamp}.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data.tobytes())
        return wav_path


def create_audio_recorder() -> AudioRecorder:
    return AudioRecorder()


WHISPER_HALLUCINATIONS = {
    "thank you.",
    "thank you",
    "thanks for watching.",
    "thanks for watching",
    "subscribe to my channel.",
    "subscribe to my channel",
    "like and subscribe.",
    "like and subscribe",
    "please subscribe.",
    "please subscribe",
    "thank you for watching.",
    "thank you for watching",
    "bye.",
    "bye",
    "you",
    "the end.",
    "the end",
}

_HALLUCINATION_REPEAT_RE = re.compile(
    r'^(?:thank you|thanks|bye|you|ok|okay|the end|\.|\s|,|!)+$',
    flags=re.IGNORECASE,
)


def is_whisper_hallucination(transcript: str) -> bool:
    """Check if a transcript is a known Whisper hallucination on silence."""
    cleaned = transcript.strip().lower()
    if not cleaned:
        return True
    if cleaned.rstrip(".!") in WHISPER_HALLUCINATIONS or cleaned in WHISPER_HALLUCINATIONS:
        return True
    if _HALLUCINATION_REPEAT_RE.match(cleaned):
        return True
    return False


DEFAULT_TTS_ECHO_SIMILARITY_THRESHOLD = 0.6
MIN_FRAGMENT_LENGTH_FOR_ECHO = 10


def _normalize_for_echo_compare(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def is_tts_echo(
    transcript: str,
    spoken_text: str,
    threshold: float = DEFAULT_TTS_ECHO_SIMILARITY_THRESHOLD,
) -> bool:
    """Return whether a playback transcript resembles the response text.

    A barge-in is cut before STT completes, so a speaker bleed capture is
    usually a short fragment of a much longer response. Compare both the
    whole response and same-length windows inside it. Short transcripts skip
    window matching because a one-word interjection can occur in any answer.
    """
    if not transcript or not spoken_text:
        return False
    candidate = _normalize_for_echo_compare(transcript)
    response = _normalize_for_echo_compare(spoken_text)
    if not candidate or not response:
        return False
    if difflib.SequenceMatcher(None, candidate, response).ratio() >= threshold:
        return True
    if len(candidate) < MIN_FRAGMENT_LENGTH_FOR_ECHO or len(candidate) >= len(response):
        return False
    return any(
        difflib.SequenceMatcher(
            None,
            candidate,
            response[start : start + len(candidate)],
        ).ratio()
        >= threshold
        for start in range(0, len(response) - len(candidate) + 1)
    )


_local_model: Any = None
_local_model_name: Optional[str] = None
_local_model_lock = threading.Lock()


def _load_local_model(model_name: str):
    global _local_model, _local_model_name

    model = _local_model
    if model is not None and _local_model_name == model_name:
        return model

    with _local_model_lock:
        if _local_model is None or _local_model_name != model_name:
            from faster_whisper import WhisperModel

            logger.info("Loading faster-whisper model '%s'...", model_name)
            _local_model = WhisperModel(model_name, device="cpu", compute_type="int8")
            _local_model_name = model_name
        return _local_model


def transcribe(wav_path: str, model: Optional[str] = None) -> Dict[str, Any]:
    """Transcribe a WAV recording locally with faster-whisper.

    Returns a dict with ``success`` and ``transcript`` (and ``error`` on
    failure). Mirrors the shape relay-tui's callers already expect.
    """
    model_name = model or DEFAULT_STT_MODEL
    try:
        whisper_model = _load_local_model(model_name)
        segments, _info = whisper_model.transcribe(
            wav_path,
            beam_size=5,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
        )
        transcript = " ".join(segment.text.strip() for segment in segments).strip()
        return {"success": True, "transcript": transcript}
    except Exception as exc:
        logger.exception("Local transcription failed")
        return {"success": False, "transcript": "", "error": str(exc)}


class LocalMicrophone:
    """Capture one bounded, silence-ended utterance and transcribe it locally."""

    def __init__(
        self,
        *,
        max_seconds: float = 15.0,
        silence_duration: float = SILENCE_DURATION_SECONDS,
        silence_threshold: int = 200,
        model: Optional[str] = None,
        recorder_factory: Any = None,
        transcribe_fn: Any = None,
        hallucination_fn: Any = None,
    ) -> None:
        if max_seconds <= 0:
            raise ValueError("microphone max seconds must be greater than zero")
        if silence_duration <= 0:
            raise ValueError("microphone silence duration must be greater than zero")
        if silence_threshold < 0:
            raise ValueError("microphone silence threshold cannot be negative")
        self.max_seconds = float(max_seconds)
        self.silence_duration = float(silence_duration)
        self.silence_threshold = int(silence_threshold)
        self.model = model or None
        self._recorder_factory = recorder_factory or create_audio_recorder
        self._transcribe_fn = transcribe_fn or transcribe
        self._hallucination_fn = hallucination_fn or is_whisper_hallucination
        self._recorder: Any = None

    def _load(self) -> None:
        if self._recorder is not None:
            return
        self._recorder = self._recorder_factory()
        if not getattr(self._recorder, "supports_silence_autostop", False):
            raise RuntimeError(
                "This microphone backend cannot detect utterance boundaries."
            )
        self._recorder._silence_threshold = self.silence_threshold
        self._recorder._silence_duration = self.silence_duration
        self._recorder._max_recording_seconds = self.max_seconds

    def capture(self, *, wait_timeout: float | None = None) -> str:
        """Record one utterance, return its transcript, or "" for silence."""
        self._load()
        finished = threading.Event()
        original_max_wait = getattr(self._recorder, "_max_wait", None)
        if wait_timeout is not None:
            if wait_timeout <= 0:
                raise ValueError("microphone wait timeout must be greater than zero")
            self._recorder._max_wait = float(wait_timeout)

        try:
            self._recorder.start(on_silence_stop=finished.set)
            capture_wait = max(self.max_seconds + 2.0, 5.0)
            if wait_timeout is not None:
                # A follow-up is deliberately a short no-speech window. If a
                # broken backend never invokes the callback, do not fall back
                # to the full recording limit and turn eight seconds into
                # seventeen.
                capture_wait = max(float(wait_timeout) + 2.0, 5.0)
            finished.wait(capture_wait)
            wav_path = self._recorder.stop()
        except KeyboardInterrupt:
            self._recorder.cancel()
            raise
        except Exception as exc:
            try:
                self._recorder.cancel()
            except Exception:
                pass
            raise RuntimeError(f"microphone capture failed: {exc}") from exc
        finally:
            if wait_timeout is not None and original_max_wait is not None:
                self._recorder._max_wait = original_max_wait

        if not wav_path:
            return ""
        try:
            result = self._transcribe_fn(wav_path, model=self.model)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
        if not result.get("success"):
            raise RuntimeError(result.get("error") or "local transcription failed")
        transcript = str(result.get("transcript") or "").strip()
        if self._hallucination_fn and self._hallucination_fn(transcript):
            return ""
        return transcript

    def close(self) -> None:
        if self._recorder is not None:
            try:
                self._recorder.shutdown()
            finally:
                self._recorder = None


class BargeInListener:
    """Detect and transcribe one spoken interruption from local audio.

    This is deliberately a consumer of an already-open ``AudioRecorder``
    stream. It never sends frames to Hermes: the only outward value is the
    locally-transcribed string. ``submit`` remains deliberately cheap because
    it only queues work for the listener and never waits for inference.

    Detection follows the full-duplex voice path in Hermes: the room is
    calibrated before playback, that floor is held while the speaker is live,
    and a majority of a short energy window trips the callback. The callback
    is intentionally earlier than transcription; callers can stop playback
    immediately and use the transcript only to decide whether to submit a
    follow-up turn.
    """

    _QUEUE_SIZE = 32
    _PRE_ROLL_SECONDS = 0.25
    _DEFAULT_MIN_SPEECH_SECONDS = 0.30
    _DEFAULT_CALIBRATION_SECONDS = 0.45
    _DEFAULT_PLAYBACK_GRACE_SECONDS = 0.50
    _DEFAULT_TRIGGER_MULTIPLIER = 3.0
    _NOISY_ROOM_FLOOR_RATIO = 4.0
    _NOISY_ROOM_TRIGGER_MULTIPLIER = 1.5
    _PLAYBACK_MIN_TRIGGER = 1500
    _TRIGGER_CEILING = 4000
    _MAJORITY_FRACTION = 0.80
    _PLAYBACK_REARM_SECONDS = 1.0

    def __init__(
        self,
        *,
        on_speech_start,
        on_transcript,
        silence_duration: float = SILENCE_DURATION_SECONDS,
        silence_threshold: int = SILENCE_RMS_THRESHOLD,
        max_seconds: float = 15.0,
        min_speech_duration: float = _DEFAULT_MIN_SPEECH_SECONDS,
        sample_rate: int = SAMPLE_RATE,
        is_playing: Any = None,
        calibration_duration: float = _DEFAULT_CALIBRATION_SECONDS,
        playback_grace_duration: float = _DEFAULT_PLAYBACK_GRACE_SECONDS,
        trigger_multiplier: float = _DEFAULT_TRIGGER_MULTIPLIER,
        model: Optional[str] = None,
        transcribe_fn: Any = None,
        hallucination_fn: Any = None,
        temp_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        if silence_duration <= 0:
            raise ValueError("barge-in silence duration must be greater than zero")
        if silence_threshold < 0:
            raise ValueError("barge-in silence threshold cannot be negative")
        if max_seconds <= 0:
            raise ValueError("barge-in max seconds must be greater than zero")
        if min_speech_duration <= 0:
            raise ValueError("barge-in minimum speech duration must be greater than zero")
        if sample_rate <= 0:
            raise ValueError("barge-in sample rate must be greater than zero")
        if calibration_duration < 0:
            raise ValueError("barge-in calibration duration cannot be negative")
        if playback_grace_duration < 0:
            raise ValueError("barge-in playback grace duration cannot be negative")
        if trigger_multiplier <= 0:
            raise ValueError("barge-in trigger multiplier must be greater than zero")

        self._on_speech_start = on_speech_start
        self._on_transcript = on_transcript
        self._silence_duration = float(silence_duration)
        self._silence_threshold = int(silence_threshold)
        self._max_samples = int(float(max_seconds) * sample_rate)
        self._min_speech_samples = max(1, int(float(min_speech_duration) * sample_rate))
        self._pre_roll_samples_limit = max(1, int(self._PRE_ROLL_SECONDS * sample_rate))
        self._sample_rate = int(sample_rate)
        self._is_playing = is_playing
        self._calibration_samples_limit = int(
            float(calibration_duration) * sample_rate
        )
        self._playback_grace_samples = int(
            float(playback_grace_duration) * sample_rate
        )
        self._trigger_multiplier = float(trigger_multiplier)
        self._model = model or None
        self._transcribe_fn = transcribe_fn or transcribe
        self._hallucination_fn = hallucination_fn or is_whisper_hallucination
        self._temp_dir = os.fspath(temp_dir or _TEMP_DIR)

        self._queue: queue.Queue[Any] = queue.Queue(maxsize=self._QUEUE_SIZE)
        self._lock = threading.Lock()
        self._active = False
        self._generation = 0
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._pre_roll: deque[Any] = deque()
        self._pre_roll_samples = 0
        self._capturing = False
        self._processing = False
        self._frames: list[Any] = []
        self._captured_samples = 0
        self._silence_samples = 0
        self._ambient_rms: deque[float] = deque(maxlen=100)
        self._calibration_samples = 0
        self._floor_locked = False
        self._quiet_floor = float(self._silence_threshold)
        self._playing_prev = False
        self._playback_seen = False
        self._samples_since_playback = int(self._sample_rate * self._PLAYBACK_REARM_SECONDS)
        self._grace_samples = 0
        self._recent_above: deque[tuple[bool, int]] = deque()
        self._recent_samples = 0
        self.dropped_frames = 0

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def capturing(self) -> bool:
        with self._lock:
            return self._capturing or self._processing

    def start(self) -> None:
        """Start the worker; it remains dormant until ``activate``."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="hermes-barge-in",
                daemon=True,
            )
            thread = self._thread
            thread.start()

    def activate(self) -> None:
        """Begin accepting one interruption for the current remote turn."""
        with self._lock:
            self._generation += 1
            self._active = True
            self._reset_capture_locked()
            self._reset_detection_locked()
            self._drain_locked()

    def deactivate(self) -> None:
        """Stop accepting interruption audio and discard queued frames."""
        with self._lock:
            self._generation += 1
            self._active = False
            self._reset_capture_locked()
            self._reset_detection_locked()
            self._drain_locked()

    def cancel_capture(self) -> None:
        """Cancel the current local utterance without invoking its callback."""
        with self._lock:
            self._generation += 1
            self._reset_capture_locked()
            self._reset_detection_locked()
            self._drain_locked()

    def stop(self) -> None:
        """Stop the worker and discard any pending local audio."""
        with self._lock:
            self._generation += 1
            self._active = False
            self._reset_capture_locked()
            self._reset_detection_locked()
            self._drain_locked()
            self._stopping.set()
            thread = self._thread
            if thread is not None:
                try:
                    self._queue.put_nowait(None)
                except queue.Full:
                    pass
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        with self._lock:
            if self._thread is thread and thread is not None and not thread.is_alive():
                self._thread = None

    def submit(self, frame: Any) -> None:
        """Queue one input frame without blocking the real-time audio thread."""
        with self._lock:
            if not self._active or self._processing:
                return
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self.dropped_frames += 1
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(frame)
            except queue.Full:
                self.dropped_frames += 1

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                frame = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if frame is None:
                return
            try:
                self._process(frame)
            except Exception:
                logger.debug("barge-in frame processing failed", exc_info=True)

    @staticmethod
    def _samples(frame: Any) -> int:
        try:
            return len(frame)
        except TypeError:
            return 0

    @staticmethod
    def _rms(frame: Any) -> int:
        import numpy as np

        values = np.asarray(frame)
        if values.size == 0:
            return 0
        return int(np.sqrt(np.mean(values.astype(np.float64) ** 2)))

    def _playback_active(self) -> bool:
        if self._is_playing is None:
            return False
        try:
            return bool(self._is_playing())
        except Exception:
            logger.debug("barge-in playback state check failed", exc_info=True)
            return False

    def _lock_quiet_floor_locked(self) -> None:
        self._quiet_floor = self._ambient_floor_locked()
        self._floor_locked = True
        logger.debug(
            "barge-in calibrated quiet floor=%0.0f trigger=%0.0f from %d frames",
            self._quiet_floor,
            self._trigger_level_locked(False),
            len(self._ambient_rms),
        )

    def _ambient_floor_locked(self) -> float:
        if self._ambient_rms:
            import numpy as np

            percentile = float(np.percentile(list(self._ambient_rms), 90))
        else:
            percentile = float(self._silence_threshold)
        return max(percentile, float(self._silence_threshold))

    def _trigger_level_locked(self, playing: bool) -> float:
        multiplier = self._trigger_multiplier
        # A loud room can make a legitimate calibration floor large enough
        # that the normal 3x trigger reaches the absolute ceiling. Keep the
        # measured floor (so steady movie audio does not trip the detector),
        # but use modest headroom when that floor is already noisy.  1.5x is
        # approximately the RMS rise of a voice over an independent noise
        # source; the absolute ceiling still protects against runaway levels.
        if self._quiet_floor >= (
            float(self._silence_threshold) * self._NOISY_ROOM_FLOOR_RATIO
        ):
            multiplier = min(multiplier, self._NOISY_ROOM_TRIGGER_MULTIPLIER)
        trigger = max(
            self._quiet_floor * multiplier,
            float(self._silence_threshold) * 2,
        )
        if playing:
            trigger = max(trigger, float(self._PLAYBACK_MIN_TRIGGER))
        return min(trigger, float(self._TRIGGER_CEILING))

    def _remember_detection_locked(self, above: bool, samples: int) -> bool:
        self._recent_above.append((above, samples))
        self._recent_samples += samples
        while len(self._recent_above) > 1:
            _old_above, old_samples = self._recent_above[0]
            if self._recent_samples - old_samples < self._min_speech_samples:
                break
            self._recent_above.popleft()
            self._recent_samples -= old_samples
        if self._recent_samples < self._min_speech_samples:
            return False
        above_samples = sum(
            frame_samples for frame_above, frame_samples in self._recent_above if frame_above
        )
        return above_samples / self._recent_samples >= self._MAJORITY_FRACTION

    def _process(self, frame: Any) -> None:
        samples = self._samples(frame)
        if samples <= 0:
            return
        with self._lock:
            if not self._active or self._processing:
                return
            generation = self._generation
            capturing = self._capturing

        rms = self._rms(frame)
        if not capturing:
            self._remember_pre_roll(frame, samples)
            with self._lock:
                if not self._active or generation != self._generation:
                    return
                playing = self._playback_active()
                if not self._floor_locked:
                    if not playing:
                        self._ambient_rms.append(float(rms))
                        self._calibration_samples += samples
                    if (
                        self._calibration_samples_limit <= 0
                        or playing
                        or self._calibration_samples >= self._calibration_samples_limit
                    ):
                        self._lock_quiet_floor_locked()
                    else:
                        return

                if playing and not self._playing_prev:
                    if (
                        not self._playback_seen
                        or self._samples_since_playback
                        >= int(self._PLAYBACK_REARM_SECONDS * self._sample_rate)
                    ):
                        self._grace_samples = self._playback_grace_samples
                    self._playback_seen = True
                self._playing_prev = playing
                if playing:
                    self._samples_since_playback = 0
                else:
                    self._samples_since_playback += samples

                trigger = self._trigger_level_locked(playing)
                if not playing and rms < trigger:
                    self._ambient_rms.append(float(rms))
                    self._quiet_floor = self._ambient_floor_locked()
                    trigger = self._trigger_level_locked(playing)

                above = rms >= trigger
                if above and self._grace_samples > 0:
                    above = False
                if self._grace_samples > 0:
                    self._grace_samples = max(0, self._grace_samples - samples)

                if not self._remember_detection_locked(above, samples):
                    return
                self._capturing = True
                self._frames = list(self._pre_roll)
                self._captured_samples = self._pre_roll_samples
                self._silence_samples = 0
                logger.debug(
                    "barge-in triggered phase=%s rms=%d trigger=%0.0f "
                    "window_samples=%d",
                    "playback" if playing else "generation",
                    rms,
                    trigger,
                    self._recent_samples,
                )
            self._notify_speech_start()
            return

        with self._lock:
            if not self._active or generation != self._generation or not self._capturing:
                return
            self._frames.append(frame)
            self._captured_samples += samples
            if rms > self._silence_threshold:
                self._silence_samples = 0
            else:
                self._silence_samples += samples
            should_finish = (
                self._silence_samples >= int(self._silence_duration * self._sample_rate)
                or self._captured_samples >= self._max_samples
            )
            if not should_finish:
                return
            frames = list(self._frames)
            self._capturing = False
            self._processing = True

        self._transcribe_frames(frames, generation)

    def _remember_pre_roll(self, frame: Any, samples: int) -> None:
        with self._lock:
            if not self._active:
                return
            self._pre_roll.append(frame)
            self._pre_roll_samples += samples
            while (
                len(self._pre_roll) > 1
                and self._pre_roll_samples > self._pre_roll_samples_limit
            ):
                old = self._pre_roll.popleft()
                self._pre_roll_samples -= self._samples(old)

    def _notify_speech_start(self) -> None:
        try:
            self._on_speech_start()
        except Exception:
            logger.debug("barge-in speech callback failed", exc_info=True)

    def _transcribe_frames(self, frames: list[Any], generation: int) -> None:
        wav_path: str | None = None
        try:
            wav_path = self._write_frames(frames)
            result = self._transcribe_fn(wav_path, model=self._model)
            if not result.get("success"):
                transcript = ""
            else:
                transcript = str(result.get("transcript") or "").strip()
                if self._hallucination_fn and self._hallucination_fn(transcript):
                    transcript = ""
        except Exception:
            logger.debug("barge-in transcription failed", exc_info=True)
            transcript = ""
        finally:
            if wav_path is not None:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass

        with self._lock:
            current = self._active and generation == self._generation
            self._processing = False
            self._reset_capture_locked()
        if current:
            try:
                self._on_transcript(transcript)
            except Exception:
                logger.debug("barge-in transcript callback failed", exc_info=True)

    def _write_frames(self, frames: list[Any]) -> str:
        os.makedirs(self._temp_dir, exist_ok=True)
        descriptor, path = tempfile.mkstemp(
            prefix="barge_in_",
            suffix=".wav",
            dir=self._temp_dir,
        )
        os.close(descriptor)
        with wave.open(path, "wb") as output:
            output.setnchannels(CHANNELS)
            output.setsampwidth(SAMPLE_WIDTH)
            output.setframerate(self._sample_rate)
            output.writeframes(b"".join(frame.tobytes() for frame in frames))
        return path

    def _reset_capture_locked(self) -> None:
        self._pre_roll.clear()
        self._pre_roll_samples = 0
        self._capturing = False
        self._frames = []
        self._captured_samples = 0
        self._silence_samples = 0

    def _reset_detection_locked(self) -> None:
        self._ambient_rms.clear()
        self._calibration_samples = 0
        # Callers that do not provide playback state retain the old fixed-floor
        # behavior; the live TUI supplies PCMPlayer.active and gets calibration.
        self._floor_locked = self._is_playing is None
        self._quiet_floor = float(self._silence_threshold)
        self._playing_prev = False
        self._playback_seen = False
        self._samples_since_playback = int(self._sample_rate * self._PLAYBACK_REARM_SECONDS)
        self._grace_samples = 0
        self._recent_above.clear()
        self._recent_samples = 0

    def _drain_locked(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
