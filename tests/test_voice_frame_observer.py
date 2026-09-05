"""The wake-word listener taps AudioRecorder's persistent stream rather than
opening a second device handle, so these tests pin the tap's contract."""

import voice


class _FakeFrame:
    def __init__(self, tag):
        self.tag = tag


def _recorder():
    return voice.AudioRecorder()


def test_observer_receives_frames_while_idle():
    recorder = _recorder()
    seen = []
    recorder.set_frame_observer(seen.append)

    recorder._dispatch_frame(_FakeFrame("a"))

    assert [frame.tag for frame in seen] == ["a"]


def test_observer_is_silent_while_recording():
    """During capture the frames belong to the recorder. The listener is deaf
    by construction, which is what stops a detection stacking a second turn."""
    recorder = _recorder()
    seen = []
    recorder.set_frame_observer(seen.append)
    recorder._recording = True

    recorder._dispatch_frame(_FakeFrame("a"))

    assert seen == []


def test_observer_can_be_cleared():
    recorder = _recorder()
    seen = []
    recorder.set_frame_observer(seen.append)
    recorder.set_frame_observer(None)

    recorder._dispatch_frame(_FakeFrame("a"))

    assert seen == []


def test_multiple_observers_can_share_the_persistent_input_stream():
    recorder = _recorder()
    first = []
    second = []
    recorder.set_frame_observer(first.append)
    recorder.add_frame_observer(second.append)

    recorder._dispatch_frame(_FakeFrame("a"))

    assert [frame.tag for frame in first] == ["a"]
    assert [frame.tag for frame in second] == ["a"]


def test_an_observer_can_be_removed_without_affecting_the_other_tap():
    recorder = _recorder()
    first = []
    second = []
    recorder.set_frame_observer(first.append)
    recorder.add_frame_observer(second.append)
    recorder.remove_frame_observer(second.append)

    recorder._dispatch_frame(_FakeFrame("a"))

    assert [frame.tag for frame in first] == ["a"]
    assert second == []


def test_observer_exception_never_escapes_the_audio_callback():
    """A raising observer must not kill the audio thread and stop recording
    for the whole process."""
    recorder = _recorder()

    def boom(frame):
        raise RuntimeError("detector exploded")

    recorder.set_frame_observer(boom)

    recorder._dispatch_frame(_FakeFrame("a"))  # must not raise


def test_open_for_listening_starts_the_stream_without_recording(monkeypatch):
    """The appliance needs the microphone open while idle, which is the one
    thing push-to-talk never had to do."""
    recorder = _recorder()
    opened = []
    monkeypatch.setattr(recorder, "_ensure_stream", lambda: opened.append(True))

    recorder.open_for_listening()

    assert opened == [True]
    assert recorder.is_recording is False


def test_the_observer_receives_a_copy_not_the_live_buffer():
    """sounddevice recycles indata between callbacks. The listener queues
    frames and scores them on another thread, so handing over the live buffer
    means scoring whatever PortAudio has since overwritten it with - audio
    that measures loud and recognises as nothing."""
    import numpy as np

    recorder = _recorder()
    seen = []
    recorder.set_frame_observer(seen.append)

    live = np.ones((4, 1), dtype="int16")
    recorder._dispatch_frame(live)
    live[:] = 999  # PortAudio reusing its buffer

    assert seen[0].tolist() == [[1], [1], [1], [1]]
