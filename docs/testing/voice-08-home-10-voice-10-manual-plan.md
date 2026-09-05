# Manual test plan — audio playback, wake acknowledgement, and TUI wake mode

Covers three merged-or-pending slices in one sitting:

| Card | What it changed | PR |
|---|---|---|
| VOICE-08 | Streamed PCM playback: the popping, and overlapping streams | #48 (merged) |
| HOME-10 | Wake and end-of-capture tones, the `heard` state, the thinking indicator | #49 |
| VOICE-10 | `/wake on\|off\|status` in the terminal client | #50 (stacked on #49) |

Every automated test for these passes against fakes. What fakes cannot answer
is whether real audio hardware behaves, and whether any of it is legible from
across a room. That is what this document is for.

Budget about 35 minutes. Parts B and C need a kitchen; part A does not.

## Prerequisites

```bash
hermes-relay install                   # installs voice and wake support
npm --prefix home_display/web run build  # only if the browser shell changed
```

A token must be resolvable: `--token`, `VOICE_SESSION_TOKEN`, or the profile
`.env`. Grant the terminal microphone permission in System Settings → Privacy &
Security → Microphone.

Have a way to see the macOS microphone indicator — the orange dot in the menu
bar. Several checks below depend on watching it appear and disappear.

---

## Part A — the terminal client (no kitchen required)

### A1. Wake mode is off until you say so

```bash
venv/bin/python app.py
```

- [ ] The client starts with **no** microphone indicator.
- [ ] `/wake` reports `wake mode: off`.
- [ ] `/wake status` says the same thing.

### A2. The flag no longer lies

```bash
venv/bin/python app.py --wake-enabled
```

- [ ] It **refuses to start**, exits non-zero, and the message names `/wake on`.
- [ ] It does **not** open the microphone.

> Before this change the flag parsed and did nothing at all. If the TUI starts
> normally here, the fix is not in your working tree.

### A3. Arming and releasing

Back in a normal session (`venv/bin/python app.py`):

- [ ] `/wake on` — the transcript confirms it, and the **microphone indicator
      appears**.
- [ ] `/wake status` now reports the model and threshold.
- [ ] `/wake off` — the transcript confirms release, and the **indicator
      clears**.

### A4. The reopen cycle — the risky one

`voice.py` warns that reopening the input stream can hang on macOS CoreAudio.
This is the path that would prove it. Do it deliberately:

- [ ] `/wake on`, `/wake off`, `/wake on`, `/wake off`, `/wake on` — five
      transitions, watching the indicator follow every one.
- [ ] The client stays responsive throughout. **No hang, no beachball.**
- [ ] `/wake off` at the end leaves the indicator clear.

> If it hangs, stop and note which transition. That is a real finding and the
> reason this section exists.

### A5. A wake turn in the terminal

With wake mode armed:

- [ ] Say the phrase. You hear the **rising two-note chirp**.
- [ ] Ask a question. When you stop, you hear the **single lower note**.
- [ ] The answer arrives as a normal turn in the transcript.
- [ ] Say the phrase again *while the answer is still playing* — it is ignored,
      no second turn starts.

### A6. Quit releases the device

- [ ] With wake mode **on**, press `Ctrl+Q`.
- [ ] The microphone indicator clears on exit.

### A7. Missing engine, useful message

In a venv without the `wake` extra:

- [ ] `/wake on` prints a message naming `hermes-relay install`.
- [ ] No traceback, and the client keeps running.

---

## Part B — playback quality (VOICE-08)

Any client will do; the appliance is the harsher test.

### B1. The popping is gone

- [ ] Ask for a reply of a few sentences. Listen to the **first half second**.
- [ ] No click at the start, no crackling between chunks.

> The old failure was an audible click roughly every 470ms as the device ran
> dry between network chunks.

### B2. Back-to-back turns do not overlap

- [ ] Ask a question. As soon as the answer *finishes*, immediately ask another.
- [ ] The second answer plays cleanly, with no tail of the first underneath it.

### B3. Known bad — truncated speech (RELAY-04)

This is expected to fail. You are confirming the shape of a Hermes-side bug,
not testing a fix.

- [ ] Ask it to **count to thirty**.
- [ ] Compare what the screen shows against what you hear.
- [ ] Expected: the text shows 1–30; the audio stops short and the first
      syllable is clipped.

If the audio is now complete, RELAY-04 has been fixed upstream — say so, it
comes off the board.

---

## Part C — the appliance (HOME-10)

```bash
venv/bin/python -m home_display.appliance --wake-enabled
```

Open the printed URL in a browser. That is the kitchen display.

### C1. The gap has something in it

- [ ] Say the phrase. Within a blink you get **both** the chirp and `Heard you`
      on screen.
- [ ] The display moves `Heard you` → `Listening` → `Thinking` → `Speaking`.
- [ ] `Heard you` appears **before** `Listening`, never after.
- [ ] During `Thinking`, a **dot slowly breathes** next to the status.
- [ ] `Speaking` appears only when sound is actually coming out.

### C2. The across-the-room test — the point of the card

Stand where you normally would in the kitchen. **Do not look at the display.**

- [ ] Say the phrase. Can you tell it heard you, by ear alone?
- [ ] Ask a question. Can you tell, by ear alone, when it stopped listening and
      started working?

If either answer is no, the tones need changing — pitch and length are
constants at the top of `earcons.py`. That is a finding, not a failure of the
run.

### C3. A misfire withdraws in silence

- [ ] Say the phrase and then say **nothing at all** for ten seconds.
- [ ] You hear the wake chirp and then **nothing** — no second tone, no speech,
      no error.
- [ ] The display returns to idle on its own.

### C4. The tones stay out of the recording

- [ ] Say the phrase and start talking immediately after the chirp.
- [ ] The transcript of your question contains no stray leading word.
- [ ] The chirp never triggers a second detection.

### C5. The off switch

```bash
venv/bin/python -m home_display.appliance --wake-enabled --no-earcons
```

- [ ] No tones at all.
- [ ] The wake word **still works** and the display still shows `Heard you`.

### C6. The kitchen soak — inherited from HOME-02

Leave it running with the extractor fan on, a tap running, and the radio going.
Nobody speaks.

```bash
venv/bin/python scripts/wake_check.py --seconds 600 --quiet
```

- [ ] After ten minutes the detection count has **not moved**.

> This is the one acceptance criterion carried since HOME-02. If the count
> moves, raise `--wake-confirmation-frames` before touching the threshold.

---

## Reporting

Anything that fails: note the step number and what actually happened. Snags
that are real but not blocking go in `docs/friction-log.md`; anything that
blocks a card goes on the card itself.
