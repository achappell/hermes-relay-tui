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

from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.legacy.server import WebSocketServer, WebSocketServerProtocol, serve

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
    ) -> None:
        """Create a display server.

        on_action -- optional coroutine called when the display POSTs to
                     /action.  Receives (action_id, choice) where both are
                     strings supplied by the Svelte client via query params:
                       POST /action?action_id=sethome&choice=yes
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
        self._server: WebSocketServer | None = None
        self._info: DisplayServerInfo | None = None

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
        self._server = None
        self._info = None

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
        self, request_path: str, headers: Headers
    ) -> tuple[HTTPStatus, list[tuple[str, str]], bytes] | None:
        path = urlsplit(request_path).path
        if path == "/state":
            if not self._origin_is_allowed(headers.get("Origin")):
                return self._http_response(HTTPStatus.FORBIDDEN, b"Forbidden\n")
            return None
        if path == "/action":
            if not self._origin_is_allowed(headers.get("Origin")):
                return self._http_response(HTTPStatus.FORBIDDEN, b"Forbidden\n")
            if headers.get("Upgrade", "").lower() == "websocket":
                return self._http_response(HTTPStatus.BAD_REQUEST, b"Not a websocket endpoint\n")
            return await self._handle_action_request(request_path)
        if headers.get("Upgrade", "").lower() == "websocket":
            return self._http_response(HTTPStatus.NOT_FOUND, b"Not found\n")

        try:
            static_path = self.resolve_static_path(request_path)
        except ValueError:
            return self._http_response(HTTPStatus.FORBIDDEN, b"Forbidden\n")

        if static_path.name == "":
            static_path /= "index.html"
        elif path == "/":
            static_path /= "index.html"

        if not static_path.is_file():
            return self._http_response(HTTPStatus.NOT_FOUND, b"Not found\n")

        content_type, _encoding = mimetypes.guess_type(static_path.name)
        return self._http_response(
            HTTPStatus.OK,
            static_path.read_bytes(),
            content_type=content_type or "application/octet-stream",
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

    async def _handle_state_connection(self, websocket: WebSocketServerProtocol) -> None:
        subscription = self._publisher.subscribe()
        next_snapshot = asyncio.create_task(anext(subscription))
        closed = asyncio.create_task(websocket.wait_closed())
        try:
            while True:
                done, _pending = await asyncio.wait(
                    {next_snapshot, closed}, return_when=asyncio.FIRST_COMPLETED
                )
                if closed in done:
                    return

                snapshot = next_snapshot.result()
                await websocket.send(json.dumps(snapshot.to_dict()))
                next_snapshot = asyncio.create_task(anext(subscription))
        except ConnectionClosed:
            return
        finally:
            if not next_snapshot.done():
                next_snapshot.cancel()
                await asyncio.gather(next_snapshot, return_exceptions=True)
            if not closed.done():
                closed.cancel()
                await asyncio.gather(closed, return_exceptions=True)
            await subscription.aclose()  # type: ignore[attr-defined]

    @staticmethod
    def _http_response(
        status: HTTPStatus, body: bytes, *, content_type: str = "text/plain"
    ) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
        return status, [("Content-Type", content_type)], body
