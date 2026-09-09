#!/usr/bin/env python3
"""Runs `esphome logs` and reconstructs each PCMDUMP-tagged capture into a
.raw file, exactly matching the WiFi-upload path's format so the existing
label_captures.py (--session-mode) works unchanged against either source.

STATUS (session 15): this host-side parser is safe and untested-but-ready.
Its firmware counterpart (pcm_capture::dump_over_serial(), continuous
~1280-lines-per-2s-sample chunked base64 over ESP_LOGI) hung the device on
first live test -- the device went completely silent on serial with no
crash marker, same symptom as session 14's connection-reuse hang. That
firmware change was reverted (git checkout HEAD -- pcm_capture.h
respeaker-lite.yaml); it is NOT currently in the committed firmware. Before
reusing this script, the firmware side needs to be rebuilt and tested far
more cautiously than session 15 did -- a single bounded capture first, not
an indefinite continuous loop -- see story 3's session 15 log for detail.

Serial transport doesn't share the WiFi-upload path's failure modes
(dropped chunks, circuit-breaker reboots) -- session 15 found the WiFi
path yielded exactly 1 genuine correlated sample across a full day of
testing, while a *safe* implementation of this path should in principle be
far more reliable, just slower per-sample (serial baud rate would be the
bottleneck instead of the 2s capture window).

Usage:
    python3 collect_serial_dumps.py --esphome-venv ../../../venv-firmware \\
        --config ../respeaker-lite.yaml --device /dev/cu.usbmodem101 \\
        --out-dir /tmp/pcm_captures
"""
import argparse
import base64
import os
import re
import subprocess
import sys
import time

LINE_RE = re.compile(r"PCMDUMP seq=(\d+) chunk=(\d+) total=(\d+) b64=(\S+)")
BEGIN_RE = re.compile(r"PCMDUMP begin seq=(\d+) total_bytes=(\d+) total_chunks=(\d+)")
END_RE = re.compile(r"PCMDUMP end seq=(\d+)")
DUMP_CHUNK_BYTES = 200  # must match pcm_capture.h's DUMP_CHUNK_BYTES


def finalize(seq, buffers, totals, out_dir):
    chunks = buffers.get(seq, {})
    if not chunks:
        return None
    total_bytes, total_chunks = totals.get(seq, (None, max(chunks) + 1))
    ordered = bytearray()
    n_missing = 0
    for i in range(total_chunks):
        if i in chunks:
            ordered += chunks[i]
        else:
            # A handful of lines occasionally get corrupted in the serial
            # pipe (~1-2 out of ~1280 per sample, empirically) -- zero-fill
            # the gap rather than discarding the whole sample. At 200
            # bytes/chunk out of a 256000-byte capture this is a negligible,
            # brief silent gap, not a meaningful loss for training purposes.
            ordered += b"\x00" * DUMP_CHUNK_BYTES
            n_missing += 1
    if total_bytes is not None:
        ordered = ordered[:total_bytes]
    out_path = os.path.join(out_dir, f"{int(time.time())}_seq{seq}.raw")
    with open(out_path, "wb") as f:
        f.write(bytes(ordered))
    return out_path, len(ordered), n_missing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--esphome-venv", required=True, help="path to the venv-firmware directory")
    parser.add_argument("--config", required=True, help="path to respeaker-lite.yaml")
    parser.add_argument("--device", default="/dev/cu.usbmodem101")
    parser.add_argument("--out-dir", default="/tmp/pcm_captures")
    parser.add_argument("--duration", type=float, default=None, help="stop after this many seconds (default: run until Ctrl+C)")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    esphome_bin = os.path.join(args.esphome_venv, "bin", "esphome")

    proc = subprocess.Popen(
        [esphome_bin, "logs", args.config, "--device", args.device],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )

    buffers = {}  # seq -> {chunk_index: bytes}
    totals = {}  # seq -> (total_bytes, total_chunks)
    n_saved = 0
    start_time = time.time()

    try:
        for line in proc.stdout:
            if args.duration and (time.time() - start_time) > args.duration:
                break

            m = BEGIN_RE.search(line)
            if m:
                seq = int(m.group(1))
                totals[seq] = (int(m.group(2)), int(m.group(3)))
                buffers[seq] = {}
                continue

            m = END_RE.search(line)
            if m:
                seq = int(m.group(1))
                result = finalize(seq, buffers, totals, args.out_dir)
                if result:
                    out_path, n_bytes, n_missing = result
                    n_saved += 1
                    missing_note = f", {n_missing} chunks zero-filled" if n_missing else ""
                    print(f"[{n_saved}] saved seq={seq} ({n_bytes} bytes{missing_note}) -> {out_path}")
                buffers.pop(seq, None)
                totals.pop(seq, None)
                continue

            m = LINE_RE.search(line)
            if not m:
                continue
            seq, chunk, total, b64 = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
            try:
                raw = base64.b64decode(b64)
            except Exception as e:
                print(f"seq={seq} chunk={chunk}: base64 decode failed: {e}", file=sys.stderr)
                continue
            buffers.setdefault(seq, {})[chunk] = raw
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        # Flush any samples that had all/most of their chunks but never saw
        # their "PCMDUMP end" line before we stopped (e.g. --duration cut
        # off mid-dump, or Ctrl+C).
        for seq in list(buffers.keys()):
            result = finalize(seq, buffers, totals, args.out_dir)
            if result:
                out_path, n_bytes, n_missing = result
                n_saved += 1
                missing_note = f", {n_missing} chunks zero-filled" if n_missing else ""
                print(f"[{n_saved}] saved seq={seq} ({n_bytes} bytes{missing_note}, flushed at exit) -> {out_path}")

    print(f"Done. {n_saved} samples saved to {args.out_dir}.")


if __name__ == "__main__":
    main()
