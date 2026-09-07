#!/usr/bin/env python3
"""Waveshare ESP32-S3-Touch-LCD-7B Interactive Local Simulator.

Renders the exact 1024x600 hardware display layout, GT911 capacitive touch
emulation, 4-corner validation targets, memory telemetry, and benchmark widgets
in an interactive local browser window.
"""

from __future__ import annotations

import argparse
import http.server
import socketserver
import webbrowser
from pathlib import Path

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Waveshare ESP32-S3-Touch-LCD-7B Simulator</title>
    <style>
        :root {
            --bg-body: #0d0e12;
            --bezel-color: #1a1a20;
            --lcd-bg: #121214;
            --panel-bg: #18181e;
            --header-bg: #1e1e24;
            --border-color: #2e2e38;
            --text-primary: #ede7f6;
            --text-secondary: #b0bec5;
            --accent-green: #69f0ae;
            --accent-yellow: #ffd54f;
            --accent-cyan: #00e5ff;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            user-select: none;
            -webkit-user-select: none;
        }

        body {
            background-color: var(--bg-body);
            color: var(--text-primary);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 24px;
        }

        .simulator-header {
            margin-bottom: 16px;
            text-align: center;
        }

        .simulator-header h1 {
            font-size: 20px;
            font-weight: 600;
            color: #fff;
            letter-spacing: 0.5px;
        }

        .simulator-header p {
            font-size: 13px;
            color: var(--text-secondary);
            margin-top: 4px;
        }

        /* 7-inch Hardware Bezel */
        .hardware-bezel {
            background: linear-gradient(145deg, #24242e, #141418);
            padding: 24px;
            border-radius: 16px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.8), inset 0 1px 1px rgba(255,255,255,0.1);
            border: 1px solid #333340;
            position: relative;
        }

        .board-tag {
            position: absolute;
            top: 6px;
            left: 28px;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: #666677;
            font-weight: 700;
        }

        /* 1024x600 IPS LCD Screen */
        .lcd-screen {
            width: 1024px;
            height: 600px;
            background-color: var(--lcd-bg);
            border-radius: 4px;
            position: relative;
            overflow: hidden;
            box-shadow: inset 0 0 12px rgba(0,0,0,0.9);
            cursor: crosshair;
        }

        /* Top Header Bar */
        .lcd-header {
            width: 1024px;
            height: 50px;
            background-color: var(--header-bg);
            border-bottom: 1px solid #33333f;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 20px;
        }

        .lcd-title {
            font-size: 15px;
            font-weight: 600;
            color: var(--text-primary);
        }

        .lcd-fps {
            font-size: 14px;
            font-family: monospace;
            color: var(--accent-green);
        }

        /* Stats & Benchmarking Panels */
        .panel-container {
            display: flex;
            gap: 20px;
            padding: 20px 60px;
            margin-top: 10px;
        }

        .lcd-card {
            background-color: var(--panel-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 16px;
            flex: 1;
            height: 200px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }

        .mem-stats {
            font-size: 13px;
            line-height: 1.6;
            color: var(--text-secondary);
            font-family: monospace;
        }

        .touch-stats {
            font-size: 14px;
            font-weight: 600;
            color: var(--accent-yellow);
            font-family: monospace;
            padding: 6px 10px;
            background: rgba(255, 213, 79, 0.08);
            border-radius: 4px;
            border-left: 3px solid var(--accent-yellow);
        }

        /* Benchmark Arc & Slider */
        .bench-wrapper {
            display: flex;
            align-items: center;
            justify-content: space-around;
            height: 100%;
        }

        .circular-meter {
            position: relative;
            width: 120px;
            height: 120px;
        }

        .circular-meter svg {
            width: 120px;
            height: 120px;
            transform: rotate(-90deg);
        }

        .circular-meter circle {
            fill: none;
            stroke-width: 10;
        }

        .meter-bg {
            stroke: #2a2a35;
        }

        .meter-fill {
            stroke: #7c4dff;
            stroke-dasharray: 314;
            stroke-dashoffset: 80;
            transition: stroke-dashoffset 0.05s linear;
        }

        .meter-label {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 13px;
            font-weight: 600;
            color: #b388ff;
        }

        .slider-bar-track {
            width: 180px;
            height: 14px;
            background: #2a2a35;
            border-radius: 7px;
            position: relative;
            overflow: hidden;
        }

        .slider-bar-fill {
            height: 100%;
            width: 65%;
            background: linear-gradient(90deg, #651fff, #00e5ff);
            border-radius: 7px;
        }

        /* Color Palette Bar */
        .palette-container {
            display: flex;
            gap: 8px;
            padding: 0 60px;
            margin-top: 15px;
        }

        .palette-swatch {
            flex: 1;
            height: 32px;
            border-radius: 4px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.4);
        }

        /* 4 Corner Verification Buttons */
        .corner-btn {
            position: absolute;
            width: 120px;
            height: 48px;
            background-color: #263238;
            color: #cfd8dc;
            border: 1px solid #455a64;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 700;
            font-family: monospace;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: background-color 0.15s, border-color 0.15s, transform 0.08s;
            z-index: 10;
        }

        .corner-btn:active {
            transform: scale(0.96);
        }

        .corner-btn.verified {
            background-color: #00c853 !important;
            border-color: #69f0ae !important;
            color: #ffffff !important;
            box-shadow: 0 0 14px rgba(0, 200, 83, 0.6);
        }

        .btn-tl { top: 60px; left: 10px; }
        .btn-tr { top: 60px; right: 10px; }
        .btn-bl { bottom: 10px; left: 10px; }
        .btn-br { bottom: 10px; right: 10px; }

        /* Floating Touch Indicator */
        .touch-pointer {
            position: absolute;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: rgba(0, 229, 255, 0.35);
            border: 2px solid var(--accent-cyan);
            pointer-events: none;
            transform: translate(-50%, -50%);
            display: none;
            z-index: 20;
            box-shadow: 0 0 16px rgba(0, 229, 255, 0.6);
        }

        /* Controls / Instructions */
        .sim-controls {
            margin-top: 20px;
            display: flex;
            gap: 16px;
            align-items: center;
        }

        .sim-badge {
            background: #1e1e28;
            border: 1px solid #333345;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            color: var(--text-secondary);
        }

        .sim-badge strong {
            color: #fff;
        }

        .btn-reset {
            background: #37474f;
            color: #eceff1;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            cursor: pointer;
        }

        .btn-reset:hover {
            background: #455a64;
        }
    </style>
</head>
<body>

    <div class="simulator-header">
        <h1>Waveshare ESP32-S3-Touch-LCD-7B Simulator</h1>
        <p>1024×600 IPS RGB565 LCD • Goodix GT911 I2C Touch • Octal PSRAM Double-Buffering</p>
    </div>

    <!-- Hardware Bezel -->
    <div class="hardware-bezel">
        <div class="board-tag">ESP32-S3-WROOM-1-N16R8 • 1024×600 RGB</div>

        <div class="lcd-screen" id="screen">
            <!-- Header Bar -->
            <div class="lcd-header">
                <div class="lcd-title">Hermes Smart Display — Waveshare ESP32-S3-Touch-LCD-7B</div>
                <div class="lcd-fps" id="fps-counter">FPS: 60 | Tear-Free Direct FB</div>
            </div>

            <!-- Main Telemetry & Benchmark Cards -->
            <div class="panel-container">
                <div class="lcd-card">
                    <div class="mem-stats">
                        Resolution: 1024×600 (16-bit RGB565)<br>
                        Octal PSRAM: 5,688 KB free / 8,192 KB total (FB0+FB1 = 2,457 KB)<br>
                        Internal SRAM: 384 KB free / 512 KB total
                    </div>
                    <div class="touch-stats" id="touch-stats">
                        Touch: Idle (Click/drag to test GT911 tracking)
                    </div>
                </div>

                <div class="lcd-card">
                    <div class="bench-wrapper">
                        <div class="circular-meter">
                            <svg>
                                <circle class="meter-bg" cx="60" cy="60" r="50"></circle>
                                <circle class="meter-fill" id="arc-fill" cx="60" cy="60" r="50"></circle>
                            </svg>
                            <div class="meter-label" id="arc-label">75%</div>
                        </div>
                        <div>
                            <div style="font-size: 12px; color: #b0bec5; margin-bottom: 8px;">PSRAM Bandwidth Test</div>
                            <div class="slider-bar-track">
                                <div class="slider-bar-fill" id="slider-fill"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Color Palette Test Bars -->
            <div class="palette-container">
                <div class="palette-swatch" style="background-color: #f44336;" title="Red 0xF800"></div>
                <div class="palette-swatch" style="background-color: #e91e63;" title="Pink"></div>
                <div class="palette-swatch" style="background-color: #9c27b0;" title="Purple"></div>
                <div class="palette-swatch" style="background-color: #3f51b5;" title="Indigo"></div>
                <div class="palette-swatch" style="background-color: #2196f3;" title="Blue 0x001F"></div>
                <div class="palette-swatch" style="background-color: #00bcd4;" title="Cyan 0x07FF"></div>
                <div class="palette-swatch" style="background-color: #009688;" title="Teal"></div>
                <div class="palette-swatch" style="background-color: #4caf50;" title="Green 0x07E0"></div>
                <div class="palette-swatch" style="background-color: #ffeb3b;" title="Yellow 0xFFE0"></div>
                <div class="palette-swatch" style="background-color: #ff9800;" title="Orange"></div>
            </div>

            <!-- 4 Corner Verification Buttons -->
            <button class="corner-btn btn-tl" id="btn-tl">TL [0, 0]</button>
            <button class="corner-btn btn-tr" id="btn-tr">TR [1023, 0]</button>
            <button class="corner-btn btn-bl" id="btn-bl">BL [0, 599]</button>
            <button class="corner-btn btn-br" id="btn-br">BR [1023, 599]</button>

            <!-- Touch Tracking Reticle -->
            <div class="touch-pointer" id="touch-pointer"></div>
        </div>
    </div>

    <!-- Simulator Diagnostics & Controls -->
    <div class="sim-controls">
        <div class="sim-badge" id="corner-progress">
            Corner Verification: <strong>0 / 4 verified</strong>
        </div>
        <button class="btn-reset" onclick="resetCorners()">Reset Validation</button>
    </div>

    <script>
        const screen = document.getElementById('screen');
        const pointer = document.getElementById('touch-pointer');
        const touchStats = document.getElementById('touch-stats');
        const cornerProgress = document.getElementById('corner-progress');
        const arcFill = document.getElementById('arc-fill');
        const arcLabel = document.getElementById('arc-label');
        const sliderFill = document.getElementById('slider-fill');

        let verifiedCorners = new Set();

        function updateTouch(x, y, active) {
            if (active) {
                pointer.style.display = 'block';
                pointer.style.left = x + 'px';
                pointer.style.top = y + 'px';
                touchStats.innerHTML = `Touch: Active | X: ${x.toString().padStart(4, '0')}, Y: ${y.toString().padStart(4, '0')} | GT911 0x5D`;
            } else {
                pointer.style.display = 'none';
                touchStats.innerHTML = 'Touch: Released (Ready)';
            }
        }

        function getLcdCoordinates(e) {
            const rect = screen.getBoundingClientRect();
            let x = Math.round(e.clientX - rect.left);
            let y = Math.round(e.clientY - rect.top);
            x = Math.max(0, Math.min(1023, x));
            y = Math.max(0, Math.min(599, y));
            return { x, y };
        }

        let isPointerDown = false;

        screen.addEventListener('mousedown', (e) => {
            isPointerDown = true;
            const { x, y } = getLcdCoordinates(e);
            updateTouch(x, y, true);
        });

        window.addEventListener('mousemove', (e) => {
            if (isPointerDown) {
                const { x, y } = getLcdCoordinates(e);
                updateTouch(x, y, true);
            }
        });

        window.addEventListener('mouseup', () => {
            if (isPointerDown) {
                isPointerDown = false;
                updateTouch(0, 0, false);
            }
        });

        // Touch event support for iPad / touch laptops
        screen.addEventListener('touchstart', (e) => {
            e.preventDefault();
            if (e.touches.length > 0) {
                const { x, y } = getLcdCoordinates(e.touches[0]);
                updateTouch(x, y, true);
            }
        }, { passive: false });

        screen.addEventListener('touchmove', (e) => {
            e.preventDefault();
            if (e.touches.length > 0) {
                const { x, y } = getLcdCoordinates(e.touches[0]);
                updateTouch(x, y, true);
            }
        }, { passive: false });

        screen.addEventListener('touchend', () => {
            updateTouch(0, 0, false);
        });

        // 4 Corner validation logic
        ['tl', 'tr', 'bl', 'br'].forEach((id) => {
            const btn = document.getElementById('btn-' + id);
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                btn.classList.add('verified');
                verifiedCorners.add(id);
                cornerProgress.innerHTML = `Corner Verification: <strong>${verifiedCorners.size} / 4 verified</strong>${verifiedCorners.size === 4 ? ' ✨ (All Corners Aligned!)' : ''}`;
            });
        });

        function resetCorners() {
            verifiedCorners.clear();
            ['tl', 'tr', 'bl', 'br'].forEach((id) => {
                document.getElementById('btn-' + id).classList.remove('verified');
            });
            cornerProgress.innerHTML = 'Corner Verification: <strong>0 / 4 verified</strong>';
        }

        // Benchmark 60 FPS animation loop
        let angle = 0;
        function animateBenchmark() {
            angle = (angle + 2) % 360;
            const pct = Math.round((Math.sin(angle * Math.PI / 180) + 1) * 50);
            
            // Circular arc math (perimeter = 2 * PI * 50 ≈ 314.15)
            const offset = 314 - (314 * pct / 100);
            arcFill.style.strokeDashoffset = offset;
            arcLabel.innerText = pct + '%';
            
            sliderFill.style.width = pct + '%';
            
            requestAnimationFrame(animateBenchmark);
        }
        requestAnimationFrame(animateBenchmark);
    </script>
</body>
</html>
"""


class SimulatorHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        encoded = HTML_CONTENT.encode("utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        pass


def run_simulator(port: int = 8794, open_browser: bool = True) -> None:
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), SimulatorHandler) as httpd:
        url = f"http://localhost:{port}"
        print(f"==================================================")
        print(f" Waveshare ESP32-S3-Touch-LCD-7B Local Simulator")
        print(f" Running at: {url}")
        print(f" Press Ctrl+C to stop.")
        print(f"==================================================")
        if open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nSimulator stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Waveshare ESP32-S3-Touch-LCD-7B Display Simulator")
    parser.add_argument("--port", type=int, default=8794, help="HTTP port (default: 8794)")
    parser.add_argument("--no-open", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()
    run_simulator(port=args.port, open_browser=not args.no_open)
