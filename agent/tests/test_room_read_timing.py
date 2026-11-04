"""scripts/room_read_timing.py, run as a person runs it, against a loopback server and a made-up key with real curl, and a
curl shim where a test needs exact numbers or to see what curl was given. It never touches a station."""
import http.server
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'room_read_timing.py'
ROOM = 'a' * 32
KEY = 'made-up-key-1234'
PAGE = f'/api/chats/{ROOM}?limit=100'
WHOLE = f'/api/chats/{ROOM}'
pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason='needs scripts/ from the full repository')


def module():
    spec = importlib.util.spec_from_file_location('room_read_timing', SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def run(*args, env=None):
    return subprocess.run([sys.executable, '-I', str(SCRIPT), *args], capture_output=True, text=True, timeout=90,
                          env=env or os.environ)


def station_file(tmp_path, station, key=KEY):
    path = tmp_path / 'station.json'
    path.write_text(json.dumps({'station': station, 'key': key}))
    return str(path)


def make_server(respond=None):
    """A station stand-in: it records what it was asked, and `respond(handler)` answers when one is given."""
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get('authorization')))
            if respond:
                respond(self)
                return
            body = b'{"messages": []}'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f'http://127.0.0.1:{httpd.server_address[1]}', seen


@pytest.fixture
def servers():
    made = []

    def start(respond=None):
        httpd, url, seen = make_server(respond)
        made.append(httpd)
        return url, seen
    yield start
    for httpd in made:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def real_curl(tmp_path):
    """The real curl with its own empty home and no proxy, so the runner's own settings can't change a test."""
    home = tmp_path / 'curl-home'
    home.mkdir()
    env = {key: value for key, value in os.environ.items() if key.lower() not in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')}
    return {**env, 'CURL_HOME': str(home), 'HOME': str(home), 'XDG_CONFIG_HOME': str(home)}, home


@pytest.fixture
def curl_shim(tmp_path):
    """A curl that logs its arguments, stdin and environment, and prints line after line of `rows`, each `exit|output`;
    the last line repeats. By default every read is a quick good one."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    log, rows, count, environment = (tmp_path / name for name in ('curl.log', 'rows', 'count', 'curl.env'))
    rows.write_text('0|200 0.01 0.02 0.03 2048 1.2.3.4\n')
    (bin_dir / 'curl').write_text(f'''#!/bin/sh
printf "%s\\n" "$*" >> "{log}"
cat >> "{log}"
env >> "{environment}"
n=$(cat "{count}" 2>/dev/null || echo 0)
echo $((n + 1)) > "{count}"
line=$(sed -n "$((n + 1))p" "{rows}")
[ -n "$line" ] || line=$(tail -n 1 "{rows}")
printf "%s" "${{line#*|}}"
exit "${{line%%|*}}"
''')
    (bin_dir / 'curl').chmod(0o755)

    def feed(*lines):
        rows.write_text(''.join(f'{line}\n' for line in lines))
    return {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}'}, log, feed, environment


def arguments_of(log):
    return [line for line in log.read_text().splitlines() if '--max-time' in line]


# What it reads and prints

def test_it_reads_the_room_as_the_web_app_does(servers, tmp_path, real_curl):
    station, seen = servers()
    env, _ = real_curl
    done = run('--room', ROOM, '--runs', '3', '--gap-ms', '0', '--station-file', station_file(tmp_path, station), env=env)
    assert done.returncode == 0, done.stderr
    assert seen == [(PAGE, f'Bearer {KEY}')] * 3
    assert 'limit=100' in done.stdout and 'resolved' in done.stdout and 'n=3 ok=3' in done.stdout and 'failed 0' in done.stdout


def test_the_line_prints_the_numbers_it_exists_to_print(curl_shim, tmp_path):
    env, _, feed, _ = curl_shim
    feed('0|200 0.011 0.050 0.100 2048 1.2.3.4', '0|200 0.012 0.040 0.300 2048 1.2.3.4', '0|200 0.013 0.030 0.200 2048 1.2.3.4',
         '0|200 0.014 0.020 0.500 2048 1.2.3.4', '0|200 0.015 0.010 0.400 2048 1.2.3.4')
    done = run('--room', ROOM, '--runs', '5', '--gap-ms', '0', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 0, done.stderr
    assert 'n=5 ok=5 p50 300 p95 500 max 500 ms' in done.stdout
    assert 'tls p50 13 first byte p50 30' in done.stdout
    assert '2 KB' in done.stdout and 'ip 1.2.3.4' in done.stdout


def test_p95_comes_from_the_totals_in_order(curl_shim, tmp_path):
    env, _, feed, _ = curl_shim
    feed(*[f'0|200 0 0 {(21 - n) / 1000:.3f} 10 1.2.3.4' for n in range(1, 21)])
    done = run('--room', ROOM, '--runs', '20', '--gap-ms', '0', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert 'p95 19 max 20 ms' in done.stdout  # nearest rank 19 of 20, whatever order they came in


def test_size_comes_from_good_reads_and_every_address_shows(curl_shim, tmp_path):
    env, _, feed, _ = curl_shim
    feed('0|503 0 0 0.01 2 9.9.9.9', '0|200 0 0 0.01 50000 1.1.1.1', '0|200 0 0 0.01 80000 2.2.2.2')
    done = run('--room', ROOM, '--runs', '3', '--gap-ms', '0', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert '48-78 KB' in done.stdout and 'ip 1.1.1.1, 2.2.2.2, 9.9.9.9' in done.stdout


def test_a_run_says_what_room_when_and_how_long(curl_shim, tmp_path):
    env, _, _, _ = curl_shim
    done = run('--room', ROOM, '--runs', '1', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert re.search(rf'room {ROOM[:8]} \d{{4}}-\d\d-\d\dT\d\d:\d\d:\d\dZ, wall \d+\.\d s, 1 reads', done.stdout)


def test_a_read_over_a_second_is_counted_and_shown(curl_shim, tmp_path):
    env, _, feed, _ = curl_shim
    feed('0|200 1.2 1.3 1.6 10 1.2.3.4', '0|200 0 0 1.0 10 1.2.3.4', '0|200 0 0 1.001 10 1.2.3.4')
    done = run('--room', ROOM, '--runs', '3', '--gap-ms', '0', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert 'over 1 s 2' in done.stdout and 'tls 1200 first byte 1300 total 1600 ms' in done.stdout


def test_up_to_six_slow_reads_are_shown(curl_shim, tmp_path):
    env, _, feed, _ = curl_shim
    feed('0|200 0 0 1.5 10 1.2.3.4')
    done = run('--room', ROOM, '--runs', '8', '--gap-ms', '0', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert 'over 1 s 8' in done.stdout and done.stdout.count('total 1500 ms') == 6


def test_max_covers_a_failed_read_too(curl_shim, tmp_path):
    env, _, feed, _ = curl_shim
    feed('0|200 0 0 0.002 10 1.2.3.4', '0|503 0 0 5.001 10 1.2.3.4', '0|200 0 0 0.002 10 1.2.3.4')
    done = run('--room', ROOM, '--runs', '3', '--gap-ms', '0', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert 'max 5001 ms' in done.stdout


@pytest.mark.parametrize('values, wanted', [([1], 1), (list(range(1, 11)), 10), (list(range(1, 21)), 19), (list(range(1, 101)), 95)])
def test_p95_is_the_nearest_rank(values, wanted):
    assert module().nearest_rank(values, .95) == wanted


# A read that went wrong is not a good read

def cut_off(handler):
    handler.send_response(200)
    handler.send_header('Content-Length', '100000')
    handler.end_headers()
    handler.wfile.write(b'0123456789')
    handler.wfile.flush()
    handler.close_connection = True


def stalls(handler):
    handler.send_response(200)
    handler.send_header('Content-Length', '100000')
    handler.end_headers()
    handler.wfile.write(b'0123456789')
    handler.wfile.flush()
    time.sleep(4)
    handler.close_connection = True


def test_a_cut_off_200_is_a_failed_read(servers, tmp_path, real_curl):
    station, _ = servers(cut_off)
    env, _ = real_curl
    done = run('--room', ROOM, '--runs', '2', '--gap-ms', '0', '--station-file', station_file(tmp_path, station), env=env)
    assert done.returncode == 1 and 'ok=0' in done.stdout and 'failed 2' in done.stdout and 'curl exits [18]' in done.stdout


def test_a_200_that_stalls_past_the_timeout_is_a_failed_read(servers, tmp_path, real_curl):
    station, _ = servers(stalls)
    env, _ = real_curl
    done = run('--room', ROOM, '--runs', '1', '--timeout', '1', '--station-file', station_file(tmp_path, station), env=env)
    assert done.returncode == 1 and 'ok=0' in done.stdout and 'curl exits [28]' in done.stdout


def test_a_read_the_station_refuses_counts_as_failed(curl_shim, tmp_path):
    env, _, feed, _ = curl_shim
    feed('0|500 0 0 0.01 10')
    done = run('--room', ROOM, '--runs', '2', '--gap-ms', '0', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 1 and 'ok=0' in done.stdout and 'no good read' in done.stdout and 'failed 2' in done.stdout
    assert 'codes [500]' in done.stdout and 'Traceback' not in done.stderr


def test_one_failed_read_among_good_ones_still_fails_the_run(curl_shim, tmp_path):
    env, _, feed, _ = curl_shim
    feed('0|200 0 0 0.1 10 1.2.3.4', '0|503 0 0 0.5 0')
    done = run('--room', ROOM, '--runs', '2', '--gap-ms', '0', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 1 and 'ok=1' in done.stdout and 'failed 1' in done.stdout


def test_a_failed_path_before_a_good_one_still_fails_the_run(curl_shim, tmp_path):
    env, _, _, _ = curl_shim
    (Path(env['PATH'].split(':')[0]) / 'curl').write_text(
        '#!/bin/sh\ncat >/dev/null\ncase "$*" in *--resolve*) printf "200 0 0 0.1 10 1.2.3.4" ;; *) printf "503 0 0 0.1 10" ;; esac\n')
    done = run('--room', ROOM, '--runs', '1', '--pin', 'good=100.1.2.3', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 1 and 'ok=0' in done.stdout and 'ok=1' in done.stdout


def test_a_station_that_cant_be_reached_is_a_failed_run_with_curls_reason(tmp_path, real_curl):
    env, _ = real_curl
    done = run('--room', ROOM, '--runs', '1', '--timeout', '2', '--station-file', station_file(tmp_path, 'http://127.0.0.1:9'), env=env)
    assert done.returncode == 1 and 'ok=0' in done.stdout and 'curl exits [7]' in done.stdout and 'Traceback' not in done.stderr


def test_curl_output_that_isnt_its_format_is_a_failed_read(curl_shim, tmp_path):
    env, _, feed, _ = curl_shim
    feed('0|not curl at all')
    done = run('--room', ROOM, '--runs', '1', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 1 and 'ok=0' in done.stdout and 'Traceback' not in done.stderr


def test_no_curl_on_this_machine_is_a_failed_read(tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    done = run('--room', ROOM, '--runs', '1', '--station-file', station_file(tmp_path, 'https://s.example'),
               env={**os.environ, 'PATH': str(empty)})
    assert done.returncode == 1 and 'ok=0' in done.stdout and 'curl exits [-1]' in done.stdout and 'Traceback' not in done.stderr


def test_a_curl_that_wont_stop_is_killed_and_shows_its_real_time(tmp_path, curl_shim):
    env, _, _, _ = curl_shim
    (Path(env['PATH'].split(':')[0]) / 'curl').write_text('#!/bin/sh\nexec sleep 300\n')
    started = time.monotonic()
    done = run('--room', ROOM, '--runs', '1', '--timeout', '1', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    took = time.monotonic() - started
    assert done.returncode == 1 and 'curl exits [-1]' in done.stdout and 'over 1 s 1' in done.stdout
    assert 10 < took < 30


# The key stays where it belongs

def test_the_key_reaches_curl_on_stdin_and_nowhere_else(curl_shim, tmp_path):
    env, log, _, environment = curl_shim
    done = run('--room', ROOM, '--runs', '1', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 0, done.stderr
    arguments, stdin = log.read_text().splitlines()
    assert KEY not in arguments and stdin == f'header = "authorization: Bearer {KEY}"'
    assert KEY not in environment.read_text() and KEY not in done.stdout + done.stderr


@pytest.mark.parametrize('row', ['0|500 0 0 0.01 10', '7|000 0 0 0 0', '0|garbage', '28|200 0 0 25.0 10 1.2.3.4'])
def test_no_failed_read_prints_the_key(curl_shim, tmp_path, row):
    env, _, feed, _ = curl_shim
    feed(row)
    done = run('--room', ROOM, '--runs', '1', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 1 and KEY not in done.stdout + done.stderr


@pytest.mark.parametrize('station', ['http://s.example', 'http://100.1.2.3:8000', 'http://192.168.1.2'])
def test_plain_http_to_another_machine_is_refused(curl_shim, tmp_path, station):
    env, log, _, _ = curl_shim
    done = run('--room', ROOM, '--station-file', station_file(tmp_path, station), env=env)
    assert done.returncode != 0 and done.stderr.startswith('room_read_timing:') and not log.exists()
    assert KEY not in done.stdout + done.stderr


def test_a_pin_cant_send_plain_http_to_another_machine(curl_shim, tmp_path):
    env, log, _, _ = curl_shim
    done = run('--room', ROOM, '--pin', 'away=100.1.2.3', '--station-file', station_file(tmp_path, 'http://127.0.0.1:8000'), env=env)
    assert done.returncode != 0 and done.stderr.startswith('room_read_timing:') and not log.exists()


@pytest.mark.parametrize('station, pin', [('http://127.0.0.1:8000', None), ('http://localhost:8000', None), ('http://[::1]:8000', None),
                                          ('http://127.0.0.1:8000', 'here=127.0.0.2'), ('https://s.example', 'away=100.1.2.3')])
def test_plain_http_stays_on_this_machine_and_https_goes_anywhere(curl_shim, tmp_path, station, pin):
    env, _, _, _ = curl_shim
    done = run('--room', ROOM, '--runs', '1', *(['--pin', pin] if pin else []), '--station-file', station_file(tmp_path, station), env=env)
    assert done.returncode == 0, done.stderr


def test_curls_own_config_cant_store_the_key(servers, tmp_path, real_curl):
    station, _ = servers()
    env, home = real_curl
    trace = tmp_path / 'trace.txt'
    (home / '.curlrc').write_text(f'trace-ascii = "{trace}"\n')
    done = run('--room', ROOM, '--runs', '1', '--station-file', station_file(tmp_path, station), env=env)
    assert done.returncode == 0, done.stderr
    assert not trace.exists()


def test_a_proxy_in_the_environment_never_sees_the_read(servers, tmp_path, real_curl):
    station, seen = servers()
    proxy, proxied = servers()
    env, _ = real_curl
    done = run('--room', ROOM, '--runs', '1', '--station-file', station_file(tmp_path, station),
               env={**env, 'http_proxy': proxy, 'HTTP_PROXY': proxy, 'all_proxy': proxy})
    assert done.returncode == 0, done.stderr
    assert proxied == [] and seen == [(PAGE, f'Bearer {KEY}')]


def redirect_to(target):
    def respond(handler):
        handler.send_response(302)
        handler.send_header('Location', target + '/elsewhere')
        handler.send_header('Content-Length', '0')
        handler.end_headers()
    return respond


def test_a_redirect_is_a_failed_read_and_never_followed(servers, tmp_path, real_curl):
    target, reached = servers()
    station, _ = servers(redirect_to(target))
    env, home = real_curl
    (home / '.curlrc').write_text('location\n')  # the config that would follow it, kept out by -q
    done = run('--room', ROOM, '--runs', '1', '--station-file', station_file(tmp_path, station), env=env)
    assert done.returncode == 1 and 'codes [302]' in done.stdout and reached == []


# Paths, rounds and stopping

def test_each_round_reads_every_pair_once_and_the_order_rotates(servers, tmp_path, real_curl):
    station, seen = servers()
    env, _ = real_curl
    done = run('--room', ROOM, '--runs', '2', '--gap-ms', '0', '--unpaged', '--station-file', station_file(tmp_path, station), env=env)
    assert done.returncode == 0, done.stderr
    assert [path for path, _ in seen] == [PAGE, WHOLE, WHOLE, PAGE]
    assert 'unpaged' in done.stdout


def test_paths_are_interleaved_not_in_blocks(curl_shim, tmp_path):
    env, log, _, _ = curl_shim
    done = run('--room', ROOM, '--runs', '3', '--gap-ms', '0', '--pin', 'b=100.1.2.3', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 0, done.stderr
    pinned = ['--resolve' in line for line in arguments_of(log)]
    assert pinned == [False, True, True, False, False, True]


@pytest.mark.parametrize('station, pin, resolve', [
    ('https://s.example', 'tailnet=100.1.2.3', 's.example:443:100.1.2.3'),
    ('https://s.example', 'six=2001:db8::1', 's.example:443:[2001:db8::1]'),
    ('https://s.example:8443', 'port=100.1.2.3', 's.example:8443:100.1.2.3'),
    ('http://127.0.0.1', 'plain=127.0.0.2', '127.0.0.1:80:127.0.0.2'),
])
def test_a_pin_adds_a_path_forced_to_that_address(curl_shim, tmp_path, station, pin, resolve):
    env, log, _, _ = curl_shim
    done = run('--room', ROOM, '--runs', '1', '--gap-ms', '0', '--pin', pin, '--station-file', station_file(tmp_path, station), env=env)
    assert done.returncode == 0, done.stderr
    lines = arguments_of(log)
    assert '--resolve' not in lines[0] and f'--resolve {resolve}' in lines[1]
    assert 'resolved' in done.stdout and pin.split('=')[0] in done.stdout


def test_unpaged_is_only_read_when_asked(servers, tmp_path, real_curl):
    station, seen = servers()
    env, _ = real_curl
    done = run('--room', ROOM, '--runs', '1', '--station-file', station_file(tmp_path, station), env=env)
    assert done.returncode == 0 and [path for path, _ in seen] == [PAGE] and 'unpaged' not in done.stdout


def test_limit_and_timeout_reach_the_read(curl_shim, tmp_path):
    env, log, _, _ = curl_shim
    done = run('--room', ROOM, '--runs', '1', '--limit', '5', '--timeout', '7', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 0, done.stderr
    line = arguments_of(log)[0]
    assert f'/api/chats/{ROOM}?limit=5' in line and '--max-time 7 ' in line and 'limit=5' in done.stdout


def test_curl_ignores_its_config_and_any_proxy(curl_shim, tmp_path):
    env, log, _, _ = curl_shim
    run('--room', ROOM, '--runs', '1', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    line = arguments_of(log)[0]
    assert line.startswith('-q ') and '--noproxy *' in line  # curl honours -q only as its first argument


@pytest.mark.parametrize('code', [401, 403, 404])
def test_a_refusal_no_retry_changes_stops_that_path(curl_shim, tmp_path, code):
    env, log, feed, _ = curl_shim
    feed(f'0|{code} 0 0 0.01 10 1.2.3.4')
    done = run('--room', ROOM, '--runs', '50', '--gap-ms', '0', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 1 and len(arguments_of(log)) == 1 and f'stopped: refused {code}' in done.stdout


def test_a_refused_path_stops_alone(curl_shim, tmp_path):
    env, _, _, _ = curl_shim
    (Path(env['PATH'].split(':')[0]) / 'curl').write_text(
        '#!/bin/sh\ncat >/dev/null\ncase "$*" in *--resolve*) printf "200 0 0 0.1 10 1.2.3.4" ;; *) printf "401 0 0 0.1 10" ;; esac\n')
    done = run('--room', ROOM, '--runs', '3', '--gap-ms', '0', '--pin', 'good=100.1.2.3', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert 'n=1 ok=0' in done.stdout and 'n=3 ok=3' in done.stdout and done.returncode == 1


def test_five_failures_in_a_row_stop_a_path(curl_shim, tmp_path):
    env, log, feed, _ = curl_shim
    feed('0|503 0 0 0.01 10')
    done = run('--room', ROOM, '--runs', '50', '--gap-ms', '0', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 1 and len(arguments_of(log)) == 5 and 'stopped: 5 failures in a row' in done.stdout


def test_a_good_read_resets_the_count_of_failures(curl_shim, tmp_path):
    env, log, feed, _ = curl_shim
    bad, good = '0|503 0 0 0.01 10', '0|200 0 0 0.01 10 1.2.3.4'
    feed(bad, bad, bad, bad, good, bad, bad, bad, bad, good)
    run('--room', ROOM, '--runs', '10', '--gap-ms', '0', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert len(arguments_of(log)) == 10


def test_a_run_stops_at_its_deadline_and_says_so(curl_shim, tmp_path):
    env, log, _, _ = curl_shim
    started = time.monotonic()
    done = run('--room', ROOM, '--runs', '1000', '--gap-ms', '100', '--deadline', '1', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert time.monotonic() - started < 15
    assert done.returncode == 1 and 'stopped at the 1 s deadline' in done.stdout and 0 < len(arguments_of(log)) < 100


def test_a_read_never_outlasts_the_deadline(curl_shim, tmp_path):
    env, log, _, _ = curl_shim
    run('--room', ROOM, '--runs', '1', '--timeout', '25', '--deadline', '3', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert '--max-time 3 ' in arguments_of(log)[0]


@pytest.mark.parametrize('sent', [signal.SIGTERM, signal.SIGINT], ids=['term', 'int'])
def test_a_stopped_run_prints_what_it_measured(curl_shim, tmp_path, sent):
    env, log, _, _ = curl_shim
    command = [sys.executable, '-I', str(SCRIPT), '--room', ROOM, '--runs', '1000', '--gap-ms', '50', '--station-file', station_file(tmp_path, 'https://s.example')]
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    limit = time.monotonic() + 30
    while time.monotonic() < limit and not (log.exists() and len(arguments_of(log)) >= 3):
        time.sleep(0.05)
    process.send_signal(sent)
    out, err = process.communicate(timeout=30)
    assert process.returncode == 1 and 'Traceback' not in err
    assert re.search(r'n=\d+ ok=\d+ p50', out) and 'stopped by a signal' in out


def test_the_gap_falls_between_reads_only(curl_shim, tmp_path):
    env, _, _, _ = curl_shim
    started = time.monotonic()
    run('--room', ROOM, '--runs', '1', '--gap-ms', '30000', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert time.monotonic() - started < 20
    started = time.monotonic()
    run('--room', ROOM, '--runs', '2', '--gap-ms', '600', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert time.monotonic() - started >= 0.6


# Bad input stops before any read

@pytest.mark.parametrize('args', [
    ['--room', 'not-a-room'], ['--room', '../../etc'], ['--room', ROOM, '--runs', '0'], ['--room', ROOM, '--runs', 'x'],
    ['--room', ROOM, '--runs', '1001'], ['--room', ROOM, '--limit', '0'], ['--room', ROOM, '--limit', '501'],
    ['--room', ROOM, '--pin', 'noequals'], ['--room', ROOM, '--pin', 'a=not-an-ip'], ['--room', ROOM, '--pin', 'a b=1.2.3.4'],
    ['--room', ROOM, '--timeout', '0'], ['--room', ROOM, '--gap-ms', '-1'], ['--room', ROOM, '--deadline', '0'], [],
    ['--room', ROOM, *[f'--pin=p{n}=100.1.2.3' for n in range(5)]],
    ['--room', ROOM, '--runs', '1000', '--unpaged', '--pin', 'a=100.1.2.3', '--pin', 'b=100.1.2.4'],
])
def test_bad_arguments_stop_before_any_read(curl_shim, tmp_path, args):
    env, log, _, _ = curl_shim
    done = run(*args, '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 2 and 'Traceback' not in done.stderr and not log.exists()


def test_the_edges_of_the_arguments_are_allowed(curl_shim, tmp_path):
    env, _, _, _ = curl_shim
    pins = [f'--pin=p{n}=100.1.2.3' for n in range(4)]
    done = run('--room', ROOM, '--runs', '1', '--limit', '500', *pins, '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 0, done.stderr
    done = run('--room', ROOM, '--runs', '1000', '--gap-ms', '0', '--deadline', '1', '--unpaged', '--station-file', station_file(tmp_path, 'https://s.example'), env=env)
    assert done.returncode == 1 and 'stopped at the 1 s deadline' in done.stdout  # 2,000 reads is allowed, and the deadline still holds


@pytest.mark.parametrize('content', ['not json', '[]', '{}', '{"station": 1, "key": 2}', '{"station": "ftp://x", "key": "k"}',
                                     '{"station": "https://", "key": "k"}', '{"station": "https://[bad", "key": "k"}',
                                     '{"station": "https://s.example:notaport", "key": "k"}',
                                     '{"station": "https://s.example", "key": "has\\"quote"}',
                                     '{"station": "https://s.example", "key": "two\\nlines"}', '{"station": "https://s.example", "key": ""}',
                                     '{"station": "https://s.example", "key": "has quote"}', '{"station": "https://s.example", "key": "has\\\\quote"}'])
def test_a_bad_station_file_stops_with_a_sentence_and_repeats_no_key(curl_shim, tmp_path, content):
    env, log, _, _ = curl_shim
    path = tmp_path / 'station.json'
    path.write_text(content)
    done = run('--room', ROOM, '--station-file', str(path), env=env)
    assert done.returncode != 0 and done.stderr.startswith('room_read_timing:') and not log.exists()
    assert 'quote' not in done.stderr and 'lines' not in done.stderr


def test_a_missing_station_file_stops_with_a_sentence(tmp_path):
    done = run('--room', ROOM, '--station-file', str(tmp_path / 'nothing.json'))
    assert done.returncode != 0 and done.stderr.startswith('room_read_timing:')
