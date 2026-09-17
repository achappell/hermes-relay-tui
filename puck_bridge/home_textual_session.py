"""Textual adapter that keeps microphone capture local and turns on Home."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import config
from puck_bridge.home_session import HomePuckSession
from session import HermesSession, SessionNotReadyError, UnsupportedTransportError


class HomeTextualSession(HermesSession):
    """Use Home for turns while reusing the TUI's local microphone capture."""

    def __init__(
        self,
        args: Any,
        *,
        home_session_factory: Callable[..., HomePuckSession] | None = None,
    ) -> None:
        super().__init__(args)
        self._home_session: HomePuckSession | None = None
        self._home_session_factory = home_session_factory
        self._profile_env = getattr(args, "profile_env", None)
        self._home_url = str(
            getattr(args, "home_bridge_url", None) or getattr(args, "url", "") or ""
        ).strip()
        self._initial_reconnect = bool(
            getattr(args, "home_reconnect_required", False)
        )
        self._session_id = str(getattr(args, "session_id", "home-local") or "home-local")
        self.confirmed_model = None
        self.confirmed_title = None
        self.confirmed_chat_id = None
        self.confirmed_server_version = None
        self.confirmed_context_limit = None
        self.initial_history = []
        self.active_turn_id = None

    @property
    def capabilities(self) -> frozenset[str]:
        if self._home_session is not None:
            return self._home_session.capabilities
        return super().capabilities

    @property
    def supports_structured_prompts(self) -> bool:
        return (
            self._home_session.supports_structured_prompts
            if self._home_session is not None
            else True
        )

    @property
    def supports_interrupt(self) -> bool:
        return bool(
            self._home_session is not None and self._home_session.supports_interrupt
        )

    def _get_home_session(self) -> HomePuckSession:
        if self._home_session is not None:
            return self._home_session
        if not self._home_url:
            raise RuntimeError(
                "Home bridge URL is missing; set url to the approved "
                "/api/v1/bridge/ws endpoint."
            )
        credential = config.resolve_home_device_credential(self._profile_env)
        if not credential:
            raise RuntimeError(
                f"{config.HOME_DEVICE_CREDENTIAL_ENV} is missing from the private profile env."
            )
        conversation_handle = config.resolve_home_conversation_handle(
            self._profile_env
        )
        if not conversation_handle:
            raise RuntimeError(
                f"{config.HOME_CONVERSATION_HANDLE_ENV} is missing from the private profile env."
            )
        factory = self._home_session_factory or HomePuckSession
        self._home_session = factory(
            self._home_url,
            credential,
            conversation_handle,
            supports_structured_prompts=True,
            session_id=self._session_id,
            session_label="TUI",
            reconnect_required=self._initial_reconnect,
        )
        return self._home_session

    async def connect(self) -> dict[str, Any]:
        home = self._get_home_session()
        ready = await home.connect()
        self._capabilities = home.capabilities
        self._hello_verified = True
        self.turn_index = home.turn_index
        return ready

    def is_connected(self) -> bool:
        return bool(
            self._hello_verified
            and self._home_session is not None
            and self._home_session.is_connected()
        )

    async def wait_for_disconnect(self) -> None:
        home = self._home_session
        if home is None:
            raise SessionNotReadyError("Home bridge is not connected")
        await home.wait_for_disconnect()
        self._hello_verified = False

    async def close(self) -> None:
        self._hello_verified = False
        home = self._home_session
        try:
            if home is not None:
                await home.close()
        finally:
            await super().close()

    def send_turn(
        self,
        text: str,
        *,
        stt_source: str = "local",
    ) -> AsyncIterator[dict[str, Any]]:
        if not self.is_connected():
            raise SessionNotReadyError("Home bridge is not connected")
        home = self._get_home_session()
        events = home.send_turn(text, stt_source=stt_source)

        async def relay_events() -> AsyncIterator[dict[str, Any]]:
            try:
                async for event in events:
                    self.active_turn_id = home.active_turn_id
                    self.turn_index = home.turn_index
                    yield event
            finally:
                self.active_turn_id = home.active_turn_id
                self.turn_index = home.turn_index

        return relay_events()

    async def send_prompt_response(self, **payload: Any) -> bool:
        home = self._home_session
        if home is None:
            return False
        return await home.send_prompt_response(**payload)

    async def interrupt_active_turn(self) -> bool:
        home = self._home_session
        if home is None:
            return False
        return await home.interrupt_active_turn()

    async def list_sessions(self, **_kwargs: Any) -> list[dict[str, Any]]:
        raise UnsupportedTransportError("Home owns session selection; listing is unavailable")

    async def new_session(self, **_kwargs: Any) -> dict[str, Any]:
        raise UnsupportedTransportError("Home owns conversation creation")

    async def switch_session(self, _session_id: str) -> dict[str, Any]:
        raise UnsupportedTransportError("Home owns conversation selection")


__all__ = ["HomeTextualSession"]
