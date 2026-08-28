# Hermes Streaming TUI Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Port `hermes-hybrid-tui.py` (a `prompt_toolkit` CLI client for the Hermes voice-session websocket) into a modular Textual TUI with the same functionality: text turns, `/voice` mic turns, live-streamed text, live PCM audio playback.

**Architecture:** Five modules — `config.py` (env/arg resolution), `audio.py` (PCM playback), `mic.py` (microphone capture wrapper), `client.py` (websocket protocol, ported to yield structured events instead of printing), `app.py` (Textual `App` that consumes those events and renders them). See `docs/superpowers/specs/2026-08-28-hermes-streaming-tui-design.md` for full design rationale.

**Tech Stack:** Python 3.14, Textual 8.x, `websockets`, `sounddevice`, `python-dotenv` (optional), `pytest` + `pytest-asyncio` for tests.

**Reference script:** `~/Documents/Vaults/Personal Vault/scripts/hermes-hybrid-tui.py` — read this alongside each task; each task cites the exact lines it ports from.

---

## Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pytest.ini`
- Create: `tests/__init__.py` (empty)

**Step 1: Write `requirements.txt`**

```
textual>=8.2
websockets>=12.0
sounddevice>=0.4.6
python-dotenv>=1.0.1
```

**Step 2: Write `requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.0
pytest-asyncio>=0.24
```

**Step 3: Write `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
```

**Step 4: Create empty test package**

```bash
touch tests/__init__.py
```

**Step 5: Install into the project venv**

Run: `venv/bin/pip install -r requirements-dev.txt`
Expected: installs `websockets`, `sounddevice`, `python-dotenv`, `pytest`, `pytest-asyncio` without errors (textual is already present).

**Step 6: Commit**

```bash
git add requirements.txt requirements-dev.txt pytest.ini tests/__init__.py
git commit -m "chore: add project dependencies and test scaffolding"
```

---

## Task 2: `config.py` — env/arg resolution

Ports lines 25–87 and 399–427 of the reference script (defaults, `_env_float`, `_env_int`, `_resolve_token`, `_connect_factory`, `_connection_kwargs`, the `argparse` setup).

**Files:**
- Create: `config.py`
- Test: `tests/test_config.py`

**Step 1: Write the failing tests**

```python
# tests/test_config.py
import os

import pytest

from config import _env_float, _env_int, _resolve_token, _connection_kwargs


def test_env_float_uses_default_when_unset(monkeypatch):
    monkeypatch.delenv("SOME_FLOAT", raising=False)
    assert _env_float("SOME_FLOAT", 1.5) == 1.5


def test_env_float_parses_set_value(monkeypatch):
    monkeypatch.setenv("SOME_FLOAT", "3.25")
    assert _env_float("SOME_FLOAT", 1.5) == 3.25


def test_env_float_falls_back_on_bad_value(monkeypatch):
    monkeypatch.setenv("SOME_FLOAT", "not-a-number")
    assert _env_float("SOME_FLOAT", 1.5) == 1.5


def test_env_int_parses_set_value(monkeypatch):
    monkeypatch.setenv("SOME_INT", "42")
    assert _env_int("SOME_INT", 7) == 42


def test_resolve_token_prefers_explicit_argument(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("VOICE_SESSION_TOKEN=from-file\n")
    assert _resolve_token("explicit-token", env_path) == "explicit-token"


def test_resolve_token_prefers_env_var_over_file(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("VOICE_SESSION_TOKEN=from-file\n")
    monkeypatch.setenv("VOICE_SESSION_TOKEN", "from-environment")
    assert _resolve_token(None, env_path) == "from-environment"


def test_resolve_token_reads_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("VOICE_SESSION_TOKEN", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text('VOICE_SESSION_TOKEN="quoted-token"\n')
    assert _resolve_token(None, env_path) == "quoted-token"


def test_resolve_token_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("VOICE_SESSION_TOKEN", raising=False)
    assert _resolve_token(None, tmp_path / "nope.env") == ""


def test_connection_kwargs_uses_additional_headers_when_supported():
    def fake_connect(url, additional_headers=None, max_size=None):
        pass

    kwargs = _connection_kwargs(fake_connect, "tok")
    assert kwargs["additional_headers"] == {"Authorization": "Bearer tok"}


def test_connection_kwargs_falls_back_to_extra_headers():
    def fake_connect(url, extra_headers=None, max_size=None):
        pass

    kwargs = _connection_kwargs(fake_connect, "tok")
    assert kwargs["extra_headers"] == {"Authorization": "Bearer tok"}
```

**Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_config.py -v`
Expected: `ModuleNotFoundError: No module named 'config'`

**Step 3: Write `config.py`**

```python
"""Environment/argument resolution for the Hermes streaming TUI.

Ported from hermes-hybrid-tui.py's config/argparse setup, unchanged in
behavior — only relocated so config concerns don't live in the same
file as protocol or UI code.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Optional

DEFAULT_URL = "ws://100.90.186.57:8792/voice-session"
DEFAULT_CHECKOUT = Path.home() / ".hermes" / "hermes-agent"
DEFAULT_PROFILE_ENV = Path.home() / ".hermes" / "profiles" / "amanda" / ".env"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _resolve_token(explicit: Optional[str], env_path: Path) -> str:
    if explicit:
        return explicit
    from_environment = os.getenv("VOICE_SESSION_TOKEN", "").strip()
    if from_environment:
        return from_environment
    if not env_path.exists():
        return ""
    try:
        from dotenv import dotenv_values

        value = dotenv_values(env_path).get("VOICE_SESSION_TOKEN")
        return str(value).strip() if value else ""
    except ImportError:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line.startswith("VOICE_SESSION_TOKEN="):
                continue
            value = line.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            return value
    except OSError:
        return ""
    return ""


def connect_factory():
    try:
        from websockets.asyncio.client import connect
    except ImportError:
        from websockets import connect  # type: ignore[no-redef]
    return connect


def _connection_kwargs(connect: Any, token: str) -> dict[str, Any]:
    import inspect

    headers = {"Authorization": f"Bearer {token}"}
    try:
        params = inspect.signature(connect).parameters
    except (TypeError, ValueError):
        params = {}
    header_name = "additional_headers" if "additional_headers" in params else "extra_headers"
    return {header_name: headers, "max_size": 256 * 1024}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes streaming TUI")
    parser.add_argument("--url", default=os.getenv("HERMES_VOICE_SESSION_URL", DEFAULT_URL))
    parser.add_argument("--token", help="Bearer token; prefer VOICE_SESSION_TOKEN or the profile .env")
    parser.add_argument("--profile-env", type=Path, default=DEFAULT_PROFILE_ENV)
    parser.add_argument("--checkout", type=Path, default=DEFAULT_CHECKOUT)
    parser.add_argument("--client-id", default=os.getenv("VOICE_SESSION_CLIENT_ID", "amanda-laptop"))
    parser.add_argument("--device-id", default=os.getenv("VOICE_SESSION_DEVICE_ID", "amanda-mac"))
    parser.add_argument("--session-id", default=os.getenv("VOICE_SESSION_ID", "hybrid-tui"))
    parser.add_argument("--display-name", default="Amanda streaming TUI")
    parser.add_argument("--history", type=Path, default=Path.home() / ".hermes" / "streaming-tui-history")
    parser.add_argument("--no-play", action="store_true", help="buffer audio instead of opening the local speaker")
    parser.add_argument("--output", type=Path, help="also save each response WAV (later turns get a suffix)")
    parser.add_argument("--mic-max-seconds", type=float, default=_env_float("VOICE_SESSION_MIC_MAX_SECONDS", 15.0))
    parser.add_argument("--mic-silence-duration", type=float, default=_env_float("VOICE_SESSION_MIC_SILENCE_DURATION", 3.0))
    parser.add_argument("--mic-silence-threshold", type=int, default=_env_int("VOICE_SESSION_MIC_SILENCE_THRESHOLD", 200))
    parser.add_argument("--stt-model", default=os.getenv("VOICE_SESSION_STT_MODEL") or None)
    parser.add_argument(
        "--turn-timeout",
        type=float,
        default=_env_float("VOICE_SESSION_TURN_TIMEOUT", 195.0),
        help="seconds to wait for a response before closing the session (0 disables)",
    )
    return parser
```

**Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_config.py -v`
Expected: all tests PASS

**Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add config module for env/arg resolution"
```

---

## Task 3: `audio.py` — PCM playback

Ports lines 126–176 of the reference script (`PCMPlayer`), unchanged in behavior.

**Files:**
- Create: `audio.py`
- Test: `tests/test_audio.py`

**Step 1: Write the failing tests**

```python
# tests/test_audio.py
import sys
import types

import pytest

from audio import PCMPlayer


def test_disabled_player_never_starts():
    player = PCMPlayer(enabled=False)
    player.start((24000, 1, 2))
    assert not player.active
    assert player.failure is None


def test_unsupported_sample_width_records_failure():
    player = PCMPlayer(enabled=True)
    player.start((24000, 1, 1))  # 8-bit, unsupported
    assert not player.active
    assert "8-bit" in player.failure


def test_start_success_makes_player_active(monkeypatch):
    started = {}

    class FakeStream:
        def start(self):
            started["started"] = True

        def write(self, chunk):
            started["wrote"] = chunk

        def stop(self):
            started["stopped"] = True

        def close(self):
            started["closed"] = True

    fake_module = types.SimpleNamespace(
        RawOutputStream=lambda **kwargs: FakeStream()
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_module)

    player = PCMPlayer(enabled=True)
    player.start((24000, 1, 2))
    assert player.active

    player.write(b"\x00\x01")
    assert started["wrote"] == b"\x00\x01"

    player.close()
    assert started["stopped"] and started["closed"]
    assert not player.active


def test_start_failure_sets_failure_message(monkeypatch):
    fake_module = types.SimpleNamespace(
        RawOutputStream=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("no device"))
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_module)

    player = PCMPlayer(enabled=True)
    player.start((24000, 1, 2))
    assert not player.active
    assert player.failure == "no device"
```

**Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_audio.py -v`
Expected: `ModuleNotFoundError: No module named 'audio'`

**Step 3: Write `audio.py`**

```python
"""PCM audio playback for the Hermes streaming TUI.

Ported from hermes-hybrid-tui.py's PCMPlayer, unchanged in behavior.
"""

from __future__ import annotations

from typing import Any, Optional


class PCMPlayer:
    """Play signed 16-bit PCM chunks locally, with a safe buffering fallback."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.stream: Any = None
        self.failure: Optional[str] = None

    @property
    def active(self) -> bool:
        return self.stream is not None

    def start(self, audio_format: tuple[int, int, int]) -> None:
        if not self.enabled:
            return
        sample_rate, channels, sample_width = audio_format
        if sample_width != 2:
            self.failure = f"unsupported {sample_width * 8}-bit PCM"
            return
        try:
            import sounddevice as sd

            self.stream = sd.RawOutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="int16",
                latency="low",
            )
            self.stream.start()
        except Exception as exc:
            self.stream = None
            self.failure = str(exc)

    def write(self, chunk: bytes) -> None:
        if self.stream is None:
            return
        try:
            self.stream.write(chunk)
        except Exception as exc:
            self.failure = str(exc)
            self.close()

    def close(self) -> None:
        if self.stream is None:
            return
        try:
            self.stream.stop()
        finally:
            self.stream.close()
            self.stream = None
```

**Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_audio.py -v`
Expected: all tests PASS

**Step 5: Commit**

```bash
git add audio.py tests/test_audio.py
git commit -m "feat: add audio module for PCM playback"
```

---

## Task 4: `mic.py` — microphone capture wrapper

Ports lines 90–99 of the reference script (`_load_microphone`).

**Files:**
- Create: `mic.py`
- Test: `tests/test_mic.py`

**Step 1: Write the failing tests**

```python
# tests/test_mic.py
import pytest

from mic import load_microphone_class


def test_missing_voice_client_raises(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        load_microphone_class(tmp_path)


def test_loads_local_microphone_class(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "voice-session-client.py").write_text(
        "class LocalMicrophone:\n"
        "    def __init__(self, **kwargs):\n"
        "        self.kwargs = kwargs\n"
        "    def capture(self):\n"
        "        return 'hello'\n"
        "    def close(self):\n"
        "        pass\n"
    )

    microphone_class = load_microphone_class(tmp_path)
    instance = microphone_class(max_seconds=5.0)
    assert instance.capture() == "hello"
```

**Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_mic.py -v`
Expected: `ModuleNotFoundError: No module named 'mic'`

**Step 3: Write `mic.py`**

```python
"""Microphone capture wrapper for the Hermes streaming TUI.

Ported from hermes-hybrid-tui.py's _load_microphone, unchanged in
behavior beyond a clearer public name.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def load_microphone_class(checkout: Path):
    source = checkout / "scripts" / "voice-session-client.py"
    if not source.exists():
        raise RuntimeError(f"Hermes voice client not found at {source}")
    spec = importlib.util.spec_from_file_location("hermes_voice_session_client", source)
    if not spec or not spec.loader:
        raise RuntimeError(f"Could not load Hermes voice client from {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LocalMicrophone
```

**Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_mic.py -v`
Expected: all tests PASS

**Step 5: Commit**

```bash
git add mic.py tests/test_mic.py
git commit -m "feat: add mic module for microphone capture loading"
```

---

## Task 5: `client.py` — protocol event stream

This is the core rewrite: ports lines 178–269 of the reference script (`_receive_json`, `_send_turn`) from print-driven to an async generator yielding structured event dicts, plus the `hello`/`hello_ack` handshake (lines 332–346).

**Files:**
- Create: `client.py`
- Test: `tests/test_client.py`

**Step 1: Write the failing tests**

```python
# tests/test_client.py
import json

import pytest

from client import ProtocolError, send_hello, send_turn


class FakeWebSocket:
    """Minimal fake matching the subset of the websockets API client.py uses."""

    def __init__(self, frames):
        self._frames = list(frames)
        self.sent = []

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if not self._frames:
            raise AssertionError("no more frames queued")
        return self._frames.pop(0)


async def test_send_hello_returns_ack_payload():
    ack = {"type": "hello_ack", "chat_id": "abc"}
    ws = FakeWebSocket([json.dumps(ack)])

    result = await send_hello(
        ws,
        client_id="c1",
        device_id="d1",
        session_id="s1",
        display_name="test",
    )

    assert result == ack
    sent = json.loads(ws.sent[0])
    assert sent["type"] == "hello"
    assert sent["session_id"] == "s1"


async def test_send_hello_rejects_non_ack():
    ws = FakeWebSocket([json.dumps({"type": "error", "error": "nope"})])
    with pytest.raises(ProtocolError):
        await send_hello(ws, client_id="c", device_id="d", session_id="s", display_name="n")


async def test_send_turn_yields_text_deltas_and_turn_end():
    frames = [
        json.dumps({"type": "turn_accepted"}),
        json.dumps({"type": "text_delta", "text": "Hel"}),
        json.dumps({"type": "text_delta", "text": "Hello"}),
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    kinds = [event["type"] for event in events]
    assert kinds == ["text_delta", "text_delta", "turn_end"]
    assert events[0]["text"] == "Hel"
    assert events[1]["text"] == "lo"  # only the new suffix is yielded


async def test_send_turn_yields_audio_chunks_between_start_and_end():
    frames = [
        json.dumps({"type": "audio_start", "sample_rate": 24000, "channels": 1, "sample_width": 2}),
        b"\x00\x01\x02\x03",
        json.dumps({"type": "turn_end"}),
    ]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    kinds = [event["type"] for event in events]
    assert kinds == ["audio_start", "audio_chunk", "turn_end"]
    assert events[1]["data"] == b"\x00\x01\x02\x03"


async def test_send_turn_yields_error_and_stops():
    frames = [json.dumps({"type": "error", "error": "boom"})]
    ws = FakeWebSocket(frames)

    events = [event async for event in send_turn(ws, session_id="s1", text="hi", stt_source="local")]

    assert events == [{"type": "error", "error": "boom"}]
```

**Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_client.py -v`
Expected: `ModuleNotFoundError: No module named 'client'`

**Step 3: Write `client.py`**

```python
"""Websocket protocol client for the Hermes voice-session channel.

Ported from hermes-hybrid-tui.py's _receive_json/_send_turn, restructured
to yield structured events instead of printing them, so a UI layer can
render them however it likes.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator, Optional


class ProtocolError(RuntimeError):
    """Raised when the server sends something the client can't handle."""


async def _receive_json(ws: Any) -> dict[str, Any]:
    while True:
        frame = await ws.recv()
        if isinstance(frame, bytes):
            continue
        payload = json.loads(frame)
        if isinstance(payload, dict):
            return payload
        raise ProtocolError("server sent a non-object JSON frame")


async def send_hello(
    ws: Any,
    *,
    client_id: str,
    device_id: str,
    session_id: str,
    display_name: str,
) -> dict[str, Any]:
    await ws.send(
        json.dumps(
            {
                "type": "hello",
                "protocol_version": 1,
                "client_id": client_id,
                "device_id": device_id,
                "session_id": session_id,
                "display_name": display_name,
            }
        )
    )
    hello = await _receive_json(ws)
    if hello.get("type") != "hello_ack":
        raise ProtocolError(f"voice-session hello failed: {hello}")
    return hello


async def send_turn(
    ws: Any,
    *,
    session_id: str,
    text: str,
    stt_source: str,
    turn_id: Optional[str] = None,
) -> AsyncIterator[dict[str, Any]]:
    turn_id = turn_id or uuid.uuid4().hex
    await ws.send(
        json.dumps(
            {
                "type": "turn",
                "protocol_version": 1,
                "turn_id": turn_id,
                "session_id": session_id,
                "text": text,
                "stt_source": stt_source,
            }
        )
    )

    rendered_preview = ""
    streamed_text = False

    while True:
        frame = await ws.recv()
        if isinstance(frame, bytes):
            yield {"type": "audio_chunk", "data": frame}
            continue

        payload = json.loads(frame)
        kind = payload.get("type")

        if kind == "turn_accepted":
            continue
        elif kind == "text_delta":
            preview = str(payload.get("text") or "")
            if preview.startswith(rendered_preview):
                delta = preview[len(rendered_preview):]
            else:
                delta = f"\n{preview}"
            rendered_preview = preview
            streamed_text = True
            yield {"type": "text_delta", "text": delta}
        elif kind in {"text", "text_final"}:
            final_text = str(payload.get("text") or "")
            if kind == "text" or (kind == "text_final" and not streamed_text):
                yield {"type": "text_delta", "text": final_text}
            elif kind == "text_final" and final_text != rendered_preview.rstrip("▉"):
                yield {"type": "text_delta", "text": f"\n{final_text}"}
        elif kind == "status":
            status_text = str(payload.get("text") or payload.get("status") or "").strip()
            if status_text:
                yield {"type": "status", "text": status_text}
        elif kind == "audio_start":
            yield {
                "type": "audio_start",
                "sample_rate": int(payload.get("sample_rate", 24000)),
                "channels": int(payload.get("channels", 1)),
                "sample_width": int(payload.get("sample_width", 2)),
            }
        elif kind == "error":
            yield {"type": "error", "error": payload.get("error", "voice-session error")}
            return
        elif kind == "turn_end":
            yield {"type": "turn_end", "turn_id": turn_id}
            return
        else:
            continue
```

**Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_client.py -v`
Expected: all tests PASS

**Step 5: Commit**

```bash
git add client.py tests/test_client.py
git commit -m "feat: add client module with event-stream protocol handling"
```

---

## Task 6: `app.py` — Textual App

Ports lines 297–397 of the reference script (`_run`'s prompt loop, `/voice` handling, `/help`, `/quit`) into a Textual `App`. Key bindings replace typed `/voice`, `/help`, `/quit` per the spec revision.

**Files:**
- Modify: `app.py` (replace the "Hello, Textual!" stub entirely)
- Test: `tests/test_app.py`

**Step 1: Write the failing tests**

These use Textual's `App.run_test()` (a `Pilot`) with the websocket/mic layers mocked out — no real network or hardware — to check the app wires up correctly.

```python
# tests/test_app.py
import pytest

from app import HermesStreamingApp


class FakeSession:
    """Stands in for the worker that owns the websocket connection."""

    def __init__(self):
        self.sent_turns = []

    async def send_turn(self, text: str):
        self.sent_turns.append(text)


async def test_app_mounts_with_transcript_and_input():
    app = HermesStreamingApp(session_factory=lambda: FakeSession())
    async with app.run_test() as pilot:
        assert app.query_one("#transcript") is not None
        assert app.query_one("#input") is not None


async def test_submitting_input_sends_a_turn_and_clears_input():
    fake_session = FakeSession()
    app = HermesStreamingApp(session_factory=lambda: fake_session)
    async with app.run_test() as pilot:
        input_widget = app.query_one("#input")
        input_widget.value = "hello hermes"
        await pilot.press("enter")
        assert fake_session.sent_turns == ["hello hermes"]
        assert input_widget.value == ""


async def test_voice_binding_is_registered():
    app = HermesStreamingApp(session_factory=lambda: FakeSession())
    async with app.run_test():
        binding_keys = {binding.key for binding in app._bindings}
        assert "ctrl+r" in binding_keys
```

**Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_app.py -v`
Expected: `ImportError: cannot import name 'HermesStreamingApp' from 'app'`

**Step 3: Write `app.py`**

```python
"""Textual TUI for the Hermes voice-session channel.

Consumes events from client.py (text deltas, status, audio, turn_end)
and renders them into a scrolling transcript, replacing the print()
calls in hermes-hybrid-tui.py's turn loop.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, RichLog

import config
from audio import PCMPlayer
from client import ProtocolError, send_hello, send_turn
from mic import load_microphone_class


class HermesSession:
    """Owns one open websocket connection and turn history for the app's lifetime."""

    def __init__(self, args) -> None:
        self.args = args
        self.ws: Any = None
        self.turn_index = 0
        self.microphone: Any = None

    async def connect(self) -> dict[str, Any]:
        connect = config.connect_factory()
        token = config._resolve_token(self.args.token, self.args.profile_env)
        if not token:
            raise RuntimeError("No voice-session token found. Set VOICE_SESSION_TOKEN or use the profile .env.")
        kwargs = config._connection_kwargs(connect, token)
        self.ws = await connect(self.args.url, **kwargs).__aenter__()
        return await send_hello(
            self.ws,
            client_id=self.args.client_id,
            device_id=self.args.device_id,
            session_id=self.args.session_id,
            display_name=self.args.display_name,
        )

    def send_turn(self, text: str, *, stt_source: str = "local"):
        self.turn_index += 1
        return send_turn(self.ws, session_id=self.args.session_id, text=text, stt_source=stt_source)

    def capture_voice(self) -> str:
        if self.microphone is None:
            microphone_class = load_microphone_class(self.args.checkout)
            self.microphone = microphone_class(
                max_seconds=self.args.mic_max_seconds,
                silence_duration=self.args.mic_silence_duration,
                silence_threshold=self.args.mic_silence_threshold,
                model=self.args.stt_model,
            )
        return self.microphone.capture()


class HermesStreamingApp(App):
    """A Textual TUI for a Hermes voice-session chat."""

    BINDINGS = [
        ("ctrl+r", "voice_turn", "Voice turn"),
        ("f1", "show_help", "Help"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, args=None, session_factory: Optional[Callable[[], Any]] = None) -> None:
        super().__init__()
        self.args = args
        self._session_factory = session_factory
        self.session: Any = None
        self.player = PCMPlayer(enabled=not (args and args.no_play))

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield RichLog(id="transcript", wrap=True, highlight=True)
            yield Input(placeholder="you>", id="input")
        yield Footer()

    async def on_mount(self) -> None:
        self.session = self._session_factory() if self._session_factory else HermesSession(self.args)
        if isinstance(self.session, HermesSession):
            transcript = self.query_one("#transcript", RichLog)
            try:
                hello = await self.session.connect()
                transcript.write(f"Connected to {self.args.session_id} (chat {hello.get('chat_id')}).")
            except (ProtocolError, RuntimeError, OSError, ConnectionError) as exc:
                transcript.write(f"[error] {exc}")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        await self._run_turn(text)

    async def action_voice_turn(self) -> None:
        transcript = self.query_one("#transcript", RichLog)
        if not isinstance(self.session, HermesSession):
            await self.session.send_turn("(voice)")
            return
        transcript.write("listening…")
        transcript_text = await asyncio.to_thread(self.session.capture_voice)
        if not transcript_text:
            transcript.write("no speech detected.")
            return
        transcript.write(f"you (voice): {transcript_text}")
        await self._run_turn(transcript_text, stt_source="local-faster-whisper")

    async def action_show_help(self) -> None:
        self.query_one("#transcript", RichLog).write(
            "Bindings: ctrl+r = voice turn, f1 = help, ctrl+q = quit. Everything typed is sent to Hermes."
        )

    async def _run_turn(self, text: str, *, stt_source: str = "local") -> None:
        transcript = self.query_one("#transcript", RichLog)
        transcript.write(f"you> {text}")
        if not isinstance(self.session, HermesSession):
            await self.session.send_turn(text)
            return

        transcript.write("hermes: ", scroll_end=False)
        async for event in self.session.send_turn(text, stt_source=stt_source):
            kind = event["type"]
            if kind == "text_delta":
                transcript.write(event["text"])
            elif kind == "status":
                transcript.write(f"[{event['text']}]")
            elif kind == "audio_start":
                self.player.start((event["sample_rate"], event["channels"], event["sample_width"]))
                if self.player.active:
                    transcript.write(" [audio streaming]")
                elif self.player.failure:
                    transcript.write(f" [audio buffering: {self.player.failure}]")
            elif kind == "audio_chunk":
                await asyncio.to_thread(self.player.write, event["data"])
            elif kind == "error":
                transcript.write(f"[error] {event['error']}")
            elif kind == "turn_end":
                self.player.close()


def main() -> int:
    parser = config.build_arg_parser()
    args = parser.parse_args()
    app = HermesStreamingApp(args=args)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_app.py -v`
Expected: all tests PASS

**Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: replace stub app with Textual streaming TUI"
```

---

## Task 7: Full test suite + manual end-to-end validation

**Step 1: Run the full automated suite**

Run: `venv/bin/pytest -v`
Expected: all tests across `test_config.py`, `test_audio.py`, `test_mic.py`, `test_client.py`, `test_app.py` PASS.

**Step 2: Manual validation against the real Hermes endpoint**

No automated coverage exists for the real websocket/mic/speaker path (matches the reference script, which also has none). Run these by hand:

1. `venv/bin/python app.py` — confirm it connects and shows "Connected to hybrid-tui (chat ...)."
2. Type a message, press enter — confirm text streams into the transcript live, not all at once.
3. Press `ctrl+r` — confirm "listening…" appears, speak, confirm the transcript shows your words and Hermes' streamed reply, and audio plays through speakers.
4. Press `f1` — confirm the help line appears.
5. Kill network (e.g. toggle Wi-Fi) mid-turn — confirm the app shows an error in the transcript instead of crashing.
6. Press `ctrl+q` — confirm clean exit.

**Step 3: Commit any fixes found during manual validation**

If manual validation surfaces a bug, fix it, add a regression test if the bug was in testable logic (`client.py`, `config.py`, `audio.py`, `mic.py`), and commit:

```bash
git add -A
git commit -m "fix: <describe what manual validation caught>"
```

---

## Task 8: Update `.gitignore` for test artifacts and cleanup

**Files:**
- Modify: `.gitignore`

**Step 1: Add pytest cache to `.gitignore`**

Append to `.gitignore`:

```
.pytest_cache/
```

**Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore pytest cache"
```
