# TUI Epic 1 physical voice acceptance

Use the candidate checkout with an existing paired Home profile and approved grant. Record the candidate commit, macOS version, input/output device names, wake phrase, STT model, capture limit and silence settings. Do not store credentials or audio recordings in the repository. These checks require a person speaking through the actual microphone; synthetic PCM and fake listeners do not close them.

## Wake continuation — TUI-DEFECT-102

1. Launch the candidate TUI in Home mode, confirm the intended Profile, and run `/wake on`.
2. Say the configured wake phrase, wait for capture acknowledgement, then say “Reply with first turn received.” Confirm the complete transcript and spoken answer.
3. During the follow-up window, say “Reply with second turn received” without another wake phrase. Confirm the second complete transcript and spoken answer.
4. Allow the follow-up window to expire. Say the wake phrase and a third short request. Confirm capture restarts.
5. Say exactly “stop” in a capture window. Confirm no replacement prompt is sent and wake detection can resume.

The original defect captured the first turn but failed to capture the second after the response. Record capture behavior and microphone ownership, not only the word shown in the status line.

## Sustained capture — TUI-DEFECT-104

1. Begin a wake-triggered capture and speak continuously for roughly ten seconds, below the configured maximum. End with a distinct phrase such as “the final words are purple umbrella.”
2. Confirm the transcript includes the ending and does not stop mid-sentence. Confirm the resulting response completes.
3. Repeat once with ordinary short pauses below the configured silence threshold. Record whether a pause, the maximum duration, or actual mid-speech truncation ended capture.

Do not increase capture limits merely to hide a reproduced defect. Record the actual configuration and observed transcript boundary.

## Responsive teardown — T-5

1. With wake armed, run `/wake off`; verify the UI remains responsive and the microphone-open marker clears. Repeat disarm, then re-arm and make one successful capture.
2. With wake armed, exercise `/reload` and `/reconnect` separately. Each must release the microphone and require deliberate `/wake on`; reconnect must not replay a prompt.
3. Quit during active capture with Ctrl+Q. Confirm prompt exit and microphone release. Relaunch and verify a new capture can start without a stale wake or device-busy failure.
4. Record unexpected disconnect behavior on a controlled connection interruption when available. The microphone must disarm, recovery must be explicit, and uncertain prompts must not replay.

Late-open cancellation, repeated teardown, blocked native close, and stale callbacks also require the focused lifecycle regression suite; a manual happy path does not prove those races.

## Evidence

Record pass/fail per step in the owning validation artifact. Include whether the result is a direct observation or Amanda's report. Keep defects open until reproduced and fixed or shown superseded on the supported Home/Standard baseline. Home pairing/session acceptance, physical voice acceptance, and deployment remain separate gates.
