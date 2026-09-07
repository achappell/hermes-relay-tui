from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIRMWARE_DIR = REPO_ROOT / "firmware" / "esp32-s3-touch-lcd-7"


def test_firmware_files_exist():
    expected_files = [
        FIRMWARE_DIR / "CMakeLists.txt",
        FIRMWARE_DIR / "sdkconfig.defaults",
        FIRMWARE_DIR / "platformio.ini",
        FIRMWARE_DIR / "README.md",
        FIRMWARE_DIR / "main" / "CMakeLists.txt",
        FIRMWARE_DIR / "main" / "include" / "board_config.h",
        FIRMWARE_DIR / "main" / "include" / "bsp_lcd.h",
        FIRMWARE_DIR / "main" / "include" / "bsp_touch.h",
        FIRMWARE_DIR / "main" / "include" / "bsp_io_expander.h",
        FIRMWARE_DIR / "main" / "include" / "ui_test.h",
        FIRMWARE_DIR / "main" / "include" / "lv_conf.h",
        FIRMWARE_DIR / "main" / "src" / "main.c",
        FIRMWARE_DIR / "main" / "src" / "bsp_lcd.c",
        FIRMWARE_DIR / "main" / "src" / "bsp_touch.c",
        FIRMWARE_DIR / "main" / "src" / "bsp_io_expander.c",
        FIRMWARE_DIR / "main" / "src" / "ui_test.c",
    ]
    for file_path in expected_files:
        assert file_path.exists(), f"Missing firmware file: {file_path}"


def test_board_config_timings_and_frame_rate():
    board_config_path = FIRMWARE_DIR / "main" / "include" / "board_config.h"
    content = board_config_path.read_text()

    # Find all definitions for 7B (second match in if-else block)
    h_res_matches = re.findall(r"BOARD_LCD_H_RES\s+(\d+)", content)
    v_res_matches = re.findall(r"BOARD_LCD_V_RES\s+(\d+)", content)
    pclk_matches = re.findall(r"BOARD_LCD_PIXEL_CLOCK_HZ\s+\((\d+)\s*\*\s*1000\s*\*\s*1000\)", content)
    hpw_matches = re.findall(r"BOARD_LCD_HSYNC_PULSE_WIDTH\s+(\d+)", content)
    hbp_matches = re.findall(r"BOARD_LCD_HSYNC_BACK_PORCH\s+(\d+)", content)
    hfp_matches = re.findall(r"BOARD_LCD_HSYNC_FRONT_PORCH\s+(\d+)", content)
    vpw_matches = re.findall(r"BOARD_LCD_VSYNC_PULSE_WIDTH\s+(\d+)", content)
    vbp_matches = re.findall(r"BOARD_LCD_VSYNC_BACK_PORCH\s+(\d+)", content)
    vfp_matches = re.findall(r"BOARD_LCD_VSYNC_FRONT_PORCH\s+(\d+)", content)

    # 7B is the default (index 1)
    h_res = int(h_res_matches[1])
    v_res = int(v_res_matches[1])
    pclk = int(pclk_matches[1]) * 1_000_000
    hpw = int(hpw_matches[1])
    hbp = int(hbp_matches[1])
    hfp = int(hfp_matches[1])
    vpw = int(vpw_matches[1])
    vbp = int(vbp_matches[1])
    vfp = int(vfp_matches[1])

    assert h_res == 1024
    assert v_res == 600
    assert pclk >= 16_000_000

    total_h = h_res + hpw + hbp + hfp
    total_v = v_res + vpw + vbp + vfp
    total_pixels_per_frame = total_h * total_v

    assert total_pixels_per_frame > (h_res * v_res)

    fps = pclk / total_pixels_per_frame
    # Assert refresh rate is within standard 18Hz..65Hz range for LCD panel
    assert 18.0 <= fps <= 65.0, f"Calculated FPS {fps} out of range"


def test_board_config_pin_conflicts():
    board_config_path = FIRMWARE_DIR / "main" / "include" / "board_config.h"
    content = board_config_path.read_text()

    # Find all GPIO pin definitions
    matches = re.findall(r"BOARD_[A-Z0-9_]+PIN[A-Z0-9_]*\s+GPIO_NUM_(\d+)", content)
    used_pins = [int(pin) for pin in matches]

    # Every mapped pin should be unique (no hardware GPIO collisions)
    assert len(used_pins) == len(set(used_pins)), f"Found duplicate GPIO pin mappings: {used_pins}"
    assert len(used_pins) >= 20, f"Expected at least 20 hardware pin definitions, got {len(used_pins)}"


def test_psram_memory_budget():
    h_res = 1024
    v_res = 600
    bytes_per_pixel = 2  # 16-bit RGB565
    num_buffers = 2       # Double buffer

    frame_buffer_bytes = h_res * v_res * bytes_per_pixel
    total_fb_bytes = frame_buffer_bytes * num_buffers

    psram_total_bytes = 8 * 1024 * 1024  # 8MB Octal PSRAM
    psram_headroom_bytes = psram_total_bytes - total_fb_bytes

    assert frame_buffer_bytes == 1_228_800
    assert total_fb_bytes == 2_457_600
    # Headroom should be > 5.5MB for LVGL widgets, audio buffers, and networking
    assert psram_headroom_bytes >= 5_500_000


def test_sdkconfig_and_platformio_config():
    sdkconfig_path = FIRMWARE_DIR / "sdkconfig.defaults"
    sdk_content = sdkconfig_path.read_text()

    assert 'CONFIG_IDF_TARGET="esp32s3"' in sdk_content
    assert "CONFIG_SPIRAM=y" in sdk_content
    assert "CONFIG_SPIRAM_MODE_OCT=y" in sdk_content
    assert "CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y" in sdk_content
    assert "CONFIG_LV_COLOR_DEPTH_16=y" in sdk_content

    pio_path = FIRMWARE_DIR / "platformio.ini"
    pio_content = pio_path.read_text()

    assert "esp32-s3-touch-lcd-7b" in pio_content
    assert "esp32-s3-devkitc-1" in pio_content
    assert "board_build.psram_type = opi" in pio_content


def test_simulator_html_content():
    simulator_path = FIRMWARE_DIR / "simulator.py"
    assert simulator_path.exists()
    content = simulator_path.read_text()

    assert "1024x600" in content or "1024×600" in content
    assert "GT911" in content
    assert "btn-tl" in content and "btn-tr" in content and "btn-bl" in content and "btn-br" in content
    assert "touch-pointer" in content

