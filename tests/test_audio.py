# tests/test_audio.py
import sys
import types

import pytest

from audio import PCMPlayer


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
