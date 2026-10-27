"""The package writer (store-copy spec I 6.1 steps 4 to 7, 6.2, D3, D33, D42, R26)."""
import json
import sqlite3
import uuid

import pytest

import store_identity
from store_identity import ancestry
from tests.imprint_support import (iid, shipped_ids, stored_instance_id, vectors_of, written, written_with_source)


def test_insertion_only(tmp_path):
    path = written(tmp_path)                 # a package from a source whose rowids have gaps and odd order
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA freelist_count").fetchone()[0] == 0 and conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert path.read_bytes()[18:20] == b"\x01\x01"


def test_rowids_run_one_to_n(tmp_path):
    conn = sqlite3.connect(written(tmp_path))
    for table in ("episodes", "semantics", "episode_fts_docsize", "semantic_fts_docsize"):
        ids = [r[0] for r in conn.execute(f"SELECT rowid FROM {table} ORDER BY rowid")]
        assert ids == list(range(1, len(ids) + 1)), table
    assert [r[0] for r in conn.execute("SELECT id FROM episodes ORDER BY rowid")] == ["e1", "e2", "e3"]


def test_vectors_are_copied_bit_for_bit(tmp_path):
    src, path = written_with_source(tmp_path)
    for layer in ("episode", "semantic"):
        assert vectors_of(path, layer) == vectors_of(src, layer, only=shipped_ids(path, layer))
        assert vectors_of(path, layer)


def test_the_package_is_an_imprint_of_its_source(tmp_path):
    src, path = written_with_source(tmp_path, source="fork")
    meta = dict(sqlite3.connect(path).execute("SELECT key, value FROM meta"))
    assert meta["instance_id_origin"] == "imprint" and meta["forked_from_instance_id"] == iid(src)
    assert json.loads(meta["ancestry"]) == [iid(src)] + ancestry(src.conn)[0] and uuid.UUID(meta["instance_id"]).version == 4
    assert set(meta) == set(store_identity.KEYS) - {"instance_id_basis_episode"}


def test_a_source_older_than_identity_names_its_derived_id(tmp_path):
    src, path = written_with_source(tmp_path, source="before_identity")   # episodes, no stored instance_id
    derived = store_identity.effective_id(src.conn)                       # the id its migration would assign
    meta = dict(sqlite3.connect(path).execute("SELECT key, value FROM meta"))
    assert meta["forked_from_instance_id"] == derived and stored_instance_id(src) is None
    assert (json.loads(meta["ancestry"]), meta["ancestry_complete"]) == ([derived], "false")


def test_co_subject_rows_are_written_only_at_home(tmp_path):
    src, path = written_with_source(tmp_path, cosubjects={"e1": "person:jenn"}, home=True)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT memory_id, layer, subject FROM imprint_subjects").fetchall() == [("e1", "episode", "person:jenn")]
    _, away = written_with_source(tmp_path / "away", cosubjects={"e1": "person:jenn"}, home=False)
    assert sqlite3.connect(away).execute("SELECT count(*) FROM imprint_subjects").fetchone()[0] == 0


def test_the_writer_refuses_an_existing_file(tmp_path):
    from imprint import write_package
    src, path = written_with_source(tmp_path)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_package(None, path, source_id="x", source_ancestry=[], source_complete=True, imprint_id="y")
    assert path.read_bytes() == before


def test_batches_split_by_rows_and_by_bytes_and_commit_each(tmp_path, monkeypatch):
    import imprint
    monkeypatch.setattr(imprint, "BATCH_ROWS", 2)
    _, path = written_with_source(tmp_path)
    assert sqlite3.connect(path).execute("SELECT count(*) FROM episodes").fetchone()[0] == 3
    monkeypatch.setattr(imprint, "BATCH_ROWS", 1000)
    monkeypatch.setattr(imprint, "BATCH_BYTES", 1)          # every row alone is over: one row a batch
    sizes = []
    real = imprint._batched
    monkeypatch.setattr(imprint, "_batched", lambda rows: (sizes.append(len(b)) or b for b in real(rows)))
    _, path2 = written_with_source(tmp_path / "two")
    assert sizes and set(sizes) == {1}
    assert sqlite3.connect(path2).execute("SELECT count(*) FROM episodes").fetchone()[0] == 3


def test_the_ddl_is_the_specs(tmp_path):
    from imprint_filter import IMPRINT_SUBJECTS_DDL
    assert "PRIMARY KEY (memory_id, layer, subject)" in IMPRINT_SUBJECTS_DDL
    conn = sqlite3.connect(written(tmp_path))
    assert conn.execute("SELECT sql FROM sqlite_master WHERE name = 'imprint_subjects'").fetchone()[0] == IMPRINT_SUBJECTS_DDL
