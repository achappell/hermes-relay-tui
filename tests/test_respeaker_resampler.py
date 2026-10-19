"""Exercise the vendored resampler worker/control code, not a copied lifecycle model.

RTOS scheduling, DSP conversion and the TX device are deterministic native stubs;
the production resampler_speaker.cpp and its public receipt API are compiled as-is.
No ESPHome installation, hardware, microphone or network is used by these tests.
"""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "firmware/respeaker-lite/components/resampler/speaker/resampler_speaker.cpp"

STUBS = r"""
#pragma once
#include <algorithm>
#include <cassert>
#include <cinttypes>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <utility>
#include <vector>

using TickType_t = uint32_t;
using UBaseType_t = uint32_t;
using esp_err_t = int;
constexpr int ESP_OK = 0;
constexpr int ESP_ERR_NO_MEM = 1;
constexpr int ESP_ERR_NOT_SUPPORTED = 2;
constexpr int ESP_FAIL = 3;
#define ESP_LOGCONFIG(...) ((void) 0)
#define ESP_LOGD(...) ((void) 0)
#define ESP_LOGV(...) ((void) 0)
#define ESP_LOGE(...) ((void) 0)
#define LOG_STR(x) x

struct Events { uint32_t bits{0}; };
using EventGroupHandle_t = Events *;
inline std::vector<std::unique_ptr<Events>> event_groups;
inline EventGroupHandle_t xEventGroupCreate() {
  event_groups.push_back(std::make_unique<Events>());
  return event_groups.back().get();
}
inline uint32_t xEventGroupGetBits(EventGroupHandle_t e) { return e->bits; }
inline uint32_t xEventGroupSetBits(EventGroupHandle_t e, uint32_t bits) { return e->bits |= bits; }
inline uint32_t xEventGroupClearBits(EventGroupHandle_t e, uint32_t bits) {
  auto before = e->bits;
  e->bits &= ~bits;
  return before;
}
inline void vTaskDelay(TickType_t) {}

namespace esphome {
using std::make_unique;
namespace setup_priority { constexpr float DATA = 600; }
class Component {
 public:
  virtual ~Component() = default;
  virtual float get_setup_priority() const { return 0; }
  virtual void setup() {}
  virtual void dump_config() {}
  virtual void loop() {}
  void mark_failed() { failed = true; }
  void disable_loop() { loop_enabled = false; }
  void enable_loop_soon_any_context() { loop_enabled = true; }
  void status_set_error(const char *) { error = true; }
  void status_clear_error() { error = false; }
  bool error{false}, failed{false}, loop_enabled{true};
};
struct Application {
  uint32_t now{0};
  uint32_t get_loop_component_start_time() const { return now; }
  void wake_loop_threadsafe() {}
};
inline Application App;

class StaticTask {
 public:
  inline static bool fail_create{false};
  inline static StaticTask *pending{nullptr};
  bool create(void (*fn)(void *), const char *, uint32_t, void *arg, UBaseType_t, bool) {
    if (fail_create) return false;
    created = true;
    suspended = false;
    entry = fn;
    params = arg;
    pending = this;
    return true;
  }
  bool is_created() const { return created; }
  bool deallocate() {
    if (!suspended) return false;
    created = false;
    if (pending == this) pending = nullptr;
    return true;
  }
  static void run() {
    auto *task = pending;
    assert(task != nullptr && task->created && !task->suspended);
    task->entry(task->params);
    assert(task->suspended);
  }
  bool created{false}, suspended{false};
  void (*entry)(void *){nullptr};
  void *params{nullptr};
};

namespace audio {
class AudioStreamInfo {
 public:
  AudioStreamInfo(uint8_t bits = 16, uint8_t channels = 1, uint32_t rate = 16000)
      : bits_(bits), channels_(channels), rate_(rate) {}
  uint8_t get_bits_per_sample() const { return bits_; }
  uint8_t get_channels() const { return channels_; }
  uint32_t get_sample_rate() const { return rate_; }
  size_t ms_to_bytes(uint32_t ms) const { return size_t(ms) * rate_ / 1000 * channels_ * bits_ / 8; }
 private:
  uint8_t bits_, channels_;
  uint32_t rate_;
};
}
namespace speaker {
enum State : uint8_t { STATE_STOPPED, STATE_STARTING, STATE_RUNNING, STATE_STOPPING };
class Speaker {
 public:
  virtual ~Speaker() = default;
  virtual size_t play(const uint8_t *, size_t, TickType_t) = 0;
  virtual size_t play(const uint8_t *data, size_t size) = 0;
  virtual void start() = 0;
  virtual void stop() = 0;
  virtual void finish() { stop(); }
  virtual bool has_buffered_data() const = 0;
  virtual bool get_pause_state() const { return false; }
  virtual void set_pause_state(bool) {}
  virtual void set_mute_state(bool value) { mute_state_ = value; }
  virtual bool get_mute_state() { return mute_state_; }
  virtual void set_volume(float value) { volume_ = value; }
  virtual float get_volume() { return volume_; }
  bool is_running() const { return state_ == STATE_RUNNING; }
  bool is_stopped() const { return state_ == STATE_STOPPED; }
  void set_audio_stream_info(const audio::AudioStreamInfo &info) { audio_stream_info_ = info; }
  template<typename F> void add_audio_output_callback(F callback) { audio_output_callback_ = callback; }
 protected:
  State state_{STATE_STOPPED};
  audio::AudioStreamInfo audio_stream_info_;
  bool mute_state_{false};
  float volume_{1.0f};
  std::function<void(uint32_t, int64_t)> audio_output_callback_ = [](uint32_t, int64_t) {};
};
}
namespace ring_buffer {
class RingBuffer {
 public:
  inline static bool fail_create{false};
  static std::shared_ptr<RingBuffer> create(size_t capacity) {
    if (fail_create) return nullptr;
    return std::make_shared<RingBuffer>(capacity);
  }
  explicit RingBuffer(size_t capacity) : capacity_(capacity) {}
  size_t available() const { return data.size(); }
  size_t write_without_replacement(const uint8_t *bytes, size_t size, TickType_t) {
    size = std::min(size, capacity_ - data.size());
    data.insert(data.end(), bytes, bytes + size);
    return size;
  }
  std::vector<uint8_t> data;
 private:
  size_t capacity_;
};
}
namespace audio {
enum class AudioResamplerState { RESAMPLING, FINISHED, FAILED };
class AudioResampler {
 public:
  inline static esp_err_t start_error{ESP_OK}, source_error{ESP_OK}, sink_error{ESP_OK};
  inline static bool fail_resample{false};
  inline static std::function<void(bool)> tick;
  inline static size_t source_consumed{0}, output_written{0};
  inline static unsigned graceful_calls{0};
  AudioResampler(size_t, size_t) {}
  esp_err_t start(AudioStreamInfo &input, AudioStreamInfo &output, uint16_t, uint16_t) {
    ratio = output.get_sample_rate() / input.get_sample_rate();
    return start_error;
  }
  esp_err_t add_source(std::weak_ptr<ring_buffer::RingBuffer> &source) {
    source_ = source.lock();
    return source_error;
  }
  esp_err_t add_sink(speaker::Speaker *sink) { sink_ = sink; return sink_error; }
  AudioResamplerState resample(bool graceful, int32_t *differential) {
    if (tick) tick(graceful);
    if (fail_resample) return AudioResamplerState::FAILED;
    *differential = 0;
    if (graceful) ++graceful_calls;
    if (graceful && source_->available() == 0 && pending.empty()) return AudioResamplerState::FINISHED;
    if (!pending.empty()) {
      const size_t written = sink_->play(pending.data(), pending.size(), 0);
      output_written += written;
      pending.erase(pending.begin(), pending.begin() + written);
    }
    if (pending.empty()) {
      const size_t count = std::min(size_t(192), source_->available());
      assert(count % 2 == 0);
      for (size_t i = 0; i < count; i += 2) {
        for (unsigned copy = 0; copy < ratio; ++copy) {
          pending.push_back(source_->data[i]);
          pending.push_back(source_->data[i + 1]);
        }
      }
      source_->data.erase(source_->data.begin(), source_->data.begin() + count);
      source_consumed += count;
    }
    return AudioResamplerState::RESAMPLING;
  }
 private:
  unsigned ratio{1};
  std::shared_ptr<ring_buffer::RingBuffer> source_;
  speaker::Speaker *sink_{nullptr};
  std::vector<uint8_t> pending;
};
}
}
inline void vTaskSuspend(void *) { esphome::StaticTask::pending->suspended = true; }
"""

HARNESS = r"""
#include "resampler_stubs.h"
#include "RESAMPLER_SOURCE"
#include <string>
using namespace esphome;
using resampler::ResamplerSpeaker;
using audio::AudioResampler;

static uint32_t output_errors = 0;
static uint32_t error_generation() { return output_errors; }

class Output final : public speaker::Speaker {
 public:
  void start() override {
    ++starts;
    state_ = refuse_start ? speaker::STATE_STOPPED : speaker::STATE_RUNNING;
  }
  void stop() override { ++stops; buffered = false; state_ = speaker::STATE_STOPPED; }
  void finish() override {
    ++finishes;
    bytes_at_finish = bytes.size();
    state_ = speaker::STATE_STOPPING;
  }
  void drain() { buffered = false; state_ = speaker::STATE_STOPPED; }
  void fault() { ++output_errors; buffered = false; state_ = speaker::STATE_STOPPED; }
  size_t play(const uint8_t *data, size_t size, TickType_t) override {
    assert(finishes == 0);  // No output bytes may be delivered after TX finish.
    if (!is_running()) return 0;
    size = std::min(size, write_limit);
    bytes.insert(bytes.end(), data, data + size);
    buffered |= size > 0;
    return size;
  }
  size_t play(const uint8_t *data, size_t size) override { return play(data, size, 0); }
  bool has_buffered_data() const override { return buffered; }
  bool get_pause_state() const override { return paused; }
  void set_pause_state(bool value) override { paused = value; }
  size_t write_limit{128}, bytes_at_finish{0};
  bool buffered{false}, paused{false}, refuse_start{false};
  int starts{0}, stops{0}, finishes{0};
  std::vector<uint8_t> bytes;
};

struct Fixture {
  Output output;
  ResamplerSpeaker resampler;
  explicit Fixture(uint32_t rate = 16000, bool callback = true) {
    App.now = 0;
    StaticTask::fail_create = false;
    ring_buffer::RingBuffer::fail_create = false;
    AudioResampler::start_error = AudioResampler::source_error = AudioResampler::sink_error = ESP_OK;
    AudioResampler::fail_resample = false;
    AudioResampler::source_consumed = AudioResampler::output_written = AudioResampler::graceful_calls = 0;
    AudioResampler::tick = nullptr;
    resampler.set_output_speaker(&output);
    if (callback) resampler.set_output_error_generation_callback(error_generation);
    resampler.set_audio_stream_info(audio::AudioStreamInfo(16, 1, rate));
    resampler.set_target_sample_rate(48000);
    resampler.set_passthrough_bits_per_sample(true);
    resampler.set_buffer_duration(100);
    resampler.set_taps(16);
    resampler.set_filters(16);
    resampler.setup();
  }
  void start() {
    resampler.start();
    resampler.loop();
    resampler.loop();
    assert(resampler.is_running());
  }
  void collect_worker() { resampler.loop(); resampler.loop(); }
  void complete() {
    collect_worker();
    assert(!resampler.is_stopped());  // TX still owns buffered bytes / DMA.
    assert(resampler.completed_playback_generation() == 0);
    output.drain();
    resampler.loop();
    assert(resampler.is_stopped());
    assert(!resampler.has_buffered_data());
  }
};

static std::vector<uint8_t> pcm(size_t size) {
  std::vector<uint8_t> result(size);
  for (size_t i = 0; i < size; ++i) result[i] = uint8_t(i * 37 + 11);
  return result;
}

static void buffered_eof(uint32_t rate, size_t size) {
  Fixture f(rate);
  auto source = pcm(size);
  size_t accepted = 0;
  bool eof = false;
  unsigned ticks = 0;
  f.start();
  assert(f.resampler.playback_generation() == 0);  // start alone is not a cue receipt.
  AudioResampler::tick = [&](bool) {
    assert(++ticks < 10000);
    if (!eof) {
      accepted += f.resampler.play(source.data() + accepted, source.size() - accepted);
      if (accepted == source.size()) {
        assert(f.resampler.has_buffered_data());
        eof = true;
        f.resampler.start();  // A duplicate START pending with EOF must not suppress FINISH.
        f.resampler.finish();
      }
    }
    f.resampler.loop();
    assert(f.resampler.completed_playback_generation() == 0);
  };
  StaticTask::run();
  assert(eof);
  f.complete();
  assert(AudioResampler::graceful_calls > 0);
  assert(AudioResampler::source_consumed == accepted);
  assert(f.output.finishes == 1 && f.output.stops == 0);
  assert(f.output.bytes_at_finish == size * (48000 / rate));
  assert(f.output.bytes.size() == f.output.bytes_at_finish);
  for (size_t i = 0; i < size; i += 2) {
    for (unsigned copy = 0; copy < 48000 / rate; ++copy) {
      const size_t offset = i * (48000 / rate) + copy * 2;
      assert(f.output.bytes[offset] == source[i] && f.output.bytes[offset + 1] == source[i + 1]);
    }
  }
  assert(f.resampler.playback_generation() == 1);
  assert(f.resampler.completed_playback_generation() == 1);
}

static void early_eof(bool passthrough) {
  Fixture f(passthrough ? 48000 : 16000);
  f.resampler.start();
  f.resampler.finish();  // Both commands pending before even the first main-loop tick.
  f.resampler.loop();
  f.resampler.loop();
  assert(f.resampler.is_running());
  f.resampler.loop();
  if (!passthrough) StaticTask::run();
  f.complete();
  assert(f.output.starts == 1 && f.output.finishes == 1 && f.output.stops == 0);
  assert(f.resampler.playback_generation() == 0);
  assert(f.resampler.completed_playback_generation() == 0);  // No accepted bytes, no fabricated cue.
}

static void passthrough(bool callback, bool fault, bool force) {
  Fixture f(48000, callback);
  auto source = pcm(128);
  f.start();
  assert(f.resampler.play(source.data(), source.size()) == source.size());
  assert(f.resampler.playback_generation() == 1);
  f.resampler.finish();
  f.resampler.loop();
  assert(f.output.finishes == 1);
  assert(f.resampler.play(source.data(), source.size()) == 0);
  assert(f.resampler.completed_playback_generation() == 0);
  if (fault) f.output.fault();
  else if (force) { f.resampler.stop(); f.resampler.loop(); }
  else f.output.drain();
  f.resampler.loop();
  assert(f.resampler.is_stopped());
  assert(f.resampler.completed_playback_generation() == (callback && !fault && !force ? 1u : 0u));
  assert(f.output.bytes == source);
}

static void accepted_during_startup() {
  Fixture f(48000);
  auto source = pcm(64);
  f.resampler.start();
  f.resampler.loop();  // TX is accepting bytes; wrapper has not observed RUNNING yet.
  assert(!f.resampler.is_running());
  assert(f.resampler.play(source.data(), source.size()) == source.size());
  assert(f.resampler.playback_generation() == 1);
  f.resampler.finish();
  f.resampler.loop();
  f.resampler.loop();
  assert(f.output.finishes == 1 && f.output.bytes_at_finish == source.size());
  assert(f.resampler.completed_playback_generation() == 0);
  f.output.drain();
  f.resampler.loop();
  assert(f.resampler.is_stopped());
  assert(f.resampler.completed_playback_generation() == 1);
}

static void worker_failure(const std::string &kind) {
  Fixture f;
  if (kind == "task") StaticTask::fail_create = true;
  if (kind == "alloc") ring_buffer::RingBuffer::fail_create = true;
  if (kind == "unsupported") AudioResampler::start_error = ESP_ERR_NOT_SUPPORTED;
  if (kind == "start") AudioResampler::start_error = ESP_FAIL;
  if (kind == "sink") AudioResampler::sink_error = ESP_ERR_NO_MEM;
  if (kind == "source") AudioResampler::source_error = ESP_FAIL;
  f.resampler.start();
  f.resampler.loop();
  if (kind != "task") {
    f.resampler.loop();
    if (kind == "resample") {
      AudioResampler::tick = [&](bool) {
        auto source = pcm(128);
        assert(f.resampler.play(source.data(), source.size()) == source.size());
        f.resampler.finish();
        f.resampler.loop();
        AudioResampler::fail_resample = true;
      };
    }
    StaticTask::run();
  }
  f.collect_worker();
  assert(f.resampler.is_stopped());
  assert(f.output.finishes == 0);
  assert(f.output.stops > 0);
  assert(f.resampler.completed_playback_generation() == 0);
  assert(f.resampler.playback_generation() == (kind == "resample" ? 1u : 0u));
}

static void forced_stop(const std::string &kind) {
  Fixture f;
  auto source = pcm(3200);
  bool injected = false;
  unsigned ticks = 0;
  f.start();
  AudioResampler::tick = [&](bool) {
    assert(++ticks < 100);
    if (!injected) {
      assert(f.resampler.play(source.data(), source.size()) == source.size());
      f.resampler.finish();
      f.resampler.loop();
      assert(f.output.finishes == 0);  // EOF cannot finish TX ahead of source drain.
      injected = true;
      if (kind == "stop") f.resampler.stop();
      else if (kind == "fault") f.output.fault();
      else if (kind == "paused") f.output.paused = true;
      else { f.output.write_limit = 0; App.now += 5001; }
    }
    f.resampler.loop();
    if (kind == "fault") assert(f.output.stops > 0);  // Explicit fault aborts without waiting for timeout.
  };
  StaticTask::run();
  f.collect_worker();
  assert(f.resampler.is_stopped());
  assert(f.output.finishes == 0);
  assert(f.output.stops > 0);
  assert(f.resampler.playback_generation() == 1);
  assert(f.resampler.completed_playback_generation() == 0);
}

static void consecutive_generations() {
  Fixture f(48000);
  auto source = pcm(32);
  const uint32_t errors_before = output_errors;
  for (uint32_t generation = 1; generation <= 4; ++generation) {
    f.output.finishes = 0;
    f.start();
    assert(f.resampler.play(source.data(), source.size()) == source.size());
    assert(f.resampler.playback_generation() == generation);
    assert(f.resampler.completed_playback_generation() == (generation == 1 ? 0u : 1u));
    f.resampler.finish();
    f.resampler.loop();
    if (generation == 1 || generation == 4) f.output.drain();
    else if (generation == 2) { f.resampler.stop(); f.resampler.loop(); }
    else f.output.fault();
    f.resampler.loop();
    assert(f.resampler.is_stopped());
    assert(f.resampler.completed_playback_generation() == (generation == 4 ? 4u : 1u));
    assert(output_errors == errors_before + (generation >= 3 ? 1u : 0u));
  }
}

static void start_timeout() {
  Fixture f(48000);
  f.output.refuse_start = true;
  f.resampler.start();
  f.resampler.finish();
  f.resampler.loop();
  App.now += 5001;
  f.resampler.loop();
  f.resampler.loop();
  assert(f.resampler.is_stopped());
  assert(f.output.finishes == 0 && f.output.stops > 0);
  assert(f.resampler.completed_playback_generation() == 0);
}

int main(int argc, char **argv) {
  assert(argc == 2);
  const std::string scenario = argv[1];
  if (scenario == "short-cue") buffered_eof(16000, 2560);
  else if (scenario == "tts-24k") buffered_eof(24000, 24000);
  else if (scenario == "early-eof") early_eof(false);
  else if (scenario == "early-eof-passthrough") early_eof(true);
  else if (scenario == "passthrough") passthrough(true, false, false);
  else if (scenario == "startup-accepted") accepted_during_startup();
  else if (scenario == "no-error-receipt") passthrough(false, false, false);
  else if (scenario == "downstream-fault") passthrough(true, true, false);
  else if (scenario == "stop-after-finish") passthrough(true, false, true);
  else if (scenario == "generations") consecutive_generations();
  else if (scenario == "start-timeout") start_timeout();
  else if (scenario.rfind("fail-", 0) == 0) worker_failure(scenario.substr(5));
  else forced_stop(scenario);
}
"""


@pytest.fixture(scope="module")
def resampler_binary(tmp_path_factory):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("native C++ compiler unavailable")
    directory = tmp_path_factory.mktemp("resampler_native")
    (directory / "resampler_stubs.h").write_text(STUBS)
    for relative in (
        "esphome/components/audio/audio.h",
        "esphome/components/audio/audio_transfer_buffer.h",
        "esphome/components/audio/audio_resampler.h",
        "esphome/components/ring_buffer/ring_buffer.h",
        "esphome/components/speaker/speaker.h",
        "esphome/core/component.h",
        "esphome/core/static_task.h",
        "esphome/core/application.h",
        "esphome/core/defines.h",
        "esphome/core/helpers.h",
        "esphome/core/log.h",
        "freertos/event_groups.h",
    ):
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('#include "resampler_stubs.h"\n')
    harness = directory / "resampler_native.cpp"
    harness.write_text(HARNESS.replace("RESAMPLER_SOURCE", SOURCE.as_posix()))
    binary = directory / "resampler_native"
    result = subprocess.run(
        [compiler, "-std=c++17", "-DUSE_ESP32", "-Wall", "-Wextra",
         "-Wno-unused-variable", "-Wno-unused-const-variable",
         "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
         "-I", str(directory), str(harness), "-o", str(binary)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize("scenario", [
    "short-cue", "tts-24k", "early-eof", "early-eof-passthrough", "passthrough",
    "no-error-receipt", "downstream-fault", "stop-after-finish", "generations",
    "startup-accepted",
    "start-timeout", "fail-task", "fail-alloc", "fail-unsupported", "fail-start",
    "fail-source", "fail-sink", "fail-resample", "stop", "fault", "paused", "timeout",
])
def test_actual_resampler_drain_and_success_receipt(resampler_binary, scenario):
    result = subprocess.run(
        [str(resampler_binary), scenario], capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"{scenario}:\n{result.stdout}{result.stderr}"
