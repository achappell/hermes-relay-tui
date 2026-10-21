"""Execute public/internal detection dispatch into the real wake capture boundary."""

from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from tests.test_puck_firmware import _compile_and_run_capture_harness, _write_capture_stubs

ROOT = Path(__file__).resolve().parents[1]


def test_internal_events_cannot_reach_real_capture_or_upload(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("native C++ compiler unavailable")
    _write_capture_stubs(tmp_path)
    _compile_and_run_capture_harness(tmp_path, compiler, r'''
        #include "components/micro_wake_word/detection_event.h"
        #include "pcm_capture.h"
        #include <cassert>
        #include <vector>
        #include <cstring>
        #include <type_traits>
        using namespace esphome::micro_wake_word;
        namespace capture = pcm_capture::wake_capture;
        std::uint32_t fake_millis = 0;
        struct ModelFixture {
          std::string *word;
          bool internal;
          bool get_internal_only() const { return internal; }
          DetectionEvent determine_detected() {
            DetectionEvent event;
            event.wake_word = word;
            event.detected = true;
            return event;
          }
        };
        DetectionEvent queued_detection(ModelFixture &model) {
          static_assert(std::is_trivially_copyable<DetectionEvent>::value);
          const auto produced = make_model_detection(model);
          DetectionEvent received;
          std::memcpy(&received, &produced, sizeof(received)); // FreeRTOS queue byte-copy contract
          return received;
        }
        struct CaptureTrigger {
          unsigned calls = 0;
          void trigger(const std::string &name) {
            ++calls;
            // Exercise the existing real authorization/admission path, not a
            // fake capture function. A synthetic admitted reply is fixture data.
            const auto seq = capture::pending_sequence();
            assert(puck_response::begin_home_admission(seq));
            puck_response::note_home_admission(200, "admitted:" + std::to_string(seq));
            capture::prepare(name);
            capture::start_pending();
          }
        };
        int main() {
          puck_identity::setup("fixture-device-identity");
          capture::setup();
          CaptureTrigger trigger;
          esphome::http_request::HttpRequestComponent client;
          std::string stop = "Stop", public_word = "hey missy", arbitrary = "future internal model";
          const DetectionEvent unspecified;
          assert(unspecified.internal_only);
          assert(!dispatch_public_detection(unspecified, trigger));
          for (auto *word : {&stop, &arbitrary, &public_word}) {
            ModelFixture model{word, true};
            const DetectionEvent internal = queued_detection(model);
            assert(internal.internal_only);
            assert(!is_public_wake_model(internal.internal_only));
            assert(detection_route(internal) == DetectionRoute::INTERNAL_CONTROL);
            assert(!dispatch_public_detection(internal, trigger));
            capture::upload(&client, "http://fixture/upload", "fixture-token");
            assert(trigger.calls == 0 && !capture::capturing && !capture::wake_pending);
            assert(!capture::capture_pending_upload && client.urls.empty());
            assert(!puck_response::home_admission_in_flight() && !puck_response::home_admission_granted());
          }
          ModelFixture public_model{nullptr, false};
          DetectionEvent event = queued_detection(public_model);
          assert(!event.internal_only); // model provenance, not a manually public event
          assert(detection_route(event) == DetectionRoute::IGNORED); // no word
          assert(!dispatch_public_detection(event, trigger));
          public_model.word = &public_word;
          event = queued_detection(public_model);
          event.detected = false;
          assert(!dispatch_public_detection(event, trigger));
          event.detected = true;
          event.blocked_by_vad = true;
          assert(detection_route(event) == DetectionRoute::VAD_BLOCKED);
          assert(!dispatch_public_detection(event, trigger));
          assert(trigger.calls == 0 && client.urls.empty());
          event.blocked_by_vad = false;
          assert(is_public_wake_model(event.internal_only));
          assert(dispatch_public_detection(event, trigger));
          assert(trigger.calls == 1 && capture::capturing);
          // Internal events must not disturb a public capture already in flight.
          DetectionEvent internal;
          internal.wake_word = &stop;
          internal.detected = true;
          assert(!dispatch_public_detection(internal, trigger));
          assert(trigger.calls == 1 && capture::capturing);
          capture::tick(true, true, next_vad_generation());  // speech precedes the full buffer
          std::vector<uint8_t> synthetic_pcm(capture::WAKE_CAPTURE_BYTES, 0x35);
          capture::write(synthetic_pcm.data(), synthetic_pcm.size());
          assert(!capture::capturing && capture::capture_pending_upload);
          capture::upload(&client, "http://fixture/upload", "fixture-token");
          size_t bytes = 0;
          for (const auto &body : client.bodies) bytes += body.size();
          assert(bytes == synthetic_pcm.size() && capture::last_upload_delivered);
          const auto requests = client.urls.size();
          assert(!dispatch_public_detection(internal, trigger));
          capture::upload(&client, "http://fixture/upload", "fixture-token");
          assert(trigger.calls == 1 && client.urls.size() == requests);
        }
    ''', extra_flags=("-fsanitize=address,undefined", "-fno-sanitize-recover=all"))


def test_actual_esphome_configuration_preserves_arbitrary_internal_roles(tmp_path):
    esphome = ROOT / "venv-firmware/bin/esphome"
    if not esphome.is_file():
        pytest.skip("firmware ESPHome environment is not installed")
    firmware = ROOT / "firmware/respeaker-lite"
    config = {
        "esphome": {"name": "p10-role-check", "build_path": str(tmp_path / "build")},
        "esp32": {"board": "seeed_xiao_esp32s3", "framework": {"type": "esp-idf"}},
        "external_components": [{"source": {"type": "local", "path": str(firmware / "components")}, "components": ["i2s_audio", "micro_wake_word"]}],
        "i2s_audio": [{"id": "input_bus", "i2s_lrclk_pin": "GPIO7", "i2s_bclk_pin": "GPIO8"}],
        "microphone": [{"platform": "i2s_audio", "id": "mic", "i2s_audio_id": "input_bus", "i2s_din_pin": "GPIO44", "adc_type": "external", "pdm": False, "sample_rate": 48000, "bits_per_sample": "32bit", "i2s_mode": "secondary", "channel": "stereo"}],
        "micro_wake_word": {
            "microphone": {"microphone": "mic", "channels": 1},
            "models": [
                {"id": "public_model", "model": str(firmware / "wake_models/hey_missy.json"), "internal": False},
                {"id": "stop_control", "model": str(firmware / "wake_models/stop.json"), "internal": True},
                {"id": "additional_internal", "model": str(firmware / "wake_models/hey_bestie.json"), "internal": True},
            ],
        },
    }
    path = tmp_path / "roles.yaml"
    path.write_text(yaml.safe_dump(config))
    result = subprocess.run([str(esphome), "config", str(path)], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    normalized = yaml.load(result.stdout, Loader=yaml.BaseLoader)
    roles = {model["id"]: model["internal"] for model in normalized["micro_wake_word"]["models"]}
    assert roles == {"public_model": "false", "stop_control": "true", "additional_internal": "true"}
