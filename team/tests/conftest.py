import shutil
import tempfile

import pytest


@pytest.fixture
def short_dir():
    """A fresh folder under /tmp with a short path, for Unix socket paths: macOS allows 104 bytes, and pytest's tmp_path
    under /var/folders/... is longer. Removed afterwards."""
    folder = tempfile.mkdtemp(prefix="sy-t-", dir="/tmp")
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(autouse=True)
def no_loopback_scan(request, monkeypatch):
    """The listener check's loopback scan connects to every port on this machine's loopback. Unit tests get an empty
    scan (nothing reachable) unless they are marked real_scan or give their own (the `listeners` fixture does)."""
    if request.node.get_closest_marker("real_scan"):
        return
    from superyak_team import lane
    monkeypatch.setattr(lane, "scan_loopback", lambda targets, ports=None, **kwargs: {})

