// 1-p-1-authorized-wake-and-capture: the Puck's identity gate.
//
// Before this existed, `on_wake_word_detected:` called
// `wake_capture::start()` immediately and the device's only credential --
// a hardcoded X-Puck-Token -- was not checked until the bridge received
// the upload (puck_bridge/receiver.py). The bridge's check is correctly
// fail-closed for the bridge, but by the time it runs, several seconds of
// a room have already been recorded and put on the network. Epic 1
// requires identity to fail closed BEFORE capture, with no fallback.
//
// Scope, per the story's Boundaries: this does NOT invent credentialing.
// Provisioning and revocation belong to separate device-administration
// work. This consumes the configured token and refuses to capture when it
// is absent or has been actively rejected. A token baked into firmware
// cannot be revoked without reflashing, so the value delivered here is
// ORDERING (no capture before authorization) and OBSERVABILITY (a refusal
// is visible), not cryptographic assurance. Said plainly so nobody reads
// this file as more than it is.
#pragma once

#include "esphome/core/log.h"
#include <cstdint>
#include <string>

namespace puck_identity {

static const char *const TAG = "puck_identity";

// Three states, per the contract decided 2026-09-10. The distinction that
// matters is REJECTED vs UNREACHABLE:
//
//   - A 401 is a reachable authority actively saying no. Fail closed.
//   - An unreachable bridge says nothing about identity, and there is
//     nowhere for audio to go anyway -- it sits in PSRAM, the upload
//     fails, pcm_capture.h's 2-failure abandonment drops it, the next
//     capture overwrites it. The failure mode is a lost turn, not a leak.
//     Refusing wakes during a WiFi blip would make the appliance
//     indistinguishable from broken, which is the worse outcome.
enum class State : uint8_t {
  AUTHORIZED,    // token configured, not rejected -- capture normally
  UNAUTHORIZED,  // token missing, or bridge answered 4xx -- fail closed
  DEGRADED,      // no response or bridge/server answered 3xx/5xx -- capture
};

static State state = State::UNAUTHORIZED;  // fail closed until proven otherwise

inline const char *state_name(State s) {
  switch (s) {
    case State::AUTHORIZED:
      return "AUTHORIZED";
    case State::UNAUTHORIZED:
      return "UNAUTHORIZED";
    case State::DEGRADED:
      return "DEGRADED";
  }
  return "UNKNOWN";
}

// Called once at boot with the compile-time token. Deliberately starts in
// UNAUTHORIZED above rather than defaulting open: a build that somehow
// ships without a token must refuse, not capture.
inline void setup(const std::string &token) {
  if (token.empty()) {
    state = State::UNAUTHORIZED;
    ESP_LOGE(TAG, "no device token configured -- wake capture will fail closed");
    return;
  }
  state = State::AUTHORIZED;
  ESP_LOGI(TAG, "device token configured (%u chars) -- state=%s", (unsigned) token.size(), state_name(state));
}

// The gate itself. Consulted by on_wake_word_detected BEFORE any capture
// buffer is touched.
inline bool may_capture() { return state != State::UNAUTHORIZED; }

// Called from the upload path with each chunk's HTTP status.
//
// status 4xx  -> the reachable bridge rejected the request. Fail closed from
//                here on; only a reboot (i.e. a reflash or a restored token)
//                clears it. 401 is the normal credential-rejection response;
//                the rest are still explicit client-side refusals under the
//                P-1 contract.
// status <= 0 -> no HTTP response at all: connection refused, timeout,
//                DNS failure. DEGRADED, NOT a refusal -- see the enum.
// status 3xx/5xx -> the bridge or server is reachable but unavailable for
//                this attempt. DEGRADED, not an identity decision.
// 2xx         -> identity is good; clears a previous DEGRADED.
inline void note_upload_status(int status) {
  if (status >= 400 && status < 500) {
    if (state != State::UNAUTHORIZED) {
      if (status == 401) {
        ESP_LOGE(TAG, "bridge rejected our token (401) -- failing closed; no further capture until reboot");
      } else {
        ESP_LOGE(TAG, "bridge rejected the upload (HTTP %d) -- failing closed; no further capture until reboot",
                 status);
      }
    }
    state = State::UNAUTHORIZED;
    return;
  }
  // Once rejected, stay rejected. A 2xx from somewhere else must not
  // silently re-authorize a device an authority has refused.
  if (state == State::UNAUTHORIZED) {
    return;
  }
  if (status >= 200 && status < 300) {
    if (state != State::AUTHORIZED) {
      ESP_LOGI(TAG, "bridge reachable again -- state=AUTHORIZED");
    }
    state = State::AUTHORIZED;
  } else {
    if (state != State::DEGRADED) {
      ESP_LOGW(TAG, "bridge unavailable (status %d) -- state=DEGRADED; still capturing (lost turn, not a leak)",
               status);
    }
    state = State::DEGRADED;
  }
}

}  // namespace puck_identity
