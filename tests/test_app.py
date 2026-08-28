import pytest

from app import HermesStreamingApp


class FakeSession:
    """Stands in for the worker that owns the websocket connection."""

    def __init__(self):
        self.sent_turns = []

    async def send_turn(self, text: str):
        self.sent_turns.append(text)


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
