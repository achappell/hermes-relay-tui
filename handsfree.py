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

# Inside the `hermes_relay_tui` tree on purpose: diagnostics.configure_logging
# attaches the debug file handler there, and a bare top-level name inherits
# none of it. This module logged into the void until 2026-09-02.
logger = logging.getLogger("hermes_relay_tui.handsfree")

__all__ = [
    "IDLE",
    "ACKNOWLEDGING",
    "CAPTURING",
    "SENDING",
    "SPEAKING",
    "HandsFreeCoordinator",
    "build_hands_free",
    "DEFAULT_LISTEN_TIMEOUT",
    "is_local_stop_command",
]

IDLE = "idle"
# The moment between hearing the phrase and opening the microphone: the unit
# has claimed the turn and is telling the room so. Short — the length of a
# tone — but a real phase, and the display must not call it listening when the
# microphone is still shut.
ACKNOWLEDGING = "acknowledging"
CAPTURING = "capturing"
SENDING = "sending"
SPEAKING = "speaking"

# How long to wait, after the wake phrase, for the speaker to actually start
# talking. Not a recording limit: it answers "did anyone start speaking at
# all", which is the question only hands-free capture has to ask. Confirmed at
# 8s by Amanda on 2026-09-01 — long enough to turn off a tap and turn round.
DEFAULT_LISTEN_TIMEOUT = 8.0


def is_local_stop_command(transcript: str) -> bool:
    return transcript.strip().casefold().rstrip(".,!?").strip() == "stop"


_is_local_stop_command = is_local_stop_command


class HandsFreeCoordinator:
    """Wake event in, one turn plus one optional follow-up out."""

    def __init__(
        self,
        session: Any,
        *,
        capture: Callable[[], str],
        send: Callable[[str], Any],
        follow_up_capture: Callable[[], str] | None = None,
        listen_timeout: float = DEFAULT_LISTEN_TIMEOUT,
        follow_up_listen_timeout: float | None = None,
        speech_detected: Callable[[], bool] | None = None,
        stop_playback: Callable[[], Any] | None = None,
        acknowledge: Callable[[], Any] | None = None,
        capture_finished: Callable[[], Any] | None = None,
        barge_in: bool = False,
        on_state_change: Callable[[str], Any] | None = None,
        route_wake: Callable[[str | None], bool] | None = None,
        is_ready: Callable[[], bool] | None = None,
        on_unavailable: Callable[[], Any] | None = None,
        is_hallucination: Callable[[str], bool] | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session = session
        self._capture = capture
        self._send = send
        self._follow_up_capture = follow_up_capture
        self._listen_timeout = listen_timeout
        self._follow_up_listen_timeout = follow_up_listen_timeout
        self._active_listen_timeout = listen_timeout
        self._speech_detected = speech_detected
        self._stop_playback = stop_playback
        self._acknowledge = acknowledge
        self._capture_finished = capture_finished
        self._barge_in = barge_in
        self._on_state_change = on_state_change
        self._route_wake = route_wake
        self._is_ready = is_ready or self._session_is_connected
        self._on_unavailable = on_unavailable
        self._is_hallucination = is_hallucination
        self._now = now
        self._state = IDLE
        self._capture_started = 0.0
        self._last_wake_phrase: str | None = None
        self._lock = threading.Lock()

    @property
    def last_wake_phrase(self) -> str | None:
        return self._last_wake_phrase

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

    def _notify(self, callback: Callable[[], Any] | None, what: str) -> None:
        """Run an acknowledgement hook, swallowing whatever it does wrong.

        These hooks make sounds. A sound is a courtesy, and a courtesy that
        fails must never cost the user their question.
        """
        if callback is None:
            return
        try:
            callback()
        except Exception:
            logger.debug("%s acknowledgement failed", what, exc_info=True)

    def _session_is_connected(self) -> bool:
        try:
            return bool(self._session.is_connected())
        except Exception:
            logger.debug("session readiness check failed", exc_info=True)
            return False

    def _report_unavailable(self) -> None:
        if self._on_unavailable is None:
            return
        try:
            self._on_unavailable()
        except Exception:
            logger.debug("hands-free unavailable callback failed", exc_info=True)

    def _ready_or_report(self, stage: str) -> bool:
        try:
            ready = bool(self._is_ready())
        except Exception:
            logger.debug("readiness callback failed %s", stage, exc_info=True)
            ready = False
        if not ready:
            self._report_unavailable()
        return ready

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

    def on_wake(self, phrase: str | bool | None = None) -> bool:
        """Handle a detection and its one optional wake-word-free follow-up."""
        if isinstance(phrase, str) and phrase.strip():
            self._last_wake_phrase = phrase.strip()
        elif phrase is True:
            self._last_wake_phrase = "hey hermes"
        else:
            self._last_wake_phrase = None
        with self._lock:
            if self._state == SPEAKING:
                if not self._barge_in:
                    return False
            elif self._state != IDLE:
                return False

        # A raw transport is not enough: a session is usable only after its
        # selected profile has completed the authorization handshake. This
        # check happens before acknowledgement or capture, so a disconnected
        # doorway stays silent and never opens its microphone.
        if not self._ready_or_report("before wake"):
            return False

        if self._route_wake is not None:
            try:
                allowed = self._route_wake(self._last_wake_phrase)
            except Exception:
                logger.debug("route_wake callback failed", exc_info=True)
                allowed = False
            if not allowed:
                return False

        if not self._ready_or_report("after wake routing"):
            return False

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

            # Claim the turn before releasing the lock. Acknowledging is a
            # busy state, so a second detection during the tone is dropped by
            # the same single-flight rule as one during a capture.
            self._set_state(ACKNOWLEDGING)

        # Blocking here is the ordering guarantee: the microphone does not
        # open until the tone has finished leaving the speaker, so the unit
        # can never record its own acknowledgement. Deliberately outside the
        # lock — this waits on hardware, and the lock guards state.
        self._notify(self._acknowledge, "wake")

        if not self._ready_or_report("before capture"):
            self._finish()
            return False

        with self._lock:
            self._begin_capture()

        try:
            transcript = self._capture()
        except Exception:
            # A misfire must be silent and cheap. Never announce a failure the
            # user did not ask for.
            logger.debug("hands-free capture failed", exc_info=True)
            self._finish()
            return False

        if _is_local_stop_command(transcript or ""):
            self._finish()
            return True

        delivered = self._deliver(transcript)
        if delivered and self._follow_up_capture is not None:
            if not self._ready_or_report("before follow-up"):
                self._finish()
                return True
            with self._lock:
                self._begin_capture(follow_up=True)
            if not self._ready_or_report("before follow-up capture"):
                self._finish()
                return True
            try:
                follow_up = self._follow_up_capture()
            except Exception:
                logger.debug("hands-free follow-up capture failed", exc_info=True)
                self._finish()
                return True
            if _is_local_stop_command(follow_up or ""):
                self._finish()
            elif not (follow_up or "").strip():
                self._finish()
            else:
                self._deliver(follow_up)
        return True

    def _begin_capture(self, *, follow_up: bool = False) -> None:
        self._active_listen_timeout = (
            self._follow_up_listen_timeout
            if follow_up and self._follow_up_listen_timeout is not None
            else self._listen_timeout
        )
        self._capture_started = self._now()
        self._set_state(CAPTURING)

    def _begin_capture_for_test(self) -> None:
        """Enter CAPTURING without running a capture, for window tests."""
        with self._lock:
            self._begin_capture()

    def _deliver(self, transcript: str) -> bool:
        text = (transcript or "").strip()
        if not text:
            self._finish()
            return False
        if self._is_hallucination is not None:
            try:
                if self._is_hallucination(text):
                    self._finish()
                    return False
            except Exception:
                logger.debug("hallucination check failed", exc_info=True)

        # Only now is there work to announce. A misfire has already been
        # acknowledged and withdrawn without this.
        self._notify(self._capture_finished, "capture")
        self._set_state(SENDING)
        delivered = True
        try:
            delivered = self._send(text) is not False
        except Exception:
            logger.debug("hands-free send failed", exc_info=True)
            delivered = False
        finally:
            self._finish()
        return delivered

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
            if self._now() - self._capture_started < self._active_listen_timeout:
                return
            self._set_state(IDLE)


def build_hands_free(
    session: Any,
    args: Any,
    *,
    on_state_change: Callable[[str], Any] | None = None,
    send: Callable[[str], Any] | None = None,
    capture: Callable[[], str] | None = None,
    follow_up_capture: Callable[[], str] | None = None,
    speech_detected: Callable[[], bool] | None = None,
    stop_playback: Callable[[], Any] | None = None,
    acknowledge: Callable[[], Any] | None = None,
    capture_finished: Callable[[], Any] | None = None,
    route_wake: Callable[[str | None], bool] | None = None,
    is_ready: Callable[[], bool] | None = None,
    on_unavailable: Callable[[], Any] | None = None,
    _load_engine: Callable[[str | None], Any] | None = None,
    _load_sherpa_engine: Callable[..., Any] | None = None,
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

    engine_name = getattr(args, "wake_engine", "openwakeword")
    wake_phrases = getattr(args, "wake_phrases", None)

    if _load_sherpa_engine is not None:
        phrases = wake_phrases or wake.DEFAULT_SHERPA_PHRASES
        engine = _load_sherpa_engine(
            phrases,
            keywords_score=getattr(args, "wake_keywords_score", 1.0),
            keywords_threshold=getattr(args, "wake_keywords_threshold", 0.25),
        )
    elif _load_engine is not None and not (engine_name == "sherpa" or wake_phrases):
        engine = _load_engine(getattr(args, "wake_model", None))
    elif engine_name == "sherpa" or wake_phrases:
        phrases = wake_phrases or wake.DEFAULT_SHERPA_PHRASES
        engine = wake.load_sherpa_engine(
            phrases,
            keywords_score=getattr(args, "wake_keywords_score", 1.0),
            keywords_threshold=getattr(args, "wake_keywords_threshold", 0.25),
        )
    else:
        engine = wake.load_openwakeword_engine(getattr(args, "wake_model", None))

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
        capture=capture or session.capture_voice,
        # `session.send_turn` returns an async iterator, so a front end with an
        # event loop passes its own `send` that drives the turn there and
        # blocks until it is finished.
        send=send or session.send_turn,
        follow_up_capture=follow_up_capture,
        follow_up_listen_timeout=getattr(args, "wake_followup_seconds", 8.0),
        speech_detected=speech_detected,
        listen_timeout=getattr(args, "wake_listen_timeout", DEFAULT_LISTEN_TIMEOUT),
        barge_in=getattr(args, "wake_barge_in", False),
        stop_playback=stop_playback,
        acknowledge=acknowledge,
        capture_finished=capture_finished,
        on_state_change=on_state_change,
        route_wake=route_wake,
        is_ready=is_ready,
        on_unavailable=on_unavailable,
        is_hallucination=is_whisper_hallucination,
    )

    listener = wake.WakeListener(
        detector,
        on_wake=coordinator.on_wake,
        chunker=wake.FrameChunker(),
    )
    return listener, coordinator
