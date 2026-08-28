"""Textual TUI for the Hermes voice-session channel.

Consumes events from client.py (text deltas, status, audio, turn_end)
and renders them into a scrolling transcript, replacing the print()
calls in hermes-hybrid-tui.py's turn loop.

The transcript is a single accumulated string rendered into a `Static`
inside a `VerticalScroll`. That mirrors the reference CLI's
`print(..., end="")`: each delta grows the buffer and re-renders, so
streamed tokens flow inline. A `RichLog` cannot do this — every
`write()` starts a new line, which turned a streamed sentence into a
token-per-line list.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Callable, Optional, Protocol

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Input, Static

import config
from audio import PCMPlayer, audio_path, write_wav
from client import send_hello, send_turn
from mic import load_microphone_class


class SessionProtocol(Protocol):
    """What `app.py` needs from a session — implemented by `HermesSession`
    and by the test doubles, so there is exactly one code path here."""

    turn_index: int

    async def connect(self) -> dict[str, Any]: ...

    def is_connected(self) -> bool: ...

    def send_turn(self, text: str, *, stt_source: str = "local") -> AsyncIterator[dict[str, Any]]: ...

    def capture_voice(self) -> str: ...

    async def close(self) -> None: ...


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

    def is_connected(self) -> bool:
        return self.ws is not None

    async def close(self) -> None:
        if self._connect_cm is not None:
            try:
                await self._connect_cm.__aexit__(None, None, None)
            finally:
                self._connect_cm = None
                self.ws = None

    def send_turn(self, text: str, *, stt_source: str = "local"):
        # turn_index stays 0-based for the first turn, matching the reference
        # script's `index` — _audio_path only adds a suffix from index 1 on.
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


RETRY_HINT = "Retry with a fresh --session-id after the remote model recovers."


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
        self.session: SessionProtocol = None  # type: ignore[assignment]
        self.player = PCMPlayer(enabled=not (args and args.no_play))
        self.transcript_text = ""
        self._turn_in_flight = False

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="transcript-scroll"):
            # markup=False so a literal "[error] ..." isn't eaten as Rich markup.
            yield Static("", id="transcript", markup=False)
        yield Input(placeholder="you>", id="input")
        yield Footer()

    # --- transcript rendering -------------------------------------------------

    def _append(self, text: str) -> None:
        """Append inline, exactly like the CLI's print(..., end="")."""
        if not text:
            return
        self.transcript_text += text
        self.query_one("#transcript", Static).update(self.transcript_text)
        self.query_one("#transcript-scroll", VerticalScroll).scroll_end(animate=False)

    def _append_block(self, text: str) -> None:
        """Append `text` on a line of its own, terminated by a newline."""
        prefix = "" if (not self.transcript_text or self.transcript_text.endswith("\n")) else "\n"
        self._append(f"{prefix}{text}\n")

    # --- lifecycle ------------------------------------------------------------

    async def on_mount(self) -> None:
        self.session = self._session_factory() if self._session_factory else HermesSession(self.args)
        self.set_focus(self.query_one("#input", Input))
        # In a worker so a hanging endpoint can't freeze the UI (or block ctrl+q).
        self.run_worker(self._connect(), exclusive=True)

    async def _connect(self) -> None:
        try:
            hello = await self.session.connect()
        except Exception as exc:  # nothing during connect may take the app down
            self._append_block(f"[error] {exc}")
            self._append_block(RETRY_HINT)
            return
        session_id = getattr(self.args, "session_id", "session")
        self._append_block(f"Connected to {session_id} (chat {hello.get('chat_id')}).")

    async def on_unmount(self) -> None:
        if self.session is not None:
            await self.session.close()

    # --- input paths ----------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        await self._run_turn(text)

    async def action_voice_turn(self) -> None:
        if self._turn_in_flight:
            self._append_block("[a turn is already in flight]")
            return
        self._append_block("listening…")
        transcript_text = await asyncio.to_thread(self.session.capture_voice)
        if not transcript_text:
            self._append_block("no speech detected.")
            return
        await self._run_turn(transcript_text, stt_source="local-faster-whisper")

    async def action_show_help(self) -> None:
        self._append_block(
            "Bindings: ctrl+r = voice turn, f1 = help, ctrl+q = quit. Everything typed is sent to Hermes."
        )

    # --- the turn loop --------------------------------------------------------

    async def _run_turn(self, text: str, *, stt_source: str = "local") -> None:
        if self._turn_in_flight:
            # Two coroutines calling ws.recv() concurrently raises
            # websockets.ConcurrencyError; refuse the second turn instead.
            self._append_block("[a turn is already in flight]")
            return
        if not self.session.is_connected():
            self._append_block(f"you> {text}")
            self._append_block("[error] not connected")
            return

        self._turn_in_flight = True
        index = self.session.turn_index
        self._append_block(f"you> {text}")
        self._append("hermes: ")
        timeout = getattr(self.args, "turn_timeout", 0) or 0
        try:
            events = self.session.send_turn(text, stt_source=stt_source)
            if timeout > 0:
                await asyncio.wait_for(self._consume_turn(events, index), timeout)
            else:
                await self._consume_turn(events, index)
        except (asyncio.TimeoutError, TimeoutError):
            self._append_block(
                f"[error] voice turn exceeded {timeout:g}s without completing; "
                "the remote model may be stalled. Start a fresh session and retry."
            )
        except Exception as exc:
            # ConnectionClosed, ConcurrencyError, AttributeError from a dead
            # socket — none of them should take the whole app down.
            self._append_block(f"[error] {exc}")
            self._append_block(RETRY_HINT)
        finally:
            # Always tear the stream down; leaving it open leaked a
            # sounddevice stream per failed turn.
            self.player.close()
            self._turn_in_flight = False

    async def _consume_turn(self, events: AsyncIterator[dict[str, Any]], index: int) -> None:
        audio = bytearray()
        audio_format: Optional[tuple[int, int, int]] = None

        async for event in events:
            kind = event["type"]
            if kind == "text_delta":
                self._append(event["text"])
            elif kind == "status":
                self._append(f"\n[{event['text']}]")
            elif kind == "audio_start":
                audio_format = (event["sample_rate"], event["channels"], event["sample_width"])
                self.player.start(audio_format)
                if self.player.active:
                    self._append(" [audio streaming]")
                elif self.player.failure:
                    self._append(f" [audio buffering: {self.player.failure}]")
            elif kind == "audio_chunk":
                audio.extend(event["data"])
                if self.player.active:
                    await asyncio.to_thread(self.player.write, event["data"])
            elif kind == "error":
                self._append_block(f"[error] {event['error']}")
            elif kind == "turn_end":
                self._append("\n")
                self._save_turn_audio(
                    bytes(audio), audio_format, index, event.get("turn_id", ""), self.player.active
                )

    def _save_turn_audio(
        self,
        audio: bytes,
        audio_format: Optional[tuple[int, int, int]],
        index: int,
        turn_id: str,
        played_live: bool,
    ) -> None:
        """Write the turn's PCM out as a WAV when asked to, or as a safety net
        when playback never went live — same rule as the reference script."""
        base = getattr(self.args, "output", None)
        if not (audio and audio_format and (base or not played_live)):
            return
        output = audio_path(base, index, turn_id or "turn")
        try:
            write_wav(output, audio, audio_format)
        except OSError as exc:
            self._append_block(f"[error] could not write {output}: {exc}")
            return
        self._append_block(f"audio: {output} ({len(audio)} PCM bytes)")


def main() -> int:
    parser = config.build_arg_parser()
    args = parser.parse_args()
    app = HermesStreamingApp(args=args)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
