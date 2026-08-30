"""Local attachment metadata and path handling for the TUI."""

from __future__ import annotations

import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_INLINE_REFERENCE = re.compile(r"(?<!\S)@(?P<path>\S+)")
_FINAL_REFERENCE = re.compile(r"(?<!\S)(?P<token>@(?P<path>\S*))$")


@dataclass(frozen=True)
class Attachment:
    """Metadata for a local file prepared as an attachment."""

    path: Path
    filename: str
    mime_type: str
    size_bytes: int


class AttachmentError(ValueError):
    """Raised when a local attachment cannot be prepared."""


def resolve_attachment(
    raw_path: str,
    *,
    cwd: Optional[Path] = None,
    image_only: bool = False,
) -> Attachment:
    """Resolve a local readable file and return metadata without reading it."""
    if not raw_path or "\x00" in raw_path:
        raise AttachmentError("attachment path is empty or contains a NUL byte")

    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (cwd or Path.cwd()) / candidate
    try:
        path = candidate.resolve(strict=False)
    except OSError as exc:
        raise AttachmentError(f"cannot resolve attachment {raw_path!r}: {exc}") from exc

    if not path.exists():
        raise AttachmentError(f"attachment not found: {raw_path}")
    if not path.is_file():
        raise AttachmentError(f"attachment is not a regular file: {raw_path}")
    if not os.access(path, os.R_OK):
        raise AttachmentError(f"attachment is not readable: {raw_path}")

    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if image_only and not mime_type.startswith("image/"):
        raise AttachmentError(f"attachment is not an image: {raw_path}")
    try:
        size_bytes = path.stat().st_size
    except OSError as exc:
        raise AttachmentError(f"cannot inspect attachment {raw_path!r}: {exc}") from exc
    return Attachment(path, path.name, mime_type, size_bytes)


def _is_explicit_path(raw_path: str, *, cwd: Path) -> bool:
    """Distinguish a path-shaped reference from an ordinary @mention."""
    if raw_path.startswith(("/", "./", "../", "~/")) or "/" in raw_path:
        return True
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    return candidate.exists()


def find_inline_attachments(
    text: str,
    *,
    cwd: Optional[Path] = None,
) -> tuple[Attachment, ...]:
    """Find explicit local ``@path`` references in ordinary prompt text."""
    base = (cwd or Path.cwd()).resolve()
    found: list[Attachment] = []
    seen: set[Path] = set()
    for match in _INLINE_REFERENCE.finditer(text):
        raw_path = match.group("path")
        if not _is_explicit_path(raw_path, cwd=base):
            continue
        attachment = resolve_attachment(raw_path, cwd=base)
        if attachment.path in seen:
            continue
        seen.add(attachment.path)
        found.append(attachment)
    return tuple(found)


def _display_path(path: Path, *, raw_path: str, cwd: Path) -> str:
    if raw_path.startswith("~/"):
        try:
            return "~/" + str(path.relative_to(Path.home()))
        except ValueError:
            return str(path)
    if Path(raw_path).is_absolute():
        return str(path)
    try:
        return str(path.relative_to(cwd))
    except ValueError:
        return str(path)


def complete_path_reference(
    text: str,
    *,
    cwd: Optional[Path] = None,
) -> list[str]:
    """Return full-text replacements for the final local ``@path`` token."""
    match = _FINAL_REFERENCE.search(text)
    if match is None:
        return []
    raw_path = match.group("path")
    base = (cwd or Path.cwd()).resolve()
    expanded = Path(raw_path).expanduser()
    if not expanded.is_absolute():
        expanded = base / expanded
    if raw_path.endswith("/"):
        directory = expanded
        prefix = ""
    else:
        directory = expanded.parent
        prefix = expanded.name
    if not directory.is_dir():
        return []
    candidates = sorted(
        candidate
        for candidate in directory.iterdir()
        if candidate.name.startswith(prefix)
    )
    replacements = []
    for candidate in candidates:
        rendered = _display_path(candidate, raw_path=raw_path, cwd=base)
        if candidate.is_dir():
            rendered += "/"
        replacements.append(text[: match.start("token")] + "@" + rendered)
    return replacements


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KiB"
    return f"{size_bytes / (1024 * 1024):.1f} MiB"


def format_attachment_preview(attachment: Attachment) -> str:
    """Render attachment metadata without opening the file."""
    return (
        f"{attachment.filename} — {attachment.mime_type}, "
        f"{_format_size(attachment.size_bytes)} ({attachment.path})"
    )


__all__ = [
    "Attachment",
    "AttachmentError",
    "complete_path_reference",
    "find_inline_attachments",
    "format_attachment_preview",
    "resolve_attachment",
]
