"""SH-11: store_digest hashes the store in chunks, never reading it whole."""

import hashlib
import os
from pathlib import Path

from lighthouse_daemon import PublisherStore


def test_store_digest_does_not_read_the_whole_file(tmp_path, monkeypatch):
    db = tmp_path / "graph.db"
    data = os.urandom(3 * 1024 * 1024)
    db.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    store = PublisherStore(
        name="p", db_path=db, policy_path=tmp_path / "p.toml",
        disclosures_path=tmp_path / "d.db",
    )

    def refuse(self):
        raise AssertionError("read_bytes called")

    monkeypatch.setattr(Path, "read_bytes", refuse)
    assert store.store_digest() == {"algorithm": "sha256", "value": expected}
