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

from home_display.appliance import (
    ANSWER_REJECTED_STATUS,
    Appliance,
    _classify_prompt_request,
)
from puck_bridge.home_session import (
    HOME_BRIDGE_PATH,
    HomeBridgeProtocolError,
    HomeBrowserSession,
    HomePuckSession,
    _normalize_event,
    _standard_clarify,
)
from tests.test_home_appliance import FakeServer, _args, _wait_for
from tests.test_puck_home_session import (
    _event,
    _FakeConnect,
    _FakeSocket,
    _reply,
    _rpc_error,
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
    "multi_question_with_multi_select": _batch(_question("q0"), _question("q1", multi=True)),
    "multi_question_with_free_text": _batch(_question("q0"), _question("q1", choices=None)),
    "multi_question_duplicate_qid": _batch(_question("q0"), _question("q0", "Again?")),
    "multi_question_missing_qid": _batch(
        _question("q0"), {"question": "x", "choices": ["a"], "multi_select": False}
    ),
    "multi_question_empty_choice": _batch(_question("q0"), _question("q1", choices=("a", ""))),
    "multi_question_not_an_object": {"request_id": "f968a59f", "questions": [_question("q0"), "nope"]},
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
@pytest.mark.parametrize(
    "name",
    ["free_text", "multi_select"]
    + sorted(name for name in UNSUPPORTED_PAYLOADS if name.startswith("multi_question")),
)
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


# --- sequential multi-question single-select batches ----------------------


def _sequence(count=3, request_id="f968a59f"):
    return _batch(
        *[
            _question(f"q{index}", f"Question {index}?", (f"A{index}", f"B{index}"))
            for index in range(count)
        ],
        request_id=request_id,
    )


def _ok(*remaining, resolve=False, **extra):
    return {"result": {"status": "accepted", "remaining": list(remaining), **extra}, "resolve": resolve}


class _SequenceSocket(_FakeSocket):
    """Scripts one ``prompt.respond`` reply per answer; gates make one slow."""

    def __init__(
        self,
        *frames,
        steps,
        request_id="f968a59f",
        interrupt_event=("turn.interrupted", {"status": "interrupted"}),
    ) -> None:
        super().__init__(prompt_frames=list(frames))
        self.steps = list(steps)
        self.request_id = request_id
        self.interrupt_event = interrupt_event

    @property
    def responses(self):
        return [
            frame["params"]["response"]
            for frame in self.sent
            if frame["method"] == "prompt.respond"
        ]

    async def send(self, raw: str) -> None:
        import json

        payload = json.loads(raw)
        if payload["method"] == "session.interrupt":
            self.sent.append(payload)
            self.incoming.put_nowait(
                _reply(payload["id"], {"accepted": True, "status": "accepted"})
            )
            self.incoming.put_nowait(
                _event(self.interrupt_event[0], "home-turn-1", self.interrupt_event[1])
            )
            return
        if payload["method"] != "prompt.respond":
            await super().send(raw)
            return
        self.sent.append(payload)
        step = self.steps.pop(0)

        def deliver() -> None:
            if "error" in step:
                self.incoming.put_nowait(_rpc_error(payload["id"], step["error"]))
                return
            self.incoming.put_nowait(
                _reply(
                    payload["id"],
                    {"conversation_handle": "opaque-home-handle", **step["result"]},
                )
            )
            if step.get("resolve"):
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

        gate = step.get("gate")
        if gate is None:
            deliver()
            return

        async def wait_then_deliver() -> None:
            await gate.wait()
            deliver()

        asyncio.get_running_loop().create_task(wait_then_deliver())


def _option(prompt_or_event, label):
    options = (
        prompt_or_event["options"]
        if isinstance(prompt_or_event, dict)
        else prompt_or_event.options
    )
    if isinstance(prompt_or_event, dict):
        return next(option["id"] for option in options if option["label"] == label)
    return next(option.id for option in options if option.label == label)


def _body(context) -> str:
    prompt = context.publisher.snapshot.prompt
    return "" if prompt is None else prompt.body


async def _start_sequence(socket, count=3):
    session = _browser_session(socket)
    appliance, context = await _browser_context(session)
    turn = asyncio.create_task(context.handle_voice_turn("ask me something"))
    assert await _wait_for(lambda: _body(context) == "(1/%d) Question 0?" % count)
    return session, context, turn


async def _finish(session, context, turn):
    if not turn.done():
        turn.cancel()
    await asyncio.gather(turn, return_exceptions=True)
    await context.close()
    await session.close()


@pytest.mark.asyncio
async def test_session_offers_the_first_question_with_position_bound_option_ids():
    socket = _SequenceSocket(_clarify_frame(_sequence(3)), steps=[])
    session = _browser_session(socket)
    stream, event = await _first_prompt(session)
    try:
        assert event["type"] == "prompt_request"
        assert event["prompt_kind"] == "clarify"
        assert event["prompt_id"] == event["correlation_id"] == "f968a59f"
        assert event["question_id"] == "q0"
        assert event["text"] == "(1/3) Question 0?"
        assert event["options"] == [
            {"id": "1.1", "label": "A0"},
            {"id": "1.2", "label": "B0"},
        ]
        assert event["answers"] == {"1.1": "A0", "1.2": "B0"}
        assert [view["question_id"] for view in event["sequence"]["views"]] == [
            "q0",
            "q1",
            "q2",
        ]
        assert _classify_prompt_request(event).kind == "clarify"
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_session_answers_a_three_question_batch_once_each_in_order():
    socket = _SequenceSocket(
        _clarify_frame(_sequence(3)),
        steps=[_ok("q1", "q2"), _ok("q2"), _ok(resolve=True)],
    )
    session = _browser_session(socket)
    stream, event = await _first_prompt(session)
    try:
        for position, label in enumerate(("B0", "A1", "B2")):
            option_id = _option(event, label)
            assert option_id.startswith(f"{position + 1}.")
            assert await session.send_prompt_response(
                prompt_id="f968a59f", prompt_kind="clarify", option_id=option_id
            )
            outcome = session.take_clarify_outcome()
            assert outcome["accepted"] is True
            if position < 2:
                event = outcome["next"]
                assert event["question_id"] == f"q{position + 1}"
                assert event["text"] == f"({position + 2}/3) Question {position + 1}?"
                assert _classify_prompt_request(event) is not None
            else:
                assert outcome["next"] is None
        assert socket.responses == [
            {"answer": "B0", "question_id": "q0"},
            {"answer": "A1", "question_id": "q1"},
            {"answer": "B2", "question_id": "q2"},
        ]
        assert session.take_clarify_outcome() is None
        # Nothing is pending any more, so a repeat is not dispatched.
        assert not await session.send_prompt_response(
            prompt_id="f968a59f", prompt_kind="clarify", option_id="3.2"
        )
        assert len(socket.responses) == 3
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_an_answered_questions_option_id_cannot_answer_the_next_question():
    socket = _SequenceSocket(
        _clarify_frame(_sequence(2)), steps=[_ok("q1"), _ok(resolve=True)]
    )
    session = _browser_session(socket)
    stream, event = await _first_prompt(session)
    try:
        assert await session.send_prompt_response(
            prompt_id="f968a59f", prompt_kind="clarify", option_id="1.1"
        )
        # The same tap again, and the other first-question option, are both refused
        # even though question 2 is now pending under the same prompt id.
        for stale in ("1.1", "1.2", "A0", "Kitchen"):
            assert not await session.send_prompt_response(
                prompt_id="f968a59f", prompt_kind="clarify", option_id=stale
            )
        assert len(socket.responses) == 1
        assert await session.send_prompt_response(
            prompt_id="f968a59f", prompt_kind="clarify", option_id="2.2"
        )
        assert socket.responses == [
            {"answer": "A0", "question_id": "q0"},
            {"answer": "B1", "question_id": "q1"},
        ]
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_browser_walks_a_two_question_batch_to_idle():
    socket = _SequenceSocket(
        _clarify_frame(_sequence(2)), steps=[_ok("q1"), _ok(resolve=True)]
    )
    session, context, turn = await _start_sequence(socket, count=2)
    try:
        first = context.publisher.snapshot.prompt
        assert first.kind == "clarify"
        await context.handle_action(first.action_id, _option(first, "B0"))
        assert _body(context) == "(2/2) Question 1?"
        second = context.publisher.snapshot.prompt
        assert second.action_id == first.action_id
        assert {option.id for option in second.options}.isdisjoint(
            {option.id for option in first.options}
        )
        assert context.publisher.snapshot.state == "prompt"
        await context.handle_action(second.action_id, _option(second, "A1"))
        assert await asyncio.wait_for(turn, 2) is True
        assert socket.responses == [
            {"answer": "B0", "question_id": "q0"},
            {"answer": "A1", "question_id": "q1"},
        ]
        assert context.publisher.snapshot.prompt is None
    finally:
        await _finish(session, context, turn)


@pytest.mark.asyncio
async def test_browser_walks_a_three_question_batch_with_exactly_one_answer_each():
    socket = _SequenceSocket(
        _clarify_frame(_sequence(3)),
        steps=[_ok("q1", "q2"), _ok("q2"), _ok(resolve=True)],
    )
    session, context, turn = await _start_sequence(socket)
    try:
        prompt = context.publisher.snapshot.prompt
        tap = _option(prompt, "A0")
        # A double tap on question 1 dispatches once; the second finds the
        # session already on question 2 and its option id no longer matches.
        await asyncio.gather(
            context.handle_action(prompt.action_id, tap),
            context.handle_action(prompt.action_id, tap),
        )
        assert _body(context) == "(2/3) Question 1?"
        assert len(socket.responses) == 1
        # The first question's tap cannot answer question 2.
        await context.handle_action(prompt.action_id, tap)
        await context.handle_action(prompt.action_id, "1.2")
        assert len(socket.responses) == 1
        assert _body(context) == "(2/3) Question 1?"

        prompt = context.publisher.snapshot.prompt
        await context.handle_action(prompt.action_id, _option(prompt, "B1"))
        assert _body(context) == "(3/3) Question 2?"
        prompt = context.publisher.snapshot.prompt
        await context.handle_action(prompt.action_id, _option(prompt, "A2"))
        assert await asyncio.wait_for(turn, 2) is True
        assert socket.responses == [
            {"answer": "A0", "question_id": "q0"},
            {"answer": "B1", "question_id": "q1"},
            {"answer": "A2", "question_id": "q2"},
        ]
    finally:
        await _finish(session, context, turn)


@pytest.mark.asyncio
async def test_a_replacement_prompt_during_an_answer_is_not_overwritten():
    gate = asyncio.Event()
    socket = _SequenceSocket(
        _clarify_frame(_sequence(3)), steps=[{**_ok("q1", "q2"), "gate": gate}]
    )
    session, context, turn = await _start_sequence(socket)
    try:
        prompt = context.publisher.snapshot.prompt
        answer = asyncio.create_task(
            context.handle_action(prompt.action_id, _option(prompt, "A0"))
        )
        assert await _wait_for(lambda: len(socket.responses) == 1)
        socket.incoming.put_nowait(
            _clarify_frame(
                _batch(_question("r0", "Replacement?"), request_id="other-prompt")
            )
        )
        assert await _wait_for(lambda: _body(context) == "Replacement?")
        gate.set()
        await asyncio.wait_for(answer, 2)
        assert _body(context) == "Replacement?"
        assert context._child._pending_prompt_action_id == "other-prompt"
        assert session._pending_prompt["correlation_id"] == "other-prompt"
        assert len(socket.responses) == 1
    finally:
        await _finish(session, context, turn)


@pytest.mark.asyncio
async def test_a_prompt_resolved_during_an_answer_is_not_advanced():
    gate = asyncio.Event()
    socket = _SequenceSocket(
        _clarify_frame(_sequence(3)), steps=[{**_ok("q1", "q2"), "gate": gate}]
    )
    session, context, turn = await _start_sequence(socket)
    try:
        prompt = context.publisher.snapshot.prompt
        answer = asyncio.create_task(
            context.handle_action(prompt.action_id, _option(prompt, "A0"))
        )
        assert await _wait_for(lambda: len(socket.responses) == 1)
        socket.incoming.put_nowait(
            _event(
                "prompt_resolved",
                "home-turn-1",
                {"request_id": "f968a59f", "status": "expired"},
            )
        )
        assert await _wait_for(lambda: context._child._pending_prompt_action_id is None)
        gate.set()
        await asyncio.wait_for(answer, 2)
        assert _body(context) == "(1/3) Question 0?"
        assert context._child._pending_prompt_action_id is None
        assert session._pending_prompt is None
        assert len(socket.responses) == 1
    finally:
        await _finish(session, context, turn)


@pytest.mark.asyncio
async def test_a_disconnect_during_an_answer_never_advances_or_replays():
    gate = asyncio.Event()
    socket = _SequenceSocket(
        _clarify_frame(_sequence(3)), steps=[{**_ok("q1", "q2"), "gate": gate}]
    )
    session, context, turn = await _start_sequence(socket)
    try:
        prompt = context.publisher.snapshot.prompt
        answer = asyncio.create_task(
            context.handle_action(prompt.action_id, _option(prompt, "A0"))
        )
        assert await _wait_for(lambda: len(socket.responses) == 1)
        await context.close()
        gate.set()
        await asyncio.wait_for(answer, 2)
        assert "Question 1?" not in _body(context)
        assert session._pending_prompt is None
        assert not session.is_connected()
        assert len(socket.responses) == 1
    finally:
        await _finish(session, context, turn)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["rpc_error", "accepted_false"])
@pytest.mark.parametrize("ending", ["interrupted", "failed", "completed"])
async def test_a_rejected_answer_cancels_the_question_and_never_retries(failure, ending):
    step = (
        {"error": "request_rejected"}
        if failure == "rpc_error"
        else {"result": {"accepted": False, "status": "rejected"}}
    )
    endings = {
        "interrupted": ("turn.interrupted", {"status": "interrupted"}),
        "failed": ("turn.failed", {"status": "failed"}),
        "completed": ("turn.complete", {"status": "completed"}),
    }
    socket = _SequenceSocket(
        _clarify_frame(_sequence(3)),
        steps=[_ok("q1", "q2"), step],
        interrupt_event=endings[ending],
    )
    session, context, turn = await _start_sequence(socket)
    try:
        prompt = context.publisher.snapshot.prompt
        await context.handle_action(prompt.action_id, _option(prompt, "A0"))
        assert _body(context) == "(2/3) Question 1?"
        prompt = context.publisher.snapshot.prompt
        tap = _option(prompt, "B1")
        await context.handle_action(prompt.action_id, tap)
        # Home keeps a rejected batch pending, so the turn is interrupted, not
        # left waiting; the page says why however the turn then ends, and shows
        # no further question.
        assert await asyncio.wait_for(turn, 2) is False
        snapshot = context.publisher.snapshot
        assert snapshot.state == "error"
        assert snapshot.status_text == ANSWER_REJECTED_STATUS
        assert snapshot.prompt is None
        assert "session.interrupt" in [frame["method"] for frame in socket.sent]
        # No retry, by tap or by any other route.
        await context.handle_action(prompt.action_id, tap)
        assert not await session.send_prompt_response(
            prompt_id="f968a59f", prompt_kind="clarify", option_id=tap
        )
        assert socket.responses == [
            {"answer": "A0", "question_id": "q0"},
            {"answer": "B1", "question_id": "q1"},
        ]
        # The refusal does not leak into the next turn on this connection.
        socket.prompt_frames = [
            _event("turn.complete", "home-turn-1", {"status": "completed"})
        ]
        assert await asyncio.wait_for(context.handle_voice_turn("again"), 2) is True
        assert context.publisher.snapshot.state == "idle"
        assert context.publisher.snapshot.status_text is None
    finally:
        await _finish(session, context, turn)


@pytest.mark.asyncio
async def test_a_rejected_answer_that_cannot_be_interrupted_closes_the_connection():
    socket = _SequenceSocket(
        _clarify_frame(_sequence(2)), steps=[{"error": "request_rejected"}]
    )
    session, context, turn = await _start_sequence(socket, count=2)

    async def cannot_interrupt():
        return False

    session.interrupt_active_turn = cannot_interrupt
    try:
        prompt = context.publisher.snapshot.prompt
        await context.handle_action(prompt.action_id, _option(prompt, "A0"))
        assert context._closed
        await asyncio.wait_for(asyncio.gather(turn, return_exceptions=True), 2)
        assert context.publisher.snapshot.status_text == ANSWER_REJECTED_STATUS
        assert len(socket.responses) == 1
    finally:
        await _finish(session, context, turn)


@pytest.mark.asyncio
async def test_a_status_update_during_an_answer_does_not_lose_the_next_question():
    gate = asyncio.Event()
    socket = _SequenceSocket(
        _clarify_frame(_sequence(3)), steps=[{**_ok("q1", "q2"), "gate": gate}]
    )
    session, context, turn = await _start_sequence(socket)
    try:
        prompt = context.publisher.snapshot.prompt
        answer = asyncio.create_task(
            context.handle_action(prompt.action_id, _option(prompt, "A0"))
        )
        assert await _wait_for(lambda: len(socket.responses) == 1)
        socket.incoming.put_nowait(
            _event("status.update", "home-turn-1", {"text": "Still working"})
        )
        assert await _wait_for(lambda: context.publisher.snapshot.prompt is None)
        gate.set()
        await asyncio.wait_for(answer, 2)
        assert _body(context) == "(2/3) Question 1?"
        assert context._child._pending_prompt_action_id == "f968a59f"
    finally:
        await _finish(session, context, turn)


@pytest.mark.asyncio
async def test_the_last_answer_completes_when_home_reports_nothing_remaining():
    # Home treats an absent `remaining` as nothing left (standard.py
    # _has_remaining_prompt_questions), so the last answer may omit it.
    socket = _SequenceSocket(
        _clarify_frame(_sequence(2)),
        steps=[_ok("q1"), {"result": {"status": "accepted"}, "resolve": True}],
    )
    session, context, turn = await _start_sequence(socket, count=2)
    try:
        prompt = context.publisher.snapshot.prompt
        await context.handle_action(prompt.action_id, _option(prompt, "A0"))
        prompt = context.publisher.snapshot.prompt
        await context.handle_action(prompt.action_id, _option(prompt, "B1"))
        assert await asyncio.wait_for(turn, 2) is True
        assert context.publisher.snapshot.prompt is None
    finally:
        await _finish(session, context, turn)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remaining",
    [
        pytest.param(None, id="missing"),
        pytest.param([], id="empty_with_questions_left"),
        pytest.param(["q1"], id="short"),
        pytest.param(["q1", "q2", "q9"], id="extra"),
        pytest.param(["q2", "q1"], id="reordered"),
        pytest.param(["q0", "q1", "q2"], id="repeats_the_answered_question"),
        pytest.param("q1", id="not_a_list"),
        pytest.param([1, 2], id="not_ids"),
    ],
)
async def test_unexpected_remaining_closes_without_asking_another_question(remaining):
    result = {"status": "accepted"}
    if remaining is not None:
        result["remaining"] = remaining
    socket = _SequenceSocket(
        _clarify_frame(_sequence(3)), steps=[{"result": result}, _ok("q2")]
    )
    session, context, turn = await _start_sequence(socket)
    try:
        prompt = context.publisher.snapshot.prompt
        await context.handle_action(prompt.action_id, _option(prompt, "A0"))
        assert await asyncio.wait_for(turn, 2) is False
        assert not session.is_connected()
        assert session._pending_prompt is None
        snapshot = context.publisher.snapshot
        assert snapshot.prompt is None
        assert snapshot.state == "disconnected"
        assert len(socket.responses) == 1
    finally:
        await _finish(session, context, turn)


@pytest.mark.asyncio
async def test_remaining_after_the_last_question_closes_the_session():
    socket = _SequenceSocket(
        _clarify_frame(_sequence(2)), steps=[_ok("q1"), _ok("q1")]
    )
    session = _browser_session(socket)
    stream, event = await _first_prompt(session)
    try:
        assert await session.send_prompt_response(
            prompt_id="f968a59f", prompt_kind="clarify", option_id="1.1"
        )
        with pytest.raises(HomeBridgeProtocolError):
            await session.send_prompt_response(
                prompt_id="f968a59f", prompt_kind="clarify", option_id="2.1"
            )
        assert not session.is_connected()
        assert session.take_clarify_outcome() is None
    finally:
        await stream.aclose()
        await session.close()


UNRENDERABLE_STEP = _batch(
    _question("q0"), _question("q1", choices=("x" * 300, "y")), _question("q2")
)


@pytest.mark.asyncio
async def test_a_sequence_with_an_unrenderable_step_is_refused_before_any_answer():
    socket = _SequenceSocket(_clarify_frame(UNRENDERABLE_STEP), steps=[])
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
        assert socket.responses == []
    finally:
        await _finish(session, context, turn)


def test_only_the_browser_session_offers_a_multi_question_batch():
    payload = _sequence(2)
    state = {"correlation_id": "f968a59f", "turn_id": "home-turn-1"}
    puck = _normalize_event("clarify.request", payload, dict(state))
    assert puck["unsupported"] is True
    assert puck["options"] == []
    assert "sequence" not in puck
    assert _standard_clarify(payload)["unsupported"] is True
    browser = _normalize_event(
        "clarify.request", payload, dict(state), sequential_clarify=True
    )
    assert browser["question_id"] == "q0"
    assert "unsupported" not in browser


def test_a_single_question_batch_is_normalized_exactly_as_before():
    state = {"correlation_id": "f968a59f", "turn_id": "home-turn-1"}
    payload = _batch(_question("q3"))
    plain = _normalize_event("clarify.request", payload, dict(state))
    browser = _normalize_event(
        "clarify.request", payload, dict(state), sequential_clarify=True
    )
    assert browser == plain
    assert plain == {
        "type": "prompt_request",
        "prompt_id": "f968a59f",
        "prompt_kind": "clarify",
        "turn_id": "home-turn-1",
        "text": "Which room?",
        "options": [{"id": "1", "label": "Kitchen"}, {"id": "2", "label": "Study"}],
        "sensitive": False,
        "timeout_s": 300,
        "question_id": "q3",
        "answers": {"1": "Kitchen", "2": "Study"},
        "correlation_id": "f968a59f",
    }
    assert _standard_clarify(payload, sequential=True) == _standard_clarify(payload)


@pytest.mark.asyncio
async def test_a_single_question_batch_ignores_remaining_and_records_no_outcome():
    socket = _SequenceSocket(
        _clarify_frame(_batch(_question("q3"))), steps=[_ok("q9", resolve=True)]
    )
    session, context, turn = await _start_sequence_single(socket)
    try:
        prompt = context.publisher.snapshot.prompt
        assert prompt.body == "Which room?"
        assert [option.id for option in prompt.options] == ["1", "2"]
        await context.handle_action(prompt.action_id, "2")
        assert socket.responses == [{"answer": "Study", "question_id": "q3"}]
        assert await asyncio.wait_for(turn, 2) is True
        assert session.take_clarify_outcome() is None
        assert context.publisher.snapshot.prompt is None
    finally:
        await _finish(session, context, turn)


async def _start_sequence_single(socket):
    session = _browser_session(socket)
    appliance, context = await _browser_context(session)
    turn = asyncio.create_task(context.handle_voice_turn("ask me something"))
    assert await _wait_for(lambda: _body(context) == "Which room?")
    return session, context, turn
