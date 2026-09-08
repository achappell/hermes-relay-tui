#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WASM_SOURCE_DIR="$REPO_ROOT/shared/display/wasm"
FIRMWARE_SOURCE_DIR="$REPO_ROOT/firmware/esp32-s3-touch-lcd-7"

# Keep the browser artifact reproducible. The Emscripten release is taken from
# the official emsdk release map; LVGL matches the native SDL target.
EMSCRIPTEN_VERSION="6.0.5"
LVGL_VERSION="8.3.11"

EMCC="${EMCC:-emcc}"
BUILD_DIR="${DISPLAY_WASM_BUILD_DIR:-$REPO_ROOT/build/display-wasm}"
LVGL_DIR="${LVGL_DIR:-$BUILD_DIR/lvgl-$LVGL_VERSION}"
OUTPUT_DIR="${DISPLAY_WASM_OUTPUT_DIR:-$REPO_ROOT/home_display/web/public/wasm}"

EXPORTED_FUNCTIONS='["_display_wasm_abi_version","_display_wasm_init","_display_wasm_reset","_display_wasm_state_from_name","_display_wasm_apply_snapshot","_display_wasm_validate_choice","_display_wasm_validate_dismiss","_display_wasm_set_connection_state","_display_wasm_set_pointer","_display_wasm_action_pending","_display_wasm_action_id","_display_wasm_action_choice","_display_wasm_action_clear","_display_wasm_view_state","_display_wasm_view_sequence","_display_wasm_view_is_busy","_display_wasm_view_connection_healthy","_display_wasm_view_can_choose","_display_wasm_view_can_dismiss","_display_wasm_framebuffer","_display_wasm_framebuffer_width","_display_wasm_framebuffer_height","_display_wasm_tick"]'
EXPORTED_RUNTIME_METHODS='["ccall","cwrap","HEAPU8"]'

die() {
    echo "build_display_wasm: $*" >&2
    exit 1
}

usage() {
    cat >&2 <<EOF
Usage: $0 [--check]

Builds the shared LVGL display core for the browser. Set EMCC, LVGL_DIR,
DISPLAY_WASM_BUILD_DIR, or DISPLAY_WASM_OUTPUT_DIR to override local paths.
EOF
}

check_toolchain() {
    command -v "$EMCC" >/dev/null 2>&1 || die "Emscripten $EMSCRIPTEN_VERSION is required; install and activate that emsdk version before building."
    local version_output
    version_output="$("$EMCC" --version 2>&1 || true)"
    grep -Fq "$EMSCRIPTEN_VERSION" <<<"$version_output" || die "expected Emscripten $EMSCRIPTEN_VERSION, got: ${version_output%%$'\n'*}"
}

ensure_lvgl() {
    if [[ -f "$LVGL_DIR/lvgl.h" ]]; then
        return
    fi
    if [[ -e "$LVGL_DIR" ]]; then
        die "LVGL source directory exists but is missing lvgl.h: $LVGL_DIR"
    fi
    mkdir -p "$(dirname "$LVGL_DIR")"
    echo "Fetching LVGL $LVGL_VERSION sources..."
    git clone --depth 1 --branch "v$LVGL_VERSION" https://github.com/lvgl/lvgl.git "$LVGL_DIR"
}

if [[ $# -gt 1 ]]; then
    usage
    exit 2
fi
if [[ $# -eq 1 && "$1" != "--check" ]]; then
    usage
    exit 2
fi

check_toolchain
if [[ $# -eq 1 ]]; then
    [[ -f "$LVGL_DIR/lvgl.h" ]] || die "LVGL $LVGL_VERSION sources are missing at $LVGL_DIR; run the build once to fetch them."
    echo "Emscripten $EMSCRIPTEN_VERSION and LVGL $LVGL_VERSION are ready."
    exit 0
fi

ensure_lvgl
mkdir -p "$OUTPUT_DIR" "$BUILD_DIR"

sources=(
    "$REPO_ROOT/shared/display/display_rules.c"
    "$REPO_ROOT/shared/display/display_wasm.c"
    "$FIRMWARE_SOURCE_DIR/main/src/ui_snapshot.c"
    "$FIRMWARE_SOURCE_DIR/main/src/ui_display.c"
)
while IFS= read -r source; do
    sources+=("$source")
done < <(find "$LVGL_DIR/src" -type f -name '*.c' -print | sort)

"$EMCC" \
    -std=c11 \
    -O2 \
    -DNDEBUG \
    -DDISPLAY_WASM=1 \
    -DDISPLAY_WASM_WITH_LVGL=1 \
    -DLV_CONF_INCLUDE_SIMPLE \
    -I"$WASM_SOURCE_DIR" \
    -I"$LVGL_DIR" \
    -I"$FIRMWARE_SOURCE_DIR/main/include" \
    -I"$REPO_ROOT/shared/display" \
    "${sources[@]}" \
    -sMODULARIZE=1 \
    -sEXPORT_ES6=1 \
    -sEXPORT_NAME=DisplayCoreModule \
    -sENVIRONMENT=web \
    -sALLOW_MEMORY_GROWTH=1 \
    -sINITIAL_MEMORY=16777216 \
    -sFILESYSTEM=0 \
    "-sEXPORTED_FUNCTIONS=$EXPORTED_FUNCTIONS" \
    "-sEXPORTED_RUNTIME_METHODS=$EXPORTED_RUNTIME_METHODS" \
    -o "$OUTPUT_DIR/display_core.js"

[[ -s "$OUTPUT_DIR/display_core.js" ]] || die "Emscripten did not produce $OUTPUT_DIR/display_core.js"
[[ -s "$OUTPUT_DIR/display_core.wasm" ]] || die "Emscripten did not produce $OUTPUT_DIR/display_core.wasm"

echo "Built display_core.js and display_core.wasm in $OUTPUT_DIR"
