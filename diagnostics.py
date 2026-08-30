"""Opt-in, content-safe diagnostics for live Hermes sessions."""

from __future__ import annotations

import hashlib
import logging
import tempfile
from pathlib import Path
from typing import Any, Optional

LOGGER_NAME = "hermes_relay_tui"
DEFAULT_LOG_FILE = Path(tempfile.gettempdir()) / "hermes-relay-tui-debug.log"

logger = logging.getLogger(LOGGER_NAME)


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
    _clear_handlers()
    if not debug and log_file is None:
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
    return path
