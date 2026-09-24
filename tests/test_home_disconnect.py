"""Home closure regression through a real loopback WebSocket and Textual app."""
from __future__ import annotations

import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

import app as app_module
from app import HermesStreamingApp
from puck_bridge.home_session import HomePuckSession
from puck_bridge.home_textual_session import HomeTextualSession
from tests.test_app import make_args, transcript_of, voice_status_of
from tests.test_home_textual_session import FakeHomeClient, READY


@pytest.mark.asyncio
@pytest.mark.parametrize("partial_reply", [False, True], ids=["while-thinking", "during-reply"])
async def test_home_websocket_close_ends_thinking_preserves_uncertainty_and_never_replays(
    tmp_path, monkeypatch, partial_reply
):
    # HTTP/keyring are fakes; only the bridge socket is real and bound to loopback.
    monkeypatch.setattr("puck_bridge.home_textual_session.HomeClient", FakeHomeClient)
    submitted = asyncio.Event()
    close_upstream = asyncio.Event()
    requests = []

    async def handler(socket):
        async for raw in socket:
            request = json.loads(raw)
            requests.append(request)
            method = request["method"]
            result = dict(READY)
            if method == "prompt.submit":
                result = {"schema": 1, "status": "submitted", "conversation_handle": "opaque-handle", "turn_id": "turn-1"}
            elif method == "conversation.close":
                result = {"schema": 1, "status": "closed", "conversation_handle": "opaque-handle"}
            await socket.send(json.dumps({"jsonrpc": "2.0", "schema": 1, "id": request["id"], "result": result}))
            if method == "prompt.submit":
                event = {"type": "thinking.delta", "payload": {"text": "Working on the request"}}
                await socket.send(json.dumps({"jsonrpc": "2.0", "schema": 1, "method": "event", "params": {"schema": 1, "conversation_handle": "opaque-handle", "turn_id": "turn-1", "event": event}}))
                if partial_reply:
                    event = {"type": "message.delta", "payload": {"text": "Partial answer retained."}}
                    await socket.send(json.dumps({"jsonrpc": "2.0", "schema": 1, "method": "event", "params": {"schema": 1, "conversation_handle": "opaque-handle", "turn_id": "turn-1", "event": event}}))
                submitted.set()
                await close_upstream.wait()
                await socket.close(code=1011, reason="upstream unavailable")
                return

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]

        def loopback_connect(_home_url, *, additional_headers=None, **kwargs):
            return connect(f"ws://127.0.0.1:{port}", additional_headers=additional_headers, **kwargs)

        def bridge_factory(*args, **kwargs):
            return HomePuckSession(*args, connect_factory=loopback_connect, **kwargs)

        def session_factory(args):
            return HomeTextualSession(args, home_session_factory=bridge_factory)

        app = HermesStreamingApp(
            args=make_args(transport="home", url="wss://home.example/api/v1/bridge/ws", history_path=tmp_path / "prompts.jsonl"),
            session_factory=session_factory,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._connection_is_ready()
            original_session = app.session
            original_bridge = app.session._home_session
            turn = asyncio.create_task(app._run_turn("A question that must never be replayed"))
            try:
                await asyncio.wait_for(submitted.wait(), timeout=2)
                await pilot.pause()
                assert app._turn_in_flight
                assert app.voice_state == app_module.VOICE_THINKING
                app._queued_prompts.append("Unsent question must remain queued")
                close_upstream.set()
                # turn_timeout is zero: closure, rather than a timeout, must end it.
                await asyncio.wait_for(asyncio.shield(turn), timeout=2)
                await pilot.pause()

                assert not app._turn_in_flight
                assert app.connection_state == app_module.CONNECTION_DISCONNECTED
                assert app.voice_state == app_module.VOICE_DISCONNECTED
                assert "thinking" not in voice_status_of(app).lower()
                assert app.transcript._active_activity is None
                assert app.transcript._streaming_message is None
                assert app._last_prompt_status == app_module.PROMPT_AMBIGUOUS
                assert "A question that must never be replayed" in transcript_of(app)
                if partial_reply:
                    assert "Partial answer retained." in transcript_of(app)
                assert app._queued_prompts == ["Unsent question must remain queued"]

                await asyncio.wait_for(app._handle_reconnect_command(""), timeout=2)
                await pilot.pause()
                assert app.session is original_session
                assert app.session._home_session is original_bridge
                assert app._connection_is_ready()
                assert app._last_prompt_status == app_module.PROMPT_AMBIGUOUS
                assert "earlier turn remains unresolved" in transcript_of(app)
                assert "/home leave" in transcript_of(app)
                assert await app._run_turn("Another question before resolving uncertainty") is False
                assert app._queued_prompts == ["Unsent question must remain queued"]
                assert [r["method"] for r in requests] == ["conversation.open", "prompt.submit", "conversation.reconnect"]
                assert app.session.home_client.claim_count == 1
            finally:
                close_upstream.set()
                if not turn.done():
                    turn.cancel()
                    await asyncio.gather(turn, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["fallback", "unavailable", "timeout"])
async def test_home_audio_failure_preserves_completed_text_in_app(tmp_path, monkeypatch, ending):
    from tests.test_puck_home_session import _FakeConnect, _ready_socket, _audio, _event

    class BoundClient(FakeHomeClient):
        async def claim(self, *args, **kwargs):
            result = await super().claim(*args, **kwargs)
            result["conversation_handle"] = "opaque-home-handle"
            return result

    monkeypatch.setattr("puck_bridge.home_textual_session.HomeClient", BoundClient)
    frames = [
        _audio("start", "home-turn-1", sample_rate=24000, channels=1,
               sample_width=2, byte_order="little"),
        _event("message.delta", "home-turn-1", {"text": "Confirmed answer."}),
        _event("message.complete", "home-turn-1", {}),
    ]
    if ending != "timeout":
        frames.append(_audio(ending, "home-turn-1"))
    socket = _ready_socket(*frames)
    def bridge_factory(*args, **kwargs):
        return HomePuckSession(*args, connect_factory=_FakeConnect([socket, _ready_socket()]), request_timeout=1, **kwargs)
    def session_factory(args):
        return HomeTextualSession(args, home_session_factory=bridge_factory)
    app = HermesStreamingApp(
        args=make_args(transport="home", url="https://home.example", history_path=tmp_path / "prompts.jsonl"),
        session_factory=session_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._connection_is_ready(), transcript_of(app)
        app.session._home_session._request_timeout = 0.02
        assert await app._run_turn("TEST") is True, transcript_of(app)
        await pilot.pause()
        assert app._last_prompt_status == app_module.PROMPT_COMPLETED
        assert "Confirmed answer." in transcript_of(app)
        assert "audio unavailable" in transcript_of(app)
        assert app._audio_unavailable_reason
        assert not app._turn_in_flight
        if ending == "timeout":
            assert app.connection_state == app_module.CONNECTION_DISCONNECTED
            assert app.voice_state == app_module.VOICE_DISCONNECTED
        else:
            assert app.voice_state == app_module.VOICE_READY
        assert sum(request["method"] == "prompt.submit" for request in socket.sent) == 1
