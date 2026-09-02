import importlib.util
import json
import re
from pathlib import Path
import tomllib

import yaml


ROOT = Path(__file__).resolve().parents[1]


def rendered_formula() -> str:
    """Render the formula the release workflow actually publishes to the tap.

    Asserting against a checked-in copy of the formula guards a file nothing
    installs, and that copy had already drifted a release behind.
    """
    spec = importlib.util.spec_from_file_location(
        "generate_homebrew_formula", ROOT / "scripts/generate_homebrew_formula.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FORMULA.format(version="9.9.9", sha256="0" * 64)


def test_project_metadata_exposes_the_console_command():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "hermes-relay-tui"
    assert metadata["project"]["requires-python"] == ">=3.14,<3.15"
    assert metadata["project"]["scripts"]["hermes-relay"] == "app:main"
    # The appliance owns the home entry point; the scripted fake display keeps
    # its own command so it stays runnable without a relay or a microphone.
    assert (
        metadata["project"]["scripts"]["hermes-relay-home"]
        == "home_display.appliance:main"
    )
    assert (
        metadata["project"]["scripts"]["hermes-relay-home-demo"]
        == "home_display.demo:main"
    )
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
    formula = rendered_formula()

    assert 'depends_on "python@3.14"' in formula
    assert 'depends_on "portaudio"' in formula
    assert '"bin/hermes-relay"' in formula


def test_homebrew_formula_installs_a_checksummed_release_archive():
    """A git-source formula clones full history, including rewritten commits."""
    formula = rendered_formula()

    assert "using: :git" not in formula
    assert "revision:" not in formula
    assert "/releases/download/" in formula
    assert re.search(r'^  sha256 "[0-9a-f]{64}"$', formula, re.MULTILINE)


def test_homebrew_formula_links_the_kiosk_entry_point_only_when_present():
    formula = rendered_formula()

    assert 'if (venv / "bin/hermes-relay-home").exist?' in formula


def test_homebrew_formula_resigns_relinked_bundled_dylibs():
    """DIST-02: Homebrew rewrites Mach-O install names across the keg, which
    invalidates the signatures PyAV ships on its bundled FFmpeg dylibs. macOS
    then SIGKILLs any process importing av or faster_whisper, killing local
    speech-to-text with no traceback."""
    formula = rendered_formula()

    assert "def post_install" in formula
    assert '"codesign", "--force", "--sign", "-"' in formula
    # The affected dylibs sit in hidden ".dylibs" directories, which the
    # default ** glob skips.
    assert "File::FNM_DOTMATCH" in formula
    # The formula's own test block must exercise the imports that break.
    assert "import av, faster_whisper" in formula


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
    assert "sha256sum sdist.tar.gz" in workflow
    assert "--sha256" in workflow
    assert "--revision" not in workflow
    assert "tap/Formula/hermes-relay-tui.rb" in workflow
    assert "Formula/hermes-streaming-tui.rb" in workflow
    assert "git push origin HEAD:main" in workflow
    assert "gh pr create" not in workflow
    assert "workflow_dispatch:" in workflow
    assert "description: \"Existing release tag to package" in workflow
    assert "ref: ${{ inputs.tag || github.ref }}" in workflow
    assert "RELEASE_TAG" in workflow


def test_readme_documents_upgrade_and_uninstall_state():
    """DIST-02: a clean Mac must uninstall without orphaned runtime state."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Upgrade and uninstall" in readme
    for path in (
        "~/.hermes-relay-tui/config.yaml",
        "~/.hermes-relay-tui/.env",
        "~/.hermes-relay-tui/history.jsonl",
        "~/.hermes-relay-tui/crash.log",
    ):
        assert path in readme, path
    assert "brew uninstall" in readme
    assert "pipx uninstall" in readme
    # The speech model lives in a cache shared with unrelated tools, so the
    # docs must scope removal to this client's entry only.
    assert "models--Systran--faster-whisper-*" in readme
    assert "rm -rf ~/.cache/huggingface\n" not in readme


def test_pypi_and_homebrew_publish_independently():
    """A PyPI failure must not skip the Homebrew tap update."""
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    )
    jobs = workflow["jobs"]

    assert jobs["publish-pypi"]["needs"] == "package"
    assert jobs["update-homebrew"]["needs"] == "package"
    # Neither channel may depend on the other, in either direction.
    assert "publish-pypi" not in str(jobs["update-homebrew"]["needs"])
    assert "update-homebrew" not in str(jobs["publish-pypi"]["needs"])
    # The publish step must not sit inside the job the tap update needs.
    assert "gh-action-pypi-publish" not in yaml.dump(jobs["package"])


def test_wake_dependencies_live_in_an_optional_extra():
    """HOME-02: a terminal install must not pull an ONNX runtime."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = metadata["project"]["optional-dependencies"]
    base = " ".join(metadata["project"]["dependencies"])

    wake_extra = " ".join(extras["wake"])
    assert "openwakeword" in wake_extra
    assert "onnxruntime" in wake_extra
    assert "openwakeword" not in base
    assert "onnxruntime" not in base


def test_the_home_extra_pulls_what_the_appliance_needs():
    """A plain install gives the home entry point without a wake-word engine,
    so the appliance needs an install line that names its own dependencies."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = metadata["project"]["optional-dependencies"]

    assert "hermes-relay-tui[wake]" in extras["home"]
