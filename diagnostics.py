"""Content-safe diagnostics and persistent crash reporting for Hermes sessions."""

from __future__ import annotations

import hashlib
import importlib.metadata
import logging
import os
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

LOGGER_NAME = "hermes_relay_tui"
DEFAULT_LOG_FILE = Path(tempfile.gettempdir()) / "hermes-relay-tui-debug.log"
DEFAULT_CRASH_LOG_FILE = Path.home() / ".hermes-relay-tui" / "crash.log"

logger = logging.getLogger(LOGGER_NAME)
_active_log_file: Optional[Path] = None
_crash_log_file: Optional[Path] = None
_previous_sys_excepthook: Optional[Callable[..., Any]] = None
_previous_threading_excepthook: Optional[Callable[..., Any]] = None


def summarize_text(value: Any) -> str:
    """Describe text without putting its contents into a debug log."""
    if value is None:
        return "none"
    if not isinstance(value, str):
        return f"type={type(value).__name__}"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"len={len(value)} sha256={digest}"


def summarize_bytes(value: Any) -> str:
    """Describe binary data without logging the data itself."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"bytes={len(value)} sha256={hashlib.sha256(bytes(value)).hexdigest()[:16]}"
    return f"type={type(value).__name__}"


def _keys(value: Any) -> str:
    if not isinstance(value, dict):
        return f"type={type(value).__name__}"
    return ",".join(sorted(str(key) for key in value)) or "-"


def summarize_payload(payload: Any) -> str:
    """Return safe shape and size metadata for a protocol frame."""
    if not isinstance(payload, dict):
        return f"frame={type(payload).__name__}"

    parts = [f"keys={_keys(payload)}"]
    nested = payload.get("payload")
    source = nested if isinstance(nested, dict) else payload
    if nested is not None:
        parts.append(f"payload_keys={_keys(nested)}")

    for field in ("text", "rendered", "reasoning", "failure_reason", "error", "message", "status"):
        if field in source:
            parts.append(f"{field}_{summarize_text(source[field])}")
    for field in ("replace", "draft_id"):
        if field in source:
            value = source[field]
            if isinstance(value, (bool, int, float)) or value is None:
                parts.append(f"{field}={value!r}")
            else:
                parts.append(f"{field}_{summarize_text(value)}")
    if "data" in source:
        parts.append(f"data_{summarize_bytes(source['data'])}")
    return " ".join(parts)


def _clear_handlers() -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def configure_logging(*, debug: bool, log_file: Optional[Path] = None) -> Optional[Path]:
    """Enable a private file trace when ``--debug`` is requested.

    The named logger is isolated from Textual's logging configuration. Calling
    this with ``debug=False`` also resets it, which keeps tests and embedded
    callers from retaining an old file handler.
    """
    global _active_log_file
    _clear_handlers()
    if not debug and log_file is None:
        _active_log_file = None
        logger.setLevel(logging.WARNING)
        logger.propagate = True
        return None

    path = Path(log_file) if log_file else DEFAULT_LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.info("debug logging enabled file=%s", path)
    _active_log_file = path
    return path


def active_log_file() -> Optional[Path]:
    """Return the currently configured debug log path, if logging is active."""
    return _active_log_file


def crash_log_file() -> Path:
    """Return the path used for the persistent crash report."""
    return _crash_log_file or DEFAULT_CRASH_LOG_FILE


def _package_version() -> str:
    try:
        return importlib.metadata.version("hermes-relay-tui")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _crash_report(
    exc_type: type[BaseException],
    traceback_object: Any,
    *,
    thread_name: Optional[str] = None,
) -> str:
    timestamp = datetime.now().astimezone().isoformat()
    lines = [
        f"--- crash {timestamp} ---",
        f"version: {_package_version()}",
        f"thread: {thread_name or threading.current_thread().name}",
        f"exception: {exc_type.__module__}.{exc_type.__qualname__}",
        "traceback:",
    ]
    for frame in traceback.extract_tb(traceback_object):
        lines.append(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}')
    lines.append("---")
    return "\n".join(lines) + "\n"


def _write_crash_report(
    exc_type: type[BaseException],
    traceback_object: Any,
    *,
    thread_name: Optional[str] = None,
) -> None:
    path = crash_log_file()
    try:
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(
                _crash_report(exc_type, traceback_object, thread_name=thread_name)
            )
    except BaseException:
        # A crash reporter must never turn one failure into another failure.
        return


def _handle_uncaught_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    traceback_object: Any,
) -> None:
    _write_crash_report(exc_type, traceback_object)
    if _previous_sys_excepthook is not None:
        _previous_sys_excepthook(exc_type, exc_value, traceback_object)


def _handle_uncaught_thread_exception(args: threading.ExceptHookArgs) -> None:
    _write_crash_report(
        args.exc_type,
        args.exc_traceback,
        thread_name=args.thread.name if args.thread is not None else None,
    )
    if _previous_threading_excepthook is not None:
        _previous_threading_excepthook(args)


def install_crash_logging(log_file: Optional[Path] = None) -> Path:
    """Install persistent, content-safe hooks for uncaught exceptions."""
    global _crash_log_file, _previous_sys_excepthook, _previous_threading_excepthook
    _crash_log_file = Path(log_file) if log_file else DEFAULT_CRASH_LOG_FILE
    if sys.excepthook is not _handle_uncaught_exception:
        _previous_sys_excepthook = sys.excepthook
    if threading.excepthook is not _handle_uncaught_thread_exception:
        _previous_threading_excepthook = threading.excepthook
    sys.excepthook = _handle_uncaught_exception
    threading.excepthook = _handle_uncaught_thread_exception
    return _crash_log_file
