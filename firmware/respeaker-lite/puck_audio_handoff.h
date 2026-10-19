#pragma once

#include "esphome/core/hal.h"
#include <cstdint>

// P-2/P-3 control only: the resampler owns audio and its successful-drain
// receipt. Player IDLE alone is never evidence that physical TX has finished.
namespace puck_audio_handoff {

static constexpr uint32_t HANDOFF_TIMEOUT_MS = 5000;
static constexpr uint32_t FOLLOW_UP_SETTLE_MS = 200;
static constexpr uint32_t CUE_MINIMUM_MS = 150;

enum class Result : uint8_t { WAITING, READY, FAILED };

struct Output {
  bool media_idle;
  bool resampler_stopped;
  bool speaker_stopped;
  bool buffered;
  bool detector_stopped;
  uint32_t playback_generation;
  uint32_t completed_generation;
  bool source_failed{false};
  uint32_t error_generation{0};
  bool source_idle{false};
};


using OutputReader = Output (*)();
inline OutputReader output_reader = nullptr;
inline void set_output_reader(OutputReader reader) { output_reader = reader; }
inline Output current_output() { return output_reader ? output_reader() : Output{}; }
inline bool drained(const Output &output) {
  return output.media_idle && output.source_idle && output.resampler_stopped &&
         output.speaker_stopped && !output.buffered;
}

class Barrier {
 public:
  void begin(uint32_t baseline_generation, uint32_t settle_ms = 0,
             uint32_t minimum_ms = 0) {
    this->baseline_generation_ = baseline_generation;
    this->started_ms_ = millis();
    this->settle_ms_ = settle_ms;
    this->minimum_ms_ = minimum_ms;
    this->settling_ = false;
    this->active_ = true;
  }

  bool active() const { return this->active_; }
  void cancel() { this->active_ = false; }

  Result poll(const Output &output) {
    if (!this->active_) return Result::WAITING;
    const uint32_t now = millis();
    const uint32_t expected = this->baseline_generation_ + 1;
    // One owned announcement pipeline: an unexpected extra playback is not
    // the acknowledgement/response we requested. Never accept its authority.
    if (now - this->started_ms_ >= HANDOFF_TIMEOUT_MS ||
        (output.playback_generation != this->baseline_generation_ &&
         output.playback_generation != expected)) {
      this->active_ = false;
      return Result::FAILED;
    }
    if (!drained(output) || !output.detector_stopped ||
        output.playback_generation != expected ||
        output.completed_generation != expected) {
      this->settling_ = false;
      return Result::WAITING;
    }
    if (!this->settling_) {
      this->settle_started_ms_ = now;
      this->settling_ = true;
    }
    if (now - this->started_ms_ < this->minimum_ms_ ||
        now - this->settle_started_ms_ < this->settle_ms_) {
      return Result::WAITING;
    }
    this->active_ = false;
    return Result::READY;
  }

 private:
  uint32_t baseline_generation_{0};
  uint32_t started_ms_{0};
  uint32_t settle_started_ms_{0};
  uint32_t settle_ms_{0};
  uint32_t minimum_ms_{0};
  bool active_{false};
  bool settling_{false};
};

inline Barrier wake_cue;
inline Barrier follow_up;
inline uint32_t response_baseline_generation = 0;
inline bool response_audio_requested = false;
inline uint32_t response_error_baseline = 0;

inline bool response_failed(const Output &output) {
  return response_audio_requested &&
         (output.source_failed || output.error_generation != response_error_baseline);
}

inline void response_requested(uint32_t generation) {
  response_baseline_generation = generation;
  response_error_baseline = current_output().error_generation;
  response_audio_requested = true;
  follow_up.cancel();
}

inline Result poll_follow_up(const Output &output) {
  if (!response_audio_requested) return Result::FAILED;
  if (response_failed(output)) {
    follow_up.cancel();
    response_audio_requested = false;
    return Result::FAILED;
  }
  if (!follow_up.active()) {
    follow_up.begin(response_baseline_generation, FOLLOW_UP_SETTLE_MS);
  }
  const Result result = follow_up.poll(output);
  if (result != Result::WAITING) response_audio_requested = false;
  return result;
}

}  // namespace puck_audio_handoff
