from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain import (
    ConnectionPhase,
    DomainState,
    PromptAction,
    TUI_CAPABILITIES,
    TuiDomain,
    TurnPhase,
    decide_busy,
)


def connected_domain() -> TuiDomain:
    domain = TuiDomain()
    domain.set_connection_state("connected")
    return domain


def start_turn(domain: TuiDomain, turn_id: str = "turn-1") -> None:
    result = domain.begin_turn(turn_id)
    assert result.accepted


def test_normal_turn_replay_keeps_terminal_phases_explicit_and_projects_display_state() -> None:
    domain = connected_domain()

    assert domain.apply_event({"type": "capture_started"}).accepted
    assert domain.state.phase is TurnPhase.LISTENING
    assert domain.apply_event({"type": "capture_finished"}).accepted
    assert domain.state.phase is TurnPhase.TRANSCRIBING
    start_turn(domain)

    assert domain.apply_event({"type": "text_delta", "text": "hello "}).accepted
    assert domain.apply_event({"type": "text_delta", "text": "world"}).accepted
    assert domain.state.response_text == "hello world"
    assert domain.apply_event({"type": "audio_start"}).accepted
    assert domain.state.phase is TurnPhase.SPEAKING
    assert domain.state.display_state == "speaking"

    result = domain.apply_event({"type": "turn_end", "turn_id": "turn-1"})
    assert result.accepted
    assert domain.state.phase is TurnPhase.COMPLETE
    assert domain.state.display_state == "idle"
    assert domain.state.turn_active is False


def test_terminal_only_phases_project_to_the_shared_display_states() -> None:
    domain = connected_domain()
    assert domain.apply_event({"type": "capture_started"}).accepted
    assert domain.apply_event({"type": "capture_finished"}).accepted
    assert domain.state.phase is TurnPhase.TRANSCRIBING
    assert domain.state.display_state == "listening"

    domain = connected_domain()
    start_turn(domain)
    interrupted = domain.apply_event({"type": "turn_interrupted", "turn_id": "turn-1"})
    assert interrupted.accepted
    assert domain.state.phase is TurnPhase.INTERRUPTED
    assert domain.state.display_state == "idle"


def test_prompt_action_is_validated_once_and_rejection_is_retryable() -> None:
    domain = connected_domain()
    start_turn(domain)
    prompt_event = {
        "type": "prompt_request",
        "turn_id": "turn-1",
        "prompt_id": "confirm-1",
        "prompt_kind": "approval",
        "text": "Proceed?",
        "options": [
            {"id": "yes", "label": "Yes"},
            {"id": "no", "label": "No"},
        ],
    }
    assert domain.apply_event(prompt_event).accepted
    assert domain.state.phase is TurnPhase.PROMPT
    assert domain.state.prompt is not None
    assert domain.state.prompt.accepts_free_text is False

    invalid = domain.prepare_prompt_action(option_id="maybe")
    assert invalid.accepted is False
    assert invalid.reason == "invalid_prompt_option"
    assert domain.state.prompt_awaiting is False

    valid = domain.prepare_prompt_action(option_id="yes")
    assert valid.accepted
    assert isinstance(valid.action, PromptAction)
    assert valid.action.to_display_action() == {
        "type": "action",
        "schema": 1,
        "action_id": "confirm-1",
        "choice": "yes",
    }
    assert domain.state.prompt_awaiting is True

    duplicate = domain.prepare_prompt_action(option_id="no")
    assert duplicate.accepted is False
    assert duplicate.reason == "prompt_response_pending"
    assert domain.state.prompt_awaiting is True

    assert domain.apply_event(
        {
            "type": "prompt_response_rejected",
            "turn_id": "turn-1",
            "prompt_id": "confirm-1",
            "reason": "try again",
        }
    ).accepted
    assert domain.state.prompt_awaiting is False
    assert domain.state.prompt_rejection == "try again"
    assert domain.prepare_prompt_action(option_id="no").accepted


def test_stale_prompt_resolution_cannot_change_a_later_turn() -> None:
    domain = connected_domain()
    start_turn(domain)
    assert domain.apply_event(
        {
            "type": "prompt_request",
            "turn_id": "turn-1",
            "prompt_id": "confirm-1",
            "prompt_kind": "approval",
            "text": "Proceed?",
            "options": [{"id": "yes", "label": "Yes"}],
        }
    ).accepted
    assert domain.apply_event({"type": "prompt_resolved", "prompt_id": "confirm-1"}).accepted
    assert domain.apply_event({"type": "turn_end", "turn_id": "turn-1"}).accepted
    assert domain.begin_turn("turn-2").accepted
    assert domain.apply_event({"type": "audio_start", "turn_id": "turn-2"}).accepted
    before = domain.state

    stale = domain.apply_event({"type": "prompt_resolved", "prompt_id": "confirm-1"})
    assert stale.accepted is False
    assert stale.reason == "stale_prompt"
    assert domain.state == before


def test_free_text_and_masked_prompt_capabilities_are_explicit() -> None:
    domain = connected_domain()
    start_turn(domain)
    assert domain.apply_event(
        {
            "type": "prompt_request",
            "turn_id": "turn-1",
            "prompt_id": "secret-1",
            "prompt_kind": "secret",
            "text": "Token",
            "sensitive": True,
        }
    ).accepted
    assert "prompt.masked_input" in TUI_CAPABILITIES
    assert domain.state.prompt is not None and domain.state.prompt.masked
    action = domain.prepare_prompt_action(value="s3cr3t")
    assert action.accepted
    assert action.action is not None and action.action.value == "s3cr3t"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("queue", "queue"), ("steer", "steer"), ("interrupt", "interrupt")],
)
def test_busy_decision_is_pure(mode: str, expected: str) -> None:
    assert decide_busy(mode=mode, turn_in_flight=True, has_queued_prompts=False).action == expected
    assert decide_busy(mode=mode, turn_in_flight=False, has_queued_prompts=False).action == "start"
    assert decide_busy(mode=mode, turn_in_flight=False, has_queued_prompts=True).action == "start_queued"


def test_stale_events_and_invalid_milestones_leave_the_last_safe_state() -> None:
    idle_domain = connected_domain()
    idle_before = idle_domain.state
    invalid_milestone = idle_domain.apply_event({"type": "audio_start"})
    assert invalid_milestone.accepted is False
    assert invalid_milestone.reason == "invalid_phase_transition"
    assert idle_domain.state == idle_before

    domain = connected_domain()
    assert domain.begin_turn("turn-new", generation=2).accepted
    before = domain.state

    stale = domain.apply_event(
        {"type": "text_delta", "turn_id": "turn-new", "text": "wrong"},
        generation=1,
    )
    assert stale.accepted is False
    assert stale.reason == "stale_turn_event"
    assert domain.state == before

    invalid = domain.apply_event({"type": "audio_chunk", "turn_id": "turn-new"}, generation=2)
    assert invalid.accepted is False
    assert invalid.reason == "audio_not_started"
    assert domain.state == before

    valid = domain.apply_event({"type": "audio_start", "turn_id": "turn-new"}, generation=2)
    assert valid.accepted
    assert domain.state.phase is TurnPhase.SPEAKING

    repeated = domain.apply_event({"type": "audio_start", "turn_id": "turn-new"}, generation=2)
    assert repeated.accepted
    assert domain.state.phase is TurnPhase.SPEAKING

    assert domain.apply_event({"type": "turn_end", "turn_id": "turn-new"}, generation=2).accepted
    late = domain.apply_event(
        {"type": "text_delta", "turn_id": "turn-new", "text": "late"},
        generation=2,
    )
    assert late.accepted is False
    assert late.reason == "late_turn_event"
    assert domain.state.response_text == ""

    rejected_connection = domain.set_connection_state("bogus")
    assert rejected_connection.accepted is False
    assert rejected_connection.reason == "unsupported connection state: bogus"


def test_recovery_requires_a_fresh_turn_and_does_not_replay_the_ambiguous_one() -> None:
    domain = connected_domain()
    start_turn(domain, "turn-old")
    assert domain.apply_event({"type": "text_delta", "turn_id": "turn-old", "text": "partial"}).accepted
    assert domain.apply_event({"type": "connection_lost"}).accepted
    assert domain.state.connection is ConnectionPhase.DISCONNECTED
    assert domain.state.phase is TurnPhase.DISCONNECTED
    assert domain.state.turn_active is False

    assert domain.set_connection_state("connected").accepted
    assert domain.state.phase is TurnPhase.IDLE
    assert domain.begin_turn("turn-new").accepted
    late = domain.apply_event({"type": "text_delta", "turn_id": "turn-old", "text": "replayed"})
    assert late.accepted is False
    assert late.reason == "stale_turn_event"
    assert domain.state.response_text == ""


def test_shared_snapshot_fixtures_map_to_the_v1_display_state_set() -> None:
    fixture_dir = Path(__file__).parents[1] / "shared" / "display" / "fixtures" / "snapshots"
    fixture_paths = sorted(fixture_dir.glob("*.json"))
    assert fixture_paths, "the shared snapshot fixtures are the contract seed"

    allowed_states = {
        "idle",
        "heard",
        "listening",
        "thinking",
        "speaking",
        "buffering",
        "error",
        "disconnected",
        "prompt",
    }
    assert TuiDomain().state.display_state == "disconnected"
    for fixture_path in fixture_paths:
        fixture = json.loads(fixture_path.read_text())
        state = fixture["state"]
        assert state in allowed_states
        domain_state = DomainState(
            phase=TurnPhase(state),
            connection=(
                ConnectionPhase.DISCONNECTED
                if state == "disconnected"
                else ConnectionPhase.CONNECTED
            ),
        )
        assert domain_state.display_state == state


def test_session_reset_discards_turn_local_state_without_losing_connection() -> None:
    domain = connected_domain()
    assert domain.reset_session("session-a").accepted
    assert domain.state.session_id == "session-a"
    assert domain.begin_turn("turn-a", generation=1).accepted
    assert domain.apply_event(
        {"type": "text_delta", "turn_id": "turn-a", "session_id": "session-a", "text": "old"},
        generation=1,
    ).accepted

    assert domain.reset_session("session-b").accepted
    assert domain.state.session_id == "session-b"
    assert domain.state.response_text == ""
    assert domain.state.turn_active is False
    assert domain.state.connection is ConnectionPhase.CONNECTED
    assert domain.begin_turn("turn-b", generation=2).accepted
    stale = domain.apply_event(
        {"type": "text_delta", "turn_id": "turn-b", "session_id": "session-a", "text": "old"},
        generation=2,
    )
    assert stale.accepted is False
    assert stale.reason == "stale_session_event"


def test_late_audio_from_an_old_session_cannot_mutate_a_fresh_turn() -> None:
    domain = connected_domain()
    assert domain.reset_session("session-a").accepted
    assert domain.begin_turn("turn-a", generation=1).accepted
    assert domain.apply_event(
        {"type": "audio_start", "turn_id": "turn-a", "session_id": "session-a"},
        generation=1,
    ).accepted

    assert domain.reset_session("session-b").accepted
    assert domain.begin_turn("turn-b", generation=2).accepted
    before = domain.state

    stale = domain.apply_event(
        {"type": "audio_start", "turn_id": "turn-b", "session_id": "session-a"},
        generation=2,
    )

    assert stale.accepted is False
    assert stale.reason == "stale_session_event"
    assert domain.state == before

    assert domain.apply_event(
        {"type": "audio_start", "turn_id": "turn-b", "session_id": "session-b"},
        generation=2,
    ).accepted
    assert domain.state.audio_active is True
    late = domain.apply_event(
        {"type": "audio_chunk", "turn_id": "turn-a", "session_id": "session-a"},
        generation=1,
    )
    assert late.accepted is False
    assert late.reason == "stale_turn_event"
    assert domain.state.audio_active is True


def test_shared_prompt_action_fixture_is_the_tui_choice_projection() -> None:
    fixture_root = Path(__file__).parents[1] / "shared" / "display" / "fixtures"
    snapshot = json.loads((fixture_root / "snapshots" / "prompt.json").read_text())
    action_fixture = json.loads((fixture_root / "actions" / "prompt_choice.json").read_text())
    prompt = snapshot["prompt"]

    domain = connected_domain()
    start_turn(domain)
    assert domain.apply_event(
        {
            "type": "prompt_request",
            "turn_id": "turn-1",
            "prompt_id": prompt["action_id"],
            "prompt_kind": prompt["kind"],
            "text": prompt["body"],
            "options": prompt["options"],
            "timeout_s": prompt["timeout_seconds"],
        }
    ).accepted

    result = domain.prepare_prompt_action(option_id=action_fixture["choice"])
    assert result.accepted
    assert result.action is not None
    assert result.action.to_display_action() == action_fixture


def test_local_capture_empty_and_partial_error_keep_terminal_facts_honest() -> None:
    domain = connected_domain()

    assert domain.apply_event({"type": "capture_started"}).accepted
    assert domain.apply_event({"type": "capture_finished"}).accepted
    empty = domain.apply_event({"type": "capture_empty"})
    assert empty.accepted
    assert domain.state.phase is TurnPhase.IDLE
    assert domain.state.turn_active is False

    start_turn(domain)
    assert domain.apply_event({"type": "text_delta", "text": "partial reply"}).accepted
    failed = domain.apply_event({"type": "error", "error": "socket went away"})

    assert failed.accepted
    assert domain.state.phase is TurnPhase.ERROR
    assert domain.state.turn_active is False
    assert domain.state.response_text == "partial reply"
    assert domain.state.last_error == "socket went away"


def test_activity_and_unknown_events_cannot_regress_an_active_speaking_turn() -> None:
    domain = connected_domain()
    start_turn(domain)
    assert domain.apply_event({"type": "text_delta", "text": "answer"}).accepted
    assert domain.apply_event({"type": "audio_start"}).accepted
    before = domain.state

    for event in (
        {"type": "status", "text": "working"},
        {"type": "tool_start", "name": "search"},
        {"type": "unknown_event", "event_type": "future.event"},
    ):
        result = domain.apply_event(event)
        assert result.accepted
        assert domain.state.phase is TurnPhase.SPEAKING
        assert domain.state.response_text == before.response_text

    assert domain.state.audio_active is True
