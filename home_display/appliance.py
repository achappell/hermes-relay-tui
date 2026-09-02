"""The appliance loop: wake phrase in, spoken answer out, display in step.

HOME-02 gave the unit ears and HOME-03 gave it a face, but nothing joined
them: the display was driven by a scripted fake and the listener had nowhere
to send a turn. This module is the join. It owns one `HermesSession`, one
wake-word listener, one audio player, and the display state channel, and it
guarantees the screen only ever claims a state the hardware is actually in.

Threads, because this is where they meet:

- The audio callback thread hands frames to the listener and never blocks.
- The listener's worker thread scores frames and, on a detection, runs the
  whole capture-and-send turn. Blocking there is correct: it is what makes a
  detection during a turn a no-op instead of a second turn.
- The asyncio loop owns the websocket, the display server, and playback
  scheduling. Everything crossing into it goes through `call_soon_threadsafe`.

Front end, not core: it may import the display server. It must not import
`app.py` — the Textual TUI is a sibling, not a dependency.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
import threading
from pathlib import Path
from typing import Any, Callable

import audio as audio_module
import config
import handsfree
from session import HermesSession

from .server import DisplayServer
from .state import DisplayState, DisplayStatePublisher

logger = logging.getLogger("hermes_relay_tui.appliance")

__all__ = ["Appliance", "display_text", "main"]

# Hermes packs the model's chain-of-thought and the answer into a single text
# frame: this marker, a fenced block, then the reply. A scrollback transcript
# can afford to show that; a kitchen display cannot. The speaker says one
# sentence while the wall would show four hundred words of deliberation.
REASONING_MARKER = "\U0001f4ad"
FENCE = "```"


def display_text(text: str) -> str:
    """The answer alone, with any reasoning preamble taken off the front.

    Only a preamble at the very start is removed, so a code fence inside a
    genuine answer is left alone. While the block is still streaming its fence
    has not closed yet and nothing is shown: the half-written thought is worse
    than a blank region for the second before the reply arrives.
    """
    if not text.startswith(REASONING_MARKER):
        return text
    opened = text.find(FENCE)
    if opened == -1:
        return ""
    closed = text.find(FENCE, opened + len(FENCE))
    if closed == -1:
        return ""
    return text[closed + len(FENCE):].strip()

# Coordinator state to what the room is told. The coordinator is the authority
# on the capture half of a turn; the event stream is the authority on the
# response half, and publishes over the top of these.
DISPLAY_FOR_COORDINATOR: dict[str, DisplayState] = {
    handsfree.IDLE: "idle",
    handsfree.CAPTURING: "listening",
    handsfree.SENDING: "thinking",
    handsfree.SPEAKING: "speaking",
}

STATUS_TEXT: dict[str, str | None] = {
    "idle": None,
    "listening": "Listening",
    "thinking": "Thinking",
    "speaking": "Speaking",
    "buffering": "Buffering",
    "disconnected": "Reconnecting to Hermes",
}

INITIAL_RECONNECT_DELAY = 1.0
MAX_RECONNECT_DELAY = 30.0

# How often the listening window is checked for expiry. Fine enough that a
# misfire clears while the user is still in the room, coarse enough to be free.
TICK_INTERVAL = 0.25


class Appliance:
    """One kitchen unit: wake word, session, audio, and the display channel."""

    def __init__(
        self,
        args: Any,
        *,
        publisher: DisplayStatePublisher | None = None,
        session: Any = None,
        player: Any = None,
        recorder: Any = None,
        server: Any = None,
        build_hands_free: Callable[..., Any] = handsfree.build_hands_free,
        reconnect_delay: float = INITIAL_RECONNECT_DELAY,
        tick_interval: float = TICK_INTERVAL,
        on_ready: Callable[[Any], Any] | None = None,
    ) -> None:
        self.args = args
        self.publisher = publisher or DisplayStatePublisher()
        self._session = session
        self._player = player
        self._recorder = recorder
        self._server = server
        self._build_hands_free = build_hands_free
        self._reconnect_delay = reconnect_delay
        self._tick_interval = tick_interval
        self._on_ready = on_ready

        self._listener: Any = None
        self._coordinator: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._response_text = ""
        self._published: tuple[Any, ...] | None = None
        self._reconnect: asyncio.Event | None = None
        self._stopping = threading.Event()
        self.info: Any = None

    # ---- display -------------------------------------------------------

    def _publish(
        self,
        state: DisplayState,
        *,
        response_text: str | None = None,
        status_text: str | None = None,
    ) -> None:
        """Publish a display state from whichever thread noticed the change."""
        if response_text is not None:
            self._response_text = response_text
        status = status_text if status_text is not None else STATUS_TEXT.get(state)
        payload = (state, self._response_text, status)
        if payload == self._published:
            return
        self._published = payload

        def _apply() -> None:
            self.publisher.publish(
                state=state, response_text=payload[1], status_text=status
            )

        loop = self._loop
        if loop is None:
            _apply()
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            _apply()
        else:
            loop.call_soon_threadsafe(_apply)

    def _on_coordinator_state(self, state: str) -> None:
        """Called on the listener thread as the capture half of a turn moves."""
        if state == handsfree.CAPTURING:
            # A new question replaces the last answer: leaving the previous
            # response on screen while listening claims a conversation that
            # has already moved on.
            self._publish("listening", response_text="")
            return
        display = DISPLAY_FOR_COORDINATOR.get(state)
        if display is not None:
            self._publish(display)

    # ---- turn ----------------------------------------------------------

    def _send(self, text: str) -> None:
        """Run one turn on the event loop, blocking the listener thread.

        Blocking is the point. The coordinator is single-flight: while this
        call is outstanding it is in SENDING, so a second detection is dropped
        rather than turned into an overlapping turn.
        """
        loop = self._loop
        if loop is None:
            raise RuntimeError("the appliance loop is not running")
        future = asyncio.run_coroutine_threadsafe(self._run_turn(text), loop)
        future.result()

    async def _run_turn(self, text: str) -> None:
        response = ""
        file_audio = bytearray()
        file_format: tuple[int, int, int] | None = None
        speaking = False
        spoke = False

        def begin_playback(fmt: tuple[int, int, int]) -> bool:
            nonlocal speaking
            nonlocal spoke
            self._player.start(fmt)
            if self._player.active:
                self._coordinator.playback_started()
                self._publish("speaking")
                speaking = True
                spoke = True
                return True
            # Audio is arriving but nothing can play it. Say so rather than
            # showing "speaking" over a silent room.
            self._publish("buffering")
            return False

        try:
            async for event in self._session.send_turn(text, stt_source="local"):
                kind = event.get("type")
                if kind == "text_delta":
                    response += str(event.get("text") or "")
                    self._publish_response(response, speaking, spoke)
                elif kind == "text_replace":
                    response = str(event.get("text") or "")
                    self._publish_response(response, speaking, spoke)
                elif kind == "audio_start":
                    begin_playback(
                        (
                            event["sample_rate"],
                            event["channels"],
                            event["sample_width"],
                        )
                    )
                elif kind == "audio_chunk":
                    if self._player.active:
                        await asyncio.to_thread(self._player.write, event["data"])
                elif kind == "audio_end":
                    await self._finish_playback()
                    speaking = False
                elif kind == "audio_file_start":
                    file_audio.clear()
                    metadata = tuple(
                        event.get(field)
                        for field in ("sample_rate", "channels", "sample_width")
                    )
                    file_format = (
                        (int(metadata[0]), int(metadata[1]), int(metadata[2]))
                        if all(value is not None for value in metadata)
                        else None
                    )
                    # Hermes streams PCM *and* sends a file copy. Do not
                    # announce a state change for the spare copy when the
                    # answer has already been spoken aloud.
                    if not spoke:
                        self._publish("buffering")
                elif kind == "audio_file_chunk":
                    file_audio.extend(event["data"])
                elif kind == "audio_file_end":
                    if event.get("data"):
                        file_audio.extend(event["data"])
                    try:
                        decoded, fmt = audio_module.read_wav(bytes(file_audio))
                    except ValueError:
                        if file_format is None:
                            # An undecodable fallback is not a failed turn. If
                            # the answer was already spoken, the spare copy is
                            # simply unused; if it was not, the room heard
                            # silence and `buffering` is what that means.
                            # `error` is reserved for the relay saying so.
                            logger.debug("undecodable audio fallback, ignoring")
                            if not spoke:
                                self._publish("buffering")
                            continue
                        decoded, fmt = bytes(file_audio), file_format
                    if begin_playback(fmt):
                        await asyncio.to_thread(self._player.write, decoded)
                        await self._finish_playback()
                        speaking = False
                elif kind == "error":
                    self._publish(
                        "error", status_text=str(event.get("error") or "Hermes error")
                    )
                elif kind == "turn_end":
                    break
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # The connection is the usual reason a turn stops mid-stream.
            # Report it as what the unit is: not talking to Hermes.
            logger.debug("appliance turn failed", exc_info=True)
            self._publish("disconnected", status_text=STATUS_TEXT["disconnected"])
            self._request_reconnect()
            raise RuntimeError("the turn ended without a reply") from error
        finally:
            await self._finish_playback()

    def _speech_detected(self) -> bool:
        """Has anyone actually started talking since the wake phrase?

        Without this the listening window expires on someone who is mid-
        sentence. With it, the window only ever cuts off a room that stayed
        silent — which is exactly what a misfire looks like.
        """
        return bool(getattr(self._recorder, "has_detected_speech", False))

    async def _expire_listening_window(self) -> None:
        """Abandon a wake that nobody followed with speech.

        The coordinator decides *when* the window is over; the capture itself
        has to be cancelled here, or the display would go back to idle while
        the microphone was still recording an empty room.
        """
        while not self._stopping.is_set():
            await asyncio.sleep(self._tick_interval)
            before = self._coordinator.state
            self._coordinator.tick()
            if before == handsfree.CAPTURING and self._coordinator.state != before:
                logger.debug("appliance listening window expired")
                with contextlib.suppress(Exception):
                    self._session.cancel_voice()

    def _publish_response(self, response: str, speaking: bool, spoke: bool) -> None:
        """Stream text into the display without lying about the audio state.

        Some gateways send the audio before the text. A reply that lands after
        playback has finished must not drag the display back to `thinking`:
        the unit is not thinking, it has already answered. In that case only
        the text changes and whatever state the unit is really in stands.
        """
        if speaking:
            state: DisplayState = "speaking"
        elif spoke:
            state = self._published[0] if self._published else "idle"
        else:
            state = "thinking"
        self._publish(state, response_text=display_text(response))

    async def _finish_playback(self) -> None:
        if self._player is None or not self._player.active:
            return
        # sounddevice's stop drains the device buffer, which can take as long
        # as the tail of the sentence. Off the loop it goes.
        await asyncio.to_thread(self._player.close)
        self._coordinator.playback_finished()

    # ---- connection ----------------------------------------------------

    def _request_reconnect(self) -> None:
        loop, event = self._loop, self._reconnect
        if loop is None or event is None:
            return
        loop.call_soon_threadsafe(event.set)

    async def _supervise(self) -> None:
        """Keep one session connected, and say so honestly when it is not."""
        delay = self._reconnect_delay
        while not self._stopping.is_set():
            self._publish("disconnected")
            try:
                await self._session.connect()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("appliance connect failed", exc_info=True)
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAX_RECONNECT_DELAY)
                continue

            delay = self._reconnect_delay
            self._publish("idle")
            # Only listen while there is somewhere for a turn to go. A wake
            # phrase the unit cannot act on must do nothing at all, not queue.
            self._listener.resume()
            try:
                await self._reconnect.wait()
            finally:
                self._reconnect.clear()
                self._listener.pause()
                with contextlib.suppress(Exception):
                    await self._session.close()

    # ---- lifecycle -----------------------------------------------------

    def _build(self) -> None:
        if self._session is None:
            self._session = HermesSession(self.args)
        if self._player is None:
            self._player = audio_module.PCMPlayer(
                enabled=not getattr(self.args, "no_play", False),
                output_device=getattr(self.args, "audio_output_device", None),
            )
        if self._recorder is None:
            from voice import create_audio_recorder

            self._recorder = create_audio_recorder()
        built = self._build_hands_free(
            self._session,
            self.args,
            on_state_change=self._on_coordinator_state,
            send=self._send,
            speech_detected=self._speech_detected,
            stop_playback=self._player.close,
        )
        if built is None:
            raise RuntimeError(
                "The appliance is a hands-free unit: enable the wake word with "
                "--wake-enabled (or wake_enabled in the config file)."
            )
        self._listener, self._coordinator = built
        if self._server is None:
            self._server = DisplayServer(
                self.publisher,
                Path(__file__).with_name("static"),
                port=getattr(self.args, "display_port", 0),
            )
        self._session.use_shared_recorder(self._recorder)

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._reconnect = asyncio.Event()
        self._build()
        self.info = await self._server.start()

        # Start the worker *before* opening the stream. The other order lets
        # frames pile into a bounded queue with nothing draining it, and the
        # entire warm-up is dropped audio — 96 frames on a first run.
        self._listener.start()
        self._listener.pause()
        self._recorder.set_frame_observer(self._listener.submit)
        await asyncio.to_thread(self._open_recorder)
        if self._on_ready is not None:
            self._on_ready(self.info)

        ticker = asyncio.create_task(self._expire_listening_window())
        try:
            await self._supervise()
        finally:
            ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticker
            await self.aclose()

    def _open_recorder(self) -> None:
        from mic import input_device_context

        with input_device_context(getattr(self.args, "mic_input_device", None)):
            self._recorder.open_for_listening()

    async def aclose(self) -> None:
        self._stopping.set()
        if self._listener is not None:
            self._listener.stop()
        if self._recorder is not None:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._recorder.shutdown)
        if self._player is not None:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._player.close)
        if self._session is not None:
            with contextlib.suppress(Exception):
                await self._session.close()
        if self._server is not None:
            with contextlib.suppress(Exception):
                await self._server.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = config.build_arg_parser()
    parser.add_argument(
        "--display-port",
        type=int,
        default=0,
        help="loopback port for the display; 0 selects an available port",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    config.ensure_default_config_file(args.config)
    if args.log_file is not None:
        args.debug = True
    config.configure_logging(debug=args.debug, log_file=args.log_file)

    def announce(info: Any) -> None:
        print(f"Home display: {info.http_url}")

    appliance = Appliance(args, on_ready=announce)

    try:
        asyncio.run(appliance.run())
    except KeyboardInterrupt:
        return 0
    except RuntimeError as error:
        print(f"{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
