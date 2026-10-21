"""Fault-inject actual I2S speaker sources and their real resampler receipt consumer.

Only RTOS/IDF, buffers and allocator primitives are stubbed. Production speaker
base/standard and resampler translation units are compiled unchanged; assertions
observe runtime fault counters, DEBUG diagnostics and successful drain receipts.
"""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "firmware/respeaker-lite/components"

STUBS = r"""
#pragma once
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cinttypes>
#include <climits>
#include <cstdarg>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>
#include <sys/types.h>

using TickType_t = uint32_t;
using UBaseType_t = uint32_t;
using BaseType_t = int;
using esp_err_t = int;
constexpr int ESP_OK = 0, ESP_FAIL = -1, ESP_ERR_NO_MEM = 257;
constexpr int ESP_ERR_INVALID_STATE = 259, ESP_ERR_NOT_SUPPORTED = 262;
constexpr int INJECTED = 28673;
constexpr int pdTRUE = 1, pdFALSE = 0;
#define pdMS_TO_TICKS(ms) (ms)
#define IRAM_ATTR
#define ESP_IDF_VERSION_VAL(a,b,c) ((a)*10000+(b)*100+(c))
#define ESP_IDF_VERSION ESP_IDF_VERSION_VAL(5,5,5)
#define DMA_DESCRIPTOR_BUFFER_MAX_SIZE_4B_ALIGNED 4092
#define LOG_STR(x) x

namespace fake {
inline std::string scenario;
inline std::vector<std::string> logs;
inline std::function<void()> source_fill_hook;
inline bool failed_once{false}, event_alloc_fail{false}, task_alloc_fail{false};
inline bool silence_alloc_fail{false}, ring_alloc_fail{false}, source_alloc_fail{false};
inline bool in_worker{false};
inline unsigned queue_creates{0}, record_sends{0}, fill_calls{0};
inline uint32_t now{0};
inline size_t dma_size{960}, dma_progress{0};
struct TaskDone {};
inline void log(const char *format, ...) {
  char buffer[768];
  va_list args;
  va_start(args, format);
  vsnprintf(buffer, sizeof(buffer), format, args);
  va_end(args);
  logs.emplace_back(buffer);
}
}
#define ESP_LOGD(tag, ...) fake::log(__VA_ARGS__)
#define ESP_LOGE(...) ((void)0)
#define ESP_LOGV(...) ((void)0)
#define ESP_LOGCONFIG(...) ((void)0)
inline const char *esp_err_to_name(int code) {
  return code == INJECTED ? "INJECTED" : code == ESP_OK ? "ESP_OK" : "OTHER";
}
inline uint32_t millis() { return fake::now; }
inline int64_t esp_timer_get_time() { return int64_t(fake::now) * 1000; }
inline void vTaskDelay(TickType_t ticks) {
  fake::now += ticks;
  if (fake::in_worker) throw fake::TaskDone{};  // Worker reached its terminal delay-until-delete loop.
}
inline void vTaskSuspend(void *) { assert(false && "resampling task must not run in passthrough test"); }

struct Events { uint32_t bits{0}; };
using EventGroupHandle_t = Events *;
inline std::vector<std::unique_ptr<Events>> event_groups;
inline EventGroupHandle_t xEventGroupCreate() {
  if (fake::event_alloc_fail) return nullptr;
  event_groups.push_back(std::make_unique<Events>());
  return event_groups.back().get();
}
inline uint32_t xEventGroupGetBits(EventGroupHandle_t e) { return e->bits; }
inline uint32_t xEventGroupSetBits(EventGroupHandle_t e, uint32_t bits) { return e->bits |= bits; }
inline uint32_t xEventGroupClearBits(EventGroupHandle_t e, uint32_t bits) {
  const auto old = e->bits;
  e->bits &= ~bits;
  return old;
}
inline int xEventGroupSetBitsFromISR(EventGroupHandle_t e, uint32_t bits, BaseType_t *) {
  xEventGroupSetBits(e, bits);
  return pdTRUE;
}
struct Queue {
  size_t capacity, item_size;
  std::deque<std::vector<uint8_t>> items;
};
using QueueHandle_t = Queue *;
inline std::vector<std::unique_ptr<Queue>> queues;
inline QueueHandle_t xQueueCreate(size_t count, size_t size) {
  ++fake::queue_creates;
  if ((fake::scenario == "queue-first" && fake::queue_creates == 1) ||
      (fake::scenario == "queue-second" && fake::queue_creates == 2)) return nullptr;
  queues.push_back(std::make_unique<Queue>(Queue{count, size, {}}));
  return queues.back().get();
}
inline void xQueueReset(QueueHandle_t q) { q->items.clear(); }
inline int xQueueSend(QueueHandle_t q, const void *item, TickType_t) {
  if (q->item_size == sizeof(uint32_t)) {
    ++fake::record_sends;
    if ((fake::scenario == "preload-record" && fake::record_sends == 1) ||
        (fake::scenario == "write-record" && fake::record_sends == 6)) return pdFALSE;
  }
  if (q->items.size() >= q->capacity) return pdFALSE;
  const auto *bytes = static_cast<const uint8_t *>(item);
  q->items.emplace_back(bytes, bytes + q->item_size);
  return pdTRUE;
}
inline int xQueueReceive(QueueHandle_t q, void *item, TickType_t) {
  if (q->items.empty()) return pdFALSE;
  memcpy(item, q->items.front().data(), q->item_size);
  q->items.pop_front();
  return pdTRUE;
}
inline int xQueueIsQueueFullFromISR(QueueHandle_t q) { return q->items.size() == q->capacity; }
inline int xQueueReceiveFromISR(QueueHandle_t q, void *item, BaseType_t *) { return xQueueReceive(q, item, 0); }
inline int xQueueSendToBackFromISR(QueueHandle_t q, const void *item, BaseType_t *) { return xQueueSend(q, item, 0); }
struct Task { void (*entry)(void *); void *arg; bool deleted{false}; };
using TaskHandle_t = Task *;
inline std::vector<std::unique_ptr<Task>> tasks;
inline int xTaskCreate(void (*entry)(void *), const char *, size_t, void *arg, ssize_t, TaskHandle_t *handle) {
  if (fake::task_alloc_fail) { *handle = nullptr; return pdFALSE; }
  tasks.push_back(std::make_unique<Task>(Task{entry, arg, false}));
  *handle = tasks.back().get();
  return pdTRUE;
}
inline void vTaskDelete(TaskHandle_t task) { if (task != nullptr) task->deleted = true; }

using gpio_num_t = int;
using i2s_port_t = int;
using i2s_role_t = int;
using i2s_slot_mode_t = int;
using i2s_std_slot_mask_t = int;
using i2s_slot_bit_width_t = int;
using i2s_mclk_multiple_t = int;
using i2s_clock_src_t = int;
using i2s_data_bit_width_t = int;
constexpr int I2S_GPIO_UNUSED = -1, GPIO_MODE_OUTPUT = 1;
constexpr int I2S_ROLE_SLAVE = 1, I2S_SLOT_MODE_MONO = 1, I2S_SLOT_MODE_STEREO = 2;
constexpr int I2S_STD_SLOT_BOTH = 3, I2S_SLOT_BIT_WIDTH_AUTO = 0;
constexpr int I2S_MCLK_MULTIPLE_256 = 256, I2S_CLK_SRC_DEFAULT = 0;
struct i2s_std_gpio_config_t {
  int mclk, bclk, ws, dout, din;
  struct { bool mclk_inv, bclk_inv, ws_inv; } invert_flags;
};
struct i2s_chan_config_t {
  int id, role;
  size_t dma_desc_num;
  uint32_t dma_frame_num;
  bool auto_clear;
  int intr_priority;
};
struct i2s_std_clk_config_t { uint32_t sample_rate_hz; int clk_src, mclk_multiple; };
struct i2s_std_slot_config_t { int slot_bit_width{0}; uint32_t ws_width{0}; int slot_mask{0}; };
struct i2s_std_config_t {
  i2s_std_clk_config_t clk_cfg;
  i2s_std_slot_config_t slot_cfg;
  i2s_std_gpio_config_t gpio_cfg;
};
#define I2S_STD_PCM_SLOT_DEFAULT_CONFIG(bits, mode) i2s_std_slot_config_t{}
#define I2S_STD_MSB_SLOT_DEFAULT_CONFIG(bits, mode) i2s_std_slot_config_t{}
#define I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(bits, mode) i2s_std_slot_config_t{}
struct Channel;
using i2s_chan_handle_t = Channel *;
struct i2s_event_data_t {};
struct i2s_event_callbacks_t { bool (*on_sent)(i2s_chan_handle_t, i2s_event_data_t *, void *); };
struct Channel {
  i2s_event_callbacks_t callbacks{};
  void *user{nullptr};
  bool deleted{false};
};
struct i2s_chan_info_t { size_t total_dma_buf_size; };
inline std::vector<std::unique_ptr<Channel>> channels;
inline int i2s_new_channel(const i2s_chan_config_t *, i2s_chan_handle_t *tx, void *) {
  if (fake::scenario == "channel-allocate") return INJECTED;
  channels.push_back(std::make_unique<Channel>());
  *tx = channels.back().get();
  return ESP_OK;
}
inline int i2s_channel_init_std_mode(i2s_chan_handle_t, const i2s_std_config_t *) {
  return fake::scenario == "channel-init" ? INJECTED : ESP_OK;
}
inline int i2s_del_channel(i2s_chan_handle_t channel) { channel->deleted = true; return ESP_OK; }
inline int i2s_channel_disable(i2s_chan_handle_t) { return ESP_OK; }
inline int gpio_reset_pin(int) { return ESP_OK; }
inline int gpio_set_direction(int, int) { return ESP_OK; }
inline int gpio_set_level(int, int) { return ESP_OK; }
inline int i2s_channel_get_info(i2s_chan_handle_t, i2s_chan_info_t *info) {
  info->total_dma_buf_size = fake::dma_size * 5;
  return ESP_OK;
}
inline int i2s_channel_preload_data(i2s_chan_handle_t, const void *, size_t bytes, size_t *loaded) {
  *loaded = fake::scenario == "preload-partial" ? bytes - 2 : bytes;
  return fake::scenario == "preload-error" ? INJECTED : ESP_OK;
}
inline int i2s_channel_register_event_callback(i2s_chan_handle_t channel,
                                              const i2s_event_callbacks_t *callbacks, void *user) {
  if (fake::scenario == "callback") return INJECTED;
  channel->callbacks = *callbacks;
  channel->user = user;
  return ESP_OK;
}
inline void emit(i2s_chan_handle_t channel) {
  if (channel->callbacks.on_sent != nullptr) {
    i2s_event_data_t event;
    channel->callbacks.on_sent(channel, &event, channel->user);
  }
}
inline int i2s_channel_enable(i2s_chan_handle_t channel) {
  if (fake::scenario == "enable") return INJECTED;
  if (fake::scenario == "desync") {
    queues.at(1)->items.clear();
    emit(channel);
  } else {
    const unsigned count = fake::scenario == "isr-overflow" ? 11 : 5;
    for (unsigned i = 0; i < count; ++i) emit(channel);
  }
  return ESP_OK;
}
inline int i2s_channel_write(i2s_chan_handle_t channel, const void *data, size_t bytes,
                            size_t *written, TickType_t) {
  assert(++fake::now < 20000);
  const bool real = bytes > 0 && static_cast<const uint8_t *>(data)[0] != 0;
  const std::string prefix = real ? "real-" : "silence-";
  const bool inject = !fake::failed_once && fake::scenario.rfind(prefix, 0) == 0;
  *written = inject && fake::scenario == prefix + "partial" ? bytes - 2 : bytes;
  fake::dma_progress += *written;
  if (fake::dma_progress >= fake::dma_size) {
    fake::dma_progress -= fake::dma_size;
    emit(channel);
  }
  if (inject) {
    fake::failed_once = true;
    if (fake::scenario == prefix + "error") return INJECTED;
  }
  return ESP_OK;
}

namespace esphome {
using std::make_unique;
using std::optional;
namespace setup_priority { constexpr float PROCESSOR = 600, DATA = 500; }
class Component {
 public:
  virtual ~Component() = default;
  virtual float get_setup_priority() const { return 0; }
  virtual void setup() {}
  virtual void dump_config() {}
  virtual void loop() {}
  bool is_ready() const { return true; }
  bool is_failed() const { return failed; }
  void mark_failed() { failed = true; }
  bool status_has_error() const { return error; }
  void status_momentary_error(const char *, uint32_t) { error = true; }
  void status_set_error(const char *) { error = true; }
  void status_clear_error() { error = false; }
  void disable_loop() {}
  void enable_loop_soon_any_context() {}
  bool error{false}, failed{false};
};
class Mutex {
 public:
  void lock() { locked = true; }
  bool try_lock() { if (locked) return false; locked = true; return true; }
  void unlock() { locked = false; }
  bool locked{false};
};
template<typename T> class Parented {
 public:
  void set_parent(T *parent) { parent_ = parent; }
 protected:
  T *parent_{nullptr};
};
template<typename T> class RAMAllocator {
 public:
  T *allocate(size_t count) { return fake::silence_alloc_fail ? nullptr : new T[count]; }
  void deallocate(T *data, size_t) { delete[] data; }
};
template<typename In, typename Out> Out remap(In value, In a, In b, Out c, Out d) {
  return c + (d - c) * (value - a) / (b - a);
}
struct Application {
  uint32_t get_loop_component_start_time() const { return fake::now; }
  void wake_loop_threadsafe() {}
};
inline Application App;
class StaticTask {
 public:
  bool is_created() const { return false; }
  bool deallocate() { return true; }
  bool create(void (*)(void *), const char *, uint32_t, void *, UBaseType_t, bool) {
    assert(false && "unexpected resampling worker in passthrough test");
    return false;
  }
};
namespace audio {
class AudioStreamInfo {
 public:
  AudioStreamInfo(uint8_t bits = 16, uint8_t channels = 1, uint32_t rate = 16000)
      : bits_(bits), channels_(channels), rate_(rate) {}
  uint8_t get_bits_per_sample() const { return bits_; }
  uint8_t get_channels() const { return channels_; }
  uint32_t get_sample_rate() const { return rate_; }
  uint32_t ms_to_frames(uint32_t ms) const { return uint64_t(ms) * rate_ / 1000; }
  size_t frames_to_bytes(size_t frames) const { return frames * channels_ * bits_ / 8; }
  uint32_t bytes_to_frames(size_t bytes) const { return bytes / frames_to_bytes(1); }
  size_t samples_to_bytes(size_t samples) const { return samples * bits_ / 8; }
  size_t ms_to_bytes(uint32_t ms) const { return frames_to_bytes(ms_to_frames(ms)); }
  int64_t frames_to_microseconds(size_t frames) const { return frames * 1000000 / rate_; }
  bool operator!=(const AudioStreamInfo &other) const {
    return bits_ != other.bits_ || channels_ != other.channels_ || rate_ != other.rate_;
  }
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
  virtual size_t play(const uint8_t *, size_t) = 0;
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
  static std::shared_ptr<RingBuffer> create(size_t capacity) {
    if (fake::ring_alloc_fail) return nullptr;
    return std::make_shared<RingBuffer>(capacity);
  }
  explicit RingBuffer(size_t capacity) : capacity_(capacity) {}
  size_t available() const { return bytes.size(); }
  size_t write_without_replacement(const void *data, size_t count, TickType_t) {
    count = std::min(count, capacity_ - bytes.size());
    const auto *begin = static_cast<const uint8_t *>(data);
    bytes.insert(bytes.end(), begin, begin + count);
    return count;
  }
  std::vector<uint8_t> bytes;
 private:
  size_t capacity_;
};
}
namespace audio {
class RingBufferAudioSource {
 public:
  static std::unique_ptr<RingBufferAudioSource> create(std::shared_ptr<ring_buffer::RingBuffer> ring,
                                                      size_t cap, uint8_t) {
    if (ring == nullptr || fake::source_alloc_fail) return nullptr;
    return std::make_unique<RingBufferAudioSource>(std::move(ring), cap);
  }
  RingBufferAudioSource(std::shared_ptr<ring_buffer::RingBuffer> ring, size_t cap)
      : ring_(std::move(ring)), cap_(cap) {}
  size_t fill(TickType_t, bool) {
    assert(++fake::fill_calls < 1000);
    if (fake::source_fill_hook) fake::source_fill_hook();
    const size_t count = std::min(ring_->available(), cap_ - exposed.size());
    exposed.insert(exposed.end(), ring_->bytes.begin(), ring_->bytes.begin() + count);
    ring_->bytes.erase(ring_->bytes.begin(), ring_->bytes.begin() + count);
    return count;
  }
  size_t available() const { return exposed.size(); }
  uint8_t *mutable_data() { return exposed.data(); }
  void consume(size_t count) { exposed.erase(exposed.begin(), exposed.begin() + count); }
 private:
  std::shared_ptr<ring_buffer::RingBuffer> ring_;
  size_t cap_;
  std::vector<uint8_t> exposed;
};
enum class AudioResamplerState { RESAMPLING, FINISHED, FAILED };
class AudioResampler {
 public:
  AudioResampler(size_t, size_t) { assert(false && "DSP not used by passthrough harness"); }
  int start(AudioStreamInfo &, AudioStreamInfo &, uint16_t, uint16_t) { return ESP_FAIL; }
  int add_source(std::weak_ptr<ring_buffer::RingBuffer> &) { return ESP_FAIL; }
  int add_sink(speaker::Speaker *) { return ESP_FAIL; }
  AudioResamplerState resample(bool, int32_t *) { return AudioResamplerState::FAILED; }
};
}
}
namespace esp_audio_libs {
namespace gain {
inline int32_t db_to_q31(float) { return INT32_MAX; }
inline void apply(uint8_t *, uint8_t *, int32_t, uint32_t, size_t) {}
}
namespace pcm_convert {
inline void copy_frames(uint8_t *, uint8_t *, uint8_t, uint8_t, uint8_t, uint8_t, uint32_t) {
  assert(false && "narrowing is outside this fault harness");
}
}
}
"""

HARNESS = r"""
#include "speaker_stubs.h"
#include "i2s_audio/speaker/i2s_audio_speaker_standard.h"
#include "resampler/speaker/resampler_speaker.h"
using namespace esphome;
using i2s_audio::I2SAudioSpeaker;
static I2SAudioSpeaker *active_output;
static uint32_t output_error_generation() { return active_output->playback_error_generation(); }

static void expect_diagnostic(const char *site, bool has_code, int code = ESP_OK) {
  const std::string site_fragment = std::string(" site=") + site + " ";
  const std::string code_fragment = has_code
      ? std::string("esp_err=") + esp_err_to_name(code) + " (" + std::to_string(code) + ")"
      : "esp_err=not_provided";
  bool found = false;
  for (const auto &line : fake::logs) {
    if (line.rfind("fault generation=", 0) == 0 && line.find(site_fragment) != std::string::npos &&
        line.find(code_fragment) != std::string::npos) found = true;
  }
  assert(found);
}

struct Fixture {
  i2s_audio::I2SAudioComponent bus;
  I2SAudioSpeaker output;
  resampler::ResamplerSpeaker resampler;
  Fixture() {
    bus.set_port(1);
    output.set_parent(&bus);
    output.set_sample_rate(48000);
    output.set_i2s_role(I2S_ROLE_SLAVE);
    output.set_dout_pin(43);
    output.set_buffer_duration(100);
    output.set_audio_stream_info(audio::AudioStreamInfo(16, 1, 48000));
    active_output = &output;
    resampler.set_output_speaker(&output);
    resampler.set_output_error_generation_callback(output_error_generation);
    resampler.set_target_sample_rate(48000);
    resampler.set_passthrough_bits_per_sample(true);
    resampler.set_audio_stream_info(audio::AudioStreamInfo(16, 1, 48000));
    resampler.set_buffer_duration(100);
    resampler.set_taps(16);
    resampler.set_filters(16);
  }
  void setup() { output.setup(); resampler.setup(); }
  void start() {
    resampler.start();
    resampler.loop();
    output.loop();
  }
  void run_worker() {
    assert(!tasks.empty());
    auto *task = tasks.back().get();
    fake::in_worker = true;
    bool terminal_delay = false;
    try { task->entry(task->arg); }
    catch (const fake::TaskDone &) { terminal_delay = true; }
    fake::in_worker = false;
    assert(terminal_delay);
    assert((event_groups.at(0)->bits & i2s_audio::TASK_STOPPED) != 0);
  }
  void collect() {
    output.loop();
    resampler.loop();
    resampler.loop();
  }
};

static void setup_failure() {
  Fixture f;
  fake::event_alloc_fail = true;
  f.output.setup();
  assert(f.output.is_failed());
  assert(f.output.playback_error_generation() == 1);
  expect_diagnostic("event_group_create", false);
  uint8_t byte = 0;
  assert(f.output.play(&byte, 1) == 0);
  assert(f.output.playback_error_generation() == 2);
  expect_diagnostic("play_after_setup_failure", false);
}

static void driver_failure(const std::string &scenario) {
  Fixture f;
  f.setup();
  if (scenario == "task") fake::task_alloc_fail = true;
  if (scenario == "parent-busy") f.bus.lock();
  if (scenario == "incompatible") {
    f.output.set_audio_stream_info(audio::AudioStreamInfo(16, 1, 16000));
    f.output.start();
    f.output.loop();
  } else f.start();
  assert(f.output.playback_error_generation() > 0);
  assert(f.resampler.completed_playback_generation() == 0);
  assert(tasks.empty());
  if (scenario == "channel-allocate") expect_diagnostic("channel_allocate", true, INJECTED);
  else if (scenario == "channel-init") expect_diagnostic("channel_init", true, INJECTED);
  else if (scenario == "queue-first" || scenario == "queue-second") expect_diagnostic("event_queue_allocate", false);
  else if (scenario == "task") expect_diagnostic("task_create", false);
  else if (scenario == "parent-busy") expect_diagnostic("parent_bus_busy", true, ESP_ERR_INVALID_STATE);
  else expect_diagnostic("incompatible_stream", true, ESP_ERR_NOT_SUPPORTED);
  if (scenario != "task") {
    const int error = scenario == "channel-allocate" || scenario == "channel-init" ? INJECTED
        : scenario == "parent-busy" ? ESP_ERR_INVALID_STATE
        : scenario == "incompatible" ? ESP_ERR_NOT_SUPPORTED : ESP_ERR_NO_MEM;
    expect_diagnostic("driver_start", true, error);
  }
  const auto generation = f.output.playback_error_generation();
  f.output.stop();
  f.output.finish();
  f.output.loop();
  assert(f.output.playback_error_generation() == generation);  // Stop/cleanup cannot erase fault history.
}

static void worker_case(const std::string &scenario) {
  Fixture f;
  f.setup();
  fake::silence_alloc_fail = scenario == "silence-allocate";
  fake::ring_alloc_fail = scenario == "ring-allocate";
  fake::source_alloc_fail = scenario == "source-allocate";
  f.start();
  bool accepted = false;
  fake::source_fill_hook = [&] {
    f.output.loop();
    f.resampler.loop();
    if (scenario == "callback") {
      // Registration already failed before RUNNING; no accepted cue may be manufactured.
      f.output.stop();
      return;
    }
    if (!accepted) {
      std::vector<uint8_t> bytes(128, 0x5a);
      assert(f.output.is_running() && f.resampler.is_running());
      assert(f.resampler.play(bytes.data(), bytes.size()) == bytes.size());
      assert(f.resampler.playback_generation() == 1);
      assert(f.resampler.completed_playback_generation() == 0);
      accepted = true;
      f.resampler.finish();
      f.resampler.loop();
    }
  };
  const uint32_t boundary = f.output.playback_error_generation();
  f.run_worker();
  const uint32_t before_cleanup = f.output.playback_error_generation();
  f.collect();
  assert(f.output.is_stopped());
  assert(f.resampler.is_stopped());
  assert(!f.output.has_buffered_data());
  if (scenario == "clean") {
    assert(accepted);
    assert(f.output.playback_error_generation() == boundary);
    assert(f.resampler.completed_playback_generation() == 1);
    return;
  }
  assert(f.output.playback_error_generation() > boundary);
  assert(f.output.playback_error_generation() >= before_cleanup);
  assert(f.resampler.completed_playback_generation() == 0);
  const auto persistent = f.output.playback_error_generation();
  f.output.loop();
  f.output.stop();
  f.output.finish();
  assert(f.output.playback_error_generation() == persistent);
  if (scenario == "silence-allocate") expect_diagnostic("silence_buffer_allocate", false);
  else if (scenario == "ring-allocate") expect_diagnostic("ring_buffer_allocate", false);
  else if (scenario == "source-allocate") expect_diagnostic("audio_source_allocate", false);
  else if (scenario == "preload-error") expect_diagnostic("dma_preload", true, INJECTED);
  else if (scenario == "preload-partial") expect_diagnostic("dma_preload_partial", true, ESP_OK);
  else if (scenario == "preload-record") expect_diagnostic("preload_record_queue_full", false);
  else if (scenario == "callback") expect_diagnostic("dma_callback_register", true, INJECTED);
  else if (scenario == "enable") expect_diagnostic("channel_enable", true, INJECTED);
  else if (scenario == "desync") expect_diagnostic("event_without_write_record", false);
  else if (scenario == "isr-overflow") expect_diagnostic("isr_event_queue_overflow", false);
  else if (scenario == "write-record") expect_diagnostic("write_record_queue_full", false);
  else {
    assert(accepted);  // DMA failures invalidate a real accepted cue, not merely an empty start.
    const bool real = scenario.rfind("real-", 0) == 0;
    const bool partial = scenario.find("partial") != std::string::npos;
    const std::string site = std::string("dma_") + (real ? "real_" : "silence_") + (partial ? "partial" : "write");
    expect_diagnostic(site.c_str(), true, partial ? ESP_OK : INJECTED);
  }
}

static void recovery_after_worker_fault() {
  Fixture f;
  f.setup();
  uint32_t persistent_errors = 0;
  for (uint32_t generation = 1; generation <= 2; ++generation) {
    fake::scenario = generation == 1 ? "real-partial" : "clean";
    fake::failed_once = false;
    fake::dma_progress = 0;
    fake::fill_calls = 0;
    bool accepted = false;
    f.start();
    fake::source_fill_hook = [&] {
      f.output.loop();
      f.resampler.loop();
      if (!accepted) {
        std::vector<uint8_t> bytes(128, 0x5a);
        assert(f.resampler.is_running());
        assert(f.resampler.play(bytes.data(), bytes.size()) == bytes.size());
        assert(f.resampler.playback_generation() == generation);
        accepted = true;
        f.resampler.finish();
        f.resampler.loop();
      }
    };
    f.run_worker();
    f.collect();
    assert(accepted && f.output.is_stopped() && f.resampler.is_stopped());
    if (generation == 1) {
      persistent_errors = f.output.playback_error_generation();
      assert(persistent_errors > 0);
      assert(f.resampler.completed_playback_generation() == 0);
      expect_diagnostic("dma_real_partial", true, ESP_OK);
    } else {
      assert(f.output.playback_error_generation() == persistent_errors);
      assert(f.resampler.completed_playback_generation() == 2);
    }
  }
}

static void playback_stats() {
  // 48 kHz output, 480-frame (10 ms) DMA buffers.
  i2s_audio::PlaybackStatsTracker probe;
  // Leading silence before any audio is not an underrun.
  probe.note_dma_buffer(0, 480, 48000);
  probe.note_dma_buffer(480, 480, 48000);
  probe.note_dma_buffer(480, 480, 48000);
  // A 30 ms gap (half-buffer tail + 2 empty buffers + half-buffer head is
  // 240 + 960 frames = 25 ms), then audio resumes: one underrun.
  probe.note_dma_buffer(240, 480, 48000);
  probe.note_dma_buffer(0, 480, 48000);
  probe.note_dma_buffer(0, 480, 48000);
  probe.note_dma_buffer(480, 480, 48000);
  // A shorter 10 ms gap: second underrun, longest unchanged.
  probe.note_dma_buffer(0, 480, 48000);
  probe.note_dma_buffer(480, 480, 48000);
  // Trailing silence after the last real audio is not an underrun.
  probe.note_dma_buffer(0, 480, 48000);
  probe.note_dma_buffer(0, 480, 48000);
  auto stats = probe.stats();
  assert(stats.underruns == 2);
  assert(stats.longest_underrun_ms == 25);
  assert(stats.played_ms == (480 * 4 + 240) * 1000 / 48000);
  probe.request_reset();
  probe.note_dma_buffer(0, 480, 48000);
  stats = probe.stats();
  assert(stats.underruns == 0 && stats.longest_underrun_ms == 0 && stats.played_ms == 0);
  probe.note_dma_buffer(480, 480, 48000);  // reset also forgets the old gap
  assert(probe.stats().underruns == 0);
}

int main(int argc, char **argv) {
  assert(argc == 2);
  const std::string scenario = argv[1];
  fake::scenario = scenario;
  if (scenario == "playback-stats") { playback_stats(); return 0; }
  if (scenario == "setup") setup_failure();
  else if (scenario == "recovery") recovery_after_worker_fault();
  else if (scenario == "channel-allocate" || scenario == "channel-init" || scenario == "queue-first" ||
           scenario == "queue-second" || scenario == "task" || scenario == "parent-busy" || scenario == "incompatible") {
    driver_failure(scenario);
  } else worker_case(scenario);
}
"""


@pytest.fixture(scope="module")
def speaker_binary(tmp_path_factory):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("native C++ compiler unavailable")
    directory = tmp_path_factory.mktemp("speaker_native")
    (directory / "speaker_stubs.h").write_text(STUBS)
    for relative in (
        "esphome/core/component.h", "esphome/core/defines.h", "esphome/core/helpers.h",
        "esphome/core/gpio.h", "esphome/core/application.h", "esphome/core/hal.h",
        "esphome/core/log.h", "esphome/core/static_task.h", "esp_idf_version.h",
        "esphome/components/audio/audio.h", "esphome/components/audio/audio_transfer_buffer.h",
        "esphome/components/audio/audio_resampler.h", "esphome/components/ring_buffer/ring_buffer.h",
        "esphome/components/speaker/speaker.h", "driver/i2s_std.h", "driver/gpio.h",
        "freertos/event_groups.h", "freertos/queue.h", "freertos/FreeRTOS.h",
        "hal/dma_types.h", "esp_timer.h", "gain.h", "pcm_convert.h",
    ):
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('#include "speaker_stubs.h"\n')
    harness = directory / "speaker_native.cpp"
    harness.write_text(HARNESS)
    binary = directory / "speaker_native"
    result = subprocess.run(
        [compiler, "-std=c++17", "-DUSE_ESP32", "-Wall", "-Wextra",
         "-Wno-unused-variable", "-Wno-unused-const-variable", "-Wno-unused-parameter",
         "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
         "-I", str(directory), "-I", str(COMPONENTS), str(harness),
         str(COMPONENTS / "i2s_audio/speaker/i2s_audio_speaker.cpp"),
         str(COMPONENTS / "i2s_audio/speaker/i2s_audio_speaker_standard.cpp"),
         str(COMPONENTS / "resampler/speaker/resampler_speaker.cpp"),
         "-o", str(binary)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize("scenario", [
    "clean", "setup", "channel-allocate", "channel-init", "queue-first", "queue-second",
    "task", "parent-busy", "incompatible", "silence-allocate", "ring-allocate", "source-allocate",
    "preload-error", "preload-partial", "preload-record", "callback", "enable", "desync",
    "isr-overflow", "write-record", "real-error", "real-partial", "silence-error", "silence-partial",
    "recovery",
])
def test_actual_speaker_fault_receipt_and_diagnostic(speaker_binary, scenario):
    result = subprocess.run(
        [str(speaker_binary), scenario], capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"{scenario}:\n{result.stdout}{result.stderr}"


def test_speaker_counts_audible_underruns_but_not_leading_or_trailing_silence(speaker_binary):
    result = subprocess.run(
        [str(speaker_binary), "playback-stats"], capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
