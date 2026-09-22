"""One in-flight spoken response, produced by a turn and consumed by the Puck.

The bridge publishes Hermes' answer as something the device can fetch over HTTP
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

import hashlib
import logging
import struct
import threading
import time
from collections import deque
from typing import Callable

logger = logging.getLogger("hermes_relay_tui.puck_bridge.response")

# How long a reader waits for the turn to declare its first audio format before
# giving up. This is the same 20-second responsiveness budget used by the turn
# runner. Keeping the endpoint and producer on one budget matters: a valid
# first audio event arriving after one side has already given the Puck a 504
# is a silent delivery failure.
FIRST_AUDIO_TIMEOUT_SECONDS = 20.0
FORMAT_WAIT_SECONDS = FIRST_AUDIO_TIMEOUT_SECONDS

# How long a reader blocks for the next chunk before checking whether the
# producer has finished. Short, so `finish()` is noticed promptly; this is
# a poll interval, not a deadline.
CHUNK_POLL_SECONDS = 0.5

# How much audio to accumulate before releasing the first byte of PCM.
#
# Hermes produces TTS at roughly real time and the device consumes at
# exactly real time, so forwarding each chunk the instant it arrives leaves
# ZERO slack: any hesitation upstream starves the device's DAC and the
# answer comes out choppy (reported by ear 2026-09-12 -- every byte
# arrived, so this was never visible in the logs).
#
# `audio.py` already solved this for the TUI and documents the real
# behaviour: "Response audio is generated as it is spoken, so it arrives in
# fits... 379ms of audio every ~470ms." Near real time, but bursty -- so
# what is needed is jitter absorption, not a large deficit reserve. The TUI
# uses DEFAULT_PREBUFFER_SECONDS = 0.6 and plays smoothly.
#
# 1.5s rather than the TUI's 0.6s because this path has two extra sources
# of jitter the TUI does not: a WiFi hop, and on-device decode + resample.
# Deliberately still small -- it is added directly to the delay before the
# first word.
#
# (An earlier version of this comment claimed the producer runs at 64-75%
# of real time. That measurement started the clock at TURN start, so it
# counted Hermes thinking before any audio existed as generation time. It
# pointed at an architecture change that was not warranted.)
#
# Well inside the device's ~30s no-read failure budget.
PREBUFFER_SECONDS = 1.5

# Total silence a reader tolerates mid-stream before declaring the producer
# dead. Deliberately under the device's ~30s budget so the bridge ends the
# body cleanly rather than letting the device time the connection out --
# a definite short response beats an indefinite hang.
STREAM_STALL_SECONDS = 20.0

# The Puck is the real-time consumer. A producer that briefly outruns it may
# borrow ten source-seconds of memory, but never more. The producer waits in a
# worker thread when this fills; the Hermes event loop remains free to service
# the rest of the session.
MAX_QUEUED_PCM_BYTES = 480_000
MAX_QUEUE_CHUNK_BYTES = 16_384
TERMINAL_STATUS_TTL_SECONDS = 60.0


def _validate_audio_format(audio_format: tuple[int, int, int]) -> tuple[int, int, int]:
    """Validate the PCM dimensions before they reach WAV packing or metrics."""
    if not isinstance(audio_format, (tuple, list)) or len(audio_format) != 3:
        raise ValueError("audio format must be (sample_rate, channels, sample_width)")
    sample_rate, channels, sample_width = audio_format
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in (sample_rate, channels, sample_width)
    ):
        raise ValueError("audio format dimensions must be integers")
    if not 1 <= sample_width <= 4:
        raise ValueError("audio sample width must be between 1 and 4 bytes")
    if not 1 <= sample_rate <= 0xFFFFFFFF:
        raise ValueError("audio sample rate is out of range")
    if not 1 <= channels <= 0xFFFF:
        raise ValueError("audio channel count is out of range")
    if sample_rate * channels * sample_width > 0xFFFFFFFF:
        raise ValueError("audio byte rate is out of range")
    if channels * sample_width > 0xFFFF:
        raise ValueError("audio block alignment is out of range")
    return sample_rate, channels, sample_width


class ResponseStreamError(RuntimeError):
    """Base class for a response that can no longer accept PCM."""


class ResponseStreamBackpressure(ResponseStreamError):
    """The consumer did not make room before the bounded wait expired."""


class ResponseStream:
    """Thread-safe single-response channel: one producer, one consumer.

    Producer completion and delivery completion are deliberately separate.
    Hermes can finish while the Puck still has queued PCM; only the consumer
    may then promote the response to public ``complete`` status.
    """

    def __init__(
        self,
        *,
        max_queue_bytes: int = MAX_QUEUED_PCM_BYTES,
        stall_timeout: float = STREAM_STALL_SECONDS,
        clock: Callable[[], float] | None = None,
        device_build_identity: str = "unknown",
    ) -> None:
        if max_queue_bytes <= 0:
            raise ValueError("max_queue_bytes must be positive")
        if stall_timeout <= 0:
            raise ValueError("stall_timeout must be positive")
        self._cv = threading.Condition()
        self._shutdown = False
        self._clock = clock or time.monotonic
        self._chunks: deque[bytes] = deque()
        self._queued_bytes = 0
        self._queue_high_water = 0
        self._max_queue_bytes = max_queue_bytes
        self._stall_timeout = stall_timeout
        self._device_build_identity = device_build_identity
        self._audio_format: tuple[int, int, int] | None = None
        self._source_terminal: str | None = None
        self._delivery_terminal: str | None = None
        self._eof_pending = False
        self._terminal_at: float | None = None
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
        self._reader_seq: int | None = None
        self._source_bytes = 0
        self._source_hash = hashlib.sha256()
        self._delivered_bytes = 0
        self._delivered_hash = hashlib.sha256()
        self._response_started_at = self._clock()
        self._first_pcm_at: float | None = None
        self._last_source_progress = self._response_started_at
        self._last_consumer_progress = self._response_started_at
        self._producer_gap_max = 0.0
        self._stall_duration = 0.0
        self._terminal_reason: str | None = None
        self._response_ended_at: float | None = None

    # -- producer side (the turn) -----------------------------------------

    def shutdown(self) -> None:
        """Permanently close admission and wake all delivery waiters."""
        with self._cv:
            self._shutdown = True
            self._mark_unavailable_locked(reason="shutdown")
            self._cv.notify_all()

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
            if (
                self._shutdown
                or self._reader_active
                or self._expecting
                or self._eof_pending
            ):
                return False
            # A response that finished at Hermes but was never fetched has no
            # active reader left to release it. Once the next capture is
            # admitted, its queued tail is stale by definition; discard it
            # before resetting the owner so one lost fetch cannot poison every
            # later response.
            if self._queued_bytes and self._source_terminal != "complete":
                return False
            if seq is not None and self._seq is not None and seq <= self._seq:
                return False
            self._expecting = True
            self._audio_format = None
            self._source_terminal = None
            self._delivery_terminal = None
            self._eof_pending = False
            self._terminal_at = None
            self._terminal_reason = None
            self._response_ended_at = None
            self._clear_queue_locked()
            self._seq = seq
            self._reset_metrics_locked()
            self._cv.notify_all()
            return True

    def abandon(self, seq: int | None = None) -> bool:
        """Declare that no audio is coming after all (no turn, or it failed).

        A no-op while a reader is active, for the mirror reason `expect()`
        refuses: a dropped or empty follow-up capture must not truncate an
        answer that is still being delivered.
        """
        with self._cv:
            if (
                not self._matches_locked(seq)
                or self._reader_active
                or self._eof_pending
            ):
                return False
            return self._mark_unavailable_locked()

    @property
    def expecting(self) -> bool:
        with self._cv:
            return self._expecting


    @property
    def seq(self) -> int | None:
        with self._cv:
            return self._seq

    def begin(self, seq: int | None, audio_format: tuple[int, int, int]) -> None:
        """Declare the format and open the stream for writing.

        Hermes can split one answer into several audio segments. Every segment
        has an `audio_start`, but it is still one response for the Puck. Keep
        the existing queue and format when a later segment arrives; `expect()`
        is the operation that starts a genuinely new response and clears the
        old body.
        """
        audio_format = _validate_audio_format(audio_format)
        with self._cv:
            if self._shutdown:
                raise ResponseStreamError("response stream shut down")
            if self._seq is None:
                self._seq = seq
                self._expecting = True
                self._reset_metrics_locked()
            elif self._seq != seq:
                raise ValueError(
                    "response sequence changed while audio was streaming"
                )
            if self._source_terminal is not None or self._eof_pending:
                raise ResponseStreamError("response is already terminal")
            if self._audio_format is not None:
                if self._audio_format != audio_format:
                    raise ValueError(
                        "audio format changed between response segments"
                    )
                self._cv.notify_all()
                return
            self._audio_format = audio_format
            self._cv.notify_all()
        logger.debug("puck response stream opened seq=%s format=%s", seq, audio_format)

    def write(
        self,
        data: bytes,
        *,
        seq: int | None = None,
        timeout: float | None = None,
    ) -> bool:
        """Queue PCM without exceeding the byte bound.

        This method may wait for consumer progress. ``TurnRunner`` invokes it
        in ``asyncio.to_thread`` so the bounded wait never blocks Hermes' event
        loop. A late sequence is rejected without entering the next response.
        """
        if not data:
            return True
        with self._cv:
            if (
                not self._matches_locked(seq)
                or self._source_terminal is not None
                or self._eof_pending
            ):
                return False
            now = self._clock()
            producer_gap = max(0.0, now - self._last_source_progress)
            self._producer_gap_max = max(self._producer_gap_max, producer_gap)
            if producer_gap >= self._stall_timeout:
                self._stall_duration = max(self._stall_duration, producer_gap)
                self._mark_unavailable_locked(reason="producer_stall")
                return False
            self._source_bytes += len(data)
            self._source_hash.update(data)
            # Source progress is the arrival of a Hermes PCM event, not the
            # eventual queue insertion time. This keeps healthy backpressure
            # from looking like a producer stall while the writer waits for
            # the consumer to make room.
            self._last_source_progress = now
            wait_budget = self._stall_timeout if timeout is None else timeout
            last_consumer_progress = self._last_consumer_progress
            deadline = now + wait_budget
            offset = 0
            while offset < len(data):
                while self._queued_bytes >= self._max_queue_bytes:
                    if self._source_terminal is not None:
                        raise ResponseStreamError("response became terminal")
                    if self._last_consumer_progress != last_consumer_progress:
                        # The budget is for a lack of consumer progress, not
                        # for the total size of one producer write. A large
                        # Hermes frame may take several waits to fit while
                        # the reader is making healthy progress.
                        last_consumer_progress = self._last_consumer_progress
                        deadline = self._clock() + wait_budget
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        self._mark_unavailable_locked(reason="backpressure")
                        raise ResponseStreamBackpressure(
                            "response queue stayed full without consumer progress"
                        )
                    self._cv.wait(min(CHUNK_POLL_SECONDS, remaining))
                if self._source_terminal is not None:
                    raise ResponseStreamError("response became terminal")
                available = self._max_queue_bytes - self._queued_bytes
                size = min(
                    available,
                    MAX_QUEUE_CHUNK_BYTES,
                    len(data) - offset,
                )
                chunk = bytes(data[offset : offset + size])
                self._chunks.append(chunk)
                self._queued_bytes += len(chunk)
                self._queue_high_water = max(
                    self._queue_high_water, self._queued_bytes
                )
                if self._first_pcm_at is None:
                    self._first_pcm_at = self._clock()
                offset += len(chunk)
                self._cv.notify_all()
            return True

    def complete(self, seq: int | None = None) -> bool:
        """Mark Hermes' source complete; delivery still has to drain."""
        with self._cv:
            if (
                not self._matches_locked(seq)
                or self._delivery_terminal == "unavailable"
                or self._eof_pending
            ):
                return False
            if self._audio_format is None or self._source_bytes == 0:
                self._mark_unavailable_locked(reason="empty_source")
                return False
            if self._source_terminal is None:
                self._source_terminal = "complete"
                self._expecting = False
                self._cv.notify_all()
            return True

    def finish(self, seq: int | None = None) -> bool:
        """Compatibility alias for producer completion."""
        return self.complete(seq)

    def unavailable(
        self, seq: int | None = None, *, reason: str = "unavailable"
    ) -> bool:
        """Latch an unavailable response and discard queued PCM."""
        with self._cv:
            if not self._matches_locked(seq) or self._eof_pending:
                return False
            return self._mark_unavailable_locked(reason=reason)

    def _mark_unavailable_locked(self, *, reason: str = "unavailable") -> bool:
        if self._delivery_terminal == "complete":
            return False
        if self._delivery_terminal == "unavailable":
            return True
        self._source_terminal = "unavailable"
        self._delivery_terminal = "unavailable"
        self._eof_pending = False
        self._expecting = False
        self._clear_queue_locked()
        self._terminal_at = self._clock()
        self._response_ended_at = self._terminal_at
        self._terminal_reason = reason
        self._cv.notify_all()
        return True

    def _clear_queue_locked(self) -> None:
        self._chunks.clear()
        self._queued_bytes = 0

    def _reset_metrics_locked(self) -> None:
        self._source_bytes = 0
        self._source_hash = hashlib.sha256()
        self._delivered_bytes = 0
        self._delivered_hash = hashlib.sha256()
        self._response_started_at = self._clock()
        self._first_pcm_at = None
        self._last_source_progress = self._response_started_at
        self._last_consumer_progress = self._response_started_at
        self._queue_high_water = 0
        self._producer_gap_max = 0.0
        self._stall_duration = 0.0
        self._terminal_reason = None
        self._response_ended_at = None

    def _matches_locked(self, seq: int | None) -> bool:
        return seq is None or seq == self._seq

    @property
    def source_terminal(self) -> str | None:
        with self._cv:
            return self._source_terminal

    @property
    def terminal_status(self) -> str | None:
        with self._cv:
            return self._delivery_terminal

    @property
    def queued_bytes(self) -> int:
        with self._cv:
            return self._queued_bytes

    @property
    def queue_high_water(self) -> int:
        with self._cv:
            return self._queue_high_water

    def status_for(self, seq: int) -> str | None:
        """Return ``active`` or a retained terminal result for ``seq``."""
        with self._cv:
            if (
                self._terminal_at is not None
                and self._clock() - self._terminal_at
                > TERMINAL_STATUS_TTL_SECONDS
            ):
                self._seq = None
                self._source_terminal = None
                self._delivery_terminal = None
                self._terminal_at = None
                self._audio_format = None
                self._expecting = False
            if self._seq != seq:
                return None
            return self._delivery_terminal or "active"

    def acquire_reader(self, seq: int | None = None) -> bool:
        """Claim the single consumer slot for one sequence."""
        with self._cv:
            if (
                self._reader_active
                or not self._matches_locked(seq)
                or self._delivery_terminal is not None
            ):
                return False
            self._reader_active = True
            self._reader_seq = self._seq if seq is None else seq
            self._last_consumer_progress = self._clock()
            return True

    def release_reader(self) -> None:
        with self._cv:
            self._reader_active = False
            self._reader_seq = None
            self._cv.notify_all()

    def mark_delivery_complete(self, seq: int | None = None) -> bool:
        """Latch public ``complete`` only after the queue is drained."""
        with self._cv:
            if (
                not self._matches_locked(seq)
                or self._source_terminal != "complete"
                or self._queued_bytes
                or self._delivery_terminal == "unavailable"
                or not self._eof_pending
            ):
                return False
            if (
                self._delivered_bytes != self._source_bytes
                or self._delivered_hash.digest() != self._source_hash.digest()
            ):
                self._mark_unavailable_locked(reason="delivery_accounting")
                return False
            self._delivery_terminal = "complete"
            self._eof_pending = False
            self._terminal_at = self._clock()
            self._response_ended_at = self._terminal_at
            self._terminal_reason = "complete"
            self._expecting = False
            self._cv.notify_all()
            return True

    def ready_for_eof(self, seq: int | None = None) -> bool:
        """Reserve the right to emit chunked EOF for this response.

        The reservation is made while holding the response lock. The handler
        writes the zero chunk immediately afterwards, outside the lock so a
        socket write cannot block the producer. While the reservation is
        pending, a concurrent failure cannot silently downgrade the stream
        underneath a success terminator; the handler must call
        ``fail_delivery`` if that write fails.
        """
        with self._cv:
            if self._eof_pending:
                return self._matches_locked(seq)
            ready = (
                self._matches_locked(seq)
                and self._source_terminal == "complete"
                and not self._queued_bytes
                and self._delivery_terminal is None
            )
            if not ready:
                return False
            if (
                self._delivered_bytes != self._source_bytes
                or self._delivered_hash.digest() != self._source_hash.digest()
            ):
                self._mark_unavailable_locked(reason="delivery_accounting")
                return False
            self._eof_pending = True
            self._cv.notify_all()
            return True

    def fail_delivery(
        self, seq: int | None = None, *, reason: str = "delivery_failure"
    ) -> bool:
        """Abort a reserved EOF, or fail an in-progress delivery.

        ``unavailable()`` refuses to race a reserved EOF because doing so
        would leave the consumer free to emit a success terminator anyway.
        The response handler uses this method when its final socket write
        fails, which clears that reservation and makes the failure
        authoritative.
        """
        with self._cv:
            if not self._matches_locked(seq):
                return False
            self._eof_pending = False
            return self._mark_unavailable_locked(reason=reason)

    def record_delivered(self, data: bytes, seq: int | None = None) -> bool:
        """Account PCM only after its HTTP frame was written successfully."""
        if not data:
            return True
        with self._cv:
            if not self._matches_locked(seq):
                return False
            if self._delivery_terminal is not None or self._eof_pending:
                return False
            self._delivered_bytes += len(data)
            self._delivered_hash.update(data)
            self._last_consumer_progress = self._clock()
            return True

    def metrics(self) -> dict[str, object]:
        """Return bounded, content-safe delivery metrics for one sequence."""
        with self._cv:
            now = self._clock()
            response_ended_at = self._response_ended_at or now
            source_duration = self._source_bytes / self._bytes_per_second_locked()
            delivered_duration = (
                self._delivered_bytes / self._bytes_per_second_locked()
            )
            consumer_elapsed = max(
                0.0,
                response_ended_at
                - (self._first_pcm_at or self._response_started_at),
            )
            return {
                "seq": self._seq,
                "device_build_identity": self._device_build_identity,
                "audio_format": self._audio_format,
                "source_bytes": self._source_bytes,
                "source_duration_seconds": source_duration,
                "source_sha256": self._source_hash.hexdigest(),
                "delivered_bytes": self._delivered_bytes,
                "delivered_duration_seconds": delivered_duration,
                "delivered_sha256": self._delivered_hash.hexdigest(),
                "first_pcm_seconds": (
                    self._first_pcm_at - self._response_started_at
                    if self._first_pcm_at is not None
                    else None
                ),
                "producer_gap_seconds": max(
                    0.0, now - self._last_source_progress
                ),
                "producer_gap_max_seconds": self._producer_gap_max,
                "consumer_gap_seconds": max(
                    0.0, now - self._last_consumer_progress
                ),
                "consumer_rate_bytes_per_second": (
                    self._delivered_bytes / consumer_elapsed
                    if consumer_elapsed > 0
                    else 0.0
                ),
                "stall_duration_seconds": self._stall_duration,
                "response_duration_seconds": max(
                    0.0, response_ended_at - self._response_started_at
                ),
                "queued_bytes": self._queued_bytes,
                "queue_high_water": self._queue_high_water,
                "terminal": self._delivery_terminal or self._source_terminal,
                "terminal_reason": self._terminal_reason,
            }

    def _bytes_per_second_locked(self) -> float:
        if self._audio_format is None:
            return 1.0
        sample_rate, channels, sample_width = self._audio_format
        return float(sample_rate * channels * sample_width)

    @property
    def finished(self) -> bool:
        with self._cv:
            return self._source_terminal is not None

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
                or self._source_terminal is not None,
                timeout,
            )
            return self._audio_format

    def wait_for_prebuffer(
        self, audio_format: tuple[int, int, int], seconds: float = PREBUFFER_SECONDS
    ) -> bool:
        """Block until `seconds` of audio is queued, or the turn finishes.

        Gives the device a cushion to start playback with. Returns early if
        the answer is shorter than the prebuffer -- a two-word reply must
        not wait for audio that will never exist.
        """
        sample_rate, channels, width = audio_format
        target = min(
            int(sample_rate * channels * width * seconds),
            self._max_queue_bytes,
        )
        if target <= 0:
            return True
        with self._cv:
            last_source_progress = self._last_source_progress
            while self._source_terminal is None and self._queued_bytes < target:
                remaining = self._stall_timeout - (
                    self._clock() - last_source_progress
                )
                if remaining <= 0:
                    self._stall_duration = max(
                        self._stall_duration, self._stall_timeout
                    )
                    self._mark_unavailable_locked(reason="producer_stall")
                    logger.warning(
                        "puck response prebuffer stalled for %.0fs; "
                        "ending the body as unavailable",
                        self._stall_timeout,
                    )
                    return False
                self._cv.wait(min(CHUNK_POLL_SECONDS, remaining))
                if self._last_source_progress != last_source_progress:
                    last_source_progress = self._last_source_progress
            return self._source_terminal != "unavailable"

    def iter_chunks(self, stall_timeout: float | None = None):
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
        timeout = self._stall_timeout if stall_timeout is None else stall_timeout
        while True:
            chunk: bytes | None = None
            with self._cv:
                if self._chunks:
                    if self._source_terminal is None:
                        remaining = timeout - (
                            self._clock() - self._last_source_progress
                        )
                        if remaining <= 0:
                            self._stall_duration = max(
                                self._stall_duration,
                                self._clock() - self._last_source_progress,
                            )
                            self._mark_unavailable_locked(reason="producer_stall")
                            logger.warning(
                                "puck response stream stalled for %.0fs; "
                                "ending the body as unavailable",
                                timeout,
                            )
                            return
                    chunk = self._chunks.popleft()
                    self._queued_bytes -= len(chunk)
                    self._last_consumer_progress = self._clock()
                    self._cv.notify_all()
                else:
                    if self._source_terminal is not None:
                        return
                    remaining = timeout - (
                        self._clock() - self._last_source_progress
                    )
                    if remaining <= 0:
                        self._stall_duration = max(
                            self._stall_duration,
                            self._clock() - self._last_source_progress,
                        )
                        self._mark_unavailable_locked(reason="producer_stall")
                        logger.warning(
                            "puck response stream stalled for %.0fs; "
                            "ending the body as unavailable",
                            timeout,
                        )
                        return
                    self._cv.wait(min(CHUNK_POLL_SECONDS, remaining))
                    continue
            if chunk is not None:
                yield chunk


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
    sample_rate, channels, sample_width = _validate_audio_format(audio_format)
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
