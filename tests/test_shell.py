import shlex
import sys

import pytest

from shell import (
    ShellExecutionError,
    ShellPolicy,
    interpolate_commands,
    parse_command,
    run_command,
    standalone_command,
)


@pytest.mark.asyncio
async def test_disabled_shell_rejects_command():
    with pytest.raises(ShellExecutionError, match="disabled"):
        await run_command("printf hello", policy=ShellPolicy())


def test_parse_command_rejects_shell_operators():
    with pytest.raises(ShellExecutionError, match="operator"):
        parse_command("printf hello | cat")


def python_command(source: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(source)}"


@pytest.mark.asyncio
async def test_interpolation_returns_stdout_when_enabled():
    result = await interpolate_commands(
        "value={!" + python_command('print("ok")') + "}",
        policy=ShellPolicy(enabled=True),
    )

    assert result == "value=ok"


@pytest.mark.asyncio
async def test_nonzero_exit_prevents_interpolation():
    with pytest.raises(ShellExecutionError, match="status 3"):
        await interpolate_commands(
            "value={!" + python_command("raise SystemExit(3)") + "}",
            policy=ShellPolicy(enabled=True),
        )


@pytest.mark.asyncio
async def test_output_limit_terminates_command():
    with pytest.raises(ShellExecutionError, match="output limit"):
        await run_command(
            python_command('print("123456789")'),
            policy=ShellPolicy(enabled=True, output_limit=8),
        )


@pytest.mark.asyncio
async def test_timeout_terminates_command():
    with pytest.raises(ShellExecutionError, match="timeout"):
        await run_command(
            python_command("import time; time.sleep(0.5)"),
            policy=ShellPolicy(enabled=True, timeout_seconds=0.1),
        )


@pytest.mark.asyncio
async def test_child_does_not_receive_session_credentials(monkeypatch):
    monkeypatch.setenv("VOICE_SESSION_TOKEN", "test-token-not-for-child")

    result = await run_command(
        python_command('import os; print(os.environ.get("VOICE_SESSION_TOKEN", "missing"))'),
        policy=ShellPolicy(enabled=True),
    )

    assert result.returncode == 0
    assert result.output.strip() == "missing"


@pytest.mark.asyncio
async def test_shell_syntax_is_not_expanded():
    result = await run_command(
        "printf '$HOME'",
        policy=ShellPolicy(enabled=True),
    )

    assert result.output == "$HOME"


def test_standalone_command_only_matches_single_bang_line():
    assert standalone_command("!printf ok") == "printf ok"
    assert standalone_command("ordinary text") is None
    assert standalone_command("!printf first\nprintf second") is None
