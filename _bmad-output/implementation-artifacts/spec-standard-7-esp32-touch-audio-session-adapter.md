---
id: STANDARD-7-ESP32
title: Add the ESP32 Touch audio and session adapter
type: feature
created: 2026-09-17
baseline_commit: a197548f571244e660ffe218e5c54ebfe3b0a1e6
status: draft
route: dispatch
review_loop_iteration: 0
github_issue: https://github.com/achappell/hermes-relay-tui/issues/184
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-standard-3-tui-migrate-terminal-client.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Touch firmware receives display snapshots and sends actions, but no bounded microphone-audio path reaches its Home session. The selected audio hardware uses a separate C6 controller.

**Approach:** After device admission and a ready Home conversation binding, the Media Server accepts bounded transient PCM, transcribes it locally, submits one final transcript through the bound `HomeBrowserSession`, and returns observed state and response PCM to that doorway. Hermes credentials and session authority stay behind Home. An endpoint may hold its own revocable Device credential only through approved secure storage.

## Boundaries & Constraints

- Frame each capture as JSON `mic_start`, binary PCM chunks up to 4 KiB, then `mic_end` or `mic_abort`, all with one capture ID. PCM is 16 kHz mono signed-16 little-endian, at most 15 seconds or 480,000 bytes, one capture at a time.
- Keep PCM and transcripts transient; publish transcript separately from assistant response text; clear both on abort, malformed input, timeout, STT failure, or disconnect. Final transcript limit: 4,000 characters. Never log credentials, handles, transcripts, or PCM; never persist Hermes credentials, conversation handles, or raw audio. Fail closed if approved Device-credential storage is unavailable.
- Home transcribes and submits one final prompt through the bound session. Never retry an uncertain prompt. A confirmed accepted turn may resume only on its existing Home session. Firmware does not open Hermes sessions or parse Hermes events.
- Send response PCM only to the owning doorway and preserve sample metadata; convert for the mono speaker only at audio output. Do not report `speaking` before playback starts; interruption remains pending until Home's terminal event.

## I/O & Edge Cases

| Case | Required behavior |
|---|---|
| Valid capture | Show capture/transcribing, then submit one non-empty transcript through the ready Home binding. |
| Unauthorized, malformed, duplicate, late, or oversized input | Reject, clear transient data, and create no Home turn. |
| Abort, empty transcript, or STT failure | Clear audio and transcript; submit nothing. |
| Disconnect or uncertain submit | Discard unsubmitted capture; never replay a possibly accepted prompt. Resume only the accepted turn on the same Home session; a new device socket needs fresh initiation. |
| Stop or playback failure | Wait for Home's terminal interruption event; preserve completed text and report unavailable audio when playback fails. |

</frozen-after-approval>

## Resolved Direction

- The Waveshare ESP32-S3-Touch-LCD-7B (SKU 31726) is the only networked Touch
  endpoint and the only device with Home identity. The kitchen C6 is a local
  audio peripheral for the INMP441 microphone and MAX98357A mono amplifier;
  it has no Home identity, network session, or Hermes session.
- Start with tap-to-talk. Home must admit the S3 and bind it to a ready
  Room/Profile conversation before the C6 opens the microphone. Wake listening
  and follow-up belong to later work.
- The Media Server's Python adapter owns speech-to-text, Home session use,
  uncertain-submit/no-replay handling, observed phase/state, and response PCM.
  `home_display` terminates S3 PCM, transcribes it in memory, and submits one
  final transcript through the already-bound `HomeBrowserSession`; it does not
  add microphone frames to the Home bridge or Hermes protocol. The S3 never
  receives Hermes credentials or parses Hermes events.
- STD-7 transcribes only after capture ends and returns one final transcript;
  it does not stream partial hypotheses. The later `2-E-2` slice owns
  live-word updates.
- Approved bounds: 16 kHz mono signed-16 little-endian PCM, 4 KiB maximum
  binary message, 15 seconds / 480,000 bytes per capture, and 4,000 transcript
  characters. Permit one active capture and one active Home turn per admitted
  socket; allow later captures on that binding after the preceding turn ends.

## Proposed Contract

### Admission and capture framing

- A Home-owned Touch admission step must bind the S3's revocable Device identity
  to its approved Room/Profile and an opaque conversation handle. `/state`
  origin checks are not device admission. An unauthenticated or unbound socket
  cannot open a microphone or submit audio. Do not create its privileged
  `HomeBrowserSession` context until Home admission returns ready.
- On a user tap, the S3 sends `mic_start` JSON with `schema: 1` and a bounded,
  per-capture `capture_id`. The host returns `mic_ready` only after admission
  and Home session readiness succeed; otherwise it returns a safe
  `mic_reject` reason. The S3 commands the C6 to open the mic only after
  `mic_ready`.
- After `mic_ready`, the S3 sends ordered WebSocket binary messages of raw
  16 kHz, mono, signed 16-bit little-endian PCM. Each message is at most 4 KiB;
  each capture is at most 15 seconds (480,000 bytes). Binary messages belong
  to the single active capture on that socket. `mic_end` or `mic_abort` JSON
  must carry the same `capture_id`. Reject orphan, stale, duplicate,
  out-of-order, odd-length, malformed, or oversized input and clear its buffer.
- Permit one active capture and one active Home turn per admitted socket. After
  Home reports a terminal turn event, allow another tap-to-talk capture on the
  same ready binding. Each capture can create at most one Home turn. Keep PCM
  and final transcript in memory only. Transcribe after `mic_end`, with a
  4,000-character transcript ceiling; do not create a WAV file as an
  intermediate. Empty speech, abort, timeout, malformed input, STT failure, or
  disconnect creates no Home turn.
- Submit one non-empty final transcript once. If submission outcome is
  uncertain, never retry it. The Home session may recover its own upstream
  transport while this S3 socket remains open; losing the S3 `/state` socket
  closes its binding, discards the capture, and requires fresh admission and
  explicit initiation on a new socket.

### State and response audio

- Keep `DisplaySnapshot` as presentation state, separate from audio/session
  controls. Add a distinct optional `transcript_text` field and a `transcribing`
  state; keep assistant output in `response_text`. This story returns only the
  final transcript. The later `2-E-2` story owns partial/live-word updates.
- Use observed phases only: show `heard` after Home authorizes the capture,
  `listening` after the C6 reports capture started, `transcribing` after
  `mic_end`, then `thinking` after transcript acceptance. Show `speaking` only
  after the C6 reports that speaker playback has begun. Preserve completed
  response text when audio is unavailable.
- Stream response audio only to the owning S3 socket using the existing
  `audio_start` JSON metadata (`turn_id`, sample rate, channels, sample width),
  raw binary PCM, and `audio_end` or `audio_abort`. Preserve metadata through
  the S3/C6 handoff; the C6 converts to its mono speaker format at output.
- Before transcript acceptance, stop sends `mic_abort`. During Home submission,
  latch at most one stop request and send one Home interrupt once the accepted
  turn ID is known, if Home advertises that capability. Keep the display in a
  pending state until Home's terminal event. If interruption is unsupported or
  declined, report that honestly without claiming the turn stopped.

## Prerequisites & Sequence

1. **Home-owned Touch admission and explicit initiation.** *Assigned
   2026-09-21 as **HOME-NW-16** — "Admit Touch panels and grant bound
   tap-to-talk claims" (`hermes-relay-home` issue #48), status
   `ready-for-dev`.* HOME-NW-05 is done, but it grants `wake_claim` mappings
   and defines no tap-to-talk claim for the Touch S3. NW-16 adds
   `POST /api/v1/touch-claims`: a separate non-acoustic route with its own
   `touch_claim` capability and a Room/Profile binding fixed in credential
   scope, granting synchronously and returning a ready opaque handle. Each
   admitted S3 session is bound to one preconfigured, Home-approved
   Room/Profile; the display has no Profile picker. Room contention is decided:
   a tap into a live Room (capture, turn, or playback outstanding) is denied
   `room_busy`; a tap into a Room whose claim is only in its 8-second idle tail
   supersedes it. Still open in this repository: the current `/state` handler
   creates a Home context before device admission and must not, and the
   host-owned STT path still needs reconciling with `hermes-relay-home`'s
   bridge-route spec, which assigns mic/STT to the endpoint. Home owns NW-16's
   record and status; this spec does not track it.
2. **C6 physical interface.** *Resolved 2026-09-21; see Personal Vault
   `projects/hermes/Hermes - Smart Display Hardware.md`.* The kitchen board is
   an ACEIRMC **ESP32-C6 Super Mini** (ESP32-C6FH4, 4MB flash), already on
   hand. The S3/C6 link is the 7B's **UART2 header at 921600 baud**, because
   the link carries audio rather than commands alone: the C6 owns the
   microphone and amplifier while the S3 owns Wi-Fi, so capture PCM runs
   C6 → S3 → network at a sustained 256 kbps with response playback on top.
   UART is full-duplex on separate conductors, giving each direction roughly
   92,000 bytes/sec against a 32,000 byte/sec capture load.

   **SPI is not available on this board and must not be specified.** The 7B
   breaks out only five GPIO in total — GPIO6, GPIO8/9 (the I²C header,
   already carrying the touch controller and CH422G expander), and GPIO43/44
   (the UART2 header). The RGB parallel LCD consumes the rest, and the RS-485
   and CAN connectors expose transceiver lines rather than raw GPIO.

   Pin map — I²S BCLK GPIO0, WS/LRCLK GPIO1, mic data-in GPIO2, amp data-out
   GPIO3 on the C6; link S3 GPIO43 (TX) → C6 GPIO19 (RX) and S3 GPIO44 (RX) ←
   C6 GPIO18 (TX), crossed; reset S3 GPIO6 → C6 RST; C6 GPIO14, 20, 21, 22 and
   23 spare. The C6's UART is mapped to GPIO18/19 through the GPIO matrix
   rather than its native GPIO16/17, keeping the C6's own console free. All
   avoid the C6's strapping/JTAG pins (GPIO4–9, 15) and USB pair
   (GPIO12–13). Because GPIO43/44 are the S3's console UART behind the
   onboard slide switch, S3 debug logging moves to native USB-CDC. Verify
   against the board silkscreen at bring-up. Still owned by this story: the
   UART frame format carrying `mic_start`/`mic_end`/`mic_abort` and status
   alongside PCM, and its failure behavior — C6 unresponsive, buffer overrun,
   playback failure — for which the reset line is the recovery action. Do not
   reuse the voice-puck C6 plan.
3. **STD-7 implementation.** Both prerequisites above are now settled as
   selections and contracts; NW-16 must be *implemented* in Home before a live
   admitted capture can be demonstrated end to end, but the host adapter, S3
   transport, and UART framing can be built against the agreed contract in
   parallel. Follow with the local `1-E-1` through `1-E-5` doorway acceptance
   work. `2-E-2` remains the later live-transcription acceptance slice.

Delivered foundations: HOME-NW-02/03/05, STD-3, and the private per-connection
Home-session/audio sender from STD-8. The Touch admission and C6
physical-interface prerequisites are now specified but not yet built.

## Home-Owned Predecessor

Amanda selected one preconfigured Home-approved Room/Profile per admitted S3
session, with no on-device Profile picker. That tap-to-talk claim is now
specified as **HOME-NW-16** (`hermes-relay-home` issue #48), which returns a
ready opaque binding before capture; HOME-NW-05 binds wake claims to mappings
and does not define this flow. Do not expose arbitrary Profile or Session IDs
to firmware. NW-16 is specified and `ready-for-dev`, not implemented — a live
admitted capture cannot be demonstrated until it lands.

## Code Map

- `home_display/server.py`: per-`/state` private response-audio sender exists;
  binary microphone ingress and device admission do not. The handler currently
  creates a browser context when the socket connects.
- `home_display/appliance.py` and `puck_bridge/home_session.py`: Home session,
  text submission, turn interruption, and response PCM; interrupt capability
  may be absent, and the accepted turn ID is not available until submit returns.
- `voice.py`: local faster-whisper transcription currently reads a WAV path;
  implement a bounded in-memory PCM entry point.
- `home_display/state.py`, `shared/display/`, and firmware snapshots have no
  `transcribing` state or separate user-transcript field. `ui_transport.c`
  handles text JSON only; `main.c` queues UI updates outside LVGL callbacks.
- `board_config.h` covers only the S3; the SDL simulator excludes WebSocket,
  C6 wiring, microphone capture, and speaker playback. Add the S3-side UART2
  and reset pins for the C6 link, and keep the simulator honest about which of
  these it cannot exercise.

## Tasks & Acceptance

**Execution:**
- [ ] Add admitted per-connection PCM framing, bounds, teardown, and host tests.
- [ ] Add in-memory STT, isolated final transcript state, one Home submit, and
      Home-owned no-replay/interruption handling.
- [ ] Extend shared state and S3 binary transport; define the UART frame format
      and failure behavior for the S3/C6 link, including reset-line recovery,
      then integrate the C6.
- [ ] Verify bounds, authorization, connection isolation, stop races, uncertain
      submit, and audio failure; record simulator, build, and hardware evidence
      separately.

**Acceptance:**
- Mic capture cannot start before a ready, admitted Home binding is returned.
- A valid capture produces one final transcript and at most one Home turn;
  invalid, empty, or aborted audio produces none.
- PCM and transcripts are transient; transcript and assistant response text
  are separate; response PCM reaches only the owning doorway.
- Disconnect and uncertain submission never replay a turn. Stop remains
  pending until Home confirms a terminal event or reports interruption
  unavailable.
- Phases remain honest through transcription, playback start/failure, and
  disconnect. Evidence distinguishes simulator rendering from S3 transport
  and physical C6 audio behavior.

## Design Notes

Hardware source: Personal Vault, `projects/hermes/Hermes - Smart Display
Hardware.md`. Home claim source: `hermes-relay-home` HOME-NW-05 and the current
bridge-route-roaming spec; their Touch admission and STT ownership gaps are
listed above rather than assumed solved.

## Verification

- `venv/bin/pytest -q tests/test_home_display_server.py tests/test_home_appliance.py tests/test_home_display_state.py tests/test_firmware_transport.py tests/test_firmware_ui.py`
- `venv/bin/pytest`
- `./scripts/simulate_native.sh`
- `pio run -d firmware/esp32-s3-touch-lcd-7`
- On physical hardware, verify admitted capture, mono playback, stop, and no
  replay after disconnect. Simulator evidence does not prove audio or wiring.
