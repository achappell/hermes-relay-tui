"""Microphone capture wrapper for the Hermes streaming TUI.

Ported from hermes-hybrid-tui.py's _load_microphone, unchanged in
behavior beyond a clearer public name.
"""

from __future__ import annotations

import importlib.util
import threading
from pathlib import Path


def prepare_local_stt() -> None:
    """Avoid tqdm's multiprocessing lock under Textual's redirected streams."""
    try:
        from tqdm import tqdm
    except ImportError:
        return
    tqdm.set_lock(threading.RLock())


def load_microphone_class(checkout: Path):
    source = checkout / "scripts" / "voice-session-client.py"
    if not source.exists():
        raise RuntimeError(f"Hermes voice client not found at {source}")
    prepare_local_stt()
    spec = importlib.util.spec_from_file_location("hermes_voice_session_client", source)
    if not spec or not spec.loader:
        raise RuntimeError(f"Could not load Hermes voice client from {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LocalMicrophone
