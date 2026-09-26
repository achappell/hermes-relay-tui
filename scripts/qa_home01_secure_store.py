"""Opt-in native-store acceptance probe using disposable .invalid origins only.

Run from the repository root with its Python environment. On Linux, run inside
an isolated, unlocked Secret Service session. No real pairing is read or changed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from home_client import HomeError, PairingRecord, SecurePairings, SERVICE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-unavailable", action="store_true")
    args = parser.parse_args()
    prefix = uuid.uuid4().hex
    origins = [f"https://home01-{prefix}-{i}.invalid" for i in range(2)]
    store = SecurePairings()
    if args.expect_unavailable:
        try:
            store.load(origins[0])
        except HomeError as exc:
            assert exc.code == "secure_store"
        else:
            raise AssertionError("Unavailable native store did not fail closed")
        print(json.dumps({"unavailable_store": "pass", "fallback": False}))
        return
    try:
        records = [PairingRecord(home, f"synthetic-{i}", uuid.uuid4().hex,
                                 1, time.time() + 3600)
                   for i, home in enumerate(origins)]
        for record in records:
            assert store.load(record.home) is None
            store.save(record)
        assert store.load(origins[0]).credential == records[0].credential
        assert store.load(origins[1]).credential == records[1].credential
        assert store.load(origins[0].upper() + "/").device_id == "synthetic-0"
        store.delete(origins[0])
        assert store.load(origins[0]) is None
        assert store.load(origins[1]).credential == records[1].credential
        store.backend.set_password(SERVICE, origins[0], "malformed synthetic record")
        try:
            store.load(origins[0])
        except HomeError as exc:
            assert exc.code == "secure_store"
        else:
            raise AssertionError("Malformed record was accepted")
        store.delete(origins[0])
        store.delete(origins[0])
        print(json.dumps({"backend": type(store.backend).__module__,
                          "roundtrip": "pass", "canonical_origin": "pass",
                          "two_home_isolation": "pass", "local_delete": "pass",
                          "corrupt_delete": "pass", "absent_delete": "pass"}))
    finally:
        for home in origins:
            store.delete(home)
        assert all(store.load(home) is None for home in origins)


if __name__ == "__main__":
    main()
