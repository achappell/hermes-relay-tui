#!/usr/bin/env python3
"""Playback-and-capture orchestration for story 3's custom wake-word
training data (the "step 2" the story's RESUME HERE section flagged as
never attempted across sessions 11-14).

Generates "hey jarvis" utterances with macOS `say` across several natural
voices/rates, plays each through this Mac's speaker (positioned at the
physical Puck) via `afplay`, and logs each playback's wall-clock start/end
to a manifest (manifest.jsonl in --out-dir). label_captures.py then
correlates that manifest against the receiver's saved raw captures
(tools/receiver.py's <out_dir>) by timestamp to build labeled training
clips -- this script does not touch the raw captures itself.

Usage:
    python3 collect_samples.py --count 40 --out-dir /tmp/pcm_captures/manifest
    python3 collect_samples.py --count 40 --negative --out-dir /tmp/pcm_captures/manifest
"""
import argparse
import json
import os
import subprocess
import tempfile
import time

POSITIVE_PHRASE = "hey jarvis"

# Deliberately excludes macOS's novelty voices (Albert, Bells, Zarvox, etc.)
# -- they don't sound like natural speech and would just add noise to a
# wake-word dataset's positive class.
VOICES = ["Samantha", "Daniel", "Karen", "Moira", "Fred", "Ralph", "Kathy"]
RATES = [160, 180, 200, 220]  # words per minute; natural human range

# Negative/background phrases: short, everyday sentences that are NOT the
# wake phrase, to give the model real spoken-but-wrong-word examples
# rather than only silence/ambient noise as negatives.
NEGATIVE_PHRASES = [
    "what time is it",
    "turn on the lights",
    "how's the weather today",
    "play some music",
    "set a timer for five minutes",
    "good morning",
    "thank you very much",
    "can you help me with this",
    "I'm going to the store",
    "close the garage door",
]


def synth_and_play(text: str, voice: str, rate: int, tmpdir: str) -> tuple[float, float]:
    wav_path = os.path.join(tmpdir, f"utt_{int(time.time() * 1000)}.aiff")
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", wav_path, text], check=True)
    start = time.time()
    subprocess.run(["afplay", wav_path], check=True)
    end = time.time()
    os.remove(wav_path)
    return start, end


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--out-dir", default="/tmp/pcm_captures/manifest")
    parser.add_argument("--negative", action="store_true", help="generate negative/background phrases instead")
    parser.add_argument("--gap-seconds", type=float, default=3.0, help="pause between utterances")
    parser.add_argument("--session-tag", default=None,
                         help="if set, also writes a *_session.json with {tag, label, start, end} spanning the "
                              "whole run -- label_captures.py's --session-mode uses this broad window instead of "
                              "per-utterance correlation, which is far more forgiving of the ~2s capture window's "
                              "imprecise timing relative to any single utterance")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    manifest_path = os.path.join(args.out_dir, "manifest.jsonl")

    print(f"Collecting {args.count} {'negative' if args.negative else 'positive'} samples, "
          f"manifest -> {manifest_path}")
    print("Make sure the Puck is powered on, near this Mac's speaker, and the receiver is running.")

    session_start = time.time()
    with tempfile.TemporaryDirectory() as tmpdir, open(manifest_path, "a") as manifest:
        for i in range(args.count):
            voice = VOICES[i % len(VOICES)]
            rate = RATES[i % len(RATES)]
            if args.negative:
                text = NEGATIVE_PHRASES[i % len(NEGATIVE_PHRASES)]
                label = "negative"
            else:
                text = POSITIVE_PHRASE
                label = "positive"

            start, end = synth_and_play(text, voice, rate, tmpdir)
            record = {
                "label": label,
                "text": text,
                "voice": voice,
                "rate": rate,
                "play_start": start,
                "play_end": end,
            }
            manifest.write(json.dumps(record) + "\n")
            manifest.flush()
            print(f"[{i + 1}/{args.count}] {label}: \"{text}\" ({voice}, {rate}wpm) "
                  f"{start:.2f}-{end:.2f}")
            time.sleep(args.gap_seconds)

    session_end = time.time()
    if args.session_tag:
        session_path = os.path.join(args.out_dir, f"{args.session_tag}_session.json")
        with open(session_path, "w") as f:
            json.dump({
                "tag": args.session_tag,
                "label": "negative" if args.negative else "positive",
                "start": session_start,
                "end": session_end,
            }, f)
        print(f"Session window written to {session_path}: {session_start:.2f}-{session_end:.2f}")

    print(f"Done. {args.count} utterances logged to {manifest_path}.")


if __name__ == "__main__":
    main()
