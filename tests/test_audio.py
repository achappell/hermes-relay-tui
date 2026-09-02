# tests/test_audio.py
import sys
import types
import wave
from io import BytesIO
from pathlib import Path

import pytest

from audio import PCMPlayer, audio_device_list, audio_path, write_wav


def test_audio_path_uses_the_base_unchanged_for_the_first_turn(tmp_path):
    base = tmp_path / "reply.wav"
    assert audio_path(base, 0, "t0") == base


def test_audio_path_suffixes_later_turns(tmp_path):
    base = tmp_path / "reply.wav"
    assert audio_path(base, 2, "t2") == tmp_path / "reply-2.wav"


def test_audio_path_without_a_base_falls_back_to_the_turn_id():
    assert audio_path(None, 3, "abc123") == Path.cwd() / "hybrid-tui-abc123.wav"


def test_write_wav_creates_parent_directories_and_a_readable_file(tmp_path):
    target = tmp_path / "nested" / "out.wav"
    write_wav(target, b"\x00\x01\x02\x03", (24000, 1, 2))

    with wave.open(str(target), "rb") as handle:
        assert handle.getframerate() == 24000
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.readframes(2) == b"\x00\x01\x02\x03"


def test_read_wav_returns_pcm_and_format():
    from audio import read_wav

    source = BytesIO()
    with wave.open(source, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x01\x02\x03")

    assert read_wav(source.getvalue()) == (b"\x00\x01\x02\x03", (16000, 1, 2))


def test_disabled_player_never_starts():
    player = PCMPlayer(enabled=False)
    player.start((24000, 1, 2))
    assert not player.active
    assert player.failure is None


def test_unsupported_sample_width_records_failure():
    player = PCMPlayer(enabled=True)
    player.start((24000, 1, 1))  # 8-bit, unsupported
    assert not player.active
    assert "8-bit" in player.failure


def test_start_success_makes_player_active(monkeypatch):
    started = {}

    class FakeStream:
        def start(self):
            started["started"] = True

        def write(self, chunk):
            started["wrote"] = chunk

        def stop(self):
            started["stopped"] = True

        def close(self):
            started["closed"] = True

    fake_module = types.SimpleNamespace(
        RawOutputStream=lambda **kwargs: FakeStream()
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_module)

    player = PCMPlayer(enabled=True)
    player.start((24000, 1, 2))
    assert player.active

    player.write(b"\x00\x01")
    player.close()  # shorter than the cushion, so it flushes on close
    assert started["wrote"] == b"\x00\x01"

    assert started["stopped"] and started["closed"]
    assert not player.active


def test_start_passes_selected_output_device_to_sounddevice(monkeypatch):
    received = {}

    class FakeStream:
        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    def raw_output_stream(**kwargs):
        received.update(kwargs)
        return FakeStream()

    fake_module = types.SimpleNamespace(RawOutputStream=raw_output_stream)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_module)

    player = PCMPlayer(enabled=True, output_device="USB Headset")
    player.start((24000, 1, 2))

    assert received["device"] == "USB Headset"


def test_audio_device_list_normalizes_input_and_output_capabilities(monkeypatch):
    fake_module = types.SimpleNamespace(
        query_devices=lambda: [
            {"name": "Built-in Microphone", "max_input_channels": 2, "max_output_channels": 0},
            {"name": "USB Headset", "max_input_channels": 1, "max_output_channels": 2},
        ]
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_module)

    assert audio_device_list() == [
        {"index": 0, "name": "Built-in Microphone", "inputs": 2, "outputs": 0},
        {"index": 1, "name": "USB Headset", "inputs": 1, "outputs": 2},
    ]


def test_start_failure_sets_failure_message(monkeypatch):
    fake_module = types.SimpleNamespace(
        RawOutputStream=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("no device"))
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_module)

    player = PCMPlayer(enabled=True)
    player.start((24000, 1, 2))
    assert not player.active
    assert player.failure == "no device"


# --- prebuffering -----------------------------------------------------------
#
# Measured against a live gateway: 14 of 19 chunks arrived slower than they
# play — 379ms of audio every ~470ms. With no cushion the device runs dry
# between chunks, and every underrun is an audible pop.


def _fake_stream(monkeypatch, log):
    class FakeStream:
        def start(self):
            log.append(("start",))

        def write(self, chunk):
            log.append(("write", bytes(chunk)))

        def stop(self):
            log.append(("stop",))

        def close(self):
            log.append(("close",))

    received = {}

    def raw_output_stream(**kwargs):
        received.update(kwargs)
        return FakeStream()

    monkeypatch.setitem(
        sys.modules, "sounddevice", types.SimpleNamespace(RawOutputStream=raw_output_stream)
    )
    return received


def test_playback_holds_a_cushion_before_the_first_sample(monkeypatch):
    log = []
    _fake_stream(monkeypatch, log)

    # 24kHz mono 16-bit: 48 bytes per millisecond.
    player = PCMPlayer(enabled=True, prebuffer_seconds=0.01)  # 480 bytes
    player.start((24000, 1, 2))

    player.write(b"\x00" * 200)
    assert player.playing is False
    assert ("write", b"\x00" * 200) not in log

    player.write(b"\x01" * 400)

    # The cushion is full: everything buffered goes out in one write, and the
    # player is only now actually making a sound.
    assert player.playing is True
    assert ("write", b"\x00" * 200 + b"\x01" * 400) in log


def test_audio_shorter_than_the_cushion_is_still_played(monkeypatch):
    """A one-word reply must not be swallowed by the buffer."""
    log = []
    _fake_stream(monkeypatch, log)

    player = PCMPlayer(enabled=True, prebuffer_seconds=1.0)
    player.start((24000, 1, 2))
    player.write(b"\x07" * 100)
    assert player.playing is False

    player.close()

    assert ("write", b"\x07" * 100) in log
    assert log.index(("write", b"\x07" * 100)) < log.index(("stop",))


def test_the_output_stream_is_not_opened_at_minimum_latency(monkeypatch):
    """`latency="low"` asks PortAudio for the smallest possible buffer, which
    is precisely the wrong request for audio arriving off a network."""
    log = []
    received = _fake_stream(monkeypatch, log)

    PCMPlayer(enabled=True).start((24000, 1, 2))

    assert received.get("latency") != "low"


def test_starting_again_closes_a_stream_that_is_still_playing(monkeypatch):
    """Some gateways never send `audio_end`, so a stream can still be open and
    draining when the next turn begins. Replacing it silently orphans it and
    cuts off whatever was left to play."""
    log = []
    _fake_stream(monkeypatch, log)

    player = PCMPlayer(enabled=True)
    player.start((24000, 1, 2))
    player.start((24000, 1, 2))

    assert log.count(("stop",)) == 1, log
    assert log.count(("close",)) == 1, log
