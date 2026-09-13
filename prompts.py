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
    choice_object_id: Optional[str] = None
    choice_operations: tuple[str, ...] = ()
    choice_freshness: Optional[str] = None
    focused_index: int = 0
    # Set once a response has been sent and we're waiting on prompt_resolved
    # or prompt_response_rejected, so a second answer for the same prompt_id
    # can't go out while the first is still in flight.
    awaiting_response: bool = False
    rejection_reason: Optional[str] = None
    request_message: Any = field(default=None, repr=False, compare=False)
    request_rejected: bool = field(default=False, repr=False, compare=False)
    domain_state: Optional[PromptState] = field(default=None, repr=False, compare=False)
    # The prompt response must never cross a session replacement boundary.
    session_identity: Any = field(default=None, repr=False, compare=False)
    session_generation: int | None = field(default=None, repr=False, compare=False)

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
                choice_object_id=domain_state.choice_object_id,
                choice_operations=domain_state.choice_operations,
                choice_freshness=domain_state.choice_freshness,
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
        raw_choice = event.get("choice")
        choice_object_id: Optional[str] = None
        choice_operations: tuple[str, ...] = ()
        choice_freshness: Optional[str] = None
        if str(event.get("prompt_kind") or "").strip().lower() == "choice":
            if isinstance(raw_choice, dict):
                raw_object_id = raw_choice.get("object_id")
                choice_object_id = str(raw_object_id or "") or None
                raw_operations = raw_choice.get("operations")
                if isinstance(raw_operations, (list, tuple)):
                    choice_operations = tuple(
                        str(operation).strip().lower()
                        for operation in raw_operations
                        if str(operation).strip()
                    )
                raw_freshness = raw_choice.get("freshness")
                choice_freshness = str(raw_freshness or "") or None
        return cls(
            prompt_id=str(event.get("prompt_id") or ""),
            prompt_kind=str(event.get("prompt_kind") or ""),
            text=str(event.get("text") or ""),
            options=options,
            sensitive=bool(event.get("sensitive", False)),
            turn_id=str(event.get("turn_id") or ""),
            session_id=str(event.get("session_id") or ""),
            timeout_s=timeout_s,
            choice_object_id=choice_object_id,
            choice_operations=choice_operations,
            choice_freshness=choice_freshness,
        )

    @property
    def is_choice(self) -> bool:
        return self.prompt_kind.strip().lower() == "choice"

    @property
    def focused_option(self) -> Optional[PromptOption]:
        if not self.options:
            return None
        index = min(max(self.focused_index, 0), len(self.options) - 1)
        return self.options[index]

    def move_focus(self, delta: int) -> None:
        if not self.options:
            self.focused_index = 0
            return
        self.focused_index = min(
            max(self.focused_index + delta, 0),
            len(self.options) - 1,
        )

    def focus_option(self, option_id: str) -> None:
        for index, option in enumerate(self.options):
            if option.id == option_id:
                self.focused_index = index
                return

    def supports_operation(self, operation: str) -> bool:
        return self.is_choice and operation.strip().lower() in self.choice_operations

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
            if self.is_choice:
                marker = "  [focused]" if position - 1 == self.focused_index else ""
                affordances: list[str] = []
                if self.supports_operation("choose"):
                    affordances.append("Choose [Enter]")
                if self.supports_operation("explore"):
                    affordances.append("Explore [Right Arrow]")
                suffix = f" — {' · '.join(affordances)}" if affordances else ""
                lines.append(f"  {position}) {option.label}{marker}{suffix}")
            else:
                lines.append(f"  {position}) {option.label}")
        if self.is_choice:
            controls = ["Up/Down move focus"]
            if self.supports_operation("choose"):
                controls.append("Enter choose")
            if self.supports_operation("explore"):
                controls.append("Right Arrow explore")
            lines.append("  " + " · ".join(controls))
        elif self.prompt_kind == "clarify":
            lines.append("  Other: type a free-text answer below and press Enter")
        elif self.masked:
            lines.append("  masked input — press Enter to submit, value is never shown")
        if self.awaiting_response:
            lines.append("  waiting for the relay to resolve this response…")
        if self.rejection_reason:
            lines.append(f"  rejected: {self.rejection_reason} — try again")
        return lines
