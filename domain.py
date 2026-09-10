"""Framework-independent state and policy for the terminal doorway.

The TUI owns rendering, input widgets, audio devices, and transcript history.
This module owns the small amount of stateful policy that must not be hidden in
those presentation concerns: normalized turn phases, prompt actions, stale
event rejection, and busy-turn decisions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Literal, Mapping


BUSY_MODES = frozenset({"queue", "steer", "interrupt"})

# These are terminal capabilities, not additions to the v1 room-display
# schema.  Keeping them explicit makes the richer TUI projection intentional.
TUI_CAPABILITIES = frozenset(
    {
        "voice.capture",
        "prompt.choose",
        "prompt.free_text",
        "prompt.masked_input",
        "turn.queue",
        "turn.steer",
        "turn.interrupt",
        "transcript.details",
    }
)


class TurnPhase(str, Enum):
    IDLE = "idle"
    HEARD = "heard"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    BUFFERING = "buffering"
    SPEAKING = "speaking"
    PROMPT = "prompt"
    COMPLETE = "complete"
    INTERRUPTED = "interrupted"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class ConnectionPhase(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    RETRYING = "retrying"
    CONNECTED = "connected"


@dataclass(frozen=True, slots=True)
class PromptOption:
    """One option that can be selected in a structured prompt."""

    option_id: str
    label: str


@dataclass(frozen=True, slots=True)
class PromptState:
    """Validated prompt data needed by both the policy and terminal renderer."""

    prompt_id: str
    prompt_kind: str
    text: str
    options: tuple[PromptOption, ...] = ()
    sensitive: bool = False
    turn_id: str | None = None
    session_id: str | None = None
    timeout_s: float | None = None

    @classmethod
    def from_event(cls, event: Mapping[str, Any]) -> "PromptState":
        prompt_id = str(event.get("prompt_id") or event.get("id") or "").strip()
        if not prompt_id:
            raise ValueError("prompt_request is missing prompt_id")
        if len(prompt_id) > 64:
            raise ValueError("prompt_id exceeds the shared action limit")

        raw_options = event.get("options")
        if raw_options is None:
            raw_options = ()
        elif not isinstance(raw_options, (list, tuple)):
            raise ValueError("prompt_request options must be a list")

        options: list[PromptOption] = []
        for raw_option in raw_options:
            if not isinstance(raw_option, Mapping):
                raise ValueError("prompt option must be an object")
            option_id = str(raw_option.get("id") or raw_option.get("option_id") or "").strip()
            if not option_id:
                raise ValueError("prompt option is missing id")
            if len(option_id) > 32:
                raise ValueError("prompt option id exceeds the shared action limit")
            label = str(raw_option.get("label") or option_id)
            options.append(PromptOption(option_id=option_id, label=label))

        raw_timeout = event.get("timeout_s")
        timeout_s: float | None
        if raw_timeout is None:
            timeout_s = None
        else:
            try:
                timeout_s = float(raw_timeout)
            except (TypeError, ValueError) as exc:
                raise ValueError("prompt timeout_s must be numeric") from exc
            if not math.isfinite(timeout_s) or timeout_s <= 0:
                raise ValueError("prompt timeout_s must be positive and finite")

        return cls(
            prompt_id=prompt_id,
            prompt_kind=str(event.get("prompt_kind") or event.get("kind") or "prompt"),
            text=str(event.get("text") or event.get("question") or ""),
            options=tuple(options),
            sensitive=bool(event.get("sensitive", False)),
            turn_id=_optional_text(event.get("turn_id")),
            session_id=_optional_text(event.get("session_id")),
            timeout_s=timeout_s,
        )

    @property
    def masked(self) -> bool:
        return self.sensitive or self.prompt_kind.lower() in {"sudo", "secret", "password"}

    @property
    def accepts_free_text(self) -> bool:
        return self.masked or self.prompt_kind.lower() == "clarify" or not self.options

    @property
    def option_ids(self) -> frozenset[str]:
        return frozenset(option.option_id for option in self.options)


@dataclass(frozen=True, slots=True)
class DomainState:
    """Immutable snapshot of the policy state observed by a front end."""

    phase: TurnPhase = TurnPhase.IDLE
    connection: ConnectionPhase = ConnectionPhase.DISCONNECTED
    session_id: str | None = None
    turn_id: str | None = None
    generation: int | None = None
    turn_active: bool = False
    response_text: str = ""
    audio_active: bool = False
    prompt: PromptState | None = None
    prompt_awaiting: bool = False
    prompt_rejection: str | None = None
    last_error: str | None = None

    @property
    def display_state(self) -> str:
        """Project terminal-only phases onto the shared nine-state display set."""

        if self.connection is not ConnectionPhase.CONNECTED and not self.turn_active:
            return "disconnected"
        return {
            TurnPhase.TRANSCRIBING: "listening",
            TurnPhase.COMPLETE: "idle",
            TurnPhase.INTERRUPTED: "idle",
        }.get(self.phase, self.phase.value)


@dataclass(frozen=True, slots=True)
class PromptAction:
    """A validated, single-shot prompt response ready for the session port."""

    prompt_id: str
    prompt_kind: str
    option_id: str | None = None
    value: str | None = None

    @property
    def is_choice(self) -> bool:
        return self.option_id is not None

    def to_display_action(self) -> dict[str, Any] | None:
        """Return the v1 display action shape for an option selection."""

        if self.option_id is None:
            return None
        return {
            "type": "action",
            "schema": 1,
            "action_id": self.prompt_id,
            "choice": self.option_id,
        }


@dataclass(frozen=True, slots=True)
class DomainResult:
    accepted: bool
    state: DomainState
    reason: str | None = None
    action: PromptAction | None = None


BusyAction = Literal["start", "start_queued", "queue", "steer", "interrupt"]


@dataclass(frozen=True, slots=True)
class BusyDecision:
    action: BusyAction


def decide_busy(*, mode: str, turn_in_flight: bool, has_queued_prompts: bool) -> BusyDecision:
    """Select a busy-mode action without mutating UI or session state."""

    if mode not in BUSY_MODES:
        raise ValueError(f"unsupported busy mode: {mode}")
    if not turn_in_flight:
        return BusyDecision("start_queued" if has_queued_prompts else "start")
    if mode == "queue":
        return BusyDecision("queue")
    if mode == "steer":
        return BusyDecision("steer")
    return BusyDecision("interrupt")


_ALLOWED_PHASES: dict[TurnPhase, frozenset[TurnPhase]] = {
    TurnPhase.IDLE: frozenset(
        {
            TurnPhase.HEARD,
            TurnPhase.LISTENING,
            TurnPhase.TRANSCRIBING,
            TurnPhase.THINKING,
            TurnPhase.PROMPT,
            TurnPhase.ERROR,
            TurnPhase.DISCONNECTED,
        }
    ),
    TurnPhase.HEARD: frozenset(
        {
            TurnPhase.LISTENING,
            TurnPhase.TRANSCRIBING,
            TurnPhase.THINKING,
            TurnPhase.INTERRUPTED,
            TurnPhase.IDLE,
            TurnPhase.ERROR,
            TurnPhase.DISCONNECTED,
        }
    ),
    TurnPhase.LISTENING: frozenset(
        {
            TurnPhase.TRANSCRIBING,
            TurnPhase.THINKING,
            TurnPhase.INTERRUPTED,
            TurnPhase.IDLE,
            TurnPhase.ERROR,
            TurnPhase.DISCONNECTED,
        }
    ),
    TurnPhase.TRANSCRIBING: frozenset(
        {
            TurnPhase.THINKING,
            TurnPhase.INTERRUPTED,
            TurnPhase.IDLE,
            TurnPhase.ERROR,
            TurnPhase.DISCONNECTED,
        }
    ),
    TurnPhase.THINKING: frozenset(
        {
            TurnPhase.BUFFERING,
            TurnPhase.SPEAKING,
            TurnPhase.PROMPT,
            TurnPhase.COMPLETE,
            TurnPhase.INTERRUPTED,
            TurnPhase.ERROR,
            TurnPhase.DISCONNECTED,
        }
    ),
    TurnPhase.BUFFERING: frozenset(
        {
            TurnPhase.SPEAKING,
            TurnPhase.THINKING,
            TurnPhase.PROMPT,
            TurnPhase.COMPLETE,
            TurnPhase.INTERRUPTED,
            TurnPhase.ERROR,
            TurnPhase.DISCONNECTED,
        }
    ),
    TurnPhase.SPEAKING: frozenset(
        {
            TurnPhase.BUFFERING,
            TurnPhase.THINKING,
            TurnPhase.PROMPT,
            TurnPhase.COMPLETE,
            TurnPhase.INTERRUPTED,
            TurnPhase.ERROR,
            TurnPhase.DISCONNECTED,
        }
    ),
    TurnPhase.PROMPT: frozenset(
        {
            TurnPhase.THINKING,
            TurnPhase.PROMPT,
            TurnPhase.COMPLETE,
            TurnPhase.INTERRUPTED,
            TurnPhase.ERROR,
            TurnPhase.DISCONNECTED,
        }
    ),
    TurnPhase.COMPLETE: frozenset(
        {
            TurnPhase.IDLE,
            TurnPhase.HEARD,
            TurnPhase.LISTENING,
            TurnPhase.TRANSCRIBING,
            TurnPhase.THINKING,
            TurnPhase.ERROR,
            TurnPhase.DISCONNECTED,
        }
    ),
    TurnPhase.INTERRUPTED: frozenset(
        {
            TurnPhase.IDLE,
            TurnPhase.HEARD,
            TurnPhase.LISTENING,
            TurnPhase.TRANSCRIBING,
            TurnPhase.THINKING,
            TurnPhase.ERROR,
            TurnPhase.DISCONNECTED,
        }
    ),
    TurnPhase.ERROR: frozenset(
        {
            TurnPhase.IDLE,
            TurnPhase.HEARD,
            TurnPhase.LISTENING,
            TurnPhase.TRANSCRIBING,
            TurnPhase.THINKING,
            TurnPhase.DISCONNECTED,
        }
    ),
    TurnPhase.DISCONNECTED: frozenset(
        {
            TurnPhase.IDLE,
            TurnPhase.HEARD,
            TurnPhase.LISTENING,
            TurnPhase.TRANSCRIBING,
            TurnPhase.THINKING,
            TurnPhase.ERROR,
        }
    ),
}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class TuiDomain:
    """Stateful adapter for normalized session events.

    Every mutation produces a new :class:`DomainState`.  A rejected event or
    prompt action leaves the previous snapshot untouched, which is the useful
    property when reconnects deliver late frames or users press a prompt key
    twice.
    """

    capabilities = TUI_CAPABILITIES

    def __init__(self) -> None:
        self._state = DomainState()

    @property
    def state(self) -> DomainState:
        return self._state

    def set_connection_state(self, raw_state: str) -> DomainResult:
        mapping = {
            "disconnected": ConnectionPhase.DISCONNECTED,
            "connecting": ConnectionPhase.CONNECTING,
            "retrying": ConnectionPhase.RETRYING,
            "connected": ConnectionPhase.CONNECTED,
        }
        try:
            connection = mapping[raw_state]
        except KeyError:
            return DomainResult(
                False,
                self._state,
                reason=f"unsupported connection state: {raw_state}",
            )

        if connection is ConnectionPhase.DISCONNECTED:
            self._state = replace(
                self._state,
                connection=connection,
                phase=TurnPhase.DISCONNECTED,
                turn_id=None,
                turn_active=False,
                audio_active=False,
                prompt=None,
                prompt_awaiting=False,
                prompt_rejection=None,
            )
        elif connection is ConnectionPhase.CONNECTED:
            phase = (
                TurnPhase.IDLE
                if not self._state.turn_active
                and self._state.phase in {TurnPhase.DISCONNECTED, TurnPhase.ERROR}
                else self._state.phase
            )
            self._state = replace(self._state, connection=connection, phase=phase)
        else:
            self._state = replace(self._state, connection=connection)
        return DomainResult(True, self._state)

    def observe_voice_state(self, raw_state: str) -> DomainResult:
        """Accept the TUI's existing labels as a presentation-to-domain bridge."""

        raw_state = raw_state.rstrip("…")
        mapping = {
            "heard": TurnPhase.HEARD,
            "listening": TurnPhase.LISTENING,
            "transcribing": TurnPhase.TRANSCRIBING,
            "thinking": TurnPhase.THINKING,
            "buffering": TurnPhase.BUFFERING,
            "speaking": TurnPhase.SPEAKING,
            "interrupted": TurnPhase.INTERRUPTED,
            "error": TurnPhase.ERROR,
            "disconnected": TurnPhase.DISCONNECTED,
        }
        phase = mapping.get(raw_state)
        if phase is None:
            # "ready", "starting", and connection labels are presentation
            # milestones; the normalized event stream remains authoritative.
            return DomainResult(True, self._state)
        if phase is not self._state.phase and phase not in _ALLOWED_PHASES[self._state.phase]:
            return DomainResult(False, self._state, reason="invalid_phase_transition")
        self._state = replace(self._state, phase=phase)
        return DomainResult(True, self._state)

    def reset_session(self, session_id: str | None) -> DomainResult:
        """Discard turn-local policy when the relay session identity changes."""

        connection = self._state.connection
        self._state = DomainState(
            phase=(
                TurnPhase.IDLE
                if connection is ConnectionPhase.CONNECTED
                else TurnPhase.DISCONNECTED
            ),
            connection=connection,
            session_id=_optional_text(session_id),
        )
        return DomainResult(True, self._state)

    def begin_turn(
        self,
        turn_id: str | None = None,
        *,
        generation: int | None = None,
    ) -> DomainResult:
        """Start a fresh, explicitly initiated turn."""

        if self._state.turn_active:
            return DomainResult(False, self._state, reason="turn_already_active")
        if self._state.connection is not ConnectionPhase.CONNECTED:
            return DomainResult(False, self._state, reason="not_connected")
        if not self._can_transition(TurnPhase.THINKING):
            return DomainResult(False, self._state, reason="invalid_phase_transition")
        self._state = replace(
            self._state,
            phase=TurnPhase.THINKING,
            turn_id=_optional_text(turn_id),
            generation=generation,
            turn_active=True,
            response_text="",
            audio_active=False,
            prompt=None,
            prompt_awaiting=False,
            prompt_rejection=None,
            last_error=None,
        )
        return DomainResult(True, self._state)

    def bind_turn_id(self, turn_id: str | None) -> DomainResult:
        """Bind a session-assigned id after the session creates the turn."""

        if not self._state.turn_active:
            return DomainResult(False, self._state, reason="no_active_turn")
        if self._state.turn_id is not None:
            if _optional_text(turn_id) != self._state.turn_id:
                return DomainResult(False, self._state, reason="turn_id_already_bound")
            return DomainResult(True, self._state)
        self._state = replace(self._state, turn_id=_optional_text(turn_id))
        return DomainResult(True, self._state)

    def apply_event(
        self,
        event: Mapping[str, Any],
        *,
        generation: int | None = None,
    ) -> DomainResult:
        """Apply one normalized session or local lifecycle event."""

        event_type = str(event.get("type") or event.get("event") or "")
        if not event_type:
            return DomainResult(False, self._state, reason="missing_event_type")

        if event_type in {"connection", "connection_state"}:
            return self.set_connection_state(str(event.get("state") or event.get("connection") or ""))

        if event_type in {"capture_started", "wake_heard"}:
            return self._transition(TurnPhase.HEARD if event_type == "wake_heard" else TurnPhase.LISTENING)
        if event_type in {"capture_finished", "transcription_started"}:
            return self._transition(TurnPhase.TRANSCRIBING)
        if event_type in {"capture_cancelled", "capture_empty"}:
            return self._transition(TurnPhase.IDLE)
        if event_type in {"connection_lost", "disconnected"}:
            return self.set_connection_state("disconnected")

        stale = self._reject_stale_event(event, generation=generation)
        if stale is not None:
            return stale

        if event_type == "turn_started":
            return self.begin_turn(
                _optional_text(event.get("turn_id")),
                generation=generation,
            )

        if event_type in {"text_delta", "text_replace"}:
            if event_type == "text_replace":
                text = str(event.get("text") or "")
            else:
                text = self._state.response_text + str(event.get("text") or event.get("delta") or "")
            phase = self._state.phase
            if phase not in {TurnPhase.SPEAKING, TurnPhase.BUFFERING}:
                phase = TurnPhase.THINKING
            return self._transition(phase, response_text=text)

        if event_type in {
            "thinking",
            "thinking_delta",
            "reasoning",
            "reasoning_available",
            "status",
            "tool_start",
            "tool_progress",
            "tool_complete",
            "tool_end",
            "notification",
            "notification_clear",
            "background_complete",
        }:
            if self._state.phase in {TurnPhase.SPEAKING, TurnPhase.BUFFERING}:
                return DomainResult(True, self._state)
            return self._transition(TurnPhase.THINKING)

        if event_type == "audio_start":
            result = self._transition(TurnPhase.SPEAKING)
            if result.accepted:
                self._state = replace(self._state, audio_active=True)
                return DomainResult(True, self._state)
            return result

        if event_type in {"audio_chunk", "audio_end"}:
            if not self._state.audio_active:
                return DomainResult(False, self._state, reason="audio_not_started")
            if event_type == "audio_end":
                self._state = replace(self._state, audio_active=False)
            return DomainResult(True, self._state)

        if event_type in {"audio_file_start", "audio_buffering"}:
            result = self._transition(TurnPhase.BUFFERING)
            if result.accepted:
                self._state = replace(self._state, audio_active=True)
                return DomainResult(True, self._state)
            return result

        if event_type in {"audio_file_chunk", "audio_file_end"}:
            if not self._state.audio_active:
                return DomainResult(False, self._state, reason="audio_not_started")
            if event_type == "audio_file_end":
                self._state = replace(self._state, audio_active=False)
            return DomainResult(True, self._state)

        if event_type == "audio_abort":
            self._state = replace(self._state, audio_active=False)
            return self._transition(TurnPhase.INTERRUPTED)

        if event_type == "prompt_request":
            try:
                prompt = PromptState.from_event(event)
            except ValueError as exc:
                return DomainResult(False, self._state, reason=str(exc))
            if (
                self._state.prompt is not None
                and self._state.prompt.prompt_id == prompt.prompt_id
                and self._state.prompt_awaiting
            ):
                return DomainResult(False, self._state, reason="duplicate_prompt")
            if not self._can_transition(TurnPhase.PROMPT):
                return DomainResult(False, self._state, reason="invalid_phase_transition")
            self._state = replace(
                self._state,
                phase=TurnPhase.PROMPT,
                prompt=prompt,
                prompt_awaiting=False,
                prompt_rejection=None,
            )
            return DomainResult(True, self._state)

        if event_type == "prompt_resolved":
            prompt_id = _optional_text(event.get("prompt_id") or event.get("id"))
            if (
                self._state.prompt is None
                or prompt_id is None
                or prompt_id != self._state.prompt.prompt_id
            ):
                return DomainResult(False, self._state, reason="stale_prompt")
            self._state = replace(
                self._state,
                phase=TurnPhase.THINKING,
                prompt=None,
                prompt_awaiting=False,
                prompt_rejection=None,
            )
            return DomainResult(True, self._state)

        if event_type == "prompt_response_rejected":
            prompt_id = _optional_text(event.get("prompt_id") or event.get("id"))
            if (
                self._state.prompt is None
                or prompt_id is None
                or prompt_id != self._state.prompt.prompt_id
            ):
                return DomainResult(False, self._state, reason="stale_prompt")
            self._state = replace(
                self._state,
                prompt_awaiting=False,
                prompt_rejection=str(event.get("reason") or event.get("message") or "rejected"),
            )
            return DomainResult(True, self._state)

        if event_type in {"turn_interrupted", "turn_cancelled"}:
            return self._finish(TurnPhase.INTERRUPTED)

        if event_type == "error":
            self._state = replace(
                self._state,
                phase=TurnPhase.ERROR,
                turn_active=False,
                audio_active=False,
                prompt=None,
                prompt_awaiting=False,
                last_error=str(event.get("message") or event.get("error") or "turn failed"),
            )
            return DomainResult(True, self._state)

        if event_type == "turn_end":
            final_text = event.get("text")
            kwargs: dict[str, Any] = {}
            if final_text is not None:
                kwargs["response_text"] = str(final_text)
            return self._finish(TurnPhase.COMPLETE, **kwargs)

        # Unknown diagnostics remain visible to the TUI, but do not invent a
        # state transition in the domain adapter.
        return DomainResult(True, self._state)

    def validate_prompt_action(
        self,
        *,
        option_id: str | None = None,
        value: str | None = None,
    ) -> str | None:
        prompt = self._state.prompt
        if prompt is None:
            return "no_prompt"
        if self._state.prompt_awaiting:
            return "prompt_response_pending"
        if option_id is not None:
            if "prompt.choose" not in self.capabilities:
                return "unsupported_prompt_choice"
            if option_id not in prompt.option_ids:
                return "invalid_prompt_option"
            if value is not None:
                return "choice_cannot_include_free_text"
            return None
        if value is None:
            return "missing_prompt_response"
        if not prompt.accepts_free_text:
            return "unsupported_prompt_free_text"
        capability = "prompt.masked_input" if prompt.masked else "prompt.free_text"
        if capability not in self.capabilities:
            return "unsupported_prompt_input"
        return None

    def prepare_prompt_action(
        self,
        *,
        option_id: str | None = None,
        value: str | None = None,
    ) -> DomainResult:
        reason = self.validate_prompt_action(option_id=option_id, value=value)
        if reason is not None:
            return DomainResult(False, self._state, reason=reason)
        assert self._state.prompt is not None  # guarded by validation
        action = PromptAction(
            prompt_id=self._state.prompt.prompt_id,
            prompt_kind=self._state.prompt.prompt_kind,
            option_id=option_id,
            value=value,
        )
        self._state = replace(self._state, prompt_awaiting=True, prompt_rejection=None)
        return DomainResult(True, self._state, action=action)

    def prompt_response_failed(self, reason: str) -> DomainResult:
        if self._state.prompt is None:
            return DomainResult(False, self._state, reason="no_prompt")
        self._state = replace(
            self._state,
            prompt_awaiting=False,
            prompt_rejection=reason,
        )
        return DomainResult(True, self._state)

    def _reject_stale_event(
        self,
        event: Mapping[str, Any],
        *,
        generation: int | None,
    ) -> DomainResult | None:
        if generation is not None:
            if not self._state.turn_active:
                return DomainResult(False, self._state, reason="late_turn_event")
            if self._state.generation != generation:
                return DomainResult(False, self._state, reason="stale_turn_event")

        event_session_id = _optional_text(event.get("session_id"))
        if (
            event_session_id is not None
            and self._state.session_id is not None
            and event_session_id != self._state.session_id
        ):
            return DomainResult(False, self._state, reason="stale_session_event")

        event_turn_id = _optional_text(event.get("turn_id"))
        if not event_turn_id:
            return None
        if not self._state.turn_active:
            return DomainResult(False, self._state, reason="late_turn_event")
        if self._state.turn_id is not None and event_turn_id != self._state.turn_id:
            return DomainResult(False, self._state, reason="stale_turn_event")
        return None

    def _can_transition(self, phase: TurnPhase) -> bool:
        return phase is self._state.phase or phase in _ALLOWED_PHASES[self._state.phase]

    def _transition(self, phase: TurnPhase, **changes: Any) -> DomainResult:
        if not self._can_transition(phase):
            return DomainResult(False, self._state, reason="invalid_phase_transition")
        self._state = replace(self._state, phase=phase, **changes)
        return DomainResult(True, self._state)

    def _finish(self, phase: TurnPhase, **changes: Any) -> DomainResult:
        if not self._can_transition(phase):
            return DomainResult(False, self._state, reason="invalid_phase_transition")
        self._state = replace(
            self._state,
            phase=phase,
            turn_active=False,
            turn_id=None,
            audio_active=False,
            prompt=None,
            prompt_awaiting=False,
            **changes,
        )
        return DomainResult(True, self._state)
