import sys
import threading
import types

from mic import prepare_local_stt, wrap_recorder
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
    from tqdm import tqdm

    prepare_local_stt()
    assert isinstance(tqdm.get_lock(), type(threading.RLock()))


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
