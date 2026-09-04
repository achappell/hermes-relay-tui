"""Local full-duplex speech detection stays entirely on the client."""

import threading

import numpy as np

from voice import BargeInListener


def _frame(level: int, samples: int = 20):
    return np.full((samples, 1), level, dtype="int16")


def test_speech_activity_interrupts_promptly_then_returns_local_stt_text(tmp_path):
    started = threading.Event()
    completed = threading.Event()
    seen = []

    def transcribe(wav_path, *, model=None):
        seen.append((wav_path, model))
        return {"success": True, "transcript": "  what about Dawn soap?  "}

    listener = BargeInListener(
        on_speech_start=started.set,
        on_transcript=lambda text: (seen.append(text), completed.set()),
        transcribe_fn=transcribe,
        sample_rate=100,
        min_speech_duration=0.2,
        silence_duration=0.2,
        max_seconds=2.0,
        model="tiny",
        temp_dir=tmp_path,
    )
    listener.start()
    listener.activate()

    try:
        listener.submit(_frame(1200))
        listener.submit(_frame(1200))
        assert started.wait(1.0)

        listener.submit(_frame(0))
        listener.submit(_frame(0))
        assert completed.wait(1.0)

        assert seen[-1] == "what about Dawn soap?"
        assert seen[0][1] == "tiny"
    finally:
        listener.stop()


def test_silence_never_starts_a_barge_capture():
    started = []
    completed = []
    listener = BargeInListener(
        on_speech_start=lambda: started.append(True),
        on_transcript=completed.append,
        sample_rate=100,
        min_speech_duration=0.2,
        silence_duration=0.2,
    )
    listener.start()
    listener.activate()

    try:
        for _ in range(4):
            listener.submit(_frame(0))
        assert not started
        assert not completed
    finally:
        listener.stop()


def test_short_room_noise_does_not_start_a_barge_capture():
    started = threading.Event()
    listener = BargeInListener(
        on_speech_start=started.set,
        on_transcript=lambda text: None,
        sample_rate=100,
        silence_duration=0.2,
    )
    listener.start()
    listener.activate()

    try:
        for _ in range(4):
            listener.submit(_frame(1200, samples=10))
        assert not started.wait(0.1)

        listener.submit(_frame(1200, samples=10))
        assert started.wait(1.0)
    finally:
        listener.stop()


def test_cancelling_an_utterance_drops_its_local_transcript():
    started = threading.Event()
    completed = []
    listener = BargeInListener(
        on_speech_start=started.set,
        on_transcript=completed.append,
        transcribe_fn=lambda wav_path, *, model=None: {
            "success": True,
            "transcript": "stop",
        },
        sample_rate=100,
        min_speech_duration=0.2,
        silence_duration=0.2,
    )
    listener.start()
    listener.activate()

    try:
        listener.submit(_frame(1200))
        listener.submit(_frame(1200))
        assert started.wait(1.0)
        listener.cancel_capture()
        listener.submit(_frame(0))
        listener.submit(_frame(0))
        assert not completed
    finally:
        listener.stop()
