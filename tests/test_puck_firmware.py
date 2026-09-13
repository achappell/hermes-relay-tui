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
    assert '"&token=" + puck_response::url_encode("${puck_device_token}")' in source
    assert "media_player.play_media" in source


def test_response_status_is_checked_after_idle_before_wake_resumes():
    root = Path(__file__).resolve().parents[1]
    source = (root / "firmware/respeaker-lite/respeaker-lite.yaml").read_text()
    config = yaml.load(source, Loader=yaml.BaseLoader)
    status_interval = next(
        item for item in config["interval"] if item["interval"] == "250ms"
    )
    status_action = next(
        action for action in status_interval["then"] if "if" in action
        and "http_request.get" in action["if"]["then"][0]
    )
    request = status_action["if"]["then"][0]["http_request.get"]

    assert request["id"] == "http_client"
    assert "/response-status?seq=" in request["url"]
    assert request["capture_response"] == "true"
    assert request["max_response_buffer_size"] == "128"
    assert "puck_response::note_status(response->status_code, body)" in (
        request["on_response"]["then"][0]["lambda"]
    )
    assert "puck_response::note_transport_failure()" in (
        request["on_error"]["then"][0]["lambda"]
    )
    response_header = (root / "firmware/respeaker-lite/puck_response.h").read_text()
    assert "STATUS_RETRY_INTERVAL_MS = 250" in response_header
    assert "STATUS_RETRY_WINDOW_MS = 2000" in response_header
    assert "REFUSAL_WATCHDOG_MS = 2000" in response_header

    idle_start = source.index("    on_idle:")
    idle_end = source.index("    volume_initial:", idle_start)
    idle = source[idle_start:idle_end]
    assert "puck_response::holds_wake()" in idle
    assert "puck_response::media_idle()" in idle
    assert idle.index("puck_response::media_idle()") < idle.index("id(mww).start()")

    assert "if (!puck_response::holds_wake() &&" in source
    response_begin = source.index("puck_response::begin(")
    response_url = source.index("/response?seq=")
    assert response_begin < response_url
    assert "audio-file://refused_sound" in (
        source[source.index("puck_response::refusal_pending()"):]
    )
    assert '#include "pcm_capture.h"' not in response_header


def test_respeaker_yaml_passes_esphome_config_generation():
    root = Path(__file__).resolve().parents[1]
    esphome = root / "venv-firmware/bin/esphome"
    if not esphome.is_file():
        pytest.skip("firmware ESPHome environment is not installed")
    result = subprocess.run(
        [str(esphome), "config", "firmware/respeaker-lite/respeaker-lite.yaml"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, "ESPHome rejected the Puck configuration"


def test_response_status_state_machine_retries_then_refuses(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the response state harness")

    hal_header = tmp_path / "esphome/core/hal.h"
    hal_header.parent.mkdir(parents=True)
    hal_header.write_text(
        "#pragma once\n"
        "#include <cstdint>\n"
        "extern uint32_t fake_millis;\n"
        "inline uint32_t millis() { return fake_millis; }\n"
    )
    log_header = tmp_path / "esphome/core/log.h"
    log_header.write_text(
        "#pragma once\n"
        "#define ESP_LOGD(...) do {} while (0)\n"
        "#define ESP_LOGI(...) do {} while (0)\n"
        "#define ESP_LOGW(...) do {} while (0)\n"
    )
    harness = tmp_path / "response_state.cpp"
    harness.write_text(
        textwrap.dedent(
            """
            #include "puck_response.h"
            #include <cassert>
            #include <cstdint>

            uint32_t fake_millis = 0;

            int main() {
              using namespace puck_response;

              begin(7);
              assert(holds_wake());
              media_idle();
              assert(poll_due());
              note_status(409, "");
              fake_millis = 249;
              assert(!poll_due());
              fake_millis = 250;
              assert(poll_due());
              note_status(409, "");
              fake_millis = 2000;
              note_status(409, "");
              assert(refusal_pending());
              refusal_started();
              media_idle();
              assert(ready_to_resume());
              wake_resumed();
              assert(state == State::IDLE);

              begin(8);
              media_idle();
              note_status(200, terminal_body(8, "complete"));
              assert(ready_to_resume());
              wake_resumed();
              assert(state == State::IDLE);

              begin(9);
              media_idle();
              note_transport_failure();
              assert(refusal_pending());
              refusal_started();
              media_idle();
              assert(ready_to_resume());
              wake_resumed();
              assert(state == State::IDLE);

              begin(10);
              media_idle();
              note_status(404, "");
              assert(refusal_pending());
              refusal_started();
              media_idle();
              assert(ready_to_resume());
              wake_resumed();

              begin(11);
              media_idle();
              note_status(200, terminal_body(11, "unavailable"));
              assert(refusal_pending());
              refusal_started();
              fake_millis = 3999;
              assert(!refusal_recovery_due());
              fake_millis = 4000;
              assert(refusal_recovery_due());
              refusal_recovered();
              assert(ready_to_resume());
              wake_resumed();
              assert(state == State::IDLE);

              assert(url_encode("a+b & c") == "a%2Bb%20%26%20c");
              return 0;
            }
            """
        )
    )
    executable = tmp_path / "response_state"
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


def test_wake_acknowledgement_finishes_before_capture_opens():
    yaml_source = (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml").read_text()
    capture_source = (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/pcm_capture.h").read_text()
    assert "inline void prepare(const std::string &wake_word)" in capture_source
    assert "inline void start_pending()" in capture_source
    prepare = yaml_source.index("wake_capture::prepare(wake_word)")
    acknowledgement = yaml_source.index('media_url: "audio-file://heard_sound"')
    delay = yaml_source.index("delay: 150ms")
    start = yaml_source.index("wake_capture::start_pending()")
    assert prepare < acknowledgement < delay < start


def test_wake_capture_acknowledgement_signal_covers_both_close_paths():
    source = (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/pcm_capture.h").read_text()
    assert "static bool last_capture_captured = false;" in source

    buffer_limit = source.index("wake capture reached the")
    vad_close = source.index("wake capture ended on VAD silence")
    assert "last_capture_captured = write_pos > 0;" in source[:buffer_limit]
    assert "last_capture_captured = write_pos > 0;" in source[vad_close - 300:vad_close]


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
