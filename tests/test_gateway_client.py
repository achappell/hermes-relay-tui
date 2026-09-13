import asyncio
import json
import logging

import pytest

from gateway_client import (
    GatewayClient,
    GatewayTransportError,
    gateway_url_with_token,
    redact_gateway_url,
)


_CLOSE = object()


class FakeSocket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = asyncio.Event()

    async def send(self, data):
        self.sent.append(json.loads(data))

    async def recv(self):
        frame = await self.incoming.get()
        if frame is _CLOSE:
            raise ConnectionError("socket closed")
        return frame

    async def wait_closed(self):
        await self.closed.wait()

    def feed(self, payload):
        self.incoming.put_nowait(json.dumps(payload))

    def close_transport(self):
        self.closed.set()
        self.incoming.put_nowait(_CLOSE)


class FakeContextManager:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, exc_type, exc, tb):
        self.socket.closed.set()


async def connect_client():
    socket = FakeSocket()
    calls = []

    def connect(url, **kwargs):
        calls.append((url, kwargs))
        return FakeContextManager(socket)

    client = GatewayClient(
        "ws://hermes.example/api/ws?skin=terminal",
        "secret-token",
        connect_factory=connect,
    )
    opening = asyncio.create_task(client.connect())
    await asyncio.sleep(0)
    socket.feed(
        {
            "jsonrpc": "2.0",
            "method": "event",
            "params": {
                "type": "gateway.ready",
                "payload": {"skin": "default", "heartbeat": True},
            },
        }
    )
    ready = await opening
    return client, socket, calls, ready


@pytest.mark.asyncio
async def test_gateway_ready_uses_query_token_and_one_reader(caplog):
    caplog.set_level(logging.DEBUG, logger="hermes_relay_tui")
    client, socket, calls, ready = await connect_client()

    assert ready["type"] == "gateway.ready"
    assert calls[0][0] == gateway_url_with_token(
        "ws://hermes.example/api/ws?skin=terminal", "secret-token"
    )
    assert "secret-token" not in caplog.text
    assert "REDACTED" in caplog.text

    request = asyncio.create_task(client.request("session.create", {"source": "tui"}))
    await asyncio.sleep(0)
    request_id = socket.sent[-1]["id"]
    # An unrelated reply must not satisfy this request.
    socket.feed({"jsonrpc": "2.0", "id": "unrelated", "result": {"wrong": True}})
    socket.feed(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"session_id": "runtime-1"},
        }
    )
    assert await request == {"session_id": "runtime-1"}

    await client.close()
    assert client.is_connected is False


def test_gateway_url_replaces_existing_token_without_logging_it():
    url = gateway_url_with_token(
        "wss://example.test/api/ws?token=old&skin=default", "new token"
    )
    assert url == "wss://example.test/api/ws?skin=default&token=new+token"
    assert "new+token" not in redact_gateway_url(url)
    assert "REDACTED" in redact_gateway_url(url)


@pytest.mark.asyncio
async def test_reader_failure_unblocks_events_with_a_transport_error():
    client, socket, _calls, _ready = await connect_client()

    socket.close_transport()
    with pytest.raises(GatewayTransportError):
        await client.next_event()
    assert client.is_connected is False
    await client.close()
