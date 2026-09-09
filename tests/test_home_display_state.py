import asyncio
import json

import pytest

from home_display.state import (
    DisplayCapabilities,
    DisplayPrompt,
    DisplaySnapshot,
    DisplayStatePublisher,
    PromptOption,
)


def test_initial_snapshot_is_idle_and_json_safe():
    assert DisplayStatePublisher().snapshot.to_dict() == {
        "type": "snapshot", "schema": 1, "sequence": 0,
        "state": "idle", "response_text": "", "status_text": None,
        "media": None, "prompt": None,
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


def test_published_snapshot_is_not_affected_by_media_mutation():
    publisher = DisplayStatePublisher()
    media = {"provider": "future", "options": {"limit": 1}}
    snapshot = publisher.publish(state="idle", media=media)

    media["provider"] = object()
    media["options"]["limit"] = object()

    serialized = json.dumps(snapshot.to_dict(), allow_nan=False)
    assert json.loads(serialized)["media"] == {
        "provider": "future",
        "options": {"limit": 1},
    }


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


def test_heard_is_a_valid_display_state():
    """The moment between the phrase landing and the microphone opening."""
    snapshot = DisplaySnapshot(state="heard")
    assert snapshot.state == "heard"
    assert snapshot.to_dict()["state"] == "heard"


def test_prompt_snapshot_advertises_the_browser_choice_capability():
    prompt = DisplayPrompt(
        kind="confirm",
        title="Set home?",
        body="Use this display as home?",
        options=(PromptOption(id="yes", label="Yes"),),
        action_id="sethome",
    )

    snapshot = DisplayStatePublisher().publish(state="prompt", prompt=prompt)

    assert snapshot.to_dict()["capabilities"] == {
        "actions": ["prompt.choose"],
        "features": ["prompt_overlay"],
    }


def test_hands_free_capabilities_serialize_only_non_secret_configuration():
    capabilities = DisplayCapabilities(
        features=("browser_voice", "browser_hands_free"),
        wake_phrases=("hey hermes", "hello hermes"),
        wake_listen_seconds=8.0,
        wake_followup_seconds=6.0,
    )

    assert capabilities.to_dict() == {
        "actions": [],
        "features": ["browser_voice", "browser_hands_free"],
        "wake_phrases": ["hey hermes", "hello hermes"],
        "wake_listen_seconds": 8.0,
        "wake_followup_seconds": 6.0,
    }


def test_capabilities_reject_more_than_the_browser_wake_phrase_bound():
    with pytest.raises(ValueError, match="at most 8"):
        DisplayCapabilities(wake_phrases=tuple(f"phrase {index}" for index in range(9)))
