# typed: strict
# frozen_string_literal: true

# Homebrew formula for the Hermes Streaming TUI.
class HermesStreamingTui < Formula
  desc "Textual terminal UI for authenticated Hermes voice sessions"
  homepage "https://github.com/achappell/hermes-streaming-tui"

  # Pin the public source tag and revision for reproducible installs.
  url "https://github.com/achappell/hermes-streaming-tui.git", using: :git,
      tag: "v0.1.0", revision: "9796b63452e8e77b246ffa9119936f36c5a220a9"
  head "https://github.com/achappell/hermes-streaming-tui.git", branch: "main"

  depends_on "portaudio"
  depends_on "python@3.14"

  def install
    python = formula_opt_bin("python@3.14") / "python3.14"
    venv = libexec / "venv"

    system python, "-m", "venv", venv
    system venv / "bin/pip", "install", "--disable-pip-version-check", "--no-cache-dir", "."

    (bin / "hermes-streaming-tui").write_env_script(
      venv / "bin/hermes-streaming-tui",
      HERMES_STREAMING_TUI_VENV: venv.to_s,
    )
  end

  test do
    assert_match "Hermes streaming TUI", shell_output("#{bin}/hermes-streaming-tui --help")
  end
end
