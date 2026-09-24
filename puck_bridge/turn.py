"""Turn runner: one transcript in, one real Hermes turn out, spoken here.

Directly constructs `handsfree.HandsFreeCoordinator` rather than calling
`handsfree.build_hands_free()`: that helper unconditionally builds a local
wake-word engine, and the Puck's own on-device wake detection already made
that decision before this transcript ever arrived. `session.py`'s
`SessionProtocol` and `handsfree.py`'s `HandsFreeCoordinator` are consumed
unchanged, matching this story's Boundaries & Constraints.

The sync-callback -> async-turn bridge below is a from-scratch,
intentionally minimal version of the same shape
`home_display/appliance.py:_send`/`_run_turn` use (a background asyncio
loop plus `asyncio.run_coroutine_threadsafe`) -- referenced for the
pattern only, per the spec's Code Map; nothing is imported from that
module.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from typing import Any, Callable

from client import TransportError
from audio import PCMPlayer, read_wav
from handsfree import (
    DEFAULT_LISTEN_TIMEOUT,
    HandsFreeCoordinator,
    is_local_stop_command,
)

from .home_admission import HOME_WAKE_ADMISSION_TIMEOUT_SECONDS
from .home_session import HOME_CLAIM_RETIRE_CALL_TIMEOUT_SECONDS
from .response import MAX_QUEUED_PCM_BYTES, ResponseStreamError

logger = logging.getLogger("hermes_relay_tui.puck_bridge.turn")

# A hung Hermes turn must not block the receiving thread (and the
# single-flight coordinator behind it) forever. But the bound has to be on
# RESPONSIVENESS, not on total duration.
#
# The previous single `SEND_TIMEOUT_SECONDS = 10.0` bounded the whole turn
# -- including streaming and playing the entire spoken answer, since
# `_run_turn` plays inline. Any real answer takes longer than 10s to speak,
# so the timeout fired on every genuine response and returned the device to
# idle mid-sentence. Observed live 2026-09-10: transcription succeeded at
# 0.99 confidence and the turn still "timed out" every time. It was not a
# hang guard; it was a guarantee of failure.
#
# Replaced by two bounds on the gaps between events, applied inside
# `_run_turn` where the stream actually is:

# How long Hermes may leave a gap before the FIRST AUDIO event. Activity,
# thinking, and tool events do not mean that the spoken response has begun;
# keep this budget until audio_start (or an audio-file fallback) arrives.
FIRST_EVENT_TIMEOUT_SECONDS = 20.0

# Maximum gap BETWEEN events once the stream has started. A healthy
# response emits audio chunks continuously, so a long silence mid-stream
# means the turn died rather than that the answer is simply long. This is
# what lets a five-minute answer succeed while a stalled one still fails.
STALL_TIMEOUT_SECONDS = 20.0

# Absolute backstop for the blocking caller. `_run_turn` self-bounds via
# the two timeouts above, so reaching this means something wedged inside
# the loop itself rather than in Hermes. Deliberately far larger than any
# plausible spoken answer -- it exists so a bug cannot wedge every future
# wake until the process restarts, not to bound normal operation.
TURN_BACKSTOP_SECONDS = 600.0


# Closing the response generator must itself be bounded -- see the call
# site. Short, because this runs on the failure path and its only job is
# to release the socket, not to drain it.
STREAM_CLOSE_TIMEOUT_SECONDS = 5.0


# Writing PCM to the output device must be bounded too. `PCMPlayer.write`
# ends in a blocking `stream.write()` on the sound device, which normally
# paces playback in real time -- but a wedged or half-closed stream blocks
# forever. The per-event timeouts above bound FETCHING events from Hermes;
# on their own they leave PROCESSING them unbounded, which is exactly where
# a turn hung for minutes on 2026-09-11 while the 20s stall timeout sat
# uselessly around the fetch. Generous, because a legitimate write blocks
# for roughly the duration of the audio it is pacing.
PLAYBACK_WRITE_TIMEOUT_SECONDS = 60.0
RECONNECT_TIMEOUT_SECONDS = 10.0
SHUTDOWN_TIMEOUT_SECONDS = 10.0

# The firmware bounds the actual microphone window to eight seconds. The
# bridge-side wait also has to cover both bounded PCM buffers: the bridge can
# hold 480 KB and the Puck's audio_http source can read ahead 300 KB. Use the
# slowest supported response rate for a conservative playback-tail budget,
# then add the status poll. This is a bridge backstop, not the user-facing
# capture limit; the firmware still decides when the microphone window closes.
MIN_RESPONSE_BYTES_PER_SECOND = 16000 * 2  # 16 kHz, 16-bit mono
PUCK_AUDIO_HTTP_BUFFER_BYTES = 300_000
FOLLOW_UP_PLAYBACK_GUARD_SECONDS = (
    (MAX_QUEUED_PCM_BYTES + PUCK_AUDIO_HTTP_BUFFER_BYTES)
    / MIN_RESPONSE_BYTES_PER_SECOND
    + 2.0
)
FOLLOW_UP_CAPTURE_WAIT_SECONDS = (
    DEFAULT_LISTEN_TIMEOUT + FOLLOW_UP_PLAYBACK_GUARD_SECONDS + 1.0
)

TRANSCRIPT_ACCEPTED = "accepted"
TRANSCRIPT_SILENT = "silent"
TRANSCRIPT_REJECTED = "rejected"


class TurnTimeout(Exception):
    """Raised inside `_run_turn` when Hermes stops producing events."""


class _OwnedPCMPlayer(PCMPlayer):
    """Bridge executor owns native teardown through actual completion."""

    def _abort_native(self, stream) -> bool:
        try:
            getattr(stream, "abort", stream.stop)()
            return True
        except Exception:
            self.failure = "audio stream abort failed"
            return False

    def _close_native(self, stream) -> None:
        with self._lock:
            if self._close_in_progress is stream:
                return
            self._close_in_progress = stream
        try:
            stream.close()
        except Exception:
            # A failed close is not a released stream. Retain it for the
            # shutdown owner's retry without exposing backend exception text.
            self.failure = "audio stream close failed"
            raise RuntimeError(self.failure) from None
        else:
            with self._lock:
                if self.stream is stream:
                    self.stream = None
        finally:
            with self._lock:
                self._close_in_progress = None

    def abort(self) -> None:
        with self._lock:
            stream = self.stream
            self._pending.clear()
            self.playing = False
            self._abort_requested.set()
            attempted = getattr(self, "_abort_attempted_stream", None)
            self._abort_attempted_stream = stream
        if stream is None:
            return
        if attempted is not stream:
            self._abort_native(stream)
        # The bridge bounds callers, not native ownership. A backend may
        # ignore abort; keep the final close behind its actual writer.
        with self._write_lock:
            with self._lock:
                if self.stream is not stream:
                    return
            self._close_native(stream)
            if self.active:
                raise RuntimeError("audio stream cleanup pending")


class TurnRunner:
    """Owns the background event loop that drives one Hermes session."""

    def __init__(
        self,
        session: Any,
        *,
        player: PCMPlayer | None = None,
        response_stream: Any | None = None,
        session_factory: Callable[[], Any] | None = None,
        home_claim_factory: Any | None = None,
        home_claim_recovery_state: Any | None = None,
        home_claim_retired: bool = False,
        home_claim_close_confirmed: bool = True,
    ) -> None:
        self._session = session
        self._session_factory = session_factory
        self._home_claim_factory = home_claim_factory
        self._home_claim_recovery_state = home_claim_recovery_state
        self._home_claim_retired = bool(home_claim_retired)
        self._home_claim_close_confirmed = bool(home_claim_close_confirmed)
        self._home_identity_rejected = False
        self._home_admission_lock = threading.Lock()
        self._turn_transport_uncertain = False
        self._turn_stage = "idle"
        self._player = player if player is not None else _OwnedPCMPlayer(True)
        # When set, the spoken answer is published here for the Puck to
        # fetch instead of being played on this host. Optional so the
        # host-playback path keeps working unchanged -- the device-playback
        # path is additive, not a replacement, until it is proven on
        # hardware.
        self._response_stream = response_stream
        # The capture this turn answers, so the response stream can be
        # matched against the device's /response?seq=N request.
        self._response_seq: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._pending_transcript: str | None = None
        self._delivery_succeeded = False
        self._follow_up_queue: deque[tuple[str, str]] = deque()
        self._follow_up_waiting = False
        # Admit the next device capture as soon as a turn is in flight. The
        # Puck cannot send that capture until its response playback/status
        # hand-off is complete, but the bridge must retain the mailbox while
        # the coordinator is still waiting for `_send()` to return.
        self._follow_up_admission = False
        self._needs_reconnect = False
        self._reconnect_task: asyncio.Task | None = None
        self._shutdown_future = None
        self._lifecycle_lock = threading.RLock()
        self._stopping = threading.Event()
        self._closed = threading.Event()
        self._shutdown_deadline = None
        self._connect_task = None
        self._turn_task = None
        self._abort_task = None
        self._player_start_task = None
        # RLock, not Lock: `on_wake()` below synchronously calls back into
        # `_take_pending_transcript` on the same thread (via the
        # coordinator's `capture` callback), so the set+on_wake pair and the
        # take must be reentrant-safe for one thread while still
        # serializing two near-simultaneous callers on different threads.
        self._pending_transcript_lock = threading.RLock()
        self._follow_up_condition = threading.Condition(self._pending_transcript_lock)
        # Initial submission is serialized, but follow-up uploads must be
        # able to wake the waiting capture callback while that initial call is
        # still blocked inside the coordinator. It is deliberately separate
        # from the condition lock so the mailbox cannot deadlock the owner.
        self._submission_lock = threading.Lock()
        self._coordinator = HandsFreeCoordinator(
            session,
            capture=self._take_pending_transcript,
            send=self._send,
            follow_up_capture=self._take_follow_up_transcript,
            follow_up_listen_timeout=DEFAULT_LISTEN_TIMEOUT,
            is_ready=self._session_is_connected,
            on_finish=self._disarm_follow_up_admission,
        )

    def _session_is_connected(self) -> bool:
        session = self._session
        if session is None:
            return False
        try:
            return bool(session.is_connected())
        except Exception:
            return False

    @property
    def coordinator(self) -> HandsFreeCoordinator:
        return self._coordinator

    def start(self, *, connect: bool = True) -> None:
        """Start the owned loop; shutdown may interrupt initial connection."""
        with self._lifecycle_lock:
            if self._stopping.is_set() or self._loop_thread is not None:
                return
            ready = threading.Event()

            def run() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                ready.set()
                try:
                    loop.run_forever()
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    # Cancellation of a to_thread wrapper does not stop its
                    # native operation. Retain this owner until workers finish.
                    loop.run_until_complete(loop.shutdown_default_executor())
                finally:
                    loop.close()
                    self._closed.set()

            self._loop_thread = threading.Thread(target=run, name="puck-bridge-loop")
            self._loop_thread.start()
            ready.wait()
            if not connect:
                return
            future = asyncio.run_coroutine_threadsafe(self._connect_initial(), self._loop)
        try:
            future.result()
        except BaseException:
            if not self._stopping.is_set():
                raise

    async def _connect_initial(self) -> None:
        if self._stopping.is_set():
            return
        self._connect_task = asyncio.current_task()
        await self._session.connect()

    def request_stop(self, deadline: float | None = None) -> None:
        """Latch admission and schedule one cleanup owner without waiting."""
        with self._lifecycle_lock:
            if self._stopping.is_set():
                return
            self._stopping.set()
            with self._follow_up_condition:
                self._follow_up_condition.notify_all()
            self._shutdown_deadline = deadline if deadline is not None else time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS
            if self._response_stream is not None:
                self._response_stream.shutdown()
            if self._loop is None:
                # Even a never-started runner owns its session.
                self._stopping.clear()
                self.start(connect=False)
                self._stopping.set()
            self._shutdown_future = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
            self._shutdown_future.add_done_callback(self._shutdown_finished)

    def stop(self, deadline: float | None = None) -> bool:
        self.request_stop(deadline)
        remaining = max(0.0, self._shutdown_deadline - time.monotonic())
        complete = self._closed.wait(remaining)
        if not complete:
            logger.warning("puck bridge shutdown cleanup pending")
        return complete

    def wait_closed(self) -> None:
        """Standalone process policy: retain ownership after the wait budget."""
        self._closed.wait()

    @staticmethod
    def _cancel_once(task) -> None:
        if task is not None and not task.done() and not task.cancelling():
            task.cancel()

    def _shutdown_finished(self, future) -> None:
        try:
            future.result()
        except BaseException as exc:
            # An unexpected cleanup failure must not certify release. Keep
            # the loop/resource owner alive and make the unresolved state plain.
            logger.warning("puck bridge shutdown cleanup unresolved (%s)", type(exc).__name__)
        else:
            self._loop.call_soon_threadsafe(self._loop.stop)

    async def _close_session(self) -> None:
        warned = False
        while True:
            try:
                await self._session.close()
                return
            except Exception as exc:
                if not warned:
                    logger.warning("puck bridge session cleanup pending (%s)", type(exc).__name__)
                    warned = True
                await asyncio.sleep(0.05)

    async def _close_player(self) -> None:
        abort = getattr(self._player, "abort", self._player.close)
        warned = False
        failed = False
        try:
            await asyncio.to_thread(abort)
        except Exception as exc:
            logger.warning("puck bridge playback cleanup pending (%s)", type(exc).__name__)
            warned = True
            failed = True
        start_task = self._player_start_task
        if start_task is not None:
            try:
                await start_task
            except Exception as exc:
                logger.warning("puck bridge playback startup failed (%s)", type(exc).__name__)
        # Retry only unresolved release, including a resource opened after an
        # earlier abort. Startup failure cannot skip this independent cleanup.
        while failed or self._player.active:
            try:
                await asyncio.to_thread(abort)
                failed = False
            except Exception as exc:
                failed = True
                if not warned:
                    logger.warning("puck bridge playback cleanup pending (%s)", type(exc).__name__)
                    warned = True
            if failed or self._player.active:
                await asyncio.sleep(0.05)

    async def _shutdown(self) -> None:
        self._abort_task = asyncio.create_task(self._close_player())
        owned = {task for task in (self._connect_task, self._turn_task, self._reconnect_task) if task is not None}
        for task in owned:
            self._cancel_once(task)
        for task in owned:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        # Session and playback cleanup progress independently. Their owners
        # remain pending after failures until actual release succeeds.
        await asyncio.gather(self._close_session(), self._abort_task)

    def set_response_seq(self, seq: int | None) -> None:
        """Tell the next turn which capture it answers.

        The device asks for a specific capture (`/response?seq=N`), so the
        stream has to know which one it is carrying or the match cannot be
        made -- without this the seq the firmware sends was never compared
        against anything.
        """
        with self._lifecycle_lock:
            if not self._stopping.is_set():
                self._response_seq = seq

    def _mark_silent(self, seq: int | None, *, reason: str) -> None:
        if self._response_stream is None:
            return
        response_seq = seq if seq is not None else self._response_seq
        self._response_stream.silent(response_seq, reason=reason)

    def _queue_follow_up_locked(
        self,
        disposition: str,
        transcript: str,
        seq: int | None,
        *,
        reason: str,
    ) -> str:
        if not (self._follow_up_waiting or self._follow_up_admission) or self._follow_up_queue:
            return TRANSCRIPT_REJECTED
        if disposition == TRANSCRIPT_SILENT:
            self._mark_silent(seq, reason=reason)
        elif disposition == TRANSCRIPT_REJECTED and self._response_stream is not None:
            response_seq = seq if seq is not None else self._response_seq
            self._response_stream.unavailable(response_seq, reason=reason)
        self._follow_up_queue.append((disposition, transcript))
        self._follow_up_condition.notify_all()
        return disposition

    def _disarm_follow_up_admission(self) -> None:
        with self._follow_up_condition:
            self._follow_up_admission = False
            self._follow_up_queue.clear()
            self._follow_up_condition.notify_all()

    def submit_transcript_outcome(
        self, transcript: str, *, seq: int | None = None
    ) -> str:
        """Admit one Puck transcript and return its transport disposition.

        An initial transcript runs through ``HandsFreeCoordinator`` and waits
        for the conversation to finish. Once that coordinator is parked in a
        bounded follow-up capture, later Puck uploads only fill its mailbox;
        the coordinator thread remains the sole owner that calls Hermes. This
        preserves one session and one send per accepted phrase without
        allowing an early or duplicate upload to become a replay.
        """
        text = (transcript or "").strip()
        if self._stopping.is_set():
            return TRANSCRIPT_REJECTED

        # A legitimate follow-up arrives while the coordinator is blocked in
        # `_take_follow_up_transcript`. Handle it before the initial-submission
        # lock; waiting for that lock here would deadlock the coordinator.
        with self._follow_up_condition:
            if self._follow_up_waiting or self._follow_up_admission:
                if not text or is_local_stop_command(text):
                    return self._queue_follow_up_locked(
                        TRANSCRIPT_SILENT,
                        "",
                        seq,
                        reason="local_stop" if text else "empty_follow_up",
                    )
                return self._queue_follow_up_locked(
                    TRANSCRIPT_ACCEPTED,
                    text,
                    seq,
                    reason="follow_up_accepted",
                )
            if self._coordinator.state != "idle":
                return TRANSCRIPT_REJECTED

        # A wake capture containing exact `stop` is local even if the session
        # is disconnected. It must not reconnect merely to decline the turn.
        if not text or is_local_stop_command(text):
            self._mark_silent(
                seq,
                reason="local_stop" if text else "empty_capture",
            )
            return TRANSCRIPT_SILENT

        # Do not queue a second initial submission. Non-blocking acquisition
        # is intentional: a caller that races an in-flight turn is rejected,
        # never held until its uncertain capture might be replayed later.
        if not self._submission_lock.acquire(blocking=False):
            return TRANSCRIPT_REJECTED
        try:
            with self._follow_up_condition:
                if self._follow_up_waiting or self._follow_up_admission:
                    return self._queue_follow_up_locked(
                        TRANSCRIPT_ACCEPTED,
                        text,
                        seq,
                        reason="follow_up_accepted",
                    )
                if self._coordinator.state != "idle":
                    return TRANSCRIPT_REJECTED
                if self._stopping.is_set():
                    return TRANSCRIPT_REJECTED
                if self._home_claim_factory is not None:
                    if (
                        self._home_identity_rejected
                        or self._home_claim_retired
                        or not self._session_is_connected()
                    ):
                        return TRANSCRIPT_REJECTED
                elif self._needs_reconnect or not self._session.is_connected():
                    if self._loop is None:
                        return TRANSCRIPT_REJECTED
                    self._needs_reconnect = True
                    future = asyncio.run_coroutine_threadsafe(
                        self._reconnect(), self._loop,
                    )
                    try:
                        if not future.result(timeout=RECONNECT_TIMEOUT_SECONDS + 1):
                            return TRANSCRIPT_REJECTED
                    except Exception as exc:
                        future.cancel()
                        logger.error(
                            "puck bridge reconnect failed: %s; question not sent",
                            type(exc).__name__,
                        )
                        return TRANSCRIPT_REJECTED
                    self._needs_reconnect = False
                    logger.info("puck bridge reconnected for a fresh question")
                self._pending_transcript = text
                self._delivery_succeeded = False

            accepted = self._coordinator.on_wake(True)
            return (
                TRANSCRIPT_ACCEPTED
                if accepted and self._delivery_succeeded
                else TRANSCRIPT_REJECTED
            )
        finally:
            self._submission_lock.release()

    def submit_transcript(self, transcript: str) -> bool:
        """Compatibility wrapper for callers that only need a boolean."""
        return self.submit_transcript_outcome(transcript) == TRANSCRIPT_ACCEPTED

    def submit_capture_silent(self, seq: int) -> str:
        """Complete an empty Puck capture without manufacturing a transcript."""
        with self._follow_up_condition:
            if self._follow_up_waiting or self._follow_up_admission:
                return self._queue_follow_up_locked(
                    TRANSCRIPT_SILENT,
                    "",
                    seq,
                    reason="empty_capture",
                )
            if self._coordinator.state != "idle":
                return TRANSCRIPT_REJECTED
        self._mark_silent(seq, reason="empty_capture")
        return TRANSCRIPT_SILENT

    def submit_capture_failure(self, seq: int) -> str:
        """End a failed Puck capture without replaying its uncertain audio."""
        with self._follow_up_condition:
            if self._follow_up_waiting or self._follow_up_admission:
                return self._queue_follow_up_locked(
                    TRANSCRIPT_REJECTED,
                    "",
                    seq,
                    reason="capture_failure",
                )
            if self._coordinator.state != "idle":
                return TRANSCRIPT_REJECTED
        if self._response_stream is not None:
            self._response_stream.unavailable(seq, reason="capture_failure")
        return TRANSCRIPT_REJECTED

    def admit_wake(self, wake_phrase: str, seq: int) -> str:
        """Authorize a physical wake before the device opens its mic."""
        if self._stopping.is_set():
            return "unavailable"
        if self._home_claim_factory is None:
            # Compatibility for older Direct firmware that still asks this
            # endpoint; current Direct builds bypass the Home-only gate.
            return "admitted"
        if self._loop is None:
            return "unavailable"
        if self._home_identity_rejected:
            return "identity_rejected"
        factory = self._home_claim_factory
        if not self._home_admission_lock.acquire(blocking=False):
            return "denied"
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._admit_home_wake(wake_phrase, seq), self._loop
            )
            try:
                return str(
                    future.result(
                        timeout=(
                            HOME_CLAIM_RETIRE_CALL_TIMEOUT_SECONDS
                            + HOME_WAKE_ADMISSION_TIMEOUT_SECONDS
                            + 1.0
                        )
                    )
                )
            except Exception as exc:
                future.cancel()
                logger.warning(
                    "Puck Home pre-capture admission failed (%s)",
                    type(exc).__name__,
                )
                return "denied"
        finally:
            self._home_admission_lock.release()

    def admit_follow_up(self, seq: int) -> str:
        """Authorize a wake-free follow-up only while its session stays live."""
        if self._stopping.is_set() or self._loop is None:
            return "unavailable"
        if not self._home_admission_lock.acquire(blocking=False):
            return "denied"
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._admit_follow_up(seq), self._loop
            )
            try:
                return str(future.result(timeout=RECONNECT_TIMEOUT_SECONDS + 1.0))
            except Exception as exc:
                future.cancel()
                logger.warning(
                    "Puck follow-up admission failed (%s)", type(exc).__name__
                )
                self._disarm_follow_up_admission()
                return "denied"
        finally:
            self._home_admission_lock.release()

    async def _admit_follow_up(self, seq: int) -> str:
        with self._follow_up_condition:
            follow_up_expected = self._follow_up_admission or self._follow_up_waiting
        if (
            self._stopping.is_set()
            or not follow_up_expected
            or self._response_seq != seq
            or self._home_identity_rejected
        ):
            self._disarm_follow_up_admission()
            return "denied"
        if self._session_is_connected() and not self._home_claim_retired:
            return "admitted"
        if self._home_claim_factory is not None:
            await self._retire_home_claim()
        else:
            self._needs_reconnect = True
        self._disarm_follow_up_admission()
        return "denied"

    async def _admit_home_wake(self, wake_phrase: str, seq: int) -> str:
        del seq  # The HTTP reply binds this result to the request sequence.
        if self._stopping.is_set():
            return "unavailable"
        if self._home_identity_rejected:
            return "identity_rejected"
        factory = self._home_claim_factory

        # The active claim admits only the wake mapping that owns it. A
        # physical phrase for a different configured mapping cannot borrow
        # this conversation handle.
        if not self._home_claim_retired and self._session_is_connected():
            mapping_id = str(getattr(self._session, "wake_mapping_id", "") or "")
            resolve_mapping = getattr(factory, "current_mapping_id", None)
            if not callable(resolve_mapping):
                return "denied"
            try:
                resolved = await resolve_mapping(wake_phrase, mapping_id)
            except Exception as exc:
                if getattr(exc, "status", None) in {401, 403}:
                    self._home_identity_rejected = True
                    return "identity_rejected"
                logger.warning(
                    "Puck Home wake mapping check failed (%s)", type(exc).__name__
                )
                return "denied"
            if self._home_claim_retired or not self._session_is_connected():
                if not self._home_claim_retired:
                    await self._retire_home_claim()
                return "denied"
            if not resolved:
                return "denied"
            if not mapping_id:
                try:
                    self._session.wake_mapping_id = str(resolved)
                    if self._home_claim_recovery_state is not None:
                        self._home_claim_recovery_state.record_active(
                            str(getattr(self._session, "conversation_handle", "")),
                            str(resolved),
                        )
                except Exception as exc:
                    logger.warning(
                        "Puck Home mapping binding could not be persisted (%s)",
                        type(exc).__name__,
                    )
                    return "denied"
            return "admitted"

        if not self._home_claim_retired:
            await self._retire_home_claim()
        elif not self._home_claim_close_confirmed:
            await self._retry_home_claim_retirement()
        if not self._home_claim_close_confirmed:
            return (
                "identity_rejected"
                if self._home_identity_rejected
                else "denied"
            )
        if factory is None:
            return "denied"
        result = await factory.admit_wake(
            wake_phrase,
            previous_handle=str(
                getattr(self._session, "conversation_handle", "")
            ),
        )
        status = str(getattr(result, "status", "denied"))
        if status == "identity_rejected":
            self._home_identity_rejected = True
            return status
        if status != "admitted":
            return "denied"
        replacement = getattr(result, "session", None)
        if replacement is None:
            return "denied"
        mapping_id = str(getattr(replacement, "wake_mapping_id", "") or "")
        if not mapping_id:
            await self._retire_replacement_home_claim(replacement)
            return "denied"
        try:
            ready = bool(replacement.is_connected())
        except Exception:
            ready = False
        if not ready:
            await self._retire_replacement_home_claim(replacement)
            return "denied"

        self._session = replacement
        self._home_claim_retired = False
        self._home_claim_close_confirmed = True
        self._home_identity_rejected = False
        self._needs_reconnect = False
        logger.info("Puck Home claim admitted for a fresh physical wake")
        return "admitted"

    async def _retire_replacement_home_claim(self, replacement: Any) -> bool:
        """Retire a granted claim that lost its socket during handoff."""
        self._session = replacement
        self._home_claim_retired = True
        self._home_claim_close_confirmed = False
        handle = str(getattr(replacement, "conversation_handle", ""))
        mapping_id = str(getattr(replacement, "wake_mapping_id", ""))
        if not self._record_home_retirement(handle, mapping_id, False):
            logger.error("Puck fresh Home claim recovery state could not be written")
            return False
        retire = getattr(replacement, "retire_uncertain_claim", None)
        confirmed = False
        if callable(retire):
            try:
                confirmed = bool(
                    await asyncio.wait_for(
                        retire(), timeout=HOME_CLAIM_RETIRE_CALL_TIMEOUT_SECONDS
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Puck fresh Home claim retirement failed (%s)",
                    type(exc).__name__,
                )
        persisted = self._record_home_retirement(handle, mapping_id, confirmed)
        self._home_claim_close_confirmed = confirmed and persisted
        if not self._home_claim_close_confirmed:
            logger.error("Puck fresh Home claim close was not confirmed; capture stays closed")
        return self._home_claim_close_confirmed

    async def _retire_home_claim(self) -> bool:
        """Attempt the Home contract's one control-only close path."""
        if self._home_claim_retired:
            return self._home_claim_close_confirmed
        self._home_claim_retired = True
        self._home_claim_close_confirmed = False
        session = self._session
        handle = str(getattr(session, "conversation_handle", ""))
        mapping_id = str(getattr(session, "wake_mapping_id", ""))
        if not self._record_home_retirement(handle, mapping_id, False):
            logger.error("Puck Home claim recovery state could not be written")
            return False
        retire = getattr(session, "retire_uncertain_claim", None)
        if retire is None:
            logger.error("Puck Home claim cannot be retired; capture stays closed")
            return False
        try:
            closed = await asyncio.wait_for(
                retire(), timeout=HOME_CLAIM_RETIRE_CALL_TIMEOUT_SECONDS
            )
        except Exception as exc:
            logger.warning(
                "Puck Home claim retirement failed (%s)", type(exc).__name__
            )
            closed = False
        confirmed = bool(closed)
        persisted = self._record_home_retirement(handle, mapping_id, confirmed)
        self._home_claim_close_confirmed = confirmed and persisted
        if not self._home_claim_close_confirmed:
            logger.error("Puck Home claim close was not confirmed; capture stays closed")
        return self._home_claim_close_confirmed

    async def _retry_home_claim_retirement(self) -> bool:
        """Retry an unconfirmed claim close only when a new physical wake arrives."""
        session = self._session
        handle = str(getattr(session, "conversation_handle", ""))
        mapping_id = str(getattr(session, "wake_mapping_id", ""))
        if not self._record_home_retirement(handle, mapping_id, False):
            logger.error("Puck Home claim recovery state could not be refreshed")
            return False
        retry = getattr(session, "retry_uncertain_claim", None)
        if not callable(retry):
            logger.error("Puck Home claim cannot retry retirement; capture stays closed")
            return False
        try:
            closed = await asyncio.wait_for(
                retry(), timeout=HOME_CLAIM_RETIRE_CALL_TIMEOUT_SECONDS
            )
        except Exception as exc:
            logger.warning(
                "Puck Home claim retirement retry failed (%s)", type(exc).__name__
            )
            closed = False
        confirmed = bool(closed)
        persisted = self._record_home_retirement(handle, mapping_id, confirmed)
        self._home_claim_close_confirmed = confirmed and persisted
        if not self._home_claim_close_confirmed:
            logger.error("Puck Home claim close remains unconfirmed; capture stays closed")
        return self._home_claim_close_confirmed

    def _record_home_retirement(
        self, handle: str, mapping_id: str, confirmed: bool
    ) -> bool:
        state = self._home_claim_recovery_state
        if state is None or not handle:
            return True
        try:
            state.record_retired(handle, mapping_id, confirmed=confirmed)
            return True
        except Exception as exc:
            logger.warning(
                "Puck Home retirement state could not be persisted (%s)",
                type(exc).__name__,
            )
            return False

    def _mark_home_admission_required(self) -> None:
        if self._response_stream is not None:
            self._response_stream.require_home_admission(self._response_seq)

    def _recover_after_uncertain_turn(self, turn_task=None) -> None:
        """Retire Home or request a fresh direct session after uncertain delivery."""
        self._needs_reconnect = True
        if self._home_claim_factory is None:
            return
        self._mark_home_admission_required()
        loop = self._loop
        if loop is None or self._stopping.is_set():
            return

        async def retire_after_turn() -> None:
            if turn_task is not None:
                try:
                    await turn_task
                except BaseException:
                    pass
            await self._retire_home_claim()

        future = asyncio.run_coroutine_threadsafe(retire_after_turn(), loop)
        try:
            future.result(timeout=RECONNECT_TIMEOUT_SECONDS + 1.0)
        except Exception as exc:
            logger.warning(
                "Puck Home retirement remains unresolved (%s)", type(exc).__name__
            )

    async def _reconnect(self) -> bool:
        if self._stopping.is_set():
            return False
        # A cancelled connect may still be closing its socket. Keep that
        # task as the owner until cleanup ends, so it cannot close a newer
        # connection behind the next question.
        previous = self._reconnect_task
        if previous is not None:
            if not previous.done():
                logger.warning("puck bridge reconnect cleanup pending; question not sent")
                return False
            if not previous.cancelled():
                previous.exception()
        deadline = time.monotonic() + RECONNECT_TIMEOUT_SECONDS

        async def bounded(operation) -> tuple[bool, Any]:
            task = asyncio.create_task(operation)
            self._reconnect_task = task
            remaining = max(0.0, deadline - time.monotonic())
            done, _ = await asyncio.wait({task}, timeout=remaining)
            if not done:
                if not task.cancelling():
                    task.cancel()
                logger.error("puck bridge reconnect timed out; question not sent")
                return False, None
            try:
                return True, task.result()
            except Exception as exc:
                logger.error(
                    "puck bridge reconnect operation failed (%s); question not sent",
                    type(exc).__name__,
                )
                return False, None

        old_session = self._session
        if self._session_factory is None:
            # Compatibility for direct TurnRunner users and focused fakes.
            # The production direct-Hermes server always supplies a factory.
            operation = getattr(old_session, "connect", None)
            if operation is None:
                return False
            ok, _ = await bounded(operation())
            return ok and self._session_is_connected()

        if old_session is not None:
            ok, _ = await bounded(old_session.close())
            if not ok:
                return False
        if self._stopping.is_set():
            return False
        try:
            replacement = self._session_factory()
        except Exception as exc:
            logger.error(
                "puck bridge could not create a fresh session (%s); question not sent",
                type(exc).__name__,
            )
            return False
        ok, _ = await bounded(replacement.connect())
        if not ok:
            return False
        try:
            ready = bool(replacement.is_connected())
        except Exception:
            ready = False
        if not ready:
            logger.error("puck bridge fresh session was not verified; question not sent")
            return False
        self._session = replacement
        logger.info("puck bridge replaced the failed session for a fresh question")
        return True

    def _take_pending_transcript(self) -> str:
        with self._follow_up_condition:
            transcript = self._pending_transcript or ""
            self._pending_transcript = None
            return transcript

    def _take_follow_up_transcript(self) -> str:
        """Wait for one firmware-bounded follow-up capture outcome."""
        deadline = time.monotonic() + FOLLOW_UP_CAPTURE_WAIT_SECONDS
        with self._follow_up_condition:
            self._follow_up_waiting = True
            try:
                while not self._follow_up_queue and not self._stopping.is_set():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        logger.info(
                            "puck bridge follow-up window expired without a capture"
                        )
                        self._follow_up_admission = False
                        return ""
                    self._follow_up_condition.wait(remaining)
                if not self._follow_up_queue:
                    self._follow_up_admission = False
                    return ""
                disposition, transcript = self._follow_up_queue.popleft()
                if disposition != TRANSCRIPT_ACCEPTED:
                    self._follow_up_admission = False
                return transcript if disposition == TRANSCRIPT_ACCEPTED else ""
            finally:
                self._follow_up_waiting = False

    def _send(self, text: str) -> bool:
        """Run one turn on the background loop, blocking the caller thread.

        Blocking is the point: the coordinator is single-flight, so while
        this call is outstanding a second upload's transcript is dropped
        rather than turned into an overlapping turn (the same rule
        `home_display/appliance.py:_send` documents for the wake-word
        appliance).
        """
        loop = self._loop
        if loop is None:
            raise RuntimeError("turn runner is not started")
        owner = {"task": None, "cancel_requested": False}

        async def run_owned():
            if owner["cancel_requested"]:
                return False
            owner["task"] = asyncio.current_task()
            self._turn_stage = "preparing"
            return await self._run_turn(text)

        def cancel_owned():
            owner["cancel_requested"] = True
            self._cancel_once(owner["task"])

        with self._lifecycle_lock:
            if self._stopping.is_set():
                return False
            self._turn_transport_uncertain = False
            with self._follow_up_condition:
                self._follow_up_admission = True
            future = asyncio.run_coroutine_threadsafe(run_owned(), loop)
        try:
            self._delivery_succeeded = bool(
                future.result(timeout=TURN_BACKSTOP_SECONDS)
            )
            if not self._delivery_succeeded:
                self._disarm_follow_up_admission()
                if self._turn_transport_uncertain or not self._session_is_connected():
                    self._recover_after_uncertain_turn(owner["task"])
            return self._delivery_succeeded
        except TurnTimeout as exc:
            self._disarm_follow_up_admission()
            if self._turn_transport_uncertain or not self._session_is_connected():
                self._recover_after_uncertain_turn(owner["task"])
            # Hermes stopped producing events. `_run_turn` has already
            # logged the specifics and closed the player.
            logger.error("puck bridge turn abandoned: %s", exc)
            return False
        except TimeoutError:
            self._disarm_follow_up_admission()
            # The backstop, not the normal path -- `_run_turn` bounds itself.
            #
            # Cancel rather than merely stop waiting (deferred-work #36):
            # `future.result(timeout=...)` only ends the CALLER's wait, so
            # without this the orphaned coroutine keeps running on the
            # background loop and can still write to the shared PCMPlayer
            # behind a later turn's back -- two responses interleaving into
            # one speaker.
            loop.call_soon_threadsafe(cancel_owned)
            if self._turn_stage == "waiting_for_hermes_event":
                self._turn_transport_uncertain = True
            if self._turn_transport_uncertain or not self._session_is_connected():
                self._recover_after_uncertain_turn(owner["task"])
            logger.error(
                "puck bridge turn hit the %.0fs backstop and was cancelled; "
                "this indicates a wedge inside the turn loop, not a slow answer",
                TURN_BACKSTOP_SECONDS,
            )
            return False

        except Exception as exc:
            self._disarm_follow_up_admission()
            if isinstance(exc, TransportError):
                self._turn_transport_uncertain = True
            if self._turn_transport_uncertain or not self._session_is_connected():
                self._recover_after_uncertain_turn(owner["task"])
            # The coordinator catches callback exceptions at DEBUG. Report
            # the failure here without exception text, which can contain
            # credentials or conversation content.
            logger.error("puck bridge turn failed: %s; not replaying", type(exc).__name__)
            return False

    async def _wait_owned(self, operation, timeout):
        """Cancel a child once, retaining its cleanup even during shutdown."""
        task = asyncio.ensure_future(operation)
        try:
            done, _ = await asyncio.wait({task}, timeout=timeout)
            if done:
                return task.result()
            if not task.cancelling():
                task.cancel()
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # A child cancellation is expected. Parent cancellation is
                # handled below and must not cancel the child a second time.
                if asyncio.current_task().cancelling():
                    raise
            raise TimeoutError
        except asyncio.CancelledError:
            if not task.done() and not task.cancelling():
                task.cancel()
            try:
                await asyncio.shield(task)
            except (asyncio.CancelledError, Exception):
                pass
            raise

    async def _start_player(self, audio_format):
        if self._stopping.is_set():
            return
        self._player_start_task = asyncio.create_task(
            asyncio.to_thread(self._player.start, audio_format)
        )
        # Cancellation stops the turn, not an in-progress native device open.
        await asyncio.shield(self._player_start_task)

    async def _write_audio(self, data: bytes) -> None:
        """Hand one PCM chunk to the player, bounded.

        `PCMPlayer.write` blocks on the sound device, which is correct --
        it is what paces playback in real time. But a wedged or half-closed
        stream blocks forever, and nothing else in this turn can time that
        out: the per-event deadlines guard fetching events from Hermes, not
        processing them. Observed 2026-09-11 as a turn that hung for
        minutes past its 20s stall budget with no log line at all, because
        the stall budget was wrapped around the wrong await.

        A timeout here aborts the turn rather than limping on: the player
        is shared across turns, so continuing to feed a stream that will
        not drain risks the next turn inheriting the same wedge.
        """
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._player.write, data),
                PLAYBACK_WRITE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            raise TurnTimeout(
                "playback stalled for %.0fs writing audio"
                % PLAYBACK_WRITE_TIMEOUT_SECONDS
            ) from None

    async def _run_turn(self, text: str) -> bool:
        """Drive one `send_turn` to completion, speaking the response here."""
        if self._stopping.is_set():
            return False
        self._turn_task = asyncio.current_task()
        file_audio = bytearray()
        spoke = False
        host_player_started = False
        chunks_spoken = 0
        audio_bytes = 0
        audio_format: tuple[int, int, int] | None = None
        first_audio_at: float | None = None
        started_at = time.monotonic()
        # Only a normal event-stream end may become `complete`; all early
        # returns and exceptions must remain visible as unavailable.
        response_outcome = "unavailable"
        response_delivery_failed = False
        # Iterate manually rather than with `async for`, so each individual
        # step can carry its own deadline. `async for` can only be bounded
        # as a whole, which is precisely the mistake this replaces.
        stream = self._session.send_turn(text, stt_source="local").__aiter__()
        awaiting_first_audio = True
        try:
            while True:
                budget = (
                    FIRST_EVENT_TIMEOUT_SECONDS
                    if awaiting_first_audio
                    else STALL_TIMEOUT_SECONDS
                )
                try:
                    self._turn_stage = "waiting_for_hermes_event"
                    event = await self._wait_owned(stream.__anext__(), budget)
                    self._turn_stage = "processing_event"
                except StopAsyncIteration:
                    break
                except TimeoutError:
                    self._turn_transport_uncertain = True
                    raise TurnTimeout(
                        "no first audio within %.0fs" % budget
                        if awaiting_first_audio
                        else "stream stalled for %.0fs mid-response" % budget
                    ) from None
                kind = event.get("type")
                if kind == "error":
                    logger.error("puck bridge turn failed: remote error; not replaying")
                    return False
                if kind in {"audio_abort", "turn_interrupted"}:
                    logger.warning(
                        "puck bridge turn ended before delivery (%s); not replaying",
                        kind,
                    )
                    return False
                if kind == "audio_start":
                    awaiting_first_audio = False
                    audio_format = (
                        event["sample_rate"],
                        event["channels"],
                        event["sample_width"],
                    )
                    if self._response_stream is not None:
                        # Publish for the Puck to fetch. Declared as early
                        # as possible: the device cannot be sent a WAV
                        # header until the format is known, and its audio
                        # reader fails a stream that goes ~30s without a
                        # successful read.
                        self._response_stream.begin(self._response_seq, audio_format)
                    else:
                        host_player_started = True
                        if not self._player.active:
                            await self._start_player(audio_format)
                elif kind == "audio_chunk":
                    if event["data"]:
                        awaiting_first_audio = False
                    if self._response_stream is not None:
                        accepted = await asyncio.to_thread(
                            self._response_stream.write,
                            event["data"],
                            seq=self._response_seq,
                        )
                        if not accepted and event["data"]:
                            raise ResponseStreamError(
                                "response stream rejected a PCM chunk"
                            )
                        if event["data"]:
                            spoke = True
                            chunks_spoken += 1
                            audio_bytes += len(event["data"])
                            if first_audio_at is None:
                                first_audio_at = time.monotonic()
                    elif self._player.active:
                        await self._write_audio(event["data"])
                        spoke = True
                        chunks_spoken += 1
                elif kind == "audio_file_start":
                    file_audio.clear()
                elif kind == "audio_file_chunk":
                    file_audio.extend(event["data"])
                    if event["data"]:
                        awaiting_first_audio = False
                elif kind == "audio_file_end":
                    if event.get("data"):
                        file_audio.extend(event["data"])
                        awaiting_first_audio = False
                    # Hermes streams PCM *and* sends a file copy of the same
                    # response. Only fall back to the file copy when
                    # nothing was actually played from the streamed path.
                    if not spoke and file_audio:
                        try:
                            decoded, fmt = read_wav(bytes(file_audio))
                        except ValueError:
                            logger.debug(
                                "puck bridge: undecodable audio fallback, ignoring"
                            )
                            continue
                        # Route the fallback the same way as streamed
                        # audio. It used to always play on the HOST, so a
                        # response delivered only as a file (no streamed
                        # chunks) came out of the Mac in --play-on-device
                        # mode -- which server.py logs as impossible ("this
                        # host stays silent") -- while the Puck waited out
                        # its format budget for a stream that never got one.
                        if self._response_stream is not None:
                            self._response_stream.begin(self._response_seq, fmt)
                            accepted = await asyncio.to_thread(
                                self._response_stream.write,
                                decoded,
                                seq=self._response_seq,
                            )
                            if not accepted:
                                raise ResponseStreamError(
                                    "response stream rejected fallback audio"
                                )
                            spoke = True
                            chunks_spoken += 1
                            audio_bytes += len(decoded)
                            if first_audio_at is None:
                                first_audio_at = time.monotonic()
                        else:
                            host_player_started = True
                            if not self._player.active:
                                await self._start_player(fmt)
                            if self._player.active:
                                await self._write_audio(decoded)
                                spoke = True
                                chunks_spoken += 1
            if self._response_stream is not None and spoke:
                response_outcome = "complete"
        except TurnTimeout:
            if self._turn_transport_uncertain and self._home_claim_factory is not None:
                self._mark_home_admission_required()
            raise
        except TransportError:
            self._turn_transport_uncertain = True
            if self._home_claim_factory is not None:
                self._mark_home_admission_required()
            raise
        except ConnectionError:
            if (
                self._turn_stage == "waiting_for_hermes_event"
                or not self._session_is_connected()
            ):
                self._turn_transport_uncertain = True
            if (
                self._turn_transport_uncertain
                and self._home_claim_factory is not None
            ):
                self._mark_home_admission_required()
            raise
        except Exception:
            if not self._session_is_connected():
                self._turn_transport_uncertain = True
            if (
                self._turn_transport_uncertain
                and self._home_claim_factory is not None
            ):
                self._mark_home_admission_required()
            raise
        finally:
            self._turn_stage = "local_delivery"
            # Publish the producer outcome before closing the generator. The
            # consumer may already be waiting on the condition, and it must
            # either drain a normal completion or stop immediately on a
            # failure.
            if self._response_stream is not None:
                try:
                    if response_outcome == "complete":
                        completed = self._response_stream.complete(
                            self._response_seq
                        )
                        if not completed:
                            response_delivery_failed = True
                    else:
                        self._response_stream.fail_delivery(
                            self._response_seq, reason="turn_failure"
                        )
                except Exception:  # pragma: no cover - best-effort cleanup
                    response_delivery_failed = True
                    logger.debug(
                        "puck bridge: error recording response outcome",
                        exc_info=True,
                    )
            # Close the generator before the player: it may still be
            # producing, and an abandoned async generator left open holds
            # the underlying websocket read alive.
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                try:
                    # BOUNDED. An unbounded await here can hang forever and
                    # swallow the very timeout that sent us into this
                    # `finally` -- closing a generator parked on a websocket
                    # read waits for that read. That turns a clean
                    # "abandoned" into total silence, which is exactly what
                    # was observed on 2026-09-11: a turn that neither
                    # completed, timed out, nor logged anything for minutes.
                    await self._wait_owned(aclose(), STREAM_CLOSE_TIMEOUT_SECONDS)
                except TimeoutError:
                    logger.warning(
                        "puck bridge: turn stream did not close within %.0fs; abandoning it",
                        STREAM_CLOSE_TIMEOUT_SECONDS,
                    )
                except Exception:  # pragma: no cover - best-effort cleanup
                    logger.debug("puck bridge: error closing turn stream", exc_info=True)
            if not self._stopping.is_set() and self._player.active:
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self._player.close),
                        PLAYBACK_WRITE_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    logger.error(
                        "puck bridge: player did not close within %.0fs",
                        PLAYBACK_WRITE_TIMEOUT_SECONDS,
                    )
        # Surface a playback failure instead of discarding it. PCMPlayer
        # records problems on `.failure` (unsupported format, device error,
        # aborted stream) and nothing here ever read it, so a turn could
        # fail to make a sound while reporting nothing at all.
        # Only meaningful when THIS turn actually used the player.
        # PCMPlayer.failure is cleared in start(), so a turn that never
        # started it -- every turn in device-playback mode, and any turn
        # whose response had no audio -- must not re-report the PREVIOUS
        # turn's failure as its own. Inspect after close: normal cleanup
        # clears `active`, but leaves the failure available here.
        if host_player_started:
            player_failure = getattr(self._player, "failure", None)
            if player_failure:
                logger.error("puck bridge playback failed: %s", player_failure)
                return False
        if response_delivery_failed or (
            self._response_stream is not None
            and self._response_stream.terminal_status == "unavailable"
        ):
            logger.warning(
                "puck bridge response was not delivered; no automatic replay"
            )
            return False
        if not spoke:
            logger.warning("puck bridge turn completed with no audible response")
            if self._response_stream is not None:
                return False
        else:
            # Say so explicitly. A successful turn used to log nothing at
            # all, so "it worked" and "it is still running" looked
            # identical in the log -- the same silent-success trap that let
            # the upload path lose three captures without complaint. The
            # happy path is exactly when you most want a line to point at.
            elapsed = time.monotonic() - started_at
            logger.info(
                "puck bridge turn complete: %d audio chunks spoken in %.1fs",
                chunks_spoken,
                elapsed,
            )
            # Say plainly when the producer is slower than real time. The
            # device plays at exactly 100%, so a source below that runs it
            # dry and the answer comes out choppy -- which on 2026-09-12
            # took an evening to diagnose by ear because nothing measured
            # it. Bytes are counted against the declared format, so this is
            # a true audio-seconds-per-wall-second ratio.
            # Measure from the FIRST AUDIO CHUNK, not from turn start.
            # Turn start includes Hermes thinking before any audio exists,
            # and counting that as "generation time" made a healthy stream
            # look like a 64-75% producer on 2026-09-12 -- which sent the
            # diagnosis toward an architecture change that was not needed.
            # audio.py's own note records the real behaviour: "379ms of
            # audio every ~470ms", i.e. near real time in fits, which a
            # 0.6s cushion covers for the TUI.
            stream_elapsed = (
                time.monotonic() - first_audio_at if first_audio_at else 0.0
            )
            if audio_format and stream_elapsed > 0 and audio_bytes:
                elapsed = stream_elapsed
                rate, chans, width = audio_format
                bps = rate * chans * width
                if bps:
                    produced = audio_bytes / bps
                    ratio = produced / elapsed
                    if ratio < 1.0:
                        logger.warning(
                            "puck bridge: TTS generated %.1fs of audio in "
                            "%.1fs (%.0f%% of real time) -- slower than "
                            "playback, so a %.1fs cushion is needed to avoid "
                            "underrun; expect choppy audio on the device",
                            produced, elapsed, ratio * 100,
                            max(0.0, produced / ratio - produced),
                        )
        return True
