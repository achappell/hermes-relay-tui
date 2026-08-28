import json

import pytest

from client import ProtocolError, send_hello, send_turn


class FakeWebSocket:
    """Minimal fake matching the subset of the websockets API client.py uses."""

    def __init__(self, frames):
        self._frames = list(frames)
        self.sent = []

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if not self._frames:
            raise AssertionError("no more frames queued")
        return self._frames.pop(0)


async def test_send_hello_returns_ack_payload():
    ack = {"type": "hello_ack", "chat_id": "abc"}
    ws = FakeWebSocket([json.dumps(ack)])

    result = await send_hello(
        ws,
        client_id="c1",
        device_id="d1",
        session_id="s1",
        display_name="test",
    )

    assert result == ack
    sent = json.loads(ws.sent[0])
    assert sent["type"] == "hello"
    assert sent["session_id"] == "s1"


async def test_send_hello_rejects_non_ack():
    ws = FakeWebSocket([json.dumps({"type": "error", "error": "nope"})])
    with pytest.raises(ProtocolError):
        await send_hello(ws, client_id="c", device_id="d", session_id="s", display_name="n")


async def test_send_turn_yields_text_deltas_and_turn_end():
    frames = [
        json.dumps({"type": "turn_accepted"}),
        json.dumps({"type": "text_delta", "text": "Hel"}),
        json.dumps({"type": "text_delta", "text": "Hello"}),
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    kinds = [event["type"] for event in events]
    assert kinds == ["text_delta", "text_delta", "turn_end"]
    assert events[0]["text"] == "Hel"
    assert events[1]["text"] == "lo"  # only the new suffix is yielded


async def test_send_turn_yields_audio_chunks_between_start_and_end():
    frames = [
        json.dumps({"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2}),
        b"\x00\x01\x02\x03",
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    kinds = [event["type"] for event in events]
    assert kinds == ["audio_start", "audio_chunk", "turn_end"]
    assert events[1]["data"] == b"\x00\x01\x02\x03"


async def test_send_turn_yields_error_and_stops():
    frames = [json.dumps({"type": "error", "error": "boom"})]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    assert events == [{"type": "error", "error": "boom"}]
