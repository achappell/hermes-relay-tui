"""Slash-command parsing, registry, help, and first-pass completion."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    """A command known to the laptop TUI."""

    name: str
    description: str
    aliases: tuple[str, ...] = ()
    args_hint: str = ""


COMMAND_REGISTRY: tuple[Command, ...] = (
    Command("help", "Show available commands", args_hint="[filter]"),
    Command("new", "Start a fresh Hermes session"),
    Command("clear", "Clear the visible transcript"),
    Command("status", "Show connection and session status"),
    Command("model", "Change the active Hermes model", args_hint="[model]"),
    Command("reasoning", "Change the active reasoning effort", args_hint="[level]"),
    Command("fast", "Toggle fast mode", args_hint="[on|off]"),
    Command("sessions", "List resumable Hermes sessions"),
    Command("resume", "Resume a Hermes session", args_hint="[session-id]"),
    Command("queue", "Queue a prompt for the next turn", args_hint="<prompt>"),
    Command("busy", "Show or set active-turn behavior", args_hint="[queue|steer|interrupt]"),
    Command("details", "Show or hide thinking and tool detail", args_hint="[show|hide]"),
    Command("voice", "Capture and send a microphone turn"),
    Command("audio", "List or select local audio devices", args_hint="[list|status|input|output]"),
    Command("image", "Stage a local image attachment", args_hint="<path>|list|clear"),
    Command("history", "Search or show prompt history", args_hint="[search term]"),
    Command("reload", "Reload settings from the config file and environment"),
    Command("quit", "Exit the TUI", aliases=("exit",)),
)

_COMMAND_LOOKUP = {
    name: command
    for command in COMMAND_REGISTRY
    for name in (command.name, *command.aliases)
}


@dataclass(frozen=True)
class CommandInvocation:
    """One submitted slash command, including commands not in our registry."""

    name: str
    args: str
    command: Command | None
    raw: str


def parse_slash_command(text: str) -> CommandInvocation | None:
    """Parse a slash command, or return ``None`` for an ordinary prompt."""
    if not text.startswith("/"):
        return None
    parts = text[1:].split(maxsplit=1)
    name = parts[0].lower() if parts else ""
    args = parts[1] if len(parts) == 2 else ""
    return CommandInvocation(name, args, _COMMAND_LOOKUP.get(name), text)


def complete_slash_command(text: str) -> list[str]:
    """Return command-name completions for a bare slash word."""
    if not text.startswith("/") or any(character.isspace() for character in text):
        return []
    prefix = text[1:].lower()
    names = [command.name for command in COMMAND_REGISTRY]
    names.extend(alias for command in COMMAND_REGISTRY for alias in command.aliases)
    return [f"/{name}" for name in names if name.startswith(prefix)]


def help_text(filter_text: str = "") -> str:
    """Render the compact command help shown by ``/help``."""
    needle = filter_text.strip().lower()
    commands = (
        command
        for command in COMMAND_REGISTRY
        if not needle
        or needle in command.name.lower()
        or needle in command.description.lower()
    )
    lines = []
    for command in commands:
        args = f" {command.args_hint}" if command.args_hint else ""
        aliases = f" (alias: /{' /'.join(command.aliases)})" if command.aliases else ""
        lines.append(f"/{command.name}{args} — {command.description}{aliases}")
    if not lines:
        return f"No commands match {filter_text!r}."
    return "Available commands:\n" + "\n".join(lines)
