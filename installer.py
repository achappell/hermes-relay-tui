"""Visible installation of optional Hermes Relay capabilities.

The Homebrew formula installs the typed client only. This module owns the
longer, user-requested dependency step so pip progress is visible and a voice
or appliance failure cannot leave the base install half-configured.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Callable

PROJECT_NAME = "hermes-relay-tui"
_TARGET_TO_EXTRA = {"all": "home", "home": "home", "voice": "voice"}


def _source_root() -> Path | None:
    """Return the checkout root when running from source, otherwise ``None``."""
    root = Path(__file__).resolve().parent
    return root if (root / "pyproject.toml").is_file() else None


def _requirement(extra: str) -> tuple[str, Path | None]:
    root = _source_root()
    if root is not None:
        return f".[{extra}]", root
    try:
        installed_version = version(PROJECT_NAME)
    except PackageNotFoundError:
        return f"{PROJECT_NAME}[{extra}]", None
    return f"{PROJECT_NAME}[{extra}]=={installed_version}", None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes-relay install",
        description="Install optional Hermes Relay capabilities with visible progress.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        choices=tuple(_TARGET_TO_EXTRA),
        default="all",
        help="capability set to install (default: all)",
    )
    return parser


def run_install(
    argv: list[str] | None = None,
    *,
    runner: Callable[..., Any] = subprocess.run,
    output_fn: Callable[[str], Any] = print,
) -> int:
    """Install one optional capability set and return pip's exit status."""
    args = _parser().parse_args(argv)
    extra = _TARGET_TO_EXTRA[args.target]
    requirement, cwd = _requirement(extra)
    if args.target == "voice":
        label = "voice capture and speech-to-text"
    else:
        label = "all optional voice and household appliance support"
    output_fn(f"Installing {label} ({extra} extra).")
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        requirement,
    ]
    result = runner(command, cwd=str(cwd) if cwd is not None else None)
    if result.returncode != 0:
        output_fn(f"Optional support installation failed with exit code {result.returncode}.")
        return int(result.returncode)
    output_fn(f"Installed {label}.")
    return 0


if __name__ == "__main__":  # pragma: no cover - console entry point dispatches here
    raise SystemExit(run_install())
