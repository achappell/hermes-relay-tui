"""Home browser turns survive Home's explicit audio fallback/unavailable frame.

Observed live (pinned Standard with no streaming TTS provider): Home forwards
``audio.frame`` ``fallback`` before any prompt. The browser must keep the text,
the prompt and the terminal event, report audio honestly, and stay fatal for
every other audio failure.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from home_display.appliance import Appliance
from home_display.home_admission import BrowserAdmission, BrowserSession
from puck_bridge.home_session import (
    HomeBridgeAudioError,
    HomeBrowserSession,
    HomePuckSession,
)
from tests.test_browser_home_admission import Client
from tests.test_home_appliance import (
    FakeServer,
    FakeSession,
    RecordingPublisher,
    _args,
    _wait_for,
)
from tests.test_home_clarify_browser import (
    URL,
    _ClarifySocket,
    _batch,
    _browser_session,
    _clarify_frame,
    _question,
)
from tests.test_puck_home_session import (
    _audio,
    _event,
    _FakeConnect,
    _ready_socket,
)

TURN = "home-turn-1"
START = dict(sample_rate=24000, channels=1, sample_width=2, byte_order="little")
UNAVAILABLE = "Audio unavailable"
CLARIFY = {
    "type": "prompt_request",
    "prompt_kind": "clarify",
    "prompt_id": "p1",
    "correlation_id": "p1",
    "text": "Which room?",
    "options": [{"id": "a", "label": "Kitchen"}],
}


async def _types(stream):
    return [event["type"] async for event in stream]


# --- the browser session --------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["fallback", "unavailable"])
async def test_fallback_before_text_keeps_the_prompt_and_terminal(kind):
    socket = _ClarifySocket(
        _audio(kind, TURN),
        _clarify_frame(_batch(_question(qid="q1"))),
    )
    session = _browser_session(socket)
    await session.connect()
    stream = session.send_turn("ask me something")
    try:
        first = await stream.__anext__()
        assert first == {
            "type": "audio_unavailable",
            "reason": "Home bridge response audio unavailable",
        }
        prompt = await stream.__anext__()
        assert prompt["type"] == "prompt_request"
        assert await session.send_prompt_response(
            prompt_id="f968a59f",
            prompt_kind="clarify",
            option_id=prompt["options"][0]["id"],
        )
        assert await _types(stream) == ["prompt_resolved", "turn_end"]
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_unavailable_after_pcm_drops_later_audio_and_keeps_text():
    socket = _ready_socket(
        _audio("start", TURN, **START),
        b"\x01\x00",
        _audio("unavailable", TURN),
        b"\x02\x00",
        _event("message.delta", TURN, {"rendered": "still text"}),
        _event("turn.complete", TURN, {"status": "completed"}),
    )
    session = _browser_session(socket)
    await session.connect()
    try:
        events = [event async for event in session.send_turn("TEST")]
        assert [event["type"] for event in events] == [
            "audio_start",
            "audio_chunk",
            "audio_unavailable",
            "text_delta",
            "turn_end",
        ]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_puck_session_still_reports_the_same_frame_as_audio_abort():
    socket = _ready_socket(
        _audio("fallback", TURN),
        _event("turn.complete", TURN, {"status": "completed"}),
    )
    session = HomePuckSession(
        URL, "device-secret", "opaque-home-handle", connect_factory=_FakeConnect([socket])
    )
    await session.connect()
    try:
        events = [event async for event in session.send_turn("TEST")]
        assert events == [
            {"type": "audio_abort", "error": "Home bridge response audio unavailable",
             "reason": "home_audio_fallback"}
        ]
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frames",
    [
        [_audio("start", TURN, **{**START, "channels": 2})],
        [_audio("end", TURN)],
        [_audio("start", TURN, **START), _audio("start", TURN, **START)],
        [b"\x00\x00"],
        [_audio("garbage", TURN)],
        [_audio("fallback", "another-turn")],
    ],
)
async def test_malformed_audio_frames_stay_fatal(frames):
    session = _browser_session(_ready_socket(*frames))
    await session.connect()
    try:
        with pytest.raises(HomeBridgeAudioError):
            _ = [event async for event in session.send_turn("TEST")]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_audio_completion_timeout_after_text_stays_audio_abort():
    socket = _ready_socket(
        _audio("start", TURN, **START),
        _event("message.complete", TURN, {}),
    )
    session = _browser_session(socket)
    session._request_timeout = 0.02
    await session.connect()
    try:
        events = [event async for event in session.send_turn("TEST")]
        abort = next(event for event in events if event["type"] == "audio_abort")
        assert abort["text_completed"] is True and "timed out" in abort["error"]
        assert not any(event["type"] == "audio_unavailable" for event in events)
    finally:
        await session.close()


# --- through browser admission (the observed failure) ---------------------


def _admission_factory(socket, **kwargs):
    connect = _FakeConnect([socket])

    def factory(_url, credential, _handle):
        return HomeBrowserSession(
            URL, credential, "opaque-home-handle", connect_factory=connect, **kwargs
        )

    return factory


@pytest.mark.asyncio
async def test_admission_delivers_prompt_and_terminal_after_a_fallback_frame():
    socket = _ClarifySocket(_audio("fallback", TURN), _clarify_frame(_batch(_question())))
    admission = BrowserAdmission(Client(), session_factory=_admission_factory(socket))
    await admission.refresh(force=True)
    session = BrowserSession(admission, "tab")
    await session.connect()
    stream = session.send_turn("ask me something")
    events = []
    try:
        async for event in stream:
            events.append(event)
            if event["type"] == "prompt_request":
                assert await session.send_prompt_response(
                    prompt_id=event["prompt_id"],
                    prompt_kind="clarify",
                    option_id=event["options"][0]["id"],
                )
        assert [event["type"] for event in events] == [
            "audio_unavailable",
            "prompt_request",
            "prompt_resolved",
            "turn_end",
        ]
        assert session.bridge is not None and session.claim_ref
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_admission_still_fails_closed_on_a_lost_audio_tail():
    socket = _ready_socket(
        _audio("start", TURN, **START),
        _event("message.complete", TURN, {}),
    )
    factory = _admission_factory(socket, request_timeout=0.02)
    admission = BrowserAdmission(Client(), session_factory=factory)
    await admission.refresh(force=True)
    session = BrowserSession(admission, "tab")
    await session.connect()
    try:
        events = [event async for event in session.send_turn("TEST")]
        assert events[-1]["type"] == "error"
        assert events[-1]["reason"] == "hermes_unavailable"
    finally:
        await session.close()


# --- the browser turn -----------------------------------------------------


@asynccontextmanager
async def _browser_turn_appliance(script):
    publisher = RecordingPublisher()
    server = FakeServer()
    session = FakeSession(script)
    appliance = Appliance(
        _args(browser_voice=True, wake_enabled=False),
        session=session,
        server=server,
        publisher=publisher,
    )
    task = asyncio.create_task(appliance.run())
    try:
        assert await _wait_for(lambda: appliance._connected)
        yield appliance, session, server, publisher
    finally:
        appliance._stopping.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


PCM = {"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2}


@pytest.mark.asyncio
async def test_unavailable_after_pcm_aborts_audio_once_and_completes_the_text():
    script = [
        PCM,
        {"type": "audio_chunk", "data": b"\x01\x02"},
        {"type": "audio_unavailable", "reason": "Home bridge response audio unavailable"},
        {"type": "audio_chunk", "data": b"\x03\x04"},
        {"type": "audio_start", **{k: v for k, v in PCM.items() if k != "type"}},
        {"type": "text_delta", "text": "Still the answer."},
        {"type": "audio_end", "final": True},
        {"type": "turn_end"},
    ]
    async with _browser_turn_appliance(script) as (appliance, _s, server, publisher):
        assert await appliance._on_browser_voice_turn("say it") is True
        assert [kind for kind, _ in server.audio] == ["start", "chunk", "abort"]
        assert publisher.history[-1] == ("idle", "Still the answer.", UNAVAILABLE)
        assert publisher.sequence.count("speaking") == 1


@pytest.mark.asyncio
async def test_fallback_before_audio_publishes_status_without_touching_the_stream():
    script = [
        {"type": "audio_unavailable", "reason": "x"},
        {"type": "text_delta", "text": "Plain answer."},
        {"type": "message_complete", "text": "Plain answer."},
        {"type": "turn_end"},
    ]
    async with _browser_turn_appliance(script) as (appliance, _s, server, publisher):
        assert await appliance._on_browser_voice_turn("say it") is True
        assert server.audio == []
        assert ("thinking", "", UNAVAILABLE) in publisher.history
        assert ("thinking", "Plain answer.", UNAVAILABLE) in publisher.history
        assert publisher.history[-1] == ("idle", "Plain answer.", UNAVAILABLE)


@pytest.mark.asyncio
async def test_prompt_after_a_fallback_is_shown_and_never_replaced():
    script = [
        {"type": "audio_unavailable", "reason": "x"},
        CLARIFY,
        {"type": "turn_end"},
    ]
    async with _browser_turn_appliance(script) as (appliance, _s, _server, publisher):
        assert await appliance._on_browser_voice_turn("ask") is True
        assert publisher.history[-1][0] == "prompt"
        assert appliance._pending_prompt_action_id == "p1"


@pytest.mark.asyncio
async def test_fallback_while_a_prompt_is_pending_does_not_republish_over_it():
    script = [CLARIFY, {"type": "audio_unavailable", "reason": "x"}, {"type": "turn_end"}]
    async with _browser_turn_appliance(script) as (appliance, _s, _server, publisher):
        assert await appliance._on_browser_voice_turn("ask") is True
        assert publisher.history[-1][0] == "prompt"
        assert all(entry[2] != UNAVAILABLE for entry in publisher.history)


@pytest.mark.asyncio
async def test_a_rejection_status_outranks_the_audio_notice():
    unsupported = {
        "type": "prompt_request",
        "prompt_kind": "choice",
        "prompt_id": "c1",
        "correlation_id": "c1",
        "text": "?",
        "options": [],
    }
    script = [{"type": "audio_unavailable", "reason": "x"}, unsupported, {"type": "turn_end"}]
    async with _browser_turn_appliance(script) as (appliance, _s, _server, publisher):
        assert await appliance._on_browser_voice_turn("ask") is False
        assert publisher.history[-1][0] == "error"
        assert publisher.history[-1][2] != UNAVAILABLE


@pytest.mark.asyncio
async def test_the_audio_notice_does_not_survive_into_the_next_turn():
    first = [
        {"type": "audio_unavailable", "reason": "x"},
        {"type": "text_delta", "text": "One."},
        {"type": "turn_end"},
    ]
    async with _browser_turn_appliance(first) as (appliance, session, _server, publisher):
        assert await appliance._on_browser_voice_turn("one") is True
        assert publisher.history[-1][2] == UNAVAILABLE
        mark = len(publisher.history)
        session.script = [{"type": "text_delta", "text": "Two."}, {"type": "turn_end"}]
        assert await appliance._on_browser_voice_turn("two") is True
        assert all(entry[2] != UNAVAILABLE for entry in publisher.history[mark:])
        assert publisher.history[-1] == ("idle", "Two.", None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal", [{"type": "audio_abort", "error": "lost"}, {"type": "error", "error": "boom"}]
)
async def test_other_audio_and_turn_failures_stay_fatal_in_the_browser(terminal):
    script = [{"type": "audio_unavailable", "reason": "x"}, terminal, {"type": "turn_end"}]
    async with _browser_turn_appliance(script) as (appliance, _s, _server, publisher):
        assert await appliance._on_browser_voice_turn("say it") is False
        assert publisher.history[-1][0] == "error"
