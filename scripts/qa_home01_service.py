"""Opt-in TUI/Home contract acceptance against a disposable real Home HTTP service.

Requires the sibling hermes-relay-home checkout and its test dependencies. Uses
temporary TLS trust and SQLite state, the native credential store with loopback
origins, and Home's synthetic Standard session-directory fixture. Never contacts
the deployed Home or Standard service. All native pairing entries are removed.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
HOME_REPO = Path(os.environ.get("HOME01_SERVICE_REPO", str(Path.home() / "Development/hermes-relay-home")))
sys.path[:0] = [str(ROOT), str(HOME_REPO / "src")]
import home_client
import home_pairing_cli
from home_client import HomeClient, HomeError, PairingRecord, SecurePairings
from hermes_home.api.server import create_server

spec = importlib.util.spec_from_file_location("isolated_home_fixture", HOME_REPO / "tests/test_client_claims_api.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


@contextmanager
def lab():
    with tempfile.TemporaryDirectory(prefix="home01-service-") as directory:
        path = Path(directory)
        cert, key = path / "certificate.pem", path / "private.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(key), "-out", str(cert), "-days", "1",
                        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
                       check=True, capture_output=True)
        h = fixture.Home(path)
        clock = [time.time()]
        h.service._clock = lambda: clock[0]
        server = create_server(h.app, host="127.0.0.1", port=0)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"https://localhost:{server.server_port}"
        store = SecurePairings()
        assert store.load(origin) is None

        def admin(route, body):
            conn = http.client.HTTPSConnection("localhost", server.server_port)
            try:
                conn.request("POST", route, json.dumps(body),
                             {"Authorization": "Bearer admin-secret", "Content-Type": "application/json"})
                response = conn.getresponse()
                data = json.loads(response.read())
                assert response.status == 200, (route, response.status)
                return data
            finally:
                conn.close()

        with patch.dict(os.environ, {"SSL_CERT_FILE": str(cert)}):
            try:
                yield SimpleNamespace(home=h, origin=origin, store=store, clock=clock,
                                      path=path, admin=admin)
            finally:
                try:
                    store.delete(origin)
                    assert store.load(origin) is None
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=3)
                    h.configuration.close()
                    lock = Path.home() / ".hermes-relay-tui/home-locks" / hashlib.sha256(origin.encode()).hexdigest()
                    lock.unlink(missing_ok=True)
                    assert not thread.is_alive()


def enrollment_client(lab, outcome):
    class EnrollmentClient(HomeClient):
        async def request(self, method, route, body=None, *, record=None):
            result = await super().request(method, route, body, record=record)
            if route == "/api/v1/enrollment/requests":
                request_id = result["request_id"]
                if outcome == "approve":
                    await asyncio.to_thread(lab.admin, f"/api/v1/enrollment/requests/{request_id}/approve",
                        {"schema": 1, "scope": {"rooms": [], "capabilities": ["client_claim"],
                         "wake_mapping_grant": {"mode": "selected", "ids": []},
                         "client_grants": [{"profile_id": "amanda"}, {"profile_id": "spark"}]}})
                elif outcome == "reject":
                    await asyncio.to_thread(lab.admin, f"/api/v1/enrollment/requests/{request_id}/reject", {"schema": 1})
                elif outcome == "expire":
                    lab.clock[0] = result["expires_at"] + 1
            return result
    return EnrollmentClient(lab.origin, store=lab.store)


def enroll(lab, outcome="approve", link=False):
    code = lab.admin("/api/v1/enrollment/offers", {"schema": 1})["enrollment_code"]
    client = enrollment_client(lab, outcome)
    output = []
    with patch.object(home_pairing_cli, "HomeClient", lambda _url: client):
        if outcome != "approve":
            try:
                asyncio.run(home_pairing_cli.pair(lab.origin, code, label="Disposable QA", output_fn=output.append, timeout=0.1))
            except HomeError as exc:
                expected = {"pending": "request_expired", "reject": "rejected", "expire": "expired_or_consumed"}[outcome]
                assert exc.code == expected, (outcome, exc.code)
            else:
                raise AssertionError("Enrollment failure unexpectedly succeeded")
            assert lab.store.load(lab.origin) is None
            assert any("Confirmation code:" in line for line in output)
            return
        args = ["pair", "--label", "Disposable QA", "--profile", "qa", "--config", str(lab.path / "config.yaml")]
        secret = f"hermes-home://pair?home={quote(lab.origin, safe='')}&code={quote(code, safe='')}" if link else code
        if not link:
            args += ["--home", lab.origin]
        assert home_pairing_cli.run_pairing_command(args, secret_fn=lambda _: secret,
            input_fn=lambda _: "Amanda", output_fn=output.append) == 0
    record = lab.store.load(lab.origin)
    assert record is not None
    public = (lab.path / "config.yaml").read_text() + "\n".join(output)
    assert record.credential not in public and code not in public
    return record


async def check_service(lab, record):
    client = HomeClient(lab.origin, store=lab.store)
    revision, grants = await client.configuration(record)
    amanda, spark = (next(g for g in grants if g.label == label) for label in ("Amanda", "Spark"))
    rows = await client.sessions(record, amanda)
    assert rows and rows[0]["session_ref"]
    for label, rev, grant, mode, ref, expected in (
        ("cross-profile-reference", revision, spark, "resume", rows[0]["session_ref"], "session_unavailable"),
        ("stale-configuration", revision + 1, amanda, "new", None, "stale_configuration"),
    ):
        try:
            await client.claim(record, rev, grant, mode, ref, claim_id=label)
        except HomeError as exc:
            assert exc.code == expected, (label, exc.code)
        else:
            raise AssertionError(label)
        print(label, "pass", flush=True)
    await client.claim(record, revision, amanda, "new", claim_id="claim-one")
    await client.claim(record, revision, spark, "new", claim_id="claim-two")
    try:
        await client.claim(record, revision, amanda, "new", claim_id="claim-three")
    except HomeError as exc:
        assert exc.code == "claim_limit"
    else:
        raise AssertionError("claim limit")
    print("claim-limit pass", flush=True)

    children = [lab.home.pair(f"qa-child-{i}", ["amanda"]) for i in range(2)]
    pending = await client.owners("pending")
    assert len(pending) == 2
    for index, approved in enumerate((True, False)):
        grant_id = children[index]["client_grants"][0]["grant_id"]
        await client.decide(grant_id, approve=approved)
        child = PairingRecord.material(lab.origin, children[index])
        _, child_grants = await client.configuration(child)
        if approved:
            assert child_grants[0].status == "active"
        else:
            # Home removes rejected grants from the device's usable snapshot.
            assert all(g.grant_id != grant_id for g in child_grants)
    assert not await client.owners("pending")
    assert await client.owners("holders")
    target = lab.home.pair("qa-authorization-target", ["amanda"])
    target_id = target["client_grants"][0]["grant_id"]
    outsider = PairingRecord.material(lab.origin, lab.home.pair("qa-non-owner", ["spark"]))
    try:
        await client.request("POST", f"/api/v1/profile-grants/{target_id}/approve", {"schema": 1}, record=outsider)
    except HomeError as exc:
        assert exc.code == "unauthorized"
    else:
        raise AssertionError("A non-owner approved an owned Profile")
    await client.configuration(outsider)
    print("owner-approve-reject pass", flush=True)

    lab.clock[0] = record.expires_at - 7 * 86400
    clock = SimpleNamespace(time=lambda: lab.clock[0], monotonic=time.monotonic)
    requests = []
    class LostRenewalClient(HomeClient):
        async def request(self, method, route, body=None, *, record=None):
            result = await super().request(method, route, body, record=record)
            if route.endswith("/renew"):
                requests.append(body["request_id"])
                raise HomeError("transport")
            return result
    with patch.object(home_client, "time", clock):
        try:
            await LostRenewalClient(lab.origin, store=lab.store).credential()
        except HomeError as exc:
            assert exc.code == "transport"
        else:
            raise AssertionError("response-loss injection did not run")
        pending_id = lab.store.load(lab.origin).renewal_request_id
        assert pending_id == requests[0]
        renewed = await client.credential()
        assert renewed.generation == record.generation + 1
        assert renewed.renewal_request_id is None
        await client.configuration(renewed)
        lab.clock[0] = renewed.expires_at - 7 * 86400
        windows = [HomeClient(lab.origin, store=SecurePairings()) for _ in range(2)]
        records = await asyncio.gather(*(window.credential() for window in windows))
        assert [r.generation for r in records] == [renewed.generation + 1] * 2
        assert records[0].credential == records[1].credential
    print("native-renewal-lost-response-retry-and-two-concurrent-clients pass", flush=True)
    return records[0]


def main():
    revision = subprocess.check_output(["git", "-C", str(HOME_REPO), "rev-parse", "HEAD"], text=True).strip()
    print("Home source", revision, flush=True)
    for outcome in ("pending", "reject", "expire"):
        with lab() as instance:
            enroll(instance, outcome)
        print("enrollment-" + outcome, "pass", flush=True)
    for link in (False, True):
        with lab() as instance:
            enroll(instance, link=link)
        print("enrollment-" + ("link" if link else "code"), "pass", flush=True)
    with lab() as instance:
        record = enroll(instance)
        record = asyncio.run(check_service(instance, record))
        output = []
        assert home_pairing_cli.run_pairing_command(["unpair", "--home", instance.origin], output_fn=output.append) == 0
        assert instance.store.load(instance.origin) is None
        assert "does not revoke" in " ".join(output)
        client = HomeClient(instance.origin, store=instance.store)
        asyncio.run(client.configuration(record))
        instance.admin(f"/api/v1/devices/{record.device_id}/revoke", {"schema": 1})
        try:
            asyncio.run(client.configuration(record))
        except HomeError as exc:
            assert exc.code == "unauthorized"
        else:
            raise AssertionError("revoked credential still accepted")
        print("native-unpair-keeps-server-access-until-server-revocation pass", flush=True)


if __name__ == "__main__":
    main()
