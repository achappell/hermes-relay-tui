"""Explicit live quit probe using one named existing QA conversation; sends no prompt.

The saved Home pairing is used normally. The early-quit case holds the claim
response in memory after Home accepts it, quits the real Textual app, then
explicitly retires that known claim. No production credential is modified.
"""
import argparse
import asyncio
from copy import copy
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from app import HermesStreamingApp
from home_client import HomeClient, bridge_url
from puck_bridge.home_session import HomePuckSession
from puck_bridge.home_textual_session import HomeTextualSession


async def run(options):
    argv = ["--profile", options.profile, "--home-grant", options.grant, "--no-play", "--no-earcons"]
    args = config.build_arg_parser(argv, resolve_relay_profile_tokens=False).parse_args(argv)
    assert args.transport == "home"
    client = HomeClient(args.url)
    record = await client.credential(renew=False)
    _, grants = await client.configuration(record)
    grant = next(g for g in grants if g.label == options.grant and g.usable)
    rows = await client.sessions(record, grant)
    row = next((r for r in rows if r["title"] == options.qa_title), None)
    if row is None or row["active"]:
        raise RuntimeError("The named QA conversation is absent or busy")
    args.home_resume = row["session_ref"]
    args.home_continue = False
    releases = []

    class ObservedSession(HomeTextualSession):
        async def release_claim(self):
            result = await super().release_claim()
            releases.append(result)
            return result

    with tempfile.TemporaryDirectory(prefix="home01-live-quit-") as directory:
        args.history_path = Path(directory) / "history.jsonl"
        session = ObservedSession(copy(args))
        app = HermesStreamingApp(args=copy(args), session_factory=lambda: session)
        async with app.run_test() as pilot:
            async with asyncio.timeout(30):
                while not app._connection_is_ready():
                    await pilot.pause()
                    await asyncio.sleep(0.05)
        assert releases == [True]
        assert app.return_code in (None, 0)
        print("live-ready-quit: claim close confirmed; normal exit; no prompt", flush=True)
        remaining = await client.sessions(record, grant)
        assert any(item["title"] == options.qa_title and not item["active"] for item in remaining)
        print("live-ready-quit: saved QA conversation remains available after close", flush=True)

        claim_ready = asyncio.Event()
        claim = {}
        class HeldClaimClient(HomeClient):
            async def claim(self, *a, **kw):
                result = await super().claim(*a, **kw)
                claim.update(result)
                claim_ready.set()
                await asyncio.Event().wait()

        session = ObservedSession(copy(args))
        session._home_client = HeldClaimClient(args.url)
        app = HermesStreamingApp(args=copy(args), session_factory=lambda: session)
        try:
            async with app.run_test() as pilot:
                await asyncio.wait_for(claim_ready.wait(), timeout=30)
                assert session._claim_request_uncertain
                app.exit()
            assert releases == [True, False]
            assert app.return_code in (None, 0)
            print("live-early-quit: unconfirmed claim; normal exit; no transcript exception", flush=True)
        finally:
            if claim:
                latest = await client.credential(renew=False)
                cleanup = HomePuckSession(bridge_url(args.url), latest.credential,
                                         claim["conversation_handle"], session_label="TUI QA cleanup")
                try:
                    await cleanup.connect()
                    assert await cleanup.close_claim()
                    print("live-early-quit: test claim explicitly retired", flush=True)
                finally:
                    await cleanup.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--grant", required=True)
    parser.add_argument("--qa-title", required=True)
    options = parser.parse_args()
    asyncio.run(run(options))
