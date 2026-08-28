import pytest

from app import HermesSession, HermesStreamingApp


class FakeSession:
    """Stands in for the worker that owns the websocket connection."""

    def __init__(self):
        self.sent_turns = []
        self.closed = False

    async def send_turn(self, text: str):
        self.sent_turns.append(text)

    async def close(self):
        self.closed = True


async def test_app_mounts_with_transcript_and_input():
    app = HermesStreamingApp(session_factory=lambda: FakeSession())
    async with app.run_test() as pilot:
        assert app.query_one("#transcript") is not None
        assert app.query_one("#input") is not None


async def test_submitting_input_sends_a_turn_and_clears_input():
    fake_session = FakeSession()
    app = HermesStreamingApp(session_factory=lambda: fake_session)
    async with app.run_test() as pilot:
        input_widget = app.query_one("#input")
        input_widget.value = "hello hermes"
        await pilot.press("enter")
        assert fake_session.sent_turns == ["hello hermes"]
        assert input_widget.value == ""


class FakeConnectContextManager:
    """Stands in for the object `connect(...)` returns before entering it."""

    def __init__(self):
        self.aexit_called_with = None

    async def __aenter__(self):
        return "fake-ws"

    async def __aexit__(self, exc_type, exc, tb):
        self.aexit_called_with = (exc_type, exc, tb)


async def test_session_close_exits_the_connect_context_manager():
    session = HermesSession(args=None)
    fake_cm = FakeConnectContextManager()
    session._connect_cm = fake_cm

    await session.close()

    assert fake_cm.aexit_called_with == (None, None, None)
    assert session._connect_cm is None


async def test_app_unmount_closes_the_websocket_session():
    # Reproduces the reviewer's finding: ctrl+q (mapped to Textual's built-in
    # `quit` action) tore the app down without closing the websocket, because
    # HermesSession.connect() never kept the context manager needed to close
    # it. on_unmount now calls session.close() for real HermesSession
    # instances. We mount with a FakeSession (so on_mount doesn't attempt a
    # real network connection), then swap in a HermesSession wired to a fake
    # connect context manager and drive on_unmount directly, since Pilot
    # doesn't expose a bare unmount hook independent of app.run_test()'s own
    # teardown.
    app = HermesStreamingApp(session_factory=lambda: FakeSession())
    async with app.run_test():
        real_session = HermesSession(args=None)
        fake_cm = FakeConnectContextManager()
        real_session._connect_cm = fake_cm
        app.session = real_session

        await app.on_unmount()

        assert fake_cm.aexit_called_with == (None, None, None)
        assert real_session._connect_cm is None


async def test_voice_binding_is_registered():
    # NOTE: app._bindings is Textual's internal BindingsMap. In the
    # installed version (8.2.8) iterating it yields (key, Binding) tuples,
    # not bare Binding objects, so the brief's `binding.key for binding in
    # app._bindings` would raise AttributeError on the tuple. We unpack the
    # tuple and read Binding.action to prove ctrl+r is actually wired to
    # the voice-turn action (not just present as a key).
    app = HermesStreamingApp(session_factory=lambda: FakeSession())
    async with app.run_test():
        bindings_by_key = {key: binding for key, binding in app._bindings}
        assert "ctrl+r" in bindings_by_key
        assert bindings_by_key["ctrl+r"].action == "voice_turn"
