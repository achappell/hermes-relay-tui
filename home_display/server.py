from __future__ import annotations

import asyncio
import ipaddress
import json
import mimetypes
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Awaitable, Callable
from urllib.parse import parse_qs, unquote, urlsplit

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from .state import DisplayStatePublisher

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass(frozen=True, slots=True)
class DisplayServerInfo:
    host: str
    port: int

    @property
    def http_url(self) -> str:
        return f"http://{_format_url_host(self.host)}:{self.port}/"

    @property
    def websocket_url(self) -> str:
        return f"ws://{_format_url_host(self.host)}:{self.port}/state"


def _format_url_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


class DisplayServer:
    def __init__(
        self,
        publisher: DisplayStatePublisher,
        static_dir: Path,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        allow_remote: bool = False,
        on_action: Callable[[str, str], Awaitable[None]] | None = None,
        on_voice_turn: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Create a display server.

        on_action -- optional coroutine called when the display POSTs to
                     /action.  Receives (action_id, choice) where both are
                     strings supplied by the Svelte client via query params:
                       POST /action?action_id=sethome&choice=yes
        on_voice_turn -- optional coroutine called when a same-origin browser
                        sends a recognized turn over the state WebSocket.
        """
        try:
            host_address = ipaddress.ip_address(host)
        except (ValueError, TypeError) as error:
            raise ValueError("host must be a loopback IP address") from error
        if not host_address.is_loopback and not allow_remote:
            raise ValueError("host must be a loopback IP address")

        self._publisher = publisher
        self._static_dir = Path(static_dir).resolve()
        self._host = host
        self._port = port
        self._on_action = on_action
        self._on_voice_turn = on_voice_turn
        self._server: Server | None = None
        self._info: DisplayServerInfo | None = None
        self._state_connections: set[ServerConnection] = set()
        self._connection_locks: dict[ServerConnection, asyncio.Lock] = {}

    async def start(self) -> DisplayServerInfo:
        if self._server is not None:
            return self._info  # type: ignore[return-value]

        self._server = await serve(
            self._handle_state_connection,
            self._host,
            self._port,
            process_request=self._serve_http_request,
        )
        socket = self._server.sockets[0]
        bound_host, bound_port = socket.getsockname()[:2]
        self._info = DisplayServerInfo(host=str(bound_host), port=bound_port)
        return self._info

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._state_connections.clear()
        self._connection_locks.clear()
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
        if not action_ids or not choices:
            return self._http_response(
                HTTPStatus.BAD_REQUEST,
                b'{"error": "action_id and choice are required"}\n',
                content_type="application/json",
            )
        action_id = action_ids[0]
        choice = choices[0]
        if self._on_action is not None:
            loop = asyncio.get_event_loop()
            loop.create_task(self._on_action(action_id, choice))
        return self._http_response(
            HTTPStatus.OK, b"{}\n", content_type="application/json"
        )

    def _origin_is_allowed(self, origin: str | None) -> bool:
        if origin is None:
            return True
        if self._info is None:
            return False

        parsed_origin = urlsplit(origin)
        try:
            origin_port = parsed_origin.port
        except ValueError:
            return False
        return (
            parsed_origin.scheme == "http"
            and parsed_origin.hostname == self._info.host
            and origin_port == self._info.port
            and parsed_origin.username is None
            and parsed_origin.password is None
            and parsed_origin.path in ("", "/")
            and not parsed_origin.query
            and not parsed_origin.fragment
        )

    async def _handle_state_connection(self, websocket: ServerConnection) -> None:
        self._state_connections.add(websocket)
        self._connection_locks[websocket] = asyncio.Lock()
        subscription = self._publisher.subscribe()
        next_snapshot = asyncio.create_task(anext(subscription))
        closed = asyncio.create_task(websocket.wait_closed())
        incoming = asyncio.create_task(websocket.recv())
        try:
            while True:
                done, _pending = await asyncio.wait(
                    {next_snapshot, closed, incoming}, return_when=asyncio.FIRST_COMPLETED
                )
                if closed in done:
                    return

                if incoming in done:
                    try:
                        message = incoming.result()
                        action = self._parse_websocket_action(message)
                        voice_text = self._parse_websocket_voice_turn(message)
                    except ConnectionClosed:
                        return
                    if action is not None and self._on_action is not None:
                        loop = asyncio.get_event_loop()
                        loop.create_task(self._on_action(*action))
                    if voice_text is not None and self._on_voice_turn is not None:
                        loop = asyncio.get_event_loop()
                        loop.create_task(self._on_voice_turn(voice_text))
                    incoming = asyncio.create_task(websocket.recv())

                if next_snapshot in done:
                    snapshot = next_snapshot.result()
                    if not await self._send_frame(websocket, json.dumps(snapshot.to_dict())):
                        return
                    next_snapshot = asyncio.create_task(anext(subscription))
        except ConnectionClosed:
            return
        finally:
            for task in (next_snapshot, closed, incoming):
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await subscription.aclose()  # type: ignore[attr-defined]
            self._forget_connection(websocket)

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

    def _forget_connection(self, websocket: ServerConnection) -> None:
        self._state_connections.discard(websocket)
        self._connection_locks.pop(websocket, None)

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
    def _parse_websocket_action(message: str | bytes) -> tuple[str, str] | None:
        if not isinstance(message, (str, bytes)):
            return None
        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("type") != "action" or payload.get("schema") != 1:
            return None
        action_id = payload.get("action_id")
        choice = payload.get("choice")
        if (
            not isinstance(action_id, str)
            or not 0 < len(action_id) <= 64
            or not isinstance(choice, str)
            or not 0 < len(choice) <= 32
        ):
            return None
        return action_id, choice

    @staticmethod
    def _parse_websocket_voice_turn(message: str | bytes) -> str | None:
        if not isinstance(message, (str, bytes)):
            return None
        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("type") != "voice_turn" or payload.get("schema") != 1:
            return None
        text = payload.get("text")
        if not isinstance(text, str):
            return None
        text = text.strip()
        if not 0 < len(text) <= 4000:
            return None
        return text

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
