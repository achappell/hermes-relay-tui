from __future__ import annotations

import asyncio
import json
import mimetypes
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

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
        return f"http://{self.host}:{self.port}/"

    @property
    def websocket_url(self) -> str:
        return f"ws://{self.host}:{self.port}/state"


class DisplayServer:
    def __init__(
        self,
        publisher: DisplayStatePublisher,
        static_dir: Path,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self._publisher = publisher
        self._static_dir = Path(static_dir).resolve()
        self._host = host
        self._port = port
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

        return self._static_dir / Path(*relative_path.parts)

    async def _serve_http_request(
        self, request_path: str, _headers: object
    ) -> tuple[HTTPStatus, list[tuple[str, str]], bytes] | None:
        if urlsplit(request_path).path == "/state":
            return None

        try:
            static_path = self.resolve_static_path(request_path)
        except ValueError:
            return self._http_response(HTTPStatus.FORBIDDEN, b"Forbidden\n")

        if static_path.name == "":
            static_path /= "index.html"
        elif urlsplit(request_path).path == "/":
            static_path /= "index.html"

        if not static_path.is_file():
            return self._http_response(HTTPStatus.NOT_FOUND, b"Not found\n")

        content_type, _encoding = mimetypes.guess_type(static_path.name)
        return self._http_response(
            HTTPStatus.OK,
            static_path.read_bytes(),
            content_type=content_type or "application/octet-stream",
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
