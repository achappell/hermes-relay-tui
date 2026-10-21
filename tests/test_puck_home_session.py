"""Deterministic coverage for the opt-in Puck/Home bridge adapter."""

from __future__ import annotations

import asyncio
import json
import time

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
from puck_bridge.home_admission import (
    CalibratedProximityEvidence,
    HomeClaimRecoveryState,
    HomePuckSessionFactory,
)
from puck_bridge.home_admission import (
    HomeClaimHTTPError, HomeIdentityRejectionState, HomeMappingUnavailable,
    _request_json, is_home_identity_rejection,
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
        elif method == "conversation.close":
            self.incoming.put_nowait(
                _reply(
                    payload["id"],
                    {
                        "conversation_handle": "opaque-home-handle",
                        "status": "closed",
                    },
                )
            )
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
                "type": "prompt.request",
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
                "type": "prompt.request",
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


# Typed-choice projection copied from hermes-relay-home
# _bmad-output/specs/spec-home-bridge-route-roaming/bridge-contract.md
# ("Typed choices use this normalized event payload"), carried in the
# contract's `event` notification envelope.
HOME_CONTRACT_CHOICE_PAYLOAD = {
    "prompt_id": "standard-request-id",
    "prompt_kind": "choice",
    "text": "Choose an inspection step.",
    "timeout_s": 300,
    "choice": {
        "object_id": "home-choice-id",
        "freshness": "home-freshness-id",
        "operations": ["choose", "explore"],
    },
    "options": [{"id": "inspect", "label": "Inspect"}],
}


def _home_contract_choice_frame(event_type: str = "prompt.request") -> str:
    return _notification(
        "event",
        {
            "schema": 1,
            "conversation_handle": "opaque-home-handle",
            "turn_id": "home-turn-1",
            "correlation_id": "standard-request-id",
            "event": {
                "type": event_type,
                "payload": HOME_CONTRACT_CHOICE_PAYLOAD,
            },
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["choose", "explore"])
async def test_home_contract_prompt_request_reaches_display_and_answers_with_dotted_event_type(
    operation,
):
    from home_display.appliance import _classify_prompt_request
    from home_display.state import DisplayChoice

    socket = _ready_socket(_home_contract_choice_frame())
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
        # Recognised as a structured prompt, not an unknown wire event.
        assert event["type"] == "prompt_request"
        assert event["prompt_id"] == "standard-request-id"
        assert event["prompt_kind"] == "choice"
        assert event["correlation_id"] == "standard-request-id"
        assert event["choice"] == HOME_CONTRACT_CHOICE_PAYLOAD["choice"]
        assert event["options"] == [{"id": "inspect", "label": "Inspect"}]

        # The appliance/browser path turns it into a typed choice prompt.
        prompt = _classify_prompt_request(event)
        assert prompt is not None
        assert prompt.kind == "choice"
        assert prompt.action_id == "standard-request-id"
        assert prompt.choice == DisplayChoice(
            "home-choice-id", ("choose", "explore"), "home-freshness-id"
        )

        # Freshness/object/operation gating still applies: nothing is written.
        for bad in (
            {"object_id": "other-object", "freshness": "home-freshness-id"},
            {"object_id": "home-choice-id", "freshness": "stale"},
        ):
            assert not await session.send_prompt_response(
                prompt_id="standard-request-id",
                prompt_kind="choice",
                option_id="inspect",
                operation=operation,
                **bad,
            )
        assert not await session.send_prompt_response(
            prompt_id="standard-request-id",
            prompt_kind="choice",
            option_id="inspect",
            operation="dismiss",
            object_id="home-choice-id",
            freshness="home-freshness-id",
        )
        assert not await session.send_prompt_response(
            prompt_id="standard-request-id",
            prompt_kind="choice",
            option_id="not-offered",
            operation=operation,
            object_id="home-choice-id",
            freshness="home-freshness-id",
        )
        assert [frame["method"] for frame in socket.sent] == [
            "conversation.open",
            "prompt.submit",
        ]

        assert await session.send_prompt_response(
            prompt_id="standard-request-id",
            prompt_kind="choice",
            option_id="inspect",
            operation=operation,
            object_id="home-choice-id",
            freshness="home-freshness-id",
        )
        assert socket.sent[-1]["method"] == "prompt.respond"
        assert socket.sent[-1]["params"] == {
            "conversation_handle": "opaque-home-handle",
            "turn_id": "home-turn-1",
            "correlation_id": "standard-request-id",
            "event_type": "prompt.request",
            "response": {
                "operation": operation,
                "option_id": "inspect",
                "object_id": "home-choice-id",
                "freshness": "home-freshness-id",
            },
        }
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_home_contract_choice_respects_operations_home_offers():
    frame = _notification(
        "event",
        {
            "schema": 1,
            "conversation_handle": "opaque-home-handle",
            "turn_id": "home-turn-1",
            "correlation_id": "standard-request-id",
            "event": {
                "type": "prompt.request",
                "payload": {
                    **HOME_CONTRACT_CHOICE_PAYLOAD,
                    "choice": {
                        **HOME_CONTRACT_CHOICE_PAYLOAD["choice"],
                        "operations": ["explore"],
                    },
                },
            },
        },
    )
    socket = _ready_socket(frame)
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
            prompt_id="standard-request-id",
            prompt_kind="choice",
            option_id="inspect",
            operation="choose",
            object_id="home-choice-id",
            freshness="home-freshness-id",
        )
        assert [frame["method"] for frame in socket.sent] == [
            "conversation.open",
            "prompt.submit",
        ]
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_home_contract_prompt_request_is_refused_without_structured_prompt_support():
    socket = _ready_socket(_home_contract_choice_frame())
    session = _session(_FakeConnect([socket]))
    await session.connect()
    stream = session.send_turn("inspect")
    events = [await stream.__anext__()]
    await stream.aclose()

    assert events == [
        {"type": "error", "error": "Home Puck does not support structured prompts"}
    ]
    assert not session.is_connected()
    await session.close()


@pytest.mark.asyncio
async def test_underscore_prompt_request_is_not_a_home_wire_event():
    # Home never emits `prompt_request`; the underscore name only exists as
    # the normalized event this session yields. A wire frame using it must
    # not become a pending prompt that could be answered.
    socket = _ready_socket(_home_contract_choice_frame("prompt_request"))
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
        assert event["type"] == "unknown_event"
        assert event["event_type"] == "prompt_request"
        assert not await session.send_prompt_response(
            prompt_id="standard-request-id",
            prompt_kind="choice",
            option_id="inspect",
            operation="choose",
            object_id="home-choice-id",
            freshness="home-freshness-id",
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
        "prompt.request",
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
            {"type": "audio_abort", "error": "Home bridge response audio unavailable", "reason": "home_audio_unavailable"},
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
async def test_home_normalizes_thinking_delta_field_from_standard_event():
    socket = _ready_socket(
        _event("thinking.delta", "home-turn-1", {"delta": "working it out"}),
        _event("message.complete", "home-turn-1", {"text": "done"}),
    )
    session = _session(_FakeConnect([socket]))
    await session.connect()
    try:
        events = [event async for event in session.send_turn("think")]
        assert events[0] == {"type": "thinking_delta", "text": "working it out"}
        assert all(event.get("type") != "unknown_event" for event in events)
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


@pytest.mark.asyncio
async def test_home_drops_queued_events_after_socket_disconnect():
    class _QueueThenDisconnectSocket(_FakeSocket):
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
                self.incoming.put_nowait(
                    _event(
                        "message.delta",
                        "home-turn-1",
                        {"rendered": "stale queued event"},
                    )
                )
                self.incoming.put_nowait(ConnectionError("socket closed"))

    session = HomePuckSession(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "opaque-home-handle",
        connect_factory=_FakeConnect([_QueueThenDisconnectSocket()]),
        resume_uncertain_turn=False,
    )
    await session.connect()

    delivered = []
    with pytest.raises(HomeBridgeTransportError):
        async for event in session.send_turn("uncertain turn"):
            delivered.append(event)

    assert delivered == []
    assert not session.is_connected()
    await session.close()


@pytest.mark.asyncio
async def test_retired_puck_claim_uses_one_control_only_close_without_replay():
    first = _ready_socket(
        _event("message.delta", "home-turn-1", {"text": "discard this"}),
        ConnectionError("socket dropped"),
    )
    control = _FakeSocket()
    factory = _FakeConnect([first, control])
    session = HomePuckSession(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "opaque-home-handle",
        connect_factory=factory,
        resume_uncertain_turn=False,
    )
    await session.connect()
    with pytest.raises(HomeBridgeTransportError):
        _ = [event async for event in session.send_turn("submit exactly once")]

    assert [frame["method"] for frame in first.sent].count("prompt.submit") == 1
    assert len(factory.calls) == 1
    assert await session.retire_uncertain_claim()
    assert session.claim_retired
    assert [frame["method"] for frame in control.sent] == [
        "conversation.reconnect",
        "conversation.close",
    ]
    assert all("discard this" not in json.dumps(frame) for frame in control.sent)
    await session.close()


@pytest.mark.asyncio
async def test_unconfirmed_puck_claim_can_retry_control_close_once():
    class _FailedCloseSocket(_FakeSocket):
        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            if payload["method"] == "conversation.close":
                self.sent.append(payload)
                self.incoming.put_nowait(ConnectionError("close not confirmed"))
                return
            await super().send(raw)

    first = _FakeSocket()
    failed_control = _FailedCloseSocket()
    confirmed_control = _FakeSocket()
    factory = _FakeConnect([first, failed_control, confirmed_control])
    session = _session(factory)
    await session.connect()

    assert not await session.retire_uncertain_claim()
    assert not session._retirement_confirmed
    assert await session.retry_uncertain_claim()
    assert session._retirement_confirmed
    assert [
        frame["method"] for frame in failed_control.sent
    ] == ["conversation.reconnect", "conversation.close"]
    assert [
        frame["method"] for frame in confirmed_control.sent
    ] == ["conversation.reconnect", "conversation.close"]
    await session.close()


@pytest.mark.asyncio
async def test_home_strict_fresh_claim_fetches_policy_but_does_not_claim_without_evidence():
    calls = []
    factory = HomePuckSessionFactory(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "puck-1",
        evidence_provider=None,
        request_json=lambda *args, **kwargs: calls.append((args, kwargs)) or {
            "schema": 1, "snapshot": {
                "revision": 4,
                "wake_mappings": [{"id": "hey-missy", "phrase": "Hey Missy"}],
            },
        },
    )

    result = await factory.admit_wake("hey missy")

    assert result.status == "denied"
    assert result.reason == "calibration_unavailable"
    assert len(calls) == 1 and calls[0][0][0] == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    ["stale", "future", "negative", "too_large", "nan", "infinite", "blank_id", "bool"],
)
async def test_home_strict_fresh_claim_rejects_invalid_evidence_before_claim(case):
    now_ms = int(time.time() * 1000)
    value = 0.8
    calibration_id = "calibration-1"
    observed_at_ms = now_ms
    if case == "stale":
        observed_at_ms -= 1001
    elif case == "future":
        observed_at_ms += 1000
    elif case == "negative":
        value = -0.01
    elif case == "too_large":
        value = 1.01
    elif case == "nan":
        value = float("nan")
    elif case == "infinite":
        value = float("inf")
    elif case == "blank_id":
        calibration_id = "  "
    elif case == "bool":
        value = True

    requests = []
    factory = HomePuckSessionFactory(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "puck-1",
        evidence_provider=lambda _phrase: CalibratedProximityEvidence(
            value, calibration_id, observed_at_ms
        ),
        request_json=lambda *args, **kwargs: requests.append((args, kwargs)) or {
            "schema": 1, "snapshot": {
                "revision": 4,
                "wake_mappings": [{"id": "hey-missy", "phrase": "Hey Missy"}],
            },
        },
    )

    result = await factory.admit_wake("hey missy")

    assert result.status == "denied"
    assert result.reason == "invalid_proximity_evidence"
    assert len(requests) == 1 and requests[0][0][0] == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_field", ["claim_id", "configuration_revision"])
async def test_home_fresh_claim_rejects_a_mismatched_grant_binding(wrong_field):
    requested = []

    def request_json(method, url, *, credential, payload, timeout):
        del url, credential, timeout
        if method == "GET":
            return {
                "schema": 1,
                "snapshot": {
                    "revision": 4,
                    "wake_mappings": [{"id": "hey-missy", "phrase": "Hey Missy"}],
                },
            }
        requested.append(payload)
        response = {
            "schema": 1,
            "claim_id": payload["claim_id"],
            "configuration_revision": 4,
            "decision": "granted",
            "conversation_handle": "fresh-home-handle",
        }
        response[wrong_field] = (
            "some-other-claim"
            if wrong_field == "claim_id"
            else 5
        )
        return response

    factory = HomePuckSessionFactory(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "puck-1",
        evidence_provider=lambda _phrase: CalibratedProximityEvidence(
            0.8, "calibration-1", int(time.time() * 1000)
        ),
        request_json=request_json,
        connect_factory=lambda *_args, **_kwargs: pytest.fail(
            "a mismatched grant must not open its conversation"
        ),
    )

    result = await factory.admit_wake("hey missy")

    assert result.status == "denied"
    assert len(requested) == 1
    assert requested[0]["wake_mapping_id"] == "hey-missy"
    assert requested[0]["configuration_revision"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [
    None, {}, {"mode": "strict"}, {"mode": "paired_room", "room_id": "", "wake_mapping_ids": ["hey-missy"]},
    {"mode": "paired_room", "room_id": "living-room", "wake_mapping_ids": ["other"]},
    {"mode": "paired_room", "room_id": "living-room", "wake_mapping_ids": ["hey-missy", "hey-missy"]},
    {"mode": "paired_room", "room_id": "living-room", "wake_mapping_ids": ["hey-missy"], "score": 1},
])
async def test_paired_room_malformed_policy_never_claims_or_opens(policy):
    calls = []

    def request(method, *args, **kwargs):
        calls.append(method)
        assert method == "GET"
        return {"schema": 1, "snapshot": {
            "revision": 4,
            "wake_mappings": [{"id": "hey-missy", "phrase": "Hey Missy"}],
            "wake_admission": policy,
        }}

    factory = HomePuckSessionFactory(
        f"wss://home.example{HOME_BRIDGE_PATH}", "fixture", "puck-1",
        request_json=request,
        connect_factory=lambda *a, **kw: pytest.fail("invalid policy must never open"),
    )
    result = await factory.admit_wake("Hey Missy")
    assert result.status == "denied"
    assert result.reason == "invalid_admission_policy"
    assert calls == ["GET"]
    assert not factory.identity_rejected


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("admission_mode", None), ("admission_mode", "strict"),
    ("claim_id", "foreign"), ("configuration_revision", True),
    ("configuration_revision", 5), ("schema", True),
    ("conversation_handle", ""),
])
async def test_paired_room_grant_requires_exact_authority(field, value):
    calls = []

    def request(method, url, *, payload, **kwargs):
        calls.append((method, url))
        if method == "GET":
            return {"schema": 1, "snapshot": {
                "revision": 4,
                "wake_mappings": [{"id": "hey-missy", "phrase": "Hey Missy"}],
                "wake_admission": {"mode": "paired_room", "room_id": "living-room", "wake_mapping_ids": ["hey-missy"]},
            }}
        assert url.endswith("/paired-room-claims")
        assert set(payload) == {"schema", "claim_id", "device_id", "wake_mapping_id", "configuration_revision", "initiation"}
        grant = {"schema": 1, "claim_id": payload["claim_id"], "decision": "granted",
                 "configuration_revision": 4, "conversation_handle": "issued",
                 "admission_mode": "paired_room"}
        grant[field] = value
        return grant

    factory = HomePuckSessionFactory(
        f"wss://home.example{HOME_BRIDGE_PATH}", "fixture", "puck-1",
        request_json=request,
        connect_factory=lambda *a, **kw: pytest.fail("invalid grant must never open"),
    )
    assert (await factory.admit_wake("Hey Missy")).status == "denied"
    assert [method for method, _ in calls] == ["GET", "POST"]
    assert not factory.identity_rejected


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [
    (403, "forbidden"), (409, "duplicate_claim"), (409, "stale_configuration"),
    (409, "conversation_active"), (503, "service_unavailable"),
])
async def test_paired_room_denial_is_not_replayed_or_credential_retirement(status, code):
    calls = []

    def request(method, url, *, payload, **kwargs):
        calls.append((method, url))
        if method == "GET":
            return {"schema": 1, "snapshot": {
                "revision": 4, "wake_mappings": [{"id": "hey-missy", "phrase": "Hey Missy"}],
                "wake_admission": {"mode": "paired_room", "room_id": "living-room", "wake_mapping_ids": ["hey-missy"]},
            }}
        assert url.endswith("/paired-room-claims")
        raise HomeClaimHTTPError(status, code)

    factory = HomePuckSessionFactory(
        f"wss://home.example{HOME_BRIDGE_PATH}", "fixture", "puck-1",
        request_json=request,
        connect_factory=lambda *a, **kw: pytest.fail("denied claim must never open"),
    )
    assert (await factory.admit_wake("Hey Missy")).status == "denied"
    assert [method for method, _ in calls] == ["GET", "POST"]
    assert not factory.identity_rejected


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [None, "schema", "handle", "mode", "status", "not_found", "forbidden", "unauthorized"])
async def test_owned_paired_retirement_requires_exact_authoritative_receipt(mutation):
    calls = []

    def request(method, url, *, payload, **kwargs):
        calls.append((method, url, payload))
        if mutation in {"not_found", "forbidden", "unauthorized"}:
            raise HomeClaimHTTPError(
                {"not_found": 404, "forbidden": 403, "unauthorized": 401}[mutation],
                mutation,
            )
        receipt = {"schema": 1, "conversation_handle": "saved", "admission_mode": "paired_room", "status": "closed"}
        if mutation == "schema":
            receipt["schema"] = True
        elif mutation == "handle":
            receipt["conversation_handle"] = "foreign"
        elif mutation == "mode":
            receipt["admission_mode"] = "wake"
        elif mutation == "status":
            receipt["status"] = "active"
        return receipt

    factory = HomePuckSessionFactory(
        f"wss://home.example{HOME_BRIDGE_PATH}", "fixture", "puck-1", request_json=request,
    )
    assert await factory.close_paired_claim("saved") is (mutation is None)
    assert calls == [("POST", "https://home.example/api/v1/paired-room-claims/close",
                      {"schema": 1, "conversation_handle": "saved"})]
    assert factory.identity_rejected is (mutation == "unauthorized")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 201, 202])
async def test_owned_paired_retirement_requires_actual_http_200(status):
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.path == "/api/v1/paired-room-claims/close"
            assert payload == {"schema": 1, "conversation_handle": "saved"}
            body = json.dumps({"schema": 1, "conversation_handle": "saved",
                               "admission_mode": "paired_room", "status": "closed"}).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        factory = HomePuckSessionFactory(
            f"wss://home.example{HOME_BRIDGE_PATH}", "fixture", "puck-1",
            api_base_url=f"http://127.0.0.1:{server.server_port}/api/v1",
        )
        assert await factory.close_paired_claim("saved") is (status == 200)
        assert not factory.identity_rejected
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("paired_room", [False, True])
async def test_home_fresh_claim_opens_a_verified_new_handle(tmp_path, paired_room):
    calls = []

    class _FreshHandleSocket(_FakeSocket):
        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            method = payload["method"]
            if method in {"conversation.open", "conversation.reconnect"}:
                ready = {**READY, "conversation_handle": "fresh-home-handle"}
                self.incoming.put_nowait(_reply(payload["id"], ready))
            elif method == "conversation.close":
                self.incoming.put_nowait(
                    _reply(
                        payload["id"],
                        {
                            "conversation_handle": "fresh-home-handle",
                            "status": "closed",
                        },
                    )
                )

    def request_json(method, url, *, credential, payload, timeout):
        del url, credential, timeout
        calls.append((method, payload))
        if method == "GET":
            configuration = {
                "schema": 1,
                "snapshot": {
                    "revision": 4,
                    "wake_mappings": [{"id": "hey-missy", "phrase": "Hey Missy"}],
                },
            }
            if paired_room:
                configuration["snapshot"]["wake_admission"] = {
                    "mode": "paired_room", "room_id": "living-room",
                    "wake_mapping_ids": ["hey-missy"],
                }
            return configuration
        return {
            "schema": 1,
            "claim_id": payload["claim_id"],
            "configuration_revision": 4,
            "decision": "granted",
            "conversation_handle": "fresh-home-handle",
            **({"admission_mode": "paired_room"} if paired_room else {}),
        }

    socket = _FreshHandleSocket()
    recovery_state = HomeClaimRecoveryState("puck-1", tmp_path / "claim.json")
    factory = HomePuckSessionFactory(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "puck-1",
        evidence_provider=None if paired_room else lambda _phrase: CalibratedProximityEvidence(
            0.8, "calibration-1", int(time.time() * 1000)
        ),
        request_json=request_json,
        connect_factory=_FakeConnect([socket]),
        recovery_state=recovery_state,
    )

    result = await factory.admit_wake("hey missy", previous_handle="old-handle")

    assert result.status == "admitted"
    assert result.session is not None and result.session.is_connected()
    assert result.session.wake_admission_mode == ("paired_room" if paired_room else "")
    assert result.session.conversation_handle == "fresh-home-handle"
    assert result.session.wake_mapping_id == "hey-missy"
    persisted = recovery_state.load()
    assert persisted is not None and persisted.status == "active"
    assert persisted.conversation_handle == "fresh-home-handle"
    assert [method for method, _payload in calls] == ["GET", "POST"]
    claim = calls[1][1]
    if paired_room:
        assert claim == {
            "schema": 1, "claim_id": claim["claim_id"], "device_id": "puck-1",
            "wake_mapping_id": "hey-missy", "configuration_revision": 4,
            "initiation": {"kind": "wake_word"},
        }
    else:
        assert "acoustic_evidence" in claim
        assert "initiation" not in claim
    assert await result.session.close_claim()


@pytest.mark.asyncio
async def test_home_active_claim_admits_only_its_current_authorized_mapping():
    config = {
        "schema": 1,
        "snapshot": {
            "revision": 9,
            "wake_mappings": [
                {"id": "hey-missy", "phrase": "Hey Missy"},
                {"id": "hey-other", "phrase": "Hey Other"},
            ],
        },
    }
    factory = HomePuckSessionFactory(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "puck-1",
        request_json=lambda *_args, **_kwargs: config,
    )

    assert await factory.current_mapping_id("HEY MISSY", "hey-missy") == "hey-missy"
    assert await factory.current_mapping_id("Hey Other", "hey-missy") is None
    # An unbound initial handle cannot borrow one of several active mappings.
    assert await factory.current_mapping_id("Hey Missy") is None


@pytest.mark.asyncio
async def test_home_active_mapping_does_not_infer_a_blank_mapping_id():
    config = {
        "schema": 1,
        "snapshot": {
            "revision": 10,
            "wake_mappings": [
                {"id": "   ", "phrase": "Hey Missy"},
                {"id": "hey-other", "phrase": "Hey Other"},
            ],
        },
    }
    factory = HomePuckSessionFactory(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "puck-1",
        request_json=lambda *_args, **_kwargs: config,
    )

    with pytest.raises(HomeMappingUnavailable):
        await factory.current_mapping_id("Hey Missy")


def test_home_claim_retirement_outer_budget_covers_control_close_cleanup():
    from puck_bridge.home_session import (
        HOME_BRIDGE_CLOSE_TIMEOUT,
        HOME_CLAIM_RETIRE_CALL_TIMEOUT_SECONDS,
        HOME_CLAIM_RETIRE_TIMEOUT,
    )

    assert HOME_CLAIM_RETIRE_CALL_TIMEOUT_SECONDS >= (
        HOME_CLAIM_RETIRE_TIMEOUT + (3 * HOME_BRIDGE_CLOSE_TIMEOUT)
    )


def test_home_claim_recovery_state_survives_restart_and_records_unconfirmed_close(tmp_path):
    state_path = tmp_path / "private" / "claim.json"
    first = HomeClaimRecoveryState("puck-1", state_path)
    assert first.load() is None
    first.record_active("opaque-handle", "hey-missy")

    second = HomeClaimRecoveryState("puck-1", state_path)
    active = second.load()
    assert active is not None
    assert active.status == "active"
    assert active.conversation_handle == "opaque-handle"
    assert active.wake_mapping_id == "hey-missy"
    assert state_path.stat().st_mode & 0o777 == 0o600
    assert state_path.parent.stat().st_mode & 0o777 == 0o700

    second.record_retired("opaque-handle", "hey-missy", confirmed=False)
    third = HomeClaimRecoveryState("puck-1", state_path)
    unconfirmed = third.load()
    assert unconfirmed is not None and unconfirmed.status == "unconfirmed"

    with pytest.raises(ValueError, match="invalid"):
        HomeClaimRecoveryState("another-device", state_path).load()


@pytest.mark.asyncio
@pytest.mark.parametrize("paired_room", [False, True])
async def test_home_fresh_claim_closes_grant_when_websocket_open_fails(tmp_path, paired_room):
    class _OpenFailureSocket(_FakeSocket):
        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if payload["method"] == "conversation.open":
                raise ConnectionError("private open failure")

    class _ControlCloseSocket(_FakeSocket):
        async def send(self, raw: str) -> None:
            payload = json.loads(raw)
            self.sent.append(payload)
            if payload["method"] in {"conversation.open", "conversation.reconnect"}:
                ready = {**READY, "conversation_handle": "fresh-home-handle"}
                self.incoming.put_nowait(_reply(payload["id"], ready))
            elif payload["method"] == "conversation.close":
                self.incoming.put_nowait(
                    _reply(
                        payload["id"],
                        {
                            "conversation_handle": "fresh-home-handle",
                            "status": "closed",
                        },
                    )
                )

    def request_json(method, url, *, credential, payload, timeout):
        del url, credential, timeout
        if method == "GET":
            configuration = {
                "schema": 1,
                "snapshot": {
                    "revision": 4,
                    "wake_mappings": [{"id": "hey-missy", "phrase": "Hey Missy"}],
                },
            }
            if paired_room:
                configuration["snapshot"]["wake_admission"] = {
                    "mode": "paired_room", "room_id": "living-room",
                    "wake_mapping_ids": ["hey-missy"],
                }
            return configuration
        return {
            "schema": 1,
            "claim_id": payload["claim_id"],
            "configuration_revision": 4,
            "decision": "granted",
            "conversation_handle": "fresh-home-handle",
            **({"admission_mode": "paired_room"} if paired_room else {}),
        }

    opening = _OpenFailureSocket()
    control = _ControlCloseSocket()
    recovery_state = HomeClaimRecoveryState("puck-1", tmp_path / "claim.json")
    factory = HomePuckSessionFactory(
        f"wss://home.example{HOME_BRIDGE_PATH}",
        "device-secret",
        "puck-1",
        evidence_provider=None if paired_room else lambda _phrase: CalibratedProximityEvidence(
            0.8, "calibration-1", int(time.time() * 1000)
        ),
        request_json=request_json,
        connect_factory=_FakeConnect([opening, control]),
        recovery_state=recovery_state,
    )

    result = await factory.admit_wake("hey missy")

    assert result.status == "denied"
    assert [frame["method"] for frame in opening.sent] == ["conversation.open"]
    assert [frame["method"] for frame in control.sent] == [
        "conversation.reconnect",
        "conversation.close",
    ]
    record = recovery_state.load()
    assert record is not None and record.status == "retired"


@pytest.mark.asyncio
async def test_failed_healthy_close_releases_actual_client_before_owned_http_confirmation():
    class FailedCloseSocket(_FakeSocket):
        async def send(self, raw):
            frame = json.loads(raw)
            if frame["method"] == "conversation.close":
                raise ConnectionError("isolated close RPC failure")
            await super().send(raw)

    socket = FailedCloseSocket()
    connector = _FakeConnect([socket])
    session = HomePuckSession(
        f"wss://home.example{HOME_BRIDGE_PATH}", "fixture", "opaque-home-handle",
        connect_factory=connector, wake_admission_mode="paired_room",
    )
    await session.connect()
    assert session.is_connected()
    assert not await session.close_claim()
    assert connector.contexts[0].closed
    assert session._client is None

    def owned_receipt(method, url, *, payload, **kwargs):
        assert connector.contexts[0].closed
        assert session._client is None
        return {"schema": 1, "conversation_handle": payload["conversation_handle"],
                "admission_mode": "paired_room", "status": "closed"}

    factory = HomePuckSessionFactory(
        f"wss://home.example{HOME_BRIDGE_PATH}", "fixture", "puck",
        request_json=owned_receipt,
    )
    assert await factory.close_paired_claim(session.conversation_handle)
    await session.close()


@pytest.mark.asyncio
async def test_failed_first_open_retains_pending_owner_until_exact_close_before_new_claim(tmp_path):
    requests = []
    allow_close = [False]
    ready_open = [False]
    handles = []

    class OpeningSocket(_FakeSocket):
        async def send(self, raw):
            frame = json.loads(raw)
            self.sent.append(frame)
            if frame["method"] == "conversation.open" and ready_open[0]:
                self.incoming.put_nowait(_reply(frame["id"], {**READY, "conversation_handle": handles[-1]}))
            elif frame["method"] == "conversation.close":
                self.incoming.put_nowait(_reply(frame["id"], {"conversation_handle": handles[-1], "status": "closed"}))
            else:
                raise ConnectionError("isolated first-open and control-close failure")

    def request(method, url, *, payload, **kwargs):
        requests.append((method, url))
        if url.endswith("/paired-room-claims/close"):
            if not allow_close[0]:
                raise HomeClaimHTTPError(503, "service_unavailable")
            return {"schema": 1, "conversation_handle": payload["conversation_handle"],
                    "admission_mode": "paired_room", "status": "closed"}
        if method == "GET":
            return {"schema": 1, "snapshot": {
                "revision": 4, "wake_mappings": [{"id": "hey-missy", "phrase": "Hey Missy"}],
                "wake_admission": {"mode": "paired_room", "room_id": "living-room", "wake_mapping_ids": ["hey-missy"]},
            }}
        handles.append("issued-" + str(len(handles) + 1))
        return {"schema": 1, "claim_id": payload["claim_id"], "configuration_revision": 4,
                "decision": "granted", "conversation_handle": handles[-1], "admission_mode": "paired_room"}

    state = HomeClaimRecoveryState("puck", tmp_path / "claim.json")
    factory = HomePuckSessionFactory(
        f"wss://home.example{HOME_BRIDGE_PATH}", "fixture", "puck",
        request_json=request, connect_factory=lambda *a, **kw: _FakeContext(OpeningSocket()),
        recovery_state=state,
    )
    assert (await factory.admit_wake("Hey Missy")).status == "denied"
    assert state.load().status == "unconfirmed"
    assert state.load().conversation_handle == "issued-1"
    requests.clear()
    assert (await factory.admit_wake("Hey Missy")).reason == "claim_retirement_unconfirmed"
    assert handles == ["issued-1"]
    assert requests == [("POST", "https://home.example/api/v1/paired-room-claims/close")]
    # A fresh factory after process loss sees the same durable unconfirmed
    # marker; the production server restores it for runner retirement.
    assert HomeClaimRecoveryState("puck", tmp_path / "claim.json").load().status == "unconfirmed"
    allow_close[0] = True
    ready_open[0] = True
    requests.clear()
    result = await factory.admit_wake("Hey Missy")
    try:
        assert result.status == "admitted"
        assert handles == ["issued-1", "issued-2"]
        assert [method for method, _ in requests] == ["POST", "GET", "POST"]
        assert state.load().conversation_handle == "issued-2"
    finally:
        if result.session is not None:
            await result.session.close_claim()


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


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["end", "fallback", "unavailable"])
async def test_home_text_terminal_waits_for_audio_completion(ending):
    socket = _ready_socket(
        _audio("start", "home-turn-1", sample_rate=24000, channels=1,
               sample_width=2, byte_order="little"),
        _event("message.complete", "home-turn-1", {}),
        b"\x01\x00",
        _audio(ending, "home-turn-1"),
    )
    session = _session(_FakeConnect([socket]))
    await session.connect()
    try:
        events = [event async for event in session.send_turn("TEST")]
        assert [event["type"] for event in events] == [
            "audio_start", "message_complete", "audio_chunk",
            "audio_end" if ending == "end" else "audio_abort",
        ]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_missing_audio_end_times_out_after_text_terminal():
    socket = _ready_socket(
        _audio("start", "home-turn-1", sample_rate=24000, channels=1,
               sample_width=2, byte_order="little"),
        _event("message.complete", "home-turn-1", {}),
    )
    session = _session(_FakeConnect([socket]))
    session._request_timeout = 0.02
    await session.connect()
    events = []
    try:
        async for event in session.send_turn("TEST"):
            events.append(event)
        assert events[-2]["type"] == "message_complete"
        assert events[-1]["text_completed"] is True
        assert "timed out" in events[-1]["error"]
        assert not session.is_connected()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_audio_activity_extends_completion_deadline():
    socket = _ready_socket(
        _audio("start", "home-turn-1", sample_rate=24000, channels=1,
               sample_width=2, byte_order="little"),
        _event("message.complete", "home-turn-1", {}),
    )
    session = _session(_FakeConnect([socket]))
    session._request_timeout = 0.1
    await session.connect()
    async def feed_audio():
        for _ in range(4):
            await asyncio.sleep(0.04)
            socket.incoming.put_nowait(b"\x01\x00")
        socket.incoming.put_nowait(_audio("end", "home-turn-1"))
    feeder = asyncio.create_task(feed_audio())
    try:
        events = [event async for event in session.send_turn("TEST")]
        assert events[-1] == {"type": "audio_end"}
        assert sum(event["type"] == "audio_chunk" for event in events) == 4
    finally:
        await feeder
        await session.close()


@pytest.mark.asyncio
async def test_home_advertised_audio_can_start_after_text_terminal():
    socket = _ready_socket(
        _event("message.complete", "home-turn-1", {}),
        _audio("start", "home-turn-1", sample_rate=24000, channels=1,
               sample_width=2, byte_order="little"),
        b"\x01\x00",
        _audio("end", "home-turn-1"),
    )
    session = _session(_FakeConnect([socket]))
    await session.connect()
    session._capabilities = session.capabilities | {"audio"}
    try:
        events = [event async for event in session.send_turn("TEST")]
        assert [event["type"] for event in events] == [
            "message_complete", "audio_start", "audio_chunk", "audio_end",
        ]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_home_unrelated_frames_do_not_extend_audio_deadline():
    socket = _ready_socket(
        _audio("start", "home-turn-1", sample_rate=24000, channels=1,
               sample_width=2, byte_order="little"),
        _event("message.complete", "home-turn-1", {}),
    )
    session = _session(_FakeConnect([socket]))
    session._request_timeout = 0.03
    await session.connect()
    async def chatter():
        for _ in range(20):
            await asyncio.sleep(0.01)
            socket.incoming.put_nowait(_notification("heartbeat", {}))
    feeder = asyncio.create_task(chatter())
    try:
        async with asyncio.timeout(0.15):
            events = [event async for event in session.send_turn("TEST")]
        assert events[-1]["text_completed"] is True
        assert "timed out" in events[-1]["error"]
    finally:
        feeder.cancel()
        await asyncio.gather(feeder, return_exceptions=True)
        await session.close()


@pytest.mark.asyncio
async def test_home_audio_wait_excludes_slow_consumer_processing():
    socket = _ready_socket(
        _audio("start", "home-turn-1", sample_rate=24000, channels=1,
               sample_width=2, byte_order="little"),
        _event("message.complete", "home-turn-1", {}),
        b"\x01\x00", b"\x02\x00", _audio("end", "home-turn-1"),
    )
    session = _session(_FakeConnect([socket]))
    session._request_timeout = 0.01
    await session.connect()
    events = []
    try:
        async for event in session.send_turn("TEST"):
            events.append(event)
            await asyncio.sleep(0.02)
        assert events[-1] == {"type": "audio_end"}
        assert session.is_connected()
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("session_type", [HomePuckSession, HomeBrowserSession], ids=["puck", "browser"])
async def test_home_text_completed_before_audio_disconnect_does_not_replay_or_reuse_tail(session_type):
    first = _ready_socket(
        _audio("start", "home-turn-1", sample_rate=24000, channels=1,
               sample_width=2, byte_order="little"),
        _event("message.delta", "home-turn-1", {"text": "Confirmed answer."}),
        _event("message.complete", "home-turn-1", {}),
        ConnectionError("audio transport dropped"),
    )
    class ResumedSocket(_FakeSocket):
        async def send(self, raw):
            request = json.loads(raw)
            if request["method"] != "conversation.reconnect":
                return await super().send(raw)
            self.sent.append(request)
            self.incoming.put_nowait(_reply(request["id"], {**READY, "unresolved_turn": {
                "schema": 1, "conversation_handle": "opaque-home-handle",
                "turn_id": "home-turn-1", "status": "submitted",
            }}))
            # Home's still-running worker can send a tail after attachment.
            self.incoming.put_nowait(b"\x02\x00")
            self.incoming.put_nowait(_audio("end", "home-turn-1"))
    resumed = ResumedSocket()
    fresh = _ready_socket(_event("message.complete", "home-turn-1", {}))
    session = session_type(
        f"wss://home.example{HOME_BRIDGE_PATH}", "device-secret", "opaque-home-handle",
        connect_factory=_FakeConnect([first, resumed, fresh]),
    )
    await session.connect()
    try:
        if session_type is HomeBrowserSession:
            events = []
            with pytest.raises(HomeBridgeTransportError):
                async for event in session.send_turn("TEST"):
                    events.append(event)
            assert not any(event["type"] == "turn_end" for event in events)
            assert not session.is_connected()
            assert resumed.sent == []
            assert sum(request["method"] == "prompt.submit" for request in first.sent) == 1
            return
        events = [event async for event in session.send_turn("TEST")]
        assert {"type": "text_delta", "text": "Confirmed answer."} in events
        assert any(event["type"] == "audio_end" for event in events)
        assert any(event.get("text_completed") is True for event in events)
        assert session.active_turn_id is None
        assert not session.is_connected()
        assert sum(request["method"] == "prompt.submit" for sock in (first, resumed) for request in sock.sent) == 1
        await session.connect()
        next_events = [event async for event in session.send_turn("TEST")]
        expected = ["message_complete"]
        assert [event["type"] for event in next_events] == expected
    finally:
        await session.close()


@pytest.mark.parametrize("status,code,rejected", [
    (401, "unauthorized", True), (401, "credential_revoked", True),
    (403, "forbidden", False), (403, "claim_denied", False),
    (409, "stale_mapping", False), (503, "service_unavailable", False),
    (401, "", False),
])
@pytest.mark.asyncio
async def test_home_denials_only_latch_confirmed_credential_rejection(
    tmp_path, status, code, rejected,
):
    path = tmp_path / "identity.json"
    state = HomeIdentityRejectionState("wss://home.example/api/v1/bridge/ws", "puck", "isolated", path)
    calls = []

    def request(*args, **kwargs):
        calls.append(args)
        raise HomeClaimHTTPError(status, code)

    factory = HomePuckSessionFactory(
        "wss://home.example/api/v1/bridge/ws", "isolated", "puck",
        identity_state=state, request_json=request,
    )
    with pytest.raises(HomeClaimHTTPError):
        await factory.current_mapping_id("Hey Missy", "missy")
    assert factory.identity_rejected is rejected
    assert state.is_rejected() is rejected
    restarted = HomePuckSessionFactory(
        "wss://home.example/api/v1/bridge/ws", "isolated", "puck",
        identity_state=state, request_json=request,
    )
    assert restarted.identity_rejected is rejected
    if rejected:
        result = await restarted.admit_wake("Hey Missy")
        assert result.status == "identity_rejected"
        assert len(calls) == 1
        raw = path.read_text()
        assert "isolated" not in raw and "home.example" not in raw and "puck" not in raw
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700


def test_home_rejection_scope_is_exact_and_malformed_state_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    original = HomeIdentityRejectionState("wss://home/api/v1/bridge/ws", "puck", "old")
    original.reject()
    assert original.is_rejected()
    for home, device, credential in [
        ("wss://other/api/v1/bridge/ws", "puck", "old"),
        ("wss://home/api/v1/bridge/ws", "other", "old"),
        ("wss://home/api/v1/bridge/ws", "puck", "renewed"),
    ]:
        assert not HomeIdentityRejectionState(home, device, credential).is_rejected()
    original.path.write_text("{}")
    with pytest.raises(ValueError, match="invalid"):
        original.is_rejected()


@pytest.mark.parametrize("status,code", [(401, "unauthorized"), (403, "claim_denied"), (403, "forbidden")])
def test_home_http_preserves_safe_contract_error_code(monkeypatch, status, code):
    import io
    import urllib.error

    def fail(_request, timeout):
        raise urllib.error.HTTPError(
            "https://isolated.invalid", status, "private", {},
            io.BytesIO(json.dumps({"schema": 1, "error": {"code": code, "message": "private"}}).encode()),
        )

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(HomeClaimHTTPError) as raised:
        _request_json("GET", "https://isolated.invalid", credential="test", payload=None, timeout=1)
    assert raised.value.status == status
    assert raised.value.code == code
    assert is_home_identity_rejection(raised.value) is (code == "unauthorized")
    assert "private" not in str(raised.value)


@pytest.mark.asyncio
async def test_home_unavailable_current_mapping_does_not_borrow_independent_mapping():
    configuration = {"schema": 1, "snapshot": {
        "revision": 5, "wake_mappings": [{"id": "other", "phrase": "Hey Other"}],
    }}
    factory = HomePuckSessionFactory(
        "wss://home.example/api/v1/bridge/ws", "isolated", "puck",
        request_json=lambda *args, **kwargs: configuration,
    )
    with pytest.raises(HomeMappingUnavailable):
        await factory.current_mapping_id("Hey Missy", "missy")
    assert not await factory.verify_mapping_id("missy", 5)
    assert await factory.verify_mapping_id("other", 5)
    assert await factory.current_mapping_id("Hey Other", "other") == "other"
    assert factory.identity_rejected is False


@pytest.mark.asyncio
async def test_home_same_id_profile_repoint_invalidates_old_claim_revision():
    # Device projection intentionally hides Profile IDs. A repoint publishes
    # a new revision even when the mapping ID and phrase are unchanged.
    configuration = {"schema": 1, "snapshot": {
        "revision": 11, "wake_mappings": [{"id": "missy", "phrase": "Hey Missy"}],
    }}
    factory = HomePuckSessionFactory(
        "wss://home/api/v1/bridge/ws", "isolated", "puck",
        request_json=lambda *a, **kw: configuration,
    )
    assert await factory.current_mapping_id("Hey Missy", "missy", configuration_revision=11) == "missy"
    configuration["snapshot"]["revision"] = 12
    with pytest.raises(HomeMappingUnavailable):
        await factory.current_mapping_id("Hey Missy", "missy", configuration_revision=11)
    assert not await factory.verify_mapping_id("missy", 11)
    assert not await factory.verify_mapping_id("missy")
    assert factory.identity_rejected is False


@pytest.mark.asyncio
async def test_independent_mapping_can_obtain_its_own_verified_claim_without_fallback(tmp_path):
    calls = []

    class Socket(_FakeSocket):
        async def send(self, raw):
            frame = json.loads(raw)
            self.sent.append(frame)
            handle = "other-profile-handle"
            if frame["method"] in {"conversation.open", "conversation.reconnect"}:
                self.incoming.put_nowait(_reply(frame["id"], {**READY, "conversation_handle": handle}))
            elif frame["method"] == "conversation.close":
                self.incoming.put_nowait(_reply(frame["id"], {
                    "conversation_handle": handle, "status": "closed",
                }))

    def request(method, url, *, credential, payload, timeout):
        calls.append((method, payload))
        if method == "GET":
            return {"schema": 1, "snapshot": {"revision": 4, "wake_mappings": [
                {"id": "other", "phrase": "Hey Other"},
            ]}}
        assert payload["wake_mapping_id"] == "other"
        return {"schema": 1, "claim_id": payload["claim_id"], "configuration_revision": 4,
                "decision": "granted", "conversation_handle": "other-profile-handle"}

    socket = Socket()
    factory = HomePuckSessionFactory(
        "wss://home/api/v1/bridge/ws", "isolated", "puck",
        request_json=request, connect_factory=_FakeConnect([socket]),
        evidence_provider=lambda _: CalibratedProximityEvidence(0.8, "isolated-trusted-fixture", int(time.time() * 1000)),
        identity_state=HomeIdentityRejectionState("wss://home/api/v1/bridge/ws", "puck", "isolated", tmp_path / "identity.json"),
    )
    denied = await factory.admit_wake("Hey Missy")
    assert denied.status == "denied" and not factory.identity_rejected
    assert [method for method, _ in calls] == ["GET"]
    granted = await factory.admit_wake("Hey Other")
    try:
        assert granted.status == "admitted"
        assert granted.session.wake_mapping_id == "other"
        assert granted.session.wake_configuration_revision == 4
        assert granted.session.is_connected()
        assert await factory.verify_mapping_id("other", 4)
        assert [frame["method"] for frame in socket.sent] == ["conversation.open"]
    finally:
        if granted.session is not None:
            await granted.session.close_claim()


@pytest.mark.asyncio
@pytest.mark.parametrize("credential_response", [200, 401, 403, 503])
async def test_bridge_unauthorized_does_not_revoke_a_valid_device_credential(
    tmp_path, credential_response,
):
    state = HomeIdentityRejectionState(
        "wss://home/api/v1/bridge/ws", "puck", "isolated", tmp_path / "refusal.json",
    )
    calls = []

    def request(*args, **kwargs):
        calls.append(args)
        if credential_response == 200:
            return {"schema": 1, "snapshot": {"revision": 1, "wake_mappings": []}}
        raise HomeClaimHTTPError(
            credential_response,
            {401: "unauthorized", 403: "forbidden", 503: "service_unavailable"}[credential_response],
        )

    factory = HomePuckSessionFactory(
        "wss://home/api/v1/bridge/ws", "isolated", "puck",
        identity_state=state, request_json=request,
    )
    error = HomeBridgeRPCError("conversation.open", "unauthorized", "known")
    assert await factory.confirm_identity_rejection(error) is (credential_response == 401)
    assert state.is_rejected() is (credential_response == 401)
    assert factory.identity_rejected is (credential_response == 401)
    assert len(calls) == 1
