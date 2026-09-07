from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import yaml

from profile_cli import run_profile_command


def _create_args(name: str, url: str, env_path: Path) -> list[str]:
    return [
        "create",
        name,
        "--url",
        url,
        "--display-name",
        name.capitalize(),
        "--client-id",
        f"{name}-client",
        "--device-id",
        "shared-device",
        "--session-id",
        f"{name}-session",
        "--profile-env",
        str(env_path),
    ]


def test_profile_cli_create_and_list_keep_token_out_of_config_and_output(tmp_path):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    output: list[str] = []

    result = run_profile_command(
        ["--config", str(config_path), *_create_args("amanda", "wss://amanda.example", env_path)],
        secret_fn=lambda prompt: "amanda-secret",
        output_fn=output.append,
    )

    assert result == 0
    assert "amanda-secret" not in config_path.read_text(encoding="utf-8")
    output.clear()
    assert run_profile_command(
        ["--config", str(config_path), "list"], output_fn=output.append
    ) == 0
    listing = "\n".join(output)
    assert "amanda" in listing
    assert "wss://amanda.example/voice-session" in listing
    assert "amanda-secret" not in listing
    assert "token configured" in listing


def test_profile_cli_edit_select_and_delete(tmp_path):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    quiet = lambda message: None
    for name, url in (("amanda", "wss://amanda.example"), ("jensen", "wss://jensen.example")):
        assert run_profile_command(
            ["--config", str(config_path), *_create_args(name, url, env_path)],
            secret_fn=lambda prompt, name=name: f"{name}-secret",
            output_fn=quiet,
        ) == 0

    assert run_profile_command(
        [
            "--config",
            str(config_path),
            "edit",
            "amanda",
            "--display-name",
            "Amanda laptop",
        ],
        secret_fn=lambda prompt: "",
        output_fn=quiet,
    ) == 0
    assert run_profile_command(
        ["--config", str(config_path), "select", "jensen"], output_fn=quiet
    ) == 0

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["active_profile"] == "jensen"
    assert saved["profiles"]["amanda"]["display_name"] == "Amanda laptop"

    assert run_profile_command(
        ["--config", str(config_path), "delete", "amanda", "--yes"], output_fn=quiet
    ) == 0
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert list(saved["profiles"]) == ["jensen"]


def test_profile_cli_delete_requires_deliberate_confirmation(tmp_path):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    run_profile_command(
        ["--config", str(config_path), *_create_args("amanda", "wss://amanda.example", env_path)],
        secret_fn=lambda prompt: "secret",
        output_fn=lambda message: None,
    )
    output: list[str] = []

    result = run_profile_command(
        ["--config", str(config_path), "delete", "amanda"], output_fn=output.append
    )

    assert result == 2
    assert "--yes" in "\n".join(output)
    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["profiles"]


def test_app_entrypoint_accepts_bare_profile_before_options(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "profiles": {
                    "amanda": {
                        "url": "wss://amanda.example/voice-session",
                        "client_id": "amanda-client",
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "app.py"),
            "amanda",
            "--config",
            str(config_path),
            "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--profile" in result.stdout
    assert "amanda" in result.stdout
