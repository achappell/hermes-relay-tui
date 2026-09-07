"""Native checks for the ESP adapter's shared display-rule boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
FIRMWARE_DIR = REPO_ROOT / "firmware" / "esp32-s3-touch-lcd-7"
SHARED_DISPLAY_DIR = REPO_ROOT / "shared" / "display"


def _compile_and_run(source: str) -> subprocess.CompletedProcess[str]:
    harness = Path(__file__).with_name("_firmware_ui_core_harness.c")
    binary = Path(__file__).with_name("_firmware_ui_core_harness")
    harness.write_text(source)
    try:
        compile_result = subprocess.run(
            [
                "cc",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(FIRMWARE_DIR / "main" / "include"),
                "-I",
                str(FIRMWARE_DIR / "simulator" / "include"),
                "-I",
                str(SHARED_DISPLAY_DIR),
                str(harness),
                str(FIRMWARE_DIR / "main" / "src" / "ui_snapshot.c"),
                str(FIRMWARE_DIR / "main" / "src" / "ui_display.c"),
                str(SHARED_DISPLAY_DIR / "display_rules.c"),
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


def test_esp_snapshot_adapter_feeds_shared_reducer_and_validates_touch_action() -> None:
    result = _compile_and_run(
        r'''
        #include <assert.h>
        #include <string.h>
        #include "display_rules.h"
        #include "ui_snapshot.h"

        int main(void) {
            ui_snapshot_t snapshot;
            assert(ui_snapshot_init(&snapshot));
            snapshot.sequence = 10;
            assert(ui_snapshot_set_state(&snapshot, "prompt"));
            snapshot.prompt.present = true;
            snapshot.prompt.can_choose = true;
            strcpy(snapshot.prompt.action_id, "sethome");
            snapshot.prompt.option_count = 2;
            strcpy(snapshot.prompt.options[0].id, "yes");
            strcpy(snapshot.prompt.options[1].id, "no");

            display_rules_snapshot_t rules_snapshot;
            assert(ui_snapshot_to_rules(&snapshot, &rules_snapshot));

            display_rules_reducer_t reducer;
            display_rules_init(&reducer);
            assert(display_rules_apply_snapshot(&reducer, &rules_snapshot) == DISPLAY_RULES_ACCEPTED);
            assert(display_rules_validate_choice(&reducer, "sethome", "yes") == DISPLAY_RULES_ACCEPTED);
            assert(display_rules_validate_choice(&reducer, "sethome", "later") == DISPLAY_RULES_UNKNOWN_CHOICE);

            rules_snapshot.sequence = 9;
            rules_snapshot.state = DISPLAY_RULES_IDLE;
            rules_snapshot.prompt.present = false;
            assert(display_rules_apply_snapshot(&reducer, &rules_snapshot) == DISPLAY_RULES_STALE);
            assert(display_rules_view(&reducer)->state == DISPLAY_RULES_PROMPT);
            return 0;
        }
        '''
    )
    assert result.returncode == 0, result.stderr


def test_firmware_builds_compile_the_shared_reducer_for_hardware_and_simulator() -> None:
    firmware_cmake = (FIRMWARE_DIR / "main" / "CMakeLists.txt").read_text()
    simulator_makefile = (FIRMWARE_DIR / "simulator" / "Makefile").read_text()
    simulator_cmake = (FIRMWARE_DIR / "simulator" / "CMakeLists.txt").read_text()

    assert "display_rules.c" in firmware_cmake
    assert "display_rules.c" in simulator_makefile
    assert "display_rules.c" in simulator_cmake
    assert "ui_snapshot.c" in simulator_cmake
    assert "ui_display.c" in simulator_cmake


def test_lvgl_surface_accepts_only_reducer_validated_prompt_actions() -> None:
    result = _compile_and_run(
        r'''
        #include <assert.h>
        #include <string.h>
        #include "ui_display.h"

        int main(void) {
            ui_snapshot_t snapshot;
            assert(ui_snapshot_init(&snapshot));
            snapshot.sequence = 4;
            assert(ui_snapshot_set_state(&snapshot, "prompt"));
            snapshot.prompt.present = true;
            snapshot.prompt.can_choose = true;
            strcpy(snapshot.prompt.action_id, "approve");
            snapshot.prompt.option_count = 1;
            strcpy(snapshot.prompt.options[0].id, "yes");

            assert(ui_display_init(NULL, NULL));
            assert(ui_display_set_connection_state(UI_DISPLAY_CONNECTION_ERROR) == DISPLAY_RULES_ACCEPTED);
            assert(ui_display_rules_view()->state == DISPLAY_RULES_ERROR);
            assert(ui_display_set_connection_state(UI_DISPLAY_CONNECTION_CONNECTED) == DISPLAY_RULES_ACCEPTED);
            assert(!ui_display_rules_view()->initialized);
            assert(ui_display_set_snapshot(&snapshot) == DISPLAY_RULES_ACCEPTED);
            assert(ui_display_validate_choice("approve", "yes") == DISPLAY_RULES_ACCEPTED);
            assert(ui_display_validate_choice("approve", "no") == DISPLAY_RULES_UNKNOWN_CHOICE);
            return 0;
        }
        '''
    )
    assert result.returncode == 0, result.stderr


def test_firmware_main_keeps_transport_events_out_of_lvgl_rendering() -> None:
    source = (FIRMWARE_DIR / "main" / "src" / "main.c").read_text()

    assert "s_pending_transport_state" in source
    assert "ui_display_set_connection_state" in source
    assert "ui_display_set_snapshot" in source


def test_esp_snapshot_parser_preserves_capability_gates_and_rejects_overlong_fields() -> None:
    source = (FIRMWARE_DIR / "main" / "src" / "ui_snapshot_json.c").read_text()

    assert "parse_capabilities" in source
    assert '"prompt.choose"' in source
    assert '"prompt.dismiss"' in source
    assert "copy_strict" in source


def test_touch_actions_use_the_shared_normalized_action_payload() -> None:
    header = (FIRMWARE_DIR / "main" / "include" / "ui_transport.h").read_text()
    source = (FIRMWARE_DIR / "main" / "src" / "ui_transport.c").read_text()
    main = (FIRMWARE_DIR / "main" / "src" / "main.c").read_text()

    assert "ui_transport_send_action" in header
    assert '"type"' in source and '"action"' in source
    assert '"schema"' in source and '"action_id"' in source and '"choice"' in source
    assert "esp_websocket_client_send_text" in source
    assert "transport_action_cb" in main


def test_native_simulator_advances_snapshot_sequences_for_demo_states() -> None:
    source = (FIRMWARE_DIR / "simulator" / "sdl_main.c").read_text()

    assert "s_demo_sequence" in source
    assert "s_demo_snapshot.sequence = ++s_demo_sequence" in source


def test_native_simulator_demo_keys_follow_legal_reducer_transitions() -> None:
    source = (FIRMWARE_DIR / "simulator" / "sdl_main.c").read_text()

    assert source.count("demo_snapshot(UI_DISPLAY_IDLE") >= 3
    assert "demo_snapshot(UI_DISPLAY_HEARD" in source
    assert "demo_snapshot(UI_DISPLAY_THINKING" in source
    assert "s_demo_snapshot.prompt.can_choose = true" in source
