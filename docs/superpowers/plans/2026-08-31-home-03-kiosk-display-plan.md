# HOME-03 Kiosk Display Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a browser-based kiosk display shell with a Python-owned local state channel, fake-state validation, and explicit seams for future touch and media surfaces.

**Architecture:** Add a front-end-specific `home_display/` Python package that publishes versioned snapshots and serves the compiled web app plus a `/state` WebSocket from one loopback origin. Build a Svelte/Vite/TypeScript browser app that renders the seven approved states, keeps streamed text in one stable region, and reconnects without importing or duplicating Hermes session logic.

**Tech Stack:** Python 3.14, existing `websockets` dependency, Svelte, Vite, TypeScript, Vitest, Chromium kiosk validation.

**Spec:** `docs/superpowers/specs/2026-08-31-home-03-kiosk-display-design.md`

## Global Constraints

- The front end lives in this repository under `home_display/`; do not create a second repository.
- The display is browser-based and must not import `app.py` or Textual.
- The host binds to `127.0.0.1` and serves static assets and WebSocket state from one configured local origin.
- The appliance must not need Node at runtime; compiled assets are the runtime input.
- States are `idle`, `listening`, `thinking`, `speaking`, `buffering`, `error`, and `disconnected`.
- Snapshots use `schema: 1`, a monotonic `sequence`, stable `response_text`, nullable `status_text`, and nullable future `media` data.
- The browser ignores stale snapshots and receives the latest snapshot immediately after connecting.
- The first implementation has no visible touch controls, real photo playback, YouTube integration, Hermes connection, audio capture, or appliance supervision.
- Tests must not require a live Hermes endpoint, audio hardware, photo library, YouTube, Chromium hardware, or target-panel hardware.
- Run `venv/bin/pytest` before completion.

## File Map

- Create `home_display/__init__.py` — package boundary and public exports.
- Create `home_display/state.py` — snapshot value object and async publisher.
- Create `home_display/server.py` — same-origin static host and `/state` WebSocket server.
- Create `home_display/demo.py` — deterministic fake-state source.
- Modify `pyproject.toml` — package and compiled static asset metadata.
- Create `home_display/web/` — Svelte/Vite source, build config, and browser tests.
- Build `home_display/static/` — compiled browser assets served at runtime.
- Create `tests/test_home_display_state.py`, `tests/test_home_display_server.py`, and `tests/test_home_display_demo.py`.
- Create frontend `*.test.ts` files for protocol, channel, and surface behavior.
- Modify `tests/test_packaging.py`, `README.md`, and create `docs/testing/home-03-kiosk-display.md`.

Before implementation begins, reconcile the project board’s current `HOME-07` item, which is also marked `Building`; then move `HOME-03` to `Building`. After validation, move `HOME-03` to `Verify` and attach evidence. Do not mark it `Done` until merged.

### Task 1: Define the Python snapshot model and publisher

**Files:**

- Create: `home_display/__init__.py`
- Create: `home_display/state.py`
- Test: `tests/test_home_display_state.py`

**Interfaces:**

- `DisplayState = Literal["idle", "listening", "thinking", "speaking", "buffering", "error", "disconnected"]`.
- `DisplaySnapshot` fields: `schema: int`, `sequence: int`, `state: DisplayState`, `response_text: str`, `status_text: str | None`, `media: dict[str, object] | None`.
- `DisplaySnapshot.to_dict() -> dict[str, object]`.
- `DisplayStatePublisher.snapshot -> DisplaySnapshot`.
- `DisplayStatePublisher.publish(*, state, response_text="", status_text=None, media=None) -> DisplaySnapshot`.
- `DisplayStatePublisher.subscribe() -> AsyncIterator[DisplaySnapshot]`, yielding the current snapshot first and newest updates thereafter.

- [ ] **Step 1: Write failing tests for the initial snapshot, validation, sequence ordering, and subscriber hydration.**

```python
import asyncio
import pytest
from home_display.state import DisplaySnapshot, DisplayStatePublisher


def test_initial_snapshot_is_idle_and_json_safe():
    assert DisplayStatePublisher().snapshot.to_dict() == {
        "type": "snapshot", "schema": 1, "sequence": 0,
        "state": "idle", "response_text": "", "status_text": None,
        "media": None,
    }


def test_snapshot_rejects_unknown_state_and_negative_sequence():
    with pytest.raises(ValueError, match="state"):
        DisplaySnapshot(sequence=0, state="unknown")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sequence"):
        DisplaySnapshot(sequence=-1, state="idle")


@pytest.mark.asyncio
async def test_subscriber_starts_current_and_receives_newest_update():
    publisher = DisplayStatePublisher()
    publisher.publish(state="speaking", response_text="hello")
    subscription = publisher.subscribe()
    assert (await anext(subscription)).sequence == 1
    publisher.publish(state="thinking", status_text="working")
    received = await asyncio.wait_for(anext(subscription), timeout=0.2)
    assert received.state == "thinking"
    await subscription.aclose()
```

- [ ] **Step 2: Run `venv/bin/pytest tests/test_home_display_state.py -v`; verify failure because the package is missing.**
- [ ] **Step 3: Implement a frozen/slotted snapshot dataclass with schema/state/sequence/type checks. Implement the publisher with one `asyncio.Queue(maxsize=1)` per subscriber; discard an older pending value before enqueueing a newer snapshot. Start at sequence `0`, increment on each publish, and remove queues in the async-generator `finally` block.**
- [ ] **Step 4: Run `venv/bin/pytest tests/test_home_display_state.py -v`; expect all tests to pass.**
- [ ] **Step 5: Commit with `git add home_display tests/test_home_display_state.py && git commit -m "feat: add home display state publisher"`.**

### Task 2: Add the same-origin Python display server

**Files:**

- Create: `home_display/server.py`
- Test: `tests/test_home_display_server.py`
- Modify: `home_display/__init__.py`

**Interfaces:**

- `DisplayServer(publisher, static_dir, *, host="127.0.0.1", port=0)`.
- `await DisplayServer.start() -> DisplayServerInfo`.
- `await DisplayServer.close() -> None`.
- `DisplayServerInfo.host`, `.port`, `.http_url`, and `.websocket_url`.
- `DisplayServer.resolve_static_path(request_path: str) -> Path`.

- [ ] **Step 1: Write failing tests for `GET /`, initial `/state` hydration, update delivery without reconnect, loopback binding, and `..` path rejection.**

```python
import json
from urllib.request import urlopen
import pytest
from websockets.legacy.client import connect
from home_display.server import DisplayServer
from home_display.state import DisplayStatePublisher


@pytest.mark.asyncio
async def test_server_serves_static_and_current_state(tmp_path):
    (tmp_path / "index.html").write_text("home", encoding="utf-8")
    server = DisplayServer(DisplayStatePublisher(), tmp_path)
    info = await server.start()
    try:
        assert info.host == "127.0.0.1"
        assert urlopen(info.http_url).read() == b"home"
        async with connect(info.websocket_url) as socket:
            assert json.loads(await socket.recv())["state"] == "idle"
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_server_pushes_updates_without_reconnect(tmp_path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    publisher = DisplayStatePublisher()
    server = DisplayServer(publisher, tmp_path)
    info = await server.start()
    try:
        async with connect(info.websocket_url) as socket:
            await socket.recv()
            publisher.publish(state="speaking", response_text="one block")
            update = json.loads(await socket.recv())
        assert update["response_text"] == "one block"
    finally:
        await server.close()


def test_static_path_escape_is_rejected(tmp_path):
    server = DisplayServer(DisplayStatePublisher(), tmp_path)
    with pytest.raises(ValueError, match="path"):
        server.resolve_static_path("/../secret")
```

- [ ] **Step 2: Run `venv/bin/pytest tests/test_home_display_server.py -v`; verify failure because the server is missing.**
- [ ] **Step 3: Implement the loopback server using the existing legacy-compatible `websockets` server API. Keep `/state` available for WebSocket upgrade; serve `index.html` and MIME-typed assets through the HTTP request hook. URL-decode paths, reject absolute paths and any `..` component, derive the port from the bound socket, subscribe once per client, send the current snapshot first, and clean up on normal client close. Do not import Textual or parse Hermes events.**
- [ ] **Step 4: Run `venv/bin/pytest tests/test_home_display_server.py tests/test_core_boundary.py -v`; expect all tests to pass and Textual to stay out of `sys.modules`.**
- [ ] **Step 5: Commit with `git add home_display tests/test_home_display_server.py && git commit -m "feat: serve home display state over localhost"`.**

### Task 3: Scaffold the browser protocol and reconnecting channel

**Files:**

- Create: `home_display/web/package.json`, `package-lock.json`, `index.html`, `tsconfig.json`, `vite.config.ts`.
- Create: `home_display/web/src/state/protocol.ts`, `channel.ts`.
- Test: `home_display/web/src/state/protocol.test.ts`, `channel.test.ts`.

**Interfaces:**

- `parseSnapshot(raw: unknown): DisplaySnapshot | null` accepts only schema-1 snapshots with the seven states.
- `StateChannel` has `start(): void` and `stop(): void`, accepts `onSnapshot`, `onConnectionState`, `onProtocolError`, and an injectable `socketFactory`.
- Reconnect delays are `250ms`, `500ms`, `1000ms`, `2000ms`, and `4000ms`, capped at `4000ms`; only one reconnect timer may exist.

- [ ] **Step 1: Add the package scripts and write failing tests for parser rejection, stale-sequence filtering, connection-state callbacks, timer backoff, and `stop()` cleanup.**

```json
{
  "private": true,
  "type": "module",
  "scripts": {
    "build": "vite build",
    "check": "svelte-check --tsconfig ./tsconfig.json",
    "test": "vitest run"
  }
}
```

```typescript
export type ConnectionState = "connecting" | "connected" | "disconnected";
export type SnapshotListener = (snapshot: DisplaySnapshot) => void;
export type SocketFactory = (url: string) => WebSocketLike;
export type ProtocolErrorListener = (message: string) => void;

export interface WebSocketLike {
  onopen: (() => void) | null;
  onmessage: ((event: MessageEvent<string>) => void) | null;
  onerror: (() => void) | null;
  onclose: (() => void) | null;
  close(): void;
}

export const defaultSocketFactory: SocketFactory = (url) => new WebSocket(url);

export class StateChannel {
  constructor(
    private readonly url: string,
    private readonly onSnapshot: SnapshotListener,
    private readonly onConnectionState: (state: ConnectionState) => void,
    private readonly onProtocolError: ProtocolErrorListener = () => {},
    private readonly socketFactory: SocketFactory = defaultSocketFactory,
  ) {}

  start(): void {}
  stop(): void {}
}
```

```typescript
it("rejects an unknown state", () => {
  expect(parseSnapshot({
    type: "snapshot", schema: 1, sequence: 1, state: "unknown",
    response_text: "", status_text: null, media: null,
  })).toBeNull();
});
```

- [ ] **Step 2: Run `npm --prefix home_display/web install && npm --prefix home_display/web test`; verify the new tests fail because the modules are missing.**
- [ ] **Step 3: Implement the literal TypeScript snapshot types, runtime parser, and injectable `StateChannel`. Reset the last accepted sequence on every new socket open so a restarted host can hydrate with a fresh sequence. On close, emit `disconnected`, schedule the next backoff once, and reconnect. On valid newer data, emit the snapshot; on malformed data, retain the last snapshot and call `onProtocolError("display data unavailable")` without throwing from an event callback.**
- [ ] **Step 4: Run `npm --prefix home_display/web test && npm --prefix home_display/web run check`; expect PASS with no diagnostics.**
- [ ] **Step 5: Commit with `git add home_display/web && git commit -m "feat: add home display browser channel"`.**

### Task 4: Render the approved ambient and voice surfaces

**Files:**

- Create: `home_display/web/src/App.svelte`, `src/surfaces/StateSurface.svelte`, and `src/styles.css`.
- Test: `home_display/web/src/App.test.ts` and `src/surfaces/StateSurface.test.ts`.

**Interfaces:**

- `StateSurface` accepts `snapshot: DisplaySnapshot`, `connectionState: ConnectionState`, and optional `protocolError?: string | null`.
- `App` creates a same-origin `StateChannel` on mount and stops it on unmount.
- The response is plain text in one stable element with `[data-response-text]`.

- [ ] **Step 1: Write failing component tests for all seven states, one stable response element, and disconnected-over-stale-state behavior.**

```typescript
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import StateSurface from "./StateSurface.svelte";

const snapshot = (state: string, response_text = "") => ({
  type: "snapshot" as const, schema: 1 as const, sequence: 1,
  state: state as never, response_text, status_text: null, media: null,
});

describe("StateSurface", () => {
  it.each(["idle", "listening", "thinking", "speaking", "buffering", "error", "disconnected"])(
    "renders data-state for %s", (state) => {
      const { container } = render(StateSurface, {
        props: { snapshot: snapshot(state), connectionState: "connected" },
      });
      expect(container.querySelector(`[data-state="${state}"]`)).not.toBeNull();
    },
  );

  it("keeps streamed response text in one DOM region", async () => {
    const { container, rerender } = render(StateSurface, {
      props: { snapshot: snapshot("speaking", "one"), connectionState: "connected" },
    });
    const response = container.querySelector("[data-response-text]");
    await rerender({ snapshot: snapshot("speaking", "one stable block"), connectionState: "connected" });
    expect(container.querySelector("[data-response-text]")).toBe(response);
  });

  it("shows disconnected when the channel is down", () => {
    render(StateSurface, {
      props: { snapshot: snapshot("idle"), connectionState: "disconnected" },
    });
    expect(screen.getByText(/disconnected/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run `npm --prefix home_display/web test -- src/surfaces/StateSurface.test.ts`; verify failure because the components are missing.**
- [ ] **Step 3: Implement a full-viewport, landscape-first Svelte surface. Add distinct `data-state` roots and concise state labels; keep idle quiet, speaking readable, and buffering/error/disconnected action-oriented. Use a single plain-text response element, `clamp()` typography, `min-height: 100dvh`, and high contrast. Add named CSS tokens for the future bottom sheet without rendering touch controls now. Do not add photos, YouTube iframes, terminal chrome, or Rich transcript concepts.**
- [ ] **Step 4: Run `npm --prefix home_display/web test && npm --prefix home_display/web run check && npm --prefix home_display/web run build`; expect PASS and output under `home_display/static/`.**
- [ ] **Step 5: Commit with `git add home_display/web home_display/static && git commit -m "feat: add home display state surfaces"`.**

### Task 5: Add the deterministic fake state source and local smoke procedure

**Files:**

- Create: `home_display/demo.py`.
- Test: `tests/test_home_display_demo.py`.
- Modify: `home_display/__init__.py` and create `docs/testing/home-03-kiosk-display.md`.

**Interfaces:**

- `DEMO_STEPS: tuple[tuple[DisplayState, str, str | None], ...]` covers `idle`, `listening`, `thinking`, `speaking`, `buffering`, `error`, and `idle` in that order.
- `async def run_demo(publisher: DisplayStatePublisher, *, interval: float) -> None` performs one finite sequence for tests.
- The CLI loop starts `DisplayServer` with `home_display/static` and repeats the sequence until interrupted.

- [ ] **Step 1: Write the failing finite-sequence test.**

```python
import pytest
from home_display.demo import DEMO_STEPS, run_demo
from home_display.state import DisplayStatePublisher


@pytest.mark.asyncio
async def test_demo_publishes_the_approved_state_sequence():
    publisher = DisplayStatePublisher()
    await run_demo(publisher, interval=0)
    assert [state for state, _, _ in DEMO_STEPS] == [
        "idle", "listening", "thinking", "speaking", "buffering", "error", "idle",
    ]
    assert publisher.snapshot.state == "idle"
```

- [ ] **Step 2: Run `venv/bin/pytest tests/test_home_display_demo.py -v`; verify failure because `home_display.demo` is missing.**
- [ ] **Step 3: Implement explicit fake labels and response text, a finite `run_demo`, and a repeating CLI wrapper that serves the static shell. Keep it independent of Hermes, audio, photos, YouTube, and hardware. Document the build and run commands below.**

```bash
npm --prefix home_display/web install
npm --prefix home_display/web run check
npm --prefix home_display/web run build
venv/bin/python -m home_display.demo --interval 2
```

- [ ] **Step 4: Run `venv/bin/pytest tests/test_home_display_demo.py tests/test_home_display_server.py -v && npm --prefix home_display/web test && npm --prefix home_display/web run check && npm --prefix home_display/web run build`; expect PASS.**
- [ ] **Step 5: Commit with `git add home_display tests/test_home_display_demo.py docs/testing/home-03-kiosk-display.md && git commit -m "test: add home display fake-state smoke flow"`.**

### Task 6: Package compiled assets without a device Node runtime

**Files:**

- Modify: `pyproject.toml`.
- Modify: `tests/test_packaging.py` and `README.md`.

**Interfaces:**

- Setuptools includes the `home_display` package and `home_display/static/**/*` package data.
- The base dependency list remains unchanged; Svelte, Vite, TypeScript, and browser-test packages are not device runtime dependencies.

- [ ] **Step 1: Add failing packaging and boundary assertions.**

```python
def test_home_display_package_and_static_assets_are_declared():
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert '"home_display"' in text
    assert "static" in text


def test_home_display_python_files_do_not_import_textual():
    for path in Path("home_display").rglob("*.py"):
        assert "import textual" not in path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run `venv/bin/pytest tests/test_packaging.py -v`; verify the new assertions fail before metadata changes.**
- [ ] **Step 3: Configure setuptools package discovery/data and document that the frontend build runs before the Python distribution build. Add a README link to the HOME-03 smoke procedure and explicitly describe touch, photos, YouTube, Hermes, and audio as outside this slice.**
- [ ] **Step 4: Run `venv/bin/pytest tests/test_packaging.py tests/test_core_boundary.py -v && npm --prefix home_display/web run build && venv/bin/python -m build`; expect PASS and confirm the wheel/sdist contains `home_display` and compiled assets.**
- [ ] **Step 5: Commit with `git add pyproject.toml tests/test_packaging.py README.md home_display/static && git commit -m "build: package home display assets"`.**

### Task 7: Complete focused, full, and manual verification

**Files:**

- Modify: `docs/testing/home-03-kiosk-display.md` with the actual verification date/results.
- Modify: the `HOME-03` GitHub Project item with evidence and workflow state.

- [ ] **Step 1: Run focused verification.**

```bash
venv/bin/pytest tests/test_home_display_state.py tests/test_home_display_server.py tests/test_home_display_demo.py tests/test_core_boundary.py -v
npm --prefix home_display/web test
npm --prefix home_display/web run check
```

Expected: all focused Python and frontend tests pass with no frontend diagnostics.

- [ ] **Step 2: Run `venv/bin/pytest`; expect the complete repository suite to pass.**
- [ ] **Step 3: Run `npm --prefix home_display/web run build && venv/bin/python -m home_display.demo --interval 2`; verify every state, one stable response block, honest disconnected state on host stop, and reconnect/hydration after host restart. Review at roughly two metres in landscape orientation.**
- [ ] **Step 4: Run `git diff --check`, `git status --short`, and `venv/bin/python -m zipfile -l dist/*.whl | rg 'home_display/(static|state|server)'`; confirm no token, prompt, response capture, audio, credential, or unintended generated file is present.**
- [ ] **Step 5: Attach focused/full/build/manual evidence to `HOME-03`, move it from `Building` to `Verify`, and leave it out of `Done` until the validated change is merged.**
