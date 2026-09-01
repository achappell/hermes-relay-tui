"""Bundled wake-word models, so the client is self-contained.

Everything openWakeWord needs to detect "hey hermes" ships inside this
package. The client must work on a clean machine with no Hermes install
present and no first-run download: nothing here resolves a path into
``~/.hermes``, and no model is fetched at runtime.

Three files, because openWakeWord needs all three and only ever ships the
first one's *format*, not the files themselves:

- ``hey_hermes.onnx`` — the phrase model.
- ``melspectrogram.onnx`` — shared feature extraction.
- ``embedding_model.onnx`` — shared feature extraction.

openWakeWord downloads the two shared models into its own package directory
on first use. Bundling them here removes that network round trip and the
failure it causes on an appliance with no connectivity at boot.

Only the ONNX variants are bundled. openWakeWord defaults to tflite, whose
runtime is packaged as ``tflite-runtime`` on some platforms and
``ai-edge-litert`` on others, and whose import openWakeWord hardcodes; the
client forces the ONNX framework to avoid that entirely.

See ``README.md`` in this directory for provenance and licensing.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "MODEL_DIR",
    "WAKE_MODEL",
    "MELSPECTROGRAM_MODEL",
    "EMBEDDING_MODEL",
    "bundled_models_present",
]

MODEL_DIR = Path(__file__).resolve().parent

WAKE_MODEL = MODEL_DIR / "hey_hermes.onnx"
MELSPECTROGRAM_MODEL = MODEL_DIR / "melspectrogram.onnx"
EMBEDDING_MODEL = MODEL_DIR / "embedding_model.onnx"


def bundled_models_present() -> bool:
    """Whether every bundled model survived packaging."""
    return all(
        path.is_file()
        for path in (WAKE_MODEL, MELSPECTROGRAM_MODEL, EMBEDDING_MODEL)
    )
