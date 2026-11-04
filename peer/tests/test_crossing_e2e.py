"""Ship home and crossing plan, Task 13: one crossing end to end, every hop real (B4, spec section 3's measure).

Two throwaway peers on loopback: A, a push peer running federation-listen over real HTTPS, and M, a pull peer running
federate --crossing-socket. They pair in process, through the suite's own `paired` helper. A's Engram home serves its
house from the lighthouse daemon under enforce, with remote-stores registered, S1's two allows and the policy grant
written by grant-remote; M's home runs attach_neighbors against M's crossing.sock. Engram's halves run in Engram's own
environment (engram/scripts/crossing_check_engram.py), and talk to the peers only over the daemon socket and
crossing.sock, as in production. peer/scripts/crossing_check.py runs this test."""
import json
import os
from pathlib import Path
import select
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

import pytest

from conftest import lesson_ship, paired

REPO = Path(__file__).resolve().parents[2]
ENGRAM = REPO / 'engram'
HELPER = ENGRAM / 'scripts' / 'crossing_check_engram.py'
TEXT = 'm1: shared: rivers need bridges across the valley floor'
M1 = '00000000-0000-0000-0000-000000000001'

pytestmark = pytest.mark.skipif(shutil.which('uv') is None, reason="Engram's half runs under uv, in its own venv")


def engram_command(*args):
    return ['uv', 'run', '--locked', '--project', str(ENGRAM), 'python', '-I', str(HELPER), *map(str, args)]


def engram_env():
    env = dict(os.environ)
    env.pop('VIRTUAL_ENV', None)  # the peer's venv is not Engram's
    return env


def engram(*args, timeout=180):
    done = subprocess.run(engram_command(*args), capture_output=True, text=True, timeout=timeout, env=engram_env(),
                          cwd=REPO)
    assert done.returncode == 0, done.stderr[-4000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def line_from(proc, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        ready, _, _ = select.select([proc.stdout], [], [], 0.2)
        if ready:
            text = proc.stdout.readline()
            if text:
                return text
        if proc.poll() is not None:
            break
    raise AssertionError(f'no line from {proc.args[:6]}: {proc.stderr.read()[-4000:] if proc.poll() is not None else ""}')


def wait_until(condition, seconds, what):
    end = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < end, f'timed out waiting for {what}'
        time.sleep(0.1)


def listening(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            return True
    except OSError:
        return False


def stop(proc):
    if proc is not None and proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(5)


def test_a_recall_on_the_pull_peer_delivers_from_the_push_peers_house_and_the_four_records_link():
    from superyak_peer.db import Store
    from superyak_peer.federation import Federation
    base = Path(tempfile.mkdtemp(prefix='x'))  # Unix socket paths stay under 108 bytes
    port = free_port()
    a_store = Store(base / 'a')
    alice = a_store.create_user('alice', 'Alice', 'a-long-password', is_admin=True)['id']
    rio = lesson_ship(a_store, alice, 'rio-grande')
    a_store.claim_federation_mode('push')
    a_fed = Federation(a_store, endpoint=f'https://127.0.0.1:{port}')
    m_store = Store(base / 'm')
    mo = m_store.create_user('mo', 'Mo', 'a-long-password', is_admin=True)['id']
    tardis = lesson_ship(m_store, mo, 'tardis')
    m_store.claim_federation_mode('pull')
    m_fed = Federation(m_store, endpoint=None)
    contact = paired(a_fed, alice, m_fed.card(tardis['id']))['id']
    paired(m_fed, mo, a_fed.card(rio['id']))
    a_peer, m_peer = a_fed.identity.peer_id, m_fed.identity.peer_id

    instance = engram('prepare', base / 'mhome')['instance_id']
    ref = f'urn:superyak:{m_peer}:store:{instance}'
    publisher = listener = federate = None
    try:
        publisher = subprocess.Popen(engram_command('publisher', base / 'ahome', '--socket', base / 'd.sock', '--ref', ref),
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=engram_env(), cwd=REPO)
        sidecar = Path(json.loads(line_from(publisher, 180))['sidecar'])
        (a_store.data_dir / 'crossings.toml').write_text(
            f'[[published]]\nship = "rio-grande"\npublisher = "why"\ndaemon_socket = "{base / "d.sock"}"\n'
            f'sidecar = "{sidecar}"\n')
        (m_store.data_dir / 'crossings.toml').write_text(f'[[hosted]]\nship = "tardis"\ninstance_id = "{instance}"\n')
        listener = subprocess.Popen([sys.executable, '-m', 'superyak_peer', 'federation-listen', '--data-dir',
                                     str(a_store.data_dir), '--port', str(port)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        federate = subprocess.Popen([sys.executable, '-m', 'superyak_peer', 'federate', '--crossing-socket',
                                     '--data-dir', str(m_store.data_dir)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        wait_until(lambda: listening(port), 60, 'federation-listen')
        wait_until((m_store.data_dir / 'crossing.sock').exists, 60, 'crossing.sock')

        def ask():
            return engram('ask', base / 'mhome', '--crossing-socket', m_store.data_dir / 'crossing.sock', '--peer', a_peer,
                          '--ship', rio['id'], '--receiver-ship', tardis['id'], '--query', TEXT)

        first = ask()
        assert first['delivered'] == [TEXT], first
        [disclosure] = first['recorded']                                        # M's remote_deliveries
        assert first['receipts'][-1] == [{'publisher': f'urn:superyak:{a_peer}:ship:{rio["id"]}',
                                          'disclosureId': disclosure}]          # M's receipt
        with sqlite3.connect(f'file:{sidecar}?mode=ro', uri=True) as db:      # A's sidecar
            assert (disclosure, ref, 'read') in db.execute('SELECT id, receiver, action FROM disclosures').fetchall()
        with a_store.reading() as db:                                           # A's crossings
            row = db.execute('SELECT origin_peer, receiver_ref FROM crossings WHERE disclosure_id=?',
                             (disclosure,)).fetchone()
        assert tuple(row) == (m_peer, ref)

        assert engram('unshare', base / 'ahome', '--memory', M1) == {'unshared': 1}
        assert ask()['delivered'] == []                                         # unshare stops the crossing

        a_fed.unpair(alice, contact)
        third = ask()
        assert third['delivered'] == [] and {'publisher': f'urn:superyak:{a_peer}:ship:{rio["id"]}',
                                             'code': 'REFUSED_UNPAIRED'} in third['diagnostics']   # check 3 refuses
    finally:
        for proc in (federate, listener, publisher):
            stop(proc)
        shutil.rmtree(base, ignore_errors=True)
