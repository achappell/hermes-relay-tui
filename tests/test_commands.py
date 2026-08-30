import pytest

from commands import complete_slash_command, help_text, parse_slash_command


def test_plain_text_is_not_a_command():
    assert parse_slash_command("tell Hermes hello") is None


def test_known_command_and_alias_are_resolved():
    invocation = parse_slash_command("/exit now")

    assert invocation is not None
    assert invocation.name == "exit"
    assert invocation.args == "now"
    assert invocation.command is not None
    assert invocation.command.name == "quit"


def test_unknown_command_stays_a_command_for_gateway_dispatch():
    invocation = parse_slash_command("/plugin-command --flag")

    assert invocation is not None
    assert invocation.command is None
    assert invocation.name == "plugin-command"
    assert invocation.args == "--flag"


def test_completion_only_targets_a_bare_slash_word():
    assert complete_slash_command("/sta") == ["/status"]
    assert complete_slash_command("/q") == ["/queue", "/quit"]
    assert complete_slash_command("/model gpt") == []


def test_steer_is_not_a_registered_command():
    invocation = parse_slash_command("/steer answer the second question")

    assert invocation is not None
    assert invocation.command is None
    assert invocation.args == "answer the second question"


@pytest.mark.parametrize("name", ["save", "copy", "logs", "usage", "retry", "undo", "compress"])
def test_daily04_commands_are_discoverable(name):
    invocation = parse_slash_command(f"/{name}")

    assert invocation is not None
    assert invocation.command is not None
    assert invocation.command.name == name


def test_busy_command_is_registered_for_session_configuration():
    invocation = parse_slash_command("/busy steer")

    assert invocation is not None
    assert invocation.command is not None
    assert invocation.command.name == "busy"
    assert invocation.args == "steer"


def test_audio_command_is_registered_for_local_device_controls():
    invocation = parse_slash_command("/audio input USB Microphone")

    assert invocation is not None
    assert invocation.command is not None
    assert invocation.command.name == "audio"
    assert invocation.args == "input USB Microphone"


def test_image_command_is_registered_for_local_attachments():
    invocation = parse_slash_command("/image list")

    assert invocation is not None
    assert invocation.command is not None
    assert invocation.command.name == "image"
    assert invocation.args == "list"


def test_help_can_filter_commands():
    rendered = help_text("microphone")

    assert "/voice" in rendered
    assert "/model" not in rendered
