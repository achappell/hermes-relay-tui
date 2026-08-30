"""Small, platform-native clipboard integration for transcript copying."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


class ClipboardError(RuntimeError):
    """Raised when no supported clipboard command can accept the text."""


_CLIPBOARD_COMMANDS = (
    ("pbcopy",),
    ("wl-copy",),
    ("xclip", "-selection", "clipboard"),
)


def find_clipboard_command() -> tuple[str, ...] | None:
    """Return the first available native clipboard command."""
    for command in _CLIPBOARD_COMMANDS:
        if shutil.which(command[0]):
            return command
    return None


async def copy_text(text: str) -> None:
    """Copy text through a native clipboard helper without blocking Textual."""
    command = find_clipboard_command()
    if command is None:
        raise ClipboardError(
            "no supported clipboard command found (pbcopy, wl-copy, or xclip)"
        )

    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate(text.encode("utf-8"))
    if process.returncode:
        detail = stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise ClipboardError(
            f"{Path(command[0]).name} exited with status {process.returncode}{suffix}"
        )
