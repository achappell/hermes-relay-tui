"""Browser-only admission: fresh lazy claims, one owner process, no turn replay."""
from __future__ import annotations

import asyncio
from collections import Counter
import contextlib
import logging
import time
import uuid

from home_client import HomeClient, HomeError, RENEW_WINDOW, bridge_url, _string
from puck_bridge.home_session import HomeBrowserSession, HomeBridgeRPCError, HomeBridgeUnavailableError

logger = logging.getLogger("hermes_relay_tui.browser")
MESSAGES = {
    "home_unreachable": "Hermes Home can't be reached. Try again shortly.",
    "home_unauthorized": "This display needs to be paired again.",
    "hermes_unavailable": "Hermes isn't responding. This conversation was not replayed.",
    "profile_unavailable": "This Profile isn't available on this display.",
    "grant_pending": "This Profile still needs its owner's approval.",
    "configuration_changed": "Home access changed. Review the Profile and try again.",
    "credential_renewal_uncertain": "Home access is being recovered. This conversation was not replayed.",
    "claim_limit": "Too many conversations are open. Try again in a moment.",
}


class AdmissionError(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason if reason in MESSAGES else "home_unreachable"
        super().__init__(MESSAGES[self.reason])


def reason_for(error: Exception) -> str:
    if isinstance(error, AdmissionError):
        return error.reason
    if isinstance(error, HomeError):
        return {"unauthorized": "home_unauthorized", "not_paired": "home_unauthorized", "private_store": "home_unauthorized", "stale_configuration": "configuration_changed", "client_claim_unavailable": "profile_unavailable", "profile_unavailable": "profile_unavailable", "grant_pending": "grant_pending", "claim_limit": "claim_limit"}.get(error.code, "home_unreachable")
    if isinstance(error, HomeBridgeRPCError) and error.code == "unauthorized":
        return "home_unauthorized"
    if isinstance(error, HomeBridgeUnavailableError):
        return "hermes_unavailable"
    return "hermes_unavailable"


class BrowserAdmission:
    """All claim/config/renewal transitions serialize; HTTP never admits a turn twice."""
    def __init__(self, client: HomeClient, *, socket_limit: int = 8, session_factory=HomeBrowserSession):
        self.client = client
        self.socket_limit = socket_limit
        self.session_factory = session_factory
        self.lock = asyncio.Lock()
        self.record = None
        self.revision = 0
        self.grants = []
        self.updated = 0.0
        self.reason: str | None = "home_unreachable"
        self.maximum = 0
        self.known: set[str] = set()
        self.accounted = False
        self.sessions: set[BrowserSession] = set()
        self.task: asyncio.Task | None = None
        self.last_log: dict[str, float] = {}

    def failure(self, error: Exception, connection: str = "service") -> str:
        reason = reason_for(error)
        now = time.monotonic()
        if now - self.last_log.get(reason, -100) >= 10:
            logger.log(logging.ERROR if reason == "home_unauthorized" else logging.WARNING,
                       "browser.admission.failed reason=%s exc=%s connection=%s", reason, type(error).__name__, connection[:16])
            self.last_log[reason] = now
        return reason

    async def start(self):
        self.client.store.acquire_lease()
        self.task = asyncio.create_task(self._maintain())

    async def _maintain(self):
        while True:
            await self.refresh(force=True)
            await asyncio.sleep(15)

    async def close(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        for session in list(self.sessions):
            await session.close()
        self.client.store.release_lease()

    async def refresh(self, *, force=False):
        async with self.lock:
            if not force and self.accounted and time.monotonic() - self.updated < 30 and self.reason is None:
                return
            try:
                await self._refresh_locked()
            except Exception as error:
                self.reason = self.failure(error)
                if self.reason == "home_unauthorized":
                    self.grants = []
                    self.accounted = False
                    for session in list(self.sessions):
                        await session._retire_locked(uncertain=True, reason=self.reason)
            for session in self.sessions:
                session.changed()

    async def _refresh_locked(self):
        before = await self.client.credential(renew=False)
        due = before.renewal_request_id or before.expires_at - time.time() <= RENEW_WINDOW
        changed = self.record is not None and self.record.generation != before.generation
        if due or changed:
            # Retire the local turns BEFORE Home invalidates their generation.
            for session in list(self.sessions):
                await session._retire_locked(uncertain=True)
            self.accounted = False
        if due:
            logger.warning("browser.credential_expiring")
            try:
                self.record = await self.client.credential()
            except HomeError as error:
                if error.code == "unauthorized":
                    raise
                raise AdmissionError("credential_renewal_uncertain") from None
        else:
            self.record = before
        await self._configuration_locked()
        active = {s.claim_ref for s in self.sessions if s.claim_ref}
        self.maximum, actual = await self.client.list_claims(self.record)
        self.known = actual
        self.accounted = True
        orphans = actual - active
        if orphans:
            confirmed = await self.client.close_claims(self.record, orphans)
            self.known -= confirmed
        # A Home restart/revocation may remove a live claim. Never reconnect it.
        for session in list(self.sessions):
            if session.claim_ref and session.claim_ref not in actual:
                await session._retire_locked(uncertain=True, reason="configuration_changed")
        self.updated = time.monotonic()
        self.reason = None if any(g.usable for g in self.grants) else "profile_unavailable"

    async def _configuration_locked(self):
        revision, grants = await self.client.configuration(self.record)
        counts = Counter(g.label.casefold() for g in grants)
        self.grants = [g for g in grants if counts[g.label.casefold()] == 1]
        self.revision = revision

    def health(self):
        reason = self.reason
        if time.monotonic() - self.updated > 45:
            reason = reason or "home_unreachable"
        return (503, {"status": "degraded", "reason": reason}) if reason else (200, {"status": "ok"})

    async def open(self, owner: BrowserSession):
        await self.refresh()
        async with self.lock:
            if self.reason:
                raise AdmissionError(self.reason)
            if owner.retired_during_turn:
                raise AdmissionError("credential_renewal_uncertain")
            grant = next((g for g in self.grants if g.grant_id == owner.selected), None)
            if grant is None or not grant.usable:
                raise AdmissionError("grant_pending" if grant and grant.status == "pending_owner" else "profile_unavailable")
            if not self.accounted or len(self.known) >= min(self.socket_limit, self.maximum):
                raise AdmissionError("claim_limit")
            # A lost response can have consumed capacity: require a later list,
            # never retry the claim that belongs to this action.
            self.accounted = False
            try:
                data = await self.client.claim(self.record, self.revision, grant, "new", claim_id=uuid.uuid4().hex)
                ref = _string(data.get("claim_ref"), 128)
            except HomeError as error:
                if error.code == "stale_configuration":
                    try:
                        await self._configuration_locked()
                        self.updated = time.monotonic()
                    except HomeError:
                        self.updated = 0
                    owner.changed()
                self.updated = 0
                raise AdmissionError(self.failure(error, owner.identity)) from None
            except BaseException:
                self.updated = 0
                raise
            self.known.add(ref)
            self.accounted = True
            owner.claim_ref = ref
            owner.bridge = self.session_factory(bridge_url(self.client.home), self.record.credential, data["conversation_handle"])
            try:
                await owner.bridge.connect()
            except BaseException:
                await owner._retire_locked(uncertain=True)
                raise


class BrowserSession:
    """SessionProtocol facade; idle tabs have no upstream session or claim."""
    def __init__(self, admission: BrowserAdmission, identity: str):
        self.admission = admission
        self.identity = identity
        self.selected: str | None = None
        self.tokens: dict[str, str] = {}
        self.bridge = None
        self.claim_ref: str | None = None
        self.on_change = None
        self.active = False
        self.retired_during_turn = False
        self.retired_reason = "credential_renewal_uncertain"
        admission.sessions.add(self)

    def changed(self):
        current = {g.grant_id for g in self.admission.grants}
        self.tokens = {token: grant for token, grant in self.tokens.items() if grant in current}
        assigned = set(self.tokens.values())
        for grant in self.admission.grants:
            if grant.grant_id not in assigned:
                self.tokens[uuid.uuid4().hex] = grant.grant_id
        if self.selected is None:
            self.selected = next((g.grant_id for g in self.admission.grants if g.usable), None)
        if self.on_change:
            self.on_change()

    def catalog(self):
        self.changed_tokens_only()
        tokens = {grant: token for token, grant in self.tokens.items()}
        return tuple((tokens[g.grant_id], g.label, g.usable) for g in self.admission.grants), tokens.get(self.selected)

    def changed_tokens_only(self):
        callback, self.on_change = self.on_change, None
        try:
            self.changed()
        finally:
            self.on_change = callback

    async def select(self, token: str):
        await self.admission.refresh()
        if self.active:
            return False
        grant_id = self.tokens.get(token)
        grant = next((g for g in self.admission.grants if g.grant_id == grant_id), None)
        if grant is None or not grant.usable:
            raise AdmissionError("profile_unavailable")
        if self.selected != grant_id:
            async with self.admission.lock:
                if self.active:
                    return False
                await self._retire_locked()
                self.selected = grant_id
        self.changed()
        return True

    @property
    def label(self):
        return next((g.label for g in self.admission.grants if g.grant_id == self.selected), "Choose a Profile")

    @property
    def capabilities(self):
        return getattr(self.bridge, "capabilities", set())

    @property
    def supported_prompt_kinds(self):
        return getattr(self.bridge, "supported_prompt_kinds", ())

    def is_connected(self):
        return True  # The local doorway remains usable while Home is unavailable.

    async def connect(self):
        self.changed()

    async def _retire_locked(self, *, uncertain=False, reason="credential_renewal_uncertain"):
        bridge, self.bridge = self.bridge, None
        ref, self.claim_ref = self.claim_ref, None
        if self.active:
            self.retired_during_turn = True
            self.retired_reason = reason
        if bridge is not None:
            confirmed = False
            if not uncertain and bridge.is_connected():
                with contextlib.suppress(Exception):
                    confirmed = await bridge.close_claim()
            await bridge.close()
            if confirmed and ref:
                self.admission.known.discard(ref)
        # Unconfirmed refs remain in known until next authenticated list/close.
        if ref in self.admission.known:
            self.admission.updated = 0

    async def close(self):
        async with self.admission.lock:
            await self._retire_locked()
            self.admission.sessions.discard(self)
        await self.admission.refresh(force=True)

    def cancel_voice(self):
        if self.bridge:
            self.bridge.cancel_voice()

    async def interrupt_active_turn(self):
        if self.bridge and self.bridge.is_connected():
            return await self.bridge.interrupt_active_turn()
        return False

    async def send_prompt_response(self, **kwargs):
        if not self.bridge or not self.bridge.is_connected():
            return False
        try:
            return await self.bridge.send_prompt_response(**kwargs)
        except Exception as error:
            self.admission.failure(error, self.identity)
            async with self.admission.lock:
                await self._retire_locked(uncertain=True)
            return False

    async def send_turn(self, text: str, **kwargs):
        self.active = True
        self.retired_during_turn = False
        try:
            await self.admission.refresh()
            if self.admission.reason:
                raise AdmissionError(self.admission.reason)
            if self.bridge is not None and not self.bridge.is_connected():
                async with self.admission.lock:
                    await self._retire_locked(uncertain=True)
                self.retired_during_turn = False
            if self.bridge is None:
                await self.admission.open(self)
            if self.retired_during_turn:
                raise AdmissionError(self.retired_reason)
            async for event in self.bridge.send_turn(text, **kwargs):
                if event.get("type") in {"error", "audio_abort"}:
                    raise AdmissionError("hermes_unavailable")
                yield event
        except asyncio.CancelledError:
            async with self.admission.lock:
                await self._retire_locked(uncertain=True)
            raise
        except Exception as error:
            reason = reason_for(error)
            if reason == "hermes_unavailable":
                # A bridge close alone cannot distinguish a revoked grant from
                # an upstream outage. Reconcile authority, never retry the turn.
                await self.admission.refresh(force=True)
                if self.admission.reason:
                    reason = self.admission.reason
                elif not any(g.grant_id == self.selected and g.usable for g in self.admission.grants):
                    reason = "profile_unavailable"
                elif self.retired_during_turn:
                    reason = self.retired_reason
            elif self.retired_during_turn:
                reason = self.retired_reason
            self.admission.failure(AdmissionError(reason), self.identity)
            async with self.admission.lock:
                await self._retire_locked(uncertain=True)
            yield {"type": "error", "error": MESSAGES[reason], "reason": reason}
        finally:
            self.active = False
