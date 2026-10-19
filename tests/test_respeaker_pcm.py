"""Execute the production ReSpeaker PCM boundary; fixtures contain synthetic audio only."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "firmware/respeaker-lite/components"
HEADER_DIR = COMPONENTS / "i2s_audio/microphone"
FIXTURE = ROOT / "tests/firmware/respeaker_pcm_fixture.json"


def test_signed_stereo_conversion_is_fragmentation_independent(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("native C++ compiler unavailable")
    fixture = json.loads(FIXTURE.read_text())
    rows = lambda key: ",".join("{" + ",".join(map(str, row)) + "}" for row in fixture[key])
    source = tmp_path / "pcm.cpp"
    source.write_text(textwrap.dedent(r'''
        #include "respeaker_pcm.h"
        #include <algorithm>
        #include <array>
        #include <cassert>
        #include <vector>
        using namespace esphome::i2s_audio::respeaker_pcm;
        const int32_t input[][2] = {INPUT_ROWS};
        const int32_t expected[][2] = {EXPECTED_ROWS};
        void pack(std::vector<uint8_t> &bytes, int32_t sample) {
          uint32_t word = static_cast<uint32_t>(sample);
          for (int i = 0; i < 4; ++i) bytes.push_back(uint8_t(word >> (8 * i)));
        }
        int main() {
          std::vector<uint8_t> bytes, wanted;
          for (const auto &frame : input) for (auto sample : frame) pack(bytes, sample);
          for (const auto &frame : expected) for (auto sample : frame) pack(wanted, sample);
          assert(INPUT_RATE == 48000 && OUTPUT_RATE == 16000);
          assert(bytes.size() / 8 == 3 * wanted.size() / 8);
          assert(double(bytes.size() / 8) / INPUT_RATE == double(wanted.size() / 8) / OUTPUT_RATE);
          // All byte boundaries, including reads smaller than one stereo word.
          for (size_t chunk = 1; chunk <= bytes.size(); ++chunk) {
            Decimator converter;
            std::vector<uint8_t> result;
            for (size_t offset = 0; offset < bytes.size(); offset += chunk) {
              const size_t count = std::min(chunk, bytes.size() - offset);
              std::vector<uint8_t> out(Decimator::output_capacity(count) + 1, 0xA5);
              const size_t emitted = converter.convert(bytes.data() + offset, count, out.data());
              assert(emitted <= Decimator::output_capacity(count));
              assert(out.back() == 0xA5);
              result.insert(result.end(), out.begin(), out.begin() + emitted);
            }
            assert(result == wanted);
          }
          uint32_t peaks[2]{};
          for (size_t i = 0; i < wanted.size(); i += 8) {
            for (size_t ch = 0; ch < 2; ++ch) {
              assert(decode_s32le(wanted.data() + i + 4 * ch) == expected[i / 8][ch]);
              peaks[ch] = std::max(peaks[ch], magnitude_s32le(wanted.data() + i + 4 * ch));
            }
          }
          assert(peaks[0] == 2147483648u && peaks[1] == 2147483648u);
          // An unfinished frame is not emitted; a fresh task starts at frame zero.
          Decimator old_stream;
          std::array<uint8_t, 16> out{};
          assert(old_stream.convert(bytes.data(), 7, out.data()) == 0);
          Decimator fresh_stream;
          assert(fresh_stream.convert(bytes.data(), 8, out.data()) == 8);
          assert(std::equal(out.begin(), out.begin() + 8, wanted.begin()));
          // Exactly one second at board input yields one second at consumer rate.
          Decimator second;
          size_t total = 0;
          std::vector<uint8_t> second_out(Decimator::output_capacity(bytes.size()));
          for (size_t n = 0; n < 4000; ++n)
            total += second.convert(bytes.data(), bytes.size(), second_out.data());
          assert(total / 8 == OUTPUT_RATE);
        }
    ''').replace("INPUT_ROWS", rows("input_s32le_stereo")).replace("EXPECTED_ROWS", rows("expected_s32le_stereo")))
    binary = tmp_path / "pcm"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsanitize=undefined,address", "-fno-sanitize-recover=all", "-I", str(HEADER_DIR), str(source), "-o", str(binary)], check=True, capture_output=True, text=True)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def test_real_esphome_format_validator_rejects_unsupported_formats():
    firmware_python = Path(os.environ.get("ESPHOME_PYTHON", ROOT / "venv-firmware/bin/python"))
    if not firmware_python.is_file():
        pytest.skip("firmware ESPHome environment is not installed")
    script = r'''
import sys
sys.path.insert(0, sys.argv[1])
from i2s_audio.microphone import _validate_respeaker_format
from esphome.config_validation import Invalid
valid = dict(adc_type="external", pdm=False, sample_rate=48000, bits_per_sample=32,
             channel="stereo", i2s_mode="secondary", correct_dc_offset=False)
assert _validate_respeaker_format(valid.copy()) == valid
cases = dict(adc_type=["internal"], pdm=[True], sample_rate=[16000, 44100, 96000],
             bits_per_sample=[8, 16, 24], channel=["left", "right", "mono"],
             i2s_mode=["primary"], correct_dc_offset=[True])
count = 0
for key, values in cases.items():
    for value in values:
        bad = dict(valid, **{key: value})
        try:
            _validate_respeaker_format(bad)
        except Invalid as error:
            assert "ReSpeaker microphone supports only" in str(error)
            assert key in str(error)
            count += 1
        else:
            raise AssertionError((key, value))
assert count == 13
print("accepted proven format; rejected 13 unsupported combinations")
'''
    subprocess.run([str(firmware_python), "-c", script, str(COMPONENTS)], check=True, capture_output=True, text=True)
