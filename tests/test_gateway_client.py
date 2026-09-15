import asyncio
import json
import logging

import pytest

import gateway_client as gateway_client_module
from gateway_client import (
    GatewayClient,
    GatewayProtocolError,
    STANDARD_HERMES_COMMIT,
    STANDARD_HERMES_VERSION,
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


def test_standard_boundary_is_pinned_to_the_approved_revision():
    assert STANDARD_HERMES_VERSION == "0.21.1"
    assert STANDARD_HERMES_COMMIT == "2237be355906fbe6065ce1815711eee52b2d646e"


@pytest.mark.asyncio
async def test_gateway_rejects_a_non_standard_endpoint_before_connecting():
    client = GatewayClient("wss://hermes.example/voice-session", "secret-token")

    with pytest.raises(GatewayProtocolError, match="/api/ws"):
        await client.connect()


@pytest.mark.asyncio
async def test_gateway_rejects_non_json_rpc_frames():
    client, socket, _calls, _ready = await connect_client()
    socket.feed(
        {
            "method": "event",
            "params": {"type": "message.delta", "payload": {"text": "unsafe"}},
        }
    )

    with pytest.raises(GatewayProtocolError):
        await client.next_event()
    await client.close()


@pytest.mark.asyncio
async def test_gateway_request_timeout_fails_the_connection_without_replaying(
    monkeypatch,
):
    client, socket, _calls, _ready = await connect_client()
    monkeypatch.setattr(gateway_client_module, "GATEWAY_REQUEST_TIMEOUT", 0.01)

    with pytest.raises(GatewayTransportError, match="session.create"):
        await client.request("session.create", {"source": "tui"})

    assert client.is_connected is False
    assert [frame["method"] for frame in socket.sent] == ["session.create"]
    await client.close()


@pytest.mark.asyncio
async def test_gateway_reply_with_matching_id_but_no_result_or_error_is_protocol_failure():
    client, socket, _calls, _ready = await connect_client()
    request = asyncio.create_task(client.request("session.create", {"source": "tui"}))
    await asyncio.sleep(0)
    request_id = socket.sent[-1]["id"]
    socket.feed({"jsonrpc": "2.0", "id": request_id})

    with pytest.raises(GatewayProtocolError, match="neither result nor error"):
        await request
    await client.close()


@pytest.mark.asyncio
async def test_gateway_reply_with_result_and_error_is_protocol_failure():
    client, socket, _calls, _ready = await connect_client()
    request = asyncio.create_task(client.request("session.create", {"source": "tui"}))
    await asyncio.sleep(0)
    request_id = socket.sent[-1]["id"]
    socket.feed(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"session_id": "runtime-1"},
            "error": {"code": -32000},
        }
    )

    with pytest.raises(GatewayProtocolError, match="both result and error"):
        await request
    await client.close()


@pytest.mark.asyncio
async def test_gateway_rejects_conflicting_event_session_identities():
    client, socket, _calls, _ready = await connect_client()
    socket.feed(
        {
            "jsonrpc": "2.0",
            "method": "event",
            "params": {
                "type": "message.delta",
                "session_id": "runtime-1",
                "payload": {"session_id": "runtime-2", "text": "wrong"},
            },
        }
    )

    with pytest.raises(GatewayProtocolError, match="conflicting session identities"):
        await client.next_event()
    await client.close()


@pytest.mark.asyncio
async def test_gateway_preserves_durable_identity_on_session_title_event():
    client, socket, _calls, _ready = await connect_client()
    socket.feed(
        {
            "jsonrpc": "2.0",
            "method": "event",
            "params": {
                "type": "session.title",
                "session_id": "runtime-1",
                "payload": {"session_id": "stored-1", "title": "A live title"},
            },
        }
    )

    event = await client.next_event()

    assert event["session_id"] == "runtime-1"
    assert event["stored_session_id"] == "stored-1"
    assert event["payload"] == {"title": "A live title"}
    await client.close()


@pytest.mark.asyncio
async def test_raw_standard_event_preserves_identity_and_correlation_fields():
    client, socket, _calls, _ready = await connect_client()
    socket.feed(
        {
            "jsonrpc": "2.0",
            "method": "event",
            "params": {
                "type": "message.delta",
                "session_id": "runtime-1",
                "turn_id": "remote-turn-1",
                "correlation_id": "corr-1",
                "request_id": "request-1",
                "seq": 4,
                "payload": {"text": "hello"},
            },
        }
    )

    assert await client.next_event() == {
        "type": "message.delta",
        "payload": {"text": "hello"},
        "session_id": "runtime-1",
        "turn_id": "remote-turn-1",
        "correlation_id": "corr-1",
        "request_id": "request-1",
        "seq": 4,
    }
    await client.close()


@pytest.mark.asyncio
async def test_pending_gateway_request_fails_when_the_socket_disconnects():
    client, socket, _calls, _ready = await connect_client()
    request = asyncio.create_task(client.request("session.create", {"source": "tui"}))
    await asyncio.sleep(0)
    socket.close_transport()

    with pytest.raises(GatewayTransportError):
        await request
    await client.close()
