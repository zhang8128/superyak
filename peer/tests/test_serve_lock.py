"""The public-route-bound plan, Task 1: one serve per data dir. Serve takes serve.lock before its identity and its store,
so a second serve on the same dir refuses having touched nothing. Only serve takes it: federate, a Store and the
station commands run beside a serve as before."""
import fcntl
import hashlib
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import time

import pytest

from superyak_peer.db import Store
from superyak_peer.dispatch import federation_lock, serve_lock

PEER = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def snapshot(directory):
    """Every file under it, by its bytes and its mtime."""
    return {str(path.relative_to(directory)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in sorted(directory.rglob('*')) if path.is_file()}


def test_the_lock_is_a_private_file_of_its_own_closed_on_exec(tmp_path):
    data = tmp_path / 'home'
    fd = serve_lock(data)  # makes the directory, as the Store would
    try:
        lock = data / 'serve.lock'
        assert stat.S_IMODE(lock.stat().st_mode) == 0o600 and stat.S_IMODE(data.stat().st_mode) == 0o700
        assert fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC  # a child serve starts never holds it
        with pytest.raises(ValueError, match=f'another serve runs on this data dir: {lock} is held'):
            serve_lock(data)
        os.close(federation_lock(data))  # its own file: federate's lock is free
    finally:
        os.close(fd)
    os.close(serve_lock(data))  # free again once closed


def test_the_lock_refuses_links(tmp_path):
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (tmp_path / 'linked').symlink_to(elsewhere)
    with pytest.raises(ValueError, match='Symlinked state'):
        serve_lock(tmp_path / 'linked')
    assert list(elsewhere.iterdir()) == []
    data = tmp_path / 'home'
    data.mkdir()
    (data / 'serve.lock').symlink_to(elsewhere / 'planted')
    with pytest.raises(OSError):
        serve_lock(data)
    assert not (elsewhere / 'planted').exists()


def test_a_second_serve_on_the_same_dir_refuses_and_touches_nothing(tmp_path, monkeypatch, capsys):
    """With --peer-tls and --sync, which would make an identity and a federation.lock: the lock comes first."""
    import uvicorn
    from superyak_peer.__main__ import main
    data = tmp_path / 'home'
    Store(data).create_user('patient', 'Patient', 'long-password-patient')
    held = serve_lock(data)
    try:
        before = snapshot(data)
        monkeypatch.setattr(uvicorn, 'run', lambda app, **_: pytest.fail('a second serve ran'))
        with pytest.raises(SystemExit) as stopped:
            main(['serve', '--data-dir', str(data), '--port', str(free_port()), '--peer-tls', '--sync'])
        assert stopped.value.code == 1
        assert f'another serve runs on this data dir: {data / "serve.lock"} is held' in capsys.readouterr().err
        assert snapshot(data) == before
    finally:
        os.close(held)


def test_serve_runs_beside_federate_and_frees_its_lock_when_it_returns(tmp_path, monkeypatch):
    import uvicorn
    from superyak_peer.__main__ import main
    data, ran = tmp_path / 'home', []
    data.mkdir(mode=0o700)
    federating = federation_lock(data)
    monkeypatch.setattr(uvicorn, 'run', lambda app, **_: ran.append(app))
    try:
        main(['serve', '--data-dir', str(data), '--port', str(free_port())])
    finally:
        os.close(federating)
    assert len(ran) == 1
    os.close(serve_lock(data))  # main() closed serve's descriptor when it returned


def test_a_store_and_station_approve_run_while_serve_holds_its_lock(tmp_path, capsys):
    from superyak_peer.__main__ import main
    store = Store(tmp_path / 'station')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    docking = store.start_docking('defiant', 'bazzite')
    held = serve_lock(store.data_dir)
    try:
        Store(store.data_dir).create_user('patient', 'Patient', 'long-password-patient')
        main(['station-approve', '--data-dir', str(store.data_dir), '--id', docking['id'][:8], '--as', 'andy'])
    finally:
        os.close(held)
    assert capsys.readouterr().out.startswith('Defiant is docked for andy.')
    assert not Store(store.data_dir, signing=False).station_pending()


def test_a_killed_serve_frees_the_lock(tmp_path):
    data, port, errors = tmp_path / 'home', free_port(), tmp_path / 'serve.err'
    with open(errors, 'w') as stderr:
        proc = subprocess.Popen([sys.executable, '-m', 'superyak_peer', 'serve', '--data-dir', str(data), '--port', str(port)],
                                cwd=PEER, stdout=subprocess.DEVNULL, stderr=stderr)
    try:
        deadline = time.monotonic() + 60
        while True:
            assert proc.poll() is None, errors.read_text()[-4000:]
            assert time.monotonic() < deadline, 'serve never listened'
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.1)
        with pytest.raises(ValueError, match='another serve runs on this data dir'):
            serve_lock(data)
        proc.kill()
        proc.wait(10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(5)
    os.close(serve_lock(data))
