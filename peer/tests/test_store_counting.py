"""The public-route-bound plan, Task 0: counting the store's work per request, by bucket (path, public or tailnet, lane),
across every thread, with a peak per bucket and per union of buckets. Off unless a test or a measure's scratch serve
turns it on.

Its positive controls come first: a "0 reads" assertion elsewhere means something only if a request that does read is
counted, from the thread Starlette runs it on, under the right bucket, and nothing it does lands outside it."""
from contextlib import closing
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import urllib.request

from fastapi.testclient import TestClient
import pytest

from superyak_peer import counting
from superyak_peer.app import create_app
from superyak_peer.db import Store
from superyak_peer.dispatch import GateTimeout

PEER = Path(__file__).resolve().parents[1]
PUBLIC_CLIENT = ('203.0.113.5', 50000)  # an internet address, as a Funnel request looks after the proxy


@pytest.fixture
def app(tmp_path):
    clock = [1000000.0]
    app = create_app(tmp_path / 'peer', clock=lambda: clock[0], allowed_origins=['http://testserver'])
    app.state.store.create_user('patient', 'Patient', 'long-password-patient')
    return app


def signed_in(app, client=None):
    browser = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    answer = browser.post('/api/login', json={'username': 'patient', 'password': 'long-password-patient'})
    assert answer.status_code == 200
    if client is None:
        return browser
    public = TestClient(app, base_url='http://testserver', client=client, headers={'origin': 'http://testserver'})
    public.cookies.set('superyak_session', browser.cookies.get('superyak_session'))
    return public


def gated(store):
    """Whether this store's reads take the dispatch gate: in rollback mode they do, in WAL none does."""
    with closing(sqlite3.connect(store.db_path)) as db:
        return db.execute('PRAGMA journal_mode').fetchone()[0] != 'wal'


def test_counting_is_off_unless_something_turns_it_on(app):
    assert not counting.on()
    assert counting.counted('read') is counting.counted('transaction')  # off, a store call allocates nothing
    TestClient(app, base_url='http://testserver').get('/api/health')  # outside counts(): nothing is kept
    with app.state.store.counting() as counted:
        assert counted.total() == 0
    assert not counting.on()


def test_a_tailnet_health_read_counts_exactly_its_transaction_and_its_gate(app):
    """Positive control: health's one read is a transaction (app.py's health route), counted under its own bucket."""
    client = TestClient(app, base_url='http://testserver')
    with app.state.store.counting() as counted:
        assert client.get('/api/health').status_code == 200
    assert counted.total('transaction', path='/api/health', where='tailnet', lane=counting.BEFORE) == 1
    assert counted.total('gate', path='/api/health', where='tailnet') == 1
    assert counted.total('read', path='/api/health') == 0
    assert counted.total() == 2


def test_a_signed_in_public_get_is_counted_exactly_from_the_thread_that_runs_it(app):
    """Positive control, pinned: GET /api/chats makes 3 reads, and over the public route 1 more, the public route's own
    session check (PublicRoute.valid). All run in Starlette's threadpool and are filed under their request: none is
    unfiled, which is where a worker that lost the request's context would put its count (the reader's M1). In rollback
    mode each read takes the gate; in WAL none does. A later task that changes these numbers changes them here."""
    tailnet, public = signed_in(app), signed_in(app, PUBLIC_CLIENT)
    reads_gate = gated(app.state.store)
    with app.state.store.counting() as inside:
        assert tailnet.get('/api/chats').status_code == 200
    assert inside.total('read', path='/api/chats', where='tailnet', lane=counting.BEFORE) == 3
    assert inside.total() == (6 if reads_gate else 3)
    for _ in range(2):  # twice, so the count is the request's own
        with app.state.store.counting() as counted:
            assert public.get('/api/chats').status_code == 200
        assert counted.total('read', path='/api/chats', where='public', lane=counting.BEFORE) == 4
        assert counted.total('gate', path='/api/chats', where='public', lane=counting.BEFORE) == (4 if reads_gate else 0)
        assert counted.total('transaction') == 0
        assert counted.total(where=counting.UNFILED) == 0
        assert counted.total() == (8 if reads_gate else 4)


def test_a_request_no_route_matches_is_one_bucket_not_one_per_path(app):
    """The bucket is the route's path, never the request's: a scan of made-up paths makes one bucket."""
    public = signed_in(app, PUBLIC_CLIENT)
    with app.state.store.counting() as counted:
        for path in ('/no-such-page-1', '/no-such-page-2', '/api/no-such-route'):
            public.get(path)
    assert counted.total('read', path=counting.UNMATCHED, where='public') == 3  # each one's session check
    assert {row[0] for row in counted.table()['totals']} == {counting.UNMATCHED}


def test_a_wal_read_counts_one_read_and_takes_no_gate(app):
    """The reader's M2: reading()'s WAL branch is counted, once, with no gate."""
    with closing(sqlite3.connect(app.state.store.db_path)) as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
    store = Store(app.state.store.data_dir)  # learns WAL when it opens, as serve's store does
    with store.counting() as counted:
        with store.reading() as db:
            db.execute('SELECT 1').fetchone()
    assert counted.total('read') == 1 and counted.total('gate') == 0 and counted.total() == 1


@pytest.mark.journal('delete')
def test_a_rollback_read_counts_one_read_and_its_gate(app):
    store = app.state.store
    with store.counting() as counted:
        with store.reading() as db:
            db.execute('SELECT 1').fetchone()
    assert counted.total('read') == 1 and counted.total('gate') == 1 and counted.total() == 2


def work(store, kind):
    if kind == 'read':
        with store.reading() as db:
            db.execute('SELECT 1').fetchone()
    else:
        with store.transaction() as db:
            db.execute('SELECT 1').fetchone()


@pytest.mark.journal('delete')
@pytest.mark.parametrize('kind', ['read', 'transaction'])
def test_a_read_or_a_transaction_runs_from_its_entry_while_it_waits_for_the_gate(app, kind):
    """The reader's M4: both are counted once, at entry, after their refusals and before the gate, so 4 waiting behind
    a held gate are 4 at once, for reads as for transactions."""
    store = app.state.store
    with store.counting() as counted:
        with store.dispatch_gate:
            workers = [threading.Thread(target=work, args=(store, kind)) for _ in range(4)]
            for worker in workers:
                worker.start()
            deadline = time.monotonic() + 10
            while counted.total(kind) < 4:
                assert time.monotonic() < deadline, f'4 {kind}s never entered'
                time.sleep(0.01)
        for worker in workers:
            worker.join(10)
    assert counted.total(kind) == 4 and counted.peak(kind) == 4
    assert counted.total('gate') == 5  # the one held here, then each worker's


@pytest.mark.journal('delete')
@pytest.mark.parametrize('kind', ['read', 'transaction'])
def test_a_read_or_a_transaction_that_gives_up_at_a_bounded_gate_counts_once_with_no_gate(app, kind):
    store, outcome = app.state.store, []

    def bounded():
        try:
            with store.dispatch_gate.bounded(time.monotonic() + 0.05):
                work(store, kind)
            outcome.append('ran')
        except GateTimeout:
            outcome.append('gave up')
    with store.dispatch_gate, store.counting() as counted:
        worker = threading.Thread(target=bounded)
        worker.start()
        worker.join(10)
    assert outcome == ['gave up']
    assert counted.total(kind) == 1 and counted.total('gate') == 0 and counted.total() == 1


def test_a_peak_is_how_many_ran_at_once_not_how_many_ran():
    """The reader's M3: spans one after another, and one that raised, leave a peak of 1."""
    with counting.counts() as counted:
        for _ in range(2):
            with counting.counted('read'):
                pass
        with pytest.raises(RuntimeError):
            with counting.counted('transaction'):
                raise RuntimeError('refused inside the span')
        with counting.counted('transaction'):
            pass
    assert counted.total('read') == 2 and counted.peak('read') == 1
    assert counted.total('transaction') == 2 and counted.peak('transaction') == 1


def test_a_lane_files_its_work_and_its_peak_is_over_every_path_in_it():
    """Two requests on different paths in one lane at once: each path's peak is 1, the lane's is 2 (the reader's S3)."""
    both_in, release = threading.Barrier(3), threading.Event()

    def worker(path):
        token = counting.request(path, True)
        try:
            with counting.lane('x'), counting.counted('read'):
                both_in.wait(5)
                release.wait(5)
        finally:
            counting.reset(token)
    with counting.counts() as counted:
        threads = [threading.Thread(target=worker, args=(path,)) for path in ('/a', '/b')]
        for thread in threads:
            thread.start()
        both_in.wait(5)
        release.set()
        for thread in threads:
            thread.join(5)
        with counting.counted('read'):  # outside any request, so before any lane
            pass
    assert counted.total('read', lane='x') == 2 and counted.peak('read', lane='x') == 2
    assert counted.peak('read', path='/a') == 1 and counted.peak('read', path='/b') == 1
    assert counted.peak('read', where='public', lane='x') == 2 and counted.peak('read') == 2
    assert counted.total('read', path=counting.UNFILED, lane=counting.BEFORE) == 1
    assert counted.peak('read', where=counting.UNFILED) == 1


def test_a_store_read_inside_a_lane_is_filed_under_it(app):
    store = app.state.store
    with store.counting() as counted:
        with counting.lane('miss'):
            with store.reading() as db:
                db.execute('SELECT 1').fetchone()
    assert counted.total('read', lane='miss') == 1


def test_a_count_started_during_a_span_owes_that_span_nothing():
    with counting.counts():
        span = counting.counted('read')
        span.__enter__()
        with counting.counts() as fresh:
            span.__exit__(None, None, None)  # no KeyError, and no running count below 0
            with counting.counted('read'):
                pass
    assert fresh.total('read') == 1 and fresh.peak('read') == 1


@pytest.fixture
def measure_root(tmp_path, monkeypatch):
    root = tmp_path / 'measure-root'
    root.mkdir(mode=0o700)
    monkeypatch.setattr(counting, 'MEASURE_ROOT', root)
    yield root
    counting._state['on'] = False


def test_the_measure_switch_counts_only_a_data_dir_under_its_root(measure_root, tmp_path):
    out = tmp_path / 'counts.json'
    (tmp_path / 'elsewhere').mkdir()
    (measure_root / 'link-out').symlink_to(tmp_path / 'elsewhere')
    for refused in (tmp_path / 'elsewhere', measure_root, measure_root / '..' / 'elsewhere',
                    measure_root / 'scratch' / '..' / '..' / 'lighthouse', measure_root / 'link-out'):
        with pytest.raises(ValueError, match='only a data dir under'):
            counting.start_measuring(refused, out)
        assert not counting.on()
    write = counting.start_measuring(measure_root / 'scratch', out)
    assert counting.on()
    with counting.counted('read'):
        pass
    write()
    assert json.loads(out.read_text())['totals'] == [[counting.UNFILED, counting.UNFILED, counting.BEFORE, 'read', 1]]
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_the_measure_root_is_made_this_users_own_and_refused_otherwise(tmp_path, monkeypatch):
    """The reader's S2: anyone can make /dev/shm/superyak-measure first, as a link to the live data's parent or as a
    directory they can write. A missing root is made 0700; a linked, open or someone else's root is refused."""
    out, made = tmp_path / 'counts.json', tmp_path / 'made-root'
    monkeypatch.setattr(counting, 'MEASURE_ROOT', made)
    try:
        counting.start_measuring(made / 'scratch', out)
        assert counting.on() and stat.S_IMODE(made.stat().st_mode) == 0o700
    finally:
        counting._state['on'] = False
    (tmp_path / 'live' / 'lighthouse').mkdir(parents=True)
    linked, opened, flat = tmp_path / 'linked-root', tmp_path / 'open-root', tmp_path / 'flat-root'
    linked.symlink_to(tmp_path / 'live')
    opened.mkdir()
    opened.chmod(0o777)
    flat.write_text('')
    for root, why in ((linked, 'is a symlink'), (opened, 'can be written by others'), (flat, 'is not a directory')):
        monkeypatch.setattr(counting, 'MEASURE_ROOT', root)
        with pytest.raises(ValueError, match=f'refuses {root}: it {why}$'):
            counting.start_measuring(root / 'lighthouse', out)
        assert not counting.on()
    monkeypatch.setattr(counting, 'MEASURE_ROOT', made)
    uid = os.getuid()
    monkeypatch.setattr(os, 'getuid', lambda: uid + 1)  # as another user sees the root this one made
    with pytest.raises(ValueError, match="it is not this user's$"):
        counting.start_measuring(made / 'scratch', out)
    assert not counting.on()


def test_the_counts_are_never_written_through_a_symlink(measure_root, tmp_path):
    kept, out = tmp_path / 'kept.json', tmp_path / 'counts.json'
    kept.write_text('kept\n')
    out.symlink_to(kept)
    write = counting.start_measuring(measure_root / 'scratch', out)
    write()  # the link itself is replaced, by a file of this user's
    assert kept.read_text() == 'kept\n'
    assert not out.is_symlink() and 'totals' in json.loads(out.read_text())
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_a_write_cut_short_leaves_the_last_counts_whole(measure_root, tmp_path, monkeypatch):
    """The reader's N3: written in place, a second SIGTERM mid-write left an empty file. Now the old file stays until a
    whole new one replaces it, and no temp file is left behind."""
    out = tmp_path / 'counts.json'
    out.write_text('{"totals": [], "peaks": []}\n')
    write = counting.start_measuring(measure_root / 'scratch', out)

    def cut(*_):
        raise KeyboardInterrupt('stopped mid-write')
    monkeypatch.setattr(counting.os, 'replace', cut)
    with pytest.raises(KeyboardInterrupt):
        write()
    assert out.read_text() == '{"totals": [], "peaks": []}\n'
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(['counts.json', 'measure-root'])


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def test_serve_counts_with_the_switch_and_writes_at_a_clean_exit(measure_root, tmp_path, monkeypatch):
    import uvicorn
    from superyak_peer.__main__ import main
    out, seen, port = tmp_path / 'counts.json', [], free_port()
    before = signal.getsignal(signal.SIGTERM)

    def run(app, **_):  # stands in for uvicorn: one tailnet health read, then a clean exit
        seen.append(counting.on())
        assert TestClient(app, base_url=f'http://127.0.0.1:{port}').get('/api/health').status_code == 200
    monkeypatch.setattr(uvicorn, 'run', run)
    monkeypatch.setenv('SUPERYAK_MEASURE_COUNTS', str(out))
    main(['serve', '--data-dir', str(measure_root / 'scratch'), '--port', str(port)])
    assert seen == [True]
    totals = json.loads(out.read_text())['totals']
    assert ['/api/health', 'tailnet', counting.BEFORE, 'transaction', 1] in totals
    assert signal.getsignal(signal.SIGTERM) == before  # serve put back what it found


SERVE = """import sys
from pathlib import Path
from superyak_peer import counting
counting.MEASURE_ROOT = Path(sys.argv[1])
from superyak_peer.__main__ import main
main(['serve', '--data-dir', sys.argv[2], '--port', sys.argv[3]])
"""


@pytest.mark.parametrize('stop, code', [(signal.SIGTERM, 128 + signal.SIGTERM), (signal.SIGINT, 0)])
def test_serve_under_uvicorn_writes_its_counts_when_it_is_stopped(measure_root, tmp_path, stop, code):
    """The reader's S1, with real uvicorn: it raises a captured SIGTERM again after its graceful shutdown, so without
    serve's own handler a kill or systemd's stop ends the process before the counts are written."""
    out, port, errors = tmp_path / 'counts.json', free_port(), tmp_path / 'serve.err'
    env = {**os.environ, 'SUPERYAK_MEASURE_COUNTS': str(out)}
    with open(errors, 'w') as stderr:
        proc = subprocess.Popen([sys.executable, '-c', SERVE, str(measure_root), str(measure_root / 'scratch'), str(port)],
                                cwd=PEER, env=env, stdout=subprocess.DEVNULL, stderr=stderr)
    try:
        deadline = time.monotonic() + 60
        while True:
            assert proc.poll() is None, errors.read_text()[-4000:]
            assert time.monotonic() < deadline, 'serve never answered'
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=5) as answer:
                    assert answer.status == 200
                break
            except OSError:
                time.sleep(0.1)
        proc.send_signal(stop)
        assert proc.wait(30) == code, errors.read_text()[-4000:]
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(5)
    totals = json.loads(out.read_text())['totals']
    assert ['/api/health', 'tailnet', counting.BEFORE, 'transaction', 1] in totals


def test_serve_counts_nothing_without_the_switch(measure_root, tmp_path, monkeypatch):
    """Nor does it touch SIGTERM (the reader's N1): live, serve's handler would end it by SystemExit(143), which
    systemd counts as a failure."""
    import uvicorn
    from superyak_peer.__main__ import main
    seen, before = [], signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(uvicorn, 'run', lambda app, **_: seen.append((counting.on(), signal.getsignal(signal.SIGTERM))))
    monkeypatch.delenv('SUPERYAK_MEASURE_COUNTS', raising=False)
    main(['serve', '--data-dir', str(tmp_path / 'live'), '--port', str(free_port())])
    assert seen == [(False, before)]


def test_serve_writes_no_counts_when_uvicorn_exits_on_its_own(measure_root, tmp_path, monkeypatch):
    """The reader's N2: uvicorn's sys.exit(3) at a failed start is not serve's SIGTERM, and leaves no counts file."""
    import uvicorn
    from superyak_peer.__main__ import main
    out = tmp_path / 'counts.json'

    def failed_start(app, **_):
        raise SystemExit(3)
    monkeypatch.setattr(uvicorn, 'run', failed_start)
    monkeypatch.setenv('SUPERYAK_MEASURE_COUNTS', str(out))
    with pytest.raises(SystemExit) as stopped:
        main(['serve', '--data-dir', str(measure_root / 'scratch'), '--port', str(free_port())])
    assert stopped.value.code == 3 and not out.exists()


def test_serve_refuses_the_switch_outside_its_root_before_it_writes_anything(measure_root, tmp_path, monkeypatch,
                                                                             capsys):
    import uvicorn
    from superyak_peer.__main__ import main
    monkeypatch.setattr(uvicorn, 'run', lambda app, **_: pytest.fail('serve ran with a refused switch'))
    monkeypatch.setenv('SUPERYAK_MEASURE_COUNTS', str(tmp_path / 'counts.json'))
    with pytest.raises(SystemExit) as stopped:  # --peer-tls makes an identity and --sync a lock file in the data dir
        main(['serve', '--data-dir', str(measure_root / '..' / 'lighthouse'), '--port', str(free_port()),
              '--peer-tls', '--sync'])
    assert stopped.value.code == 1 and 'only a data dir under' in capsys.readouterr().err
    assert not (tmp_path / 'lighthouse').exists()  # refused before anything was made there
