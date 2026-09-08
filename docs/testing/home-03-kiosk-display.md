# HOME-03 kiosk display smoke procedure

The HOME-03 display demo is a local fake-state source. It does not connect to
Hermes, use audio or hardware, or load photos or YouTube. The visible browser
surface is the compiled shared C/LVGL display, with prompt touch actions sent
through the local `/action` adapter.

## Build the browser shell

Run these commands from the repository root:

```bash
source build/display-wasm/emsdk/emsdk_env.sh
bash scripts/build_display_wasm.sh --check
bash scripts/build_display_wasm.sh
npm --prefix home_display/web install
npm --prefix home_display/web run check
npm --prefix home_display/web run build
```

The build writes the static browser shell to `home_display/static/`. Node is a
build-time dependency only; the demo itself runs with Python.

## Run the local demo

```bash
venv/bin/python -m home_display.demo --interval 2
```

Open the printed loopback URL in a browser. The demo repeats this sequence:

`idle` → `listening` → `thinking` → `speaking` → `buffering` → `error` → `idle`.

Stop it with `Ctrl+C`. The browser should show its disconnected state after the
host stops, and should reconnect and hydrate from the current snapshot after a
restart.

For a prompt-action check, serve a snapshot with `state: "prompt"`, one or more
options, and `capabilities.actions: ["prompt.choose"]`. Tap the corresponding
button on the canvas and verify the server receives the normalized
`action_id`/`choice` pair. The shared LVGL layout is 1024x600; the host scales
the backing canvas for device-pixel ratio and maps touches from its CSS bounds.

## Re-verification evidence — 2026-09-07 (CDT)

- `venv/bin/pytest` — 828 passed; one existing `websockets.legacy` deprecation warning.
- `npm --prefix home_display/web test` — 120 passed; `npm --prefix home_display/web run check` — 0 errors and 0 warnings.
- `source build/display-wasm/emsdk/emsdk_env.sh && bash scripts/build_display_wasm.sh` — regenerated the Emscripten 6.0.5 / LVGL 8.3.11 artifacts; the generated ABI smoke covered the framebuffer, fast pointer down/up, and `sethome/yes` action queue.
- `npm --prefix home_display/web run build` — packaged the current canvas host and WASM artifacts under `home_display/static/`.
- Chrome loopback smoke — loaded the packaged `display_core.wasm`, visibly rendered the LVGL header/panel, and advanced from `idle` to `listening` from the Python demo stream. A prompt server rendered the C/LVGL prompt and a canvas tap produced `ACTION sethome yes`.
- `git diff --check` — passed. Voice/audio, physical ESP32 hardware, and iPad-specific review remain outside this slice and belong to HOME-16.

## Verification evidence — 2026-08-31 (CDT)

- `venv/bin/pytest tests/test_home_display_state.py tests/test_home_display_server.py tests/test_home_display_demo.py tests/test_core_boundary.py -v` — 25 passed (one existing `websockets.legacy` deprecation warning).
- `npm --prefix home_display/web test` — 4 files and 31 tests passed.
- `npm --prefix home_display/web run check` — 0 errors and 0 warnings.
- `venv/bin/pytest` — 275 passed (one existing `websockets.legacy` deprecation warning).
- `npm --prefix home_display/web run build` — Vite production build completed; static output was written under `home_display/static/`.
- Live local loopback smoke against `venv/bin/python -u -m home_display.demo --interval 2 --port 0`: HTTP `GET /` returned `200 text/html`; a WebSocket client observed `idle`, `listening`, `thinking`, `speaking`, `buffering`, and `error` in the repeating sequence. The speaking and buffering snapshots carried identical response text. A connected client observed close code `1001` when the host was stopped. After restarting the demo on the same loopback port, a new connection immediately received the current snapshot (`sequence` 3, `thinking`).
- The frontend test suite covers stale-snapshot filtering, WebSocket reconnect behavior, disconnected-over-stale rendering, all seven rendered state surfaces, and replacement of one `[data-response-text]` DOM element. Browser automation and a physical landscape/two-metre review were unavailable in this environment, so neither was performed or claimed.
- `git diff --check` passed; pre-documentation `git status --short` was empty. The wheel contains `home_display/state.py`, `home_display/server.py`, and compiled files in `home_display/static/`. No untracked files or audio captures were found. The only credential-pattern match was an existing unrelated documentation example containing `VOICE_SESSION_TOKEN='redacted-token'`; no secret, prompt/response capture, or credential was added by HOME-03.
- GitHub Project update was attempted with `gh project item-list 3 --owner achappell --format json -L 100`, but GitHub CLI is unauthenticated: `gh auth login` or `GH_TOKEN` is required. HOME-03 was not moved to `Verify` and no board evidence was attached.

## Re-verification evidence — 2026-09-01 (CDT)

- `/Users/amandachappell/Development/hermes-relay-tui/venv/bin/pytest` — 281 passed; one existing `websockets.legacy` deprecation warning. The first sandboxed attempt could not bind loopback sockets; the passing run used permitted loopback access.
- `npm --prefix home_display/web test` — 36 passed; `npm --prefix home_display/web run check` — 0 errors and 0 warnings; `npm --prefix home_display/web run build` — passed.
- `/Users/amandachappell/Development/hermes-relay-tui/venv/bin/python -m build` — passed after allowing the isolated build environment to reach PyPI; the wheel contains `home_display`, `home_display/static`, and both console entry points.
- Live loopback smoke against `python -u -m home_display.demo --interval 0.5`: `GET /` returned `200 text/html`; WebSocket delivery observed `idle`, `listening`, `thinking`, `speaking`, `buffering`, and `error`. The demo was stopped cleanly afterward.
- `git diff --check` and `git status --short --untracked-files=all` — clean before this evidence update. GUI permissions still prevented rendered-browser/physical two-metre review; `gh project item-list` still failed because GitHub CLI is unauthenticated.
