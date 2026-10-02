# Validation: TUI-STD-01

Updated: 2026-09-29

## Implementation evidence

Fresh setup requires an explicit HomeBridge or Standard Hermes choice, and both fresh choices reach their intended flow. Standard setup asks for its endpoint, Hermes Profile, and token separately; it stores the token in the private environment file, rejects credential-bearing URL fields, preserves named profiles and promotes a root-only connection to `default` when adding another transport, and skips speech-model preparation unless `--stt-model` is explicit.

Standard mode and its effective Hermes Profile appear in connection status, `/status`, and `/profile list`; Standard setup no longer asks for legacy IDs that `session.create` ignores. Profile changes are rejected before `active_profile` is written when work is active, queued, attached, or uncertain. Reconnect preserves Standard uncertainty and sends no prompt; failed `/session new` preserves it, successful `/session new` clears it and the retry candidate, and wake startup remains blocked while uncertainty is unresolved.

Prompt history is scoped by transport, endpoint, local profile, and effective Hermes Profile. Unscoped legacy history remains untouched instead of being copied into a named profile; Standard history additionally separates endpoint and Hermes Profile identities. Credential query values and URL user information are excluded from history path hashes, token rotation does not move history, blank Hermes Profile values use the effective `default`, and the legacy path helper still resolves its pre-scope location.

## Matrix coverage

| Matrix row | Evidence |
| --- | --- |
| FIRST_SETUP | Missing and invalid choices leave config untouched; fresh HomeBridge pairing, Standard setup, optional model setup, root-only connection preservation, named catalog preservation, and connection-failure retention tests passed. |
| CAPABILITIES | `test_text_turn_is_inline_ignores_other_sessions_and_ends_once`, gateway audio/interrupt tests, `test_unsupported_prompt_is_cancelled_without_collecting_a_value`, and both optional Standard speech setup tests passed. |
| MODE_CHANGE | Standard uncertainty, failed and successful session replacement, queued prompt, staged attachment, successful cross-identity switch, reconnect, and wake-start blocking tests passed. |
| HISTORY_SCOPE | Endpoint and credential query handling, token rotation, Hermes Profile/default normalization, old-path lookup, and unscoped-history isolation in `tests/test_history.py`, `tests/test_profile_app.py`, and `tests/test_app.py` passed. |

## Automated verification

The reproducible combined focused run passed **167 tests** across setup, history, profile app, gateway session, profile CLI, relay profiles, core import boundaries, and seven directly relevant `tests/test_app.py` cases. Python 3.14.4's pytest-asyncio runner otherwise hangs while joining its default executor after tests using `asyncio.to_thread`; the command below temporarily sets the join timeout to 0.1 seconds and filters only that shutdown warning. No repository test configuration was changed.

```sh
venv/bin/python -c '
import asyncio.runners
import warnings
import pytest

asyncio.runners.constants.THREAD_JOIN_TIMEOUT = 0.1
warnings.filterwarnings(
    "ignore",
    message=r"The executor did not finishing joining its threads within 0\.1 seconds\.",
    category=RuntimeWarning,
)
raise SystemExit(pytest.main([
    "-q",
    "tests/test_setup.py",
    "tests/test_history.py",
    "tests/test_profile_app.py",
    "tests/test_gateway_session.py",
    "tests/test_profile_cli.py",
    "tests/test_relay_profiles.py",
    "tests/test_core_boundary.py",
    "tests/test_app.py::test_no_play_shutdown_does_not_start_executor_workers",
    "tests/test_app.py::test_gateway_transport_selects_the_gateway_session_without_changing_default",
    "tests/test_app.py::test_gateway_transport_preserves_an_explicit_resume_key",
    "tests/test_app.py::test_reconnect_failure_preserves_an_uncertain_response",
    "tests/test_app.py::test_reconnect_does_not_replay_an_uncertain_turn_or_hide_partial_text",
    "tests/test_app.py::test_failed_standard_session_new_keeps_uncertainty_and_blocks_prompt",
    "tests/test_app.py::test_standard_uncertainty_blocks_wake_microphone_startup",
]))
'
```

The required full-suite attempt, `timeout 45s venv/bin/pytest -vv -o faulthandler_timeout=15`, collected **1,718 tests** and timed out at `tests/test_app.py::test_late_audio_write_cannot_abort_or_feed_replacement_player`. The event loop remained in `selectors.select()` with executor workers idle; the same unchanged test also stalled when run alone. The broader focused command from the spec timed out at the same test. The full suite is therefore not recorded as passing.

`git diff --check` passed.

## External gates

No live Standard Hermes endpoint was configured. Live typed text, response audio, interrupt, unsupported-prompt, connection-failure, and recovery checks remain untested. The change is not merged or pushed; merge validation remains pending.
