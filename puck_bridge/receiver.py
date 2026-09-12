"""Chunked-upload HTTP receiver for one Puck wake-triggered audio capture.

Matches `firmware/respeaker-lite/tools/receiver.py`'s wire shape exactly
(`POST /upload?seq=N&chunk=C&total=T`, `UPLOAD_CHUNK_BYTES`-sized bodies --
see `pcm_capture.h`), so this is a drop-in host-side successor for that
training-data receiver's protocol, not a new one. Adds the hardcoded-token
header check this story stands in for Story 4's real per-device credential
system, and -- once every chunk for a sequence has arrived -- converts the
reassembled raw PCM into a mono 16kHz WAV using the exact
Q31->Q25->gain->16-bit conversion already validated in
`firmware/respeaker-lite/tools/label_captures.py`'s
`process_frame_sample()`, then hands it to `voice.py:transcribe()`
unchanged.

Raw audio stays transient (NFR3): the in-memory chunk buffer for a sequence
is discarded as soon as it is reassembled, and the WAV file is deleted
immediately after transcription, success or failure.
"""

from __future__ import annotations

import http.server
import logging
import os
import socketserver
import struct
import tempfile
import threading
import time
import wave
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .response import ResponseStream, streaming_wav_header

logger = logging.getLogger("hermes_relay_tui.puck_bridge.receiver")

# Must match pcm_capture.h's UPLOAD_CHUNK_BYTES. Only used here as a sanity
# hint in logs -- the receiver reassembles by declared chunk index, not by
# assuming every chunk is exactly this size (the last chunk of a capture is
# usually shorter). Restored to 16000 alongside the firmware constant once
# the Puck was relocated to a strong signal -- see pcm_capture.h's comment
# for the full history, including why it was temporarily 2000.
UPLOAD_CHUNK_BYTES = 16000

# The raw capture is stereo, 32-bit, 16kHz -- the exact format
# MicrophoneSource hands to micro_wake_word before any of its own
# processing. Channel/gain constants match respeaker-lite.yaml's
# `micro_wake_word: microphone: channels: 1` / `gain_factor: 4`.
SOURCE_CHANNELS = 2
CHANNEL_INDEX = 1
GAIN_FACTOR = 4
SOURCE_SAMPLE_RATE = 16000
BYTES_PER_FRAME = SOURCE_CHANNELS * 4
Q25_MAX = (1 << 25) - 1
Q25_MIN = ~Q25_MAX

import re as _re

_TOKEN_IN_URL = _re.compile(r"([?&]token=)[^&\s]+")


def _redact_token(text: str) -> str:
    """Blank a `token=` query value so credentials do not reach the logs."""
    return _TOKEN_IN_URL.sub(r"\1REDACTED", text)


TOKEN_HEADER = "X-Puck-Token"
UPLOAD_PATH = "/upload"
RESPONSE_PATH = "/response"


def process_frame_sample(raw4: bytes) -> int:
    """Byte-for-byte match of `label_captures.py`'s per-sample conversion.

    Replicates `MicrophoneSource::process_audio_()`: channel select, Q31 ->
    Q25, multiply by the configured gain, clamp, Q25 -> Q31, take the top 16
    bits. Kept in lockstep with that file rather than imported from it --
    the firmware tool has no reason to depend on this package, or vice
    versa.
    """
    sample = int.from_bytes(raw4, byteorder="little", signed=True)  # Q31
    sample >>= 6  # Q31 -> Q25 (arithmetic shift, matches GCC on ESP32)
    sample *= GAIN_FACTOR  # Q25
    sample = max(Q25_MIN, min(Q25_MAX, sample))  # clamp
    sample *= 1 << 6  # Q25 -> Q31
    sample32 = sample & 0xFFFFFFFF
    out16 = (sample32 >> 16) & 0xFFFF  # top 16 bits
    if out16 >= 0x8000:
        out16 -= 0x10000
    return out16


def raw_stereo32_to_wav(raw: bytes, wav_path: str) -> int:
    """Convert one raw stereo/32-bit/16kHz capture into a mono 16-bit WAV.

    Returns the number of source frames converted.
    """
    if len(raw) % BYTES_PER_FRAME != 0:
        logger.warning(
            "puck bridge capture has a trailing partial frame: %d bytes is "
            "not a multiple of %d bytes/frame; dropping the remainder",
            len(raw),
            BYTES_PER_FRAME,
        )
    n_frames = len(raw) // BYTES_PER_FRAME
    samples = bytearray()
    for index in range(n_frames):
        base = index * BYTES_PER_FRAME + CHANNEL_INDEX * 4
        out16 = process_frame_sample(raw[base : base + 4])
        samples += struct.pack("<h", out16)
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SOURCE_SAMPLE_RATE)
        wf.writeframes(bytes(samples))
    return n_frames


# How long an incomplete capture may sit in `captures` before it is treated
# as abandoned and evicted. A Puck that stops mid-upload (crash, wedged
# esp_http_client, dropped WiFi) must never leave its raw audio sitting in
# memory indefinitely -- that would violate NFR3's "raw Puck audio stays
# transient" for the one path (an incomplete sequence) the happy-path
# reassemble-then-pop in `do_POST` never touches.
PENDING_CAPTURE_TTL_SECONDS = 30.0


class _PendingCapture:
    """Chunks for one in-flight `seq`, reassembled once `total` arrive."""

    __slots__ = ("chunks", "total", "created_at")

    def __init__(self, total: int) -> None:
        self.chunks: dict[int, bytes] = {}
        self.total = total
        self.created_at = time.monotonic()

    @property
    def complete(self) -> bool:
        return self.total > 0 and len(self.chunks) >= self.total

    def assemble(self) -> bytes:
        return b"".join(self.chunks[index] for index in range(self.total))


def _evict_stale_captures(captures: dict[int, _PendingCapture]) -> None:
    """Drop any `_PendingCapture` older than the TTL, still holding no `total` chunks.

    Called under `captures_lock` on every `do_POST`, so an abandoned/
    incomplete sequence (Puck crash, wedged upload, dropped WiFi) is bounded
    to the TTL rather than accumulating raw audio in memory forever --
    the happy path's pop-on-complete in `do_POST` never reaches these.
    """
    now = time.monotonic()
    stale = [
        seq
        for seq, capture in captures.items()
        if now - capture.created_at > PENDING_CAPTURE_TTL_SECONDS
    ]
    for seq in stale:
        logger.warning(
            "puck bridge evicting abandoned capture seq=%d (%d/%d chunks, "
            "stale after %.0fs)",
            seq,
            len(captures[seq].chunks),
            captures[seq].total,
            PENDING_CAPTURE_TTL_SECONDS,
        )
        del captures[seq]


def make_handler(
    *,
    expected_token: str,
    on_transcript: Callable[[str], None],
    transcribe_fn: Callable[[str], dict] | None = None,
    work_dir: str | os.PathLike[str] | None = None,
    response_stream: "ResponseStream | None" = None,
) -> type[http.server.BaseHTTPRequestHandler]:
    """Build a request handler bound to one token and one transcript sink.

    A factory rather than a module-level handler: tests inject a fake
    token, a fake `transcribe_fn`, and a fake `on_transcript` sink without
    reaching into global state, and a real deployment can run several
    bridges (one per Puck, or one per test) without them sharing captures.
    """
    from voice import transcribe as _default_transcribe

    transcribe = transcribe_fn or _default_transcribe
    resolved_work_dir = os.fspath(
        work_dir or tempfile.mkdtemp(prefix="puck_bridge_")
    )
    captures: dict[int, _PendingCapture] = {}
    captures_lock = threading.Lock()

    class Handler(http.server.BaseHTTPRequestHandler):
        # ESP-IDF's http_request component reuses one esp_http_client
        # connection across every chunk of one upload (pcm_capture.h);
        # http.server's BaseHTTPRequestHandler defaults to HTTP/1.0's
        # close-after-each-request otherwise, which would silently defeat
        # that reuse -- see tools/receiver.py's own docstring for the same
        # rule this story's spec calls out explicitly.
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
            # Redact the query-string credential: /response carries the
            # device token in the URL because audio_http cannot send a
            # header (see do_GET), and this handler logs full request lines.
            safe = tuple(
                _redact_token(a) if isinstance(a, str) else a for a in args
            )
            logger.debug(fmt, *safe)

        def _respond(self, code: int, body: bytes = b"") -> None:
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
            """Stream the current spoken response to the Puck.

            The device fetches this after its upload, and ESPHome's
            audio_http source plays it through the media_player. Two rules
            come from that reader (audio/audio_reader.cpp) and both are
            load-bearing:

              * It fails a stream after ~30s without a successful read, so
                every wait below is bounded well inside that.
              * A zero-length read is a TIMEOUT, not EOF -- the body has to
                be terminated definitively or the device waits forever.
            """
            path = self.path.split("?", 1)[0]
            if path != RESPONSE_PATH:
                self._respond(404, b"not found")
                return

            # Same fail-closed check as the upload path -- response audio
            # is as private as the question that produced it -- but the
            # credential has to arrive differently.
            #
            # ESPHome's audio_http media source never calls
            # esp_http_client_set_header(), so the device physically cannot
            # send X-Puck-Token when fetching this. The token therefore also
            # comes as a query parameter. That is a real, if small,
            # downgrade: URLs land in logs and proxies in a way headers do
            # not, which is why the log line below redacts it. Acceptable
            # while the credential is a hardcoded home-LAN shared secret
            # standing in for the device-administration system; revisit when
            # that lands, since a per-device credential in a URL would be
            # worth more than this one.
            query = parse_qs(urlparse(self.path).query)
            token = self.headers.get(TOKEN_HEADER, "") or (
                query.get("token", [""])[0]
            )
            if not expected_token or token != expected_token:
                logger.warning("puck bridge response rejected: invalid token")
                self._respond(401, b"invalid token")
                return

            if response_stream is None:
                self._respond(503, b"no response stream configured")
                return

            # Distinguish the two "no audio" cases in the log, because they
            # mean very different things: nothing was ever coming (no turn
            # accepted for this capture) versus a turn was accepted but
            # never produced audio. The first is routine -- an empty
            # transcript, a false wake -- and the second is a real fault.
            was_expecting = response_stream.expecting
            audio_format = response_stream.wait_for_format()
            if audio_format is None:
                if was_expecting:
                    logger.warning(
                        "puck bridge response: a turn was accepted but "
                        "produced no audio within the wait budget"
                    )
                else:
                    logger.info(
                        "puck bridge response: nothing to stream for this "
                        "capture (no turn was accepted); telling the device "
                        "at once rather than making it wait"
                    )
                self._respond(504, b"no response audio")
                return

            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            # No Content-Length: the length genuinely is not known yet.
            # Chunked encoding lets the body be terminated definitively,
            # which is what the device needs to see end-of-stream.
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()

            total = 0
            try:
                self._write_chunk(streaming_wav_header(audio_format))
                for chunk in response_stream.iter_chunks():
                    self._write_chunk(chunk)
                    total += len(chunk)
                # Terminating zero-length chunk: this is what makes
                # esp_http_client_is_complete_data_received() true.
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                logger.info("puck bridge response: device closed the connection")
                return
            logger.info("puck bridge response streamed %d bytes of PCM", total)

        def _write_chunk(self, data: bytes) -> None:
            """Write one HTTP chunked-encoding frame."""
            if not data:
                return
            self.wfile.write(b"%X\r\n" % len(data))
            self.wfile.write(data)
            self.wfile.write(b"\r\n")
            self.wfile.flush()

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
            path = self.path.split("?", 1)[0]
            if path != UPLOAD_PATH:
                self._respond(404, b"not found")
                return

            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                self._respond(400, b"bad content-length")
                return
            body = self.rfile.read(length) if length else b""

            # Fail closed *before* touching any capture state: a missing or
            # wrong token must never advance a reassembly, let alone
            # produce a turn -- true even for a hardcoded credential
            # standing in for Story 4's real one.
            token = self.headers.get(TOKEN_HEADER, "")
            if not expected_token or token != expected_token:
                logger.warning("puck bridge upload rejected: invalid token")
                self._respond(401, b"invalid token")
                return

            qs = parse_qs(urlparse(self.path).query)
            try:
                seq = int(qs.get("seq", ["-1"])[0])
                chunk = int(qs.get("chunk", ["-1"])[0])
                total = int(qs.get("total", ["-1"])[0])
            except (TypeError, ValueError):
                self._respond(400, b"bad chunk metadata")
                return
            if seq < 0 or chunk < 0 or total <= 0 or chunk >= total:
                self._respond(400, b"bad chunk metadata")
                return

            finished_capture: _PendingCapture | None = None
            with captures_lock:
                _evict_stale_captures(captures)
                capture = captures.setdefault(seq, _PendingCapture(total))
                capture.chunks[chunk] = body
                if capture.complete:
                    finished_capture = captures.pop(seq)

            # Acknowledge the chunk before doing the (comparatively slow)
            # WAV conversion and transcription -- the Puck's own upload
            # loop is waiting on this response before sending the next
            # chunk or moving on.
            #
            # 202 for a chunk that was accepted into an incomplete
            # reassembly, 200 only once the capture is whole. Before this
            # distinction existed every chunk got a flat 200, so the
            # firmware could not tell "you accepted my bytes" from "you
            # have the whole capture" -- and logged "Uploaded wake capture"
            # on runs the bridge had already evicted on TTL. Both sides
            # reported their own half truthfully and nobody reported the
            # lost turn. Both codes are 2xx, so existing success checks
            # (firmware `chunk_ok`, puck_identity::note_upload_status) are
            # unaffected.
            self._respond(200 if finished_capture is not None else 202)

            if finished_capture is not None:
                self._finish_capture(seq, finished_capture)

        def _finish_capture(self, seq: int, capture: _PendingCapture) -> None:
            # Declare intent HERE, before transcription, not after it.
            # The device fetches /response the moment its upload is
            # confirmed, and transcription takes seconds -- so a fetch
            # arriving mid-transcription must WAIT, not fast-fail. Setting
            # this after the transcript was accepted introduced exactly
            # that race on 2026-09-11: the turn ran and produced audio with
            # nobody left reading the stream. Every path out of this
            # function that will not produce audio calls abandon().
            if response_stream is not None:
                response_stream.expect()
            raw = capture.assemble()
            os.makedirs(resolved_work_dir, exist_ok=True)
            wav_path = os.path.join(resolved_work_dir, f"puck_{seq}.wav")
            try:
                raw_stereo32_to_wav(raw, wav_path)
                result = transcribe(wav_path)
            except Exception:
                logger.exception("puck bridge capture processing failed")
                if response_stream is not None:
                    response_stream.abandon()
                return
            finally:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass

            if not result.get("success"):
                logger.warning(
                    "puck bridge transcription failed: %s", result.get("error")
                )
                # Same reason as the empty-transcript path: the device may
                # already be waiting on /response for audio that will never
                # be produced.
                if response_stream is not None:
                    response_stream.abandon()
                return
            transcript = str(result.get("transcript") or "").strip()
            if not transcript:
                logger.info("puck bridge capture produced an empty transcript")
                # The device may already be fetching /response on the back
                # of a confirmed upload. Tell it at once that no audio is
                # coming, rather than letting it wait out the format budget.
                if response_stream is not None:
                    response_stream.abandon()
                return
            try:
                # The return value matters: the coordinator is single-flight,
                # so a transcript arriving while an earlier turn is still in
                # flight is DROPPED. That was silent -- on 2026-09-11 a
                # wedged turn swallowed a following capture with nothing in
                # the log to say a question had been thrown away. A dropped
                # turn is a lost turn and should say so.
                delivered = on_transcript(transcript)
            except Exception:
                logger.exception("puck bridge turn callback failed")
                if response_stream is not None:
                    response_stream.abandon()
            else:
                if delivered is False and response_stream is not None:
                    response_stream.abandon()
                if delivered is False:
                    logger.warning(
                        "puck bridge dropped a capture: a turn is already in "
                        "flight (single-flight coordinator). The question was "
                        "transcribed but never asked."
                    )

    return Handler


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
