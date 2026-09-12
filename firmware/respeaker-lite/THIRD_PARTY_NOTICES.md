# ReSpeaker Lite third-party provenance and notices

This record identifies third-party source, firmware, and model assets used by
the ReSpeaker Lite Puck prototype. It records the evidence available in this
checkout and from the referenced upstream projects; it is not legal advice.
Where an individual artifact does not state its own license or provenance, the
status is left unresolved rather than inferred from a repository-level license.

## Component sources

| Local path | Source and version | Local treatment | License evidence |
| --- | --- | --- | --- |
| `components/i2s_audio/` | `formatBCE/esphome` at commit `eedcdbee335dbe296d432b3e6421da0469907365` | Vendored, with the project-specific microphone format changes documented in the component and YAML comments | The pinned source carries ESPHome's root license: GPL-3.0 for the C/C++ runtime and MIT for Python and other files. Apply the file-level terms and preserve upstream notices. |
| `components_stock/i2s_audio/` | Same pinned `formatBCE/esphome` source | Unmodified comparison copy used by the stock-format test configuration | Same ESPHome license evidence as above. |
| `components/respeaker_lite/` | `formatBCE/Respeaker-Lite-ESPHome-integration`, pinned at commit `3136cf7` | Vendored integration with the two environment-specific fixes described in `respeaker-lite.yaml`; no DFU or audio behavior change is intended | No separate license file was found in the inspected upstream integration tree. Do not assign an MIT, Apache, or GPL license to formatBCE-authored integration changes without confirming the author's terms. |
| `components/micro_wake_word/` | ESPHome `2026.8.2` | Vendored copy with the local raw-probability diagnostic described in the source comments | The component follows ESPHome's file-level license terms. See the upstream license links below. |

Upstream references:

- [formatBCE/Respeaker-Lite-ESPHome-integration](https://github.com/formatBCE/Respeaker-Lite-ESPHome-integration)
- [formatBCE/esphome at the pinned component commit](https://github.com/formatBCE/esphome/tree/eedcdbee335dbe296d432b3e6421da0469907365)
- [ESPHome license at the pinned component commit](https://raw.githubusercontent.com/formatBCE/esphome/eedcdbee335dbe296d432b3e6421da0469907365/LICENSE)
- [ESPHome's micro-wake-word component documentation](https://esphome.io/components/micro_wake_word/)

## External DFU firmware

The XMOS firmware is downloaded during an ESPHome build; the binary is not
stored in this repository:

- URL: `https://github.com/formatBCE/Respeaker-Lite-ESPHome-integration/raw/refs/heads/main/respeaker_lite_i2s_dfu_firmware_48k_v1.1.0.bin`
- Declared version: `1.1.0`
- Declared MD5: `9297155d1bf3eb21a9d4db52a89ea0c6`
- Reference documentation: [Seeed reSpeaker Lite guide](https://wiki.seeedstudio.com/respeaker_lite_ha/)

The URL points at the upstream `main` branch rather than an immutable release
asset. The inspected configuration and upstream integration did not provide a
separate license or redistribution term for this binary. A future release
must pin and review the binary's provenance and terms before distributing it.

## Bundled wake-model assets

The JSON/TFLite pairs below are committed under `wake_models/`. Their manifests
identify an author and, for the `hey_*` models, a website, but do not contain a
per-artifact license field or training-data provenance. The Apache-2.0 license
of the upstream micro-wake-word code/model repositories does not by itself
resolve the terms for these individual model files.

| Asset pair | Manifest author / website | SHA-256 (JSON / TFLite) |
| --- | --- | --- |
| `hey_bestie` | microwakeword.com — [microwakeword.com](https://microwakeword.com) | `14dbd0492d43c585c143d5fa7ae11813eec93fcc4aa8cd8e82cc4d67d52f80c6` / `aed347cf97629411ed9f8ccce8da4ca252ec24bffc50da3d47b18aa785db4c4c` |
| `hey_missy` | microwakeword.com — [microwakeword.com](https://microwakeword.com) | `7d884f8738d71abc4a5944fee037c32a73045b9e4a42241c334853fc506c510f` / `d15f00a985c4a46b2aa0a4af19dfe254d0753cac8277d04ca6540e794fc8178a` |
| `hey_skippy` | microwakeword.com — [microwakeword.com](https://microwakeword.com) | `4aac741997fda13596e2d1ee642d3e3ce169d520c204fe9b5c703a3bf80ef4e6` / `92eacaf28f159fbd213467a3e729db6e6cd67b88d4429cf99c6835ee3e84993f` |
| `stop` | Kevin Ahrendt — [kevinahrendt.com](https://www.kevinahrendt.com/) | `bd13aeb1b83852649dc4fb6135cb160ff68716d14612b06f6a405342c57447aa` / `b5a18c4ad681a89950dfade31011e1631bdcb333e93c84519a1a63ff4f071146` |
| `vad` | Kevin Ahrendt — [kevinahrendt.com](https://www.kevinahrendt.com/) | `bd8c9cd4350814f761e651685ae5196e2a56521aaf5670071ba742927de58ed7` / `7aa4db6d5fb7c5358609f6931e7847d303c16a43d178638bc14104f50d7eff5f` |

Related upstream projects:

- [OHF-Voice/micro-wake-word](https://github.com/OHF-Voice/micro-wake-word) — Apache-2.0 code and model-format project.
- [esphome/micro-wake-word-models](https://github.com/esphome/micro-wake-word-models) — Apache-2.0 repository-level license; individual model terms and training provenance still require confirmation where the artifact manifest is silent.
- [Upstream discussion of per-model licensing ambiguity](https://github.com/esphome/micro-wake-word-models/issues/31)

## Redistribution gate

Before distributing a firmware binary or the bundled model files outside a
private development pilot, confirm and record:

1. the license and redistribution terms for each individual wake model and
   its training data;
2. the license or permission covering formatBCE-authored integration changes;
3. the terms and an immutable source reference for the XMOS DFU binary; and
4. the required notices and source-offer obligations for ESPHome GPL-licensed
   runtime files.
