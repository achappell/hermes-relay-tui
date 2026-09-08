from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

DisplayState = Literal[
    "idle",
    "heard",
    "listening",
    "thinking",
    "speaking",
    "buffering",
    "error",
    "disconnected",
    "prompt",
]
_STATES = frozenset(DisplayState.__args__)
DisplayActionName = Literal["prompt.choose", "prompt.dismiss"]


@dataclass(frozen=True, slots=True)
class PromptOption:
    """One selectable option in an interactive display prompt."""

    id: str
    label: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("PromptOption.id must be a non-empty string")
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("PromptOption.label must be a non-empty string")

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "label": self.label}


@dataclass(frozen=True, slots=True)
class DisplayPrompt:
    """Payload for the 'prompt' display state — an interactive overlay.

    The display renders title + body + one button per option. On tap it
    POSTs {action_id, choice} to the display server's /action endpoint.
    The appliance dispatches based on (kind, action_id, choice).

    kind    -- a string token the appliance uses to route the response
               e.g. "notice", "approval", "confirm", "clarify"
    title   -- short heading shown at the top of the overlay
    body    -- one or two sentences explaining what is being asked
    options -- ordered list of selectable options (at least one)
    action_id -- opaque token that correlates the POST /action back to the
                 pending gateway operation or appliance decision
    timeout_seconds -- if not None, the overlay auto-dismisses after this
                       many seconds, choosing the first option's id
    """

    kind: str
    title: str
    body: str
    options: tuple[PromptOption, ...]
    action_id: str
    timeout_seconds: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind:
            raise ValueError("DisplayPrompt.kind must be a non-empty string")
        if not isinstance(self.title, str) or not self.title:
            raise ValueError("DisplayPrompt.title must be a non-empty string")
        if not isinstance(self.body, str):
            raise TypeError("DisplayPrompt.body must be a string")
        if not self.options:
            raise ValueError("DisplayPrompt.options must have at least one entry")
        for opt in self.options:
            if not isinstance(opt, PromptOption):
                raise TypeError("each option must be a PromptOption")
        if not isinstance(self.action_id, str) or not self.action_id:
            raise ValueError("DisplayPrompt.action_id must be a non-empty string")
        if self.timeout_seconds is not None and (
            not isinstance(self.timeout_seconds, int) or self.timeout_seconds <= 0
        ):
            raise ValueError("DisplayPrompt.timeout_seconds must be a positive int or None")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "options": [o.to_dict() for o in self.options],
            "action_id": self.action_id,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True, slots=True)
class DisplayCapabilities:
    """Optional actions and features advertised by a display snapshot."""

    actions: tuple[DisplayActionName, ...] = ()
    features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        allowed_actions = {"prompt.choose", "prompt.dismiss"}
        if any(
            not isinstance(action, str) or action not in allowed_actions
            for action in self.actions
        ):
            raise ValueError("capabilities.actions contains an unknown action")
        if len(set(self.actions)) != len(self.actions):
            raise ValueError("capabilities.actions must be unique")
        if any(not isinstance(feature, str) or not feature for feature in self.features):
            raise ValueError("capabilities.features must contain non-empty strings")
        if len(set(self.features)) != len(self.features):
            raise ValueError("capabilities.features must be unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "actions": list(self.actions),
            "features": list(self.features),
        }


@dataclass(frozen=True, slots=True)
class DisplaySnapshot:
    schema: int = 1
    sequence: int = 0
    state: DisplayState = "idle"
    response_text: str = ""
    status_text: str | None = None
    media: dict[str, object] | None = None
    account: str | None = None
    prompt: DisplayPrompt | None = None
    capabilities: DisplayCapabilities | None = None

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
        if self.account is not None and not isinstance(self.account, str):
            raise TypeError("account must be a string or None")
        if self.media is not None and not isinstance(self.media, dict):
            raise TypeError("media must be a dict or None")
        if self.media is not None:
            copied_media = copy.deepcopy(self.media)
            object.__setattr__(self, "media", copied_media)
            try:
                json.dumps(copied_media, allow_nan=False)
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError("media must be JSON serializable") from error
        if self.prompt is not None and not isinstance(self.prompt, DisplayPrompt):
            raise TypeError("prompt must be a DisplayPrompt or None")
        if self.capabilities is not None and not isinstance(self.capabilities, DisplayCapabilities):
            raise TypeError("capabilities must be a DisplayCapabilities or None")
        if self.state == "prompt" and self.prompt is None:
            raise ValueError("prompt must be set when state is 'prompt'")
        if self.state != "prompt" and self.prompt is not None:
            raise ValueError("prompt must only be set when state is 'prompt'")
        if self.prompt is not None and self.capabilities is None:
            object.__setattr__(
                self,
                "capabilities",
                DisplayCapabilities(actions=("prompt.choose",), features=("prompt_overlay",)),
            )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "type": "snapshot",
            "schema": self.schema,
            "sequence": self.sequence,
            "state": self.state,
            "response_text": self.response_text,
            "status_text": self.status_text,
            "media": self.media,
            "prompt": self.prompt.to_dict() if self.prompt is not None else None,
        }
        if self.account is not None:
            data["account"] = self.account
        if self.capabilities is not None:
            data["capabilities"] = self.capabilities.to_dict()
        return data


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
        account: str | None = None,
        prompt: DisplayPrompt | None = None,
        capabilities: DisplayCapabilities | None = None,
    ) -> DisplaySnapshot:
        snapshot = DisplaySnapshot(
            sequence=self._snapshot.sequence + 1,
            state=state,
            response_text=response_text,
            status_text=status_text,
            media=media,
            account=account,
            prompt=prompt,
            capabilities=capabilities,
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
