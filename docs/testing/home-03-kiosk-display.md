# HOME-03 kiosk display smoke procedure

The HOME-03 display demo is a local fake-state source. It does not connect to
Hermes, use audio or hardware, or load photos or YouTube.

## Build the browser shell

Run these commands from the repository root:

```bash
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
