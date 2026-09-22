from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import mimetypes
import ssl
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Protocol
from urllib.parse import parse_qs, unquote, urlsplit

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from .state import DisplayStatePublisher
from .touch import MAX_CAPTURE_ID_LENGTH, MAX_PCM_CHUNK_BYTES

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass(frozen=True, slots=True)
class DisplayServerInfo:
    host: str
    port: int
    secure: bool = False

    @property
    def http_url(self) -> str:
        scheme = "https" if self.secure else "http"
        return f"{scheme}://{_format_url_host(self.host)}:{self.port}/"

    @property
    def websocket_url(self) -> str:
        scheme = "wss" if self.secure else "ws"
        return f"{scheme}://{_format_url_host(self.host)}:{self.port}/state"


DEFAULT_BROWSER_SESSION_LIMIT = 8
BROWSER_SESSION_CAPACITY_CODE = 1013
BROWSER_SESSION_CAPACITY_REASON = "browser session capacity reached"
# Three catalog candidates may each spend up to the bounded connect and close
# windows in the appliance before a healthy later entry is admitted.
BROWSER_CONTEXT_SETUP_TIMEOUT = 45.0
MAX_CONNECTION_TASKS = 8
CONNECTION_TASK_CLEANUP_TIMEOUT = 3.0
MAX_BROWSER_ROUTE_REQUEST_ID_LENGTH = 64
MAX_BROWSER_WAKE_PHRASE_LENGTH = 128

# ---- ESP32 Touch doorway ingress ---------------------------------------
#
# The Touch endpoint speaks the same `/state` socket as the browser, but it
# also sends control frames and raw microphone PCM. The server owns the frame
# shape and the byte bounds; the appliance-owned binding owns the capture and
# session semantics. Nothing here ever inspects audio or transcript content.
MAX_TOUCH_TURN_ID_LENGTH = 128
MAX_TOUCH_REASON_LENGTH = 64
TOUCH_PCM_SAMPLE_WIDTH = 2
TOUCH_INGRESS_QUEUE_MAX = 256

TOUCH_CAPTURE_FRAMES = frozenset(
    {"mic_start", "mic_capture_started", "mic_end", "mic_abort"}
)
TOUCH_TURN_FRAMES = frozenset({"audio_playback_started", "audio_playback_failed"})
TOUCH_CONTROL_FRAMES = TOUCH_CAPTURE_FRAMES | TOUCH_TURN_FRAMES | {"turn_stop"}

_TOUCH_OVERFLOW = object()
_TOUCH_MALFORMED = object()


@dataclass(frozen=True, slots=True)
class TouchFrame:
    """One validated Touch control frame — never any audio or text."""

    type: str
    capture_id: str | None = None
    turn_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class BrowserVoiceTurn:
    """Validated browser text plus an optional catalog phrase."""

    text: str
    wake_phrase: str | None = None


@dataclass(frozen=True, slots=True)
class BrowserProfileRouteResult:
    """Safe result returned by an appliance-owned profile route."""

    accepted: bool
    account: str | None = None
    reason: str | None = None


class BrowserAudioSender(Protocol):
    """Connection-scoped response audio owned by the display server."""

    async def send_audio_start(
        self,
        *,
        turn_id: str,
        sample_rate: int,
        channels: int,
        sample_width: int,
    ) -> None: ...

    async def send_audio_chunk(self, data: bytes) -> None: ...

    async def send_audio_end(self, *, turn_id: str) -> None: ...

    async def send_audio_abort(self, *, turn_id: str, reason: str) -> None: ...

    async def close(self, *, code: int = 1000, reason: str = "") -> None: ...


class TouchSessionBinding(Protocol):
    """Appliance-owned capture and session state for one Touch socket."""

    publisher: DisplayStatePublisher

    async def handle_touch_frame(self, frame: TouchFrame) -> None: ...

    async def handle_touch_audio(self, data: bytes) -> None: ...

    async def handle_touch_malformed(self, reason: str = "malformed") -> None: ...

    async def close(self) -> None: ...


class BrowserSessionBinding(Protocol):
    """Appliance-owned state and callbacks for one accepted browser socket."""

    publisher: DisplayStatePublisher

    async def handle_action(
        self,
        action_id: str,
        choice: str,
        operation: str | None = None,
        object_id: str | None = None,
        freshness: str | None = None,
    ) -> None: ...

    async def handle_voice_turn(
        self, text: str, wake_phrase: str | None = None
    ) -> bool | None: ...

    async def handle_profile_route(
        self, wake_phrase: str
    ) -> BrowserProfileRouteResult: ...

    async def close(self) -> None: ...


class _ConnectionAudioSender:
    """Send response audio only through one state WebSocket."""

    def __init__(self, server: "DisplayServer", websocket: ServerConnection) -> None:
        self._server = server
        self._websocket = websocket

    async def send_audio_start(
        self,
        *,
        turn_id: str,
        sample_rate: int,
        channels: int,
        sample_width: int,
    ) -> None:
        self._server._validate_audio_format(
            turn_id=turn_id,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
        )
        sent = await self._server._send_connection_json(
            self._websocket,
            {
                "type": "audio_start",
                "schema": 1,
                "turn_id": turn_id,
                "sample_rate": sample_rate,
                "channels": channels,
                "sample_width": sample_width,
            },
        )
        if not sent:
            raise ConnectionError("browser connection is closed")

    async def send_audio_chunk(self, data: bytes) -> None:
        if not isinstance(data, bytes):
            raise TypeError("audio data must be bytes")
        if data:
            sent = await self._server._send_connection_frame(self._websocket, data)
            if not sent:
                raise ConnectionError("browser connection is closed")

    async def send_audio_end(self, *, turn_id: str) -> None:
        self._server._validate_turn_id(turn_id)
        sent = await self._server._send_connection_json(
            self._websocket,
            {"type": "audio_end", "schema": 1, "turn_id": turn_id},
        )
        if not sent:
            raise ConnectionError("browser connection is closed")

    async def send_audio_abort(self, *, turn_id: str, reason: str) -> None:
        self._server._validate_turn_id(turn_id)
        if not isinstance(reason, str) or not reason:
            raise ValueError("audio abort reason must be a non-empty string")
        sent = await self._server._send_connection_json(
            self._websocket,
            {
                "type": "audio_abort",
                "schema": 1,
                "turn_id": turn_id,
                "reason": reason[:256],
            },
        )
        if not sent:
            raise ConnectionError("browser connection is closed")

    async def send_control(self, payload: dict[str, object]) -> bool:
        """Send one JSON control frame to this socket alone.

        Touch admission answers (`mic_ready` / `mic_reject`) belong to the
        socket that asked. Broadcasting one would tell every other panel in
        the house that this one was admitted.
        """
        if not isinstance(payload, dict):
            raise TypeError("control payload must be a dict")
        return await self._server._send_connection_json(self._websocket, payload)

    async def close(self, *, code: int = 1000, reason: str = "") -> None:
        try:
            await self._websocket.close(code=code, reason=reason)
        except (ConnectionClosed, OSError):
            pass


@dataclass(frozen=True, slots=True)
class _Origin:
    scheme: str
    hostname: str
    port: int


_DEFAULT_ORIGIN_PORTS = {"http": 80, "https": 443}


def _parse_origin(origin: str, *, label: str = "origin") -> _Origin:
    """Parse an HTTP origin into the scheme/host/effective-port tuple."""
    if not isinstance(origin, str) or not origin or any(char.isspace() for char in origin):
        raise ValueError(f"{label} must be an origin URL")

    parsed = urlsplit(origin)
    scheme = parsed.scheme.casefold()
    if scheme not in _DEFAULT_ORIGIN_PORTS or parsed.hostname is None:
        raise ValueError(f"{label} must use http or https with a host")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{label} must not contain credentials, a path, query, or fragment")

    try:
        explicit_port = parsed.port
    except ValueError as error:
        raise ValueError(f"{label} has an invalid port") from error
    if explicit_port is not None and not 1 <= explicit_port <= 65535:
        raise ValueError(f"{label} has an invalid port")

    return _Origin(
        scheme=scheme,
        hostname=parsed.hostname.casefold(),
        port=(
            explicit_port
            if explicit_port is not None
            else _DEFAULT_ORIGIN_PORTS[scheme]
        ),
    )


def _format_url_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def load_tls_context(
    certificate: Path | str | None,
    private_key: Path | str | None,
) -> ssl.SSLContext | None:
    """Load an optional server certificate without inventing one at runtime."""
    if (certificate is None) != (private_key is None):
        raise ValueError("display TLS certificate and private key must be supplied together")
    if certificate is None or private_key is None:
        return None

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        context.load_cert_chain(certfile=certificate, keyfile=private_key)
    except (OSError, ValueError, ssl.SSLError) as error:
        raise ValueError(f"could not load display TLS certificate/key: {error}") from error
    return context


class DisplayServer:
    def __init__(
        self,
        publisher: DisplayStatePublisher,
        static_dir: Path,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        allow_remote: bool = False,
        on_action: Callable[..., Awaitable[None]] | None = None,
        on_voice_turn: Callable[[str], Awaitable[None]] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        public_origin: str | None = None,
        browser_session_limit: int = DEFAULT_BROWSER_SESSION_LIMIT,
        on_browser_connect: Callable[
            [str, BrowserAudioSender], Awaitable[BrowserSessionBinding]
        ]
        | None = None,
        browser_context_factory: Callable[
            [str, BrowserAudioSender], Awaitable[BrowserSessionBinding]
        ]
        | None = None,
        on_touch_connect: Callable[
            [str, BrowserAudioSender], Awaitable[TouchSessionBinding]
        ]
        | None = None,
    ) -> None:
        """Create a display server.

        on_action -- optional coroutine called when the display POSTs to
                     /action. It receives either the legacy (action_id,
                     choice) pair or the typed-choice action fields.
        on_voice_turn -- optional coroutine called when a same-origin browser
                        sends a recognized turn over the state WebSocket.
        on_browser_connect -- optional appliance callback that creates the
                             connection-scoped state/session binding. The
                             callback is called after a slot is reserved and
                             receives a private audio sender for this socket.
        browser_context_factory -- compatibility spelling for
                                  on_browser_connect.
        on_touch_connect -- optional appliance callback that creates the
                           connection-scoped ESP32 Touch doorway. Selecting
                           it puts this server in Touch mode: control frames
                           and binary microphone PCM are routed to the
                           doorway instead of the browser voice callbacks.
        """
        try:
            host_address = ipaddress.ip_address(host)
        except (ValueError, TypeError) as error:
            raise ValueError("host must be a loopback IP address") from error
        if not host_address.is_loopback and not allow_remote:
            raise ValueError("host must be a loopback IP address")
        if type(browser_session_limit) is not int or browser_session_limit <= 0:
            raise ValueError("browser_session_limit must be a positive integer")
        if on_browser_connect is not None and browser_context_factory is not None:
            raise ValueError(
                "on_browser_connect and browser_context_factory are mutually exclusive"
            )
        if on_touch_connect is not None and (
            on_browser_connect is not None or browser_context_factory is not None
        ):
            raise ValueError(
                "on_touch_connect cannot be combined with a browser context factory"
            )

        self._publisher = publisher
        self._static_dir = Path(static_dir).resolve()
        self._host = host
        self._port = port
        self._on_action = on_action
        self._on_voice_turn = on_voice_turn
        self._browser_context_factory = (
            on_browser_connect or browser_context_factory or on_touch_connect
        )
        self._touch_mode = on_touch_connect is not None
        self._browser_session_limit = browser_session_limit
        self._ssl_context = ssl_context
        self._public_origin = (
            _parse_origin(public_origin, label="public origin")
            if public_origin is not None
            else None
        )
        self._server: Server | None = None
        self._info: DisplayServerInfo | None = None
        self._state_connections: set[ServerConnection] = set()
        self._connection_locks: dict[ServerConnection, asyncio.Lock] = {}
        self._connection_bindings: dict[ServerConnection, BrowserSessionBinding] = {}
        self._connection_tasks: dict[ServerConnection, set[asyncio.Task[Any]]] = {}
        self._connection_cleanup_tasks: set[asyncio.Task[Any]] = set()
        self._reserved_browser_slots = 0

    @property
    def browser_session_limit(self) -> int:
        return self._browser_session_limit

    @property
    def browser_sessions_in_use(self) -> int:
        """Return admitted plus pending browser connections."""
        return self._reserved_browser_slots

    @property
    def browser_contexts_enabled(self) -> bool:
        """Whether each state socket receives its own appliance context."""
        return self._browser_context_factory is not None

    @property
    def touch_contexts_enabled(self) -> bool:
        """Whether each state socket is an ESP32 Touch doorway."""
        return self._touch_mode

    async def start(self) -> DisplayServerInfo:
        if self._server is not None:
            return self._info  # type: ignore[return-value]

        self._server = await serve(
            self._handle_state_connection,
            self._host,
            self._port,
            process_request=self._serve_http_request,
            ssl=self._ssl_context,
        )
        socket = self._server.sockets[0]
        bound_host, bound_port = socket.getsockname()[:2]
        self._info = DisplayServerInfo(
            host=str(bound_host), port=bound_port, secure=self._ssl_context is not None
        )
        return self._info

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        cleanup_tasks = tuple(
            task for task in self._connection_cleanup_tasks if not task.done()
        )
        if cleanup_tasks:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(*cleanup_tasks, return_exceptions=True),
                    CONNECTION_TASK_CLEANUP_TIMEOUT,
                )
        self._state_connections.clear()
        self._connection_locks.clear()
        self._connection_bindings.clear()
        self._connection_tasks.clear()
        self._reserved_browser_slots = 0
        self._server = None
        self._info = None

    async def send_audio_start(
        self,
        *,
        turn_id: str,
        sample_rate: int,
        channels: int,
        sample_width: int,
    ) -> None:
        """Broadcast a signed 16-bit PCM stream header to browser clients."""
        self._validate_audio_format(
            turn_id=turn_id,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
        )
        await self._broadcast_json(
            {
                "type": "audio_start",
                "schema": 1,
                "turn_id": turn_id,
                "sample_rate": sample_rate,
                "channels": channels,
                "sample_width": sample_width,
            }
        )

    async def send_audio_chunk(self, data: bytes) -> None:
        """Broadcast one raw signed 16-bit PCM chunk to browser clients."""
        if not isinstance(data, bytes):
            raise TypeError("audio data must be bytes")
        if data:
            await self._broadcast(data)

    async def send_audio_end(self, *, turn_id: str) -> None:
        self._validate_turn_id(turn_id)
        await self._broadcast_json(
            {"type": "audio_end", "schema": 1, "turn_id": turn_id}
        )

    async def send_audio_abort(self, *, turn_id: str, reason: str) -> None:
        self._validate_turn_id(turn_id)
        if not isinstance(reason, str) or not reason:
            raise ValueError("audio abort reason must be a non-empty string")
        await self._broadcast_json(
            {
                "type": "audio_abort",
                "schema": 1,
                "turn_id": turn_id,
                "reason": reason[:256],
            }
        )

    def resolve_static_path(self, request_path: str) -> Path:
        decoded_path = unquote(urlsplit(request_path).path)
        if not decoded_path.startswith("/"):
            raise ValueError("path must be absolute from the server root")

        relative_path = PurePosixPath(decoded_path[1:])
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("path must stay within the static directory")

        candidate = self._static_dir / Path(*relative_path.parts)
        try:
            resolved_path = candidate.resolve()
            resolved_path.relative_to(self._static_dir)
        except (OSError, RuntimeError, ValueError) as error:
            raise ValueError("path must stay within the static directory") from error
        return resolved_path

    async def _serve_http_request(
        self, _connection: ServerConnection, request: Request
    ) -> Response | None:
        path = urlsplit(request.path).path
        headers = request.headers
        if path == "/state":
            if not self._origin_is_allowed(headers.get("Origin")):
                return self._web_response(
                    self._http_response(HTTPStatus.FORBIDDEN, b"Forbidden\n")
                )
            if request.method != "GET":
                return self._web_response(
                    self._http_response(
                        HTTPStatus.METHOD_NOT_ALLOWED, b"Method Not Allowed\n"
                    )
                )
            return None
        if path == "/action":
            if not self._origin_is_allowed(headers.get("Origin")):
                return self._web_response(
                    self._http_response(HTTPStatus.FORBIDDEN, b"Forbidden\n")
                )
            if headers.get("Upgrade", "").lower() == "websocket":
                return self._web_response(
                    self._http_response(
                        HTTPStatus.BAD_REQUEST, b"Not a websocket endpoint\n"
                    )
                )
            if request.method != "POST":
                return self._web_response(
                    self._http_response(
                        HTTPStatus.METHOD_NOT_ALLOWED, b"Method Not Allowed\n"
                    )
                )
            return self._web_response(await self._handle_action_request(request.path))
        if headers.get("Upgrade", "").lower() == "websocket":
            return self._web_response(
                self._http_response(HTTPStatus.NOT_FOUND, b"Not found\n")
            )
        if request.method != "GET":
            return self._web_response(
                self._http_response(
                    HTTPStatus.METHOD_NOT_ALLOWED, b"Method Not Allowed\n"
                )
            )

        try:
            static_path = self.resolve_static_path(request.path)
        except ValueError:
            return self._web_response(
                self._http_response(HTTPStatus.FORBIDDEN, b"Forbidden\n")
            )

        if static_path.name == "":
            static_path /= "index.html"
        elif path == "/":
            static_path /= "index.html"

        if not static_path.is_file():
            return self._web_response(
                self._http_response(HTTPStatus.NOT_FOUND, b"Not found\n")
            )

        content_type, _encoding = mimetypes.guess_type(static_path.name)
        return self._web_response(
            self._http_response(
                HTTPStatus.OK,
                static_path.read_bytes(),
                content_type=content_type or "application/octet-stream",
            )
        )

    async def _handle_action_request(
        self, request_path: str
    ) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
        """Handle POST /action — the display's button-tap callback.

        The Svelte client encodes the payload in the query string because
        websockets' process_request only exposes headers, not the body:

            POST /action?action_id=sethome&choice=yes

        The on_action callback is scheduled as a fire-and-forget task so it
        does not block the HTTP response pipeline.  A missing or malformed
        query string returns 400; an absent on_action is silently ignored.
        """
        qs = parse_qs(urlsplit(request_path).query)
        action_ids = qs.get("action_id", [])
        choices = qs.get("choice", [])
        typed_names = {"operation", "option_id", "object_id", "freshness"}
        typed = {name: qs.get(name, []) for name in typed_names}
        typed_present = {name for name, values in typed.items() if values}
        if len(action_ids) != 1:
            return self._http_response(
                HTTPStatus.BAD_REQUEST,
                b'{"error": "action_id is required"}\n',
                content_type="application/json",
            )
        action_id = action_ids[0]
        action: tuple[str, ...] | None = None
        if not typed_present and len(choices) == 1 and 0 < len(choices[0]) <= 32:
            action = (action_id, choices[0])
        elif (
            typed_present == typed_names
            and not choices
            and all(len(values) == 1 for values in typed.values())
        ):
            operation = typed["operation"][0]
            option_id = typed["option_id"][0]
            object_id = typed["object_id"][0]
            freshness = typed["freshness"][0]
            if (
                operation in {"choose", "explore"}
                and 0 < len(option_id) <= 64
                and 0 < len(object_id) <= 64
                and 0 < len(freshness) <= 64
            ):
                action = (action_id, option_id, operation, object_id, freshness)
        if action is None or not 0 < len(action_id) <= 64:
            return self._http_response(
                HTTPStatus.BAD_REQUEST,
                b'{"error": "malformed display action"}\n',
                content_type="application/json",
            )
        if self._on_action is not None:
            loop = asyncio.get_event_loop()
            loop.create_task(self._on_action(*action))
        return self._http_response(
            HTTPStatus.OK, b"{}\n", content_type="application/json"
        )

    def _origin_is_allowed(self, origin: str | None) -> bool:
        if origin is None:
            return True
        if self._info is None:
            return False

        try:
            parsed_origin = _parse_origin(origin)
        except ValueError:
            return False

        listener_origin = _Origin(
            scheme="https" if self._ssl_context is not None else "http",
            hostname=self._info.host.casefold(),
            port=self._info.port,
        )
        return parsed_origin in {listener_origin, self._public_origin}

    async def _handle_state_connection(self, websocket: ServerConnection) -> None:
        closed = asyncio.create_task(websocket.wait_closed())
        isolated = self._browser_context_factory is not None
        slot_reserved = False
        if isolated and not self._reserve_browser_slot():
            closed.cancel()
            await asyncio.gather(closed, return_exceptions=True)
            with contextlib.suppress(ConnectionClosed, OSError):
                await websocket.close(
                    code=BROWSER_SESSION_CAPACITY_CODE,
                    reason=BROWSER_SESSION_CAPACITY_REASON,
                )
            return
        slot_reserved = isolated

        self._state_connections.add(websocket)
        self._connection_locks[websocket] = asyncio.Lock()
        self._connection_tasks[websocket] = set()
        binding: BrowserSessionBinding | None = None
        subscription: AsyncIterator[Any] | None = None
        next_snapshot: asyncio.Task[Any] | None = None
        incoming: asyncio.Task[Any] | None = None
        factory_task: asyncio.Task[Any] | None = None
        touch_queue: asyncio.Queue[Any] | None = None
        touch_worker: asyncio.Task[Any] | None = None
        try:
            if self._browser_context_factory is not None:
                sender = _ConnectionAudioSender(self, websocket)
                factory_task = asyncio.create_task(
                    self._browser_context_factory(
                        f"browser-{uuid.uuid4().hex}",
                        sender,
                    )
                )
                done, _pending = await asyncio.wait(
                    {factory_task, closed},
                    timeout=BROWSER_CONTEXT_SETUP_TIMEOUT,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    factory_task.cancel()
                    await asyncio.gather(factory_task, return_exceptions=True)
                    with contextlib.suppress(ConnectionClosed, OSError):
                        await websocket.close(
                            code=1011, reason="browser session unavailable"
                        )
                    return
                if closed in done:
                    if factory_task in done:
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            completed_binding = factory_task.result()
                            if completed_binding is not None:
                                await completed_binding.close()
                    else:
                        factory_task.cancel()
                        await asyncio.gather(factory_task, return_exceptions=True)
                    return
                binding = factory_task.result()
                if binding is None:
                    raise RuntimeError("browser context factory returned no context")
                self._connection_bindings[websocket] = binding
                subscription = binding.publisher.subscribe()
                if self._touch_mode:
                    # One serial consumer per socket. Microphone PCM arrives
                    # as many small frames; a task per frame would either
                    # exhaust the per-connection task budget or let chunks
                    # land out of order, and a reordered capture is a
                    # corrupted one.
                    touch_queue = asyncio.Queue(maxsize=TOUCH_INGRESS_QUEUE_MAX)
                    touch_worker = asyncio.create_task(
                        self._run_touch_ingress(binding, touch_queue)
                    )
            else:
                subscription = self._publisher.subscribe()

            next_snapshot = asyncio.create_task(anext(subscription))
            incoming = asyncio.create_task(websocket.recv())
            while True:
                pending_tasks = {next_snapshot, closed, incoming}
                done, _pending = await asyncio.wait(
                    pending_tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if closed in done:
                    return

                if incoming in done:
                    if self._touch_mode:
                        try:
                            message = incoming.result()
                        except ConnectionClosed:
                            return
                        if touch_queue is not None:
                            self._enqueue_touch_message(touch_queue, message)
                        incoming = asyncio.create_task(websocket.recv())
                        if next_snapshot in done:
                            snapshot = next_snapshot.result()
                            if not await self._send_frame(
                                websocket, json.dumps(snapshot.to_dict())
                            ):
                                return
                            next_snapshot = asyncio.create_task(anext(subscription))
                        continue
                    try:
                        message = incoming.result()
                        action = self._parse_websocket_action(message)
                        voice_turn = self._parse_websocket_voice_turn(message)
                        profile_route = self._parse_websocket_profile_route(message)
                    except ConnectionClosed:
                        return
                    if binding is not None:
                        if action is not None:
                            self._track_connection_task(
                                websocket, binding.handle_action(*action)
                            )
                        if profile_route is not None:
                            route_task = self._dispatch_profile_route(
                                websocket,
                                binding,
                                *profile_route,
                            )
                            if not self._track_connection_task(websocket, route_task):
                                await self._send_profile_route_ack(
                                    websocket,
                                    profile_route[0],
                                    accepted=False,
                                    reason="busy",
                                )
                        else:
                            malformed_request_id = (
                                self._parse_websocket_profile_route_request_id(message)
                            )
                            if malformed_request_id is not None:
                                await self._send_profile_route_ack(
                                    websocket,
                                    malformed_request_id,
                                    accepted=False,
                                    reason="malformed_request",
                                )
                        if voice_turn is not None:
                            if voice_turn.wake_phrase is None:
                                callback = binding.handle_voice_turn(voice_turn.text)
                            else:
                                callback = binding.handle_voice_turn(
                                    voice_turn.text,
                                    voice_turn.wake_phrase,
                                )
                            self._track_connection_task(websocket, callback)
                    else:
                        if (
                            action is not None
                            and len(action) == 2
                            and self._on_action is not None
                        ):
                            self._track_connection_task(
                                websocket, self._on_action(*action)
                            )
                        if (
                            voice_turn is not None
                            and voice_turn.wake_phrase is None
                            and self._on_voice_turn is not None
                        ):
                            self._track_connection_task(
                                websocket, self._on_voice_turn(voice_turn.text)
                            )
                    incoming = asyncio.create_task(websocket.recv())

                if next_snapshot in done:
                    snapshot = next_snapshot.result()
                    if not await self._send_frame(websocket, json.dumps(snapshot.to_dict())):
                        return
                    next_snapshot = asyncio.create_task(anext(subscription))
        except ConnectionClosed:
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            with contextlib.suppress(ConnectionClosed, OSError):
                await websocket.close(code=1011, reason="browser session unavailable")
            return
        finally:
            for task in (factory_task, next_snapshot, closed, incoming, touch_worker):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(
                    task
                    for task in (
                        factory_task,
                        next_snapshot,
                        closed,
                        incoming,
                        touch_worker,
                    )
                    if task is not None
                ),
                return_exceptions=True,
            )
            connection_tasks = self._connection_tasks.pop(websocket, set())
            for task in connection_tasks:
                if not task.done():
                    task.cancel()
            await self._cancel_connection_tasks(connection_tasks)
            if binding is not None:
                with contextlib.suppress(Exception):
                    await binding.close()
            if subscription is not None:
                with contextlib.suppress(Exception):
                    await subscription.aclose()  # type: ignore[attr-defined]
            self._forget_connection(websocket)
            if slot_reserved:
                self._release_browser_slot()

    # ---- Touch ingress -------------------------------------------------

    def _enqueue_touch_message(
        self, queue: asyncio.Queue[Any], message: str | bytes
    ) -> None:
        """Validate one Touch frame's shape and hand it to the serial consumer."""
        if isinstance(message, (bytes, bytearray, memoryview)):
            data = bytes(message)
            item: Any
            if (
                not data
                or len(data) % TOUCH_PCM_SAMPLE_WIDTH
                or len(data) > MAX_PCM_CHUNK_BYTES
            ):
                item = _TOUCH_MALFORMED
            else:
                item = data
        else:
            frame = self._parse_touch_frame(message)
            item = _TOUCH_MALFORMED if frame is None else frame
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            # The endpoint is sending faster than this host can consume. The
            # capture is already unusable, so drop the backlog and make that
            # explicit rather than submitting a prompt with holes in it.
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(_TOUCH_OVERFLOW)

    async def _run_touch_ingress(
        self, binding: TouchSessionBinding, queue: asyncio.Queue[Any]
    ) -> None:
        """Apply Touch frames one at a time, in the order they arrived."""
        while True:
            item = await queue.get()
            try:
                if item is _TOUCH_OVERFLOW:
                    await binding.handle_touch_malformed("overflow")
                elif item is _TOUCH_MALFORMED:
                    await binding.handle_touch_malformed("malformed")
                elif isinstance(item, bytes):
                    await binding.handle_touch_audio(item)
                else:
                    await binding.handle_touch_frame(item)
            except asyncio.CancelledError:
                raise
            except Exception:
                with contextlib.suppress(Exception):
                    await binding.handle_touch_malformed("unavailable")

    @staticmethod
    def _bounded_token(value: Any, limit: int) -> str | None:
        if (
            not isinstance(value, str)
            or not 0 < len(value) <= limit
            or any(char.isspace() for char in value)
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            return None
        return value

    @classmethod
    def _parse_touch_frame(cls, message: str | bytes) -> TouchFrame | None:
        """Accept only the schema-1 Touch control frames, with bounded ids."""
        if not isinstance(message, (str, bytes)):
            return None
        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        frame_type = payload.get("type")
        if (
            frame_type not in TOUCH_CONTROL_FRAMES
            or type(payload.get("schema")) is not int
            or payload.get("schema") != 1
        ):
            return None

        reason = payload.get("reason")
        if reason is not None:
            reason = cls._bounded_token(reason, MAX_TOUCH_REASON_LENGTH)
            if reason is None:
                return None

        if frame_type in TOUCH_CAPTURE_FRAMES:
            capture_id = cls._bounded_token(
                payload.get("capture_id"), MAX_CAPTURE_ID_LENGTH
            )
            if capture_id is None:
                return None
            return TouchFrame(
                type=str(frame_type), capture_id=capture_id, reason=reason
            )
        if frame_type in TOUCH_TURN_FRAMES:
            turn_id = cls._bounded_token(
                payload.get("turn_id"), MAX_TOUCH_TURN_ID_LENGTH
            )
            if turn_id is None:
                return None
            return TouchFrame(type=str(frame_type), turn_id=turn_id, reason=reason)
        return TouchFrame(type=str(frame_type), reason=reason)

    def _reserve_browser_slot(self) -> bool:
        if self._reserved_browser_slots >= self._browser_session_limit:
            return False
        self._reserved_browser_slots += 1
        return True

    def _release_browser_slot(self) -> None:
        self._reserved_browser_slots = max(0, self._reserved_browser_slots - 1)

    def _track_connection_task(
        self, websocket: ServerConnection, awaitable: Awaitable[Any]
    ) -> bool:
        tasks = self._connection_tasks.get(websocket)
        if tasks is None or len(tasks) >= MAX_CONNECTION_TASKS:
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            else:
                cancel = getattr(awaitable, "cancel", None)
                if callable(cancel):
                    cancel()
            return False
        task = asyncio.create_task(awaitable)
        tasks.add(task)

        def discard(done: asyncio.Task[Any]) -> None:
            tasks.discard(done)
            with contextlib.suppress(asyncio.CancelledError, Exception):
                done.result()

        task.add_done_callback(discard)
        return True

    async def _cancel_connection_tasks(
        self, tasks: set[asyncio.Task[Any]]
    ) -> None:
        if not tasks:
            return
        for task in tasks:
            if not task.done():
                task.cancel()

        async def wait_for_tasks() -> None:
            await asyncio.gather(*tasks, return_exceptions=True)

        cleanup_task = asyncio.create_task(wait_for_tasks())
        try:
            await asyncio.wait_for(
                asyncio.shield(cleanup_task), CONNECTION_TASK_CLEANUP_TIMEOUT
            )
        except asyncio.TimeoutError:
            self._retain_connection_cleanup(cleanup_task)
        except asyncio.CancelledError:
            self._retain_connection_cleanup(cleanup_task)

    def _retain_connection_cleanup(self, task: asyncio.Task[Any]) -> None:
        self._connection_cleanup_tasks.add(task)

        def finished(done: asyncio.Task[Any]) -> None:
            self._connection_cleanup_tasks.discard(done)
            with contextlib.suppress(asyncio.CancelledError, Exception):
                done.result()

        task.add_done_callback(finished)

    async def _broadcast_json(self, payload: dict[str, object]) -> None:
        await self._broadcast(json.dumps(payload))

    async def _broadcast(self, frame: str | bytes) -> None:
        connections = tuple(self._state_connections)
        if not connections:
            return
        await asyncio.gather(
            *(self._send_frame(connection, frame) for connection in connections),
            return_exceptions=True,
        )

    async def _send_connection_json(
        self, websocket: ServerConnection, payload: dict[str, object]
    ) -> bool:
        return await self._send_connection_frame(websocket, json.dumps(payload))

    async def _send_connection_frame(
        self, websocket: ServerConnection, frame: str | bytes
    ) -> bool:
        return await self._send_frame(websocket, frame)

    async def _send_frame(self, websocket: ServerConnection, frame: str | bytes) -> bool:
        lock = self._connection_locks.get(websocket)
        if lock is None:
            return False
        try:
            async with lock:
                await websocket.send(frame)
        except (ConnectionClosed, OSError):
            self._forget_connection(websocket)
            return False
        return True

    async def _dispatch_profile_route(
        self,
        websocket: ServerConnection,
        binding: BrowserSessionBinding,
        request_id: str,
        wake_phrase: str,
    ) -> None:
        """Resolve one browser route and return its result to that socket."""
        handler = getattr(binding, "handle_profile_route", None)
        if not callable(handler):
            result = BrowserProfileRouteResult(
                accepted=False,
                reason="unsupported",
            )
        else:
            try:
                result = await handler(wake_phrase)
            except Exception:
                result = BrowserProfileRouteResult(
                    accepted=False,
                    reason="unavailable",
                )
            if not isinstance(result, BrowserProfileRouteResult):
                result = BrowserProfileRouteResult(
                    accepted=bool(result),
                    reason=None if result else "unavailable",
                )

        await self._send_profile_route_ack(
            websocket,
            request_id,
            accepted=result.accepted,
            account=result.account if result.accepted else None,
            reason=result.reason if not result.accepted else None,
        )

    async def _send_profile_route_ack(
        self,
        websocket: ServerConnection,
        request_id: str,
        *,
        accepted: bool,
        account: str | None = None,
        reason: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "type": "profile_route_ack",
            "schema": 1,
            "request_id": request_id,
            "accepted": accepted,
        }
        if accepted and account:
            payload["account"] = account[:128]
        elif not accepted and reason:
            payload["reason"] = reason[:64]
        await self._send_connection_json(websocket, payload)

    def _forget_connection(self, websocket: ServerConnection) -> None:
        self._state_connections.discard(websocket)
        self._connection_locks.pop(websocket, None)
        self._connection_bindings.pop(websocket, None)

    @staticmethod
    def _validate_turn_id(turn_id: str) -> None:
        if not isinstance(turn_id, str) or not 0 < len(turn_id) <= 128:
            raise ValueError("turn_id must be a non-empty string of at most 128 characters")

    @classmethod
    def _validate_audio_format(
        cls,
        *,
        turn_id: str,
        sample_rate: int,
        channels: int,
        sample_width: int,
    ) -> None:
        cls._validate_turn_id(turn_id)
        if type(sample_rate) is not int or sample_rate <= 0:
            raise ValueError("sample_rate must be a positive integer")
        if type(channels) is not int or not 0 < channels <= 8:
            raise ValueError("channels must be between 1 and 8")
        if sample_width != 2:
            raise ValueError("browser audio requires signed 16-bit PCM")

    @staticmethod
    def _parse_websocket_action(
        message: str | bytes,
    ) -> tuple[str, str] | tuple[str, str, str, str, str] | None:
        if not isinstance(message, (str, bytes)):
            return None
        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        if (
            payload.get("type") != "action"
            or type(payload.get("schema")) is not int
            or payload.get("schema") != 1
        ):
            return None
        action_id = payload.get("action_id")
        choice = payload.get("choice")
        if not isinstance(action_id, str) or not 0 < len(action_id) <= 64:
            return None
        typed_names = {"operation", "option_id", "object_id", "freshness"}
        typed_present = typed_names.intersection(payload)
        if not typed_present and isinstance(choice, str) and 0 < len(choice) <= 32:
            return action_id, choice
        if typed_present != typed_names or "choice" in payload:
            return None
        operation = payload.get("operation")
        option_id = payload.get("option_id")
        object_id = payload.get("object_id")
        freshness = payload.get("freshness")
        if (
            not isinstance(operation, str)
            or operation not in {"choose", "explore"}
            or not isinstance(option_id, str)
            or not 0 < len(option_id) <= 64
            or not isinstance(object_id, str)
            or not 0 < len(object_id) <= 64
            or not isinstance(freshness, str)
            or not 0 < len(freshness) <= 64
        ):
            return None
        return action_id, option_id, operation, object_id, freshness

    @staticmethod
    def _parse_websocket_voice_turn(
        message: str | bytes,
    ) -> BrowserVoiceTurn | None:
        if not isinstance(message, (str, bytes)):
            return None
        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        if (
            payload.get("type") != "voice_turn"
            or type(payload.get("schema")) is not int
            or payload.get("schema") != 1
        ):
            return None
        text = payload.get("text")
        if not isinstance(text, str):
            return None
        text = text.strip()
        if not 0 < len(text) <= 4000:
            return None
        wake_phrase: str | None = None
        if "wake_phrase" in payload:
            raw_phrase = payload.get("wake_phrase")
            if (
                not isinstance(raw_phrase, str)
                or not 0 < len(raw_phrase) <= MAX_BROWSER_WAKE_PHRASE_LENGTH
                or any(ord(char) < 32 or ord(char) == 127 for char in raw_phrase)
            ):
                return None
            wake_phrase = raw_phrase.strip()
            if not wake_phrase:
                return None
        return BrowserVoiceTurn(text=text, wake_phrase=wake_phrase)

    @staticmethod
    def _parse_websocket_profile_route(
        message: str | bytes,
    ) -> tuple[str, str] | None:
        if not isinstance(message, (str, bytes)):
            return None
        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        if (
            payload.get("type") != "profile_route"
            or type(payload.get("schema")) is not int
            or payload.get("schema") != 1
        ):
            return None
        request_id = payload.get("request_id")
        wake_phrase = payload.get("wake_phrase")
        if (
            not isinstance(request_id, str)
            or not 0 < len(request_id) <= MAX_BROWSER_ROUTE_REQUEST_ID_LENGTH
            or any(char.isspace() for char in request_id)
            or any(ord(char) < 32 or ord(char) == 127 for char in request_id)
            or not isinstance(wake_phrase, str)
            or not 0 < len(wake_phrase) <= MAX_BROWSER_WAKE_PHRASE_LENGTH
            or any(ord(char) < 32 or ord(char) == 127 for char in wake_phrase)
        ):
            return None
        wake_phrase = wake_phrase.strip()
        if not wake_phrase:
            return None
        return request_id, wake_phrase

    @staticmethod
    def _parse_websocket_profile_route_request_id(
        message: str | bytes,
    ) -> str | None:
        """Recover a safe request id so malformed routes still receive an ACK."""
        if not isinstance(message, (str, bytes)):
            return None
        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        if (
            payload.get("type") != "profile_route"
            or type(payload.get("schema")) is not int
            or payload.get("schema") != 1
        ):
            return None
        request_id = payload.get("request_id")
        if (
            not isinstance(request_id, str)
            or not 0 < len(request_id) <= MAX_BROWSER_ROUTE_REQUEST_ID_LENGTH
            or any(char.isspace() for char in request_id)
            or any(ord(char) < 32 or ord(char) == 127 for char in request_id)
        ):
            return None
        return request_id

    @staticmethod
    def _http_response(
        status: HTTPStatus, body: bytes, *, content_type: str = "text/plain"
    ) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
        return status, [("Content-Type", content_type)], body

    @staticmethod
    def _web_response(
        response: tuple[HTTPStatus, list[tuple[str, str]], bytes]
    ) -> Response:
        status, headers, body = response
        return Response(status, status.phrase, Headers(headers), body)
