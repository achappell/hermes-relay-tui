import pytest

from mic import load_microphone_class


def test_missing_voice_client_raises(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        load_microphone_class(tmp_path)


def test_loads_local_microphone_class(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "voice-session-client.py").write_text(
        "class LocalMicrophone:\n"
        "    def __init__(self, **kwargs):\n"
        "        self.kwargs = kwargs\n"
        "    def capture(self):\n"
        "        return 'hello'\n"
        "    def close(self):\n"
        "        pass\n"
    )

    microphone_class = load_microphone_class(tmp_path)
    instance = microphone_class(max_seconds=5.0)
    assert instance.capture() == "hello"
