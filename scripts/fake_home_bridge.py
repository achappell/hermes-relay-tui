#!/usr/bin/env python3
"""A stand-in Home bridge server, for live end-to-end testing of typed
Choose/Explore prompts without a real Hermes/Home deployment.

home_display.appliance's `--browser-transport home` path talks to
`/api/v1/bridge/ws` (`puck_bridge.home_session.HomeBrowserSession`), a
JSON-RPC-over-WebSocket protocol that is unrelated to the legacy
voice-session protocol `fake_relay.py` speaks. This script speaks enough of
that bridge protocol for one full round trip per turn:

    conversation.open -> ready
    prompt.submit     -> submitted, then a typed-choice `prompt_request` event
    prompt.respond    -> accepted, then `prompt_resolved` + a terminal event

That is enough to drive a real renderer (the native simulator, the web
kiosk, or physical hardware) against `home_display/server.py` and watch a
genuine Choose/Explore tap travel all the way to a bridge socket and back.

The client (`require_home_bridge_url`) refuses anything but `wss://`, so
this always serves TLS. Reuse the local CA recipe from
`docs/testing/home-09-appliance-loop.md`, or point `--tls-cert`/`--tls-key`
at any certificate whose SAN covers the host you connect to.

    python scripts/fake_home_bridge.py \\
        --tls-cert ~/.hermes-relay-tui/certs/display-cert.pem \\
        --tls-key ~/.hermes-relay-tui/certs/display-key.pem

Point the appliance at it (the credential file just needs to contain the
same string as --device-credential):

    printf 'stub-secret' > /tmp/home-device-credential
    venv/bin/python -m home_display.appliance --browser-transport home \\
        --home-bridge-url wss://127.0.0.1:8798/api/v1/bridge/ws \\
        --home-conversation-handle stub-handle \\
        --home-device-credential-file /tmp/home-device-credential

Then open the native simulator or web kiosk against the display server's
printed loopback URL, say something to submit a turn (or use the TUI's text
entry), and tap Choose or Explore when the prompt renders.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import websockets  # noqa: E402

HOME_BRIDGE_PATH = "/api/v1/bridge/ws"
HOME_BRIDGE_SCHEMA = 1

DEFAULT_OPTIONS = [
    {"id": "inspect", "label": "Inspect the device"},
    {"id": "compare", "label": "Compare the readings"},
]


class FakeHomeBridge:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.turns = 0

    async def handle(self, websocket) -> None:
        peer = getattr(websocket, "remote_address", ("?",))[0]
        print(f"[home-bridge] client connected from {peer}")
        try:
            async for frame in websocket:
                if isinstance(frame, bytes):
                    continue
                request = json.loads(frame)
                method = request.get("method")
                request_id = request.get("id")
                params = request.get("params") or {}
                if method in ("conversation.open", "conversation.reconnect"):
                    await self._reply_ready(websocket, request_id, params)
                elif method == "prompt.submit":
                    await self._handle_prompt_submit(websocket, request_id, params)
                elif method == "prompt.respond":
                    await self._handle_prompt_respond(websocket, request_id, params)
                elif method == "bridge.ping":
                    await self._reply(
                        websocket,
                        request_id,
                        {"schema": HOME_BRIDGE_SCHEMA, "status": "ready"},
                    )
                elif method == "session.interrupt":
                    await self._reply(
                        websocket,
                        request_id,
                        {"schema": HOME_BRIDGE_SCHEMA, "accepted": False},
                    )
                elif request_id is not None:
                    print(f"[home-bridge] unhandled method {method!r}, rejecting")
                    await self._reply_error(websocket, request_id, "unsupported_method")
        except websockets.ConnectionClosed:
            print("[home-bridge] client disconnected")

    async def _reply(self, websocket, request_id, result) -> None:
        await websocket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "schema": HOME_BRIDGE_SCHEMA,
                    "id": request_id,
                    "result": result,
                }
            )
        )

    async def _reply_error(self, websocket, request_id, code: str) -> None:
        await websocket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "schema": HOME_BRIDGE_SCHEMA,
                    "id": request_id,
                    "error": {"code": code, "delivery": "known"},
                }
            )
        )

    async def _reply_ready(self, websocket, request_id, params) -> None:
        handle = params.get("conversation_handle")
        print(f"[home-bridge] conversation.open handle={handle!r}")
        await self._reply(
            websocket,
            request_id,
            {
                "schema": HOME_BRIDGE_SCHEMA,
                "status": "ready",
                "conversation_handle": handle,
                "route": {"class": "home", "id": "stub-route"},
                "capabilities": {
                    "commands": ["session.interrupt"],
                    "timing": "absent",
                },
            },
        )

    async def _handle_prompt_submit(self, websocket, request_id, params) -> None:
        self.turns += 1
        handle = params.get("conversation_handle")
        turn_id = f"stub-turn-{self.turns}"
        print(f"[home-bridge] prompt.submit text={params.get('text')!r} turn_id={turn_id}")
        await self._reply(
            websocket,
            request_id,
            {
                "schema": HOME_BRIDGE_SCHEMA,
                "conversation_handle": handle,
                "status": "submitted",
                "turn_id": turn_id,
            },
        )
        self._pending = {
            "conversation_handle": handle,
            "turn_id": turn_id,
            "correlation_id": f"stub-correlation-{self.turns}",
            "prompt_id": f"stub-prompt-{self.turns}",
            "object_id": f"stub-object-{self.turns}",
            "freshness": f"stub-freshness-{self.turns}-{uuid.uuid4().hex[:8]}",
        }
        asyncio.create_task(self._send_prompt(websocket))

    async def _send_prompt(self, websocket) -> None:
        await asyncio.sleep(self.args.think)
        pending = self._pending
        event_params = {
            "schema": HOME_BRIDGE_SCHEMA,
            "conversation_handle": pending["conversation_handle"],
            "turn_id": pending["turn_id"],
            "correlation_id": pending["correlation_id"],
            "event": {
                "type": "prompt_request",
                "payload": {
                    "prompt_id": pending["prompt_id"],
                    "prompt_kind": "choice",
                    "text": self.args.text,
                    "options": DEFAULT_OPTIONS,
                    "choice": {
                        "object_id": pending["object_id"],
                        "operations": ["choose", "explore"],
                        "freshness": pending["freshness"],
                    },
                },
            },
        }
        await websocket.send(
            json.dumps({"jsonrpc": "2.0", "schema": HOME_BRIDGE_SCHEMA, "method": "event", "params": event_params})
        )
        print(
            "[home-bridge] sent typed choice prompt "
            f"object_id={pending['object_id']} freshness={pending['freshness']}"
        )

    async def _handle_prompt_respond(self, websocket, request_id, params) -> None:
        pending = getattr(self, "_pending", None)
        response = params.get("response") or {}
        print(
            "[home-bridge] prompt.respond "
            f"operation={response.get('operation')!r} "
            f"option_id={response.get('option_id')!r} "
            f"object_id={response.get('object_id')!r} "
            f"freshness={response.get('freshness')!r}"
        )
        if (
            self.args.reject_once
            and pending is not None
            and not getattr(self, "_rejected_once", False)
        ):
            self._rejected_once = True
            print("[home-bridge] rejecting the first response, as requested")
            await self._reply(
                websocket,
                request_id,
                {"schema": HOME_BRIDGE_SCHEMA, "accepted": False, "status": "rejected"},
            )
            return
        await self._reply(
            websocket,
            request_id,
            {"schema": HOME_BRIDGE_SCHEMA, "accepted": True, "status": "accepted"},
        )
        if pending is None:
            return
        resolved_params = {
            "schema": HOME_BRIDGE_SCHEMA,
            "conversation_handle": pending["conversation_handle"],
            "turn_id": pending["turn_id"],
            "correlation_id": pending["correlation_id"],
            "event": {
                "type": "prompt_resolved",
                "payload": {
                    "prompt_id": pending["prompt_id"],
                    "prompt_kind": "choice",
                    "status": "accepted",
                },
            },
        }
        await websocket.send(
            json.dumps({"jsonrpc": "2.0", "schema": HOME_BRIDGE_SCHEMA, "method": "event", "params": resolved_params})
        )
        terminal_params = {
            "schema": HOME_BRIDGE_SCHEMA,
            "conversation_handle": pending["conversation_handle"],
            "turn_id": pending["turn_id"],
            "correlation_id": pending["correlation_id"],
            "event": {"type": "turn.complete", "payload": {}},
        }
        await websocket.send(
            json.dumps({"jsonrpc": "2.0", "schema": HOME_BRIDGE_SCHEMA, "method": "event", "params": terminal_params})
        )
        print("[home-bridge] prompt resolved; turn complete")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8798)
    parser.add_argument("--tls-cert", required=True, type=Path)
    parser.add_argument("--tls-key", required=True, type=Path)
    parser.add_argument(
        "--text",
        default="Which inspection step should I explain or take?",
        help="body text of the typed choice prompt",
    )
    parser.add_argument(
        "--think",
        type=float,
        default=0.6,
        help="seconds between prompt.submit and the choice prompt appearing",
    )
    parser.add_argument(
        "--reject-once",
        action="store_true",
        help="reject the first prompt.respond per run, then accept the retry",
    )
    return parser


async def serve(args: argparse.Namespace) -> None:
    bridge = FakeHomeBridge(args)
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(str(args.tls_cert), str(args.tls_key))
    async with websockets.serve(
        bridge.handle, args.host, args.port, ssl=ssl_context
    ):
        print(
            f"[home-bridge] listening on wss://{args.host}:{args.port}{HOME_BRIDGE_PATH}"
        )
        print("[home-bridge] point the appliance at it with --home-bridge-url")
        await asyncio.Future()


def main() -> int:
    args = build_parser().parse_args()
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        print("\n[home-bridge] stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
