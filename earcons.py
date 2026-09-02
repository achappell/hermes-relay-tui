"""Short local tones the appliance uses to say "heard you" and "working on it".

These are not responses. They never travel over the session, they never route
through the response player, and they are generated here rather than shipped as
files — two notes and an envelope do not need a binary in the repository, and
generating them keeps pitch and length adjustable without an audio editor.

The envelope matters more than the pitch. A tone that begins at full amplitude
is a click, and this module exists inside a card about the unit sounding calm.

Core module: no user-interface framework, no assumed terminal.
"""

from __future__ import annotations

import logging
import math
import struct
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["WAKE", "CAPTURE_DONE", "EarconPlayer", "render"]

WAKE = "wake"
CAPTURE_DONE = "capture_done"

SAMPLE_RATE = 24_000
CHANNELS = 1
SAMPLE_WIDTH = 2

# Quiet. This plays in a kitchen at head height, not through a PA.
AMPLITUDE = 0.22

# Long enough to round the edges off, short enough to leave a recognisable
# note in the middle of a 90ms tone.
FADE_SECONDS = 0.012

# Wake rises, capture-done falls to a single lower note. The shapes are chosen
# so the two are distinguishable from across a room without being a jingle:
# going up is a question being taken, settling down is the unit getting on
# with it.
_TONES: dict[str, tuple[tuple[float, float], ...]] = {
    WAKE: ((660.0, 0.075), (880.0, 0.095)),
    CAPTURE_DONE: ((440.0, 0.120),),
}

_cache: dict[str, bytes] = {}


def _note(frequency: float, seconds: float) -> list[float]:
    """One sine note with its edges faded to silence."""
    total = max(1, int(SAMPLE_RATE * seconds))
    fade = min(int(SAMPLE_RATE * FADE_SECONDS), total // 2)
    step = 2.0 * math.pi * frequency / SAMPLE_RATE

    values = []
    for index in range(total):
        value = math.sin(step * index)
        if fade:
            if index < fade:
                value *= index / fade
            elif index >= total - fade:
                value *= (total - 1 - index) / fade
        values.append(value)
    # Guarantee the ends are exactly silent rather than nearly so: the fade
    # ramp alone leaves a fraction of a sample at each edge.
    values[0] = 0.0
    values[-1] = 0.0
    return values


def render(name: str) -> bytes:
    """The earcon as signed 16-bit mono PCM at `SAMPLE_RATE`.

    Cached: this is called on the wake path, where the whole point is that
    something happens within 200ms of detection.
    """
    cached = _cache.get(name)
    if cached is not None:
        return cached
    if name not in _TONES:
        raise KeyError(name)

    values: list[float] = []
    for frequency, seconds in _TONES[name]:
        values.extend(_note(frequency, seconds))

    peak = 32767 * AMPLITUDE
    pcm = struct.pack(
        f"<{len(values)}h",
        *(max(-32768, min(32767, int(value * peak))) for value in values),
    )
    _cache[name] = pcm
    return pcm


def _open_output_stream(**kwargs: Any) -> Any:
    import sounddevice as sd  # noqa: PLC0415 - keep the hardware seam explicit

    stream = sd.RawOutputStream(**kwargs)
    return stream


class EarconPlayer:
    """Plays one short tone at a time on its own stream.

    Deliberately not `audio.PCMPlayer`. That player is held open across a turn
    and closed by the appliance for barge-in and end-of-turn; sharing it would
    let a courtesy chirp cut off a sentence, or a sentence cut off the chirp.
    A stream per tone costs a few milliseconds and owns nothing.
    """

    def __init__(
        self,
        enabled: bool = True,
        output_device: int | str | None = None,
        open_stream: Callable[..., Any] = _open_output_stream,
    ) -> None:
        self.enabled = enabled
        self.output_device = output_device
        self.failure: str | None = None
        self._open_stream = open_stream

    def play(self, name: str) -> None:
        """Play a tone to completion. Never raises.

        Blocking is the contract: the caller opens the microphone as soon as
        this returns, and an early return puts the chirp inside the recording.
        A failure here is logged and dropped — losing the courtesy must never
        cost the answer.
        """
        if not self.enabled:
            return
        try:
            pcm = render(name)
        except KeyError:
            logger.debug("unknown earcon %r", name)
            return

        kwargs: dict[str, Any] = {
            "samplerate": SAMPLE_RATE,
            "channels": CHANNELS,
            "dtype": "int16",
            "latency": "low",
        }
        if self.output_device is not None:
            kwargs["device"] = self.output_device

        try:
            stream = self._open_stream(**kwargs)
        except Exception as error:
            self.failure = str(error)
            logger.debug("earcon stream failed to open", exc_info=True)
            return

        try:
            stream.start()
            stream.write(pcm)
            # stop() drains the device buffer. Without it this returns while
            # the tone is still in flight and the microphone opens over it.
            stream.stop()
        except Exception as error:
            self.failure = str(error)
            logger.debug("earcon playback failed", exc_info=True)
        finally:
            try:
                stream.close()
            except Exception:
                logger.debug("closing the earcon stream failed", exc_info=True)
