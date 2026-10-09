#!/usr/bin/env python3
"""Local-only real Home + appliance smoke; Standard is a controlled protocol fixture.

Install the authoritative Home checkout in the same venv, build the web bundle,
then run this script. --serve retains the temporary UI for browser inspection.
No production data, credentials, hosts, or Tailscale configuration are touched.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import secrets
import signal
import ssl
import sys
import tempfile
import threading
import uuid

from aiohttp import ClientSession, WSMsgType, web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from home_client import HomeClient
from home_display.home_store import PrivatePairings
from home_pairing_cli import pair
from hermes_home.runtime import create_runtime, load_settings


async def listen(app, *, tls=None):
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=tls)
    await site.start()
    return runner, site._server.sockets[0].getsockname()[1]


def certificate(directory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = directory / "local-ca.pem", directory / "local-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key_path.chmod(0o600)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context, cert_path


async def run(serve, appliance_python=None):
    with tempfile.TemporaryDirectory(prefix="home-browser-smoke-") as temporary:
        directory = Path(temporary).resolve()
        directory.chmod(0o700)
        standard_token, admin_token = secrets.token_hex(32), secrets.token_hex(32)
        for name, value in (("admin", admin_token), ("standard", standard_token), ("root", secrets.token_hex(32))):
            (directory / name).write_text(value)
            (directory / name).chmod(0o600)
        tls, cert_path = certificate(directory)
        os.environ["SSL_CERT_FILE"] = str(cert_path)
        prompts, sessions, methods = [], [], []
        standard_sockets = set()
        audio_ready = asyncio.Queue()

        async def standard(request):
            if request.query.get("token") != standard_token:
                raise web.HTTPUnauthorized()
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            if request.path == "/api/audio/speak-stream":
                audio_ready.put_nowait(True)
                started = False
                async for message in ws:
                    if message.type != WSMsgType.TEXT:
                        continue
                    data = json.loads(message.data)
                    if data.get("text"):
                        if not started:
                            await ws.send_json({"type": "start", "sample_rate": 24000, "channels": 1})
                            started = True
                        await ws.send_bytes(b"\x00\x00" * 240)
                    if data.get("done"):
                        await ws.send_json({"type": "end"})
                    if data.get("stop"):
                        break
                return ws
            standard_sockets.add(ws)
            await ws.send_json({"jsonrpc": "2.0", "method": "event", "params": {"type": "gateway.ready", "payload": {}}})
            try:
                async for message in ws:
                    if message.type != WSMsgType.TEXT:
                        continue
                    frame = json.loads(message.data)
                    method, params = frame["method"], frame.get("params", {})
                    methods.append(method)
                    if method == "commands.catalog":
                        result = {"pairs": [["/status", "Show status"]]}
                    elif method == "session.create":
                        identity = uuid.uuid4().hex
                        sessions.append(identity)
                        result = {"session_id": identity, "stored_session_id": "stored-" + identity}
                    elif method == "prompt.submit":
                        prompts.append((params["session_id"], params["text"]))
                        result = {"accepted": True}
                    elif method in {"interrupt", "session.interrupt", "prompt.respond"}:
                        result = {"accepted": True}
                    else:
                        await ws.send_json({"jsonrpc": "2.0", "id": frame["id"], "error": {"code": -32601, "message": "unsupported fixture method"}})
                        continue
                    await ws.send_json({"jsonrpc": "2.0", "id": frame["id"], "result": result})
                    if method == "prompt.submit":
                        # Controlled generation begins after the independently
                        # opened speech sidecar; this is not a mock Home API.
                        await asyncio.wait_for(audio_ready.get(), 5)
                        turn = uuid.uuid4().hex
                        for kind, payload in (("message.start", {"turn_id": turn}), ("message.delta", {"text": "Local Home received: " + params["text"]}), ("message.complete", {"status": "completed"})):
                            if params["text"] == "hold" and kind == "message.complete":
                                continue
                            await ws.send_json({"jsonrpc": "2.0", "method": "event", "params": {"session_id": params["session_id"], "type": kind, "payload": payload}})
            finally:
                standard_sockets.discard(ws)
            return ws

        fixture = web.Application()
        fixture.router.add_get("/api/ws", standard)
        fixture.router.add_get("/api/audio/speak-stream", standard)
        fixture_runner, fixture_port = await listen(fixture)
        runtime = create_runtime(load_settings({
            "HERMES_HOME_DATA_DIR": str(directory / "home"),
            "HERMES_HOME_ADMIN_TOKEN_FILE": str(directory / "admin"),
            "HERMES_HOME_CREDENTIAL_ROOT_SECRET_FILE": str(directory / "root"),
            "HERMES_HOME_PORT": "0", "HERMES_HOME_BRIDGE_PORT": "0",
            "HERMES_HOME_STANDARD_GATEWAY_URL": f"ws://127.0.0.1:{fixture_port}/api/ws",
            "HERMES_HOME_STANDARD_TOKEN_FILE": str(directory / "standard"),
        }))
        http_thread = threading.Thread(target=runtime.server.serve_forever, daemon=True)
        http_thread.start()
        http_origin = f"http://127.0.0.1:{runtime.server.server_address[1]}"
        bridge_origin = f"http://127.0.0.1:{runtime.bridge_server.socket.getsockname()[1]}"
        process = None
        proxy_runner = control_runner = None
        async with ClientSession() as http:
            async def admin(method, path, body=None):
                async with http.request(method, http_origin + path, json=body, headers={"Authorization": "Bearer " + admin_token}) as response:
                    data = await response.json()
                    if response.status != 200:
                        raise RuntimeError(f"temporary Home admin {method} {path}: status={response.status} code={data.get('error', {}).get('code')}")
                    return data

            async def proxy(request):
                if request.headers.get("Upgrade", "").lower() == "websocket":
                    downstream = web.WebSocketResponse()
                    await downstream.prepare(request)
                    async with http.ws_connect(bridge_origin + request.path_qs, headers={"Authorization": request.headers.get("Authorization", "")}) as upstream:
                        async def copy(source, target):
                            async for frame in source:
                                if frame.type == WSMsgType.TEXT:
                                    await target.send_str(frame.data)
                                elif frame.type == WSMsgType.BINARY:
                                    await target.send_bytes(frame.data)
                        tasks = [asyncio.create_task(copy(downstream, upstream)), asyncio.create_task(copy(upstream, downstream))]
                        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        for task in pending:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                    await downstream.close()
                    return downstream
                headers = {key: value for key, value in request.headers.items() if key.lower() in {"authorization", "content-type"}}
                async with http.request(request.method, http_origin + request.path_qs, data=await request.read(), headers=headers) as response:
                    return web.Response(status=response.status, body=await response.read(), content_type="application/json")

            proxy_app = web.Application()
            proxy_app.router.add_route("*", "/{path:.*}", proxy)
            proxy_runner, proxy_port = await listen(proxy_app, tls=tls)
            home = f"https://127.0.0.1:{proxy_port}"
            try:
                await admin("PUT", "/api/v1/configuration", {"schema": 1, "expected_revision": 0, "snapshot": {
                    "rooms": [], "profiles": [{"id": name, "name": name.title(), "available": True, "shared": True} for name in ("first", "later")], "wake_mappings": [], "devices": [],
                }})
                offer = await admin("POST", "/api/v1/enrollment/offers", {"schema": 1})
                store = PrivatePairings(directory / "pairing.json")
                pairing = asyncio.create_task(pair(home, offer["enrollment_code"], label="Local browser smoke", store=store, browser=True, output_fn=lambda _: None, timeout=30))
                async with asyncio.timeout(15):
                    while True:
                        pending = (await admin("GET", "/api/v1/enrollment/requests"))["requests"]
                        if pending:
                            break
                        await asyncio.sleep(0.05)
                await admin("POST", f"/api/v1/enrollment/requests/{pending[0]['request_id']}/approve", {"schema": 1, "scope": {"rooms": [], "capabilities": ["client_claim"], "wake_mapping_grant": {"mode": "selected", "ids": []}, "client_grants": [{"profile_id": "first"}]}})
                await pairing
                record = store.load(home)
                client = HomeClient(home, store=store)
                assert (directory / "pairing.json").stat().st_mode & 0o777 == 0o600
                config = directory / "browser.yaml"
                config.write_text("profiles: {}\n")
                async def launch(port=0):
                    child = await asyncio.create_subprocess_exec(str(appliance_python or sys.executable), "-u", "-m", "home_display.appliance", "--config", str(config), "--browser-voice", "--browser-transport", "home", "--home-bridge-url", home.replace("https:", "wss:") + "/api/v1/bridge/ws", "--home-device-credential-file", str(directory / "pairing.json"), "--display-host", "127.0.0.1", "--display-port", str(port), cwd=directory if appliance_python else ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                    try:
                        async with asyncio.timeout(20):
                            while True:
                                line = await child.stdout.readline()
                                if not line:
                                    raise RuntimeError("appliance exited before readiness")
                                text = line.decode()
                                print(text, end="", flush=True)
                                if text.startswith("Home display: http://127.0.0.1:"):
                                    return child, int(text.rsplit(":", 1)[1].strip().rstrip("/"))
                    except BaseException:
                        child.terminate()
                        await child.wait()
                        raise
                process, app_port = await launch()
                app_origin = f"http://127.0.0.1:{app_port}"
                async def drain():
                    async for line in process.stdout:
                        print(line.decode(), end="", flush=True)
                drain_task = asyncio.create_task(drain())
                async def control(request):
                    nonlocal process, drain_task
                    operation = request.match_info["operation"]
                    if operation == "add-profile":
                        await admin("POST", f"/api/v1/devices/{record.device_id}/profile-grants", {"schema": 1, "profile_id": "later", "idempotency_key": "smoke-later"})
                    elif operation == "revoke":
                        await admin("POST", f"/api/v1/devices/{record.device_id}/revoke", {"schema": 1})
                    elif operation == "drop-bridge":
                        for ws in list(standard_sockets):
                            await ws.close()
                    elif operation == "restart-appliance":
                        process.terminate()
                        await asyncio.wait_for(process.wait(), 10)
                        await drain_task
                        process, port = await launch(app_port)
                        assert port == app_port
                        drain_task = asyncio.create_task(drain())
                    elif operation != "status":
                        raise web.HTTPNotFound()
                    return web.json_response({"prompt_count": len(prompts), "session_count": len(sessions), "resume_count": methods.count("session.resume"), "url": app_origin})
                control_app = web.Application()
                control_app.router.add_route("*", "/fixture/{operation}", control)
                control_runner, control_port = await listen(control_app)
                print(json.dumps({"ready": True, "ui": app_origin, "control": f"http://127.0.0.1:{control_port}/fixture", "paired": True, "private_mode": "0600", "home_implementation": str(Path(sys.modules['hermes_home.runtime'].__file__).resolve())}), flush=True)
                if serve:
                    stop = asyncio.Event()
                    for sig in (signal.SIGINT, signal.SIGTERM):
                        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
                    await stop.wait()
                else:
                    from websockets.asyncio.client import connect
                    async with connect(app_origin.replace("http:", "ws:") + "/state", origin=app_origin) as one, connect(app_origin.replace("http:", "ws:") + "/state", origin=app_origin) as two:
                        async def snapshot(ws, predicate, *, fail_unavailable=False):
                            async with asyncio.timeout(20):
                                async for raw in ws:
                                    if not isinstance(raw, str):
                                        continue
                                    value = json.loads(raw)
                                    if fail_unavailable and value.get("state") in {"error", "disconnected"}:
                                        raise RuntimeError(f"appliance unavailable: {value.get('status_text')} fixture_methods={methods}")
                                    if value.get("type") == "snapshot" and predicate(value):
                                        return value
                        initial = await snapshot(one, lambda s: bool(s.get("capabilities", {}).get("profiles")))
                        second = await snapshot(two, lambda s: bool(s.get("capabilities", {}).get("profiles")))
                        assert initial["capabilities"]["selected_profile"] != second["capabilities"]["selected_profile"]
                        for ws, text in ((one, "tab one"), (two, "tab two")):
                            await ws.send(json.dumps({"type": "voice_turn", "schema": 1, "text": text}))
                            await snapshot(ws, lambda s: s.get("state") == "idle" and text in s.get("response_text", ""), fail_unavailable=True)
                        assert len(prompts) == 2 and prompts[0][0] != prompts[1][0]
                        _, claims = await client.list_claims(record)
                        assert len(claims) == 2
                        await admin("POST", f"/api/v1/devices/{record.device_id}/profile-grants", {"schema": 1, "profile_id": "later", "idempotency_key": "smoke-later"})
                        refreshed = await snapshot(one, lambda s: len(s.get("capabilities", {}).get("profiles", [])) == 2)
                        later = next(p["selector_id"] for p in refreshed["capabilities"]["profiles"] if p["label"] == "Later")
                        await one.send(json.dumps({"type": "profile_select", "schema": 1, "request_id": "later", "selector_id": later}))
                        await snapshot(one, lambda s: s.get("capabilities", {}).get("selected_profile") == later)
                        await one.send(json.dumps({"type": "voice_turn", "schema": 1, "text": "hold"}))
                        await snapshot(one, lambda s: "hold" in s.get("response_text", ""))
                        for ws in list(standard_sockets):
                            await ws.close()
                        failed = await snapshot(one, lambda s: s.get("state") == "error")
                        assert "not replayed" in failed["status_text"]
                        count = len(prompts)
                        await one.send(json.dumps({"type": "voice_turn", "schema": 1, "text": "fresh after bridge loss"}))
                        await snapshot(one, lambda s: s.get("state") == "idle" and "fresh after bridge loss" in s.get("response_text", ""), fail_unavailable=True)
                        assert len(prompts) == count + 1 and prompts[-1][0] != prompts[-2][0]
                    async with asyncio.timeout(10):
                        while (await client.list_claims(record))[1]:
                            await asyncio.sleep(0.1)
                    before = len(prompts)
                    async with connect(app_origin.replace("http:", "ws:") + "/state", origin=app_origin) as fresh:
                        await snapshot(fresh, lambda s: bool(s.get("capabilities", {}).get("profiles")))
                        assert not (await client.list_claims(record))[1]
                        assert len(prompts) == before
                        await fresh.send(json.dumps({"type": "voice_turn", "schema": 1, "text": "fresh browser connection"}))
                        await snapshot(fresh, lambda s: s.get("state") == "idle" and "fresh browser connection" in s.get("response_text", ""), fail_unavailable=True)
                        assert len(prompts) == before + 1
                        await admin("POST", f"/api/v1/devices/{record.device_id}/revoke", {"schema": 1})
                        revoked = await snapshot(fresh, lambda s: s.get("state") == "error")
                        assert "paired again" in revoked["status_text"]
                        async with http.get(app_origin + "/healthz") as response:
                            assert response.status == 503
                            assert (await response.json())["reason"] == "home_unauthorized"
                    assert "session.resume" not in methods
                    print(json.dumps({"smoke": "passed", "independent_tabs": 2, "prompt_count": len(prompts), "dynamic_later_grant": True, "fresh_bridge_and_browser_conversations": True, "revocation_health": 503, "cleanup_before_revocation": 0, "automatic_replays": 0}), flush=True)
                drain_task.cancel()
            finally:
                if process is not None and process.returncode is None:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), 10)
                if control_runner:
                    await control_runner.cleanup()
                if proxy_runner:
                    await proxy_runner.cleanup()
                await asyncio.to_thread(runtime.server.shutdown)
                await asyncio.to_thread(runtime.close)
                await fixture_runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", help="retain the temporary actual UI until Ctrl-C")
    parser.add_argument("--appliance-python", type=Path, help="installed-wheel interpreter; launch outside the source checkout")
    args = parser.parse_args()
    asyncio.run(run(args.serve, args.appliance_python))
