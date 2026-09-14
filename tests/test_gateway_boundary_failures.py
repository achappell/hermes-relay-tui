import asyncio

import pytest

from gateway_audio import GatewayAudioTransportError
from gateway_client import GatewayProtocolError, GatewayTransportError
from gateway_session import GatewaySession, _require_accepted_request
from tests.test_gateway_audio import make_stream
from tests.test_gateway_client import connect_client
from tests.test_gateway_session import make_args


@pytest.mark.asyncio
async def test_pending_gateway_request_fails_on_socket_disconnect():
    """[P0] A disconnected socket fails the in-flight request."""
    # Given a connected gateway with an in-flight JSON-RPC request
    client, socket, _calls, _ready = await connect_client()
    request = asyncio.create_task(client.request("session.create", {"source": "tui"}))
    await asyncio.sleep(0)

    # When the socket disconnects before its reply arrives
    socket.close_transport()

    # Then the pending request fails with a typed transport error
    with pytest.raises(GatewayTransportError):
        await request
    assert client.is_connected is False
    await client.close()


@pytest.mark.asyncio
async def test_gateway_client_reports_unknown_and_invalid_json_rpc_events():
    """[P1] Unknown methods are safe events; malformed event params fail the reader."""
    # Given a connected gateway client
    client, socket, _calls, _ready = await connect_client()

    # When an unknown JSON-RPC method arrives
    socket.feed({"jsonrpc": "2.0", "method": "gateway.notice", "params": {"source": "test"}})

    # Then it is exposed as a content-safe diagnostic event
    assert await client.next_event() == {
        "type": "unknown_event",
        "event_type": "gateway.notice",
        "payload_keys": ["jsonrpc", "method", "params"],
    }

    # When the next event has malformed params
    socket.feed({"jsonrpc": "2.0", "method": "event", "params": []})

    # Then the reader reports a protocol failure
    with pytest.raises(GatewayProtocolError, match="params are not an object"):
        await client.next_event()
    await client.close()


@pytest.mark.asyncio
async def test_gateway_audio_malformed_json_becomes_unavailable():
    """[P1] Malformed sidecar JSON is an explicit audio failure."""
    # Given an open audio sidecar
    stream, socket, _calls = make_stream()
    await stream.open()

    # When malformed JSON arrives
    socket.feed("{not-json")

    # Then audio is explicitly marked unavailable
    assert await asyncio.wait_for(stream.next_event(), 1) == {
        "type": "audio_unavailable",
        "reason": "invalid audio JSON",
    }
    await stream.close()


@pytest.mark.asyncio
async def test_gateway_audio_duplicate_start_becomes_unavailable():
    """[P1] A second audio start terminates the sidecar safely."""
    # Given an open sidecar that has started one PCM stream
    stream, socket, _calls = make_stream()
    await stream.open()
    start = {"type": "start", "sample_rate": 24000, "channels": 1}
    socket.feed_json(start)
    socket.feed_json(start)

    # When the duplicate metadata arrives
    assert (await asyncio.wait_for(stream.next_event(), 1))["type"] == "audio_start"
    failure = await asyncio.wait_for(stream.next_event(), 1)

    # Then the sidecar reports the protocol failure as unavailable audio
    assert failure["type"] == "audio_unavailable"
    assert "duplicate start" in failure["reason"]
    await stream.close()


@pytest.mark.asyncio
async def test_gateway_audio_send_and_finish_before_open_are_noops():
    """[P2] Pre-open audio writes do not create frames or errors."""
    # Given a sidecar that has not been opened
    stream, socket, _calls = make_stream()

    # When callers send text and finish the stream
    await stream.send_text("ignored")
    await stream.finish()

    # Then no wire frames are produced
    assert socket.sent == []
    await stream.close()


@pytest.mark.asyncio
async def test_gateway_audio_send_failure_is_typed():
    """[P1] A socket write failure becomes a gateway audio transport error."""
    # Given an open sidecar whose socket write fails
    stream, socket, _calls = make_stream()

    async def fail_send(_frame):
        raise ConnectionError("socket closed")

    socket.send = fail_send
    await stream.open()

    # When a text fragment is sent
    # Then the failure remains a typed sidecar transport error
    with pytest.raises(GatewayAudioTransportError, match="gateway audio text"):
        await stream.send_text("hello")
    await stream.close()


def test_gateway_session_rejects_invalid_session_result_and_acceptance_response():
    """[P0] Session handshakes require typed IDs and explicit acceptance."""
    # Given a Standard session adapter
    session = GatewaySession(make_args())

    # When the session result and request acceptance are malformed
    # Then both boundaries fail closed with protocol errors
    with pytest.raises(GatewayProtocolError, match="not an object"):
        session._apply_session_result(None)
    with pytest.raises(GatewayProtocolError, match="invalid acceptance"):
        _require_accepted_request({"accepted": "yes"}, "prompt.submit")


@pytest.mark.asyncio
async def test_gateway_session_normalizes_already_streamed_interim_message():
    """[P2] An already-streamed interim seals the preview without duplicating text."""
    # Given a preview already emitted as streamed text
    session = GatewaySession(make_args())
    state = {
        "rendered_preview": "draft",
        "streamed_text": True,
        "committed": "",
        "current_draft": "draft-1",
        "streamed_reasoning": False,
    }

    # When Hermes marks that preview as already streamed
    events = [
        event
        async for event in session._normalize_event(
            {
                "type": "message.interim",
                "payload": {"text": "draft", "already_streamed": True},
            },
            turn_id="turn-1",
            state=state,
            gateway=None,
            session_id="runtime-1",
        )
    ]

    # Then it is committed without emitting duplicate text
    assert events == []
    assert state["committed"] == "draft"
    assert state["rendered_preview"] == ""
    assert state["current_draft"] is None
