"""VOICE-11: an open microphone is visible, not remembered.

The TUI can hold the input device open indefinitely once `/wake on` is used.
The only thing standing between that and a surprise is whether the surface
says so, so these tests are about what is on screen rather than what is armed.
"""

import app as app_module

from tests.test_app_wake import WakeFakes, make_app


from tests.test_app import voice_status_of as status_line


async def test_the_indicator_is_absent_until_wake_mode_is_armed():
    app, _, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()

        assert app_module.MIC_OPEN_LABEL not in status_line(app)


async def test_arming_shows_the_indicator_immediately():
    """Arming from idle does not change the voice state, so a surface that
    only repaints on a state change would stay silent about an open
    microphone — which is the entire failure this card exists to prevent."""
    app, _, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

        assert app_module.MIC_OPEN_LABEL in status_line(app)


async def test_disarming_clears_it_immediately():
    app, _, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        await app._handle_wake_command("off")

        assert app_module.MIC_OPEN_LABEL not in status_line(app)


async def test_the_indicator_survives_every_state_of_a_turn():
    """The device is held throughout. An indicator that vanishes while the
    unit thinks or speaks is telling the user the microphone closed."""
    app, _, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

        for state in (
            app_module.VOICE_LISTENING,
            app_module.VOICE_TRANSCRIBING,
            app_module.VOICE_THINKING,
            app_module.VOICE_SPEAKING,
            app_module.VOICE_BUFFERING,
            app_module.VOICE_READY,
        ):
            app._set_voice_state(state)
            line = status_line(app)
            assert state in line, f"{state} should still be reported"
            assert app_module.MIC_OPEN_LABEL in line, (
                f"the microphone is still open during {state}"
            )


async def test_the_indicator_is_not_confusable_with_listening():
    """`listening…` means a capture is running right now; the indicator means
    the device is held. Two different facts, and the card requires they be
    distinguishable."""
    app, _, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        app._set_voice_state(app_module.VOICE_READY)

        line = status_line(app)

        assert app_module.VOICE_LISTENING not in line
        assert app_module.MIC_OPEN_LABEL in line


async def test_a_failed_arm_leaves_no_indicator():
    """If wake mode could not start, the microphone is not open and the
    surface must not claim it is."""
    app, _, _ = make_app(fakes=WakeFakes(available=False))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")

        assert app.wake_armed is False
        assert app_module.MIC_OPEN_LABEL not in status_line(app)


async def test_the_indicator_renders_as_colour_not_as_literal_markup():
    """A broken style tag still contains the words, so every assertion above
    would pass while the user saw `[$warning]◉ mic open[/]` on screen."""
    from textual.widgets import Static

    app, _, _ = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._handle_wake_command("on")
        await pilot.pause()

        widget = app.query_one("#voice-status", Static)
        segments = list(widget.render_line(0))
        rendered = "".join(segment.text for segment in segments)

        assert "[" not in rendered and "]" not in rendered
        colours = {
            segment.style.color.name
            for segment in segments
            if segment.style is not None and segment.style.color is not None
        }
        assert len(colours) > 1, "the indicator must not share the muted state colour"
