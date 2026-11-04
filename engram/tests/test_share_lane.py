"""A house copy keeps its source's lane (the Pi's first real lighthouse share,
2026-11-04: three work decisions crossed labelled personal)."""

from __future__ import annotations

import uuid

import pytest

from sharing import share
from storage import Storage

MIGRATIONS = "migrations"


def _stores(tmp_path):
    return (Storage(str(tmp_path / "src.db"), migrations_dir=MIGRATIONS),
            Storage(str(tmp_path / "pub.db"), migrations_dir=MIGRATIONS))


def _episode(src, lane, content="a decision made at work"):
    eid = str(uuid.uuid4())
    src.add_episode(id=eid, session_id=None, content=content, episode_type="test", lane=lane)
    src.conn.commit()
    return eid


def _semantic(src, lane, embedding):
    sid = str(uuid.uuid4())
    source = _episode(src, lane, "the chosen episode behind it")
    if embedding is None:
        src.conn.execute(
            "INSERT INTO semantics (id, content, kind, confidence, created_at, "
            "auto_generated, content_hash, lane, touched_capture) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, "a learned thing", "fact", 0.75, "2026-11-04T00:00:00Z", 0, None, lane, 0))
        src.conn.execute("INSERT INTO semantic_sources (semantic_id, episode_id) VALUES (?, ?)", (sid, source))
        src.conn.commit()
    else:
        src.add_semantic(id=sid, content="a learned thing", kind="fact", confidence=0.75,
                         embedding=embedding, source_episode_ids=[source], lane=lane)
        src.conn.commit()
    return sid


def _share(src, pub, source_id, layer):
    return share(source_storage=src, published_storage=pub, source_id=source_id, layer=layer,
                 audience="commons", reason="worth meeting me through", source_instance="engram")


@pytest.mark.parametrize("lane", ["work", "personal"])
def test_an_episode_copy_keeps_its_lane(tmp_path, lane):
    src, pub = _stores(tmp_path)
    record = _share(src, pub, _episode(src, lane), "episode")
    assert pub.get_episode(record.memory_id)["lane"] == lane


@pytest.mark.parametrize("lane", ["work", "personal"])
@pytest.mark.parametrize("embedding", [None, [0.1] * 768], ids=["no-vector", "vector"])
def test_a_semantic_copy_keeps_its_lane(tmp_path, lane, embedding):
    src, pub = _stores(tmp_path)
    record = _share(src, pub, _semantic(src, lane, embedding), "semantic")
    assert pub.get_semantic(record.memory_id)["lane"] == lane
