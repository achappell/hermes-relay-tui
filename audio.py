"""PCM audio playback for the Hermes streaming TUI.

Ported from hermes-hybrid-tui.py's PCMPlayer, unchanged in behavior.
"""

from __future__ import annotations

from typing import Any, Optional


class PCMPlayer:
    """Play signed 16-bit PCM chunks locally, with a safe buffering fallback."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.stream: Any = None
        self.failure: Optional[str] = None

    @property
    def active(self) -> bool:
        return self.stream is not None

    def start(self, audio_format: tuple[int, int, int]) -> None:
        if not self.enabled:
            return
        sample_rate, channels, sample_width = audio_format
        if sample_width != 2:
            self.failure = f"unsupported {sample_width * 8}-bit PCM"
            return
        try:
            import sounddevice as sd

            self.stream = sd.RawOutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="int16",
                latency="low",
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
