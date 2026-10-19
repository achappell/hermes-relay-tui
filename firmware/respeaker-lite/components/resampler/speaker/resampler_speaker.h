// ESPHome 2026.9.1, Copyright (c) 2019 ESPHome; C++ runtime licensed GPLv3 (../LICENSE).
// Canonical source: esphome-2026.9.1-py3-none-any.whl from https://pypi.org/project/esphome/2026.9.1/
// Upstream commit: 0b2b16e664ecfc0add37f3435db1c2140b8a687e
// Wheel SHA256: 54b1b401b62206937dce8e56c91bf6a382bc2ee1501727494a3814c7f236c414
// Unmodified package member SHA256 (paths relative to esphome/components/resampler/):
// __init__.py: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
// speaker/__init__.py: b01adab8b4f2e39915a366c5335734627f3d5f58da08dcee71d5c66c20b995c1
// speaker/resampler_speaker.h: 25c93cca60716b0cde99ae31a18b5563af1b22e220cad443f9675a1acb825ad2
// speaker/resampler_speaker.cpp: e295ca7f19b499b5319769bc4f5c0b551876ff38f3fdf29f8f3441e3aade7b2f
// Modified 2026-10-19: drain upstream before TX finish; retain successful accepted-playback receipts.
// Python files are unchanged and MIT licensed; the complete package license is retained in ../LICENSE.
#pragma once

#ifdef USE_ESP32

#include "esphome/components/audio/audio.h"
#include "esphome/components/audio/audio_transfer_buffer.h"
#include "esphome/components/ring_buffer/ring_buffer.h"
#include "esphome/components/speaker/speaker.h"

#include "esphome/core/component.h"
#include "esphome/core/static_task.h"

#include <freertos/event_groups.h>
#include <atomic>

namespace esphome::resampler {

class ResamplerSpeaker final : public Component, public speaker::Speaker {
 public:
  float get_setup_priority() const override { return esphome::setup_priority::DATA; }
  void dump_config() override;
  void setup() override;
  void loop() override;

  size_t play(const uint8_t *data, size_t length, TickType_t ticks_to_wait) override;
  size_t play(const uint8_t *data, size_t length) override { return this->play(data, length, 0); }

  void start() override;
  void stop() override;
  void finish() override;

  /// Advances on the first accepted audio byte of a run, not merely on start().
  uint32_t playback_generation() const { return this->playback_generation_.load(); }
  /// Advances only after graceful upstream drain and an error-free, empty downstream stop.
  uint32_t completed_playback_generation() const { return this->completed_playback_generation_.load(); }
  void set_output_error_generation_callback(uint32_t (*callback)()) {
    this->output_error_generation_callback_ = callback;
  }

  void set_pause_state(bool pause_state) override { this->output_speaker_->set_pause_state(pause_state); }
  bool get_pause_state() const override { return this->output_speaker_->get_pause_state(); }

  bool has_buffered_data() const override;

  /// @brief Mute state changes are passed to the parent's output speaker
  void set_mute_state(bool mute_state) override;
  bool get_mute_state() override { return this->output_speaker_->get_mute_state(); }

  /// @brief Volume state changes are passed to the parent's output speaker
  void set_volume(float volume) override;
  float get_volume() override { return this->output_speaker_->get_volume(); }

  void set_output_speaker(speaker::Speaker *speaker) { this->output_speaker_ = speaker; }
  void set_task_stack_in_psram(bool task_stack_in_psram) { this->task_stack_in_psram_ = task_stack_in_psram; }

  void set_target_bits_per_sample(uint8_t target_bits_per_sample) {
    this->target_bits_per_sample_ = target_bits_per_sample;
  }
  void set_target_sample_rate(uint32_t target_sample_rate) { this->target_sample_rate_ = target_sample_rate; }

  /// @brief When enabled, the input bits per sample are passed through to the output speaker unchanged instead of being
  /// converted to a fixed target. Only the sample rate is resampled if it differs from the target.
  void set_passthrough_bits_per_sample(bool passthrough_bits_per_sample) {
    this->passthrough_bits_per_sample_ = passthrough_bits_per_sample;
  }

  void set_filters(uint16_t filters) { this->filters_ = filters; }
  void set_taps(uint16_t taps) { this->taps_ = taps; }

  void set_buffer_duration(uint32_t buffer_duration_ms) { this->buffer_duration_ms_ = buffer_duration_ms; }

 protected:
  /// @brief Starts the output speaker after setting the resampled stream info. If resampling is required, it starts the
  /// task.
  /// @return ESP_OK if successful,
  ///         ESP_ERR_NO_MEM if the resampler task couldn't be created
  esp_err_t start_();

  /// @brief Transitions to STATE_STOPPING, records the stopping timestamp, sends the task stop command if the task is
  /// running, and stops the output speaker.
  void enter_stopping_state_();

  /// @brief Sets the appropriate status error based on the start failure reason.
  void set_start_error_(esp_err_t err);

  /// @brief Sends a command via event group bits, enables the loop, and optionally wakes the main loop.
  void send_command_(uint32_t command_bit, bool wake_loop = false);

  inline bool requires_resampling_() const;
  static void resample_task(void *params);

  EventGroupHandle_t event_group_{nullptr};

  std::weak_ptr<ring_buffer::RingBuffer> ring_buffer_;

  speaker::Speaker *output_speaker_{nullptr};

  StaticTask task_;

  audio::AudioStreamInfo target_stream_info_;

  uint64_t callback_remainder_{0};

  std::atomic<uint32_t> playback_generation_{0};
  std::atomic<uint32_t> completed_playback_generation_{0};
  std::atomic<bool> playback_accepted_{false};
  uint32_t (*output_error_generation_callback_)(){nullptr};
  uint32_t output_error_generation_start_{0};

  uint32_t buffer_duration_ms_;
  uint32_t state_start_ms_{0};
  uint32_t target_sample_rate_;

  uint16_t taps_;
  uint16_t filters_;

  uint8_t target_bits_per_sample_{0};

  bool passthrough_bits_per_sample_{false};
  bool task_stack_in_psram_{false};
  bool waiting_for_output_{false};
  bool graceful_finish_{false};
  bool upstream_drained_{false};
};

}  // namespace esphome::resampler

#endif
