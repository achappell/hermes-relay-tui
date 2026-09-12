import shutil
import subprocess
import textwrap
import wave
from pathlib import Path

import pytest
import yaml


def test_stop_button_has_a_defined_unpressed_level():
    path = Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml"
    config = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    button = next(item for item in config["binary_sensor"] if item["id"] == "user_button")
    assert button["pin"]["inverted"] == "true"
    assert button["pin"].get("mode", {}).get("pullup") == "true"
    assert button["on_press"] == [{"media_player.stop": "puck_media_player"}]


def test_local_status_audio_assets_are_buildable_wavs():
    root = Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/sounds"
    for name in ("refused.wav", "heard.wav"):
        path = root / name
        assert path.is_file(), f"missing committed firmware asset: {path}"
        with wave.open(str(path), "rb") as wav:
            assert wav.getframerate() == 16000
            assert wav.getnchannels() == 1
            assert wav.getsampwidth() == 2
            assert wav.getnframes() > 0
            if name == "heard.wav":
                assert wav.getnframes() / wav.getframerate() <= 0.1


def test_response_handoff_uses_the_confirmed_sequence_and_query_token():
    source = (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml").read_text()
    assert "last_upload_delivered" in source
    assert "/response?seq=" in source
    assert '"&token=${puck_device_token}"' in source
    assert "media_player.play_media" in source


def test_wake_acknowledgement_finishes_before_capture_opens():
    yaml_source = (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml").read_text()
    capture_source = (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/pcm_capture.h").read_text()
    assert "last_capture_captured" not in capture_source
    assert "inline void prepare(const std::string &wake_word)" in capture_source
    assert "inline void start_pending()" in capture_source
    prepare = yaml_source.index("wake_capture::prepare(wake_word)")
    acknowledgement = yaml_source.index('media_url: "audio-file://heard_sound"')
    delay = yaml_source.index("delay: 150ms")
    start = yaml_source.index("wake_capture::start_pending()")
    assert prepare < acknowledgement < delay < start


def test_speaker_volume_matches_the_documented_room_safety_policy():
    path = Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml"
    config = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    player = next(item for item in config["media_player"] if item["id"] == "puck_media_player")
    assert player["volume_initial"] == "0.25"
    assert player["volume_max"] == "0.80"


def test_rolling_pcm_capture_checks_identity_before_recording():
    source = (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/pcm_capture.h").read_text()
    start = source.index("inline void start()")
    write = source.index("inline void write(const uint8_t *data, size_t len)")
    rolling_capture = source[start:write]
    assert "puck_identity::may_capture()" in rolling_capture
    write_end = source.index("// Constructing a single std::string", write)
    assert "puck_identity::may_capture()" in source[write:write_end]


def test_wake_upload_aborts_a_rejected_chunk_before_the_generic_breaker():
    source = (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/pcm_capture.h").read_text()
    upload_start = source.index("inline void upload(esphome::http_request::HttpRequestComponent")
    upload_end = source.index("}  // namespace wake_capture", upload_start)
    upload = source[upload_start:upload_end]
    refusal_break = upload.index("if (client_rejected)")
    generic_breaker = upload.index("if (consecutive_failures >= 2)")
    assert refusal_break < generic_breaker
    assert "puck_identity::note_upload_status(status);" in upload


def test_identity_header_fail_closes_4xx_but_degrades_on_server_or_transport_failure(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the firmware identity harness")

    log_header = tmp_path / "esphome/core/log.h"
    log_header.parent.mkdir(parents=True)
    log_header.write_text(
        "#pragma once\n"
        "#define ESP_LOGE(...) do {} while (0)\n"
        "#define ESP_LOGI(...) do {} while (0)\n"
        "#define ESP_LOGW(...) do {} while (0)\n"
    )
    harness = tmp_path / "identity_gate.cpp"
    harness.write_text(
        textwrap.dedent(
            """
            #include "puck_identity.h"
            #include <cassert>

            int main() {
              puck_identity::setup("configured");
              assert(puck_identity::state == puck_identity::State::AUTHORIZED);
              assert(puck_identity::may_capture());

              puck_identity::note_upload_status(503);
              assert(puck_identity::state == puck_identity::State::DEGRADED);
              assert(puck_identity::may_capture());

              puck_identity::note_upload_status(-1);
              assert(puck_identity::state == puck_identity::State::DEGRADED);
              assert(puck_identity::may_capture());

              puck_identity::note_upload_status(200);
              assert(puck_identity::state == puck_identity::State::AUTHORIZED);

              puck_identity::note_upload_status(403);
              assert(puck_identity::state == puck_identity::State::UNAUTHORIZED);
              assert(!puck_identity::may_capture());

              return 0;
            }
            """
        )
    )
    executable = tmp_path / "identity_gate"
    compile_result = subprocess.run(
        [
            compiler,
            "-std=c++17",
            f"-I{tmp_path}",
            f"-I{Path(__file__).resolve().parents[1] / 'firmware/respeaker-lite'}",
            str(harness),
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    run_result = subprocess.run([str(executable)], capture_output=True, text=True)
    assert run_result.returncode == 0, run_result.stderr
