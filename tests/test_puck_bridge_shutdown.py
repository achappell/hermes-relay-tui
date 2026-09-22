"""Lifecycle evidence uses fake sessions/audio and loopback sockets only."""
import asyncio
import http.client
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

import pytest

from puck_bridge.receiver import ThreadingHTTPServer, make_handler
from puck_bridge.response import ResponseStream, ResponseStreamError
from puck_bridge.turn import TurnRunner


class Session:
    def __init__(self):
        self.closed = 0
        self.connected = False

    async def connect(self):
        self.connected = True

    async def close(self):
        self.closed += 1

    def is_connected(self):
        return self.connected


class Player:
    active = False
    failure = None

    def __init__(self):
        self.aborted = threading.Event()

    def abort(self):
        self.aborted.set()
        self.active = False

    def close(self):
        self.active = False

    def start(self, fmt):
        self.active = True

    def write(self, data):
        pass


def test_shutdown_latches_response_and_wakes_blocked_producer():
    stream = ResponseStream(max_queue_bytes=2)
    assert stream.expect(1)
    stream.begin(1, (16000, 1, 2))
    stream.write(b'aa', seq=1)
    finished = threading.Event()

    def produce():
        try:
            stream.write(b'bb', seq=1)
        except ResponseStreamError:
            pass
        finally:
            finished.set()

    worker = threading.Thread(target=produce)
    worker.start()
    stream.shutdown()
    assert finished.wait(1)
    worker.join()
    assert stream.queued_bytes == 0
    assert not stream.expect(2)
    with pytest.raises(ResponseStreamError):
        stream.begin(2, (16000, 1, 2))
    assert not stream.ready_for_eof(1)
    assert list(stream.iter_chunks()) == []


def test_connect_cleanup_is_cancelled_once_and_all_callers_share_deadline(caplog):
    entered = threading.Event()
    cleaning = threading.Event()
    release = threading.Event()

    class Slow(Session):
        cancels = 0

        async def connect(self):
            entered.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                self.cancels += 1
                cleaning.set()
                while not release.is_set():
                    await asyncio.sleep(.001)
                raise

    session = Slow()
    runner = TurnRunner(session, player=Player())
    starter = threading.Thread(target=runner.start)
    starter.start()
    assert entered.wait(1)
    start = time.monotonic()
    try:
        assert not runner.stop(start + .08)
        assert cleaning.is_set()
        assert not runner.stop(time.monotonic() + 10)
        assert time.monotonic() - start < .3
        assert session.closed == 0
        assert runner.submit_transcript('late') is False
        assert 'cleanup pending' in caplog.text
    finally:
        release.set()
        starter.join(2)
        runner.wait_closed()
    assert session.cancels == 1
    assert session.closed == 1
    assert runner._loop.is_closed()


def test_stalled_generator_does_not_delay_playback_abort():
    waiting = threading.Event()
    cleaning = threading.Event()
    release = threading.Event()

    class Slow(Session):
        async def send_turn(self, text, **kwargs):
            yield {'type': 'audio_start', 'sample_rate': 16000, 'channels': 1, 'sample_width': 2}
            yield {'type': 'audio_chunk', 'data': b'aa'}
            waiting.set()
            try:
                await asyncio.sleep(60)
            finally:
                cleaning.set()
                while not release.is_set():
                    await asyncio.sleep(.001)

    session = Slow()
    player = Player()
    runner = TurnRunner(session, player=player)
    runner.start()
    worker = threading.Thread(target=lambda: runner.submit_transcript('question'))
    worker.start()
    assert waiting.wait(1)
    try:
        assert not runner.stop(time.monotonic() + .08)
        assert cleaning.is_set()
        assert player.aborted.is_set()
        assert session.closed == 0
    finally:
        release.set()
        worker.join(2)
        runner.wait_closed()
    assert session.closed == 1


def test_native_write_completion_outlives_cancelled_async_wrapper():
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    class Native(Player):
        def write(self, data):
            entered.set()
            release.wait()
            completed.set()

    class AudioSession(Session):
        async def send_turn(self, text, **kwargs):
            yield {'type': 'audio_start', 'sample_rate': 16000, 'channels': 1, 'sample_width': 2}
            yield {'type': 'audio_chunk', 'data': b'aa'}

    player = Native()
    runner = TurnRunner(AudioSession(), player=player)
    runner.start()
    worker = threading.Thread(target=lambda: runner.submit_transcript('question'))
    worker.start()
    assert entered.wait(1)
    try:
        assert not runner.stop(time.monotonic() + .08)
        assert player.aborted.is_set()
        assert not completed.is_set()
        assert not runner._closed.is_set()
        assert runner._loop_thread.is_alive()
    finally:
        release.set()
        worker.join(2)
        runner.wait_closed()
    assert completed.is_set()


def test_transcription_retains_wav_until_worker_finishes_and_rejects_late_result(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    paths = []
    admitted = []

    def transcribe(path):
        paths.append(Path(path))
        entered.set()
        release.wait()
        return {'success': True, 'transcript': 'late'}

    handler = make_handler(expected_token='fake', on_transcript=admitted.append,
                           transcribe_fn=transcribe)
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    serving = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02})
    serving.start()
    connection = http.client.HTTPConnection(*server.server_address)
    try:
        connection.request('POST', '/upload?seq=1&chunk=0&total=1', body=b'\0'*8,
                           headers={'X-Puck-Token': 'fake'})
        response = connection.getresponse()
        response.read()
        assert response.status == 200
        assert entered.wait(1)
        server.request_stop()
        server.shutdown()
        server.server_close()
        assert not server.wait_workers(time.monotonic() + .03)
        assert paths[0].exists()
    finally:
        release.set()
        connection.close()
        serving.join(2)
        server.wait_workers()
    assert not admitted
    assert not paths[0].exists()
    assert not paths[0].parent.exists()


def test_partial_http_body_socket_is_closed_on_stop():
    handler = make_handler(expected_token='fake', on_transcript=lambda _: True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    serving = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02})
    serving.start()
    connection = socket.create_connection(server.server_address)
    connection.sendall(b'POST /upload?seq=1&chunk=0&total=2 HTTP/1.1\r\nHost: localhost\r\nX-Puck-Token: fake\r\nContent-Length: 200\r\n\r\nx')
    deadline = time.monotonic() + 1
    while not server._sockets and time.monotonic() < deadline:
        time.sleep(.001)
    server.request_stop()
    server.shutdown()
    server.server_close()
    assert server.wait_workers(time.monotonic() + .5)
    connection.settimeout(.5)
    assert connection.recv(1024) == b''
    connection.close()
    serving.join(1)


@pytest.mark.parametrize('sig', [signal.SIGINT, signal.SIGTERM])
@pytest.mark.parametrize('startup', [False, True, 'active'])
def test_module_entry_signals_stop_real_process_without_live_services(tmp_path, sig, startup):
    # sitecustomize installs fakes before `python -m puck_bridge` delegates to
    # main. A pipe-backed ready file synchronizes signals with connect/serving.
    ready = tmp_path / 'ready'
    closed = tmp_path / 'closed'
    site = tmp_path / 'sitecustomize.py'
    site.write_text(f'''
import asyncio
from pathlib import Path
from types import SimpleNamespace
from puck_bridge import server
server.build_session_args = lambda args: SimpleNamespace(profile_env=Path("unused"), profile_name="fake", session_id="fake")
server.config.resolve_puck_device_token = lambda path: "fake"
class Session:
    async def connect(self):
        if {startup!r} is True:
            Path({str(ready)!r}).write_text("connect")
            await asyncio.sleep(60)
    async def close(self):
        Path({str(closed)!r}).write_text("closed")
    def is_connected(self): return True
    async def send_turn(self, text, **kwargs):
        yield {{"type": "audio_start", "sample_rate": 16000, "channels": 1, "sample_width": 2}}
        yield {{"type": "audio_chunk", "data": b"aa"}}
        Path({str(ready)!r}).write_text("active")
        await asyncio.sleep(60)
if {startup!r} == "active":
    import threading
    OriginalRunner = server.TurnRunner
    class Runner(OriginalRunner):
        def start(self, **kwargs):
            super().start(**kwargs)
            threading.Thread(target=lambda: self.submit_transcript("fake")).start()
    server.TurnRunner = Runner
server.HermesSession = lambda args: Session()
original = server.ThreadingHTTPServer
class HTTP(original):
    def handle_request(self):
        if {startup!r} != "active":
            Path({str(ready)!r}).write_text("serve")
        super().handle_request()
server.ThreadingHTTPServer = HTTP
''')
    env = dict(os.environ, PYTHONPATH=str(tmp_path) + os.pathsep + str(Path.cwd()))
    process = subprocess.Popen([sys.executable, '-m', 'puck_bridge', '--host', '127.0.0.1', '--port', '0'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.exists()
        started = time.monotonic()
        process.send_signal(sig)
        stdout, stderr = process.communicate(timeout=2)
        assert time.monotonic() - started < 1
        assert process.returncode == 0, stderr.decode()
        assert closed.exists()
        if startup is True:
            assert 'listening' not in stderr.decode()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


@pytest.mark.parametrize('stage', ['connect', 'handler', 'bind'])
def test_partial_startup_preserves_failure_closes_session_restores_signals(monkeypatch, stage):
    from types import SimpleNamespace
    from puck_bridge import server
    session = Session()
    original_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    failure = RuntimeError('synthetic startup failure')
    if stage == 'connect':
        async def connect():
            raise failure
        session.connect = connect
    monkeypatch.setattr(server, 'build_session_args', lambda _: SimpleNamespace(profile_env=Path('unused'), profile_name='fake', session_id='fake'))
    monkeypatch.setattr(server.config, 'resolve_puck_device_token', lambda _: 'fake')
    monkeypatch.setattr(server, 'HermesSession', lambda _: session)
    def fail(*args, **kwargs):
        raise failure
    if stage == 'handler':
        monkeypatch.setattr(server, 'make_handler', fail)
    if stage == 'bind':
        monkeypatch.setattr(server, 'ThreadingHTTPServer', fail)
    with pytest.raises(RuntimeError) as result:
        server.main(['--host', '127.0.0.1', '--port', '0'])
    assert result.value is failure
    assert session.closed == 1
    assert all(signal.getsignal(sig) is old for sig, old in original_signals.items())


def test_owned_native_close_does_not_release_owner_at_audio_timeout():
    from puck_bridge.turn import _OwnedPCMPlayer
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    class Native:
        def stop(self):
            pass
        def abort(self):
            pass
        def close(self):
            entered.set()
            release.wait()
            completed.set()
    player = _OwnedPCMPlayer(True)
    native = Native()
    player.stream = native
    runner = TurnRunner(Session(), player=player)
    runner.start()
    try:
        assert not runner.stop(time.monotonic() + .05)
        assert entered.wait(1)
        assert player.stream is native
        assert not completed.is_set()
        assert not runner._closed.is_set()
    finally:
        release.set()
        runner.wait_closed()
    assert completed.is_set()
    assert player.stream is None


def test_stop_before_start_closes_session_without_connecting():
    class NeverConnect(Session):
        async def connect(self):
            pytest.fail('stopped runner must not connect')
    session = NeverConnect()
    runner = TurnRunner(session, player=Player())
    assert runner.stop()
    runner.start()
    assert runner.stop()
    assert session.closed == 1


def test_concurrent_stop_has_one_owner():
    session = Session()
    runner = TurnRunner(session, player=Player())
    runner.start()
    workers = [threading.Thread(target=runner.stop) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(1)
        assert not worker.is_alive()
    assert session.closed == 1


def test_native_open_finishing_after_abort_is_owned_and_closed():
    entered = threading.Event()
    release = threading.Event()
    class SlowOpen(Player):
        def start(self, fmt):
            entered.set()
            release.wait()
            self.active = True
    class Audio(Session):
        async def send_turn(self, text, **kwargs):
            yield {'type': 'audio_start', 'sample_rate': 16000, 'channels': 1, 'sample_width': 2}
            yield {'type': 'audio_chunk', 'data': b'aa'}
    player = SlowOpen()
    runner = TurnRunner(Audio(), player=player)
    runner.start()
    worker = threading.Thread(target=lambda: runner.submit_transcript('question'))
    worker.start()
    assert entered.wait(1)
    try:
        assert not runner.stop(time.monotonic() + .05)
        assert player.aborted.is_set()
        assert not runner._closed.is_set()
    finally:
        release.set()
        worker.join(2)
        runner.wait_closed()
    assert not player.active


def test_shutdown_during_timed_out_generator_cleanup_never_cancels_twice(monkeypatch):
    from puck_bridge import turn
    monkeypatch.setattr(turn, 'FIRST_EVENT_TIMEOUT_SECONDS', .01)
    cleaning = threading.Event()
    release = threading.Event()
    cancellations = []
    class Slow(Session):
        async def send_turn(self, text, **kwargs):
            try:
                await asyncio.sleep(60)
                yield {}
            except asyncio.CancelledError:
                cancellations.append('first')
                cleaning.set()
                try:
                    while not release.is_set():
                        await asyncio.sleep(.001)
                except asyncio.CancelledError:
                    cancellations.append('second')
                    raise
                raise
    runner = TurnRunner(Slow(), player=Player())
    runner.start()
    worker = threading.Thread(target=lambda: runner.submit_transcript('question'))
    worker.start()
    assert cleaning.wait(1)
    try:
        assert not runner.stop(time.monotonic() + .05)
        assert cancellations == ['first']
    finally:
        release.set()
        worker.join(2)
        runner.wait_closed()
    assert cancellations == ['first']


def test_real_player_native_start_lock_cannot_block_shutdown_loop(monkeypatch):
    from types import SimpleNamespace
    from puck_bridge.turn import _OwnedPCMPlayer
    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    class Native:
        def __init__(self, **kwargs):
            pass
        def start(self):
            entered.set()
            release.wait()
        def stop(self):
            pass
        def abort(self):
            pass
        def close(self):
            closed.set()
    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace(RawOutputStream=Native))
    class Audio(Session):
        async def send_turn(self, text, **kwargs):
            yield {'type': 'audio_start', 'sample_rate': 16000, 'channels': 1, 'sample_width': 2}
    player = _OwnedPCMPlayer(True)
    runner = TurnRunner(Audio(), player=player)
    runner.start()
    worker = threading.Thread(target=lambda: runner.submit_transcript('question'))
    worker.start()
    assert entered.wait(1)
    responsive = threading.Event()
    try:
        assert not runner.stop(time.monotonic() + .05)
        runner._loop.call_soon_threadsafe(responsive.set)
        assert responsive.wait(.2)
        assert not closed.is_set()
    finally:
        release.set()
        worker.join(2)
        runner.wait_closed()
    assert closed.is_set()


@pytest.mark.parametrize('sig', [signal.SIGINT, signal.SIGTERM])
def test_standalone_retains_pending_startup_cleanup_after_shared_budget(tmp_path, sig):
    ready, cleaning, release, closed = [tmp_path / name for name in ('ready', 'cleaning', 'release', 'closed')]
    (tmp_path / 'sitecustomize.py').write_text(f'''
import asyncio
from pathlib import Path
from types import SimpleNamespace
from puck_bridge import server
server.SHUTDOWN_TIMEOUT_SECONDS = .05
server.build_session_args = lambda args: SimpleNamespace(profile_env=Path("unused"), profile_name="fake", session_id="fake")
server.config.resolve_puck_device_token = lambda path: "fake"
class Session:
    async def connect(self):
        Path({str(ready)!r}).touch()
        try:
            await asyncio.sleep(60)
        finally:
            Path({str(cleaning)!r}).touch()
            while not Path({str(release)!r}).exists():
                await asyncio.sleep(.005)
    async def close(self):
        Path({str(closed)!r}).touch()
    def is_connected(self): return False
server.HermesSession = lambda args: Session()
''')
    env = dict(os.environ, PYTHONPATH=str(tmp_path) + os.pathsep + str(Path.cwd()))
    process = subprocess.Popen([sys.executable, '-m', 'puck_bridge', '--host', '127.0.0.1', '--port', '0'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.005)
        assert ready.exists()
        process.send_signal(sig)
        deadline = time.monotonic() + 1
        while not cleaning.exists() and time.monotonic() < deadline:
            time.sleep(.005)
        assert cleaning.exists()
        process.send_signal(sig)
        time.sleep(.1)
        assert process.poll() is None
        assert not closed.exists()
        release.touch()
        stdout, stderr = process.communicate(timeout=2)
        assert process.returncode == 0, stderr.decode()
        assert closed.exists()
        assert 'cleanup pending' in stderr.decode()
        assert 'listening' not in stderr.decode()
    finally:
        if process.poll() is None:
            release.touch()
            process.kill()
            process.communicate()


def test_active_http_response_shutdown_truncates_body_without_success_terminator():
    stream = ResponseStream()
    assert stream.expect(4)
    stream.begin(4, (16000, 1, 2))
    # Enough PCM to pass the ordinary prebuffer while leaving the producer
    # active, so the reader genuinely waits in the streaming body.
    stream.write(b'\x01\x02' * 32000, seq=4)
    handler = make_handler(expected_token='fake', on_transcript=lambda _: True, response_stream=stream)
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    serving = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02})
    serving.start()
    connection = socket.create_connection(server.server_address)
    connection.settimeout(1)
    connection.sendall(b'GET /response?seq=4&token=fake HTTP/1.1\r\nHost: localhost\r\n\r\n')
    body = bytearray()
    try:
        while b'RIFF' not in body:
            body.extend(connection.recv(65536))
        assert b'200 OK' in body
        started = time.monotonic()
        server.request_stop()
        server.shutdown()
        server.server_close()
        assert server.wait_workers(started + 1)
        assert time.monotonic() - started < 1
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            body.extend(chunk)
        assert not body.endswith(b'0\r\n\r\n')
        assert stream.terminal_status == 'unavailable'
        assert not stream._reader_active
        assert not server._sockets
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        server.wait_workers()
        serving.join(1)


def test_real_bind_failure_closes_acquired_socket_and_handler_directory(monkeypatch):
    from types import SimpleNamespace
    from puck_bridge import server
    session = Session()
    occupied = socket.socket()
    occupied.bind(('127.0.0.1', 0))
    occupied.listen()
    captured = []
    dirs = []
    original_server = server.ThreadingHTTPServer
    original_mkdtemp = __import__('tempfile').mkdtemp
    def mkdtemp(*args, **kwargs):
        result = original_mkdtemp(*args, **kwargs)
        dirs.append(Path(result))
        return result
    class HTTP(original_server):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.append(self)
    monkeypatch.setattr('puck_bridge.receiver.tempfile.mkdtemp', mkdtemp)
    monkeypatch.setattr(server, 'ThreadingHTTPServer', HTTP)
    monkeypatch.setattr(server, 'build_session_args', lambda _: SimpleNamespace(profile_env=Path('unused'), profile_name='fake', session_id='fake'))
    monkeypatch.setattr(server.config, 'resolve_puck_device_token', lambda _: 'fake')
    monkeypatch.setattr(server, 'HermesSession', lambda _: session)
    try:
        with pytest.raises(OSError):
            server.main(['--host', '127.0.0.1', '--port', str(occupied.getsockname()[1])])
    finally:
        occupied.close()
    assert session.closed == 1
    assert len(captured) == 1
    assert captured[0].socket.fileno() == -1
    assert dirs and all(not path.exists() for path in dirs)


def test_backstop_during_shutdown_does_not_recancel_generator_cleanup(monkeypatch):
    from puck_bridge import turn
    monkeypatch.setattr(turn, 'TURN_BACKSTOP_SECONDS', .06)
    entered, cleaning, release = (threading.Event() for _ in range(3))
    cancellations = []
    class Slow(Session):
        async def send_turn(self, text, **kwargs):
            entered.set()
            try:
                await asyncio.sleep(60)
                yield {}
            finally:
                cleaning.set()
                try:
                    while not release.is_set():
                        await asyncio.sleep(.001)
                except asyncio.CancelledError:
                    cancellations.append('recancelled')
                    raise
    runner = TurnRunner(Slow(), player=Player())
    runner.start()
    worker = threading.Thread(target=lambda: runner.submit_transcript('fake'))
    worker.start()
    assert entered.wait(1)
    try:
        assert not runner.stop(time.monotonic() + .02)
        assert cleaning.wait(1)
        worker.join(.3)
        assert not worker.is_alive()
        assert not runner._closed.is_set()
        assert not cancellations
    finally:
        release.set()
        runner.wait_closed()
        worker.join(1)


def test_actual_native_writer_outlives_abort_timeout_then_is_closed(monkeypatch):
    from types import SimpleNamespace
    import audio
    from puck_bridge.turn import _OwnedPCMPlayer
    monkeypatch.setattr(audio, 'AUDIO_TEARDOWN_TIMEOUT', .01)
    entered, release, closed = (threading.Event() for _ in range(3))
    class Native:
        def __init__(self, **kwargs): pass
        def start(self): pass
        def stop(self): pass
        def abort(self): pass
        def write(self, data):
            entered.set()
            release.wait()
        def close(self): closed.set()
    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace(RawOutputStream=Native))
    class Audio(Session):
        async def send_turn(self, text, **kwargs):
            yield {'type': 'audio_start', 'sample_rate': 16000, 'channels': 1, 'sample_width': 2}
            yield {'type': 'audio_chunk', 'data': b'aa'}
    player = _OwnedPCMPlayer(True, prebuffer_seconds=0)
    runner = TurnRunner(Audio(), player=player)
    runner.start()
    worker = threading.Thread(target=lambda: runner.submit_transcript('fake'))
    worker.start()
    assert entered.wait(1)
    try:
        assert not runner.stop(time.monotonic() + .05)
        assert player.stream is not None
        assert not closed.is_set()
    finally:
        release.set()
        runner.wait_closed()
        worker.join(1)
    assert closed.is_set()
    assert player.stream is None


@pytest.mark.parametrize('resource', ['session', 'native_close'])
def test_cleanup_failure_retains_owner_until_resource_can_close(resource, caplog):
    from puck_bridge.turn import _OwnedPCMPlayer
    release = threading.Event()
    attempted = threading.Event()
    class FailingSession(Session):
        async def close(self):
            if resource == 'session' and not release.is_set():
                attempted.set()
                raise RuntimeError('PRIVATE_SESSION_TEXT')
            await super().close()
    class Native:
        def abort(self): pass
        def stop(self): pass
        def close(self):
            if not release.is_set():
                attempted.set()
                raise RuntimeError('PRIVATE_NATIVE_TEXT')
    session = FailingSession()
    player = _OwnedPCMPlayer(True) if resource == 'native_close' else Player()
    if resource == 'native_close': player.stream = Native()
    runner = TurnRunner(session, player=player)
    runner.start()
    try:
        assert not runner.stop(time.monotonic() + .07)
        assert attempted.is_set()
        assert runner._loop_thread.is_alive()
        assert not runner._shutdown_future.done()
        if resource == 'native_close': assert player.stream is not None
        assert 'cleanup pending' in caplog.text
        assert 'PRIVATE_' not in caplog.text
    finally:
        release.set()
        runner.wait_closed()
    assert session.closed == 1
    if resource == 'native_close': assert player.stream is None


def test_failed_abort_does_not_skip_late_open_cleanup(caplog):
    entered, release = threading.Event(), threading.Event()
    class Late(Player):
        attempts = 0
        def start(self, fmt):
            entered.set()
            release.wait()
            self.active = True
        def abort(self):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError('PRIVATE_ABORT_TEXT')
            super().abort()
    class Audio(Session):
        async def send_turn(self, text, **kwargs):
            yield {'type': 'audio_start', 'sample_rate': 16000, 'channels': 1, 'sample_width': 2}
    player = Late()
    runner = TurnRunner(Audio(), player=player)
    runner.start()
    worker = threading.Thread(target=lambda: runner.submit_transcript('fake'))
    worker.start()
    assert entered.wait(1)
    try:
        assert not runner.stop(time.monotonic() + .05)
        assert not runner._shutdown_future.done()
    finally:
        release.set()
        runner.wait_closed()
        worker.join(1)
    assert player.attempts == 2
    assert not player.active
    assert 'PRIVATE_ABORT_TEXT' not in caplog.text


def test_server_close_final_worker_removes_directory_without_wait_workers():
    entered, release = threading.Event(), threading.Event()
    paths = []
    def transcribe(path):
        paths.append(Path(path))
        entered.set()
        release.wait()
        return {'success': True, 'transcript': 'late'}
    handler = make_handler(expected_token='fake', on_transcript=lambda _: pytest.fail('late admission'), transcribe_fn=transcribe)
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    serving = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
    serving.start()
    client = http.client.HTTPConnection(*server.server_address)
    try:
        client.request('POST', '/upload?seq=1&chunk=0&total=1', b'\0'*8, {'X-Puck-Token': 'fake'})
        assert client.getresponse().status == 200
        assert entered.wait(1)
        server.shutdown()
        server.server_close()
        assert paths[0].exists()
    finally:
        release.set()
        client.close()
        serving.join(1)
    deadline = time.monotonic() + 1
    while paths[0].parent.exists() and time.monotonic() < deadline:
        time.sleep(.005)
    assert not paths[0].parent.exists()


@pytest.mark.parametrize('sig', [signal.SIGINT, signal.SIGTERM])
@pytest.mark.parametrize('mode', ['partial_upload', 'response', 'transcription'])
def test_main_signals_close_http_admission_and_retain_delayed_cleanup(tmp_path, sig, mode):
    port_file, ready, release, wav_file, turn_file = [tmp_path / name for name in ('port', 'ready', 'release', 'wav', 'turn')]
    (tmp_path / 'sitecustomize.py').write_text(f'''
import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from puck_bridge import server
server.SHUTDOWN_TIMEOUT_SECONDS = .05
server.build_session_args = lambda args: SimpleNamespace(profile_env=Path("unused"), profile_name="fake", session_id="fake")
server.config.resolve_puck_device_token = lambda path: "fake"
class Session:
    async def connect(self): pass
    async def close(self):
        while not Path({str(release)!r}).exists():
            await asyncio.sleep(.005)
    def is_connected(self): return True
    async def send_turn(self, text, **kwargs):
        Path({str(turn_file)!r}).touch()
        try:
            yield {{"type": "audio_start", "sample_rate": 16000, "channels": 1, "sample_width": 2}}
            yield {{"type": "audio_chunk", "data": b"aa" * 32000}}
            Path({str(ready)!r}).touch()
            await asyncio.sleep(60)
        finally:
            while not Path({str(release)!r}).exists():
                await asyncio.sleep(.005)
server.HermesSession = lambda args: Session()
original_handler = server.make_handler
def transcribe(path):
    Path({str(wav_file)!r}).write_text(path)
    if {mode!r} == "transcription":
        Path({str(ready)!r}).touch()
        while not Path({str(release)!r}).exists():
            time.sleep(.005)
    return {{"success": True, "transcript": "fake"}}
def handler(**kwargs):
    return original_handler(**kwargs, transcribe_fn=transcribe)
server.make_handler = handler
OriginalHTTP = server.ThreadingHTTPServer
class HTTP(OriginalHTTP):
    def server_activate(self):
        super().server_activate()
        pending_port = Path({str(port_file)!r}).with_suffix(".pending")
        pending_port.write_text(str(self.server_address[1]))
        pending_port.replace(Path({str(port_file)!r}))
server.ThreadingHTTPServer = HTTP
''')
    env = dict(os.environ, PYTHONPATH=str(tmp_path) + os.pathsep + str(Path.cwd()))
    process = subprocess.Popen([sys.executable, '-m', 'puck_bridge', '--host', '127.0.0.1', '--port', '0'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    connection = None
    upload = None
    body = bytearray()
    try:
        deadline = time.monotonic() + 5
        while not port_file.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.005)
        assert port_file.exists()
        port = int(port_file.read_text())
        if mode == 'partial_upload':
            connection = socket.create_connection(('127.0.0.1', port))
            connection.sendall(b'POST /upload?seq=1&chunk=0&total=2 HTTP/1.1\r\nHost: localhost\r\nX-Puck-Token: fake\r\nContent-Length: 200\r\n\r\nx')
        else:
            upload = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
            upload.request('POST', '/upload?seq=1&chunk=0&total=1', b'\0'*8, {'X-Puck-Token': 'fake'})
            response = upload.getresponse()
            assert response.status == 200
            response.read()
            deadline = time.monotonic() + 2
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.005)
            assert ready.exists()
            if mode == 'response':
                connection = socket.create_connection(('127.0.0.1', port))
                connection.settimeout(1)
                connection.sendall(b'GET /response?seq=1&token=fake HTTP/1.1\r\nHost: localhost\r\n\r\n')
                while b'RIFF' not in body:
                    chunk = connection.recv(65536)
                    assert chunk
                    body.extend(chunk)
            else:
                connection = upload.sock
                assert Path(wav_file.read_text()).exists()
        started = time.monotonic()
        process.send_signal(sig)
        connection.settimeout(.8)
        while True:
            try:
                chunk = connection.recv(65536)
            except ConnectionResetError:
                break
            if not chunk:
                break
            body.extend(chunk)
        # The listener must close as well as this particular connection.
        while True:
            try:
                probe = socket.create_connection(('127.0.0.1', port), timeout=.05)
            except OSError:
                break
            probe.close()
            assert time.monotonic() - started < 1
            time.sleep(.005)
        assert time.monotonic() - started < 1
        time.sleep(.1)
        assert process.poll() is None
        if mode == 'response': assert not body.endswith(b'0\r\n\r\n')
        if mode == 'transcription':
            assert Path(wav_file.read_text()).exists()
            assert not turn_file.exists()
        release.touch()
        stdout, stderr = process.communicate(timeout=2)
        assert process.returncode == 0, stderr.decode()
        assert 'cleanup pending' in stderr.decode()
        if wav_file.exists():
            assert not Path(wav_file.read_text()).parent.exists()
        if mode == 'transcription': assert not turn_file.exists()
    finally:
        release.touch()
        if connection is not None: connection.close()
        if upload is not None: upload.close()
        if process.poll() is None:
            process.kill()
            process.communicate()
