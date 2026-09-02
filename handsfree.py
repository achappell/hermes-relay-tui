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
    "build_hands_free",
    "DEFAULT_LISTEN_TIMEOUT",
]

IDLE = "idle"
CAPTURING = "capturing"
SENDING = "sending"
SPEAKING = "speaking"

# How long to wait, after the wake phrase, for the speaker to actually start
# talking. Not a recording limit: it answers "did anyone start speaking at
# all", which is the question only hands-free capture has to ask. Confirmed at
# 8s by Amanda on 2026-09-01 — long enough to turn off a tap and turn round.
DEFAULT_LISTEN_TIMEOUT = 8.0


class HandsFreeCoordinator:
    """Wake event in, at most one session turn out."""

    def __init__(
        self,
        session: Any,
        *,
        capture: Callable[[], str],
        send: Callable[[str], Any],
        listen_timeout: float = DEFAULT_LISTEN_TIMEOUT,
        speech_detected: Callable[[], bool] | None = None,
        stop_playback: Callable[[], Any] | None = None,
        barge_in: bool = False,
        on_state_change: Callable[[str], Any] | None = None,
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
        """Enter SPEAKING, from idle or from the turn that produced the audio.

        Response audio arrives while the turn is still streaming, so SENDING is
        the normal state to enter SPEAKING from. Idle is allowed too, for audio
        the appliance plays outside a turn.
        """
        with self._lock:
            if self._state not in (IDLE, SENDING):
                return
            self._set_state(SPEAKING)

    def playback_finished(self) -> None:
        """Leave SPEAKING for IDLE — the unit is ready for the phrase again.

        Playback is the last phase of a turn, so returning to idle rather than
        to SENDING is what the room actually sees: the answer has been spoken
        and the user may speak again.
        """
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


def build_hands_free(
    session: Any,
    args: Any,
    *,
    on_state_change: Callable[[str], Any] | None = None,
    send: Callable[[str], Any] | None = None,
    speech_detected: Callable[[], bool] | None = None,
    stop_playback: Callable[[], Any] | None = None,
    _load_engine: Callable[[str | None], Any] | None = None,
):
    """Assemble the hands-free loop for a front end, or None when disabled.

    Raises wake.MissingWakeDependency when the optional extra is absent, so the
    caller can report it plainly instead of dying on an import.

    Wiring order matters. Call ``listener.start()`` *before* opening the audio
    stream. The other way round, frames pile into a bounded queue with nothing
    draining it and the entire warm-up is dropped audio - measured at 96 lost
    frames on a first run, which is roughly three seconds of the room.
    """
    if not getattr(args, "wake_enabled", False):
        return None

    import wake  # noqa: PLC0415 - keep the optional-dependency seam explicit
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
        # `session.send_turn` returns an async iterator, so a front end with an
        # event loop passes its own `send` that drives the turn there and
        # blocks until it is finished.
        send=send or session.send_turn,
        speech_detected=speech_detected,
        listen_timeout=getattr(args, "wake_listen_timeout", DEFAULT_LISTEN_TIMEOUT),
        barge_in=getattr(args, "wake_barge_in", False),
        stop_playback=stop_playback,
        on_state_change=on_state_change,
        is_hallucination=is_whisper_hallucination,
    )

    listener = wake.WakeListener(
        detector,
        on_wake=coordinator.on_wake,
        chunker=wake.FrameChunker(),
    )
    return listener, coordinator
