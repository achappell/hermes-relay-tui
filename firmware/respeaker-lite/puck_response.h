// P-5 response hand-off state for the reSpeaker Lite.
//
// The audio_http/media_player components own the response bytes and their
// playback task. This header owns only the small control contract around
// that playback: do not restart wake detection until the bridge has confirmed
// the exact response sequence, and turn a failed confirmation into one local
// refusal before returning to a reusable wake state.
//
// It deliberately does not touch pcm_capture.h. Capture/upload sequencing and
// the wake acknowledgement are separate, already-proven contracts.
#pragma once

#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "puck_identity.h"

#include <cstdint>
#include <string>

namespace puck_response {

static const char *const TAG = "puck_response";
static const char *const BUILD_IDENTITY = "respeaker-lite-p5";

static constexpr uint32_t STATUS_RETRY_INTERVAL_MS = 250;
static constexpr uint32_t STATUS_RETRY_WINDOW_MS = 2000;
static constexpr uint32_t REFUSAL_WATCHDOG_MS = 2000;

enum class State : uint8_t {
  IDLE,
  WAITING_FOR_MEDIA_IDLE,
  POLLING,
  FOLLOW_UP_PENDING,
  FOLLOW_UP_CAPTURING,
  REFUSAL_PENDING,
  REFUSAL_PLAYING,
  READY_TO_RESUME,
};

static State state = State::IDLE;
static uint32_t response_seq = 0;
static uint32_t retry_started_ms = 0;
static uint32_t next_poll_ms = 0;
static uint32_t refusal_started_ms = 0;
static bool home_admission_needed = false;
static bool home_admission_pending = false;
static bool home_admission_granted_flag = false;
static uint32_t home_admission_seq = 0;
static bool follow_up_admission_pending = false;
static bool follow_up_admission_granted_flag = false;
static uint32_t follow_up_admission_seq = 0;

inline const char *state_name(State value) {
  switch (value) {
    case State::IDLE:
      return "IDLE";
    case State::WAITING_FOR_MEDIA_IDLE:
      return "WAITING_FOR_MEDIA_IDLE";
    case State::POLLING:
      return "POLLING";
    case State::FOLLOW_UP_PENDING:
      return "FOLLOW_UP_PENDING";
    case State::FOLLOW_UP_CAPTURING:
      return "FOLLOW_UP_CAPTURING";
    case State::REFUSAL_PENDING:
      return "REFUSAL_PENDING";
    case State::REFUSAL_PLAYING:
      return "REFUSAL_PLAYING";
    case State::READY_TO_RESUME:
      return "READY_TO_RESUME";
  }
  return "UNKNOWN";
}

inline std::string terminal_body(uint32_t seq, const char *status) {
  return std::string("{\"seq\": ") + std::to_string(seq) +
         ", \"status\": \"" + status + "\"}";
}

inline std::string home_admission_terminal_body(uint32_t seq) {
  return std::string("{\"seq\": ") + std::to_string(seq) +
         ", \"status\": \"unavailable\", \"needs_home_admission\": true}";
}

inline std::string url_encode(const std::string &value) {
  static const char hex[] = "0123456789ABCDEF";
  std::string encoded;
  encoded.reserve(value.size());
  for (unsigned char c : value) {
    const bool safe = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                      (c >= '0' && c <= '9') || c == '-' || c == '_' ||
                      c == '.' || c == '~';
    if (safe) {
      encoded += static_cast<char>(c);
    } else {
      encoded += '%';
      encoded += hex[c >> 4];
      encoded += hex[c & 0x0F];
    }
  }
  return encoded;
}

inline void begin(uint32_t seq) {
  response_seq = seq;
  retry_started_ms = 0;
  next_poll_ms = 0;
  refusal_started_ms = 0;
  home_admission_pending = false;
  home_admission_granted_flag = false;
  follow_up_admission_pending = false;
  follow_up_admission_granted_flag = false;
  state = State::WAITING_FOR_MEDIA_IDLE;
  ESP_LOGI(TAG, "response admitted seq=%u build=%s; waiting for media idle",
           (unsigned) response_seq, BUILD_IDENTITY);
}

inline uint32_t sequence() { return response_seq; }

inline bool needs_home_admission() { return home_admission_needed; }

inline bool home_admission_in_flight() { return home_admission_pending; }

inline bool can_start_wake_capture() {
  return home_admission_granted_flag && !home_admission_pending;
}

inline bool can_start_follow_up_capture() {
  return state == State::FOLLOW_UP_PENDING &&
         follow_up_admission_granted_flag &&
         !follow_up_admission_pending;
}

inline bool follow_up_admission_in_flight() {
  return follow_up_admission_pending;
}

inline bool home_admission_granted() { return home_admission_granted_flag; }

inline bool consume_home_admission() {
  if (!can_start_wake_capture()) {
    return false;
  }
  home_admission_granted_flag = false;
  return true;
}

inline bool begin_home_admission(uint32_t seq) {
  if (home_admission_pending || home_admission_granted_flag ||
      state != State::IDLE) {
    return false;
  }
  home_admission_pending = true;
  home_admission_granted_flag = false;
  home_admission_seq = seq;
  return true;
}

inline bool begin_follow_up_admission(uint32_t seq) {
  if (follow_up_admission_pending || follow_up_admission_granted_flag ||
      state != State::FOLLOW_UP_PENDING || seq != response_seq) {
    return false;
  }
  follow_up_admission_pending = true;
  follow_up_admission_seq = seq;
  return true;
}

template <typename AdmitFn, typename DenyFn>
inline void dispatch_wake_capture(bool admitted, AdmitFn admit,
                                 DenyFn deny) {
  if (admitted) {
    admit();
  } else {
    deny();
  }
}

inline void refuse_home_admission(const char *reason) {
  home_admission_pending = false;
  home_admission_granted_flag = false;
  response_seq = home_admission_seq;
  state = State::REFUSAL_PENDING;
  ESP_LOGW(TAG, "Home wake admission refused for seq=%u (%s); capture stays closed",
           (unsigned) response_seq, reason);
}

inline void note_home_admission(int status, const std::string &body) {
  if (!home_admission_pending) {
    return;
  }
  if (status == 200 &&
      body == std::string("admitted:") + std::to_string(home_admission_seq)) {
    home_admission_pending = false;
    home_admission_granted_flag = true;
    home_admission_needed = false;
    ESP_LOGI(TAG, "Home wake admission granted for seq=%u; capture may open",
             (unsigned) home_admission_seq);
    return;
  }
  if (body == std::string("identity_rejected:") +
                  std::to_string(home_admission_seq)) {
    puck_identity::reject_authority("Home");
    refuse_home_admission("Home identity rejected");
    return;
  }
  if (status == 401) {
    puck_identity::note_upload_status(status);
    refuse_home_admission("local bridge identity rejected");
    return;
  }
  refuse_home_admission(status <= 0 ? "admission service unreachable"
                                    : "Home claim denied or unavailable");
}

inline void note_home_admission_transport_failure() {
  note_home_admission(0, "");
}

inline void initial_upload_failed(uint32_t seq) {
  response_seq = seq;
  retry_started_ms = 0;
  next_poll_ms = 0;
  refusal_started_ms = 0;
  state = State::REFUSAL_PENDING;
  ESP_LOGW(TAG, "initial upload failed for seq=%u; playing one refusal",
           (unsigned) response_seq);
}

// Wake detection remains stopped for every non-IDLE response state. In
// particular, READY_TO_RESUME waits for the interval action to start the
// detector on the component's normal task rather than from media_player's
// callback.
inline bool holds_wake() { return state != State::IDLE; }

inline void media_idle() {
  if (state == State::WAITING_FOR_MEDIA_IDLE) {
    retry_started_ms = millis();
    next_poll_ms = retry_started_ms;
    state = State::POLLING;
    ESP_LOGI(TAG, "media idle for seq=%u; starting status confirmation",
             (unsigned) response_seq);
  } else if (state == State::REFUSAL_PLAYING) {
    state = State::READY_TO_RESUME;
    ESP_LOGI(TAG, "refusal sound finished for seq=%u; wake may resume",
             (unsigned) response_seq);
  }
}

inline bool poll_due() {
  return state == State::POLLING &&
         static_cast<int32_t>(millis() - next_poll_ms) >= 0;
}

inline void refuse(const char *reason) {
  if (state == State::REFUSAL_PENDING ||
      state == State::REFUSAL_PLAYING ||
      state == State::READY_TO_RESUME ||
      state == State::IDLE) {
    return;
  }
  follow_up_admission_pending = false;
  follow_up_admission_granted_flag = false;
  state = State::REFUSAL_PENDING;
  ESP_LOGW(TAG, "response seq=%u unavailable (%s); playing one refusal",
           (unsigned) response_seq, reason);
}

inline void note_status(int status, const std::string &body) {
  if (state != State::POLLING) {
    return;
  }

  const uint32_t now = millis();
  if (status == 200 && body == terminal_body(response_seq, "complete")) {
    state = State::FOLLOW_UP_PENDING;
    ESP_LOGI(TAG, "response seq=%u confirmed complete (build=%s); follow-up window pending",
             (unsigned) response_seq, BUILD_IDENTITY);
    return;
  }

  if (status == 200 && body == terminal_body(response_seq, "silent")) {
    state = State::READY_TO_RESUME;
    ESP_LOGI(TAG, "response seq=%u confirmed silent; wake may resume",
             (unsigned) response_seq);
    return;
  }

  if (status == 200 &&
      body == home_admission_terminal_body(response_seq)) {
    home_admission_needed = true;
    refuse("Home claim retired; fresh admission required");
    return;
  }

  if (status == 409 &&
      static_cast<uint32_t>(now - retry_started_ms) < STATUS_RETRY_WINDOW_MS) {
    next_poll_ms = now + STATUS_RETRY_INTERVAL_MS;
    ESP_LOGD(TAG, "response seq=%u still active; retrying status in %ums",
             (unsigned) response_seq, (unsigned) STATUS_RETRY_INTERVAL_MS);
    return;
  }

  if (status == 409) {
    refuse("status remained active beyond retry window");
  } else if (status == 404) {
    refuse("unknown response sequence");
  } else if (status == 401 || status == 403) {
    puck_identity::note_upload_status(status);
    refuse("status authentication rejected");
  } else if (status >= 200 && status < 300) {
    refuse("terminal status was not complete");
  } else {
    refuse("status request failed");
  }
}

inline void note_transport_failure() {
  if (state == State::POLLING) {
    refuse("status transport failure");
  }
}

inline bool refusal_pending() { return state == State::REFUSAL_PENDING; }

inline bool follow_up_pending() { return state == State::FOLLOW_UP_PENDING; }

inline bool follow_up_capturing() { return state == State::FOLLOW_UP_CAPTURING; }

inline void follow_up_started() {
  if (can_start_follow_up_capture()) {
    follow_up_admission_granted_flag = false;
    state = State::FOLLOW_UP_CAPTURING;
    ESP_LOGI(TAG, "follow-up capture started for response seq=%u",
             (unsigned) response_seq);
  }
}

inline void note_follow_up_admission(int status, const std::string &body) {
  if (!follow_up_admission_pending) {
    return;
  }
  const std::string admitted =
      std::string("admitted:") + std::to_string(follow_up_admission_seq);
  if (status == 200 && body == admitted &&
      follow_up_admission_seq == response_seq &&
      state == State::FOLLOW_UP_PENDING) {
    follow_up_admission_pending = false;
    follow_up_admission_granted_flag = true;
    ESP_LOGI(TAG, "follow-up admission granted for seq=%u",
             (unsigned) follow_up_admission_seq);
    return;
  }
  const std::string identity_rejected =
      std::string("identity_rejected:") + std::to_string(follow_up_admission_seq);
  if (body == identity_rejected) {
    puck_identity::reject_authority("Home");
  } else if (status == 401) {
    puck_identity::note_upload_status(status);
  }
  refuse("follow-up admission denied or unavailable");
}

inline void note_follow_up_admission_transport_failure() {
  note_follow_up_admission(0, "");
}

inline void follow_up_capture_failed() {
  if (state == State::FOLLOW_UP_PENDING ||
      state == State::FOLLOW_UP_CAPTURING) {
    follow_up_admission_pending = false;
    follow_up_admission_granted_flag = false;
    refuse("follow-up capture or upload failed");
  }
}

// The upload interval calls one transition for either capture kind. Keep the
// dispatch here so the initial-versus-follow-up distinction is executable in
// the state-machine harness instead of living only in ESPHome YAML.
inline void upload_failed(uint32_t seq) {
  if (state == State::FOLLOW_UP_CAPTURING) {
    follow_up_capture_failed();
  } else {
    initial_upload_failed(seq);
  }
}

inline void refusal_started() {
  if (state == State::REFUSAL_PENDING) {
    refusal_started_ms = millis();
    state = State::REFUSAL_PLAYING;
  }
}

inline bool refusal_recovery_due() {
  return state == State::REFUSAL_PLAYING &&
         static_cast<uint32_t>(millis() - refusal_started_ms) >=
             REFUSAL_WATCHDOG_MS;
}

// The refusal is deliberately best-effort. If the media pipeline enters an
// error state and never produces the idle callback, do not hold wake detection
// forever; the interval action stops the failed playback and calls this
// fallback transition.
inline void refusal_recovered() {
  if (state == State::REFUSAL_PLAYING) {
    state = State::READY_TO_RESUME;
    ESP_LOGW(TAG, "refusal sound watchdog expired for seq=%u; wake may resume",
             (unsigned) response_seq);
  }
}

inline bool ready_to_resume() { return state == State::READY_TO_RESUME; }

inline void wake_resumed() {
  if (state == State::READY_TO_RESUME) {
    ESP_LOGI(TAG, "wake detection resumed after response seq=%u",
             (unsigned) response_seq);
    state = State::IDLE;
    follow_up_admission_pending = false;
    follow_up_admission_granted_flag = false;
  }
}

}  // namespace puck_response
