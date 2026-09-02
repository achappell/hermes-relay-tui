# HOME-09 appliance loop smoke procedure

This is the first procedure that needs the real thing: a microphone, a speaker,
and a live Hermes relay. It answers one question — does saying the phrase in the
room produce a spoken answer, with the screen telling the truth throughout.

The HOME-03 procedure covers the display shell on its own; run that first if the
browser assets have changed.

## Prerequisites

```bash
venv/bin/pip install -e '.[home]'
npm --prefix home_display/web run build   # only if the shell has changed
```

The `home` extra brings the wake-word engine. Without it the appliance reports
the missing dependency and exits rather than starting deaf.

A token must be resolvable: `--token`, `VOICE_SESSION_TOKEN`, or the profile
`.env`. Grant the terminal microphone permission in System Settings → Privacy &
Security → Microphone.

## Run it

```bash
venv/bin/hermes-relay-home --wake-enabled
```

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
venv/bin/hermes-relay-home --wake-enabled \
    --url ws://127.0.0.1:8799/voice-session --token stub
```

Everything except Hermes itself is real — the wake word, the microphone, the
websocket, playback, and the display. Useful flags: `--no-audio` for text only,
`--fail` to make every turn return an error, `--drop` to hang up mid-turn so
reconnection can be watched, and `--reply` to change what it says.

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

## What this slice does not cover

Barge-in stays off (`--wake-barge-in`) until HOME-05 delivers echo
cancellation: with the speaker feeding the microphone, the unit hears itself.
Idle photos are HOME-04, and appliance boot and recovery are HOME-06.
