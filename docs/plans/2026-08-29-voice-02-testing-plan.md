# VOICE-02 Testing Plan

> **For test executors:** Run the deterministic checks first, then complete the hardware smoke test when an accessible PortAudio input device is available. Do not commit tokens, debug logs, or captured audio.

**Goal:** Validate microphone cancellation, session-local input/output device selection, and actionable audio diagnostics without regressing typed turns, voice turns, playback fallback, or UI responsiveness.

**Architecture:** Keep protocol behavior under test with fakes. Test the microphone adapter at its boundary with a fake Hermes recorder and fake `sounddevice`; test Textual behavior with `App.run_test()`; reserve a real Hermes session for the final text/voice smoke test.

**Tech Stack:** Python 3.14, pytest, Textual test pilot, `asyncio.to_thread`, fake WebSocket/session objects, Hermes `LocalMicrophone`, PortAudio through `sounddevice`.

**Scope:** The current VOICE-02 implementation in `app.py`, `audio.py`, `config.py`, `mic.py`, and `commands.py`, plus its focused tests.

## Acceptance criteria

- Pressing `Ctrl+C` while microphone capture is blocked wakes the recorder, returns control to the TUI, leaves no empty prompt queued, and does not exit the application.
- `/audio list` reports each local device index, name, and input/output capability counts; an unavailable device query becomes an in-app error instead of crashing the TUI.
- `/audio status` shows the selected input and output selectors and current voice state.
- `/audio input <index-or-name>` applies to the next capture and releases an existing microphone before changing devices.
- `/audio output <index-or-name>` applies to the next playback stream; `default` restores the system default.
- `--mic-input-device`, `--audio-output-device`, `VOICE_SESSION_MIC_INPUT_DEVICE`, and `VOICE_SESSION_AUDIO_OUTPUT_DEVICE` accept numeric indexes, names, and `default`.
- A failed speaker stream falls back to buffering/WAV behavior already covered by the existing lifecycle tests.
- The full suite passes, and the live smoke path has evidence for a normal voice turn, cancellation, device selection, and recovery after cancellation.

## Files and test responsibilities

| Area | Files | Evidence to collect |
| --- | --- | --- |
| Configuration | `config.py`, `tests/test_config.py` | Flags and environment variables resolve to `int`, `str`, or `None`. |
| Playback and discovery | `audio.py`, `tests/test_audio.py` | Output selector reaches `RawOutputStream`; device records are normalized. |
| Microphone adapter | `mic.py`, `tests/test_mic.py` | Input selection is scoped and restored; cancellation reaches the recorder and wakes the silence callback. |
| Commands and UI | `app.py`, `commands.py`, `tests/test_app.py`, `tests/test_commands.py` | `/audio` routes, renders, updates selectors, and preserves app state. |
| Live boundary | Hermes endpoint plus local PortAudio devices | A real text/voice session behaves correctly and leaves the TUI usable. |

## Phase 1: deterministic automated gate

- [ ] **Run the VOICE-02-focused suite.**

  ```bash
  venv/bin/pytest tests/test_config.py tests/test_audio.py tests/test_mic.py tests/test_commands.py tests/test_app.py -q
  ```

  Expected result: all focused tests pass. The current baseline is 101 passed tests.

- [ ] **Confirm the cancellation and device-selection cases are present.**

  ```bash
  venv/bin/pytest \
    tests/test_mic.py::test_wrapped_recorder_selects_input_device_and_cancellation_wakes_capture \
    tests/test_app.py::test_session_input_device_change_releases_existing_microphone \
    tests/test_app.py::test_ctrl_c_cancels_an_active_microphone_capture \
    tests/test_app.py::test_ctrl_c_key_cancels_an_active_microphone_capture \
    tests/test_app.py::test_audio_command_selects_input_and_output_devices_for_the_session \
    tests/test_app.py::test_audio_command_lists_detected_devices -q
  ```

  Expected result: each named test passes; the blocking-capture test completes within its timeout.

- [ ] **Run the complete regression suite.**

  ```bash
  venv/bin/pytest
  ```

  Expected result: all tests pass. The current baseline is 136 passed tests.

- [ ] **Check the command-line surface.**

  ```bash
  venv/bin/python app.py --help
  ```

  Expected result: help includes `--mic-input-device` and `--audio-output-device`, and importing the CLI does not require a live Hermes connection.

- [ ] **Probe local device discovery without starting a session.**

  ```bash
  venv/bin/python -c 'from audio import audio_device_list; print(audio_device_list())'
  ```

  Expected result: a list of normalized device dictionaries, or `[]` when PortAudio exposes no devices. An empty list is a hardware prerequisite failure, not proof that the UI path is broken.

- [ ] **Check the worktree for test hygiene.**

  ```bash
  git diff --check
  rg --files -g '*.wav' -g '*.log' -g '*.env' .
  ```

  Expected result: no whitespace errors and no credentials, captured audio, or debug logs in the repository.

## Phase 2: fake-device and failure-path coverage

These cases should remain deterministic and should not open a microphone, speaker, WebSocket, or real Hermes session.

- [ ] **Input selection scope:** In `tests/test_mic.py`, keep a fake `sounddevice.default.device` with both prior input and output values. Assert that the selected input is visible during recorder startup and that the original pair is restored immediately afterward.
- [ ] **Cancellation wake-up:** Assert that the proxy calls the recorder's `cancel()` and invokes the silence callback, allowing a blocked `LocalMicrophone.capture()` to return. Assert that the proxy does not require a second `Ctrl+C`.
- [ ] **Session cleanup:** In `tests/test_app.py`, assert that changing the input device closes and clears an existing microphone before the new selector is stored.
- [ ] **Command parsing:** In `tests/test_config.py` and `tests/test_commands.py`, cover numeric selectors, names containing spaces, `default`, and blank/invalid command forms. Invalid `/audio` syntax must render usage text and must not mutate the current selector.
- [ ] **Device listing:** With fake `query_devices()` data containing input-only, output-only, and combined devices, assert that the rendered list includes the correct capabilities. With `query_devices()` raising, assert an `[error] audio devices:` transcript block.
- [ ] **Playback failure:** Reuse the existing fake `RawOutputStream` failure case and verify that the player records the error, becomes inactive, and allows the app's existing buffering/WAV fallback to continue.
- [ ] **Post-cancellation recovery:** After the fake blocking capture is interrupted, submit a normal typed prompt and verify that it still reaches the fake session. This catches stale voice state and leaked capture tasks.

## Phase 3: live hardware smoke test

### Prerequisites

- A valid Hermes profile or `VOICE_SESSION_TOKEN` and a reachable configured endpoint.
- The Hermes checkout containing `scripts/voice-session-client.py`.
- At least one accessible input device and one accessible output device. A headset satisfies both.
- Microphone permission granted to the launching application (Terminal, iTerm, VS Code, or the IDE).
- A temporary log path outside the repository; do not commit it.

### Start the app

Use the configured profile and endpoint. Keep the token in the environment or profile file; never paste it into this plan or a shell transcript.

```bash
venv/bin/python app.py --debug --log-file /tmp/hermes-streaming-tui-voice-02.log
```

If speaker playback is unavailable, repeat the voice-turn checks with `--no-play`; the app should still buffer audio and report the fallback clearly.

### Smoke scenarios

- [ ] **Baseline and discovery:** Submit `/audio status`, then `/audio list`.

  Expected: status shows `input=default` and `output=default` unless selectors were supplied at launch. The list shows real device indexes, names, and capabilities; no traceback appears.

- [ ] **Input selection:** Submit `/audio input <real microphone index>` and `/audio status`.

  Expected: the status shows the chosen index. Repeat with `/audio input <real microphone name>` when the name contains spaces; the status shows the name. `default` returns to the system input.

- [ ] **Output selection:** Submit `/audio output <real speaker index>` and `/audio status`.

  Expected: the status shows the chosen index and the next response attempts that output. `default` returns to the system output.

- [ ] **Normal voice turn:** Press `Ctrl+R`, speak one short sentence, and wait for completion.

  Expected: the app moves through listening/transcribing, sends exactly one transcribed user turn, renders one assistant response, and returns to ready. Audio plays, or the app reports buffering/WAV fallback without hanging.

- [ ] **Microphone cancellation:** Press `Ctrl+R`, wait until listening is active, then press `Ctrl+C` before speaking or before silence detection completes.

  Expected: the status becomes interrupted, the app remains open, no empty prompt is sent, and the composer accepts the next message immediately.

- [ ] **Recovery after cancellation:** Send a short typed prompt after the cancelled capture.

  Expected: the typed prompt completes normally. This proves cancellation did not leave a worker, socket, or voice-state lock behind.

- [ ] **Missing/invalid device path:** Select an unavailable output index, then complete a response; separately, temporarily remove or deny access to the selected microphone if practical.

  Expected: the app displays an actionable audio error or buffering fallback, remains responsive, closes the failed stream, and can return to `default` without restarting. Do not treat a local fallback as successful device support if the selected device was never actually used.

### Live evidence

Record the date, OS, selected device indexes/names, scenario results, and any visible error text in the GitHub Project item. Use the optional content-safe log only when a scenario fails:

```bash
rg -n 'audio|microphone|player|app.event|app.turn.finish|voice' /tmp/hermes-streaming-tui-voice-02.log
```

The log is for local diagnosis and must remain outside the repository.

## Current status and unblocker

- Automated evidence already available: focused app tests pass (59 tests); the full suite passes (136 tests), including the key-level `Ctrl+C` microphone-cancellation regression; CLI help exposes both selectors; `git diff --check` is clean.
- Current hardware probe returns `[]`, so the real microphone cancellation and device-selection smoke scenarios cannot yet be executed on this machine.
- The next validation action is to expose an accessible PortAudio microphone/speaker and confirm the launching app has microphone permission, then run Phase 3 and attach the evidence to the VOICE-02 GitHub Project item before moving it to `Verify`.
