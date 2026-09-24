"""In-memory native-store stand-in; never constructs a real keyring backend."""
from contextlib import asynccontextmanager
import asyncio
import json

from keyring.errors import PasswordDeleteError

from home_client import SERVICE, SecurePairings

HOME = "https://home.example"
NOW = 2_000_000_000.0


class MemoryBackend:
    def __init__(self):
        self.values = {}
        self.fail_probe = False
        self.fail_generation = None
        self.fail_delete = False
        self.saves = []

    def get_password(self, service, key):
        return self.values.get((service, key))

    def set_password(self, service, key, value):
        if service.endswith(".probe") and self.fail_probe:
            raise RuntimeError("synthetic store failure")
        if service == SERVICE:
            record = json.loads(value)
            if record["generation"] == self.fail_generation:
                self.fail_generation = None
                raise RuntimeError("synthetic interrupted write")
            self.saves.append(record)
        self.values[service, key] = value

    def delete_password(self, service, key):
        if self.fail_delete or (service, key) not in self.values:
            raise PasswordDeleteError("synthetic delete failure or absence")
        del self.values[service, key]


class MemoryPairings(SecurePairings):
    def __init__(self):
        self.backend = MemoryBackend()
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def locked(self, home):
        async with self.lock:
            yield


def material(*, generation=1, grants=False):
    value = {
        "schema": 1,
        "device_id": "synthetic-device",
        "credential": f"synthetic-private-credential-{generation}",
        "generation": generation,
        "expires_at": NOW + 60 * 24 * 3600,
    }
    if grants:
        value["client_grants"] = [
            {"grant_id": "grant-approved", "label": "Amanda", "status": "active", "available": True},
            {"grant_id": "grant-pending", "label": "Amanda", "status": "pending_owner", "available": True},
        ]
    return value
