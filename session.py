"""Front-end-agnostic Hermes session orchestration.

Owns the connection, turn lifecycle, and microphone wiring for one Hermes
voice session. This module deliberately imports no user-interface framework:
the Textual TUI in `app.py` is one consumer, and a voice-only or display-based
front end is expected to drive the same class without importing the TUI.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any, AsyncIterator, Protocol

import config
from client import send_hello, send_interrupt, send_turn
from diagnostics import logger as diagnostic_logger, summarize_text
from mic import (
    LocalMicrophone,
    cancel_microphone,
    make_recorder_factory,
    prepare_local_stt,
)


class SessionProtocol(Protocol):
    """What a front end needs from a session — implemented by `HermesSession`
    and by the test doubles, so there is exactly one code path here."""

    turn_index: int

    async def connect(self) -> dict[str, Any]: ...

    def is_connected(self) -> bool: ...

    def send_turn(self, text: str, *, stt_source: str = "local") -> AsyncIterator[dict[str, Any]]: ...

    async def interrupt_active_turn(self) -> bool: ...

    def capture_voice(self, *, wait_timeout: float | None = None) -> str: ...

    def cancel_voice(self) -> None: ...

    async def set_input_device(self, device: int | str | None) -> None: ...

    async def close(self) -> None: ...


class HermesSession:
    """Owns one open websocket connection and turn history for the app's lifetime."""

    def __init__(self, args) -> None:
        self.args = args
        self.ws: Any = None
        self._connect_cm: Any = None
        self.turn_index = 0
        self.microphone: Any = None
        self.input_device = getattr(args, "mic_input_device", None)
        self._voice_cancel_requested = threading.Event()
        self._shared_recorder: Any = None
        self._capabilities: frozenset[str] = frozenset()
        self.active_turn_id: str | None = None
        self._interrupt_sent_for_turn: str | None = None

    @property
    def supports_interrupt(self) -> bool:
        """Whether the connected endpoint advertised remote interruption."""
        return "interrupt" in self._capabilities

    def use_shared_recorder(self, recorder: Any) -> None:
        """Capture through a recorder somebody else already opened.

        The hands-free appliance keeps one input stream open for the whole
        process so its wake-word listener can hear the room. Capture has to
        borrow that stream: two input streams on one device is unreliable, and
        reopening one can hang on macOS CoreAudio.
        """
        self._shared_recorder = recorder
        self.microphone = None

    async def connect(self) -> dict[str, Any]:
        if self._connect_cm is not None or self.ws is not None:
            await self.close()
        connect = config.connect_factory()
        token = config._resolve_token(self.args.token, self.args.profile_env)
        if not token:
            raise RuntimeError(
                "No voice-session token found. Run `hermes-relay setup`, "
                "set VOICE_SESSION_TOKEN, or configure the profile .env."
            )
        kwargs = config._connection_kwargs(connect, token)
        diagnostic_logger.debug(
            "connect.start url=%s session_id=%s client_id=%s device_id=%s",
            self.args.url.split("?", 1)[0],
            self.args.session_id,
            self.args.client_id,
            self.args.device_id,
        )
        try:
            self._connect_cm = connect(self.args.url, **kwargs)
            self.ws = await self._connect_cm.__aenter__()
            hello = await send_hello(
                self.ws,
                client_id=self.args.client_id,
                device_id=self.args.device_id,
                session_id=self.args.session_id,
                display_name=self.args.display_name,
            )
            capabilities = hello.get("capabilities")
            if not isinstance(capabilities, (list, tuple, set, frozenset)):
                nested = hello.get("payload")
                capabilities = nested.get("capabilities") if isinstance(nested, dict) else ()
            self._capabilities = frozenset(
                str(capability).strip().lower()
                for capability in capabilities
                if str(capability).strip()
            )
            diagnostic_logger.debug(
                "connect.hello_ack keys=%s chat_id_present=%s capabilities=%s",
                ",".join(sorted(str(key) for key in hello)),
                bool(hello.get("chat_id")),
                ",".join(sorted(self._capabilities)) or "-",
            )
            return hello
        except BaseException as exc:
            diagnostic_logger.error("connect.failed type=%s", type(exc).__name__)
            try:
                await self.close()
            except Exception:
                pass
            raise

    def is_connected(self) -> bool:
        return self.ws is not None

    async def close(self) -> None:
        self.cancel_voice()
        microphone = self.microphone
        self.microphone = None
        # A shared recorder outlives the session that borrowed it: closing the
        # microphone here would shut down the appliance's listening stream on
        # every reconnect.
        if microphone is not None and self._shared_recorder is None:
            await asyncio.to_thread(microphone.close)
        if self._connect_cm is not None:
            try:
                await self._connect_cm.__aexit__(None, None, None)
            finally:
                self._connect_cm = None
                self.ws = None
        self._capabilities = frozenset()
        self.active_turn_id = None
        self._interrupt_sent_for_turn = None

    def send_turn(self, text: str, *, stt_source: str = "local"):
        # turn_index stays 0-based for the first turn, matching the reference
        # script's `index` — _audio_path only adds a suffix from index 1 on.
        self.turn_index += 1
        diagnostic_logger.debug(
            "session.turn index=%d stt_source=%s %s",
            self.turn_index,
            stt_source,
            summarize_text(text),
        )
        turn_id = uuid.uuid4().hex
        self.active_turn_id = turn_id
        self._interrupt_sent_for_turn = None
        return send_turn(
            self.ws,
            session_id=self.args.session_id,
            text=text,
            stt_source=stt_source,
            turn_id=turn_id,
        )

    async def interrupt_active_turn(self) -> bool:
        """Ask Hermes to stop the current turn when the endpoint supports it."""
        turn_id = self.active_turn_id
        if not self.is_connected() or not self.supports_interrupt or not turn_id:
            return False
        if self._interrupt_sent_for_turn == turn_id:
            return True
        await send_interrupt(
            self.ws,
            session_id=self.args.session_id,
            turn_id=turn_id,
        )
        self._interrupt_sent_for_turn = turn_id
        return True

    def capture_voice(self, *, wait_timeout: float | None = None) -> str:
        self._voice_cancel_requested.clear()
        # faster-whisper downloads its model lazily. Its tqdm subclass can
        # otherwise create multiprocessing's resource tracker, which cannot
        # pass Textual's intentionally invalid stderr fd on macOS.
        prepare_local_stt()
        if self.microphone is None:
            self.microphone = LocalMicrophone(
                max_seconds=self.args.mic_max_seconds,
                silence_duration=self.args.mic_silence_duration,
                silence_threshold=self.args.mic_silence_threshold,
                model=self.args.stt_model,
                recorder_factory=make_recorder_factory(
                    self.input_device,
                    self._voice_cancel_requested,
                    recorder=self._shared_recorder,
                ),
            )
        if wait_timeout is None:
            return self.microphone.capture()
        return self.microphone.capture(wait_timeout=wait_timeout)

    def cancel_voice(self) -> None:
        self._voice_cancel_requested.set()
        if self.microphone is not None:
            cancel_microphone(self.microphone)

    async def set_input_device(self, device: int | str | None) -> None:
        """Select the input device for subsequent microphone captures."""
        if self.input_device == device:
            return
        self.cancel_voice()
        microphone = self.microphone
        self.microphone = None
        self.input_device = device
        if microphone is not None and self._shared_recorder is None:
            await asyncio.to_thread(microphone.close)
