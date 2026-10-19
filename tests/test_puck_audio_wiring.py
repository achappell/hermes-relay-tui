"""Execute configured ESPHome audio lambdas against real control headers.

Only hardware IDs and HTTP responses are fixtures. Readiness, admission,
watchdogs, capture, and diagnostics transitions execute production C++ and the
actual YAML lambda bodies, including the nonempty response media_url action.
"""

from pathlib import Path
import shutil

import pytest
import yaml

from tests.test_puck_firmware import (
    _compile_and_run_capture_harness,
    _configured_ids_cpp,
    _response_handoff_cpp,
    _write_capture_stubs,
)


ROOT = Path(__file__).resolve().parents[1]


def _configured_cpp():
    config = yaml.load(
        (ROOT / "firmware/respeaker-lite/respeaker-lite.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    boot = next(
        action["lambda"]
        for entry in config["esphome"]["on_boot"]
        for action in entry["then"]
        if isinstance(action, dict) and "set_output_reader" in action.get("lambda", "")
    )
    fast = next(item for item in config["interval"] if item["interval"] == "100ms")
    control = next(item for item in config["interval"] if item["interval"] == "250ms")

    def condition(action):
        if not isinstance(action, dict):
            return ""
        return action.get("if", {}).get("condition", {}).get("lambda", "")

    status_poll = next(
        action for action in control["then"] if "poll_due()" in condition(action)
    )

    follow_up = next(
        action for action in control["then"]
        if "follow_up_pending()" in condition(action)
    )
    recovery = [
        action for action in control["then"]
        if any(name in condition(action) for name in (
            "refusal_pending()", "refusal_recovery_due()", "ready_to_resume()",
        ))
    ]

    def render(actions):
        statements = []
        for action in actions:
            if isinstance(action, str):
                scalar_actions = {
                    "micro_wake_word.stop": "id(mww).stop();",
                    "micro_wake_word.start": "id(mww).start();",
                }
                if action not in scalar_actions:
                    raise AssertionError(f"unsupported configured scalar audio action: {action}")
                statements.append(scalar_actions[action])
                continue
            if "lambda" in action:
                statements.append(action["lambda"])
            elif "if" in action:
                branch = action["if"]
                code = f"if ([&]() {{ {branch['condition']['lambda']} }}()) {{ {render(branch['then'])} }}"
                if "else" in branch:
                    code += f" else {{ {render(branch['else'])} }}"
                statements.append(code)
            elif "micro_wake_word.stop" in action:
                statements.append("id(mww).stop();")
            elif "micro_wake_word.start" in action:
                statements.append("id(mww).start();")
            elif "media_player.stop" in action:
                statements.append(
                    "++media_stops; if (puck_response::playback_cleanup_pending) ++cleanup_stops;"
                )
            elif "media_player.play_media" in action:
                url = action["media_player.play_media"]["media_url"]
                expression = f'[&]() -> std::string {{ {url} }}()' if "return " in url else f'"{url}"'
                statements.append(f"media_urls.push_back({expression}); ++media_requests;")
            elif "http_request.get" in action:
                request = action["http_request.get"]
                success = render(request["on_response"]["then"])
                failure = render(request["on_error"]["then"])
                statements.append("{\n" +
                    f"const auto url = [&]() -> std::string {{ {request['url']} }}();\n" +
                    'const bool is_status = url.find("/response-status?") != std::string::npos;\n'
                    "if (is_status) { ++status_requests; status_urls.push_back(url); }\n"
                    "else { ++admission_requests; admission_urls.push_back(url); }\n"
                    "if (is_status ? status_transport_error : admission_transport_error) {\n" +
                    failure + "\n} else {\n"
                    "struct Response { int status_code; } fixture_response{"
                    "is_status ? status_code : (admission_granted ? 200 : 503)};\n"
                    "auto *response = &fixture_response;\n"
                    "const std::string body = is_status ? status_body : "
                    "std::string(admission_granted ? \"admitted:\" : \"denied:\") + "
                    "std::to_string(puck_response::sequence());\n" + success + "\n}\n}")
            else:
                raise AssertionError(f"unsupported configured audio action: {action}")
        return "\n".join(statements)

    player = next(item for item in config["media_player"] if item["id"] == "puck_media_player")
    source = r'''
        #include "pcm_capture.h"
        #include <cassert>
        #include <vector>
        #include <string>
        std::uint32_t fake_millis = 1000;
        int media_requests = 0, media_stops = 0, admission_requests = 0;
        int cleanup_stops = 0;
        unsigned unavailable_notifications = 0;
        bool admission_transport_error = false, admission_granted = true;
        int status_requests = 0, status_code = 200;
        bool status_transport_error = false;
        std::string status_body;
        std::vector<std::string> status_urls;
        std::vector<std::string> media_urls, admission_urls;
        namespace capture = pcm_capture::wake_capture;
        using namespace puck_firmware_fixture;
        void boot_wiring() { BOOT }
        void fast_tick() { FAST }
        void fast_observation() { FAST_OBSERVATION }
        void fast_cleanup() { FAST_CLEANUP }
        void follow_up_tick() { FOLLOW_UP }
        void status_poll() { STATUS_POLL }
        void confirm_status(const char *terminal) {
          status_body = puck_response::terminal_body(42, terminal);
          const auto before = status_requests;
          status_poll();
          assert(status_requests == before + 1);
          assert(status_urls.back() == "http://fixture:8765/response-status?seq=42&token=synthetic-token");
        }
        void stop_output_completes() {
          puck_media_player.state = media_player::MEDIA_PLAYER_STATE_IDLE;
          puck_resampler.stopped = puck_speaker.stopped = true;
          puck_resampler.buffered = puck_speaker.buffered = false;
          puck_http_source.state = puck_local_source.state = media_source::MediaSourceState::IDLE;
        }
        void recovery_tick() { RECOVERY }
        void announcement() { ANNOUNCEMENT }
        void published_idle() { PUBLISHED_IDLE }
        void response_handoff() { RESPONSE_HANDOFF }
        void setup_fixture() {
          puck_identity::setup("configured");
          puck_identity::setup_indicator([](bool unavailable) {
            if (unavailable) ++unavailable_notifications;
          });
          capture::setup();
          boot_wiring();
          assert(puck_resampler.error_reader != nullptr);
          assert(puck_resampler.audio_callback != nullptr);
        }
        void request_nonempty_response() {
          capture::last_upload_delivered = true;
          capture::last_delivered_empty = false;
          capture::last_delivered_seq = 42;
          puck_resampler.generation = puck_resampler.completed = 10;
          puck_speaker.errors = 5;
          response_handoff();
          assert(!capture::last_upload_delivered && media_requests == 1);
          assert(puck_media_player.last_media_url == "http://fixture:8765/response?seq=42&token=synthetic-token");
          assert(mww.stops == 1 && !mww.running);
          assert(puck_audio_handoff::response_audio_requested);
          assert(puck_audio_handoff::response_baseline_generation == 10);
          assert(puck_audio_handoff::response_error_baseline == 5);
          assert(puck_response::state == puck_response::State::WAITING_FOR_MEDIA_IDLE);
          status_poll(); // The actual poll_due condition must keep HTTP closed during playback.
          assert(status_requests == 0 && status_urls.empty());
          puck_resampler.generation = 11;
          puck_resampler.stopped = puck_speaker.stopped = false;
          puck_resampler.buffered = puck_speaker.buffered = true;
        }
    '''
    replacements = {
        "BOOT": boot,
        "FAST_OBSERVATION": render(fast["then"][:1]),
        "FAST_CLEANUP": render(fast["then"][1:]),
        "FAST": render(fast["then"]),
        "FOLLOW_UP": render([follow_up]),
        "STATUS_POLL": render([status_poll]),
        "RECOVERY": render(recovery),
        "ANNOUNCEMENT": render(player["on_announcement"]),
        "PUBLISHED_IDLE": render(player["on_idle"]),
        "RESPONSE_HANDOFF": _response_handoff_cpp(),
    }
    for token, replacement in replacements.items():
        source = source.replace(token, replacement)
    for key, value in {
        "puck_bridge_host": "fixture", "puck_bridge_port": "8765",
        "puck_device_token": "synthetic-token",
    }.items():
        source = source.replace("${" + key + "}", value)
    return _configured_ids_cpp(source)


def _native(tmp_path, body):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("native C++ compiler unavailable")
    _write_capture_stubs(tmp_path)
    return _compile_and_run_capture_harness(
        tmp_path, compiler, _configured_cpp() + body,
        extra_flags=("-fsanitize=address,undefined", "-fno-sanitize-recover=all"),
    )


def test_configured_fast_tick_requires_actual_cue_drain_and_fresh_vad(tmp_path):
    _native(tmp_path, r'''
        int main() {
          setup_fixture();
          assert(puck_response::begin_home_admission(0));
          puck_response::note_home_admission(200, "admitted:0");
          capture::prepare("hey missy");
          assert(capture::wake_pending && !capture::capturing);
          mww.running = false;
          puck_resampler.generation = 10;
          puck_resampler.completed = 10;
          puck_audio_handoff::wake_cue.begin(10, 0, puck_audio_handoff::CUE_MINIMUM_MS);
          puck_resampler.generation = 11;
          puck_resampler.stopped = false;
          puck_resampler.buffered = true;
          fast_tick();
          assert(!capture::capturing && mww.starts == 0);
          fake_millis += puck_audio_handoff::CUE_MINIMUM_MS;
          puck_resampler.completed = 11;
          puck_resampler.stopped = true;
          puck_resampler.buffered = false;
          puck_speaker.stopped = false;
          puck_speaker.buffered = true;
          fast_tick(); // Source is IDLE and resampler done; physical TX still tails.
          assert(!capture::capturing && mww.diagnostic_starts == 0);
          puck_speaker.stopped = true;
          puck_speaker.buffered = false;
          mww.running = true; // Detector still STOPPING cannot open the capture.
          fast_tick();
          assert(!capture::capturing && mww.starts == 0);
          mww.running = false;
          fast_tick();
          assert(capture::capturing && !capture::wake_pending);
          assert(mww.starts == 1 && mww.diagnostic_starts == 1);
          assert(!capture::speech_seen); // Invalid snapshot did not discard warm-up PCM.
          const std::uint8_t pcm[] = {1, 2, 3, 4};
          capture::write(pcm, sizeof(pcm));
          mww.vad = {false, true, 99};
          fast_tick();
          assert(!capture::speech_seen && capture::write_pos == sizeof(pcm));
          mww.vad = {true, true, 0};
          fast_tick(); // Real configured valid/detected/generation argument order.
          assert(capture::speech_seen && capture::last_vad_generation == 0);
          fake_millis += 100;
          mww.vad = {true, false, 1};
          fast_tick();
          fake_millis += capture::VAD_SILENCE_DEBOUNCE_MS;
          mww.vad.generation = 2;
          fast_tick();
          assert(!capture::capturing && capture::completed_capture_bytes == sizeof(pcm));
          assert(mww.diagnostic_finishes == 1);
          fast_tick();
          assert(mww.diagnostic_finishes == 1);
        }
    ''')


@pytest.mark.parametrize("idle_publication", ["before_drain", "missed_short"])
def test_configured_follow_up_admission_waits_for_tail_detector_and_settle(tmp_path, idle_publication):
    _native(tmp_path, r'''
        int main() {
          setup_fixture();
          request_nonempty_response(); // Executes the actual media_url lambda.
          fast_tick();
          assert(puck_response::state == puck_response::State::WAITING_FOR_MEDIA_IDLE);
          const bool idle_was_published = IDLE_PUBLISHED;
          if (idle_was_published) {
            published_idle();
            confirm_status("complete");
            follow_up_tick();
            assert(admission_requests == 0 && !capture::capturing);
          }
          fake_millis += 100;
          puck_resampler.completed = 11;
          puck_resampler.stopped = true;
          puck_resampler.buffered = false;
          fast_tick(); // Speaker still running/buffered, despite source IDLE.
          if (!idle_was_published)
            assert(puck_response::state == puck_response::State::WAITING_FOR_MEDIA_IDLE);
          follow_up_tick();
          assert(admission_requests == 0 && mww.diagnostic_starts == 0);
          puck_speaker.stopped = true;
          puck_speaker.buffered = false;
          fast_tick();
          if (!idle_was_published) {
            assert(puck_response::poll_due()); // Successful short drain survives missed player publication.
            confirm_status("complete");
          }
          mww.running = true;
          follow_up_tick();
          assert(admission_requests == 0 && !capture::capturing);
          mww.running = false;
          follow_up_tick(); // Stable settle starts only here.
          fake_millis += puck_audio_handoff::FOLLOW_UP_SETTLE_MS - 1;
          follow_up_tick();
          assert(admission_requests == 0 && !capture::capturing);
          puck_speaker.buffered = true;
          ++fake_millis;
          follow_up_tick(); // A renewed tail clears prior settle.
          puck_speaker.buffered = false;
          ++fake_millis;
          follow_up_tick();
          fake_millis += puck_audio_handoff::FOLLOW_UP_SETTLE_MS;
          follow_up_tick(); // Executes configured condition, HTTP callbacks, capture/start actions.
          assert(admission_requests == 1 && admission_urls.size() == 1);
          assert(admission_urls[0] == "http://fixture:8765/follow-up-admission?seq=42&token=synthetic-token");
          assert(capture::capturing && puck_response::follow_up_capturing());
          assert(mww.stops == 2 && mww.starts == 1 && mww.diagnostic_starts == 1);
          follow_up_tick();
          assert(admission_requests == 1 && mww.diagnostic_starts == 1);
          fake_millis = capture::capture_started_ms + capture::CAPTURE_LISTEN_TIMEOUT_MS;
          fast_tick();
          assert(!capture::capturing && capture::completed_capture_bytes == 0);
          assert(mww.diagnostic_finishes == 1);
        }
    '''.replace("IDLE_PUBLISHED", str(idle_publication == "before_drain").lower()))


@pytest.mark.parametrize("terminal", ["silent", "complete", "unavailable", "transport"])
@pytest.mark.parametrize("failure", ["no_progress", "source_error", "speaker_error", "long_progress"])
def test_configured_playback_watchdog_uses_progress_and_bounded_recovery(tmp_path, failure, terminal):
    _native(tmp_path, r'''
        int main() {
          setup_fixture();
          request_nonempty_response();
          puck_media_player.state = media_player::MEDIA_PLAYER_STATE_ANNOUNCING;
          const auto marker = puck_response::playback_progress_marker.load();
          announcement(); // Actual configured on_announcement marker, not a fake readiness receipt.
          assert(puck_response::playback_progress_marker.load() != marker);
          fast_tick();
          const std::string failure = "FAILURE";
          if (failure == "source_error") {
            puck_http_source.state = media_source::MediaSourceState::ERROR;
            fast_tick();
          } else if (failure == "speaker_error") {
            ++puck_speaker.errors;
            fast_tick();
          } else {
            if (failure == "long_progress") {
              const auto started = fake_millis;
              for (unsigned i = 0; i < 4; ++i) {
                fake_millis += puck_response::PLAYBACK_PROGRESS_TIMEOUT_MS - 1;
                puck_resampler.audio_callback(160, std::int64_t(fake_millis) * 1000);
                fast_tick();
                assert(puck_response::state == puck_response::State::WAITING_FOR_MEDIA_IDLE);
                assert(admission_requests == 0 && !capture::capturing);
              }
              assert(fake_millis - started > puck_response::PLAYBACK_PROGRESS_TIMEOUT_MS * 3);
            }
            fake_millis += puck_response::PLAYBACK_PROGRESS_TIMEOUT_MS - 1;
            const auto before_empty_callback = puck_response::playback_progress_marker.load();
            announcement(); // Same-state/volume publications are not new progress.
            announcement();
            assert(puck_response::playback_progress_marker.load() == before_empty_callback);
            puck_resampler.audio_callback(0, 0);
            assert(puck_response::playback_progress_marker.load() == before_empty_callback);
            fast_tick();
            assert(puck_response::state == puck_response::State::WAITING_FOR_MEDIA_IDLE);
            ++fake_millis;
            fast_tick();
          }
          assert(puck_response::poll_due() && puck_response::silent_completion_only);
          assert(puck_response::playback_cleanup_pending && cleanup_stops == 1 && media_stops == 1);
          assert(puck_resampler.completed == 10 && puck_resampler.generation == 11);
          assert(!capture::capturing && admission_requests == 0 && mww.diagnostic_starts == 0);
          const std::string terminal = "TERMINAL";
          if (terminal == "transport") {
            status_transport_error = true;
            status_poll();
          } else {
            confirm_status(terminal.c_str());
          }
          stop_output_completes();
          fast_tick(); // Only a later physical drained observation clears cleanup.
          assert(!puck_response::playback_cleanup_pending && media_stops == 1);
          if (terminal == "silent") {
            assert(puck_response::ready_to_resume());
            recovery_tick();
            assert(puck_response::state == puck_response::State::IDLE && mww.starts == 1);
            assert(media_requests == 1 && media_urls.empty() && media_stops == 1);
            follow_up_tick();
            assert(admission_requests == 0 && !capture::capturing);
          } else {
            assert(puck_response::refusal_pending());
            recovery_tick();
            assert(puck_response::state == puck_response::State::REFUSAL_PLAYING);
            assert(media_requests == 2 && media_urls.size() == 1);
            assert(media_urls.front() == "audio-file://refused_sound");
            fast_tick(); // Response faults cannot reset the refusal watchdog.
            fake_millis += puck_response::REFUSAL_WATCHDOG_MS - 1;
            recovery_tick();
            assert(puck_response::state == puck_response::State::REFUSAL_PLAYING && mww.starts == 0);
            ++fake_millis;
            recovery_tick();
            assert(puck_response::state == puck_response::State::IDLE);
            assert(mww.starts == 1 && media_stops == 3);
          }
          assert(!capture::capturing && admission_requests == 0);
        }
    '''.replace("FAILURE", failure).replace("TERMINAL", terminal))


@pytest.mark.parametrize("admission_failure", ["denied", "transport"])
def test_configured_follow_up_admission_failure_cannot_begin_capture(tmp_path, admission_failure):
    _native(tmp_path, r'''
        int main() {
          setup_fixture();
          request_nonempty_response();
          puck_resampler.completed = 11;
          puck_resampler.stopped = puck_speaker.stopped = true;
          puck_resampler.buffered = puck_speaker.buffered = false;
          fast_tick();
          assert(puck_response::poll_due());
          confirm_status("complete");
          admission_granted = false;
          admission_transport_error = TRANSPORT_ERROR;
          follow_up_tick();
          fake_millis += puck_audio_handoff::FOLLOW_UP_SETTLE_MS;
          follow_up_tick(); // Actual YAML HTTP error/denied callback and following actions.
          assert(admission_requests == 1 && puck_response::refusal_pending());
          assert(!capture::capturing && mww.diagnostic_starts == 0 && mww.starts == 0);
          follow_up_tick();
          assert(admission_requests == 1);
          recovery_tick();
          fake_millis += puck_response::REFUSAL_WATCHDOG_MS;
          recovery_tick();
          assert(puck_response::state == puck_response::State::IDLE && mww.starts == 1);
          assert(!capture::capturing && mww.diagnostic_starts == 0);
        }
    '''.replace("TRANSPORT_ERROR", str(admission_failure == "transport").lower()))


def test_configured_silent_terminal_cannot_resume_before_playback_cleanup(tmp_path):
    _native(tmp_path, r'''
        int main() {
          setup_fixture();
          request_nonempty_response();
          puck_http_source.state = media_source::MediaSourceState::ERROR;
          fast_observation(); // Interleave status after fault detection, before the next configured action.
          assert(puck_response::poll_due() && puck_response::playback_cleanup_pending);
          assert(media_stops == 0 && puck_resampler.completed == 10);
          confirm_status("silent");
          assert(puck_response::state == puck_response::State::READY_TO_RESUME && !puck_response::ready_to_resume());
          recovery_tick(); // The actual 250ms wake guard must block here.
          assert(mww.starts == 0 && !puck_response::ready_to_resume());
          assert(media_requests == 1 && admission_requests == 0);
          fast_cleanup(); // Requests stop, but hardware has not acknowledged it.
          assert(media_stops == 1 && cleanup_stops == 1);
          assert(puck_response::playback_cleanup_pending && mww.starts == 0);
          for (unsigned i = 0; i < 3; ++i) {
            fast_tick();
            recovery_tick();
            assert(puck_response::playback_cleanup_pending && mww.starts == 0);
            assert(media_stops == 1); // Never repeat the asynchronous stop request.
          }
          stop_output_completes();
          fast_tick();
          assert(!puck_response::playback_cleanup_pending && media_stops == 1);
          assert(puck_resampler.completed == 10); // No fabricated successful drain.
          recovery_tick();
          assert(puck_response::state == puck_response::State::IDLE && mww.starts == 1);
          assert(media_requests == 1 && media_urls.empty() && admission_requests == 0);
        }
    ''')


@pytest.mark.parametrize("error_order", ["before_idle", "after_idle"])
@pytest.mark.parametrize("terminal", ["silent", "complete", "active_until_deadline"])
def test_configured_idle_error_order_cannot_accept_complete_or_reset_deadline(tmp_path, error_order, terminal):
    _native(tmp_path, r'''
        int main() {
          setup_fixture();
          request_nonempty_response();
          const bool error_before_idle = ERROR_BEFORE_IDLE;
          if (error_before_idle)
            puck_http_source.state = media_source::MediaSourceState::ERROR;
          published_idle(); // Executes configured fault check BEFORE its media_idle call.
          assert(puck_response::poll_due());
          const auto confirmation_started = puck_response::retry_started_ms;
          if (error_before_idle) {
            assert(puck_response::silent_completion_only && puck_response::playback_cleanup_pending);
          } else {
            assert(!puck_response::silent_completion_only);
            fake_millis += puck_response::STATUS_RETRY_WINDOW_MS - 1;
            ++puck_speaker.errors;
          }
          fast_tick(); // Entire configured action list must clean up the failed output.
          assert(puck_response::silent_completion_only);
          assert(puck_response::retry_started_ms == confirmation_started);
          assert(puck_response::playback_cleanup_pending && cleanup_stops == 1);
          assert(puck_resampler.completed == 10 && puck_resampler.generation == 11);
          const std::string terminal = "TERMINAL";
          if (terminal == "active_until_deadline") {
            fake_millis = confirmation_started + puck_response::STATUS_RETRY_WINDOW_MS;
            status_code = 409;
            status_body.clear();
            status_poll();
          } else {
            confirm_status(terminal.c_str());
          }
          stop_output_completes();
          fast_tick();
          assert(!puck_response::playback_cleanup_pending && media_stops == 1);
          if (terminal == "silent") {
            assert(puck_response::ready_to_resume());
            recovery_tick();
            assert(puck_response::state == puck_response::State::IDLE);
            assert(media_requests == 1 && media_urls.empty());
          } else {
            assert(puck_response::refusal_pending());
            recovery_tick();
            assert(media_requests == 2 && media_urls.front() == "audio-file://refused_sound");
            fake_millis += puck_response::REFUSAL_WATCHDOG_MS;
            recovery_tick();
            assert(puck_response::state == puck_response::State::IDLE);
          }
          assert(admission_requests == 0 && !capture::capturing && mww.starts == 1);
        }
    '''.replace("ERROR_BEFORE_IDLE", str(error_order == "before_idle").lower()).replace("TERMINAL", terminal))


@pytest.mark.parametrize("failure", ["source_error", "speaker_error"])
def test_configured_follow_up_rejects_fault_after_successful_receipt(tmp_path, failure):
    _native(tmp_path, r'''
        int main() {
          setup_fixture();
          request_nonempty_response();
          puck_resampler.completed = 11;
          puck_resampler.stopped = puck_speaker.stopped = true;
          puck_resampler.buffered = puck_speaker.buffered = false;
          fast_tick();
          assert(puck_response::poll_due());
          confirm_status("complete");
          assert(puck_response::follow_up_pending());
          if (std::string("FAILURE") == "source_error")
            puck_http_source.state = media_source::MediaSourceState::ERROR;
          else
            ++puck_speaker.errors;
          follow_up_tick(); // Even an earlier completed receipt cannot authorize a newly failed output.
          assert(puck_response::refusal_pending());
          assert(admission_requests == 0 && !capture::capturing && mww.diagnostic_starts == 0);
          assert(!puck_audio_handoff::response_audio_requested);
          recovery_tick();
          fake_millis += puck_response::REFUSAL_WATCHDOG_MS;
          stop_output_completes(); // Refusal stop acknowledged by both actual source/TX fixtures.
          recovery_tick();
          assert(puck_response::state == puck_response::State::IDLE && mww.starts == 1);
          assert(admission_requests == 0 && !capture::capturing);
        }
    '''.replace("FAILURE", failure))


@pytest.mark.parametrize("held_source", ["http", "local"])
def test_configured_active_source_blocks_stopped_tx_follow_up(tmp_path, held_source):
    _native(tmp_path, r'''
        int main() {
          setup_fixture();
          request_nonempty_response();
          puck_resampler.completed = 11;
          stop_output_completes();
          auto &held = std::string("HELD_SOURCE") == "http" ? puck_http_source : puck_local_source;
          held.state = media_source::MediaSourceState::READING;
          fast_tick();
          assert(!puck_audio_handoff::current_output().source_idle);
          assert(!puck_audio_handoff::drained(puck_audio_handoff::current_output()));
          assert(puck_response::state == puck_response::State::WAITING_FOR_MEDIA_IDLE);
          published_idle(); // Even if player IDLE is published ahead of its source.
          confirm_status("complete");
          follow_up_tick();
          fake_millis += puck_audio_handoff::FOLLOW_UP_SETTLE_MS;
          follow_up_tick();
          assert(admission_requests == 0 && !capture::capturing);
          held.state = media_source::MediaSourceState::IDLE;
          follow_up_tick(); // Fresh stable settle starts after actual source IDLE.
          fake_millis += puck_audio_handoff::FOLLOW_UP_SETTLE_MS;
          follow_up_tick();
          assert(admission_requests == 1 && capture::capturing && mww.starts == 1);
        }
    '''.replace("HELD_SOURCE", held_source))


def test_configured_late_fault_after_silent_waits_five_seconds_fail_closed_then_actual_ack(tmp_path):
    _native(tmp_path, r'''
        int main() {
          setup_fixture();
          request_nonempty_response();
          puck_resampler.completed = 11;
          stop_output_completes();
          published_idle();
          confirm_status("silent");
          assert(puck_response::ready_to_resume());
          // Fault/output activity appears after SILENT, before the 250ms wake action.
          ++puck_speaker.errors;
          puck_resampler.stopped = puck_speaker.stopped = false;
          puck_resampler.buffered = puck_speaker.buffered = true;
          puck_http_source.state = media_source::MediaSourceState::READING;
          recovery_tick();
          assert(puck_response::playback_cleanup_pending && mww.starts == 0);
          assert(!puck_response::ready_to_resume());
          puck_response::wake_resumed(); // Header API itself must also remain fail-closed.
          assert(puck_response::state == puck_response::State::READY_TO_RESUME);
          fast_tick();
          assert(media_stops == 1 && puck_response::playback_cleanup_stop_requested);
          const auto requested = puck_response::playback_cleanup_started_ms;
          fake_millis = requested + puck_response::PLAYBACK_CLEANUP_TIMEOUT_MS - 1;
          fast_tick();
          recovery_tick();
          assert(!puck_response::playback_cleanup_unavailable && mww.starts == 0);
          ++fake_millis;
          fast_tick();
          assert(puck_response::playback_cleanup_unavailable && puck_identity::unavailable_visible);
          assert(unavailable_notifications == 1 && mww.starts == 0 && media_stops == 1);
          fake_millis += puck_response::PLAYBACK_CLEANUP_TIMEOUT_MS;
          fast_tick();
          recovery_tick();
          assert(unavailable_notifications == 1 && puck_response::playback_cleanup_pending);
          assert(!capture::capturing && admission_requests == 0 && mww.starts == 0);
          assert(puck_resampler.completed == 11); // Old receipt is not a new cleanup receipt.
          stop_output_completes();
          fast_tick();
          assert(!puck_response::playback_cleanup_pending);
          assert(!puck_audio_handoff::response_audio_requested && !puck_audio_handoff::follow_up.active());
          recovery_tick();
          assert(puck_response::state == puck_response::State::IDLE && mww.starts == 1);
          fast_tick(); // The old error counter cannot re-arm cleanup after its actual acknowledgement.
          assert(!puck_response::playback_cleanup_pending && media_stops == 1);
          assert(media_requests == 1 && media_urls.empty() && admission_requests == 0);
        }
    ''')


def test_configured_unowned_refusal_tail_enters_bounded_fail_closed_cleanup(tmp_path):
    _native(tmp_path, r'''
        int main() {
          setup_fixture();
          request_nonempty_response();
          puck_resampler.completed = 11;
          stop_output_completes();
          fast_tick();
          confirm_status("complete");
          ++puck_speaker.errors;
          follow_up_tick();
          assert(puck_response::refusal_pending());
          assert(!puck_audio_handoff::response_audio_requested);
          recovery_tick();
          assert(puck_response::state == puck_response::State::REFUSAL_PLAYING);
          assert(media_stops == 1 && media_requests == 2);
          puck_media_player.state = media_player::MEDIA_PLAYER_STATE_ANNOUNCING;
          puck_resampler.generation = 12;
          puck_resampler.stopped = puck_speaker.stopped = false;
          puck_resampler.buffered = puck_speaker.buffered = true;
          puck_local_source.state = media_source::MediaSourceState::READING;
          fake_millis = puck_response::refusal_started_ms + puck_response::REFUSAL_WATCHDOG_MS;
          recovery_tick(); // Refusal watchdog stops, but does not invent physical stop acknowledgement.
          assert(puck_response::state == puck_response::State::READY_TO_RESUME);
          assert(puck_response::playback_cleanup_pending && mww.starts == 0);
          assert(media_stops == 2);
          fast_tick();
          assert(puck_response::playback_cleanup_stop_requested && media_stops == 3);
          fake_millis = puck_response::playback_cleanup_started_ms +
                        puck_response::PLAYBACK_CLEANUP_TIMEOUT_MS;
          fast_tick();
          recovery_tick();
          assert(puck_response::playback_cleanup_unavailable && unavailable_notifications == 1);
          assert(puck_identity::unavailable_visible && mww.starts == 0);
          fake_millis += puck_response::PLAYBACK_CLEANUP_TIMEOUT_MS;
          fast_tick();
          recovery_tick();
          assert(unavailable_notifications == 1 && media_stops == 3);
          assert(puck_response::playback_cleanup_pending && !capture::capturing);
          stop_output_completes();
          fast_tick();
          assert(!puck_response::playback_cleanup_pending && puck_resampler.completed == 11);
          recovery_tick();
          assert(puck_response::state == puck_response::State::IDLE && mww.starts == 1);
          assert(media_requests == 2 && admission_requests == 0 && !capture::capturing);
        }
    ''')


def test_configured_early_refusal_idle_waits_for_natural_tail_without_truncation(tmp_path):
    _native(tmp_path, r'''
        int main() {
          setup_fixture();
          request_nonempty_response();
          puck_resampler.completed = 11;
          stop_output_completes();
          fast_tick();
          confirm_status("unavailable");
          recovery_tick();
          assert(puck_response::state == puck_response::State::REFUSAL_PLAYING);
          const auto refusal_start = puck_response::refusal_started_ms;
          assert(media_stops == 1 && media_requests == 2);
          puck_resampler.generation = 12;
          puck_resampler.stopped = puck_speaker.stopped = false;
          puck_resampler.buffered = puck_speaker.buffered = true;
          puck_local_source.state = media_source::MediaSourceState::READING;
          fake_millis = refusal_start + 100;
          published_idle(); // Source/player can publish IDLE before physical TX's short tail.
          assert(puck_response::state == puck_response::State::READY_TO_RESUME);
          recovery_tick();
          fast_tick();
          assert(!puck_response::playback_cleanup_pending && media_stops == 1 && mww.starts == 0);
          fake_millis = refusal_start + 359;
          recovery_tick();
          assert(!puck_response::playback_cleanup_pending && media_stops == 1 && mww.starts == 0);
          fake_millis = refusal_start + 360;
          stop_output_completes();
          puck_resampler.completed = 12; // Fixture hardware reports the ordinary tone's natural drain.
          fast_tick();
          recovery_tick();
          assert(puck_response::state == puck_response::State::IDLE && mww.starts == 1);
          assert(media_stops == 1 && media_requests == 2 && !puck_response::playback_cleanup_pending);
          assert(admission_requests == 0 && !capture::capturing);
        }
    ''')
