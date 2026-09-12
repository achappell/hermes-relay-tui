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
    python -m puck_bridge --host-playback  # explicit local-speaker fallback
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Sequence

import config
from session import HermesSession

from .receiver import ThreadingHTTPServer, make_handler
from .response import ResponseStream
from .turn import TurnRunner

logger = logging.getLogger("hermes_relay_tui.puck_bridge.server")

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8766


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Standalone bridge: receives one bounded, VAD-gated audio "
            "upload per Puck wake, transcribes it, and drives one real "
            "Hermes turn with the response streamed back to the Puck."
        )
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST, help=f"bind address (default: {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"listen port (default: {DEFAULT_PORT})"
    )
    playback = parser.add_mutually_exclusive_group()
    playback.add_argument(
        "--play-on-device",
        dest="play_on_device",
        action="store_true",
        help="stream the spoken answer to the Puck (the default)",
    )
    playback.add_argument(
        "--host-playback",
        dest="play_on_device",
        action="store_false",
        help="use the host speaker as an explicit fallback instead of the Puck",
    )
    parser.set_defaults(play_on_device=True)
    return parser


def build_session_args(remaining_argv: Sequence[str]) -> argparse.Namespace:
    """Resolve one relay profile's connection settings for this bridge.

    Reuses `config.build_arg_parser` unchanged -- the same CLI-flag >
    env-var > YAML-config > built-in precedence, profile selection, and
    token resolution the TUI and household appliance already rely on. This
    bridge always suffixes the resolved `session_id` so its turns land in
    their own Hermes session rather than colliding with another doorway's.

    `config.build_arg_parser` always populates a non-empty `session_id`
    from the selected profile's own YAML config (e.g. "amanda-kiosk"), so
    an emptiness check here would never fire -- the suffix must be applied
    unconditionally, except when the caller explicitly passed `--session-id`
    on this bridge's own command line, which is honored verbatim.
    """
    session_parser = config.build_arg_parser(list(remaining_argv))
    session_args = session_parser.parse_args(list(remaining_argv))
    explicit_session_id = any(
        arg == "--session-id" or arg.startswith("--session-id=")
        for arg in remaining_argv
    )
    if not explicit_session_id:
        session_args.session_id = f"{session_args.session_id}-puck-bridge"
    return session_args


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
    # Device playback is the normal Puck path. Host playback remains an
    # explicit diagnostic fallback for a firmware or response-stream outage.
    response_stream = ResponseStream() if args.play_on_device else None
    runner = TurnRunner(session, response_stream=response_stream)
    if response_stream is not None:
        logger.info(
            "puck bridge will stream the answer to the device at %s; "
            "this host stays silent",
            "/response",
        )
    logger.info(
        "puck bridge connecting Hermes session profile=%s session_id=%s",
        session_args.profile_name,
        session_args.session_id,
    )
    runner.start()

    handler_cls = make_handler(
        expected_token=token,
        on_transcript=runner.submit_transcript,
        set_response_seq=runner.set_response_seq,
        response_stream=response_stream,
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
