import shutil
import sys
import tempfile
from pathlib import Path

import pytest

MOCK_BIN = Path(__file__).resolve().parent / "mock-bin"


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



@pytest.fixture(autouse=True)
def isolated_team_home(tmp_path, monkeypatch):
    """No test touches the real ~/.superyak/team or the OS secret store (a test's own fixture may point these at
    another temporary folder)...or a real engram store: a worker's agent memory (agents.py) goes through a stand-in
    engram/cli.py, in every team test, lanes' included."""
    monkeypatch.setenv("SUPERYAK_TEAM_HOME", str(tmp_path / "teamhome"))
    monkeypatch.setenv("SUPERYAK_TEAM_TOKEN_STORE", "file")
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path / "engramhome"))
    monkeypatch.setenv("SUPERYAK_ENGRAM_PYTHON", sys.executable)
    monkeypatch.setenv("SUPERYAK_ENGRAM_CLI", str(MOCK_BIN / "fake_engram_cli.py"))
