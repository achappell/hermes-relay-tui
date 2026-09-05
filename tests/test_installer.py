from __future__ import annotations

from types import SimpleNamespace

import installer


def test_install_defaults_to_all_optional_support(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(installer, "_source_root", lambda: tmp_path)

    def run(command, *, cwd):
        calls.append((command, cwd))
        return SimpleNamespace(returncode=0)

    output = []
    assert installer.run_install([], runner=run, output_fn=output.append) == 0
    assert calls == [
        (
            [
                installer.sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                ".[home]",
            ],
            str(tmp_path),
        )
    ]
    assert "all optional" in output[0]
    assert output[-1].startswith("Installed")


def test_install_voice_only_uses_the_voice_extra(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(installer, "_source_root", lambda: tmp_path)

    def run(command, *, cwd):
        calls.append((command, cwd))
        return SimpleNamespace(returncode=0)

    assert installer.run_install(["voice"], runner=run, output_fn=lambda _: None) == 0
    assert calls[0][0][-1] == ".[voice]"
    assert calls[0][1] == str(tmp_path)


def test_installed_install_targets_the_current_package_version(monkeypatch):
    calls = []
    monkeypatch.setattr(installer, "_source_root", lambda: None)
    monkeypatch.setattr(installer, "version", lambda name: "0.7.0")

    def run(command, *, cwd):
        calls.append((command, cwd))
        return SimpleNamespace(returncode=0)

    assert installer.run_install(["voice"], runner=run, output_fn=lambda _: None) == 0
    assert calls == [
        (
            [
                installer.sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "hermes-relay-tui[voice]==0.7.0",
            ],
            None,
        )
    ]


def test_install_returns_pip_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "_source_root", lambda: tmp_path)

    def run(command, *, cwd):
        return SimpleNamespace(returncode=17)

    output = []
    assert installer.run_install(["voice"], runner=run, output_fn=output.append) == 17
    assert "failed with exit code 17" in output[-1]
