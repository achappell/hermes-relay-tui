"""POSIX service-private Home pairing; no browser or environment credential copy."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
import time

from home_client import HomeError, PairingRecord, canonical_home, _string


class PrivatePairings:
    """One appliance identity in a service-owned 0700 directory / 0600 file.

    Atomic replacement plus file and directory fsync preserves the pending renewal
    ID across process loss. A separate, never-replaced inode serializes writers.
    The process lease prevents a second appliance from sweeping live tab claims.
    """
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().absolute()
        self._lease: int | None = None

    def _directory(self) -> None:
        parent = self.path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise HomeError("private_store")
        # No symlink ancestors or repository-local credential material.
        if parent.resolve() != parent or any((p / ".git").exists() for p in (parent, *parent.parents)):
            raise HomeError("private_store")

    def _open(self, path: Path, flags: int) -> int:
        self._directory()
        fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            os.close(fd)
            raise HomeError("private_store")
        return fd

    def acquire_lease(self) -> None:
        if self._lease is not None:
            return
        fd = self._open(self.path.with_suffix(".service-lock"), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise HomeError("lock_busy") from None
        self._lease = fd

    def release_lease(self) -> None:
        if self._lease is not None:
            os.close(self._lease)
            self._lease = None

    def preflight(self, home: str) -> None:
        self._directory()
        # Exercise the same durable write path before consuming an enrollment.
        self._replace(self.path.with_suffix(".probe"), b"probe")
        self.path.with_suffix(".probe").unlink()

    def load(self, home: str) -> PairingRecord | None:
        try:
            fd = self._open(self.path, os.O_RDONLY)
            with os.fdopen(fd, "r", encoding="utf-8") as source:
                data = json.loads(source.read(16385))
            if data.get("home") != canonical_home(home):
                raise ValueError
            record = PairingRecord.material(home, {**data, "schema": 1})
            pending = data.get("renewal_request_id")
            record.renewal_request_id = _string(pending, 128) if pending is not None else None
            return record
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError, AttributeError, HomeError):
            raise HomeError("private_store") from None

    def _replace(self, destination: Path, payload: bytes) -> None:
        self._directory()
        fd, temporary = tempfile.mkstemp(prefix=".home-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as target:
                target.write(payload)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, destination)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save(self, record: PairingRecord) -> None:
        try:
            self._replace(self.path, json.dumps(asdict(record)).encode())
        except (OSError, ValueError):
            raise HomeError("private_store") from None

    @asynccontextmanager
    async def locked(self, home: str):
        fd = self._open(self.path.with_suffix(".renewal-lock"), os.O_CREAT | os.O_RDWR)
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
