"""Guards the boundary between the front-end-agnostic core and the front ends.

The core modules must stay importable by a front end that is not the Textual
TUI — a voice-only or display-based client should be able to drive a Hermes
session without pulling in a terminal UI framework. These tests fail loudly the
first time a convenient `textual` import creeps into a core module.
"""

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

CORE_MODULES = [
    "attachments",
    "audio",
    "client",
    "config",
    "mic",
    "session",
    "shell",
]


@pytest.mark.parametrize("module", CORE_MODULES)
def test_core_module_does_not_import_a_ui_framework(module):
    # A subprocess per module: importing them in-process would let one module's
    # imports mask another's, and the TUI is already imported by other tests.
    probe = (
        f"import sys, importlib; importlib.import_module({module!r});"
        "leaked = sorted(m for m in sys.modules"
        " if m == 'textual' or m.startswith('textual.'));"
        "print(','.join(leaked))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "", (
        f"{module}.py pulled in Textual: {result.stdout.strip()}. "
        "Core modules must stay usable by a non-terminal front end."
    )


def test_session_orchestration_lives_outside_the_tui_module():
    import session

    assert session.HermesSession.__module__ == "session"
    assert session.SessionProtocol.__module__ == "session"


def test_app_consumes_the_shared_session_rather_than_defining_it():
    import app

    # app.py may re-export these for convenience, but must not own them.
    assert app.HermesSession.__module__ == "session"
    assert app.SessionProtocol.__module__ == "session"
