# Waveshare ESP32-S3-Touch-LCD-7B Firmware

Firmware baseline and hardware bring-up for the **Waveshare ESP32-S3-Touch-LCD-7B** (1024×600 RGB IPS LCD, GT911 capacitive touch controller, 16MB Flash, 8MB Octal PSRAM) acting as the dedicated household smart display appliance for **Hermes**.

---

## Hardware Specifications

| Component | Specification | Description |
|---|---|---|
| **MCU** | ESP32-S3-WROOM-1-N16R8 | Dual-core Xtensa LX7 @ 240MHz, Vector Instructions |
| **Flash** | 16MB Quad SPI (QIO) | Embedded firmware, wake models, fonts, assets |
| **PSRAM** | 8MB Octal SPI (OPI @ 80MHz) | Double-buffered framebuffers (~2.45MB) + LVGL heap |
| **Display** | 7.0" IPS LCD (1024×600) | 16-bit parallel RGB565 interface, 30MHz PCLK |
| **Touch** | Goodix GT911 | 5-point capacitive multi-touch over I2C |
| **IO Expander** | CH422G at 0x24 | Shared I2C control for LCD_RST, TP_RST, DISP, SD_CS and brightness |
| **Backlight** | CH422G enable + PWM | Smooth hardware brightness scaling (0..97%) |

---

## Pinout Mapping

### 1. 16-bit RGB LCD Interface

| Signal | GPIO | Description |
|---|:---:|---|
| `PCLK` | **GPIO 7** | Pixel clock (30 MHz) |
| `VSYNC` | **GPIO 3** | Vertical sync |
| `HSYNC` | **GPIO 46** | Horizontal sync |
| `DE` | **GPIO 5** | Data enable |
| `R3`..`R7` | **GPIO 1, 2, 42, 41, 40** | Red data bus (5 bits) |
| `G2`..`G7` | **GPIO 39, 0, 45, 48, 47, 21** | Green data bus (6 bits) |
| `B3`..`B7` | **GPIO 14, 38, 18, 17, 10** | Blue data bus (5 bits) |

### 2. GT911 Touch & I2C Bus

| Signal | GPIO | Description |
|---|:---:|---|
| `I2C SDA` | **GPIO 8** | I2C Data (with pull-up) |
| `I2C SCL` | **GPIO 9** | I2C Clock (with pull-up) |
| `TP_INT` | **GPIO 4** | GT911 interrupt / address select |
| `TP_RST` | **CH422G EXIO1** | GT911 hardware reset |

### 3. Backlight & Power

| Signal | Pin / Channel | Description |
|---|:---:|---|
| `DISP` (enable) | **CH422G EXIO2** | Backlight / display enable |
| `LCD_RST` | **CH422G EXIO3** | LCD panel reset |
| `LCD_BL` (PWM) | **CH422G PWM register** | Hardware brightness scaling |
| `LCD_VDD_EN` | **CH422G EXIO6** | Panel voltage enable |

---

## Memory Budget & Octal PSRAM

- **Frame Buffer Size:** $1024 \times 600 \times 2\text{ bytes} = 1,228,800\text{ bytes} \approx 1.23\text{ MB}$ per buffer.
- **Double Buffering:** 2 full frame buffers allocated directly in Octal PSRAM $= 2.45\text{ MB}$.
- **Remaining PSRAM:** $\approx 5.55\text{ MB}$ reserved for:
  - LVGL widget heap & image cache (~1.5 MB)
  - Audio RX/TX ring buffers (~512 KB)
  - `microWakeWord` neural network weights & vector buffers (~1.0 MB)
  - WebSocket network buffers & TLS session memory (~512 KB)

---

## Build & Flashing

### Using ESP-IDF (v5.1+)

```bash
cd firmware/esp32-s3-touch-lcd-7
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/tty.usbmodem* flash monitor
```

### Using PlatformIO

```bash
cd firmware/esp32-s3-touch-lcd-7
pio run -e esp32-s3-touch-lcd-7b -t upload
pio device monitor
```

---

## Validation Scenario (ESP-01 Acceptance Test)

1. **Power-On & PSRAM Check:** Monitor serial output at 115200 baud; confirm Octal PSRAM detects 8MB total with >= 5MB free after double buffer allocation.
2. **Display Timing & Signal Check:** Confirm the 1024×600 IPS display lights up with crisp text, correct color palette bars (Red, Green, Blue, Cyan, Magenta, Yellow), and zero horizontal/vertical sync tearing.
3. **4-Corner Touch Accuracy Test:**
   - Tap **TL [0, 0]** (Top-Left): Button turns green.
   - Tap **TR [1023, 0]** (Top-Right): Button turns green.
   - Tap **BL [0, 599]** (Bottom-Left): Button turns green.
   - Tap **BR [1023, 599]** (Bottom-Right): Button turns green.
4. **Benchmark & Frame Rate:** Confirm benchmark arc/slider animates smoothly at 30+ FPS without visual stutter or PSRAM bandwidth under-run artifacts. The 7B timing is 30MHz PCLK with 1386×661 total timing, approximately 32.7Hz.

## ESP-02 Shared Display Shell

The firmware and native simulator now consume the same bounded C snapshot model
(`ui_snapshot`) and LVGL surface (`ui_display`). The JSON parser accepts the
schema-1 `DisplaySnapshot` contract emitted by `home_display/server.py`,
including the nine display states and bounded prompt options. The ESP-IDF
WebSocket client subscribes to the server's `/state` endpoint, reassembles
fragmented JSON frames, and uses the built-in reconnect ladder. The host
appliance must opt into a LAN bind with `--display-remote`; loopback remains
the default.

The native simulator demonstrates the state surface without a relay. With the
window focused, press `1` for idle, `2` for listening, `3` for speaking, `4`
for a two-choice prompt, or `5` for an error. The diagnostic line retains live
touch coordinates and frame rate while the same UI sources build for ESP-IDF.
