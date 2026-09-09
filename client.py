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

from diagnostics import summarize_payload, summarize_text, trace_monotonic_ms
from timing import normalize_speech_timing


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


# What separates one segment of an answer from the next in the rendered
# transcript. The relay speaks the segments as one continuous reply, so they
# are joined rather than kept apart.
SEGMENT_BREAK = "\n\n"


def _joined(committed: str, preview: str) -> str:
    """The whole answer so far: finished segments plus the one in progress."""
    if not committed:
        return preview
    if not preview:
        return committed
    return committed + SEGMENT_BREAK + preview


def _final_text_update(
    final_text: str,
    rendered_preview: str,
    streamed_text: bool,
    committed: str = "",
) -> Optional[dict[str, str]]:
    """Return the append-or-replace update needed for a terminal text frame.

    `final_text` is terminal for the *current segment* only. A replacement
    therefore has to carry the finished segments back with it, or finalising
    segment three would delete segments one and two.
    """
    if not final_text:
        return None
    if not streamed_text:
        return {"type": "text_delta", "text": final_text}
    preview = rendered_preview.rstrip("▉")
    if final_text == preview:
        return None
    if final_text.startswith(preview):
        return {"type": "text_delta", "text": final_text[len(preview):]}
    return {"type": "text_replace", "text": _joined(committed, final_text)}


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


async def send_interrupt(ws: Any, *, session_id: str, turn_id: str) -> None:
    """Request cancellation of one active remote turn."""
    logger.debug("interrupt.send turn_id=%s session_id=%s", turn_id, session_id)
    await ws.send(
        json.dumps(
            {
                "type": "interrupt",
                "protocol_version": 1,
                "turn_id": turn_id,
                "session_id": session_id,
            }
        )
    )


async def send_prompt_response(
    ws: Any,
    *,
    session_id: str,
    prompt_id: str,
    prompt_kind: str,
    option_id: Optional[str] = None,
    value: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    """Answer one structured prompt without opening a second reader.

    The value is intentionally never included in the diagnostic line. This
    function is also used for masked sudo and secret responses, whose contents
    must remain between the websocket and the waiting gateway operation.
    """
    payload: dict[str, Any] = {
        "type": "prompt_response",
        "protocol_version": 1,
        "prompt_id": prompt_id,
        "prompt_kind": prompt_kind,
        "session_id": session_id,
    }
    if option_id is not None:
        payload["option_id"] = option_id
    if value is not None:
        payload["value"] = value
    if reason is not None:
        payload["reason"] = reason
    logger.debug(
        "prompt_response.send prompt_id=%s prompt_kind=%s option_id=%s "
        "value=%s reason=%s session_id=%s",
        prompt_id,
        prompt_kind,
        summarize_text(option_id),
        summarize_text(value),
        summarize_text(reason),
        session_id,
    )
    await ws.send(json.dumps(payload))


async def send_session_list(
    ws: Any,
    *,
    limit: int = 20,
    search: str = "",
) -> list[dict[str, Any]]:
    """Request available sessions from the relay."""
    payload: dict[str, Any] = {
        "type": "session_list",
        "protocol_version": 1,
        "limit": limit,
    }
    if search:
        payload["search"] = search
    logger.debug("session_list.send limit=%d search=%s", limit, summarize_text(search))
    await ws.send(json.dumps(payload))
    response = await _receive_json(ws)
    logger.debug(
        "session_list.recv kind=%s %s",
        response.get("type"),
        summarize_payload(response),
    )
    if response.get("type") != "session_list_result":
        raise ProtocolError(f"session_list failed: {response}")
    sessions = response.get("sessions")
    if isinstance(sessions, list):
        return [dict(item) for item in sessions if isinstance(item, dict)]
    return []


async def send_session_new(
    ws: Any,
    *,
    session_id: Optional[str] = None,
    title: Optional[str] = None,
) -> dict[str, Any]:
    """Request creation of a new session on the relay."""
    payload: dict[str, Any] = {
        "type": "session_new",
        "protocol_version": 1,
    }
    if session_id:
        payload["session_id"] = session_id
    if title:
        payload["title"] = title
    logger.debug(
        "session_new.send session_id=%s title=%s",
        summarize_text(session_id),
        summarize_text(title),
    )
    await ws.send(json.dumps(payload))
    response = await _receive_json(ws)
    logger.debug(
        "session_new.recv kind=%s %s",
        response.get("type"),
        summarize_payload(response),
    )
    if response.get("type") not in ("session_switched", "session_created", "session_new_ack"):
        raise ProtocolError(f"session_new failed: {response}")
    return response


async def send_session_switch(
    ws: Any,
    *,
    session_id: str,
) -> dict[str, Any]:
    """Request switching to and hydrating an existing session."""
    payload: dict[str, Any] = {
        "type": "session_switch",
        "protocol_version": 1,
        "session_id": session_id,
    }
    logger.debug("session_switch.send session_id=%s", session_id)
    await ws.send(json.dumps(payload))
    response = await _receive_json(ws)
    logger.debug(
        "session_switch.recv kind=%s %s",
        response.get("type"),
        summarize_payload(response),
    )
    if response.get("type") not in ("session_switched", "session_resumed"):
        raise ProtocolError(f"session_switch failed: {response}")
    return response


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
        "turn.send mono_ms=%d turn_id=%s session_id=%s stt_source=%s %s",
        trace_monotonic_ms(),
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
    # Hermes splits one answer into segments, each carrying its own draft_id
    # and its own terminal text frame. `committed` holds the segments already
    # finished; `rendered_preview` is only ever the segment in progress.
    # Measured live 2026-09-02: a single turn arrived as 338 + 83 + 268
    # characters, and treating each boundary as a revision left 309 of them.
    committed = ""
    current_draft: Any = None
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
        advertised_session_ids = {
            str(candidate)
            for candidate in (
                event_payload.get("session_id"),
                payload.get("session_id") if event_payload is not payload else None,
            )
            if candidate not in (None, "")
        }
        if any(candidate != str(session_id) for candidate in advertised_session_ids):
            logger.debug(
                "frame.stale index=%d kind=%s expected_session_id=%s frame_session_ids=%s",
                frame_index,
                kind or "missing",
                session_id,
                ",".join(sorted(advertised_session_ids)),
            )
            continue
        frame_turn_id = event_payload.get("turn_id")
        if frame_turn_id is None and event_payload is not payload:
            frame_turn_id = payload.get("turn_id")
        if frame_turn_id not in (None, "") and str(frame_turn_id) != turn_id:
            logger.debug(
                "frame.stale index=%d kind=%s expected_turn_id=%s frame_turn_id=%s",
                frame_index,
                kind or "missing",
                turn_id,
                frame_turn_id,
            )
            continue

        if kind == "turn_accepted":
            continue
        elif kind == "prompt_request":
            options = event_payload.get("options")
            if not isinstance(options, list):
                options = []
            normalized_options = [
                dict(option) for option in options if isinstance(option, dict)
            ]
            prompt_turn_id = event_payload.get("turn_id")
            if prompt_turn_id is None:
                prompt_turn_id = turn_id
            try:
                timeout_s = int(event_payload.get("timeout_s", 300))
            except (TypeError, ValueError):
                timeout_s = 300
            yield {
                "type": "prompt_request",
                "prompt_id": str(event_payload.get("prompt_id") or ""),
                "prompt_kind": str(event_payload.get("prompt_kind") or ""),
                "turn_id": str(prompt_turn_id),
                "session_id": str(
                    event_payload.get("session_id")
                    or payload.get("session_id")
                    or session_id
                ),
                "text": str(event_payload.get("text") or ""),
                "options": normalized_options,
                "sensitive": bool(event_payload.get("sensitive", False)),
                "timeout_s": timeout_s,
            }
        elif kind == "prompt_resolved":
            yield {
                "type": "prompt_resolved",
                "prompt_id": str(event_payload.get("prompt_id") or ""),
                "prompt_kind": str(event_payload.get("prompt_kind") or ""),
                "status": str(event_payload.get("status") or ""),
                "session_id": str(
                    event_payload.get("session_id")
                    or payload.get("session_id")
                    or session_id
                ),
            }
        elif kind == "prompt_response_rejected":
            yield {
                "type": "prompt_response_rejected",
                "prompt_id": str(event_payload.get("prompt_id") or ""),
                "reason": str(event_payload.get("reason") or ""),
                "session_id": str(
                    event_payload.get("session_id")
                    or payload.get("session_id")
                    or session_id
                ),
            }
        elif kind in {"text_delta", "message.delta"}:
            draft_id = event_payload.get("draft_id")
            if (
                draft_id is not None
                and current_draft is not None
                and draft_id != current_draft
            ):
                # A new segment, stated by the server rather than guessed at.
                # Bank the finished one before anything can overwrite it.
                committed = _joined(committed, rendered_preview)
                rendered_preview = ""
            if draft_id is not None:
                current_draft = draft_id
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
                # Opening a fresh segment: the break belongs in front of it, or
                # the last word of one segment runs into the first of the next.
                if committed and not rendered_preview:
                    delta = SEGMENT_BREAK + delta
                emitted_type = "text_delta"
                rendered_preview = preview
                mode = "segment_open" if committed and not rendered_preview else "cumulative_suffix"
            elif event_payload.get("replace"):
                # A genuine revision *within* the current segment — Hermes
                # rewriting a preview when a late token changes formatting.
                # The replacement carries the finished segments with it, so
                # revising segment three cannot erase segments one and two.
                rendered_preview = preview
                delta = _joined(committed, preview)
                emitted_type = "text_replace"
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
            update = _final_text_update(
                final_text, rendered_preview, streamed_text, committed
            )
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
            update = _final_text_update(
                final_text, rendered_preview, streamed_text, committed
            )
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
        elif kind == "audio_abort":
            yield {
                "type": "audio_abort",
                "turn_id": str(event_payload.get("turn_id") or turn_id),
                "session_id": str(event_payload.get("session_id") or session_id),
                "error": str(
                    event_payload.get("error")
                    or event_payload.get("reason")
                    or "audio stream aborted"
                ),
            }
        elif kind == "turn_interrupted":
            yield {
                "type": "turn_interrupted",
                "turn_id": str(event_payload.get("turn_id") or turn_id),
                "session_id": str(event_payload.get("session_id") or session_id),
                "reason": str(
                    event_payload.get("reason")
                    or event_payload.get("error")
                    or event_payload.get("message")
                    or "turn interrupted"
                ),
            }
            return
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
        elif kind == "speech_timing":
            raw_words = event_payload.get("words")
            word_count = len(raw_words) if isinstance(raw_words, list) else -1
            logger.debug(
                "speech_timing.recv mono_ms=%d turn_id=%s segment_id=%s "
                "segment_index=%s audio_offset_ms=%s duration_ms=%s source=%s "
                "words=%d fallback=%s",
                trace_monotonic_ms(),
                turn_id,
                summarize_text(event_payload.get("segment_id")),
                event_payload.get("segment_index", "missing"),
                event_payload.get("audio_offset_ms", "missing"),
                event_payload.get("duration_ms", "missing"),
                event_payload.get("timing_source", "missing"),
                word_count,
                event_payload.get("fallback_reason", "missing"),
            )
            timing = normalize_speech_timing(event_payload)
            if timing is not None:
                logger.debug(
                    "speech_timing.normalized mono_ms=%d turn_id=%s segment_id=%s "
                    "offset_ms=%d duration_ms=%d source=%s words=%d fallback=%s",
                    trace_monotonic_ms(),
                    turn_id,
                    summarize_text(timing.segment_id),
                    round(timing.audio_offset * 1000),
                    round(timing.duration * 1000),
                    timing.timing_source,
                    len(timing.words),
                    timing.fallback_reason or "none",
                )
                yield timing.as_event()
            else:
                logger.debug("speech_timing ignored without safe geometry turn_id=%s", turn_id)
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
