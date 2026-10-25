import re
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


def _write_capture_stubs(tmp_path):
    """Host stand-ins for the ESP-IDF/ESPHome headers pcm_capture.h includes."""
    (tmp_path / "puck_audio_wiring_stubs.h").write_text(textwrap.dedent(r"""
        #pragma once
        #include "puck_audio_handoff.h"
        #include <cstdint>
        #include <string>
        namespace media_player {
        enum MediaPlayerState { MEDIA_PLAYER_STATE_IDLE, MEDIA_PLAYER_STATE_ANNOUNCING };
        }
        namespace media_source {
        enum class MediaSourceState { IDLE, READING, ERROR };
        enum class MediaSourceCommand { STOP };
        }
        namespace puck_firmware_fixture {
        struct VADSnapshot {
          bool valid = false, detected = false;
          std::uint32_t generation = 0;
        };
        struct Detector {
          bool running = true, stop_completes = true;
          unsigned starts = 0, stops = 0, diagnostic_starts = 0, diagnostic_finishes = 0;
          VADSnapshot vad;
          bool is_running() const { return running; }
          void start() { ++starts; running = true; }
          void stop() { ++stops; if (stop_completes) running = false; }
          VADSnapshot get_vad_snapshot() const { return vad; }
          bool get_vad_state() const { return vad.valid && vad.detected; }
          void begin_capture_diagnostics() { ++diagnostic_starts; }
          void finish_capture_diagnostics() { ++diagnostic_finishes; }
        };
        struct OutputDevice {
          bool stopped = true, buffered = false, failed = false;
          std::uint32_t generation = 0, completed = 0, errors = 0;
          std::uint32_t (*error_reader)() = nullptr;
          void (*audio_callback)(std::uint32_t, std::int64_t) = nullptr;
          bool is_stopped() const { return stopped; }
          bool has_buffered_data() const { return buffered; }
          bool is_failed() const { return failed; }
          std::uint32_t playback_generation() const { return generation; }
          std::uint32_t completed_playback_generation() const { return completed; }
          std::uint32_t playback_error_generation() const { return errors; }
          void set_output_error_generation_callback(std::uint32_t (*reader)()) { error_reader = reader; }
          void add_audio_output_callback(void (*callback)(std::uint32_t, std::int64_t)) { audio_callback = callback; }
          struct Stats { std::uint32_t played_ms = 0, underruns = 0, longest_underrun_ms = 0, longest_underrun_at_ms = 0; } stats;
          unsigned stats_resets = 0;
          Stats playback_stats() const { return stats; }
          void reset_playback_stats() { ++stats_resets; stats = Stats{}; }
        };
        struct WifiFixture {
          float rssi = -60.0f;
          float wifi_rssi() const { return rssi; }
        };
        struct MediaPlayer {
          media_player::MediaPlayerState state = media_player::MEDIA_PLAYER_STATE_IDLE;
          std::string last_media_url;
          bool failed = false;
          bool is_failed() const { return failed; }
        };
        struct HttpSource {
          media_source::MediaSourceState state = media_source::MediaSourceState::IDLE;
          unsigned direct_stops = 0;
          media_source::MediaSourceState get_state() const { return state; }
          // Real micro-decoder stop() moves FAILED to IDLE.
          void handle_command(media_source::MediaSourceCommand) {
            ++direct_stops;
            if (state == media_source::MediaSourceState::ERROR) state = media_source::MediaSourceState::IDLE;
          }
        };
        inline Detector mww;
        inline WifiFixture wifi_fixture;
        inline OutputDevice puck_resampler, puck_speaker;
        inline MediaPlayer puck_media_player;
        inline HttpSource puck_http_source, puck_local_source;
        }
        namespace wifi {
        inline puck_firmware_fixture::WifiFixture *global_wifi_component = &puck_firmware_fixture::wifi_fixture;
        }
    """))
    (tmp_path / "esphome/core").mkdir(parents=True)
    (tmp_path / "esphome/components/http_request").mkdir(parents=True)
    (tmp_path / "freertos").mkdir()
    (tmp_path / "esp_heap_caps.h").write_text(
        "#pragma once\n"
        "#include <cstddef>\n"
        "#include <cstdint>\n"
        "#include <cstdlib>\n"
        "enum { MALLOC_CAP_SPIRAM = 1, MALLOC_CAP_INTERNAL = 2 };\n"
        "inline int fake_heap_allocations = 0;\n"
        "inline void *heap_caps_malloc(std::size_t size, int) {\n"
        "  ++fake_heap_allocations;\n"
        "  return std::malloc(size);\n"
        "}\n"
        "inline std::uint32_t heap_caps_get_free_size(int) { return 200000; }\n"
        "inline std::uint32_t heap_caps_get_minimum_free_size(int) { return 200000; }\n"
    )
    (tmp_path / "esphome/core/application.h").write_text(
        "#pragma once\n"
        "namespace esphome {\n"
        "struct Application { void safe_reboot() {} void feed_wdt() {} };\n"
        "inline Application App;\n"
        "}\n"
        '#include "puck_audio_wiring_stubs.h"\n'
    )
    (tmp_path / "esphome/core/hal.h").write_text(
        "#pragma once\n"
        "#include <cstdint>\n"
        "extern std::uint32_t fake_millis;\n"
        "inline std::uint32_t millis() { return fake_millis; }\n"
        "inline std::uint32_t next_vad_generation() { static std::uint32_t value = 0; return ++value; }\n"
    )
    (tmp_path / "esphome/core/log.h").write_text(
        "#pragma once\n"
        "#include <cstdio>\n"
        "#include <string>\n"
        "inline std::string fake_warnings;\n"
        "inline std::string fake_formatted_warnings;\n"
        "template <typename... Args> inline const char *fake_format(const char *fmt, Args...) { return fmt; }\n"
        "template <typename... Args> inline int fake_record(const char *fmt, Args... args) {\n"
        "  char line[512];\n"
        "  std::snprintf(line, sizeof(line), fmt, args...);\n"
        "  fake_formatted_warnings += line;\n"
        "  fake_formatted_warnings += '\\n';\n"
        "  return 0;\n"
        "}\n"
        "#define ESP_LOGD(...) do {} while (0)\n"
        "#define ESP_LOGE(...) do {} while (0)\n"
        "#define ESP_LOGI(...) do {} while (0)\n"
        "#define ESP_LOGW(tag, ...) (fake_warnings += fake_format(__VA_ARGS__), fake_warnings += '\\n', fake_record(__VA_ARGS__))\n"
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
        "  std::vector<int> statuses;\n"
        "  Response response;\n"
        "  Response *post(const std::string &url, const std::string &body, const std::vector<Header> &) {\n"
        "    urls.push_back(url);\n"
        "    bodies.push_back(body);\n"
        "    if (urls.size() <= statuses.size()) response.status_code = statuses[urls.size() - 1];\n"
        "    return &response;\n"
        "  }\n"
        "  Response *post(const std::string &url, const std::string &body) {\n"
        "    return post(url, body, {});\n"
        "  }\n"
        "};\n"
        "}\n"
    )
    (tmp_path / "esphome/core/alloc_helpers.h").write_text("#pragma once\n")


def _compile_and_run_capture_harness(tmp_path, compiler, source, extra_flags=()):
    harness = tmp_path / "harness.cpp"
    harness.write_text(textwrap.dedent(source))
    executable = tmp_path / "harness"
    compile_result = subprocess.run(
        [
            compiler,
            "-std=c++17",
            *extra_flags,
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
    run_result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=120)
    assert run_result.returncode == 0, run_result.stdout + run_result.stderr
    return run_result.stdout


def _configured_ids_cpp(source):
    """Resolve ESPHome lambda IDs without leaking a macro into system headers."""
    return re.sub(r"\bid\(([A-Za-z_]\w*)\)", r"puck_firmware_fixture::\1", source)


def _response_handoff_cpp():
    """Execute the configured ESPHome handoff with a counted media action."""
    path = Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml"
    config = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    interval = next(item for item in config["interval"] if item["interval"] == "1s")
    handoff = next(action for action in interval["then"] if "if" in action)

    def render(actions):
        statements = []
        for action in actions:
            if "lambda" in action:
                statements.append(action["lambda"])
            elif "if" in action:
                branch = action["if"]
                condition = branch["condition"]["lambda"]
                statements.append(
                    f"if ([&]() {{ {condition} }}()) {{ {render(branch['then'])} }}"
                )
            elif "media_player.play_media" in action:
                media_url = action["media_player.play_media"]["media_url"]
                statements.append(
                    f"puck_firmware_fixture::puck_media_player.last_media_url = "
                    f"[&]() -> std::string {{ {media_url} }}(); ++media_requests;"
                )
            else:
                raise AssertionError(f"unhandled response handoff action: {action}")
        return "\n".join(statements)

    return _configured_ids_cpp(render([handoff]))


@pytest.mark.parametrize("completion", ["deadline", "buffer_before_tick"])
def test_follow_up_no_speech_discards_buffered_pcm_before_empty_upload(tmp_path, completion):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the capture-state harness")

    _write_capture_stubs(tmp_path)
    harness = tmp_path / "capture_state.cpp"
    harness.write_text(
        textwrap.dedent(
            """
            #include "pcm_capture.h"
            #include <cassert>
            #include <cstdint>
            #include <vector>

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
              tick(true, true, next_vad_generation());
              fake_millis = 1;
              tick(true, false, next_vad_generation());
              fake_millis += VAD_SILENCE_DEBOUNCE_MS;
              tick(true, false, next_vad_generation());
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

              if (COMPLETE_BY_BUFFER) {
                std::vector<std::uint8_t> remainder(WAKE_CAPTURE_BYTES - write_pos, 0);
                write(remainder.data(), remainder.size());
                assert(fake_warnings.find("buffer limit") == std::string::npos);
              } else {
                fake_millis = capture_started_ms + CAPTURE_LISTEN_TIMEOUT_MS - 1;
                tick(true, false, next_vad_generation());
                assert(capturing);
                fake_millis = capture_started_ms + CAPTURE_LISTEN_TIMEOUT_MS;
                tick(true, false, next_vad_generation());
              }
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
              assert(last_delivered_empty);
              int media_requests = 0;
              RESPONSE_HANDOFF
              assert(media_requests == 0);
              assert(!last_upload_delivered);
              assert(puck_response::poll_due());
              puck_response::note_status(
                  200, puck_response::terminal_body(last_delivered_seq, "silent"));
              assert(puck_response::ready_to_resume());
              assert(!puck_response::refusal_pending());
              assert(!puck_identity::unavailable_visible);
              puck_response::wake_resumed();
              assert(!puck_response::holds_wake());
              return 0;
            }
            """
        ).replace(
            "COMPLETE_BY_BUFFER", str(completion == "buffer_before_tick").lower()
        ).replace("RESPONSE_HANDOFF", _response_handoff_cpp())
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


@pytest.mark.parametrize("frame", ["inflight_frame", "inflight_full_buffer"])
def test_no_speech_completion_snapshot_survives_inflight_microphone_write(tmp_path, frame):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the capture-state harness")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(
        tmp_path,
        compiler,
        """
        #include <algorithm>
        #include <atomic>
        #include <cstddef>
        #include <cstdint>
        #include <cstring>
        #include <string>
        #include <vector>

        void *copy_with_deadline(void *, const void *, std::size_t);
        #define memcpy copy_with_deadline
        #include "pcm_capture.h"
        #undef memcpy
        #include <cassert>

        std::uint32_t fake_millis = 100000;
        bool expire_inside_copy = false;
        bool preempted = false;

        void *copy_with_deadline(void *dest, const void *source, std::size_t size) {
          void *result = std::memcpy(dest, source, size);
          if (expire_inside_copy) {
            expire_inside_copy = false;
            preempted = true;
            fake_millis = pcm_capture::wake_capture::capture_started_ms +
                          pcm_capture::wake_capture::CAPTURE_LISTEN_TIMEOUT_MS;
            pcm_capture::wake_capture::tick(true, false, next_vad_generation());
          }
          return result;
        }

        int main() {
          using namespace pcm_capture::wake_capture;
          puck_identity::setup("configured");
          setup();
          puck_response::response_seq = 7;
          puck_response::state = puck_response::State::FOLLOW_UP_PENDING;
          assert(puck_response::begin_follow_up_admission(7));
          puck_response::note_follow_up_admission(200, "admitted:7");
          assert(start_follow_up());
          puck_response::follow_up_started();
          std::vector<std::uint8_t> frames(FULL_BUFFER ? WAKE_CAPTURE_BYTES : 8, 0);
          expire_inside_copy = true;
          write(frames.data(), frames.size());
          assert(preempted);
          assert(!capturing && capture_pending_upload);
          assert(completed_capture_bytes == 0);
          assert(!last_capture_captured);
          esphome::http_request::HttpRequestComponent client;
          upload(&client, "http://bridge/upload", "token");
          assert(client.bodies.size() == 1);
          assert(client.bodies.front().empty());
          assert(last_upload_delivered && last_delivered_empty);
          // A late finalizer cannot publish a second capture after upload.
          finish_capture(WAKE_CAPTURE_BYTES);
          tick(true, false, next_vad_generation());
          upload(&client, "http://bridge/upload", "token");
          assert(client.bodies.size() == 1);
          int media_requests = 0;
          RESPONSE_HANDOFF
          assert(media_requests == 0);
          assert(puck_response::poll_due());
          puck_response::note_status(
              200, puck_response::terminal_body(last_delivered_seq, "silent"));
          assert(puck_response::ready_to_resume());
          puck_response::wake_resumed();
          assert(!puck_response::holds_wake());
          assert(fake_warnings.find("buffer limit") == std::string::npos);
          return 0;
        }
        """.replace(
            "FULL_BUFFER", str(frame == "inflight_full_buffer").lower()
        ).replace("RESPONSE_HANDOFF", _response_handoff_cpp()),
        extra_flags=("-fsanitize=address,undefined", "-fno-omit-frame-pointer"),
    )


def test_known_empty_response_confirms_only_matching_silent_status(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the response-state harness")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(
        tmp_path,
        compiler,
        """
        #include "puck_response.h"
        #include <cassert>
        #include <cstdint>
        #include <utility>

        std::uint32_t fake_millis = 100000;

        int main() {
          using namespace puck_response;
          puck_identity::setup("configured");
          begin(12, true);
          assert(poll_due());
          note_status(409, "");
          assert(state == State::POLLING);
          assert(!poll_due());
          fake_millis += STATUS_RETRY_INTERVAL_MS;
          assert(poll_due());
          note_status(200, terminal_body(12, "silent"));
          assert(ready_to_resume());
          wake_resumed();
          assert(state == State::IDLE);

          const std::pair<int, std::string> rejected[] = {
            {200, terminal_body(12, "complete")},
            {200, terminal_body(99, "silent")},
            {200, ""},
            {201, terminal_body(12, "silent")},
            {204, terminal_body(12, "silent")},
            {404, ""},
            {500, ""},
          };
          for (const auto &outcome : rejected) {
            begin(12, true);
            note_status(outcome.first, outcome.second);
            assert(refusal_pending());
            assert(!follow_up_pending());
            refusal_started();
            media_idle();
            wake_resumed();
          }

          begin(12, true);
          fake_millis += STATUS_RETRY_WINDOW_MS;
          note_status(409, "");
          assert(refusal_pending());

          // Reset the silent-only expectation for ordinary speech responses.
          begin(13);
          assert(state == State::WAITING_FOR_MEDIA_IDLE);
          media_idle();
          note_status(200, terminal_body(13, "complete"));
          assert(follow_up_pending());

          begin(14, true);
          note_status(200, home_admission_terminal_body(14));
          assert(needs_home_admission());
          assert(refusal_pending());
          assert(puck_identity::unavailable_visible);

          begin(15, true);
          note_status(401, "");
          assert(refusal_pending());
          assert(!puck_identity::may_capture());
          return 0;
        }
        """,
    )


@pytest.mark.parametrize("completion", ["vad_silence", "speech_buffer"])
def test_follow_up_speech_retains_capture_limit_debounce_and_media(tmp_path, completion):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the capture-state harness")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(
        tmp_path,
        compiler,
        """
        #include "pcm_capture.h"
        #include <cassert>
        #include <cstdint>
        #include <vector>

        std::uint32_t fake_millis = 100000;

        int main() {
          using namespace pcm_capture::wake_capture;
          static_assert(CAPTURE_LISTEN_TIMEOUT_MS == 8000);
          static_assert(WAKE_CAPTURE_SECONDS == 8);
          static_assert(VAD_SILENCE_DEBOUNCE_MS == 800);
          puck_identity::setup("configured");
          setup();
          puck_response::response_seq = 7;
          puck_response::state = puck_response::State::FOLLOW_UP_PENDING;
          assert(puck_response::begin_follow_up_admission(7));
          puck_response::note_follow_up_admission(200, "admitted:7");
          assert(start_follow_up());
          puck_response::follow_up_started();

          const std::uint8_t speech_frame[] = {1, 2, 3, 4};
          write(speech_frame, sizeof(speech_frame));
          tick(true, true, next_vad_generation());
          fake_millis += FOLLOW_UP_MIN_SPEECH_MS;  // sustained speech, not an echo blip
          tick(true, true, next_vad_generation());
          if (COMPLETE_BY_BUFFER) {
            std::vector<std::uint8_t> remainder(WAKE_CAPTURE_BYTES - write_pos, 0);
            write(remainder.data(), remainder.size());
            assert(write_pos == WAKE_CAPTURE_BYTES);
            assert(fake_warnings.find("buffer limit") != std::string::npos);
          } else {
            ++fake_millis;
            tick(true, false, next_vad_generation());
            fake_millis += VAD_SILENCE_DEBOUNCE_MS - 1;
            tick(true, false, next_vad_generation());
            assert(capturing);
            ++fake_millis;
            tick(true, false, next_vad_generation());
            assert(write_pos == sizeof(speech_frame));
          }
          assert(!capturing);
          assert(last_capture_captured);
          esphome::http_request::HttpRequestComponent client;
          upload(&client, "http://bridge/upload", "token");
          assert(last_upload_delivered);
          assert(!last_delivered_empty);
          assert(!client.bodies.front().empty());
          int media_requests = 0;
          RESPONSE_HANDOFF
          assert(media_requests == 1);
          assert(puck_response::state == puck_response::State::WAITING_FOR_MEDIA_IDLE);
          puck_response::media_idle();
          puck_response::note_status(
              200, puck_response::terminal_body(last_delivered_seq, "complete"));
          assert(puck_response::follow_up_pending());
          return 0;
        }
        """.replace(
            "COMPLETE_BY_BUFFER", str(completion == "speech_buffer").lower()
        ).replace("RESPONSE_HANDOFF", _response_handoff_cpp()),
    )


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


def test_wake_acknowledgement_finishes_before_capture_opens(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(tmp_path, compiler, """
        #include "pcm_capture.h"
        #include "puck_audio_handoff.h"
        #include <cassert>
        std::uint32_t fake_millis = 0;
        int begins = 0, ends = 0;
        int main() {
          using namespace puck_audio_handoff;
          using namespace pcm_capture::wake_capture;
          assert(!drained(current_output())); // Missing reader fails closed.
          puck_identity::setup("configured");
          setup();
          set_capture_diagnostics([](){ ++begins; }, [](){ ++ends; });
          assert(puck_response::begin_home_admission(0));
          puck_response::note_home_admission(200, "admitted:0");
          prepare("hey missy");
          assert(wake_pending && !capturing);
          Output output{true, true, true, false, true, 40, 40, false, 0, true};
          wake_cue.begin(40, 0, CUE_MINIMUM_MS);
          fake_millis = 150;
          assert(wake_cue.poll(output) == Result::WAITING); // Queued, not accepted.
          output.playback_generation = 41;
          assert(wake_cue.poll(output) == Result::WAITING); // Fault/forced stop is not completion.
          output.completed_generation = 41;
          output.speaker_stopped = false;
          assert(wake_cue.poll(output) == Result::WAITING); // Source IDLE is insufficient.
          assert(!capturing && begins == 0);
          output.speaker_stopped = true;
          // No ANNOUNCING publication was needed: the actual drain receipt survives.
          assert(wake_cue.poll(output) == Result::READY);
          start_pending();
          assert(capturing && !wake_pending && begins == 1);
          finish_capture(0);
          finish_capture(4);
          assert(ends == 1); // Only the completion winner closes diagnostics.

          Barrier failed;
          failed.begin(40);
          output.completed_generation = 40;
          fake_millis += HANDOFF_TIMEOUT_MS - 1;
          assert(failed.poll(output) == Result::WAITING);
          ++fake_millis;
          assert(failed.poll(output) == Result::FAILED);
          assert(!capturing);
          failed.begin(40);
          output.playback_generation = 42;
          assert(failed.poll(output) == Result::FAILED); // Not the requested cue.
        }
    """)


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




def test_speaker_volume_matches_the_documented_room_safety_policy():
    path = Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml"
    config = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    player = next(item for item in config["media_player"] if item["id"] == "puck_media_player")
    assert player["volume_initial"] == "0.25"
    assert player["volume_max"] == "0.80"


def test_default_firmware_build_keeps_raw_pcm_diagnostics_off():
    root = Path(__file__).resolve().parents[1] / "firmware/respeaker-lite"
    yaml_source = (root / "respeaker-lite.yaml").read_text()
    capture_source = (root / "pcm_capture.h").read_text()
    config = yaml.load(yaml_source, Loader=yaml.BaseLoader)
    assert config["substitutions"]["puck_pcm_diagnostics"] == "false"
    assert config["substitutions"]["puck_pcm_diagnostics_url"] == ""
    assert (
        'pcm_capture::setup(${puck_pcm_diagnostics}, "${puck_pcm_diagnostics_url}");' in yaml_source
    )
    # Only one export path exists, and the serial/base64 dump is gone.
    assert yaml_source.count("pcm_capture::upload_and_restart(") == 1
    assert "dump_over_serial" not in capture_source + yaml_source
    assert "base64_encode" not in capture_source
    assert "PCMDUMP" not in capture_source
    assert not (root / "tools/collect_serial_dumps.py").exists()
    # Content-safe amplitude and status diagnostics stay separate.
    assert 'ESP_LOGI("mic_diag", "peak amplitude' in yaml_source
    assert 'ESP_LOGI("mww_diag", "mww is_running' in yaml_source
    # The wake path does not route through the diagnostic buffer.
    wake = yaml_source.split("  on_wake_word_detected:\n", 1)[1]
    assert "pcm_capture::start()" not in wake


def test_raw_pcm_diagnostics_are_off_by_default_and_bounded_when_opted_in(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the diagnostic capture harness")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(
        tmp_path,
        compiler,
        """
        #include "pcm_capture.h"
        #include <cassert>
        #include <string>
        #include <vector>

        std::uint32_t fake_millis = 0;
        namespace pc = pcm_capture;

        static void fill_window() {
          std::vector<std::uint8_t> frame(4096, 0x5a);
          for (std::size_t n = 0; n < pc::CAPTURE_BYTES; n += frame.size()) {
            pc::write(frame.data(), frame.size());
          }
        }

        int main() {
          puck_identity::setup("configured");
          esphome::http_request::HttpRequestComponent client;

          // Default build: nothing allocated, captured, or exported.
          pc::setup(false, "http://receiver/upload");
          pc::start();
          assert(!pc::diagnostics_enabled());
          assert(pc::buffer == nullptr && fake_heap_allocations == 0);
          for (int i = 0; i < 40; ++i) {
            fill_window();
            pc::upload_and_restart(&client);
          }
          assert(client.urls.empty());
          assert(fake_warnings.find("RAW MICROPHONE") == std::string::npos);

          // The flag alone, without an export URL, stays disabled.
          pc::setup(true, "");
          assert(!pc::diagnostics_enabled() && fake_heap_allocations == 0);

          // Explicit opt-in is visible and warns.
          pc::setup(true, "http://receiver/upload");
          assert(pc::diagnostics_enabled() && fake_heap_allocations == 1);
          assert(fake_warnings.find("RAW MICROPHONE PCM DIAGNOSTICS ENABLED") != std::string::npos);
          pc::start();
          assert(pc::state.load() == pc::DiagState::CAPTURING);

          // A window is not exported until it is complete.
          std::uint8_t half[8] = {};
          pc::write(half, sizeof(half));
          pc::upload_and_restart(&client);
          assert(client.urls.empty());

          // Bounded: extra windows past the limit are never captured.
          for (std::uint32_t i = 0; i < pc::MAX_DIAGNOSTIC_CAPTURES + 5; ++i) {
            fill_window();
            pc::upload_and_restart(&client);
          }
          const std::size_t chunks = (pc::CAPTURE_BYTES + pc::UPLOAD_CHUNK_BYTES - 1) / pc::UPLOAD_CHUNK_BYTES;
          assert(client.urls.size() == pc::MAX_DIAGNOSTIC_CAPTURES * chunks);
          std::size_t exported = 0;
          for (const auto &body : client.bodies) exported += body.size();
          assert(exported == pc::MAX_DIAGNOSTIC_CAPTURES * pc::CAPTURE_BYTES);
          assert(pc::state.load() == pc::DiagState::COMPLETE);
          assert(fake_warnings.find("raw PCM diagnostics complete") != std::string::npos);
          pc::start();
          fill_window();
          pc::upload_and_restart(&client);
          assert(client.urls.size() == pc::MAX_DIAGNOSTIC_CAPTURES * chunks);
          return 0;
        }
        """,
    )


def test_raw_pcm_diagnostics_discard_buffered_audio_when_identity_is_revoked(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the diagnostic capture harness")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(
        tmp_path,
        compiler,
        """
        #include "pcm_capture.h"
        #include <cassert>
        #include <vector>

        std::uint32_t fake_millis = 0;
        namespace pc = pcm_capture;

        int main() {
          // Unauthorized at boot: opt-in allocates but never starts capture.
          pc::setup(true, "http://receiver/upload");
          pc::start();
          assert(pc::state.load() == pc::DiagState::IDLE);

          puck_identity::setup("configured");
          pc::start();
          assert(pc::state.load() == pc::DiagState::CAPTURING);
          std::vector<std::uint8_t> frame(pc::CAPTURE_BYTES, 0x11);
          pc::write(frame.data(), frame.size());
          assert(pc::state.load() == pc::DiagState::READY);

          // A 4xx from the wake path revokes identity; the finished window
          // is discarded by the next callback instead of being exported.
          puck_identity::note_upload_status(401);
          pc::write(frame.data(), 4);
          assert(pc::state.load() == pc::DiagState::IDLE);
          esphome::http_request::HttpRequestComponent client;
          pc::upload_and_restart(&client);
          assert(client.urls.empty());
          pc::start();
          assert(pc::state.load() == pc::DiagState::IDLE);
          return 0;
        }
        """,
    )


def test_raw_pcm_diagnostic_export_drops_a_claimed_window_after_identity_loss(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the diagnostic capture harness")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(
        tmp_path,
        compiler,
        """
        #include "pcm_capture.h"
        #include <cassert>
        #include <vector>

        std::uint32_t fake_millis = 0;
        namespace pc = pcm_capture;

        int main() {
          puck_identity::setup("configured");
          pc::setup(true, "http://receiver/upload");
          pc::start();
          std::vector<std::uint8_t> frame(pc::CAPTURE_BYTES, 0x22);
          pc::write(frame.data(), frame.size());
          assert(pc::state.load() == pc::DiagState::READY);

          // Revocation lands with no further mic callback, so the exporter
          // claims the window itself and must drop it, not export it.
          puck_identity::note_upload_status(403);
          esphome::http_request::HttpRequestComponent client;
          pc::upload_and_restart(&client);
          assert(client.urls.empty());
          assert(pc::captures_exported == 1);
          assert(pc::write_pos == 0);
          assert(pc::state.load() == pc::DiagState::IDLE);
          // Fail-closed identity keeps diagnostics stopped until reboot.
          pc::start();
          pc::write(frame.data(), frame.size());
          pc::upload_and_restart(&client);
          assert(client.urls.empty() && pc::state.load() == pc::DiagState::IDLE);
          return 0;
        }
        """,
    )


def test_raw_pcm_diagnostics_reach_the_bound_when_every_upload_fails(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the diagnostic capture harness")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(
        tmp_path,
        compiler,
        """
        #include "pcm_capture.h"
        #include <cassert>
        #include <vector>

        std::uint32_t fake_millis = 0;
        namespace pc = pcm_capture;

        int main() {
          puck_identity::setup("configured");
          pc::setup(true, "http://receiver/upload");
          pc::start();
          esphome::http_request::HttpRequestComponent client;
          client.response.status_code = 500;
          std::vector<std::uint8_t> frame(pc::CAPTURE_BYTES, 0x33);
          for (std::uint32_t i = 0; i < pc::MAX_DIAGNOSTIC_CAPTURES + 5; ++i) {
            pc::write(frame.data(), frame.size());
            pc::upload_and_restart(&client);
          }
          // Each window is abandoned after two failed chunks, yet counts.
          assert(pc::captures_exported == pc::MAX_DIAGNOSTIC_CAPTURES);
          assert(client.urls.size() == pc::MAX_DIAGNOSTIC_CAPTURES * 2);
          assert(pc::state.load() == pc::DiagState::COMPLETE);
          // The diagnostic receiver is not an identity authority.
          assert(puck_identity::may_capture());
          return 0;
        }
        """,
    )


def test_raw_pcm_diagnostic_export_never_reads_a_window_being_written(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the diagnostic capture harness")
    _write_capture_stubs(tmp_path)
    source = """
        #include "pcm_capture.h"
        #include <cassert>
        #include <cstdio>
        #include <cstring>
        #include <map>
        #include <thread>

        std::uint32_t fake_millis = 0;
        namespace pc = pcm_capture;

        int main() {
          puck_identity::setup("configured");
          pc::setup(true, "http://receiver/upload");
          pc::start();
          esphome::http_request::HttpRequestComponent client;

          // Mic task: a monotonically increasing counter per frame.
          std::thread mic([] {
            std::uint32_t counter = 1;
            while (pc::state.load() != pc::DiagState::COMPLETE) {
              std::uint8_t frame[sizeof(counter)];
              std::memcpy(frame, &counter, sizeof(counter));
              pc::write(frame, sizeof(frame));
              ++counter;
            }
          });
          // Main loop: export concurrently until the bound is reached.
          while (pc::state.load() != pc::DiagState::COMPLETE) {
            pc::upload_and_restart(&client);
          }
          mic.join();

          std::map<std::string, std::string> windows;
          for (std::size_t i = 0; i < client.urls.size(); ++i) {
            const std::string &url = client.urls[i];
            std::string seq = url.substr(url.find("seq="), url.find("&chunk=") - url.find("seq="));
            windows[seq] += client.bodies[i];
          }
          assert(windows.size() == pc::MAX_DIAGNOSTIC_CAPTURES);
          for (const auto &entry : windows) {
            const std::string &pcm = entry.second;
            assert(pcm.size() == pc::CAPTURE_BYTES);
            std::uint32_t previous = 0;
            for (std::size_t offset = 0; offset < pcm.size(); offset += 4) {
              std::uint32_t value;
              std::memcpy(&value, pcm.data() + offset, sizeof(value));
              // A torn or overwritten window would break strict ordering.
              assert(value == previous + 1 || offset == 0);
              previous = value;
            }
          }
          std::printf("windows=%zu\\n", windows.size());
          return 0;
        }
        """
    flags = ["-pthread", "-O1"]
    sanitizer = subprocess.run(
        [compiler, "-fsanitize=thread", "-x", "c++", "-", "-o", str(tmp_path / "probe")],
        input="int main() { return 0; }\n",
        capture_output=True,
        text=True,
    )
    if sanitizer.returncode == 0 and subprocess.run([str(tmp_path / "probe")]).returncode == 0:
        flags.append("-fsanitize=thread")
    output = _compile_and_run_capture_harness(tmp_path, compiler, source, flags)
    assert "windows=15" in output


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


def test_unavailable_led_is_exact_xiao_user_led_without_pin_conflicts():
    source = (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml").read_text()
    config = yaml.load(source, Loader=yaml.BaseLoader)
    assert config["esp32"]["board"] == "seeed_xiao_esp32s3"
    led = next(item for item in config["output"] if item["id"] == "puck_unavailable_led")
    assert led["platform"] == "gpio"
    assert led["pin"] == {"number": "GPIO21", "inverted": "true"}
    def pins(value):
        if isinstance(value, dict):
            return [pin for item in value.values() for pin in pins(item)]
        if isinstance(value, list):
            return [pin for item in value for pin in pins(item)]
        return [value] if isinstance(value, str) and value.startswith("GPIO") else []

    assert pins(config).count("GPIO21") == 1


def test_home_unavailable_is_visible_before_real_capture_and_not_cleared_by_reachability(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for real-header identity harness")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(tmp_path, compiler, """
        #include "pcm_capture.h"
        #include <cassert>
        std::uint32_t fake_millis = 0;
        static bool led_on = false;
        static void indicator(bool on) { led_on = on; }
        namespace cap = pcm_capture::wake_capture;
        namespace response = puck_response;

        static void reset_response() {
          response::state = response::State::IDLE;
          response::home_admission_pending = false;
          response::home_admission_granted_flag = false;
        }
        int main() {
          cap::setup();
          puck_identity::setup_indicator(indicator);
          puck_identity::setup("local-test-token", true);
          assert(led_on); // Home reboot is not verification.
          esphome::http_request::HttpRequestComponent client;
          uint8_t synthetic[32] = {};
          for (const char *denial : {"denied:12", "unavailable:12", "admitted:11"}) {
            reset_response();
            assert(response::begin_home_admission(12));
            response::note_home_admission(200, denial);
            assert(led_on && puck_identity::unavailable_visible);
            response::dispatch_wake_capture(response::can_start_wake_capture(),
                [&]() { cap::prepare("Hey Missy"); },
                [&]() { cap::cancel_pending(); });
            cap::start_pending();
            cap::write(synthetic, sizeof(synthetic));
            cap::upload(&client, "http://isolated/wake", "local-test-token");
            assert(!cap::capturing && cap::write_pos == 0 && client.urls.empty());
            puck_identity::note_upload_status(200); // Reachability cannot restore it.
            assert(led_on);
          }
          reset_response();
          assert(response::begin_home_admission(13));
          response::note_home_admission(200, "admitted:13");
          assert(!led_on);
          cap::prepare("Hey Missy");
          cap::start_pending();
          assert(cap::capturing);
          cap::capturing = false;
          reset_response();
          assert(response::begin_home_admission(99));
          response::note_home_admission_transport_failure(); // Absent/unpaired bridge.
          assert(led_on && !response::can_start_wake_capture());
          response::dispatch_wake_capture(response::can_start_wake_capture(),
              [&]() { cap::prepare("Hey Missy"); },
              [&]() { cap::cancel_pending(); });
          cap::start_pending();
          cap::write(synthetic, sizeof(synthetic));
          cap::upload(&client, "http://isolated/wake", "local-test-token");
          assert(!cap::capturing && cap::write_pos == 0 && client.urls.empty());
          reset_response();
          assert(response::begin_home_admission(14));
          response::note_home_admission(200, "identity_rejected:14");
          assert(led_on && !puck_identity::may_capture());
          puck_identity::note_upload_status(200);
          assert(led_on && !puck_identity::may_capture());
          reset_response();
          assert(response::begin_home_admission(15));
          response::note_home_admission(200, "admitted:15");
          assert(led_on); // Even a grant cannot clear rejected local authority.
          cap::prepare("Hey Other");
          cap::start_pending();
          assert(!cap::capturing && client.urls.empty());
          // Preserve the locked Direct-mode degraded policy.
          puck_identity::setup("local-test-token");
          puck_identity::note_upload_status(503);
          assert(puck_identity::may_capture());
          return 0;
        }
    """)


def test_follow_up_waits_for_successful_output_drain_and_stable_settle(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(tmp_path, compiler, """
        #include "puck_audio_handoff.h"
        #include <cassert>
        std::uint32_t fake_millis = 1000;
        int main() {
          using namespace puck_audio_handoff;
          Output output{true, false, false, true, true, 11, 10, false, 0, false};
          response_requested(10);
          assert(poll_follow_up(output) == Result::WAITING);
          assert(response_audio_requested); // No admission while tail is queued.
          fake_millis = 1100;
          output = {true, true, true, false, false, 11, 11, false, 0, true};
          assert(poll_follow_up(output) == Result::WAITING); // Detector still STOPPING.
          output.detector_stopped = true;
          assert(poll_follow_up(output) == Result::WAITING);
          fake_millis = 1299;
          assert(poll_follow_up(output) == Result::WAITING);
          output.buffered = true; // Renewed output invalidates prior settle time.
          fake_millis = 1300;
          assert(poll_follow_up(output) == Result::WAITING);
          output.buffered = false;
          fake_millis = 1400;
          assert(poll_follow_up(output) == Result::WAITING);
          fake_millis = 1599;
          assert(poll_follow_up(output) == Result::WAITING);
          fake_millis = 1600;
          assert(poll_follow_up(output) == Result::READY);
          assert(!response_audio_requested);

          response_requested(11);
          output = {true, true, true, false, true, 12, 11, false, 0, true}; // Faulted TX stopped.
          assert(poll_follow_up(output) == Result::WAITING);
          fake_millis += HANDOFF_TIMEOUT_MS;
          assert(poll_follow_up(output) == Result::FAILED);
          assert(!response_audio_requested);

          Barrier wrap;
          fake_millis = UINT32_MAX - 50;
          wrap.begin(UINT32_MAX, FOLLOW_UP_SETTLE_MS);
          output = {true, true, true, false, true, 0, 0, false, 0, true};
          assert(wrap.poll(output) == Result::WAITING);
          fake_millis = 149;
          assert(wrap.poll(output) == Result::READY);
        }
    """)


@pytest.mark.parametrize("scenario", [
    "stale_true", "repeated_generation", "invalid_resets_silence",
    "late_speech", "stalled_input", "initial_stalled_input",
])
def test_capture_requires_fresh_vad_and_keeps_hard_eight_second_bound(tmp_path, scenario):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(tmp_path, compiler, """
        #include "pcm_capture.h"
        #include <cassert>
        #include <string>
        std::uint32_t fake_millis = 10000;
        int main() {
          using namespace pcm_capture::wake_capture;
          puck_identity::setup("configured");
          setup();
          const std::string scenario = "SCENARIO";
          if (scenario == "initial_stalled_input") {
            assert(puck_response::begin_home_admission(0));
            puck_response::note_home_admission(200, "admitted:0");
            prepare("hey missy");
            start_pending();
          } else {
            puck_response::state = puck_response::State::FOLLOW_UP_PENDING;
            assert(puck_response::begin_follow_up_admission(0));
            puck_response::note_follow_up_admission(200, "admitted:0");
            assert(start_follow_up());
            puck_response::follow_up_started();
          }
          assert(capturing);
          const bool stalled = scenario.find("stalled_input") != std::string::npos;
          const std::uint8_t frame[] = {1, 2, 3, 4};
          if (!stalled) write(frame, sizeof(frame));
          tick(false, true, 99); // Old true/partial window can never mark speech.
          assert(!speech_seen && capturing);
          if (scenario == "stale_true" || stalled) {
            fake_millis = capture_started_ms + CAPTURE_LISTEN_TIMEOUT_MS - 1;
            tick(false, true, 99);
            assert(capturing && !speech_seen);
            ++fake_millis;
            tick(false, true, 99);
          } else if (scenario == "late_speech") {
            fake_millis = capture_started_ms + CAPTURE_LISTEN_TIMEOUT_MS - 1 - FOLLOW_UP_MIN_SPEECH_MS;
            tick(true, true, 7);
            fake_millis += FOLLOW_UP_MIN_SPEECH_MS;  // follow-ups need sustained speech
            tick(true, true, 1);
            assert(capturing && speech_seen);
            ++fake_millis;
            tick(true, true, 2); // Speech never extends the original clock.
          } else {
            tick(true, true, 7);
            fake_millis += FOLLOW_UP_MIN_SPEECH_MS;  // follow-ups need sustained speech
            tick(true, true, 1);
            fake_millis += 100;
            tick(true, false, 2);
            fake_millis += VAD_SILENCE_DEBOUNCE_MS;
            if (scenario == "repeated_generation") {
              tick(true, false, 2);
              assert(capturing); // Re-reading an old false cannot end speech.
            }
            tick(false, false, 2); // Stale inference resets the debounce.
            assert(capturing);
            ++fake_millis;
            tick(true, false, 3);
            fake_millis += VAD_SILENCE_DEBOUNCE_MS - 1;
            tick(true, false, 4);
            assert(capturing);
            ++fake_millis;
            tick(true, false, 5);
          }
          assert(!capturing && capture_pending_upload);
          const bool empty = scenario == "stale_true" || stalled;
          assert(completed_capture_bytes == (empty ? 0 : sizeof(frame)));
          esphome::http_request::HttpRequestComponent client;
          upload(&client, "http://bridge/upload", "synthetic-token");
          assert(client.bodies.size() == 1);
          assert(client.bodies.front().size() == (empty ? 0 : sizeof(frame)));
          assert(last_delivered_empty == empty);
        }
    """.replace("SCENARIO", scenario))


def test_first_fresh_vad_generation_zero_is_not_a_sentinel(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(tmp_path, compiler, r"""
        #include "pcm_capture.h"
        #include <cassert>
        std::uint32_t fake_millis = 1000;
        int main() {
          using namespace pcm_capture::wake_capture;
          puck_identity::setup("configured");
          setup();
          puck_response::state = puck_response::State::FOLLOW_UP_PENDING;
          assert(puck_response::begin_follow_up_admission(0));
          puck_response::note_follow_up_admission(200, "admitted:0");
          assert(start_follow_up());
          puck_response::follow_up_started();
          const std::uint8_t frame[] = {1, 2, 3, 4};
          write(frame, sizeof(frame));
          tick(false, true, 0);
          assert(!speech_seen && !has_vad_generation);
          tick(true, true, 0); // A real generation can be zero after wrap.
          assert(has_vad_generation && last_vad_generation == 0);
          fake_millis += FOLLOW_UP_MIN_SPEECH_MS;
          tick(true, true, 7);
          assert(speech_seen);
          fake_millis += 100;
          tick(true, false, 7); // Same generation cannot switch the decision.
          assert(capturing && silence_start_ms == 0);
          tick(true, false, 1);
          assert(silence_start_ms == fake_millis);
          fake_millis += VAD_SILENCE_DEBOUNCE_MS;
          tick(true, false, 2);
          assert(!capturing && completed_capture_bytes == sizeof(frame));
        }
    """)


def test_full_capture_upload_failure_names_chunk_and_http_status_at_warn(tmp_path):
    """2026-10-19 retest: an 8 s capture (64 chunks) lost its final chunk to a
    bridge 503 and the device kept only W/E counts. The WARN summary must name
    the failing chunk and HTTP status so the next window cannot miss it."""
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the capture-state harness")
    _write_capture_stubs(tmp_path)
    output = _compile_and_run_capture_harness(
        tmp_path,
        compiler,
        """
        #include "pcm_capture.h"
        #include <cassert>
        #include <cstdint>
        #include <cstdio>
        #include <vector>

        std::uint32_t fake_millis = 0;

        int main() {
          using namespace pcm_capture::wake_capture;
          puck_identity::setup("configured");
          setup();
          const auto seq = pending_sequence();
          assert(puck_response::begin_home_admission(seq));
          const std::string grant = "admitted:" + std::to_string(seq);
          puck_response::note_home_admission(200, grant.c_str());
          prepare("hey missy");
          start_pending();
          assert(capturing);
          tick(true, true, next_vad_generation());
          std::vector<std::uint8_t> pcm(WAKE_CAPTURE_BYTES, 0);
          write(pcm.data(), pcm.size());
          assert(!capturing && capture_pending_upload);
          assert(completed_capture_bytes == 1024000);

          esphome::http_request::HttpRequestComponent client;
          client.statuses.assign(63, 202);
          client.statuses.push_back(503);
          upload(&client, "http://bridge/upload", "token");
          assert(client.urls.size() == 64);
          assert(!last_upload_delivered && last_upload_failed);
          std::printf("%s", fake_formatted_warnings.c_str());
          return 0;
        }
        """,
    )
    assert "Wake upload 0 chunk 63 failed (status 503)" in output
    assert "FAILED at chunk 63/64 with HTTP status 503" in output


@pytest.mark.parametrize("speaks", [True, False])
def test_initial_wake_waits_for_speech_before_silence_can_end_it(tmp_path, speaks):
    """2026-10-20 retest: with the 0.5 cutoff an initial wake capture ended
    ~1 s after the cue (800 ms of pre-speech silence) and STT received no
    speech. Silence may only end a capture after speech; a wake with no
    speech ends empty at the eight-second deadline."""
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the capture-state harness")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(
        tmp_path,
        compiler,
        """
        #include "pcm_capture.h"
        #include <cassert>
        #include <cstdint>
        std::uint32_t fake_millis = 0;
        int main() {
          using namespace pcm_capture::wake_capture;
          puck_identity::setup("configured");
          setup();
          const auto seq = pending_sequence();
          assert(puck_response::begin_home_admission(seq));
          puck_response::note_home_admission(200, "admitted:" + std::to_string(seq));
          prepare("hey missy");
          start_pending();
          assert(capturing);
          const std::uint8_t frame[64] = {7};
          for (int i = 0; i < 30; ++i) {  // 3 s of breath after the cue
            write(frame, sizeof(frame));
            tick(true, false, next_vad_generation());
            fake_millis += 100;
          }
          assert(capturing);
          if (SPEAKS) {
            tick(true, true, next_vad_generation());
            fake_millis += 100;
            tick(true, false, next_vad_generation());
            fake_millis += VAD_SILENCE_DEBOUNCE_MS;
            tick(true, false, next_vad_generation());
            assert(!capturing && completed_capture_bytes > 0);
          } else {
            fake_millis = capture_started_ms + CAPTURE_LISTEN_TIMEOUT_MS;
            tick(true, false, next_vad_generation());
            assert(!capturing && completed_capture_bytes == 0);
          }
          return 0;
        }
        """.replace("SPEAKS", str(speaks).lower()),
    )


@pytest.mark.parametrize("run_ms", [100, 300])
def test_follow_up_needs_sustained_speech_not_an_echo_blip(tmp_path, run_ms):
    """2026-10-20 retest: a follow-up recorded 5.8 s while the owner stayed
    quiet. Brief VAD blips (echo/room) must not mark a follow-up as spoken;
    300 ms of continuous speech does. Initial wakes are unaffected."""
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the capture-state harness")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(
        tmp_path,
        compiler,
        """
        #include "pcm_capture.h"
        #include <cassert>
        #include <cstdint>
        std::uint32_t fake_millis = 1000;
        int main() {
          using namespace pcm_capture::wake_capture;
          puck_identity::setup("configured");
          setup();
          puck_response::response_seq = 0;
          puck_response::state = puck_response::State::FOLLOW_UP_PENDING;
          assert(puck_response::begin_follow_up_admission(0));
          puck_response::note_follow_up_admission(200, "admitted:0");
          assert(start_follow_up());
          const std::uint8_t frame[64] = {3};
          write(frame, sizeof(frame));
          tick(true, true, next_vad_generation());
          fake_millis += RUN_MS;
          tick(true, true, next_vad_generation());
          fake_millis += 30;
          tick(true, false, next_vad_generation());
          fake_millis += 1;
          tick(true, false, next_vad_generation());
          fake_millis += VAD_SILENCE_DEBOUNCE_MS;
          tick(true, false, next_vad_generation());
          if (RUN_MS > 100) {
            assert(!capturing && completed_capture_bytes > 0);
          } else {
            assert(capturing);  // blips never count; only the deadline ends it
            fake_millis = capture_started_ms + CAPTURE_LISTEN_TIMEOUT_MS;
            tick(true, false, next_vad_generation());
            assert(!capturing && completed_capture_bytes == 0);
          }
          return 0;
        }
        """.replace("RUN_MS", str(run_ms)),
    )


def test_silent_terminal_needing_home_admission_resumes_without_refusal(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the response-state harness")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(
        tmp_path,
        compiler,
        """
        #include "pcm_capture.h"
        #include <cassert>
        std::uint32_t fake_millis = 1000;
        int main() {
          puck_identity::setup("configured");
          puck_response::begin(5, true);
          assert(puck_response::poll_due());
          puck_response::note_status(
              200, "{\\"seq\\": 5, \\"status\\": \\"silent\\", \\"needs_home_admission\\": true}");
          assert(puck_response::state == puck_response::State::READY_TO_RESUME);
          assert(puck_response::needs_home_admission());
          return 0;
        }
        """,
    )


def test_wifi_modem_sleep_is_disabled_for_streamed_playback():
    """2026-10-20: answer playback was patchy throughout; ESP32 LIGHT modem
    sleep (the ESPHome default) batches streamed TCP delivery."""
    config = yaml.load(
        (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert config["wifi"]["power_save_mode"] == "none"


def test_playback_telemetry_rides_on_the_status_poll_only_after_real_playback(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("no C++ compiler available for the response-state harness")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(tmp_path, compiler, r"""
        #include "pcm_capture.h"
        #include <cassert>
        std::uint32_t fake_millis = 1000;
        static unsigned resets = 0;
        int main() {
          puck_identity::setup("configured");
          puck_response::set_playback_stats_source(
              []() -> puck_response::PlaybackStats { return {6080, 3, 420, 1500}; },
              []() { ++resets; });
          // Empty capture: nothing played, nothing reported.
          puck_response::begin(1, true);
          assert(resets == 1 && puck_response::telemetry_query().empty());
          puck_response::begin(2, false);
          assert(resets == 2);
          puck_response::sample_rssi(-50.0f);  // before playback: ignored
          fake_millis = 2000;
          puck_response::announcement_started();
          assert(puck_response::playback_in_progress());
          puck_response::sample_rssi(-60.0f);
          puck_response::sample_rssi(-70.0f);
          puck_response::sample_rssi(0.0f);  // not a real RSSI
          assert(puck_response::telemetry_query().empty());  // still playing
          fake_millis = 9750;
          puck_response::media_idle();
          puck_response::sample_rssi(-90.0f);  // after playback: ignored
          assert(!puck_response::playback_in_progress());
          assert(puck_response::telemetry_query() ==
                 "&pb_wall_ms=7750&pb_played_ms=6080&pb_underruns=3"
                 "&pb_longest_underrun_ms=420&pb_longest_underrun_at_ms=1500"
                 "&pb_rssi_min=-70&pb_rssi_avg=-65");
          return 0;
        }
    """)


def test_status_poll_url_carries_playback_telemetry():
    config = (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml").read_text()
    assert "/response-status?seq=" in config
    status_block = config[config.index("/response-status?seq="):]
    assert "puck_response::telemetry_query()" in status_block[:400]
    assert "set_playback_stats_source" in config
    assert "puck_response::sample_rssi(wifi::global_wifi_component->wifi_rssi())" in config


def test_unmapped_hey_bestie_is_not_built_or_enabled():
    """2026-10-21: hey_bestie has no Home mapping and caused two
    wake_mapping_unavailable refusals; it is out of the build."""
    config = yaml.load(
        (Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    ids = [model["id"] for model in config["micro_wake_word"]["models"]]
    assert ids == ["hey_missy", "stop", "hey_skippy"]
    assert "enable_model: hey_bestie" not in (
        Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml").read_text()
