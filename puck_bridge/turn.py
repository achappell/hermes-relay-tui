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
from typing import Any

from audio import PCMPlayer, read_wav
from handsfree import HandsFreeCoordinator

logger = logging.getLogger("hermes_relay_tui.puck_bridge.turn")

# Matches `stop()`'s own close timeout. A hung Hermes turn must not block
# the receiving thread (and the single-flight coordinator behind it)
# forever -- bounding the wait lets a wedged turn fail back to idle instead
# of wedging every later wake until process restart.
SEND_TIMEOUT_SECONDS = 10.0


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
            return future.result(timeout=SEND_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.error(
                "puck bridge turn timed out after %.0fs; returning to idle",
                SEND_TIMEOUT_SECONDS,
            )
            return False

    async def _run_turn(self, text: str) -> bool:
        """Drive one `send_turn` to completion, speaking the response here."""
        file_audio = bytearray()
        spoke = False
        try:
            async for event in self._session.send_turn(text, stt_source="local"):
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
                        await asyncio.to_thread(self._player.write, event["data"])
                        spoke = True
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
                            await asyncio.to_thread(self._player.write, decoded)
                            spoke = True
        finally:
            if self._player.active:
                await asyncio.to_thread(self._player.close)
        if not spoke:
            logger.warning("puck bridge turn completed with no audible response")
        return True
