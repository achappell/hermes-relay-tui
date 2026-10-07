---
title: 'Keep Home connected when stopping local playback after remote completion'
type: 'bugfix'
created: '2026-10-07'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="user-approved independent TUI audit finding">

## Intent

**Problem:** In Home mode the shared event iterator retires the remote turn before the TUI finishes draining its local PCM output. Ctrl+C during that interval stops the speaker but treats the absence of a remote interrupt target as a failed interrupt and unnecessarily disconnects the healthy Home session.

**Approach:** Distinguish the TUI's positively identified, completed remote turn/local playback drain from an active remote turn. Stop only that local output and retain the connection and conversation so the next prompt works. Preserve turn-scoped remote-tail interruption and the existing failure/reconnect behavior for genuinely active remote work. Late events from the stopped turn must not restart audio. Do not alter direct/legacy transport behavior, add retries, modify Home or other clients, merge, or deploy.

Prove the reported local-only failure before the fix; cover connection retention, the next prompt, active-remote failure, and late-event isolation. Run relevant tests and configured lint, exercise the real CLI/TUI against a controlled local transport, obtain independent review, and open a PR with exact-head CI evidence. Local controlled transport evidence does not establish household acceptance.

</frozen-after-approval>

## Implementation Notes

- Route assessment: no unresolved user-visible intent, no irreversible operation, and a small TUI-only footprint. Isolated worktree starts at `origin/main` `15b38bdc3d164473c738fe143442959af1ae61c3`.
- Reuse the domain's accepted `COMPLETE` state and Home's existing active-turn identity rather than treating every false interrupt as success. Refresh the wrapper's public identity before its normal exhausted-stream completion; snapshot local-only ownership before awaiting PCM abort, so completion/queued-prompt scheduling cannot change the interrupt target.
- Reuse `TuiDomain._reject_stale_event` and Home's existing turn-scoped frame filtering for late audio. No new retries, protocol shape, shared-device behavior, or direct/legacy path.
- Verification boundaries: real TUI/domain/Home adapters with controlled socket and native PCM boundaries for regressions; real CLI under a PTY against loopback WSS for the smoke. Neither substitutes for household Home/audio acceptance.
- User-facing behavior is documented in `README.md` and the requested unreleased `CHANGELOG.md` entry.
- Failing-before evidence: targeted app local-drain and adapter normal-end regressions both failed on the unmodified implementation. The app cancelled the still-draining turn; the adapter exposed stale `home-turn-1` while its underlying remote owner was already `None`.
- Late-event acceptance preserves the existing wire contract: legitimate queued PCM after local abort is not played; wrong-turn `audio.frame`/unlabelled PCM is a protocol error and fails closed rather than being silently accepted. Healthy next-prompt continuity is tested separately from malformed-stream rejection.
- Independent review uses the configured one-shot Blind Hunter layer; no additional review layers are configured for this route.
- Independent same-model review examined the production delta, completion consumers, native playback teardown, and corrected late-audio regressions. It found no provable patch-introduced defect and requested no production changes. No checks were run by the reviewer.
- Executed the real CLI/Textual PTY smoke against an isolated loopback HTTPS/WSS Home fixture (not merely prepared it): all four scenarios passed, each exited 0 and confirmed cleanup. Only native credential storage and `sounddevice.RawOutputStream` were substituted; `app.main`, `PCMPlayer`, Home adapters, HTTPS configuration/claim, and WSS transport ran unchanged.
  - Healthy local drain: Ctrl+C to native abort 2.10 ms; the same websocket stayed open; zero remote interrupt RPCs; exactly two prompt submissions; second response PCM and app turn completed. Raw output operations were stream 1 write → blocked stop → abort → close, then stream 2 write → normal stop → close.
  - Malformed late old-turn audio: zero late PCM output, no second output stream, visible fail-closed error. This does not claim successful continuation on a malformed stream.
  - Active remote rejection and RPC error: local PCM aborted, unsafe connection retired, one submitted prompt with no automatic replay. Ctrl+C to fixture abort measured 1.64 ms and 4.62 ms respectively; these are controlled-fixture timings, not hardware/acoustic latency.
  - No household endpoint, enrollment, real keychain, microphone, or speaker was exercised. Local controlled evidence does not establish household acceptance.
- Initial complete local suite: 1714 passed, 3 skipped, 6 failures. Three new test synchronization failures were corrected to observe received domain text instead of intentionally delayed audio captions. The other failures were existing environment-sensitive checks: the wake test matches `stop` inside this worktree's output path, and two deployment tests require modern Bash but macOS `/bin/bash` lacks `BASHPID`. No unrelated source was changed.
- Final focused verification: `venv/bin/python -m pytest tests/test_app.py tests/test_home_textual_session.py tests/test_puck_home_session.py -q` — **371 passed**. Covers local-only stop/next prompt, wrong-turn audio fail-closed behavior, accepted scoped remote-tail interruption with late in-flight PCM, rejected interrupts, RPC errors, and existing direct/legacy app behavior.
- No Python linter is configured by the repository. Explicit isolated correctness lint (`uvx ruff check --isolated --select E9,F63,F7,F82` on the four changed Python files) and `git diff --check` both passed. `venv/bin/python -m build --sdist --wheel` built both distributions successfully.
- Independent follow-up review approved the final caption-independent test synchronization; no blockers or deferred findings.
- Removed the temporary smoke runner, fixture credentials/certificates/logs, generated test audio, and package build outputs after recording observed evidence. The PR records exact-head CI separately; no merge or deployment is authorized.
- The generic post-build story-sync hook cannot resolve its required `_bmad-output/planning-artifacts/prd.md` in this repository. This approved freeform fix has no sprint story key; no story/issue state was invented or changed. PR creation and exact-head CI use the explicitly requested repository delivery path instead.
