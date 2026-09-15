"""Deterministic coverage for the opt-in Puck/Home bridge adapter."""

from __future__ import annotations

import asyncio
import json

import pytest

from puck_bridge.home_session import (
    HOME_BRIDGE_PATH,
    HomeBridgeAudioError,
    HomeBridgeProtocolError,
    HomeBridgeRPCError,
    HomeBridgeTransportError,
    HomePuckSession,
    require_home_bridge_url,
)


READY = {
    "schema": 1,
    "status": "ready",
    "conversation_handle": "opaque-home-handle",
    "route": {"class": "home", "id": "approved-route"},
    "capabilities": {
        "commands": [],
        "heartbeat": True,
        "timing": "absent",
        "interrupt": True,
    },
}


def _reply(request_id: str, result: object) -> str:
    if isinstance(result, dict):
        result = {"schema": 1, **result}
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "schema": 1,
            "id": request_id,
            "result": result,
        }
    )


def _rpc_error(request_id: str, code: str, delivery: str = "known") -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "schema": 1,
            "id": request_id,
            "error": {
                "code": -32000,
                "message": "rejected",
                "data": {"schema": 1, "code": code, "delivery": delivery},
            },
        }
    )


def _notification(method: str, params: dict) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "schema": 1, "method": method, "params": params}
    )


def _event(event_type: str, turn_id: str, payload: dict | None = None) -> str:
    return _notification(
        "event",
        {
            "schema": 1,
            "conversation_handle": "opaque-home-handle",
            "turn_id": turn_id,
            "event": {"type": event_type, "payload": payload or {}},
        },
    )


def _audio(kind: str, turn_id: str, **fields: object) -> str:
    frame = {"kind": kind, **fields}
    return _notification(
        "audio.frame",
        {
            "schema": 1,
            "conversation_handle": "opaque-home-handle",
            "turn_id": turn_id,
            "frame": frame,
        },
    )


class _FakeSocket:
    def __init__(self, *, prompt_frames: list[object] | None = None) -> None:
        self.incoming: asyncio.Queue[object] = asyncio.Queue()
        self.sent: list[dict] = []
        self.prompt_frames = list(prompt_frames or [])

    async def send(self, raw: str) -> None:
        payload = json.loads(raw)
        self.sent.append(payload)
        method = payload["method"]
        if method in {"conversation.open", "conversation.reconnect"}:
            self.incoming.put_nowait(_reply(payload["id"], READY))
        elif method == "prompt.submit":
            self.incoming.put_nowait(
                _reply(
                    payload["id"],
                    {
                        "conversation_handle": "opaque-home-handle",
                        "turn_id": "home-turn-1",
                        "status": "submitted",
                    },
                )
            )
            for frame in self.prompt_frames:
                self.incoming.put_nowait(frame)

    async def recv(self) -> object:
        frame = await self.incoming.get()
        if isinstance(frame, BaseException):
            raise frame
        return frame


class _FakeContext:
    def __init__(self, socket: _FakeSocket) -> None:
        self.socket = socket
        self.closed = False

    async def __aenter__(self) -> _FakeSocket:
        return self.socket

    async def __aexit__(self, *_args: object) -> None:
        self.closed = True


class _FakeConnect:
    def __init__(self, sockets: list[_FakeSocket]) -> None:
        self.sockets = list(sockets)
        self.calls: list[tuple[str, dict]] = []

    def __call__(
        self,
        url: str,
        additional_headers: dict | None = None,
        **kwargs: object,
    ) -> _FakeContext:
        self.calls.append((url, {"additional_headers": additional_headers, **kwargs}))
        return _FakeContext(self.sockets.pop(0))


def _ready_socket(*frames: object) -> _FakeSocket:
    return _FakeSocket(prompt_frames=list(frames))


def _session(factory: _FakeConnect) -> HomePuckSession:
    return HomePuckSession(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "opaque-home-handle",
        connect_factory=factory,
    )


@pytest.mark.asyncio
async def test_home_connect_uses_device_header_and_opaque_handle_only():
    factory = _FakeConnect([_FakeSocket()])
    session = _session(factory)

    ready = await session.connect()
    try:
        assert ready["status"] == "ready"
        assert session.is_connected()
        assert not session.supports_structured_prompts
        url, options = factory.calls[0]
        assert url == f"wss://home.example{HOME_BRIDGE_PATH}"
        assert options["additional_headers"] == {
            "Authorization": "Device device-secret"
        }
        sent = session._client.ws.sent[0]  # type: ignore[union-attr]
        assert sent["method"] == "conversation.open"
        assert sent["schema"] == 1
        assert sent["params"] == {"conversation_handle": "opaque-home-handle"}
        assert "device-secret" not in json.dumps(sent)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_turn_maps_audio_and_waits_for_terminal_event():
    socket = _ready_socket(
        _event("message.delta", "home-turn-1", {"rendered": "hello"}),
        _audio(
            "start",
            "home-turn-1",
            sample_rate=24000,
            channels=1,
            sample_width=2,
            byte_order="little",
        ),
        b"\x01",
        b"\x00\x02\x00",
        _audio("end", "home-turn-1"),
        _event("turn.complete", "home-turn-1", {"status": "completed"}),
    )
    factory = _FakeConnect([socket])
    session = _session(factory)
    await session.connect()
    try:
        events = [event async for event in session.send_turn("hello")]
        assert events == [
            {"type": "text_delta", "text": "hello"},
            {
                "type": "audio_start",
                "sample_rate": 24000,
                "channels": 1,
                "sample_width": 2,
            },
            {"type": "audio_chunk", "data": b"\x01\x00\x02\x00"},
            {"type": "audio_end"},
        ]
        assert [frame["method"] for frame in socket.sent] == [
            "conversation.open",
            "prompt.submit",
        ]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_cumulative_preview_emits_only_new_suffix():
    socket = _ready_socket(
        _event("message.delta", "home-turn-1", {"rendered": "Hel"}),
        _event("message.delta", "home-turn-1", {"rendered": "Hello"}),
        _event("turn.complete", "home-turn-1", {"status": "completed"}),
    )
    factory = _FakeConnect([socket])
    session = _session(factory)
    await session.connect()
    try:
        events = [event async for event in session.send_turn("suffix")]
        assert events == [
            {"type": "text_delta", "text": "Hel"},
            {"type": "text_delta", "text": "lo"},
        ]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_transport_failure_requires_reconnect_and_never_replays_prompt():
    first = _ready_socket(ConnectionError("socket closed"))
    second = _FakeSocket()
    factory = _FakeConnect([first, second])
    session = _session(factory)
    await session.connect()
    with pytest.raises(HomeBridgeTransportError):
        _ = [event async for event in session.send_turn("do not replay")]

    assert not session.is_connected()
    await session.connect()
    try:
        assert [frame["method"] for frame in second.sent] == [
            "conversation.reconnect"
        ]
        assert all(frame["method"] != "prompt.submit" for frame in second.sent)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_known_prompt_rejection_keeps_ready_socket_without_replay():
    class _RejectingSocket(_FakeSocket):
        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if payload["method"] in {"conversation.open", "conversation.reconnect"}:
                self.incoming.put_nowait(_reply(payload["id"], READY))
            elif payload["method"] == "prompt.submit":
                self.incoming.put_nowait(_rpc_error(payload["id"], "request_rejected"))

    socket = _RejectingSocket()
    factory = _FakeConnect([socket])
    session = _session(factory)
    await session.connect()
    try:
        with pytest.raises(HomeBridgeRPCError) as raised:
            _ = [event async for event in session.send_turn("rejected")]
        assert raised.value.code == "request_rejected"
        assert raised.value.delivery == "known"
        assert session.is_connected()
        assert [frame["method"] for frame in socket.sent] == [
            "conversation.open",
            "prompt.submit",
        ]
    finally:
        await session.close()


class _ReadinessSocket(_FakeSocket):
    def __init__(self, result: dict) -> None:
        super().__init__()
        self.result = result

    async def send(self, raw: str) -> None:
        payload = json.loads(raw)
        self.sent.append(payload)
        if payload["method"] in {"conversation.open", "conversation.reconnect"}:
            self.incoming.put_nowait(_reply(payload["id"], self.result))


class _PromptResultSocket(_FakeSocket):
    def __init__(self, result: dict) -> None:
        super().__init__()
        self.result = result

    async def send(self, raw: str) -> None:
        payload = json.loads(raw)
        self.sent.append(payload)
        if payload["method"] in {"conversation.open", "conversation.reconnect"}:
            self.incoming.put_nowait(_reply(payload["id"], READY))
        elif payload["method"] == "prompt.submit":
            self.incoming.put_nowait(_reply(payload["id"], self.result))


@pytest.mark.asyncio
async def test_home_malformed_prompt_result_closes_ready_binding():
    socket = _PromptResultSocket(
        {
            "schema": 1,
            "conversation_handle": "wrong-handle",
            "turn_id": "home-turn-1",
            "status": "submitted",
        }
    )
    session = _session(_FakeConnect([socket]))
    await session.connect()
    with pytest.raises(HomeBridgeProtocolError):
        _ = [event async for event in session.send_turn("bad result")]
    assert not session.is_connected()
    await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        {"schema": 1, "status": "unavailable", "conversation_handle": "opaque-home-handle"},
        {"schema": 1, "status": "ready", "route": READY["route"], "capabilities": {}},
        {
            "schema": 1,
            "status": "ready",
            "conversation_handle": "opaque-home-handle",
            "route": {"class": "unknown", "id": "route"},
            "capabilities": {},
        },
        {
            "schema": 1,
            "status": "ready",
            "conversation_handle": "opaque-home-handle",
            "route": READY["route"],
            "capabilities": [],
        },
    ],
)
async def test_home_readiness_rejects_unavailable_or_malformed_results(result):
    factory = _FakeConnect([_ReadinessSocket(result)])
    session = _session(factory)
    with pytest.raises(HomeBridgeProtocolError):
        await session.connect()
    assert not session.is_connected()


@pytest.mark.asyncio
async def test_home_ignores_foreign_and_global_events_before_active_turn():
    foreign = _event("turn.complete", "other-turn", {"status": "completed"})
    global_event = _notification(
        "event",
        {
            "schema": 1,
            "conversation_handle": "opaque-home-handle",
            "event": {"type": "turn.complete", "payload": {"status": "completed"}},
        },
    )
    socket = _ready_socket(
        foreign,
        global_event,
        _audio(
            "start",
            "home-turn-1",
            sample_rate=24000,
            channels=1,
            sample_width=2,
            byte_order="little",
        ),
        b"\x00\x00",
        _audio("end", "home-turn-1"),
        _event("turn.complete", "home-turn-1", {"status": "completed"}),
    )
    factory = _FakeConnect([socket])
    session = _session(factory)
    await session.connect()
    try:
        events = [event async for event in session.send_turn("fresh")]
        assert [event["type"] for event in events] == [
            "audio_start",
            "audio_chunk",
            "audio_end",
        ]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_audio_rejects_pcm_before_start_and_odd_sample():
    for bad_frame in (
        b"\x00\x00",
        _audio("start", "home-turn-1", sample_rate=24000, channels=1, sample_width=2, byte_order="little"),
    ):
        socket = _ready_socket(bad_frame)
        factory = _FakeConnect([socket])
        session = _session(factory)
        await session.connect()
        try:
            if isinstance(bad_frame, bytes):
                with pytest.raises(HomeBridgeAudioError):
                    _ = [event async for event in session.send_turn("bad pcm")]
            else:
                socket.prompt_frames.extend(
                    [b"\x01", _audio("end", "home-turn-1")]
                )
                with pytest.raises(HomeBridgeAudioError):
                    _ = [event async for event in session.send_turn("odd pcm")]
        finally:
            await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frames",
    [
        [_audio("start", "home-turn-1", sample_rate=24000, channels=1, sample_width=2, byte_order="big")],
        [_audio("start", "home-turn-1", sample_rate=24000, channels=2, sample_width=2, byte_order="little")],
        [_audio("start", "home-turn-1", sample_rate=384001, channels=1, sample_width=2, byte_order="little")],
        [_audio("end", "home-turn-1")],
        [
            _audio("start", "home-turn-1", sample_rate=24000, channels=1, sample_width=2, byte_order="little"),
            _audio("start", "home-turn-1", sample_rate=24000, channels=1, sample_width=2, byte_order="little"),
        ],
        [
            _audio("start", "home-turn-1", sample_rate=24000, channels=1, sample_width=2, byte_order="little"),
            _audio("end", "home-turn-1"),
            b"\x00\x00",
        ],
    ],
)
async def test_home_audio_rejects_invalid_metadata_and_order(frames):
    socket = _ready_socket(*frames)
    factory = _FakeConnect([socket])
    session = _session(factory)
    await session.connect()
    try:
        with pytest.raises(HomeBridgeAudioError):
            _ = [event async for event in session.send_turn("bad audio")]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_audio_failure_preserves_later_text_and_terminal_event():
    socket = _ready_socket(
        _audio("unavailable", "home-turn-1"),
        _event("message.delta", "home-turn-1", {"rendered": "still text"}),
        _event("turn.complete", "home-turn-1", {"status": "completed"}),
    )
    factory = _FakeConnect([socket])
    session = _session(factory)
    await session.connect()
    try:
        events = [event async for event in session.send_turn("text survives")]
        assert events == [
            {"type": "audio_abort", "error": "Home bridge response audio unavailable"},
            {"type": "text_delta", "text": "still text"},
        ]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_rejects_foreign_audio_binding():
    foreign_audio = _notification(
        "audio.frame",
        {
            "schema": 1,
            "conversation_handle": "other-handle",
            "turn_id": "home-turn-1",
            "frame": {
                "kind": "start",
                "sample_rate": 24000,
                "channels": 1,
                "sample_width": 2,
                "byte_order": "little",
            },
        },
    )
    socket = _ready_socket(foreign_audio)
    session = _session(_FakeConnect([socket]))
    await session.connect()
    try:
        with pytest.raises(HomeBridgeAudioError):
            _ = [event async for event in session.send_turn("foreign audio")]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_ping_uses_home_schema_and_handle():
    class _PingSocket(_FakeSocket):
        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if payload["method"] in {"conversation.open", "conversation.reconnect"}:
                self.incoming.put_nowait(_reply(payload["id"], READY))
            elif payload["method"] == "bridge.ping":
                self.incoming.put_nowait(
                    _reply(
                        payload["id"],
                        {
                            "status": "alive",
                            "conversation_handle": "opaque-home-handle",
                        },
                    )
                )

    socket = _PingSocket()
    session = _session(_FakeConnect([socket]))
    await session.connect()
    try:
        assert await session.ping() == {
            "schema": 1,
            "status": "alive",
            "conversation_handle": "opaque-home-handle",
        }
        assert socket.sent[-1]["method"] == "bridge.ping"
        assert socket.sent[-1]["schema"] == 1
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_interrupt_requires_advertised_capability_and_returns_ack():
    class _InterruptSocket(_FakeSocket):
        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if payload["method"] in {"conversation.open", "conversation.reconnect"}:
                self.incoming.put_nowait(_reply(payload["id"], READY))
            elif payload["method"] == "session.interrupt":
                self.incoming.put_nowait(
                    _reply(
                        payload["id"],
                        {"accepted": True, "status": "accepted"},
                    )
                )

    socket = _InterruptSocket()
    session = _session(_FakeConnect([socket]))
    await session.connect()
    try:
        session._active_turn_id = "home-turn-1"
        assert await session.interrupt_active_turn()
        assert socket.sent[-1]["method"] == "session.interrupt"
        assert socket.sent[-1]["params"] == {
            "conversation_handle": "opaque-home-handle",
            "turn_id": "home-turn-1",
        }
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_preserves_standard_final_text_and_completion_events():
    socket = _ready_socket(
        _event("message.delta", "home-turn-1", {"rendered": "draft"}),
        _event(
            "message.complete",
            "home-turn-1",
            {"status": "complete", "text": "final", "reasoning": "checked"},
        ),
    )
    factory = _FakeConnect([socket])
    session = _session(factory)
    await session.connect()
    try:
        events = [event async for event in session.send_turn("final text")]
        assert events == [
            {"type": "text_delta", "text": "draft"},
            {"type": "thinking_delta", "text": "checked"},
            {"type": "text_replace", "text": "final"},
            {
                "type": "message_complete",
                "text": "final",
                "reasoning": "checked",
                "failure_reason": "",
            },
        ]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_rejects_concurrent_puck_turns():
    socket = _ready_socket()
    factory = _FakeConnect([socket])
    session = _session(factory)
    await session.connect()
    first = session.send_turn("first")
    first_task = asyncio.create_task(first.__anext__())
    try:
        for _ in range(100):
            if len(socket.sent) >= 2:
                break
            await asyncio.sleep(0)
        assert len(socket.sent) == 2
        with pytest.raises(HomeBridgeProtocolError):
            await session.send_turn("second").__anext__()
    finally:
        first_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_task
        await session.close()


def test_home_url_requires_secure_pinned_path():
    assert require_home_bridge_url(f"wss://home.example{HOME_BRIDGE_PATH}/") == (
        f"wss://home.example{HOME_BRIDGE_PATH}"
    )
    with pytest.raises(ValueError):
        require_home_bridge_url("ws://home.example/api/v1/bridge/ws")
    with pytest.raises(ValueError):
        require_home_bridge_url("wss://home.example/api/ws")
    with pytest.raises(ValueError):
        require_home_bridge_url(
            "wss://user:password@home.example/api/v1/bridge/ws?ticket=secret"
        )
