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
from typing import Any

from audio import PCMPlayer, read_wav
from handsfree import HandsFreeCoordinator

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

# How long Hermes may take to produce its FIRST event. This is the real
# "is the relay answering at all" question, and the only one a caller
# genuinely needs to fail fast on.
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


class TurnTimeout(Exception):
    """Raised inside `_run_turn` when Hermes stops producing events."""


class TurnRunner:
    """Owns the background event loop that drives one Hermes session."""

    def __init__(self, session: Any, *, player: PCMPlayer | None = None) -> None:
        self._session = session
        self._player = player if player is not None else PCMPlayer(True)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._pending_transcript: str | None = None
        # RLock, not Lock: `on_wake()` below synchronously calls back into
        # `_take_pending_transcript` on the same thread (via the
        # coordinator's `capture` callback), so the set+on_wake pair and the
        # take must be reentrant-safe for one thread while still
        # serializing two near-simultaneous callers on different threads.
        self._pending_transcript_lock = threading.RLock()
        self._coordinator = HandsFreeCoordinator(
            session,
            capture=self._take_pending_transcript,
            send=self._send,
        )

    @property
    def coordinator(self) -> HandsFreeCoordinator:
        return self._coordinator

    def start(self) -> None:
        """Start the background loop and connect the Hermes session."""
        if self._loop_thread is not None:
            return
        ready = threading.Event()

        def run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            ready.set()
            loop.run_forever()

        self._loop_thread = threading.Thread(
            target=run, name="puck-bridge-loop", daemon=True
        )
        self._loop_thread.start()
        ready.wait()
        asyncio.run_coroutine_threadsafe(
            self._session.connect(), self._loop
        ).result()

    def stop(self) -> None:
        """Close the Hermes session and stop the background loop."""
        loop = self._loop
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._session.close(), loop).result(
                timeout=10.0
            )
        except Exception:
            logger.debug("puck bridge session close failed", exc_info=True)
        loop.call_soon_threadsafe(loop.stop)
        thread = self._loop_thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._loop_thread = None
        self._loop = None

    def submit_transcript(self, transcript: str) -> bool:
        """Run exactly one Hermes turn for one already-transcribed utterance.

        Reuses `HandsFreeCoordinator.on_wake` unmodified: it is the same
        capture -> deliver -> send state machine the wake-word appliance
        drives, given a `capture` closure that returns text already in
        hand instead of opening a microphone. `on_wake(True)` marks a
        synthetic wake phrase so the coordinator's logging/last-wake-phrase
        bookkeeping stays meaningful without inventing new API surface.
        """
        with self._pending_transcript_lock:
            self._pending_transcript = transcript
            return self._coordinator.on_wake(True)

    def _take_pending_transcript(self) -> str:
        with self._pending_transcript_lock:
            transcript = self._pending_transcript or ""
            self._pending_transcript = None
            return transcript

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
        future = asyncio.run_coroutine_threadsafe(self._run_turn(text), loop)
        try:
            return future.result(timeout=TURN_BACKSTOP_SECONDS)
        except TurnTimeout as exc:
            # Hermes stopped producing events. `_run_turn` has already
            # logged the specifics and closed the player.
            logger.error("puck bridge turn abandoned: %s", exc)
            return False
        except TimeoutError:
            # The backstop, not the normal path -- `_run_turn` bounds itself.
            #
            # Cancel rather than merely stop waiting (deferred-work #36):
            # `future.result(timeout=...)` only ends the CALLER's wait, so
            # without this the orphaned coroutine keeps running on the
            # background loop and can still write to the shared PCMPlayer
            # behind a later turn's back -- two responses interleaving into
            # one speaker.
            future.cancel()
            logger.error(
                "puck bridge turn hit the %.0fs backstop and was cancelled; "
                "this indicates a wedge inside the turn loop, not a slow answer",
                TURN_BACKSTOP_SECONDS,
            )
            return False

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
        file_audio = bytearray()
        spoke = False
        chunks_spoken = 0
        started_at = time.monotonic()
        # Iterate manually rather than with `async for`, so each individual
        # step can carry its own deadline. `async for` can only be bounded
        # as a whole, which is precisely the mistake this replaces.
        stream = self._session.send_turn(text, stt_source="local").__aiter__()
        awaiting_first = True
        try:
            while True:
                budget = (
                    FIRST_EVENT_TIMEOUT_SECONDS
                    if awaiting_first
                    else STALL_TIMEOUT_SECONDS
                )
                try:
                    event = await asyncio.wait_for(stream.__anext__(), budget)
                except StopAsyncIteration:
                    break
                except TimeoutError:
                    raise TurnTimeout(
                        "no first event within %.0fs" % budget
                        if awaiting_first
                        else "stream stalled for %.0fs mid-response" % budget
                    ) from None
                awaiting_first = False
                kind = event.get("type")
                if kind == "audio_start":
                    audio_format = (
                        event["sample_rate"],
                        event["channels"],
                        event["sample_width"],
                    )
                    if not self._player.active:
                        self._player.start(audio_format)
                elif kind == "audio_chunk":
                    if self._player.active:
                        await self._write_audio(event["data"])
                        spoke = True
                        chunks_spoken += 1
                elif kind == "audio_file_start":
                    file_audio.clear()
                elif kind == "audio_file_chunk":
                    file_audio.extend(event["data"])
                elif kind == "audio_file_end":
                    if event.get("data"):
                        file_audio.extend(event["data"])
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
                        if not self._player.active:
                            self._player.start(fmt)
                        if self._player.active:
                            await self._write_audio(decoded)
                            spoke = True
        finally:
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
                    await asyncio.wait_for(aclose(), STREAM_CLOSE_TIMEOUT_SECONDS)
                except TimeoutError:
                    logger.warning(
                        "puck bridge: turn stream did not close within %.0fs; abandoning it",
                        STREAM_CLOSE_TIMEOUT_SECONDS,
                    )
                except Exception:  # pragma: no cover - best-effort cleanup
                    logger.debug("puck bridge: error closing turn stream", exc_info=True)
            if self._player.active:
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
        player_failure = getattr(self._player, "failure", None)
        if player_failure:
            logger.error("puck bridge playback failed: %s", player_failure)
        if not spoke:
            logger.warning("puck bridge turn completed with no audible response")
        else:
            # Say so explicitly. A successful turn used to log nothing at
            # all, so "it worked" and "it is still running" looked
            # identical in the log -- the same silent-success trap that let
            # the upload path lose three captures without complaint. The
            # happy path is exactly when you most want a line to point at.
            logger.info(
                "puck bridge turn complete: %d audio chunks spoken in %.1fs",
                chunks_spoken,
                time.monotonic() - started_at,
            )
        return True
