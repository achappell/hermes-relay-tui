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
