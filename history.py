"""Persistent prompt history across TUI launches.

Entries are stored one JSON string per line so multi-line prompts survive
round-tripping without ambiguity. Corrupt lines are skipped rather than
failing the whole load.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from collections.abc import Iterable
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
    install this app only ever *reads* from (``--profile-env``).
    A laptop that talks to more than one Hermes
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


def _profile_slug(name: str) -> str:
    """Keep profile-derived paths inside the chosen artifact directory."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "default").strip().lower())
    return slug or "default"


def artifact_path_for_profile(
    base: Optional[Path],
    profile_name: str,
    *,
    legacy: bool = False,
) -> Optional[Path]:
    """Namespace one local artifact path for a named profile."""
    if base is None or legacy:
        return base
    path = Path(base).expanduser()
    return path.parent / "profiles" / _profile_slug(profile_name) / path.name


def history_path_for_profile(
    url: Optional[str],
    profile_name: str,
    *,
    configured_path: Optional[Path] = None,
    legacy: bool = False,
) -> Path:
    """Return prompt history isolated from every other named profile."""
    base = Path(configured_path).expanduser() if configured_path is not None else history_path_for_url(url)
    scoped = artifact_path_for_profile(base, profile_name, legacy=legacy)
    return Path(scoped) if scoped is not None else base


def legacy_history_path_for_profile(
    url: Optional[str],
    profile_name: str,
    *,
    configured_path: Optional[Path] = None,
) -> Path:
    """Return the unscoped history path used before profile namespacing."""
    del profile_name
    return history_path_for_profile(
        url,
        "default",
        configured_path=configured_path,
        legacy=True,
    )


class PromptHistory:
    """Ordered prompt history backed by a JSONL file, oldest first."""

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        legacy_paths: Optional[Iterable[Path]] = None,
    ) -> None:
        self.path = Path(path if path is not None else DEFAULT_HISTORY_PATH).expanduser()
        self._lock = threading.RLock()
        destination_exists = self.path.exists()
        self.entries: list[str] = self._load()
        if not destination_exists:
            self._migrate(legacy_paths)

    def _load(self) -> list[str]:
        """Load only non-empty JSON strings from the selected history file."""
        try:
            raw_lines = self.path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return []
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            # A read-only filesystem must not make otherwise readable history
            # unusable.
            pass
        return self._entries_from_lines(raw_lines)

    @staticmethod
    def _entries_from_lines(raw_lines: Iterable[str]) -> list[str]:
        """Decode JSONL without allowing arbitrary JSON values into history."""
        entries: list[str] = []
        seen: set[str] = set()
        for raw_line in raw_lines:
            line = raw_line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, str) or not value.strip():
                continue
            if value in seen:
                continue
            seen.add(value)
            entries.append(value)
        return entries[-MAX_HISTORY_ENTRIES:]

    @classmethod
    def _load_file(cls, path: Path) -> list[str]:
        try:
            raw_lines = Path(path).expanduser().read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return []
        return cls._entries_from_lines(raw_lines)

    def _migrate(self, legacy_paths: Optional[Iterable[Path]]) -> None:
        """Copy old prompt-only history without deleting or rewriting its source."""
        if not legacy_paths:
            return
        sources: list[Path] = []
        for candidate in legacy_paths:
            source = Path(candidate).expanduser()
            if source == self.path or source in sources:
                continue
            sources.append(source)

        migrated: list[str] = []
        seen: set[str] = set()
        for source in sources:
            for entry in self._load_file(source):
                if entry in seen:
                    continue
                seen.add(entry)
                migrated.append(entry)
        if not migrated:
            return

        self.entries = migrated[-MAX_HISTORY_ENTRIES:]
        self._save()

    def append(self, text: str) -> None:
        """Record a submitted prompt, skipping blanks and immediate repeats."""
        if not isinstance(text, str):
            return
        text = text.strip("\n")
        if not text.strip():
            return
        with self._lock:
            if self.entries and self.entries[-1] == text:
                return
            self.entries.append(text)
            if len(self.entries) > MAX_HISTORY_ENTRIES:
                self.entries = self.entries[-MAX_HISTORY_ENTRIES:]
            self._save()

    def _save(self) -> None:
        fd: Optional[int] = None
        temporary: Optional[str] = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
            )
            os.fchmod(fd, 0o600)
            handle = os.fdopen(fd, "w", encoding="utf-8")
            fd = None
            with handle:
                for entry in self.entries:
                    handle.write(json.dumps(entry) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
            os.chmod(self.path, 0o600)
        except OSError:
            # History is a convenience, never a reason to break a turn.
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            return
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


__all__ = [
    "DEFAULT_APP_DIR",
    "DEFAULT_HISTORY_DIR",
    "DEFAULT_HISTORY_PATH",
    "MAX_HISTORY_ENTRIES",
    "PromptHistory",
    "artifact_path_for_profile",
    "legacy_history_path_for_profile",
    "history_path_for_profile",
    "history_path_for_url",
]
