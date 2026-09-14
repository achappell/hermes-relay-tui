import asyncio
import json

import pytest

from gateway_audio import (
    GatewayAudioStream,
    GatewayAudioTransportError,
    gateway_audio_url_with_token,
    redact_gateway_audio_url,
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
            raise ConnectionError("audio socket closed")
        return frame

    async def wait_closed(self):
        await self.closed.wait()

    def feed_json(self, payload):
        self.incoming.put_nowait(json.dumps(payload))

    def feed(self, frame):
        self.incoming.put_nowait(frame)


class FakeContext:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, exc_type, exc, tb):
        self.socket.closed.set()


def make_stream(queue_size=4):
    socket = FakeSocket()
    calls = []

    def connect(url, **kwargs):
        calls.append((url, kwargs))
        return FakeContext(socket)

    stream = GatewayAudioStream(
        "wss://hermes.example/api/ws?skin=terminal",
        "secret-token",
        profile="amanda",
        connect_factory=connect,
        queue_size=queue_size,
    )
    return stream, socket, calls


def test_audio_url_replaces_auth_and_targets_the_existing_sidecar():
    url = gateway_audio_url_with_token(
        "wss://hermes.example/api/ws?skin=terminal&token=old&profile=old",
        "new token",
        profile="amanda",
    )

    assert url == (
        "wss://hermes.example/api/audio/speak-stream?"
        "skin=terminal&token=new+token&profile=amanda"
    )
    redacted = redact_gateway_audio_url(url)
    assert "new+token" not in redacted
    assert "REDACTED" in redacted

    preserved = gateway_audio_url_with_token(
        "wss://hermes.example/api/ws?profile=stored",
        "new-token",
    )
    assert "profile=stored" in preserved


@pytest.mark.asyncio
async def test_stream_translates_start_pcm_end_and_feeds_text():
    stream, socket, calls = make_stream()
    await stream.open()

    await stream.send_text("Hello")
    await stream.finish()
    assert socket.sent == [{"text": "Hello"}, {"done": True}]
    assert "token=secret-token" in calls[0][0]
    assert "profile=amanda" in calls[0][0]

    socket.feed_json({"type": "start", "sample_rate": 24000, "channels": 1})
    socket.feed(b"\x00\x01")
    socket.feed_json({"type": "end"})

    events = [await asyncio.wait_for(stream.next_event(), 1) for _ in range(3)]
    assert events == [
        {
            "type": "audio_start",
            "sample_rate": 24000,
            "channels": 1,
            "sample_width": 2,
        },
        {"type": "audio_chunk", "data": b"\x00\x01"},
        {"type": "audio_end"},
    ]
    await stream.close()


@pytest.mark.asyncio
async def test_nested_speech_timing_is_normalized_without_becoming_an_audio_failure():
    stream, socket, _calls = make_stream(queue_size=8)
    await stream.open()

    socket.feed_json({"type": "speech_timing", "payload": {"text": "ignored"}})
    socket.feed_json({"type": "start", "sample_rate": 24000, "channels": 1})
    socket.feed_json(
        {
            "type": "speech_timing",
            "turn_id": "server-turn",
            "session_id": "server-session",
            "payload": {
                "segment_id": "speech-tts-0",
                "text": "Hermes moves.",
                "timing_source": "duration_fallback",
                "fallback_reason": "disabled",
                "audio_offset_ms": 0,
                "duration_ms": 200,
                "words": [],
            },
        }
    )
    socket.feed(b"\x00\x01")
    socket.feed_json({"type": "end"})

    events = [await asyncio.wait_for(stream.next_event(), 1) for _ in range(4)]
    assert [event["type"] for event in events] == [
        "audio_start",
        "speech_timing",
        "audio_chunk",
        "audio_end",
    ]
    assert events[1] == {
        "type": "speech_timing",
        "segment_id": "speech-tts-0",
        "text": "Hermes moves.",
        "timing_source": "duration_fallback",
        "audio_offset": 0.0,
        "duration": 0.2,
        "fallback_reason": "disabled",
        "words": [],
    }
    await stream.close()


@pytest.mark.asyncio
async def test_invalid_start_becomes_audio_unavailable_without_raising():
    stream, socket, _calls = make_stream()
    await stream.open()
    socket.feed_json(
        {
            "type": "start",
            "sample_rate": 24000,
            "channels": 1,
            "sample_width": 4,
        }
    )

    event = await asyncio.wait_for(stream.next_event(), 1)
    assert event["type"] == "audio_unavailable"
    assert "16-bit" in event["reason"]
    await stream.close()


@pytest.mark.asyncio
async def test_multi_channel_audio_is_rejected_by_the_standard_contract():
    stream, socket, _calls = make_stream()
    await stream.open()
    socket.feed_json(
        {
            "type": "start",
            "sample_rate": 24000,
            "channels": 2,
            "sample_width": 2,
        }
    )

    event = await asyncio.wait_for(stream.next_event(), 1)
    assert event["type"] == "audio_unavailable"
    await stream.close()


@pytest.mark.asyncio
async def test_non_little_endian_audio_is_rejected_by_the_standard_contract():
    stream, socket, _calls = make_stream()
    await stream.open()
    socket.feed_json(
        {
            "type": "start",
            "sample_rate": 24000,
            "channels": 1,
            "sample_width": 2,
            "byte_order": "big",
        }
    )

    event = await asyncio.wait_for(stream.next_event(), 1)
    assert event["type"] == "audio_unavailable"
    assert "little-endian" in event["reason"]
    await stream.close()


@pytest.mark.asyncio
async def test_fallback_frame_becomes_audio_unavailable():
    stream, socket, _calls = make_stream()
    await stream.open()
    socket.feed_json({"type": "fallback"})

    event = await asyncio.wait_for(stream.next_event(), 1)
    assert event == {
        "type": "audio_unavailable",
        "reason": "server audio fallback",
    }
    await stream.close()


@pytest.mark.asyncio
async def test_unknown_audio_frame_becomes_audio_unavailable():
    stream, socket, _calls = make_stream()
    await stream.open()
    socket.feed_json({"type": "future_audio_mode", "payload": {}})

    event = await asyncio.wait_for(stream.next_event(), 1)
    assert event == {
        "type": "audio_unavailable",
        "reason": "unsupported audio frame type: future_audio_mode",
    }
    await stream.close()


@pytest.mark.asyncio
async def test_sidecar_refuses_replacement_while_old_reader_is_still_shutting_down():
    stream, _socket, _calls = make_stream()
    reader = asyncio.create_task(asyncio.Event().wait())
    stream._reader_task = reader

    with pytest.raises(GatewayAudioTransportError) as error:
        await stream.connect()
    assert error.value.cause_type == "RuntimeError"
    assert stream._reader_task is reader

    reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reader


@pytest.mark.asyncio
async def test_stop_sends_the_sidecar_stop_frame_before_closing():
    stream, socket, _calls = make_stream()
    await stream.open()

    await stream.stop()

    assert socket.sent == [{"stop": True}]
    assert socket.closed.is_set()


@pytest.mark.asyncio
async def test_pcm_frames_are_reassembled_and_incomplete_audio_is_unavailable():
    stream, socket, _calls = make_stream()
    await stream.open()
    socket.feed_json({"type": "start", "sample_rate": 24000, "channels": 1})
    socket.feed(b"\x00")
    socket.feed(b"\x01\x02")
    socket.feed_json({"type": "end"})

    start = await asyncio.wait_for(stream.next_event(), 1)
    chunk = await asyncio.wait_for(stream.next_event(), 1)
    unavailable = await asyncio.wait_for(stream.next_event(), 1)
    assert start["type"] == "audio_start"
    assert chunk == {"type": "audio_chunk", "data": b"\x00\x01"}
    assert unavailable["type"] == "audio_unavailable"
    await stream.close()


@pytest.mark.asyncio
async def test_empty_audio_end_is_unavailable_and_close_sentinel_survives_full_queue():
    stream, socket, _calls = make_stream()
    await stream.open()
    socket.feed_json({"type": "start", "sample_rate": 24000, "channels": 1})
    socket.feed_json({"type": "end"})

    assert (await asyncio.wait_for(stream.next_event(), 1))["type"] == "audio_start"
    assert (await asyncio.wait_for(stream.next_event(), 1))["type"] == "audio_unavailable"
    await stream.close()

    stream = GatewayAudioStream(
        "wss://hermes.example/api/ws",
        "secret-token",
        queue_size=1,
    )
    stream._events.put_nowait({"type": "audio_chunk", "data": b"\x00\x01"})
    stream._queue_close_sentinel()
    with pytest.raises(GatewayAudioTransportError):
        await stream.next_event()


@pytest.mark.asyncio
async def test_binary_before_start_and_disconnect_are_safe_side_lane_failures():
    stream, socket, _calls = make_stream()
    await stream.open()
    socket.feed(b"not framed audio")

    event = await asyncio.wait_for(stream.next_event(), 1)
    assert event == {
        "type": "audio_unavailable",
        "reason": "binary before audio start",
    }
    await stream.close()

    stream, socket, _calls = make_stream()
    await stream.open()
    socket.feed(_CLOSE)
    event = await asyncio.wait_for(stream.next_event(), 1)
    assert event["type"] == "audio_unavailable"
    await stream.close()


@pytest.mark.asyncio
async def test_audio_queue_is_bounded_and_late_frames_after_end_are_discarded():
    stream, socket, _calls = make_stream()
    assert stream._events.maxsize == 4
    await stream.open()
    socket.feed_json({"type": "start", "sample_rate": 16000, "channels": 1})
    socket.feed(b"\x00\x01")
    socket.feed_json({"type": "end"})
    socket.feed(b"late")

    first = await asyncio.wait_for(stream.next_event(), 1)
    second = await asyncio.wait_for(stream.next_event(), 1)
    third = await asyncio.wait_for(stream.next_event(), 1)
    assert first["type"] == "audio_start"
    assert second == {"type": "audio_chunk", "data": b"\x00\x01"}
    assert third["type"] == "audio_end"
    await stream.close()
