#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace esphome::i2s_audio::respeaker_pcm {

constexpr size_t FRAME_BYTES = 8;
constexpr uint32_t INPUT_RATE = 48000;
constexpr uint32_t OUTPUT_RATE = 16000;

// Assemble unsigned bytes, then convert without implementation-defined unsigned
// to signed overflow. This also defines INT32_MIN independently of host endian.
inline int32_t decode_s32le(const uint8_t *data) {
  const uint32_t word = uint32_t(data[0]) | (uint32_t(data[1]) << 8) |
                        (uint32_t(data[2]) << 16) | (uint32_t(data[3]) << 24);
  return word <= INT32_MAX ? static_cast<int32_t>(word) : -1 - static_cast<int32_t>(UINT32_MAX - word);
}

inline uint32_t magnitude_s32le(const uint8_t *data) {
  const int32_t sample = decode_s32le(data);
  return sample < 0 ? uint32_t(-(int64_t(sample))) : uint32_t(sample);
}

// Board's proven nearest-frame conversion: retain frames 0,3,6,... without
// filtering or changing the two signed 32-bit little-endian channel words.
// One instance per microphone task keeps read fragmentation out of the format.
class Decimator {
 public:
  static constexpr size_t output_capacity(size_t input_bytes) {
    return ((input_bytes / FRAME_BYTES + 3) / 3) * FRAME_BYTES;
  }

  // Input and output must not overlap. output_capacity(input_bytes) bytes suffice.
  size_t convert(const uint8_t *input, size_t input_bytes, uint8_t *output) {
    size_t written = 0;
    if (this->pending_bytes_ != 0) {
      const size_t needed = FRAME_BYTES - this->pending_bytes_;
      const size_t taken = input_bytes < needed ? input_bytes : needed;
      std::memcpy(this->pending_ + this->pending_bytes_, input, taken);
      this->pending_bytes_ += taken;
      input += taken;
      input_bytes -= taken;
      if (this->pending_bytes_ != FRAME_BYTES)
        return 0;
      if (this->phase_ == 0) {
        std::memcpy(output, this->pending_, FRAME_BYTES);
        written += FRAME_BYTES;
      }
      this->phase_ = (this->phase_ + 1) % 3;
      this->pending_bytes_ = 0;
    }
    while (input_bytes >= FRAME_BYTES) {
      if (this->phase_ == 0) {
        std::memcpy(output + written, input, FRAME_BYTES);
        written += FRAME_BYTES;
      }
      this->phase_ = (this->phase_ + 1) % 3;
      input += FRAME_BYTES;
      input_bytes -= FRAME_BYTES;
    }
    if (input_bytes != 0) {
      std::memcpy(this->pending_, input, input_bytes);
      this->pending_bytes_ = input_bytes;
    }
    return written;
  }

 private:
  uint8_t pending_[FRAME_BYTES]{};
  size_t pending_bytes_{0};
  uint8_t phase_{0};
};

}  // namespace esphome::i2s_audio::respeaker_pcm
