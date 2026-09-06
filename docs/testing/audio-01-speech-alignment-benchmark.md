# AUDIO-01 Speech Alignment Benchmark and Rollout Gate

This runbook validates streamed speech timing without storing prompts,
response text, or audio. The benchmark consumes the same timing normalization
and visible-text projection used by the client.

## 1. Run the deterministic fixture gate

From the repository root:

```bash
venv/bin/python speech_benchmark.py --fixtures
```

The fixture matrix covers short speech, long fallback pacing, Markdown and
paragraph boundaries, punctuation and numbers, multiple segments, malformed
spans, provider rejection, and alignment timeout. The command must report
`gate: PASS`.

For machine-readable evidence:

```bash
venv/bin/python speech_benchmark.py --json > /tmp/audio-01-fixtures.json
```

Inspect the JSON locally, then remove it after recording the aggregate result.
It contains no prompt or response content.

## 2. Capture a local-profile baseline

Keep alignment disabled in the local Hermes profile. Start the TUI with a
content-safe trace:

```bash
venv/bin/python app.py --debug --log-file /tmp/hermes-relay-local.log
```

Perform one short voice turn and one long voice turn. Confirm that playback
and the visible transcript remain usable. Do not copy prompts, response text,
or audio captures into the repository.

## 3. Capture the media-profile candidate

Enable the candidate speech-alignment configuration in the media profile,
then repeat the same short and long smoke turns with a separate trace:

```bash
venv/bin/python app.py --debug --log-file /tmp/hermes-relay-media.log
```

Analyze both traces:

```bash
venv/bin/python speech_benchmark.py --strict \
  --log local=/tmp/hermes-relay-local.log \
  --log media=/tmp/hermes-relay-media.log
```

The analyzer reports first-audio latency, aligned and fallback segment
counts, fallback reasons, total audio duration, timing parse failures, and
offset monotonicity. It never prints the logged text or audio contents.

## 4. Pass criteria

The rollout gate passes only when all of the following are true:

- The deterministic fixture gate passes.
- Both local and media traces contain at least one turn and audio stream.
- Both traces have no timing parse failures and monotonic segment offsets.
- The short and long voice turns play through without blank captions,
  repeated paragraphs, backward visible text, or a stuck fallback.
- Any provider 422 or alignment timeout degrades to duration pacing without
  interrupting playback.
- The aggregate first-audio latency and total-duration measurements are
  recorded with the verification evidence.

Until these criteria pass, alignment stays disabled by default.

## 5. Rollback

If the candidate causes timing drift, malformed spans, provider errors, or
playback disruption, disable the alignment feature in the active Hermes
profile (`HERMES_SPEECH_ALIGNMENT=off` or the equivalent
`alignment.enabled: false` setting), restart the client, and rerun the local
baseline smoke. The client’s duration fallback remains the safe path.

Do not commit raw debug traces, prompts, response text, or audio captures.
