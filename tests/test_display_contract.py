"""Executable checks for the shared ESP/Web/TUI display contract."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


CONTRACT_DIR = Path(__file__).parents[1] / "shared" / "display"
FIXTURES_DIR = CONTRACT_DIR / "fixtures"


def _read_json(path: Path) -> object:
    return json.loads(path.read_text())


def _assert_valid(schema_path: Path, instance: object) -> None:
    schema = _read_json(schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    assert not errors, "contract errors: " + "; ".join(error.message for error in errors)


def _assert_invalid(schema_path: Path, instance: object) -> None:
    schema = _read_json(schema_path)
    assert not Draft202012Validator(schema).is_valid(instance)


def test_display_snapshot_schema_declares_the_shared_state_contract() -> None:
    schema = _read_json(CONTRACT_DIR / "display_snapshot.schema.json")

    assert schema["$id"] == "https://hermes-relay.dev/schemas/display-snapshot-1.json"
    assert schema["properties"]["schema"]["const"] == 1
    assert schema["properties"]["state"]["enum"] == [
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
    assert {"type", "schema", "sequence", "state", "response_text"} <= set(
        schema["required"]
    )
    assert schema["additionalProperties"] is True
    assert "capabilities" in schema["properties"]


def test_valid_snapshot_fixtures_match_the_schema() -> None:
    schema_path = CONTRACT_DIR / "display_snapshot.schema.json"
    fixtures = sorted((FIXTURES_DIR / "snapshots").glob("*.json"))

    assert {path.stem for path in fixtures} >= {
        "idle",
        "heard",
        "listening",
        "thinking",
        "speaking",
        "buffering",
        "error",
        "disconnected",
        "prompt",
        "legacy_idle",
        "unknown_field",
    }
    for fixture in fixtures:
        _assert_valid(schema_path, _read_json(fixture))


def test_invalid_snapshot_fixtures_are_rejected() -> None:
    schema_path = CONTRACT_DIR / "display_snapshot.schema.json"
    fixtures = sorted((FIXTURES_DIR / "invalid").glob("*.json"))

    assert fixtures
    for fixture in fixtures:
        _assert_invalid(schema_path, _read_json(fixture))


def test_stale_sequence_is_a_valid_snapshot_with_explicit_ordering_metadata() -> None:
    case = _read_json(FIXTURES_DIR / "sequences" / "stale.json")

    _assert_valid(CONTRACT_DIR / "display_snapshot.schema.json", case["snapshot"])
    assert case["baseline_sequence"] > case["snapshot"]["sequence"]
    assert case["expected"] == {"classification": "stale"}


def test_display_action_schema_covers_prompt_choice_actions() -> None:
    schema_path = CONTRACT_DIR / "display_action.schema.json"
    valid = _read_json(FIXTURES_DIR / "actions" / "prompt_choice.json")

    _assert_valid(schema_path, valid)
    assert valid == {
        "type": "action",
        "schema": 1,
        "action_id": "sethome",
        "choice": "yes",
    }


def test_invalid_display_actions_are_rejected() -> None:
    schema_path = CONTRACT_DIR / "display_action.schema.json"
    fixtures = sorted((FIXTURES_DIR / "invalid-actions").glob("*.json"))

    assert fixtures
    for fixture in fixtures:
        _assert_invalid(schema_path, _read_json(fixture))
