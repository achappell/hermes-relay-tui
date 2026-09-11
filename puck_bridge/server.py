"""Entry point for the standalone Puck audio bridge process.

Wires `receiver.py`'s chunked-upload HTTP server to `turn.py`'s
directly-constructed `HandsFreeCoordinator`, against a real
`session.HermesSession` built from this project's existing relay-profile
configuration (`config.py`) -- same profiles the TUI and household
appliance already use, plus the hardcoded `PUCK_DEVICE_TOKEN` stand-in this
story adds alongside them.

Deliberately a separate process, not imported by `app.py` or
`home_display/appliance.py` (see the spec's Boundaries & Constraints).

Usage:
    python -m puck_bridge [--host 0.0.0.0] [--port 8766] [--profile NAME]
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Sequence

import config
from session import HermesSession

from .receiver import ThreadingHTTPServer, make_handler
from .turn import TurnRunner

logger = logging.getLogger("hermes_relay_tui.puck_bridge.server")

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8766


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Standalone bridge: receives one bounded, VAD-gated audio "
            "upload per Puck wake, transcribes it, and drives one real "
            "Hermes turn with the response played on this host's speakers."
        )
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST, help=f"bind address (default: {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"listen port (default: {DEFAULT_PORT})"
    )
    return parser


def build_session_args(remaining_argv: Sequence[str]) -> argparse.Namespace:
    """Resolve one relay profile's connection settings for this bridge.

    Reuses `config.build_arg_parser` unchanged -- the same CLI-flag >
    env-var > YAML-config > built-in precedence, profile selection, and
    token resolution the TUI and household appliance already rely on. This
    bridge only adds a distinct `session_id` so its turns land in their own
    Hermes session rather than colliding with another doorway's.
    """
    session_parser = config.build_arg_parser(list(remaining_argv))
    session_args = session_parser.parse_args(list(remaining_argv))
    session_args.session_id = _bridge_session_id(session_args)
    return session_args


# Suffix marking a session id as this bridge's own.
BRIDGE_SESSION_SUFFIX = "-puck-bridge"


def _bridge_session_id(session_args: argparse.Namespace) -> str:
    """Derive a session id that cannot collide with another doorway's.

    The previous guard here was `if not session_args.session_id`, which
    never fired: `config.build_arg_parser()` always resolves a non-empty
    session_id before this runs -- from the profile entry (`session_id`,
    else `f"{name}-session"`, config.py:479) or the `hybrid-tui` fallback
    (config.py:497-499). So the bridge silently inherited whatever the TUI
    was using, observed live as `amanda-kiosk`. Epic 1 requires one Active
    Turn *per doorway*; two doorways sharing a session id breaks that, and
    the failure stays invisible until two turns interleave.

    Applied unconditionally rather than only-when-unset, because
    distinctness is a correctness property of this doorway, not a user
    preference -- an explicit `--session-id` that happened to match the
    TUI's would otherwise reintroduce exactly the collision this prevents.

    Deliberately deterministic, not random: a uuid suffix would also
    guarantee distinctness, but would mint a brand-new Hermes session on
    every bridge restart and discard conversation continuity. The same
    profile must return to the same bridge session across restarts.

    Idempotent, so re-deriving an already-derived id is a no-op rather
    than accreting suffixes.
    """
    base = str(getattr(session_args, "session_id", "") or "").strip()
    if not base:
        base = str(getattr(session_args, "profile_name", "") or "").strip()
    if not base:
        # Nothing to qualify. Still a valid, distinct bridge id -- and
        # still not another doorway's.
        return BRIDGE_SESSION_SUFFIX.lstrip("-")
    if base.endswith(BRIDGE_SESSION_SUFFIX):
        return base
    return f"{base}{BRIDGE_SESSION_SUFFIX}"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args, remaining = build_arg_parser().parse_known_args(raw_argv)

    session_args = build_session_args(remaining)
    token = config.resolve_puck_device_token(session_args.profile_env)
    if not token:
        print(
            "error: no PUCK_DEVICE_TOKEN configured. Set it in the profile "
            "env file (see config.py's token_env pattern) or the "
            "PUCK_DEVICE_TOKEN environment variable before starting the "
            "bridge -- see firmware/respeaker-lite/README.md.",
            file=sys.stderr,
        )
        return 1

    session = HermesSession(session_args)
    runner = TurnRunner(session)
    logger.info(
        "puck bridge connecting Hermes session profile=%s session_id=%s",
        session_args.profile_name,
        session_args.session_id,
    )
    runner.start()

    handler_cls = make_handler(
        expected_token=token,
        on_transcript=runner.submit_transcript,
    )
    try:
        with ThreadingHTTPServer((args.host, args.port), handler_cls) as httpd:
            logger.info("puck bridge listening on %s:%d", args.host, args.port)
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                pass
    finally:
        runner.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
