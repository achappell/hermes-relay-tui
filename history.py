"""Persistent prompt history across TUI launches.

Entries are stored one JSON string per line so multi-line prompts survive
round-tripping without ambiguity. Corrupt lines are skipped rather than
failing the whole load.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

DEFAULT_APP_DIR = Path.home() / ".hermes-relay-tui"
DEFAULT_HISTORY_PATH = DEFAULT_APP_DIR / "history.jsonl"
DEFAULT_HISTORY_DIR = DEFAULT_APP_DIR / "history"
MAX_HISTORY_ENTRIES = 500


def history_path_for_url(url: Optional[str]) -> Path:
    """Scope the default history file to the connection endpoint's host.

    Prompt history is this client's own state, not Hermes's — it lives
    under this app's own dotfolder (``~/.hermes-relay-tui/``), not
    inside ``~/.hermes/``, which belongs to the actual Hermes agent
    install this app only ever *reads* from (``--checkout``,
    ``--profile-env``). A laptop that talks to more than one Hermes
    backend (a local agent, a media-server gateway) should also not
    interleave their prompts in one file. Falls back to the flat
    ``DEFAULT_HISTORY_PATH`` when the URL has no parseable host, e.g.
    tests or callers that never configured one.
    """
    host = urlsplit(url).hostname if url else None
    if not host:
        return DEFAULT_HISTORY_PATH
    port = urlsplit(url).port
    slug = re.sub(r"[^A-Za-z0-9.-]+", "_", host)
    if port:
        slug = f"{slug}_{port}"
    return DEFAULT_HISTORY_DIR / f"{slug}.jsonl"


class PromptHistory:
    """Ordered prompt history backed by a JSONL file, oldest first."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path if path is not None else DEFAULT_HISTORY_PATH
        self.entries: list[str] = self._load()

    def _load(self) -> list[str]:
        try:
            raw_lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        entries: list[str] = []
        for raw_line in raw_lines:
            line = raw_line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries[-MAX_HISTORY_ENTRIES:]

    def append(self, text: str) -> None:
        """Record a submitted prompt, skipping blanks and immediate repeats."""
        text = text.strip("\n")
        if not text.strip():
            return
        if self.entries and self.entries[-1] == text:
            return
        self.entries.append(text)
        if len(self.entries) > MAX_HISTORY_ENTRIES:
            self.entries = self.entries[-MAX_HISTORY_ENTRIES:]
        self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as handle:
                for entry in self.entries:
                    handle.write(json.dumps(entry) + "\n")
        except OSError:
            pass


__all__ = [
    "DEFAULT_APP_DIR",
    "DEFAULT_HISTORY_DIR",
    "DEFAULT_HISTORY_PATH",
    "MAX_HISTORY_ENTRIES",
    "PromptHistory",
    "history_path_for_url",
]
