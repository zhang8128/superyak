"""Federation pull, plan Task 8: the processes. One process syncs a data directory, `serve --sync` or `federate`
(dispatch.federation_lock)."""
import os
import subprocess
import sys

import pytest


def test_a_second_sync_process_exits_and_the_lock_is_private(tmp_path):
    from superyak_peer.db import Store
    from superyak_peer.dispatch import federation_lock
    data = tmp_path / 'peer'
    Store(data)
    held = federation_lock(data)
    try:
        with pytest.raises(ValueError, match='another process already syncs this directory'):
            federation_lock(data)
        done = subprocess.run([sys.executable, '-m', 'superyak_peer', 'serve', '--data-dir', str(data), '--sync',
                               '--port', '0'], capture_output=True, text=True, timeout=60)
        assert done.returncode == 1 and 'another process already syncs this directory' in done.stderr
    finally:
        os.close(held)
    assert (data / 'federation.lock').stat().st_mode & 0o777 == 0o600
    os.close(federation_lock(data))  # released with its descriptor, as when the holding process ends


def test_the_lock_never_follows_a_link(tmp_path):
    from superyak_peer.dispatch import federation_lock
    (tmp_path / 'elsewhere').write_text('')
    (tmp_path / 'federation.lock').symlink_to(tmp_path / 'elsewhere')
    with pytest.raises(OSError):
        federation_lock(tmp_path)


# Task 8d: federate (plan P4, P7, P9, P13, nit 18)

class Wake:
    """A clock federate reads and a sleep that moves it, so passes run without waiting."""
    def __init__(self, at=1_000_000.0):
        self.at = at

    def __call__(self):
        return self.at

    def sleep(self, seconds):
        self.at += seconds


def puller(tmp_path):
    from superyak_peer.identity import pairing_code
    from test_federation_outcomes import Clock, station
    clock = Clock()
    a = station(tmp_path / 'a', 'alice', clock)
    mac = station(tmp_path / 'mac', 'mo', clock, mode='pull')
    a[2].pair(a[1], mac[2].card(mac[1]), code=pairing_code(mac[2].card(mac[1])))
    mac[2].pair(mac[1], a[2].card(a[1]), code=pairing_code(a[2].card(a[1])))
    return clock, a, mac


def test_federate_pulls_at_start_after_a_recovery_and_after_a_sleep_overrun(tmp_path, monkeypatch):
    from superyak_peer.federate import Federate
    clock, a, mac = puller(tmp_path)
    wake, pulls, answers = Wake(), [], [{'next': 2}, {'next': 60}, {'next': 60}, {'next': 60}]
    monkeypatch.setattr(mac[2], 'pull_once', lambda card, send=None: pulls.append(wake()) or answers.pop(0))
    loop = Federate(mac[2], clock=wake, sleep=wake.sleep)
    loop.run_pass()                                   # at start: nothing is due yet, so it pulls
    wake.sleep(1), loop.run_pass()                    # 1 s later its 2 s backoff isn't over
    wake.sleep(1), loop.run_pass()                    # it is now: the retry recovers, and the next pull is 60 s off
    wake.sleep(5), loop.run_pass()                    # a normal pass: not due
    wake.sleep(5 + 31), loop.run_pass()               # the machine slept past the pass by more than 30 s: at once
    assert pulls == [1_000_000.0, 1_000_002.0, 1_000_043.0]


def test_federate_survives_a_pull_that_raises_and_still_pushes(tmp_path, monkeypatch):
    from superyak_peer.federate import Federate
    clock, a, mac = puller(tmp_path)
    synced = []

    def broken(card, send=None):
        raise RuntimeError('the pull broke')
    monkeypatch.setattr(mac[2], 'pull_once', broken)
    monkeypatch.setattr(mac[2], 'sync_once', lambda **k: synced.append(1) or {})
    loop = Federate(mac[2], clock=Wake(), sleep=lambda s: None)
    loop.run_pass()
    loop.run_pass()
    assert len(synced) == 2


def test_federate_never_listens(tmp_path, monkeypatch):
    import socket
    from superyak_peer.federate import Federate
    clock, a, mac = puller(tmp_path)

    def refuse(*args, **kwargs):
        raise AssertionError('federate opened a listening socket')
    monkeypatch.setattr(socket.socket, 'bind', refuse)
    monkeypatch.setattr(socket.socket, 'listen', refuse)
    monkeypatch.setattr(mac[2], 'pull_once', lambda card, send=None: {'next': 60})
    Federate(mac[2], clock=Wake(), sleep=lambda s: None).run_pass()


def test_a_push_peer_runs_federate_without_pulling(tmp_path, monkeypatch):
    from superyak_peer.federate import Federate
    clock, a, mac = puller(tmp_path)
    monkeypatch.setattr(a[2], 'pull_once', lambda card, send=None: (_ for _ in ()).throw(AssertionError('pulled')))
    synced = []
    monkeypatch.setattr(a[2], 'sync_once', lambda **k: synced.append(1) or {})
    Federate(a[2], clock=Wake(), sleep=lambda s: None).run_pass()
    assert synced == [1]


def test_federate_creates_nothing_without_a_database_and_takes_the_sync_lock(tmp_path):
    from superyak_peer.dispatch import federation_lock
    empty = tmp_path / 'typo'
    empty.mkdir()
    done = subprocess.run([sys.executable, '-m', 'superyak_peer', 'federate', '--data-dir', str(empty)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 1 and 'peer.sqlite3' in done.stderr and list(empty.iterdir()) == []
    clock, a, mac = puller(tmp_path)
    held = federation_lock(mac[0].data_dir)
    try:
        done = subprocess.run([sys.executable, '-m', 'superyak_peer', 'federate', '--data-dir', str(mac[0].data_dir)],
                              capture_output=True, text=True, timeout=60)
    finally:
        os.close(held)
    assert done.returncode == 1 and 'another process already syncs this directory' in done.stderr


def test_federate_runs_its_passes_and_sigterm_ends_it_cleanly(tmp_path):
    """The real process on a pull peer: it starts, runs passes (its peer's address can't be dialled here, so each pull
    fails, is logged and backs off), and SIGTERM ends it between steps with exit 0 and no traceback."""
    import signal
    import time
    clock, a, mac = puller(tmp_path)
    proc = subprocess.Popen([sys.executable, '-m', 'superyak_peer', 'federate', '--data-dir', str(mac[0].data_dir)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(3)
    proc.send_signal(signal.SIGTERM)
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 0, err
    assert 'Traceback (most recent call last)' not in err.split('A pull from')[0]  # only a logged pull failure, if any
