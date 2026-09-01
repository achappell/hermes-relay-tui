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
    seen = []
    coordinator, _, _, _ = _coordinator(on_state_change=seen.append)

    coordinator.on_wake()

    assert seen == [handsfree.CAPTURING, handsfree.SENDING, handsfree.IDLE]


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
