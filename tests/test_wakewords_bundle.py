"""The client must be self-contained.

Hands-free capture has to work on a clean machine with no Hermes install
present and no first-run download. These tests fail the moment something
reintroduces a dependency on either.
"""

import ast
import tomllib
from pathlib import Path

import wake
import wakewords

ROOT = Path(__file__).resolve().parents[1]


def test_every_model_openwakeword_needs_is_bundled():
    """The phrase model alone is not enough: openWakeWord's wheel omits the
    shared feature-extraction pair and downloads them on first use."""
    assert wakewords.WAKE_MODEL.is_file()
    assert wakewords.MELSPECTROGRAM_MODEL.is_file()
    assert wakewords.EMBEDDING_MODEL.is_file()
    assert wakewords.bundled_models_present() is True


def test_the_bundled_models_are_real_files_not_placeholders():
    assert wakewords.WAKE_MODEL.stat().st_size > 100_000
    assert wakewords.MELSPECTROGRAM_MODEL.stat().st_size > 500_000
    assert wakewords.EMBEDDING_MODEL.stat().st_size > 500_000


def test_no_bundled_path_resolves_into_a_hermes_install():
    """The whole point: nothing may reach into ~/.hermes at runtime."""
    for path in (
        wakewords.WAKE_MODEL,
        wakewords.MELSPECTROGRAM_MODEL,
        wakewords.EMBEDDING_MODEL,
    ):
        assert ".hermes" not in str(path)
        assert path.is_relative_to(ROOT)


def _code_string_literals(path):
    """Every string constant in a module except its docstrings.

    Prose is allowed to mention ~/.hermes; code is not allowed to read from it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))

    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_no_source_file_reads_a_path_out_of_a_hermes_install():
    for name in ("wake.py", "handsfree.py", "wakewords/__init__.py"):
        for literal in _code_string_literals(ROOT / name):
            assert ".hermes" not in literal, f"{name}: {literal!r}"


def test_the_engine_defaults_to_the_bundled_models_and_forces_onnx():
    seen = {}

    def _factory(**kwargs):
        seen.update(kwargs)
        return type("M", (), {"predict": lambda self, frame: {}})()

    wake.load_openwakeword_engine(_import_module=lambda: _factory)

    assert seen["inference_framework"] == "onnx"
    assert seen["wakeword_models"] == [str(wakewords.WAKE_MODEL)]
    assert seen["melspec_model_path"] == str(wakewords.MELSPECTROGRAM_MODEL)
    assert seen["embedding_model_path"] == str(wakewords.EMBEDDING_MODEL)


def test_an_explicit_model_keeps_the_bundled_shared_models():
    """Choosing another phrase must not cost the offline guarantee."""
    seen = {}

    def _factory(**kwargs):
        seen.update(kwargs)
        return type("M", (), {"predict": lambda self, frame: {}})()

    wake.load_openwakeword_engine(
        "/models/hey_idris.onnx", _import_module=lambda: _factory
    )

    assert seen["wakeword_models"] == ["/models/hey_idris.onnx"]
    assert seen["melspec_model_path"] == str(wakewords.MELSPECTROGRAM_MODEL)


def test_a_missing_bundle_falls_back_rather_than_crashing():
    seen = {}

    def _factory(**kwargs):
        seen.update(kwargs)
        return type("M", (), {"predict": lambda self, frame: {}})()

    wake.load_openwakeword_engine(_import_module=lambda: _factory, _bundled=dict)

    assert seen == {"inference_framework": "onnx"}


def test_the_models_are_declared_as_package_data():
    """A model that is not packaged is a model that is not there."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    setuptools = metadata["tool"]["setuptools"]

    assert "wakewords" in setuptools["packages"]["find"]["include"]
    assert "*.onnx" in setuptools["package-data"]["wakewords"]


def test_the_wake_modules_are_actually_installed():
    """wake.py and handsfree.py are flat modules; omitting them from
    py-modules ships a package that cannot import its own listener."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    modules = metadata["tool"]["setuptools"]["py-modules"]

    assert "wake" in modules
    assert "handsfree" in modules
