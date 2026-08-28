"""Textual TUI for the Hermes voice-session channel.

Consumes events from client.py (text deltas, status, audio, turn_end)
and renders them into a scrolling transcript, replacing the print()
calls in hermes-hybrid-tui.py's turn loop.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, RichLog

import config
from audio import PCMPlayer
from client import ProtocolError, send_hello, send_turn
from mic import load_microphone_class


class HermesSession:
    """Owns one open websocket connection and turn history for the app's lifetime."""

    def __init__(self, args) -> None:
        self.args = args
        self.ws: Any = None
        self._connect_cm: Any = None
        self.turn_index = 0
        self.microphone: Any = None

    async def connect(self) -> dict[str, Any]:
        connect = config.connect_factory()
        token = config._resolve_token(self.args.token, self.args.profile_env)
        if not token:
            raise RuntimeError("No voice-session token found. Set VOICE_SESSION_TOKEN or use the profile .env.")
        kwargs = config._connection_kwargs(connect, token)
        self._connect_cm = connect(self.args.url, **kwargs)
        self.ws = await self._connect_cm.__aenter__()
        return await send_hello(
            self.ws,
            client_id=self.args.client_id,
            device_id=self.args.device_id,
            session_id=self.args.session_id,
            display_name=self.args.display_name,
        )

    async def close(self) -> None:
        if self._connect_cm is not None:
            await self._connect_cm.__aexit__(None, None, None)
            self._connect_cm = None

    def send_turn(self, text: str, *, stt_source: str = "local"):
        self.turn_index += 1
        return send_turn(self.ws, session_id=self.args.session_id, text=text, stt_source=stt_source)

    def capture_voice(self) -> str:
        if self.microphone is None:
            microphone_class = load_microphone_class(self.args.checkout)
            self.microphone = microphone_class(
                max_seconds=self.args.mic_max_seconds,
                silence_duration=self.args.mic_silence_duration,
                silence_threshold=self.args.mic_silence_threshold,
                model=self.args.stt_model,
            )
        return self.microphone.capture()


class HermesStreamingApp(App):
    """A Textual TUI for a Hermes voice-session chat."""

    BINDINGS = [
        ("ctrl+r", "voice_turn", "Voice turn"),
        ("f1", "show_help", "Help"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, args=None, session_factory: Optional[Callable[[], Any]] = None) -> None:
        super().__init__()
        self.args = args
        self._session_factory = session_factory
        self.session: Any = None
        self.player = PCMPlayer(enabled=not (args and args.no_play))

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield RichLog(id="transcript", wrap=True, highlight=True)
            yield Input(placeholder="you>", id="input")
        yield Footer()

    async def on_mount(self) -> None:
        self.session = self._session_factory() if self._session_factory else HermesSession(self.args)
        if isinstance(self.session, HermesSession):
            transcript = self.query_one("#transcript", RichLog)
            try:
                hello = await self.session.connect()
                transcript.write(f"Connected to {self.args.session_id} (chat {hello.get('chat_id')}).")
            except (ProtocolError, RuntimeError, OSError, ConnectionError) as exc:
                transcript.write(f"[error] {exc}")
        self.set_focus(self.query_one("#input", Input))

    async def on_unmount(self) -> None:
        if isinstance(self.session, HermesSession):
            await self.session.close()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        await self._run_turn(text)

    async def action_voice_turn(self) -> None:
        transcript = self.query_one("#transcript", RichLog)
        if not isinstance(self.session, HermesSession):
            await self.session.send_turn("(voice)")
            return
        transcript.write("listening…")
        transcript_text = await asyncio.to_thread(self.session.capture_voice)
        if not transcript_text:
            transcript.write("no speech detected.")
            return
        transcript.write(f"you (voice): {transcript_text}")
        await self._run_turn(transcript_text, stt_source="local-faster-whisper")

    async def action_show_help(self) -> None:
        self.query_one("#transcript", RichLog).write(
            "Bindings: ctrl+r = voice turn, f1 = help, ctrl+q = quit. Everything typed is sent to Hermes."
        )

    async def _run_turn(self, text: str, *, stt_source: str = "local") -> None:
        transcript = self.query_one("#transcript", RichLog)
        transcript.write(f"you> {text}")
        if not isinstance(self.session, HermesSession):
            await self.session.send_turn(text)
            return

        transcript.write("hermes: ", scroll_end=False)
        async for event in self.session.send_turn(text, stt_source=stt_source):
            kind = event["type"]
            if kind == "text_delta":
                transcript.write(event["text"])
            elif kind == "status":
                transcript.write(f"[{event['text']}]")
            elif kind == "audio_start":
                self.player.start((event["sample_rate"], event["channels"], event["sample_width"]))
                if self.player.active:
                    transcript.write(" [audio streaming]")
                elif self.player.failure:
                    transcript.write(f" [audio buffering: {self.player.failure}]")
            elif kind == "audio_chunk":
                await asyncio.to_thread(self.player.write, event["data"])
            elif kind == "error":
                transcript.write(f"[error] {event['error']}")
            elif kind == "turn_end":
                self.player.close()


def main() -> int:
    parser = config.build_arg_parser()
    args = parser.parse_args()
    app = HermesStreamingApp(args=args)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
