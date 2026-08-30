import logging

from diagnostics import configure_logging, summarize_payload, summarize_text


def test_summarize_text_reports_shape_without_content():
    summary = summarize_text("The answer is here.")

    assert "len=19" in summary
    assert "sha256=" in summary
    assert "The answer" not in summary


def test_summarize_payload_reports_event_shape_without_content():
    summary = summarize_payload(
        {
            "type": "message.delta",
            "payload": {"text": "The answer", "rendered": "The answer"},
        }
    )

    assert "keys=payload,type" in summary
    assert "payload_keys=rendered,text" in summary
    assert "text_len=10" in summary
    assert "rendered_len=10" in summary
    assert "The answer" not in summary


def test_configure_logging_writes_a_debug_trace_without_response_content(tmp_path):
    path = tmp_path / "session.log"
    configure_logging(debug=True, log_file=path)
    try:
        logging.getLogger("hermes_streaming_tui.test").debug(
            "recv kind=%s %s", "message.delta", summarize_text("private response")
        )
    finally:
        configure_logging(debug=False)

    contents = path.read_text(encoding="utf-8")
    assert "message.delta" in contents
    assert "len=16" in contents
    assert "private response" not in contents
