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

import logging
import os
import re
import tempfile
import threading
import time
import wave
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # Whisper native rate
CHANNELS = 1
DTYPE = "int16"
SAMPLE_WIDTH = 2
SILENCE_RMS_THRESHOLD = 200
SILENCE_DURATION_SECONDS = 3.0
DEFAULT_STT_MODEL = "base"

_TEMP_DIR = os.path.join(tempfile.gettempdir(), "hermes_relay_tui_voice")


def _import_audio():
    import numpy as np
    import sounddevice as sd

    return sd, np


class AudioRecorder:
    """Thread-safe microphone recorder with silence-based auto-stop.

    A persistent ``sounddevice.InputStream`` is opened on first use and kept
    alive across recordings, since closing/reopening it can hang on macOS
    CoreAudio. Between recordings the stream's callback simply discards
    audio.
    """

    supports_silence_autostop = True

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stream: Any = None
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
        self._frame_observer: Any = None

    def set_frame_observer(self, observer) -> None:
        """Receive frames the recorder would otherwise discard.

        The wake-word listener subscribes here instead of opening its own
        InputStream: two input streams on one device is unreliable across
        platforms, and this stream is deliberately kept open for the process
        lifetime because reopening it can hang on macOS CoreAudio.
        """
        self._frame_observer = observer

    def open_for_listening(self) -> None:
        """Open the capture stream without starting a recording.

        Push-to-talk only ever needed the stream while recording. A wake-word
        listener needs it open the whole time it is idle, which is exactly when
        frames reach the observer.
        """
        self._ensure_stream()

    def _dispatch_frame(self, indata) -> None:
        """Hand an idle frame to the observer. Called from the audio thread."""
        if self._recording:
            return
        observer = self._frame_observer
        if observer is None:
            return
        try:
            # sounddevice recycles indata between callbacks. The listener
            # queues frames and scores them on another thread, so handing over
            # the live buffer means scoring whatever PortAudio has since
            # written into it: audio that measures loud and matches nothing.
            # The recording path above copies for the same reason.
            observer(indata.copy() if hasattr(indata, "copy") else indata)
        except Exception:
            # The audio callback must survive a broken consumer: raising here
            # would stop the stream and take recording down with it.
            logger.debug("wake frame observer failed", exc_info=True)

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
    def has_detected_speech(self) -> bool:
        """Whether the current recording has heard anyone speak yet.

        Hands-free capture is the only caller: it has to tell "the user is
        still thinking about what to ask" apart from "the wake word misfired
        and nobody is there".
        """
        return self._recording and self._has_spoken

    def _ensure_stream(self) -> None:
        if self._stream is not None:
            return

        sd, np = _import_audio()

        def _callback(indata, frames, time_info, status):  # noqa: ARG001
            if status:
                logger.debug("sounddevice status: %s", status)
            if not self._recording:
                self._dispatch_frame(indata)
                return
            self._frames.append(indata.copy())

            rms = int(np.sqrt(np.mean(indata.astype(np.float64) ** 2)))
            self._current_rms = rms
            self._peak_rms = max(self._peak_rms, rms)

            if self._on_silence_stop is None:
                return

            now = time.monotonic()
            elapsed = now - self._start_time

            if rms > self._silence_threshold:
                self._dip_start = 0.0
                if self._speech_start == 0.0:
                    self._speech_start = now
                elif not self._has_spoken and now - self._speech_start >= self._min_speech_duration:
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
                with self._lock:
                    cb = self._on_silence_stop
                    self._on_silence_stop = None
                if cb:
                    def _safe_cb():
                        try:
                            cb()
                        except Exception:
                            logger.exception("Silence callback failed")

                    threading.Thread(target=_safe_cb, daemon=True).start()

        stream = None
        try:
            stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=CHANNELS,
                dtype=DTYPE,
                callback=_callback,
            )
            stream.start()
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
        self._stream = stream

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
        if self._stream is None:
            return
        stream = self._stream
        self._stream = None

        def _do_close():
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        t = threading.Thread(target=_do_close, daemon=True)
        t.start()
        deadline = time.monotonic() + timeout
        while t.is_alive() and time.monotonic() < deadline:
            t.join(timeout=0.1)

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
        silence_duration: float = 3.0,
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

    def capture(self) -> str:
        """Record one utterance, return its transcript, or "" for silence."""
        self._load()
        finished = threading.Event()

        try:
            self._recorder.start(on_silence_stop=finished.set)
            finished.wait(max(self.max_seconds + 2.0, 5.0))
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
