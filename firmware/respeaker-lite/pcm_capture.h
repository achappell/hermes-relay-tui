// Training-data capture pipeline for story 3's custom wake-word model
// (Hermes Relay TUI, follow-up after cross-validation proved the pipeline
// itself is correct and the remaining gap is acoustic -- this hardware's
// processed audio doesn't match what pretrained models expect). Captures
// short rolling windows of the exact audio micro_wake_word's own
// MicrophoneSource delivers, and uploads each one over WiFi via
// http_request as soon as it fills, then immediately restarts -- so a
// human/TTS speaking near the device gets continuously captured without
// any per-sample trigger round-trip.
//
// Same safety pattern as the original diagnostic version: a single
// heap_caps_malloc call made once in setup() (never resized), and the
// real-time mic callback only ever does a bounded memcpy -- no
// allocation, growth, or blocking I/O on that path. The upload (which
// blocks on a POST) only ever runs from a slow `interval:` tick.
#pragma once

#include "esp_heap_caps.h"
#include "esphome/core/alloc_helpers.h"
#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "esphome/components/http_request/http_request.h"
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <algorithm>
#include <cstdint>
#include <cstddef>
#include <cstring>

namespace pcm_capture {

static const char *const TAG = "pcm_capture";

// 2 seconds of stereo, 32-bit, 16kHz audio -- long enough to comfortably
// hold one spoken utterance with lead/trail silence, short enough to
// upload quickly and keep the rolling capture cadence tight.
static const size_t CAPTURE_BYTES = 16000 * 4 * 2 * 2;

static uint8_t *buffer = nullptr;
static size_t write_pos = 0;
static bool capturing = false;
static bool capture_done = false;
static uint32_t sample_index = 0;

inline void setup() {
  buffer = static_cast<uint8_t *>(heap_caps_malloc(CAPTURE_BYTES, MALLOC_CAP_SPIRAM));
  if (buffer == nullptr) {
    ESP_LOGE(TAG, "Failed to allocate %u bytes of PSRAM for PCM capture", (unsigned) CAPTURE_BYTES);
  } else {
    ESP_LOGI(TAG, "Allocated %u bytes of PSRAM for PCM capture", (unsigned) CAPTURE_BYTES);
  }
}

inline void start() {
  if (buffer == nullptr) {
    return;
  }
  write_pos = 0;
  capture_done = false;
  capturing = true;
}

// Called from the microphone's real-time on_data callback. Bounded,
// allocation-free: a single memcpy per call, clamped to the pre-sized
// buffer. Never grows or reallocates anything.
inline void write(const uint8_t *data, size_t len) {
  if (!capturing || buffer == nullptr) {
    return;
  }
  size_t remaining = CAPTURE_BYTES - write_pos;
  size_t to_copy = len < remaining ? len : remaining;
  memcpy(buffer + write_pos, data, to_copy);
  write_pos += to_copy;
  if (write_pos >= CAPTURE_BYTES) {
    capturing = false;
    capture_done = true;
  }
}

// Constructing a single std::string from the whole ~256KB capture buffer
// crashed the device: libstdc++'s default allocator for a plain
// std::string does not land on PSRAM here, and a contiguous ~256KB
// internal-RAM allocation reliably fails (std::bad_alloc -> abort, no
// exception handler -> crash-loop). Uploading in small chunks keeps each
// std::string allocation trivially small and internal-RAM-safe, and the
// receiver reassembles them by sequence + chunk index.
static const size_t UPLOAD_CHUNK_BYTES = 16000;  // ~16KB per POST body

// Called from a slow `interval:` tick, never from the real-time audio
// path. Blocks on each POST (fine here -- main loop, not the mic task),
// then immediately re-arms capture for the next window once fully sent.
inline void upload_and_restart(esphome::http_request::HttpRequestComponent *client, const std::string &url) {
  if (!capture_done || buffer == nullptr) {
    return;
  }

  // Per-chunk retry was tried and reverted (see story 3, follow-up session
  // 12): once esp_http_client wedges into ESP_FAIL, *each individual POST
  // call itself blocks for ~11 seconds before failing -- an ESP-IDF-internal
  // reconnect delay, not something app-level retry/backoff can shorten or
  // route around. Retrying the same wedged chunk just stacks multiple 11s
  // blocks on top of each other with no corresponding gain in success rate,
  // turning a ~22s stall into a ~66s one. Back to single-attempt-per-chunk
  // with bounded abandonment; the real fix needs to act on the client
  // connection itself (forced close/reconnect, or a periodic component
  // reset), not retry the same call.
  size_t total_chunks = (write_pos + UPLOAD_CHUNK_BYTES - 1) / UPLOAD_CHUNK_BYTES;
  bool ok = true;
  int consecutive_failures = 0;
  for (size_t chunk = 0; chunk < total_chunks; ++chunk) {
    size_t offset = chunk * UPLOAD_CHUNK_BYTES;
    size_t len = std::min(UPLOAD_CHUNK_BYTES, write_pos - offset);
    std::string body(reinterpret_cast<const char *>(buffer + offset), len);
    std::string full_url = url + "?seq=" + std::to_string(sample_index) + "&chunk=" + std::to_string(chunk) +
                            "&total=" + std::to_string(total_chunks) + "&ms=" + std::to_string(millis());
    // Diagnostic (story 3 follow-up session 13): ESPHome's IDF http_request
    // backend creates a *fresh* esp_http_client_handle_t on every single
    // post() call and cleans it up in end() -- confirmed by reading
    // http_request_idf.cpp -- so the ESP_FAIL wedging is not a leaked/reused
    // client handle at this layer. Logging internal-RAM heap (current free
    // and the all-time-low watermark) proved a real pattern: every FAILED
    // call costs several KB of internal RAM that does not reliably come back
    // (min_ever cascades down across a run of failures -- e.g.
    // 200996 -> 194436 -> 188064 -> ... -- while successful calls show no
    // such trend, recovering back to baseline). This is very likely a
    // lingering/delayed-release resource inside ESP-IDF's own connect-failure
    // path (a half-torn-down TCP socket, not something visible or patchable
    // from this component), not a leak in this file's own code. Left as a
    // permanent diagnostic since it's what caught this.
    uint32_t heap_before = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    auto response = client->post(full_url, body);
    uint32_t heap_after = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    bool chunk_ok = response != nullptr && response->status_code >= 200 && response->status_code < 300;
    if (!chunk_ok) {
      ESP_LOGW(TAG, "Upload %u chunk %u failed (status %d) -- internal heap before=%u after=%u min_ever=%u",
               (unsigned) sample_index, (unsigned) chunk, response ? response->status_code : -1,
               (unsigned) heap_before, (unsigned) heap_after, (unsigned) heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL));
      ok = false;
      consecutive_failures++;
    } else {
      ESP_LOGD(TAG, "Upload %u chunk %u ok -- internal heap before=%u after=%u", (unsigned) sample_index,
               (unsigned) chunk, (unsigned) heap_before, (unsigned) heap_after);
      consecutive_failures = 0;
    }
    if (response != nullptr) {
      response->end();
    }

    // Circuit breaker (session 13): the failed-call heap cost above isn't
    // bounded by anything in this file, and a real burst was measured
    // spiraling from a ~224KB baseline down through ~161KB in well under a
    // minute of intermittent failures. Left unchecked this heads toward an
    // uncontrolled out-of-memory crash somewhere else in the firmware (WiFi,
    // TLS, the wake-word engine) at an unpredictable moment. A clean reboot
    // -- which fully reclaims whatever ESP-IDF is holding onto -- is a far
    // better failure mode than that: it costs one lost capture window and
    // a ~10s reconnect, not an unbounded crash-loop risk. The next capture
    // cycle starts fresh with full heap.
    //
    // Checked against the all-time-low watermark (heap_caps_get_minimum_
    // free_size), not the post-call heap_after snapshot: a first attempt at
    // this checked heap_after and never fired, because heap partially
    // recovers within a few hundred ms of a failed call finishing -- by the
    // time heap_after was read, a transient dip to 86508 bytes had already
    // bounced back up past the threshold. The watermark catches the real
    // danger point (a transient dip is exactly when something else
    // allocating would crash) and, being monotonic for the process
    // lifetime, only trips once -- which is the right behavior here: reboot
    // once things have ever gotten this low, not just when they currently
    // are. Threshold (96KB) is well above where this board has been
    // observed to actually crash, so this fires as an early warning.
    static const uint32_t LOW_HEAP_REBOOT_THRESHOLD = 96000;
    uint32_t heap_watermark = heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL);
    if (heap_watermark < LOW_HEAP_REBOOT_THRESHOLD) {
      ESP_LOGE(TAG, "Internal heap watermark critically low (%u bytes) after a run of failed uploads -- rebooting "
                     "to reclaim ESP-IDF-held resources before an uncontrolled crash",
               (unsigned) heap_watermark);
      esphome::App.safe_reboot();
    }
    // A run of failures usually means the HTTP client has wedged (seen as
    // persistent ESP_FAIL after a burst of successful uploads). Bail out of
    // this sample rather than burning through every remaining chunk at the
    // ESP-IDF client's own multi-second retry cadence; the next capture
    // cycle gets a fresh attempt instead of being stuck behind this one.
    if (consecutive_failures >= 2) {
      ESP_LOGW(TAG, "Upload %u abandoned after %d consecutive chunk failures", (unsigned) sample_index,
               consecutive_failures);
      break;
    }
    // Small breathing room between chunks -- back-to-back POSTs with no
    // gap appear to exhaust something in the ESP32's TCP/socket stack
    // (observed as persistent ESP_FAIL after the first few chunks).
    vTaskDelay(pdMS_TO_TICKS(30));
  }
  if (ok) {
    ESP_LOGD(TAG, "Uploaded sample %u (%u bytes, %u chunks)", (unsigned) sample_index, (unsigned) write_pos,
             (unsigned) total_chunks);
  }

  sample_index++;
  start();
}

// Serial-dump path (story 3, session 16 -- see story doc for the full
// history). A prior version dumped the *full* ~256KB capture (~1280 chunks)
// continuously, immediately re-arming after every 2s window, indefinitely;
// it hung the device on first live test with no crash marker. Root-caused
// later the same session (loopTask watchdog starvation, fixed via
// App.feed_wdt() below) and proven safe one-shot at full capture size.
// This step re-arms, but only for a small, bounded number of repeats
// (MAX_DUMPS) -- not an indefinite loop -- to test whether *repeated*
// captures are safe before ever going back to continuous.
static const size_t DUMP_CHUNK_BYTES = 200;
static const size_t DUMP_MAX_CHUNKS = 1280;  // full ~256KB/2s capture
// Verified at 15 (session 16 step 5): 15/15 full captures completed clean,
// zero crash markers, chunk-corruption rate held flat (~0.05%, no worse
// than smaller runs). Still bounded, not indefinite -- see story doc.
static const uint32_t MAX_DUMPS = 15;

inline void dump_over_serial() {
  static uint32_t dumps_done = 0;
  if (dumps_done >= MAX_DUMPS || !capture_done || buffer == nullptr) {
    return;
  }

  size_t full_chunks = (write_pos + DUMP_CHUNK_BYTES - 1) / DUMP_CHUNK_BYTES;
  size_t total_chunks = std::min(full_chunks, DUMP_MAX_CHUNKS);
  size_t total_bytes = std::min(write_pos, total_chunks * DUMP_CHUNK_BYTES);

  ESP_LOGI(TAG, "PCMDUMP begin seq=%u total_bytes=%u total_chunks=%u", (unsigned) sample_index,
           (unsigned) total_bytes, (unsigned) total_chunks);
  for (size_t chunk = 0; chunk < total_chunks; ++chunk) {
    size_t offset = chunk * DUMP_CHUNK_BYTES;
    size_t len = std::min(DUMP_CHUNK_BYTES, write_pos - offset);
    std::string b64 = esphome::base64_encode(buffer + offset, len);
    ESP_LOGI(TAG, "PCMDUMP seq=%u chunk=%u total=%u b64=%s", (unsigned) sample_index, (unsigned) chunk,
             (unsigned) total_chunks, b64.c_str());
    // Session 16 step 2 (300 chunks) tripped ESPHome's own loopTask
    // watchdog (task_wdt: Aborting) partway through -- ESPHome only feeds
    // it once per loop() iteration, and this whole dump runs inside a
    // single interval callback, so a long enough dump starves it even
    // though vTaskDelay below yields the CPU. http_request's own component
    // hits this same class of problem and fixes it the same way (see
    // http_request.h: `App.feed_wdt()` inside its own long-running loops)
    // -- App.feed_wdt() is ESPHome's own rate-limited public API for this,
    // not a raw ESP-IDF watchdog bypass like session 14's dangerous
    // connection-reuse attempt.
    esphome::App.feed_wdt();
    // Deliberate breathing room -- session 15 speculated the hang may have
    // been the host-side reader unable to drain fast enough at high serial
    // volume. This dump is small enough that this delay barely matters for
    // total time, but keep it for consistency with what will be tried at
    // larger scale later.
    vTaskDelay(pdMS_TO_TICKS(10));
  }
  ESP_LOGI(TAG, "PCMDUMP end seq=%u", (unsigned) sample_index);
  sample_index++;
  dumps_done++;
  if (dumps_done < MAX_DUMPS) {
    // Bounded re-arm: start the next 2s capture. capture_done goes false
    // again immediately, so this function no-ops on subsequent interval
    // ticks until the new capture fills, exactly like the first one.
    start();
  } else {
    ESP_LOGI(TAG, "PCMDUMP series complete after %u dumps -- not re-arming further", (unsigned) dumps_done);
  }
}

}  // namespace pcm_capture
