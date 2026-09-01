import asyncio

import pytest

from home_display.state import DisplaySnapshot, DisplayStatePublisher


def test_initial_snapshot_is_idle_and_json_safe():
    assert DisplayStatePublisher().snapshot.to_dict() == {
        "type": "snapshot", "schema": 1, "sequence": 0,
        "state": "idle", "response_text": "", "status_text": None,
        "media": None,
    }


def test_snapshot_rejects_unknown_state_and_negative_sequence():
    with pytest.raises(ValueError, match="state"):
        DisplaySnapshot(sequence=0, state="unknown")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sequence"):
        DisplaySnapshot(sequence=-1, state="idle")


def test_snapshot_rejects_unknown_schema_version():
    with pytest.raises(ValueError, match="schema"):
        DisplaySnapshot(schema=2)


def test_publisher_rejects_non_json_serializable_media():
    with pytest.raises(ValueError, match="media"):
        DisplayStatePublisher().publish(
            state="idle", media={"provider": object()}
        )


@pytest.mark.asyncio
async def test_subscriber_starts_current_and_receives_newest_update():
    publisher = DisplayStatePublisher()
    publisher.publish(state="speaking", response_text="hello")
    subscription = publisher.subscribe()
    assert (await anext(subscription)).sequence == 1
    publisher.publish(state="thinking", status_text="working")
    received = await asyncio.wait_for(anext(subscription), timeout=0.2)
    assert received.state == "thinking"
    await subscription.aclose()
