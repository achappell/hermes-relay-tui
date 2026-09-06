# AUDIO-01 Speech Alignment Benchmark Implementation Plan

**Goal:** Build a repeatable, content-safe gate for deciding whether speech alignment is reliable enough to enable on configured Hermes profiles.

**Architecture:** A pure-Python benchmark module will generate deterministic timing fixtures and reuse `timing.py` as the client oracle. A second parser will consume the existing debug trace format and report aggregate live-profile metrics without reading or storing prompt, response, or audio contents. The command exits non-zero when a required invariant fails, while alignment remains a runtime configuration decision outside the benchmark.

**Tech Stack:** Python 3.14, standard library (`argparse`, `json`, `re`, `dataclasses`), existing `timing.py`, pytest.

## Design decision

Selected: one reusable `speech_benchmark.py` module with a console entry point and a content-safe trace analyzer.

Rejected:

- A network client embedded in the benchmark: it would duplicate provider authentication and could accidentally persist live content or audio.
- A second timing implementation in the benchmark: it would allow the gate to pass while the TUI behaved differently; all caption assertions must call the existing `normalize_speech_timing`, `visible_text`, and fallback helpers.
- Enabling alignment from the benchmark: the tool records evidence and returns a gate verdict; profile configuration remains the explicit rollout decision.

## Tasks

### Task 1: Define deterministic fixtures and metric records

**Files:**

- Create: `speech_benchmark.py`
- Test: `tests/test_speech_benchmark.py`

Add typed fixture and result records for short aligned speech, long fallback speech, Markdown, paragraph breaks, punctuation/numbers, multi-segment timing, malformed spans, 422 fallback, and timeout fallback. Include content-safe metrics for alignment count, fallback counts, coverage, first-audio latency, total audio duration, and monotonic segment offsets.

### Task 2: Implement the deterministic client gate

**Files:**

- Modify: `speech_benchmark.py`
- Test: `tests/test_speech_benchmark.py`

Run every fixture through the existing timing normalizer and visible-text functions. Assert no blank visible transcript during active playback, no backward visible-text movement, no duplicated paragraph projection, valid fallback for failed alignment, and audio-bounded monotonic offsets. Produce stable JSON and human-readable summaries.

### Task 3: Add content-safe debug-trace analysis

**Files:**

- Modify: `speech_benchmark.py`
- Modify: `client.py` (include the monotonic timestamp on `turn.send`)
- Test: `tests/test_speech_benchmark.py`
- Test: `tests/test_client.py`

Parse the existing structural log lines for turn start, first audio, audio chunks, speech timing, and playback samples. Calculate first-audio latency from monotonic timestamps and aggregate alignment/fallback/duration/offset metrics. Ignore unknown lines and never emit prompt text, response text, hashes, or raw audio.

### Task 4: Expose and document the gate

**Files:**

- Modify: `pyproject.toml`
- Modify: `README.md`
- Create: `docs/testing/audio-01-speech-alignment-benchmark.md`

Add `hermes-relay-benchmark` with `--fixtures`, `--log PATH` (repeatable), `--json`, and `--strict` options. Document the disabled baseline versus candidate alignment run, local/media profile procedure, safe output, pass/fail interpretation, and rollback to `alignment.enabled: false` / `HERMES_SPEECH_ALIGNMENT=off`.

### Task 5: Verify and reconcile

Run the focused benchmark, timing, client, and app tests, then `venv/bin/pytest`, `git diff --check`, and the fixture command in human and JSON modes. Move AUDIO-01 to Verify with the evidence; leave it there until the configured local/media short and long smoke logs are supplied and pass the gate.
