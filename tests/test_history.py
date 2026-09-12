import history as history_module
from history import (
    PromptHistory,
    artifact_path_for_profile,
    history_path_for_profile,
    history_path_for_url,
)


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
    path.write_text(
        '"valid"\nnot json\n123\n{"prompt": "not a string"}\n"also valid"\n',
        encoding="utf-8",
    )
    history = PromptHistory(path)
    assert history.entries == ["valid", "also valid"]


def test_load_deduplicates_non_adjacent_prompts_preserving_order(tmp_path):
    path = tmp_path / ".hermes_history"
    path.write_text('"first"\n"second"\n"first"\n"third"\n', encoding="utf-8")

    history = PromptHistory(path)

    assert history.entries == ["first", "second", "third"]


def test_load_tightens_existing_history_to_owner_only_mode(tmp_path):
    path = tmp_path / ".hermes_history"
    path.write_text('"private prompt"\n', encoding="utf-8")
    path.chmod(0o644)

    history = PromptHistory(path)

    assert history.entries == ["private prompt"]
    assert path.stat().st_mode & 0o777 == 0o600


def test_load_keeps_readable_history_when_permission_tightening_fails(tmp_path, monkeypatch):
    path = tmp_path / ".hermes_history"
    path.write_text('"private prompt"\n', encoding="utf-8")

    def fail_chmod(*_args, **_kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(history_module.os, "chmod", fail_chmod)

    assert PromptHistory(path).entries == ["private prompt"]


def test_failed_history_save_closes_temp_descriptor(tmp_path, monkeypatch):
    path = tmp_path / ".hermes_history"
    history = PromptHistory(path)
    closed: list[int] = []
    real_close = history_module.os.close

    def fail_fchmod(*_args, **_kwargs):
        raise OSError("permission denied")

    def record_close(fd):
        closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(history_module.os, "fchmod", fail_fchmod)
    monkeypatch.setattr(history_module.os, "close", record_close)

    history._save()

    assert closed


def test_profile_history_migrates_old_prompts_oldest_first_without_touching_source(tmp_path):
    legacy = tmp_path / "history.jsonl"
    original = '"first"\n"duplicate"\n123\n"duplicate"\n"last"\n'
    legacy.write_text(original, encoding="utf-8")
    destination = history_path_for_profile(
        "wss://relay.example:8792/voice-session",
        "amanda",
        configured_path=legacy,
    )

    history = PromptHistory(destination, legacy_paths=(legacy,))

    assert history.entries == ["first", "duplicate", "last"]
    assert legacy.read_text(encoding="utf-8") == original
    assert destination.read_text(encoding="utf-8").splitlines() == [
        '"first"',
        '"duplicate"',
        '"last"',
    ]


def test_history_persistence_is_owner_only(tmp_path):
    path = tmp_path / "history.jsonl"
    history = PromptHistory(path)
    history.append("private prompt")

    assert path.stat().st_mode & 0o777 == 0o600


def test_failed_history_migration_keeps_entries_in_memory_and_source_usable(
    tmp_path, monkeypatch
):
    legacy = tmp_path / "history.jsonl"
    original = '"legacy prompt"\n'
    legacy.write_text(original, encoding="utf-8")
    destination = tmp_path / "profiles" / "amanda" / "history.jsonl"

    def fail_replace(*_args, **_kwargs):
        raise OSError("history destination unavailable")

    monkeypatch.setattr(history_module.os, "replace", fail_replace)
    history = PromptHistory(destination, legacy_paths=(legacy,))

    assert history.entries == ["legacy prompt"]
    assert not destination.exists()
    assert legacy.read_text(encoding="utf-8") == original


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


def test_profile_history_is_namespaced_under_the_profile_name():
    amanda = history_path_for_profile(
        "wss://relay.example:8792/voice-session", "amanda"
    )
    jensen = history_path_for_profile(
        "wss://relay.example:8792/voice-session", "jensen"
    )

    assert amanda == history_module.DEFAULT_HISTORY_DIR / "profiles" / "amanda" / "relay.example_8792.jsonl"
    assert jensen != amanda


def test_legacy_profile_keeps_existing_history_path():
    configured = history_module.DEFAULT_HISTORY_DIR / "legacy.jsonl"
    assert history_path_for_profile(
        "wss://relay.example/voice-session",
        "default",
        configured_path=configured,
        legacy=True,
    ) == configured


def test_profile_artifact_path_namespaces_an_explicit_path():
    path = artifact_path_for_profile(
        history_module.DEFAULT_APP_DIR / "transcripts" / "reply.wav",
        "amanda",
    )
    assert path == history_module.DEFAULT_APP_DIR / "transcripts" / "profiles" / "amanda" / "reply.wav"


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
