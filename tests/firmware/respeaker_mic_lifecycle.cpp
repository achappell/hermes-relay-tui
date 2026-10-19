#include "respeaker_mic_stubs.h"
#include <cassert>

#define protected public
#include "firmware/respeaker-lite/components/i2s_audio/microphone/i2s_audio_microphone.cpp"
#undef protected

using namespace esphome::i2s_audio;

static void expect_calls(std::initializer_list<const char *> wanted) {
  assert(driver.calls.size() == wanted.size());
  size_t index = 0;
  for (const char *name : wanted) assert(driver.calls[index++] == name);
}

int main() {
  I2SAudioComponent parent;
  assert(parent.get_port() == 0);
  parent.set_port(1);
  I2SAudioMicrophone mic;
  mic.set_parent(&parent);
  assert(mic.i2s_role_ == 0 && mic.slot_mode_ == I2S_SLOT_MODE_MONO);
  assert(mic.std_slot_mask_ == I2S_STD_SLOT_BOTH && mic.slot_bit_width_ == I2S_SLOT_BIT_WIDTH_AUTO);
  assert(mic.sample_rate_ == 16000 && !mic.use_apll_ && mic.mclk_multiple_ == I2S_MCLK_MULTIPLE_256);
  mic.set_slot_mode(I2S_SLOT_MODE_STEREO);
  mic.set_slot_bit_width(32);
  mic.set_sample_rate(48000);

  assert(mic.rx_handle_ == nullptr && !mic.locked_driver_ && !mic.channel_enabled_);
  assert(!mic.correct_dc_offset_);
  auto pins = parent.get_pin_config();
  assert(pins.mclk == -1 && pins.bclk == -1 && pins.ws == -1 && pins.dout == -1 && pins.din == -1);
  assert(!pins.invert_flags.mclk_inv && !pins.invert_flags.bclk_inv && !pins.invert_flags.ws_inv);
  assert(parent.get_port() == 1);
  mic.stop_driver_();
  expect_calls({});

  driver.busy = true;
  assert(!mic.start_driver_());
  mic.stop_driver_();
  expect_calls({"lock"});
  assert(driver.locks == 0 && driver.unlocks == 0);
  driver.busy = false;

  for (int stage = 0; stage < 3; ++stage) {
    driver.reset_trace();
    driver.allocation_error = stage == 0 ? ESP_FAIL : 0;
    driver.init_error = stage == 1 ? ESP_FAIL : 0;
    driver.enable_error = stage == 2 ? ESP_FAIL : 0;
    assert(!mic.start_driver_());
    assert(mic.rx_handle_ == nullptr && !mic.locked_driver_ && !mic.channel_enabled_);
    assert(driver.locks == 1 && driver.unlocks == 1);
    auto failure = mic.get_driver_failure();
    assert(failure.error == ESP_FAIL);
    assert(failure.operation == (stage == 0 ? RxDriverOperation::ALLOCATE : stage == 1 ? RxDriverOperation::INITIALIZE : RxDriverOperation::ENABLE));
    if (stage == 0) expect_calls({"lock", "allocate", "unlock"});
    if (stage == 1) expect_calls({"lock", "allocate", "initialize", "delete", "unlock"});
    if (stage == 2) expect_calls({"lock", "allocate", "initialize", "enable", "delete", "unlock"});
    const auto count = driver.calls.size();
    mic.stop_driver_();
    assert(driver.calls.size() == count);
    driver.allocation_error = driver.init_error = driver.enable_error = 0;
    driver.reset_trace();
    assert(mic.start_driver_());
    assert(mic.get_driver_failure().operation == RxDriverOperation::NONE);
    assert(mic.channel_enabled_ && mic.rx_handle_ != nullptr && mic.locked_driver_);
    mic.stop_driver_();
    expect_calls({"lock", "allocate", "initialize", "enable", "disable", "delete", "unlock"});
    assert(driver.locks == driver.unlocks);
  }

  // A driver may return an allocated handle together with an allocation error.
  driver.reset_trace();
  driver.allocation_error = ESP_FAIL;
  driver.allocation_returns_handle = true;
  assert(!mic.start_driver_());
  expect_calls({"lock", "allocate", "delete", "unlock"});
  assert(mic.rx_handle_ == nullptr);
  driver.allocation_error = 0;
  driver.allocation_returns_handle = false;

  for (int failure_mode = 1; failure_mode <= 3; ++failure_mode) {
    driver.reset_trace();
    assert(mic.start_driver_());
    const auto old_handle = mic.rx_handle_;
    driver.disable_error = failure_mode & 1 ? ESP_FAIL : 0;
    driver.delete_error = failure_mode & 2 ? ESP_FAIL : 0;
    mic.stop_driver_();
    expect_calls({"lock", "allocate", "initialize", "enable", "disable", "delete", "unlock"});
    assert(mic.rx_handle_ == nullptr && !mic.channel_enabled_ && !mic.locked_driver_);
    assert(driver.unlocks == 1);
    for (auto operation : {"disable", "delete"}) {
      bool expected = std::string(operation) == "disable" ? driver.disable_error != 0 : driver.delete_error != 0;
      bool logged = false;
      for (const auto &line : driver.logs)
        logged |= line.find(operation) != std::string::npos && line.find("RX port=1") != std::string::npos;
      assert(logged == expected);
    }
    const auto count = driver.calls.size();
    mic.stop_driver_();
    assert(driver.calls.size() == count);
    driver.disable_error = driver.delete_error = 0;
    assert(mic.start_driver_());
    assert(mic.rx_handle_ != old_handle);
    mic.stop_driver_();
    assert(driver.locks == driver.unlocks);
  }

  // A created task may not have published TASK_RUNNING yet. The component
  // loop must not attempt another start and tear the live driver out from it.
  driver.reset_trace();
  assert(mic.start_driver_());
  driver.calls.clear();
  mic.task_handle_ = reinterpret_cast<void *>(1);
  mic.state_ = esphome::microphone::STATE_STARTING;
  mic.loop();
  expect_calls({});
  assert(mic.locked_driver_ && mic.channel_enabled_);
  mic.task_handle_ = nullptr;
  mic.state_ = esphome::microphone::STATE_STOPPED;
  mic.stop_driver_();

  driver.reset_trace();
  driver.init_error = ESP_FAIL;
  driver.delete_error = ESP_ERR_TIMEOUT;
  assert(!mic.start_driver_());
  assert(mic.get_driver_failure().operation == RxDriverOperation::INITIALIZE);
  assert(mic.get_driver_failure().error == ESP_FAIL);
  expect_calls({"lock", "allocate", "initialize", "delete", "unlock"});
  assert(!mic.locked_driver_ && mic.rx_handle_ == nullptr);
  std::puts("actual microphone source: allocate/init/enable/disable/delete faults, cleanup, retry and defaults PASS");
}
