#pragma once

#include <algorithm>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <sys/types.h>

using esp_err_t = int;
constexpr int ESP_OK = 0, ESP_ERR_TIMEOUT = 1, ESP_FAIL = 2;
inline const char *esp_err_to_name(int error) { return error == ESP_OK ? "ESP_OK" : "injected_error"; }
using gpio_num_t = int;
constexpr int I2S_GPIO_UNUSED = -1;
using i2s_port_t = int;
using i2s_role_t = int;
using i2s_slot_mode_t = int;
using i2s_std_slot_mask_t = int;
using i2s_slot_bit_width_t = int;
using i2s_mclk_multiple_t = int;
using i2s_clock_src_t = int;
using i2s_data_bit_width_t = int;
constexpr int I2S_SLOT_BIT_WIDTH_AUTO = 0, I2S_SLOT_BIT_WIDTH_16BIT = 16;
constexpr int I2S_SLOT_MODE_MONO = 1, I2S_SLOT_MODE_STEREO = 2;
constexpr int I2S_STD_SLOT_LEFT = 1, I2S_STD_SLOT_RIGHT = 2, I2S_STD_SLOT_BOTH = 3;
constexpr int I2S_CLK_SRC_DEFAULT = 0, I2S_MCLK_MULTIPLE_256 = 256;
struct FakeChannel { int identity; bool enabled = false; bool deleted = false; };
using i2s_chan_handle_t = FakeChannel *;
struct i2s_chan_config_t {
  int id, role, dma_desc_num, dma_frame_num;
  bool auto_clear;
};
struct i2s_std_gpio_config_t {
  int mclk, bclk, ws, dout, din;
  struct { bool mclk_inv, bclk_inv, ws_inv; } invert_flags;
};
struct i2s_std_clk_config_t { uint32_t sample_rate_hz; int clk_src, mclk_multiple; };
struct i2s_std_slot_config_t { int data_bit_width, slot_mode, slot_bit_width, slot_mask; };
struct i2s_std_config_t {
  i2s_std_clk_config_t clk_cfg;
  i2s_std_slot_config_t slot_cfg;
  i2s_std_gpio_config_t gpio_cfg;
};
#define I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(bits, mode) i2s_std_slot_config_t{bits, mode, bits, I2S_STD_SLOT_BOTH}
#define ESP_IDF_VERSION_VAL(a, b, c) ((a) * 10000 + (b) * 100 + (c))
#define ESP_IDF_VERSION ESP_IDF_VERSION_VAL(5, 5, 5)

struct DriverTrace {
  std::vector<std::string> calls, logs;
  int allocation_error = 0, init_error = 0, enable_error = 0, disable_error = 0, delete_error = 0;
  bool busy = false, allocation_returns_handle = false;
  int locks = 0, unlocks = 0, next_channel = 0;
  FakeChannel channels[64]{};
  void reset_trace() { calls.clear(); logs.clear(); locks = unlocks = 0; }
};
inline DriverTrace driver;
inline esp_err_t i2s_new_channel(const i2s_chan_config_t *, void *, i2s_chan_handle_t *handle) {
  driver.calls.push_back("allocate");
  if (driver.allocation_error == 0 || driver.allocation_returns_handle) {
    auto &channel = driver.channels[driver.next_channel++];
    channel.identity = driver.next_channel;
    *handle = &channel;
  }
  return driver.allocation_error;
}
inline esp_err_t i2s_channel_init_std_mode(i2s_chan_handle_t handle, const i2s_std_config_t *) {
  if (!handle) std::abort();
  driver.calls.push_back("initialize");
  return driver.init_error;
}
inline esp_err_t i2s_channel_enable(i2s_chan_handle_t handle) {
  if (!handle) std::abort();
  driver.calls.push_back("enable");
  if (driver.enable_error == 0) handle->enabled = true;
  return driver.enable_error;
}
inline esp_err_t i2s_channel_disable(i2s_chan_handle_t handle) {
  if (!handle || !handle->enabled) std::abort();
  driver.calls.push_back("disable");
  if (driver.disable_error == 0) handle->enabled = false;
  return driver.disable_error;
}
inline esp_err_t i2s_del_channel(i2s_chan_handle_t handle) {
  if (!handle) std::abort();
  driver.calls.push_back("delete");
  if (driver.delete_error == 0) handle->deleted = true;
  return driver.delete_error;
}
inline esp_err_t i2s_channel_read(i2s_chan_handle_t, uint8_t *, size_t, size_t *read, uint32_t) {
  *read = 0;
  return ESP_OK;
}
template<typename... Args> inline void capture_log(const char *, const char *format, Args... args) {
  char text[256];
  if constexpr (sizeof...(Args) == 0)
    std::snprintf(text, sizeof(text), "%s", format);
  else
    std::snprintf(text, sizeof(text), format, args...);
  driver.logs.emplace_back(text);
}
#define ESP_LOGE(...) capture_log(__VA_ARGS__)
#define ESP_LOGW(...) capture_log(__VA_ARGS__)
#define ESP_LOGV(...) do {} while (0)
#define ESP_LOGCONFIG(...) do {} while (0)
#define YESNO(value) ((value) ? "YES" : "NO")
using UBaseType_t = unsigned;
using SemaphoreHandle_t = void *;
using EventGroupHandle_t = void *;
using TaskHandle_t = void *;
inline void *xSemaphoreCreateCounting(unsigned, unsigned) { return reinterpret_cast<void *>(1); }
inline void *xEventGroupCreate() { return reinterpret_cast<void *>(1); }
inline void xSemaphoreTake(void *, int) {}
inline void xSemaphoreGive(void *) {}
inline unsigned uxSemaphoreGetCount(void *) { return 16; }
inline uint32_t xEventGroupGetBits(void *) { return 0; }
inline void xEventGroupSetBits(void *, uint32_t) {}
inline void xEventGroupClearBits(void *, uint32_t) {}
inline void vTaskDelete(void *) {}
inline void vTaskDelay(int) {}
inline void xTaskCreate(void (*)(void *), const char *, size_t, void *, int, void **handle) { *handle = reinterpret_cast<void *>(1); }
#define pdMS_TO_TICKS(ms) (ms)

namespace esphome {
class Component {
 public:
  virtual ~Component() = default;
  virtual void setup() {}
  virtual void loop() {}
  virtual void dump_config() {}
  bool is_failed() const { return false; }
  void mark_failed() {}
  bool status_has_warning() const { return false; }
  bool status_has_error() const { return false; }
  void status_set_warning() {}
  void status_clear_warning() {}
  void status_clear_error() {}
  void status_momentary_error(const char *, int) {}
};
template<class Parent> class Parented {
 public: void set_parent(Parent *parent) { parent_ = parent; }
 protected: Parent *parent_{nullptr};
};
class Mutex {
 public:
  void lock() { if (!try_lock()) std::abort(); }
  bool try_lock() {
    driver.calls.push_back("lock");
    if (driver.busy || this->held_) return false;
    ++driver.locks;
    this->held_ = true;
    return true;
  }
  void unlock() {
    if (!this->held_) std::abort();
    this->held_ = false;
    driver.calls.push_back("unlock");
    ++driver.unlocks;
  }
 private:
  bool held_{false};
};
namespace audio {
class AudioStreamInfo {
 public:
  AudioStreamInfo(int = 32, int = 2, int = 16000) {}
  size_t ms_to_bytes(int ms) const { return size_t(ms) * 128; }
  size_t samples_to_bytes(int samples) const { return size_t(samples) * 4; }
  uint32_t bytes_to_samples(size_t bytes) const { return bytes / 4; }
};
inline int32_t unpack_audio_sample_to_q31(uint8_t *, size_t) { return 0; }
inline void pack_q31_as_audio_sample(int32_t, uint8_t *, size_t) {}
}
namespace microphone {
enum State { STATE_STOPPED, STATE_STARTING, STATE_RUNNING, STATE_STOPPING };
class Microphone {
 public:
  virtual ~Microphone() = default;
  virtual void start() {}
  virtual void stop() {}
 public:
  State state_{STATE_STOPPED};
  audio::AudioStreamInfo audio_stream_info_;
  struct Callbacks {
    size_t size() const { return 0; }
    void call(const std::vector<uint8_t> &) {}
  } data_callbacks_;
};
}
}
