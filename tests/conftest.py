import pytest

import config as config_module
import history as history_module


@pytest.fixture(autouse=True)
def isolated_history_path(tmp_path, monkeypatch):
    """Never let a test touch Amanda's real ~/.hermes history files."""
    monkeypatch.setattr(history_module, "DEFAULT_HISTORY_PATH", tmp_path / ".hermes_history")
    monkeypatch.setattr(history_module, "DEFAULT_HISTORY_DIR", tmp_path / "history")


@pytest.fixture(autouse=True)
def isolated_config_path(tmp_path, monkeypatch):
    """Never let a test load Amanda's real ~/.hermes-relay-tui/config.yaml.

    Points at a path that doesn't exist by default, so build_arg_parser()'s
    config-file layer resolves to {} unless a test explicitly writes one.
    """
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.delenv("HERMES_RELAY_TUI_CONFIG", raising=False)
