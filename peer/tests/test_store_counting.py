"""The public-route-bound plan, Task 0: counting the store's work per request, by bucket (path, public or tailnet, lane),
across every thread, with a peak per bucket. Off unless a test or a measure's scratch serve turns it on.

Its positive controls come first: a "0 reads" assertion elsewhere means something only if a request that does read is
counted, from the thread Starlette runs it on, under the right bucket."""
import json
import socket
import threading

from fastapi.testclient import TestClient
import pytest

from superyak_peer import counting
from superyak_peer.app import create_app

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


def test_counting_is_off_unless_something_turns_it_on(app):
    assert not counting.on()
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
    assert counted.total(where='public') == 0


def test_a_signed_in_public_get_is_counted_from_the_thread_that_runs_it(app):
    """Positive control: a public GET with a valid session reads the store in Starlette's threadpool, and each of those
    reads is filed under its request. Two identical requests count the same, so the count is the request's own."""
    client = signed_in(app, PUBLIC_CLIENT)
    with app.state.store.counting() as once:
        assert client.get('/api/chats').status_code == 200
    first = once.total(path='/api/chats', where='public')
    assert first > 0
    assert once.total(path=None, where='tailnet') == 0
    with app.state.store.counting() as twice:
        assert client.get('/api/chats').status_code == 200
        assert client.get('/api/chats').status_code == 200
    assert twice.total(path='/api/chats', where='public') == 2 * first


def test_a_lane_files_its_work_and_counts_how_many_ran_at_once():
    both_in, release = threading.Barrier(3), threading.Event()

    def worker():
        with counting.lane('x'), counting.counted('read'):
            both_in.wait(5)
            release.wait(5)
    with counting.counts() as counted:
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        both_in.wait(5)
        release.set()
        for thread in threads:
            thread.join(5)
        with counting.counted('read'):  # no lane: before any
            pass
    assert counted.total('read', lane='x') == 2 and counted.peak('read', lane='x') == 2
    assert counted.total('read', lane=counting.BEFORE) == 1 and counted.peak('read', lane=counting.BEFORE) == 1


def test_a_store_read_inside_a_lane_is_filed_under_it(app):
    store = app.state.store
    with store.counting() as counted:
        with counting.lane('miss'):
            with store.reading() as db:
                db.execute('SELECT 1').fetchone()
    assert counted.total('read', lane='miss') == 1


@pytest.fixture
def measure_root(tmp_path, monkeypatch):
    root = tmp_path / 'measure-root'
    root.mkdir()
    monkeypatch.setattr(counting, 'MEASURE_ROOT', root)
    yield root
    counting._state['on'] = False


def test_the_measure_switch_counts_only_a_data_dir_under_its_root(measure_root, tmp_path):
    out = tmp_path / 'counts.json'
    for refused in (tmp_path / 'elsewhere', measure_root, measure_root / '..' / 'elsewhere',
                    measure_root / 'scratch' / '..' / '..' / 'lighthouse'):
        with pytest.raises(ValueError, match='only a data dir under'):
            counting.start_measuring(refused, out)
        assert not counting.on()
    write = counting.start_measuring(measure_root / 'scratch', out)
    assert counting.on()
    with counting.counted('read'):
        pass
    write()
    assert json.loads(out.read_text())['totals'] == [[None, None, counting.BEFORE, 'read', 1]]


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def test_serve_counts_with_the_switch_and_writes_at_a_clean_exit(measure_root, tmp_path, monkeypatch):
    import uvicorn
    from superyak_peer.__main__ import main
    out, seen, port = tmp_path / 'counts.json', [], free_port()

    def run(app, **_):  # stands in for uvicorn: one tailnet health read, then a clean exit
        seen.append(counting.on())
        assert TestClient(app, base_url=f'http://127.0.0.1:{port}').get('/api/health').status_code == 200
    monkeypatch.setattr(uvicorn, 'run', run)
    monkeypatch.setenv('SUPERYAK_MEASURE_COUNTS', str(out))
    main(['serve', '--data-dir', str(measure_root / 'scratch'), '--port', str(port)])
    assert seen == [True]
    totals = json.loads(out.read_text())['totals']
    assert ['/api/health', 'tailnet', counting.BEFORE, 'transaction', 1] in totals


def test_serve_counts_nothing_without_the_switch(measure_root, tmp_path, monkeypatch):
    import uvicorn
    from superyak_peer.__main__ import main
    seen = []
    monkeypatch.setattr(uvicorn, 'run', lambda app, **_: seen.append(counting.on()))
    monkeypatch.delenv('SUPERYAK_MEASURE_COUNTS', raising=False)
    main(['serve', '--data-dir', str(tmp_path / 'live'), '--port', str(free_port())])
    assert seen == [False]


def test_serve_refuses_the_switch_outside_its_root(measure_root, tmp_path, monkeypatch, capsys):
    import uvicorn
    from superyak_peer.__main__ import main
    monkeypatch.setattr(uvicorn, 'run', lambda app, **_: pytest.fail('serve ran with a refused switch'))
    monkeypatch.setenv('SUPERYAK_MEASURE_COUNTS', str(tmp_path / 'counts.json'))
    with pytest.raises(SystemExit) as stopped:
        main(['serve', '--data-dir', str(measure_root / '..' / 'lighthouse'), '--port', str(free_port())])
    assert stopped.value.code == 1 and 'only a data dir under' in capsys.readouterr().err
    assert not (tmp_path / 'lighthouse').exists()  # refused before the store was made
