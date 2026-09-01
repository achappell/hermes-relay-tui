"""Render the Homebrew formula for a tagged Hermes Relay TUI release."""

from argparse import ArgumentParser
from pathlib import Path


# The formula installs from the signed-off sdist attached to the GitHub
# release rather than cloning the repository. A checksummed archive keeps
# installs reproducible, avoids shipping the full history to every user,
# and cannot drift if a tag is ever re-pointed.
FORMULA = """# typed: strict
# frozen_string_literal: true

# Homebrew formula for the Hermes Relay TUI.
class HermesRelayTui < Formula
  desc \"Textual terminal UI for authenticated Hermes voice sessions\"
  homepage \"https://github.com/achappell/hermes-relay-tui\"

  # Install from the checksummed release sdist, not a git clone.
  url \"https://github.com/achappell/hermes-relay-tui/releases/download/v{version}/hermes_relay_tui-{version}.tar.gz\"
  sha256 \"{sha256}\"
  version \"{version}\"
  head \"https://github.com/achappell/hermes-relay-tui.git\", branch: \"main\"

  depends_on \"portaudio\"
  depends_on \"python@3.14\"

  def install
    python = formula_opt_bin(\"python@3.14\") / \"python3.14\"
    venv = libexec / \"venv\"

    system python, \"-m\", \"venv\", venv
    system venv / \"bin/pip\", \"install\", \"--disable-pip-version-check\", \"--no-cache-dir\", \".\"

    (bin / \"hermes-relay\").write_env_script(
      venv / \"bin/hermes-relay\",
      HERMES_RELAY_TUI_VENV: venv.to_s,
    )

    # The kiosk entry point only exists in releases that ship home_display,
    # so link it when the installed distribution actually provides it.
    if (venv / \"bin/hermes-relay-home\").exist?
      (bin / \"hermes-relay-home\").write_env_script(
        venv / \"bin/hermes-relay-home\",
        HERMES_RELAY_TUI_VENV: venv.to_s,
      )
    end
  end

  test do
    assert_match \"Hermes streaming TUI\", shell_output(\"#{{bin}}/hermes-relay --help\")
  end
end
"""


def parse_args() -> ArgumentParser:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="release version without the v prefix")
    parser.add_argument("--sha256", required=True, help="sha256 of the release sdist archive")
    parser.add_argument("--output", type=Path, required=True, help="formula path to write")
    return parser


def main() -> None:
    args = parse_args().parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        FORMULA.format(version=args.version, sha256=args.sha256),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
