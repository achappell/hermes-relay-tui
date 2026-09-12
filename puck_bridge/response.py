"""One in-flight spoken response, produced by a turn and consumed by the Puck.

The bridge plays Hermes' answer on the host today. To move it onto the
Puck, that audio has to become something the device can fetch over HTTP
while it is still being produced -- Hermes streams the answer, and waiting
for the whole thing before playing any of it would add the full length of
the answer to the latency.

This is the hand-off point: the turn writes PCM in as it arrives, the
`/response` handler reads it out, and neither knows about the other.

Two constraints come from ESPHome's own audio reader on the device
(`audio/audio_reader.cpp`), and they are the reason this class looks the
way it does rather than being a plain queue:

  * The reader FAILS a stream after ~30s without a successful read
    (MAX_FETCHING_HEADER_ATTEMPTS * CONNECTION_TIMEOUT_MS = 6 * 5000ms).
    So the response cannot sit idle waiting for Hermes to start speaking --
    every wait here is bounded well inside that.
  * A zero-length read is treated as a TIMEOUT, not as end-of-stream. The
    device detects the end via esp_http_client_is_complete_data_received(),
    so the body must be terminated definitively rather than by simply
    going quiet.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

logger = logging.getLogger("hermes_relay_tui.puck_bridge.response")

# How long a reader waits for the turn to declare an audio format before
# giving up. Hermes emits `audio_start` almost immediately (measured at
# 0.1s against the live relay), so this is generous -- but it stays well
# inside the device's ~30s no-read failure budget.
FORMAT_WAIT_SECONDS = 15.0

# How long a reader blocks for the next chunk before checking whether the
# producer has finished. Short, so `finish()` is noticed promptly; this is
# a poll interval, not a deadline.
CHUNK_POLL_SECONDS = 0.5

# Total silence a reader tolerates mid-stream before declaring the producer
# dead. Deliberately under the device's ~30s budget so the bridge ends the
# body cleanly rather than letting the device time the connection out --
# a definite short response beats an indefinite hang.
STREAM_STALL_SECONDS = 20.0


class ResponseStream:
    """Thread-safe single-response channel: one producer, one consumer."""

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._chunks: deque[bytes] = deque()
        self._audio_format: tuple[int, int, int] | None = None
        self._finished = False
        self._seq: int | None = None
        # Whether a turn is actually on its way. The device fetches
        # /response as soon as its upload is confirmed, which happens
        # BEFORE we know whether the capture produced a question at all --
        # an empty transcript runs no turn and yields no audio. Without
        # this the device sat waiting the full format budget for audio that
        # was never coming (observed 2026-09-11: three fetches, three
        # "nothing to stream" after a 15s wait each). Only the bridge can
        # know the difference, so it tells the device immediately.
        self._expecting = False
        # One consumer at a time. Two concurrent readers would each pop
        # from the same deque and split the answer between them, so both
        # would play garbage -- and the device was observed opening two
        # connections for a single response (ports 52539/52540 on
        # 2026-09-11), which is exactly that shape. A second reader is
        # refused rather than silently corrupting the first.
        self._reader_active = False

    # -- producer side (the turn) -----------------------------------------

    def expect(self, seq: int | None = None) -> bool:
        """Declare that a capture is being processed and audio may follow.

        Refuses while a reader is still streaming a previous answer, and
        returns False. Without that guard a second wake -- an ordinary
        follow-up question -- clobbered the shared stream mid-delivery:
        it cleared the queued tail of the previous answer, un-finished the
        stream so the active reader blocked for the full stall timeout
        instead of ending, and if the new turn then called begin() it
        appended the new answer's PCM to the old body under the OLD WAV
        header, while the device's fetch for the new one was refused 409.
        The caller decides what to do about a busy stream; this refuses to
        corrupt one.
        """
        with self._cv:
            if self._reader_active:
                return False
            self._expecting = True
            self._audio_format = None
            self._finished = False
            self._chunks.clear()
            self._seq = seq
            self._cv.notify_all()
            return True

    def abandon(self) -> None:
        """Declare that no audio is coming after all (no turn, or it failed).

        A no-op while a reader is active, for the mirror reason `expect()`
        refuses: a dropped or empty follow-up capture must not truncate an
        answer that is still being delivered.
        """
        with self._cv:
            if self._reader_active:
                return
            self._expecting = False
            self._finished = True
            self._cv.notify_all()

    @property
    def expecting(self) -> bool:
        with self._cv:
            return self._expecting


    @property
    def seq(self) -> int | None:
        with self._cv:
            return self._seq

    def begin(self, seq: int | None, audio_format: tuple[int, int, int]) -> None:
        """Declare the format and open the stream for writing."""
        with self._cv:
            self._chunks.clear()
            self._audio_format = audio_format
            self._finished = False
            self._seq = seq
            self._cv.notify_all()
        logger.debug("puck response stream opened seq=%s format=%s", seq, audio_format)

    def write(self, data: bytes) -> None:
        if not data:
            return
        with self._cv:
            self._chunks.append(data)
            self._cv.notify_all()

    def finish(self) -> None:
        """Mark the response complete. Idempotent.

        Also clears `_expecting`: a turn can finish WITHOUT ever declaring a
        format (a text-only reply, a TTS failure, a stream aborted before
        audio). Leaving `_expecting` set there left `wait_for_format`'s
        predicate unsatisfied, so the device waited the full format budget
        and got a 504 -- exactly the behaviour this class claims to have
        eliminated.
        """
        with self._cv:
            self._finished = True
            self._expecting = False
            self._cv.notify_all()

    @property
    def finished(self) -> bool:
        with self._cv:
            return self._finished

    # -- consumer side (the /response handler) -----------------------------

    def wait_for_format(
        self, timeout: float = FORMAT_WAIT_SECONDS
    ) -> tuple[int, int, int] | None:
        """Block until the turn declares an audio format, or give up.

        The WAV header cannot be written before this is known -- it carries
        the sample rate -- so this is the one unavoidable wait before the
        device receives any bytes.
        """
        with self._cv:
            if self._audio_format is not None:
                return self._audio_format
            # Nothing is coming: say so at once rather than making the
            # device wait out the whole budget for silence.
            if not self._expecting:
                return None
            self._cv.wait_for(
                lambda: self._audio_format is not None
                or not self._expecting
                or self._finished,
                timeout,
            )
            return self._audio_format

    def acquire_reader(self) -> bool:
        """Claim the single consumer slot. False if one is already active."""
        with self._cv:
            if self._reader_active:
                return False
            self._reader_active = True
            return True

    def release_reader(self) -> None:
        with self._cv:
            self._reader_active = False

    def iter_chunks(self, stall_timeout: float = STREAM_STALL_SECONDS):
        """Yield PCM chunks until the response finishes or the producer stalls.

        Ends the generator rather than raising on a stall: the consumer's
        job is to terminate the HTTP body definitively, and a short truthful
        response is better than an indefinite hang the device would have to
        time out itself.
        """
        # NEVER yield while holding _cv. The consumer's blocking socket
        # write happens during the yield, and the producer writes from the
        # asyncio event-loop thread -- so holding the lock across the yield
        # blocks the whole loop, including the very wait_for timeouts that
        # are supposed to catch a stalled turn. And because the device plays
        # in real time, TCP backpressure is the NORMAL case here, not an
        # edge case. Pop under the lock; yield outside it.
        last_progress = time.monotonic()
        while True:
            batch: list[bytes] = []
            with self._cv:
                while self._chunks:
                    batch.append(self._chunks.popleft())
                if not batch:
                    if self._finished:
                        return
                    self._cv.wait(CHUNK_POLL_SECONDS)
                    if self._chunks:
                        continue
                    if self._finished:
                        return
            if batch:
                last_progress = time.monotonic()
                for chunk in batch:
                    yield chunk
                continue
            # Measure elapsed time rather than counting poll iterations: a
            # notify_all() that adds no chunk (a concurrent expect/begin)
            # returns wait() early, so counting iterations charges the
            # budget for time that never passed and can declare a healthy
            # producer dead.
            if time.monotonic() - last_progress >= stall_timeout:
                logger.warning(
                    "puck response stream stalled for %.0fs with no audio; "
                    "ending the body so the device is not left waiting",
                    stall_timeout,
                )
                return


# A streaming WAV cannot know its length when the header is written. The
# device's decoder does not care: `micro_wav`'s wav_decoder.cpp validates
# only num_channels and sample_rate, copies `data_chunk_size_` into a
# uint32_t counter with NO validation, and stops decoding when the input
# runs out regardless of that counter. So a sentinel length streams
# correctly and neither a FLAC encoder nor buffer-then-serve is needed.
#
# 0xFFFFFFFF rather than 0: a zero-length data chunk would make the decoder
# stop immediately.
STREAMING_DATA_SIZE = 0xFFFFFFFF
STREAMING_RIFF_SIZE = 0xFFFFFFFF


def streaming_wav_header(audio_format: tuple[int, int, int]) -> bytes:
    """Build a 44-byte PCM WAV header for a stream of unknown length."""
    import struct

    sample_rate, channels, sample_width = audio_format
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    return (
        b"RIFF"
        + struct.pack("<I", STREAMING_RIFF_SIZE)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)          # PCM fmt chunk size
        + struct.pack("<H", 1)           # PCM
        + struct.pack("<H", channels)
        + struct.pack("<I", sample_rate)
        + struct.pack("<I", byte_rate)
        + struct.pack("<H", block_align)
        + struct.pack("<H", sample_width * 8)
        + b"data"
        + struct.pack("<I", STREAMING_DATA_SIZE)
    )
