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
