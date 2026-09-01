import sys
import threading
import types

from mic import prepare_local_stt, wrap_recorder
import session as session_module
from session import HermesSession
from voice import LocalMicrophone, is_whisper_hallucination


def test_local_microphone_uses_injected_recorder_and_transcriber():
    class FakeRecorder:
        supports_silence_autostop = True

        def start(self, on_silence_stop=None):
            if on_silence_stop is not None:
                on_silence_stop()

        def stop(self):
            return "/tmp/fake.wav"

        def cancel(self):
            pass

    transcribed = {}

    def fake_transcribe(wav_path, model=None):
        transcribed["wav_path"] = wav_path
        transcribed["model"] = model
        return {"success": True, "transcript": "turn on the lights"}

    microphone = LocalMicrophone(
        max_seconds=5.0,
        model="base",
        recorder_factory=FakeRecorder,
        transcribe_fn=fake_transcribe,
        hallucination_fn=lambda text: False,
    )

    assert microphone.capture() == "turn on the lights"
    assert transcribed == {"wav_path": "/tmp/fake.wav", "model": "base"}


def test_local_microphone_filters_hallucinated_transcript():
    class FakeRecorder:
        supports_silence_autostop = True

        def start(self, on_silence_stop=None):
            if on_silence_stop is not None:
                on_silence_stop()

        def stop(self):
            return "/tmp/fake.wav"

        def cancel(self):
            pass

    microphone = LocalMicrophone(
        max_seconds=5.0,
        recorder_factory=FakeRecorder,
        transcribe_fn=lambda wav_path, model=None: {"success": True, "transcript": "thank you"},
    )

    assert microphone.capture() == ""


def test_is_whisper_hallucination_catches_known_phrases_and_silence():
    assert is_whisper_hallucination("") is True
    assert is_whisper_hallucination("thank you.") is True
    assert is_whisper_hallucination("turn off the porch light") is False


def test_prepare_local_stt_pins_tqdm_to_a_thread_lock():
    from tqdm import tqdm as base_tqdm
    from tqdm.auto import tqdm

    prepare_local_stt()
    assert isinstance(base_tqdm.get_lock(), type(threading.RLock()))
    assert isinstance(tqdm.get_lock(), type(threading.RLock()))


def test_session_prepares_tqdm_before_first_model_load(monkeypatch):
    from tqdm.auto import tqdm

    monkeypatch.delattr(tqdm, "_lock", raising=False)

    class TextualStderr:
        def fileno(self):
            return -1

        def isatty(self):
            return False

        def write(self, value):
            pass

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stderr", TextualStderr())

    class FakeMicrophone:
        def __init__(self, **kwargs):
            # This is the lock construction triggered by faster-whisper's
            # first model download. It must not start multiprocessing from a
            # Textual process whose stderr fd is intentionally unavailable.
            self.lock = tqdm.get_lock()

        def capture(self):
            return ""

    monkeypatch.setattr(session_module, "LocalMicrophone", FakeMicrophone)
    args = types.SimpleNamespace(
        mic_max_seconds=15.0,
        mic_silence_duration=3.0,
        mic_silence_threshold=200,
        stt_model=None,
        mic_input_device=None,
    )

    HermesSession(args).capture_voice()


def test_wrapped_recorder_selects_input_device_and_cancellation_wakes_capture(monkeypatch):
    observed = {}
    default = types.SimpleNamespace(device=("default input", "default output"))
    fake_sounddevice = types.SimpleNamespace(default=default)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sounddevice)

    class FakeRecorder:
        supports_silence_autostop = True

        def start(self, on_silence_stop=None):
            observed["device_during_start"] = fake_sounddevice.default.device
            self.callback = on_silence_stop

        def cancel(self):
            observed["cancelled"] = True

    recorder = FakeRecorder()
    proxy = wrap_recorder(recorder, input_device="USB Microphone")
    finished = threading.Event()

    proxy.start(on_silence_stop=finished.set)
    assert observed["device_during_start"] == ("USB Microphone", "default output")
    assert fake_sounddevice.default.device == ("default input", "default output")

    proxy.cancel()

    assert observed["cancelled"] is True
    assert finished.is_set()


def test_a_shared_recorder_is_reused_instead_of_opening_a_second_one():
    """The appliance's wake listener holds one input stream open for the life
    of the process. Capture has to borrow it: two input streams on one device
    is unreliable, and reopening one can hang on macOS CoreAudio."""
    from mic import make_recorder_factory

    shared = object()
    factory = make_recorder_factory(None, threading.Event(), recorder=shared)

    first = factory()
    second = factory()

    assert first._recorder is shared
    assert second._recorder is shared


def test_a_session_captures_through_the_shared_recorder_and_leaves_it_open(monkeypatch):
    """The appliance owns the listening stream; a session that borrows it must
    not shut it down when its connection closes."""
    import asyncio

    built = {}

    class FakeMicrophone:
        def __init__(self, **kwargs):
            built["recorder"] = kwargs["recorder_factory"]()
            self.closed = False

        def capture(self):
            return ""

        def close(self):
            self.closed = True

    monkeypatch.setattr(session_module, "LocalMicrophone", FakeMicrophone)
    args = types.SimpleNamespace(
        mic_max_seconds=15.0,
        mic_silence_duration=3.0,
        mic_silence_threshold=200,
        stt_model=None,
        mic_input_device=None,
    )
    shared = object()
    session = HermesSession(args)
    session.use_shared_recorder(shared)

    session.capture_voice()
    microphone = session.microphone

    assert built["recorder"]._recorder is shared

    asyncio.run(session.close())

    assert microphone.closed is False
    assert session.microphone is None
