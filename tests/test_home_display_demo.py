import asyncio

import pytest

from home_display.demo import DEMO_STEPS, run_demo
from home_display.state import DisplayStatePublisher


@pytest.mark.asyncio
async def test_demo_publishes_the_approved_state_sequence():
    publisher = DisplayStatePublisher()
    subscription = publisher.subscribe()
    await anext(subscription)

    task = asyncio.create_task(run_demo(publisher, interval=0))
    observed = [(await anext(subscription)).state for _ in DEMO_STEPS]

    await task

    assert observed == [
        "idle",
        "listening",
        "thinking",
        "speaking",
        "buffering",
        "error",
        "idle",
    ]
    assert publisher.snapshot.state == "idle"
    await subscription.aclose()
