import asyncio
import sys
import threading
import types

import pytest
from textual.app import App
from tqdm import tqdm
from tqdm.std import TqdmDefaultWriteLock

from mic import load_microphone_class, wrap_recorder


def test_missing_voice_client_raises(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        load_microphone_class(tmp_path)


def test_loads_local_microphone_class(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "voice-session-client.py").write_text(
        "class LocalMicrophone:\n"
        "    def __init__(self, **kwargs):\n"
        "        self.kwargs = kwargs\n"
        "    def capture(self):\n"
        "        return 'hello'\n"
        "    def close(self):\n"
        "        pass\n"
    )

    microphone_class = load_microphone_class(tmp_path)
    instance = microphone_class(max_seconds=5.0)
    assert instance.capture() == "hello"


async def test_loading_microphone_prepares_tqdm_for_textual_streams(tmp_path, monkeypatch):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "voice-session-client.py").write_text(
        "from tqdm import tqdm\n"
        "tqdm.get_lock()\n"
        "class LocalMicrophone:\n"
        "    pass\n"
    )

    # Force the first get_lock() in the dynamically loaded module to exercise
    # the multiprocessing path. Under Textual that path rejects stderr's -1
    # fileno; load_microphone_class must pin tqdm to a thread-only lock first.
    monkeypatch.delattr(tqdm, "_lock", raising=False)
    monkeypatch.delattr(TqdmDefaultWriteLock, "mp_lock", raising=False)

    class Probe(App):
        loaded_class = None
        error = None

        async def on_mount(self):
            try:
                self.loaded_class = await asyncio.to_thread(load_microphone_class, tmp_path)
            except Exception as exc:  # captured for the assertion below
                self.error = exc
            self.exit()

    app = Probe()
    async with app.run_test() as pilot:
        await pilot.pause()

    assert app.error is None
    assert app.loaded_class is not None


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
