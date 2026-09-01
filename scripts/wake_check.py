#!/usr/bin/env python3
"""Live wake-word meter — the tool for the kitchen validation.

Opens the real microphone through the real capture path and prints a running
score, so you can watch what the detector actually hears in the room it has to
work in. Nothing is sent to Hermes and no turn is captured: this only answers
"does it hear me, and does it hear things that are not me".

Two questions it exists to answer:

  1. Detection rate — say the phrase ten times, count the fires.
  2. False positives — leave it running with the extractor fan, the tap, and
     the radio going, and see whether the count moves when nobody speaks.

    python scripts/wake_check.py
    python scripts/wake_check.py --seconds 600 --quiet   # a ten-minute noise soak
    python scripts/wake_check.py --threshold 0.5 --confirmation-frames 2

Ctrl-C to stop; it prints a summary.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

# Run straight from a checkout without installing first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import wake  # noqa: E402
from voice import AudioRecorder  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=None, help="path to a .onnx model (default: the bundled hey_hermes)")
    parser.add_argument("--threshold", type=float, default=wake.DEFAULT_THRESHOLD)
    parser.add_argument(
        "--confirmation-frames", type=int, default=wake.DEFAULT_CONFIRMATION_FRAMES
    )
    parser.add_argument(
        "--refractory-seconds", type=float, default=wake.DEFAULT_COOLDOWN_SECONDS
    )
    parser.add_argument("--quiet", action="store_true", help="print only detections")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="synthesize the phrase with macOS `say` and score it, no microphone involved",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="stop after this long and print the summary (default: run until Ctrl-C)",
    )
    return parser


class _ScoreTap:
    """Wraps the engine so the meter can show what the detector saw.

    Tracks the input level as well as the score, because "it did not hear the
    phrase" and "it is not hearing anything" look identical otherwise, and only
    one of them is a wake-word problem.
    """

    def __init__(self, engine) -> None:
        self._engine = engine
        self.last = 0.0
        self.peak = 0.0
        self.frames = 0
        self.level = 0
        self.level_peak = 0

    def score(self, frame):
        try:
            self.level = int(abs(frame).max())
            self.level_peak = max(self.level_peak, self.level)
        except Exception:
            pass
        value = self._engine.score(frame)
        self.last = value
        self.peak = max(self.peak, value)
        self.frames += 1
        return value


def _meter(value: float, width: int = 40) -> str:
    filled = min(int(value * width), width)
    return "#" * filled + "." * (width - filled)



def self_test(args) -> int:
    """Score a synthesized utterance, so the detector can be proven without a
    microphone, a voice, or a quiet room.

    This separates two failures that look identical from the outside: the
    software not working, and the room or the microphone not reaching it.
    """
    import shutil
    import subprocess
    import tempfile
    import wave

    import numpy as np

    if not (shutil.which("say") and shutil.which("afconvert")):
        print("--self-test needs macOS `say` and `afconvert`.", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        aiff = f"{tmp}/phrase.aiff"
        wav = f"{tmp}/phrase.wav"
        print("Synthesizing 'hey hermes'...")
        subprocess.run(["say", "-o", aiff, "hey hermes"], check=True)
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav],
            check=True,
        )
        with wave.open(wav) as handle:
            spoken = np.frombuffer(handle.readframes(handle.getnframes()), dtype="int16")

    # Real capture never stops at the end of a phrase, and openWakeWord needs
    # its rolling buffer to fill. A clip that ends on the last syllable scores
    # far lower than the same words in a live stream.
    silence = np.zeros(16000, dtype="int16")
    audio = np.concatenate([silence, spoken, silence])

    print("Loading the wake-word model...")
    try:
        engine = wake.load_openwakeword_engine(args.model)
    except wake.MissingWakeDependency as error:
        print(f"\n{error}\n", file=sys.stderr)
        return 1

    detector = wake.WakeDetector(
        engine,
        threshold=args.threshold,
        confirmation_frames=args.confirmation_frames,
        cooldown_seconds=args.refractory_seconds,
    )

    fires = 0
    scores = []
    for offset in range(0, len(audio) - 1280, 1280):
        chunk = audio[offset : offset + 1280]
        scores.append(engine.score(chunk))

    detector_engine_calls = 0

    class _Replay:
        def score(self, frame):
            nonlocal detector_engine_calls
            value = scores[detector_engine_calls]
            detector_engine_calls += 1
            return value

    replay = wake.WakeDetector(
        _Replay(),
        threshold=args.threshold,
        confirmation_frames=args.confirmation_frames,
        cooldown_seconds=args.refractory_seconds,
    )
    for _ in scores:
        if replay.feed(None):
            fires += 1

    peak = max(scores)
    over = sum(1 for value in scores if value >= args.threshold)

    print()
    print(f"chunks scored           {len(scores)}")
    print(f"highest score           {peak:.3f}   (threshold {args.threshold})")
    print(f"frames over threshold   {over}   (need {args.confirmation_frames} in a row)")
    print(f"detections              {fires}")
    print()
    if fires:
        print("The detector works. If the live meter never fires for you, the")
        print("problem is between your voice and the microphone, not in the")
        print("software: check the input device named by a normal run, and that")
        print("the terminal has microphone permission.")
        return 0

    print("The detector did not fire on a clean synthesized phrase. That is a")
    print("software problem, not a microphone one.")
    return 1


def main() -> int:
    args = build_parser().parse_args()

    if args.self_test:
        return self_test(args)

    try:
        import sounddevice as sd

        device = sd.query_devices(kind="input")
        print(f"Input device: {device['name']}  "
              f"({device['max_input_channels']}ch @ {device['default_samplerate']:.0f}Hz)")
    except Exception as error:
        print(f"Could not query the input device: {error}")

    print("Loading the wake-word model (this takes a moment on first run)...")
    try:
        engine = wake.load_openwakeword_engine(args.model)
    except wake.MissingWakeDependency as error:
        print(f"\n{error}\n", file=sys.stderr)
        return 1

    tap = _ScoreTap(engine)
    detector = wake.WakeDetector(
        tap,
        threshold=args.threshold,
        confirmation_frames=args.confirmation_frames,
        cooldown_seconds=args.refractory_seconds,
    )

    detections: list[float] = []
    started = time.monotonic()

    def on_wake() -> None:
        detections.append(time.monotonic() - started)
        print(f"\r*** WAKE  #{len(detections)}  at {detections[-1]:6.1f}s  "
              f"score {tap.last:.3f}{' ' * 20}")

    def on_silent_stream() -> None:
        print("\r!!! The microphone is open but sending pure silence. "
              f"Check the input device.{' ' * 10}")

    listener = wake.WakeListener(
        detector,
        on_wake=on_wake,
        on_silent_stream=on_silent_stream,
        chunker=wake.FrameChunker(),
        peak_of=lambda frame: int(abs(frame).max()) if len(frame) else 0,
        silence_monitor=wake.SilentStreamMonitor(),
    )

    # Start the worker before opening the stream. The other order lets frames
    # pile into a bounded queue with nothing draining it, and the whole warm-up
    # is dropped audio.
    listener.start()

    recorder = AudioRecorder()
    recorder.set_frame_observer(listener.submit)
    recorder.open_for_listening()

    phrase = args.model or "hey hermes"
    print(f"\nListening for: {phrase}")
    print(f"threshold={args.threshold}  confirmation_frames={args.confirmation_frames}  "
          f"refractory={args.refractory_seconds}s")
    print("Say the phrase. Ctrl-C to stop.\n")

    stop = threading.Event()
    deadline = started + args.seconds if args.seconds else None
    try:
        while not stop.wait(0.1):
            if deadline is not None and time.monotonic() >= deadline:
                break
            if not args.quiet:
                elapsed = time.monotonic() - started
                print(
                    f"\r{elapsed:6.1f}s  mic [{_meter(min(tap.level / 3000, 1.0), 12)}] "
                    f"{tap.level:5d}   wake [{_meter(tap.last, 24)}] {tap.last:.3f}  "
                    f"peak {tap.peak:.3f}  fires {len(detections)}",
                    end="",
                    flush=True,
                )
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        recorder.shutdown()

    elapsed = time.monotonic() - started
    print("\n\n--- summary ---")
    print(f"listened            {elapsed:.1f}s")
    print(f"frames scored       {tap.frames}")
    print(f"detections          {len(detections)}")
    print(f"loudest input seen  {tap.level_peak}  (silence is under 10)")
    print(f"highest score seen  {tap.peak:.3f}  (threshold {args.threshold})")
    if listener.dropped_frames:
        print(f"dropped frames      {listener.dropped_frames}")
    if detections:
        print("fired at            " + ", ".join(f"{t:.1f}s" for t in detections))
    else:
        print()
        if tap.level_peak < 10:
            print("The microphone delivered silence. This is not a wake-word")
            print("problem - nothing reached the detector at all. Check that the")
            print("terminal has microphone permission in System Settings >")
            print("Privacy & Security > Microphone, and that the input device")
            print("named above is the one you are speaking into.")
        elif tap.peak < 0.05:
            print("Audio arrived but the phrase never registered at all. If you")
            print("were saying it, the model may not recognise your delivery -")
            print("try 'hey hermes' as two clear words, or lower --threshold to")
            print("see whether it registers at all.")
        elif tap.peak < args.threshold:
            print(f"It heard something: peak {tap.peak:.3f} against a threshold of")
            print(f"{args.threshold}. That is a near miss rather than a failure.")
            print("Re-run with --threshold set just under that peak to confirm.")
        else:
            print("The score crossed the threshold but no detection fired, so")
            print(f"--wake-confirmation-frames ({args.confirmation_frames}) rejected it")
            print("as too brief. Try a lower value.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
