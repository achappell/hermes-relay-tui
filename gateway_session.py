"""SessionProtocol adapter for Hermes' standard gateway WebSocket."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from typing import Any, AsyncIterator

import config
from client import SEGMENT_BREAK, _final_text_update, _joined
from diagnostics import logger as diagnostic_logger, summarize_text
from gateway_client import (
    GatewayClient,
    GatewayProtocolError,
    GatewayRPCError,
    GatewayTransportError,
    GatewayUnsupportedError,
)
from gateway_audio import (
    AUDIO_DRAIN_TIMEOUT,
    GatewayAudioStream,
    GatewayAudioTransportError,
)
from session import HermesSession, SessionNotReadyError


_UNSUPPORTED_PROMPT_EVENTS = frozenset(
    {
        "approval.request",
        "clarify.request",
        "prompt.request",
        "secret.request",
        "sudo.request",
    }
)
_CANCELLATION_STATUSES = frozenset(
    {"cancelled", "canceled", "interrupted", "aborted", "stopped"}
)
_FAILED_STATUSES = frozenset(
    {"failed", "error", "timeout", "timed_out", "timed-out"}
)
_TERMINAL_STATUSES = _CANCELLATION_STATUSES | _FAILED_STATUSES | frozenset(
    {"complete", "completed"}
)
_NONTERMINAL_STATUSES = frozenset(
    {"accepted", "pending", "queued", "running", "streaming", "started", "in_progress", "in-progress"}
)
_ACCEPTED_REQUEST_STATUSES = frozenset(
    {"accepted", "queued", "streaming", "submitted", "interrupted", "cancelled", "canceled"}
)


class GatewaySession(HermesSession):
    """Drive the existing TUI session contract over the standard gateway."""

    def __init__(self, args: Any) -> None:
        super().__init__(args)
        self._gateway: GatewayClient | None = None
        self._durable_session_id: str | None = None
        self._session_key: str | None = None
        self._gateway_ready = False
        self._gateway_token: str | None = None
        self._active_audio: GatewayAudioStream | None = None
        self._last_event_seq = 0
        self._submission_started_for_turn: str | None = None
        self._cancel_before_submission_for_turn: str | None = None

    @property
    def session_id(self) -> str:
        """Return the runtime ID Hermes assigned to the live doorway."""

        return self._session_id

    @property
    def supports_interrupt(self) -> bool:
        """The standard gateway exposes session.interrupt in this slice."""

        return self.is_connected()

    @property
    def supports_structured_prompts(self) -> bool:
        """Prompt parity is deliberately deferred for the first gateway slice."""

        return False

    async def connect(self) -> dict[str, Any]:
        """Wait for gateway readiness, then create or resume one session."""

        if self._gateway is not None or self.ws is not None:
            await self.close()
        token = self._resolve_token()
        if not token:
            raise RuntimeError(
                "No gateway token found. Set VOICE_SESSION_TOKEN or configure the profile .env."
            )

        gateway = GatewayClient(self.args.url, token)
        self._gateway = gateway
        self._gateway_token = token
        try:
            ready = await gateway.connect()
            self._last_event_seq = 0
            requested_resume = self._requested_resume_id()
            if requested_resume:
                result = await gateway.request(
                    "session.resume",
                    {
                        "session_id": requested_resume,
                        **self._session_context(),
                    },
                )
                operation = "resume"
            else:
                result = await gateway.request(
                    "session.create",
                    self._session_context(),
                )
                operation = "create"
            normalized = self._apply_session_result(result)
            self._hello_verified = True
            self._gateway_ready = True
            diagnostic_logger.debug(
                "gateway.session.%s runtime_id=%s durable_id=%s history=%d",
                operation,
                self._session_id,
                self._durable_session_id or "-",
                len(self.initial_history),
            )
            return {
                "type": "gateway_ready",
                "gateway": ready,
                **normalized,
            }
        except BaseException:
            diagnostic_logger.error("gateway.session.connect.failed")
            await self.close()
            raise

    def is_connected(self) -> bool:
        """Only report ready after both gateway and session handshakes pass."""

        return bool(
            self._gateway is not None
            and self._gateway_ready
            and self._hello_verified
            and self._gateway.is_connected
        )

    async def wait_for_disconnect(self) -> None:
        if not self.is_connected() or self._gateway is None:
            raise SessionNotReadyError("Not connected to gateway")
        await self._gateway.wait_for_disconnect()

    async def close(self) -> None:
        """Close the gateway while preserving the inherited microphone rules."""

        self._hello_verified = False
        self._gateway_ready = False
        self.cancel_voice()
        audio = self._active_audio
        self._active_audio = None
        microphone = self.microphone
        self.microphone = None
        gateway = self._gateway
        self._gateway = None
        try:
            if audio is not None:
                await audio.close()
            if microphone is not None and self._shared_recorder is None:
                await asyncio.to_thread(microphone.close)
            if gateway is not None:
                await gateway.close()
        finally:
            self.ws = None
            self._capabilities = frozenset()
            self._last_event_seq = 0
            self.confirmed_chat_id = None
            self.confirmed_server_version = None
            self.confirmed_context_limit = None
            self.active_turn_id = None
            self._interrupt_sent_for_turn = None
            self._submission_started_for_turn = None
            self._cancel_before_submission_for_turn = None
            self._gateway_token = None

    def send_turn(self, text: str, *, stt_source: str = "local") -> AsyncIterator[dict[str, Any]]:
        """Submit one text turn and normalize its session-scoped events."""

        if not self.is_connected() or self._gateway is None:
            raise SessionNotReadyError("Not connected to gateway")
        self.turn_index += 1
        turn_id = uuid.uuid4().hex
        self.active_turn_id = turn_id
        self._interrupt_sent_for_turn = None
        self._submission_started_for_turn = None
        self._cancel_before_submission_for_turn = None
        runtime_session_id = self._session_id
        gateway = self._gateway
        diagnostic_logger.debug(
            "gateway.turn.start index=%d stt_source=%s session_id=%s %s",
            self.turn_index,
            stt_source,
            runtime_session_id,
            summarize_text(text),
        )

        async def stream() -> AsyncIterator[dict[str, Any]]:
            state: dict[str, Any] = {
                "rendered_preview": "",
                "streamed_text": False,
                "committed": "",
                "current_draft": None,
                "streamed_reasoning": False,
            }
            audio = self._new_audio_stream() if self._gateway_audio_enabled else None
            self._active_audio = audio
            audio_task: asyncio.Task[dict[str, Any]] | None = None
            gateway_task: asyncio.Task[dict[str, Any]] | None = None
            audio_done = audio is None
            audio_failure: str | None = None
            pending_terminal: dict[str, Any] | None = None
            audio_text_sent = ""
            drain_deadline: float | None = None

            async def audio_unavailable(reason: str) -> AsyncIterator[dict[str, Any]]:
                yield {
                    "type": "audio_unavailable",
                    "reason": reason,
                    "turn_id": turn_id,
                    "session_id": runtime_session_id,
                }

            async def feed_audio_text(event: dict[str, Any]) -> str | None:
                """Send only new text; replacements cannot retract spoken words."""

                nonlocal audio_text_sent
                if audio is None or audio_done:
                    return None
                kind = event.get("type")
                text_fragment = str(event.get("text") or "")
                if not text_fragment:
                    return None
                if kind == "text_replace":
                    if text_fragment.startswith(audio_text_sent):
                        text_fragment = text_fragment[len(audio_text_sent):]
                    else:
                        diagnostic_logger.debug(
                            "gateway.audio.text_replace_skipped turn_id=%s",
                            turn_id,
                        )
                        return None
                if not text_fragment:
                    return None
                try:
                    await audio.send_text(text_fragment)
                except Exception as exc:
                    return f"audio sidecar send failed ({type(exc).__name__})"
                audio_text_sent += text_fragment
                return None

            async def finish_terminal() -> AsyncIterator[dict[str, Any]]:
                """Release the held terminal event after audio is settled."""

                nonlocal pending_terminal
                if pending_terminal is not None:
                    terminal = pending_terminal
                    pending_terminal = None
                    yield terminal

            def refresh_audio_drain_deadline() -> None:
                """Keep a healthy PCM stream alive; bound only a silent stall."""

                nonlocal drain_deadline
                if pending_terminal is not None:
                    drain_deadline = (
                        asyncio.get_running_loop().time() + AUDIO_DRAIN_TIMEOUT
                    )

            async def abandon_audio(*, stop: bool = False) -> None:
                """Invalidate the sidecar reader and discard late PCM."""

                nonlocal audio_done, audio_task
                audio_done = True
                if audio_task is not None and not audio_task.done():
                    audio_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await audio_task
                audio_task = None
                if audio is not None:
                    if stop:
                        await audio.stop()
                    else:
                        await audio.close()

            try:
                if self._cancel_before_submission_for_turn == turn_id:
                    yield {
                        "type": "turn_interrupted",
                        "turn_id": turn_id,
                        "session_id": runtime_session_id,
                        "reason": "cancelled_before_submission",
                    }
                    return
                if audio is not None:
                    try:
                        await audio.open()
                    except Exception as exc:
                        audio_failure = f"audio sidecar unavailable ({type(exc).__name__})"
                        audio_done = True
                self._submission_started_for_turn = turn_id
                submission = await gateway.request(
                    "prompt.submit",
                    {
                        "session_id": runtime_session_id,
                        "text": text,
                        "surface": "tui",
                    },
                )
                _require_accepted_request(submission, "prompt.submit")
                if audio_failure is not None:
                    async for unavailable in audio_unavailable(audio_failure):
                        yield unavailable
                if audio is not None and not audio_done:
                    audio_task = asyncio.create_task(audio.next_event())
                gateway_task = asyncio.create_task(gateway.next_event())
                while True:
                    if gateway_task is None and audio_task is None:
                        break
                    tasks = {
                        task
                        for task in (gateway_task, audio_task)
                        if task is not None
                    }
                    timeout = None
                    if pending_terminal is not None and audio_task is not None:
                        if drain_deadline is None:
                            drain_deadline = asyncio.get_running_loop().time() + AUDIO_DRAIN_TIMEOUT
                        timeout = max(
                            0.0,
                            drain_deadline - asyncio.get_running_loop().time(),
                        )
                    done, _pending = await asyncio.wait(
                        tasks,
                        timeout=timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        if pending_terminal is not None:
                            audio_done = True
                            if audio_task is not None and not audio_task.done():
                                audio_task.cancel()
                                with contextlib.suppress(asyncio.CancelledError):
                                    await audio_task
                            audio_task = None
                            async for unavailable in audio_unavailable("audio drain timed out"):
                                yield unavailable
                            async for terminal in finish_terminal():
                                yield terminal
                            return
                        continue

                    if gateway_task is not None and gateway_task in done:
                        gateway_task = None
                        event = done.pop().result() if len(done) == 1 else None
                        # When both lanes finish in one loop turn, retain the
                        # gateway event explicitly instead of relying on set
                        # ordering below.
                        if event is None:
                            for completed in tuple(done):
                                if completed is not audio_task:
                                    event = completed.result()
                                    done.remove(completed)
                                    break
                        terminal_seen = False
                        if event is not None and self._belongs_to_session(
                            event, runtime_session_id
                        ):
                            sequence = event.get("seq")
                            if isinstance(sequence, int):
                                if sequence <= self._last_event_seq:
                                    diagnostic_logger.debug(
                                        "gateway.event.stale_ignored seq=%d last_seq=%d",
                                        sequence,
                                        self._last_event_seq,
                                    )
                                    event = None
                                else:
                                    self._last_event_seq = sequence
                        if event is not None and self._belongs_to_session(
                            event, runtime_session_id
                        ):
                            async for normalized in self._normalize_event(
                                event,
                                turn_id=turn_id,
                                state=state,
                                gateway=gateway,
                                session_id=runtime_session_id,
                            ):
                                if normalized["type"] in {"text_delta", "text_replace"}:
                                    failure = await feed_audio_text(normalized)
                                    if failure is not None:
                                        await abandon_audio()
                                        async for unavailable in audio_unavailable(failure):
                                            yield unavailable
                                if normalized["type"] == "turn_end":
                                    pending_terminal = normalized
                                    terminal_seen = True
                                    if audio is None or audio_done:
                                        async for terminal in finish_terminal():
                                            yield terminal
                                        return
                                    try:
                                        await audio.finish()
                                    except Exception as exc:
                                        await abandon_audio()
                                        async for unavailable in audio_unavailable(
                                            f"audio finish failed ({type(exc).__name__})"
                                        ):
                                            yield unavailable
                                        async for terminal in finish_terminal():
                                            yield terminal
                                        return
                                    drain_deadline = (
                                        asyncio.get_running_loop().time()
                                        + AUDIO_DRAIN_TIMEOUT
                                    )
                                    continue
                                if normalized["type"] in {"turn_interrupted", "error"}:
                                    if audio is not None and not audio_done:
                                        await abandon_audio(stop=True)
                                    yield normalized
                                    return
                                yield normalized
                        if not terminal_seen and gateway_task is None:
                            gateway_task = asyncio.create_task(gateway.next_event())

                    if audio_task is not None and audio_task in done:
                        audio_task = None
                        try:
                            audio_event = next(
                                completed.result()
                                for completed in done
                                if completed is not gateway_task
                            )
                        except StopIteration:
                            audio_event = None
                        except GatewayAudioTransportError:
                            audio_event = {
                                "type": "audio_unavailable",
                                "reason": "audio sidecar disconnected",
                            }
                        if audio_event is not None:
                            kind = audio_event.get("type")
                            audio_event.update(
                                {"turn_id": turn_id, "session_id": runtime_session_id}
                            )
                            if kind == "audio_unavailable":
                                audio_done = True
                                yield audio_event
                                if pending_terminal is not None:
                                    async for terminal in finish_terminal():
                                        yield terminal
                                    return
                            else:
                                if kind == "audio_end":
                                    audio_done = True
                                else:
                                    refresh_audio_drain_deadline()
                                yield audio_event
                                if audio_done and pending_terminal is not None:
                                    async for terminal in finish_terminal():
                                        yield terminal
                                    return
                            if not audio_done:
                                audio_task = asyncio.create_task(audio.next_event())
            finally:
                for task in (gateway_task, audio_task):
                    if task is not None and not task.done():
                        task.cancel()
                for task in (gateway_task, audio_task):
                    if task is not None:
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
                if audio is not None:
                    await audio.close()
                if self._active_audio is audio:
                    self._active_audio = None
                if self.active_turn_id == turn_id:
                    self.active_turn_id = None
                self._interrupt_sent_for_turn = None
                if self._submission_started_for_turn == turn_id:
                    self._submission_started_for_turn = None
                if self._cancel_before_submission_for_turn == turn_id:
                    self._cancel_before_submission_for_turn = None

        return stream()

    async def interrupt_active_turn(self) -> bool:
        """Request interruption; the turn stream still owns confirmation."""

        turn_id = self.active_turn_id
        if not self.is_connected() or self._gateway is None or not turn_id:
            return False
        if self._interrupt_sent_for_turn == turn_id:
            return True
        audio = self._active_audio
        if self._submission_started_for_turn != turn_id:
            self._cancel_before_submission_for_turn = turn_id
            if audio is not None:
                await audio.stop()
            self._interrupt_sent_for_turn = turn_id
            diagnostic_logger.debug(
                "gateway.turn.interrupt_before_submission turn_id=%s", turn_id
            )
            return True
        try:
            result = await self._gateway.request(
                "session.interrupt",
                {"session_id": self._session_id},
            )
        except BaseException:
            if audio is not None:
                await audio.stop()
            raise
        status = str(result.get("status") or "").lower() if isinstance(result, dict) else ""
        if status.lower() in _FAILED_STATUSES or status.lower() in {
            "rejected",
            "refused",
        }:
            return False
        _require_accepted_request(result, "session.interrupt")
        if audio is not None:
            await audio.stop()
        self._interrupt_sent_for_turn = turn_id
        diagnostic_logger.debug(
            "gateway.turn.interrupt_requested session_id=%s turn_id=%s",
            self._session_id,
            turn_id,
        )
        return True

    @property
    def _gateway_audio_enabled(self) -> bool:
        configured = getattr(self.args, "gateway_audio_enabled", None)
        if configured is not None:
            return bool(configured)
        return getattr(self.args, "transport", "voice-session") == "gateway"

    def _new_audio_stream(self) -> GatewayAudioStream:
        token = self._gateway_token or self._resolve_token()
        return GatewayAudioStream(
            self.args.url,
            token,
            profile=getattr(self.args, "hermes_profile", None),
        )

    async def send_prompt_response(
        self,
        *,
        prompt_id: str,
        prompt_kind: str,
        option_id: str | None = None,
        value: str | None = None,
        reason: str | None = None,
        operation: str | None = None,
        object_id: str | None = None,
        freshness: str | None = None,
    ) -> bool:
        """Reject prompt responses until standard prompt parity is designed."""

        # Deliberately do not retain or log any supplied value.  The gateway
        # turn is interrupted when its request event is observed instead.
        return False

    async def list_sessions(
        self, *, limit: int = 20, search: str = ""
    ) -> list[dict[str, Any]]:
        if not self.is_connected() or self._gateway is None:
            raise SessionNotReadyError("Not connected to gateway")
        result = await self._gateway.request(
            "session.list",
            {"limit": max(1, min(int(limit), 200)), "include_hidden": False},
        )
        rows = result.get("sessions") if isinstance(result, dict) else result
        if not isinstance(rows, list):
            return []
        normalized: list[dict[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            sid = row.get("resolved_id") or row.get("session_id") or row.get("id")
            if sid not in (None, ""):
                row["session_id"] = str(sid)
            normalized.append(row)
        return normalized

    async def new_session(
        self, *, session_id: str | None = None, title: str | None = None
    ) -> dict[str, Any]:
        if not self.is_connected() or self._gateway is None:
            raise SessionNotReadyError("Not connected to gateway")
        # The existing app passes `/session new ARG` through session_id.  In
        # gateway mode that argument is a title, never a client-owned ID.
        session_title = title or (session_id.strip() if session_id else None)
        result = await self._gateway.request(
            "session.create",
            self._session_context(title=session_title),
        )
        return self._apply_session_result(result)

    async def switch_session(self, session_id: str) -> dict[str, Any]:
        if not self.is_connected() or self._gateway is None:
            raise SessionNotReadyError("Not connected to gateway")
        result = await self._gateway.request(
            "session.resume",
            {"session_id": session_id, **self._session_context()},
        )
        return self._apply_session_result(result)

    def _resolve_token(self) -> str:
        profile_token_env = getattr(self.args, "profile_token_env", None)
        profile_env = getattr(self.args, "profile_env", None) or config.DEFAULT_PROFILE_ENV
        if profile_token_env and not getattr(self.args, "token", None):
            return config.resolve_profile_token_source(profile_env, profile_token_env)
        return config._resolve_token(
            getattr(self.args, "token", None), profile_env
        )

    def _requested_resume_id(self) -> str | None:
        explicit = getattr(self.args, "gateway_resume_session_id", None)
        if explicit:
            return str(explicit).strip() or None
        if getattr(self.args, "session_id_explicit", False):
            value = getattr(self.args, "session_id", None)
            return str(value).strip() if value else None
        return None

    def _session_context(self, *, title: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"source": "tui"}
        profile = str(getattr(self.args, "hermes_profile", "") or "").strip()
        if profile:
            params["profile"] = profile
        if title:
            params["title"] = title
        return params

    def _apply_session_result(self, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise GatewayProtocolError("gateway session response is not an object")
        runtime_candidates = [
            result[key]
            for key in ("session_id", "runtime_session_id")
            if result.get(key) not in (None, "")
        ]
        if any(not isinstance(value, str) or not value.strip() for value in runtime_candidates):
            raise GatewayProtocolError("gateway session response has an invalid runtime ID")
        if len({value.strip() for value in runtime_candidates}) > 1:
            raise GatewayProtocolError(
                "gateway session response has conflicting runtime IDs"
            )
        runtime_id = runtime_candidates[0] if runtime_candidates else None
        if not isinstance(runtime_id, str) or not runtime_id.strip():
            raise GatewayProtocolError("gateway session response has no runtime ID")
        self._session_id = runtime_id.strip()
        durable_id = result.get("stored_session_id") or result.get("session_key")
        if durable_id is not None and (
            not isinstance(durable_id, str) or not durable_id.strip()
        ):
            raise GatewayProtocolError("gateway session response has an invalid durable ID")
        self._durable_session_id = durable_id.strip() if durable_id else None
        session_key = result.get("session_key")
        if session_key is not None and (
            not isinstance(session_key, str) or not session_key.strip()
        ):
            raise GatewayProtocolError("gateway session response has an invalid session key")
        self._session_key = session_key.strip() if session_key else None
        if self._durable_session_id:
            # App recovery creates a new adapter from copied args. Preserve
            # the durable key there; the runtime ID below is only for this
            # live socket and is not a valid resume key.
            self.args.gateway_resume_session_id = self._durable_session_id
        info = result.get("info") if isinstance(result.get("info"), dict) else {}
        self.confirmed_model = _optional_str(
            result.get("model") or info.get("model") or info.get("model_name")
        )
        self.confirmed_title = _optional_str(
            result.get("title") or info.get("title")
        )
        self.confirmed_chat_id = _optional_str(result.get("chat_id"))
        self.confirmed_server_version = _optional_str(
            result.get("server_version") or result.get("version") or info.get("version")
        )
        raw_limit = result.get("context_limit") or info.get("context_limit")
        try:
            self.confirmed_context_limit = int(raw_limit) if raw_limit is not None else None
        except (TypeError, ValueError):
            self.confirmed_context_limit = None
        raw_messages = result.get("messages")
        self.initial_history = [
            dict(message) for message in raw_messages
            if isinstance(message, dict)
        ] if isinstance(raw_messages, list) else []
        self._capabilities = frozenset({"interrupt"})
        self.turn_index = 0
        normalized = dict(result)
        normalized["session_id"] = self._session_id
        normalized["history"] = list(self.initial_history)
        return normalized

    @staticmethod
    def _belongs_to_session(event: dict[str, Any], session_id: str) -> bool:
        advertised = event.get("session_id")
        payload = event.get("payload")
        if advertised in (None, "") and isinstance(payload, dict):
            advertised = payload.get("session_id")
        return advertised not in (None, "") and str(advertised) == str(session_id)

    async def _normalize_event(
        self,
        event: dict[str, Any],
        *,
        turn_id: str,
        state: dict[str, Any],
        gateway: GatewayClient,
        session_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        event_type = str(event.get("type") or "")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        if event_type in _UNSUPPORTED_PROMPT_EVENTS:
            await self._cancel_unsupported_prompt(
                gateway, session_id=session_id, event_type=event_type
            )
            raise GatewayUnsupportedError(
                f"gateway {event_type} is not supported by this TUI slice"
            )
        if event_type == "message.start":
            yield {"type": "message_start", "turn_id": turn_id, "session_id": session_id}
            return
        if event_type in {"message.delta", "text_delta"}:
            update = self._normalize_text_delta(payload, event_type, state)
            if update:
                update.update({"turn_id": turn_id, "session_id": session_id})
                yield update
            return
        if event_type == "message.interim":
            interim = str(payload.get("text") or "")
            if payload.get("already_streamed"):
                # The gateway is sealing text that deltas already showed.
                # Bank it so the final answer becomes a new inline segment.
                if state["rendered_preview"]:
                    state["committed"] = _joined(
                        state["committed"], state["rendered_preview"]
                    )
                    state["rendered_preview"] = ""
                    state["current_draft"] = None
                return
            if interim:
                # An interim event carries a complete mid-turn assistant
                # message when it was not already streamed as deltas. Keep it
                # as a committed segment instead of letting message.complete
                # replace it with only the final answer.
                if state["rendered_preview"]:
                    state["committed"] = _joined(
                        state["committed"], state["rendered_preview"]
                    )
                    state["rendered_preview"] = ""
                prefix = SEGMENT_BREAK if state["committed"] else ""
                state["committed"] = _joined(state["committed"], interim)
                state["streamed_text"] = True
                state["current_draft"] = None
                yield {
                    "type": "text_delta",
                    "text": prefix + interim,
                    "turn_id": turn_id,
                    "session_id": session_id,
                }
            return
        if event_type in {"thinking.delta", "reasoning.delta"}:
            text = str(payload.get("text") or "")
            if text:
                state["streamed_reasoning"] = True
                yield {
                    "type": "thinking_delta",
                    "text": text,
                    "turn_id": turn_id,
                    "session_id": session_id,
                }
            return
        if event_type == "error":
            raw_error = payload.get("message") or payload.get("error")
            if isinstance(raw_error, dict):
                raw_error = raw_error.get("message") or raw_error.get("detail")
            error_text = str(raw_error or "gateway turn failed")
            yield {
                "type": "error",
                "error": error_text,
                "turn_id": turn_id,
                "session_id": session_id,
            }
            return
        if event_type == "reasoning.available":
            text = str(payload.get("text") or "")
            if text:
                yield {
                    "type": "thinking_delta",
                    "text": text,
                    "turn_id": turn_id,
                    "session_id": session_id,
                }
            else:
                yield {
                    "type": "reasoning_available",
                    "turn_id": turn_id,
                    "session_id": session_id,
                }
            return
        if event_type in {"status.update", "status"}:
            text = str(payload.get("text") or payload.get("status") or "").strip()
            if text:
                yield {
                    "type": "status",
                    "text": text,
                    "kind": str(payload.get("kind") or "status"),
                    "turn_id": turn_id,
                    "session_id": session_id,
                }
            return
        if event_type == "tool.start":
            yield {
                "type": "tool_start",
                "tool_id": str(payload.get("tool_id") or ""),
                "name": str(payload.get("name") or "tool"),
                "context": str(payload.get("context") or ""),
                "turn_id": turn_id,
                "session_id": session_id,
            }
            return
        if event_type in {"tool.progress", "tool.generating"}:
            yield {
                "type": "tool_progress",
                "tool_id": str(payload.get("tool_id") or ""),
                "name": str(payload.get("name") or "tool"),
                "preview": str(payload.get("preview") or "drafting…"),
                "turn_id": turn_id,
                "session_id": session_id,
            }
            return
        if event_type == "tool.complete":
            yield {
                "type": "tool_complete",
                "tool_id": str(payload.get("tool_id") or ""),
                "name": str(payload.get("name") or "tool"),
                "summary": str(payload.get("summary") or ""),
                "error": str(payload.get("error") or ""),
                "turn_id": turn_id,
                "session_id": session_id,
            }
            return
        if event_type == "background.complete":
            yield {
                "type": "background_complete",
                "task_id": str(payload.get("task_id") or ""),
                "text": str(payload.get("text") or ""),
                "turn_id": turn_id,
                "session_id": session_id,
            }
            return
        if event_type == "message.complete":
            final_text = str(payload.get("text") or payload.get("rendered") or "")
            if payload.get("reasoning") and not state["streamed_reasoning"]:
                yield {
                    "type": "thinking_delta",
                    "text": str(payload.get("reasoning")),
                    "turn_id": turn_id,
                    "session_id": session_id,
                }
            update = _final_text_update(
                final_text,
                state["rendered_preview"],
                state["streamed_text"],
                state["committed"],
            )
            if (
                update
                and update["type"] == "text_delta"
                and state["committed"]
                and not state["rendered_preview"]
            ):
                update["text"] = SEGMENT_BREAK + update["text"]
            if update:
                update.update({"turn_id": turn_id, "session_id": session_id})
                yield update
            full_text = _joined(
                state["committed"], final_text or state["rendered_preview"]
            )
            status = str(payload.get("status") or "complete").lower()
            if status in _CANCELLATION_STATUSES:
                yield {
                    "type": "turn_interrupted",
                    "turn_id": turn_id,
                    "session_id": session_id,
                    "reason": status,
                }
                return
            if status in _FAILED_STATUSES:
                yield {
                    "type": "error",
                    "error": "gateway turn failed",
                    "turn_id": turn_id,
                    "session_id": session_id,
                }
                return
            if status in _NONTERMINAL_STATUSES:
                yield {
                    "type": "status",
                    "text": status,
                    "turn_id": turn_id,
                    "session_id": session_id,
                }
                return
            if status not in _TERMINAL_STATUSES:
                raise GatewayProtocolError(
                    f"gateway message.complete has unknown status: {status}"
                )
            yield {
                "type": "turn_end",
                "turn_id": turn_id,
                "session_id": session_id,
                "text": full_text,
            }
            return
        if event_type in {"notification.show", "notification.clear"}:
            if event_type == "notification.show":
                yield {
                    "type": "notification",
                    "text": str(payload.get("text") or ""),
                    "level": str(payload.get("level") or "info"),
                    "key": str(payload.get("key") or ""),
                    "turn_id": turn_id,
                    "session_id": session_id,
                }
            else:
                yield {
                    "type": "notification_clear",
                    "key": str(payload.get("key") or ""),
                    "turn_id": turn_id,
                    "session_id": session_id,
                }
            return
        # Keep unknown events explicit but content-safe.  The app can show the
        # event name without accidentally placing a full gateway payload in a
        # diagnostic line or transcript.
        yield {
            "type": "unknown_event",
            "event_type": event_type or "missing",
            "payload_keys": sorted(str(key) for key in payload),
            "turn_id": turn_id,
            "session_id": session_id,
        }

    @staticmethod
    def _normalize_text_delta(
        payload: dict[str, Any], event_type: str, state: dict[str, Any]
    ) -> dict[str, str] | None:
        draft_id = payload.get("draft_id")
        if (
            draft_id is not None
            and state["current_draft"] is not None
            and draft_id != state["current_draft"]
        ):
            state["committed"] = _joined(
                state["committed"], state["rendered_preview"]
            )
            state["rendered_preview"] = ""
        if draft_id is not None:
            state["current_draft"] = draft_id

        has_rendered = event_type == "message.delta" and payload.get("rendered") is not None
        preview = str(
            payload.get("rendered") if has_rendered else payload.get("text") or ""
        )
        if event_type == "message.delta" and not has_rendered:
            delta = preview
            state["rendered_preview"] += preview
            emitted_type = "text_delta"
        elif preview.startswith(state["rendered_preview"]):
            delta = preview[len(state["rendered_preview"]):]
            if state["committed"] and not state["rendered_preview"] and delta:
                delta = SEGMENT_BREAK + delta
            state["rendered_preview"] = preview
            emitted_type = "text_delta"
        elif payload.get("replace"):
            state["rendered_preview"] = preview
            delta = _joined(state["committed"], preview)
            emitted_type = "text_replace"
        else:
            delta = f"\n{preview}" if preview else ""
            state["rendered_preview"] = preview
            emitted_type = "text_delta"
        state["streamed_text"] = True
        return {"type": emitted_type, "text": delta} if delta else None

    async def _cancel_unsupported_prompt(
        self, gateway: GatewayClient, *, session_id: str, event_type: str
    ) -> None:
        """Interrupt a deferred prompt and require a terminal cancellation."""

        try:
            result = await gateway.request("session.interrupt", {"session_id": session_id})
            _require_accepted_request(result, "session.interrupt")
            async with asyncio.timeout(2.0):
                while True:
                    event = await gateway.next_event()
                    if not self._belongs_to_session(event, session_id):
                        continue
                    if event.get("type") != "message.complete":
                        continue
                    payload = event.get("payload")
                    payload = payload if isinstance(payload, dict) else {}
                    status = str(payload.get("status") or "").lower()
                    if status in _CANCELLATION_STATUSES:
                        diagnostic_logger.debug(
                            "gateway.prompt.unsupported_cancelled type=%s", event_type
                        )
                        return
                    raise GatewayTransportError(
                        "gateway prompt cancellation",
                        ConnectionError("gateway did not confirm cancellation"),
                    )
        except GatewayTransportError:
            await self.close()
            raise
        except GatewayRPCError as exc:
            await self.close()
            raise GatewayTransportError(
                "gateway prompt cancellation", ConnectionError("interrupt rejected")
            ) from exc
        except (asyncio.TimeoutError, TimeoutError) as exc:
            await self.close()
            raise GatewayTransportError(
                "gateway prompt cancellation", TimeoutError("cancellation unconfirmed")
            ) from exc


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_accepted_request(result: Any, operation: str) -> None:
    """Require explicit Standard acceptance before treating a request as sent."""

    if not isinstance(result, dict):
        raise GatewayProtocolError(f"gateway {operation} response is not an object")
    accepted = result.get("accepted")
    resolved = result.get("resolved")
    if accepted is not None and type(accepted) is not bool:
        raise GatewayProtocolError(f"gateway {operation} response has invalid acceptance")
    if resolved is not None and type(resolved) is not bool:
        raise GatewayProtocolError(f"gateway {operation} response has invalid resolution")
    status = result.get("status")
    if status is not None and not isinstance(status, str):
        raise GatewayProtocolError(f"gateway {operation} response has invalid status")
    normalized_status = status.lower() if isinstance(status, str) else ""
    if accepted is False or resolved is False or normalized_status in {"rejected", "refused", "failed", "error"}:
        raise GatewayRPCError(operation, normalized_status or "rejected")
    if accepted is True or resolved is True or normalized_status in _ACCEPTED_REQUEST_STATUSES:
        return
    raise GatewayProtocolError(f"gateway {operation} response has no acceptance proof")


__all__ = ["GatewaySession"]
