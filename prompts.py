"""Structured prompt state for the Textual front end.

Kept separate from app.py so the presentation logic for a pending
approval/confirm/clarify/sudo/secret prompt can be tested without booting a
Textual app, and so app.py's already-large turn loop doesn't grow a second
state machine inline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from domain import PromptState

MASKED_PROMPT_KINDS = frozenset({"sudo", "secret", "password"})


@dataclass(frozen=True)
class PromptOption:
    id: str
    label: str


@dataclass
class PendingPrompt:
    prompt_id: str
    prompt_kind: str
    text: str
    options: list[PromptOption] = field(default_factory=list)
    sensitive: bool = False
    turn_id: str = ""
    session_id: str = ""
    timeout_s: int = 0
    # Set once a response has been sent and we're waiting on prompt_resolved
    # or prompt_response_rejected, so a second answer for the same prompt_id
    # can't go out while the first is still in flight.
    awaiting_response: bool = False
    rejection_reason: Optional[str] = None
    domain_state: Optional[PromptState] = field(default=None, repr=False, compare=False)

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> "PendingPrompt":
        try:
            domain_state = PromptState.from_event(event)
        except ValueError:
            domain_state = None
        if domain_state is not None:
            return cls(
                prompt_id=domain_state.prompt_id,
                prompt_kind=domain_state.prompt_kind,
                text=domain_state.text,
                options=[
                    PromptOption(id=option.option_id, label=option.label)
                    for option in domain_state.options
                ],
                sensitive=domain_state.sensitive,
                turn_id=domain_state.turn_id or "",
                session_id=domain_state.session_id or "",
                timeout_s=int(domain_state.timeout_s or 0),
                domain_state=domain_state,
            )
        raw_options = event.get("options")
        options = [
            PromptOption(id=str(option.get("id") or ""), label=str(option.get("label") or ""))
            for option in (raw_options if isinstance(raw_options, list) else [])
            if isinstance(option, dict)
        ]
        try:
            timeout_s = int(event.get("timeout_s") or 0)
        except (TypeError, ValueError):
            timeout_s = 0
        return cls(
            prompt_id=str(event.get("prompt_id") or ""),
            prompt_kind=str(event.get("prompt_kind") or ""),
            text=str(event.get("text") or ""),
            options=options,
            sensitive=bool(event.get("sensitive", False)),
            turn_id=str(event.get("turn_id") or ""),
            session_id=str(event.get("session_id") or ""),
            timeout_s=timeout_s,
        )

    @property
    def masked(self) -> bool:
        """Whether the answer must never be echoed anywhere visible."""
        if self.domain_state is not None:
            return self.domain_state.masked
        return self.prompt_kind in MASKED_PROMPT_KINDS or self.sensitive

    @property
    def accepts_free_text(self) -> bool:
        """Whether a free-text input box should be offered at all."""
        if self.domain_state is not None:
            return self.domain_state.accepts_free_text
        return self.masked or self.prompt_kind == "clarify" or not self.options

    def option_at(self, number: int) -> Optional[PromptOption]:
        """1-indexed lookup matching the numbers shown by render_lines."""
        index = number - 1
        if 0 <= index < len(self.options):
            return self.options[index]
        return None

    def render_lines(self) -> list[str]:
        lines = [f"[{self.prompt_kind}] {self.text}".rstrip()]
        for position, option in enumerate(self.options, start=1):
            lines.append(f"  {position}) {option.label}")
        if self.prompt_kind == "clarify":
            lines.append("  Other: type a free-text answer below and press Enter")
        elif self.masked:
            lines.append("  masked input — press Enter to submit, value is never shown")
        if self.awaiting_response:
            lines.append("  waiting for the relay to resolve this response…")
        if self.rejection_reason:
            lines.append(f"  rejected: {self.rejection_reason} — try again")
        return lines
