import io
import json
import asyncio
from urllib.error import HTTPError

import pytest

import scripts.check_ops_web as check
from scripts.check_ops_web import check_action_route, origin_urls


def test_origin_urls_keep_the_public_origin_and_switch_state_to_wss():
    assert origin_urls("https://hermes-home.chappell-home.dev/") == (
        "https://hermes-home.chappell-home.dev",
        "https://hermes-home.chappell-home.dev/",
        "wss://hermes-home.chappell-home.dev/state",
    )


def test_origin_urls_preserve_an_explicit_public_port():
    assert origin_urls("https://display.example:8443") == (
        "https://display.example:8443",
        "https://display.example:8443/",
        "wss://display.example:8443/state",
    )


@pytest.mark.parametrize(
    "value",
    [
        "ws://display.example",
        "https://display.example/path",
        "https://user:pass@display.example",
        "https://display.example?probe=1",
        "https://display.example:70000",
        "https://:443",
    ],
)
def test_origin_urls_reject_non_origin_values(value):
    with pytest.raises(ValueError):
        origin_urls(value)


def test_action_route_accepts_the_expected_safe_malformed_response(monkeypatch):
    seen = {}

    def fake_urlopen(request, *, timeout, context=None):
        seen["url"] = request.full_url
        seen["origin"] = request.headers["Origin"]
        seen["context"] = context
        raise HTTPError(
            request.full_url,
            400,
            "bad request",
            {},
            io.BytesIO(check.EXPECTED_ACTION_ERROR),
        )

    monkeypatch.setattr("scripts.check_ops_web.urlopen", fake_urlopen)

    check_action_route("https://hermes-home.chappell-home.dev", timeout=1.0)

    assert seen == {
        "url": "https://hermes-home.chappell-home.dev/action",
        "origin": "https://hermes-home.chappell-home.dev",
        "context": None,
    }


def test_run_check_exercises_page_action_and_state_with_the_same_tls_context(monkeypatch):
    requests = []
    websocket_calls = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return "https://display.example/"

        def read(self):
            return b'<title>Hermes Home Display</title><div id="app"></div>'

    def fake_urlopen(request, *, timeout, context=None):
        requests.append((request.full_url, context))
        if request.full_url.endswith("/action"):
            raise HTTPError(
                request.full_url,
                400,
                "bad request",
                {},
                io.BytesIO(check.EXPECTED_ACTION_ERROR),
            )
        return Response()

    class WebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def recv(self):
            return json.dumps({
                "type": "snapshot",
                "schema": 1,
                "sequence": 0,
                "state": "idle",
                "capabilities": {
                    "features": ["browser_hands_free"],
                    "wake_phrases": ["hey missy", "hey skippy", "hey spark"],
                },
            })

    def fake_connect(url, **kwargs):
        websocket_calls["url"] = url
        websocket_calls.update(kwargs)
        return WebSocket()

    monkeypatch.setattr(check, "urlopen", fake_urlopen)
    monkeypatch.setattr(check, "connect", fake_connect)

    asyncio.run(check.run_check("https://display.example", insecure=True, timeout=1.0))

    assert [url for url, _context in requests] == [
        "https://display.example/",
        "https://display.example/action",
    ]
    assert requests[0][1] is requests[1][1]
    assert websocket_calls["url"] == "wss://display.example/state"
    assert websocket_calls["origin"] == "https://display.example"


@pytest.mark.asyncio
async def test_state_check_can_require_the_advertised_wake_catalog(monkeypatch):
    class WebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def recv(self):
            return json.dumps({
                "type": "snapshot",
                "schema": 1,
                "sequence": 0,
                "state": "idle",
                "capabilities": {
                    "features": ["browser_hands_free"],
                    "wake_phrases": ["hey missy", "hey skippy"],
                },
            })

    monkeypatch.setattr(check, "connect", lambda *_args, **_kwargs: WebSocket())

    with pytest.raises(check.CheckError, match="expected wake-word catalog"):
        await check.check_state_channel(
            "wss://display.example/state",
            origin="https://display.example",
            timeout=1.0,
            tls_context=None,
            expected_wake_phrases=("hey missy", "hey skippy", "hey spark"),
        )


def test_page_check_rejects_a_generic_success_page(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return "https://display.example/"

        def read(self):
            return b"generic fallback"

    monkeypatch.setattr(check, "urlopen", lambda *args, **kwargs: Response())

    with pytest.raises(check.CheckError, match="not the Hermes Home display"):
        check.check_page(
            "https://display.example/",
            origin="https://display.example",
            timeout=1.0,
        )


def test_action_check_rejects_an_unrelated_bad_request(monkeypatch):
    def fake_urlopen(request, *, timeout, context=None):
        raise HTTPError(request.full_url, 400, "bad request", {}, io.BytesIO(b"proxy error"))

    monkeypatch.setattr(check, "urlopen", fake_urlopen)

    with pytest.raises(check.CheckError, match="unexpected malformed-payload"):
        check_action_route("https://display.example", timeout=1.0)


@pytest.mark.asyncio
async def test_state_check_rejects_an_arbitrary_json_state(monkeypatch):
    seen = {}

    class WebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def recv(self):
            return json.dumps({"state": "pretend-healthy"})

    def fake_connect(_url, **kwargs):
        seen.update(kwargs)
        return WebSocket()

    monkeypatch.setattr(check, "connect", fake_connect)

    with pytest.raises(check.CheckError, match="invalid initial snapshot"):
        await check.check_state_channel(
            "wss://display.example/state",
            origin="https://display.example",
            timeout=1.0,
            tls_context=None,
        )
    assert "ssl" not in seen


def test_main_rejects_an_infinite_timeout():
    assert check.main(["--timeout", "inf"]) == 2
