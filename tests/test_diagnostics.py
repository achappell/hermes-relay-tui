import logging
import stat
import sys
import threading

import diagnostics
from diagnostics import (
    active_log_file,
    configure_logging,
    install_crash_logging,
    summarize_payload,
    summarize_text,
)


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
        logging.getLogger("hermes_relay_tui.test").debug(
            "recv kind=%s %s", "message.delta", summarize_text("private response")
        )
    finally:
        configure_logging(debug=False)

    contents = path.read_text(encoding="utf-8")
    assert "message.delta" in contents
    assert "len=16" in contents
    assert "private response" not in contents


def test_active_log_file_tracks_the_local_debug_log(tmp_path):
    path = tmp_path / "session.log"
    configure_logging(debug=True, log_file=path)
    try:
        assert active_log_file() == path
    finally:
        configure_logging(debug=False)

    assert active_log_file() is None


def test_install_crash_logging_records_a_private_safe_traceback(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "crash.log"
    monkeypatch.setattr(sys, "excepthook", lambda *args: None)
    monkeypatch.setattr(threading, "excepthook", lambda args: None)

    install_crash_logging(path)
    try:
        raise RuntimeError("private prompt bearer SECRET-TOKEN")
    except RuntimeError as exc:
        sys.excepthook(type(exc), exc, exc.__traceback__)

    contents = path.read_text(encoding="utf-8")
    assert "RuntimeError" in contents
    assert "test_install_crash_logging_records_a_private_safe_traceback" in contents
    assert "private prompt" not in contents
    assert "SECRET-TOKEN" not in contents
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_install_crash_logging_records_uncaught_worker_exception(tmp_path, monkeypatch):
    path = tmp_path / "crash.log"
    monkeypatch.setattr(sys, "excepthook", lambda *args: None)
    monkeypatch.setattr(threading, "excepthook", lambda args: None)

    install_crash_logging(path)

    def crash_worker():
        raise RuntimeError("worker failure")

    worker = threading.Thread(
        target=crash_worker,
        name="crash-worker",
    )
    worker.start()
    worker.join()

    contents = path.read_text(encoding="utf-8")
    assert "exception: builtins.RuntimeError" in contents
    assert "thread: crash-worker" in contents
    assert "worker failure" not in contents


# ---- every module's trace actually reaches the file (HOME-10) ---------


def test_the_debug_trace_captures_the_wake_and_hands_free_modules(tmp_path):
    """The trace attaches its handler to the `hermes_relay_tui` logger.

    Modules that name their logger anything else inherit nothing and log into
    the void. `wake.py`, `handsfree.py` and `earcons.py` each used
    `getLogger(__name__)`, which for a top-level module is a bare name outside
    that tree — so the entire hands-free subsystem was invisible under
    --debug, and HOME-02, HOME-09 and HOME-10 were all diagnosed by ear.
    """
    import earcons
    import handsfree
    import wake

    path = tmp_path / "trace.log"
    diagnostics.configure_logging(debug=True, log_file=path)
    try:
        wake.logger.debug("wake-probe")
        handsfree.logger.debug("handsfree-probe")
        earcons.logger.debug("earcons-probe")
        for handler in diagnostics.logger.handlers:
            handler.flush()
        written = path.read_text(encoding="utf-8")
    finally:
        diagnostics.configure_logging(debug=False)

    assert "wake-probe" in written
    assert "handsfree-probe" in written
    assert "earcons-probe" in written


def test_every_traced_module_logs_inside_the_configured_namespace():
    """A guard against the next module quietly logging nowhere."""
    import client
    import earcons
    import handsfree
    import wake
    from home_display import appliance

    for module in (wake, handsfree, earcons, client, appliance):
        name = module.logger.name
        assert name == diagnostics.LOGGER_NAME or name.startswith(
            diagnostics.LOGGER_NAME + "."
        ), f"{module.__name__} logs to {name!r}, outside the debug trace"
