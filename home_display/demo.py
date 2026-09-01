from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .server import DisplayServer
from .state import DisplayState, DisplayStatePublisher

DEMO_STEPS: tuple[tuple[DisplayState, str, str | None], ...] = (
    ("idle", "", None),
    ("listening", "", "Listening"),
    ("thinking", "", "Thinking"),
    ("speaking", "Here is a calm, readable response from the home display.", "Speaking"),
    ("buffering", "Here is a calm, readable response from the home display.", "Buffering"),
    ("error", "", "Something went wrong. Please try again."),
    ("idle", "", None),
)


async def run_demo(publisher: DisplayStatePublisher, *, interval: float) -> None:
    """Publish one deterministic fake display-state sequence."""
    for state, response_text, status_text in DEMO_STEPS:
        publisher.publish(
            state=state,
            response_text=response_text,
            status_text=status_text,
        )
        await asyncio.sleep(interval)


async def serve_demo(*, interval: float, port: int) -> None:
    """Serve the static shell while repeating the fake state sequence."""
    publisher = DisplayStatePublisher()
    static_dir = Path(__file__).with_name("static")
    server = DisplayServer(publisher, static_dir, port=port)
    info = await server.start()
    print(f"Home display demo: {info.http_url}")
    try:
        while True:
            await run_demo(publisher, interval=interval)
    finally:
        await server.close()


def _non_negative_float(value: str) -> float:
    interval = float(value)
    if interval < 0:
        raise argparse.ArgumentTypeError("interval must be non-negative")
    return interval


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the deterministic home display demo.")
    parser.add_argument(
        "--interval",
        type=_non_negative_float,
        default=2.0,
        help="seconds to show each fake state (default: 2)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="loopback port; 0 selects an available port (default: 0)",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    try:
        asyncio.run(serve_demo(interval=args.interval, port=args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
