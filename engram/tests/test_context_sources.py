import sqlite3

from context_sources import EngramSource


def test_source_preserves_attribution_and_never_mutates_database(tmp_path):
    path = tmp_path / "memories.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE episodes(id TEXT, content TEXT, core INTEGER)")
        conn.execute("INSERT INTO episodes VALUES('e1','Mira likes cheese',1)")
        conn.execute("INSERT INTO episodes VALUES('e2','Unrelated architecture',0)")
        conn.execute("CREATE TABLE semantics(id TEXT, content TEXT)")
        conn.execute("INSERT INTO semantics VALUES('s1','Cheese institute account')")
    before = path.read_bytes()
    source = EngramSource(path)
    candidates = source.search("cheese")
    assert any(c.id == "engram:episode:e1" and "Mira likes cheese" in c.representations[0] for c in candidates)
    assert all(c.role == "user" and not c.required for c in candidates)
    assert path.read_bytes() == before
    assert source.mode == "sqlite_lexical"
    assert source.read("engram:episode:e1", offset=5, limit=5)["text"] == "likes"


def test_missing_source_does_not_create_database(tmp_path):
    path = tmp_path / "absent.db"
    source = EngramSource(path)
    assert source.search("anything") == []
    assert not path.exists()
