# Bundled wake-word models

These ship with the package so hands-free capture works on a clean machine.
No Hermes install, no first-run download, no network at boot.

| File | Size | What it is |
|---|---|---|
| `hey_hermes.onnx` | 205 KB | The "hey hermes" phrase model. |
| `melspectrogram.onnx` | 1.1 MB | Shared feature extraction (audio → melspectrogram). |
| `embedding_model.onnx` | 1.3 MB | Shared feature extraction (melspectrogram → embedding). |

## Why all three

openWakeWord needs a phrase model *and* the two shared feature-extraction
models. Its PyPI wheel does not contain the shared pair — `download_models()`
fetches them into the installed package directory on first use. An appliance
that wakes up without connectivity would otherwise fail on its first wake word,
which is the worst possible moment to discover a missing download.

Only the ONNX variants are bundled. openWakeWord defaults to the tflite
framework, whose runtime is `tflite-runtime` on some platforms and
`ai-edge-litert` on others while openWakeWord hardcodes the former's import
path. The client forces `inference_framework="onnx"`, so `onnxruntime` — a
declared dependency of the `wake` extra — is the only runtime needed.

## Provenance

- **Engine:** [openWakeWord](https://github.com/dscripka/openWakeWord), Apache-2.0.
- **`hey_hermes.onnx`:** trained with openWakeWord's training pipeline
  (synthetic TTS-generated speech). Registers under the label `hey_hermes`.
  Originally produced for the Hermes agent and copied here so this client
  carries its own copy rather than reading one out of a Hermes install.
- **`melspectrogram.onnx` / `embedding_model.onnx`:** openWakeWord's shared
  feature-extraction models, distributed with the project under Apache-2.0.
  The embedding model derives from Google's `speech_embedding` model, also
  Apache-2.0.

Redistribution is permitted under those licences. The files are vendored
rather than fetched so that installing this package is the only step required.

## Using a different phrase

Point `--wake-model` at another `.onnx` file, or at a built-in openWakeWord
name (`hey_jarvis`, `alexa`, `hey_mycroft`, …). Note that built-in names are
downloaded on demand and therefore give up the offline guarantee above.

HOME-08 covers choosing a phrase specific to this household, most likely via
sherpa-onnx keyword spotting, which needs no trained model at all.
