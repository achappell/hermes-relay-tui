"""Websocket protocol client for the Hermes voice-session channel.

Ported from hermes-hybrid-tui.py's _receive_json/_send_turn, restructured
to yield structured events instead of printing them, so a UI layer can
render them however it likes.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import uuid
from typing import Any, AsyncIterator, Optional

from diagnostics import summarize_payload, summarize_text


logger = logging.getLogger("hermes_relay_tui.client")


class ProtocolError(RuntimeError):
    """Raised when the server sends something the client can't handle."""


def _decode_audio_data(value: Any) -> Optional[bytes]:
    """Decode an optional inline file payload without guessing at text data."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, list):
        try:
            return bytes(value)
        except ValueError:
            return None
    if isinstance(value, str):
        try:
            return base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            return None
    return None


def _final_text_update(
    final_text: str,
    rendered_preview: str,
    streamed_text: bool,
) -> Optional[dict[str, str]]:
    """Return the append-or-replace update needed for a terminal text frame."""
    if not final_text:
        return None
    if not streamed_text:
        return {"type": "text_delta", "text": final_text}
    preview = rendered_preview.rstrip("▉")
    if final_text == preview:
        return None
    if final_text.startswith(preview):
        return {"type": "text_delta", "text": final_text[len(preview):]}
    return {"type": "text_replace", "text": final_text}


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
    logger.debug(
        "hello.send client_id=%s device_id=%s session_id=%s display_name=%s",
        client_id,
        device_id,
        session_id,
        display_name,
    )
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
    logger.debug("hello.recv kind=%s %s", hello.get("type"), summarize_payload(hello))
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
    logger.debug(
        "turn.send turn_id=%s session_id=%s stt_source=%s %s",
        turn_id,
        session_id,
        stt_source,
        summarize_text(text),
    )
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
    streamed_reasoning = False
    audio_file_active = False

    frame_index = 0
    while True:
        frame = await ws.recv()
        frame_index += 1
        if isinstance(frame, bytes):
            kind = "audio_file_chunk" if audio_file_active else "audio_chunk"
            logger.debug(
                "frame.recv index=%d kind=%s turn_id=%s bytes=%d audio_file_active=%s",
                frame_index,
                kind,
                turn_id,
                len(frame),
                audio_file_active,
            )
            yield {"type": kind, "data": frame}
            continue

        try:
            payload = json.loads(frame)
        except (TypeError, ValueError, json.JSONDecodeError):
            logger.exception("frame.decode_failed index=%d size=%d", frame_index, len(frame))
            raise
        if not isinstance(payload, dict):
            # Same guard _receive_json has, but reported as an event rather
            # than raised: send_turn's contract is "failure arrives as an
            # error event that ends the generator".
            yield {"type": "error", "error": "server sent a non-object JSON frame"}
            return
        kind = payload.get("type")
        logger.debug(
            "frame.recv index=%d kind=%s turn_id=%s %s",
            frame_index,
            kind or "missing",
            payload.get("turn_id") or turn_id,
            summarize_payload(payload),
        )
        event_payload = payload.get("payload")
        if not isinstance(event_payload, dict):
            event_payload = payload

        if kind == "turn_accepted":
            continue
        elif kind in {"text_delta", "message.delta"}:
            preview_value = event_payload.get("text")
            has_rendered_preview = (
                kind == "message.delta" and event_payload.get("rendered") is not None
            )
            if has_rendered_preview:
                preview_value = event_payload.get("rendered")
            preview = str(preview_value or "")
            if kind == "message.delta" and not has_rendered_preview:
                # Gateway message.delta frames carry append-only chunks when
                # no cumulative rendered preview is supplied.
                delta = preview
                emitted_type = "text_delta"
                rendered_preview += preview
                mode = "raw_delta"
            elif preview.startswith(rendered_preview):
                delta = preview[len(rendered_preview):]
                emitted_type = "text_delta"
                rendered_preview = preview
                mode = "cumulative_suffix"
            elif event_payload.get("replace"):
                # Hermes can revise a cumulative preview (for example when a
                # late token changes formatting). Replace the active display
                # record instead of appending the complete preview again.
                delta = preview
                emitted_type = "text_replace"
                rendered_preview = preview
                mode = "cumulative_replace"
            else:
                delta = f"\n{preview}"
                emitted_type = "text_delta"
                rendered_preview = preview
                mode = "cumulative_rewind"
            streamed_text = True
            logger.debug(
                "normalize.text_delta source=%s mode=%s replace=%s preview=%s emitted=%s rendered_preview=%s",
                kind,
                mode,
                bool(event_payload.get("replace")),
                summarize_text(preview),
                summarize_text(delta),
                summarize_text(rendered_preview),
            )
            if delta:
                yield {"type": emitted_type, "text": delta}
        elif kind in {"text", "text_final"}:
            final_text = str(event_payload.get("text") or event_payload.get("rendered") or "")
            update = _final_text_update(final_text, rendered_preview, streamed_text)
            logger.debug(
                "normalize.text_final source=%s final=%s emitted=%s prior_preview=%s streamed=%s",
                kind,
                summarize_text(final_text),
                summarize_text(update.get("text") if update else None),
                summarize_text(rendered_preview),
                streamed_text,
            )
            if update:
                yield update
            if final_text:
                rendered_preview = final_text
                streamed_text = True
        elif kind == "message.start":
            yield {"type": "message_start"}
        elif kind == "message.complete":
            final_text = str(event_payload.get("text") or event_payload.get("rendered") or "")
            completion_reasoning = str(event_payload.get("reasoning") or "")
            if completion_reasoning and not streamed_reasoning:
                streamed_reasoning = True
                yield {"type": "thinking_delta", "text": completion_reasoning}
            update = _final_text_update(final_text, rendered_preview, streamed_text)
            logger.debug(
                "normalize.message_complete final=%s emitted=%s prior_preview=%s streamed=%s",
                summarize_text(final_text),
                summarize_text(update.get("text") if update else None),
                summarize_text(rendered_preview),
                streamed_text,
            )
            if update:
                yield update
            if final_text:
                rendered_preview = final_text
                streamed_text = True
            yield {
                "type": "message_complete",
                "text": final_text,
                "reasoning": str(event_payload.get("reasoning") or ""),
                "failure_reason": str(event_payload.get("failure_reason") or ""),
            }
        elif kind in {"thinking.delta", "reasoning.delta"}:
            thinking_text = str(event_payload.get("text") or "")
            if thinking_text:
                streamed_reasoning = True
                yield {"type": "thinking_delta", "text": thinking_text}
        elif kind == "reasoning.available":
            reasoning_text = str(event_payload.get("text") or "")
            if reasoning_text:
                streamed_reasoning = True
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
                "sample_rate": int(event_payload.get("sample_rate", 24000)),
                "channels": int(event_payload.get("channels", 1)),
                "sample_width": int(event_payload.get("sample_width", 2)),
            }
        elif kind == "audio_end":
            yield {"type": "audio_end"}
        elif kind == "audio_file_start":
            audio_file_active = True
            event = {"type": "audio_file_start"}
            for field in (
                "filename",
                "mime_type",
                "format",
                "sample_rate",
                "channels",
                "sample_width",
            ):
                if field in event_payload:
                    event[field] = event_payload[field]
            yield event
        elif kind == "audio_file_end":
            audio_file_active = False
            event = {"type": "audio_file_end"}
            data = _decode_audio_data(event_payload.get("data"))
            if data is not None:
                event["data"] = data
            yield event
        elif kind == "error":
            yield {
                "type": "error",
                "error": event_payload.get("error")
                or event_payload.get("message")
                or "voice-session error",
            }
            return
        elif kind == "turn_end":
            logger.debug(
                "turn.end turn_id=%s frame_index=%d streamed=%s preview=%s",
                turn_id,
                frame_index,
                streamed_text,
                summarize_text(rendered_preview),
            )
            yield {"type": "turn_end", "turn_id": turn_id}
            return
        else:
            yield {
                "type": "unknown_event",
                "event_type": str(kind or "missing"),
                "payload": payload,
            }
