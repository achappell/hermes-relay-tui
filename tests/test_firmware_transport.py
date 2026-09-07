"""Host checks for the ESP32 display WebSocket transport seam."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
FIRMWARE_DIR = REPO_ROOT / "firmware" / "esp32-s3-touch-lcd-7"


def test_transport_component_exists_and_uses_the_display_state_endpoint() -> None:
    header = FIRMWARE_DIR / "main" / "include" / "ui_transport.h"
    source = FIRMWARE_DIR / "main" / "src" / "ui_transport.c"
    manifest = FIRMWARE_DIR / "main" / "idf_component.yml"
    cmake = (FIRMWARE_DIR / "main" / "CMakeLists.txt").read_text()

    assert header.exists()
    assert source.exists()
    assert manifest.exists()
    assert "ui_transport.c" in cmake
    assert "websocket" in cmake
    assert "esp_websocket_client" in manifest.read_text()
    source_text = source.read_text()
    assert "esp_websocket_client" in source_text
    assert 'UI_TRANSPORT_DISPLAY_PATH "/state"' in header.read_text()


def test_transport_reassembles_fragmented_json_and_enables_reconnect() -> None:
    source = (FIRMWARE_DIR / "main" / "src" / "ui_transport.c").read_text()

    assert "payload_offset" in source
    assert "payload_len" in source
    assert "data_len" in source
    assert "ui_snapshot_from_json" in source
    assert "reconnect_timeout_ms" in source
    assert "enable_close_reconnect" in source
