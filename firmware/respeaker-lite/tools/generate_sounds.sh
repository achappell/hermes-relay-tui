#!/usr/bin/env bash
# Generate the short local status tones embedded by ESPHome's audio_file
# component. Keep the generated WAVs committed: firmware builds need the
# files, while this script keeps the tone design reproducible.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
output_dir="${script_dir}/../sounds"
ffmpeg_bin="${FFMPEG:-ffmpeg}"

mkdir -p "${output_dir}"

render_pair() {
  local output_name="$1"
  local first_hz="$2"
  local second_hz="$3"
  local tone_duration="$4"
  local fade_end="$5"

  "${ffmpeg_bin}" -hide_banner -loglevel error -y \
    -f lavfi -i "sine=frequency=${first_hz}:duration=${tone_duration}:sample_rate=16000" \
    -f lavfi -i "sine=frequency=${second_hz}:duration=${tone_duration}:sample_rate=16000" \
    -filter_complex \
      "[0:a]volume=0.25,afade=t=in:st=0:d=0.005,afade=t=out:st=${fade_end}:d=0.005[a];[1:a]volume=0.25,afade=t=in:st=0:d=0.005,afade=t=out:st=${fade_end}:d=0.005[b];[a][b]concat=n=2:v=0:a=1,aresample=16000" \
    -ac 1 -ar 16000 -c:a pcm_s16le "${output_dir}/${output_name}"
}

# Descending means unavailable; ascending means heard. The refusal is a
# deliberate longer status sound. The wake acknowledgement is only 80ms so
# the capture hand-off can happen quickly; playing a 360ms acknowledgement
# before opening the mic was enough to make the user start speaking into the
# AEC-suppressed interval on hardware.
render_pair refused.wav 660 440 0.18 0.17
render_pair heard.wav 440 660 0.04 0.03
