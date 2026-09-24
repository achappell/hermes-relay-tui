"""Puck-side adapter for the planned Standard Home bridge route.

The Puck still owns capture and playback. Home owns endpoint authorization,
conversation binding, route selection, and the server-held Hermes credential.
This module is deliberately an opt-in transport: the older direct Hermes
bridge remains available as an explicit rollback until the public Home route
is deployed.

The WebSocket has one reader task. JSON-RPC replies are matched by request ID;
event notifications and binary PCM frames stay in one ordered queue for the
turn generator. That prevents an interrupt or reconnect operation from
starting a second ``recv`` against the same socket.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import uuid
from typing import Any, AsyncIterator
from urllib.parse import urlsplit

import config
from client import ProtocolError, TransportError, transport_error_for

logger = logging.getLogger("hermes_relay_tui.puck_bridge.home_session")

HOME_BRIDGE_PATH = "/api/v1/bridge/ws"
HOME_BRIDGE_SCHEMA = 1
HOME_BRIDGE_CONNECT_TIMEOUT = 10.0
HOME_BRIDGE_REQUEST_TIMEOUT = 15.0
HOME_BRIDGE_CLOSE_TIMEOUT = 3.0
HOME_CLAIM_RETIRE_TIMEOUT = 10.0
# Claim retirement closes the old reader, performs a bounded control reconnect,
# then closes that control client. Bound all three phases at their outer callsite.
HOME_CLAIM_RETIRE_CALL_TIMEOUT_SECONDS = (
    (2 * HOME_BRIDGE_CLOSE_TIMEOUT)
    + HOME_CLAIM_RETIRE_TIMEOUT
    + HOME_BRIDGE_CLOSE_TIMEOUT
    + 1.0
)
HOME_BRIDGE_MAX_SIZE = 256 * 1024
HOME_BRIDGE_QUEUE_MAX = 128
HOME_BRIDGE_MAX_SAMPLE_RATE = 384_000

_CLOSE_SENTINEL = object()
_TERMINAL_EVENT_TYPES = frozenset(
    {
        "turn_complete",
        "turn.complete",
        "turn.completed",
        "turn.end",
        "turn.ended",
        "turn_end",
        "response.complete",
        "response.completed",
    }
)
_INTERRUPTED_EVENT_TYPES = frozenset(
    {"turn_interrupted", "turn.interrupted", "turn.cancelled", "response.interrupted"}
)
_ERROR_EVENT_TYPES = frozenset(
    {
        "error",
        "turn.error",
        "turn.failed",
        "response.error",
        "response.failed",
        "message.error",
    }
)
_COMPLETED_STATUSES = frozenset({"complete", "completed", "done", "success"})
_FAILED_STATUSES = frozenset(
    {
        "error",
        "failed",
        "failure",
        "unavailable",
        "timeout",
        "timed_out",
        "timed-out",
    }
)
_INTERRUPTED_STATUSES = frozenset(
    {"interrupted", "cancelled", "canceled", "aborted", "stopped"}
)
_TERMINAL_STATUSES = _COMPLETED_STATUSES | _FAILED_STATUSES | _INTERRUPTED_STATUSES
_STRUCTURED_PROMPT_EVENT_TYPES = frozenset(
    {
        "prompt_request",
        "approval.request",
        "clarify.request",
        "secret.request",
        "sudo.request",
    }
)


class HomeBridgeProtocolError(ProtocolError):
    """The Home bridge sent a frame that is unsafe to interpret."""


class HomeBridgeAudioError(HomeBridgeProtocolError):
    """The Home bridge violated the bounded PCM framing contract."""


class HomeBridgeRPCError(HomeBridgeProtocolError):
    """A Home bridge method returned a typed JSON-RPC error."""

    def __init__(
        self,
        operation: str,
        code: Any = "unknown",
        delivery: Any = "unknown",
    ) -> None:
        self.operation = operation
        known_codes = {"invalid_request", "authorization_unavailable", "unauthorized", "stale_conversation", "conversation_mismatch", "request_rejected", "transport_unavailable", "transport_timeout", "protocol_error", "capability_unavailable", "hermes_unavailable", "reconnect_required"}
        self.code = code if isinstance(code, str) and code in known_codes else "unknown"
        normalized_delivery = str(delivery or "unknown").strip().lower()
        self.delivery = (
            normalized_delivery
            if normalized_delivery in {"known", "uncertain"}
            else "unknown"
        )
        super().__init__(f"home bridge {operation} rejected ({self.code})")


class HomeBridgeTransportError(TransportError):
    """A network failure at the Home bridge WebSocket boundary."""


class HomeBridgeUnavailableError(HomeBridgeProtocolError):
    """Home authenticated the request path but did not make it ready."""

    def __init__(self, status: Any, reason: Any = "unavailable") -> None:
        self.status = str(status or "unavailable")
        self.reason = str(reason or "unavailable")
        super().__init__(f"home bridge is {self.status}")


def require_home_bridge_url(url: str) -> str:
    """Validate the deployed Home route shape before opening a socket."""

    parsed = urlsplit(str(url).strip())
    path = parsed.path.rstrip("/") or "/"
    if (
        parsed.scheme != "wss"
        or not parsed.netloc
        or not parsed.hostname
        or "@" in parsed.netloc
    ):
        raise ValueError("Home bridge requires a wss:// URL")
    if path != HOME_BRIDGE_PATH:
        raise ValueError(
            f"Home bridge requires {HOME_BRIDGE_PATH}, got {path}"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Home bridge URL must not contain credentials or query data")
    return parsed._replace(path=path).geturl()


def _home_connection_kwargs(connect: Any, credential: str) -> dict[str, Any]:
    """Build websocket options for Device-header authentication."""

    try:
        parameters = inspect.signature(connect).parameters
    except (TypeError, ValueError):
        parameters = {}
    header_name = (
        "additional_headers"
        if "additional_headers" in parameters
        else "extra_headers"
    )
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    kwargs: dict[str, Any] = {
        header_name: {"Authorization": f"Device {credential}"},
        "max_size": HOME_BRIDGE_MAX_SIZE,
    }
    for name, value in (
        ("ping_interval", config.WEBSOCKET_PING_INTERVAL),
        ("ping_timeout", config.WEBSOCKET_PING_TIMEOUT),
    ):
        if name in parameters or accepts_kwargs:
            kwargs[name] = value
    return kwargs


class HomeBridgeClient:
    """Own one Home bridge socket and its single receive task."""

    def __init__(
        self,
        url: str,
        credential: str,
        *,
        connect_factory: Any | None = None,
        request_timeout: float = HOME_BRIDGE_REQUEST_TIMEOUT,
        discard_queued_events_on_close: bool = False,
    ) -> None:
        self.url = require_home_bridge_url(url)
        self.credential = credential
        self._connect_factory = connect_factory
        self._request_timeout = request_timeout
        self._discard_queued_events_on_close = bool(
            discard_queued_events_on_close
        )
        self._connect_cm: Any = None
        self.ws: Any = None
        self._reader_task: asyncio.Task[None] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._pending: dict[str, tuple[asyncio.Future[Any], str]] = {}
        self._events: asyncio.Queue[Any] = asyncio.Queue(
            maxsize=HOME_BRIDGE_QUEUE_MAX
        )
        self._send_lock = asyncio.Lock()
        self._closed = asyncio.Event()
        self._terminal_error: BaseException | None = None
        self._sentinel_queued = False
        self._closing = False
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and not self._closed.is_set()

    @property
    def cleanup_pending(self) -> bool:
        task = self._cleanup_task
        return task is not None and not task.done()

    async def wait_for_cleanup(self) -> None:
        task = self._cleanup_task
        if task is None:
            return
        with contextlib.suppress(BaseException):
            await task
        if self._cleanup_task is task:
            self._cleanup_task = None

    async def connect(self) -> None:
        """Open the socket; readiness is established by ``HomePuckSession``."""

        if self._cleanup_task is not None:
            if self.cleanup_pending:
                raise HomeBridgeTransportError(
                    "home bridge connect",
                    RuntimeError("previous Home bridge cleanup is still pending"),
                )
            await self.wait_for_cleanup()
        if self._connect_cm is not None or self.ws is not None:
            await self.close()
        if self._reader_task is not None and not self._reader_task.done():
            raise HomeBridgeTransportError(
                "home bridge connect",
                RuntimeError("previous Home bridge reader is still shutting down"),
            )

        connect = self._connect_factory or config.connect_factory()
        self._reset_runtime_state()
        try:
            async with asyncio.timeout(HOME_BRIDGE_CONNECT_TIMEOUT):
                self._connect_cm = connect(
                    self.url,
                    **_home_connection_kwargs(connect, self.credential),
                )
                # Device authorization must never follow an HTTP redirect to
                # another origin. The supported asyncio connector exposes its
                # redirect decision before it sends the next handshake.
                if hasattr(self._connect_cm, "process_redirect"):
                    self._connect_cm.process_redirect = lambda exc: exc
                elif self._connect_factory is None:
                    raise HomeBridgeProtocolError("Home requires a WebSocket connector that can refuse redirects")
                self.ws = await self._connect_cm.__aenter__()
                self._reader_task = asyncio.create_task(
                    self._read_frames(),
                    name="puck Home bridge websocket reader",
                )
                self._connected = True
        except asyncio.TimeoutError as exc:
            error = HomeBridgeTransportError(
                "home bridge connect",
                TimeoutError("Home bridge connect timed out"),
            )
            await self.close()
            raise error from exc
        except BaseException as exc:
            error = self._as_transport_error("home bridge connect", exc)
            if error is not None:
                await self.close()
                raise error from exc
            await self.close()
            raise

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Send one JSON-RPC request and await its matching reply."""

        if not self.is_connected or self.ws is None:
            raise HomeBridgeTransportError(
                f"home bridge {method}",
                ConnectionError("Home bridge is not connected"),
            )
        request_id = f"puck-{uuid.uuid4().hex}"
        loop = asyncio.get_running_loop()
        reply: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = (reply, method)
        frame = json.dumps(
            {
                "jsonrpc": "2.0",
                "schema": HOME_BRIDGE_SCHEMA,
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        )
        logger.debug(
            "home bridge request method=%s param_keys=%s",
            method,
            ",".join(sorted(str(key) for key in (params or {}))) or "-",
        )
        try:
            async with self._send_lock:
                await self.ws.send(frame)
        except BaseException as exc:
            self._pending.pop(request_id, None)
            error = self._as_transport_error(f"home bridge {method} send", exc)
            if error is not None:
                self._fail(error)
                raise error from exc
            raise
        try:
            result = await asyncio.wait_for(reply, self._request_timeout)
            logger.debug("home bridge reply method=%s", method)
            return result
        except asyncio.TimeoutError as exc:
            error = HomeBridgeTransportError(
                f"home bridge {method}",
                TimeoutError("Home bridge request timed out"),
            )
            self._fail(error)
            raise error from exc
        finally:
            self._pending.pop(request_id, None)

    async def next_frame(self) -> dict[str, Any] | bytes:
        """Return the next ordered notification or PCM frame."""

        frame = await self._events.get()
        if frame is _CLOSE_SENTINEL:
            error = self._terminal_error
            if error is not None:
                raise error
            raise HomeBridgeTransportError(
                "home bridge receive",
                ConnectionError("Home bridge connection closed"),
            )
        if isinstance(frame, (bytes, dict)):
            return frame
        raise HomeBridgeProtocolError("Home bridge queued an invalid frame")

    async def wait_for_disconnect(self) -> None:
        """Wait for socket liveness without consuming application frames."""

        if self.ws is None:
            raise HomeBridgeTransportError(
                "home bridge connection wait",
                ConnectionError("Home bridge is not connected"),
            )
        await self._closed.wait()

    async def close(self) -> None:
        """Stop the reader and release the websocket context."""

        self._closing = True
        self._connected = False
        self._fail(
            HomeBridgeTransportError(
                "home bridge close",
                ConnectionError("Home bridge closed"),
            )
        )
        reader = self._reader_task
        if (
            reader is not None
            and not reader.done()
            and reader is not asyncio.current_task()
        ):
            reader.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(reader), HOME_BRIDGE_CLOSE_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.debug("home bridge reader close pending")
                self._retain_close_ownership(reader)
                return
            except asyncio.CancelledError:
                logger.debug("home bridge reader close cancelled")
                if not reader.done():
                    self._retain_close_ownership(reader)
                    return
        if reader is None or reader.done():
            self._reader_task = None

        await self._close_context()
        self._closing = False

    def _retain_close_ownership(self, reader: asyncio.Task[None]) -> None:
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return
        self._cleanup_task = asyncio.create_task(
            self._finish_deferred_close(reader),
            name="puck Home bridge deferred close",
        )

    async def _finish_deferred_close(self, reader: asyncio.Task[None]) -> None:
        try:
            with contextlib.suppress(BaseException):
                await reader
            if self._reader_task is reader:
                self._reader_task = None
            await self._close_context()
        finally:
            self._closing = False

    async def _close_context(self) -> None:
        context = self._connect_cm
        self._connect_cm = None
        self.ws = None
        if context is not None:
            try:
                await asyncio.wait_for(
                    context.__aexit__(None, None, None),
                    HOME_BRIDGE_CLOSE_TIMEOUT,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.debug("home bridge context close pending")
            except Exception:
                logger.debug("home bridge context close failed", exc_info=True)

    async def _read_frames(self) -> None:
        try:
            while True:
                frame = await self.ws.recv()
                if isinstance(frame, bytes):
                    self._queue_frame(frame)
                    continue
                try:
                    payload = json.loads(frame)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise HomeBridgeProtocolError(
                        "Home bridge sent invalid JSON"
                    ) from exc
                if not isinstance(payload, dict):
                    raise HomeBridgeProtocolError(
                        "Home bridge sent a non-object JSON frame"
                    )
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
            raise HomeBridgeProtocolError("Home bridge frame is not JSON-RPC 2.0")
        if type(payload.get("schema")) is not int or payload.get("schema") != HOME_BRIDGE_SCHEMA:
            raise HomeBridgeProtocolError("Home bridge frame has an unsupported schema")
        if "id" in payload and type(payload.get("id")) not in {str, int}:
            raise HomeBridgeProtocolError("Home bridge request ID is invalid")

        has_result = "result" in payload
        has_error = "error" in payload
        if "id" in payload and has_result and has_error:
            raise HomeBridgeProtocolError(
                "Home bridge reply contains both result and error"
            )
        if "id" in payload and (has_result or has_error):
            request_id = str(payload["id"])
            pending = self._pending.get(request_id)
            if pending is None:
                logger.debug("home bridge ignored unmatched reply")
                return
            future, method = pending
            if future.done():
                return
            if has_error:
                error_payload = payload.get("error")
                if not isinstance(error_payload, dict):
                    raise HomeBridgeProtocolError(
                        "Home bridge error is not an object"
                    )
                data = error_payload.get("data")
                if not isinstance(data, dict):
                    raise HomeBridgeProtocolError(
                        "Home bridge error has no data envelope"
                    )
                _require_schema(data, "Home bridge error")
                code = _require_string(
                    data.get("code"),
                    "Home bridge error has no code",
                )
                delivery = _require_string(
                    data.get("delivery"),
                    "Home bridge error has no delivery classification",
                ).lower()
                if delivery not in {"known", "uncertain"}:
                    raise HomeBridgeProtocolError(
                        "Home bridge error has an unknown delivery classification"
                    )
                future.set_exception(HomeBridgeRPCError(method, code, delivery))
            else:
                future.set_result(payload.get("result"))
            return

        if "id" in payload:
            request_id = str(payload["id"])
            pending = self._pending.get(request_id)
            if pending is not None and not pending[0].done():
                pending[0].set_exception(
                    HomeBridgeProtocolError(
                        "Home bridge reply has neither result nor error"
                    )
                )
                return
            raise HomeBridgeProtocolError("Home bridge request frame is malformed")

        method = payload.get("method")
        params = payload.get("params")
        if not isinstance(method, str) or not method:
            raise HomeBridgeProtocolError("Home bridge notification has no method")
        if not isinstance(params, dict):
            raise HomeBridgeProtocolError(
                "Home bridge notification params are not an object"
            )
        self._queue_frame(payload)

    def _reset_runtime_state(self) -> None:
        self._pending.clear()
        self._events = asyncio.Queue(maxsize=HOME_BRIDGE_QUEUE_MAX)
        self._closed = asyncio.Event()
        self._terminal_error = None
        self._sentinel_queued = False
        self._connected = False
        self._reader_task = None

    def _queue_close_sentinel(self) -> None:
        if not self._sentinel_queued:
            self._sentinel_queued = True
            if self._discard_queued_events_on_close:
                # P-4's Puck mode treats every queued event from a dropped
                # socket as unresolved. It must see transport failure before
                # any of those events can be forwarded as authoritative.
                while True:
                    try:
                        self._events.get_nowait()
                    except asyncio.QueueEmpty:
                        break
            try:
                self._events.put_nowait(_CLOSE_SENTINEL)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._events.get_nowait()
                self._events.put_nowait(_CLOSE_SENTINEL)

    def _queue_frame(self, frame: dict[str, Any] | bytes) -> None:
        try:
            self._events.put_nowait(frame)
        except asyncio.QueueFull as exc:
            raise HomeBridgeProtocolError(
                "Home bridge notification queue is full"
            ) from exc

    def _fail(self, error: BaseException) -> None:
        if self._terminal_error is None:
            self._terminal_error = error
        self._connected = False
        self._closed.set()
        for future, _method in list(self._pending.values()):
            if not future.done():
                future.set_exception(self._terminal_error)
        self._queue_close_sentinel()

    @staticmethod
    def _as_reader_error(exc: BaseException) -> BaseException:
        if isinstance(exc, HomeBridgeProtocolError):
            return exc
        error = HomeBridgeClient._as_transport_error("home bridge receive", exc)
        if error is not None:
            return error
        return HomeBridgeProtocolError("Home bridge reader failed")

    @staticmethod
    def _as_transport_error(
        operation: str, exc: BaseException
    ) -> HomeBridgeTransportError | None:
        error = transport_error_for(operation, exc)
        if error is None:
            return None
        return HomeBridgeTransportError(operation, exc)


class HomePuckSession:
    """Adapt the Home bridge contract to the existing Puck turn runner."""

    def __init__(
        self,
        url: str,
        device_credential: str,
        conversation_handle: str,
        *,
        connect_factory: Any | None = None,
        request_timeout: float = HOME_BRIDGE_REQUEST_TIMEOUT,
        supports_structured_prompts: bool = False,
        reconnect_required: bool = False,
        resume_uncertain_turn: bool = True,
        session_id: str = "home-puck",
        session_label: str = "Puck",
        wake_mapping_id: str = "",
    ) -> None:
        self.url = require_home_bridge_url(url)
        self.device_credential = str(device_credential).strip()
        self._conversation_handle = str(conversation_handle).strip()
        self.wake_mapping_id = str(wake_mapping_id).strip()
        if not self.device_credential:
            raise ValueError("Home Device credential is required")
        if not self._conversation_handle:
            raise ValueError("Home conversation handle is required")
        self._connect_factory = connect_factory
        self._request_timeout = request_timeout
        self._supports_structured_prompts = bool(supports_structured_prompts)
        self._session_id = str(session_id).strip() or "home-puck"
        self._session_label = str(session_label).strip() or "Home"
        self._client: HomeBridgeClient | None = None
        self._retired_client: HomeBridgeClient | None = None
        self._opened = False
        self._reconnect_required = bool(reconnect_required)
        self._resume_uncertain_turn = bool(resume_uncertain_turn)
        self._claim_retired = False
        self._retirement_attempted = False
        self._retirement_confirmed = False
        self.retirement_rejection: str | None = None
        self._connected = False
        self._active_turn_id: str | None = None
        self._pending_prompt: dict[str, Any] | None = None
        self._turn_lock = asyncio.Lock()
        self._prompt_response_lock = asyncio.Lock()
        self._retirement_lock = asyncio.Lock()
        self._capabilities: frozenset[str] = frozenset()
        self._timing_capability: str | None = None
        self.turn_index = 0
        self.confirmed_model: str | None = None
        self.confirmed_title: str | None = None
        self.confirmed_chat_id: str | None = None
        self.confirmed_server_version: str | None = None
        self.confirmed_context_limit: int | None = None

    @property
    def capabilities(self) -> frozenset[str]:
        return self._capabilities

    @property
    def supports_structured_prompts(self) -> bool:
        return self._supports_structured_prompts

    @property
    def timing_capability(self) -> str | None:
        """The timing contract confirmed by Home, if one exists."""
        return self._timing_capability

    @property
    def supports_interrupt(self) -> bool:
        return "interrupt" in self._capabilities

    @property
    def session_id(self) -> str:
        # Home deliberately withholds the Hermes runtime/session identity.
        return self._session_id

    @property
    def active_turn_id(self) -> str | None:
        return self._active_turn_id

    def is_connected(self) -> bool:
        return bool(
            self._connected
            and self._client is not None
            and self._client.is_connected
        )

    async def connect(self) -> dict[str, Any]:
        """Authenticate and open or reconnect the opaque Home conversation."""

        await self._reap_retired_client()
        if self._client is not None or self._connected:
            await self.close()
        await self._reap_retired_client()
        client = HomeBridgeClient(
            self.url,
            self.device_credential,
            connect_factory=self._connect_factory,
            request_timeout=self._request_timeout,
            discard_queued_events_on_close=not self._resume_uncertain_turn,
        )
        self._client = client
        method = "conversation.reconnect" if self._reconnect_required else "conversation.open"
        try:
            await client.connect()
            result = await client.request(
                method,
                {"conversation_handle": self._conversation_handle},
            )
            ready = self._validate_ready_result(result)
        except BaseException:
            await client.close()
            if client.cleanup_pending:
                self._retired_client = client
            self._client = None
            self._connected = False
            raise

        self._capabilities = _capability_names(ready.get("capabilities"))
        self._timing_capability = _timing_capability(ready["capabilities"])
        self._connected = True
        self._opened = True
        self._reconnect_required = False
        logger.info("%s Home bridge ready via %s", self._session_label, method)
        return ready

    async def wait_for_disconnect(self) -> None:
        client = self._client
        if not self.is_connected() or client is None:
            raise HomeBridgeTransportError(
                "home bridge connection wait",
                ConnectionError("Home bridge is not connected"),
            )
        await client.wait_for_disconnect()
        self._connected = False
        self._reconnect_required = self._opened

    async def close(self) -> None:
        client = self._client
        self._client = None
        self._connected = False
        self._active_turn_id = None
        self._pending_prompt = None
        if self._opened:
            self._reconnect_required = True
        if client is not None:
            await client.close()
            if client.cleanup_pending:
                self._retired_client = client

    async def _reap_retired_client(self) -> None:
        client = self._retired_client
        if client is None:
            return
        if client.cleanup_pending:
            raise HomeBridgeTransportError(
                "home bridge connect",
                RuntimeError("previous Home bridge cleanup is still pending"),
            )
        await client.wait_for_cleanup()
        if self._retired_client is client:
            self._retired_client = None

    def send_turn(
        self,
        text: str,
        *,
        stt_source: str = "local",
    ) -> AsyncIterator[dict[str, Any]]:
        del stt_source
        if not self.is_connected() or self._client is None:
            raise HomeBridgeTransportError(
                "home bridge prompt.submit",
                ConnectionError("Home bridge is not ready"),
            )
        if not str(text).strip():
            raise ValueError("Home bridge prompts must not be empty")
        return self._send_turn(str(text))

    async def _send_turn(self, text: str) -> AsyncIterator[dict[str, Any]]:
        if self._turn_lock.locked():
            raise HomeBridgeProtocolError(
                "Home bridge does not support concurrent Puck turns"
            )
        await self._turn_lock.acquire()
        try:
            async for event in self._send_turn_locked(text):
                yield event
        finally:
            self._turn_lock.release()

    async def _send_turn_locked(self, text: str) -> AsyncIterator[dict[str, Any]]:
        client = self._client
        if client is None or not self.is_connected():
            raise HomeBridgeTransportError(
                "home bridge prompt.submit",
                ConnectionError("Home bridge is not ready"),
            )
        try:
            result = await client.request(
                "prompt.submit",
                {
                    "conversation_handle": self._conversation_handle,
                    "text": text,
                },
            )
        except asyncio.CancelledError:
            await self._close_after_uncertain_prompt()
            raise
        except HomeBridgeTransportError:
            self._note_uncertain_transport()
            raise
        except HomeBridgeRPCError as exc:
            if exc.delivery != "known" or exc.code != "request_rejected":
                await self._close_after_uncertain_prompt()
                raise HomeBridgeTransportError(
                    "home bridge prompt.submit",
                    ConnectionError("Home bridge prompt delivery is uncertain"),
                ) from exc
            # A typed request_rejected response is known non-delivery. Keep
            # the ready socket so the next fresh capture may proceed.
            raise

        try:
            turn_id = self._validate_prompt_result(result)
        except HomeBridgeProtocolError:
            await self._close_after_protocol_failure()
            raise
        self.turn_index += 1
        self._active_turn_id = turn_id
        audio_started = False
        audio_ended = False
        audio_failed = False
        pcm_remainder = b""
        resume_attempts = 0
        audio_lost = False
        text_terminal = False
        audio_wait_remaining: float | None = None
        text_state: dict[str, Any] = {
            "committed": "",
            "rendered_preview": "",
            "streamed": False,
            "draft_id": None,
            "turn_id": turn_id,
            "streamed_reasoning": False,
        }
        try:
            while True:
                try:
                    if audio_wait_remaining is None:
                        frame = await client.next_frame()
                    else:
                        # Count network waiting only; rendering/playback happens
                        # while this generator is suspended at yield.
                        started_wait = asyncio.get_running_loop().time()
                        try:
                            async with asyncio.timeout(max(0, audio_wait_remaining)):
                                frame = await client.next_frame()
                        except asyncio.TimeoutError:
                            try:
                                yield {"type": "audio_abort", "error": "Home audio completion timed out; text completed. Reconnect before the next prompt.", "text_completed": True}
                            finally:
                                await self._close_after_protocol_failure()
                            return
                        audio_wait_remaining -= asyncio.get_running_loop().time() - started_wait
                except HomeBridgeTransportError:
                    if not self._resume_uncertain_turn:
                        self._note_uncertain_transport()
                        raise
                    if resume_attempts >= 3:
                        raise
                    resume_attempts += 1
                    self._note_uncertain_transport()
                    ready = await self.connect()
                    resumed_turn_id = _reconnected_turn_id(
                        ready,
                        self._conversation_handle,
                    )
                    if resumed_turn_id != turn_id:
                        await self._close_after_protocol_failure()
                        raise HomeBridgeProtocolError(
                            "Home did not restore the submitted unresolved turn"
                        )
                    client = self._client
                    if client is None or not self.is_connected():
                        raise HomeBridgeTransportError(
                            "home bridge reconnect",
                            ConnectionError("Home bridge did not remain connected"),
                        )
                    self._active_turn_id = turn_id
                    if audio_started and not audio_ended and not audio_failed:
                        audio_ended = True
                        audio_lost = True
                        pcm_remainder = b""
                        yield {"type": "audio_end"}
                        if text_terminal:
                            # The resumed worker may still send unlabelled PCM.
                            # Retire this socket so its tail cannot enter a new turn.
                            try:
                                yield {"type": "audio_abort", "error": "Home audio was interrupted; text completed. Reconnect before the next prompt.", "text_completed": True}
                            finally:
                                await self._close_after_protocol_failure()
                            return
                    continue
                if isinstance(frame, bytes):
                    if audio_failed or audio_lost:
                        continue
                    if not audio_started or audio_ended:
                        raise HomeBridgeAudioError(
                            "Home bridge sent PCM outside an active audio frame"
                        )
                    if text_terminal and frame:
                        audio_wait_remaining = self._request_timeout
                    data = pcm_remainder + frame
                    pcm_remainder = data[-1:] if len(data) % 2 else b""
                    if pcm_remainder:
                        data = data[:-1]
                    if data:
                        yield {"type": "audio_chunk", "data": data}
                    continue

                method = frame.get("method")
                params = frame.get("params")
                if not isinstance(params, dict):
                    raise HomeBridgeProtocolError(
                        "Home bridge notification params are not an object"
                    )
                if method == "audio.frame":
                    if audio_lost:
                        continue
                    audio_event = self._audio_event(
                        params,
                        turn_id,
                        audio_started=audio_started,
                        audio_ended=audio_ended,
                    )
                    if audio_event is None:
                        continue
                    if text_terminal:
                        audio_wait_remaining = self._request_timeout
                    kind = audio_event["type"]
                    if kind == "audio_start":
                        audio_started = True
                        yield audio_event
                    elif kind == "audio_end":
                        if pcm_remainder:
                            raise HomeBridgeAudioError(
                                "Home bridge audio ended with an incomplete PCM sample"
                            )
                        audio_ended = True
                        yield audio_event
                    else:
                        yield audio_event
                        audio_failed = True
                    if text_terminal and (audio_ended or audio_failed):
                        return
                    continue
                if method != "event":
                    # Heartbeat and future Home notifications cannot complete
                    # or retarget the active turn. Ignore them safely.
                    continue

                event_handle = _require_string(
                    params.get("conversation_handle"),
                    "Home bridge event has no conversation handle",
                )
                if event_handle != self._conversation_handle:
                    continue
                event = _event_from_params(params)
                event_turn_id = _frame_turn_id(params, event)
                if event_turn_id is None or event_turn_id != turn_id:
                    continue
                event_type = _require_string(
                    event.get("type"),
                    "Home bridge event has no type",
                )
                payload = event.get("payload")
                if payload is None:
                    payload = {}
                if not isinstance(payload, dict):
                    raise HomeBridgeProtocolError(
                        "Home bridge event payload is not an object"
                    )
                correlation_candidates = [
                    candidate
                    for candidate in (
                        params.get("correlation_id"),
                        event.get("correlation_id"),
                        payload.get("correlation_id"),
                    )
                    if candidate not in (None, "")
                ]
                for candidate in correlation_candidates:
                    if not isinstance(candidate, str) or not candidate.strip():
                        raise HomeBridgeProtocolError(
                            "Home bridge event correlation ID is invalid"
                        )
                distinct_correlations = {
                    candidate.strip() for candidate in correlation_candidates
                }
                if len(distinct_correlations) > 1:
                    raise HomeBridgeProtocolError(
                        "Home bridge event has conflicting correlation IDs"
                    )
                correlation_id = next(iter(distinct_correlations), None)
                if correlation_id is None and event_type in _STRUCTURED_PROMPT_EVENT_TYPES:
                    correlation_id = payload.get("request_id")
                if correlation_id is not None:
                    text_state["correlation_id"] = _require_string(
                        correlation_id,
                        "Home bridge event correlation ID is invalid",
                    )

                if (
                    event_type in _STRUCTURED_PROMPT_EVENT_TYPES
                    and not self.supports_structured_prompts
                ):
                    normalized = {
                        "type": "error",
                        "error": "Home Puck does not support structured prompts",
                    }
                    await self._close_after_protocol_failure()
                else:
                    if (
                        event_type in _STRUCTURED_PROMPT_EVENT_TYPES
                        and correlation_id is None
                    ):
                        raise HomeBridgeProtocolError(
                            "Home bridge structured prompt has no correlation ID"
                        )
                    normalized = _normalize_event(event_type, payload, text_state)
                    if (
                        event_type in _STRUCTURED_PROMPT_EVENT_TYPES
                        and isinstance(normalized, dict)
                        and normalized.get("type") == "prompt_request"
                    ):
                        self._remember_pending_prompt(
                            event_type, normalized, turn_id
                        )
                normalized_events = (
                    [normalized]
                    if isinstance(normalized, dict)
                    else (normalized or [])
                )
                for normalized_event in normalized_events:
                    if normalized_event.get("type") == "prompt_resolved":
                        self._clear_pending_prompt(normalized_event)
                    yield normalized_event
                    if normalized_event["type"] in {
                        "error",
                        "audio_abort",
                        "turn_interrupted",
                    }:
                        return
                if _is_terminal_event(event_type, payload):
                    # Home pumps text and audio independently. Text completion
                    # does not end an advertised or already-started audio stream.
                    if (audio_started or "audio" in self.capabilities) and not audio_ended and not audio_failed:
                        if not text_terminal:
                            audio_wait_remaining = self._request_timeout
                        text_terminal = True
                        continue
                    return
        except asyncio.CancelledError:
            await self._close_after_uncertain_prompt()
            raise
        except HomeBridgeTransportError:
            self._note_uncertain_transport()
            raise
        except HomeBridgeProtocolError:
            self._reconnect_required = self._opened
            self._connected = False
            await self.close()
            raise
        finally:
            if self._active_turn_id == turn_id:
                self._active_turn_id = None
            if self._pending_prompt is not None and self._pending_prompt["turn_id"] == turn_id:
                self._pending_prompt = None

    async def interrupt_active_turn(self) -> bool:
        """Request interruption; terminal event remains the authority."""

        client = self._client
        turn_id = self._active_turn_id
        if (
            not self.is_connected()
            or client is None
            or not turn_id
            or not self.supports_interrupt
        ):
            return False
        try:
            result = await client.request(
                "session.interrupt",
                {
                    "conversation_handle": self._conversation_handle,
                    "turn_id": turn_id,
                },
            )
        except HomeBridgeRPCError as exc:
            if exc.code == "capability_unavailable":
                return False
            raise
        try:
            if not isinstance(result, dict):
                raise HomeBridgeProtocolError(
                    "Home bridge interrupt result is not an object"
                )
            _require_schema(result, "Home bridge interrupt result")
        except HomeBridgeProtocolError:
            await self._close_after_protocol_failure()
            raise
        return _accepted_result(result)

    async def ping(self) -> dict[str, Any]:
        """Exercise Home application liveness, separate from WebSocket pings."""

        client = self._client
        if not self.is_connected() or client is None:
            raise HomeBridgeTransportError(
                "home bridge ping",
                ConnectionError("Home bridge is not ready"),
            )
        try:
            result = await client.request(
                "bridge.ping",
                {"conversation_handle": self._conversation_handle},
            )
            if not isinstance(result, dict):
                raise HomeBridgeProtocolError(
                    "Home bridge ping result is not an object"
                )
            _require_schema(result, "Home bridge ping result")
            return result
        except HomeBridgeProtocolError:
            await self._close_after_protocol_failure()
            raise

    async def send_prompt_response(
        self,
        *,
        prompt_id: str,
        prompt_kind: str,
        option_id: str | None = None,
        value: str | None = None,
        reason: str | None = None,
        operation: str | None = None,
        object_id: str | None = None,
        freshness: str | None = None,
    ) -> bool:
        """Resolve the current Home prompt without creating another turn.

        Typed choices carry Home's current operation, object, and freshness
        values back through the same correlated prompt response. Secret
        values are never logged.
        """
        del reason
        if (
            not self.supports_structured_prompts
            or not self.is_connected()
            or self._client is None
        ):
            return False

        async with self._prompt_response_lock:
            pending = self._pending_prompt
            if pending is None:
                return False
            requested_id = str(prompt_id or "").strip()
            if requested_id not in {
                pending["prompt_id"],
                pending["correlation_id"],
            }:
                return False
            if not _prompt_kind_matches(
                pending["event_type"], pending["prompt_kind"], prompt_kind
            ):
                return False
            if _is_choice_prompt(pending["event_type"], pending["prompt_kind"]):
                allowed_options = pending.get("option_ids")
                if (
                    not isinstance(option_id, str)
                    or not option_id
                    or not isinstance(allowed_options, frozenset)
                    or option_id not in allowed_options
                ):
                    return False
            elif option_id is not None:
                allowed_options = pending.get("option_ids")
                if (
                    isinstance(allowed_options, frozenset)
                    and option_id not in allowed_options
                ):
                    return False
            choice_context = pending.get("choice")
            typed_fields = (operation, object_id, freshness)
            if pending.get("choice_invalid"):
                return False
            if any(field is not None for field in typed_fields):
                operations = (
                    choice_context.get("operations")
                    if isinstance(choice_context, dict)
                    else None
                )
                if (
                    not isinstance(choice_context, dict)
                    or not isinstance(operation, str)
                    or operation not in {"choose", "explore"}
                    or not isinstance(object_id, str)
                    or not isinstance(freshness, str)
                    or not isinstance(operations, list)
                    or not 1 <= len(operations) <= 2
                    or any(
                        not isinstance(item, str) or item not in {"choose", "explore"}
                        for item in operations
                    )
                    or len(set(operations)) != len(operations)
                    or object_id != choice_context.get("object_id")
                    or freshness != choice_context.get("freshness")
                    or operation not in operations
                ):
                    return False
            elif (
                pending["event_type"] == "prompt_request"
                and pending["prompt_kind"].strip().lower() == "choice"
            ):
                # Home choice prompts require typed object and freshness
                # identity; missing metadata cannot fall back to a legacy tap.
                return False
            response = _prompt_response(
                pending["event_type"],
                pending["prompt_kind"],
                option_id=option_id,
                value=value,
                operation=operation,
                object_id=object_id,
                freshness=freshness,
            )
            if response is None:
                return False
            params = {
                "conversation_handle": self._conversation_handle,
                "turn_id": pending["turn_id"],
                "correlation_id": pending["correlation_id"],
                "event_type": pending["event_type"],
                "response": response,
            }
            try:
                result = await self._client.request("prompt.respond", params)
            except asyncio.CancelledError:
                await self._close_after_uncertain_prompt()
                raise
            except HomeBridgeRPCError as exc:
                if exc.delivery == "known":
                    return False
                await self._close_after_uncertain_prompt()
                raise HomeBridgeTransportError(
                    "home bridge prompt.respond",
                    ConnectionError("Home bridge prompt delivery is uncertain"),
                ) from exc
            except HomeBridgeTransportError:
                await self._close_after_uncertain_prompt()
                raise

            try:
                _validate_prompt_response_result(result)
            except HomeBridgeRPCError:
                return False
            except HomeBridgeProtocolError:
                await self._close_after_protocol_failure()
                raise
            if self._pending_prompt == pending:
                self._pending_prompt = None
            return True

    async def list_sessions(self, **_kwargs: Any) -> list[dict[str, Any]]:
        raise HomeBridgeProtocolError("Home Puck session does not expose sessions")

    async def new_session(self, **_kwargs: Any) -> dict[str, Any]:
        raise HomeBridgeProtocolError("Home owns Puck session creation")

    async def switch_session(self, _session_id: str) -> dict[str, Any]:
        raise HomeBridgeProtocolError("Home owns Puck session selection")

    def capture_voice(self, **_kwargs: Any) -> str:
        raise HomeBridgeProtocolError("Puck capture is owned by the firmware")

    def cancel_voice(self) -> None:
        return None

    async def set_input_device(self, _device: int | str | None) -> None:
        return None

    def _note_uncertain_transport(self) -> None:
        self._connected = False
        self._reconnect_required = self._opened

    async def _close_after_uncertain_prompt(self) -> None:
        self._note_uncertain_transport()
        await self.close()

    async def _close_after_protocol_failure(self) -> None:
        self._connected = False
        self._reconnect_required = self._opened
        await self.close()

    @property
    def conversation_handle(self) -> str:
        return self._conversation_handle

    @property
    def claim_retired(self) -> bool:
        return self._claim_retired

    async def dispatch_title(self, title: str) -> None:
        """Dispatch only the title operation advertised on this bridge."""
        if "title" not in self.capabilities or not self.is_connected() or self._client is None:
            raise HomeBridgeProtocolError("Home title command is unavailable")
        if not isinstance(title, str) or not title.strip() or len(title) > 256:
            raise ValueError("Title must contain 1–256 characters")
        result = await self._client.request("command.dispatch", {"conversation_handle": self._conversation_handle, "name": "title", "arg": title})
        if not isinstance(result, dict) or result.get("schema") != 1 or result.get("conversation_handle") != self._conversation_handle:
            raise HomeBridgeProtocolError("Home title command returned an invalid result")
        if result.get("accepted") is False or result.get("status") in {"rejected", "error", "failed"}:
            raise HomeBridgeProtocolError("Home rejected the title command")

    async def close_claim(self) -> bool:
        """Retire a healthy claim on its current ready control connection."""
        client = self._client
        if not self.is_connected() or client is None:
            return False
        try:
            result = await client.request(
                "conversation.close",
                {"conversation_handle": self._conversation_handle},
            )
            _validate_close_result(result, self._conversation_handle)
        except Exception as exc:
            logger.warning("Puck Home claim close was not confirmed (%s)", type(exc).__name__)
            self._claim_retired = True
            return False
        self._claim_retired = True
        self._retirement_confirmed = True
        await self.close()
        return True

    async def retire_uncertain_claim(self) -> bool:
        """Use one control-only reconnect to close a claim after turn loss.

        The temporary reader may queue old response frames while the close
        RPC is in flight. This method never consumes or forwards that queue.
        """
        async with self._retirement_lock:
            return await self._retire_uncertain_claim_once()

    async def retry_uncertain_claim(self) -> bool:
        """Make one fresh control-only close attempt on a later physical wake."""
        async with self._retirement_lock:
            if self._retirement_confirmed:
                return True
            self._retirement_attempted = False
            return await self._retire_uncertain_claim_once()

    async def _retire_uncertain_claim_once(self) -> bool:
        if self._retirement_attempted:
            return self._retirement_confirmed
        self._retirement_attempted = True
        self._claim_retired = True
        await self.close()
        client = HomeBridgeClient(
            self.url,
            self.device_credential,
            connect_factory=self._connect_factory,
            request_timeout=min(self._request_timeout, 3.0),
            discard_queued_events_on_close=True,
        )
        try:
            async with asyncio.timeout(HOME_CLAIM_RETIRE_TIMEOUT):
                await client.connect()
                ready = await client.request(
                    "conversation.reconnect",
                    {"conversation_handle": self._conversation_handle},
                )
                self._validate_ready_result(ready)
                result = await client.request(
                    "conversation.close",
                    {"conversation_handle": self._conversation_handle},
                )
                _validate_close_result(result, self._conversation_handle)
            self._retirement_confirmed = True
            return True
        except Exception as exc:
            self.retirement_rejection = exc.code if isinstance(exc, HomeBridgeRPCError) else None
            logger.warning(
                "Puck Home claim retirement was not confirmed (%s)",
                type(exc).__name__,
            )
            return False
        finally:
            try:
                await asyncio.wait_for(client.close(), HOME_BRIDGE_CLOSE_TIMEOUT)
            except Exception as exc:
                logger.debug(
                    "Puck Home control connection cleanup pending (%s)",
                    type(exc).__name__,
                )

    def _validate_prompt_result(self, result: Any) -> str:
        if not isinstance(result, dict):
            raise HomeBridgeProtocolError(
                "Home bridge prompt result is not an object"
            )
        _require_schema(result, "Home bridge prompt result")
        handle = _require_string(
            result.get("conversation_handle"),
            "Home bridge prompt result has no conversation handle",
        )
        if handle != self._conversation_handle:
            raise HomeBridgeProtocolError(
                "Home bridge prompt result changed conversation handle"
            )
        status = str(result.get("status") or "").strip().lower()
        if status not in {"submitted", "accepted"}:
            raise HomeBridgeProtocolError(
                "Home bridge prompt result is not an accepted turn"
            )
        return _require_string(
            result.get("turn_id"),
            "Home bridge prompt result has no turn ID",
        )

    def _validate_ready_result(self, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise HomeBridgeProtocolError(
                "Home bridge readiness result is not an object"
            )
        _require_schema(result, "Home bridge readiness result")
        status = result.get("status")
        if status != "ready":
            reconnect_required = result.get("reconnect_required", False)
            if type(reconnect_required) is not bool:
                raise HomeBridgeProtocolError(
                    "Home bridge unavailable result has an invalid reconnect_required flag"
                )
            self._reconnect_required = reconnect_required
            raise HomeBridgeUnavailableError(status, result.get("reason"))
        handle = result.get("conversation_handle")
        if not isinstance(handle, str) or not handle.strip():
            raise HomeBridgeProtocolError(
                "Home bridge readiness result has no conversation handle"
            )
        if handle.strip() != self._conversation_handle:
            raise HomeBridgeProtocolError(
                "Home bridge readiness result changed conversation handle"
            )
        route = result.get("route")
        if (
            not isinstance(route, dict)
            or type(route.get("class")) is not str
            or route.get("class") not in {"home", "tailscale", "public"}
            or type(route.get("id")) is not str
            or not route.get("id").strip()
        ):
            raise HomeBridgeProtocolError(
                "Home bridge readiness result has no approved route"
            )
        if "capabilities" not in result or not isinstance(result["capabilities"], dict):
            raise HomeBridgeProtocolError(
                "Home bridge readiness capabilities are not an object"
            )
        _timing_capability(result["capabilities"])
        return result

    def _remember_pending_prompt(
        self,
        event_type: str,
        normalized: dict[str, Any],
        turn_id: str,
    ) -> None:
        prompt_id = str(normalized.get("prompt_id") or "").strip()
        correlation_id = str(normalized.get("correlation_id") or "").strip()
        if not prompt_id:
            prompt_id = correlation_id
        if not correlation_id:
            raise HomeBridgeProtocolError(
                "Home bridge structured prompt has no correlation ID"
            )
        if not prompt_id:
            raise HomeBridgeProtocolError(
                "Home bridge structured prompt has no prompt ID"
            )
        raw_choice = normalized.get("choice")
        self._pending_prompt = {
            "prompt_id": prompt_id,
            "correlation_id": correlation_id,
            "event_type": event_type,
            "prompt_kind": str(normalized.get("prompt_kind") or "").strip(),
            "turn_id": turn_id,
            "option_ids": frozenset(
                str(option.get("id") or "").strip()
                for option in normalized.get("options", [])
                if isinstance(option, dict) and str(option.get("id") or "").strip()
            ),
            "choice": (
                dict(raw_choice)
                if isinstance(raw_choice, dict)
                else None
            ),
            "choice_invalid": raw_choice is not None and not isinstance(raw_choice, dict),
        }

    def _clear_pending_prompt(self, normalized: dict[str, Any]) -> None:
        pending = self._pending_prompt
        if pending is None:
            return
        identifiers = {
            str(normalized.get("prompt_id") or "").strip(),
            str(normalized.get("correlation_id") or "").strip(),
        }
        if identifiers & {pending["prompt_id"], pending["correlation_id"]}:
            self._pending_prompt = None

    def _audio_event(
        self,
        params: dict[str, Any],
        turn_id: str,
        *,
        audio_started: bool,
        audio_ended: bool,
    ) -> dict[str, Any] | None:
        _require_schema(params, "Home bridge audio frame")
        frame_handle = _require_string(
            params.get("conversation_handle"),
            "Home bridge audio frame has no conversation handle",
        )
        if frame_handle != self._conversation_handle:
            raise HomeBridgeAudioError(
                "Home bridge audio frame belongs to another conversation"
            )
        frame_turn_id = params.get("turn_id")
        if not isinstance(frame_turn_id, str):
            raise HomeBridgeAudioError("Home bridge audio frame has no turn ID")
        if frame_turn_id != turn_id:
            raise HomeBridgeAudioError(
                "Home bridge audio frame belongs to another turn"
            )
        frame = params.get("frame")
        if not isinstance(frame, dict):
            raise HomeBridgeAudioError("Home bridge audio frame is not an object")
        kind = _require_string(frame.get("kind"), "Home bridge audio frame has no kind")
        if kind == "start":
            if audio_started or audio_ended:
                raise HomeBridgeAudioError(
                    "Home bridge sent a duplicate audio start"
                )
            sample_rate = _positive_int(
                frame.get("sample_rate"),
                "sample rate",
                maximum=HOME_BRIDGE_MAX_SAMPLE_RATE,
            )
            channels = _positive_int(frame.get("channels"), "channels")
            sample_width = _positive_int(frame.get("sample_width"), "sample width")
            if channels != 1 or sample_width != 2:
                raise HomeBridgeAudioError(
                    "Home bridge audio must be mono signed 16-bit PCM"
                )
            byte_order = frame.get("byte_order")
            if (
                not isinstance(byte_order, str)
                or byte_order.strip().lower() not in {"little", "le"}
            ):
                raise HomeBridgeAudioError(
                    "Home bridge audio must be little-endian PCM"
                )
            return {
                "type": "audio_start",
                "sample_rate": sample_rate,
                "channels": channels,
                "sample_width": sample_width,
            }
        if kind == "end":
            if not audio_started or audio_ended:
                raise HomeBridgeAudioError(
                    "Home bridge sent an invalid audio end"
                )
            return {"type": "audio_end"}
        if kind in {"fallback", "unavailable"}:
            return {
                "type": "audio_abort",
                "error": "Home bridge response audio unavailable",
            }
        raise HomeBridgeAudioError(f"Home bridge audio kind {kind!r} is unsupported")


def _reconnected_turn_id(result: dict[str, Any], conversation_handle: str) -> str | None:
    unresolved = result.get("unresolved_turn")
    if isinstance(unresolved, dict):
        _require_schema(unresolved, "Home bridge unresolved turn")
        handle = _require_string(
            unresolved.get("conversation_handle"),
            "Home bridge unresolved turn has no conversation handle",
        )
        if handle != conversation_handle:
            raise HomeBridgeProtocolError(
                "Home bridge unresolved turn changed conversation handle"
            )
        status = _require_string(
            unresolved.get("status"),
            "Home bridge unresolved turn has no status",
        )
        del status
        turn_id = _require_string(
            unresolved.get("turn_id"),
            "Home bridge unresolved turn has no turn ID",
        )
        top_level_turn_id = result.get("turn_id")
        if top_level_turn_id is not None and top_level_turn_id != turn_id:
            raise HomeBridgeProtocolError(
                "Home bridge returned conflicting unresolved turn IDs"
            )
        return turn_id
    if type(unresolved) is bool:
        if not unresolved:
            return None
        return _require_string(
            result.get("turn_id"),
            "Home bridge omitted the unresolved turn ID",
        )
    raise HomeBridgeProtocolError(
        "Home bridge reconnect omitted unresolved-turn state"
    )


def _validate_close_result(result: Any, conversation_handle: str) -> None:
    if not isinstance(result, dict):
        raise HomeBridgeProtocolError("Home bridge close result is not an object")
    _require_schema(result, "Home bridge close result")
    handle = _require_string(
        result.get("conversation_handle"),
        "Home bridge close result has no conversation handle",
    )
    if handle != conversation_handle:
        raise HomeBridgeProtocolError(
            "Home bridge close result changed conversation handle"
        )
    if result.get("status") != "closed":
        raise HomeBridgeProtocolError("Home bridge did not confirm claim closure")


def _require_schema(params: dict[str, Any], what: str) -> None:
    if type(params.get("schema")) is not int or params.get("schema") != HOME_BRIDGE_SCHEMA:
        raise HomeBridgeProtocolError(f"{what} has an unsupported schema")


def _require_string(value: Any, message: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HomeBridgeProtocolError(message)
    return value.strip()


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise HomeBridgeProtocolError("Home bridge identity is not a string")
    return value


def _positive_int(
    value: Any,
    label: str,
    *,
    maximum: int | None = None,
) -> int:
    if type(value) is not int or value <= 0 or (
        maximum is not None and value > maximum
    ):
        raise HomeBridgeAudioError(f"Home bridge {label} is invalid")
    return value


def _event_from_params(params: dict[str, Any]) -> dict[str, Any]:
    _require_schema(params, "Home bridge event")
    raw_event = params.get("event")
    if raw_event is None:
        raw_event = params
    if not isinstance(raw_event, dict):
        raise HomeBridgeProtocolError("Home bridge event is not an object")
    return raw_event


def _frame_turn_id(params: dict[str, Any], event: dict[str, Any]) -> str | None:
    values = [params.get("turn_id"), event.get("turn_id")]
    present = [value for value in values if value not in (None, "")]
    if any(not isinstance(value, str) for value in present):
        raise HomeBridgeProtocolError("Home bridge event turn ID is not a string")
    seen = set(present)
    if len(seen) > 1:
        raise HomeBridgeProtocolError("Home bridge event has conflicting turn IDs")
    if not seen:
        return None
    value = next(iter(seen))
    if not all(value == str(candidate) for candidate in values if candidate not in (None, "")):
        raise HomeBridgeProtocolError("Home bridge event has conflicting turn IDs")
    return value


def _capability_names(raw: Any) -> frozenset[str]:
    if not isinstance(raw, dict):
        return frozenset()
    values: set[str] = set()
    commands = raw.get("commands")
    if isinstance(commands, list):
        values.update(str(item).strip() for item in commands if str(item).strip())
    for name, enabled in raw.items():
        if enabled is True:
            values.add(str(name).strip())
    if "session.interrupt" in values:
        values.add("interrupt")
    return frozenset(values)


def _timing_capability(raw: Any) -> str | None:
    """Accept only the timing contract Home has actually defined."""
    if not isinstance(raw, dict) or "timing" not in raw:
        return None
    timing = raw.get("timing")
    if timing != "absent":
        raise HomeBridgeProtocolError(
            "Home bridge readiness has an unsupported timing capability"
        )
    return "absent"


def _accepted_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("accepted") is True:
        return True
    status = str(result.get("status") or "").strip().lower()
    return status in {"accepted", "ok", "ready"}


def _validate_prompt_response_result(result: Any) -> None:
    """Require Home to prove that the structured prompt was resolved."""
    if not isinstance(result, dict):
        raise HomeBridgeProtocolError(
            "Home bridge prompt response result is not an object"
        )
    _require_schema(result, "Home bridge prompt response result")
    for name in ("accepted", "resolved"):
        value = result.get(name)
        if value is not None and type(value) is not bool:
            raise HomeBridgeProtocolError(
                f"Home bridge prompt response has invalid {name} flag"
            )
    status = result.get("status")
    if status is not None and not isinstance(status, str):
        raise HomeBridgeProtocolError(
            "Home bridge prompt response has invalid status"
        )
    normalized_status = status.strip().lower() if isinstance(status, str) else ""
    if result.get("accepted") is False or result.get("resolved") is False:
        raise HomeBridgeRPCError("prompt.respond", "request_rejected", "known")
    if normalized_status in {"rejected", "denied", "expired", "failed", "error"}:
        raise HomeBridgeRPCError("prompt.respond", "request_rejected", "known")
    if (
        result.get("accepted") is True
        or result.get("resolved") is True
        or normalized_status in {"ok", "accepted", "resolved", "complete", "completed"}
    ):
        return
    raise HomeBridgeProtocolError(
        "Home bridge prompt response has no accepted terminal status"
    )


def _prompt_kind_matches(event_type: str, pending_kind: str, supplied: str) -> bool:
    actual = str(supplied or "").strip().lower()
    expected = str(pending_kind or "").strip().lower()
    if event_type == "approval.request":
        return actual in {"choice", "approval", "confirm"}
    if event_type == "clarify.request":
        return actual in {"clarify", "choice"}
    if event_type == "secret.request":
        return actual == "secret"
    if event_type == "sudo.request":
        return actual == "sudo"
    if event_type == "prompt_request":
        return actual == expected or (
            expected in {"choice", "approval", "confirm"}
            and actual in {"choice", "approval", "confirm"}
        )
    return False


def _is_choice_prompt(event_type: str, prompt_kind: str) -> bool:
    kind = str(prompt_kind or "").strip().lower()
    return event_type == "approval.request" or (
        event_type == "prompt_request"
        and kind in {"choice", "approval", "confirm"}
    )


def _prompt_response(
    event_type: str,
    prompt_kind: str,
    *,
    option_id: str | None,
    value: str | None,
    operation: str | None = None,
    object_id: str | None = None,
    freshness: str | None = None,
) -> dict[str, str] | None:
    kind = str(prompt_kind or "").strip().lower()
    if _is_choice_prompt(event_type, kind):
        if operation is not None:
            if (
                not isinstance(operation, str)
                or operation not in {"choose", "explore"}
                or not isinstance(option_id, str)
                or not option_id
                or not isinstance(object_id, str)
                or not object_id
                or not isinstance(freshness, str)
                or not freshness
            ):
                return None
            return {
                "operation": operation,
                "option_id": option_id,
                "object_id": object_id,
                "freshness": freshness,
            }
        if object_id is not None or freshness is not None:
            return None
        return {"choice": option_id} if isinstance(option_id, str) and option_id else None
    if event_type == "clarify.request" or (
        event_type == "prompt_request" and kind == "clarify"
    ):
        answer = value if value is not None else option_id
        return {"answer": answer} if isinstance(answer, str) and answer else None
    if event_type == "secret.request" or (
        event_type == "prompt_request" and kind == "secret"
    ):
        return {"value": value} if isinstance(value, str) and value else None
    if event_type == "sudo.request" or (
        event_type == "prompt_request" and kind == "sudo"
    ):
        return {"password": value} if isinstance(value, str) and value else None
    return None


def _is_terminal_event(event_type: str, payload: dict[str, Any]) -> bool:
    if event_type in _TERMINAL_EVENT_TYPES or event_type == "message.complete":
        if "status" not in payload:
            return True
        raw_status = payload.get("status")
        if not isinstance(raw_status, str) or not raw_status.strip():
            raise HomeBridgeProtocolError(
                f"Home bridge {event_type} has an invalid terminal status"
            )
        status = raw_status.strip().lower()
        if status not in _TERMINAL_STATUSES:
            raise HomeBridgeProtocolError(
                f"Home bridge {event_type} has a non-terminal status"
            )
        return True
    status = str(payload.get("status") or "").strip().lower()
    return status in _TERMINAL_STATUSES and event_type.startswith("turn.")


def _joined_text(committed: str, preview: str) -> str:
    if not committed:
        return preview
    if not preview:
        return committed
    return f"{committed}\n\n{preview}"


def _final_text_update(
    final_text: str,
    state: dict[str, Any],
) -> dict[str, str] | None:
    if not final_text:
        return None
    preview = str(state["rendered_preview"]).rstrip("▉")
    if not state["streamed"]:
        return {"type": "text_delta", "text": final_text}
    if final_text == preview:
        return None
    if final_text.startswith(preview):
        return {"type": "text_delta", "text": final_text[len(preview):]}
    return {
        "type": "text_replace",
        "text": _joined_text(str(state["committed"]), final_text),
    }


def _normalize_event(
    event_type: str,
    payload: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any] | list[dict[str, Any]] | None:
    status = str(payload.get("status") or "").strip().lower()
    if event_type in _INTERRUPTED_EVENT_TYPES or status in _INTERRUPTED_STATUSES:
        return {"type": "turn_interrupted"}
    if event_type in _ERROR_EVENT_TYPES or status in _FAILED_STATUSES:
        return {"type": "error", "error": "Home bridge turn failed"}
    if _is_terminal_event(event_type, payload):
        if event_type == "message.complete":
            pass
        else:
            return None
    elif event_type == "message.complete":
        return None
    if event_type == "message.start":
        return {"type": "message_start"}
    if event_type in {"text.delta", "text_delta", "message.delta"}:
        draft_id = payload.get("draft_id")
        if draft_id is not None:
            if (
                state["draft_id"] is not None
                and draft_id != state["draft_id"]
            ):
                state["committed"] = _joined_text(
                    str(state["committed"]),
                    str(state["rendered_preview"]),
                )
                state["rendered_preview"] = ""
            state["draft_id"] = draft_id
        if event_type in {"message.delta", "text.delta", "text_delta"} and "rendered" not in payload:
            delta_value = (
                payload.get("text")
                if "text" in payload
                else payload.get("delta")
            )
            delta = str(delta_value or "")
            state["rendered_preview"] = (
                str(state["rendered_preview"]) + delta
            )
        else:
            preview = str(payload.get("rendered") or payload.get("text") or "")
            prior = str(state["rendered_preview"])
            if preview.startswith(prior):
                delta = preview[len(prior):]
                if state["committed"] and not prior:
                    delta = f"\n\n{delta}"
            elif payload.get("replace"):
                delta = _joined_text(str(state["committed"]), preview)
                state["rendered_preview"] = preview
                state["streamed"] = True
                return {"type": "text_replace", "text": delta}
            else:
                delta = f"\n{preview}" if preview else ""
            state["rendered_preview"] = preview
        state["streamed"] = True
        return {"type": "text_delta", "text": delta} if delta else None
    if event_type in {"text", "text_final"}:
        final_text = str(payload.get("text") or payload.get("rendered") or "")
        update = _final_text_update(final_text, state)
        if final_text:
            state["rendered_preview"] = final_text
            state["streamed"] = True
        return update
    if event_type == "message.complete":
        final_text = str(payload.get("text") or payload.get("rendered") or "")
        update = _final_text_update(final_text, state)
        if final_text:
            state["rendered_preview"] = final_text
            state["streamed"] = True
        events: list[dict[str, Any]] = []
        completion_reasoning = str(payload.get("reasoning") or "")
        if completion_reasoning and not state.get("streamed_reasoning"):
            events.append({"type": "thinking_delta", "text": completion_reasoning})
            state["streamed_reasoning"] = True
        if update:
            events.append(update)
        events.append(
            {
                "type": "message_complete",
                "text": final_text,
                "reasoning": str(payload.get("reasoning") or ""),
                "failure_reason": str(payload.get("failure_reason") or ""),
            }
        )
        return events
    if event_type in {"thinking.delta", "reasoning.delta"} and payload.get("text"):
        state["streamed_reasoning"] = True
        return {"type": "thinking_delta", "text": str(payload["text"])}
    if event_type == "reasoning.available":
        reasoning_text = str(payload.get("text") or "")
        if reasoning_text:
            state["streamed_reasoning"] = True
            return {"type": "thinking_delta", "text": reasoning_text}
        return {"type": "reasoning_available"}
    if event_type in {"status", "status.update"}:
        text = str(payload.get("text") or payload.get("status") or "").strip()
        if not text:
            return None
        event = {"type": "status", "text": text}
        if event_type == "status.update":
            event["kind"] = str(payload.get("kind") or "status")
        return event
    if event_type == "tool.start":
        return {
            "type": "tool_start",
            "tool_id": str(payload.get("tool_id") or ""),
            "name": str(payload.get("name") or "tool"),
            "context": str(payload.get("context") or ""),
        }
    if event_type in {"tool.progress", "tool.generating"}:
        return {
            "type": "tool_progress",
            "tool_id": str(payload.get("tool_id") or ""),
            "name": str(payload.get("name") or "tool"),
            "preview": str(payload.get("preview") or "drafting…"),
        }
    if event_type == "tool.complete":
        return {
            "type": "tool_complete",
            "tool_id": str(payload.get("tool_id") or ""),
            "name": str(payload.get("name") or "tool"),
            "summary": str(payload.get("summary") or ""),
            "error": str(payload.get("error") or ""),
        }
    if event_type == "notification.show":
        return {
            "type": "notification",
            "text": str(payload.get("text") or ""),
            "level": str(payload.get("level") or "info"),
            "key": str(payload.get("key") or ""),
        }
    if event_type == "notification.clear":
        return {"type": "notification_clear", "key": str(payload.get("key") or "")}
    if event_type in {
        "prompt_request",
        "approval.request",
        "clarify.request",
        "secret.request",
        "sudo.request",
    }:
        options = payload.get("options")
        if not isinstance(options, list):
            options = []
        prompt_kind = str(
            payload.get("prompt_kind")
            or {
                "approval.request": "choice",
                "clarify.request": "clarify",
                "secret.request": "secret",
                "sudo.request": "sudo",
            }.get(event_type, "")
        )
        prompt_turn_id = payload.get("turn_id")
        if prompt_turn_id in (None, ""):
            prompt_turn_id = state.get("turn_id")
        try:
            timeout_s = int(payload.get("timeout_s", 300))
        except (TypeError, ValueError):
            timeout_s = 300
        if prompt_kind.strip().lower() == "choice":
            normalized_options = [
                {
                    "id": option.get("id") or option.get("option_id"),
                    "label": option.get("label"),
                }
                for option in options
                if isinstance(option, dict)
            ]
        else:
            normalized_options = [
                dict(option) for option in options if isinstance(option, dict)
            ]
        return {
            "type": "prompt_request",
            "prompt_id": str(
                payload.get("prompt_id")
                or payload.get("request_id")
                or payload.get("id")
                or state.get("correlation_id")
                or ""
            ),
            "prompt_kind": prompt_kind,
            "turn_id": str(prompt_turn_id or ""),
            "text": str(payload.get("text") or ""),
            "options": normalized_options,
            "sensitive": bool(payload.get("sensitive", False)),
            "timeout_s": timeout_s,
            **(
                {"correlation_id": str(state["correlation_id"])}
                if state.get("correlation_id")
                else {}
            ),
            **(
                {"choice": payload.get("choice")}
                if prompt_kind.strip().lower() == "choice"
                else {}
            ),
        }
    if event_type == "prompt_resolved":
        return {
            "type": "prompt_resolved",
            "prompt_id": str(
                payload.get("prompt_id")
                or payload.get("request_id")
                or payload.get("id")
                or state.get("correlation_id")
                or ""
            ),
            "prompt_kind": str(payload.get("prompt_kind") or ""),
            "status": str(payload.get("status") or ""),
            **(
                {"correlation_id": str(state["correlation_id"])}
                if state.get("correlation_id")
                else {}
            ),
        }
    if event_type == "prompt_response_rejected":
        return {
            "type": "prompt_response_rejected",
            "prompt_id": str(
                payload.get("prompt_id")
                or payload.get("request_id")
                or payload.get("id")
                or state.get("correlation_id")
                or ""
            ),
            "reason": str(payload.get("reason") or ""),
            **(
                {"correlation_id": str(state["correlation_id"])}
                if state.get("correlation_id")
                else {}
            ),
        }
    if event_type == "background.complete":
        return {
            "type": "background_complete",
            "task_id": str(payload.get("task_id") or ""),
            "text": str(payload.get("text") or ""),
        }
    return {
        "type": "unknown_event",
        "event_type": event_type,
        "payload": payload,
    }


class HomeBrowserSession(HomePuckSession):
    """Home bridge session for the browser's active control surface."""

    def __init__(
        self,
        url: str,
        device_credential: str,
        conversation_handle: str,
        *,
        connect_factory: Any | None = None,
        request_timeout: float = HOME_BRIDGE_REQUEST_TIMEOUT,
    ) -> None:
        super().__init__(
            url,
            device_credential,
            conversation_handle,
            connect_factory=connect_factory,
            request_timeout=request_timeout,
            supports_structured_prompts=True,
            session_id="home-browser",
            session_label="Browser",
        )

    async def _send_turn_locked(self, text: str) -> AsyncIterator[dict[str, Any]]:
        """Expose the front-end terminal event after Home owns completion.

        ``HomePuckSession`` deliberately ends its iterator at the validated
        Home terminal frame because the Puck turn runner treats normal
        exhaustion as completion. The browser appliance consumes the shared
        ``SessionProtocol`` shape, where ``turn_end`` is the explicit
        presentation boundary. Keep that distinction in this browser-only
        subclass so Puck callers retain their existing event stream.
        """
        async for event in super()._send_turn_locked(text):
            if event.get("type") == "audio_end":
                # Home has one bounded audio stream per turn. A local close
                # after reconnect is final audio for this answer even while
                # buffered text and the terminal event are still arriving.
                yield {**event, "final": True}
            else:
                yield event
        yield {"type": "turn_end"}


__all__ = [
    "HOME_BRIDGE_PATH",
    "HomeBridgeAudioError",
    "HomeBridgeClient",
    "HomeBridgeProtocolError",
    "HomeBridgeRPCError",
    "HomeBridgeTransportError",
    "HomeBridgeUnavailableError",
    "HomeBrowserSession",
    "HomePuckSession",
    "_home_connection_kwargs",
    "require_home_bridge_url",
]
