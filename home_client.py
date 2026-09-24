"""Bounded Home HTTP client and per-origin platform-secure pairing records.

No credentials or conversation handles belong in config, logs, or reprs.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, asdict
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import sys
import time
import threading
import socket
from typing import Any
from urllib.parse import urlsplit, quote
import uuid

MAX_RESPONSE = 256 * 1024
HTTP_TIMEOUT = 15.0
RENEW_WINDOW = 14 * 24 * 60 * 60
SERVICE = "hermes-relay-tui.home.v1"
_MESSAGES = {
    "rejected": "Home rejected this pairing request.",
    "expired_or_consumed": "This pairing code expired or was already consumed; start again and revoke any unused device on Home.",
    "approval_pending": "Pairing awaits approval on Home's pairing page.",
    "request_rejected": "Home rejected this pairing request.",
    "request_expired": "The pairing request expired; start pairing again.",
    "request_consumed": "This single-use pairing was already consumed; pair again and revoke the unused device on Home.",
    "grant_pending": "This Profile still needs its owner's approval.",
    "stale_configuration": "Home configuration changed; refresh grants and try again.",
    "session_busy": "Another client controls that conversation.",
    "conversation_active": "This claim is already active.",
    "claim_limit": "This device reached Home's active claim limit; close another window or wait for its claim to expire.",
    "profile_unavailable": "The granted Profile is unavailable.",
    "client_claim_unavailable": "This Profile grant is unavailable or revoked.",
    "session_unavailable": "That conversation reference is no longer available for this Profile.",
    "unauthorized": "Home no longer accepts this device credential; check revocation or pair again.",
    "forbidden": "Home has not granted this operation to this device.",
    "service_unavailable": "Home's service is unavailable; try again later.",
    "invalid_response": "Home returned an invalid response.",
    "transport": "Home could not be reached securely within the time limit.",
    "secure_store": "A working macOS Keychain or Linux Secret Service is required; no insecure fallback is used.",
    "not_paired": "This Home is not paired. Run hermes-relay pair.",
    "storage_after_consume": "Home consumed this pairing, but saving its credential failed. Pair again and revoke the unused device on Home's page.",
    "grant_selection": "Select an active, available Profile with --home-grant or /home select <label>.",
    "pairing_exists": "This Home is already paired; unpair locally before enrolling a replacement.",
    "lock_busy": "Another window is updating this Home pairing; try again shortly.",
}

class HomeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code if code in _MESSAGES else "service_unavailable"
        super().__init__(_MESSAGES[self.code])


def canonical_home(value: str) -> str:
    """Accept an HTTPS origin or the existing secure bridge route."""
    try:
        raw = str(value).strip()
        p = urlsplit(raw)
        if (p.scheme not in {"https", "wss"} or not p.hostname or p.username
                or p.password or p.query or p.fragment or "@" in p.netloc
                or any(ord(c) < 33 for c in raw)
                or p.path.rstrip("/") not in {"", "/api/v1/bridge/ws"}):
            raise ValueError
        host = p.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if ":" in host:
            host = f"[{host}]"
        port = p.port
        return f"https://{host}" + (f":{port}" if port and port != 443 else "")
    except (ValueError, UnicodeError):
        raise ValueError("Home must be an HTTPS address without credentials, query data, or an unrelated path") from None


def bridge_url(home: str) -> str:
    return canonical_home(home).replace("https://", "wss://", 1) + "/api/v1/bridge/ws"


def _string(value: Any, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise HomeError("invalid_response")
    return value


def _timestamp(value: Any) -> float:
    if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
        raise HomeError("invalid_response")
    return float(value)


def _session_timestamp(value: Any) -> float:
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise HomeError("invalid_response")
    return float(value)


@dataclass(frozen=True)
class Grant:
    grant_id: str
    label: str
    status: str
    available: bool

    @property
    def usable(self) -> bool:
        return self.status == "active" and self.available


def parse_grants(value: Any) -> list[Grant]:
    if not isinstance(value, list) or len(value) > 1000:
        raise HomeError("invalid_response")
    grants = []
    for row in value:
        if not isinstance(row, dict) or type(row.get("available")) is not bool:
            raise HomeError("invalid_response")
        grants.append(Grant(_string(row.get("grant_id"), 128), _string(row.get("label"), 256), _string(row.get("status"), 64), row["available"]))
    if len({g.grant_id for g in grants}) != len(grants):
        raise HomeError("invalid_response")
    return grants


@dataclass(repr=False)
class PairingRecord:
    home: str
    device_id: str
    credential: str = field(repr=False)
    generation: int
    expires_at: float
    renewal_request_id: str | None = None

    @classmethod
    def material(cls, home: str, data: dict[str, Any]) -> PairingRecord:
        if data.get("schema") != 1 or type(data.get("generation")) is not int or data["generation"] < 1:
            raise HomeError("invalid_response")
        return cls(canonical_home(home), _string(data.get("device_id"), 128), _string(data.get("credential"), 8192), data["generation"], _timestamp(data.get("expires_at")))


class SecurePairings:
    """Use only an explicitly trusted native backend, never keyring fallbacks."""
    def __init__(self) -> None:
        try:
            if sys.platform == "darwin":
                from keyring.backends.macOS import Keyring
            elif sys.platform.startswith("linux"):
                from keyring.backends.SecretService import Keyring
            else:
                raise HomeError("secure_store")
            self.backend = Keyring()
            # Native backend selection excludes insecure fallbacks. Availability
            # is established by off-loop reads/preflight, never a DBus priority
            # probe on the application's event loop.
        except Exception:
            raise HomeError("secure_store") from None

    def load(self, home: str) -> PairingRecord | None:
        origin = canonical_home(home)
        try:
            raw = self.backend.get_password(SERVICE, origin)
            if raw is None:
                return None
            if len(raw) > 16384:
                raise ValueError
            data = json.loads(raw)
            record = PairingRecord.material(origin, {**data, "schema": 1})
            if data.get("home") != origin:
                raise ValueError
            pending = data.get("renewal_request_id")
            record.renewal_request_id = _string(pending, 128) if pending is not None else None
            return record
        except Exception:
            raise HomeError("secure_store") from None

    def save(self, record: PairingRecord) -> None:
        try:
            self.backend.set_password(SERVICE, record.home, json.dumps(asdict(record)))
        except Exception:
            raise HomeError("secure_store") from None

    def delete(self, home: str) -> None:
        from keyring.errors import PasswordDeleteError
        origin = canonical_home(home)
        try:
            self.backend.delete_password(SERVICE, origin)
        except PasswordDeleteError:
            # macOS also wraps deletion failures in this type. Confirm absence
            # using the raw value, without deserializing a possibly broken record.
            try:
                if self.backend.get_password(SERVICE, origin) is None:
                    return
            except Exception:
                pass
            raise HomeError("secure_store") from None
        except Exception:
            raise HomeError("secure_store") from None

    @asynccontextmanager
    async def locked(self, home: str):
        # A nonsecret lock file serializes renewals across windows/processes.
        import fcntl
        directory = Path("~/.hermes-relay-tui/home-locks").expanduser()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        name = hashlib.sha256(canonical_home(home).encode()).hexdigest()
        fd = os.open(directory / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise HomeError("lock_busy")
                    await asyncio.sleep(0.1)
            yield
        finally:
            os.close(fd)


async def _secure_read(function, *args):
    """Allow cleanup to outlive a stalled read without blocking executor exit."""
    loop = asyncio.get_running_loop()
    result = loop.create_future()

    def deliver(value, error):
        if not result.done():
            if error is None:
                result.set_result(value)
            else:
                result.set_exception(error)

    def read():
        try:
            value, error = function(*args), None
        except Exception as exc:
            value, error = None, exc
        try:
            loop.call_soon_threadsafe(deliver, value, error)
        except RuntimeError:
            pass  # The cancelled caller's loop has already shut down.

    threading.Thread(target=read, daemon=True, name="Home secure-store read").start()
    return await result


async def secure_call(function, *args):
    """A cancelled caller must not release the renewal lock before a save ends."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


class HomeClient:
    def __init__(self, home: str, *, store: SecurePairings | None = None) -> None:
        self.home = canonical_home(home)
        self.store = store if store is not None else SecurePairings()

    async def request(self, method: str, path: str, body: dict[str, Any] | None = None, *, record: PairingRecord | None = None) -> dict[str, Any]:
        if record is not None and record.home != self.home:
            raise HomeError("not_paired")
        try:
            async with asyncio.timeout(HTTP_TIMEOUT + 1):
                return await asyncio.to_thread(self._request, method, path, body, record)
        except TimeoutError:
            raise HomeError("transport") from None

    def _request(self, method: str, path: str, body: dict[str, Any] | None, record: PairingRecord | None) -> dict[str, Any]:
        p = urlsplit(self.home)
        conn = http.client.HTTPSConnection(p.hostname, p.port, timeout=HTTP_TIMEOUT)
        deadline = time.monotonic() + HTTP_TIMEOUT
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if record is not None:
            headers["Authorization"] = "Device " + record.credential
        def abort_socket():
            sock = conn.sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        timer = threading.Timer(HTTP_TIMEOUT, abort_socket)
        timer.daemon = True
        timer.start()
        try:
            conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=headers)
            response = conn.getresponse()
            # http.client does not follow redirects, including credential-bearing ones.
            if 300 <= response.status < 400:
                raise HomeError("transport")
            chunks = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HomeError("transport")
                if conn.sock is not None:
                    conn.sock.settimeout(remaining)
                chunk = response.read1(min(8192, MAX_RESPONSE + 1 - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
                if len(chunks) > MAX_RESPONSE:
                    raise HomeError("invalid_response")
            payload = json.loads(chunks)
            if not isinstance(payload, dict) or type(payload.get("schema")) is not int or payload["schema"] != 1:
                raise HomeError("invalid_response")
            if not 200 <= response.status < 300:
                error = payload.get("error")
                raise HomeError(error.get("code", "service_unavailable") if isinstance(error, dict) else "service_unavailable")
            return payload
        except HomeError:
            raise
        except (ValueError, UnicodeError):
            raise HomeError("invalid_response") from None
        except Exception:
            raise HomeError("transport") from None
        finally:
            timer.cancel()
            conn.close()

    async def credential(self, *, renew: bool = True) -> PairingRecord:
        async with self.store.locked(self.home):
            record = await _secure_read(self.store.load, self.home)
            if record is None:
                raise HomeError("not_paired")
            if renew and (record.renewal_request_id or record.expires_at - time.time() <= RENEW_WINDOW):
                if record.renewal_request_id is None:
                    record.renewal_request_id = uuid.uuid4().hex
                    await secure_call(self.store.save, record)
                data = await self.request("POST", f"/api/v1/devices/{quote(record.device_id, safe='')}/credentials/renew", {"schema": 1, "request_id": record.renewal_request_id, "generation": record.generation}, record=record)
                renewed = PairingRecord.material(self.home, data)
                if renewed.device_id != record.device_id or renewed.generation != record.generation + 1 or renewed.expires_at <= time.time():
                    raise HomeError("invalid_response")
                await secure_call(self.store.save, renewed)
                record = renewed
            return record

    async def configuration(self, record: PairingRecord) -> tuple[int, list[Grant]]:
        data = await self.request("GET", f"/api/v1/devices/{quote(record.device_id, safe='')}/configuration", record=record)
        snapshot = data.get("snapshot")
        if not isinstance(snapshot, dict) or type(snapshot.get("revision")) is not int or snapshot["revision"] < 0:
            raise HomeError("invalid_response")
        return snapshot["revision"], parse_grants(snapshot.get("client_grants"))

    async def claim(self, record: PairingRecord, revision: int, grant: Grant, mode: str, session_ref: str | None = None, *, claim_id: str) -> dict[str, Any]:
        if not grant.usable:
            raise HomeError("grant_pending" if grant.status == "pending_owner" else "profile_unavailable")
        if mode not in {"new", "most_recent", "resume"}:
            raise ValueError("Unknown Home session mode")
        session = {"mode": mode}
        if mode == "resume":
            session["session_ref"] = _string(session_ref, 128)
        data = await self.request("POST", "/api/v1/client-claims", {"schema": 1, "claim_id": claim_id, "device_id": record.device_id, "configuration_revision": revision, "grant_id": grant.grant_id, "session": session}, record=record)
        if data.get("claim_id") != claim_id or data.get("decision") != "granted" or data.get("configuration_revision") != revision:
            raise HomeError("invalid_response")
        _string(data.get("conversation_handle"), 8192)
        selection = data.get("session")
        if not isinstance(selection, dict) or selection.get("mode") not in {"new", "resumed"}:
            raise HomeError("invalid_response")
        if selection["mode"] == "resumed":
            _string(selection.get("session_ref"), 128)
        return data

    async def sessions(self, record: PairingRecord, grant: Grant, limit: int = 50) -> list[dict[str, Any]]:
        data = await self.request("POST", "/api/v1/client-sessions/list", {"schema": 1, "grant_id": grant.grant_id, "limit": max(1, min(limit, 50))}, record=record)
        rows = data.get("sessions")
        if not isinstance(rows, list) or len(rows) > 50:
            raise HomeError("invalid_response")
        result = []
        for row in rows:
            if not isinstance(row, dict) or type(row.get("active")) is not bool or type(row.get("message_count")) is not int or row["message_count"] < 0:
                raise HomeError("invalid_response")
            result.append({"session_ref": _string(row.get("session_ref"), 128), "title": _string(row.get("title") or "Untitled", 1024), "started_at": _session_timestamp(row.get("started_at")), "message_count": row["message_count"], "active": row["active"]})
        return result

    async def owners(self, kind: str) -> list[dict[str, Any]]:
        if kind not in {"pending", "holders"}:
            raise ValueError("Unknown grant listing")
        record = await self.credential(renew=False)
        data = await self.request("GET", f"/api/v1/profile-grants/{kind}", record=record)
        rows = data.get(kind)
        if not isinstance(rows, list) or len(rows) > 1000:
            raise HomeError("invalid_response")
        return [{key: _string(row.get(key), 256) for key in ("grant_id", "device_label", "device_type", "profile_label", "status")} for row in rows if isinstance(row, dict)]

    async def decide(self, grant_id: str, *, approve: bool) -> None:
        record = await self.credential(renew=False)
        action = "approve" if approve else "reject"
        await self.request("POST", f"/api/v1/profile-grants/{quote(_string(grant_id, 128), safe='')}/{action}", {"schema": 1}, record=record)
