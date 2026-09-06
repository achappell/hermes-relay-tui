#!/usr/bin/env python3
"""A stand-in Hermes voice-session server, for testing the client without one.

Speaks enough of the protocol to be indistinguishable from the real relay for
one turn: `hello` → `hello_ack`, then `turn` → streamed text, spoken audio, and
`turn_end`. It runs no model and reaches no network — the reply is a canned
sentence and the audio is a synthesized tone, or macOS `say` when available.

This exists because "does the appliance work" and "is Hermes up" are two
questions, and answering them together means answering neither.

    python scripts/fake_relay.py
    python scripts/fake_relay.py --port 8799 --reply "The oven is preheated."
    python scripts/fake_relay.py --no-audio        # text only, no speech
    python scripts/fake_relay.py --fail            # every turn returns an error
    python scripts/fake_relay.py --drop            # hang up mid-turn, once
    python scripts/fake_relay.py --prompt approval # send a structured prompt first
    python scripts/fake_relay.py --prompt secret --prompt-reject-once

Point a client at it:

    venv/bin/python app.py --url ws://127.0.0.1:8799/voice-session --token stub
    venv/bin/python -m home_display.appliance --wake-enabled \
        --url ws://127.0.0.1:8799/voice-session --token stub
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import websockets  # noqa: E402

SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH = 2
CHUNK_FRAMES = 2400  # 100ms, so the client's playback path is really exercised


def _spoken_wav(text: str) -> bytes | None:
    """Render the reply with macOS `say`, so the test has a real voice in it."""
    if not (shutil.which("say") and shutil.which("afconvert")):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        aiff, wav = f"{tmp}/reply.aiff", f"{tmp}/reply.wav"
        try:
            subprocess.run(["say", "-o", aiff, text], check=True, capture_output=True)
            subprocess.run(
                [
                    "afconvert", "-f", "WAVE",
                    "-d", f"LEI16@{SAMPLE_RATE}", "-c", str(CHANNELS),
                    aiff, wav,
                ],
                check=True,
                capture_output=True,
            )
        except (subprocess.CalledProcessError, OSError):
            return None
        with wave.open(wav) as handle:
            return handle.readframes(handle.getnframes())


def _tone(seconds: float = 1.2, hertz: float = 320.0) -> bytes:
    """A plain tone, for when there is no speech synthesizer to borrow."""
    frames = int(SAMPLE_RATE * seconds)
    samples = (
        int(12000 * math.sin(2 * math.pi * hertz * index / SAMPLE_RATE))
        for index in range(frames)
    )
    return struct.pack(f"<{frames}h", *samples)


class FakeRelay:
    def __init__(self, args) -> None:
        self.args = args
        self.turns = 0
        self._audio: bytes | None = None

    def audio(self) -> bytes:
        if self._audio is None:
            self._audio = _spoken_wav(self.args.reply) or _tone()
        return self._audio

    async def handle(self, websocket) -> None:
        peer = getattr(websocket, "remote_address", ("?",))[0]
        print(f"[relay] client connected from {peer}")
        try:
            async for frame in websocket:
                if isinstance(frame, bytes):
                    continue
                payload = json.loads(frame)
                kind = payload.get("type")
                if kind == "hello":
                    print(f"[relay] hello from {payload.get('client_id')!r}")
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "hello_ack",
                                "protocol_version": 1,
                                "session_id": payload.get("session_id", "default"),
                                "chat_id": "stub-chat",
                                "model": self.args.model,
                                "server_version": self.args.relay_version,
                                "context_limit": self.args.context_limit,
                                "capabilities": ["structured_prompts", "interrupt", "sessions"],
                            }
                        )
                    )
                elif kind == "turn":
                    await self.reply(websocket, payload)
                elif kind == "session_list":
                    limit = int(payload.get("limit") or 20)
                    search = str(payload.get("search") or "").strip().lower()
                    sessions = [
                        {
                            "session_id": "default",
                            "title": "Default Session",
                            "model": self.args.model,
                            "message_count": self.turns * 2,
                            "last_active": "just now",
                        },
                        {
                            "session_id": "session-123",
                            "title": "Debug Notes",
                            "model": self.args.model,
                            "message_count": 4,
                            "last_active": "5m ago",
                        },
                    ]
                    if search:
                        sessions = [
                            s for s in sessions
                            if search in s["session_id"].lower() or search in s["title"].lower()
                        ]
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "session_list_result",
                                "sessions": sessions[:limit],
                            }
                        )
                    )
                elif kind == "session_new":
                    new_sid = payload.get("session_id") or f"session-{self.turns + 1}"
                    title = payload.get("title") or "New Session"
                    self.turns = 0
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "session_switched",
                                "session_id": new_sid,
                                "title": title,
                                "model": self.args.model,
                                "server_version": self.args.relay_version,
                                "context_limit": self.args.context_limit,
                                "history": [],
                            }
                        )
                    )
                elif kind == "session_switch":
                    target_sid = payload.get("session_id") or "default"
                    history = [
                        {"role": "user", "content": "Previous prompt in " + target_sid},
                        {"role": "assistant", "content": "Previous response in " + target_sid},
                    ]
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "session_switched",
                                "session_id": target_sid,
                                "title": f"Session {target_sid}",
                                "model": self.args.model,
                                "server_version": self.args.relay_version,
                                "context_limit": self.args.context_limit,
                                "history": history,
                            }
                        )
                    )
                else:
                    print(f"[relay] ignoring {kind!r}")
        except websockets.exceptions.ConnectionClosed:
            pass
        print("[relay] client disconnected")

    async def reply(self, websocket, payload) -> None:
        self.turns += 1
        turn_id = payload.get("turn_id", "stub-turn")
        print(f"[relay] turn {self.turns}: {payload.get('text')!r}")
        await websocket.send(json.dumps({"type": "turn_accepted", "turn_id": turn_id}))

        if self.args.fail:
            await websocket.send(
                json.dumps({"type": "error", "error": "stub relay was told to fail"})
            )
            return

        if self.args.prompt:
            await self._run_prompt(websocket, turn_id)

        await asyncio.sleep(self.args.think)

        # Word by word, so the display's streaming path gets a real workout
        # rather than one atomic paragraph. `text_delta` carries the whole
        # preview so far, not the new chunk — send the chunk alone and the
        # client's rewind path puts every word on its own line.
        preview = ""
        for word in self.args.reply.split():
            preview = f"{preview} {word}".strip()
            await websocket.send(
                json.dumps({"type": "text_delta", "turn_id": turn_id,
                            "payload": {"text": preview}})
            )
            await asyncio.sleep(0.06)

        if self.args.drop and self.turns == 1:
            print("[relay] dropping the connection mid-turn, as requested")
            await websocket.close(code=1011, reason="stub relay drop")
            return

        if not self.args.no_audio:
            audio = self.audio()
            await websocket.send(
                json.dumps(
                    {
                        "type": "audio_start",
                        "turn_id": turn_id,
                        "sample_rate": SAMPLE_RATE,
                        "channels": CHANNELS,
                        "sample_width": SAMPLE_WIDTH,
                    }
                )
            )
            step = CHUNK_FRAMES * CHANNELS * SAMPLE_WIDTH
            for offset in range(0, len(audio), step):
                await websocket.send(audio[offset : offset + step])
                await asyncio.sleep(0.01)
            await websocket.send(json.dumps({"type": "audio_end", "turn_id": turn_id}))

        await websocket.send(json.dumps({"type": "turn_end", "turn_id": turn_id}))
        print(f"[relay] turn {self.turns} complete")

    async def _run_prompt(self, websocket, turn_id: str) -> None:
        """Pause the turn on a structured prompt, for testing RELAY-01's TUI.

        Reads directly off the same websocket `handle()` is iterating —
        safe because `handle()`'s `async for` is suspended on this coroutine
        for the duration of the call, so there is only ever one reader.
        """
        kind = self.args.prompt
        prompt_id = f"prompt-{self.turns}"
        if kind in ("approval", "confirm"):
            options = [{"id": "once", "label": "Allow Once"}, {"id": "deny", "label": "Deny"}]
            text = (
                "Allow running the requested command?"
                if kind == "approval"
                else "Proceed with this action?"
            )
        elif kind == "clarify":
            options = [{"id": "dfw", "label": "DFW"}, {"id": "dal", "label": "DAL (Love Field)"}]
            text = "Which airport did you mean?"
        else:  # sudo / secret
            options = []
            text = "Enter the sudo password" if kind == "sudo" else "Enter the API key"

        await websocket.send(
            json.dumps(
                {
                    "type": "prompt_request",
                    "prompt_id": prompt_id,
                    "prompt_kind": kind,
                    "turn_id": turn_id,
                    "session_id": "default",
                    "text": text,
                    "options": options,
                    "sensitive": kind in ("sudo", "secret"),
                    "timeout_s": 300,
                }
            )
        )
        print(f"[relay] prompt_request sent: {kind} — {text!r}")

        rejected_once = False
        while True:
            frame = await websocket.recv()
            if isinstance(frame, bytes):
                continue
            response = json.loads(frame)
            if response.get("type") != "prompt_response":
                print(f"[relay] ignoring {response.get('type')!r} while awaiting a prompt response")
                continue
            print(
                "[relay] prompt_response received: "
                f"option_id={response.get('option_id')!r} "
                f"value={'<redacted>' if 'value' in response else None!r}"
            )
            if self.args.prompt_reject_once and not rejected_once:
                rejected_once = True
                await websocket.send(
                    json.dumps(
                        {
                            "type": "prompt_response_rejected",
                            "prompt_id": prompt_id,
                            "reason": "stub relay rejecting the first attempt",
                            "session_id": "default",
                        }
                    )
                )
                print("[relay] rejected the response once, as requested — try again")
                continue
            await websocket.send(
                json.dumps(
                    {
                        "type": "prompt_resolved",
                        "prompt_id": prompt_id,
                        "prompt_kind": kind,
                        "status": "accepted",
                        "session_id": "default",
                    }
                )
            )
            print("[relay] prompt resolved")
            return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument(
        "--reply",
        default="I am a stub relay. Hermes is not involved in this answer.",
        help="what every turn answers with",
    )
    parser.add_argument(
        "--think",
        type=float,
        default=1.0,
        help="seconds to stay silent before replying, so 'thinking' is visible",
    )
    parser.add_argument("--no-audio", action="store_true", help="reply with text only")
    parser.add_argument("--fail", action="store_true", help="answer every turn with an error")
    parser.add_argument(
        "--drop",
        action="store_true",
        help="hang up mid-turn on the first turn, to test reconnection",
    )
    parser.add_argument(
        "--prompt",
        choices=["approval", "confirm", "clarify", "sudo", "secret"],
        default=None,
        help="send a structured prompt before replying, to test RELAY-01's TUI",
    )
    parser.add_argument(
        "--prompt-reject-once",
        action="store_true",
        help="reject the first prompt_response for each turn, then accept the retry",
    )
    parser.add_argument(
        "--model",
        default="qwen2.5:7b",
        help="model name to report in hello_ack and session operations",
    )
    parser.add_argument(
        "--relay-version",
        default="0.8.0",
        help="relay server version to report in hello_ack and session operations",
    )
    parser.add_argument(
        "--context-limit",
        type=int,
        default=128000,
        help="context limit token count to report in hello_ack",
    )
    return parser


async def serve(args) -> None:
    relay = FakeRelay(args)
    async with websockets.serve(relay.handle, args.host, args.port):
        print(f"[relay] listening on ws://{args.host}:{args.port}/voice-session")
        print("[relay] point the client at it with --url and any --token")
        await asyncio.Future()


def main() -> int:
    args = build_parser().parse_args()
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        print("\n[relay] stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
