import history as history_module
from history import PromptHistory, history_path_for_url


def test_new_history_file_starts_empty(tmp_path):
    history = PromptHistory(tmp_path / ".hermes_history")
    assert history.entries == []


def test_append_persists_across_instances(tmp_path):
    path = tmp_path / ".hermes_history"
    first = PromptHistory(path)
    first.append("first prompt")
    first.append("second prompt")

    second = PromptHistory(path)
    assert second.entries == ["first prompt", "second prompt"]


def test_append_skips_blank_and_immediate_repeat(tmp_path):
    history = PromptHistory(tmp_path / ".hermes_history")
    history.append("same")
    history.append("same")
    history.append("   ")
    history.append("")
    assert history.entries == ["same"]


def test_multiline_prompt_round_trips(tmp_path):
    path = tmp_path / ".hermes_history"
    first = PromptHistory(path)
    first.append("line one\nline two")

    second = PromptHistory(path)
    assert second.entries == ["line one\nline two"]


def test_load_skips_corrupt_lines(tmp_path):
    path = tmp_path / ".hermes_history"
    path.write_text('"valid"\nnot json\n"also valid"\n', encoding="utf-8")
    history = PromptHistory(path)
    assert history.entries == ["valid", "also valid"]


def test_history_path_for_url_scopes_by_host_and_port():
    path = history_path_for_url("wss://media-server.local:8792/voice-session")
    assert path == history_module.DEFAULT_HISTORY_DIR / "media-server.local_8792.jsonl"


def test_history_path_for_url_differs_between_hosts():
    laptop = history_path_for_url("ws://localhost:8792/voice-session")
    media_server = history_path_for_url("wss://media-server.local:8792/voice-session")
    assert laptop != media_server


def test_history_path_for_url_falls_back_without_a_host():
    assert history_path_for_url(None) == history_module.DEFAULT_HISTORY_PATH
    assert history_path_for_url("not a url") == history_module.DEFAULT_HISTORY_PATH


def test_history_caps_entry_count(tmp_path):
    import history as history_module

    path = tmp_path / ".hermes_history"
    original_cap = history_module.MAX_HISTORY_ENTRIES
    history_module.MAX_HISTORY_ENTRIES = 3
    try:
        history = PromptHistory(path)
        for index in range(5):
            history.append(f"prompt {index}")
        assert history.entries == ["prompt 2", "prompt 3", "prompt 4"]
        reloaded = PromptHistory(path)
        assert reloaded.entries == ["prompt 2", "prompt 3", "prompt 4"]
    finally:
        history_module.MAX_HISTORY_ENTRIES = original_cap
