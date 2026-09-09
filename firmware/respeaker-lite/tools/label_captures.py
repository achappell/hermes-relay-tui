#!/usr/bin/env python3
"""Correlates collect_samples.py's manifest against tools/receiver.py's raw
captures and converts each matched capture into a labeled 16kHz mono
16-bit WAV clip, ready for microWakeWord's training pipeline.

The raw captures are the exact 32-bit stereo 16kHz stream pcm_capture.h
taps directly off the microphone (before micro_wake_word's own
MicrophoneSource does channel selection, gain, and bit-depth conversion).
This script replicates that conversion in Python -- channel select (index
1, matching this board's `channels: 1` config and this project's README
table "ch1 fits micro_wake_word"), Q31->Q25, x gain_factor, clamp, Q25->Q31,
take the top 16 bits -- byte-for-byte matching
esphome/components/microphone/microphone_source.cpp's process_audio_(),
so the resulting WAV is genuinely what the wake-word model would have
seen, not an approximation. (Session 10's cross-validation used this same
replication, done inline in that session rather than as a committed tool.)

Correlation: a capture's filename embeds recv_time (roughly when the 2s
capture window closed and upload began). A manifest entry is matched to
the capture whose recv_time falls within
[play_start - MATCH_SLACK_BEFORE, play_end + MATCH_SLACK_AFTER] --
generous on both sides since the interval-tick capture/upload cycle isn't
tightly synchronized to playback.

Usage:
    python3 label_captures.py --captures-dir /tmp/pcm_captures \\
        --manifest /tmp/pcm_captures/manifest/manifest.jsonl \\
        --out-dir /tmp/training_clips
"""
import argparse
import glob
import json
import os
import re
import struct
import wave

SOURCE_CHANNELS = 2
CHANNEL_INDEX = 1  # matches respeaker-lite.yaml's micro_wake_word: microphone: channels: 1
GAIN_FACTOR = 4  # matches respeaker-lite.yaml's gain_factor: 4
SOURCE_SAMPLE_RATE = 16000
Q25_MAX = (1 << 25) - 1
Q25_MIN = ~Q25_MAX

MATCH_SLACK_BEFORE = 2.5  # seconds before play_start a matching capture's recv_time may fall
MATCH_SLACK_AFTER = 1.5  # seconds after play_end a matching capture's recv_time may fall

FILENAME_RE = re.compile(r"^(\d+)_seq\d+\.raw$")


def process_frame_sample(raw4: bytes) -> int:
    """Replicates MicrophoneSource::process_audio_'s per-sample conversion
    for one 4-byte little-endian 32-bit source sample. Returns a signed
    16-bit int."""
    sample = int.from_bytes(raw4, byteorder="little", signed=True)  # Q31
    sample >>= 6  # Q31 -> Q25 (arithmetic shift; Python's >> is arithmetic for negatives, matching GCC on ESP32)
    sample *= GAIN_FACTOR  # Q25
    sample = max(Q25_MIN, min(Q25_MAX, sample))  # clamp
    sample *= 1 << 6  # Q25 -> Q31
    sample32 = sample & 0xFFFFFFFF
    out16 = (sample32 >> 16) & 0xFFFF  # top 16 bits, matching pack_q31_as_audio_sample's 2-byte case
    if out16 >= 0x8000:
        out16 -= 0x10000
    return out16


def convert_capture_to_wav(raw_path: str, wav_path: str) -> int:
    with open(raw_path, "rb") as f:
        data = f.read()
    frame_size = SOURCE_CHANNELS * 4
    n_frames = len(data) // frame_size
    samples = bytearray()
    for i in range(n_frames):
        base = i * frame_size + CHANNEL_INDEX * 4
        out16 = process_frame_sample(data[base:base + 4])
        samples += struct.pack("<h", out16)

    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SOURCE_SAMPLE_RATE)
        wf.writeframes(bytes(samples))
    return n_frames


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--captures-dir", default="/tmp/pcm_captures")
    parser.add_argument("--manifest", default="/tmp/pcm_captures/manifest/manifest.jsonl")
    parser.add_argument("--out-dir", default="/tmp/training_clips")
    parser.add_argument("--include-unmatched-as-negative", action="store_true",
                         help="also export every capture NOT matched to a manifest entry as a negative/background "
                              "clip -- real ambient audio through this exact hardware, free (no extra playback "
                              "needed), and a better domain match than a generic downloaded noise corpus")
    parser.add_argument("--session-mode", action="store_true",
                         help="label by broad *_session.json windows (from collect_samples.py --session-tag) "
                              "instead of per-utterance manifest correlation -- every capture whose recv_time "
                              "falls inside a session's [start, end] gets that session's label. Far more forgiving "
                              "of the ~2s capture window's imprecise timing relative to any single utterance, "
                              "since a session floods the phrase back-to-back so almost any capture in-window "
                              "contains it.")
    parser.add_argument("--session-slack", type=float, default=1.0,
                         help="seconds of slack added on both ends of a session window (session-mode only)")
    args = parser.parse_args()

    captures = []
    for path in glob.glob(os.path.join(args.captures_dir, "*.raw")):
        m = FILENAME_RE.match(os.path.basename(path))
        if not m:
            continue
        recv_time = int(m.group(1))
        size = os.path.getsize(path)
        # A full 2s window is 256000 bytes; skip obviously-truncated
        # captures (an abandoned upload mid-sample) -- too short to be a
        # useful training clip and would just add noise.
        if size < 256000 * 0.5:
            continue
        captures.append((recv_time, path))
    captures.sort()

    os.makedirs(os.path.join(args.out_dir, "positive"), exist_ok=True)
    os.makedirs(os.path.join(args.out_dir, "negative"), exist_ok=True)

    if args.session_mode:
        sessions = []
        for path in glob.glob(os.path.join(args.captures_dir, "*_session.json")):
            with open(path) as f:
                sessions.append(json.load(f))
        sessions.sort(key=lambda s: s["start"])

        matched_captures = set()
        n_positive = 0
        n_negative = 0
        for recv_time, path in captures:
            label = None
            for s in sessions:
                if s["start"] - args.session_slack <= recv_time <= s["end"] + args.session_slack:
                    label = s["label"]
                    break
            if label is None:
                continue
            matched_captures.add(path)
            out_name = f"{label}_{os.path.basename(path).replace('.raw', '')}.wav"
            out_path = os.path.join(args.out_dir, label, out_name)
            n_frames = convert_capture_to_wav(path, out_path)
            if label == "positive":
                n_positive += 1
            else:
                n_negative += 1
            print(f"{label}: {os.path.basename(path)} -> {os.path.basename(out_path)} ({n_frames} samples)")

        n_bonus_negative = 0
        if args.include_unmatched_as_negative:
            for recv_time, path in captures:
                if path in matched_captures:
                    continue
                out_name = f"ambient_{recv_time}.wav"
                out_path = os.path.join(args.out_dir, "negative", out_name)
                convert_capture_to_wav(path, out_path)
                n_bonus_negative += 1

        print()
        print(f"Session mode: {len(sessions)} session(s), {n_positive} positive, {n_negative} negative clips.")
        if args.include_unmatched_as_negative:
            print(f"Plus {n_bonus_negative} bonus ambient negatives (outside any session). "
                  f"Total negative: {n_negative + n_bonus_negative}.")
        print(f"Clips written to {args.out_dir}/positive/ and {args.out_dir}/negative/")
        return

    manifest_entries = []
    with open(args.manifest) as f:
        for line in f:
            line = line.strip()
            if line:
                manifest_entries.append(json.loads(line))

    matched_captures = set()
    n_positive = 0
    n_negative = 0
    n_unmatched_manifest = 0

    for idx, entry in enumerate(manifest_entries):
        window_start = entry["play_start"] - MATCH_SLACK_BEFORE
        window_end = entry["play_end"] + MATCH_SLACK_AFTER
        best = None
        for recv_time, path in captures:
            if path in matched_captures:
                continue
            if window_start <= recv_time <= window_end:
                # Prefer the capture closest to play_end (the window most
                # likely to have actually captured the tail of speech).
                if best is None or abs(recv_time - entry["play_end"]) < abs(best[0] - entry["play_end"]):
                    best = (recv_time, path)
        if best is None:
            n_unmatched_manifest += 1
            continue
        matched_captures.add(best[1])
        label_dir = "positive" if entry["label"] == "positive" else "negative"
        out_name = f"{label_dir}_{idx:04d}_{entry['voice']}_{entry['rate']}wpm.wav"
        out_path = os.path.join(args.out_dir, label_dir, out_name)
        n_frames = convert_capture_to_wav(best[1], out_path)
        if label_dir == "positive":
            n_positive += 1
        else:
            n_negative += 1
        print(f"{label_dir}: \"{entry['text']}\" ({entry['voice']}, {entry['rate']}wpm) -> "
              f"{os.path.basename(out_path)} ({n_frames} samples)")

    n_bonus_negative = 0
    if args.include_unmatched_as_negative:
        for recv_time, path in captures:
            if path in matched_captures:
                continue
            out_name = f"ambient_{recv_time}.wav"
            out_path = os.path.join(args.out_dir, "negative", out_name)
            convert_capture_to_wav(path, out_path)
            n_bonus_negative += 1
        print(f"Exported {n_bonus_negative} additional ambient/background captures as negatives "
              f"(unmatched to any manifest entry -- real audio through this hardware, not synthetic).")

    print()
    print(f"Matched {n_positive} positive, {n_negative} negative clips "
          f"({n_unmatched_manifest} manifest entries had no matching capture).")
    if args.include_unmatched_as_negative:
        print(f"Plus {n_bonus_negative} bonus ambient negatives. Total negative: {n_negative + n_bonus_negative}.")
    print(f"Clips written to {args.out_dir}/positive/ and {args.out_dir}/negative/")


if __name__ == "__main__":
    main()
