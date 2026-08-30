"""Bounded, opt-in local shell execution for prompt preparation."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_OUTPUT_LIMIT = 64 * 1024
_FORBIDDEN_SHELL_MARKERS = frozenset("|&;<>`")
_INTERPOLATION = re.compile(r"\{!([^{}\n]+)\}")


class ShellExecutionError(ValueError):
    """Raised when a local shell command cannot be safely completed."""


@dataclass(frozen=True)
class ShellPolicy:
    """Limits and opt-in state for one local shell operation."""

    enabled: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    output_limit: int = DEFAULT_OUTPUT_LIMIT

    def __post_init__(self) -> None:
        timeout = min(max(float(self.timeout_seconds), 0.1), DEFAULT_TIMEOUT_SECONDS)
        output_limit = min(max(int(self.output_limit), 1), DEFAULT_OUTPUT_LIMIT)
        object.__setattr__(self, "timeout_seconds", timeout)
        object.__setattr__(self, "output_limit", output_limit)


@dataclass(frozen=True)
class ShellResult:
    """The bounded result of one local command."""

    returncode: int
    output: str


def parse_command(command: str) -> list[str]:
    """Parse one executable command without enabling shell syntax."""
    if not command or "\x00" in command or "\n" in command or "\r" in command:
        raise ShellExecutionError("command is empty or contains an invalid control character")
    if _has_unquoted_shell_operator(command):
        raise ShellExecutionError("shell operator syntax is not allowed")
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ShellExecutionError(f"malformed command quoting: {exc}") from exc
    if not argv:
        raise ShellExecutionError("command is empty")
    return argv


def _has_unquoted_shell_operator(command: str) -> bool:
    """Reject shell operators while allowing them inside quoted argv values."""
    single_quoted = False
    double_quoted = False
    escaped = False
    for index, character in enumerate(command):
        if escaped:
            escaped = False
            continue
        if character == "\\" and not single_quoted:
            escaped = True
            continue
        if character == "'" and not double_quoted:
            single_quoted = not single_quoted
            continue
        if character == '"' and not single_quoted:
            double_quoted = not double_quoted
            continue
        if single_quoted or double_quoted:
            continue
        if character in _FORBIDDEN_SHELL_MARKERS or command.startswith("$(", index):
            return True
    return False


def _child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in ("VOICE_SESSION_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        environment.pop(name, None)
    return environment


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    try:
        await process.wait()
    except ProcessLookupError:
        pass


async def _collect_output(
    process: asyncio.subprocess.Process,
    output_limit: int,
) -> bytes:
    assert process.stdout is not None
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await process.stdout.read(min(4096, output_limit + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > output_limit:
            raise ShellExecutionError(
                f"command output exceeded the {output_limit} byte output limit"
            )
        chunks.append(chunk)
    await process.wait()
    return b"".join(chunks)


async def run_command(
    command: str,
    *,
    policy: ShellPolicy,
    cwd: Optional[Path] = None,
) -> ShellResult:
    """Run a bounded executable command without invoking a shell."""
    if not policy.enabled:
        raise ShellExecutionError("shell execution is disabled; use --allow-shell to enable it")
    argv = parse_command(command)
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd) if cwd is not None else None,
            env=_child_environment(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except (OSError, ValueError) as exc:
        raise ShellExecutionError(f"could not start command: {exc}") from exc

    try:
        output = await asyncio.wait_for(
            _collect_output(process, policy.output_limit),
            timeout=policy.timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        await _terminate(process)
        raise ShellExecutionError(
            f"command exceeded the {policy.timeout_seconds:g}s timeout"
        ) from exc
    except asyncio.CancelledError:
        await _terminate(process)
        raise
    except ShellExecutionError:
        await _terminate(process)
        raise

    return ShellResult(process.returncode or 0, output.decode("utf-8", errors="replace"))


async def interpolate_commands(
    text: str,
    *,
    policy: ShellPolicy,
    cwd: Optional[Path] = None,
) -> str:
    """Replace each ``{!command}`` expression with successful command output."""
    matches = list(_INTERPOLATION.finditer(text))
    if not matches:
        return text
    pieces: list[str] = []
    cursor = 0
    for match in matches:
        pieces.append(text[cursor : match.start()])
        result = await run_command(match.group(1).strip(), policy=policy, cwd=cwd)
        if result.returncode != 0:
            raise ShellExecutionError(
                f"command exited with status {result.returncode}: {result.output.strip()}"
            )
        pieces.append(result.output.rstrip("\r\n"))
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces)


def standalone_command(text: str) -> Optional[str]:
    """Return a standalone local command, or ``None`` for ordinary text."""
    stripped = text.strip()
    if not stripped.startswith("!") or "\n" in stripped or stripped.startswith("{!"):
        return None
    return stripped[1:].strip()


def interpolation_commands(text: str) -> tuple[str, ...]:
    """Return the local commands embedded in a prompt, in execution order."""
    return tuple(match.group(1).strip() for match in _INTERPOLATION.finditer(text))


__all__ = [
    "DEFAULT_OUTPUT_LIMIT",
    "DEFAULT_TIMEOUT_SECONDS",
    "ShellExecutionError",
    "ShellPolicy",
    "ShellResult",
    "interpolate_commands",
    "interpolation_commands",
    "parse_command",
    "run_command",
    "standalone_command",
]
