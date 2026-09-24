from __future__ import annotations

import asyncio
import json

import pytest

import home_client
from home_client import HomeClient, HomeError, PairingRecord, SERVICE
from tests.home_pairing_fakes import HOME, NOW, MemoryPairings, material


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["cancelled_request", "lost_response", "failed_save"])
async def test_interrupted_renewal_reuses_persisted_request_across_client_restart(monkeypatch, interruption):
    monkeypatch.setattr(home_client.time, "time", lambda: NOW)
    store = MemoryPairings()
    store.save(PairingRecord(HOME, "synthetic-device", "old-synthetic-secret", 1, NOW + 60))
    requests = []

    async def renew(method, path, body, *, record):
        persisted = store.load(HOME)
        assert persisted.renewal_request_id == body["request_id"]
        assert persisted.generation == body["generation"] == 1
        assert method == "POST"
        assert path == "/api/v1/devices/synthetic-device/credentials/renew"
        requests.append(dict(body))
        if len(requests) == 1:
            if interruption == "cancelled_request":
                raise asyncio.CancelledError
            if interruption == "lost_response":
                raise HomeError("transport")
            store.backend.fail_generation = 2
        return material(generation=2)

    first = HomeClient(HOME, store=store)
    first.request = renew
    expected = asyncio.CancelledError if interruption == "cancelled_request" else HomeError
    with pytest.raises(expected):
        await first.credential()
    pending = store.load(HOME)
    assert pending.generation == 1
    assert pending.credential == "old-synthetic-secret"
    assert pending.renewal_request_id

    restarted = HomeClient(HOME, store=store)
    restarted.request = renew
    renewed = await restarted.credential()
    assert requests[0] == requests[1]
    assert renewed.generation == 2
    assert renewed.credential == material(generation=2)["credential"]
    assert renewed.renewal_request_id is None
    assert store.load(HOME).generation == 2
    assert store.load(HOME).renewal_request_id is None
    assert not store.lock.locked()


@pytest.mark.asyncio
async def test_two_windows_share_one_renewal_transaction(monkeypatch):
    monkeypatch.setattr(home_client.time, "time", lambda: NOW)
    store = MemoryPairings()
    store.save(PairingRecord(HOME, "synthetic-device", "old-synthetic-secret", 1, NOW + 60))
    requests = []

    async def renew(method, path, body, *, record):
        requests.append(body)
        await asyncio.sleep(0)
        return material(generation=2)

    clients = [HomeClient(HOME, store=store), HomeClient(HOME, store=store)]
    for client in clients:
        client.request = renew
    records = await asyncio.gather(*(client.credential() for client in clients))
    assert len(requests) == 1
    assert [record.generation for record in records] == [2, 2]


@pytest.mark.parametrize("state", ["corrupt", "absent", "delete_failure"])
def test_unpair_deletes_corrupt_records_but_reports_real_deletion_failure(state):
    store = MemoryPairings()
    if state != "absent":
        store.backend.values[SERVICE, HOME] = "not valid credential JSON"
    store.backend.fail_delete = state == "delete_failure"
    if state == "delete_failure":
        with pytest.raises(HomeError, match="Keychain or Linux Secret Service"):
            store.delete("https://HOME.example:443/")
        assert (SERVICE, HOME) in store.backend.values
    else:
        store.delete("https://HOME.example:443/")
        assert (SERVICE, HOME) not in store.backend.values


@pytest.mark.asyncio
async def test_request_rejects_another_homes_credential_before_http(monkeypatch):
    client = HomeClient(HOME, store=MemoryPairings())
    record = PairingRecord("https://other.example", "other-device", "other-synthetic-secret", 1, NOW)

    def unexpected_http(*args):
        pytest.fail("Cross-Home credential reached HTTP")

    monkeypatch.setattr(client, "_request", unexpected_http)
    with pytest.raises(HomeError) as error:
        await client.request("GET", "/api/v1/devices/other-device/configuration", record=record)
    assert error.value.code == "not_paired"
