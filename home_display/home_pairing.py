"""Interactive, server-only browser appliance enrollment through Home's existing API."""
from __future__ import annotations

import argparse
import asyncio
import getpass
from pathlib import Path

from home_client import HomeError
from home_pairing_cli import _hidden_input, pair, parse_pairing_input
from .home_store import PrivatePairings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--label", default="Household browser")
    args = parser.parse_args()
    try:
        home, code = parse_pairing_input(args.home, _hidden_input(getpass.getpass, "Home enrollment code (hidden): "))
        store = PrivatePairings(args.credential_file)
        store.acquire_lease()
        try:
            grants = asyncio.run(pair(home, code, label=args.label, store=store, browser=True))
        finally:
            store.release_lease()
        print(f"Appliance paired. {sum(g.usable for g in grants)} Profiles available. Manage later grants through Home administration; no re-pairing required.")
        return 0
    except (HomeError, ValueError, OSError):
        print("Appliance pairing failed. Check private storage and Home enrollment; if consumption was uncertain, revoke the unused device through Home administration before trying again.")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Pairing stopped; check Home for an unused device before enrolling again.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
