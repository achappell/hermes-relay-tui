# Task 2 report: same-origin Python display server

## Original implementation

Implemented `home_display.server.DisplayServer` with the approved interface:

- Binds to `127.0.0.1` by default and derives the listening port from the
  bound socket.
- Exposes `DisplayServerInfo` with `host`, `port`, `http_url`, and
  `websocket_url`.
- Uses the existing legacy-compatible `websockets` server API, with `/state`
  reserved for WebSocket upgrades.
- Serves `/` as `index.html` and serves other static files with MIME types.
- URL-decodes static request paths and rejects absolute paths and lexical
  `..` components.
- Subscribes once per WebSocket client, sends the publisher's current snapshot
  first, forwards later snapshots without reconnecting, and closes the
  subscription when the client disconnects.
- Keeps the display server independent of Textual, `app.py`, terminal
  assumptions, and Hermes event parsing.

Focused tests covered static serving, MIME assets, initial state hydration,
live updates, loopback binding, URL-decoded absolute paths, and lexical path
traversal. The implementation was committed as `e691492`.

## Fix round 1

Added regression tests before implementation for the two reviewer findings.
The tests initially failed because symlink targets were not checked after
resolution and WebSocket upgrades to an existing static asset returned HTTP
200.

The server now resolves the candidate static path and requires the resolved
path to remain relative to the resolved static directory, rejecting symlink
escapes as well as lexical traversal. It also returns HTTP 404 for WebSocket
upgrade requests to every path except `/state`, while preserving ordinary
static HTTP requests.

Validation:

- `venv/bin/pytest tests/test_home_display_server.py -v`: 7 passed
- `venv/bin/pytest tests/test_home_display_server.py tests/test_core_boundary.py -v`: 20 passed
- `git diff --check`: clean

The worktree-local virtual environment lacks `websockets`; both commands used
`/Users/amandachappell/Development/hermes-relay-tui/venv/bin/pytest`.

## Final-review fix round: Python stream

Added TDD regressions for the final Python review findings. The RED run was:

- `venv/bin/pytest tests/test_home_display_server.py tests/test_home_display_state.py -v`: 4 failed, 12 passed; non-loopback hosts were accepted, an unrelated WebSocket origin connected, and non-JSON media was accepted.

The fixes are limited to the Python server/state stream:

- `DisplayServer` now accepts only literal loopback IP addresses, rejecting
  wildcard and non-loopback hosts before binding. IPv6 loopback URLs are
  formatted safely when used.
- `/state` now accepts no-Origin local clients and the server's bound HTTP
  origin, including its printed trailing-slash URL, while rejecting unrelated
  origins with HTTP 403.
- `DisplaySnapshot` now validates `media` with strict JSON serialization
  (`allow_nan=False`) and raises `ValueError` during snapshot construction or
  publisher publication for unsupported values. `media=None` is unchanged.

Validation:

- `/Users/amandachappell/Development/hermes-relay-tui/venv/bin/pytest tests/test_home_display_server.py tests/test_home_display_state.py -v`: 16 passed
- `/Users/amandachappell/Development/hermes-relay-tui/venv/bin/pytest`: 280 passed
- `git diff --check`: clean

The worktree-local virtual environment still lacks `websockets`, so the
repository venv was used. The only test warning is the expected deprecation
notice for the required `websockets.legacy` API. No browser files or plan,
spec, or ledger files were changed.
