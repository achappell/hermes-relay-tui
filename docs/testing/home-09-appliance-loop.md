# HOME-09 appliance loop smoke procedure

This is the first procedure that needs the real thing: a microphone, a speaker,
and a live Hermes relay. It answers one question — does saying the phrase in the
room produce a spoken answer, with the screen telling the truth throughout.

The HOME-03 procedure covers the display shell on its own; run that first if the
browser assets have changed.

## Prerequisites

From a checkout, run the appliance as a module — no install needed, and it
picks up your working tree:

```bash
venv/bin/python -m home_display.appliance --wake-enabled
```

The `venv/bin/hermes-relay-home` console script only exists once the package
itself is installed (`venv/bin/pip install -e '.[home]'`). A venv built from
`requirements-dev.txt`, or one holding an older release, will not have it.

Either way the wake-word engine must be present — the `home` extra brings it.
Without it the appliance reports the missing dependency and exits rather than
starting deaf. Run `npm --prefix home_display/web run build` only if the
browser shell has changed.

A token must be resolvable: `--token`, `VOICE_SESSION_TOKEN`, or the profile
`.env`. Grant the terminal microphone permission in System Settings → Privacy &
Security → Microphone.

## Run it

```bash
venv/bin/python -m home_display.appliance --wake-enabled
```

Add `--url ws://127.0.0.1:8792/voice-session` to use a Hermes gateway running
on this machine rather than the configured default.

It prints a loopback URL. Open it in a browser — that is the kitchen display.

## The four things to check

1. **Wake to spoken answer.** Say the phrase, then ask a question. Confirm a
   spoken reply through the speaker, with no keyboard touched at any point.
2. **The display matches the hardware.** Watch it move `idle` → `listening` →
   `thinking` → `speaking` → `idle`. `speaking` must appear only while audio is
   actually coming out; if playback cannot open, the screen must say
   `buffering` instead.
3. **A misfire is silent.** Trigger a detection (a phrase-alike, or the radio)
   and then say nothing. Within the listening window the display returns to
   `idle`, nothing is sent, and the unit does not speak.
4. **Connection loss is honest.** Stop the relay mid-turn. The display shows
   `disconnected` and the wake word does nothing while it is down. Restart the
   relay: the unit reconnects on its own and returns to `idle`, and the next
   wake phrase works without restarting the appliance.

Stop with `Ctrl+C`.

## Testing without Hermes

"Does the appliance work" and "is Hermes up" are two questions, and answering
them together answers neither. `scripts/fake_relay.py` is a stand-in server
that speaks enough of the protocol to be indistinguishable for one turn: it
answers the handshake, streams a canned reply word by word, and speaks it with
macOS `say`. No model, no network, no relay.

```bash
# One terminal:
venv/bin/python scripts/fake_relay.py

# Another:
venv/bin/python -m home_display.appliance --wake-enabled \
    --url ws://127.0.0.1:8799/voice-session --token stub
```

Everything except Hermes itself is real — the wake word, the microphone, the
websocket, playback, and the display. Useful flags: `--no-audio` for text only,
`--fail` to make every turn return an error, `--drop` to hang up mid-turn so
reconnection can be watched, and `--reply` to change what it says.

## Where the time actually goes

Measured against a live local gateway, one turn:

| Stage | Time |
|---|---|
| Silence before the utterance is considered finished | 1.2s |
| Transcription (`base` model, warm) | 0.7s |
| Turn sent → `audio_start` header | 0.1s |
| Header → first audible sample | ~2.2s |
| Speech delivered | real time, 1:1 with playback |

So roughly four seconds from your last word to the first of its. Response
audio is streamed and played chunk by chunk as it arrives — nothing waits for
the complete utterance at either end.

`audio_start` is a header, not a sound. The display enters `speaking` on the
first sample actually written to the device, not on the header, or it would
claim to be talking over two seconds of silence.

## If it feels slow to notice you have stopped

The delay between the last word and the reply is two things: a fixed wait for
silence, then transcription. The appliance waits 1.2s where the terminal
client waits 3s — three seconds of nothing happening in a kitchen reads as
broken. Transcription with the `base` model is around 0.7s once it is warm.

Tune with `--mic-silence-duration`. Lower it if the unit feels sluggish; raise
it if it cuts you off when you pause mid-sentence. A value in `config.yaml` or
`VOICE_SESSION_MIC_SILENCE_DURATION` overrides the hands-free default.

If the wait is much longer than that, it is transcription, not endpointing:
check `stt_model`. A larger model is slower per turn, and the very first turn
after a cold start also pays for loading it.

## What the display deliberately does not show

Hermes packs the model's chain-of-thought and the answer into one text frame —
a "💭 **Reasoning:**" marker and a fenced block, then the reply. The appliance
shows only the reply. If deliberation ever appears on the display, the marker
has changed shape and `display_text` needs updating.

Some gateways also send the response audio *before* the text. Text arriving
after playback has finished updates the words on screen without dragging the
state back to `thinking`.

A turn that streams as one word per line means the relay is sending append-only
chunks as `text_delta`, which the protocol defines as a *cumulative* preview.
That is a relay bug, not a client one.

## Verification evidence — 2026-09-01 (CDT)

- `venv/bin/pytest` — 401 passed (one pre-existing `websockets.legacy`
  deprecation warning).
- Checks 1 and 2 (wake to spoken answer, display matching the hardware): run
  against a live local Hermes gateway on loopback. Amanda confirmed a spoken
  answer with no keyboard; the display walked
  `idle → listening → thinking → speaking → idle`.
- Check 4 (connection loss and recovery): run against
  `scripts/fake_relay.py --drop`, which hangs up mid-turn. The display showed
  `disconnected`, reconnected on its own, and the next wake produced a
  complete turn with no restart of the appliance. The relay log confirmed two
  separate client connections.
- Check 3 (misfire timeout): run by Amanda, and it **found a bug**. The
  display showed `listening`, blinked, and showed it again before finally
  clearing. `--debug` recorded two "listening window expired" lines 8.3s
  apart: one spoken phrase produced two captures. The listener was paused
  only around the *connection*, never around a *turn*, so the detector still
  held the tail of the phrase in its rolling buffer and fired again the moment
  the microphone came free. The listener is now deaf for the duration of a
  turn, which is what `wake.WakeListener.pause` is for — it resets that
  buffer. Re-verified on the real microphone: capture at 3.00s pauses the
  listener, and it resumes at 11.11s when the unit returns to idle, with no
  second detection. Amanda re-ran the check afterwards and confirmed the
  blink is gone: all four checks pass.
- A misfire still holds `listening` for the full `--wake-listen-timeout` (8s
  by default) before clearing. That is the confirmed value for "long enough to
  turn off a tap and turn round", and is a tuning decision rather than a
  fault.

## What this slice does not cover

Barge-in stays off (`--wake-barge-in`) until HOME-05 delivers echo
cancellation: with the speaker feeding the microphone, the unit hears itself.
Idle photos are HOME-04, and appliance boot and recovery are HOME-06.
