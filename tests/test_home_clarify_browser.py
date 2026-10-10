"""Standard ``clarify.request`` through the Home session and the browser overlay.

The payload shapes below come from the pinned Standard Hermes as Home forwards
them (hermes-relay-home ``tests/test_standard_bridge.py`` and the 2026-09-16
live capture): a batch ``{request_id, questions:[{qid, question,
choices: null | [str], multi_select}]}``. Home answers a batch question only
with ``{answer, question_id}`` and releases the prompt when every ``qid`` has
been answered.
"""

from __future__ import annotations

import asyncio

import pytest

from home_display.appliance import Appliance, _classify_prompt_request
from puck_bridge.home_session import (
    HOME_BRIDGE_PATH,
    HomeBrowserSession,
    HomePuckSession,
)
from tests.test_home_appliance import FakeServer, _args, _wait_for
from tests.test_puck_home_session import (
    _event,
    _FakeConnect,
    _FakeSocket,
    _reply,
    _ready_socket,
)

URL = f"wss://home.example{HOME_BRIDGE_PATH}"
UNSUPPORTED_STATUS = "This prompt needs an input the browser cannot collect"


def _question(qid="q0", question="Which room?", choices=("Kitchen", "Study"), multi=False):
    return {
        "qid": qid,
        "question": question,
        "choices": None if choices is None else list(choices),
        "multi_select": multi,
    }


def _batch(*questions, request_id="f968a59f"):
    return {"request_id": request_id, "questions": list(questions)}


class _ClarifySocket(_FakeSocket):
    """Accepts ``prompt.respond`` and finishes the turn once it is resolved."""

    def __init__(self, *frames, request_id="f968a59f", reply=None) -> None:
        super().__init__(prompt_frames=list(frames))
        self.request_id = request_id
        self.reply = reply or {"status": "resolved"}

    async def send(self, raw: str) -> None:
        import json

        payload = json.loads(raw)
        if payload["method"] != "prompt.respond":
            await super().send(raw)
            return
        self.sent.append(payload)
        self.incoming.put_nowait(
            _reply(
                payload["id"],
                {"conversation_handle": "opaque-home-handle", **self.reply},
            )
        )
        self.incoming.put_nowait(
            _event(
                "prompt_resolved",
                "home-turn-1",
                {"request_id": self.request_id, "status": "resolved"},
            )
        )
        self.incoming.put_nowait(
            _event("turn.complete", "home-turn-1", {"status": "completed"})
        )


def _browser_session(socket) -> HomeBrowserSession:
    return HomeBrowserSession(
        URL,
        "device-secret",
        "opaque-home-handle",
        connect_factory=_FakeConnect([socket]),
    )


def _clarify_frame(payload):
    return _event("clarify.request", "home-turn-1", payload)


async def _first_prompt(session: HomeBrowserSession):
    await session.connect()
    stream = session.send_turn("ask me something")
    return stream, await stream.__anext__()


# --- normalisation -------------------------------------------------------


@pytest.mark.asyncio
async def test_single_choice_batch_clarify_becomes_a_plain_clarify_prompt():
    socket = _ClarifySocket(_clarify_frame(_batch(_question())))
    session = _browser_session(socket)
    stream, event = await _first_prompt(session)
    try:
        assert event["type"] == "prompt_request"
        assert event["prompt_kind"] == "clarify"
        assert event["prompt_id"] == event["correlation_id"] == "f968a59f"
        assert event["text"] == "Which room?"
        assert [option["label"] for option in event["options"]] == ["Kitchen", "Study"]
        # Clarify stays a plain prompt answer: no typed-choice object.
        assert not event.get("choice")

        prompt = _classify_prompt_request(event)
        assert prompt is not None
        assert prompt.kind == "clarify"
        assert prompt.choice is None
        assert prompt.body == "Which room?"
        assert [option.label for option in prompt.options] == ["Kitchen", "Study"]
        assert prompt.action_id == "f968a59f"
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_single_question_clarify_without_a_batch_renders_too():
    socket = _ClarifySocket(
        _clarify_frame(
            {"request_id": "single-1", "question": "Pick one", "choices": ["a", "b"]}
        ),
        request_id="single-1",
    )
    session = _browser_session(socket)
    stream, event = await _first_prompt(session)
    try:
        prompt = _classify_prompt_request(event)
        assert prompt is not None and prompt.kind == "clarify"
        assert prompt.body == "Pick one"
        assert [option.label for option in prompt.options] == ["a", "b"]

        assert await session.send_prompt_response(
            prompt_id="single-1",
            prompt_kind="clarify",
            option_id=prompt.options[1].id,
        )
        # A non-batch clarify has no question to name.
        assert socket.sent[-1]["params"]["response"] == {"answer": "b"}
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_legacy_text_and_options_clarify_is_unchanged():
    socket = _ClarifySocket(
        _clarify_frame(
            {
                "request_id": "legacy-1",
                "text": "Which one?",
                "options": [{"id": "x", "label": "Ex"}, {"id": "y", "label": "Why"}],
            }
        ),
        request_id="legacy-1",
    )
    session = _browser_session(socket)
    stream, event = await _first_prompt(session)
    try:
        assert event == {
            "type": "prompt_request",
            "prompt_id": "legacy-1",
            "prompt_kind": "clarify",
            "turn_id": "home-turn-1",
            "text": "Which one?",
            "options": [{"id": "x", "label": "Ex"}, {"id": "y", "label": "Why"}],
            "sensitive": False,
            "timeout_s": 300,
            "correlation_id": "legacy-1",
        }
        assert await session.send_prompt_response(
            prompt_id="legacy-1", prompt_kind="clarify", option_id="y"
        )
        assert socket.sent[-1]["params"]["response"] == {"answer": "y"}
    finally:
        await stream.aclose()
        await session.close()


# --- the answer ----------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_answer_carries_question_id_and_the_choice_text():
    socket = _ClarifySocket(
        _clarify_frame(_batch(_question(qid="q7", choices=("Kitchen", "Study"))))
    )
    session = _browser_session(socket)
    stream, event = await _first_prompt(session)
    try:
        study = next(o for o in event["options"] if o["label"] == "Study")
        assert await session.send_prompt_response(
            prompt_id="f968a59f", prompt_kind="clarify", option_id=study["id"]
        )
        assert socket.sent[-1]["method"] == "prompt.respond"
        assert socket.sent[-1]["params"] == {
            "conversation_handle": "opaque-home-handle",
            "turn_id": "home-turn-1",
            "correlation_id": "f968a59f",
            "event_type": "clarify.request",
            "response": {"answer": "Study", "question_id": "q7"},
        }
        assert [e["type"] async for e in stream] == ["prompt_resolved", "turn_end"]
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_batch_answer_rejects_an_option_the_prompt_never_offered():
    socket = _ClarifySocket(_clarify_frame(_batch(_question())))
    session = _browser_session(socket)
    stream, _event_ = await _first_prompt(session)
    try:
        assert not await session.send_prompt_response(
            prompt_id="f968a59f", prompt_kind="clarify", option_id="Kitchen-ish"
        )
        assert [frame["method"] for frame in socket.sent] == [
            "conversation.open",
            "prompt.submit",
        ]
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_free_text_batch_answer_carries_question_id():
    socket = _ClarifySocket(
        _clarify_frame(_batch(_question(qid="q0", question="What name?", choices=None)))
    )
    session = _browser_session(socket)
    stream, event = await _first_prompt(session)
    try:
        assert event["prompt_kind"] == "clarify"
        assert event["text"] == "What name?"
        assert event["options"] == []
        assert await session.send_prompt_response(
            prompt_id="f968a59f", prompt_kind="clarify", value="probe-file"
        )
        assert socket.sent[-1]["params"]["response"] == {
            "answer": "probe-file",
            "question_id": "q0",
        }
    finally:
        await stream.aclose()
        await session.close()


# --- unsupported shapes resolve visibly, never as an answerable prompt ----


UNSUPPORTED_PAYLOADS = {
    "multi_select": _batch(_question(multi=True)),
    "multi_question": _batch(_question("q0"), _question("q1", "And which floor?")),
    "empty_batch": {"request_id": "f968a59f", "questions": []},
    "questions_not_a_list": {"request_id": "f968a59f", "questions": "nope"},
    "question_not_an_object": {"request_id": "f968a59f", "questions": ["nope"]},
    "choice_not_text": _batch(_question(choices=("ok", 7))),
    "empty_choice": _batch(_question(choices=("ok", ""))),
    "missing_qid": _batch({"question": "x", "choices": ["a"], "multi_select": False}),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(UNSUPPORTED_PAYLOADS))
async def test_unsupported_batch_shapes_are_flagged_and_never_answerable(name):
    socket = _ClarifySocket(_clarify_frame(UNSUPPORTED_PAYLOADS[name]))
    session = _browser_session(socket)
    stream, event = await _first_prompt(session)
    try:
        # The session still surfaces the prompt so the front end can report it...
        assert event["type"] == "prompt_request"
        assert event["prompt_kind"] == "clarify"
        # ...but with nothing any front end could answer.
        assert event["unsupported"] is True
        assert event["options"] == []
        assert _classify_prompt_request(event) is None
        # And a guessed answer is refused locally rather than sent half-formed.
        assert not await session.send_prompt_response(
            prompt_id="f968a59f", prompt_kind="clarify", value="guess"
        )
        assert [frame["method"] for frame in socket.sent] == [
            "conversation.open",
            "prompt.submit",
        ]
    finally:
        await stream.aclose()
        await session.close()


# --- Puck and legacy gateway paths ----------------------------------------


@pytest.mark.asyncio
async def test_puck_session_still_refuses_a_standard_clarify():
    socket = _ready_socket(_clarify_frame(_batch(_question())))
    session = HomePuckSession(
        URL,
        "device-secret",
        "opaque-home-handle",
        connect_factory=_FakeConnect([socket]),
    )
    await session.connect()
    stream = session.send_turn("ask me")
    event = await stream.__anext__()
    await stream.aclose()
    assert event == {
        "type": "error",
        "error": "Home Puck does not support structured prompts",
    }
    await session.close()


def test_gateway_clarify_with_options_classifies_as_before():
    prompt = _classify_prompt_request(
        {
            "type": "prompt_request",
            "prompt_id": "gw-1",
            "prompt_kind": "clarify",
            "text": "Which?",
            "options": [{"id": "a", "label": "A"}],
        }
    )
    assert prompt is not None and prompt.kind == "clarify"
    assert [(o.id, o.label) for o in prompt.options] == [("a", "A")]
    assert prompt.action_id == "gw-1"


# --- through the browser appliance ----------------------------------------


async def _browser_context(session):
    appliance = Appliance(
        _args(browser_voice=True, browser_transport="home"),
        session_factory=lambda _profile: session,
    )
    context = await appliance._create_browser_context("clarify", FakeServer())
    return appliance, context


@pytest.mark.asyncio
async def test_browser_renders_a_standard_clarify_and_answers_with_question_id():
    socket = _ClarifySocket(
        _clarify_frame(_batch(_question(qid="q3", choices=("Kitchen", "Study"))))
    )
    session = _browser_session(socket)
    appliance, context = await _browser_context(session)
    turn = asyncio.create_task(context.handle_voice_turn("ask me something"))
    try:
        assert await _wait_for(lambda: context.publisher.snapshot.prompt is not None)
        snapshot = context.publisher.snapshot
        assert snapshot.state == "prompt"
        prompt = snapshot.prompt
        assert prompt.kind == "clarify"
        assert prompt.choice is None
        assert prompt.body == "Which room?"
        assert [option.label for option in prompt.options] == ["Kitchen", "Study"]

        study = next(option for option in prompt.options if option.label == "Study")
        await context.handle_action(prompt.action_id, study.id)
        assert socket.sent[-1]["params"]["response"] == {
            "answer": "Study",
            "question_id": "q3",
        }
        assert socket.sent[-1]["params"]["event_type"] == "clarify.request"
        assert await asyncio.wait_for(turn, 2) is True
        assert context.publisher.snapshot.prompt is None
    finally:
        if not turn.done():
            turn.cancel()
        await context.close()
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["free_text", "multi_select", "multi_question"])
async def test_browser_reports_an_unsupported_clarify_instead_of_waiting(name):
    # Free text is answerable in the terminal TUI, but the overlay has no
    # text input, so the browser reports it like the other shapes.
    payloads = {**UNSUPPORTED_PAYLOADS, "free_text": _batch(_question(choices=None))}
    socket = _ClarifySocket(_clarify_frame(payloads[name]))
    session = _browser_session(socket)
    appliance, context = await _browser_context(session)
    interrupted = []

    async def interrupt():
        interrupted.append(True)
        return True

    session.interrupt_active_turn = interrupt
    turn = asyncio.create_task(context.handle_voice_turn("ask me something"))
    try:
        assert await _wait_for(lambda: bool(interrupted) or turn.done())
        snapshot = context.publisher.snapshot
        assert snapshot.prompt is None
        assert snapshot.state == "error"
        assert snapshot.status_text == UNSUPPORTED_STATUS
        assert interrupted == [True]
    finally:
        if not turn.done():
            turn.cancel()
        await context.close()
        await session.close()
