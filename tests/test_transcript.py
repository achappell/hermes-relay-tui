from rich.console import Console, Group
from rich.markdown import Markdown

from transcript import TranscriptBuffer


def rendered_text(buffer: TranscriptBuffer, *, show_details: bool = True) -> str:
    console = Console(record=True, width=100)
    console.print(buffer.render(show_details=show_details))
    return console.export_text()


def test_streaming_records_keep_roles_and_markdown_together():
    buffer = TranscriptBuffer()
    buffer.add("user", "Show me a useful answer")
    buffer.set_activity("[thinking…]", role="thinking")
    buffer.start_stream("assistant")
    buffer.append_stream("# Answer\n\n- first")
    buffer.append_stream("\n- second\n\n```python\nprint('ok')\n```")
    buffer.finish_stream()

    assert [(message.role, message.text) for message in buffer.messages] == [
        ("user", "Show me a useful answer"),
        ("thinking", "[thinking…]"),
        (
            "assistant",
            "# Answer\n\n- first\n- second\n\n```python\nprint('ok')\n```",
        ),
    ]
    assert buffer.plain_text.startswith("you> Show me a useful answer\n")
    assert "hermes: # Answer" in buffer.plain_text

    renderable = buffer.render()
    assert isinstance(renderable, Group)
    assert any(isinstance(item, Markdown) for item in renderable.renderables)
    output = rendered_text(buffer)
    assert "Answer" in output
    assert "print('ok')" in output


def test_user_message_newlines_survive_rendering():
    # Markdown treats a single "\n" as a soft break (renders as a space);
    # user-typed text (e.g. via Shift+Enter) must keep its literal line breaks.
    buffer = TranscriptBuffer()
    buffer.add("user", "test\ntenohut")

    output = rendered_text(buffer)
    lines = [line for line in output.splitlines() if line.strip()]
    assert lines == ["you>", "test", "tenohut"]
    assert "test tenohut" not in output


def test_activity_is_replaceable_and_can_be_hidden_without_losing_answer():
    buffer = TranscriptBuffer()
    buffer.set_activity("[thinking…]", role="thinking")
    buffer.set_activity("[tool: search — reading]", role="tool")
    buffer.start_stream("assistant")
    buffer.append_stream("The answer")
    buffer.finish_stream()

    assert [message.text for message in buffer.messages] == [
        "[tool: search — reading]",
        "The answer",
    ]
    assert "[tool: search — reading]" in rendered_text(buffer)
    hidden = rendered_text(buffer, show_details=False)
    assert "[tool: search — reading]" not in hidden
    assert "The answer" in hidden


def test_plain_text_for_matches_the_selected_detail_visibility():
    buffer = TranscriptBuffer()
    buffer.add("user", "visible prompt")
    buffer.add("thinking", "private reasoning", detail=True)
    buffer.add("assistant", "visible answer")

    assert buffer.plain_text_for(show_details=False) == (
        "you> visible prompt\nhermes: visible answer"
    )


def test_interleaved_activity_does_not_split_one_assistant_stream():
    buffer = TranscriptBuffer()
    buffer.start_stream("assistant")
    buffer.append_stream("first")
    buffer.add("status", "[still working]")
    buffer.append_stream(" second")
    buffer.finish_stream()

    assert [message.text for message in buffer.messages] == [
        "first second",
        "[still working]",
    ]
    assert [message.role for message in buffer.messages] == ["assistant", "status"]


def test_streaming_message_can_be_replaced_without_creating_a_duplicate():
    buffer = TranscriptBuffer()
    buffer.start_stream("assistant")
    buffer.append_stream("draft")
    buffer.replace_stream("final answer")
    buffer.finish_stream()

    assert [message.text for message in buffer.messages] == ["final answer"]
