"""Textual adapter that keeps microphone capture local and turns on Home."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any
import asyncio
import uuid

from home_client import HomeClient, HomeError, Grant, bridge_url

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
        self._home_client: HomeClient | None = None
        self._grant_label = str(getattr(args, "home_grant", "") or "")
        self.grant: Grant | None = None
        self.grants: list[Grant] = []
        self._claim_request_uncertain = False
        self._operation_lock = asyncio.Lock()
        self._closed_explicitly = False
        self.resumed = False
        self.pending_replacement = False
        self._picker_refs: dict[str, str] = {}
        self._session_mode = "resume" if getattr(args, "home_resume", None) else ("most_recent" if getattr(args, "home_continue", False) else "new")
        self._resume_ref = getattr(args, "home_resume", None)
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

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def home_client(self) -> HomeClient:
        if self._home_client is None:
            self._home_client = HomeClient(self._home_url)
        return self._home_client

    async def refresh_grants(self, *, renew: bool = False):
        record = await self.home_client.credential(renew=renew)
        revision, self.grants = await self.home_client.configuration(record)
        return record, revision

    def _select_grant(self) -> Grant:
        if self.grant is not None:
            candidates = [g for g in self.grants if g.grant_id == self.grant.grant_id]
        elif self._grant_label:
            candidates = [g for g in self.grants if g.grant_id == self._grant_label]
            if not candidates:
                labelled = [g for g in self.grants if g.label == self._grant_label]
                candidates = [g for g in labelled if g.usable] or labelled
        else:
            candidates = [g for g in self.grants if g.usable]
        if len(candidates) != 1:
            raise HomeError("grant_selection")
        grant = candidates[0]
        if not grant.usable:
            raise HomeError("grant_pending" if grant.status == "pending_owner" else "profile_unavailable")
        self._grant_label = grant.grant_id
        return grant

    async def connect(self) -> dict[str, Any]:
        async with self._operation_lock:
            if self._closed_explicitly:
                raise SessionNotReadyError("This Home claim was closed; choose New or Resume deliberately.")
            if self._claim_request_uncertain:
                raise SessionNotReadyError("The claim request outcome is unknown. It will not be retried automatically; choose /new deliberately after checking Home.")
            # Renewal can invalidate claims on Home. Only renew before creating
            # one, and always reread the current credential on recovery.
            record, revision = await self.refresh_grants(renew=self._home_session is None)
            selected = self._select_grant()
            if self._home_session is None:
                self._claim_request_uncertain = True
                try:
                    claim = await self.home_client.claim(record, revision, selected, self._session_mode, self._resume_ref, claim_id=uuid.uuid4().hex)
                except HomeError as exc:
                    if exc.code not in {"transport", "invalid_response", "service_unavailable"}:
                        self._claim_request_uncertain = False
                    raise
                self._claim_request_uncertain = False
                self.grant = selected
                self.resumed = claim["session"]["mode"] == "resumed"
                factory = self._home_session_factory or HomePuckSession
                self._home_session = factory(bridge_url(self._home_url), record.credential, claim["conversation_handle"], supports_structured_prompts=True, session_id=self._session_id, session_label="TUI", resume_uncertain_turn=False)
            home = self._home_session
            home.device_credential = record.credential
            ready = await home.connect()
            self._session_id = home.session_id
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
        home = self._home_session
        assert home is not None
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

    async def release_claim(self) -> bool:
        """Explicit quit/switch retires the claim; close() alone preserves recovery."""
        home = self._home_session
        if home is None:
            self._closed_explicitly = True
            return not self._claim_request_uncertain
        try:
            async with asyncio.timeout(20):
                record = await self.home_client.credential(renew=False)
                home.device_credential = record.credential
                ok = await home.close_claim() if home.is_connected() else await home.retry_uncertain_claim()
                if not ok and getattr(home, "retirement_rejection", None) == "stale_conversation":
                    # Home authoritatively says the old handle no longer binds
                    # a claim. A deliberate new claim cannot overlap it.
                    ok = True
        except Exception:
            ok = False
        self._hello_verified = False
        if ok:
            self._closed_explicitly = True
        return ok

    async def list_sessions(self, *, limit: int = 50, **_kwargs: Any) -> list[dict[str, Any]]:
        record, _ = await self.refresh_grants()
        grant = self._select_grant()
        rows = await self.home_client.sessions(record, grant, limit)
        # Opaque references remain in memory; the picker displays local keys.
        self._picker_refs = {}
        listing_id = uuid.uuid4().hex
        result = []
        for index, row in enumerate(rows, 1):
            key = f"conversation-{listing_id}-{index}"
            self._picker_refs[key] = row["session_ref"]
            result.append({"session_id": key, "title": row["title"], "started_at": row["started_at"], "message_count": row["message_count"], "active": row["active"], "opaque": True})
        return result

    async def _replace(self, mode: str, ref: str | None = None, *, grant_label: str | None = None) -> dict[str, Any]:
        if self.active_turn_id:
            raise SessionNotReadyError("Cannot replace an active Home turn")
        if self._home_session is not None and not self._closed_explicitly:
            if not await self.release_claim():
                raise SessionNotReadyError("Home did not confirm closing the previous claim. Transcript retained; reconnect or try again before switching.")
        self.pending_replacement = True
        self._home_session = None
        self._closed_explicitly = False
        self._claim_request_uncertain = False
        self._session_mode, self._resume_ref = mode, ref
        self._picker_refs = {}
        if grant_label is not None:
            self.grant = None
            self._grant_label = grant_label
        old_id = self._session_id
        self._session_id = "home-" + uuid.uuid4().hex[:12]
        try:
            await self.connect()
        except BaseException:
            self._session_id = old_id
            raise
        self.active_turn_id = None
        self.confirmed_title = None
        return {"history": [], "resumed": self.resumed, "history_available": False}

    async def new_session(self, *, session_id: str | None = None, **_kwargs: Any) -> dict[str, Any]:
        if session_id:
            raise UnsupportedTransportError("Home chooses the session identity; use /new without an ID")
        return await self._replace("new")

    async def continue_session(self) -> dict[str, Any]:
        return await self._replace("most_recent")

    async def switch_session(self, session_id: str) -> dict[str, Any]:
        ref = self._picker_refs.get(session_id)
        if not ref:
            raise UnsupportedTransportError("Choose a conversation from /sessions; Home references are scoped to the current Profile")
        return await self._replace("resume", ref)

    async def select_grant(self, label: str) -> dict[str, Any]:
        await self.refresh_grants()
        matches = [g for g in self.grants if label in {g.label, g.grant_id} and g.usable]
        if len(matches) != 1:
            raise HomeError("grant_selection")
        return await self._replace("new", grant_label=matches[0].grant_id)

    async def set_title(self, title: str) -> None:
        home = self._home_session
        if not home or "title" not in home.capabilities:
            raise UnsupportedTransportError("Home has not advertised the title command")
        await home.dispatch_title(title)
        self.confirmed_title = title


__all__ = ["HomeTextualSession"]
