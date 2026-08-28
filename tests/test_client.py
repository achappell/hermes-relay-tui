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


async def test_send_hello_skips_binary_frames_and_rejects_non_objects():
    ws = FakeWebSocket([b"\x00\x01", json.dumps(["not", "an", "object"])])
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


async def test_send_turn_restarts_the_line_when_the_preview_rewinds():
    # A preview that isn't an extension of what was already shown can't be
    # diffed, so the whole thing is re-emitted on a fresh line.
    frames = [
        json.dumps({"type": "text_delta", "text": "Hello"}),
        json.dumps({"type": "text_delta", "text": "Goodbye"}),
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    assert events[1] == {"type": "text_delta", "text": "\nGoodbye"}


async def test_send_turn_yields_error_and_stops():
    frames = [json.dumps({"type": "error", "error": "boom"})]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    assert events == [{"type": "error", "error": "boom"}]


async def collect(frames):
    ws = FakeWebSocket(frames)
    return [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]


async def test_send_turn_yields_a_plain_text_frame_whole():
    events = await collect(
        [
            json.dumps({"type": "text", "text": "one shot reply"}),
            json.dumps({"type": "turn_end"}),
        ]
    )

    assert events[0] == {"type": "text_delta", "text": "one shot reply"}
    assert events[-1]["type"] == "turn_end"


async def test_text_final_without_streaming_yields_the_whole_text():
    events = await collect(
        [
            json.dumps({"type": "text_final", "text": "the complete answer"}),
            json.dumps({"type": "turn_end"}),
        ]
    )

    assert events[0] == {"type": "text_delta", "text": "the complete answer"}


async def test_text_final_that_differs_from_the_preview_is_re_emitted():
    events = await collect(
        [
            json.dumps({"type": "text_delta", "text": "partial guess"}),
            json.dumps({"type": "text_final", "text": "the corrected answer"}),
            json.dumps({"type": "turn_end"}),
        ]
    )

    kinds = [event["type"] for event in events]
    assert kinds == ["text_delta", "text_delta", "turn_end"]
    assert events[1] == {"type": "text_delta", "text": "\nthe corrected answer"}


async def test_text_final_matching_the_streamed_preview_yields_nothing_new():
    # The server pads streaming previews with a cursor block; the final frame
    # drops it, so the comparison rstrips it before deciding they differ.
    events = await collect(
        [
            json.dumps({"type": "text_delta", "text": "already streamed▉"}),
            json.dumps({"type": "text_final", "text": "already streamed"}),
            json.dumps({"type": "turn_end"}),
        ]
    )

    kinds = [event["type"] for event in events]
    assert kinds == ["text_delta", "turn_end"]
    assert events[0]["text"] == "already streamed▉"


async def test_status_frames_are_yielded_and_empty_ones_suppressed():
    events = await collect(
        [
            json.dumps({"type": "status", "text": "  thinking  "}),
            json.dumps({"type": "status", "text": "   "}),
            json.dumps({"type": "status"}),
            json.dumps({"type": "turn_end"}),
        ]
    )

    kinds = [event["type"] for event in events]
    assert kinds == ["status", "turn_end"]
    assert events[0] == {"type": "status", "text": "thinking"}


async def test_unknown_frame_kinds_are_ignored():
    events = await collect(
        [
            json.dumps({"type": "something_new", "text": "ignore me"}),
            json.dumps({"type": "turn_end"}),
        ]
    )

    assert [event["type"] for event in events] == ["turn_end"]


async def test_non_object_json_frame_yields_an_error_and_stops():
    ws = FakeWebSocket([json.dumps(["not", "an", "object"]), json.dumps({"type": "turn_end"})])

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    assert events == [{"type": "error", "error": "server sent a non-object JSON frame"}]
    # The generator stopped: the queued turn_end was never read.
    assert ws._frames == [json.dumps({"type": "turn_end"})]
