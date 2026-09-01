# HOME-02 Wake-Word Listener and Hands-Free Turn Capture

Status: Design approved; implementation not started.

Project item: `HOME-02 Wake-word listener and hands-free turn capture`

## Outcome

The home unit wakes on a spoken phrase and hands the resulting turn to the
shared session core, with no keyboard involved.

## Product decisions

- **Scope is the listener and the capture path, not the appliance loop.**
  This slice delivers detection, capture, and handoff to
  `session.SessionProtocol`. Replacing `home_display`'s fake state source with
  real session orchestration is a separate item. HOME-03 deliberately deferred
  that wiring and this slice does not absorb it.
- **The wake phrase ships as a pretrained openWakeWord model**, with the model
  path and sensitivity in configuration. Training a bespoke phrase is a
  multi-hour project with its own tuning loop; it would block the listener from
  landing on something testable. The phrase is not hardcoded, which is what the
  acceptance criteria require.
- **Barge-in is implemented and tested, but disabled by default** until HOME-05
  lands echo cancellation. Without it the unit hears its own speech and can
  retrigger on itself, interrupting its own sentence. The code and tests exist
  now; one config flag enables it when the hardware is ready.
- **openWakeWord is an optional dependency extra**, not a base dependency.
  `AGENTS.md` requires front-end-only dependencies live in an extra so
  installing the TUI does not drag in appliance hardware libraries. A terminal
  client should not pull an ONNX runtime.

## Approach: tap the existing audio stream

`AudioRecorder` already opens one persistent `sounddevice.InputStream` and
keeps it alive across recordings, because closing and reopening it can hang on
macOS CoreAudio (`voice.py:43-50`). Between recordings its callback discards
frames (`voice.py:100`):

```python
if not self._recording:
    return
```

The listener subscribes at that discard point rather than opening a device of
its own.

Alternatives considered:

- **A second `InputStream` owned by the listener**, stopped during capture.
  Cleaner on paper, but it puts two handles on one device and requires
  open/close on every capture — the exact operation `voice.py` documents as
  hanging on CoreAudio. It trades an already-solved hazard for tidiness.
- **The listener owning the device outright** and feeding frames straight to
  transcription. Arguably the right shape for a keyboard-less appliance, but it
  duplicates the silence endpointing, dip tolerance, and hallucination
  filtering in `AudioRecorder`, leaving the TUI and the home unit on two
  capture paths that will quietly diverge.

The chosen approach reuses the debugged CoreAudio behaviour and keeps one
capture path shared by both front ends, which is the point of the core /
front-end split in `AGENTS.md`.

Its cost, stated plainly: the hook sits inside a real-time audio callback. The
observer must be a non-blocking queue push. Inference never runs on the audio
thread.

## Architecture

Two new core modules, both bound by the `AGENTS.md` core rules — no Textual, no
assumed terminal, no assumed human watching a screen.

| Module | Purpose | Depends on |
|---|---|---|
| `wake.py` | Detection only. Wraps openWakeWord, owns a worker thread and a bounded frame queue, emits wake events. | injected model |
| `handsfree.py` | Orchestration. Detection to capture to transcript to `SessionProtocol`. Owns the listening window, single-flight guard, and barge-in. | `wake`, `mic`, `session` |
| `voice.py` (edit) | Frame-observer hook at the existing discard point. | — |

Detection and orchestration are separate because they fail differently and are
tested differently. `wake.py` is signal processing driven by scripted scores;
`handsfree.py` is a state machine driven by a fake session. Folding them
together would make the state machine untestable without a model.

`wake.py` imports openwakeword lazily, matching the lazy `faster_whisper`
import in `voice.py`. Because that same lazy-import pattern recently hid a
SIGKILL until first use (DIST-02), the absent-dependency path must produce an
explicit message rather than failing silently.

## State machine

`handsfree.py` owns four states. Each acceptance criterion is an edge.

```
                  detection
        +-----------------------------+
        v                             |
    +--------+  detection   +---------------+
    |  IDLE  |------------->|   CAPTURING   |
    +--------+              +---------------+
        ^                      |         |
        |  empty / hallucinated|         | transcript
        |  / window timeout    |         v
        |                      |   +-----------+
        +----------------------+---|  SENDING  |
        |        turn complete      +-----------+
        |                                 |
    +-----------+  barge-in (gated off)   |
    | SPEAKING  |<------------------------+
    +-----------+
```

**Exactly one capture per detection.** A single-flight lock plus a refractory
window. Detections arriving during `CAPTURING` or `SENDING` are dropped, not
queued; queuing them is how turns stack. The chosen approach supplies most of
this structurally — during capture the callback routes frames to the recorder,
so the listener is deaf by construction rather than by convention.

**False triggers are silent and cheap.** Three independent gates, none of which
touches `SessionProtocol`:

1. The listening window expires and returns to `IDLE`.
2. An empty transcript is dropped.
3. `is_whisper_hallucination()` (`voice.py:321`) drops the rest. A misfire on
   an extractor fan transcribes as "Thank you." or "you", which that filter
   already recognises.

A misfire therefore cannot leave a session mid-turn and cannot speak.

## The three timers

Hands-free capture needs a timer the TUI never did. Naming all three prevents
them being conflated.

| Timer | Exists | Question it answers |
|---|---|---|
| `mic_silence_duration` | yes | "Have you stopped talking?" Ends the recording and sends it. |
| `mic_max_seconds` | yes | "Are you still talking? Stop anyway." Hard cap on one recording. |
| listening window | **new** | "Did you ever start talking at all?" |

The first two only apply once speech has begun. In the TUI, pressing a key
proves a human is present and intends to speak. Hands-free has no such proof.

Real wake, someone speaks:

```
0.0s  detection -> CAPTURING
0.4s  speech begins            <- window satisfied, cancelled
2.9s  speech ends
5.9s  silence timer fires -> transcript -> send
```

Misfire, nobody present:

```
0.0s  fan noise scores above threshold -> CAPTURING
...   no speech, ever
8.0s  window expires -> discard, IDLE, silently
```

The window is disarmed the moment speech is detected, so it never competes with
the silence timer. `_has_spoken` (`voice.py:117`) already tracks that signal.

Without the window, a misfire holds the microphone until `mic_max_seconds`,
deaf to a real wake word throughout, then hands a long stretch of noise to
Whisper.

The 8s default is a starting point, not an answer. The value that matters is
how long someone takes to cross a kitchen and begin a sentence after the unit
acknowledges. That is settled by the manual validation scenario, which is why
it is configuration.

## Barge-in

`handsfree.py` does not own playback — that belongs to the appliance loop,
which is out of scope here. It is *told* about playback through two injected
callables supplied by whatever front end drives it: a way to be notified that
playback started and stopped, and a way to stop it. With nothing injected the
unit never enters `SPEAKING`, and the state machine reduces to the three states
this slice can exercise on its own. That keeps barge-in fully testable now
without this module growing an audio dependency it should not have.

The `SPEAKING -> CAPTURING` edge: stop playback, then capture. Fully
implemented and tested against fake audio, and disabled by default via
`--wake-barge-in` until HOME-05.

The code comment must record the reason, not just the behaviour: without echo
cancellation the unit hears its own voice and interrupts itself mid-sentence, a
symptom that is baffling without the context.

## Configuration

All values have defaults and none of the phrase behaviour is hardcoded.

`--wake-enabled` · `--wake-model` · `--wake-threshold` ·
`--wake-refractory-seconds` · `--wake-listen-timeout` · `--wake-barge-in`

```toml
[project.optional-dependencies]
wake = ["openwakeword>=0.6", "onnxruntime>=1.17"]
```

## Error handling

A broken listener degrades the appliance to "not hands-free". Never to
"broken", and never to "speaks unprompted".

| Failure | Behaviour |
|---|---|
| `openwakeword` not installed | Listener disabled, one clear message naming the extra. Not a traceback. |
| Model missing or unloadable | Typed error, listener off, session still usable. |
| Frame queue full | Drop oldest, never block. This is the audio callback thread; blocking it stutters recording process-wide. |
| Detection worker raises | Log, restart with backoff, session untouched. |
| Audio device disappears | Supervisor backs off and re-subscribes when the stream rebuilds. |
| Transcription fails mid-capture | Return to `IDLE` silently. |

The bounded queue is deliberate. An unbounded queue would avoid dropping
frames, but the frames dropped under load are ones the listener would score as
noise anyway, and unbounded growth on an always-on appliance running for months
is the worse trade.

Device recovery is simple because the listener owns no device state: it is only
ever a subscriber, so it has nothing to get out of sync.

## Testing

No hardware, per the card's validation scenario.

`wake.py`, driven by scripted score sequences through an injected model:

- scores below threshold produce no event
- a threshold crossing fires once
- a sustained plateau fires once, not once per frame
- a second crossing inside the refractory window does not fire

`handsfree.py`, driven by a fake `SessionProtocol` and a fake recorder — the
doubles pattern `session.py` already documents:

- detection produces exactly one capture
- detections during `CAPTURING` and `SENDING` are dropped, with no stacked turns
- window expiry with no speech returns to `IDLE` **and the fake session is
  never called**
- speech before expiry disarms the window; the silence timer governs
- empty and hallucinated transcripts are dropped
- barge-in stops playback then captures, and is off by default
- device loss re-subscribes

The "never called" assertion encodes the product rule rather than the
mechanics: a misfire at 2am must not wake the house.

Also:

- `tests/test_core_boundary.py` gains `wake` and `handsfree`.
- A packaging test asserts the `wake` extra exists and its packages are absent
  from base dependencies.

## Out of scope

- Replacing `home_display`'s fake state source with real orchestration.
- Training a bespoke wake phrase.
- Echo cancellation and audio hardware bring-up (HOME-05).
- Chromium autostart and process supervision (HOME-06).

## Dependencies

CORE-01 is complete. HOME-05 is required for realistic barge-in validation on
hardware, which is why barge-in ships gated rather than blocking this slice.
