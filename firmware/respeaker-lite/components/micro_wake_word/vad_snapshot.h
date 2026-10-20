#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace esphome::micro_wake_word {

// Worker-owned accounting shared with the native regression harness. A feature
// step is not an inference: only an actual Invoke advances generation.
class StreamingInferenceProgress {
 public:
  size_t next_feature_slot(size_t stride) {
    const size_t slot = this->stride_step_ % stride;
    this->stride_step_ = slot + 1;
    return slot;
  }
  bool ready(size_t stride) const { return this->stride_step_ >= stride; }
  void invoked(bool successful, size_t window_size) {
    ++this->generation_;
    if (!successful) {
      this->fresh_results_ = 0;
    } else if (this->fresh_results_ < window_size) {
      ++this->fresh_results_;
    }
  }
  void reset() {
    this->stride_step_ = 0;
    this->fresh_results_ = 0;
  }
  uint32_t generation() const { return this->generation_; }
  bool full_window(size_t window_size) const { return window_size > 0 && this->fresh_results_ >= window_size; }

 protected:
  size_t stride_step_{0};
  size_t fresh_results_{0};
  uint32_t generation_{0};
};

struct VADWindowResult {
  bool detected;
  uint8_t average_probability;
  uint8_t maximum_probability;
};

// The model's existing quantized rolling-window decision, shared by production
// and native tests. Preserve strict cutoff comparison and integer averaging.
inline VADWindowResult summarize_vad_window(const uint8_t *probabilities, size_t window_size, uint8_t cutoff) {
  uint32_t sum = 0;
  uint8_t maximum = 0;
  for (size_t i = 0; i < window_size; ++i) {
    sum += probabilities[i];
    if (probabilities[i] > maximum)
      maximum = probabilities[i];
  }
  return {sum > cutoff * window_size, static_cast<uint8_t>(sum / window_size), maximum};
}

struct VADSnapshot {
  bool valid{false};
  bool detected{false};
  uint32_t generation{0};
  uint32_t timestamp_ms{0};
  float average_probability{0.0f};
  float maximum_probability{0.0f};
};

struct VADCaptureDiagnostics {
  uint32_t fresh_generations{0};
  double probability_sum{0.0};
  float maximum_probability{0.0f};
  uint64_t selected_samples{0};
  uint64_t selected_rail_samples{0};
};

// Mutex supplies lock()/unlock(). Firmware uses a short ESP32 portMUX critical
// section; native tests use std::mutex to exercise the same publication boundary.
// Neither inference nor PCM scanning/logging runs inside that boundary.
template<typename Mutex> class VADSnapshotStore {
 public:
  uint32_t start() {
    Guard guard(this->mutex_);
    ++this->epoch_;
    this->running_ = true;
    this->snapshot_.valid = false;
    this->snapshot_.detected = false;
    return this->epoch_;
  }
  void invalidate() {
    Guard guard(this->mutex_);
    ++this->epoch_;
    this->running_ = false;
    this->snapshot_.valid = false;
    this->snapshot_.detected = false;
  }
  uint32_t epoch() const {
    Guard guard(this->mutex_);
    return this->epoch_;
  }
  void publish(uint32_t epoch, uint32_t generation, uint32_t now, bool full_window, bool detected,
               uint8_t average, uint8_t maximum, uint32_t cadence_ms) {
    Guard guard(this->mutex_);
    // stop() is synchronous at this boundary, even if Invoke was already in
    // flight. Repeated feature steps cannot refresh an old result's timestamp.
    if (!this->running_ || epoch != this->epoch_ || generation == this->snapshot_.generation)
      return;
    this->snapshot_ = {full_window, full_window && detected, generation, now, average / 255.0f, maximum / 255.0f};
    // Three expected Invoke periods tolerate scheduling jitter but not stopped
    // or stalled inference. Cadence = tensor stride * configured feature step.
    this->maximum_age_ms_ = cadence_ms * 3;
    if (full_window && this->diagnostics_active_) {
      ++this->diagnostics_.fresh_generations;
      this->diagnostics_.probability_sum += this->snapshot_.average_probability;
      if (this->snapshot_.maximum_probability > this->diagnostics_.maximum_probability)
        this->diagnostics_.maximum_probability = this->snapshot_.maximum_probability;
    }
  }
  VADSnapshot snapshot(uint32_t now) const {
    Guard guard(this->mutex_);
    auto result = this->snapshot_;
    result.valid = result.valid && this->running_ && uint32_t(now - result.timestamp_ms) <= this->maximum_age_ms_;
    if (!result.valid)
      result.detected = false;
    return result;
  }
  void begin_capture() {
    Guard guard(this->mutex_);
    if (this->diagnostics_active_)
      return;
    ++this->capture_epoch_;
    this->diagnostics_ = {};
    this->diagnostics_active_ = true;
  }
  bool finish_capture(VADCaptureDiagnostics &result) {
    Guard guard(this->mutex_);
    if (!this->diagnostics_active_)
      return false;
    this->diagnostics_active_ = false;
    result = this->diagnostics_;
    return true;
  }
  void record_selected_pcm(const uint8_t *data, size_t length) {
    uint32_t capture_epoch;
    {
      Guard guard(this->mutex_);
      if (!this->diagnostics_active_)
        return;
      capture_epoch = this->capture_epoch_;
    }
    // This callback is MicrophoneSource's selected, post-gain S16 mono
    // stream, NOT the raw interleaved physical microphone callback. memcpy
    // permits byte-aligned callback storage without undefined int16_t loads.
    uint64_t rails = 0;
    const size_t samples = length / sizeof(int16_t);
    for (size_t i = 0; i < samples; ++i) {
      int16_t sample;
      std::memcpy(&sample, data + i * sizeof(sample), sizeof(sample));
      rails += sample == INT16_MIN || sample == INT16_MAX;
    }
    Guard guard(this->mutex_);
    // A callback that straddles finish/begin cannot contaminate the next
    // capture. No raw values are retained, allocated, or logged.
    if (this->diagnostics_active_ && capture_epoch == this->capture_epoch_) {
      this->diagnostics_.selected_samples += samples;
      this->diagnostics_.selected_rail_samples += rails;
    }
  }

 protected:
  struct Guard {
    explicit Guard(Mutex &mutex) : mutex(mutex) { this->mutex.lock(); }
    ~Guard() { this->mutex.unlock(); }
    Mutex &mutex;
  };
  mutable Mutex mutex_;
  uint32_t epoch_{0};
  uint32_t capture_epoch_{0};
  uint32_t maximum_age_ms_{0};
  bool running_{false};
  bool diagnostics_active_{false};
  VADSnapshot snapshot_;
  VADCaptureDiagnostics diagnostics_;
};

}  // namespace esphome::micro_wake_word
