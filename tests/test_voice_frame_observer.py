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


def test_observer_exception_never_escapes_the_audio_callback():
    """A raising observer must not kill the audio thread and stop recording
    for the whole process."""
    recorder = _recorder()

    def boom(frame):
        raise RuntimeError("detector exploded")

    recorder.set_frame_observer(boom)

    recorder._dispatch_frame(_FakeFrame("a"))  # must not raise
