"""Cross-target checks for the shared display fixtures and native reducer."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DISPLAY_DIR = REPO_ROOT / "shared" / "display"
FIXTURES_DIR = DISPLAY_DIR / "fixtures"
STATE_NAMES = (
    "idle",
    "heard",
    "listening",
    "thinking",
    "speaking",
    "buffering",
    "error",
    "disconnected",
    "prompt",
)
BUSY_STATES = {"listening", "thinking", "speaking", "buffering"}


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES_DIR / "snapshots" / name).read_text())


def _c_string(value: str) -> str:
    return json.dumps(value)


def _c_case(index: int, snapshot: dict[str, object]) -> str:
    state = str(snapshot["state"])
    prompt = snapshot.get("prompt")
    capabilities = snapshot.get("capabilities") or {}
    actions = capabilities.get("actions", []) if isinstance(capabilities, dict) else []
    prompt_setup = ""
    if isinstance(prompt, dict):
        options = prompt["options"]
        prompt_setup = "\n".join(
            [
                "    value.prompt.present = true;",
                f"    value.prompt.can_choose = {'true' if 'prompt.choose' in actions else 'false'};",
                f"    value.prompt.can_dismiss = {'true' if 'prompt.dismiss' in actions else 'false'};",
                f"    strcpy(value.prompt.action_id, {_c_string(str(prompt['action_id']))});",
                f"    value.prompt.option_count = {len(options)};",
                *[
                    f"    strcpy(value.prompt.options[{option_index}].id, {_c_string(str(option['id']))});"
                    for option_index, option in enumerate(options)
                ],
            ]
        )
    return f"""    value = empty_snapshot({snapshot['sequence']}, DISPLAY_RULES_{state.upper()});
{prompt_setup}
    run_case({index}, &value);
"""


def _compile_and_run(snapshots: list[dict[str, object]]) -> subprocess.CompletedProcess[str]:
    harness = Path(__file__).with_name("_display_conformance_harness.c")
    binary = Path(__file__).with_name("_display_conformance_harness")
    cases = "".join(_c_case(index, snapshot) for index, snapshot in enumerate(snapshots))
    harness.write_text(
        f'''
        #include <stdbool.h>
        #include <stdio.h>
        #include <string.h>
        #include "display_rules.h"

        static display_rules_snapshot_t empty_snapshot(unsigned int sequence, display_rules_state_t state) {{
            display_rules_snapshot_t value;
            memset(&value, 0, sizeof(value));
            value.schema = 1;
            value.sequence = sequence;
            value.state = state;
            return value;
        }}

        static void run_case(int index, const display_rules_snapshot_t *snapshot) {{
            display_rules_reducer_t reducer;
            display_rules_init(&reducer);
            display_rules_result_t result = display_rules_apply_snapshot(&reducer, snapshot);
            const display_rules_view_t *view = display_rules_view(&reducer);
            printf("%d,%d,%d,%u,%d,%d,%d,%d\\n", index, result, view->state, view->sequence,
                   view->is_busy, view->connection_healthy, view->can_choose, view->can_dismiss);
            }}

            int main(void) {{
                display_rules_snapshot_t value;
{cases}
                display_rules_reducer_t reducer;
            display_rules_snapshot_t current = empty_snapshot(20, DISPLAY_RULES_LISTENING);
            display_rules_snapshot_t stale = empty_snapshot(19, DISPLAY_RULES_IDLE);
            display_rules_init(&reducer);
            display_rules_apply_snapshot(&reducer, &current);
            printf("stale,%d,%d,%u\\n", display_rules_apply_snapshot(&reducer, &stale),
                   display_rules_view(&reducer)->state, display_rules_view(&reducer)->sequence);
            return 0;
        }}
        '''
    )
    try:
        compile_result = subprocess.run(
            [
                "cc",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(DISPLAY_DIR),
                str(harness),
                str(DISPLAY_DIR / "display_rules.c"),
                "-o",
                str(binary),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert compile_result.returncode == 0, compile_result.stderr
        return subprocess.run([str(binary)], check=False, capture_output=True, text=True)
    finally:
        harness.unlink(missing_ok=True)
        binary.unlink(missing_ok=True)


def test_every_valid_snapshot_fixture_matches_native_reducer_normalization() -> None:
    fixtures = sorted((FIXTURES_DIR / "snapshots").glob("*.json"))
    snapshots = [json.loads(path.read_text()) for path in fixtures]
    result = _compile_and_run(snapshots)

    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert len(lines) == len(snapshots) + 1

    for index, snapshot in enumerate(snapshots):
        fields = lines[index].split(",")
        assert int(fields[0]) == index
        assert int(fields[1]) == 0
        assert int(fields[2]) == STATE_NAMES.index(snapshot["state"]) + 1
        assert int(fields[3]) == snapshot["sequence"]
        assert bool(int(fields[4])) is (snapshot["state"] in BUSY_STATES)
        assert bool(int(fields[5])) is (snapshot["state"] not in {"error", "disconnected"})
        prompt = snapshot.get("prompt")
        actions = (snapshot.get("capabilities") or {}).get("actions", [])
        assert bool(int(fields[6])) is (prompt is not None and "prompt.choose" in actions)
        assert bool(int(fields[7])) is (prompt is not None and "prompt.dismiss" in actions)


def test_stale_fixture_and_native_reducer_agree_on_ordering() -> None:
    stale_case = json.loads((FIXTURES_DIR / "sequences" / "stale.json").read_text())
    result = _compile_and_run([stale_case["snapshot"]])

    assert result.returncode == 0, result.stderr
    stale_fields = result.stdout.strip().splitlines()[-1].split(",")
    assert stale_fields == ["stale", "1", "3", "20"]
    assert stale_case["expected"] == {"classification": "stale"}


def test_prompt_without_dismiss_capability_is_rejected_by_native_rules() -> None:
    snapshot = _fixture("prompt_choose_only.json")
    result = _compile_and_run([snapshot])

    assert result.returncode == 0, result.stderr
    fields = result.stdout.strip().splitlines()[0].split(",")
    assert fields[6:8] == ["1", "0"]
