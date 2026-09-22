"""The ESP32 Touch doorway: bounded microphone audio into one Home turn.

The panel already receives display snapshots and posts touch choices. What it
has never had is a way to *say* anything. This module is that path, and it is
deliberately the only place the pieces meet:

- Admission is an HTTP claim against Home, not an origin check. `/state`
  origin validation says a page may connect; it says nothing about whether
  this device is allowed to open a conversation.
- The Device credential, the claim ID, the configuration revision, and the
  conversation handle live here and nowhere else. They are never put in a
  socket frame, never logged, and never reach the audio board.
- Microphone PCM is transient. It exists as bytes in this process between
  `mic_start` and the final transcript, and it is dropped the instant the
  transcript is produced, the capture is aborted, or anything at all goes
  wrong.
- Home receives one final transcript per capture. It never receives PCM, and
  a prompt whose delivery is uncertain is discarded rather than replayed.

Front end, not core: it owns presentation-adjacent state for one doorway.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlsplit, urlunsplit

from voice import MAX_FINAL_TRANSCRIPT_CHARACTERS

logger = logging.getLogger("hermes_relay_tui.touch")

__all__ = [
    "MAX_CAPTURE_BYTES",
    "MAX_CAPTURE_SECONDS",
    "MAX_FINAL_TRANSCRIPT_CHARACTERS",
    "MAX_PCM_CHUNK_BYTES",
    "TOUCH_CLAIM_PATH",
    "TOUCH_PCM_CHANNELS",
    "TOUCH_PCM_SAMPLE_RATE",
    "TOUCH_PCM_SAMPLE_WIDTH",
    "HttpTouchClaimClient",
    "TouchClaimError",
    "TouchConfigurationError",
    "TouchDeviceConfig",
    "TouchDoorway",
    "load_touch_device_config",
    "touch_claim_url",
]

# The capture contract, in one place. Firmware, host, and tests all read these
# numbers rather than each inventing their own bound.
TOUCH_PCM_SAMPLE_RATE = 16_000
TOUCH_PCM_CHANNELS = 1
TOUCH_PCM_SAMPLE_WIDTH = 2
MAX_PCM_CHUNK_BYTES = 4096
MAX_CAPTURE_SECONDS = 15
MAX_CAPTURE_BYTES = 480_000
MAX_CAPTURE_ID_LENGTH = 64
MAX_CONVERSATION_HANDLE_LENGTH = 512

TOUCH_CLAIM_PATH = "/api/v1/touch-claims"
TOUCH_CLAIM_TIMEOUT = 10.0
TOUCH_SESSION_CONNECT_TIMEOUT = 8.0
TOUCH_SHUTDOWN_TIMEOUT = 3.0

REJECT_UNAUTHORIZED = "unauthorized"
REJECT_UNAVAILABLE = "unavailable"
REJECT_BUSY = "busy"
REJECT_MALFORMED = "malformed"

AUDIO_UNAVAILABLE_STATUS = "Audio unavailable"


class TouchConfigurationError(RuntimeError):
    """Approved local configuration for the Touch doorway is missing."""


class TouchClaimError(RuntimeError):
    """Home refused or could not answer a device claim."""

    def __init__(self, reason: str = REJECT_UNAVAILABLE) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class TouchDeviceConfig:
    """The paired device identity, read from approved local storage only.

    A socket frame can never supply any of this. The panel says *when* it
    wants to speak; the configuration on this host says *who* it is.
    """

    device_id: str
    config_revision: str
    credential: str
    claim_url: str
    bridge_url: str

    def __repr__(self) -> str:  # pragma: no cover - defensive, never logged
        return (
            "TouchDeviceConfig(device_id=<redacted>, config_revision=<redacted>, "
            "credential=<redacted>, claim_url=<redacted>, bridge_url=<redacted>)"
        )


def touch_claim_url(bridge_url: str) -> str:
    """Derive the claim endpoint from the one configured Home bridge route."""
    parsed = urlsplit(str(bridge_url).strip())
    if parsed.scheme != "wss" or not parsed.netloc:
        raise TouchConfigurationError(
            "Touch voice requires an approved wss:// Home bridge URL"
        )
    return urlunsplit(("https", parsed.netloc, TOUCH_CLAIM_PATH, "", ""))


def _validate_claim_url(url: str) -> str:
    """Refuse a claim route that would put the credential on an open wire."""
    parsed = urlsplit(str(url).strip())
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise TouchConfigurationError("Touch claim URL must be http(s) with a host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise TouchConfigurationError(
            "Touch claim URL must not contain credentials or query data"
        )
    if parsed.scheme == "http":
        try:
            loopback = ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname.casefold() in ("localhost", "localhost.")
        if not loopback:
            raise TouchConfigurationError(
                "Touch claim URL must use https unless it is loopback"
            )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))


def _read_credential_file(path: Path) -> str:
    try:
        credential = path.expanduser().read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise TouchConfigurationError(
            "Touch Device credential storage is unavailable"
        ) from error
    if not credential:
        raise TouchConfigurationError("Touch Device credential storage is empty")
    return credential


def load_touch_device_config(args: Any) -> TouchDeviceConfig:
    """Resolve the Touch identity, or fail closed before anything listens.

    Every failure here is the same failure: this host cannot prove which
    approved device it is speaking for. There is no fallback identity and no
    anonymous mode — the doorway simply does not open.
    """
    import config as config_module
    from puck_bridge.home_session import require_home_bridge_url

    raw_bridge = str(getattr(args, "home_bridge_url", "") or "").strip()
    if not raw_bridge:
        raise TouchConfigurationError("Touch voice requires --home-bridge-url")
    try:
        bridge_url = require_home_bridge_url(raw_bridge)
    except ValueError as error:
        raise TouchConfigurationError(str(error)) from error

    device_id = str(getattr(args, "touch_device_id", "") or "").strip()
    if not device_id or len(device_id) > 128:
        raise TouchConfigurationError(
            "Touch voice requires a configured --touch-device-id"
        )
    revision = str(getattr(args, "touch_config_revision", "") or "").strip()
    if not revision or len(revision) > 128:
        raise TouchConfigurationError(
            "Touch voice requires a configured --touch-config-revision"
        )

    credential_file = getattr(args, "home_device_credential_file", None)
    if credential_file:
        credential = _read_credential_file(Path(credential_file))
    else:
        credential = config_module.resolve_home_device_credential(
            getattr(args, "profile_env", None)
        )
    if not credential:
        raise TouchConfigurationError(
            "Touch voice requires a paired Device credential in approved storage"
        )

    explicit_claim = str(getattr(args, "touch_claim_url", "") or "").strip()
    claim_url = _validate_claim_url(
        explicit_claim if explicit_claim else touch_claim_url(bridge_url)
    )
    return TouchDeviceConfig(
        device_id=device_id,
        config_revision=revision,
        credential=credential,
        claim_url=claim_url,
        bridge_url=bridge_url,
    )


class TouchClaimClient(Protocol):
    """Exchange the paired device identity for one opaque Home handle."""

    async def claim(self, *, claim_id: str, observed_at: str) -> str: ...


class HttpTouchClaimClient:
    """POST /api/v1/touch-claims with the configured device identity."""

    def __init__(
        self,
        device_config: TouchDeviceConfig,
        *,
        timeout: float = TOUCH_CLAIM_TIMEOUT,
    ) -> None:
        self._config = device_config
        self._timeout = timeout

    async def claim(self, *, claim_id: str, observed_at: str) -> str:
        return await asyncio.to_thread(self._post, claim_id, observed_at)

    def _post(self, claim_id: str, observed_at: str) -> str:
        import urllib.error
        import urllib.request

        payload = json.dumps(
            {
                "schema": 1,
                "claim_id": claim_id,
                "device_id": self._config.device_id,
                "config_revision": self._config.config_revision,
                "observed_at": observed_at,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self._config.claim_url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self._config.credential}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = response.read(64 * 1024)
        except urllib.error.HTTPError as error:
            # The status is safe to classify; the body may carry anything.
            raise TouchClaimError(
                REJECT_UNAUTHORIZED
                if error.code in (401, 403)
                else REJECT_UNAVAILABLE
            ) from None
        except Exception:
            raise TouchClaimError(REJECT_UNAVAILABLE) from None

        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError):
            raise TouchClaimError(REJECT_UNAVAILABLE) from None
        if not isinstance(decoded, dict):
            raise TouchClaimError(REJECT_UNAVAILABLE)
        handle = decoded.get("conversation_handle") or decoded.get("handle")
        if (
            not isinstance(handle, str)
            or not handle.strip()
            or len(handle) > MAX_CONVERSATION_HANDLE_LENGTH
        ):
            raise TouchClaimError(REJECT_UNAVAILABLE)
        return handle.strip()


@dataclass
class _Capture:
    """One in-flight microphone capture. Nothing about it survives the turn."""

    capture_id: str
    started: bool = False
    total_bytes: int = 0
    chunks: list[bytes] = field(default_factory=list)

    def take(self) -> bytes:
        pcm = b"".join(self.chunks)
        self.discard()
        return pcm

    def discard(self) -> None:
        self.chunks.clear()
        self.total_bytes = 0


class TouchDoorway:
    """One admitted Touch socket: capture state, Home binding, and phases.

    The doorway is deliberately serial. One capture, one Home turn, one
    socket. Frames arrive as independent tasks from the display server, so a
    single lock keeps them in arrival order and keeps the state machine from
    being two things at once.
    """

    def __init__(
        self,
        *,
        connection_id: str,
        publisher: Any,
        sender: Any,
        device_config: TouchDeviceConfig,
        claim_client: TouchClaimClient,
        session_factory: Callable[[str], Awaitable[Any]],
        transcriber: Callable[[bytes], dict[str, Any]] | None = None,
        account: str | None = None,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.connection_id = connection_id
        self.publisher = publisher
        self._sender = sender
        self._config = device_config
        self._claim_client = claim_client
        self._session_factory = session_factory
        self._transcriber = transcriber
        self._account = account
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

        self._lock = asyncio.Lock()
        self._closed = False
        self._session: Any = None
        self._capture: _Capture | None = None
        self._turn_task: asyncio.Task[Any] | None = None
        self._turn_id: str | None = None
        self._audio_open = False
        self._playback_started = False
        self._audio_unavailable = False
        self._interrupt_pending = False
        self._response_text = ""
        self._transcript_text = ""
        # The reducer's transition table has no ERROR->HEARD (or any other
        # non-idle) edge. Without tracking this, a rejected claim followed by
        # a later admitted `mic_start` would try exactly that edge and the
        # reducer would silently refuse it, freezing the panel on the error.
        self._last_published_state = "idle"

    # ---- ingress -------------------------------------------------------

    async def handle_touch_frame(self, frame: Any) -> None:
        """Apply one validated control frame from the endpoint."""
        kind = getattr(frame, "type", None)
        handlers = {
            "mic_start": self._on_mic_start,
            "mic_capture_started": self._on_capture_started,
            "mic_end": self._on_mic_end,
            "mic_abort": self._on_mic_abort,
            "turn_stop": self._on_turn_stop,
            "audio_playback_started": self._on_playback_started,
            "audio_playback_failed": self._on_playback_failed,
        }
        handler = handlers.get(str(kind))
        if handler is None:
            await self.handle_touch_malformed(REJECT_MALFORMED)
            return
        async with self._lock:
            if self._closed:
                return
            await handler(frame)

    async def handle_touch_audio(self, data: bytes) -> None:
        """Accept one bounded PCM chunk for the one started capture."""
        async with self._lock:
            if self._closed:
                return
            capture = self._capture
            if capture is None or not capture.started:
                # PCM before `mic_capture_started`, or after the capture is
                # gone, is not audio this doorway ever agreed to receive.
                self._discard_capture()
                self._publish("idle")
                return
            if (
                not data
                or len(data) % TOUCH_PCM_SAMPLE_WIDTH
                or len(data) > MAX_PCM_CHUNK_BYTES
                or capture.total_bytes + len(data) > MAX_CAPTURE_BYTES
            ):
                self._discard_capture()
                self._publish("idle")
                return
            capture.chunks.append(bytes(data))
            capture.total_bytes += len(data)

    async def handle_touch_malformed(self, reason: str = REJECT_MALFORMED) -> None:
        """Anything we could not parse clears transient state and makes no turn."""
        async with self._lock:
            if self._closed:
                return
            if self._capture is None:
                logger.debug(
                    "touch malformed frame ignored: no active capture "
                    "connection=%s reason=%s",
                    self.connection_id,
                    reason,
                )
                return
            capture_id = self._capture.capture_id
            self._discard_capture()
            await self._send_control(
                {
                    "type": "mic_reject",
                    "schema": 1,
                    "capture_id": capture_id,
                    "reason": reason,
                }
            )
            self._publish("idle")

    # ---- control frames ------------------------------------------------

    async def _on_mic_start(self, frame: Any) -> None:
        capture_id = str(getattr(frame, "capture_id", "") or "")
        if self._capture is not None:
            # A second start while one capture is open is a duplicate, not a
            # restart. Drop the audio already collected and create no turn.
            self._discard_capture()
            await self._reject(capture_id, REJECT_BUSY)
            self._publish("idle")
            return
        if self._turn_task is not None and not self._turn_task.done():
            await self._reject(capture_id, REJECT_BUSY)
            return

        if self._session is None:
            try:
                opened_session = await self._open_home_binding()
            except TouchClaimError as error:
                await self._reject(capture_id, error.reason)
                self._publish("error", status_text="Not admitted by Home")
                return
            except Exception:
                logger.debug("touch Home binding failed", exc_info=True)
                await self._reject(capture_id, REJECT_UNAVAILABLE)
                self._publish("error", status_text="Home is unavailable")
                return
            if self._closed:
                # close() ran while admission was still in flight. There is
                # no doorway left to hand this session to; close it here
                # instead of stashing it where nothing will ever clean it up.
                close = getattr(opened_session, "close", None)
                if callable(close):
                    with contextlib.suppress(Exception):
                        await close()
                return
            self._session = opened_session

        self._capture = _Capture(capture_id)
        self._audio_open = False
        self._playback_started = False
        self._audio_unavailable = False
        self._interrupt_pending = False
        self._turn_id = None
        if not await self._send_control(
            {"type": "mic_ready", "schema": 1, "capture_id": capture_id}
        ):
            self._discard_capture()
            return
        self._publish("heard", response_text="", transcript_text="")

    async def _open_home_binding(self) -> Any:
        """Claim admission from Home, then open the handle it returns.

        Both halves must succeed before the endpoint is told it may speak.
        A claim without an open conversation is not a doorway; it is a
        promise nobody can keep.
        """
        claim_id = self._id_factory()
        observed_at = self._clock().astimezone(timezone.utc).isoformat()
        handle = await self._claim_client.claim(
            claim_id=claim_id, observed_at=observed_at
        )
        session = await self._session_factory(handle)
        if session is None:
            raise TouchClaimError(REJECT_UNAVAILABLE)
        return session

    async def _on_capture_started(self, frame: Any) -> None:
        capture = self._capture
        capture_id = str(getattr(frame, "capture_id", "") or "")
        if capture is None or capture.capture_id != capture_id or capture.started:
            self._discard_capture()
            self._publish("idle")
            return
        capture.started = True
        self._publish("listening", response_text="", transcript_text="")

    async def _on_mic_end(self, frame: Any) -> None:
        capture = self._capture
        capture_id = str(getattr(frame, "capture_id", "") or "")
        if capture is None or capture.capture_id != capture_id or not capture.started:
            self._discard_capture()
            self._publish("idle")
            return
        pcm = capture.take()
        self._capture = None
        if not pcm:
            self._publish("idle")
            return
        self._publish("transcribing", response_text="", transcript_text="")
        self._turn_task = asyncio.create_task(self._transcribe_and_submit(pcm))

    async def _on_mic_abort(self, frame: Any) -> None:
        self._discard_capture()
        self._transcript_text = ""
        self._publish("idle", response_text="", transcript_text="")

    async def _on_turn_stop(self, _frame: Any) -> None:
        if self._capture is not None:
            # Nothing has been submitted, so there is nothing to interrupt.
            self._discard_capture()
            self._publish("idle", response_text="", transcript_text="")
            return
        if self._turn_task is None or self._turn_task.done():
            return
        self._interrupt_pending = True
        await self._apply_pending_interrupt()

    async def _on_playback_started(self, frame: Any) -> None:
        turn_id = str(getattr(frame, "turn_id", "") or "")
        if not self._audio_open or self._turn_id is None or turn_id != self._turn_id:
            return
        self._playback_started = True
        self._audio_unavailable = False
        self._publish("speaking")

    async def _on_playback_failed(self, frame: Any) -> None:
        turn_id = str(getattr(frame, "turn_id", "") or "")
        if self._turn_id is None or turn_id != self._turn_id:
            return
        self._playback_started = False
        self._audio_unavailable = True
        # The answer is still the answer. Only the speaker failed.
        self._publish(
            "buffering" if self._turn_active() else "complete",
            status_text=AUDIO_UNAVAILABLE_STATUS,
        )

    # ---- the one Home turn ---------------------------------------------

    async def _transcribe_and_submit(self, pcm: bytes) -> None:
        try:
            result = await asyncio.to_thread(self._transcribe, pcm)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("touch transcription failed", exc_info=True)
            result = {"success": False, "transcript": ""}

        if not result.get("success"):
            self._publish("idle", response_text="", transcript_text="")
            return
        transcript = str(result.get("transcript") or "").strip()
        if transcript:
            transcript = transcript[:MAX_FINAL_TRANSCRIPT_CHARACTERS]
        if not transcript or self._is_hallucination(transcript):
            # An empty transcript is not a turn. Say nothing to Home.
            self._publish("idle", response_text="", transcript_text="")
            return
        if self._closed:
            return
        await self._run_home_turn(transcript)

    def _transcribe(self, pcm: bytes) -> dict[str, Any]:
        if self._transcriber is not None:
            return self._transcriber(pcm)
        import voice as voice_module

        return voice_module.transcribe_pcm(
            pcm, max_characters=MAX_FINAL_TRANSCRIPT_CHARACTERS
        )

    @staticmethod
    def _is_hallucination(transcript: str) -> bool:
        try:
            import voice as voice_module
        except Exception:  # pragma: no cover - voice extra not installed
            return False
        check = getattr(voice_module, "is_whisper_hallucination", None)
        if not callable(check):  # pragma: no cover - defensive
            return False
        with contextlib.suppress(Exception):
            return bool(check(transcript))
        return False

    async def _run_home_turn(self, transcript: str) -> None:
        """Submit one final transcript and follow it to a terminal event."""
        session = self._session
        if session is None:
            self._publish("error", status_text="Home is unavailable")
            return

        self._transcript_text = transcript
        self._response_text = ""
        self._publish("thinking", response_text="", transcript_text=transcript)

        events: Any = None
        completed = False
        turn_id_captured = False
        try:
            events = session.send_turn(transcript, stt_source="touch")
            async for event in events:
                if not turn_id_captured:
                    # `active_turn_id` is only meaningful once the async
                    # generator's body has actually started running — reading
                    # it right after `send_turn()` returns, before the first
                    # `await` inside that generator has executed, always saw
                    # the pre-call value and fell back to the same id on
                    # every turn.
                    self._turn_id = str(
                        getattr(session, "active_turn_id", None)
                        or f"touch-{self.connection_id}"
                    )
                    turn_id_captured = True
                    await self._apply_pending_interrupt()
                kind = event.get("type")
                if kind in ("text_delta",):
                    self._response_text += str(event.get("text") or "")
                    self._publish(self._response_phase())
                elif kind in ("text_replace", "message_complete"):
                    text = str(event.get("text") or "")
                    if kind == "text_replace" or text:
                        self._response_text = text
                    self._publish(self._response_phase())
                elif kind == "status":
                    self._publish(
                        self._response_phase(),
                        status_text=str(event.get("text") or "Thinking"),
                    )
                elif kind == "audio_start":
                    await self._open_response_audio(event)
                elif kind == "audio_chunk":
                    data = event.get("data")
                    if self._audio_open and isinstance(data, bytes) and data:
                        await self._sender.send_audio_chunk(data)
                elif kind == "audio_end":
                    if event.get("final") is True and self._audio_open:
                        await self._sender.send_audio_end(turn_id=self._turn_id or "")
                        self._audio_open = False
                elif kind in ("audio_abort", "turn_interrupted"):
                    await self._abort_response_audio(str(kind))
                    completed = True
                    self._publish(
                        "complete",
                        status_text="Stopped",
                    )
                    break
                elif kind == "error":
                    await self._abort_response_audio("error")
                    self._publish(
                        "error",
                        status_text=str(event.get("error") or "Hermes error"),
                    )
                    return
                elif kind == "turn_end":
                    if self._audio_open:
                        await self._sender.send_audio_end(turn_id=self._turn_id or "")
                        self._audio_open = False
                    completed = True
                    self._publish(
                        "complete",
                        status_text=(
                            AUDIO_UNAVAILABLE_STATUS
                            if self._audio_unavailable
                            else None
                        ),
                    )
                    break
            if not completed:
                # The stream ended without Home ever being terminal. The
                # prompt may or may not have been accepted, so it is dropped:
                # a possibly-answered question is never asked twice.
                await self._abort_response_audio("incomplete")
                self._publish("error", status_text="Turn ended without a reply")
        except asyncio.CancelledError:
            await self._abort_response_audio("cancelled")
            raise
        except Exception:
            logger.debug("touch Home turn failed", exc_info=True)
            await self._abort_response_audio("connection lost")
            # The binding is dead. Keeping it around would make the next
            # mic_start reuse a session that can never complete a turn again.
            self._session = None
            self._publish("disconnected", status_text="Reconnecting to Hermes")
        finally:
            self._interrupt_pending = False
            aclose = getattr(events, "aclose", None)
            if callable(aclose):
                with contextlib.suppress(Exception):
                    await aclose()

    async def _open_response_audio(self, event: dict[str, Any]) -> None:
        """Start private response audio; never claim speech on the strength of it."""
        if self._audio_open:
            return
        try:
            await self._sender.send_audio_start(
                turn_id=self._turn_id or "",
                sample_rate=int(event.get("sample_rate", 0) or 0),
                channels=int(event.get("channels", 0) or 0),
                sample_width=int(event.get("sample_width", 0) or 0),
            )
        except Exception:
            self._audio_unavailable = True
            self._publish(self._response_phase(), status_text=AUDIO_UNAVAILABLE_STATUS)
            return
        self._audio_open = True
        # `speaking` waits for the endpoint's own playback acknowledgement.
        self._publish("buffering")

    async def _abort_response_audio(self, reason: str) -> None:
        if not self._audio_open:
            return
        self._audio_open = False
        with contextlib.suppress(Exception):
            await self._sender.send_audio_abort(
                turn_id=self._turn_id or "", reason=reason[:256]
            )

    async def _apply_pending_interrupt(self) -> None:
        """Latch one stop and spend it once the accepted turn ID exists."""
        if not self._interrupt_pending or self._turn_id is None:
            return
        session = self._session
        interrupt = getattr(session, "interrupt_active_turn", None)
        if not callable(interrupt):
            return
        self._interrupt_pending = False
        with contextlib.suppress(Exception):
            await interrupt()

    def _turn_active(self) -> bool:
        return self._turn_task is not None and not self._turn_task.done()

    def _response_phase(self) -> str:
        if self._playback_started:
            return "speaking"
        if self._audio_open:
            return "buffering"
        return "thinking"

    # ---- state ---------------------------------------------------------

    def _discard_capture(self) -> None:
        capture = self._capture
        if capture is not None:
            capture.discard()
        self._capture = None

    def _publish(
        self,
        state: str,
        *,
        response_text: str | None = None,
        transcript_text: str | None = None,
        status_text: str | None = None,
    ) -> None:
        if response_text is not None:
            self._response_text = response_text
        if transcript_text is not None:
            self._transcript_text = transcript_text
        if self._last_published_state == "error" and state != "idle":
            # ERROR->anything-but-IDLE is not a legal edge in the shared
            # reducer. Clear the error first so the real transition lands.
            self._last_published_state = "idle"
            with contextlib.suppress(Exception):
                self.publisher.publish(
                    state="idle",
                    response_text=self._response_text,
                    transcript_text=self._transcript_text,
                    status_text=None,
                    account=self._account,
                )
        self._last_published_state = state
        with contextlib.suppress(Exception):
            self.publisher.publish(
                state=state,
                response_text=self._response_text,
                transcript_text=self._transcript_text,
                status_text=status_text,
                account=self._account,
            )

    async def _send_control(self, payload: dict[str, object]) -> bool:
        send = getattr(self._sender, "send_control", None)
        if not callable(send):
            return False
        try:
            return bool(await send(payload))
        except Exception:
            return False

    async def _reject(self, capture_id: str, reason: str) -> None:
        await self._send_control(
            {
                "type": "mic_reject",
                "schema": 1,
                "capture_id": capture_id,
                "reason": reason,
            }
        )

    # ---- teardown ------------------------------------------------------

    async def close(self) -> None:
        """Drop everything transient. Never resubmit anything on the way out."""
        if self._closed:
            return
        self._closed = True
        self._discard_capture()
        self._transcript_text = ""
        self._response_text = ""
        self._interrupt_pending = False
        task = self._turn_task
        self._turn_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(task, TOUCH_SHUTDOWN_TIMEOUT)
        session, self._session = self._session, None
        if session is not None:
            close = getattr(session, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(close(), TOUCH_SHUTDOWN_TIMEOUT)
