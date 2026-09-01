import asyncio
import json
from urllib.request import urlopen

import pytest
from websockets.legacy.client import connect

from home_display.server import DisplayServer
from home_display.state import DisplayStatePublisher


@pytest.mark.asyncio
async def test_server_serves_index_html_and_current_state(tmp_path):
    (tmp_path / "index.html").write_text("home", encoding="utf-8")
    server = DisplayServer(DisplayStatePublisher(), tmp_path)
    info = await server.start()
    try:
        assert info.host == "127.0.0.1"
        assert await asyncio.to_thread(lambda: urlopen(info.http_url).read()) == b"home"
        async with connect(info.websocket_url) as socket:
            assert json.loads(await socket.recv())["state"] == "idle"
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_server_pushes_published_state_without_reconnecting(tmp_path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    publisher = DisplayStatePublisher()
    server = DisplayServer(publisher, tmp_path)
    info = await server.start()
    try:
        async with connect(info.websocket_url) as socket:
            await socket.recv()
            publisher.publish(state="speaking", response_text="one block")
            update = json.loads(await socket.recv())
        assert update["response_text"] == "one block"
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_server_serves_mime_typed_static_assets(tmp_path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('home')", encoding="utf-8")
    server = DisplayServer(DisplayStatePublisher(), tmp_path)
    info = await server.start()
    try:
        response = await asyncio.to_thread(lambda: urlopen(f"{info.http_url}app.js"))
        assert response.read() == b"console.log('home')"
        assert response.headers.get_content_type() == "text/javascript"
    finally:
        await server.close()


def test_static_path_escape_is_rejected(tmp_path):
    server = DisplayServer(DisplayStatePublisher(), tmp_path)

    with pytest.raises(ValueError, match="path"):
        server.resolve_static_path("/../secret")


def test_static_path_rejects_absolute_path_after_url_decoding(tmp_path):
    server = DisplayServer(DisplayStatePublisher(), tmp_path)

    with pytest.raises(ValueError, match="path"):
        server.resolve_static_path("/%2Fetc%2Fpasswd")
