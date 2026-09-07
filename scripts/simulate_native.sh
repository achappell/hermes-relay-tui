#!/usr/bin/env bash
# Build and run the native macOS SDL2 simulator for the Waveshare ESP32-S3-Touch-LCD-7B
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
SIM_DIR="$REPO_ROOT/firmware/esp32-s3-touch-lcd-7/simulator"

echo "Building native macOS simulator..."
make -C "$SIM_DIR"

echo "Launching simulator window (1024x600)..."
exec "$SIM_DIR/esp32_display_sim"
