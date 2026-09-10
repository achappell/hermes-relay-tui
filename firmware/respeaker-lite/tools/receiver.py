#!/usr/bin/env python3
"""Chunked-PCM-upload receiver for the Puck's training-data capture
pipeline (../pcm_capture.h). Listens for POST /upload?seq=N&chunk=C&
total=T&ms=MS and reassembles chunks per sequence into
<out_dir>/<recv_time>_seq<N>.raw.

protocol_version is set to HTTP/1.1 deliberately: as of story 3's session
14, pcm_capture.h reuses one esp_http_client connection across every chunk
of every sample (instead of a fresh TCP connect/teardown per chunk, which
session 13 found was leaking internal RAM on the device). That reuse only
works if this server also keeps the connection open -- Python's
http.server defaults BaseHTTPRequestHandler to HTTP/1.0's close-after-
each-request otherwise, which would silently defeat the whole point.

Usage: python3 receiver.py [out_dir]
"""
import http.server
import os
import socketserver
import sys
import time
from urllib.parse import urlparse, parse_qs

OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/pcm_captures"
os.makedirs(OUT_DIR, exist_ok=True)

seq_files = {}  # seq -> path
seq_stats = {}  # seq -> {"received": int, "total": int}


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive -- see module docstring

    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        seq = int(qs.get("seq", ["-1"])[0])
        chunk = int(qs.get("chunk", ["-1"])[0])
        total = int(qs.get("total", ["-1"])[0])
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if seq not in seq_files:
            path = os.path.join(OUT_DIR, f"{int(time.time())}_seq{seq}.raw")
            seq_files[seq] = path
            seq_stats[seq] = {"received": 0, "total": total}
            open(path, "wb").close()

        path = seq_files[seq]
        # UPLOAD_CHUNK_BYTES in pcm_capture.h -- keep in sync if that changes.
        with open(path, "r+b") as f:
            f.seek(chunk * 16000)
            f.write(body)
        seq_stats[seq]["received"] += 1

        print(f"seq={seq} chunk={chunk}/{total} bytes={len(body)} "
              f"received_so_far={seq_stats[seq]['received']}", flush=True)

        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    with ThreadingHTTPServer(("0.0.0.0", 8765), Handler) as httpd:
        print(f"Listening on 0.0.0.0:8765, writing to {OUT_DIR}", flush=True)
        httpd.serve_forever()
