"""The agent holds one part of the package at a time (store-imprint I 9, 14.1, 16; plan Task 50, A4, D42, R27).

The Pi measurement runs only with ENGRAM_PI_BUDGET=1: `imprint send` of a 512 MiB package (128 parts) in a fresh child
under `systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0`, against a station served over HTTP by the test.
The child's peak resident size (`VmHWM`, read as `ru_maxrss` of that one child) must stay under 384 MiB, and under
64 MiB plus two parts."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest

from superyak_agent.imprint import PART_BYTES

PI = pytest.mark.skipif(os.environ.get('ENGRAM_PI_BUDGET') != '1', reason='Pi measurement (R16, R27)')
PEAK_BUDGET = 384 * 2**20
IMPRINT_ID = '5b0e7f3a-1c2d-4e5f-8a9b-0c1d2e3f4a5b'
REQUEST_ID = 'a1b2c3d4-0000-4000-8000-000000000001'
PLAN, PLAN_FILE = '7c41', '7c41aa00bb11cc22'
RUN_AGENT = Path(__file__).resolve().parents[1] / 'run_agent.py'
_LAUNCHER = ('import resource, subprocess, sys\n'
             'r = subprocess.run(sys.argv[1:], capture_output=True, text=True)\n'
             'sys.stderr.write(r.stdout[-1500:] + r.stderr[-1500:])\n'
             'print(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024, r.returncode)\n')


def mib(n):
    return round(n / 2**20, 1)


class ServingStation:
    """A station over HTTP on the loopback, in a thread of the test: it allows the request at once, takes the manifest,
    every part (counting its bytes, keeping none) and `complete`."""
    def __init__(self):
        self.parts, self.bytes, self.calls = set(), 0, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, status, doc):
                body = json.dumps(doc).encode()
                self.send_response(status)
                self.send_header('content-type', 'application/json')
                self.send_header('content-length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self):
                size, left = int(self.headers.get('content-length') or 0), 0
                left = size
                while left:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    left -= len(chunk)
                return size

            def do_GET(self):
                if self.path == '/api/imprints':
                    return self._reply(200, {'ship': 'rio', 'owner': 'andy', 'operator': 'andy', 'station': 'st', 'imprints': []})
                self._reply(200, {'status': 'allowed', 'held': sorted(outer.parts), 'receipts': []})

            def do_POST(self):
                self._body()
                outer.calls.append(('POST', self.path))
                if self.path == '/api/imprints':
                    return self._reply(201, {'id': REQUEST_ID, 'code': 'AB12CD34', 'expires': 5000, 'confirm_url': 'http://x/#imprint'})
                self._reply(200, {'status': 'received'})

            def do_PUT(self):
                size = self._body()
                outer.calls.append(('PUT', self.path))
                if '/parts/' in self.path:
                    outer.parts.add(int(self.path.rsplit('/', 1)[1]))
                    outer.bytes += size
                    return self._reply(200, {'held': sorted(outer.parts)})
                self._reply(200, {'parts': 0})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @classmethod
    def serving(cls, tmp_path):
        return cls()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def built_home(tmp_path, nbytes):
    """A ship home holding a built plan whose package is a sparse file of `nbytes`, in parts of 4 MiB."""
    home = tmp_path / 'superyak'
    local = home / 'imprints' / IMPRINT_ID
    local.mkdir(parents=True, mode=0o700)
    (home / 'imprints' / 'plans').mkdir(mode=0o700)
    with open(local / 'imprint.db', 'wb') as package:
        package.truncate(nbytes)
    parts = -(-nbytes // PART_BYTES)
    manifest = {'kind': 'engram-imprint-manifest', 'package': {'file': 'imprint.db', 'bytes': nbytes, 'part_bytes': PART_BYTES,
                                                                'sha256': '0' * 64, 'parts': ['0' * 64] * parts}}
    (local / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True))
    (local / 'request.json').write_text(json.dumps({'imprint_id': IMPRINT_ID}, sort_keys=True))
    (home / 'imprints' / 'plans' / f'{PLAN_FILE}.json').write_text(json.dumps({'id': PLAN_FILE, 'imprint_id': IMPRINT_ID}))
    return home


def agent_send_command(home, station):
    (home / 'station.json').write_text(json.dumps({'station': station.url, 'key': 'key'}))
    return [sys.executable, str(RUN_AGENT), 'imprint', 'send', '--plan', PLAN, '--home', str(home)]


def child_peak_rss(*, cmd, env=None):
    argv = [str(a) for a in cmd]
    if shutil.which('systemd-run'):
        argv = ['systemd-run', '--user', '--scope', '--quiet', '-p', 'MemoryMax=512M', '-p', 'MemorySwapMax=0'] + argv
    out = subprocess.run([sys.executable, '-c', _LAUNCHER, *argv], env=env, capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.split(), out.stderr[-2000:]
    peak, status = (int(x) for x in out.stdout.split()[-2:])
    assert status == 0, out.stderr[-2000:]
    return peak


def test_a_send_against_the_serving_station_puts_every_part(tmp_path):
    station = ServingStation.serving(tmp_path)
    try:
        home = built_home(tmp_path, 3 * PART_BYTES + 5)
        env = {**os.environ, 'HOME': str(tmp_path)}
        child_peak_rss(cmd=agent_send_command(home, station), env=env)
    finally:
        station.close()
    assert station.parts == {0, 1, 2, 3} and station.bytes == 3 * PART_BYTES + 5
    assert station.calls[-1] == ('POST', f'/api/imprints/{REQUEST_ID}/complete')


@PI
def test_pi_send_holds_one_part_at_a_time(tmp_path):
    station = ServingStation.serving(tmp_path)
    try:
        home = built_home(tmp_path, 512 * 2**20)                              # 128 parts
        env = {**os.environ, 'HOME': str(tmp_path)}
        peak = child_peak_rss(cmd=agent_send_command(home, station), env=env)
        paths = f'import sys; sys.path[:0] = [{str(RUN_AGENT.parent)!r}, {str(RUN_AGENT.parent.parent / "team")!r}]'
        base = child_peak_rss(cmd=[sys.executable, '-c', paths + '; import superyak_agent.__main__'], env=env)
    finally:
        station.close()
    assert len(station.parts) == 128
    print('agent send', mib(peak), 'MiB, base', mib(base), 'MiB')
    assert peak < PEAK_BUDGET and peak < 64 * 2**20 + 2 * PART_BYTES, mib(peak)
