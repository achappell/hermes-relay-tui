"""PCM audio playback for the Hermes streaming TUI.

Ported from hermes-hybrid-tui.py's PCMPlayer, unchanged in behavior.
"""

from __future__ import annotations

import threading
import time
import wave
from io import BytesIO
from pathlib import Path
from typing import Any, Optional


def audio_path(base: Optional[Path], index: int, turn_id: str) -> Path:
    """Pick the WAV path for a turn, matching hermes-hybrid-tui.py's _audio_path."""
    if base is None:
        return Path.cwd() / f"hybrid-tui-{turn_id}.wav"
    if index == 0:
        return base
    return base.with_name(f"{base.stem}-{index}{base.suffix or '.wav'}")


def write_wav(path: Path, audio: bytes, audio_format: tuple[int, int, int]) -> None:
    """Write raw PCM out as a WAV file, matching hermes-hybrid-tui.py's _write_wav."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate, channels, sample_width = audio_format
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(sample_width)
        output.setframerate(sample_rate)
        output.writeframes(audio)


def read_wav(data: bytes) -> tuple[bytes, tuple[int, int, int]]:
    """Extract PCM and its format from a complete WAV fallback payload."""
    try:
        with wave.open(BytesIO(data), "rb") as source:
            audio_format = (
                source.getframerate(),
                source.getnchannels(),
                source.getsampwidth(),
            )
            return source.readframes(source.getnframes()), audio_format
    except (EOFError, OSError, wave.Error) as exc:
        raise ValueError("invalid WAV audio fallback") from exc


def audio_device_list() -> list[dict[str, Any]]:
    """Return the local PortAudio devices with their I/O capabilities."""
    import sounddevice as sd

    devices = sd.query_devices()
    if isinstance(devices, dict):
        devices = [devices]
    return [
        {
            "index": index,
            "name": str(device.get("name", f"device {index}")),
            "inputs": int(device.get("max_input_channels", 0)),
            "outputs": int(device.get("max_output_channels", 0)),
        }
        for index, device in enumerate(devices)
    ]


# Response audio is generated as it is spoken, so it arrives in fits. Measured
# against a live gateway: 14 of 19 chunks arrived slower than they play — 379ms
# of audio every ~470ms. Without a cushion the device runs dry between chunks,
# and every underrun is an audible pop. This is the cushion, in seconds; it is
# added to the delay before the first word is heard, so it buys smoothness at
# a price and should stay small.
DEFAULT_PREBUFFER_SECONDS = 0.6
AUDIO_TEARDOWN_TIMEOUT = 3.0


def _call_with_timeout(
    operation,
    timeout: float,
    *,
    on_complete=None,
) -> tuple[bool, Exception | None]:
    """Run a native audio operation without making its caller unkillable."""
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
        name="hermes-audio-teardown",
        daemon=True,
    ).start()
    if not finished.wait(timeout):
        return False, None
    return True, errors[0] if errors else None


class PCMPlayer:
    """Play signed 16-bit PCM chunks locally, with a safe buffering fallback."""

    def __init__(
        self,
        enabled: bool,
        output_device: int | str | None = None,
        prebuffer_seconds: float = DEFAULT_PREBUFFER_SECONDS,
    ) -> None:
        self.enabled = enabled
        self.output_device = output_device
        self.prebuffer_seconds = max(0.0, float(prebuffer_seconds))
        # Writes and interrupt teardown both run in the asyncio executor.
        # Never let PortAudio observe a write concurrent with stop/close.
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._abort_requested = threading.Event()
        self.stream: Any = None
        self._close_in_progress: Any = None
        self._poisoned = False
        self.failure: Optional[str] = None
        self.playing = False
        self._pending = bytearray()
        self._prebuffer_bytes = 0
        self._bytes_per_second = 0.0
        self._playback_clock_origin: float | None = None
        self._playback_clock_started_at: float | None = None
        self._playback_clock_last_raw_position = 0.0
        self._scheduled_audio_seconds = 0.0
        self._playback_position = 0.0

    @property
    def active(self) -> bool:
        with self._lock:
            return self.stream is not None

    @property
    def playback_position(self) -> float:
        """Return the rendered position without outrunning queued PCM."""
        with self._lock:
            self._advance_playback_clock_locked(self.stream)
            return self._playback_position

    def playback_snapshot(self) -> dict[str, Any]:
        """Return content-free state for diagnosing the playback timeline."""
        with self._lock:
            self._advance_playback_clock_locked(self.stream)
            pending_audio = (
                len(self._pending) / self._bytes_per_second
                if self._bytes_per_second > 0
                else 0.0
            )
            queued_audio = max(
                self._scheduled_audio_seconds - self._playback_position,
                0.0,
            ) + pending_audio
            return {
                "active": self.stream is not None,
                "playing": self.playing,
                "playback_position": self._playback_position,
                "scheduled_audio": self._scheduled_audio_seconds,
                "pending_audio": pending_audio,
                "queued_audio": queued_audio,
            }

    def _begin_playback_clock(self, stream: Any) -> None:
        self._playback_clock_started_at = time.monotonic()
        self._playback_clock_last_raw_position = 0.0
        try:
            self._playback_clock_origin = float(stream.time)
        except (AttributeError, TypeError, ValueError):
            self._playback_clock_origin = None

    def _advance_playback_clock_locked(self, stream: Any) -> None:
        """Advance only while there is PCM already handed to the device.

        PortAudio's stream clock continues during a network starvation gap,
        unlike AVAudioPlayerNode's rendered sample time on the iOS client.
        Treat the stream clock as a rate source, but cap each advance at the
        duration of audio that has actually been written. Calling this before
        a new write consumes the old queue first; calling it after the write
        lets a native stream clock that moved during the write contribute.
        """
        if stream is None:
            return

        raw_position: float | None = None
        if self._playback_clock_origin is not None:
            try:
                raw_position = float(stream.time) - self._playback_clock_origin
            except (AttributeError, TypeError, ValueError):
                raw_position = None
        if raw_position is None and self._playback_clock_started_at is not None:
            raw_position = time.monotonic() - self._playback_clock_started_at
        if raw_position is None:
            return

        raw_position = max(raw_position, self._playback_clock_last_raw_position, 0.0)
        elapsed = raw_position - self._playback_clock_last_raw_position
        available = max(self._scheduled_audio_seconds - self._playback_position, 0.0)
        self._playback_position += min(elapsed, available)
        self._playback_clock_last_raw_position = raw_position

    def _record_written_audio(self, stream: Any, byte_count: int) -> None:
        with self._lock:
            if self.stream is not stream or self._bytes_per_second <= 0:
                return
            self._scheduled_audio_seconds += byte_count / self._bytes_per_second
            self._advance_playback_clock_locked(stream)

    def start(self, audio_format: tuple[int, int, int]) -> None:
        with self._lock:
            if self._poisoned:
                return
        if self.active:
            self.close()
            with self._lock:
                if self._poisoned:
                    return
        cleanup_stream = None
        with self._lock:
            self.failure = None
            self.playing = False
            self._pending.clear()
            self._bytes_per_second = 0.0
            self._abort_requested.clear()
            self._playback_clock_origin = None
            self._playback_clock_started_at = None
            self._playback_clock_last_raw_position = 0.0
            self._scheduled_audio_seconds = 0.0
            self._playback_position = 0.0
            if not self.enabled:
                return
            sample_rate, channels, sample_width = audio_format
            if sample_width != 2:
                self.failure = f"unsupported {sample_width * 8}-bit PCM"
                return
            self._prebuffer_bytes = int(
                sample_rate * channels * sample_width * self.prebuffer_seconds
            )
            self._bytes_per_second = sample_rate * channels * sample_width
            stream_kwargs = {
                "samplerate": sample_rate,
                "channels": channels,
                "dtype": "int16",
                # Deliberately not "low": that asks PortAudio for the smallest
                # possible buffer, which is the wrong request for audio
                # arriving off a network in irregular chunks.
                "latency": "high",
            }
            if self.output_device is not None:
                stream_kwargs["device"] = self.output_device
            stream = None
            try:
                import sounddevice as sd

                stream = sd.RawOutputStream(**stream_kwargs)
                self.stream = stream
                stream.start()
            except Exception as exc:
                self.failure = str(exc)
                if self.stream is stream:
                    self.stream = None
                self._abort_requested.set()
                if stream is not None:
                    cleanup_stream = stream
        if cleanup_stream is not None:
            self._abort_and_close(cleanup_stream)

    def write(self, chunk: bytes) -> None:
        with self._lock:
            stream = self.stream
            if (
                stream is None
                or self._abort_requested.is_set()
                or self._poisoned
                or self._close_in_progress is stream
            ):
                return
            if not self.playing:
                self._pending.extend(chunk)
                if len(self._pending) < self._prebuffer_bytes:
                    return
                chunk = bytes(self._pending)
                self._pending.clear()
                self.playing = True
                self._begin_playback_clock(stream)
        write_error: Exception | None = None
        with self._write_lock:
            with self._lock:
                if (
                    self.stream is not stream
                    or self._abort_requested.is_set()
                    or self._poisoned
                    or self._close_in_progress is stream
                ):
                    return
            try:
                with self._lock:
                    self._advance_playback_clock_locked(stream)
                stream.write(chunk)
                self._record_written_audio(stream, len(chunk))
            except Exception as exc:
                write_error = exc
        if write_error is not None:
            self.failure = str(write_error)
            self.abort()

    def close(self) -> None:
        with self._lock:
            stream = self.stream
            if stream is None:
                return
        # Wait for a writer before draining and closing. Abort does not take
        # this lock until it has called the backend's interrupt operation, so
        # it can still break a blocking write.
        with self._write_lock:
            with self._lock:
                if (
                    self.stream is not stream
                    or self._poisoned
                    or self._close_in_progress is stream
                ):
                    self.playing = False
                    return
                aborted = self._abort_requested.is_set()
                tail = bytes(self._pending) if self._pending and not aborted else None
                self._pending.clear()
                if tail:
                    self.playing = True
                    if self._playback_clock_started_at is None:
                        self._begin_playback_clock(stream)
            if tail:
                try:
                    with self._lock:
                        self._advance_playback_clock_locked(stream)
                    stream.write(tail)
                    self._record_written_audio(stream, len(tail))
                except Exception as exc:
                    self.failure = str(exc)
            with self._lock:
                aborted = self._abort_requested.is_set()
            if not aborted:
                try:
                    stream.stop()
                except Exception as exc:
                    self.failure = str(exc)
            self._close_native(stream)
            with self._lock:
                self.playing = False

    def abort(self) -> None:
        """Discard pending audio and release the device without draining it."""
        with self._lock:
            stream = self.stream
            self._pending.clear()
            self.playing = False
            self._abort_requested.set()
        if stream is None:
            return

        # This deliberately happens before taking _write_lock: PortAudio's
        # abort is what must wake a writer blocked inside stream.write().
        with self._lock:
            if self._close_in_progress is stream:
                return
        if not self._abort_native(stream):
            return
        if not self._write_lock.acquire(timeout=AUDIO_TEARDOWN_TIMEOUT):
            self.failure = "audio write did not stop during abort"
            return
        try:
            with self._lock:
                if self.stream is not stream:
                    return
            self._close_native(stream)
            with self._lock:
                self.playing = False
        finally:
            self._write_lock.release()

    def _abort_native(self, stream: Any) -> bool:
        try:
            operation = getattr(stream, "abort", None)
            if not callable(operation):
                operation = stream.stop
            completed, error = _call_with_timeout(
                operation,
                AUDIO_TEARDOWN_TIMEOUT,
            )
        except Exception as exc:
            self.failure = str(exc)
            return False
        if error is not None:
            self.failure = str(error)
            return False
        if not completed:
            self.failure = "audio stream abort timed out"
            with self._lock:
                self._poisoned = True
            return False
        return True

    def _close_native(self, stream: Any) -> None:
        with self._lock:
            if self._close_in_progress is stream:
                return
            self._close_in_progress = stream

        def finished(error: Exception | None) -> None:
            with self._lock:
                if error is not None:
                    self.failure = str(error)
                if self._close_in_progress is stream:
                    self._close_in_progress = None
                if self.stream is stream:
                    self.stream = None

        completed, error = _call_with_timeout(
            stream.close,
            AUDIO_TEARDOWN_TIMEOUT,
            on_complete=finished,
        )
        if error is not None:
            self.failure = str(error)
            with self._lock:
                self._poisoned = True
        elif not completed:
            with self._lock:
                if self._close_in_progress is stream:
                    self._poisoned = True
                    self.failure = "audio stream close timed out"

    def _abort_and_close(self, stream: Any) -> None:
        if self._abort_native(stream):
            self._close_native(stream)
