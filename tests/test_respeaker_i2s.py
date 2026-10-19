"""Fault-inject the actual vendored microphone, not a copied lifecycle model."""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_TESTS = ROOT / "tests/firmware"


def write_mic_stubs(directory):
    stub = FIRMWARE_TESTS / "respeaker_mic_stubs.h"
    for relative in (
        "esphome/core/component.h", "esphome/core/defines.h", "esphome/core/helpers.h",
        "esphome/core/hal.h", "esphome/core/log.h", "esphome/components/audio/audio.h",
        "esphome/components/microphone/microphone.h", "driver/i2s_std.h", "driver/i2s_pdm.h",
        "freertos/FreeRTOS.h", "freertos/event_groups.h", "freertos/semphr.h", "freertos/task.h",
        "esp_idf_version.h",
    ):
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f'#include "{stub}"\n')


def test_actual_microphone_lifecycle_faults_and_retry(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("native C++ compiler unavailable")
    write_mic_stubs(tmp_path)
    binary = tmp_path / "mic_lifecycle"
    compile_result = subprocess.run(
        [compiler, "-std=c++17", "-DUSE_ESP32", "-DSOC_I2S_SUPPORTS_PDM_RX=0",
         "-Wall", "-Wextra", "-Wno-unused-const-variable", "-Wno-unused-variable",
         "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
         "-I", str(tmp_path), "-I", str(ROOT), "-I", str(FIRMWARE_TESTS),
         str(FIRMWARE_TESTS / "respeaker_mic_lifecycle.cpp"), "-o", str(binary)],
        capture_output=True, text=True,
    )
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
