"""Regression tests for the blocking microphone reader.

The microphone must not run application Python from PortAudio's real-time
callback boundary.  The barge-in path made that callback busy enough to
crash inside CoreAudio on macOS.
"""

import threading
import time
import types

import numpy as np

import voice


class _FakeInputStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.frames = []
        self._frame_ready = threading.Event()
        self.started = False
        self.stopped = False
        self.closed = False
        self.reading = threading.Event()
        self.stop_calls_while_reading = 0

    def start(self):
        self.started = True

    @property
    def read_available(self):
        return len(self.frames) * 4

    def read(self, frames):  # noqa: ARG002 - mirrors sounddevice.InputStream
        self.reading.set()
        while not self.frames:
            self._frame_ready.wait(0.01)
            if self.stopped:
                self.reading.clear()
                raise RuntimeError("stream stopped")
        frame = self.frames.pop(0)
        if not self.frames:
            self._frame_ready.clear()
        self.reading.clear()
        return frame, False

    def push(self, frame):
        self.frames.append(frame)
        self._frame_ready.set()

    def stop(self):
        if self.reading.is_set():
            self.stop_calls_while_reading += 1
        self.stopped = True
        self._frame_ready.set()

    def close(self):
        self.closed = True


def _fake_audio(monkeypatch):
    streams = []

    def input_stream(**kwargs):
        stream = _FakeInputStream(**kwargs)
        streams.append(stream)
        return stream

    fake_sounddevice = types.SimpleNamespace(
        InputStream=input_stream,
        default=types.SimpleNamespace(samplerate=16000),
    )
    monkeypatch.setattr(voice, "_import_audio", lambda: (fake_sounddevice, np))
    return streams


def _wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


def test_microphone_uses_a_blocking_reader_instead_of_a_portaudio_callback(monkeypatch):
    streams = _fake_audio(monkeypatch)
    recorder = voice.AudioRecorder()
    seen = []
    recorder.set_frame_observer(seen.append)

    recorder.open_for_listening()
    stream = streams[0]

    assert "callback" not in stream.kwargs
    stream.push(np.ones((4, 1), dtype="int16"))
    _wait_for(lambda: len(seen) == 1)

    recorder.shutdown()

    assert stream.started is True
    assert stream.stop_calls_while_reading == 0
    assert stream.closed is True
    assert recorder._reader_thread is None
