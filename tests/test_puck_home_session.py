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
    HomeBrowserSession,
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


def _rpc_error(request_id: str, code: str, delivery: str | None = "known") -> str:
    data = {"schema": 1, "code": code}
    if delivery is not None:
        data["delivery"] = delivery
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "schema": 1,
            "id": request_id,
            "error": {
                "code": -32000,
                "message": "rejected",
                "data": data,
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
        elif method == "prompt.respond":
            self.incoming.put_nowait(
                _reply(
                    payload["id"],
                    {"conversation_handle": "opaque-home-handle", "status": "resolved"},
                )
            )
            self.incoming.put_nowait(
                _event(
                    "prompt_resolved",
                    "home-turn-1",
                    {"request_id": "prompt-1", "status": "resolved"},
                )
            )
            self.incoming.put_nowait(
                _event("message.delta", "home-turn-1", {"rendered": "Confirmed."})
            )
            self.incoming.put_nowait(
                _event("turn.complete", "home-turn-1", {"status": "completed"})
            )

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


class _FailingContext:
    async def __aenter__(self) -> _FakeSocket:
        raise ConnectionError("Home is offline")

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeConnect:
    def __init__(self, sockets: list[_FakeSocket]) -> None:
        self.sockets = list(sockets)
        self.calls: list[tuple[str, dict]] = []
        self.contexts: list[_FakeContext] = []

    def __call__(
        self,
        url: str,
        additional_headers: dict | None = None,
        **kwargs: object,
    ) -> _FakeContext:
        self.calls.append((url, {"additional_headers": additional_headers, **kwargs}))
        context = _FakeContext(self.sockets.pop(0))
        self.contexts.append(context)
        return context


class _FailingConnect:
    def __call__(self, _url: str, **_kwargs: object) -> _FailingContext:
        return _FailingContext()


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
async def test_home_browser_session_resolves_a_correlated_choice_without_prompt_replay():
    prompt = _notification(
        "event",
        {
            "schema": 1,
            "conversation_handle": "opaque-home-handle",
            "turn_id": "home-turn-1",
            "correlation_id": "corr-1",
            "event": {
                "type": "approval.request",
                "payload": {
                    "request_id": "prompt-1",
                    "text": "Use the private browser session?",
                    "options": [
                        {"id": "yes", "label": "Approve"},
                        {"id": "no", "label": "Deny"},
                    ],
                },
            },
        },
    )
    socket = _ready_socket(prompt)
    session = HomeBrowserSession(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "opaque-home-handle",
        connect_factory=_FakeConnect([socket]),
    )
    await session.connect()
    stream = session.send_turn("confirm")
    try:
        assert await stream.__anext__() == {
            "type": "prompt_request",
            "prompt_id": "prompt-1",
            "prompt_kind": "choice",
            "turn_id": "home-turn-1",
            "text": "Use the private browser session?",
            "options": [
                {"id": "yes", "label": "Approve"},
                {"id": "no", "label": "Deny"},
            ],
            "sensitive": False,
            "timeout_s": 300,
            "correlation_id": "corr-1",
            "choice": None,
        }
        assert session.supports_structured_prompts
        assert session.session_id == "home-browser"
        assert session.timing_capability == "absent"

        assert not await session.send_prompt_response(
            prompt_id="prompt-1",
            prompt_kind="choice",
            option_id="not-an-option",
        )
        assert [frame["method"] for frame in socket.sent] == [
            "conversation.open",
            "prompt.submit",
        ]

        assert not await session.send_prompt_response(
            prompt_id="prompt-1",
            prompt_kind="choice",
            value="not-an-option",
        )
        assert [frame["method"] for frame in socket.sent] == [
            "conversation.open",
            "prompt.submit",
        ]

        assert await session.send_prompt_response(
            prompt_id="prompt-1",
            prompt_kind="choice",
            option_id="yes",
        )
        remaining = [event async for event in stream]
        assert remaining == [
            {"type": "prompt_resolved", "prompt_id": "prompt-1", "prompt_kind": "", "status": "resolved", "correlation_id": "corr-1"},
            {"type": "text_delta", "text": "Confirmed."},
            {"type": "turn_end"},
        ]
        sent_methods = [frame["method"] for frame in socket.sent]
        assert sent_methods == ["conversation.open", "prompt.submit", "prompt.respond"]
        response = socket.sent[-1]
        assert response["params"] == {
            "conversation_handle": "opaque-home-handle",
            "turn_id": "home-turn-1",
            "correlation_id": "corr-1",
            "event_type": "approval.request",
            "response": {"choice": "yes"},
        }
        assert "device-secret" not in json.dumps(socket.sent)
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_home_browser_session_submits_typed_choice_with_current_freshness_context():
    prompt = _notification(
        "event",
        {
            "schema": 1,
            "conversation_handle": "opaque-home-handle",
            "turn_id": "home-turn-1",
            "correlation_id": "corr-typed-1",
            "event": {
                "type": "prompt_request",
                "payload": {
                    "prompt_id": "prompt-typed-1",
                    "prompt_kind": "choice",
                    "text": "Inspect one of these items",
                    "options": [{"id": "inspect", "label": "Inspect the device"}],
                    "choice": {
                        "object_id": "home-object-1",
                        "operations": ["choose", "explore"],
                        "freshness": "home-freshness-1",
                    },
                },
            },
        },
    )
    socket = _ready_socket(prompt)
    session = HomeBrowserSession(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "opaque-home-handle",
        connect_factory=_FakeConnect([socket]),
    )
    await session.connect()
    stream = session.send_turn("inspect")
    try:
        event = await stream.__anext__()
        assert event["choice"] == {
            "object_id": "home-object-1",
            "operations": ["choose", "explore"],
            "freshness": "home-freshness-1",
        }
        assert not await session.send_prompt_response(
            prompt_id="prompt-typed-1",
            prompt_kind="choice",
            option_id="inspect",
            operation="explore",
            object_id="home-object-1",
            freshness="stale",
        )
        assert not await session.send_prompt_response(
            prompt_id="prompt-typed-1",
            prompt_kind="choice",
            option_id="inspect",
        )
        assert await session.send_prompt_response(
            prompt_id="prompt-typed-1",
            prompt_kind="choice",
            option_id="inspect",
            operation="explore",
            object_id="home-object-1",
            freshness="home-freshness-1",
        )
        assert socket.sent[-1]["params"]["response"] == {
            "operation": "explore",
            "option_id": "inspect",
            "object_id": "home-object-1",
            "freshness": "home-freshness-1",
        }
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_home_browser_session_rejects_choice_without_home_freshness_context():
    prompt = _notification(
        "event",
        {
            "schema": 1,
            "conversation_handle": "opaque-home-handle",
            "turn_id": "home-turn-1",
            "correlation_id": "corr-missing-choice-context",
            "event": {
                "type": "prompt_request",
                "payload": {
                    "prompt_id": "prompt-missing-choice-context",
                    "prompt_kind": "choice",
                    "text": "Inspect one of these items",
                    "options": [{"id": "inspect", "label": "Inspect the device"}],
                },
            },
        },
    )
    socket = _ready_socket(prompt)
    session = HomeBrowserSession(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "opaque-home-handle",
        connect_factory=_FakeConnect([socket]),
    )
    await session.connect()
    stream = session.send_turn("inspect")
    try:
        await stream.__anext__()
        assert not await session.send_prompt_response(
            prompt_id="prompt-missing-choice-context",
            prompt_kind="choice",
            option_id="inspect",
        )
        assert [frame["method"] for frame in socket.sent] == [
            "conversation.open",
            "prompt.submit",
        ]
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_home_browser_prompt_response_rejects_stale_action_without_writing():
    socket = _ready_socket(
        _notification(
            "event",
            {
                "schema": 1,
                "conversation_handle": "opaque-home-handle",
                "turn_id": "home-turn-1",
                "correlation_id": "corr-1",
                "event": {
                    "type": "approval.request",
                    "payload": {
                        "prompt_id": "prompt-1",
                        "prompt_kind": "choice",
                    },
                },
            },
        )
    )
    session = HomeBrowserSession(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "opaque-home-handle",
        connect_factory=_FakeConnect([socket]),
    )
    await session.connect()
    stream = session.send_turn("confirm")
    try:
        await stream.__anext__()
        assert not await session.send_prompt_response(
            prompt_id="other-prompt",
            prompt_kind="choice",
            option_id="yes",
        )
        assert [frame["method"] for frame in socket.sent] == [
            "conversation.open",
            "prompt.submit",
        ]
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_home_browser_session_rejects_prompt_without_fresh_correlation():
    first_prompt = _notification(
        "event",
        {
            "schema": 1,
            "conversation_handle": "opaque-home-handle",
            "turn_id": "home-turn-1",
            "correlation_id": "corr-1",
            "event": {
                "type": "approval.request",
                "payload": {
                    "prompt_id": "prompt-1",
                    "prompt_kind": "choice",
                    "options": [{"id": "yes", "label": "Approve"}],
                },
            },
        },
    )
    second_prompt_without_correlation = _event(
        "approval.request",
        "home-turn-1",
        {
            "prompt_id": "prompt-2",
            "prompt_kind": "choice",
            "options": [{"id": "no", "label": "Deny"}],
        },
    )
    socket = _ready_socket(first_prompt, second_prompt_without_correlation)
    session = HomeBrowserSession(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "opaque-home-handle",
        connect_factory=_FakeConnect([socket]),
    )
    await session.connect()
    stream = session.send_turn("confirm twice")
    try:
        first = await stream.__anext__()
        assert first["correlation_id"] == "corr-1"
        with pytest.raises(
            HomeBridgeProtocolError,
            match="structured prompt has no correlation ID",
        ):
            await stream.__anext__()
        assert not session.is_connected()
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_home_browser_session_emits_the_browser_terminal_event():
    socket = _ready_socket(
        _event("message.delta", "home-turn-1", {"rendered": "done"}),
        _event("turn.complete", "home-turn-1", {"status": "completed"}),
    )
    session = HomeBrowserSession(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "opaque-home-handle",
        connect_factory=_FakeConnect([socket]),
    )
    await session.connect()
    try:
        events = [event async for event in session.send_turn("complete")]
        assert events[-1] == {"type": "turn_end"}
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
async def test_home_text_delta_preserves_delta_when_text_is_absent():
    socket = _ready_socket(
        _event("text_delta", "home-turn-1", {"delta": "from Home"}),
        _event("turn.complete", "home-turn-1", {"status": "completed"}),
    )
    session = _session(_FakeConnect([socket]))
    await session.connect()
    try:
        events = [event async for event in session.send_turn("delta field")]
        assert events == [{"type": "text_delta", "text": "from Home"}]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_message_complete_without_status_owns_terminal_completion():
    socket = _FakeSocket()
    session = _session(_FakeConnect([socket]))
    await session.connect()
    events: list[dict] = []

    async def collect() -> None:
        async for event in session.send_turn("implicit completion"):
            events.append(event)

    stream_task = asyncio.create_task(collect())
    try:
        for _ in range(100):
            if len(socket.sent) >= 2:
                break
            await asyncio.sleep(0)
        assert len(socket.sent) == 2
        socket.incoming.put_nowait(
            _event("message.complete", "home-turn-1", {"text": "done"})
        )
        await asyncio.wait_for(stream_task, timeout=1)
    finally:
        if not stream_task.done():
            stream_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await stream_task
        await session.close()

    assert events[-1] == {
        "type": "message_complete",
        "text": "done",
        "reasoning": "",
        "failure_reason": "",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    [
        "prompt_request",
        "approval.request",
        "clarify.request",
        "secret.request",
        "sudo.request",
    ],
)
async def test_home_unsupported_structured_prompt_is_rejected_and_closes_turn(
    event_type,
):
    socket = _ready_socket(
        _event(
            event_type,
            "home-turn-1",
            {"prompt_id": "approval-1", "prompt_kind": "choice"},
        )
    )
    session = _session(_FakeConnect([socket]))
    await session.connect()
    stream = session.send_turn("needs approval")
    events = [await stream.__anext__()]
    await stream.aclose()

    assert events == [
        {"type": "error", "error": "Home Puck does not support structured prompts"}
    ]
    assert not session.is_connected()
    await session.close()


@pytest.mark.asyncio
async def test_home_transport_failure_requires_reconnect_and_never_replays_prompt():
    first = _ready_socket(ConnectionError("socket closed"))

    class _DropReconnect:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, _url: str, **_kwargs: object) -> _FakeContext | _FailingContext:
            self.calls += 1
            if self.calls == 1:
                return _FakeContext(first)
            return _FailingContext()

    factory = _DropReconnect()
    session = HomePuckSession(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "opaque-home-handle",
        connect_factory=factory,
    )
    await session.connect()
    with pytest.raises(HomeBridgeTransportError):
        _ = [event async for event in session.send_turn("do not replay")]

    assert factory.calls == 2  # the second call attempted reconnect
    assert not session.is_connected()
    assert [frame["method"] for frame in first.sent].count("prompt.submit") == 1
    await session.close()


@pytest.mark.asyncio
async def test_home_resumes_buffered_text_after_mid_turn_drop_and_closes_audio_locally():
    first = _ready_socket(
        _audio(
            "start",
            "home-turn-1",
            sample_rate=24_000,
            channels=1,
            sample_width=2,
            byte_order="little",
        ),
        b"\x01\x00\x02\x00",
        ConnectionError("socket dropped after audio started"),
    )

    class _ResumedSocket(_FakeSocket):
        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            if payload["method"] != "conversation.reconnect":
                await super().send(raw)
                return
            self.sent.append(payload)
            self.incoming.put_nowait(
                _reply(
                    payload["id"],
                    {
                        **READY,
                        "unresolved_turn": {
                            "schema": 1,
                            "conversation_handle": "opaque-home-handle",
                            "turn_id": "home-turn-1",
                            "status": "submitted",
                        },
                    },
                )
            )
            self.incoming.put_nowait(
                _event("message.delta", "home-turn-1", {"text": "continued text"})
            )
            self.incoming.put_nowait(
                _event("turn.complete", "home-turn-1", {"status": "completed"})
            )

    resumed = _ResumedSocket()
    factory = _FakeConnect([first, resumed])
    session = _session(factory)
    await session.connect()

    events = [event async for event in session.send_turn("submit once")]

    assert [event["type"] for event in events] == [
        "audio_start",
        "audio_chunk",
        "audio_end",
        "text_delta",
    ]
    assert events[-1] == {"type": "text_delta", "text": "continued text"}
    assert [frame["method"] for frame in first.sent] == [
        "conversation.open",
        "prompt.submit",
    ]
    assert [frame["method"] for frame in resumed.sent] == [
        "conversation.reconnect",
    ]
    await session.close()


@pytest.mark.asyncio
async def test_home_connection_entry_transport_failure_is_typed():
    session = _session(_FailingConnect())

    with pytest.raises(HomeBridgeTransportError):
        await session.connect()

    assert not session.is_connected()


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


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["mystery", None])
async def test_unknown_or_missing_prompt_delivery_metadata_closes_without_replay(delivery):
    class _UnknownDeliverySocket(_FakeSocket):
        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if payload["method"] in {"conversation.open", "conversation.reconnect"}:
                self.incoming.put_nowait(_reply(payload["id"], READY))
            elif payload["method"] == "prompt.submit":
                self.incoming.put_nowait(
                    _rpc_error(payload["id"], "request_rejected", delivery)
                )

    socket = _UnknownDeliverySocket()
    session = _session(_FakeConnect([socket]))
    await session.connect()
    with pytest.raises(HomeBridgeProtocolError):
        _ = [event async for event in session.send_turn("unknown delivery")]

    assert not session.is_connected()
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
        {
            "schema": 1,
            "status": "ready",
            "conversation_handle": "opaque-home-handle",
            "route": READY["route"],
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
@pytest.mark.parametrize(
    "reconnect_value",
    [None, "yes", 1],
)
async def test_home_unavailable_reconnect_flag_does_not_poison_fresh_open(
    reconnect_value,
):
    result = {
        "schema": 1,
        "status": "unavailable",
        "reason": "authorization_unavailable",
    }
    if reconnect_value is not None:
        result["reconnect_required"] = reconnect_value
    first = _ReadinessSocket(result)
    second = _FakeSocket()
    factory = _FakeConnect([first, second])
    session = _session(factory)

    with pytest.raises(HomeBridgeProtocolError):
        await session.connect()

    await session.connect()
    try:
        assert [frame["method"] for frame in second.sent] == [
            "conversation.open"
        ]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_reconnects_an_unavailable_binding_when_requested():
    first = _ReadinessSocket(
        {
            "schema": 1,
            "status": "unavailable",
            "reconnect_required": True,
        }
    )
    second = _FakeSocket()
    session = _session(_FakeConnect([first, second]))

    with pytest.raises(HomeBridgeProtocolError):
        await session.connect()

    await session.connect()
    try:
        assert [frame["method"] for frame in second.sent] == [
            "conversation.reconnect"
        ]
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_payload",
    [
        {
            "code": -32000,
            "message": "malformed",
            "data": {"schema": True, "code": "request_rejected", "delivery": "known"},
        },
        {"code": -32000, "message": "missing data"},
        {
            "code": -32000,
            "message": "missing code",
            "data": {"schema": 1, "delivery": "known"},
        },
        {
            "code": -32000,
            "message": "missing delivery",
            "data": {"schema": 1, "code": "request_rejected"},
        },
    ],
)
async def test_home_malformed_rpc_error_closes_the_binding(error_payload):
    class _MalformedErrorSocket(_FakeSocket):
        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if payload["method"] in {"conversation.open", "conversation.reconnect"}:
                self.incoming.put_nowait(_reply(payload["id"], READY))
            elif payload["method"] == "prompt.submit":
                self.incoming.put_nowait(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "schema": 1,
                            "id": payload["id"],
                            "error": error_payload,
                        }
                    )
                )

    session = _session(_FakeConnect([_MalformedErrorSocket()]))
    await session.connect()
    with pytest.raises(HomeBridgeProtocolError):
        _ = [event async for event in session.send_turn("malformed error")]

    assert not session.is_connected()
    await session.close()


@pytest.mark.asyncio
async def test_home_known_non_request_rpc_error_is_not_reusable():
    class _KnownFailureSocket(_FakeSocket):
        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if payload["method"] in {"conversation.open", "conversation.reconnect"}:
                self.incoming.put_nowait(_reply(payload["id"], READY))
            elif payload["method"] == "prompt.submit":
                self.incoming.put_nowait(_rpc_error(payload["id"], "transport_timeout", "uncertain"))

    session = _session(_FakeConnect([_KnownFailureSocket()]))
    await session.connect()
    with pytest.raises(HomeBridgeTransportError):
        _ = [event async for event in session.send_turn("known failure")]

    assert not session.is_connected()
    await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "status"),
    [
        ("message.complete", "running"),
        ("message.complete", "future-status"),
        ("turn.complete", "pending"),
        ("turn.end", True),
    ],
)
async def test_home_rejects_invalid_terminal_statuses(event_type, status):
    socket = _ready_socket(_event(event_type, "home-turn-1", {"status": status}))
    session = _session(_FakeConnect([socket]))
    await session.connect()
    try:
        with pytest.raises(HomeBridgeProtocolError):
            _ = [event async for event in session.send_turn("bad terminal")]
        assert not session.is_connected()
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["turn.complete", "message.complete"])
@pytest.mark.parametrize(
    ("status", "expected_type"),
    [
        ("failed", "error"),
        ("error", "error"),
        ("timeout", "error"),
        ("timed_out", "error"),
        ("aborted", "turn_interrupted"),
        ("stopped", "turn_interrupted"),
        ("cancelled", "turn_interrupted"),
    ],
)
async def test_home_message_and_turn_terminal_statuses_are_classified(
    event_type, status, expected_type
):
    socket = _ready_socket(_event(event_type, "home-turn-1", {"status": status}))
    session = _session(_FakeConnect([socket]))
    await session.connect()
    try:
        events = [event async for event in session.send_turn("terminal status")]
        assert [event["type"] for event in events] == [expected_type]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_cancelled_prompt_submit_before_ack_requires_reconnect():
    class _DelayedSubmitSocket(_FakeSocket):
        def __init__(self) -> None:
            super().__init__()
            self.submit_started = asyncio.Event()

        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if payload["method"] in {"conversation.open", "conversation.reconnect"}:
                self.incoming.put_nowait(_reply(payload["id"], READY))
            elif payload["method"] == "prompt.submit":
                self.submit_started.set()

    first = _DelayedSubmitSocket()
    second = _FakeSocket()
    factory = _FakeConnect([first, second])
    session = _session(factory)
    await session.connect()
    stream = session.send_turn("cancel before acknowledgement")
    stream_task = asyncio.create_task(stream.__anext__())
    try:
        await asyncio.wait_for(first.submit_started.wait(), timeout=1)
        stream_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stream_task
        assert not session.is_connected()

        await session.connect()
        assert [frame["method"] for frame in second.sent] == [
            "conversation.reconnect"
        ]
        assert all(frame["method"] != "prompt.submit" for frame in second.sent)
    finally:
        if not stream_task.done():
            stream_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await stream_task
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_home_rejects_boolean_schema_values():
    class _BooleanSchemaSocket(_FakeSocket):
        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if payload["method"] in {"conversation.open", "conversation.reconnect"}:
                self.incoming.put_nowait(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "schema": True,
                            "id": payload["id"],
                            "result": READY,
                        }
                    )
                )

    session = _session(_FakeConnect([_BooleanSchemaSocket()]))
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
async def test_home_rejects_same_turn_event_from_a_foreign_handle():
    foreign_same_turn = _notification(
        "event",
        {
            "schema": 1,
            "conversation_handle": "other-handle",
            "turn_id": "home-turn-1",
            "event": {"type": "turn.complete", "payload": {"status": "completed"}},
        },
    )
    socket = _ready_socket(
        foreign_same_turn,
        _event("text.delta", "home-turn-1", {"text": "owned"}),
        _event("turn.complete", "home-turn-1", {"status": "completed"}),
    )
    session = _session(_FakeConnect([socket]))
    await session.connect()
    try:
        events = [event async for event in session.send_turn("foreign event")]
        assert events == [{"type": "text_delta", "text": "owned"}]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_does_not_finish_until_terminal_event_after_audio_end():
    socket = _FakeSocket()
    session = _session(_FakeConnect([socket]))
    await session.connect()
    events: list[dict] = []

    async def collect() -> None:
        async for event in session.send_turn("wait for terminal"):
            events.append(event)

    stream_task = asyncio.create_task(collect())
    try:
        for _ in range(100):
            if len(socket.sent) >= 2:
                break
            await asyncio.sleep(0)
        assert len(socket.sent) == 2
        socket.incoming.put_nowait(
            _audio(
                "start",
                "home-turn-1",
                sample_rate=24000,
                channels=1,
                sample_width=2,
                byte_order="little",
            )
        )
        socket.incoming.put_nowait(b"\x00\x00")
        socket.incoming.put_nowait(_audio("end", "home-turn-1"))
        for _ in range(100):
            if any(event["type"] == "audio_end" for event in events):
                break
            await asyncio.sleep(0)
        assert any(event["type"] == "audio_end" for event in events)
        assert not stream_task.done()

        socket.incoming.put_nowait(
            _event("turn.complete", "home-turn-1", {"status": "completed"})
        )
        await asyncio.wait_for(stream_task, timeout=1)
    finally:
        if not stream_task.done():
            stream_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await stream_task
        await session.close()

    assert [event["type"] for event in events] == [
        "audio_start",
        "audio_chunk",
        "audio_end",
    ]


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
async def test_home_malformed_ping_closes_the_binding():
    class _MalformedPingSocket(_FakeSocket):
        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if payload["method"] in {"conversation.open", "conversation.reconnect"}:
                self.incoming.put_nowait(_reply(payload["id"], READY))
            elif payload["method"] == "bridge.ping":
                self.incoming.put_nowait(
                    _reply(payload["id"], {"schema": True, "status": "alive"})
                )

    session = _session(_FakeConnect([_MalformedPingSocket()]))
    await session.connect()
    with pytest.raises(HomeBridgeProtocolError):
        await session.ping()

    assert not session.is_connected()
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
async def test_home_interrupt_ack_does_not_end_the_live_turn_stream():
    class _LiveInterruptSocket(_FakeSocket):
        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if payload["method"] in {"conversation.open", "conversation.reconnect"}:
                self.incoming.put_nowait(_reply(payload["id"], READY))
            elif payload["method"] == "prompt.submit":
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
            elif payload["method"] == "session.interrupt":
                self.incoming.put_nowait(
                    _reply(payload["id"], {"accepted": True, "status": "accepted"})
                )

    socket = _LiveInterruptSocket()
    session = _session(_FakeConnect([socket]))
    await session.connect()
    events: list[dict] = []

    async def collect() -> None:
        async for event in session.send_turn("interrupt me"):
            events.append(event)

    stream_task = asyncio.create_task(collect())
    try:
        for _ in range(100):
            if session.active_turn_id == "home-turn-1":
                break
            await asyncio.sleep(0)
        assert session.active_turn_id == "home-turn-1"
        assert await session.interrupt_active_turn()
        assert not stream_task.done()
        socket.incoming.put_nowait(
            _event("turn.interrupted", "home-turn-1", {"status": "interrupted"})
        )
        await asyncio.wait_for(stream_task, timeout=1)
    finally:
        if not stream_task.done():
            stream_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await stream_task
        await session.close()

    assert events == [{"type": "turn_interrupted"}]


@pytest.mark.asyncio
async def test_home_cancelled_submitted_turn_requires_reconnect():
    first = _FakeSocket()
    second = _FakeSocket()
    factory = _FakeConnect([first, second])
    session = _session(factory)
    await session.connect()
    stream_task = asyncio.create_task(session.send_turn("cancel me").__anext__())
    try:
        for _ in range(100):
            if session.active_turn_id == "home-turn-1":
                break
            await asyncio.sleep(0)
        assert session.active_turn_id == "home-turn-1"
        stream_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stream_task
        assert not session.is_connected()

        await session.connect()
        assert [frame["method"] for frame in second.sent] == [
            "conversation.reconnect"
        ]
    finally:
        if not stream_task.done():
            stream_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await stream_task
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


@pytest.mark.asyncio
async def test_home_close_retains_reader_cleanup_ownership(monkeypatch):
    import puck_bridge.home_session as home_session_module

    monkeypatch.setattr(home_session_module, "HOME_BRIDGE_CLOSE_TIMEOUT", 0.01)

    class _SlowCloseSocket(_FakeSocket):
        def __init__(self) -> None:
            super().__init__()
            self.release = asyncio.Event()

        async def recv(self) -> object:
            try:
                return await super().recv()
            except asyncio.CancelledError:
                while not self.release.is_set():
                    try:
                        await self.release.wait()
                    except asyncio.CancelledError:
                        continue
                raise

    first = _SlowCloseSocket()
    second = _FakeSocket()
    factory = _FakeConnect([first, second])
    session = _session(factory)
    await session.connect()
    close_task = asyncio.create_task(session.close())
    await asyncio.sleep(0.05)
    try:
        if not close_task.done():
            first.release.set()
            await close_task
            pytest.fail("Home close waited for the reader beyond its bound")
        await close_task

        with pytest.raises(HomeBridgeTransportError):
            await session.connect()
    finally:
        first.release.set()
        if not close_task.done():
            await close_task

    for _ in range(100):
        retired = session._retired_client
        if retired is None or not retired.cleanup_pending:
            break
        await asyncio.sleep(0)
    assert factory.contexts[0].closed
    await session.connect()
    try:
        assert [frame["method"] for frame in second.sent] == [
            "conversation.reconnect"
        ]
    finally:
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
    with pytest.raises(ValueError):
        require_home_bridge_url("wss://:443/api/v1/bridge/ws")
    with pytest.raises(ValueError):
        require_home_bridge_url("wss://@home.example/api/v1/bridge/ws")
