from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

DisplayState = Literal[
    "idle", "listening", "thinking", "speaking", "buffering", "error", "disconnected"
]
_STATES = frozenset(DisplayState.__args__)


@dataclass(frozen=True, slots=True)
class DisplaySnapshot:
    schema: int = 1
    sequence: int = 0
    state: DisplayState = "idle"
    response_text: str = ""
    status_text: str | None = None
    media: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if type(self.schema) is not int or self.schema != 1:
            raise ValueError("schema must be 1")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if self.state not in _STATES:
            raise ValueError("state must be a known display state")
        if not isinstance(self.response_text, str):
            raise TypeError("response_text must be a string")
        if self.status_text is not None and not isinstance(self.status_text, str):
            raise TypeError("status_text must be a string or None")
        if self.media is not None and not isinstance(self.media, dict):
            raise TypeError("media must be a dict or None")
        if self.media is not None:
            try:
                json.dumps(self.media, allow_nan=False)
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError("media must be JSON serializable") from error

    def to_dict(self) -> dict[str, object]:
        return {
            "type": "snapshot",
            "schema": self.schema,
            "sequence": self.sequence,
            "state": self.state,
            "response_text": self.response_text,
            "status_text": self.status_text,
            "media": self.media,
        }


class DisplayStatePublisher:
    def __init__(self) -> None:
        self._snapshot = DisplaySnapshot()
        self._subscribers: set[asyncio.Queue[DisplaySnapshot]] = set()

    @property
    def snapshot(self) -> DisplaySnapshot:
        return self._snapshot

    def publish(
        self,
        *,
        state: DisplayState,
        response_text: str = "",
        status_text: str | None = None,
        media: dict[str, object] | None = None,
    ) -> DisplaySnapshot:
        snapshot = DisplaySnapshot(
            sequence=self._snapshot.sequence + 1,
            state=state,
            response_text=response_text,
            status_text=status_text,
            media=media,
        )
        self._snapshot = snapshot
        for queue in tuple(self._subscribers):
            if not queue.empty():
                queue.get_nowait()
            queue.put_nowait(snapshot)
        return snapshot

    async def _subscribe(self, queue: asyncio.Queue[DisplaySnapshot]) -> AsyncIterator[DisplaySnapshot]:
        self._subscribers.add(queue)
        try:
            yield self._snapshot
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

    def subscribe(self) -> AsyncIterator[DisplaySnapshot]:
        return self._subscribe(asyncio.Queue(maxsize=1))
