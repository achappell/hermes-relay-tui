"""Microphone capture wrapper for the Hermes streaming TUI.

Ported from hermes-hybrid-tui.py's _load_microphone, unchanged in
behavior beyond a clearer public name.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def load_microphone_class(checkout: Path):
    source = checkout / "scripts" / "voice-session-client.py"
    if not source.exists():
        raise RuntimeError(f"Hermes voice client not found at {source}")
    spec = importlib.util.spec_from_file_location("hermes_voice_session_client", source)
    if not spec or not spec.loader:
        raise RuntimeError(f"Could not load Hermes voice client from {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LocalMicrophone
