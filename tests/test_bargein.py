"""Local full-duplex speech detection stays entirely on the client."""

import threading

import numpy as np

from voice import BargeInListener, is_tts_echo


def _frame(level: int, samples: int = 20):
    return np.full((samples, 1), level, dtype="int16")


def test_tts_echo_guard_matches_long_fragments_but_not_short_interjections():
    assert is_tts_echo(
        "the dishes are ready",
        "I checked the kitchen and the dishes are ready for dinner tonight.",
    )
    assert not is_tts_echo("yes", "I checked the kitchen and the dishes are ready")
    assert not is_tts_echo("what about Dawn soap", "The answer is unrelated.")


def test_speech_activity_notifies_promptly_then_returns_local_stt_text(tmp_path):
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

        assert started.is_set()
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
        min_speech_duration=0.45,
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


def test_windowed_speech_detection_tolerates_a_dip_inside_a_word(tmp_path):
    started = threading.Event()
    listener = BargeInListener(
        on_speech_start=started.set,
        on_transcript=lambda text: None,
        is_playing=lambda: False,
        sample_rate=100,
        silence_threshold=50,
        calibration_duration=0.4,
        min_speech_duration=0.5,
        silence_duration=0.2,
        temp_dir=tmp_path,
    )
    listener.start()
    listener.activate()

    try:
        for _ in range(4):
            listener.submit(_frame(20, samples=10))
        for level in (180, 180, 0, 180, 180):
            listener.submit(_frame(level, samples=10))

        assert started.wait(1.0)
    finally:
        listener.stop()


def test_playback_grace_and_floor_ignore_speaker_bleed_until_speech(tmp_path):
    started = threading.Event()
    playing = False

    def is_playing():
        return playing

    listener = BargeInListener(
        on_speech_start=started.set,
        on_transcript=lambda text: None,
        is_playing=is_playing,
        sample_rate=100,
        silence_threshold=50,
        calibration_duration=0.4,
        playback_grace_duration=0.5,
        min_speech_duration=0.3,
        silence_duration=0.2,
        temp_dir=tmp_path,
    )
    listener.start()
    listener.activate()

    try:
        for _ in range(4):
            listener.submit(_frame(20, samples=10))

        playing = True
        for _ in range(8):
            listener.submit(_frame(1300, samples=10))
        assert not started.wait(0.1)

        for _ in range(3):
            listener.submit(_frame(1800, samples=10))
        assert started.wait(1.0)
    finally:
        listener.stop()


def test_loud_room_noise_does_not_make_speech_undetectable(tmp_path):
    started = threading.Event()
    calibration_processed = threading.Event()
    playing = False
    playback_checks = 0

    def is_playing():
        nonlocal playback_checks
        playback_checks += 1
        if playback_checks == 4:
            calibration_processed.set()
        return playing

    listener = BargeInListener(
        on_speech_start=started.set,
        on_transcript=lambda text: None,
        is_playing=is_playing,
        sample_rate=100,
        silence_threshold=200,
        calibration_duration=0.4,
        playback_grace_duration=0.5,
        min_speech_duration=0.3,
        silence_duration=0.2,
        temp_dir=tmp_path,
    )
    listener.start()
    listener.activate()

    try:
        for _ in range(4):
            listener.submit(_frame(1800, samples=10))
        assert calibration_processed.wait(1.0)

        playing = True
        for _ in range(20):
            listener.submit(_frame(1800, samples=10))
        assert not started.wait(0.1)
        for _ in range(3):
            listener.submit(_frame(3200, samples=10))

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
