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
