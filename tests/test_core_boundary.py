"""Guards the boundary between the front-end-agnostic core and the front ends.

The core modules must stay importable by a front end that is not the Textual
TUI — a voice-only or display-based client should be able to drive a Hermes
session without pulling in a terminal UI framework. These tests fail loudly the
first time a convenient `textual` import creeps into a core module.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

# Keep this list in step with the "Core and front ends" section of AGENTS.md.
CORE_MODULES = [
    "attachments",
    "audio",
    "client",
    "clipboard",
    "config",
    "diagnostics",
    "handsfree",
    "history",
    "mic",
    "session",
    "shell",
    "wake",
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


def test_documented_core_matches_the_enforced_core():
    """AGENTS.md and this file must not drift apart.

    The documented core list is the one a contributor reads; this list is the
    one CI enforces. If they disagree, the rule is unenforced somewhere.
    """
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    section = agents.split("**Core — must not import a user-interface framework:**")[1]
    section = section.split("**Front-end-specific:**")[0]

    documented = set(re.findall(r"`(\w+)\.py`", section))

    assert documented == set(CORE_MODULES), (
        "AGENTS.md core list and CORE_MODULES disagree: "
        f"documented-only={sorted(documented - set(CORE_MODULES))}, "
        f"enforced-only={sorted(set(CORE_MODULES) - documented)}"
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
