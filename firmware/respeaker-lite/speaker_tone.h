// PUCK-01.7 task 1 diagnostic: prove the Puck can make a sound at all.
//
// Deliberately separate from pcm_capture.h. That file owns the *input*
// direction (wake-triggered capture and chunked upload) and carries a long
// history of hard-won safety machinery; this file owns the *output*
// direction and must not entangle with it. Story 5's capture path is not
// touched by anything here.
//
// This is scaffolding, not the real playback path. PUCK-01.7 task 2
// replaces it with `audio_http` + `media_player` streaming real TTS from
// the bridge -- ESPHome's own audio stack, which handles buffering and
// decoding. The only job of this file is to answer one question before
// that work starts: does audio physically come out of the speaker, and
// does the microphone still work after the I2S bus was split in two?
#pragma once

#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "esphome/components/speaker/speaker.h"
#include "esphome/components/audio/audio.h"
#include <freertos/FreeRTOS.h>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstddef>
#include <vector>

namespace speaker_tone {

static const char *const TAG = "speaker_tone";

// Must match the `speaker:` block in respeaker-lite.yaml -- both
// directions ride the XU316's shared clocks, so this is not a free choice.
static const int SAMPLE_RATE = 48000;
static const size_t BYTES_PER_FRAME = 8;  // stereo, 32-bit

// Amplitude well below INT32_MAX. The mic path already showed ch0 peaks
// around 1.8e9, so the codec is comfortable at this scale; starting quiet
// avoids a startling full-scale blast through a desk speaker.
static const double AMPLITUDE = 1.5e8;

// Written in 10ms slices rather than one allocation: a 400ms stereo 32-bit
// tone is ~154KB, which is exactly the kind of large contiguous
// internal-RAM allocation that crash-looped this device during story 3
// (see pcm_capture.h's chunked-upload comment). One small reused buffer
// keeps this allocation-trivial.
static const size_t FRAMES_PER_CHUNK = 480;

// Declare the stream format and begin starting the speaker. Split out from
// play() because start() is asynchronous -- the caller must yield to the
// main loop (an ESPHome `delay:`) between arm() and play(), or the speaker
// will still be starting and every play() call returns 0.
inline void arm(esphome::speaker::Speaker *spk) {
  if (spk == nullptr) {
    return;
  }
  // Must be set BEFORE start(). AudioStreamInfo's default is (16 bits, 1
  // channel, 16000 Hz) -- ESPHome's historical values -- and the I2S speaker
  // in secondary/slave mode cannot reconfigure the bus, so it hard-rejects
  // any stream whose sample rate differs from the configured one with
  // "Incompatible stream settings" (i2s_audio_speaker_standard.cpp:366).
  // The XU316 masters the clocks here, so 48kHz/32-bit/stereo is not a
  // preference -- it is the only thing this bus can carry.
  spk->set_audio_stream_info(esphome::audio::AudioStreamInfo(32, 2, SAMPLE_RATE));
  spk->start();
}

inline void play(esphome::speaker::Speaker *spk, int freq_hz, int duration_ms) {
  if (spk == nullptr) {
    return;
  }
  if (!spk->is_running()) {
    ESP_LOGW(TAG, "speaker not running yet -- call arm() and yield to the main loop before play()");
    return;
  }

  std::vector<uint8_t> buf(FRAMES_PER_CHUNK * BYTES_PER_FRAME);
  const size_t total_frames = (size_t) SAMPLE_RATE * duration_ms / 1000;
  const double step = 2.0 * M_PI * freq_hz / SAMPLE_RATE;
  double phase = 0.0;
  size_t written_frames = 0;

  ESP_LOGI(TAG, "playing %dHz test tone for %dms (%u frames)", freq_hz, duration_ms, (unsigned) total_frames);

  while (written_frames < total_frames) {
    const size_t n = std::min(FRAMES_PER_CHUNK, total_frames - written_frames);
    for (size_t i = 0; i < n; ++i) {
      const int32_t v = (int32_t) (std::sin(phase) * AMPLITUDE);
      phase += step;
      const size_t off = i * BYTES_PER_FRAME;
      // Same sample to both channels -- little-endian int32, twice.
      buf[off + 0] = buf[off + 4] = (uint8_t) (v & 0xFF);
      buf[off + 1] = buf[off + 5] = (uint8_t) ((v >> 8) & 0xFF);
      buf[off + 2] = buf[off + 6] = (uint8_t) ((v >> 16) & 0xFF);
      buf[off + 3] = buf[off + 7] = (uint8_t) ((v >> 24) & 0xFF);
    }

    // Blocking variant: the speaker's DMA buffer is only `buffer_duration`
    // (100ms) deep, so a 400ms tone cannot be handed over in one go. Wait
    // for space rather than silently dropping the remainder -- play()
    // returns the count it actually accepted.
    const size_t want = n * BYTES_PER_FRAME;
    size_t sent = 0;
    while (sent < want) {
      const size_t accepted =
          spk->play(buf.data() + sent, want - sent, pdMS_TO_TICKS(200));
      if (accepted == 0) {
        ESP_LOGW(TAG, "speaker accepted no data -- aborting tone at frame %u", (unsigned) written_frames);
        return;
      }
      sent += accepted;
      // This whole loop runs inside one callback; feed the loopTask
      // watchdog for the same reason pcm_capture.h's dump loop does.
      esphome::App.feed_wdt();
    }
    written_frames += n;
  }

  ESP_LOGI(TAG, "test tone complete (%u frames written)", (unsigned) written_frames);
}

}  // namespace speaker_tone
