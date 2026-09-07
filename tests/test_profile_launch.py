from __future__ import annotations

from pathlib import Path

import yaml

import config


def test_bare_profile_launch_selects_named_relay(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "profiles": {
                    "amanda": {"url": "wss://amanda.example/voice-session"},
                    "jensen": {
                        "url": "wss://jensen.example/voice-session",
                        "client_id": "jensen-client",
                        "session_id": "jensen-session",
                    },
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    argv = ["jensen", "--config", str(config_path)]
    args = config.build_arg_parser(argv).parse_args(argv)

    assert args.profile == "jensen"
    assert args.url == "wss://jensen.example/voice-session"
    assert args.client_id == "jensen-client"
    assert args.session_id == "jensen-session"
