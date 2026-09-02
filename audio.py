"""PCM audio playback for the Hermes streaming TUI.

Ported from hermes-hybrid-tui.py's PCMPlayer, unchanged in behavior.
"""

from __future__ import annotations

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
        self.stream: Any = None
        self.failure: Optional[str] = None
        self.playing = False
        self._pending = bytearray()
        self._prebuffer_bytes = 0

    @property
    def active(self) -> bool:
        return self.stream is not None

    def start(self, audio_format: tuple[int, int, int]) -> None:
        # A stream can still be open and draining: not every gateway sends
        # `audio_end`. Replacing it silently orphans it and cuts off whatever
        # was left to play.
        if self.stream is not None:
            self.close()
        self.failure = None
        self.playing = False
        self._pending.clear()
        if not self.enabled:
            return
        sample_rate, channels, sample_width = audio_format
        if sample_width != 2:
            self.failure = f"unsupported {sample_width * 8}-bit PCM"
            return
        self._prebuffer_bytes = int(
            sample_rate * channels * sample_width * self.prebuffer_seconds
        )
        try:
            import sounddevice as sd

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
            self.stream = sd.RawOutputStream(
                **stream_kwargs,
            )
            self.stream.start()
        except Exception as exc:
            self.stream = None
            self.failure = str(exc)

    def write(self, chunk: bytes) -> None:
        if self.stream is None:
            return
        if not self.playing:
            self._pending.extend(chunk)
            if len(self._pending) < self._prebuffer_bytes:
                return
            chunk = bytes(self._pending)
            self._pending.clear()
            self.playing = True
        try:
            self.stream.write(chunk)
        except Exception as exc:
            self.failure = str(exc)
            self.close()

    def close(self) -> None:
        if self.stream is None:
            return
        # A reply shorter than the cushion is still a reply. Flush it rather
        # than swallowing the whole answer in the buffer.
        if self._pending:
            tail = bytes(self._pending)
            self._pending.clear()
            self.playing = True
            try:
                self.stream.write(tail)
            except Exception as exc:
                self.failure = str(exc)
        try:
            self.stream.stop()
        finally:
            self.stream.close()
            self.stream = None
            self.playing = False
