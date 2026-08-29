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
        if not isinstance(payload, dict):
            # Same guard _receive_json has, but reported as an event rather
            # than raised: send_turn's contract is "failure arrives as an
            # error event that ends the generator".
            yield {"type": "error", "error": "server sent a non-object JSON frame"}
            return
        kind = payload.get("type")
        event_payload = payload.get("payload")
        if not isinstance(event_payload, dict):
            event_payload = payload

        if kind == "turn_accepted":
            continue
        elif kind in {"text_delta", "message.delta"}:
            preview_value = event_payload.get("text")
            if kind == "message.delta" and event_payload.get("rendered") is not None:
                preview_value = event_payload.get("rendered")
            preview = str(preview_value or "")
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
        elif kind == "message.start":
            yield {"type": "message_start"}
        elif kind == "message.complete":
            final_text = str(event_payload.get("text") or event_payload.get("rendered") or "")
            if final_text and not streamed_text:
                yield {"type": "text_delta", "text": final_text}
            elif final_text and final_text != rendered_preview.rstrip("▉"):
                yield {"type": "text_delta", "text": f"\n{final_text}"}
            yield {
                "type": "message_complete",
                "text": final_text,
                "reasoning": str(event_payload.get("reasoning") or ""),
                "failure_reason": str(event_payload.get("failure_reason") or ""),
            }
        elif kind in {"thinking.delta", "reasoning.delta"}:
            thinking_text = str(event_payload.get("text") or "")
            if thinking_text:
                yield {"type": "thinking_delta", "text": thinking_text}
        elif kind == "reasoning.available":
            reasoning_text = str(event_payload.get("text") or "")
            if reasoning_text:
                yield {"type": "thinking_delta", "text": reasoning_text}
            else:
                yield {"type": "reasoning_available"}
        elif kind == "status":
            status_text = str(payload.get("text") or payload.get("status") or "").strip()
            if status_text:
                yield {"type": "status", "text": status_text}
        elif kind == "status.update":
            status_text = str(event_payload.get("text") or "").strip()
            if status_text:
                yield {
                    "type": "status",
                    "text": status_text,
                    "kind": str(event_payload.get("kind") or "status"),
                }
        elif kind == "notification.show":
            notification_text = str(event_payload.get("text") or "").strip()
            if notification_text:
                yield {
                    "type": "notification",
                    "text": notification_text,
                    "level": str(event_payload.get("level") or "info"),
                    "key": str(event_payload.get("key") or ""),
                }
        elif kind == "notification.clear":
            yield {"type": "notification_clear", "key": str(event_payload.get("key") or "")}
        elif kind == "tool.start":
            yield {
                "type": "tool_start",
                "tool_id": str(event_payload.get("tool_id") or ""),
                "name": str(event_payload.get("name") or "tool"),
                "context": str(event_payload.get("context") or ""),
            }
        elif kind in {"tool.progress", "tool.generating"}:
            yield {
                "type": "tool_progress",
                "tool_id": str(event_payload.get("tool_id") or ""),
                "name": str(event_payload.get("name") or "tool"),
                "preview": str(event_payload.get("preview") or "drafting…"),
            }
        elif kind == "tool.complete":
            yield {
                "type": "tool_complete",
                "tool_id": str(event_payload.get("tool_id") or ""),
                "name": str(event_payload.get("name") or "tool"),
                "summary": str(event_payload.get("summary") or ""),
                "error": str(event_payload.get("error") or ""),
            }
        elif kind == "background.complete":
            yield {
                "type": "background_complete",
                "task_id": str(event_payload.get("task_id") or ""),
                "text": str(event_payload.get("text") or ""),
            }
        elif kind == "audio_start":
            yield {
                "type": "audio_start",
                "sample_rate": int(payload.get("sample_rate", 24000)),
                "channels": int(payload.get("channels", 1)),
                "sample_width": int(payload.get("sample_width", 2)),
            }
        elif kind == "error":
            yield {
                "type": "error",
                "error": event_payload.get("error")
                or event_payload.get("message")
                or "voice-session error",
            }
            return
        elif kind == "turn_end":
            yield {"type": "turn_end", "turn_id": turn_id}
            return
        else:
            yield {
                "type": "unknown_event",
                "event_type": str(kind or "missing"),
                "payload": payload,
            }
