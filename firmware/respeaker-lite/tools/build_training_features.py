#!/usr/bin/env python3
"""Builds microWakeWord ragged-mmap spectrogram features and a
training_parameters.yaml from label_captures.py's output
(default /tmp/training_clips/{positive,negative}), then prints the
model_train_eval invocation to actually train.

Session 16 (story 3) used this to prove microWakeWord's training
pipeline runs end-to-end against 30 real clips collected the same
session over the serial-dump path. No augmentation, no HuggingFace
negative-dataset downloads -- deliberately the minimum viable run to
prove the mechanics work, not to produce a good model (30 samples is
far too few for that; see microWakeWord's own README.md caveat that
even a "real" run of its basic_training_notebook.ipynb "will most
likely not be usable"). Scaling up the dataset (more collection
sessions, real ambient negative data) is the natural next step before
trusting any model this produces.

Bypasses microwakeword.audio.clips.Clips entirely: that class loads
audio via HuggingFace `datasets`' Audio feature, which in the venv this
was built against requires torchcodec, which requires an ffmpeg
matching one of a few pinned major versions -- homebrew's installed
ffmpeg (9.x) was too new and there was no clean way to get a compatible
one without more dependency wrangling than this warranted. We already
have clean 16kHz mono 16-bit PCM WAVs (label_captures.py's output), so
this loads them directly with the stdlib `wave` module and calls
generate_features_for_clip() itself -- the actual feature-extraction
function Clips would have called anyway.

Setup used in session 16 (a training venv is NOT part of this repo):
    python3.12 -m venv /tmp/mww_train_venv
    /tmp/mww_train_venv/bin/pip install -e /tmp/microwakeword_src  # clone of kahrendt/microWakeWord
    /tmp/mww_train_venv/bin/pip install tensorboard  # model_train_eval needs it for tf.summary, not pulled in by default

Usage:
    /tmp/mww_train_venv/bin/python3 build_training_features.py
    # then, from the printed train_dir:
    cd <train_dir's parent> && /tmp/mww_train_venv/bin/python3 -m microwakeword.model_train_eval \\
        --training_config=training_parameters.yaml --train 1 --restore_checkpoint 0 \\
        --test_tflite_streaming_quantized 1 \\
        mixednet --residual_connection "0,0,0,0"
    # NOTE: mixednet's own --residual_connection default ("0,0,0,0,0", 5 values) doesn't
    # match its other list hyperparameters' length (4) and raises ValueError without this
    # override -- an upstream default mismatch, not specific to this script's config.
"""
import os
import random
import shutil
import sys
import wave

import numpy as np

sys.path.insert(0, "/tmp/microwakeword_src")

from mmap_ninja.ragged import RaggedMmap
from microwakeword.audio.audio_utils import generate_features_for_clip

WORK_DIR = "/tmp/mww_smoke_run"
POSITIVE_CLIPS_DIR = "/tmp/training_clips/positive"
NEGATIVE_CLIPS_DIR = "/tmp/training_clips/negative"

# Pre-generated ambient-negative spectrogram datasets from
# https://huggingface.co/datasets/kahrendt/microwakeword (real background
# noise, dinner-party conversation, and non-wake speech) -- optional. If
# present, wired into training_parameters.yaml so false-accept-rate
# evaluation uses real ambient audio instead of coming back nan/nan for
# lack of any negative set beyond our own 15 clips. Not committed to this
# repo (several GB); download per microWakeWord's own notebook (cell 8) or
# this project's story doc session 16 notes.
NEGATIVE_DATASETS_DIR = "/tmp/negative_datasets"
HF_NEGATIVE_FEATURES = [
    # (subdir, sampling_weight, truncation_strategy)
    ("speech", 10.0, "random"),
    ("dinner_party", 10.0, "random"),
    ("no_speech", 5.0, "random"),
    ("dinner_party_eval", 0.0, "split"),  # validation/testing only
]


def load_wav_int16(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        n = w.getnframes()
        data = w.readframes(n)
    return np.frombuffer(data, dtype=np.int16)


def split_paths(paths: list[str], seed: int = 10):
    rng = random.Random(seed)
    shuffled = paths[:]
    rng.shuffle(shuffled)
    n = len(shuffled)
    n_test = max(1, round(n * 0.1))
    n_val = max(1, round(n * 0.1))
    n_train = n - n_test - n_val
    return {
        "training": shuffled[:n_train],
        "validation": shuffled[n_train:n_train + n_val],
        "testing": shuffled[n_train + n_val:],
    }


def build_features(clips_dir: str, label: str):
    out_root = os.path.join(WORK_DIR, "features", label)
    if os.path.exists(out_root):
        shutil.rmtree(out_root)
    os.makedirs(out_root, exist_ok=True)

    paths = sorted(
        os.path.join(clips_dir, f) for f in os.listdir(clips_dir) if f.endswith(".wav")
    )
    splits = split_paths(paths)

    for split_dir, split_paths_list in splits.items():
        out_dir = os.path.join(out_root, split_dir)
        os.makedirs(out_dir, exist_ok=True)

        def gen():
            for p in split_paths_list:
                samples = load_wav_int16(p)
                yield generate_features_for_clip(samples, step_ms=10)

        RaggedMmap.from_generator(
            out_dir=os.path.join(out_dir, "wakeword_mmap"),
            sample_generator=gen(),
            batch_size=50,
            verbose=True,
        )
        print(f"{label}/{split_dir}: {len(split_paths_list)} clips -> ragged mmap")

    return out_root


def main():
    os.makedirs(WORK_DIR, exist_ok=True)

    positive_features = build_features(POSITIVE_CLIPS_DIR, "positive")
    negative_features = build_features(NEGATIVE_CLIPS_DIR, "negative")

    import yaml

    features = [
        {
            "features_dir": positive_features,
            "sampling_weight": 2.0,
            "penalty_weight": 1.0,
            "truth": True,
            "truncation_strategy": "truncate_start",
            "type": "mmap",
        },
        {
            "features_dir": negative_features,
            "sampling_weight": 2.0,
            "penalty_weight": 1.0,
            "truth": False,
            "truncation_strategy": "random",
            "type": "mmap",
        },
    ]

    for subdir, sampling_weight, truncation_strategy in HF_NEGATIVE_FEATURES:
        feature_dir = os.path.join(NEGATIVE_DATASETS_DIR, subdir)
        if os.path.isdir(feature_dir):
            features.append({
                "features_dir": feature_dir,
                "sampling_weight": sampling_weight,
                "penalty_weight": 1.0,
                "truth": False,
                "truncation_strategy": truncation_strategy,
                "type": "mmap",
            })
            print(f"Wired in HF negative dataset: {feature_dir}")
        else:
            print(f"Skipping HF negative dataset (not found): {feature_dir}")

    config = {
        "window_step_ms": 10,
        "train_dir": os.path.join(WORK_DIR, "trained_model"),
        "features": features,
        "training_steps": [2000],
        "positive_class_weight": [1],
        "negative_class_weight": [20],
        "learning_rates": [0.001],
        "batch_size": 128,
        "time_mask_max_size": [0],
        "time_mask_count": [0],
        "freq_mask_max_size": [0],
        "freq_mask_count": [0],
        "eval_step_interval": 200,
        "clip_duration_ms": 1500,
        "target_minimization": 0.9,
        "minimization_metric": None,
        "maximization_metric": "average_viable_recall",
    }

    config_path = os.path.join(WORK_DIR, "training_parameters.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    print(f"\nWrote config to {config_path}")
    print("Feature generation complete. Next: run model_train_eval.")


if __name__ == "__main__":
    main()
