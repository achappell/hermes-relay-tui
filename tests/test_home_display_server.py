import asyncio
import json
import shutil
import ssl
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from websockets.exceptions import ConnectionClosed, InvalidHandshake
from websockets.legacy.client import connect

import home_display.server as server_module
from home_display.server import (
    BrowserProfileRouteResult,
    DisplayServer,
    load_tls_context,
)
from home_display.state import DisplayStatePublisher


def _test_tls_files(tmp_path):
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is required for the TLS integration test")
    certificate = tmp_path / "display-cert.pem"
    private_key = tmp_path / "display-key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    return certificate, private_key


def _unverified_client_context() -> ssl.SSLContext:
    return ssl._create_unverified_context()


def test_load_tls_context_requires_certificate_and_key_together(tmp_path):
    with pytest.raises(ValueError, match="supplied together"):
        load_tls_context(tmp_path / "cert.pem", None)


def test_load_tls_context_reports_missing_files(tmp_path):
    with pytest.raises(ValueError, match="could not load display TLS"):
        load_tls_context(tmp_path / "cert.pem", tmp_path / "key.pem")


@pytest.mark.asyncio
async def test_server_serves_index_html_and_current_state(tmp_path):
    (tmp_path / "index.html").write_text("home", encoding="utf-8")
    server = DisplayServer(DisplayStatePublisher(), tmp_path)
    info = await server.start()
    try:
        assert info.host == "127.0.0.1"
        assert await asyncio.to_thread(lambda: urlopen(info.http_url).read()) == b"home"
        async with connect(info.websocket_url) as socket:
            assert json.loads(await socket.recv())["state"] == "idle"
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_server_serves_https_page_and_secure_state_channel(tmp_path):
    (tmp_path / "index.html").write_text("secure home", encoding="utf-8")
    certificate, private_key = _test_tls_files(tmp_path)
    server = DisplayServer(
        DisplayStatePublisher(),
        tmp_path,
        ssl_context=load_tls_context(certificate, private_key),
    )
    info = await server.start()
    client_context = _unverified_client_context()
    try:
        assert info.secure is True
        assert info.http_url.startswith("https://")
        assert info.websocket_url.startswith("wss://")
        assert await asyncio.to_thread(
            lambda: urlopen(info.http_url, context=client_context).read()
        ) == b"secure home"
        async with connect(
            info.websocket_url,
            origin=info.http_url,
            ssl=client_context,
        ) as socket:
            assert json.loads(await socket.recv())["state"] == "idle"
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_https_state_rejects_plain_http_origin(tmp_path):
    (tmp_path / "index.html").write_text("secure home", encoding="utf-8")
    certificate, private_key = _test_tls_files(tmp_path)
    server = DisplayServer(
        DisplayStatePublisher(),
        tmp_path,
        ssl_context=load_tls_context(certificate, private_key),
    )
    info = await server.start()
    try:
        with pytest.raises(InvalidHandshake) as error:
            await connect(
                info.websocket_url,
                origin=f"http://{info.host}:{info.port}/",
                ssl=_unverified_client_context(),
            )
        response = getattr(error.value, "response", None)
        status_code = getattr(error.value, "status_code", None)
        if status_code is None:
            status_code = getattr(response, "status_code", None)
        assert status_code == 403
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_server_pushes_published_state_without_reconnecting(tmp_path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    publisher = DisplayStatePublisher()
    server = DisplayServer(publisher, tmp_path)
    info = await server.start()
    try:
        async with connect(info.websocket_url) as socket:
            await socket.recv()
            publisher.publish(state="speaking", response_text="one block")
            update = json.loads(await socket.recv())
        assert update["response_text"] == "one block"
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_server_dispatches_normalized_websocket_actions(tmp_path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    calls: list[tuple[str, str]] = []

    async def on_action(action_id: str, choice: str) -> None:
        calls.append((action_id, choice))

    server = DisplayServer(DisplayStatePublisher(), tmp_path, on_action=on_action)
    info = await server.start()
    try:
        async with connect(info.websocket_url) as socket:
            await socket.recv()
            await socket.send(json.dumps({
                "type": "action",
                "schema": 1,
                "action_id": "sethome",
                "choice": "yes",
            }))
            await asyncio.sleep(0.01)
        assert calls == [("sethome", "yes")]
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_server_dispatches_browser_voice_turn_text(tmp_path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    calls: list[str] = []

    async def on_voice_turn(text: str) -> None:
        calls.append(text)

    server = DisplayServer(
        DisplayStatePublisher(),
        tmp_path,
        on_voice_turn=on_voice_turn,
    )
    info = await server.start()
    try:
        async with connect(info.websocket_url, origin=info.http_url) as socket:
            await socket.recv()
            await socket.send(json.dumps({
                "type": "voice_turn",
                "schema": 1,
                "text": "  what is the weather?  ",
            }))
            await asyncio.sleep(0.01)
        assert calls == ["what is the weather?"]
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_legacy_voice_callback_drops_wake_bearing_frames(tmp_path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    calls: list[str] = []

    async def on_voice_turn(text: str) -> None:
        calls.append(text)

    server = DisplayServer(
        DisplayStatePublisher(),
        tmp_path,
        on_voice_turn=on_voice_turn,
    )
    info = await server.start()
    try:
        async with connect(info.websocket_url, origin=info.http_url) as socket:
            await socket.recv()
            await socket.send(json.dumps({
                "type": "voice_turn",
                "schema": 1,
                "text": "should be dropped",
                "wake_phrase": "hey skippy",
            }))
            await socket.send(json.dumps({
                "type": "voice_turn",
                "schema": 1,
                "text": "legacy turn",
            }))
            await asyncio.sleep(0.01)
        assert calls == ["legacy turn"]
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_server_dispatches_profile_route_ack_and_wake_phrase(tmp_path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    routes: list[str] = []
    turns: list[tuple[str, str | None]] = []

    class Binding:
        publisher = DisplayStatePublisher()

        async def handle_profile_route(self, wake_phrase: str) -> BrowserProfileRouteResult:
            routes.append(wake_phrase)
            return BrowserProfileRouteResult(accepted=True, account="Jensen")

        async def handle_voice_turn(
            self,
            text: str,
            wake_phrase: str | None = None,
        ) -> None:
            turns.append((text, wake_phrase))

        async def handle_action(self, _action_id: str, _choice: str) -> None:
            pass

        async def close(self) -> None:
            pass

    async def create_binding(_connection_id, _sender):
        return Binding()

    server = DisplayServer(
        DisplayStatePublisher(),
        tmp_path,
        on_browser_connect=create_binding,
    )
    info = await server.start()
    try:
        async with connect(info.websocket_url, origin=info.http_url) as socket:
            await socket.recv()
            await socket.send(json.dumps({
                "type": "profile_route",
                "schema": 1,
                "request_id": "route-1",
                "wake_phrase": "hey skippy",
            }))
            route_ack = json.loads(await socket.recv())
            assert route_ack == {
                "type": "profile_route_ack",
                "schema": 1,
                "request_id": "route-1",
                "accepted": True,
                "account": "Jensen",
            }

            await socket.send(json.dumps({
                "type": "profile_route",
                "schema": 1,
                "request_id": "route-2",
                "wake_phrase": " ",
            }))
            malformed_ack = json.loads(await socket.recv())
            assert malformed_ack == {
                "type": "profile_route_ack",
                "schema": 1,
                "request_id": "route-2",
                "accepted": False,
                "reason": "malformed_request",
            }

            await socket.send(json.dumps({
                "type": "voice_turn",
                "schema": 1,
                "text": "what is the weather?",
                "wake_phrase": "hey skippy",
            }))
            await asyncio.sleep(0.01)

        assert routes == ["hey skippy"]
        assert turns == [("what is the weather?", "hey skippy")]
    finally:
        await server.close()


def test_server_rejects_malformed_profile_routing_fields():
    assert DisplayServer._parse_websocket_profile_route(json.dumps({
        "type": "profile_route",
        "schema": True,
        "request_id": "route-1",
        "wake_phrase": "hey skippy",
    })) is None
    assert DisplayServer._parse_websocket_profile_route(json.dumps({
        "type": "profile_route",
        "schema": 1,
        "request_id": "route-1",
        "wake_phrase": " ",
    })) is None
    assert DisplayServer._parse_websocket_voice_turn(json.dumps({
        "type": "voice_turn",
        "schema": 1,
        "text": "question",
        "wake_phrase": "x" * 129,
    })) is None
    assert DisplayServer._parse_websocket_voice_turn(json.dumps({
        "type": "voice_turn",
        "schema": True,
        "text": "question",
    })) is None


def test_server_parses_typed_choice_actions_and_rejects_mixed_legacy_fields():
    typed_action = {
        "type": "action",
        "schema": 1,
        "action_id": "correlation-1",
        "operation": "explore",
        "option_id": "inspect",
        "object_id": "home-object-1",
        "freshness": "home-freshness-1",
    }
    assert DisplayServer._parse_websocket_action(json.dumps(typed_action)) == (
        "correlation-1",
        "inspect",
        "explore",
        "home-object-1",
        "home-freshness-1",
    )
    assert DisplayServer._parse_websocket_action(json.dumps({
        **typed_action,
        "choice": "inspect",
    })) is None
    assert DisplayServer._parse_websocket_action(json.dumps({
        **typed_action,
        "freshness": "",
    })) is None


@pytest.mark.asyncio
async def test_isolated_browser_connections_route_state_actions_and_audio_to_the_owner(
    tmp_path,
):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")

    class Binding:
        def __init__(self, sender):
            self.publisher = DisplayStatePublisher()
            self.sender = sender
            self.actions: list[tuple[str, str]] = []
            self.turns: list[str] = []
            self.closed = False

        async def handle_action(self, action_id: str, choice: str) -> None:
            self.actions.append((action_id, choice))

        async def handle_voice_turn(self, text: str) -> None:
            self.turns.append(text)

        async def close(self) -> None:
            self.closed = True

    bindings: list[Binding] = []

    async def create_binding(_connection_id, sender):
        binding = Binding(sender)
        bindings.append(binding)
        return binding

    server = DisplayServer(
        DisplayStatePublisher(),
        tmp_path,
        on_browser_connect=create_binding,
    )
    info = await server.start()
    try:
        async with connect(info.websocket_url) as first, connect(info.websocket_url) as second:
            assert json.loads(await first.recv())["state"] == "idle"
            assert json.loads(await second.recv())["state"] == "idle"
            assert len(bindings) == 2
            assert server.browser_sessions_in_use == 2

            bindings[0].publisher.publish(state="speaking", response_text="first")
            assert json.loads(await first.recv())["response_text"] == "first"
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(second.recv(), 0.05)

            bindings[1].publisher.publish(state="thinking", response_text="second")
            assert json.loads(await second.recv())["response_text"] == "second"
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(first.recv(), 0.05)

            await first.send(json.dumps({
                "type": "action",
                "schema": 1,
                "action_id": "first-prompt",
                "choice": "yes",
            }))
            await second.send(json.dumps({
                "type": "voice_turn",
                "schema": 1,
                "text": "second question",
            }))
            await asyncio.sleep(0.01)
            assert bindings[0].actions == [("first-prompt", "yes")]
            assert bindings[0].turns == []
            assert bindings[1].turns == ["second question"]

            await bindings[0].sender.send_audio_start(
                turn_id="first-turn",
                sample_rate=24000,
                channels=1,
                sample_width=2,
            )
            assert json.loads(await first.recv())["turn_id"] == "first-turn"
            await bindings[0].sender.send_audio_chunk(b"\x01\x02")
            assert await first.recv() == b"\x01\x02"
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(second.recv(), 0.05)

            await bindings[0].sender.send_audio_end(turn_id="first-turn")
            assert json.loads(await first.recv())["type"] == "audio_end"
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(second.recv(), 0.05)

            await bindings[1].sender.send_audio_abort(
                turn_id="second-turn", reason="cancelled"
            )
            assert json.loads(await second.recv())["type"] == "audio_abort"
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(first.recv(), 0.05)
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_browser_capacity_rejects_only_the_extra_admitted_socket(tmp_path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    created = []

    class Binding:
        def __init__(self):
            self.publisher = DisplayStatePublisher()

        async def handle_action(self, _action_id: str, _choice: str) -> None:
            pass

        async def handle_voice_turn(self, _text: str) -> None:
            pass

        async def close(self) -> None:
            pass

    async def create_binding(_connection_id, _sender):
        binding = Binding()
        created.append(binding)
        return binding

    server = DisplayServer(
        DisplayStatePublisher(),
        tmp_path,
        browser_session_limit=1,
        on_browser_connect=create_binding,
    )
    info = await server.start()
    first = await connect(info.websocket_url)
    second = None
    try:
        assert json.loads(await first.recv())["state"] == "idle"
        second = await connect(info.websocket_url)
        with pytest.raises(ConnectionClosed) as error:
            await second.recv()
        assert error.value.code == 1013
        assert len(created) == 1
        assert server.browser_sessions_in_use == 1

        created[0].publisher.publish(state="speaking", response_text="still live")
        assert json.loads(await first.recv())["response_text"] == "still live"
    finally:
        await first.close()
        if second is not None:
            await second.close()
        await server.close()


@pytest.mark.asyncio
async def test_browser_factory_failure_releases_capacity_for_the_next_socket(tmp_path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    calls = 0

    class Binding:
        publisher = DisplayStatePublisher()

        async def handle_action(self, _action_id: str, _choice: str) -> None:
            pass

        async def handle_voice_turn(self, _text: str) -> None:
            pass

        async def close(self) -> None:
            pass

    async def create_binding(_connection_id, _sender):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("upstream unavailable")
        return Binding()

    server = DisplayServer(
        DisplayStatePublisher(),
        tmp_path,
        browser_session_limit=1,
        on_browser_connect=create_binding,
    )
    info = await server.start()
    first = await connect(info.websocket_url)
    second = None
    try:
        with pytest.raises(ConnectionClosed) as error:
            await first.recv()
        assert error.value.code == 1011
        for _ in range(20):
            if server.browser_sessions_in_use == 0:
                break
            await asyncio.sleep(0.01)
        assert server.browser_sessions_in_use == 0

        second = await connect(info.websocket_url)
        assert json.loads(await second.recv())["state"] == "idle"
        assert calls == 2
    finally:
        await first.close()
        if second is not None:
            await second.close()
        await server.close()


@pytest.mark.asyncio
async def test_browser_factory_timeout_releases_its_reserved_slot(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(server_module, "BROWSER_CONTEXT_SETUP_TIMEOUT", 0.01)
    release = asyncio.Event()

    async def create_binding(_connection_id, _sender):
        await release.wait()
        raise RuntimeError("test factory should be cancelled")

    server = DisplayServer(
        DisplayStatePublisher(),
        tmp_path,
        browser_session_limit=1,
        on_browser_connect=create_binding,
    )
    info = await server.start()
    socket = await connect(info.websocket_url)
    try:
        with pytest.raises(ConnectionClosed) as error:
            await socket.recv()
        assert error.value.code == 1011
        for _ in range(20):
            if server.browser_sessions_in_use == 0:
                break
            await asyncio.sleep(0.01)
        assert server.browser_sessions_in_use == 0
    finally:
        release.set()
        await socket.close()
        await server.close()


@pytest.mark.asyncio
async def test_browser_capacity_closes_pending_socket_with_retryable_1013(tmp_path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    admitted = asyncio.Event()
    release = asyncio.Event()

    class Binding:
        publisher = DisplayStatePublisher()

        async def handle_action(self, _action_id: str, _choice: str) -> None:
            pass

        async def handle_voice_turn(self, _text: str) -> None:
            pass

        async def close(self) -> None:
            pass

    async def create_binding(_connection_id, _sender):
        admitted.set()
        await release.wait()
        return Binding()

    server = DisplayServer(
        DisplayStatePublisher(),
        tmp_path,
        browser_session_limit=1,
        on_browser_connect=create_binding,
    )
    info = await server.start()
    first = await connect(info.websocket_url)
    try:
        assert await asyncio.wait_for(admitted.wait(), 1.0)
        assert server.browser_sessions_in_use == 1
        second = await connect(info.websocket_url)
        try:
            with pytest.raises(ConnectionClosed) as error:
                await second.recv()
            assert error.value.code == 1013
            assert str(error.value.reason) == "browser session capacity reached"
        finally:
            await second.close()
    finally:
        release.set()
        await first.close()
        await server.close()


@pytest.mark.asyncio
async def test_server_streams_signed_pcm_to_connected_browser(tmp_path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    server = DisplayServer(DisplayStatePublisher(), tmp_path)
    info = await server.start()
    try:
        async with connect(info.websocket_url, origin=info.http_url) as socket:
            await socket.recv()
            await server.send_audio_start(
                turn_id="turn-1",
                sample_rate=24000,
                channels=1,
                sample_width=2,
            )
            assert json.loads(await socket.recv()) == {
                "type": "audio_start",
                "schema": 1,
                "turn_id": "turn-1",
                "sample_rate": 24000,
                "channels": 1,
                "sample_width": 2,
            }

            await server.send_audio_chunk(b"\x01\x02")
            assert await socket.recv() == b"\x01\x02"

            await server.send_audio_end(turn_id="turn-1")
            assert json.loads(await socket.recv()) == {
                "type": "audio_end",
                "schema": 1,
                "turn_id": "turn-1",
            }
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_server_accepts_browser_http_action_posts(tmp_path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    server = DisplayServer(DisplayStatePublisher(), tmp_path)
    info = await server.start()
    try:
        request = Request(
            f"{info.http_url}action?action_id=sethome&choice=yes",
            method="POST",
            headers={"Origin": info.http_url},
        )
        response = await asyncio.to_thread(lambda: urlopen(request))
        assert response.status == 200
        assert response.read() == b"{}\n"
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_server_serves_mime_typed_static_assets(tmp_path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('home')", encoding="utf-8")
    server = DisplayServer(DisplayStatePublisher(), tmp_path)
    info = await server.start()
    try:
        response = await asyncio.to_thread(lambda: urlopen(f"{info.http_url}app.js"))
        assert response.read() == b"console.log('home')"
        assert response.headers.get_content_type() == "text/javascript"
    finally:
        await server.close()


def test_static_path_escape_is_rejected(tmp_path):
    server = DisplayServer(DisplayStatePublisher(), tmp_path)

    with pytest.raises(ValueError, match="path"):
        server.resolve_static_path("/../secret")


def test_static_path_rejects_absolute_path_after_url_decoding(tmp_path):
    server = DisplayServer(DisplayStatePublisher(), tmp_path)

    with pytest.raises(ValueError, match="path"):
        server.resolve_static_path("/%2Fetc%2Fpasswd")


def test_static_path_rejects_symlink_escape(tmp_path):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("private", encoding="utf-8")
    try:
        (static_dir / "escape.txt").symlink_to(outside_file)
    except (OSError, NotImplementedError):
        pytest.skip("platform cannot create symlinks")

    server = DisplayServer(DisplayStatePublisher(), static_dir)

    with pytest.raises(ValueError, match="path"):
        server.resolve_static_path("/escape.txt")


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.1"])
def test_server_rejects_non_loopback_host(tmp_path, host):
    with pytest.raises(ValueError, match="loopback"):
        DisplayServer(DisplayStatePublisher(), tmp_path, host=host)


@pytest.mark.asyncio
async def test_server_allows_explicit_remote_bind_for_lan_display(tmp_path):
    (tmp_path / "index.html").write_text("home", encoding="utf-8")
    server = DisplayServer(
        DisplayStatePublisher(), tmp_path, host="0.0.0.0", allow_remote=True
    )
    info = await server.start()
    try:
        async with connect(f"ws://127.0.0.1:{info.port}/state") as socket:
            assert json.loads(await socket.recv())["state"] == "idle"
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_server_rejects_websocket_upgrade_for_non_state_path(tmp_path):
    (tmp_path / "index.html").write_text("home", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('home')", encoding="utf-8")
    server = DisplayServer(DisplayStatePublisher(), tmp_path)
    info = await server.start()
    try:
        with pytest.raises(InvalidHandshake) as error:
            await connect(f"ws://{info.host}:{info.port}/app.js")
        response = getattr(error.value, "response", None)
        status_code = getattr(error.value, "status_code", None)
        if status_code is None:
            status_code = getattr(response, "status_code", None)
        assert status_code == 404
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_state_accepts_the_server_http_origin(tmp_path):
    (tmp_path / "index.html").write_text("home", encoding="utf-8")
    server = DisplayServer(DisplayStatePublisher(), tmp_path)
    info = await server.start()
    try:
        async with connect(info.websocket_url, origin=info.http_url) as socket:
            assert json.loads(await socket.recv())["state"] == "idle"
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_state_accepts_the_configured_public_origin(tmp_path):
    (tmp_path / "index.html").write_text("home", encoding="utf-8")
    public_origin = "https://hermes-home.chappell-home.dev"
    server = DisplayServer(
        DisplayStatePublisher(),
        tmp_path,
        public_origin=public_origin,
    )
    info = await server.start()
    try:
        async with connect(info.websocket_url, origin=public_origin) as socket:
            assert json.loads(await socket.recv())["state"] == "idle"
        async with connect(info.websocket_url, origin=f"{public_origin}:443/") as socket:
            assert json.loads(await socket.recv())["state"] == "idle"
    finally:
        await server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin",
    [
        "http://hermes-home.chappell-home.dev",
        "https://hermes-home.chappell-home.dev:444",
        "https://hermes-home.chappell-home.dev.evil",
        "https://hermes-home.chappell-home.dev/other",
        "https://hermes-home.chappell-home.dev/?probe=1",
    ],
)
async def test_state_rejects_origins_that_only_resemble_the_public_origin(tmp_path, origin):
    (tmp_path / "index.html").write_text("home", encoding="utf-8")
    server = DisplayServer(
        DisplayStatePublisher(),
        tmp_path,
        public_origin="https://hermes-home.chappell-home.dev",
    )
    info = await server.start()
    try:
        with pytest.raises(InvalidHandshake) as error:
            await connect(info.websocket_url, origin=origin)
        response = getattr(error.value, "response", None)
        status_code = getattr(error.value, "status_code", None)
        if status_code is None:
            status_code = getattr(response, "status_code", None)
        assert status_code == 403
    finally:
        await server.close()


def test_public_origin_rejects_a_path_or_non_http_scheme(tmp_path):
    with pytest.raises(ValueError, match="public origin"):
        DisplayServer(
            DisplayStatePublisher(),
            tmp_path,
            public_origin="wss://hermes-home.chappell-home.dev/state",
        )


@pytest.mark.asyncio
async def test_public_origin_reaches_action_route_without_dispatching_malformed_action(tmp_path):
    (tmp_path / "index.html").write_text("home", encoding="utf-8")
    calls: list[tuple[str, str]] = []

    async def on_action(action_id: str, choice: str) -> None:
        calls.append((action_id, choice))

    server = DisplayServer(
        DisplayStatePublisher(),
        tmp_path,
        public_origin="https://hermes-home.chappell-home.dev",
        on_action=on_action,
    )
    info = await server.start()
    try:
        request = Request(
            f"http://{info.host}:{info.port}/action",
            method="POST",
            headers={"Origin": "https://hermes-home.chappell-home.dev"},
        )
        with pytest.raises(HTTPError) as error:
            await asyncio.to_thread(lambda: urlopen(request))
        assert error.value.code == 400
        assert calls == []
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_state_rejects_an_unrelated_origin(tmp_path):
    (tmp_path / "index.html").write_text("home", encoding="utf-8")
    server = DisplayServer(DisplayStatePublisher(), tmp_path)
    info = await server.start()
    try:
        with pytest.raises(InvalidHandshake) as error:
            await connect(info.websocket_url, origin="http://unrelated.example")
        response = getattr(error.value, "response", None)
        status_code = getattr(error.value, "status_code", None)
        if status_code is None:
            status_code = getattr(response, "status_code", None)
        assert status_code == 403
    finally:
        await server.close()
