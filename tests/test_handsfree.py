"""The state machine, driven by a fake session and a fake capture. No audio,
no model, no network."""

import handsfree


class FakeSession:
    def __init__(self):
        self.turns = []

    def send_turn(self, text, *, stt_source="local"):
        self.turns.append((text, stt_source))


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def _coordinator(transcript="what is the weather", **kwargs):
    session = FakeSession()
    clock = kwargs.pop("clock", Clock())
    captures = []

    def capture():
        captures.append(True)
        return transcript

    kwargs.setdefault("capture", capture)
    kwargs.setdefault("send", lambda text: session.send_turn(text))
    coordinator = handsfree.HandsFreeCoordinator(session, now=clock, **kwargs)
    return coordinator, session, captures, clock


def test_a_detection_produces_exactly_one_capture_and_one_turn():
    coordinator, session, captures, _ = _coordinator()

    assert coordinator.on_wake() is True

    assert len(captures) == 1
    assert session.turns == [("what is the weather", "local")]
    assert coordinator.state == handsfree.IDLE


def test_a_wake_turn_accepts_one_follow_up_without_another_wake():
    session = FakeSession()
    captures = []

    def capture():
        captures.append("wake")
        return "what is the weather"

    def capture_follow_up():
        captures.append("follow-up")
        return "and tomorrow"

    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=capture,
        send=lambda text: session.send_turn(text),
        follow_up_capture=capture_follow_up,
    )

    assert coordinator.on_wake() is True

    assert captures == ["wake", "follow-up"]
    assert session.turns == [
        ("what is the weather", "local"),
        ("and tomorrow", "local"),
    ]
    assert coordinator.state == handsfree.IDLE


def test_silence_in_the_follow_up_window_returns_to_wake_listening():
    session = FakeSession()
    follow_up_captures = []

    def capture_follow_up():
        follow_up_captures.append(True)
        return ""

    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=lambda: "what is the weather",
        send=lambda text: session.send_turn(text),
        follow_up_capture=capture_follow_up,
    )

    assert coordinator.on_wake() is True

    assert follow_up_captures == [True]
    assert session.turns == [("what is the weather", "local")]
    assert coordinator.state == handsfree.IDLE


def test_detections_during_a_capture_do_not_stack_turns():
    """Repeated detections during an active capture must be dropped, not
    queued: queuing them is how a single utterance becomes three turns."""
    session = FakeSession()
    captures = []

    def capture():
        captures.append(True)
        # A second detection arriving mid-capture must be refused.
        assert coordinator.on_wake() is False
        return "hello"

    coordinator = handsfree.HandsFreeCoordinator(
        session, capture=capture, send=lambda text: session.send_turn(text)
    )

    coordinator.on_wake()

    assert len(captures) == 1
    assert len(session.turns) == 1


def test_an_empty_transcript_is_dropped_and_never_sent():
    coordinator, session, _, _ = _coordinator(transcript="")

    coordinator.on_wake()

    assert session.turns == []
    assert coordinator.state == handsfree.IDLE


def test_a_whitespace_transcript_is_dropped():
    coordinator, session, _, _ = _coordinator(transcript="   \n ")
    coordinator.on_wake()
    assert session.turns == []


def test_a_hallucinated_transcript_is_dropped():
    """A misfire on an extractor fan transcribes as 'Thank you.' — voice.py
    already knows how to recognise that."""
    coordinator, session, _, _ = _coordinator(
        transcript="Thank you.", is_hallucination=lambda text: text == "Thank you."
    )

    coordinator.on_wake()

    assert session.turns == []


def test_the_listening_window_expires_and_never_calls_the_session():
    """The product rule: a misfire at 2am must not wake the house."""
    session = FakeSession()
    clock = Clock()
    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=lambda: "ignored",
        send=lambda text: session.send_turn(text),
        listen_timeout=8.0,
        speech_detected=lambda: False,
        now=clock,
    )
    coordinator._begin_capture_for_test()

    clock.advance(9.0)
    coordinator.tick()

    assert session.turns == []
    assert coordinator.state == handsfree.IDLE


def test_speech_before_the_window_expires_disarms_it():
    session = FakeSession()
    clock = Clock()
    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=lambda: "ignored",
        send=lambda text: session.send_turn(text),
        listen_timeout=8.0,
        speech_detected=lambda: True,
        now=clock,
    )
    coordinator._begin_capture_for_test()

    clock.advance(9.0)
    coordinator.tick()

    assert coordinator.state == handsfree.CAPTURING


def test_the_window_does_not_expire_early():
    session = FakeSession()
    clock = Clock()
    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=lambda: "ignored",
        send=lambda text: session.send_turn(text),
        listen_timeout=8.0,
        speech_detected=lambda: False,
        now=clock,
    )
    coordinator._begin_capture_for_test()

    clock.advance(7.0)
    coordinator.tick()

    assert coordinator.state == handsfree.CAPTURING


def test_state_changes_are_reported():
    """ACKNOWLEDGING is reported even with no acknowledgement wired: the phase
    is real either way — the turn is claimed and the microphone is still
    shut — and a front end that shows CAPTURING there is claiming to listen
    through a closed microphone."""
    seen = []
    coordinator, _, _, _ = _coordinator(on_state_change=seen.append)

    coordinator.on_wake()

    assert seen == [
        handsfree.ACKNOWLEDGING,
        handsfree.CAPTURING,
        handsfree.SENDING,
        handsfree.IDLE,
    ]


def test_barge_in_is_off_by_default():
    coordinator, _, captures, _ = _coordinator()
    coordinator.playback_started()

    assert coordinator.state == handsfree.SPEAKING
    assert coordinator.on_wake() is False
    assert captures == []


def test_barge_in_stops_playback_then_captures():
    stopped = []
    coordinator, session, captures, _ = _coordinator(
        barge_in=True, stop_playback=lambda: stopped.append(True)
    )
    coordinator.playback_started()

    assert coordinator.on_wake() is True

    assert stopped == [True]
    assert len(captures) == 1
    assert len(session.turns) == 1


def test_playback_finished_returns_to_idle():
    coordinator, _, _, _ = _coordinator()
    coordinator.playback_started()
    coordinator.playback_finished()
    assert coordinator.state == handsfree.IDLE


def test_without_playback_wiring_the_unit_never_enters_speaking():
    """The appliance loop owns playback. With nothing injected the machine
    reduces to the three states this slice can exercise on its own."""
    coordinator, _, _, _ = _coordinator()
    assert coordinator.state == handsfree.IDLE
    coordinator.on_wake()
    assert coordinator.state == handsfree.IDLE


def test_a_capture_failure_returns_to_idle_silently():
    def capture():
        raise RuntimeError("transcription exploded")

    session = FakeSession()
    coordinator = handsfree.HandsFreeCoordinator(
        session, capture=capture, send=lambda text: session.send_turn(text)
    )

    assert coordinator.on_wake() is False
    assert session.turns == []
    assert coordinator.state == handsfree.IDLE


def test_playback_during_a_turn_makes_speaking_a_real_state():
    """Response audio arrives while the turn is still streaming, so the
    appliance calls playback_started from SENDING, not from idle."""
    seen = []
    session = FakeSession()

    def send(text):
        session.send_turn(text)
        coordinator.playback_started()
        seen.append(("during-playback", coordinator.state))
        coordinator.playback_finished()

    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=lambda: "what is the weather",
        send=send,
        on_state_change=lambda state: seen.append(state),
    )

    assert coordinator.on_wake() is True

    assert ("during-playback", handsfree.SPEAKING) in seen
    assert coordinator.state == handsfree.IDLE


def test_a_detection_while_the_answer_is_playing_is_still_refused():
    """Barge-in stays gated off until echo cancellation exists: the unit would
    otherwise wake itself on its own voice."""
    session = FakeSession()
    captures = []

    def send(text):
        session.send_turn(text)
        coordinator.playback_started()
        assert coordinator.on_wake() is False

    def capture():
        captures.append(True)
        return "what is the weather"

    coordinator = handsfree.HandsFreeCoordinator(session, capture=capture, send=send)

    coordinator.on_wake()

    assert captures == [True]
    assert len(session.turns) == 1


# ---- acknowledgement (HOME-10) ---------------------------------------


def _ordered(transcript="what is the weather", **kwargs):
    """A coordinator that records acknowledgement and capture in one order."""
    session = FakeSession()
    events = []

    def capture():
        events.append("capture")
        return transcript

    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=capture,
        send=lambda text: session.send_turn(text),
        acknowledge=lambda: events.append("acknowledge"),
        capture_finished=lambda: events.append("capture_finished"),
        **kwargs,
    )
    return coordinator, session, events


def test_the_wake_is_acknowledged_before_the_microphone_opens():
    """The whole ordering guarantee. The acknowledgement blocks, so a chirp
    can never end up inside the recording it is announcing."""
    coordinator, _, events = _ordered()

    coordinator.on_wake()

    assert events.index("acknowledge") < events.index("capture")


def test_the_full_acknowledgement_order_for_a_real_turn():
    coordinator, session, events = _ordered()

    coordinator.on_wake()

    assert events == ["acknowledge", "capture", "capture_finished"]
    assert session.turns == [("what is the weather", "local")]


def test_end_of_capture_is_announced_before_the_turn_is_sent():
    """The sound means "I have stopped listening and started working", so it
    has to land before the work, not after it."""
    session = FakeSession()
    events = []

    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=lambda: "hello",
        send=lambda text: events.append("send"),
        capture_finished=lambda: events.append("capture_finished"),
    )

    coordinator.on_wake()

    assert events == ["capture_finished", "send"]


def test_a_dropped_detection_is_not_acknowledged():
    """Single-flight refuses a detection during a turn. Chirping at one would
    tell the room something happened when nothing did."""
    session = FakeSession()
    events = []
    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=lambda: "hello",
        send=lambda text: None,
        acknowledge=lambda: events.append("acknowledge"),
    )
    coordinator.playback_started()

    assert coordinator.on_wake() is False

    assert events == []


def test_a_silent_misfire_acknowledges_the_wake_and_then_says_nothing():
    """The card's misfire rule: it heard something, it withdrew, it never
    claimed to be working."""
    coordinator, session, events = _ordered(transcript="")

    coordinator.on_wake()

    assert events == ["acknowledge", "capture"]
    assert session.turns == []
    assert coordinator.state == handsfree.IDLE


def test_a_hallucinated_transcript_does_not_announce_work():
    coordinator, session, events = _ordered(
        transcript="Thank you.", is_hallucination=lambda text: text == "Thank you."
    )

    coordinator.on_wake()

    assert "capture_finished" not in events
    assert session.turns == []


def test_a_failed_capture_does_not_announce_work():
    session = FakeSession()
    events = []

    def capture():
        raise RuntimeError("the microphone went away")

    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=capture,
        send=lambda text: None,
        acknowledge=lambda: events.append("acknowledge"),
        capture_finished=lambda: events.append("capture_finished"),
    )

    assert coordinator.on_wake() is False

    assert events == ["acknowledge"]
    assert coordinator.state == handsfree.IDLE


def test_an_expired_listening_window_never_announces_work():
    session = FakeSession()
    clock = Clock()
    events = []
    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=lambda: "ignored",
        send=lambda text: session.send_turn(text),
        capture_finished=lambda: events.append("capture_finished"),
        listen_timeout=8.0,
        speech_detected=lambda: False,
        now=clock,
    )
    coordinator._begin_capture_for_test()

    clock.advance(9.0)
    coordinator.tick()

    assert events == []


def test_a_failing_acknowledgement_never_costs_the_turn():
    """A chirp is a courtesy. A dead speaker must not eat the question."""
    session = FakeSession()

    def explode():
        raise RuntimeError("no output device")

    coordinator = handsfree.HandsFreeCoordinator(
        session,
        capture=lambda: "what is the weather",
        send=lambda text: session.send_turn(text),
        acknowledge=explode,
        capture_finished=explode,
    )

    assert coordinator.on_wake() is True

    assert session.turns == [("what is the weather", "local")]


def test_the_coordinator_works_with_no_acknowledgement_wiring():
    """Earcons are optional. With nothing injected the machine is unchanged."""
    coordinator, session, _, _ = _coordinator()

    assert coordinator.on_wake() is True
    assert session.turns == [("what is the weather", "local")]
