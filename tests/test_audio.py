# tests/test_audio.py
import sys
import types
import wave
from io import BytesIO
from pathlib import Path

import pytest

from audio import PCMPlayer, audio_path, write_wav


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
    assert started["wrote"] == b"\x00\x01"

    player.close()
    assert started["stopped"] and started["closed"]
    assert not player.active


def test_start_failure_sets_failure_message(monkeypatch):
    fake_module = types.SimpleNamespace(
        RawOutputStream=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("no device"))
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_module)

    player = PCMPlayer(enabled=True)
    player.start((24000, 1, 2))
    assert not player.active
    assert player.failure == "no device"
