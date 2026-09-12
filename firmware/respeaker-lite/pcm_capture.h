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
// 1-p-1: identity gate, fed by the upload path below and consulted before
// any capture starts. Separate header -- this file owns capture, not
// authorization.
#include "puck_identity.h"
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <algorithm>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <string>
#include <vector>

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
//
// Story 5, discovered live during this story's hardware smoke test on a
// marginal-WiFi-signal device (observed -89 to -90 dB): ESP-IDF's
// esp_http_client_write() (http_request_idf.cpp) aborts the whole POST
// with ESP_FAIL the instant a single write() call returns <=0 partway
// through the body -- it never retries that write. tcpdump on the
// receiving host confirmed the TCP handshake completing normally, a
// small partial write landing, then silence: the socket write stalled
// out on a lossy link before the full body went through. Shrunk from
// 16000 to 2000 so a single write has to survive far less time on a
// flaky link before completing -- this is a mitigation for a genuinely
// weak signal, not a fix for it; moving the device closer to the AP
// remains the real fix.
//
// RESTORED to 16000 on 2026-09-11, because that real fix happened: the
// Puck was relocated and now reads -54 dBm (versus -89/-90), and six
// consecutive captures uploaded with zero chunk failures. The mitigation
// outlived the condition it mitigated, and it was expensive -- ESPHome's
// IDF http_request backend opens a FRESH esp_http_client connection per
// post() call, so nearly all of the measured 77ms per chunk was
// connection setup rather than transfer. At 2KB a full 8s capture is 512
// POSTs (~39.5s at the measured 25.3 KB/s), which exceeded the bridge's
// 30s reassembly TTL and silently lost every long capture. At 16KB the
// same capture is 64 POSTs, cutting the per-connection tax by 8x.
//
// If this device is ever moved back to a weak-signal location, this is
// the first knob to turn back down -- the failure mode there is
// mid-transfer write stalls, not throughput.
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

// VAD-gated, single-shot, wake-triggered capture (story 5). Reuses this
// file's proven allocation/write/chunked-upload pattern above, but differs
// from `upload_and_restart`'s rolling-capture design in exactly the ways
// story 5 needs: (a) sized for ~8s of audio, not a fixed 2s window -- long
// enough for a real spoken question with lead/trail silence, (b) the
// capture window ends when `micro_wake_word`'s own VAD model (already
// proven responsive: `probability_cutoff: 0.05` in respeaker-lite.yaml)
// reports silence for a debounce period, not when the buffer fills, and
// (c) it does NOT re-arm at the end -- one wake, one upload, then it waits
// for the next `on_wake_word_detected` trigger. No continuous rolling
// capture, matching this story's Boundaries & Constraints.
namespace wake_capture {

// 8 seconds of stereo, 32-bit, 16kHz audio -- comfortably longer than any
// spoken household question, per this story's story file.
static const size_t WAKE_CAPTURE_SECONDS = 8;
static const size_t WAKE_CAPTURE_BYTES = 16000 * 4 * 2 * WAKE_CAPTURE_SECONDS;

// How long VAD must report silence before the capture window is considered
// over. Short enough to keep the round-trip snappy, long enough to survive
// a normal mid-sentence pause without cutting the question off early.
static const uint32_t VAD_SILENCE_DEBOUNCE_MS = 800;

static uint8_t *buffer = nullptr;
static size_t write_pos = 0;
static bool capturing = false;
static bool capture_done = false;
static bool capture_pending_upload = false;
static uint32_t silence_start_ms = 0;
static uint32_t sample_index = 0;

// 1-p-1 task 3: set by start() when the identity gate refuses a wake, so
// the automation can sound the refusal. Deliberately set HERE rather than
// having the automation re-evaluate may_capture() itself: the gate and
// the signal that it fired must be the same decision, or they can drift
// apart and the device could refuse silently (or beep while capturing).
// Cleared on every wake so it only ever describes the most recent one.
static bool last_wake_refused = false;

// 1-p-2 task 5: set when an upload was confirmed reassembled by the
// bridge, so the automation can fetch and play the spoken answer. Uses the
// same pattern as last_wake_refused -- the code that KNOWS the outcome
// records it, rather than the automation re-deriving it and risking the
// two drifting apart.
static bool last_upload_delivered = false;
// The sequence the bridge reassembled, so the response fetch asks for the
// right one rather than assuming the latest.
static uint32_t last_delivered_seq = 0;

inline void setup() {
  buffer = static_cast<uint8_t *>(heap_caps_malloc(WAKE_CAPTURE_BYTES, MALLOC_CAP_SPIRAM));
  if (buffer == nullptr) {
    ESP_LOGE(TAG, "Failed to allocate %u bytes of PSRAM for wake capture", (unsigned) WAKE_CAPTURE_BYTES);
  } else {
    ESP_LOGI(TAG, "Allocated %u bytes of PSRAM for wake capture", (unsigned) WAKE_CAPTURE_BYTES);
  }
}

// Called from `on_wake_word_detected:`. Single-shot: a wake heard while a
// capture or its upload is still in flight is dropped rather than
// restarting the buffer mid-write, matching the "one wake, one upload"
// rule -- the next wake after this one finishes gets a clean window.
inline void start(const std::string &wake_word) {
  // 1-p-1: authorization is a PRECONDITION of capture, checked before the
  // buffer is touched -- not afterwards at upload time, which is where the
  // only check used to live. A refused device must record nothing at all,
  // so this is deliberately the very first statement in the function.
  last_wake_refused = false;
  if (!puck_identity::may_capture()) {
    last_wake_refused = true;
    ESP_LOGW(TAG, "wake refused (wake_word=%s): identity %s -- no capture, no upload, no fallback",
             wake_word.c_str(), puck_identity::state_name(puck_identity::state));
    return;
  }
  if (buffer == nullptr || capturing || capture_pending_upload) {
    ESP_LOGD(TAG, "wake capture ignored (wake_word=%s, already busy)", wake_word.c_str());
    return;
  }
  write_pos = 0;
  capture_done = false;
  silence_start_ms = 0;
  capturing = true;
  ESP_LOGI(TAG, "wake capture started (wake_word=%s)", wake_word.c_str());
}

// Called from the microphone's real-time on_data callback, alongside the
// existing training-data `pcm_capture::write()` above. Bounded,
// allocation-free -- the same single-memcpy shape as that function.
inline void write(const uint8_t *data, size_t len) {
  if (!capturing || buffer == nullptr) {
    return;
  }
  size_t remaining = WAKE_CAPTURE_BYTES - write_pos;
  size_t to_copy = len < remaining ? len : remaining;
  memcpy(buffer + write_pos, data, to_copy);
  write_pos += to_copy;
  if (write_pos >= WAKE_CAPTURE_BYTES) {
    // The buffer filled before VAD ever reported silence -- still a valid,
    // bounded capture; end it rather than overrun.
    capturing = false;
    capture_done = true;
    capture_pending_upload = true;
    ESP_LOGW(TAG, "wake capture reached the %us buffer limit before VAD silence", (unsigned) WAKE_CAPTURE_SECONDS);
  }
}

// Called from a fast `interval:` tick (not the real-time audio path) with
// the current VAD state. Ends the capture window on debounced silence --
// this is what makes the window VAD-gated instead of a fixed timer.
inline void tick(bool vad_active) {
  if (!capturing) {
    return;
  }
  uint32_t now = millis();
  if (vad_active) {
    silence_start_ms = 0;
    return;
  }
  if (silence_start_ms == 0) {
    silence_start_ms = now;
    return;
  }
  if (now - silence_start_ms >= VAD_SILENCE_DEBOUNCE_MS) {
    capturing = false;
    capture_done = true;
    capture_pending_upload = true;
    ESP_LOGI(TAG, "wake capture ended on VAD silence (%u bytes)", (unsigned) write_pos);
  }
}

// Called from a slow `interval:` tick, never from the real-time audio
// path. Single-shot upload: unlike `upload_and_restart`, this does NOT
// call `start()` again when finished -- the next capture only begins from
// another `on_wake_word_detected` trigger. Reuses the exact chunked-POST
// loop, heap-watermark reboot circuit breaker, 2-consecutive-failure
// abandonment, and 30ms inter-chunk delay already proven above.
inline void upload(esphome::http_request::HttpRequestComponent *client, const std::string &url,
                    const std::string &token) {
  if (!capture_done || !capture_pending_upload || buffer == nullptr) {
    return;
  }
  capture_pending_upload = false;

  // VAD reported silence before any audio was ever captured (write_pos ==
  // 0): total_chunks below would compute to 0, the upload loop would
  // silently no-op, and this wake would produce no upload at all with no
  // diagnostic. Bail out explicitly instead of relying on the loop's
  // implicit skip.
  if (write_pos == 0) {
    ESP_LOGW(TAG, "Wake upload %u skipped -- capture ended with zero bytes written", (unsigned) sample_index);
    sample_index++;
    return;
  }

  size_t total_chunks = (write_pos + pcm_capture::UPLOAD_CHUNK_BYTES - 1) / pcm_capture::UPLOAD_CHUNK_BYTES;
  bool ok = true;
  bool reassembly_confirmed = false;
  int consecutive_failures = 0;
  const uint32_t upload_started_ms = millis();
  for (size_t chunk = 0; chunk < total_chunks; ++chunk) {
    size_t offset = chunk * pcm_capture::UPLOAD_CHUNK_BYTES;
    size_t len = std::min(pcm_capture::UPLOAD_CHUNK_BYTES, write_pos - offset);
    std::string body(reinterpret_cast<const char *>(buffer + offset), len);
    std::string full_url = url + "?seq=" + std::to_string(sample_index) + "&chunk=" + std::to_string(chunk) +
                            "&total=" + std::to_string(total_chunks) + "&ms=" + std::to_string(millis());
    std::vector<esphome::http_request::Header> headers = {{"X-Puck-Token", token.c_str()}};

    uint32_t heap_before = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    auto response = client->post(full_url, body, headers);
    uint32_t heap_after = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    bool chunk_ok = response != nullptr && response->status_code >= 200 && response->status_code < 300;
    // The bridge answers 202 for a chunk accepted into an incomplete
    // reassembly and 200 only when the capture is whole. Without this
    // distinction the loop below reported success purely because no POST
    // failed -- which stayed true even when the bridge had already evicted
    // the reassembly on its 30s TTL and the turn was lost.
    if (chunk_ok && response->status_code == 200) {
      reassembly_confirmed = true;
    }
    // 1-p-1: feed the identity gate. A 401 means a reachable bridge
    // actively refused this credential -- fail closed for every subsequent
    // wake. No response at all (status <= 0) is unreachability, which is
    // DEGRADED and deliberately keeps capturing; see puck_identity.h.
    puck_identity::note_upload_status(response != nullptr ? response->status_code : -1);
    if (!chunk_ok) {
      ESP_LOGW(TAG, "Wake upload %u chunk %u failed (status %d) -- internal heap before=%u after=%u min_ever=%u",
               (unsigned) sample_index, (unsigned) chunk, response ? response->status_code : -1,
               (unsigned) heap_before, (unsigned) heap_after,
               (unsigned) heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL));
      ok = false;
      consecutive_failures++;
    } else {
      ESP_LOGD(TAG, "Wake upload %u chunk %u ok -- internal heap before=%u after=%u", (unsigned) sample_index,
               (unsigned) chunk, (unsigned) heap_before, (unsigned) heap_after);
      consecutive_failures = 0;
    }
    if (response != nullptr) {
      response->end();
    }

    // Same heap-watermark reboot circuit breaker as `upload_and_restart` --
    // see that function's comment above for the full reasoning.
    static const uint32_t LOW_HEAP_REBOOT_THRESHOLD = 96000;
    uint32_t heap_watermark = heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL);
    if (heap_watermark < LOW_HEAP_REBOOT_THRESHOLD) {
      ESP_LOGE(TAG, "Internal heap watermark critically low (%u bytes) after a run of failed wake uploads -- "
                     "rebooting to reclaim ESP-IDF-held resources before an uncontrolled crash",
               (unsigned) heap_watermark);
      esphome::App.safe_reboot();
    }
    if (consecutive_failures >= 2) {
      ESP_LOGW(TAG, "Wake upload %u abandoned after %d consecutive chunk failures", (unsigned) sample_index,
               consecutive_failures);
      break;
    }
    // Same inter-chunk breathing room as `upload_and_restart` -- see that
    // function's comment above.
    vTaskDelay(pdMS_TO_TICKS(30));
  }
  const uint32_t elapsed_ms = millis() - upload_started_ms;
  last_upload_delivered = ok && reassembly_confirmed;
  last_delivered_seq = sample_index;
  if (ok && reassembly_confirmed) {
    ESP_LOGI(TAG, "Wake capture %u delivered (%u bytes, %u chunks, %ums)", (unsigned) sample_index,
             (unsigned) write_pos, (unsigned) total_chunks, (unsigned) elapsed_ms);
  } else if (ok) {
    // Every chunk was accepted but the bridge never confirmed a complete
    // reassembly -- almost certainly its TTL evicting a capture we were
    // still uploading. This is the turn-losing case that used to report
    // success; say so plainly, with the timing that explains it.
    ESP_LOGE(TAG, "Wake capture %u LOST: all %u chunks accepted but the bridge never confirmed reassembly "
                   "(%u bytes in %ums -- likely exceeded the receiver's reassembly TTL)",
             (unsigned) sample_index, (unsigned) total_chunks, (unsigned) write_pos, (unsigned) elapsed_ms);
  } else {
    ESP_LOGE(TAG, "Wake capture %u FAILED: chunk upload errors (%u bytes, %u chunks, %ums)",
             (unsigned) sample_index, (unsigned) write_pos, (unsigned) total_chunks, (unsigned) elapsed_ms);
  }

  sample_index++;
  // Deliberately no `start()` here -- single-shot, no re-arm. The next
  // capture begins only from the next `on_wake_word_detected` trigger.
}

}  // namespace wake_capture

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
