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
import socket
import socketserver
import struct
import tempfile
import threading
import time
import wave
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .response import ResponseStream, ResponseStreamError, streaming_wav_header

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
RESPONSE_STATUS_PATH = "/response-status"
WAKE_ADMISSION_PATH = "/wake-admission"
FOLLOW_UP_ADMISSION_PATH = "/follow-up-admission"
# A connected client that stops reading must not retain the single response
# reader forever. Keep this aligned with the response stream's stall budget;
# tests may shorten it to exercise the failure path without waiting 20s.
RESPONSE_WRITE_TIMEOUT_SECONDS = 20.0


def _log_response_trace(response_stream: ResponseStream, *, framing: str) -> None:
    """Write one bounded, content-safe delivery record for the current seq."""
    metrics = response_stream.metrics()
    logger.info(
        "puck bridge response trace seq=%s framing=%s device_build_identity=%s "
        "audio_format=%s source_bytes=%s source_duration_seconds=%.3f "
        "source_sha256=%s delivered_bytes=%s delivered_duration_seconds=%.3f "
        "delivered_sha256=%s first_pcm_seconds=%s producer_gap_seconds=%.3f "
        "producer_gap_max_seconds=%.3f consumer_gap_seconds=%.3f "
        "consumer_rate_bytes_per_second=%.1f queue_high_water=%s "
        "stall_duration_seconds=%.3f response_duration_seconds=%.3f "
        "terminal=%s terminal_reason=%s",
        metrics["seq"],
        framing,
        metrics["device_build_identity"],
        metrics["audio_format"],
        metrics["source_bytes"],
        metrics["source_duration_seconds"],
        metrics["source_sha256"],
        metrics["delivered_bytes"],
        metrics["delivered_duration_seconds"],
        metrics["delivered_sha256"],
        metrics["first_pcm_seconds"],
        metrics["producer_gap_seconds"],
        metrics["producer_gap_max_seconds"],
        metrics["consumer_gap_seconds"],
        metrics["consumer_rate_bytes_per_second"],
        metrics["queue_high_water"],
        metrics["stall_duration_seconds"],
        metrics["response_duration_seconds"],
        metrics["terminal"],
        metrics["terminal_reason"],
    )


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
    on_transcript: Callable[[str], object],
    set_response_seq: Callable[[int], None] | None = None,
    on_capture_silent: Callable[[int], object] | None = None,
    on_capture_failure: Callable[[int], object] | None = None,
    transcribe_fn: Callable[[str], dict] | None = None,
    work_dir: str | os.PathLike[str] | None = None,
    response_stream: "ResponseStream | None" = None,
    on_wake_admission: Callable[[str, int], str] | None = None,
    on_follow_up_admission: Callable[[int], str] | None = None,
) -> type[http.server.BaseHTTPRequestHandler]:
    """Build a request handler bound to one token and one transcript sink.

    A factory rather than a module-level handler: tests inject a fake
    token, a fake `transcribe_fn`, and a fake `on_transcript` sink without
    reaching into global state, and a real deployment can run several
    bridges (one per Puck, or one per test) without them sharing captures.

    `set_response_seq` is called before any completed capture outcome is
    handed to the turn runner. The upload sequence is the only reliable
    identity available at this boundary, so the response producer must
    receive it before it can publish audio, including silent and failed
    outcomes. `on_capture_silent` and `on_capture_failure` let a continuous
    Puck conversation wake its waiting follow-up mailbox without pretending
    that an empty or failed capture was a transcript.
    """
    from voice import transcribe as _default_transcribe

    transcribe = transcribe_fn or _default_transcribe
    resolved_work_dir = os.fspath(
        work_dir or tempfile.mkdtemp(prefix="puck_bridge_")
    )
    captures: dict[int, _PendingCapture] = {}
    captures_lock = threading.Lock()
    stopping = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        # ESP-IDF's http_request component reuses one esp_http_client
        # connection across every chunk of one upload (pcm_capture.h);
        # http.server's BaseHTTPRequestHandler defaults to HTTP/1.0's
        # close-after-each-request otherwise, which would silently defeat
        # that reuse -- see tools/receiver.py's own docstring for the same
        # rule this story's spec calls out explicitly.
        protocol_version = "HTTP/1.1"

        @classmethod
        def request_stop(cls) -> None:
            with captures_lock:
                stopping.set()
                captures.clear()
            if response_stream is not None:
                response_stream.shutdown()

        @classmethod
        def cleanup(cls) -> None:
            cls.request_stop()
            if work_dir is None:
                try:
                    os.rmdir(resolved_work_dir)
                except FileNotFoundError:
                    pass

        def handle_one_request(self) -> None:
            if stopping.is_set():
                self.close_connection = True
                return
            super().handle_one_request()


        def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
            # Redact the query-string credential: /response carries the
            # device token in the URL because audio_http cannot send a
            # header (see do_GET), and this handler logs full request lines.
            safe = tuple(
                _redact_token(a) if isinstance(a, str) else a for a in args
            )
            logger.debug(fmt, *safe)

        def _respond(
            self,
            code: int,
            body: bytes = b"",
            *,
            content_type: str | None = None,
        ) -> None:
            self.send_response(code)
            if content_type is not None:
                self.send_header("Content-Type", content_type)
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
            if path not in {
                RESPONSE_PATH,
                RESPONSE_STATUS_PATH,
                WAKE_ADMISSION_PATH,
                FOLLOW_UP_ADMISSION_PATH,
            }:
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

            if path == WAKE_ADMISSION_PATH:
                self._do_wake_admission(query)
                return

            if path == FOLLOW_UP_ADMISSION_PATH:
                self._do_follow_up_admission(query)
                return

            if response_stream is None:
                self._respond(503, b"no response stream configured")
                return

            if path == RESPONSE_STATUS_PATH:
                self._do_response_status(query)
                return

            # Distinguish the two "no audio" cases in the log, because they
            # mean very different things: nothing was ever coming (no turn
            # accepted for this capture) versus a turn was accepted but
            # never produced audio. The first is routine -- an empty
            # transcript, a false wake -- and the second is a real fault.
            was_expecting = response_stream.expecting
            # Validate the requested capture. The firmware builds
            # /response?seq=<the capture the bridge confirmed>, and
            # pcm_capture.h documents it as "so the response fetch asks for
            # the right one rather than assuming the latest" -- but nothing
            # checked it, so a retried or late fetch after a newer turn had
            # begun would silently play the WRONG capture's answer, with
            # neither side able to notice. Mismatch is a conflict, not a
            # not-found: the resource exists, it is simply a different
            # answer than the one being asked for.
            seq_values = query.get("seq", [])
            if len(seq_values) > 1:
                self._respond(400, b"bad response sequence")
                return
            if len(seq_values) != 1:
                self._respond(400, b"response sequence required")
                return
            requested = seq_values[0]
            try:
                requested_seq = int(requested)
            except ValueError:
                self._respond(400, b"bad response sequence")
                return
            if requested_seq < 0:
                self._respond(400, b"bad response sequence")
                return
            current = response_stream.seq
            if current != requested_seq:
                logger.warning(
                    "puck bridge response: device asked for capture %s but "
                    "the current answer is for %s; refusing rather than "
                    "playing the wrong one",
                    requested_seq,
                    current,
                )
                self._respond(409, b"stale capture")
                return

            # A terminal response is never replayed. The status endpoint is
            # the durable confirmation path for the device after playback.
            response_status = response_stream.status_for(requested_seq)
            if response_status == "silent":
                # The Puck still fetches the sequence after an empty capture
                # or local exact-stop command. 204 is an intentional,
                # successful no-audio result; the subsequent status poll
                # tells firmware to resume wake detection without refusal.
                self._respond(204)
                _log_response_trace(response_stream, framing="none")
                return
            if response_status in {"complete", "unavailable"}:
                self._respond(409, b"response is terminal")
                return

            audio_format = response_stream.wait_for_format()
            if audio_format is None:
                if response_stream.terminal_status == "silent":
                    self._respond(204)
                    _log_response_trace(response_stream, framing="none")
                    return
                if (
                    was_expecting
                    and response_stream.source_terminal is None
                ):
                    response_stream.unavailable(
                        requested_seq, reason="first_audio_timeout"
                    )
                if was_expecting:
                    # `expecting` is set when capture processing starts, so
                    # this covers the routine cases too -- an empty
                    # transcript from a false wake abandons the stream and
                    # lands here. Phrased as a plain fact rather than a
                    # fault: the earlier wording ("a turn was accepted but
                    # produced no audio") read as an error for what is
                    # usually just nobody having said anything.
                    logger.info(
                        "puck bridge response: no audio for this capture "
                        "(no question transcribed, or the turn produced "
                        "nothing)"
                    )
                else:
                    logger.info(
                        "puck bridge response: nothing to stream for this "
                        "capture (no turn was accepted); telling the device "
                        "at once rather than making it wait"
                    )
                self._respond(
                    503 if response_stream.terminal_status == "unavailable" else 504,
                    b"no response audio",
                )
                if response_stream.terminal_status == "unavailable":
                    _log_response_trace(response_stream, framing="none")
                return

            # Single consumer: a second concurrent fetch would pop from
            # the same queue and split the answer between the two, so both
            # would play garbage. Refuse rather than corrupt.
            if not response_stream.acquire_reader(requested_seq):
                logger.warning(
                    "puck bridge response: a second concurrent fetch was "
                    "refused; one is already streaming"
                )
                self._respond(409, b"response already streaming")
                return

            # Everything after acquire_reader() must be inside the try, so
            # the finally always releases the slot. end_headers() flushes
            # straight to an unbuffered socket writer, so if the device has
            # already dropped the connection it raises HERE -- before the
            # old try began -- leaking _reader_active and making every
            # later fetch 409. That left the Puck permanently mute until
            # the bridge process restarted.
            total = 0
            stream_seq = response_stream.seq
            previous_socket_timeout: float | None = None
            timeout_read = False
            try:
                previous_socket_timeout = self.connection.gettimeout()
                timeout_read = True
                self.connection.settimeout(RESPONSE_WRITE_TIMEOUT_SECONDS)
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                # No Content-Length: the length genuinely is not known yet.
                # Chunked encoding lets the body be terminated definitively,
                # which is what the device needs to see end-of-stream.
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self._write_chunk(streaming_wav_header(audio_format))
                # Let a cushion build before the first PCM leaves. Without
                # it the device plays exactly as fast as Hermes speaks and
                # any upstream hesitation is audible as chop.
                response_stream.wait_for_prebuffer(audio_format)
                for chunk in response_stream.iter_chunks():
                    self._write_chunk(chunk)
                    if not response_stream.record_delivered(chunk, stream_seq):
                        response_stream.fail_delivery(
                            stream_seq, reason="delivery_accounting"
                        )
                        self.close_connection = True
                        _log_response_trace(response_stream, framing="chunked")
                        return
                    total += len(chunk)
                # A zero-length chunk is earned only by a normally completed
                # source whose queue has drained. A stall/failure closes the
                # body without masquerading as EOF.
                if not response_stream.ready_for_eof(stream_seq):
                    # HTTP/1.1 has no implicit end-of-body after a handler
                    # returns. Close the connection so the device observes
                    # a failed/truncated response rather than waiting for a
                    # second request on the same socket.
                    self.close_connection = True
                    _log_response_trace(response_stream, framing="chunked")
                    return
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
                if not response_stream.mark_delivery_complete(stream_seq):
                    response_stream.fail_delivery(
                        stream_seq, reason="delivery_accounting"
                    )
                    self.close_connection = True
                    _log_response_trace(response_stream, framing="chunked")
                    return
            except OSError:
                response_stream.fail_delivery(
                    stream_seq, reason="consumer_disconnect"
                )
                self.close_connection = True
                logger.warning(
                    "puck bridge response: device closed the connection after "
                    "%d bytes -- the answer was cut short or stopped reading",
                    total,
                )
                _log_response_trace(response_stream, framing="chunked")
                return
            except (ResponseStreamError, TypeError, ValueError, struct.error) as exc:
                response_stream.fail_delivery(
                    stream_seq, reason="response_failure"
                )
                self.close_connection = True
                logger.warning(
                    "puck bridge response failed before completion (%s)",
                    type(exc).__name__,
                )
                _log_response_trace(response_stream, framing="chunked")
                return
            finally:
                if timeout_read:
                    try:
                        self.connection.settimeout(previous_socket_timeout)
                    except OSError:
                        pass
                response_stream.release_reader()
            logger.info("puck bridge response streamed %d bytes of PCM", total)
            _log_response_trace(response_stream, framing="chunked")

        def _do_response_status(self, query: dict[str, list[str]]) -> None:
            """Return the retained terminal result for exactly one sequence."""
            values = query.get("seq", [])
            if len(values) != 1:
                self._respond(400, b"bad response sequence")
                return
            try:
                seq = int(values[0])
            except ValueError:
                self._respond(400, b"bad response sequence")
                return
            status = response_stream.status_for(seq)
            if status is None:
                self._respond(404, b"unknown response sequence")
                return
            if status == "active":
                self._respond(409, b"response active")
                return
            body = b'{"seq": %d, "status": "%s"}' % (seq, status.encode("ascii"))
            if response_stream.home_admission_required_for(seq):
                body = (
                    b'{"seq": %d, "status": "%s", '
                    b'"needs_home_admission": true}'
                    % (seq, status.encode("ascii"))
                )
            self._respond(200, body, content_type="application/json")

        def _do_wake_admission(self, query: dict[str, list[str]]) -> None:
            """Resolve one pre-capture Home admission for one physical wake."""
            if on_wake_admission is None:
                self._respond(404, b"wake admission unavailable")
                return
            seq_values = query.get("seq", [])
            wake_values = query.get("wake", [])
            if len(seq_values) != 1 or len(wake_values) != 1:
                self._respond(400, b"wake sequence and phrase required")
                return
            try:
                seq = int(seq_values[0])
            except ValueError:
                self._respond(400, b"bad wake sequence")
                return
            wake_phrase = wake_values[0].strip()
            if seq < 0 or seq > 0xFFFFFFFF or not wake_phrase or len(wake_phrase) > 128:
                self._respond(400, b"invalid wake admission request")
                return
            try:
                result = on_wake_admission(wake_phrase, seq)
            except Exception as exc:
                logger.warning(
                    "puck Home wake admission failed (%s)", type(exc).__name__
                )
                result = "unavailable"
            if result not in {"admitted", "denied", "identity_rejected", "unavailable"}:
                logger.warning("puck Home wake admission returned an invalid result")
                result = "unavailable"
            body = f"{result}:{seq}".encode("ascii")
            self._respond(200, body, content_type="text/plain; charset=utf-8")

        def _do_follow_up_admission(self, query: dict[str, list[str]]) -> None:
            """Check Home readiness before a wake-free follow-up opens the mic."""
            if on_follow_up_admission is None:
                self._respond(404, b"follow-up admission unavailable")
                return
            seq_values = query.get("seq", [])
            if len(seq_values) != 1:
                self._respond(400, b"response sequence required")
                return
            try:
                seq = int(seq_values[0])
            except ValueError:
                self._respond(400, b"bad response sequence")
                return
            if seq < 0 or seq > 0xFFFFFFFF:
                self._respond(400, b"invalid response sequence")
                return
            try:
                result = on_follow_up_admission(seq)
            except Exception as exc:
                logger.warning(
                    "Puck follow-up admission failed (%s)", type(exc).__name__
                )
                result = "unavailable"
            if result not in {"admitted", "denied", "identity_rejected", "unavailable"}:
                logger.warning("Puck follow-up admission returned an invalid result")
                result = "unavailable"
            body = f"{result}:{seq}".encode("ascii")
            self._respond(200, body, content_type="text/plain; charset=utf-8")

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
                if stopping.is_set():
                    self.close_connection = True
                    return
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
            # Declare intent BEFORE the confirming 200. The firmware acts
            # on that 200 in the same 1s interval tick that finished the
            # upload, so answering first left a narrow window where the
            # device's /response GET could land while `_expecting` was
            # still false and fast-fail to 504 -- the same lost-turn shape
            # the expect() comment describes.
            if finished_capture is not None and response_stream is not None:
                if not response_stream.expect(seq):
                    logger.info(
                        "puck bridge: a previous answer is still streaming; "
                        "dropping this capture before transcription"
                    )
                    # This is temporary capacity pressure, not a bad device
                    # credential. The firmware treats 4xx as authoritative
                    # identity rejection, so a busy response must be 503
                    # rather than 409 or the valid Puck would lock itself out.
                    self._respond(503, b"response stream busy")
                    return

            try:
                self._respond(200 if finished_capture is not None else 202)
            except OSError:
                if finished_capture is not None and response_stream is not None:
                    response_stream.abandon(seq)
                self.close_connection = True
                logger.info(
                    "puck bridge upload acknowledgement failed for seq=%d; "
                    "capture will not be replayed",
                    seq,
                )
                return

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
            # expect() already ran in do_POST, before the confirming 200 --
            # calling it again here would clear the queue a second time.
            # `accepted_stream` records whether we own the stream, so every
            # abandon() below is skipped when a previous answer still does.
            accepted_stream = (
                response_stream is None or response_stream.seq == seq
            )
            if set_response_seq is not None:
                set_response_seq(seq)

            def notify_capture(callback: Callable[[int], object] | None) -> None:
                if callback is None:
                    return
                try:
                    callback(seq)
                except Exception:
                    logger.exception("puck bridge capture outcome callback failed")

            if stopping.is_set():
                capture.chunks.clear()
                return
            raw = capture.assemble()
            capture.chunks.clear()
            if not raw:
                logger.info("puck bridge capture was empty; no turn will be created")
                notify_capture(on_capture_silent)
                if response_stream is not None and accepted_stream:
                    response_stream.silent(seq, reason="empty_capture")
                return
            os.makedirs(resolved_work_dir, exist_ok=True)
            wav_path = os.path.join(resolved_work_dir, f"puck_{seq}.wav")
            try:
                raw_stereo32_to_wav(raw, wav_path)
                result = transcribe(wav_path)
            except Exception:
                logger.exception("puck bridge capture processing failed")
                notify_capture(on_capture_failure)
                if response_stream is not None and accepted_stream:
                    response_stream.unavailable(seq, reason="capture_processing")
                return
            finally:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass

            if stopping.is_set():
                return
            if not result.get("success"):
                logger.warning(
                    "puck bridge transcription failed: %s", result.get("error")
                )
                notify_capture(on_capture_failure)
                if response_stream is not None and accepted_stream:
                    response_stream.unavailable(seq, reason="transcription_failure")
                return
            transcript = str(result.get("transcript") or "").strip()
            if not transcript:
                logger.info("puck bridge capture produced an empty transcript")
                notify_capture(on_capture_silent)
                if response_stream is not None and accepted_stream:
                    response_stream.silent(seq, reason="empty_transcript")
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
                notify_capture(on_capture_failure)
                if response_stream is not None and accepted_stream:
                    response_stream.unavailable(seq, reason="turn_callback")
            else:
                accepted = delivered is True or delivered == "accepted"
                if (
                    delivered == "silent"
                    and response_stream is not None
                    and accepted_stream
                ):
                    response_stream.silent(seq, reason="local_stop")
                elif (
                    not accepted
                    and response_stream is not None
                    and accepted_stream
                ):
                    response_stream.unavailable(seq, reason="turn_rejected")
                if not accepted:
                    logger.warning(
                        "puck bridge dropped a capture or failed its delivery; "
                        "remote receipt may be uncertain. No automatic replay."
                    )

    return Handler


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = False
    block_on_close = False

    def __init__(self, *args, **kwargs):
        self._workers_cv = threading.Condition()
        self._sockets = set()
        self._stopping = False
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        with self._workers_cv:
            if self._stopping:
                self.shutdown_request(request)
                return
            self._sockets.add(request)
        try:
            super().process_request(request, client_address)
        except BaseException:
            with self._workers_cv:
                self._sockets.discard(request)
                self._workers_cv.notify_all()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._workers_cv:
                self._sockets.discard(request)
                if self._stopping and not self._sockets:
                    self.RequestHandlerClass.cleanup()
                self._workers_cv.notify_all()

    def request_stop(self):
        with self._workers_cv:
            self._stopping = True
            self.RequestHandlerClass.request_stop()
            for connection in self._sockets:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()

    def wait_workers(self, deadline=None):
        with self._workers_cv:
            while self._sockets:
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                if remaining == 0:
                    logger.warning("puck bridge request cleanup pending")
                    return False
                self._workers_cv.wait(remaining)
        self.RequestHandlerClass.cleanup()
        return True

    def server_close(self):
        self.request_stop()
        super().server_close()
        # Callers that need a bound use wait_workers(deadline) before this.
        # Request threads remain non-daemon owners of transcription cleanup.
        if not self._sockets:
            self.RequestHandlerClass.cleanup()
