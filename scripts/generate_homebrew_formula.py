"""Render the Homebrew formula for a tagged Hermes Streaming TUI release."""

from argparse import ArgumentParser
from pathlib import Path


FORMULA = """# typed: strict
# frozen_string_literal: true

# Homebrew formula for the Hermes Streaming TUI.
class HermesStreamingTui < Formula
  desc \"Textual terminal UI for authenticated Hermes voice sessions\"
  homepage \"https://github.com/achappell/hermes-streaming-tui\"

  # Pin the public source tag and revision for reproducible installs.
  url \"https://github.com/achappell/hermes-streaming-tui.git\", using: :git,
      tag: \"v{version}\", revision: \"{revision}\"
  head \"https://github.com/achappell/hermes-streaming-tui.git\", branch: \"main\"

  depends_on \"portaudio\"
  depends_on \"python@3.14\"

  def install
    python = formula_opt_bin(\"python@3.14\") / \"python3.14\"
    venv = libexec / \"venv\"

    system python, \"-m\", \"venv\", venv
    system venv / \"bin/pip\", \"install\", \"--disable-pip-version-check\", \"--no-cache-dir\", \".\"

    (bin / \"hermes-streaming-tui\").write_env_script(
      venv / \"bin/hermes-streaming-tui\",
      HERMES_STREAMING_TUI_VENV: venv.to_s,
    )
  end

  test do
    assert_match \"Hermes streaming TUI\", shell_output(\"#{{bin}}/hermes-streaming-tui --help\")
  end
end
"""


def parse_args() -> ArgumentParser:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="release version without the v prefix")
    parser.add_argument("--revision", required=True, help="source commit SHA")
    parser.add_argument("--output", type=Path, required=True, help="formula path to write")
    return parser


def main() -> None:
    args = parse_args().parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        FORMULA.format(version=args.version, revision=args.revision),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
