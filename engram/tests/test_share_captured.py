"""`share` refuses captured memories (board item fix:share-refuses-captured-memories, Serenity's finding 2069b049).

The nudge hook stores a person's novel prompts verbatim as `source='auto'` episodes in the work lane. Those are a
person's typed words, not a ship's chosen memory, so no share places one, nor a semantic built from one."""
import hashlib
import sqlite3
import uuid
from pathlib import Path

import pytest

from sharing import CapturedRefused, captured_reason, share
from storage import Storage

MIGRATIONS = str(Path(__file__).resolve().parent.parent / "migrations")


def _stores(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "pub").mkdir()
    src = Storage(str(tmp_path / "src" / "graph.db"), migrations_dir=MIGRATIONS)
    pub = Storage(str(tmp_path / "pub" / "graph.db"), migrations_dir=MIGRATIONS)
    return src, pub


def _capture(src, content="Andy typed this about a friend's surgery on Tuesday"):
    """A prompt capture exactly as hooks/nudge.py inserts one."""
    eid = str(uuid.uuid4())
    src.conn.execute(
        "INSERT INTO episodes (id, content, created_at, source, session_id, content_hash, lane) "
        "VALUES (?, ?, ?, 'auto', ?, ?, 'work')",
        (eid, content, "2026-11-03T12:00:00Z", "s1", hashlib.sha256(content.encode()).hexdigest()))
    src.conn.commit()
    return eid


def _chosen(src, content="the lessons room is d1c5d6", lane="work"):
    eid = str(uuid.uuid4())
    src.add_episode(id=eid, session_id=None, content=content, episode_type="test", lane=lane)
    src.conn.commit()
    return eid


def _semantic(src, content, sources):
    sid = str(uuid.uuid4())
    src.add_semantic(id=sid, content=content, kind="fact", confidence=0.7, embedding=[0.1] * 768,
                     source_episode_ids=sources, lane="work")
    return sid


def _share(src, pub, mid, layer):
    return share(source_storage=src, published_storage=pub, source_id=mid, layer=layer, audience="commons",
                 reason="r", source_instance="rio-grande")


def _placed(pub):
    return (pub.conn.execute("SELECT COUNT(*) FROM shared_memories").fetchone()[0],
            pub.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0],
            pub.conn.execute("SELECT COUNT(*) FROM semantics").fetchone()[0])


def test_a_captured_episode_is_refused_and_nothing_is_placed(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _capture(src)
    with pytest.raises(CapturedRefused, match="captured prompt") as caught:
        _share(src, pub, eid, "episode")
    assert isinstance(caught.value, ValueError)          # the tools turn ValueError into {"error": ...}
    assert eid in str(caught.value) and "remember" in str(caught.value)
    assert _placed(pub) == (0, 0, 0)


def test_a_semantic_built_from_a_capture_is_refused(tmp_path):
    src, pub = _stores(tmp_path)
    sid = _semantic(src, "a distilled fact", [_chosen(src), _capture(src)])
    with pytest.raises(CapturedRefused, match="built from captured prompt"):
        _share(src, pub, sid, "semantic")
    assert _placed(pub) == (0, 0, 0)


def test_a_semantic_whose_source_episode_is_gone_is_refused(tmp_path):
    # The nudge hard-deletes weak captures on a raw connection with no foreign keys, so the link stays behind.
    src, pub = _stores(tmp_path)
    gone = _capture(src)
    sid = _semantic(src, "a distilled fact", [gone])
    raw = sqlite3.connect(src.db_path)
    raw.execute("DELETE FROM episodes WHERE id = ?", (gone,))
    raw.commit()
    raw.close()
    assert src.get_semantic(sid)["source_episode_ids"] == [gone]
    with pytest.raises(CapturedRefused, match="is gone"):
        _share(src, pub, sid, "semantic")
    assert _placed(pub) == (0, 0, 0)


def test_a_semantic_whose_sources_moved_to_cold_storage_is_refused(tmp_path):
    # Moving an episode to cold storage cascades its links away, so the semantic's provenance is unknown.
    src, pub = _stores(tmp_path)
    eid = _chosen(src)
    sid = _semantic(src, "built from a chosen note", [eid])
    assert src.prune_episode_ids([eid]) == 1
    assert src.get_semantic(sid)["source_episode_ids"] == []
    with pytest.raises(CapturedRefused, match="no source episodes left"):
        _share(src, pub, sid, "semantic")


def test_a_semantic_written_by_automatic_compression_is_refused(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _chosen(src)
    sid = str(uuid.uuid4())
    src.add_semantic(id=sid, content="the lessons room is d1c5d6", kind="fact", confidence=0.7,
                     embedding=[0.1] * 768, source_episode_ids=[eid], auto_generated=True, lane="work")
    with pytest.raises(CapturedRefused, match="automatic compression"):
        _share(src, pub, sid, "semantic")
    assert _share(src, pub, eid, "episode").source_id == eid     # the chosen episode itself still shares


def test_a_verbatim_copy_of_a_capture_is_refused_whatever_its_links_say(tmp_path):
    src, pub = _stores(tmp_path)
    text = "Andy typed this about a friend's surgery on Tuesday"
    _capture(src, text)
    sid = _semantic(src, text, [_chosen(src)])
    with pytest.raises(CapturedRefused, match="word for word"):
        _share(src, pub, sid, "semantic")
    assert _placed(pub) == (0, 0, 0)


def test_a_verbatim_copy_of_a_capture_in_cold_storage_is_refused(tmp_path):
    src, pub = _stores(tmp_path)
    text = "Andy typed this about a friend's surgery on Tuesday"
    captured = _capture(src, text)
    assert src.prune_episode_ids([captured]) == 1
    src.close()                                       # a fresh open has no cold connection, so the file is read
    src = Storage(str(tmp_path / "src" / "graph.db"), migrations_dir=MIGRATIONS)
    sid = _semantic(src, text, [_chosen(src)])
    with pytest.raises(CapturedRefused, match="word for word"):
        _share(src, pub, sid, "semantic")


def test_the_check_never_creates_cold_storage(tmp_path):
    src, pub = _stores(tmp_path)
    sid = _semantic(src, "a fact", [_chosen(src)])
    assert captured_reason(src, "semantic", src.get_semantic(sid)) is None
    assert not Path(src.db_path).with_name("cold.db").exists()


def test_unreadable_cold_storage_refuses_a_semantic(tmp_path):
    src, pub = _stores(tmp_path)
    Path(src.db_path).with_name("cold.db").write_bytes(b"not a database, just bytes " * 100)
    sid = _semantic(src, "a fact", [_chosen(src)])
    with pytest.raises(CapturedRefused, match="cannot be read"):
        _share(src, pub, sid, "semantic")


def test_chosen_memories_still_share(tmp_path):
    src, pub = _stores(tmp_path)
    _capture(src)
    eid = _chosen(src)
    sid = _semantic(src, "built from chosen notes", [eid, _chosen(src, "another chosen note")])
    assert _share(src, pub, eid, "episode").source_id == eid
    assert _share(src, pub, sid, "semantic").source_id == sid
    assert captured_reason(src, "episode", src.get_episode(eid)) is None


def test_a_placement_made_before_the_check_is_not_reconfirmed(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _chosen(src)
    _share(src, pub, eid, "episode")
    src.conn.execute("UPDATE episodes SET source = 'auto' WHERE id = ?", (eid,))
    src.conn.commit()
    with pytest.raises(CapturedRefused):
        _share(src, pub, eid, "episode")
    assert _placed(pub)[0] == 1                              # the old placement stays until it is unshared
