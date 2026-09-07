"""Host checks for the ESP32 display snapshot contract."""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
FIRMWARE_DIR = REPO_ROOT / "firmware" / "esp32-s3-touch-lcd-7"
SHARED_DISPLAY_DIR = REPO_ROOT / "shared" / "display"


def _compile_and_run(source: str) -> subprocess.CompletedProcess[str]:
    harness = Path(__file__).with_name("_snapshot_harness.c")
    binary = Path(__file__).with_name("_snapshot_harness")
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
                str(SHARED_DISPLAY_DIR),
                str(harness),
                str(FIRMWARE_DIR / "main" / "src" / "ui_snapshot.c"),
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


def test_snapshot_contract_maps_states_and_bounds_text() -> None:
    result = _compile_and_run(
        r'''
        #include <assert.h>
        #include <string.h>
        #include "ui_snapshot.h"

        int main(void) {
            ui_snapshot_t snapshot;
            assert(ui_snapshot_init(&snapshot));
            assert(snapshot.state == UI_DISPLAY_IDLE);
            assert(ui_display_state_from_name("speaking") == UI_DISPLAY_SPEAKING);
            assert(ui_display_state_from_name("prompt") == UI_DISPLAY_PROMPT);
            assert(ui_display_state_from_name("unknown") == UI_DISPLAY_UNKNOWN);

            assert(ui_snapshot_set_state(&snapshot, "speaking"));
            assert(snapshot.state == UI_DISPLAY_SPEAKING);
            assert(ui_snapshot_set_text(&snapshot, "answer", "Speaking"));
            assert(strcmp(snapshot.response_text, "answer") == 0);
            assert(strcmp(snapshot.status_text, "Speaking") == 0);

            char oversized[UI_SNAPSHOT_RESPONSE_TEXT_MAX + 20];
            memset(oversized, 'x', sizeof(oversized));
            oversized[sizeof(oversized) - 1] = '\0';
            assert(ui_snapshot_set_text(&snapshot, oversized, NULL));
            assert(strlen(snapshot.response_text) == UI_SNAPSHOT_RESPONSE_TEXT_MAX - 1);
            return 0;
        }
        '''
    )
    assert result.returncode == 0, result.stderr


def test_native_simulator_uses_shared_snapshot_ui_source() -> None:
    makefile = (FIRMWARE_DIR / "simulator" / "Makefile").read_text()
    cmake = (FIRMWARE_DIR / "main" / "CMakeLists.txt").read_text()

    assert "ui_snapshot.c" in makefile
    assert "ui_display.c" in makefile
    assert "ui_snapshot.c" in cmake
    assert "ui_display.c" in cmake


def test_esp_snapshot_parser_is_part_of_the_idf_component() -> None:
    parser = FIRMWARE_DIR / "main" / "src" / "ui_snapshot_json.c"
    cmake = (FIRMWARE_DIR / "main" / "CMakeLists.txt").read_text()

    assert parser.exists()
    assert "ui_snapshot_json.c" in cmake
    assert "json" in cmake
    assert "cJSON_Parse" in parser.read_text()
