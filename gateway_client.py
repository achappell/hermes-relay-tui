"""Single-reader JSON-RPC client for Hermes' standard gateway WebSocket.

The gateway sends replies and session events over the same socket.  This
module owns the one receive loop, matches replies by JSON-RPC request ID, and
leaves event interpretation to :mod:`gateway_session`.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
from itertools import count
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import config
from client import ProtocolError, TransportError, transport_error_for
from diagnostics import logger as diagnostic_logger, summarize_payload


class GatewayProtocolError(ProtocolError):
    """The gateway sent a frame that cannot be used safely."""


class GatewayRPCError(GatewayProtocolError):
    """A standard gateway request was rejected."""

    def __init__(self, operation: str, code: Any = "unknown") -> None:
        self.operation = operation
        self.code = str(code)
        super().__init__(f"gateway {operation} rejected ({self.code})")


class GatewayUnsupportedError(GatewayProtocolError):
    """The gateway asked this client to use a deliberately deferred feature."""


class GatewayTransportError(TransportError):
    """A network failure at the gateway WebSocket boundary."""


_CLOSE_SENTINEL = object()
STANDARD_HERMES_VERSION = "0.21.1"
STANDARD_HERMES_COMMIT = "2237be355906fbe6065ce1815711eee52b2d646e"
STANDARD_GATEWAY_PATH = "/api/ws"
STANDARD_AUDIO_PATH = "/api/audio/speak-stream"
GATEWAY_CONNECT_TIMEOUT = 10.0
GATEWAY_REQUEST_TIMEOUT = 30.0
GATEWAY_CLOSE_TIMEOUT = 3.0
GATEWAY_HEARTBEAT_INTERVAL = 15.0


def gateway_url_with_token(url: str, token: str) -> str:
    """Return a gateway URL using the legacy query-token authentication mode."""

    parsed = urlsplit(str(url))
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if key.lower() != "token"]
    query.append(("token", token))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def redact_gateway_url(url: str) -> str:
    """Remove token values before a gateway URL reaches diagnostics."""

    parsed = urlsplit(str(url))
    query = [
        (key, "REDACTED" if key.lower() == "token" else value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _gateway_connection_kwargs(connect: Any) -> dict[str, Any]:
    """Build websocket tuning options without the voice-session auth header."""

    try:
        parameters = inspect.signature(connect).parameters
    except (TypeError, ValueError):
        parameters = {}
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    kwargs: dict[str, Any] = {"max_size": 256 * 1024}
    for name, value in (
        ("ping_interval", config.WEBSOCKET_PING_INTERVAL),
        ("ping_timeout", config.WEBSOCKET_PING_TIMEOUT),
    ):
        if name in parameters or accepts_kwargs:
            kwargs[name] = value
    return kwargs


class GatewayClient:
    """Own one gateway socket and its single receive task."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        connect_factory: Any | None = None,
    ) -> None:
        self.url = str(url)
        self.token = token
        self._connect_factory = connect_factory
        self._connect_cm: Any = None
        self.ws: Any = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[str, tuple[asyncio.Future[Any], str]] = {}
        self._events: asyncio.Queue[Any] = asyncio.Queue()
        self._send_lock = asyncio.Lock()
        self._ready: asyncio.Future[dict[str, Any]] | None = None
        self._closed = asyncio.Event()
        self._terminal_error: BaseException | None = None
        self._sentinel_queued = False
        self._closing = False
        self._connected = False
        self._request_ids = count(1)

    @property
    def is_connected(self) -> bool:
        """Whether the ready event has arrived and the reader is alive."""

        return self._connected and not self._closed.is_set()

    async def connect(self) -> dict[str, Any]:
        """Open the socket and wait for ``gateway.ready``."""

        if self._connect_cm is not None or self.ws is not None:
            await self.close()
        if self._reader_task is not None and not self._reader_task.done():
            raise GatewayTransportError(
                "gateway connect",
                RuntimeError("previous gateway reader is still shutting down"),
            )

        connect = self._connect_factory or config.connect_factory()
        self._reset_runtime_state()
        _require_gateway_path(self.url)
        sent_url = gateway_url_with_token(self.url, self.token)
        diagnostic_logger.debug(
            "gateway.connect.start url=%s", redact_gateway_url(sent_url)
        )
        try:
            async with asyncio.timeout(GATEWAY_CONNECT_TIMEOUT):
                self._connect_cm = connect(sent_url, **_gateway_connection_kwargs(connect))
                self.ws = await self._connect_cm.__aenter__()
                loop = asyncio.get_running_loop()
                self._ready = loop.create_future()
                self._reader_task = asyncio.create_task(
                    self._read_frames(),
                    name="hermes gateway websocket reader",
                )
                ready = await self._ready
            self._connected = True
            diagnostic_logger.debug(
                "gateway.connect.ready event=%s %s",
                ready.get("type", "gateway.ready"),
                summarize_payload(ready),
            )
            return ready
        except asyncio.TimeoutError as exc:
            error = GatewayTransportError(
                "gateway connect", TimeoutError("gateway.ready timed out")
            )
            diagnostic_logger.error("gateway.connect.timeout")
            try:
                await self.close()
            except Exception:
                pass
            raise error from exc
        except BaseException:
            diagnostic_logger.error("gateway.connect.failed")
            try:
                await self.close()
            except Exception:
                pass
            raise

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send one JSON-RPC request and await its matching reply."""

        if not self.is_connected or self.ws is None:
            raise GatewayTransportError(
                f"gateway {method}", ConnectionError("gateway is not connected")
            )
        request_id = str(next(self._request_ids))
        loop = asyncio.get_running_loop()
        reply: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = (reply, method)
        frame = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        )
        diagnostic_logger.debug(
            "gateway.request.send id=%s method=%s param_keys=%s",
            request_id,
            method,
            ",".join(sorted(str(key) for key in (params or {}))) or "-",
        )
        try:
            async with self._send_lock:
                await self.ws.send(frame)
        except BaseException as exc:
            self._pending.pop(request_id, None)
            error = self._as_transport_error(f"gateway {method} send", exc)
            if error is not None:
                self._fail(error)
                raise error from exc
            raise
        try:
            async with asyncio.timeout(GATEWAY_REQUEST_TIMEOUT):
                result = await reply
            diagnostic_logger.debug(
                "gateway.request.reply id=%s method=%s %s",
                request_id,
                method,
                summarize_payload(result),
            )
            return result
        except asyncio.TimeoutError as exc:
            error = GatewayTransportError(
                f"gateway {method}",
                TimeoutError(f"gateway {method} timed out"),
            )
            diagnostic_logger.error(
                "gateway.request.timeout id=%s method=%s", request_id, method
            )
            self._fail(error)
            raise error from exc
        finally:
            self._pending.pop(request_id, None)

    async def next_event(self) -> dict[str, Any]:
        """Return the next gateway event, or raise the terminal socket error."""

        event = await self._events.get()
        if event is _CLOSE_SENTINEL:
            error = self._terminal_error
            if error is not None:
                raise error
            raise GatewayTransportError(
                "gateway receive", ConnectionError("gateway connection closed")
            )
        return event

    async def wait_for_disconnect(self) -> None:
        """Wait for socket liveness without consuming application frames."""

        if self.ws is None:
            raise GatewayTransportError(
                "gateway connection wait", ConnectionError("gateway is not connected")
            )
        wait_closed = getattr(self.ws, "wait_closed", None)
        if callable(wait_closed):
            close_wait = asyncio.create_task(wait_closed())
            reader_wait = asyncio.create_task(self._closed.wait())
            heartbeat = asyncio.create_task(self._heartbeat())
            try:
                done, _pending = await asyncio.wait(
                    {close_wait, reader_wait, heartbeat},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if reader_wait in done:
                    return
                if heartbeat in done:
                    heartbeat.result()
                    return
                await close_wait
            except BaseException as exc:
                error = self._as_transport_error("gateway connection wait", exc)
                if error is not None:
                    self._fail(error)
                    raise error from exc
                raise
            finally:
                for task in (close_wait, reader_wait, heartbeat):
                    if not task.done():
                        task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            if not self._closing and not self._closed.is_set():
                self._fail(
                    GatewayTransportError(
                        "gateway connection", ConnectionError("gateway closed")
                    )
                )
        else:
            await self._heartbeat_until_closed()

    async def ping(self) -> dict[str, Any]:
        """Check the gateway application path, not only the WebSocket socket."""

        result = await self.request("gateway.ping")
        return result if isinstance(result, dict) else {}

    async def _heartbeat(self) -> None:
        while self.is_connected:
            await asyncio.sleep(GATEWAY_HEARTBEAT_INTERVAL)
            if not self.is_connected:
                return
            try:
                await self.ping()
            except BaseException as exc:
                error = self._as_transport_error("gateway heartbeat", exc)
                if error is None:
                    raise
                self._fail(error)
                return

    async def _heartbeat_until_closed(self) -> None:
        heartbeat = asyncio.create_task(self._heartbeat())
        try:
            await self._closed.wait()
        finally:
            if not heartbeat.done():
                heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def close(self) -> None:
        """Stop the reader and close the gateway context manager."""

        self._closing = True
        self._connected = False
        close_error = GatewayTransportError(
            "gateway close", ConnectionError("gateway closed")
        )
        self._fail(close_error)
        reader = self._reader_task
        if reader is not None and not reader.done() and reader is not asyncio.current_task():
            reader.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(reader), GATEWAY_CLOSE_TIMEOUT)
            except asyncio.TimeoutError:
                diagnostic_logger.debug("gateway.reader_close.timeout")
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
                    GATEWAY_CLOSE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                diagnostic_logger.debug("gateway.close.timeout")
            except BaseException as exc:
                error = self._as_transport_error("gateway close", exc)
                if error is not None:
                    diagnostic_logger.debug(
                        "gateway.close.failed type=%s", type(error).__name__
                    )
                else:
                    diagnostic_logger.debug(
                        "gateway.close.failed type=%s", type(exc).__name__
                    )
        self._closing = False

    async def _read_frames(self) -> None:
        try:
            while True:
                frame = await self.ws.recv()
                if isinstance(frame, bytes):
                    # The standard gateway is JSON-only. Binary frames are
                    # ignored here rather than mistaken for response audio.
                    diagnostic_logger.debug(
                        "gateway.frame.binary_ignored bytes=%d", len(frame)
                    )
                    continue
                try:
                    payload = json.loads(frame)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise GatewayProtocolError("gateway sent invalid JSON") from exc
                if not isinstance(payload, dict):
                    raise GatewayProtocolError("gateway sent a non-object JSON frame")
                self._dispatch_frame(payload)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            error = self._as_reader_error(exc)
            self._fail(error)
        finally:
            self._closed.set()
            self._queue_close_sentinel()

    def _dispatch_frame(self, payload: dict[str, Any]) -> None:
        if payload.get("jsonrpc") != "2.0":
            raise GatewayProtocolError("gateway frame is not JSON-RPC 2.0")
        if "id" in payload and type(payload.get("id")) not in {str, int}:
            raise GatewayProtocolError("gateway frame has an invalid request ID")
        has_result = "result" in payload
        has_error = "error" in payload
        if "id" in payload and has_result and has_error:
            raise GatewayProtocolError(
                "gateway reply contains both result and error"
            )
        if "id" in payload and (has_result or has_error):
            request_id = str(payload.get("id"))
            pending = self._pending.get(request_id)
            if pending is None:
                diagnostic_logger.debug(
                    "gateway.reply.unmatched id=%s", request_id
                )
                return
            future, method = pending
            if future.done():
                return
            error_payload = payload.get("error")
            if isinstance(error_payload, dict):
                future.set_exception(
                    GatewayRPCError(method, error_payload.get("code", "unknown"))
                )
            elif "error" in payload:
                future.set_exception(GatewayRPCError(method))
            else:
                future.set_result(payload.get("result"))
            return

        if "id" in payload:
            request_id = str(payload.get("id"))
            pending = self._pending.get(request_id)
            if pending is not None and not pending[0].done():
                pending[0].set_exception(
                    GatewayProtocolError(
                        "gateway reply has neither result nor error"
                    )
                )
                return

        if payload.get("method") != "event":
            self._events.put_nowait(
                {
                    "type": "unknown_event",
                    "event_type": str(payload.get("method") or "gateway.frame"),
                    "payload_keys": sorted(str(key) for key in payload),
                }
            )
            return

        params = payload.get("params")
        if not isinstance(params, dict):
            raise GatewayProtocolError("gateway event params are not an object")
        event_type = str(params.get("type") or params.get("event") or "").strip()
        if not event_type:
            raise GatewayProtocolError("gateway event has no type")
        raw_event_payload = params.get("payload")
        if raw_event_payload is not None and not isinstance(raw_event_payload, dict):
            raise GatewayProtocolError("gateway event payload is not an object")
        if event_type == "gateway.ready" and not isinstance(raw_event_payload, dict):
            raise GatewayProtocolError("gateway.ready payload is not an object")
        event_payload = dict(raw_event_payload) if isinstance(raw_event_payload, dict) else {}
        event: dict[str, Any] = {
            "type": event_type,
            "payload": event_payload,
        }
        outer_session_id = params.get("session_id")
        payload_session_id = event_payload.get("session_id")
        for identity in (outer_session_id, payload_session_id):
            if identity not in (None, "") and not isinstance(identity, str):
                raise GatewayProtocolError(
                    "gateway event session identity is not a string"
                )
        if (
            outer_session_id not in (None, "")
            and payload_session_id not in (None, "")
            and str(outer_session_id) != str(payload_session_id)
        ):
            raise GatewayProtocolError(
                "gateway event has conflicting session identities"
            )
        session_id = outer_session_id or payload_session_id
        if session_id not in (None, "") and not isinstance(session_id, str):
            raise GatewayProtocolError("gateway event session identity is not a string")
        if session_id not in (None, ""):
            event["session_id"] = str(session_id)
        for key in ("turn_id", "correlation_id", "request_id"):
            value = params.get(key)
            if value is None and isinstance(event_payload, dict):
                value = event_payload.get(key)
            if value not in (None, ""):
                if not isinstance(value, str):
                    raise GatewayProtocolError(
                        f"gateway event {key} is not a string"
                    )
                event[key] = value
        if params.get("seq") is not None:
            sequence = params.get("seq")
            if type(sequence) is not int or sequence < 1:
                raise GatewayProtocolError("gateway event sequence is invalid")
            event["seq"] = sequence
        diagnostic_logger.debug(
            "gateway.event.recv type=%s session_id=%s %s",
            event_type,
            event.get("session_id", "-"),
            summarize_payload(event_payload),
        )
        if event_type == "gateway.ready":
            if self._ready is None:
                raise GatewayProtocolError("gateway.ready arrived without a handshake")
            if self._ready.done():
                raise GatewayProtocolError("gateway sent duplicate gateway.ready")
            self._ready.set_result(event)
            # connect() returns the ready envelope. Do not leave it in the
            # application event stream as stale work for the first turn.
            return
        self._events.put_nowait(event)

    def _reset_runtime_state(self) -> None:
        self._pending.clear()
        self._events = asyncio.Queue()
        self._closed = asyncio.Event()
        self._terminal_error = None
        self._sentinel_queued = False
        self._connected = False
        self._reader_task = None

    def _queue_close_sentinel(self) -> None:
        if not self._sentinel_queued:
            self._sentinel_queued = True
            self._events.put_nowait(_CLOSE_SENTINEL)

    def _fail(self, error: BaseException) -> None:
        if self._terminal_error is None:
            self._terminal_error = error
        self._connected = False
        self._closed.set()
        if self._ready is not None and not self._ready.done():
            self._ready.set_exception(self._terminal_error)
        for future, _method in list(self._pending.values()):
            if not future.done():
                future.set_exception(self._terminal_error)
        self._queue_close_sentinel()

    def _as_reader_error(self, exc: BaseException) -> BaseException:
        if isinstance(exc, GatewayProtocolError):
            return exc
        error = self._as_transport_error("gateway receive", exc)
        if error is not None:
            return error
        return GatewayProtocolError("gateway reader failed")

    @staticmethod
    def _as_transport_error(operation: str, exc: BaseException) -> GatewayTransportError | None:
        error = transport_error_for(operation, exc)
        if error is None:
            return None
        if isinstance(error, GatewayTransportError):
            return error
        return GatewayTransportError(operation, exc)


__all__ = [
    "GATEWAY_CLOSE_TIMEOUT",
    "GATEWAY_CONNECT_TIMEOUT",
    "GATEWAY_HEARTBEAT_INTERVAL",
    "GATEWAY_REQUEST_TIMEOUT",
    "GatewayClient",
    "GatewayProtocolError",
    "GatewayRPCError",
    "GatewayTransportError",
    "GatewayUnsupportedError",
    "STANDARD_GATEWAY_PATH",
    "STANDARD_AUDIO_PATH",
    "STANDARD_HERMES_COMMIT",
    "STANDARD_HERMES_VERSION",
    "gateway_url_with_token",
    "redact_gateway_url",
]


def _require_gateway_path(url: str) -> None:
    path = urlsplit(str(url)).path.rstrip("/") or "/"
    if path != STANDARD_GATEWAY_PATH:
        raise GatewayProtocolError(
            f"standard gateway requires {STANDARD_GATEWAY_PATH}, got {path}"
        )
