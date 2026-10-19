// Vendored ESPHome runtime (GPLv3); source/version/hashes and local changes are recorded in the header.
#include "resampler_speaker.h"

#ifdef USE_ESP32

#include "esphome/components/audio/audio_resampler.h"

#include "esphome/core/application.h"
#include "esphome/core/defines.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"

#include <algorithm>
#include <cstring>

namespace esphome::resampler {

static const UBaseType_t RESAMPLER_TASK_PRIORITY = 1;

static const uint32_t TRANSFER_BUFFER_DURATION_MS = 50;

static const uint32_t TASK_STACK_SIZE = 3072;

static const uint32_t STATE_TRANSITION_TIMEOUT_MS = 5000;

static const char *const TAG = "resampler_speaker";

enum ResamplingEventGroupBits : uint32_t {
  COMMAND_STOP = (1 << 0),       // signals stop request
  COMMAND_START = (1 << 1),      // signals start request
  COMMAND_FINISH = (1 << 2),     // signals finish request (graceful stop)
  TASK_COMMAND_STOP = (1 << 5),  // signals the task to stop
  TASK_COMMAND_FINISH = (1 << 6),  // drains source and resampler transfer buffers before finishing TX
  TASK_FINISHED = (1 << 7),        // upstream drained successfully
  STATE_STARTING = (1 << 10),
  STATE_RUNNING = (1 << 11),
  STATE_STOPPING = (1 << 12),
  STATE_STOPPED = (1 << 13),
  ERR_ESP_NO_MEM = (1 << 19),
  ERR_ESP_NOT_SUPPORTED = (1 << 20),
  ERR_ESP_FAIL = (1 << 21),
  ALL_BITS = 0x00FFFFFF,  // All valid FreeRTOS event group bits
};

void ResamplerSpeaker::dump_config() {
  if (this->passthrough_bits_per_sample_) {
    ESP_LOGCONFIG(TAG,
                  "Resampler Speaker:\n"
                  "  Target Bits Per Sample: passthrough\n"
                  "  Target Sample Rate: %" PRIu32 " Hz",
                  this->target_sample_rate_);
  } else {
    ESP_LOGCONFIG(TAG,
                  "Resampler Speaker:\n"
                  "  Target Bits Per Sample: %" PRIu8 "\n"
                  "  Target Sample Rate: %" PRIu32 " Hz",
                  this->target_bits_per_sample_, this->target_sample_rate_);
  }
}

void ResamplerSpeaker::setup() {
  this->event_group_ = xEventGroupCreate();
  if (this->event_group_ == nullptr) {
    ESP_LOGE(TAG, "Failed to create event group");
    this->mark_failed();
    return;
  }

  this->output_speaker_->add_audio_output_callback([this](uint32_t new_frames, int64_t write_timestamp) {
    if (this->audio_stream_info_.get_sample_rate() != this->target_stream_info_.get_sample_rate()) {
      // Convert the number of frames from the target sample rate to the source sample rate. Track the remainder to
      // avoid losing frames from integer division truncation.
      const uint64_t numerator = new_frames * this->audio_stream_info_.get_sample_rate() + this->callback_remainder_;
      const uint64_t denominator = this->target_stream_info_.get_sample_rate();
      this->callback_remainder_ = numerator % denominator;
      this->audio_output_callback_(numerator / denominator, write_timestamp);
    } else {
      this->audio_output_callback_(new_frames, write_timestamp);
    }
  });

  // Start with loop disabled since no task is running and no commands are pending
  this->disable_loop();
}

void ResamplerSpeaker::loop() {
  uint32_t event_group_bits = xEventGroupGetBits(this->event_group_);

  // STOP wins immediately, including during graceful drain. START must precede a pending FINISH so EOF
  // arriving before the worker starts cannot be discarded while the speaker is still stopped.
  if (event_group_bits & ResamplingEventGroupBits::COMMAND_STOP) {
    xEventGroupClearBits(this->event_group_, ResamplingEventGroupBits::COMMAND_STOP |
                                                 ResamplingEventGroupBits::COMMAND_START |
                                                 ResamplingEventGroupBits::COMMAND_FINISH);
    if (this->state_ != speaker::STATE_STOPPED) {
      this->waiting_for_output_ = false;
      this->enter_stopping_state_();
    }
  } else {
    if (event_group_bits & ResamplingEventGroupBits::COMMAND_START) {
      if (this->state_ == speaker::STATE_STOPPED) {
        xEventGroupClearBits(this->event_group_, ResamplingEventGroupBits::COMMAND_START);
        this->state_ = speaker::STATE_STARTING;
      } else if (this->state_ == speaker::STATE_RUNNING) {
        xEventGroupClearBits(this->event_group_, ResamplingEventGroupBits::COMMAND_START);
      }
    }
    if (event_group_bits & ResamplingEventGroupBits::COMMAND_FINISH) {
      if (this->state_ == speaker::STATE_RUNNING) {
        xEventGroupClearBits(this->event_group_, ResamplingEventGroupBits::COMMAND_FINISH);
        this->graceful_finish_ = true;
        this->state_ = speaker::STATE_STOPPING;
        this->state_start_ms_ = App.get_loop_component_start_time();
        xEventGroupSetBits(this->event_group_, this->requires_resampling_()
                                                 ? ResamplingEventGroupBits::TASK_COMMAND_FINISH
                                                 : ResamplingEventGroupBits::TASK_FINISHED);
      } else if (this->state_ == speaker::STATE_STOPPED) {
        xEventGroupClearBits(this->event_group_, ResamplingEventGroupBits::COMMAND_FINISH);
      }
      // Retain FINISH throughout startup, including before the worker has published its ring buffer.
    }
  }

  // Re-read bits after command processing (enter_stopping_state_ may have set task bits)
  event_group_bits = xEventGroupGetBits(this->event_group_);

  if (event_group_bits & ResamplingEventGroupBits::STATE_STARTING) {
    ESP_LOGD(TAG, "Starting");
    xEventGroupClearBits(this->event_group_, ResamplingEventGroupBits::STATE_STARTING);
  }

  if (event_group_bits & ResamplingEventGroupBits::ERR_ESP_NO_MEM) {
    this->status_set_error(LOG_STR("Not enough memory"));
    xEventGroupClearBits(this->event_group_, ResamplingEventGroupBits::ERR_ESP_NO_MEM);
    this->enter_stopping_state_();
  }
  if (event_group_bits & ResamplingEventGroupBits::ERR_ESP_NOT_SUPPORTED) {
    this->status_set_error(LOG_STR("Unsupported stream"));
    xEventGroupClearBits(this->event_group_, ResamplingEventGroupBits::ERR_ESP_NOT_SUPPORTED);
    this->enter_stopping_state_();
  }
  if (event_group_bits & ResamplingEventGroupBits::ERR_ESP_FAIL) {
    this->status_set_error(LOG_STR("Resampler failure"));
    xEventGroupClearBits(this->event_group_, ResamplingEventGroupBits::ERR_ESP_FAIL);
    this->enter_stopping_state_();
  }

  // A newly requested run snapshots its own error baseline in start_() below, not the previous run's.
  if (this->state_ != speaker::STATE_STOPPED &&
      !(this->state_ == speaker::STATE_STARTING && !this->waiting_for_output_) &&
      (this->state_ != speaker::STATE_STOPPING || this->graceful_finish_) &&
      this->output_error_generation_callback_ != nullptr &&
      this->output_error_generation_callback_() != this->output_error_generation_start_) {
    this->enter_stopping_state_();
  }

  if (event_group_bits & ResamplingEventGroupBits::TASK_FINISHED) {
    xEventGroupClearBits(this->event_group_, ResamplingEventGroupBits::TASK_FINISHED);
    if (this->graceful_finish_) {
      this->upstream_drained_ = true;
      this->output_speaker_->finish();
    }
  }

  if (event_group_bits & ResamplingEventGroupBits::STATE_RUNNING) {
    ESP_LOGV(TAG, "Started");
    this->status_clear_error();
    xEventGroupClearBits(this->event_group_, ResamplingEventGroupBits::STATE_RUNNING);
  }
  if (event_group_bits & ResamplingEventGroupBits::STATE_STOPPING) {
    ESP_LOGV(TAG, "Stopping");
    xEventGroupClearBits(this->event_group_, ResamplingEventGroupBits::STATE_STOPPING);
  }
  // Retries on a subsequent loop if the task is still running on the other core
  if ((event_group_bits & ResamplingEventGroupBits::STATE_STOPPED) && this->task_.deallocate()) {
    ESP_LOGD(TAG, "Stopped");
    xEventGroupClearBits(this->event_group_, ResamplingEventGroupBits::STATE_STOPPED |
                                                 ResamplingEventGroupBits::TASK_COMMAND_STOP |
                                                 ResamplingEventGroupBits::TASK_COMMAND_FINISH);
  }

  switch (this->state_) {
    case speaker::STATE_STARTING: {
      if (!this->waiting_for_output_) {
        esp_err_t err = this->start_();
        if (err == ESP_OK) {
          this->callback_remainder_ = 0;  // reset callback remainder
          this->status_clear_error();
          this->waiting_for_output_ = true;
          this->state_start_ms_ = App.get_loop_component_start_time();
        } else {
          this->set_start_error_(err);
          this->waiting_for_output_ = false;
          this->enter_stopping_state_();
        }
      } else {
        if (this->output_speaker_->is_running()) {
          this->state_ = speaker::STATE_RUNNING;
          this->waiting_for_output_ = false;
        } else if ((App.get_loop_component_start_time() - this->state_start_ms_) > STATE_TRANSITION_TIMEOUT_MS) {
          // Timed out waiting for the output speaker to start
          this->waiting_for_output_ = false;
          this->enter_stopping_state_();
        }
      }
      break;
    }
    case speaker::STATE_RUNNING:
      if (this->output_speaker_->is_stopped()) {
        this->enter_stopping_state_();
      }
      break;
    case speaker::STATE_STOPPING: {
      if ((this->output_speaker_->get_pause_state()) ||
          ((App.get_loop_component_start_time() - this->state_start_ms_) > STATE_TRANSITION_TIMEOUT_MS)) {
        // If output speaker is paused or stopping timeout exceeded, force stop
        this->enter_stopping_state_();
      }

      if (this->output_speaker_->is_stopped() && !this->task_.is_created()) {
        // Only transition to stopped state once the output speaker and resampler task are fully stopped
        if (this->graceful_finish_ && this->upstream_drained_ && this->playback_accepted_.load() &&
            !this->output_speaker_->has_buffered_data() && this->output_error_generation_callback_ != nullptr &&
            this->output_error_generation_callback_() == this->output_error_generation_start_) {
          this->completed_playback_generation_.store(this->playback_generation_.load());
        }
        this->waiting_for_output_ = false;
        this->state_ = speaker::STATE_STOPPED;
      }
      break;
    }
    case speaker::STATE_STOPPED:
      event_group_bits = xEventGroupGetBits(this->event_group_);
      if (event_group_bits == 0) {
        // No pending events, disable loop to save CPU cycles
        this->disable_loop();
      }
      break;
  }
}

void ResamplerSpeaker::set_start_error_(esp_err_t err) {
  switch (err) {
    case ESP_ERR_NO_MEM:
      this->status_set_error(LOG_STR("Not enough memory"));
      break;
    default:
      this->status_set_error(LOG_STR("Failed to start"));
      break;
  }
}

size_t ResamplerSpeaker::play(const uint8_t *data, size_t length, TickType_t ticks_to_wait) {
  if (length == 0 || this->state_ == speaker::STATE_STOPPING ||
      (xEventGroupGetBits(this->event_group_) & (ResamplingEventGroupBits::COMMAND_STOP |
                                               ResamplingEventGroupBits::COMMAND_FINISH |
                                               ResamplingEventGroupBits::TASK_COMMAND_FINISH))) {
    return 0;
  }
  if (this->is_stopped()) {
    this->start();
  }

  size_t bytes_written = 0;
  if ((this->output_speaker_->is_running()) && (!this->requires_resampling_())) {
    bytes_written = this->output_speaker_->play(data, length, ticks_to_wait);
  } else {
    std::shared_ptr<ring_buffer::RingBuffer> temp_ring_buffer = this->ring_buffer_.lock();
    if (temp_ring_buffer != nullptr) {
      // Only write to the ring buffer if the reference is valid
      bytes_written = temp_ring_buffer->write_without_replacement(data, length, ticks_to_wait);
    } else {
      // Delay to avoid repeatedly hammering while waiting for the speaker to start
      vTaskDelay(ticks_to_wait);
    }
  }

  if (bytes_written > 0 && !this->playback_accepted_.exchange(true)) {
    this->playback_generation_.fetch_add(1);
  }

  return bytes_written;
}

void ResamplerSpeaker::send_command_(uint32_t command_bit, bool wake_loop) {
  this->enable_loop_soon_any_context();
  uint32_t event_bits = xEventGroupGetBits(this->event_group_);
  if (!(event_bits & command_bit)) {
    xEventGroupSetBits(this->event_group_, command_bit);
    if (wake_loop) {
      App.wake_loop_threadsafe();
    }
  }
}

void ResamplerSpeaker::start() { this->send_command_(ResamplingEventGroupBits::COMMAND_START, true); }

esp_err_t ResamplerSpeaker::start_() {
  this->playback_accepted_.store(false);
  this->graceful_finish_ = false;
  this->upstream_drained_ = false;
  this->output_error_generation_start_ =
      this->output_error_generation_callback_ != nullptr ? this->output_error_generation_callback_() : 0;
  // In passthrough mode, the output keeps the input's bits per sample so only the sample rate is resampled.
  const uint8_t target_bits_per_sample = this->passthrough_bits_per_sample_
                                             ? this->audio_stream_info_.get_bits_per_sample()
                                             : this->target_bits_per_sample_;
  this->target_stream_info_ = audio::AudioStreamInfo(target_bits_per_sample, this->audio_stream_info_.get_channels(),
                                                     this->target_sample_rate_);

  this->output_speaker_->set_audio_stream_info(this->target_stream_info_);
  this->output_speaker_->start();

  if (this->requires_resampling_()) {
    // Start the resampler task to handle converting sample rates
    if (!this->task_.create(resample_task, "resampler", TASK_STACK_SIZE, (void *) this, RESAMPLER_TASK_PRIORITY,
                            this->task_stack_in_psram_)) {
      return ESP_ERR_NO_MEM;
    }
  }

  return ESP_OK;
}

void ResamplerSpeaker::stop() { this->send_command_(ResamplingEventGroupBits::COMMAND_STOP); }

void ResamplerSpeaker::enter_stopping_state_() {
  this->graceful_finish_ = false;
  this->state_ = speaker::STATE_STOPPING;
  this->state_start_ms_ = App.get_loop_component_start_time();
  if (this->task_.is_created()) {
    xEventGroupSetBits(this->event_group_, ResamplingEventGroupBits::TASK_COMMAND_STOP);
  }
  this->output_speaker_->stop();
}

void ResamplerSpeaker::finish() { this->send_command_(ResamplingEventGroupBits::COMMAND_FINISH); }

bool ResamplerSpeaker::has_buffered_data() const {
  bool has_ring_buffer_data = false;
  if (this->requires_resampling_()) {
    std::shared_ptr<ring_buffer::RingBuffer> temp_ring_buffer = this->ring_buffer_.lock();
    if (temp_ring_buffer != nullptr) {
      has_ring_buffer_data = (temp_ring_buffer->available() > 0);
    }
  }
  return (has_ring_buffer_data || this->output_speaker_->has_buffered_data());
}

void ResamplerSpeaker::set_mute_state(bool mute_state) {
  this->mute_state_ = mute_state;
  this->output_speaker_->set_mute_state(mute_state);
}

void ResamplerSpeaker::set_volume(float volume) {
  this->volume_ = volume;
  this->output_speaker_->set_volume(volume);
}

bool ResamplerSpeaker::requires_resampling_() const {
  if (this->audio_stream_info_.get_sample_rate() != this->target_sample_rate_) {
    return true;
  }
  // In passthrough mode the bits per sample always matches the input, so it never forces resampling.
  return !this->passthrough_bits_per_sample_ &&
         (this->audio_stream_info_.get_bits_per_sample() != this->target_bits_per_sample_);
}

void ResamplerSpeaker::resample_task(void *params) {
  ResamplerSpeaker *this_resampler = static_cast<ResamplerSpeaker *>(params);

  xEventGroupSetBits(this_resampler->event_group_, ResamplingEventGroupBits::STATE_STARTING);

  {  // Ensure C++ objects fall out of scope for proper cleanup before stopping the task
    std::unique_ptr<audio::AudioResampler> resampler = make_unique<audio::AudioResampler>(
        this_resampler->audio_stream_info_.ms_to_bytes(TRANSFER_BUFFER_DURATION_MS),
        this_resampler->target_stream_info_.ms_to_bytes(TRANSFER_BUFFER_DURATION_MS));

    esp_err_t err = resampler->start(this_resampler->audio_stream_info_, this_resampler->target_stream_info_,
                                     this_resampler->taps_, this_resampler->filters_);

    if (err == ESP_OK) {
      std::shared_ptr<ring_buffer::RingBuffer> temp_ring_buffer = ring_buffer::RingBuffer::create(
          this_resampler->audio_stream_info_.ms_to_bytes(this_resampler->buffer_duration_ms_));

      if (temp_ring_buffer == nullptr) {
        err = ESP_ERR_NO_MEM;
      } else {
        this_resampler->ring_buffer_ = temp_ring_buffer;
        err = resampler->add_source(this_resampler->ring_buffer_);

        this_resampler->output_speaker_->set_audio_stream_info(this_resampler->target_stream_info_);
        if (err == ESP_OK) {
          err = resampler->add_sink(this_resampler->output_speaker_);
        }
      }
    }

    if (err == ESP_OK) {
      xEventGroupSetBits(this_resampler->event_group_, ResamplingEventGroupBits::STATE_RUNNING);
    } else if (err == ESP_ERR_NO_MEM) {
      xEventGroupSetBits(this_resampler->event_group_, ResamplingEventGroupBits::ERR_ESP_NO_MEM);
    } else if (err == ESP_ERR_NOT_SUPPORTED) {
      xEventGroupSetBits(this_resampler->event_group_, ResamplingEventGroupBits::ERR_ESP_NOT_SUPPORTED);
    } else {
      xEventGroupSetBits(this_resampler->event_group_, ResamplingEventGroupBits::ERR_ESP_FAIL);
    }

    while (err == ESP_OK) {
      uint32_t event_bits = xEventGroupGetBits(this_resampler->event_group_);

      if (event_bits & ResamplingEventGroupBits::TASK_COMMAND_STOP) {
        break;
      }

      // EOF drains both the ring buffer and AudioResampler's pending output before TX sees finish().
      int32_t ms_differential = 0;
      const bool finish_requested = event_bits & ResamplingEventGroupBits::TASK_COMMAND_FINISH;
      audio::AudioResamplerState resampler_state = resampler->resample(finish_requested, &ms_differential);

      if (resampler_state == audio::AudioResamplerState::FINISHED) {
        if (finish_requested) {
          xEventGroupSetBits(this_resampler->event_group_, ResamplingEventGroupBits::TASK_FINISHED);
        }
        break;
      } else if (resampler_state == audio::AudioResamplerState::FAILED) {
        xEventGroupSetBits(this_resampler->event_group_, ResamplingEventGroupBits::ERR_ESP_FAIL);
        break;
      }
    }

    xEventGroupSetBits(this_resampler->event_group_, ResamplingEventGroupBits::STATE_STOPPING);
  }

  xEventGroupSetBits(this_resampler->event_group_, ResamplingEventGroupBits::STATE_STOPPED);

  vTaskSuspend(nullptr);  // Suspend this task indefinitely until the loop method deletes it
}

}  // namespace esphome::resampler

#endif
