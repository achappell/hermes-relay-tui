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


def test_follow_up_capture_is_bounded_and_empty_upload_is_explicit():
    capture_source = (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/pcm_capture.h").read_text()
    response_source = (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/puck_response.h").read_text()
    yaml_source = (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml").read_text()

    assert "CAPTURE_LISTEN_TIMEOUT_MS" in capture_source
    assert "inline bool start_follow_up()" in capture_source
    assert "last_upload_failed" in capture_source
    assert "std::max<size_t>(" in capture_source
    assert "follow_up_pending" in response_source
    assert "FOLLOW_UP_CAPTURING" in response_source
    assert "wake_capture::start_follow_up()" in yaml_source
    assert "puck_response::follow_up_started()" in yaml_source
    assert "puck_response::follow_up_capture_failed()" in yaml_source
    assert "/follow-up-admission?seq=" in yaml_source
    no_speech_deadline = capture_source[
        capture_source.index("if (follow_up_capture && !speech_seen)"):capture_source.index(
            "if (silence_start_ms == 0)",
            capture_source.index("if (follow_up_capture && !speech_seen)"),
        )
    ]
    assert "write_pos = 0;" in no_speech_deadline
    assert "last_capture_captured = false;" in no_speech_deadline


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


def test_follow_up_no_speech_discards_buffered_pcm_before_empty_upload(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the capture-state harness")

    (tmp_path / "esphome/core").mkdir(parents=True)
    (tmp_path / "esphome/components/http_request").mkdir(parents=True)
    (tmp_path / "freertos").mkdir()
    (tmp_path / "esp_heap_caps.h").write_text(
        "#pragma once\n"
        "#include <cstddef>\n"
        "#include <cstdint>\n"
        "#include <cstdlib>\n"
        "enum { MALLOC_CAP_SPIRAM = 1, MALLOC_CAP_INTERNAL = 2 };\n"
        "inline void *heap_caps_malloc(std::size_t size, int) { return std::malloc(size); }\n"
        "inline std::uint32_t heap_caps_get_free_size(int) { return 200000; }\n"
        "inline std::uint32_t heap_caps_get_minimum_free_size(int) { return 200000; }\n"
    )
    (tmp_path / "esphome/core/alloc_helpers.h").write_text("#pragma once\n")
    (tmp_path / "esphome/core/application.h").write_text(
        "#pragma once\n"
        "namespace esphome {\n"
        "struct Application { void safe_reboot() {} void feed_wdt() {} };\n"
        "inline Application App;\n"
        "}\n"
    )
    (tmp_path / "esphome/core/hal.h").write_text(
        "#pragma once\n"
        "#include <cstdint>\n"
        "extern std::uint32_t fake_millis;\n"
        "inline std::uint32_t millis() { return fake_millis; }\n"
    )
    (tmp_path / "esphome/core/log.h").write_text(
        "#pragma once\n"
        "#define ESP_LOGD(...) do {} while (0)\n"
        "#define ESP_LOGE(...) do {} while (0)\n"
        "#define ESP_LOGI(...) do {} while (0)\n"
        "#define ESP_LOGW(...) do {} while (0)\n"
    )
    (tmp_path / "freertos/FreeRTOS.h").write_text(
        "#pragma once\n"
        "#define pdMS_TO_TICKS(value) (value)\n"
    )
    (tmp_path / "freertos/task.h").write_text(
        "#pragma once\n"
        "inline void vTaskDelay(unsigned int) {}\n"
    )
    (tmp_path / "esphome/components/http_request/http_request.h").write_text(
        "#pragma once\n"
        "#include <string>\n"
        "#include <vector>\n"
        "namespace esphome::http_request {\n"
        "struct Header { const char *name; const char *value; };\n"
        "struct Response { int status_code = 200; void end() {} };\n"
        "class HttpRequestComponent {\n"
        " public:\n"
        "  std::vector<std::string> urls;\n"
        "  std::vector<std::string> bodies;\n"
        "  Response response;\n"
        "  Response *post(const std::string &url, const std::string &body, const std::vector<Header> &) {\n"
        "    urls.push_back(url);\n"
        "    bodies.push_back(body);\n"
        "    return &response;\n"
        "  }\n"
        "  Response *post(const std::string &url, const std::string &body) {\n"
        "    return post(url, body, {});\n"
        "  }\n"
        "};\n"
        "}\n"
    )
    (tmp_path / "esphome/core/alloc_helpers.h").write_text(
        "#pragma once\n"
        "#include <cstddef>\n"
        "#include <cstdint>\n"
        "#include <string>\n"
        "namespace esphome {\n"
        "inline std::string base64_encode(const std::uint8_t *, std::size_t) { return {}; }\n"
        "}\n"
    )
    harness = tmp_path / "capture_state.cpp"
    harness.write_text(
        textwrap.dedent(
            """
            #include "pcm_capture.h"
            #include <cassert>
            #include <cstdint>

            std::uint32_t fake_millis = 0;

            int main() {
              using namespace pcm_capture::wake_capture;
              puck_identity::setup("configured");
              setup();

              auto finish_refusal = []() {
                puck_response::refusal_started();
                puck_response::media_idle();
                puck_response::wake_resumed();
              };

              // Denial and a response for another sequence leave capture shut.
              assert(puck_response::begin_home_admission(1));
              puck_response::note_home_admission(200, "denied:1");
              prepare("hey missy");
              start_pending();
              assert(last_wake_refused);
              assert(!wake_pending && !capturing && !capture_pending_upload);
              esphome::http_request::HttpRequestComponent denied_client;
              upload(&denied_client, "http://bridge/upload", "token");
              assert(denied_client.urls.empty());
              finish_refusal();

              assert(puck_response::begin_home_admission(2));
              puck_response::note_home_admission(200, "admitted:99");
              prepare("hey missy");
              start_pending();
              assert(last_wake_refused);
              assert(!wake_pending && !capturing && !capture_pending_upload);
              finish_refusal();

              assert(puck_response::begin_home_admission(3));
              puck_response::note_home_admission(200, "admitted:3");
              prepare("hey missy");
              assert(wake_pending && !capturing);
              start_pending();
              assert(capturing && !wake_pending);
              const uint8_t wake_pcm[] = {1, 2, 3, 4};
              write(wake_pcm, sizeof(wake_pcm));
              capturing = false;
              capture_done = true;
              capture_pending_upload = true;
              esphome::http_request::HttpRequestComponent wake_client;
              upload(&wake_client, "http://bridge/upload", "token");
              assert(wake_client.urls.size() == 1);
              assert(wake_client.bodies.front().size() == sizeof(wake_pcm));
              assert(last_upload_delivered);

              puck_response::response_seq = 3;
              puck_response::state = puck_response::State::FOLLOW_UP_PENDING;
              assert(!puck_response::can_start_follow_up_capture());
              assert(!start_follow_up());
              assert(puck_response::begin_follow_up_admission(3));
              puck_response::note_follow_up_admission(200, "admitted:99");
              assert(!puck_response::can_start_follow_up_capture());
              assert(!start_follow_up());
              // Reset the refused follow-up window to model a later response.
              puck_response::state = puck_response::State::FOLLOW_UP_PENDING;
              assert(puck_response::begin_follow_up_admission(3));
              puck_response::note_follow_up_admission(200, "admitted:3");
              assert(start_follow_up());
              puck_response::follow_up_started();
              assert(puck_response::follow_up_capturing());

              const std::uint8_t quiet_frames[] = {1, 2, 3, 4, 5, 6, 7, 8};
              write(quiet_frames, sizeof(quiet_frames));
              assert(write_pos == sizeof(quiet_frames));

              fake_millis = CAPTURE_LISTEN_TIMEOUT_MS;
              tick(false);
              assert(!capturing);
              assert(capture_done);
              assert(capture_pending_upload);
              assert(write_pos == 0);
              assert(!last_capture_captured);

              esphome::http_request::HttpRequestComponent client;
              upload(&client, "http://bridge/upload", "token");
              assert(client.bodies.size() == 1);
              assert(client.bodies.front().empty());
              assert(client.urls.front().find("total=1") != std::string::npos);
              assert(last_upload_delivered);
              return 0;
            }
            """
        )
    )
    executable = tmp_path / "capture_state"
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
        "#define ESP_LOGE(...) do {} while (0)\n"
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

              assert(!can_start_wake_capture());
              assert(begin_home_admission(6));
              note_home_admission(200, "admitted:6");
              assert(can_start_wake_capture());
              int prepared = 0;
              int cancelled = 0;
              dispatch_wake_capture(
                  can_start_wake_capture(),
                  [&]() { ++prepared; },
                  [&]() { ++cancelled; });
              dispatch_wake_capture(
                  false,
                  [&]() { ++prepared; },
                  [&]() { ++cancelled; });
              assert(prepared == 1);
              assert(cancelled == 1);
              assert(consume_home_admission());
              assert(!can_start_wake_capture());

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
              assert(follow_up_pending());
              assert(begin_follow_up_admission(8));
              note_follow_up_admission(200, "admitted:8");
              follow_up_started();
              assert(follow_up_capturing());
              begin(9);
              media_idle();
              note_status(200, terminal_body(9, "silent"));
              assert(ready_to_resume());
              wake_resumed();
              assert(state == State::IDLE);

              begin(10);
              media_idle();
              note_transport_failure();
              assert(refusal_pending());
              refusal_started();
              media_idle();
              assert(ready_to_resume());
              wake_resumed();
              assert(state == State::IDLE);

              begin(11);
              media_idle();
              note_status(404, "");
              assert(refusal_pending());
              refusal_started();
              media_idle();
              assert(ready_to_resume());
              wake_resumed();

              begin(12);
              media_idle();
              note_status(200, terminal_body(12, "unavailable"));
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

              begin(13);
              media_idle();
              note_status(200, home_admission_terminal_body(13));
              assert(needs_home_admission());
              assert(refusal_pending());
              refusal_started();
              media_idle();
              wake_resumed();
              assert(!can_start_wake_capture());

              assert(begin_home_admission(14));
              assert(home_admission_in_flight());
              note_home_admission(200, "denied:14");
              assert(needs_home_admission());
              assert(refusal_pending());
              refusal_started();
              media_idle();
              wake_resumed();

              assert(begin_home_admission(15));
              note_home_admission(200, "admitted:15");
              assert(!needs_home_admission());
              assert(home_admission_granted());
              assert(can_start_wake_capture());
              consume_home_admission();
              assert(!home_admission_granted());

              upload_failed(16);
              assert(refusal_pending());
              assert(response_seq == 16);
              refusal_started();
              media_idle();
              wake_resumed();
              assert(state == State::IDLE);

              begin(18);
              media_idle();
              note_status(200, terminal_body(18, "complete"));
              assert(begin_follow_up_admission(18));
              note_follow_up_admission(200, "admitted:18");
              follow_up_started();
              assert(follow_up_capturing());
              upload_failed(19);
              assert(refusal_pending());
              assert(response_seq == 18);
              refusal_started();
              media_idle();
              wake_resumed();

              puck_identity::setup("token");
              home_admission_needed = true;
              assert(begin_home_admission(17));
              note_home_admission(200, "identity_rejected:17");
              assert(puck_identity::state == puck_identity::State::UNAUTHORIZED);
              assert(refusal_pending());

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
    wake = yaml_source.split("  on_wake_word_detected:\n", 1)[1].split(
        "# Lightweight health telemetry", 1
    )[0]
    admission = wake.index("/wake-admission?seq=")
    prepare = wake.index("wake_capture::prepare(wake_word)")
    acknowledgement = wake.index('media_url: "audio-file://heard_sound"')
    delay = wake.index("delay: 150ms")
    start = wake.index("wake_capture::start_pending()")
    assert admission < prepare < acknowledgement < delay < start
    assert "puck_response::begin_home_admission(" in wake
    assert "puck_response::dispatch_wake_capture(" in wake
    assert "puck_response::can_start_wake_capture()" in wake
    assert 'puck_home_transport: "false"' in yaml_source
    assert "lambda: return ${puck_home_transport};" in wake
    assert wake.count("wake_capture::prepare(wake_word)") == 2
    assert "puck_response::needs_home_admission()" not in wake
    assert "!pcm_capture::wake_capture::capturing" in wake
    assert "!pcm_capture::wake_capture::capture_pending_upload" in wake
    assert "[&]() { pcm_capture::wake_capture::cancel_pending(); }" in wake
    assert "puck_response::upload_failed(" in yaml_source


def test_home_admission_automation_wires_response_and_transport_failure_callbacks():
    yaml_source = (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml").read_text()
    wake = yaml_source.split("  on_wake_word_detected:\n", 1)[1].split(
        "# Lightweight health telemetry", 1
    )[0]
    callback_block = (
        "on_response:\n"
        "                            then:\n"
        "                              - lambda: puck_response::note_home_admission(response->status_code, body);\n"
        "                          on_error:\n"
        "                            then:\n"
        "                              - lambda: puck_response::note_home_admission_transport_failure();"
    )

    assert "/wake-admission?seq=" in wake
    assert callback_block in wake


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
