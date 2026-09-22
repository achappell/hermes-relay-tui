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
        # The voice doorway's own observed phases are appended, never
        # inserted: every target pins the earlier positions.
        "transcribing",
        "complete",
    ]
    assert {"type", "schema", "sequence", "state", "response_text"} <= set(
        schema["required"]
    )
    assert schema["additionalProperties"] is True
    assert "capabilities" in schema["properties"]
    # What the room said and what Hermes answered are separate fields, and a
    # snapshot without a transcript is still a valid snapshot.
    assert schema["properties"]["transcript_text"]["type"] == "string"
    assert "transcript_text" not in schema["required"]


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


def test_display_action_schema_covers_freshness_bound_typed_choice() -> None:
    action = _read_json(FIXTURES_DIR / "actions" / "typed_choice_explore.json")

    _assert_valid(CONTRACT_DIR / "display_action.schema.json", action)
    assert action["operation"] == "explore"
    assert action["option_id"] == "inspect"
    assert action["object_id"] == "home-choice-1"
    assert action["freshness"] == "home-freshness-1"


def test_invalid_display_actions_are_rejected() -> None:
    schema_path = CONTRACT_DIR / "display_action.schema.json"
    fixtures = sorted((FIXTURES_DIR / "invalid-actions").glob("*.json"))

    assert fixtures
    for fixture in fixtures:
        _assert_invalid(schema_path, _read_json(fixture))


def test_coalesced_host_publisher_snapshots_reach_c_reducer(tmp_path):
    """A real one-slot subscriber skips phases; its JSON must still paint."""
    import asyncio
    import subprocess
    import pytest
    from home_display.state import DisplayStatePublisher

    async def collect():
        publisher = DisplayStatePublisher()
        stream = publisher.subscribe()
        result = [await anext(stream)]
        publisher.publish(state="error")
        result.append(await anext(stream))
        publisher.publish(state="idle")
        publisher.publish(state="heard")
        result.append(await anext(stream))
        publisher.publish(state="listening")
        result.append(await anext(stream))
        publisher.publish(state="thinking")
        publisher.publish(state="complete", response_text="Answer preserved")
        result.append(await anext(stream))
        await stream.aclose()
        return result

    snapshots = asyncio.run(collect())
    root = CONTRACT_DIR.parents[1]
    firmware = root/'firmware/esp32-s3-touch-lcd-7/main'
    cjson = Path.home()/'.platformio/packages/framework-espidf/components/json/cJSON'
    if not (cjson/'cJSON.c').exists():
        pytest.skip('ESP-IDF cJSON unavailable')
    source = '''#include <assert.h>
#include "ui_snapshot.h"
int main(void) {
 display_rules_reducer_t reducer;display_rules_init(&reducer);
 ui_snapshot_t snapshot;display_rules_snapshot_t rules;
'''
    for snapshot in snapshots:
        wire = json.dumps(json.dumps(snapshot.to_dict()))
        source += f'assert(ui_snapshot_from_json({wire}, &snapshot));\n'
        source += 'assert(ui_snapshot_to_rules(&snapshot,&rules));assert(display_rules_apply_snapshot(&reducer,&rules)==DISPLAY_RULES_ACCEPTED);\n'
    source += '''assert(display_rules_apply_snapshot(&reducer,&rules)==DISPLAY_RULES_STALE);
return 0;}
'''
    harness, binary = tmp_path/'publisher.c', tmp_path/'publisher'
    harness.write_text(source)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',
                    '-I',str(firmware/'include'),'-I',str(CONTRACT_DIR),'-I',str(cjson),
                    str(harness),str(firmware/'src/ui_snapshot.c'),str(firmware/'src/ui_snapshot_json.c'),
                    str(CONTRACT_DIR/'display_rules.c'),str(cjson/'cJSON.c'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
