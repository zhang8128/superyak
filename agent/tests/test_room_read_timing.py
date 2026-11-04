"""scripts/room_read_timing.py, run as a person runs it, against a loopback server and a made-up key, and a curl shim
where a test needs to see what curl was given. It never touches a station."""
import http.server
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'room_read_timing.py'
ROOM = 'a' * 32
KEY = 'made-up-key-1234'
pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason='needs scripts/ from the full repository')


def run(*args, env=None):
    return subprocess.run([sys.executable, '-I', str(SCRIPT), *args], capture_output=True, text=True, timeout=60,
                          env=env or os.environ)


@pytest.fixture
def server():
    """A station stand-in: it records what it was asked and answers with the status the test sets."""
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        status = 200

        def do_GET(self):
            seen.append((self.path, self.headers.get('authorization')))
            body = b'{"messages": []}'
            self.send_response(type(self).status)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{httpd.server_address[1]}', seen, Handler
    httpd.shutdown()
    httpd.server_close()


def station_file(tmp_path, station, key=KEY):
    path = tmp_path / 'station.json'
    path.write_text(json.dumps({'station': station, 'key': key}))
    return str(path)


@pytest.fixture
def curl_shim(tmp_path):
    """A curl that records its arguments and stdin, and prints what the real one's -w would."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    log = tmp_path / 'curl.log'
    (bin_dir / 'curl').write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> {log}\ncat >> {log}\nprintf "200 0.01 0.02 0.03 2048 1.2.3.4"\n')
    (bin_dir / 'curl').chmod(0o755)
    return {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}'}, log


def test_it_reads_the_room_as_the_web_app_does_with_this_ships_key(server, tmp_path):
    station, seen, _ = server
    done = run('--room', ROOM, '--runs', '3', '--gap-ms', '0', '--station-file', station_file(tmp_path, station))
    assert done.returncode == 0, done.stderr
    assert seen == [(f'/api/chats/{ROOM}?limit=100', f'Bearer {KEY}')] * 3
    assert 'limit=100' in done.stdout and 'resolved' in done.stdout and 'n=3 ok=3' in done.stdout and 'failed 0' in done.stdout


def test_unpaged_also_reads_the_whole_room(server, tmp_path):
    station, seen, _ = server
    done = run('--room', ROOM, '--runs', '1', '--unpaged', '--station-file', station_file(tmp_path, station))
    assert done.returncode == 0, done.stderr
    assert [path for path, _ in seen] == [f'/api/chats/{ROOM}?limit=100', f'/api/chats/{ROOM}']
    assert 'unpaged' in done.stdout


def test_a_read_the_station_refuses_counts_as_failed_and_the_run_says_so(server, tmp_path):
    station, _, handler = server
    handler.status = 500
    done = run('--room', ROOM, '--runs', '2', '--gap-ms', '0', '--station-file', station_file(tmp_path, station))
    assert done.returncode == 1 and 'ok=0' in done.stdout and 'no good read' in done.stdout and 'failed 2' in done.stdout
    assert '500' in done.stdout and 'Traceback' not in done.stderr


def test_one_failed_read_among_good_ones_still_fails_the_run(curl_shim, tmp_path):
    env, _ = curl_shim
    flaky = Path(env['PATH'].split(':')[0]) / 'curl'
    count = tmp_path / 'count'
    flaky.write_text(f'#!/bin/sh\ncat >/dev/null\nif [ -f {count} ]; then printf "503 0 0 0.5 0"; else : > {count}; printf "200 0 0 0.1 10 1.2.3.4"; fi\n')
    done = run('--room', ROOM, '--runs', '2', '--gap-ms', '0', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 1 and 'ok=1' in done.stdout and 'failed 1' in done.stdout


def test_a_failed_path_before_a_good_one_still_fails_the_run(curl_shim, tmp_path):
    env, _ = curl_shim
    (Path(env['PATH'].split(':')[0]) / 'curl').write_text(
        '#!/bin/sh\ncat >/dev/null\ncase "$*" in *--resolve*) printf "200 0 0 0.1 10 1.2.3.4" ;; *) printf "503 0 0 0.1 10" ;; esac\n')
    done = run('--room', ROOM, '--runs', '1', '--pin', 'good=100.1.2.3', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 1 and 'ok=0' in done.stdout and 'ok=1' in done.stdout


def test_a_station_that_cant_be_reached_is_a_failed_run_not_a_crash(tmp_path):
    done = run('--room', ROOM, '--runs', '1', '--timeout', '2', '--station-file', station_file(tmp_path, 'http://127.0.0.1:9'))
    assert done.returncode == 1 and 'ok=0' in done.stdout and 'Traceback' not in done.stderr


def test_a_read_over_a_second_is_counted_and_shown(curl_shim, tmp_path):
    env, _ = curl_shim
    slow = Path(env['PATH'].split(':')[0]) / 'curl'
    slow.write_text('#!/bin/sh\ncat >/dev/null\nprintf "200 1.2 1.3 1.6 10 1.2.3.4"\n')
    done = run('--room', ROOM, '--runs', '1', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert 'over 1 s 1' in done.stdout and 'tls 1200 first byte 1300 total 1600 ms' in done.stdout


def test_the_key_reaches_curl_on_stdin_never_in_its_arguments(curl_shim, tmp_path):
    env, log = curl_shim
    done = run('--room', ROOM, '--runs', '1', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 0, done.stderr
    arguments, stdin = log.read_text().splitlines()
    assert KEY not in arguments and stdin == f'header = "authorization: Bearer {KEY}"'
    assert KEY not in done.stdout + done.stderr


@pytest.mark.parametrize('station, pin, resolve', [
    ('https://s.example', 'tailnet=100.1.2.3', 's.example:443:100.1.2.3'),
    ('https://s.example', 'six=::1', 's.example:443:[::1]'),
    ('http://s.example', 'plain=100.1.2.3', 's.example:80:100.1.2.3'),
    ('https://s.example:8443', 'port=100.1.2.3', 's.example:8443:100.1.2.3'),
])
def test_a_pin_adds_a_path_forced_to_that_address(curl_shim, tmp_path, station, pin, resolve):
    env, log = curl_shim
    done = run('--room', ROOM, '--runs', '1', '--pin', pin, '--station-file', station_file(tmp_path, station), env=env)
    assert done.returncode == 0, done.stderr
    lines = [line for line in log.read_text().splitlines() if line.startswith('-sS')]
    assert '--resolve' not in lines[0] and f'--resolve {resolve}' in lines[1]
    assert 'resolved' in done.stdout and pin.split('=')[0] in done.stdout


@pytest.mark.parametrize('args', [
    ['--room', 'not-a-room'], ['--room', '../../etc'], ['--room', ROOM, '--runs', '0'], ['--room', ROOM, '--runs', 'x'],
    ['--room', ROOM, '--limit', '0'], ['--room', ROOM, '--limit', '1001'], ['--room', ROOM, '--runs', '1001'], ['--room', ROOM, '--pin', 'noequals'], ['--room', ROOM, '--pin', 'a=not-an-ip'],
    ['--room', ROOM, '--pin', 'a b=1.2.3.4'], ['--room', ROOM, '--timeout', '0'], ['--room', ROOM, '--gap-ms', '-1'], [],
])
def test_bad_arguments_stop_before_any_read(curl_shim, tmp_path, args):
    env, log = curl_shim
    done = run(*args, '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 2 and 'Traceback' not in done.stderr and not log.exists()


def test_curl_output_that_isnt_its_format_is_a_failed_read(curl_shim, tmp_path):
    env, _ = curl_shim
    (Path(env['PATH'].split(':')[0]) / 'curl').write_text('#!/bin/sh\ncat >/dev/null\nprintf "not curl at all"\n')
    done = run('--room', ROOM, '--runs', '1', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 1 and 'ok=0' in done.stdout and 'Traceback' not in done.stderr


def test_no_curl_on_this_machine_is_a_failed_read(tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    done = run('--room', ROOM, '--runs', '1', '--station-file', station_file(tmp_path, 'https://s.example'),
               env={**os.environ, 'PATH': str(empty)})
    assert done.returncode == 1 and 'ok=0' in done.stdout and 'Traceback' not in done.stderr


def test_a_curl_that_wont_stop_is_a_failed_read(monkeypatch):
    spec = importlib.util.spec_from_file_location('room_read_timing', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    waited = []

    def hung(command, **kwargs):
        waited.append(kwargs['timeout'])
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
    monkeypatch.setattr(module.subprocess, 'run', hung)
    assert module.read_once('https://s.example', KEY, ROOM, '?limit=100', None, 1) == module.FAILED
    assert waited[0] > 1  # past curl's own --max-time, so curl stops itself first


def test_limit_and_timeout_reach_the_read(curl_shim, tmp_path):
    env, log = curl_shim
    done = run('--room', ROOM, '--runs', '1', '--limit', '5', '--timeout', '7', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 0, done.stderr
    arguments = log.read_text().splitlines()[0]
    assert f'/api/chats/{ROOM}?limit=5' in arguments and '--max-time 7 ' in arguments and 'limit=5' in done.stdout


def test_the_gap_falls_between_reads_only(curl_shim, tmp_path):
    env, _ = curl_shim
    started = time.monotonic()
    run('--room', ROOM, '--runs', '1', '--gap-ms', '3000', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert time.monotonic() - started < 2.5
    started = time.monotonic()
    run('--room', ROOM, '--runs', '2', '--gap-ms', '600', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert time.monotonic() - started >= 0.6


@pytest.mark.parametrize('content', ['not json', '[]', '{}', '{"station": 1, "key": 2}', '{"station": "ftp://x", "key": "k"}',
                                     '{"station": "https://", "key": "k"}',
                                     '{"station": "https://s.example", "key": "has\\"quote"}',
                                     '{"station": "https://s.example", "key": "two\\nlines"}', '{"station": "https://s.example", "key": ""}',
                                     '{"station": "https://s.example", "key": "has quote"}', '{"station": "https://s.example", "key": "has\\\\quote"}'])
def test_a_bad_station_file_stops_with_a_sentence_and_repeats_no_key(curl_shim, tmp_path, content):
    env, log = curl_shim
    path = tmp_path / 'station.json'
    path.write_text(content)
    done = run('--room', ROOM, '--station-file', str(path), env=env)
    assert done.returncode != 0 and done.stderr.startswith('room_read_timing:') and not log.exists()
    assert 'quote' not in done.stderr and 'lines' not in done.stderr


def test_a_missing_station_file_stops_with_a_sentence(tmp_path):
    done = run('--room', ROOM, '--station-file', str(tmp_path / 'nothing.json'))
    assert done.returncode != 0 and done.stderr.startswith('room_read_timing:')


@pytest.mark.parametrize('values, share, wanted', [([1], .95, 1), (list(range(1, 11)), .95, 10), (list(range(1, 21)), .95, 19),
                                                   (list(range(1, 101)), .95, 95)])
def test_p95_is_the_nearest_rank(values, share, wanted):
    spec = importlib.util.spec_from_file_location('room_read_timing', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.nearest_rank(values, share) == wanted
