"""Device-selection and cancellation glue around voice.py's local recorder."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator

from voice import LocalMicrophone, create_audio_recorder

__all__ = [
    "LocalMicrophone",
    "prepare_local_stt",
    "input_device_context",
    "wrap_recorder",
    "make_recorder_factory",
    "cancel_microphone",
]

DeviceSelector = int | str | None


def prepare_local_stt() -> None:
    """Avoid tqdm's multiprocessing lock under Textual's redirected streams."""
    try:
        from tqdm import tqdm as base_tqdm
        from tqdm.auto import tqdm as auto_tqdm
    except ImportError:
        return
    lock = threading.RLock()
    base_tqdm.set_lock(lock)
    auto_tqdm.set_lock(lock)


@contextmanager
def input_device_context(device: DeviceSelector) -> Iterator[None]:
    """Temporarily select an input device for the default-based recorder."""
    if device is None:
        yield
        return

    import sounddevice as sd

    previous = sd.default.device
    output_device = previous[1] if isinstance(previous, (tuple, list)) and len(previous) > 1 else None
    sd.default.device = (device, output_device)
    try:
        yield
    finally:
        sd.default.device = previous


class _RecorderProxy:
    """Add device selection and cancellable endpointing to a recorder."""

    def __init__(
        self,
        recorder: Any,
        input_device: DeviceSelector,
        cancel_requested: threading.Event,
    ) -> None:
        object.__setattr__(self, "_recorder", recorder)
        object.__setattr__(self, "_input_device", input_device)
        object.__setattr__(self, "_cancel_requested", cancel_requested)
        object.__setattr__(self, "_on_silence_stop", None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._recorder, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_recorder", "_input_device", "_cancel_requested", "_on_silence_stop"}:
            object.__setattr__(self, name, value)
        else:
            setattr(self._recorder, name, value)

    def start(self, on_silence_stop=None) -> None:
        self._on_silence_stop = on_silence_stop
        if self._cancel_requested.is_set():
            if on_silence_stop is not None:
                on_silence_stop()
            return
        with input_device_context(self._input_device):
            self._recorder.start(on_silence_stop=on_silence_stop)

    def cancel(self) -> None:
        self._cancel_requested.set()
        try:
            self._recorder.cancel()
        finally:
            callback = self._on_silence_stop
            self._on_silence_stop = None
            if callback is not None:
                callback()

    def stop(self) -> Any:
        try:
            return self._recorder.stop()
        finally:
            self._on_silence_stop = None

    def shutdown(self) -> None:
        self._cancel_requested.set()
        try:
            self._recorder.shutdown()
        finally:
            callback = self._on_silence_stop
            self._on_silence_stop = None
            if callback is not None:
                callback()


def wrap_recorder(
    recorder: Any,
    *,
    input_device: DeviceSelector = None,
    cancel_requested: threading.Event | None = None,
) -> Any:
    """Wrap a recorder for local device selection and cancellation."""
    return _RecorderProxy(
        recorder,
        input_device,
        cancel_requested or threading.Event(),
    )


def make_recorder_factory(
    input_device: DeviceSelector,
    cancel_requested: threading.Event,
    recorder: Any = None,
) -> Any:
    """Build the dependency-injected recorder factory used by LocalMicrophone.

    Pass ``recorder`` to capture through an already-open recorder instead of
    opening a second one. The wake-word appliance needs this: its listener
    holds one input stream open for the life of the process, and a second
    stream on the same device is unreliable across platforms.
    """
    def factory() -> Any:
        return wrap_recorder(
            recorder if recorder is not None else create_audio_recorder(),
            input_device=input_device,
            cancel_requested=cancel_requested,
        )

    return factory


def cancel_microphone(microphone: Any) -> None:
    """Cancel a LocalMicrophone capture without blocking the UI."""
    recorder = getattr(microphone, "_recorder", None)
    cancel = getattr(recorder, "cancel", None)
    if callable(cancel):
        cancel()
