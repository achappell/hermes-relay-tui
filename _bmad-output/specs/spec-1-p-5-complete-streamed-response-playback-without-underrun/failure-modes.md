# P-5 failure modes

This companion defines the outcomes P-5 must preserve or make explicit. The Puck remains an audio/status-only doorway; text, profile authority, and session semantics stay outside this playback slice.

## Current evidence

- The same authenticated `/response` source produced 303,148 bytes through `curl`, while the device stopped at 127,232 bytes.
- A controlled 20-second, 960 KB probe completed through both fixed-length transfer with `Content-Length` and chunked transfer with a sentinel WAV data length. Framing and the unknown streaming-WAV length are therefore not the current failure explanation.
- The captured response is structurally valid 24 kHz mono signed 16-bit WAV with real speech. The device stopped cleanly rather than reporting an explicit playback error.
- A probe that sent 100 ms of audio every 90 ms, approximately 11% faster than real time, completed without running dry. The live bridge forwards Hermes chunks as they arrive, so producer/consumer pacing remains the working diagnosis.
- A two-second prebuffer did not fix the observed cut; an eight-second prebuffer resulted in zero delivered bytes because the device waited for data until its reader timed out. Prebuffer size is not a sufficient control by itself.
- The ESPHome reader needs a prompt header and a definitive body terminator: a zero-length read is treated as timeout, and roughly 30 seconds without a successful read ends the stream. A response cannot wait indefinitely before its first body bytes or rely on an empty read to signal EOF.
- Reducing per-inference wake diagnostics from roughly 47 log lines per second to one reduced ring-buffer overflows from roughly 40 in 30 seconds to zero. This is an already-delivered starvation fix, not the P-5 solution.
- `puck_bridge/response.py` currently allows the producer to append without a memory limit while the Puck controls consumer pace. Queue policy and backpressure therefore belong in P-5.

## Required outcomes

| Condition | Required device/bridge behavior | Proof |
|---|---|---|
| Normal live-paced response | Record Hermes completion, drain every segment and queued PCM through successful EOF; do not enter `IDLE` early or discard queued audio. | Normalized source/delivered PCM byte counts and SHA-256 plus audible hardware completion. |
| Fixed-length response | Decode and play the full body. | Controlled probe and focused regression test. |
| Chunked response | Decode and play the full body, including the streaming WAV sentinel length. | Controlled probe and focused regression test. |
| Temporary producer gap | For an active sequence, keep queued PCM within 480,000 bytes, apply asynchronous backpressure without dropping or replaying audio, and keep gaps under 20 seconds alive without EOF. | Timed 19.9-second gap fixture with recorded buffer and terminal outcome. |
| Genuine stream failure or stalled consumer | Before headers, return an HTTP error; after streaming begins, make authenticated `GET /response-status?seq=N` report `unavailable`, stop safely, keep output quiet, and release the response slot. A 20.0-second-or-longer gap or full queue with no consumer progress becomes unavailable. | Fault-injection tests at 20.0 and 20.1 seconds plus controlled device run. |
| Response failure followed by another response | Start with isolated state and no stale bytes, clipped prior stream, inherited failure, or stale status result. | Two-response sequential fixture and hardware retry. |
| Duplicate or stale fetch | Keep one response owner and do not replay an uncertain response. | Existing sequence/single-consumer tests remain green. |

The firmware media-player task owns playback. Speaker startup must yield to the component lifecycle; a synchronous automation wait or main-loop audio write is a failure mode, not a pacing fix.

## Forbidden outcomes

- Returning to `IDLE` with no error while valid response audio remains undelivered.
- Silently truncating, replaying, or mixing response bytes across sequence IDs.
- Fixing the underrun by allowing unbounded response memory or retaining raw household audio.
- Making the Puck speak a locally invented explanation in place of an unavailable/error state.
