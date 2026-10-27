import shutil
from pathlib import Path

import pytest

from cli import fork_instance
from federation import sync_genome
from sharing import share
from storage import Storage
from store_identity import ImprintRefused
from tests.imprint_support import engram_dir_with_imprint_instance, imprint_file, new_store


def test_storage_refuses_an_imprint_before_any_pragma_or_migration(tmp_path):
    path = imprint_file(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ImprintRefused):
        Storage(str(path))
    assert path.read_bytes() == before and not Path(f"{path}-wal").exists() and not Path(f"{path}-shm").exists()
    Storage.open_read_only(path).close()
    copy = tmp_path / "working.db"
    shutil.copyfile(path, copy)
    Storage(str(copy), imprint_working_copy=True).close()


def test_share_sync_genome_and_fork_refuse_an_imprint(tmp_path):
    imp, pub = Storage.open_read_only(imprint_file(tmp_path)), new_store(tmp_path, "pub")
    with pytest.raises(ImprintRefused):
        share(source_storage=imp, published_storage=pub, source_id="e1", layer="episode", audience="group:ph",
              reason="r", source_instance="default")
    with pytest.raises(ImprintRefused):
        sync_genome(str(imprint_file(tmp_path, "genome.db")), new_store(tmp_path, "inst"))
    engram_dir = engram_dir_with_imprint_instance(tmp_path, "imp")
    with pytest.raises(SystemExit):
        fork_instance("x", engram_dir=engram_dir, from_source="imp")
    assert not (engram_dir / "instances" / "x" / "graph.db").exists()


def test_resolve_db_path_never_returns_an_imprint(tmp_path, monkeypatch):
    from config import resolve_db_path

    home = tmp_path / "engram"
    imprint_dir = home / ".engram" / "imprints" / "c0a8"
    imprint_dir.mkdir(parents=True)
    shutil.copyfile(imprint_file(tmp_path), imprint_dir / "imprint.db")
    for name in ("../imprints/c0a8", "imprints/c0a8", "c0a8"):
        monkeypatch.setenv("ENGRAM_DEFAULT_INSTANCE", name)
        assert resolve_db_path(home, tmp_path / "project") == home / ".engram" / "graph.db"
