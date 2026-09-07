#!/usr/bin/env python3
"""Convenience script to run the ESP32-S3 Touch LCD 7B simulator from repo root."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "firmware" / "esp32-s3-touch-lcd-7"))

from simulator import run_simulator

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Waveshare ESP32-S3-Touch-LCD-7B Display Simulator")
    parser.add_argument("--port", type=int, default=8794, help="HTTP port (default: 8794)")
    parser.add_argument("--no-open", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()
    run_simulator(port=args.port, open_browser=not args.no_open)
