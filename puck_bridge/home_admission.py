"""Pre-capture Home wake claims for a recovered Puck conversation.

The current configured Home handle remains usable until its transport is
retired. This adapter creates a replacement handle only when a trusted,
fresh proximity provider supplies calibrated evidence; with no provider the
replacement path refuses before requesting a claim.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import inspect
import json
import logging
import math
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import unicodedata
from typing import Any, Callable

from .home_session import HomePuckSession

logger = logging.getLogger("hermes_relay_tui.puck_bridge.home_admission")

HOME_WAKE_ADMISSION_TIMEOUT_SECONDS = 10.0
HOME_HTTP_REQUEST_TIMEOUT_SECONDS = 3.0
HOME_EVIDENCE_TIMEOUT_SECONDS = 1.0
HOME_CLAIM_CLOSE_TIMEOUT_SECONDS = 3.0
HOME_MAX_RESPONSE_BYTES = 16 * 1024
HOME_MAX_EVIDENCE_AGE_MS = 1000


@dataclass(frozen=True)
class HomeClaimRecoveryRecord:
    """The last claim must not be reopened as active after process restart."""

    status: str
    conversation_handle: str
    wake_mapping_id: str


class HomeClaimRecoveryState:
    """Private durable marker for the one Home claim owned by this Puck."""

    def __init__(self, device_id: str, path: str | os.PathLike[str] | None = None):
        identity = str(device_id).strip()
        if not identity:
            raise ValueError("Home device id is required for claim recovery state")
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        self.path = Path(path).expanduser() if path is not None else (
            Path.home() / ".hermes-relay-tui" / "home-claim-state" / f"{digest}.json"
        )
        self._device_digest = digest
        self._lock = threading.Lock()

    def load(self) -> HomeClaimRecoveryRecord | None:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return None
            if (
                not isinstance(payload, dict)
                or type(payload.get("schema")) is not int
                or payload.get("schema") != 1
                or payload.get("device_sha256") != self._device_digest
                or payload.get("status") not in {"active", "retired", "unconfirmed"}
                or not isinstance(payload.get("conversation_handle"), str)
                or not payload["conversation_handle"].strip()
                or not isinstance(payload.get("wake_mapping_id"), str)
            ):
                raise ValueError("Home claim recovery state is invalid")
            return HomeClaimRecoveryRecord(
                status=payload["status"],
                conversation_handle=payload["conversation_handle"],
                wake_mapping_id=payload["wake_mapping_id"],
            )

    def record_active(self, conversation_handle: str, wake_mapping_id: str) -> None:
        self._write("active", conversation_handle, wake_mapping_id)

    def record_retired(
        self, conversation_handle: str, wake_mapping_id: str, *, confirmed: bool
    ) -> None:
        self._write(
            "retired" if confirmed else "unconfirmed",
            conversation_handle,
            wake_mapping_id,
        )

    def _write(self, status: str, conversation_handle: str, wake_mapping_id: str) -> None:
        handle = str(conversation_handle).strip()
        mapping_id = str(wake_mapping_id).strip()
        if not handle:
            raise ValueError("Home conversation handle is required")
        payload = {
            "schema": 1,
            "device_sha256": self._device_digest,
            "status": status,
            "conversation_handle": handle,
            "wake_mapping_id": mapping_id,
        }
        encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.path.parent, 0o700)
            temporary = self.path.with_name(
                f".{self.path.name}.{uuid.uuid4().hex}.tmp"
            )
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                os.chmod(self.path, 0o600)
                directory_fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass


@dataclass(frozen=True)
class CalibratedProximityEvidence:
    """Fresh provider output; raw provenance stays local to this process."""

    value: float
    calibration_id: str
    observed_at_ms: int


@dataclass(frozen=True)
class HomeAdmissionResult:
    status: str
    session: HomePuckSession | None = None
    reason: str = "unavailable"


class HomeClaimHTTPError(Exception):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"Home HTTP request failed ({status})")


class HomeClaimTransportError(Exception):
    pass


def is_home_identity_rejection(error: BaseException) -> bool:
    status = str(getattr(error, "status", "")).strip().lower()
    code = str(getattr(error, "code", "")).strip().lower()
    return status in {"unauthorized", "forbidden", "rejected"} or code in {
        "unauthorized",
        "forbidden",
        "credential_revoked",
        "device_revoked",
    }


class HomePuckSessionFactory:
    """Resolve one authorized mapping, make one claim, then open its handle."""

    def __init__(
        self,
        bridge_url: str,
        device_credential: str,
        device_id: str,
        *,
        evidence_provider: Callable[[str], CalibratedProximityEvidence] | None = None,
        api_base_url: str | None = None,
        connect_factory: Any | None = None,
        request_json: Callable[..., dict[str, Any]] | None = None,
        recovery_state: HomeClaimRecoveryState | None = None,
    ) -> None:
        self.bridge_url = bridge_url
        self.device_credential = str(device_credential).strip()
        self.device_id = str(device_id).strip()
        self.evidence_provider = evidence_provider
        self.api_base_url = api_base_url or _api_base_from_bridge(bridge_url)
        self.connect_factory = connect_factory
        self._request_json = request_json or _request_json
        self.recovery_state = recovery_state

    async def current_mapping_id(
        self, wake_phrase: str, current_mapping_id: str = ""
    ) -> str | None:
        """Confirm this phrase still names the mapping bound to the live claim."""
        if not self.device_id or not self.device_credential:
            return None
        try:
            configuration = await self._request(
                "GET",
                self._device_configuration_url(),
                timeout=HOME_HTTP_REQUEST_TIMEOUT_SECONDS,
            )
            mapping = _matching_mapping(configuration, wake_phrase)
            mappings = configuration["snapshot"]["wake_mappings"]
            valid_mappings = [
                item for item in mappings
                if isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and item["id"].strip()
                and isinstance(item.get("phrase"), str)
                and item["phrase"].strip()
            ]
            if mapping is None:
                return None
            expected = str(current_mapping_id).strip()
            if expected:
                return mapping["id"] if mapping["id"] == expected else None
            # A configured initial handle has no claim metadata available
            # locally. Infer its binding only when Home exposes one mapping.
            return mapping["id"] if len(valid_mappings) == 1 else None
        except HomeClaimHTTPError as exc:
            if exc.status in {401, 403}:
                raise
            logger.warning("Home wake mapping validation failed (%s)", type(exc).__name__)
            return None
        except Exception as exc:
            logger.warning("Home wake mapping validation failed (%s)", type(exc).__name__)
            return None

    async def admit_wake(
        self,
        wake_phrase: str,
        *,
        previous_handle: str = "",
    ) -> HomeAdmissionResult:
        """Admit a fresh wake only after its new Home session is verified."""
        if self.evidence_provider is None:
            return HomeAdmissionResult("denied", reason="calibration_unavailable")
        if not self.device_id or not self.device_credential:
            return HomeAdmissionResult("denied", reason="device_configuration_missing")

        loop = asyncio.get_running_loop()
        deadline = loop.time() + HOME_WAKE_ADMISSION_TIMEOUT_SECONDS
        granted_session: HomePuckSession | None = None

        def remaining() -> float:
            value = deadline - loop.time()
            if value <= 0:
                raise TimeoutError
            return value

        try:
            async with asyncio.timeout(HOME_WAKE_ADMISSION_TIMEOUT_SECONDS):
                evidence = await self._fresh_evidence(wake_phrase)
                if not _valid_evidence(evidence, now_ms=int(time.time() * 1000)):
                    return HomeAdmissionResult("denied", reason="invalid_proximity_evidence")

                configuration = await self._request(
                    "GET",
                    self._device_configuration_url(),
                    timeout=min(HOME_HTTP_REQUEST_TIMEOUT_SECONDS, remaining()),
                )
                mapping = _matching_mapping(configuration, wake_phrase)
                if mapping is None:
                    return HomeAdmissionResult("denied", reason="wake_mapping_unavailable")
                revision = configuration["snapshot"]["revision"]
                claim_id = f"claim-{uuid.uuid4().hex}"
                claim = {
                    "schema": 1,
                    "claim_id": claim_id,
                    "device_id": self.device_id,
                    "wake_mapping_id": mapping["id"],
                    "configuration_revision": revision,
                    "observation": {
                        "detector": "device-local",
                        "observed_at_ms": evidence.observed_at_ms,
                    },
                    "acoustic_evidence": {
                        "kind": "opaque-v1",
                        "value": evidence.value,
                    },
                    "availability": "ready",
                }
                result = await self._request(
                    "POST",
                    f"{self.api_base_url}/wake-claims",
                    payload=claim,
                    timeout=min(HOME_HTTP_REQUEST_TIMEOUT_SECONDS, remaining()),
                )
                handle = _validate_grant(result, claim_id, revision)
                if handle is None:
                    return HomeAdmissionResult("denied", reason="claim_denied")
                if handle == previous_handle:
                    return HomeAdmissionResult("denied", reason="claim_handle_reused")

                granted_session = HomePuckSession(
                    self.bridge_url,
                    self.device_credential,
                    handle,
                    connect_factory=self.connect_factory,
                    request_timeout=min(3.0, remaining()),
                    resume_uncertain_turn=False,
                    session_label="Puck",
                    wake_mapping_id=mapping["id"],
                )
                if self.recovery_state is not None:
                    self.recovery_state.record_active(handle, mapping["id"])
                await asyncio.wait_for(granted_session.connect(), timeout=remaining())
                if not granted_session.is_connected():
                    await self._retire_granted_session(granted_session)
                    return HomeAdmissionResult("denied", reason="fresh_session_unverified")
                return HomeAdmissionResult(
                    "admitted", session=granted_session, reason="granted"
                )
        except HomeClaimHTTPError as exc:
            if exc.status in {401, 403}:
                return HomeAdmissionResult("identity_rejected", reason="home_identity_rejected")
            return HomeAdmissionResult("denied", reason="home_service_unavailable")
        except BaseException as exc:
            if granted_session is not None:
                cleanup = asyncio.create_task(
                    self._retire_granted_session(granted_session)
                )
                try:
                    await asyncio.wait_for(
                        asyncio.shield(cleanup),
                        timeout=HOME_CLAIM_CLOSE_TIMEOUT_SECONDS + 0.5,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
            if isinstance(exc, asyncio.CancelledError):
                raise
            if is_home_identity_rejection(exc):
                return HomeAdmissionResult("identity_rejected", reason="home_identity_rejected")
            logger.warning(
                "Home fresh-wake admission failed (%s)",
                type(exc).__name__,
            )
            return HomeAdmissionResult("denied", reason="home_admission_unavailable")

    async def _retire_granted_session(self, session: HomePuckSession) -> bool:
        """Close a granted claim whose replacement socket could not be verified."""
        handle = session.conversation_handle
        mapping_id = session.wake_mapping_id
        if self.recovery_state is not None:
            try:
                self.recovery_state.record_retired(
                    handle, mapping_id, confirmed=False
                )
            except Exception as exc:
                logger.warning(
                    "Unusable Home grant recovery state could not be written (%s)",
                    type(exc).__name__,
                )
                return False
        try:
            confirmed = bool(
                await asyncio.wait_for(
                    session.retire_uncertain_claim(),
                    timeout=HOME_CLAIM_CLOSE_TIMEOUT_SECONDS,
                )
            )
        except Exception as exc:
            logger.warning(
                "Unusable Home grant could not be retired (%s)", type(exc).__name__
            )
            return False
        if self.recovery_state is not None:
            try:
                self.recovery_state.record_retired(
                    handle, mapping_id, confirmed=confirmed
                )
            except Exception as exc:
                logger.warning(
                    "Unusable Home grant retirement state could not be saved (%s)",
                    type(exc).__name__,
                )
                return False
        return confirmed

    async def _fresh_evidence(self, wake_phrase: str) -> CalibratedProximityEvidence | None:
        provider = self.evidence_provider
        if provider is None:
            return None
        if inspect.iscoroutinefunction(provider):
            return await asyncio.wait_for(provider(wake_phrase), HOME_EVIDENCE_TIMEOUT_SECONDS)
        result = await asyncio.wait_for(
            asyncio.to_thread(provider, wake_phrase),
            HOME_EVIDENCE_TIMEOUT_SECONDS,
        )
        if inspect.isawaitable(result):
            return await asyncio.wait_for(result, HOME_EVIDENCE_TIMEOUT_SECONDS)
        return result

    async def _request(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: float,
    ) -> dict[str, Any]:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                self._request_json,
                method,
                url,
                credential=self.device_credential,
                payload=payload,
                timeout=timeout,
            ),
            timeout=timeout,
        )
        if not isinstance(result, dict):
            raise ValueError("Home response is not an object")
        return result

    def _device_configuration_url(self) -> str:
        escaped = urllib.parse.quote(self.device_id, safe="")
        return f"{self.api_base_url}/devices/{escaped}/configuration"


def _api_base_from_bridge(url: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(url)
    scheme = {"wss": "https", "ws": "http"}.get(parsed.scheme)
    if scheme is None or not parsed.netloc:
        raise ValueError("Home bridge URL has no HTTP service origin")
    return urlunsplit((scheme, parsed.netloc, "/api/v1", "", "")).rstrip("/")


def _normalize_phrase(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _matching_mapping(
    configuration: dict[str, Any], wake_phrase: str
) -> dict[str, str] | None:
    if type(configuration.get("schema")) is not int or configuration["schema"] != 1:
        raise ValueError("Home device configuration has an invalid schema")
    snapshot = configuration.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("Home device configuration has no snapshot")
    revision = snapshot.get("revision")
    if type(revision) is not int or revision < 0:
        raise ValueError("Home device configuration has an invalid revision")
    mappings = snapshot.get("wake_mappings")
    if not isinstance(mappings, list):
        raise ValueError("Home device configuration has no wake mappings")
    wanted = _normalize_phrase(wake_phrase)
    matches = [
        mapping
        for mapping in mappings
        if isinstance(mapping, dict)
        and isinstance(mapping.get("id"), str)
        and isinstance(mapping.get("phrase"), str)
        and _normalize_phrase(mapping["phrase"]) == wanted
    ]
    if len(matches) != 1:
        return None
    return {"id": matches[0]["id"], "phrase": matches[0]["phrase"]}


def _valid_evidence(
    evidence: Any,
    *,
    now_ms: int,
) -> bool:
    return bool(
        isinstance(evidence, CalibratedProximityEvidence)
        and isinstance(evidence.value, (int, float))
        and not isinstance(evidence.value, bool)
        and math.isfinite(evidence.value)
        and 0.0 <= evidence.value <= 1.0
        and isinstance(evidence.calibration_id, str)
        and evidence.calibration_id.strip()
        and type(evidence.observed_at_ms) is int
        and 0 <= now_ms - evidence.observed_at_ms <= HOME_MAX_EVIDENCE_AGE_MS
    )


def _validate_grant(
    result: dict[str, Any], claim_id: str, configuration_revision: int
) -> str | None:
    if type(result.get("schema")) is not int or result.get("schema") != 1:
        raise ValueError("Home wake claim result has an invalid schema")
    if result.get("claim_id") != claim_id:
        raise ValueError("Home wake claim result changed claim identity")
    if type(result.get("configuration_revision")) is not int or result.get(
        "configuration_revision"
    ) != configuration_revision:
        raise ValueError("Home wake claim result changed configuration revision")
    if result.get("decision") != "granted":
        if result.get("decision") == "denied":
            return None
        raise ValueError("Home wake claim result has an invalid decision")
    handle = result.get("conversation_handle")
    if not isinstance(handle, str) or not handle.strip():
        raise ValueError("Home granted claim has no conversation handle")
    return handle.strip()


def _request_json(
    method: str,
    url: str,
    *,
    credential: str,
    payload: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Device {credential}",
    }
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(HOME_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise HomeClaimHTTPError(exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HomeClaimTransportError(type(exc).__name__) from None
    if len(raw) > HOME_MAX_RESPONSE_BYTES:
        raise ValueError("Home response exceeded its size limit")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Home response is not an object")
    return value


__all__ = [
    "CalibratedProximityEvidence",
    "HomeAdmissionResult",
    "HomePuckSessionFactory",
    "HomeClaimRecoveryRecord",
    "HomeClaimRecoveryState",
    "is_home_identity_rejection",
]
