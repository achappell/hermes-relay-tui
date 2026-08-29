from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_project_metadata_exposes_the_console_command():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "hermes-streaming-tui"
    assert metadata["project"]["requires-python"] == ">=3.14,<3.15"
    assert metadata["project"]["scripts"]["hermes-streaming-tui"] == "app:main"


def test_homebrew_trial_formula_declares_runtime_boundaries():
    formula = (ROOT / "packaging/homebrew/hermes-streaming-tui.rb").read_text(encoding="utf-8")

    assert 'depends_on "python@3.14"' in formula
    assert 'depends_on "portaudio"' in formula
    assert '"bin/hermes-streaming-tui"' in formula
