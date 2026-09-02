import json
import logging

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


async def test_message_delta_without_rendered_preview_is_append_only():
    frames = [
        json.dumps({"type": "message.delta", "payload": {"text": "The answer "}}),
        json.dumps({"type": "message.delta", "payload": {"text": "is here."}}),
        json.dumps({"type": "message.complete", "payload": {"text": "The answer is here."}}),
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    assert [event["type"] for event in events] == [
        "text_delta",
        "text_delta",
        "message_complete",
        "turn_end",
    ]
    assert "".join(event["text"] for event in events if event["type"] == "text_delta") == "The answer is here."


async def test_send_turn_replaces_a_cumulative_preview_when_server_requests_replace():
    frames = [
        json.dumps({"type": "text_delta", "text": "draft"}),
        json.dumps({"type": "text_delta", "text": "final answer", "replace": True}),
        json.dumps({"type": "text_final", "text": "final answer"}),
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    assert events[0] == {"type": "text_delta", "text": "draft"}
    assert events[1] == {"type": "text_replace", "text": "final answer"}
    assert events[2]["type"] == "turn_end" or events[2]["type"] == "message_complete"
    assert [event["type"] for event in events] == ["text_delta", "text_replace", "turn_end"]


async def test_send_turn_replaces_a_nonprefix_terminal_text_update():
    frames = [
        json.dumps({"type": "text_delta", "text": "draft"}),
        json.dumps({"type": "text_final", "text": "final answer"}),
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    assert events == [
        {"type": "text_delta", "text": "draft"},
        {"type": "text_replace", "text": "final answer"},
        {"type": "turn_end", "turn_id": events[-1]["turn_id"]},
    ]


async def test_send_turn_logs_protocol_shapes_without_text_content(caplog):
    caplog.set_level(logging.DEBUG, logger="hermes_relay_tui")
    frames = [
        json.dumps({"type": "message.delta", "payload": {"text": "The answer"}}),
        json.dumps({"type": "message.complete", "payload": {"text": "The answer"}}),
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    [event async for event in send_turn(ws, session_id="s1", text="private prompt", stt_source="local")]

    messages = "\n".join(record.message for record in caplog.records)
    assert "kind=message.delta" in messages
    assert "kind=message.complete" in messages
    assert "text_len=10" in messages
    assert "private prompt" not in messages
    assert "The answer" not in messages


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


async def test_send_turn_yields_audio_end_and_file_fallback_frames():
    frames = [
        json.dumps({"type": "audio_start", "sample_rate": 24000}),
        b"pcm",
        json.dumps({"type": "audio_end"}),
        json.dumps(
            {
                "type": "audio_file_start",
                "filename": "reply.wav",
                "mime_type": "audio/wav",
            }
        ),
        b"RIFF...",
        json.dumps({"type": "audio_file_end"}),
        json.dumps({"type": "turn_end"}),
    ]

    events = await collect(frames)

    assert [event["type"] for event in events] == [
        "audio_start",
        "audio_chunk",
        "audio_end",
        "audio_file_start",
        "audio_file_chunk",
        "audio_file_end",
        "turn_end",
    ]
    assert events[3] == {
        "type": "audio_file_start",
        "filename": "reply.wav",
        "mime_type": "audio/wav",
    }
    assert events[4]["data"] == b"RIFF..."


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


async def test_message_complete_matching_a_plain_text_frame_is_not_repeated():
    events = await collect(
        [
            json.dumps({"type": "text", "text": "the complete answer"}),
            json.dumps({"type": "message.complete", "payload": {"text": "the complete answer"}}),
            json.dumps({"type": "turn_end"}),
        ]
    )

    assert events == [
        {"type": "text_delta", "text": "the complete answer"},
        {"type": "message_complete", "text": "the complete answer", "reasoning": "", "failure_reason": ""},
        {"type": "turn_end", "turn_id": events[-1]["turn_id"]},
    ]


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
    assert kinds == ["text_delta", "text_replace", "turn_end"]
    assert events[1] == {"type": "text_replace", "text": "the corrected answer"}


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


async def test_text_frame_after_streaming_yields_only_the_unseen_suffix():
    events = await collect(
        [
            json.dumps({"type": "text_delta", "text": "Yes. Every word"}),
            json.dumps({"type": "text", "text": "Yes. Every word."}),
            json.dumps({"type": "turn_end"}),
        ]
    )

    assert events == [
        {"type": "text_delta", "text": "Yes. Every word"},
        {"type": "text_delta", "text": "."},
        {"type": "turn_end", "turn_id": events[-1]["turn_id"]},
    ]


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


async def test_send_turn_surfaces_unknown_frame_kinds_for_diagnostics():
    events = await collect(
        [
            json.dumps({"type": "something_new", "text": "ignore me"}),
            json.dumps({"type": "turn_end"}),
        ]
    )

    assert events[0] == {
        "type": "unknown_event",
        "event_type": "something_new",
        "payload": {"type": "something_new", "text": "ignore me"},
    }
    assert events[-1] == {"type": "turn_end", "turn_id": events[-1]["turn_id"]}


async def test_send_turn_normalizes_gateway_activity_events():
    events = await collect(
        [
            json.dumps({"type": "message.start"}),
            json.dumps({"type": "thinking.delta", "payload": {"text": "plan"}}),
            json.dumps({"type": "status.update", "payload": {"kind": "working", "text": "thinking"}}),
            json.dumps({"type": "notification.show", "payload": {"level": "info", "text": "heads up"}}),
            json.dumps({"type": "tool.start", "payload": {"tool_id": "tool-1", "name": "search"}}),
            json.dumps({"type": "tool.progress", "payload": {"name": "search", "preview": "reading"}}),
            json.dumps({"type": "tool.complete", "payload": {"tool_id": "tool-1", "name": "search"}}),
            json.dumps({"type": "background.complete", "payload": {"task_id": "task-1", "text": "done"}}),
            json.dumps({"type": "message.complete", "payload": {"text": "answer"}}),
            json.dumps({"type": "turn_end"}),
        ]
    )

    assert [event["type"] for event in events] == [
        "message_start",
        "thinking_delta",
        "status",
        "notification",
        "tool_start",
        "tool_progress",
        "tool_complete",
        "background_complete",
        "text_delta",
        "message_complete",
        "turn_end",
    ]
    assert events[2] == {"type": "status", "text": "thinking", "kind": "working"}
    assert events[4]["tool_id"] == "tool-1"
    assert events[8] == {"type": "text_delta", "text": "answer"}
    assert events[9]["text"] == "answer"


async def test_send_turn_surfaces_completion_reasoning_when_no_delta_was_streamed():
    events = await collect(
        [
            json.dumps(
                {
                    "type": "message.complete",
                    "payload": {"text": "answer", "reasoning": "checked the relay"},
                }
            ),
            json.dumps({"type": "turn_end"}),
        ]
    )

    assert events[0] == {"type": "thinking_delta", "text": "checked the relay"}
    assert events[1] == {"type": "text_delta", "text": "answer"}
    assert events[2]["type"] == "message_complete"
    assert events[3]["type"] == "turn_end"


async def test_send_turn_uses_error_message_when_error_field_is_absent():
    events = await collect([json.dumps({"type": "error", "message": "gateway failed"})])

    assert events == [{"type": "error", "error": "gateway failed"}]


async def test_non_object_json_frame_yields_an_error_and_stops():
    ws = FakeWebSocket([json.dumps(["not", "an", "object"]), json.dumps({"type": "turn_end"})])

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    assert events == [{"type": "error", "error": "server sent a non-object JSON frame"}]
    # The generator stopped: the queued turn_end was never read.
    assert ws._frames == [json.dumps({"type": "turn_end"})]


# ---- multi-segment answers (TURN-03) ---------------------------------

# Captured from a live gateway on 2026-09-02. One turn carried three
# segments: 338, 83 and 268 characters, each with its own draft_id and its own
# terminal frame. The client kept 309 characters of it. The speaker said all
# 689, which is how the loss was noticed at all.


async def test_a_new_draft_id_continues_the_answer_instead_of_erasing_it():
    """The bug this exists to prevent.

    draft_id marks a *segment* of one answer, not a revision of it. Treating a
    boundary as a replacement silently deletes everything the relay has
    already said.
    """
    frames = [
        json.dumps({"type": "text_delta", "text": "First part.", "replace": True, "draft_id": 508}),
        json.dumps({"type": "text", "text": "First part."}),
        json.dumps({"type": "text_delta", "text": "Second part.", "replace": True, "draft_id": 510}),
        json.dumps({"type": "text_final", "text": "Second part."}),
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    rendered = _render(events)
    assert "First part." in rendered
    assert "Second part." in rendered
    assert rendered == "First part.\n\nSecond part."


async def test_three_segments_all_survive():
    frames = [
        json.dumps({"type": "text_delta", "text": "One.", "replace": True, "draft_id": 1}),
        json.dumps({"type": "text_delta", "text": "One. Two.", "replace": True, "draft_id": 1}),
        json.dumps({"type": "text", "text": "One. Two."}),
        json.dumps({"type": "text_delta", "text": "Three.", "replace": True, "draft_id": 2}),
        json.dumps({"type": "text", "text": "Three."}),
        json.dumps({"type": "text_delta", "text": "Four.", "replace": True, "draft_id": 3}),
        json.dumps({"type": "text_final", "text": "Four."}),
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    assert _render(events) == "One. Two.\n\nThree.\n\nFour."


async def test_a_segment_boundary_is_taken_from_draft_id_not_from_prefix_luck():
    """A segment that happens to begin with the previous one's text is still a
    new segment. Guessing from the prefix gets this wrong in the direction
    that loses words."""
    frames = [
        json.dumps({"type": "text_delta", "text": "Yes.", "replace": True, "draft_id": 1}),
        json.dumps({"type": "text", "text": "Yes."}),
        json.dumps({"type": "text_delta", "text": "Yes. And more.", "replace": True, "draft_id": 2}),
        json.dumps({"type": "text_final", "text": "Yes. And more."}),
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    assert _render(events) == "Yes.\n\nYes. And more."


async def test_a_revision_inside_one_segment_still_replaces():
    """The original behaviour must survive: within a single draft, a
    non-prefix preview is a genuine revision and replaces."""
    frames = [
        json.dumps({"type": "text_delta", "text": "draft", "draft_id": 7}),
        json.dumps({"type": "text_delta", "text": "final answer", "replace": True, "draft_id": 7}),
        json.dumps({"type": "text_final", "text": "final answer"}),
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    assert _render(events) == "final answer"


async def test_a_replacement_after_a_boundary_keeps_the_earlier_segment():
    """A revision inside segment two must not take segment one with it."""
    frames = [
        json.dumps({"type": "text_delta", "text": "Kept.", "replace": True, "draft_id": 1}),
        json.dumps({"type": "text", "text": "Kept."}),
        json.dumps({"type": "text_delta", "text": "rough", "replace": True, "draft_id": 2}),
        json.dumps({"type": "text_delta", "text": "polished", "replace": True, "draft_id": 2}),
        json.dumps({"type": "text_final", "text": "polished"}),
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    assert _render(events) == "Kept.\n\npolished"


async def test_turns_without_draft_ids_are_unchanged():
    """Not every gateway sends draft_id. Absent it, nothing about the existing
    append-and-revise behaviour may change."""
    frames = [
        json.dumps({"type": "text_delta", "text": "Hello"}),
        json.dumps({"type": "text_delta", "text": "Hello world"}),
        json.dumps({"type": "text_final", "text": "Hello world"}),
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    assert _render(events) == "Hello world"


def _render(events) -> str:
    """Apply the emitted updates the way the transcript does."""
    text = ""
    for event in events:
        if event["type"] == "text_delta":
            text += event["text"]
        elif event["type"] == "text_replace":
            text = event["text"]
    return text


async def test_the_captured_live_turn_keeps_every_segment():
    """Replayed from the real trace that exposed this: turn 9066a53f,
    2026-09-02 17:51:29, against the live gateway.

    Three segments — 338, 83 and 268 characters, finalised at 309 — arrived as
    one answer and were spoken in full. The client rendered 309 of them, which
    is why it read as "the second half of what was actually said".
    """
    spec = [
        (508, [8, 60, 74, 149, 198, 255, 321, 338], ("text", 338)),
        (510, [41, 72, 83], ("text", 83)),
        (512, [11, 41, 114, 125, 199, 244, 260, 268], ("text_final", 309)),
    ]
    frames = []
    for draft, lengths, (final_kind, final_length) in spec:
        for length in lengths:
            frames.append(
                json.dumps(
                    {
                        "type": "text_delta",
                        "text": "x" * length,
                        "replace": True,
                        "draft_id": draft,
                    }
                )
            )
        frames.append(json.dumps({"type": final_kind, "text": "x" * final_length}))
    frames.append(json.dumps({"type": "turn_end"}))
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    rendered = _render(events)
    assert rendered.count("\n\n") == 2, "each segment boundary is one break"
    assert len(rendered) == 338 + 83 + 309 + 4, "every spoken character survives"
