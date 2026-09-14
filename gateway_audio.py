"""Streaming response-audio sidecar for Hermes' standard gateway.

The standard ``/api/ws`` gateway is JSON-only.  Hermes exposes response TTS
through a second WebSocket, ``/api/audio/speak-stream``: text JSON goes in and
signed 16-bit PCM comes back.  This module owns that second socket and emits
the same normalized audio events consumed by the existing TUI playback path.

It deliberately knows nothing about Textual.  A gateway audio failure is a
side-lane failure, not proof that the text turn was lost.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import config
from client import ProtocolError, TransportError, transport_error_for
from diagnostics import logger as diagnostic_logger
from gateway_client import (
    STANDARD_AUDIO_PATH,
    STANDARD_GATEWAY_PATH,
    _gateway_connection_kwargs,
)
from timing import normalize_speech_timing


class GatewayAudioProtocolError(ProtocolError):
    """The audio sidecar sent a frame that cannot be used safely."""


class GatewayAudioTransportError(TransportError):
    """The audio sidecar could not be opened or kept alive."""


_CLOSE_SENTINEL = object()

DEFAULT_AUDIO_QUEUE_SIZE = 64
AUDIO_CONNECT_TIMEOUT = 3.0
AUDIO_SEND_TIMEOUT = 3.0
AUDIO_DRAIN_TIMEOUT = 8.0
AUDIO_CLOSE_TIMEOUT = 3.0


def gateway_audio_url_with_token(
    url: str,
    token: str,
    *,
    profile: str | None = None,
) -> str:
    """Derive the standard Hermes TTS URL from a gateway ``/api/ws`` URL."""

    parsed = urlsplit(str(url))
    path = parsed.path.rstrip("/")
    if path.endswith("/api/ws"):
        path = f"{path[:-len('/ws')]}/audio/speak-stream"
    elif path.endswith("/ws"):
        path = f"{path[:-len('/ws')]}/audio/speak-stream"
    else:
        path = f"{path}/audio/speak-stream" if path else "/audio/speak-stream"

    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower == "token":
            continue
        if key_lower == "profile" and str(profile or "").strip():
            continue
        query.append((key, value))
    query.append(("token", token))
    selected_profile = str(profile or "").strip()
    if selected_profile:
        query.append(("profile", selected_profile))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, path, urlencode(query), parsed.fragment)
    )


def redact_gateway_audio_url(url: str) -> str:
    """Remove the bearer token before an audio URL reaches diagnostics."""

    parsed = urlsplit(str(url))
    query = [
        (key, "REDACTED" if key.lower() == "token" else value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


class GatewayAudioStream:
    """Own one authenticated response-audio WebSocket and its one reader."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        profile: str | None = None,
        connect_factory: Any | None = None,
        queue_size: int = DEFAULT_AUDIO_QUEUE_SIZE,
    ) -> None:
        self.url = str(url)
        self.token = token
        self.profile = profile
        self._connect_factory = connect_factory
        self._queue_size = max(1, int(queue_size))
        self._connect_cm: Any = None
        self.ws: Any = None
        self._reader_task: asyncio.Task[None] | None = None
        self._events: asyncio.Queue[Any] = asyncio.Queue(maxsize=self._queue_size)
        self._send_lock = asyncio.Lock()
        self._closed = asyncio.Event()
        self._closing = False
        self._connected = False
        self._started = False
        self._terminal_event = False
        self._finish_sent = False
        self._sentinel_queued = False
        self._pcm_remainder = b""
        self._saw_pcm = False

    @property
    def is_connected(self) -> bool:
        return self._connected and not self._closed.is_set()

    @property
    def started(self) -> bool:
        return self._started

    async def connect(self) -> None:
        """Open the sidecar and start its single receive task."""

        if self._connect_cm is not None or self.ws is not None:
            await self.close()

        connect = self._connect_factory or config.connect_factory()
        _require_gateway_path(self.url)
        audio_url = gateway_audio_url_with_token(
            self.url,
            self.token,
            profile=self.profile,
        )
        diagnostic_logger.debug(
            "gateway.audio.connect.start url=%s",
            redact_gateway_audio_url(audio_url),
        )
        self._reset_runtime_state()
        try:
            self._connect_cm = connect(
                audio_url,
                **_gateway_connection_kwargs(connect),
            )
            self.ws = await self._connect_cm.__aenter__()
            self._connected = True
            self._reader_task = asyncio.create_task(
                self._read_frames(),
                name="hermes gateway audio reader",
            )
        except BaseException as exc:
            error = self._as_transport_error("gateway audio connect", exc)
            await self.close()
            if error is not None:
                raise error from exc
            raise

    async def open(self, *, timeout: float = AUDIO_CONNECT_TIMEOUT) -> None:
        """Open with a bounded wait so text never waits forever for TTS."""

        async with asyncio.timeout(max(0.01, float(timeout))):
            await self.connect()

    async def send_text(self, text: str) -> None:
        """Feed one new text fragment to the server-side TTS stream."""

        text = str(text or "")
        if not text or not self.is_connected or self.ws is None:
            return
        await self._send_json({"text": text}, operation="gateway audio text")

    async def finish(self) -> None:
        """Tell Hermes that no more text fragments belong to this turn."""

        if self._finish_sent or not self.is_connected or self.ws is None:
            return
        self._finish_sent = True
        await self._send_json({"done": True}, operation="gateway audio finish")

    async def stop(self) -> None:
        """Stop server-side speech and discard late frames."""

        if self.is_connected and self.ws is not None:
            with contextlib.suppress(Exception):
                await self._send_json({"stop": True}, operation="gateway audio stop")
        await self.close()

    async def next_event(self) -> dict[str, Any]:
        """Return the next normalized audio event."""

        event = await self._events.get()
        if event is _CLOSE_SENTINEL:
            raise GatewayAudioTransportError(
                "gateway audio receive",
                ConnectionError("audio sidecar closed"),
            )
        return event

    async def close(self) -> None:
        """Cancel the reader and close the sidecar within a bounded wait."""

        self._closing = True
        self._connected = False
        reader = self._reader_task
        if (
            reader is not None
            and not reader.done()
            and reader is not asyncio.current_task()
        ):
            reader.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(reader),
                    AUDIO_CLOSE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                diagnostic_logger.debug("gateway.audio.reader_close.timeout")
            except asyncio.CancelledError:
                pass
        if reader is None or reader.done():
            self._reader_task = None

        context = self._connect_cm
        self._connect_cm = None
        self.ws = None
        if context is not None:
            try:
                await asyncio.wait_for(
                    context.__aexit__(None, None, None),
                    AUDIO_CLOSE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                diagnostic_logger.debug("gateway.audio.close.timeout")
            except Exception as exc:
                diagnostic_logger.debug(
                    "gateway.audio.close.failed type=%s",
                    type(exc).__name__,
                )
        self._closed.set()
        self._queue_close_sentinel()
        self._closing = False

    async def _send_json(self, payload: dict[str, Any], *, operation: str) -> None:
        frame = json.dumps(payload)
        try:
            async with asyncio.timeout(AUDIO_SEND_TIMEOUT):
                async with self._send_lock:
                    await self.ws.send(frame)
        except BaseException as exc:
            error = self._as_transport_error(operation, exc)
            if error is not None:
                raise error from exc
            raise

    async def _read_frames(self) -> None:
        try:
            while True:
                frame = await self.ws.recv()
                if isinstance(frame, bytes):
                    await self._handle_binary(frame)
                    if self._terminal_event:
                        return
                    continue
                await self._handle_json(frame)
                if self._terminal_event:
                    return
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            if not self._closing and not self._terminal_event:
                await self._mark_unavailable(self._reason_for_error(exc))
        finally:
            self._closed.set()
            if not self._closing:
                self._queue_close_sentinel()

    async def _handle_binary(self, frame: bytes) -> None:
        if self._terminal_event:
            diagnostic_logger.debug(
                "gateway.audio.binary_late_ignored bytes=%d",
                len(frame),
            )
            return
        if not frame:
            diagnostic_logger.debug("gateway.audio.binary_empty_ignored")
            return
        if not self._started:
            await self._mark_unavailable("binary before audio start")
            return
        pcm = self._pcm_remainder + bytes(frame)
        complete_bytes = len(pcm) - (len(pcm) % 2)
        self._pcm_remainder = pcm[complete_bytes:]
        if not complete_bytes:
            return
        self._saw_pcm = True
        await self._events.put({"type": "audio_chunk", "data": pcm[:complete_bytes]})

    async def _handle_json(self, frame: Any) -> None:
        try:
            payload = json.loads(frame)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            await self._mark_unavailable("invalid audio JSON")
            raise GatewayAudioProtocolError("audio sidecar sent invalid JSON") from exc
        if not isinstance(payload, dict):
            await self._mark_unavailable("invalid audio frame")
            raise GatewayAudioProtocolError("audio sidecar sent a non-object frame")

        event_type = str(payload.get("type") or "").strip().lower()
        if event_type == "start":
            self._handle_start(payload)
            return
        if event_type == "speech_timing":
            timing_payload = payload.get("payload")
            if not isinstance(timing_payload, dict):
                diagnostic_logger.debug(
                    "gateway.audio.speech_timing.ignored reason=missing_payload"
                )
                return
            timing = normalize_speech_timing(timing_payload)
            if timing is None:
                diagnostic_logger.debug(
                    "gateway.audio.speech_timing.ignored reason=invalid_payload"
                )
                return
            await self._events.put(timing.as_event())
            return
        if event_type == "end":
            if not self._started:
                await self._mark_unavailable("audio ended before start")
                return
            if self._pcm_remainder:
                await self._mark_unavailable("audio ended with an incomplete PCM sample")
                return
            if not self._saw_pcm:
                await self._mark_unavailable("audio stream contained no PCM")
                return
            await self._events.put({"type": "audio_end"})
            self._terminal_event = True
            return
        if event_type == "fallback":
            await self._mark_unavailable("server audio fallback")
            return
        diagnostic_logger.debug(
            "gateway.audio.event.ignored type=%s payload_keys=%s",
            event_type or "missing",
            ",".join(sorted(str(key) for key in payload)) or "-",
        )

    def _handle_start(self, payload: dict[str, Any]) -> None:
        if self._started:
            raise GatewayAudioProtocolError("audio sidecar sent duplicate start")
        try:
            sample_rate = self._bounded_int(
                payload.get("sample_rate"),
                name="sample rate",
                maximum=384_000,
            )
            channels = self._bounded_int(
                payload.get("channels"),
                name="channel count",
                maximum=32,
            )
            sample_width = self._bounded_int(
                payload.get("sample_width", 2),
                name="sample width",
                maximum=8,
            )
        except (TypeError, ValueError) as exc:
            raise GatewayAudioProtocolError("audio start metadata is invalid") from exc
        byte_order = str(payload.get("byte_order", "little")).strip().lower()
        if byte_order not in {"little", "le", "little-endian"}:
            raise GatewayAudioProtocolError(
                "audio start metadata must declare little-endian PCM"
            )
        if sample_rate <= 0 or channels != 1 or sample_width != 2:
            raise GatewayAudioProtocolError("audio sidecar requires signed 16-bit PCM")
        self._started = True
        self._events.put_nowait(
            {
                "type": "audio_start",
                "sample_rate": sample_rate,
                "channels": channels,
                "sample_width": sample_width,
            }
        )

    @staticmethod
    def _bounded_int(value: Any, *, name: str, maximum: int) -> int:
        if type(value) is not int or value <= 0 or value > maximum:
            raise ValueError(f"{name} is invalid")
        return value

    async def _mark_unavailable(self, reason: str) -> None:
        if self._terminal_event:
            return
        self._terminal_event = True
        await self._events.put(
            {
                "type": "audio_unavailable",
                "reason": str(reason or "audio sidecar unavailable"),
            }
        )

    @staticmethod
    def _reason_for_error(error: BaseException) -> str:
        if isinstance(error, GatewayAudioProtocolError):
            return str(error)
        return "audio sidecar disconnected"

    def _queue_close_sentinel(self) -> None:
        if self._sentinel_queued:
            return
        if self._events.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._events.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            self._events.put_nowait(_CLOSE_SENTINEL)
            self._sentinel_queued = True

    def _reset_runtime_state(self) -> None:
        self._events = asyncio.Queue(maxsize=self._queue_size)
        self._closed = asyncio.Event()
        self._closing = False
        self._connected = False
        self._started = False
        self._terminal_event = False
        self._finish_sent = False
        self._sentinel_queued = False
        self._pcm_remainder = b""
        self._saw_pcm = False
        self._reader_task = None

    @staticmethod
    def _as_transport_error(
        operation: str,
        error: BaseException,
    ) -> GatewayAudioTransportError | None:
        converted = transport_error_for(operation, error)
        if converted is None:
            return None
        if isinstance(converted, GatewayAudioTransportError):
            return converted
        return GatewayAudioTransportError(operation, error)


__all__ = [
    "AUDIO_CLOSE_TIMEOUT",
    "AUDIO_CONNECT_TIMEOUT",
    "AUDIO_DRAIN_TIMEOUT",
    "AUDIO_SEND_TIMEOUT",
    "DEFAULT_AUDIO_QUEUE_SIZE",
    "GatewayAudioProtocolError",
    "GatewayAudioStream",
    "GatewayAudioTransportError",
    "STANDARD_AUDIO_PATH",
    "STANDARD_GATEWAY_PATH",
    "gateway_audio_url_with_token",
    "redact_gateway_audio_url",
]


def _require_gateway_path(url: str) -> None:
    path = urlsplit(str(url)).path.rstrip("/") or "/"
    if path != STANDARD_GATEWAY_PATH:
        raise GatewayAudioProtocolError(
            f"standard audio requires gateway path {STANDARD_GATEWAY_PATH}, got {path}"
        )
