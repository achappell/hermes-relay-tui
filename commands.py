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
    subcommands: tuple[str, ...] = ()


COMMAND_REGISTRY: tuple[Command, ...] = (
    Command("help", "Show available commands", args_hint="[filter]"),
    Command("new", "Start a fresh Hermes session", args_hint="[session-id]"),
    Command("clear", "Clear the visible transcript"),
    Command("status", "Show connection and session status"),
    Command("model", "Change the active Hermes model", args_hint="[model]"),
    Command("reasoning", "Change the active reasoning effort", args_hint="[level]"),
    Command("fast", "Toggle fast mode", args_hint="[on|off]", subcommands=("on", "off")),
    Command(
        "session",
        "Manage or switch Hermes sessions",
        args_hint="[list|new|switch|resume|info]",
        subcommands=("list", "new", "switch", "resume", "info"),
    ),
    Command(
        "profile",
        "Manage or switch local relay profiles",
        args_hint="[list|select|create|edit|delete]",
        subcommands=("list", "select", "use", "create", "edit", "delete"),
    ),
    Command("sessions", "List and select Hermes sessions", args_hint="[search]"),
    Command("resume", "Resume a Hermes session", args_hint="[session-id]"),
    Command("queue", "Queue a prompt for the next turn", args_hint="<prompt>"),
    Command(
        "busy",
        "Show or set active-turn behavior",
        args_hint="[queue|steer|interrupt]",
        subcommands=("queue", "steer", "interrupt"),
    ),
    Command(
        "details",
        "Show or hide thinking and tool detail",
        args_hint="[show|hide]",
        subcommands=("show", "hide"),
    ),
    Command(
        "voice",
        "Control voice mode through the relay",
        args_hint="[on|off|tts|status]",
        subcommands=("on", "off", "tts", "status"),
    ),
    Command(
        "wake",
        "Arm or release local hands-free wake-word listening",
        args_hint="[on|off|status]",
        subcommands=("on", "off", "status"),
    ),
    Command(
        "audio",
        "List or select local audio devices",
        args_hint="[list|status|input|output]",
        subcommands=("list", "status", "input", "output"),
    ),
    Command(
        "image",
        "Stage a local image attachment",
        args_hint="<path>|list|clear",
        subcommands=("list", "clear"),
    ),
    Command("history", "Search or show prompt history", args_hint="[search term]"),
    Command("save", "Save the visible transcript locally", args_hint="[path]"),
    Command("copy", "Copy the visible transcript to the system clipboard"),
    Command("logs", "Show local debug and crash logging status and paths"),
    Command("usage", "Show relay usage information when supported"),
    Command("reconnect", "Reconnect without replaying an uncertain turn"),
    Command("retry", "Retry the last prompt only when it was never sent"),
    Command("undo", "Remove the last unsent local prompt from the queue"),
    Command("compress", "Compress the conversation when the relay supports it"),
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
    """Return command-name or subcommand completions for slash commands."""
    if not text.startswith("/"):
        return []

    if " " not in text:
        prefix = text[1:].lower()
        names = [command.name for command in COMMAND_REGISTRY]
        names.extend(alias for command in COMMAND_REGISTRY for alias in command.aliases)
        return [f"/{name}" for name in names if name.startswith(prefix)]

    parts = text[1:].split(maxsplit=1)
    if not parts:
        return []
    cmd_name = parts[0].lower()
    cmd = _COMMAND_LOOKUP.get(cmd_name)
    if cmd is None or not cmd.subcommands:
        return []

    after_cmd = text[1 + len(parts[0]):]
    sub_text = after_cmd.lstrip()
    if " " in sub_text:
        return []
    sub_prefix = sub_text.lower()
    return [f"/{cmd.name} {sub}" for sub in cmd.subcommands if sub.startswith(sub_prefix)]


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
