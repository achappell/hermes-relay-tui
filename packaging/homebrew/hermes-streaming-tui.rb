class HermesStreamingTui < Formula
  desc "Textual terminal UI for authenticated Hermes voice sessions"
  homepage "https://github.com/achappell/hermes-streaming-tui"

  # This is the near-term Jensen trial formula. It tracks the private main
  # branch until a tap and tagged release provide a stable, checksummed source.
  url "https://github.com/achappell/hermes-streaming-tui.git", using: :git, branch: "main"
  version "0.1.0-dev"
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
