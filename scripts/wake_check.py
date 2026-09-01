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
        "--seconds",
        type=float,
        default=None,
        help="stop after this long and print the summary (default: run until Ctrl-C)",
    )
    return parser


class _ScoreTap:
    """Wraps the engine so the meter can show what the detector saw."""

    def __init__(self, engine) -> None:
        self._engine = engine
        self.last = 0.0
        self.peak = 0.0
        self.frames = 0

    def score(self, frame):
        value = self._engine.score(frame)
        self.last = value
        self.peak = max(self.peak, value)
        self.frames += 1
        return value


def _meter(score: float, width: int = 40) -> str:
    filled = min(int(score * width), width)
    return "#" * filled + "." * (width - filled)


def main() -> int:
    args = build_parser().parse_args()

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
                    f"\r{elapsed:6.1f}s  [{_meter(tap.last)}]  "
                    f"now {tap.last:.3f}  peak {tap.peak:.3f}  "
                    f"fires {len(detections)}",
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
    print(f"highest score seen  {tap.peak:.3f}  (threshold {args.threshold})")
    if listener.dropped_frames:
        print(f"dropped frames      {listener.dropped_frames}")
    if detections:
        print("fired at            " + ", ".join(f"{t:.1f}s" for t in detections))
    else:
        print("\nNothing fired. If you were speaking the phrase, the peak score")
        print("above tells you whether it was close: a peak well under the")
        print("threshold means the detector never heard it, while a peak just")
        print("over means confirmation-frames rejected it as too brief.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
