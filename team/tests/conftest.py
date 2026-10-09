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
