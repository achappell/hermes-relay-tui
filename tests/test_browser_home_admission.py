from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from home_client import Grant, HomeClient, HomeError, PairingRecord
from home_display.home_store import PrivatePairings
from home_display.home_admission import AdmissionError, BrowserAdmission, BrowserSession
from home_display.state import DisplayCapabilities

HOME = "https://home.example.ts.net"


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    return PrivatePairings(root / "pairing.json")


def record():
    return PairingRecord(HOME, "device-test", "private-test-credential", 1, time.time() + 90 * 86400)


def test_private_store_durable_permissions_origin_and_symlinks(store, tmp_path):
    store.preflight(HOME)
    value = record()
    value.renewal_request_id = "pending-exact-id"
    store.save(value)
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert store.load(HOME).renewal_request_id == "pending-exact-id"
    assert PrivatePairings(store.path).load(HOME).credential == value.credential
    with pytest.raises(HomeError):
        store.load("https://other.example.ts.net")
    store.path.chmod(0o644)
    with pytest.raises(HomeError):
        store.load(HOME)
    store.path.chmod(0o600)
    link = store.path.parent / "link"
    link.symlink_to(store.path)
    with pytest.raises(HomeError):
        PrivatePairings(link).load(HOME)


def test_private_store_rejects_shared_directory_and_repository(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    with pytest.raises(HomeError):
        PrivatePairings(shared / "credential").save(record())
    repo = tmp_path / "repository"
    repo.mkdir(mode=0o700)
    (repo / ".git").mkdir()
    with pytest.raises(HomeError):
        PrivatePairings(repo / "credential").save(record())


def test_single_service_owner(store):
    store.acquire_lease()
    other = PrivatePairings(store.path)
    with pytest.raises(HomeError, match="Another window"):
        other.acquire_lease()
    store.release_lease()
    other.acquire_lease()
    other.release_lease()


@pytest.mark.asyncio
async def test_pending_renewal_reuses_durable_id_and_publishes_only_after_save(store):
    old = record()
    old.expires_at = time.time() + 86400
    store.save(old)
    client = HomeClient(HOME, store=store)
    calls = []

    async def request(method, path, body, **kwargs):
        calls.append(body.copy())
        if len(calls) == 1:
            raise HomeError("transport")
        return {"schema": 1, "device_id": old.device_id, "credential": "replacement-private", "generation": 2, "expires_at": time.time() + 90 * 86400}

    client.request = request
    with pytest.raises(HomeError):
        await client.credential()
    pending = store.load(HOME)
    assert pending.credential == old.credential
    assert pending.renewal_request_id == calls[0]["request_id"]
    fresh = await client.credential()
    assert calls[0] == calls[1]
    assert fresh.generation == 2 and store.load(HOME).credential == fresh.credential
    assert store.load(HOME).renewal_request_id is None


@pytest.mark.asyncio
async def test_actual_nw18_result_vocabulary(store):
    client = HomeClient(HOME, store=store)
    client.request = AsyncMock(return_value={"schema": 1, "results": [{"claim_ref": "a", "result": "closed"}, {"claim_ref": "b", "result": "not_open"}]})
    assert await client.close_claims(record(), {"a", "b"}) == {"a", "b"}
    client.request.return_value["results"][1]["result"] = "not_found"
    with pytest.raises(HomeError):
        await client.close_claims(record(), {"a", "b"})


class Bridge:
    instances = []

    def __init__(self, url, credential, handle):
        self.handle = handle
        self.connected = False
        self.prompts = []
        self.closed = False
        self.capabilities = {"prompt.choose"}
        self.supported_prompt_kinds = ("choice",)
        self.fail = False
        self.confirm_close = True
        Bridge.instances.append(self)

    async def connect(self):
        assert not self.closed, "old bridge must never reconnect"
        self.connected = True

    def is_connected(self):
        return self.connected

    async def close_claim(self):
        return self.confirm_close

    async def close(self):
        self.closed = True
        self.connected = False

    async def send_turn(self, text, **kwargs):
        self.prompts.append(text)
        if self.fail:
            self.connected = False
            raise ConnectionError("private upstream detail")
        yield {"type": "text", "text": text}
        yield {"type": "turn_end"}


class Client:
    def __init__(self):
        self.home = HOME
        self.store = SimpleNamespace(acquire_lease=lambda: None, release_lease=lambda: None)
        self.saved = record()
        self.grants = [Grant("grant-first", "First", "active", True)]
        self.revision = 1
        self.refs = set()
        self.calls = []
        self.closed = []
        self.maximum = 8
        self.error = None
        self.close_error = False
        self.claim_error = None
        self.renew_error = None

    async def credential(self, renew=True):
        if self.error:
            raise HomeError(self.error)
        if renew and self.saved.expires_at - time.time() < 14 * 86400:
            self.saved.renewal_request_id = self.saved.renewal_request_id or "same-id"
            if self.renew_error:
                raise HomeError(self.renew_error)
            self.saved = replace(self.saved, generation=self.saved.generation + 1, expires_at=time.time() + 90 * 86400, renewal_request_id=None)
            self.refs.clear()
        return replace(self.saved)

    async def configuration(self, record):
        return self.revision, list(self.grants)

    async def list_claims(self, record):
        return self.maximum, set(self.refs)

    async def close_claims(self, record, refs):
        self.closed.append(set(refs))
        if self.close_error:
            raise HomeError("transport")
        self.refs -= refs
        return refs

    async def claim(self, record, revision, grant, mode, *, claim_id):
        self.calls.append((claim_id, grant.grant_id, mode))
        if self.claim_error:
            if self.claim_error == "transport":
                self.refs.add("unknown-outcome")
            raise HomeError(self.claim_error)
        ref = f"ref-{len(self.calls)}"
        self.refs.add(ref)
        return {"claim_ref": ref, "conversation_handle": f"handle-{len(self.calls)}"}


@pytest.fixture
def client():
    Bridge.instances.clear()
    return Client()


async def admit(client):
    admission = BrowserAdmission(client, session_factory=Bridge)
    await admission.refresh(force=True)
    return admission


async def turn(session, text="intent"):
    return [event async for event in session.send_turn(text)]


@pytest.mark.asyncio
async def test_idle_tabs_dynamic_profiles_and_selector_secrecy(client):
    admission = await admit(client)
    one, two = BrowserSession(admission, "one"), BrowserSession(admission, "two")
    await one.connect()
    await two.connect()
    assert not client.calls
    first, selected = one.catalog()
    second, _ = two.catalog()
    assert first[0][0] != second[0][0] and selected == first[0][0]
    wire = json.dumps(DisplayCapabilities(features=("browser_profiles",), profiles=first, selected_profile=selected).to_dict())
    assert "grant-first" not in wire and "private-test" not in wire
    client.grants.append(Grant("grant-later", "Later", "active", True))
    client.grants.append(Grant("grant-pending", "Pending", "pending_owner", True))
    await admission.refresh(force=True)
    rows, _ = one.catalog()
    assert [row[1] for row in rows] == ["First", "Later", "Pending"]
    assert rows[-1][2] is False
    assert await one.select(rows[1][0])
    await turn(one)
    assert client.calls[0][1:] == ("grant-later", "new")
    assert not two.bridge


@pytest.mark.asyncio
async def test_independent_tabs_disconnect_and_bridge_loss_never_replay(client):
    admission = await admit(client)
    one, two = BrowserSession(admission, "one"), BrowserSession(admission, "two")
    await one.connect()
    await two.connect()
    await asyncio.gather(turn(one, "one intent"), turn(two, "two intent"))
    assert one.claim_ref != two.claim_ref
    old = one.bridge
    old.fail = True
    assert (await turn(one, "uncertain"))[-1]["reason"] == "hermes_unavailable"
    assert one.bridge is None and two.bridge is not None
    await turn(one, "new intent")
    assert one.bridge is not old
    assert old.prompts == ["one intent", "uncertain"]
    assert one.bridge.prompts == ["new intent"]
    live = two.claim_ref
    await one.close()
    assert all(live not in refs for refs in client.closed)
    assert all(call[2] == "new" for call in client.calls)


@pytest.mark.asyncio
async def test_startup_sweep_and_tombstones_block_capacity(client):
    client.refs = {"orphan"}
    client.maximum = 1
    client.close_error = True
    admission = await admit(client)
    assert admission.known == {"orphan"}
    assert admission.health()[0] == 503
    session = BrowserSession(admission, "one")
    await session.connect()
    await turn(session)
    assert not client.calls and admission.known == {"orphan"}
    client.close_error = False
    await admission.refresh(force=True)
    await turn(session)
    assert len(client.calls) == 1
    other = BrowserSession(admission, "two")
    await other.connect()
    assert (await turn(other))[-1]["reason"] == "claim_limit"
    assert len(client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("code,reason", [("stale_configuration", "configuration_changed"), ("transport", "home_unreachable"), ("claim_limit", "claim_limit"), ("unauthorized", "home_unauthorized")])
async def test_one_claim_attempt_per_action_and_typed_errors(client, code, reason):
    admission = await admit(client)
    session = BrowserSession(admission, "one")
    await session.connect()
    client.claim_error = code
    assert (await turn(session))[-1]["reason"] == reason
    assert len(client.calls) == 1
    assert session.bridge is None


@pytest.mark.asyncio
async def test_renewal_uncertainty_retires_all_claims_without_replay(client):
    admission = await admit(client)
    session = BrowserSession(admission, "one")
    await session.connect()
    await turn(session, "before renewal")
    old = session.bridge
    client.saved.expires_at = time.time() + 86400
    client.renew_error = "transport"
    await admission.refresh(force=True)
    assert session.bridge is None and old.closed
    assert admission.reason == "credential_renewal_uncertain"
    await turn(session, "must not dispatch")
    assert len(client.calls) == 1
    client.renew_error = None
    await admission.refresh(force=True)
    await turn(session, "deliberate later action")
    assert len(client.calls) == 2
    assert session.bridge.prompts == ["deliberate later action"]


@pytest.mark.asyncio
async def test_rename_reissue_and_duplicate_labels_never_retarget(client):
    admission = await admit(client)
    session = BrowserSession(admission, "one")
    await session.connect()
    token = session.catalog()[1]
    client.grants = [Grant("grant-first", "Renamed", "active", True), Grant("different", "First", "active", True)]
    await admission.refresh(force=True)
    assert session.tokens[token] == "grant-first"
    assert session.label == "Renamed"
    client.grants = [Grant("different", "First", "active", True)]
    await admission.refresh(force=True)
    assert token not in session.tokens
    assert session.selected == "grant-first"
    with pytest.raises(AdmissionError):
        await session.select(token)
    client.grants.append(Grant("duplicate", "First", "active", True))
    await admission.refresh(force=True)
    assert session.catalog()[0] == ()


@pytest.mark.asyncio
async def test_idle_health_no_claims_revocation_and_recovery(client):
    admission = await admit(client)
    assert admission.health() == (200, {"status": "ok"})
    client.error = "unauthorized"
    await admission.refresh(force=True)
    assert admission.health() == (503, {"status": "degraded", "reason": "home_unauthorized"})
    client.error = None
    await admission.refresh(force=True)
    assert admission.health()[0] == 200
    admission.updated = time.monotonic() - 46
    assert admission.health()[0] == 503
    assert not client.calls


@pytest.mark.asyncio
async def test_startup_does_not_block_local_unavailable_page_on_home_timeout(client):
    blocked = asyncio.Event()
    entered = asyncio.Event()
    async def unavailable(_record):
        entered.set()
        await blocked.wait()
        raise HomeError("transport")
    client.configuration = unavailable
    admission = BrowserAdmission(client, session_factory=Bridge)
    await asyncio.wait_for(admission.start(), 0.1)
    await entered.wait()
    assert admission.health() == (503, {"status": "degraded", "reason": "home_unreachable"})
    session = BrowserSession(admission, "idle")
    await asyncio.wait_for(session.connect(), 0.1)
    assert session.catalog() == ((), None)
    assert client.calls == []
    blocked.set()
    await admission.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("device_revoked", [False, True])
async def test_bridge_loss_reconciles_revocation_without_false_hermes_outage(client, device_revoked):
    admission = await admit(client)
    session = BrowserSession(admission, "tab")
    await session.connect()
    await turn(session, "before")
    old = session.bridge
    old.fail = True
    if device_revoked:
        client.error = "unauthorized"
    else:
        client.grants.clear()
        client.refs.clear()
    result = await turn(session, "not replayed")
    assert result[-1]["reason"] == ("home_unauthorized" if device_revoked else "profile_unavailable")
    assert old.closed and session.bridge is None
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_stale_claim_refresh_hides_duplicate_labels_without_second_claim(client):
    admission = await admit(client)
    session = BrowserSession(admission, "tab")
    await session.connect()
    client.grants.append(Grant("duplicate", "FIRST", "active", True))
    client.claim_error = "stale_configuration"
    assert (await turn(session))[-1]["reason"] == "configuration_changed"
    assert session.catalog()[0] == ()
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_queued_selection_cannot_close_a_turn_that_started_while_waiting(client):
    admission = await admit(client)
    session = BrowserSession(admission, "tab")
    await session.connect()
    await turn(session, "first")
    old_bridge, old_ref = session.bridge, session.claim_ref
    client.grants.append(Grant("later", "Later", "active", True))
    await admission.refresh(force=True)
    token = next(token for token, label, _ in session.catalog()[0] if label == "Later")
    refreshed, running, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def cached_refresh(**_kwargs):
        refreshed.set()
    async def held_turn(text, **_kwargs):
        old_bridge.prompts.append(text)
        running.set()
        await finish.wait()
        yield {"type": "turn_end"}
    admission.refresh = cached_refresh
    old_bridge.send_turn = held_turn
    await admission.lock.acquire()
    selecting = asyncio.create_task(session.select(token))
    await refreshed.wait()
    active = asyncio.create_task(turn(session, "ongoing"))
    await running.wait()
    admission.lock.release()
    assert await selecting is False
    assert session.bridge is old_bridge and session.claim_ref == old_ref
    assert not old_bridge.closed and session.selected == "grant-first"
    finish.set()
    await active
    assert len(client.calls) == 1
