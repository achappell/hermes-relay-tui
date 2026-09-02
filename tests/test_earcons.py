"""Earcon synthesis and playback, with no audio hardware anywhere in sight.

The tones are generated rather than shipped, so these tests are the only thing
standing between a considered sound and a click in the kitchen.
"""

import struct

import pytest

import earcons


def samples(pcm: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(pcm) // 2}h", pcm))


class FakeStream:
    """Stands in for a sounddevice RawOutputStream."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.written = bytearray()
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self):
        self.started = True

    def write(self, chunk):
        self.written.extend(chunk)

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class Opener:
    def __init__(self, stream_factory=FakeStream):
        self.streams = []
        self._factory = stream_factory

    def __call__(self, **kwargs):
        stream = self._factory(**kwargs)
        self.streams.append(stream)
        return stream


# ---- synthesis -------------------------------------------------------


@pytest.mark.parametrize("name", [earcons.WAKE, earcons.CAPTURE_DONE])
def test_every_earcon_renders_signed_16_bit_mono_pcm(name):
    pcm = earcons.render(name)

    assert len(pcm) % 2 == 0
    assert pcm, "an earcon that renders to nothing is a silent acknowledgement"
    values = samples(pcm)
    assert all(-32768 <= value <= 32767 for value in values)


@pytest.mark.parametrize("name", [earcons.WAKE, earcons.CAPTURE_DONE])
def test_earcons_start_and_end_at_silence(name):
    """A tone that begins at full amplitude is a click.

    The whole point of this card is that the unit stops making unpleasant
    noises at people, so an earcon with a hard edge is a regression on the two
    playback fixes that came before it.
    """
    values = samples(earcons.render(name))

    assert abs(values[0]) < 64
    assert abs(values[-1]) < 64


@pytest.mark.parametrize("name", [earcons.WAKE, earcons.CAPTURE_DONE])
def test_earcons_are_short_enough_to_stay_out_of_the_way(name):
    """The wake earcon is paid for twice: once as sound, once as the delay
    before the microphone opens. It has a budget."""
    pcm = earcons.render(name)
    seconds = len(pcm) / 2 / earcons.SAMPLE_RATE

    assert 0.05 <= seconds <= 0.25


def test_the_wake_earcon_is_distinct_from_the_capture_earcon():
    """Someone in the next room has to tell 'it heard me' from 'it is
    working' by ear alone."""
    assert earcons.render(earcons.WAKE) != earcons.render(earcons.CAPTURE_DONE)


def test_an_unknown_earcon_is_an_error_not_a_silence():
    with pytest.raises(KeyError):
        earcons.render("nonexistent")


def test_rendering_is_cached_so_a_wake_never_waits_on_numpy():
    assert earcons.render(earcons.WAKE) is earcons.render(earcons.WAKE)


# ---- playback --------------------------------------------------------


def test_playing_opens_writes_and_closes_one_stream():
    opener = Opener()
    player = earcons.EarconPlayer(enabled=True, open_stream=opener)

    player.play(earcons.WAKE)

    assert len(opener.streams) == 1
    stream = opener.streams[0]
    assert stream.started and stream.stopped and stream.closed
    assert bytes(stream.written) == earcons.render(earcons.WAKE)


def test_playback_blocks_until_the_tone_is_out():
    """The microphone opens as soon as play() returns, so returning early
    would put the chirp inside the recording."""
    opener = Opener()
    player = earcons.EarconPlayer(enabled=True, open_stream=opener)

    player.play(earcons.WAKE)

    stream = opener.streams[0]
    assert stream.stopped, "stop() drains the device; play() must wait for it"


def test_a_disabled_player_opens_nothing():
    opener = Opener()
    player = earcons.EarconPlayer(enabled=False, open_stream=opener)

    player.play(earcons.WAKE)

    assert opener.streams == []


def test_the_output_device_is_passed_through_when_set():
    opener = Opener()
    player = earcons.EarconPlayer(
        enabled=True, output_device="Kitchen Speaker", open_stream=opener
    )

    player.play(earcons.WAKE)

    assert opener.streams[0].kwargs["device"] == "Kitchen Speaker"


def test_no_device_key_is_sent_when_none_is_configured():
    opener = Opener()
    player = earcons.EarconPlayer(enabled=True, open_stream=opener)

    player.play(earcons.WAKE)

    assert "device" not in opener.streams[0].kwargs


def test_a_failed_earcon_never_breaks_the_turn():
    """A chirp is a courtesy. Losing the speaker must not lose the answer."""

    def explode(**kwargs):
        raise RuntimeError("no output device")

    player = earcons.EarconPlayer(enabled=True, open_stream=explode)

    player.play(earcons.WAKE)  # must not raise

    assert player.failure == "no output device"


def test_a_stream_that_fails_mid_write_is_still_closed():
    class BrokenStream(FakeStream):
        def write(self, chunk):
            raise RuntimeError("device went away")

    opener = Opener(BrokenStream)
    player = earcons.EarconPlayer(enabled=True, open_stream=opener)

    player.play(earcons.WAKE)

    assert opener.streams[0].closed, "a leaked stream holds the device open"
    assert player.failure == "device went away"
