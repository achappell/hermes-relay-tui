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


class PCMPlayer:
    """Play signed 16-bit PCM chunks locally, with a safe buffering fallback."""

    def __init__(self, enabled: bool, output_device: int | str | None = None) -> None:
        self.enabled = enabled
        self.output_device = output_device
        self.stream: Any = None
        self.failure: Optional[str] = None

    @property
    def active(self) -> bool:
        return self.stream is not None

    def start(self, audio_format: tuple[int, int, int]) -> None:
        self.failure = None
        if not self.enabled:
            return
        sample_rate, channels, sample_width = audio_format
        if sample_width != 2:
            self.failure = f"unsupported {sample_width * 8}-bit PCM"
            return
        try:
            import sounddevice as sd

            stream_kwargs = {
                "samplerate": sample_rate,
                "channels": channels,
                "dtype": "int16",
                "latency": "low",
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
        try:
            self.stream.write(chunk)
        except Exception as exc:
            self.failure = str(exc)
            self.close()

    def close(self) -> None:
        if self.stream is None:
            return
        try:
            self.stream.stop()
        finally:
            self.stream.close()
            self.stream = None
