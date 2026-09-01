import json
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_project_metadata_exposes_the_console_command():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "hermes-relay-tui"
    assert metadata["project"]["requires-python"] == ">=3.14,<3.15"
    assert metadata["project"]["scripts"]["hermes-relay"] == "app:main"
    assert metadata["project"]["scripts"]["hermes-relay-home"] == "home_display.demo:main"
    assert {"attachments", "shell", "setup_wizard"}.issubset(
        metadata["tool"]["setuptools"]["py-modules"]
    )


def test_home_display_package_and_static_assets_are_declared():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"home_display"' in text
    assert "static" in text


def test_home_display_python_files_do_not_import_textual():
    for path in (ROOT / "home_display").rglob("*.py"):
        assert "import textual" not in path.read_text(encoding="utf-8")


def test_homebrew_trial_formula_declares_runtime_boundaries():
    formula = (ROOT / "packaging/homebrew/hermes-relay-tui.rb").read_text(encoding="utf-8")

    assert 'depends_on "python@3.14"' in formula
    assert 'depends_on "portaudio"' in formula
    assert '"bin/hermes-relay"' in formula


def test_release_automation_tracks_the_python_package():
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    package = config["packages"]["."]
    assert package["release-type"] == "python"
    assert package["package-name"] == "hermes-relay-tui"
    assert manifest["."] == project["project"]["version"]
    assert "release-please-action@" in (
        ROOT / ".github/workflows/release-please.yml"
    ).read_text(encoding="utf-8")


def test_release_workflow_publishes_python_distributions():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "python -m build --sdist --wheel" in workflow
    assert "gh release upload" in workflow
    assert "pypa/gh-action-pypi-publish@" in workflow
    assert "HOMEBREW_TAP_AUTOMATION" in workflow
    assert "achappell/homebrew-hermes-relay" in workflow
    assert "homebrew-hermes-streaming" not in workflow
    assert "generate_homebrew_formula.py" in workflow
    assert "tap/Formula/hermes-relay-tui.rb" in workflow
    assert "Formula/hermes-streaming-tui.rb" in workflow
    assert "git push origin HEAD:main" in workflow
    assert "gh pr create" not in workflow
    assert "workflow_dispatch:" in workflow
    assert "description: \"Existing release tag to package" in workflow
    assert "ref: ${{ inputs.tag || github.ref }}" in workflow
    assert "RELEASE_TAG" in workflow
