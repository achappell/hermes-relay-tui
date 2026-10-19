#pragma once

#include <cstdint>
#include <string>

namespace esphome::micro_wake_word {

struct DetectionEvent {
  std::string *wake_word{nullptr};
  bool detected{false};
  bool partially_detection{false};
  uint8_t max_probability{0};
  uint8_t average_probability{0};
  bool blocked_by_vad{false};
  // An event without explicit model provenance never becomes a public wake.
  bool internal_only{true};
};

// Capture role at the producer, before this trivially copied event crosses the
// inference-task queue. The same handoff executes in the native regression.
template<typename Model> DetectionEvent make_model_detection(Model &model) {
  DetectionEvent event = model.determine_detected();
  event.internal_only = model.get_internal_only();
  return event;
}

inline bool is_public_wake_model(bool internal_only) { return !internal_only; }

enum class DetectionRoute : uint8_t { INTERNAL_CONTROL, VAD_BLOCKED, IGNORED, PUBLIC_WAKE };

inline DetectionRoute detection_route(const DetectionEvent &event) {
  if (!is_public_wake_model(event.internal_only))
    return DetectionRoute::INTERNAL_CONTROL;
  if (!event.detected || event.wake_word == nullptr)
    return DetectionRoute::IGNORED;
  if (event.blocked_by_vad)
    return DetectionRoute::VAD_BLOCKED;
  return DetectionRoute::PUBLIC_WAKE;
}

// The same fail-closed boundary is used by the real engine trigger and native
// capture/upload regression. No model-name allowlist, lookup or allocation.
template<typename Trigger> bool dispatch_public_detection(const DetectionEvent &event, Trigger &trigger) {
  if (detection_route(event) != DetectionRoute::PUBLIC_WAKE)
    return false;
  trigger.trigger(*event.wake_word);
  return true;
}

}  // namespace esphome::micro_wake_word
