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
import math
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any, Callable

import audio as audio_module
import config
import diagnostics
import earcons as earcons_module
import handsfree
from session import HermesSession
from timing import (
    SpeechTiming,
    duration_visible_text,
    fallback_visible_text,
    longest_valid_prefix,
    visible_text,
)

from .server import DisplayServer, load_tls_context
from .state import (
    DisplayCapabilities,
    DisplayPrompt,
    DisplayState,
    DisplayStatePublisher,
    MAX_DISPLAY_WAKE_PHRASE_LENGTH,
    MAX_DISPLAY_WAKE_PHRASES,
    PromptOption,
)

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
    handsfree.ACKNOWLEDGING: "heard",
    handsfree.CAPTURING: "listening",
    handsfree.SENDING: "thinking",
    handsfree.SPEAKING: "speaking",
}

STATUS_TEXT: dict[str, str | None] = {
    "idle": None,
    "heard": "Heard you",
    "listening": "Listening",
    "thinking": "Thinking",
    "speaking": "Speaking",
    "buffering": "Buffering",
    "disconnected": "Reconnecting to Hermes",
    "prompt": None,
}

# ---- gateway notice detection ------------------------------------------
#
# The Hermes gateway injects operational notices (e.g. "no home channel set")
# as plain text_final frames — identical on the wire to a real AI response.
# We detect known notices by text markers and convert them to a structured
# DisplayPrompt overlay rather than rendering them as response text.
#
# When Hermes adds a typed `notice` wire frame, swap this heuristic for a
# frame-type check; the rest of the overlay stack is unchanged.

_NOTICE_MARKERS = (
    "No home channel is set",
    "/sethome",
    "\U0001f4ec",  # 📬
)


def _classify_gateway_notice(text: str) -> DisplayPrompt | None:
    """Return a DisplayPrompt if text is a known gateway notice, else None.

    The prompt is a human-friendly paraphrase — the raw gateway text is never
    shown on the display.
    """
    t = text.strip()
    if not any(marker in t for marker in _NOTICE_MARKERS):
        return None
    return DisplayPrompt(
        kind="notice",
        title="Setup needed",
        body="Set this display as the home channel for this profile?",
        options=(
            PromptOption(id="yes", label="Set home"),
            PromptOption(id="no", label="Skip"),
        ),
        action_id="sethome",
        timeout_seconds=30,
    )


def _classify_prompt_request(event: dict) -> DisplayPrompt | None:
    """Convert a typed gateway prompt_request event to a DisplayPrompt.

    Returns None for unrecognised or malformed events.
    The action_id is the gateway's prompt_id so the appliance can route the
    response back via send_prompt_response when that API is available.
    """
    kind = str(event.get("kind") or "")
    prompt_id = str(event.get("prompt_id") or event.get("id") or "prompt")
    question = str(event.get("question") or event.get("text") or "")

    if kind == "approval":
        return DisplayPrompt(
            kind="approval",
            title="Permission needed",
            body=question or "Hermes is asking for your approval.",
            options=(
                PromptOption(id="yes", label="Approve"),
                PromptOption(id="no", label="Deny"),
            ),
            action_id=prompt_id,
        )
    if kind == "confirm":
        return DisplayPrompt(
            kind="confirm",
            title="Confirm",
            body=question or "Are you sure?",
            options=(
                PromptOption(id="yes", label="Yes"),
                PromptOption(id="no", label="No"),
            ),
            action_id=prompt_id,
        )
    if kind == "clarify":
        raw_options = event.get("options") or []
        options = tuple(
            PromptOption(id=str(o.get("id", i)), label=str(o.get("label", o.get("id", i))))
            for i, o in enumerate(raw_options)
            if isinstance(o, dict)
        )
        if not options:
            options = (PromptOption(id="ok", label="OK"),)
        return DisplayPrompt(
            kind="clarify",
            title="Clarification needed",
            body=question or "Please choose an option.",
            options=options,
            action_id=prompt_id,
        )
    return None


# How long the unit waits, after you stop talking, before deciding you have
# finished. The terminal client waits 3s, which is fine when you pressed a key
# on purpose and can watch the screen. Standing in a kitchen, three seconds of
# nothing happening reads as broken. Short enough to feel immediate, long
# enough to survive the pause in the middle of a sentence.
HANDS_FREE_SILENCE_DURATION = 1.2

INITIAL_RECONNECT_DELAY = 1.0
MAX_RECONNECT_DELAY = 30.0

# How often the listening window is checked for expiry. Fine enough that a
# misfire clears while the user is still in the room, coarse enough to be free.
TICK_INTERVAL = 0.25

# Maximum time to wait for a shutdown task, stream teardown, or connection close
# before returning control so interpreter shutdown is never stranded.
SHUTDOWN_TASK_TIMEOUT = 3.0


class Appliance:
    """One kitchen unit: wake word, session, audio, and the display channel."""

    def __init__(
        self,
        args: Any,
        *,
        publisher: DisplayStatePublisher | None = None,
        session: Any = None,
        sessions: dict[str, Any] | None = None,
        session_factory: Callable[[config.HouseholdProfile], Any] | None = None,
        profiles: list[config.HouseholdProfile] | None = None,
        player: Any = None,
        earcons: Any = None,
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
        self._session_factory = session_factory
        self._sessions: dict[str, Any] = dict(sessions) if sessions is not None else {}
        self._player = player
        self._earcons = earcons
        self._recorder = recorder
        self._server = server
        self._build_hands_free = build_hands_free
        self._reconnect_delay = reconnect_delay
        self._tick_interval = tick_interval
        self._on_ready = on_ready

        if profiles is not None:
            self._profiles = list(profiles)
        else:
            config_path = getattr(self.args, "config", None)
            cfg = config.load_config_file(config_path) if config_path else {}
            self._profiles = config.load_household_profiles(cfg, self.args)

        if not self._profiles:
            self._profiles = config.load_household_profiles({}, self.args)

        self._active_profile = self._profiles[0]
        if session is not None:
            self._sessions[self._active_profile.name] = session

        self._phrase_to_profile: dict[str, config.HouseholdProfile | None] = {}
        for prof in self._profiles:
            for phrase in prof.wake_phrases:
                norm = phrase.strip().casefold()
                if not norm:
                    continue
                if norm in self._phrase_to_profile:
                    if self._phrase_to_profile[norm] != prof:
                        self._phrase_to_profile[norm] = None
                else:
                    self._phrase_to_profile[norm] = prof

        all_phrases: list[str] = []
        for prof in self._profiles:
            for p in prof.wake_phrases:
                p_clean = p.strip()
                if p_clean and p_clean not in all_phrases:
                    all_phrases.append(p_clean)
        if all_phrases:
            if not getattr(self.args, "wake_phrases", None) or len(self._profiles) > 1:
                self.args.wake_phrases = ", ".join(all_phrases)

        self._listener: Any = None
        self._coordinator: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._response_text = ""
        self._published: tuple[Any, ...] | None = None
        self._reconnect: asyncio.Event | None = None
        self._connected = False
        self._is_listening: bool | None = None
        self._stopping = threading.Event()
        self._turn_future = None
        self._browser_turn_task: asyncio.Task[Any] | None = None
        self._follow_up_capturing = False
        self.info: Any = None
        self._shutting_down = False
        self._cleanup_tasks: set[asyncio.Task[Any]] = set()
        self._wake_opening = False
        self._supervisor_task: asyncio.Task[None] | None = None
        self._signals_installed: list[signal.Signals] = []
        self._sigint_count = 0
        self._pending_prompt_action_id: str | None = None

    @property
    def active_profile(self) -> config.HouseholdProfile:
        return self._active_profile

    @property
    def profiles(self) -> list[config.HouseholdProfile]:
        return list(self._profiles)

    # ---- display -------------------------------------------------------

    def _browser_capabilities(self) -> DisplayCapabilities:
        """Return browser-safe, non-secret capabilities for the active session."""
        raw_phrases = getattr(self._active_profile, "wake_phrases", ()) or ()
        phrases = tuple(
            phrase.strip()
            for phrase in raw_phrases
            if isinstance(phrase, str) and phrase.strip()
        )
        valid_phrases = (
            0 < len(phrases) <= MAX_DISPLAY_WAKE_PHRASES
            and len({phrase.casefold() for phrase in phrases}) == len(phrases)
            and all(len(phrase) <= MAX_DISPLAY_WAKE_PHRASE_LENGTH for phrase in phrases)
        )
        if not valid_phrases:
            return DisplayCapabilities(features=("browser_voice",))

        def configured_seconds(name: str) -> float:
            try:
                seconds = float(getattr(self.args, name, 8.0))
            except (TypeError, ValueError, OverflowError):
                return 8.0
            return seconds if math.isfinite(seconds) and seconds > 0 else 8.0

        return DisplayCapabilities(
            features=("browser_voice", "browser_hands_free"),
            wake_phrases=phrases,
            wake_listen_seconds=configured_seconds("wake_listen_timeout"),
            wake_followup_seconds=configured_seconds("wake_followup_seconds"),
        )

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
        account = self._active_profile.display_name if self._active_profile else None
        capabilities = (
            self._browser_capabilities()
            if getattr(self.args, "browser_voice", False) and self._connected
            else None
        )
        payload = (state, self._response_text, status, account, capabilities)
        if payload == self._published:
            return
        self._published = payload

        def _apply() -> None:
            try:
                self.publisher.publish(
                    state=state,
                    response_text=payload[1],
                    status_text=status,
                    account=account,
                    capabilities=capabilities,
                )
            except TypeError:
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

    def _publish_prompt(self, prompt: "DisplayPrompt") -> None:
        """Publish a prompt overlay, clearing any accumulated response text.

        Called from whichever thread detected the notice or prompt_request.
        The prompt state resets _response_text so a stale answer cannot bleed
        through if the overlay appears mid-turn (unlikely but possible).
        """
        self._response_text = ""
        self._published = ("prompt", "", None)

        def _apply() -> None:
            self.publisher.publish(state="prompt", prompt=prompt)

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

    async def _on_action(self, action_id: str, choice: str) -> None:
        """Dispatch a prompt response from the display's /action endpoint.

        action_id -- the opaque token set in DisplayPrompt.action_id
        choice    -- the option id the user tapped (e.g. "yes" or "no")

        Dismiss the overlay first, then act. This keeps the display
        responsive even if the follow-up turn takes a moment to start.
        """
        logger.debug("appliance action action_id=%s choice=%s", action_id, choice)
        self._pending_prompt_action_id = None
        self._publish("idle", response_text="")

        if action_id == "sethome":
            if choice == "yes":
                # Send /sethome as a normal turn so the gateway registers
                # this session as the home channel.
                logger.debug("appliance sending /sethome turn")
                await asyncio.to_thread(self._send, "/sethome")
            # choice == "no": already dismissed to idle, nothing else to do.
            return

        # Generic prompt_request response — route to the session if present.
        # When full prompt_request support lands, call the session's
        # send_prompt_response() here keyed on action_id.
        logger.debug(
            "appliance unhandled action action_id=%s choice=%s", action_id, choice
        )

    async def _on_browser_voice_turn(self, text: str) -> None:
        """Run one browser-recognized turn without opening local audio devices."""
        normalized = text.strip()
        if not normalized or len(normalized) > 4000:
            return
        if self._stopping.is_set() or not self._connected:
            return
        if self._browser_turn_task is not None and not self._browser_turn_task.done():
            self._publish(
                "error",
                response_text="",
                status_text="A response is already in progress",
            )
            return

        self._browser_turn_task = asyncio.current_task()
        try:
            await self._run_browser_turn(normalized)
        finally:
            if self._browser_turn_task is asyncio.current_task():
                self._browser_turn_task = None

    async def _run_browser_turn(self, text: str) -> bool:
        """Forward browser text to Hermes and stream response PCM to the kiosk."""
        server = self._server
        if server is None:
            self._publish("error", response_text="", status_text="Display server unavailable")
            return False

        response = ""
        audio_active = False
        file_audio = bytearray()
        file_format: tuple[int, int, int] | None = None
        file_audio_active = False
        completed = False
        turn_id = "browser-turn"
        self._publish("thinking", response_text="")

        def publish_response(state: DisplayState = "thinking") -> None:
            self._publish(state, response_text=display_text(response))

        async def abort_audio(reason: str) -> None:
            nonlocal audio_active
            if audio_active:
                with contextlib.suppress(Exception):
                    await server.send_audio_abort(turn_id=turn_id, reason=reason)
                audio_active = False

        def publish_terminal_error(status_text: str) -> None:
            self._connected = False
            self._publish("error", response_text="", status_text=status_text)
            self._set_listening()
            self._request_reconnect()

        try:
            events = self._session.send_turn(text, stt_source="browser")
            turn_id = str(
                getattr(self._session, "active_turn_id", None)
                or f"browser-{getattr(self._session, 'turn_index', 0)}"
            )
            async for event in events:
                kind = event.get("type")
                if kind == "text_delta":
                    response += str(event.get("text") or "")
                    publish_response("speaking" if audio_active else "thinking")
                elif kind == "text_replace":
                    response = str(event.get("text") or "")
                    publish_response("speaking" if audio_active else "thinking")
                elif kind == "message_complete":
                    final_text = str(event.get("text") or "")
                    if final_text and final_text != response:
                        response = final_text
                    publish_response("speaking" if audio_active else "thinking")
                elif kind == "status":
                    self._publish(
                        "speaking" if audio_active else "thinking",
                        response_text=display_text(response),
                        status_text=str(event.get("text") or "Thinking"),
                    )
                elif kind == "audio_start":
                    audio_format = (
                        int(event.get("sample_rate", 0)),
                        int(event.get("channels", 0)),
                        int(event.get("sample_width", 0)),
                    )
                    await server.send_audio_start(
                        turn_id=turn_id,
                        sample_rate=audio_format[0],
                        channels=audio_format[1],
                        sample_width=audio_format[2],
                    )
                    audio_active = True
                    publish_response("speaking")
                elif kind == "audio_chunk":
                    data = event.get("data")
                    if audio_active and isinstance(data, bytes):
                        await server.send_audio_chunk(data)
                elif kind == "audio_end":
                    if audio_active:
                        await server.send_audio_end(turn_id=turn_id)
                        audio_active = False
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
                    file_audio_active = True
                elif kind == "audio_file_chunk":
                    data = event.get("data")
                    if file_audio_active and isinstance(data, bytes):
                        file_audio.extend(data)
                elif kind == "audio_file_end":
                    data = event.get("data")
                    if isinstance(data, bytes):
                        file_audio.extend(data)
                    file_audio_active = False
                    if audio_active:
                        continue
                    try:
                        decoded, decoded_format = audio_module.read_wav(bytes(file_audio))
                    except ValueError:
                        if file_format is None:
                            self._publish(
                                "buffering",
                                response_text=display_text(response),
                            )
                            continue
                        decoded, decoded_format = bytes(file_audio), file_format
                    await server.send_audio_start(
                        turn_id=turn_id,
                        sample_rate=decoded_format[0],
                        channels=decoded_format[1],
                        sample_width=decoded_format[2],
                    )
                    audio_active = True
                    publish_response("speaking")
                    await server.send_audio_chunk(decoded)
                    await server.send_audio_end(turn_id=turn_id)
                    audio_active = False
                elif kind in ("audio_abort", "turn_interrupted"):
                    await abort_audio(str(event.get("error") or event.get("reason") or kind))
                    publish_terminal_error("Response interrupted")
                    return False
                elif kind == "error":
                    error_text = str(event.get("error") or "Hermes error")
                    await abort_audio(error_text)
                    publish_terminal_error(error_text)
                    return False
                elif kind == "turn_end":
                    if audio_active:
                        await server.send_audio_end(turn_id=turn_id)
                        audio_active = False
                    self._publish("idle", response_text=display_text(response))
                    completed = True
                    break
            if not completed:
                await abort_audio("turn ended without a reply")
                publish_terminal_error("Turn ended without a reply")
            return completed
        except asyncio.CancelledError:
            await abort_audio("turn cancelled")
            raise
        except Exception:
            logger.debug("browser voice turn failed", exc_info=True)
            await abort_audio("connection lost")
            self._connected = False
            self._publish(
                "disconnected",
                response_text="",
                status_text=STATUS_TEXT["disconnected"],
            )
            self._request_reconnect()
            return False

    def _set_listening(self) -> None:
        """Listen only when idle and connected — never during a turn.

        A turn holds the microphone, and `pause` resets the detector's rolling
        buffer. Without this the unit wakes itself: observed live, a misfire
        expired after 8s and the tail of the same spoken phrase was still in
        the buffer, firing again the moment the microphone came free.
        """
        if self._listener is None:
            return
        listening = (
            self._connected and not self._stopping.is_set()
            and not self._follow_up_capturing
            and self._coordinator.state == handsfree.IDLE
        )
        if listening == self._is_listening:
            return
        self._is_listening = listening
        if listening:
            self._listener.resume()
        else:
            self._listener.pause()

    def _on_coordinator_state(self, state: str) -> None:
        """Called on the listener thread as the capture half of a turn moves."""
        self._set_listening()
        if self._stopping.is_set():
            return
        if not self._connected:
            self._publish("disconnected")
            return
        if state == handsfree.ACKNOWLEDGING:
            # A new question replaces the last answer: leaving the previous
            # response on screen while listening claims a conversation that
            # has already moved on. Cleared here rather than at capture, so
            # the screen turns over the moment the phrase is heard.
            self._publish("heard", response_text="")
            return
        if state == handsfree.CAPTURING:
            self._publish("listening")
            return
        display = DISPLAY_FOR_COORDINATOR.get(state)
        if display is not None:
            self._publish(display)

    # ---- acknowledgement -----------------------------------------------

    def _acknowledge_wake(self) -> None:
        """Say "heard you" on the screen and out loud, then get out of the way.

        Called on the listener thread, between ACKNOWLEDGING and the capture.
        It blocks for the length of the tone — roughly 200ms — which is what
        keeps the chirp out of the recording that follows it. Measured against
        four seconds of silence, that is a bargain.

        The screen is driven by the coordinator state, not from here, so the
        display changes the instant the phrase lands rather than after the
        tone has finished playing.
        """
        self._earcons.play(earcons_module.WAKE)

    def _acknowledge_capture(self) -> None:
        """Mark the moment listening stops and work starts.

        Only reached once there is a real transcript to send, so the room never
        hears the unit announce work it is not doing.
        """
        self._earcons.play(earcons_module.CAPTURE_DONE)

    # ---- turn ----------------------------------------------------------

    def _session_is_ready(self) -> bool:
        if not self._connected or self._session is None:
            return False
        try:
            return bool(self._session.is_connected())
        except Exception:
            logger.debug("appliance session readiness check failed", exc_info=True)
            return False

    def _capture_voice(self) -> str:
        if self._stopping.is_set() or not self._session_is_ready():
            return ""
        return self._session.capture_voice()

    def _capture_follow_up(self) -> str:
        if self._stopping.is_set() or not self._session_is_ready():
            return ""
        self._follow_up_capturing = True
        try:
            if not self._session_is_ready():
                return ""
            transcript = self._session.capture_voice(
                wait_timeout=float(getattr(self.args, "wake_followup_seconds", 8.0))
            )
            if self._stopping.is_set() or not self._session_is_ready():
                return ""
            return transcript
        finally:
            self._follow_up_capturing = False
            self._set_listening()

    def _send(self, text: str) -> bool:
        """Run one turn on the event loop, blocking the listener thread.

        Blocking is the point. The coordinator is single-flight: while this
        call is outstanding it is in SENDING, so a second detection is dropped
        rather than turned into an overlapping turn.
        """
        loop = self._loop
        if loop is None:
            raise RuntimeError("the appliance loop is not running")
        if self._stopping.is_set() or not self._session_is_ready():
            return False
        future = asyncio.run_coroutine_threadsafe(self._run_turn(text), loop)
        self._turn_future = future
        try:
            return (
                future.result()
                and not self._stopping.is_set()
                and self._session_is_ready()
            )
        finally:
            self._turn_future = None

    async def _run_turn(self, text: str) -> bool:
        response = ""
        visible_response = ""
        audio = bytearray()
        file_audio = bytearray()
        file_format: tuple[int, int, int] | None = None
        audio_format: tuple[int, int, int] | None = None
        audio_started = False
        audio_duration_final = False
        fallback_playback_origin: float | None = None
        speech_timings: dict[str, SpeechTiming] = {}
        caption_task: asyncio.Task[None] | None = None
        speaking = False
        spoke = False
        completed = False
        failed = False

        def open_playback(fmt: tuple[int, int, int]) -> bool:
            """Open the output device. Not the same as making a sound."""
            nonlocal audio_format, audio_started
            audio_format = fmt
            audio_started = True
            if not self._player.active:
                self._player.start(fmt)
            if self._player.active:
                start_caption_clock()
                return True
            # Audio is arriving but nothing can play it. Say so rather than
            # showing "speaking" over a silent room.
            self._publish("buffering")
            return False

        def audio_duration() -> float | None:
            if audio_format is None:
                return None
            sample_rate, channels, sample_width = audio_format
            bytes_per_second = sample_rate * channels * sample_width
            if bytes_per_second <= 0:
                return None
            return len(audio) / bytes_per_second

        def playback_position() -> float | None:
            position = getattr(self._player, "playback_position", None)
            if callable(position):
                position = position()
            try:
                position = float(position)
            except (TypeError, ValueError):
                return None
            return position if math.isfinite(position) and position >= 0 else None

        def first_word_prefix(target: str) -> str:
            end = 0
            while end < len(target) and not target[end].isspace():
                end += 1
            while end < len(target) and target[end].isspace():
                end += 1
            return target[:end]

        def render_caption(*, complete: bool = False) -> None:
            nonlocal fallback_playback_origin, visible_response
            target = display_text(response)
            if not target:
                if visible_response:
                    visible_response = ""
                    self._publish(
                        "speaking" if speaking else "thinking",
                        response_text="",
                    )
                return
            if not complete and not spoke and audio_started and self._player.active:
                # The relay can deliver the text and timing before the
                # prebuffer produces an audible sample. Keep the established
                # thinking preview, but do not commit it as the speaking
                # cursor: the first real sample may need to begin earlier.
                self._publish("thinking", response_text=target)
                return
            if not target.startswith(visible_response):
                visible_response = ""

            if complete or not audio_started or not self._player.active:
                candidate = target
            else:
                position = playback_position()
                candidate = None
                if position is not None:
                    if fallback_playback_origin is None:
                        fallback_playback_origin = position
                    if speech_timings:
                        candidate = visible_text(
                            target,
                            speech_timings.values(),
                            position,
                        )
                    elif audio_duration_final:
                        candidate = duration_visible_text(
                            target,
                            position,
                            audio_duration() or 0.0,
                        )
                    else:
                        candidate = fallback_visible_text(
                            target,
                            position - fallback_playback_origin,
                        )
                candidate = longest_valid_prefix(
                    target,
                    [visible_response, candidate],
                ) or first_word_prefix(target)

            safe_candidate = longest_valid_prefix(
                target,
                [visible_response, candidate],
            ) or visible_response
            if safe_candidate == visible_response:
                return
            visible_response = safe_candidate
            if speaking:
                state: DisplayState = "speaking"
            elif spoke and self._published:
                state = self._published[0]
            else:
                state = "thinking"
            self._publish(state, response_text=visible_response)

        async def caption_clock() -> None:
            while self._player.active and not failed:
                await asyncio.sleep(0.05)
                if self._player.active and not failed:
                    render_caption()

        def start_caption_clock() -> None:
            nonlocal caption_task
            if caption_task is None or caption_task.done():
                caption_task = asyncio.create_task(caption_clock())

        async def stop_caption_clock() -> None:
            nonlocal caption_task
            task = caption_task
            caption_task = None
            if task is None or task.done() or task is asyncio.current_task():
                return
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        def enter_speaking() -> None:
            """Announce speech only once a sample is actually going out.

            `audio_start` is a header. Measured against a live gateway, the
            first audible sample arrived 2.2s after it — two seconds of a
            display claiming to talk over a silent room.
            """
            nonlocal speaking, spoke, visible_response
            if speaking:
                return
            visible_response = ""
            speaking = True
            spoke = True
            render_caption()
            self._coordinator.playback_started()

        try:
            async for event in self._session.send_turn(text, stt_source="local"):
                kind = event.get("type")
                if failed and kind != "turn_end":
                    continue
                if kind == "text_delta":
                    response += str(event.get("text") or "")
                    render_caption()
                elif kind == "text_replace":
                    response = str(event.get("text") or "")
                    render_caption()
                elif kind == "prompt_request":
                    # A structured gateway prompt (approval/confirm/clarify).
                    # Convert to a display overlay; do not render as response text.
                    prompt = _classify_prompt_request(event)
                    if prompt is not None:
                        logger.debug(
                            "appliance prompt_request kind=%s action=%s",
                            prompt.kind,
                            prompt.action_id,
                        )
                        self._pending_prompt_action_id = prompt.action_id
                        self._publish_prompt(prompt)
                    else:
                        logger.debug(
                            "appliance unrecognised prompt_request event=%r", event
                        )
                elif kind == "audio_start":
                    audio_duration_final = False
                    open_playback(
                        (
                            event["sample_rate"],
                            event["channels"],
                            event["sample_width"],
                        )
                    )
                elif kind == "audio_chunk":
                    audio.extend(event["data"])
                    if self._player.active:
                        await asyncio.to_thread(self._player.write, event["data"])
                        # The player holds a cushion before its first sample,
                        # so announce speech when it starts playing, not when
                        # it starts buffering.
                        if getattr(self._player, "playing", True):
                            enter_speaking()
                        render_caption()
                elif kind == "audio_end":
                    # One audio_end closes a segment. Keep the output stream
                    # and its response-relative clock alive for later segments.
                    audio_duration_final = True
                    render_caption()
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
                    if not spoke and open_playback(fmt):
                        audio.extend(decoded)
                        await asyncio.to_thread(self._player.write, decoded)
                        if getattr(self._player, "playing", True):
                            enter_speaking()
                        await self._finish_playback(notify=False)
                        render_caption(complete=True)
                        if speaking:
                            self._coordinator.playback_finished()
                        speaking = False
                elif kind == "speech_timing":
                    try:
                        timing = SpeechTiming.from_event(event)
                    except (TypeError, ValueError):
                        timing = None
                    if timing is not None and timing.segment_id:
                        speech_timings[timing.segment_id] = timing
                        render_caption()
                elif kind in ("audio_abort", "turn_interrupted"):
                    failed = True
                    await stop_caption_clock()
                    await asyncio.to_thread(self._player.abort)
                    speaking = False
                    visible_response = ""
                    self._publish("idle", response_text="")
                elif kind == "error":
                    failed = True
                    await stop_caption_clock()
                    visible_response = ""
                    self._publish(
                        "error",
                        response_text="",
                        status_text=str(event.get("error") or "Hermes error"),
                    )
                elif kind == "turn_end":
                    completed = True
                    await stop_caption_clock()
                    if not failed:
                        await self._finish_playback(notify=False)
                        # Check if the complete response is a gateway notice.
                        # If so, suppress the text and show the prompt overlay.
                        notice = _classify_gateway_notice(response)
                        if notice is not None and not audio_started:
                            logger.debug(
                                "appliance gateway notice detected, showing prompt overlay"
                            )
                            self._pending_prompt_action_id = notice.action_id
                            self._publish_prompt(notice)
                        else:
                            render_caption(complete=True)
                            if speaking:
                                self._coordinator.playback_finished()
                                speaking = False
                    break
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # The connection is the usual reason a turn stops mid-stream.
            # Report it as what the unit is: not talking to Hermes.
            logger.debug("appliance turn failed", exc_info=True)
            # Clear the partial reply. A finished answer stays up to be read;
            # half a sentence from a turn the connection killed is not an
            # answer, and must not sit there looking like one.
            self._connected = False
            self._publish(
                "disconnected",
                response_text="",
                status_text=STATUS_TEXT["disconnected"],
            )
            self._set_listening()
            self._request_reconnect()
            raise RuntimeError("the turn ended without a reply") from error
        finally:
            await stop_caption_clock()
            await self._finish_playback(abort=failed or self._stopping.is_set())
        return completed and not failed

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

    def _abort_player(self) -> None:
        """Stop local response audio immediately from a synchronous callback."""
        if self._player is None:
            return
        abort = getattr(self._player, "abort", None)
        if callable(abort):
            abort()
        else:
            self._player.close()

    async def _finish_playback(
        self, *, notify: bool = True, abort: bool = False
    ) -> None:
        if self._player is None or not self._player.active:
            return
        # sounddevice's stop drains the device buffer, which can take as long
        # as the tail of the sentence. Off the loop it goes.
        if abort or self._stopping.is_set():
            close = getattr(self._player, "abort", None)
            if not callable(close):
                close = self._player.close
        else:
            close = self._player.close
        await asyncio.to_thread(close)
        if notify and not self._stopping.is_set():
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
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._reconnect.wait(), delay)
                delay = min(delay * 2, MAX_RECONNECT_DELAY)
                continue

            # Only listen while there is somewhere for a turn to go. A wake
            # phrase the unit cannot act on must do nothing at all, not queue.
            self._connected = True
            delay = self._reconnect_delay
            self._publish("idle")
            self._set_listening()
            try:
                await self._reconnect.wait()
            finally:
                self._reconnect.clear()
                self._connected = False
                self._set_listening()
                with contextlib.suppress(Exception):
                    await self._session.close()

    # ---- profiles & session switching ---------------------------------

    def _create_session_for_profile(self, profile: config.HouseholdProfile) -> Any:
        if self._session_factory is not None:
            return self._session_factory(profile)
        if profile.name in self._sessions:
            return self._sessions[profile.name]
        profile_args = config.make_profile_args(self.args, profile)
        return HermesSession(profile_args)

    async def _switch_profile(self, profile: config.HouseholdProfile) -> bool:
        if self._active_profile == profile and self._connected:
            return True

        logger.info(
            "switching household profile: from=%s to=%s display_name=%s",
            self._active_profile.name if self._active_profile else None,
            profile.name,
            profile.display_name,
        )

        old_session = self._session
        self._connected = False
        self._set_listening()
        if old_session is not None:
            with contextlib.suppress(Exception):
                await old_session.close()

        self._active_profile = profile
        self._session = self._create_session_for_profile(profile)
        self._session.use_shared_recorder(self._recorder)

        try:
            await self._session.connect()
            self._connected = True
            self._set_listening()
            self._publish("idle", status_text=f"Switched to {profile.display_name}")
            return True
        except Exception:
            logger.debug("switching profile failed for %s", profile.name, exc_info=True)
            self._connected = False
            self._set_listening()
            self._publish(
                "disconnected",
                status_text=f"Failed to connect {profile.display_name}",
            )
            self._request_reconnect()
            return False

    async def route_wake(self, phrase: str | None) -> bool:
        if self._stopping.is_set() or not self._connected:
            return False
        if not phrase:
            if len(self._profiles) == 1:
                return True
            return False

        normalized = phrase.strip().casefold()
        profile = self._phrase_to_profile.get(normalized)
        if profile is None:
            logger.debug("ignoring unknown or ambiguous wake phrase: %r", phrase)
            return False

        current_state = self._coordinator.state if self._coordinator else handsfree.IDLE
        if self._active_profile and profile.name == self._active_profile.name:
            return True

        if current_state != handsfree.IDLE:
            logger.debug(
                "cannot switch account to %s during active turn/playback (state=%s)",
                profile.name,
                current_state,
            )
            return False

        return await self._switch_profile(profile)

    def _route_wake(self, phrase: str | None) -> bool:
        loop = self._loop
        if loop is None:
            return False
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            raise RuntimeError(
                "_route_wake called synchronously on the event loop thread; "
                "use await appliance.route_wake() or run in a worker thread"
            )
        future = asyncio.run_coroutine_threadsafe(self.route_wake(phrase), loop)
        try:
            return bool(future.result())
        except Exception:
            logger.debug("profile switch for wake phrase %r failed", phrase, exc_info=True)
            return False

    # ---- lifecycle -----------------------------------------------------

    def _display_tls_context(self):
        certificate = getattr(self.args, "display_tls_cert", None)
        private_key = getattr(self.args, "display_tls_key", None)
        if certificate is None and private_key is None:
            return None
        if not getattr(self.args, "browser_voice", False):
            raise RuntimeError(
                "display TLS requires --browser-voice; the physical display uses plain ws"
            )
        try:
            return load_tls_context(certificate, private_key)
        except ValueError as error:
            raise RuntimeError(str(error)) from error

    def _build(self) -> None:
        if self._session is None:
            self._session = self._create_session_for_profile(self._active_profile)
        tls_context = self._display_tls_context()
        if getattr(self.args, "browser_voice", False):
            if self._server is None:
                self._server = DisplayServer(
                    self.publisher,
                    Path(__file__).with_name("static"),
                    host=getattr(self.args, "display_host", "127.0.0.1"),
                    port=getattr(self.args, "display_port", 0),
                    allow_remote=getattr(self.args, "display_remote", False),
                    on_action=self._on_action,
                    on_voice_turn=self._on_browser_voice_turn,
                    ssl_context=tls_context,
                )
            return
        if self._player is None:
            self._player = audio_module.PCMPlayer(
                enabled=not getattr(self.args, "no_play", False),
                output_device=getattr(self.args, "audio_output_device", None),
            )
        if self._earcons is None:
            self._earcons = earcons_module.EarconPlayer(
                enabled=getattr(self.args, "earcons", True)
                and not getattr(self.args, "no_play", False),
                output_device=getattr(self.args, "audio_output_device", None),
            )
        if self._recorder is None:
            from voice import create_audio_recorder

            self._recorder = create_audio_recorder()

        kwargs: dict[str, Any] = {
            "on_state_change": self._on_coordinator_state,
            "send": self._send,
            "follow_up_capture": self._capture_follow_up,
            "speech_detected": self._speech_detected,
            "stop_playback": self._abort_player,
            "acknowledge": self._acknowledge_wake,
            "capture_finished": self._acknowledge_capture,
        }
        import inspect

        try:
            params = inspect.signature(self._build_hands_free).parameters
            if "capture" in params or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            ):
                kwargs["capture"] = self._capture_voice
            if "route_wake" in params or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            ):
                kwargs["route_wake"] = self._route_wake
            if "is_ready" in params or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            ):
                kwargs["is_ready"] = self._session_is_ready
        except (ValueError, TypeError):
            kwargs["capture"] = self._capture_voice
            kwargs["route_wake"] = self._route_wake
            kwargs["is_ready"] = self._session_is_ready

        hands_free_args = self.args
        if getattr(self.args, "wake_phrases", None) is None:
            all_phrases = []
            for prof in self._profiles:
                all_phrases.extend(prof.wake_phrases)
            if all_phrases:
                import copy

                hands_free_args = copy.copy(self.args)
                hands_free_args.wake_phrases = tuple(all_phrases)

        built = self._build_hands_free(self._session, hands_free_args, **kwargs)
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
                host=getattr(self.args, "display_host", "127.0.0.1"),
                port=getattr(self.args, "display_port", 0),
                allow_remote=getattr(self.args, "display_remote", False),
                on_action=self._on_action,
            )
        self._session.use_shared_recorder(self._recorder)

    def stop(self) -> None:
        """Signal the appliance to stop running."""
        self._stopping.set()
        loop, reconnect = self._loop, self._reconnect
        if loop is not None and reconnect is not None:
            loop.call_soon_threadsafe(reconnect.set)
        if (
            loop is not None
            and self._supervisor_task is not None
            and not self._supervisor_task.done()
        ):
            loop.call_soon_threadsafe(self._supervisor_task.cancel)

    def _install_signals(self, loop: asyncio.AbstractEventLoop) -> None:
        def on_signal() -> None:
            self._sigint_count += 1
            if self._sigint_count == 1:
                logger.debug("appliance received shutdown signal")
                self.stop()
            else:
                logger.debug("appliance received second shutdown signal; force exiting")
                raise KeyboardInterrupt

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, on_signal)
                self._signals_installed.append(sig)
            except (NotImplementedError, ValueError, RuntimeError):
                pass

    def _remove_signals(self, loop: asyncio.AbstractEventLoop | None) -> None:
        if loop is None:
            return
        for sig in self._signals_installed:
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, ValueError, RuntimeError):
                pass
        self._signals_installed.clear()

    def _track_cleanup_task(self, task: asyncio.Task[Any]) -> None:
        """Retain cleanup work that outlives the command that started it."""
        self._cleanup_tasks.add(task)

        def finished(done: asyncio.Task[Any]) -> None:
            self._cleanup_tasks.discard(done)
            try:
                done.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("appliance cleanup failed", exc_info=True)

        task.add_done_callback(finished)

    async def _wait_for_cleanup_tasks(self) -> None:
        tasks = [task for task in self._cleanup_tasks if not task.done()]
        if not tasks:
            return
        gathered = asyncio.gather(*tasks, return_exceptions=True)
        try:
            await asyncio.wait_for(
                asyncio.shield(gathered),
                SHUTDOWN_TASK_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "appliance.shutdown.cleanup_timeout count=%d", len(tasks)
            )

    def _finish_cancelled_recorder_open(self, recorder: Any, opening: Any) -> None:
        """Close a recorder whose native open outlived a cancelled task."""
        async def finish() -> None:
            try:
                try:
                    await opening
                except BaseException:
                    pass
                if recorder is not None:
                    await self._bounded_to_thread(recorder.shutdown)
            except Exception:
                logger.debug(
                    "closing the late appliance recorder failed", exc_info=True
                )
            finally:
                self._wake_opening = False

        self._track_cleanup_task(asyncio.create_task(finish()))

    async def _bounded_to_thread(
        self,
        func: Callable[..., Any] | None,
        *args: Any,
        timeout: float | None = None,
    ) -> None:
        """Run blocking teardown in a dedicated daemon thread with a hard timeout.

        We intentionally avoid asyncio.to_thread() here because asyncio's
        default ThreadPoolExecutor uses non-daemon worker threads. If a native
        audio/PortAudio call hangs or times out, an abandoned ThreadPoolExecutor
        worker thread will block Python's atexit._python_exit forever, trapping
        the process at shutdown. A daemon thread ensures interpreter exit is
        always clean and prompt.
        """
        if func is None:
            return
        actual_timeout = timeout if timeout is not None else SHUTDOWN_TASK_TIMEOUT
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()

        def runner() -> None:
            try:
                func(*args)
            except Exception as exc:
                if not future.done():
                    loop.call_soon_threadsafe(future.set_exception, exc)
                return
            if not future.done():
                loop.call_soon_threadsafe(future.set_result, None)

        thread = threading.Thread(
            target=runner,
            name=f"appliance-teardown-{getattr(func, '__name__', 'worker')}",
            daemon=True,
        )
        thread.start()
        try:
            await asyncio.wait_for(future, actual_timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "appliance.shutdown.timeout operation=%s",
                getattr(func, "__name__", str(func)),
            )
        except Exception:
            logger.debug(
                "appliance.shutdown.error operation=%s",
                getattr(func, "__name__", str(func)),
                exc_info=True,
            )


    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._reconnect = asyncio.Event()
        self._install_signals(self._loop)
        self._build()
        self.info = await self._server.start()

        if getattr(self.args, "browser_voice", False):
            if self._on_ready is not None:
                self._on_ready(self.info)
            self._supervisor_task = asyncio.create_task(self._supervise())
            try:
                await self._supervisor_task
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and getattr(current, "cancelling", lambda: 0)() > 0:
                    raise
            except KeyboardInterrupt:
                pass
            finally:
                self._remove_signals(self._loop)
                if self._supervisor_task is not None and not self._supervisor_task.done():
                    self._supervisor_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._supervisor_task
                await self.aclose()
            return

        # Start the worker *before* opening the stream. The other order lets
        # frames pile into a bounded queue with nothing draining it, and the
        # entire warm-up is dropped audio — 96 frames on a first run.
        self._listener.start()
        self._listener.pause()
        self._recorder.set_frame_observer(self._listener.submit)

        self._wake_opening = True
        opening = asyncio.create_task(asyncio.to_thread(self._open_recorder))
        try:
            await asyncio.shield(opening)
        except asyncio.CancelledError:
            if not opening.done():
                self._finish_cancelled_recorder_open(self._recorder, opening)
            else:
                self._wake_opening = False
            raise
        except Exception:
            self._wake_opening = False
            raise
        self._wake_opening = False

        if self._on_ready is not None:
            self._on_ready(self.info)

        ticker = asyncio.create_task(self._expire_listening_window())
        self._supervisor_task = asyncio.create_task(self._supervise())
        try:
            await self._supervisor_task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and getattr(current, "cancelling", lambda: 0)() > 0:
                raise
        except KeyboardInterrupt:
            pass
        finally:
            self._remove_signals(self._loop)
            ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticker
            if self._supervisor_task is not None and not self._supervisor_task.done():
                self._supervisor_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._supervisor_task
            await self.aclose()

    def _open_recorder(self) -> None:
        from mic import input_device_context

        with input_device_context(getattr(self.args, "mic_input_device", None)):
            self._recorder.open_for_listening()

    async def aclose(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._stopping.set()
        self._connected = False
        self._set_listening()
        if self._session is not None:
            with contextlib.suppress(Exception):
                self._session.cancel_voice()
        if self._turn_future is not None:
            self._turn_future.cancel()
        if self._browser_turn_task is not None and not self._browser_turn_task.done():
            self._browser_turn_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._browser_turn_task
        if self._earcons is not None:
            abort = getattr(self._earcons, "abort", None)
            if callable(abort):
                await self._bounded_to_thread(abort)
        if self._listener is not None:
            await self._bounded_to_thread(self._listener.stop)
        await self._wait_for_cleanup_tasks()
        if self._recorder is not None and not self._wake_opening:
            with contextlib.suppress(Exception):
                await self._bounded_to_thread(self._recorder.shutdown)
        if self._player is not None:
            with contextlib.suppress(Exception):
                await self._bounded_to_thread(self._abort_player)
        if self._sessions:
            for sess in list(self._sessions.values()):
                if sess is not self._session:
                    with contextlib.suppress(Exception):
                        close_task = asyncio.create_task(sess.close())
                        await asyncio.wait_for(
                            asyncio.shield(close_task),
                            SHUTDOWN_TASK_TIMEOUT,
                        )
        if self._session is not None:
            with contextlib.suppress(Exception):
                close_task = asyncio.create_task(self._session.close())
                await asyncio.wait_for(
                    asyncio.shield(close_task),
                    SHUTDOWN_TASK_TIMEOUT,
                )
        if self._server is not None:
            with contextlib.suppress(Exception):
                close_task = asyncio.create_task(self._server.close())
                await asyncio.wait_for(
                    asyncio.shield(close_task),
                    SHUTDOWN_TASK_TIMEOUT,
                )


def build_arg_parser(argv: list[str] | None = None) -> argparse.ArgumentParser:
    parser = config.build_arg_parser(argv)
    parser.add_argument(
        "--display-host",
        default="127.0.0.1",
        help="display bind address; keep loopback unless --display-remote is set",
    )
    parser.add_argument(
        "--display-port",
        type=int,
        default=0,
        help="display port; 0 selects an available port",
    )
    parser.add_argument(
        "--display-remote",
        action="store_true",
        help="allow the display server to bind beyond loopback for a LAN appliance",
    )
    parser.add_argument(
        "--display-tls-cert",
        type=Path,
        default=None,
        metavar="PATH",
        help="PEM certificate for an HTTPS browser display",
    )
    parser.add_argument(
        "--display-tls-key",
        type=Path,
        default=None,
        metavar="PATH",
        help="PEM private key for an HTTPS browser display",
    )
    parser.add_argument(
        "--browser-voice",
        action="store_true",
        help="let the browser own microphone capture and speaker playback",
    )

    # Only substitute the hands-free default when nobody has said otherwise.
    # An explicit flag beats a default anyway; a configured value must too.
    settings = config.load_config_file(config.config_path_from_argv(argv))
    configured = "mic_silence_duration" in settings or os.getenv(
        "VOICE_SESSION_MIC_SILENCE_DURATION"
    )
    if not configured:
        parser.set_defaults(mic_silence_duration=HANDS_FREE_SILENCE_DURATION)
    return parser


def main() -> int:
    diagnostics.install_crash_logging()
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
