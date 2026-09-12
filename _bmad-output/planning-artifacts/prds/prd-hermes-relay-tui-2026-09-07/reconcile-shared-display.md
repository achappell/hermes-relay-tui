# Input Reconciliation — Shared Display and Appliance Sources

## Inputs

The shared display contract, kiosk and wake-word designs, ESP32-S3 firmware notes, appliance loop, and voice testing plans listed in the product brief’s source ledger.

## Coverage

The PRD preserves the shared state/action contract, room-local Active Turn mirroring, live Transcription, explicit active/passive prompt roles, typed choice actions on active ESP32 Touch, direct-use W/K, and TUI surfaces, read-only passive mirroring, ESP32-S3 and iPad Display targets, Ambient Surface fallback, recovery states, closest-Device arbitration, and the single-room pilot boundary.

## Downstream detail intentionally deferred

Wire formats, reducer mechanics, LVGL/WASM implementation, wake-engine selection, exact proximity signals, audio buffering, and hardware electrical/acoustic validation remain architecture or implementation concerns. The PRD names their product consequences and keeps the mechanisms out of the requirements spine.
