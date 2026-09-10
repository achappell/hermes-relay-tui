import asyncio

import pytest

from home_display.demo import DEMO_CAPABILITIES, DEMO_PROMPT, DEMO_STEPS, run_demo, run_prompt_demo
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


@pytest.mark.asyncio
async def test_prompt_demo_publishes_a_direct_use_capability():
    publisher = DisplayStatePublisher()
    subscription = publisher.subscribe()
    await anext(subscription)

    task = asyncio.create_task(run_prompt_demo(publisher, interval=0))
    prompt_snapshot = await anext(subscription)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert prompt_snapshot.state == "prompt"
    assert prompt_snapshot.prompt == DEMO_PROMPT
    assert prompt_snapshot.capabilities == DEMO_CAPABILITIES
    await subscription.aclose()
