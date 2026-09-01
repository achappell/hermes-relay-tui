# HOME-02 Wake-Word Listener and Hands-Free Turn Capture

Status: Revised after referencing Hermes' own wake-word implementation;
pending review. Implementation not started.

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
- **The wake phrase is "hey hermes", using the model Hermes already trained.**
  `~/.hermes/hermes-agent/tools/wakewords/hey_hermes.onnx` (205 KB) was
  produced by openWakeWord's training pipeline and is redistributable under the
  openWakeWord licence (Apache-2.0). Copying that artifact costs nothing and is
  strictly better than falling back to a stock "hey jarvis". The model path and
  sensitivity stay configurable, so the phrase is not hardcoded.
- **Barge-in is implemented and tested, but disabled by default** until HOME-05
  lands echo cancellation. Without it the unit hears its own speech and can
  retrigger on itself, interrupting its own sentence. The code and tests exist
  now; one config flag enables it when the hardware is ready.
- **openWakeWord is an optional dependency extra**, not a base dependency.
  `AGENTS.md` requires front-end-only dependencies live in an extra so
  installing the TUI does not drag in appliance hardware libraries. A terminal
  client should not pull an ONNX runtime.

## Changing the phrase later

The unit answers to "hey hermes" because that model already exists and this
slice should not carry a training pass. The phrase is configuration, not
structure, so changing it later is a config edit plus a model — not a redesign.

Two routes exist when that day comes, and the second is much cheaper:

- **Train a bespoke openWakeWord model** with the synthetic-TTS pipeline that
  produced `hey_hermes.onnx`. Proven, but hours.
- **Add sherpa-onnx keyword spotting**, which Hermes' `wake_word.py` already
  implements as a second engine. Open vocabulary: any typed phrase, no training,
  ~13 MB model fetched once. Choosing a custom phrase would mean adding that
  engine rather than running a training project.

`wake.py`'s engine seam should therefore stay an injected interface with one
implementation, not an openWakeWord-shaped class. That costs nothing now and is
the whole difference between adding an engine and rewriting the module.

## Prior art: Hermes' own wake-word implementation

Hermes already ships a mature listener at
`~/.hermes/hermes-agent/tools/wake_word.py` (1,508 lines, three engines:
openWakeWord, sherpa, porcupine). This design mines it for decisions rather
than reinventing them.

**What is borrowed:**

- **The trained "hey hermes" model**, as above.
- **Confirmation frames.** openWakeWord scores one ~80 ms frame at a time, and
  a stray phoneme in background conversation can spike a single frame over the
  threshold. A real utterance holds the score high across several consecutive
  frames. Requiring N-in-a-row before firing is, in Hermes' words, "the primary
  lever against unintended triggers on ambient talk" — a stronger defence than
  raising the threshold, which just makes the phrase harder to say. Default 3,
  clamped 1–10, at a cost of a few tens of milliseconds.
- **A fire cooldown** between consecutive fires, so one utterance cannot
  retrigger across frames while the caller is still reacting. Hermes uses 2.0s.
- **Silent-stream detection.** A stream can be *open and alive but all zeros* —
  a dead mic reads as an audio device that is present and working. Hermes flags
  a stream whose peak stays at or below 10 for 10 consecutive seconds. The
  acceptance criterion "recovers from an audio device disappearing" does not
  cover this case, and on an appliance nobody is watching, a silently dead
  microphone is the more likely and more corrosive failure.

**What is corroborated:** Hermes reaches the same conclusion about device
sharing, independently — its detector exposes `pause()`/`resume()` so callers
suspend it while a voice turn holds the microphone, because "two input streams
on one device is unreliable cross-platform." That is the chosen approach here,
arrived at from `voice.py`'s CoreAudio comment and confirmed by a second
implementation in production.

**Traps it already found:**

- openWakeWord hardcodes `import tflite_runtime.interpreter` but only declares
  `tflite-runtime` for some platforms; on others the package is
  `ai-edge-litert`, and the module must be aliased for the upstream import to
  succeed.
- Inference framework selection differs on macOS arm64, so it cannot be assumed.

**What is deliberately NOT borrowed: the code itself.** `voice.py`'s module
docstring records that relay-tui previously loaded Hermes' `tools/` helpers by
file path and that this was removed, because it "reached into an upstream
fork's internal tooling with no stability contract." Importing
`tools/wake_word.py` from `~/.hermes` would undo a deliberate fix and re-couple
this client to a checkout it does not control. The model file is a data
artifact with a licence; the module is someone else's internals.

**One protocol note.** Hermes' gateway exposes `wake.start`, `wake.status`,
`wake.feed`, and a `wake.detected` event, letting a client stream frames for
server-side detection. That is the TUI gateway protocol, not the voice-session
channel relay-tui speaks, and `AGENTS.md` forbids changing the voice-session
protocol without an explicit request. Local detection is right for this slice;
whether the home unit should eventually feed frames to Hermes instead is a
separate question and deserves its own card.

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

The 8s default is confirmed (Amanda, 2026-09-01). It is the tolerated pause
between the wake phrase and the start of the sentence - long enough to turn off
a tap and turn round before asking. It stays configuration, so a week of real
use can shorten it if the household turns out to be crisper than that.

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
`--wake-confirmation-frames` · `--wake-refractory-seconds` ·
`--wake-listen-timeout` · `--wake-barge-in`

`--wake-confirmation-frames` defaults to 3 and clamps to 1–10, matching
Hermes. Setting it to 1 restores naive single-frame behaviour, which is the
configuration most likely to make the unit fire at the radio.

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
| Stream open but all zeros (dead mic) | Flag after a sustained near-zero peak; surface it as a state, do not silently pretend to listen. |

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
- a single-frame spike above threshold does **not** fire when
  `confirmation_frames > 1` — the ambient-speech rejection case
- N consecutive over-threshold frames do fire
- a streak broken before N resets, and does not fire
- an all-zero frame sequence raises the dead-mic condition

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
