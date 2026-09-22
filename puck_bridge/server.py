"""Entry point for the standalone Puck audio bridge process.

Wires `receiver.py`'s chunked-upload HTTP server to `turn.py`'s
directly-constructed `HandsFreeCoordinator`, against a real
`session.HermesSession` built from this project's existing relay-profile
configuration (`config.py`) -- same profiles the TUI and household
appliance already use. The legacy upload path retains its local
`PUCK_DEVICE_TOKEN`; the opt-in Home path uses a separate paired Device
credential and opaque conversation handle.

Deliberately a separate process, not imported by `app.py` or
`home_display/appliance.py` (see the spec's Boundaries & Constraints).

Usage:
    python -m puck_bridge [--host 0.0.0.0] [--port 8766] [--profile NAME]
    python -m puck_bridge --host-playback  # explicit local-speaker fallback
    python -m puck_bridge --transport home \
        --home-url wss://home.example/api/v1/bridge/ws
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
import time
import sys
from pathlib import Path
from typing import Sequence

import config
from session import HermesSession

from .home_session import HomePuckSession
from .receiver import ThreadingHTTPServer, make_handler
from .response import ResponseStream
from .turn import SHUTDOWN_TIMEOUT_SECONDS, TurnRunner

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
    parser.add_argument(
        "--transport",
        choices=("legacy", "home"),
        default="legacy",
        help="Puck session boundary (default: legacy; home is opt-in)",
    )
    parser.add_argument(
        "--home-url",
        default=os.getenv("HOME_BRIDGE_WS_URL", ""),
        help="paired Home bridge URL, ending in /api/v1/bridge/ws",
    )
    parser.add_argument(
        "--home-conversation-handle",
        default="",
        help="opaque Home conversation handle; prefer HOME_CONVERSATION_HANDLE",
    )
    parser.add_argument(
        "--home-device-credential-file",
        type=Path,
        default=None,
        help="private file containing the Home Device credential",
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


def _read_home_device_credential(path: Path | None) -> str:
    """Read a paired Device credential without exposing file contents."""

    if path is None:
        return ""
    try:
        return path.expanduser().read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def _home_profile_context(remaining_argv: Sequence[str]) -> tuple[Path, str]:
    """Find private pairing config without resolving a Hermes bearer token."""

    argv = list(remaining_argv)
    config_path = config.config_path_from_argv(argv)
    cfg = config.load_config_file(config_path)
    explicit_env = config._option_value(argv, "--profile-env")
    profile_env = Path(
        explicit_env or cfg.get("profile_env") or config.DEFAULT_PROFILE_ENV
    ).expanduser()
    profile_name = config._profile_selection(argv, cfg)
    return profile_env, profile_name


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args, remaining = build_arg_parser().parse_known_args(raw_argv)
    transport = getattr(args, "transport", "legacy")

    if transport == "home":
        profile_env, profile_name = _home_profile_context(remaining)
        session_args = None
    else:
        session_args = build_session_args(remaining)
        profile_env = session_args.profile_env
        profile_name = session_args.profile_name
    token = config.resolve_puck_device_token(profile_env)
    if not token:
        print(
            "error: no PUCK_DEVICE_TOKEN configured. Set it in the profile "
            "env file (see config.py's token_env pattern) or the "
            "PUCK_DEVICE_TOKEN environment variable before starting the "
            "bridge -- see firmware/respeaker-lite/README.md.",
            file=sys.stderr,
        )
        return 1

    if transport == "home":
        home_url = str(args.home_url or "").strip()
        credential = _read_home_device_credential(args.home_device_credential_file)
        if not credential:
            credential = config.resolve_home_device_credential(profile_env)
        conversation_handle = str(args.home_conversation_handle or "").strip()
        if not conversation_handle:
            conversation_handle = config.resolve_home_conversation_handle(
                profile_env
            )
        missing = []
        if not home_url:
            missing.append("--home-url/HOME_BRIDGE_WS_URL")
        if not credential:
            missing.append(
                "--home-device-credential-file/HOME_DEVICE_CREDENTIAL"
            )
        if not conversation_handle:
            missing.append("--home-conversation-handle/HOME_CONVERSATION_HANDLE")
        if missing:
            print(
                "error: Home transport requires " + ", ".join(missing) + ".",
                file=sys.stderr,
            )
            return 1
        try:
            session = HomePuckSession(
                home_url,
                credential,
                conversation_handle,
            )
        except ValueError as exc:
            print(
                f"error: invalid Home transport configuration: {exc}",
                file=sys.stderr,
            )
            return 1
    else:
        assert session_args is not None
        session = HermesSession(session_args)
    # Device playback is the normal Puck path. Host playback remains an
    # explicit diagnostic fallback for a firmware or response-stream outage.
    response_stream = (
        ResponseStream(device_build_identity="respeaker-lite-p5")
        if args.play_on_device
        else None
    )
    runner = TurnRunner(session, response_stream=response_stream)
    if response_stream is not None:
        logger.info(
            "puck bridge will stream the answer to the device at %s; "
            "this host stays silent",
            "/response",
        )
    if transport == "home":
        logger.info(
            "puck bridge connecting through Home profile=%s",
            profile_name,
        )
    else:
        assert session_args is not None
        logger.info(
            "puck bridge connecting Hermes session profile=%s session_id=%s",
            profile_name,
            session_args.session_id,
        )
    stopping = threading.Event()
    deadline = None
    previous_handlers = {}
    httpd = None
    handler_cls = None

    def signal_stop(signum, frame):
        nonlocal deadline
        if deadline is None:
            deadline = time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS
        stopping.set()

    # The handler only latches intent. This owner can stop startup and serving
    # without calling HTTPServer.shutdown from its serving thread.
    def coordinate_stop():
        stopping.wait()
        runner.request_stop(deadline)
        if httpd is not None:
            httpd.request_stop()
        runner.stop(deadline)

    coordinator = threading.Thread(target=coordinate_stop, name="puck-bridge-shutdown")
    try:
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[sig] = signal.signal(sig, signal_stop)
        coordinator.start()
        runner.start()
        if not stopping.is_set():
            handler_cls = make_handler(
                expected_token=token,
                on_transcript=getattr(
                    runner, "submit_transcript_outcome", runner.submit_transcript
                ),
                set_response_seq=runner.set_response_seq,
                on_capture_silent=getattr(runner, "submit_capture_silent", None),
                on_capture_failure=getattr(runner, "submit_capture_failure", None),
                response_stream=response_stream,
            )
        if not stopping.is_set():
            httpd = ThreadingHTTPServer(
                (args.host, args.port), handler_cls, bind_and_activate=False
            )
            if not stopping.is_set():
                httpd.server_bind()
            if not stopping.is_set():
                httpd.server_activate()
            # A short timeout permits shutdown even if the stop request races
            # listener construction, before a serving thread exists.
            httpd.timeout = 0.1
            if not stopping.is_set():
                logger.info("puck bridge listening on %s:%d", args.host, args.port)
            while not stopping.is_set():
                httpd.handle_request()
    except KeyboardInterrupt:
        signal_stop(signal.SIGINT, None)
    finally:
        signal_stop(None, None)

        def cleanup(operation, *values):
            try:
                return operation(*values)
            except Exception as exc:
                logger.warning("puck bridge cleanup failed (%s)", type(exc).__name__)
                return False

        try:
            if httpd is not None:
                cleanup(httpd.request_stop)
                cleanup(httpd.server_close)
            elif handler_cls is not None:
                cleanup(handler_cls.cleanup)
            cleanup(runner.stop, deadline)
            if httpd is not None:
                cleanup(httpd.wait_workers, deadline)
            if coordinator.ident is not None:
                coordinator.join()
            # Budget expiry ends bounded waits, not resource ownership or
            # process lifetime. Retained workers keep this process non-serving.
            cleanup(runner.wait_closed)
            if httpd is not None:
                cleanup(httpd.wait_workers)
        finally:
            for sig, previous in previous_handlers.items():
                signal.signal(sig, previous)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
