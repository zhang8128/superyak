"""`share` refuses captured memories (board item fix:share-refuses-captured-memories, Serenity's finding 2069b049).

The nudge hook stores a person's novel prompts verbatim as `source='auto'` episodes in the work lane. Those are a
person's typed words, not a ship's chosen memory, so no share places one, nor a semantic built from one."""
import hashlib
import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest

import sharing
from sharing import CapturedRefused, captured_reason, share
from storage import Storage

MIGRATIONS = str(Path(__file__).resolve().parent.parent / "migrations")


def _stores(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "pub").mkdir()
    src = Storage(str(tmp_path / "src" / "graph.db"), migrations_dir=MIGRATIONS)
    pub = Storage(str(tmp_path / "pub" / "graph.db"), migrations_dir=MIGRATIONS)
    return src, pub


def _capture(src, content="a person typed this about moving the team meeting to Tuesday"):
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


def _semantic(src, content, sources, **kw):
    sid = str(uuid.uuid4())
    src.add_semantic(id=sid, content=content, kind="fact", confidence=0.7, embedding=[0.1] * 768,
                     source_episode_ids=sources, lane="work", **kw)
    return sid


def _mark(src, sid):
    return src.conn.execute("SELECT touched_capture FROM semantics WHERE id = ?", (sid,)).fetchone()[0]


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


def test_a_semantic_marked_by_a_capture_stays_refused_after_the_capture_moves_to_cold_storage(tmp_path):
    # Finding 3: maintenance moves compressed episodes to cold storage, which cascades their links away. The mark stays.
    src, pub = _stores(tmp_path)
    chosen, captured = _chosen(src), _capture(src)
    sid = _semantic(src, "a distilled fact", [chosen, captured])
    assert src.prune_episode_ids([captured]) == 1
    assert src.get_semantic(sid)["source_episode_ids"] == [chosen]       # no link says a capture went into it
    with pytest.raises(CapturedRefused, match="was built from or reinforced by a captured prompt"):
        _share(src, pub, sid, "semantic")
    assert _placed(pub) == (0, 0, 0)


def test_a_semantic_marked_clean_whose_sources_all_moved_to_cold_storage_shares(tmp_path):
    # The mark replaces the "no source links" rule: a semantic stamped 0 is known clean, whatever its links say now.
    src, pub = _stores(tmp_path)
    eid = _chosen(src)
    sid = _semantic(src, "built from a chosen note", [eid])
    assert src.prune_episode_ids([eid]) == 1
    assert src.get_semantic(sid)["source_episode_ids"] == [] and _mark(src, sid) == 0
    assert _share(src, pub, sid, "semantic").source_id == sid


def _store_before_030(tmp_path):
    """A source store built with a copy of migrations 001 to 029 only."""
    mig = tmp_path / "m029"
    mig.mkdir()
    for f in sorted(Path(MIGRATIONS).glob("*.sql")):
        if int(f.name.split("_", 1)[0]) <= 29:
            shutil.copy(f, mig / f.name)
    (tmp_path / "src").mkdir()
    (tmp_path / "pub").mkdir()
    return Storage(str(tmp_path / "src" / "graph.db"), migrations_dir=str(mig))


def test_030_adds_the_mark_with_no_default_so_a_semantic_made_before_reads_null_and_is_refused(tmp_path):
    old = _store_before_030(tmp_path)
    assert "touched_capture" not in {r[1] for r in old.conn.execute("PRAGMA table_info(semantics)")}
    eid = _chosen(old)
    before = str(uuid.uuid4())
    old.conn.execute(
        "INSERT INTO semantics (id, content, kind, confidence, created_at, auto_generated, content_hash, lane) "
        "VALUES (?, 'made before migration 030', 'fact', 0.7, '2026-11-01T00:00:00Z', 0, 'h', 'work')", (before,))
    old.conn.execute("INSERT INTO semantic_sources (semantic_id, episode_id) VALUES (?, ?)", (before, eid))
    old.conn.commit()
    old.close()

    src = Storage(str(tmp_path / "src" / "graph.db"), migrations_dir=MIGRATIONS)
    pub = Storage(str(tmp_path / "pub" / "graph.db"), migrations_dir=MIGRATIONS)
    column = {r[1]: r for r in src.conn.execute("PRAGMA table_info(semantics)")}["touched_capture"]
    assert column[4] is None                                  # no default, so every row from before reads unknown
    assert _mark(src, before) is None
    with pytest.raises(CapturedRefused, match="was made before Engram recorded whether a captured prompt went into it, "
                                              "or by a path that doesn't record it, so that cannot be told; remember"):
        _share(src, pub, before, "semantic")
    with pytest.raises(sqlite3.IntegrityError):
        src.conn.execute("UPDATE semantics SET touched_capture = 2 WHERE id = ?", (before,))
    src.conn.rollback()

    after = _semantic(src, "made after migration 030", [eid])
    assert _mark(src, after) == 0
    assert _share(src, pub, after, "semantic").source_id == after


def test_a_link_to_a_capture_written_without_the_helper_raises_the_mark(tmp_path):
    # Round 2, N2: a server still running code from before 030 links a capture without marking it. The trigger marks.
    src, pub = _stores(tmp_path)
    chosen, captured = _chosen(src), _capture(src)
    sid = _semantic(src, "a fact", [chosen])
    src.conn.execute("INSERT INTO semantic_sources (semantic_id, episode_id) VALUES (?, ?)",
                     (sid, _chosen(src, "a chosen note old code linked")))
    src.conn.commit()
    assert _mark(src, sid) == 0
    src.conn.execute("INSERT INTO semantic_sources (semantic_id, episode_id) VALUES (?, ?)", (sid, captured))
    src.conn.commit()
    assert _mark(src, sid) == 1
    assert src.prune_episode_ids([captured]) == 1                      # the link cascades away; the mark stays
    with pytest.raises(CapturedRefused, match="was built from or reinforced by a captured prompt"):
        _share(src, pub, sid, "semantic")


@pytest.mark.parametrize("capture_in_cold", [False, True])
def test_a_copy_linked_by_old_code_to_a_semantic_marked_clean_is_refused_at_share(tmp_path, capture_in_cold):
    # Round 4, probe P5: old code links remember's copy of a capture without marking, and 030's trigger matches
    # source 'auto' only, so the mark stays 0. Share's link check refuses it while the link exists.
    src, pub = _stores(tmp_path)
    text = "a person typed this about moving the team meeting to Tuesday"
    captured = _capture(src, text)
    sid = _semantic(src, "a week of appointments", [_chosen(src)])
    copy = _chosen(src, text)
    if capture_in_cold:
        assert src.prune_episode_ids([captured]) == 1
    src.conn.execute("INSERT INTO semantic_sources (semantic_id, episode_id) VALUES (?, ?)", (sid, copy))
    src.conn.commit()
    assert _mark(src, sid) == 0
    with pytest.raises(CapturedRefused) as caught:
        _share(src, pub, sid, "semantic")
    assert str(caught.value) == (f"semantic {sid} is built from episode {copy}, which holds a captured prompt's text "
                                 "word for word; remember what you mean to share, in your own words, and share that")
    assert _placed(pub) == (0, 0, 0)


def test_030_indexes_capture_digests_and_runs_again_harmlessly(tmp_path):
    # Round 4: the store's half of the capture digests is an index read, not a scan of every episode.
    src, _ = _stores(tmp_path)
    query = "SELECT content_hash FROM episodes WHERE source = 'auto' AND content_hash IS NOT NULL"

    def index_sql():
        return [r[0] for r in src.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'episodes_capture_digest'")]

    (sql,) = index_sql()
    assert "ON episodes(content_hash) WHERE source = 'auto'" in sql
    assert any("episodes_capture_digest" in r[-1] for r in src.conn.execute(f"EXPLAIN QUERY PLAN {query}"))
    src.conn.execute("DELETE FROM schema_version WHERE version = 30")
    src.conn.commit()
    src.close()
    src = Storage(str(tmp_path / "src" / "graph.db"), migrations_dir=MIGRATIONS)
    assert src.conn.execute("SELECT COUNT(*) FROM schema_version WHERE version = 30").fetchone()[0] == 1
    assert len(index_sql()) == 1


def test_030_runs_again_harmlessly(tmp_path):
    src, _ = _stores(tmp_path)
    chosen, captured = _chosen(src), _capture(src)
    clean, marked = _semantic(src, "clean", [chosen]), _semantic(src, "marked", [chosen, captured])
    unknown = _semantic(src, "unknown", [chosen])
    src.conn.execute("UPDATE semantics SET touched_capture = NULL WHERE id = ?", (unknown,))
    src.conn.execute("DELETE FROM schema_version WHERE version = 30")
    src.conn.commit()
    src.close()

    src = Storage(str(tmp_path / "src" / "graph.db"), migrations_dir=MIGRATIONS)   # the ALTER is skipped
    assert src.conn.execute("SELECT COUNT(*) FROM schema_version WHERE version = 30").fetchone()[0] == 1
    assert (_mark(src, clean), _mark(src, marked), _mark(src, unknown)) == (0, 1, None)
    assert src.conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' "
                            "AND name = 'semantic_sources_mark_capture'").fetchone()[0] == 1
    src.conn.execute("INSERT INTO semantic_sources (semantic_id, episode_id) VALUES (?, ?)", (clean, captured))
    src.conn.commit()
    assert _mark(src, clean) == 1


def test_a_copy_of_a_captures_text_counts_as_a_capture_for_the_mark(tmp_path):
    # Round 3, S1: share refuses remember's copy of a capture's text, so the mark counts the copy as a capture too.
    src, pub = _stores(tmp_path)
    text = "a person typed this about moving the team meeting to Tuesday"
    _capture(src, text)
    copy, chosen = _chosen(src, text), _chosen(src)
    assert src.get_episode(copy)["source"] is None
    sid = _semantic(src, "what moving the meeting means for the week", [chosen, copy])
    assert _mark(src, sid) == 1
    assert src.mark_touched_capture(_semantic(src, "a clean fact", [chosen]), [copy]) is True
    clean = _semantic(src, "a fact reinforced by a copy", [chosen])
    src.reinforce_semantic(clean, [copy])
    assert _mark(src, clean) == 1


def test_a_copy_of_the_text_of_a_capture_in_cold_storage_counts_as_a_capture(tmp_path):
    src, pub = _stores(tmp_path)
    text = "a person typed this about moving the team meeting to Tuesday"
    assert src.prune_episode_ids([_capture(src, text)]) == 1
    src.close()                                       # a fresh open has no cold connection, so the file is read
    src = Storage(str(tmp_path / "src" / "graph.db"), migrations_dir=MIGRATIONS)
    sid = _semantic(src, "a week of appointments", [_chosen(src), _chosen(src, text)])
    assert _mark(src, sid) == 1
    assert getattr(src, "_cold_conn", None) is None   # read-only: Storage._cold_storage was never called


def test_with_unreadable_cold_storage_an_episode_with_no_source_of_its_own_gives_an_unknown_mark(tmp_path):
    src, pub = _stores(tmp_path)
    chosen, captured = _chosen(src), _capture(src)
    clean, marked = _semantic(src, "clean before", [chosen]), _semantic(src, "marked before", [chosen, captured])
    Path(src.db_path).with_name("cold.db").write_bytes(b"not a database, just bytes " * 100)
    later = _chosen(src, "a chosen note written while cold storage cannot be read")

    assert _mark(src, _semantic(src, "made now", [later])) is None       # never 0
    assert src.mark_touched_capture(clean, [later]) is None
    assert _mark(src, clean) is None
    src.reinforce_semantic(marked, [later])
    assert _mark(src, marked) == 1                                         # it never goes down
    assert _mark(src, _semantic(src, "made from a capture now", [later, captured])) == 1   # 1 over NULL
    assert src.mark_touched_capture(_semantic(src, "no ids", [later]), []) is False


def test_with_unreadable_cold_storage_a_copy_of_a_capture_in_the_store_still_marks_1(tmp_path):
    # 1 over NULL: the store alone shows the copy, whatever cold storage would have said.
    src, pub = _stores(tmp_path)
    text = "a person typed this about moving the team meeting to Tuesday"
    _capture(src, text)
    Path(src.db_path).with_name("cold.db").write_bytes(b"not a database, just bytes " * 100)
    copy = _chosen(src, text)
    assert _mark(src, _semantic(src, "a week of appointments", [copy])) == 1
    assert src.mark_touched_capture(_semantic(src, "another fact", [_chosen(src)]), [copy]) is True


def test_add_semantic_marks_a_capture_among_its_sources_or_its_cluster(tmp_path):
    src, _ = _stores(tmp_path)
    chosen, captured = _chosen(src), _capture(src)
    assert _mark(src, _semantic(src, "from a chosen note", [chosen])) == 0
    assert _mark(src, _semantic(src, "a captured source", [chosen, captured])) == 1
    assert _mark(src, _semantic(src, "a capture in its cluster only", [chosen],
                                cluster_episode_ids=[chosen, captured])) == 1
    assert _mark(src, _semantic(src, "a chosen cluster", [chosen],
                                cluster_episode_ids=[chosen, _chosen(src, "another chosen note")])) == 0


def test_mark_touched_capture_says_whether_a_capture_is_among_the_ids(tmp_path):
    src, _ = _stores(tmp_path)
    chosen, captured = _chosen(src), _capture(src)
    sid = _semantic(src, "a fact", [chosen])
    assert src.mark_touched_capture(sid, [chosen, "no-such-episode"]) is False and _mark(src, sid) == 0
    assert src.mark_touched_capture(sid, [chosen, captured]) is True and _mark(src, sid) == 1
    assert src.mark_touched_capture(sid, []) is False and _mark(src, sid) == 1


def test_reinforcing_with_a_capture_raises_the_mark_and_nothing_lowers_it(tmp_path):
    src, pub = _stores(tmp_path)
    chosen, captured = _chosen(src), _capture(src)
    sid = _semantic(src, "a fact", [chosen])
    src.reinforce_semantic(sid, [_chosen(src, "more chosen")])
    assert _mark(src, sid) == 0
    src.reinforce_semantic(sid, [captured])
    assert _mark(src, sid) == 1
    src.reinforce_semantic(sid, [_chosen(src, "a later chosen note")])
    assert _mark(src, sid) == 1                                        # it never goes down
    assert src.prune_episode_ids([captured]) == 1                      # its link to the capture cascades away
    with pytest.raises(CapturedRefused, match="was built from or reinforced by a captured prompt"):
        _share(src, pub, sid, "semantic")
    captured = _capture(src, "another prompt a person typed")

    unknown = _semantic(src, "a fact whose mark is unknown", [chosen])
    src.conn.execute("UPDATE semantics SET touched_capture = NULL WHERE id = ?", (unknown,))
    src.conn.commit()
    src.reinforce_semantic(unknown, [_chosen(src, "yet another chosen note")])
    assert _mark(src, unknown) is None                                 # a NULL stays NULL unless a capture comes in
    src.reinforce_semantic(unknown, [captured])
    assert _mark(src, unknown) == 1


def test_a_semantic_written_by_automatic_compression_is_refused(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _chosen(src)
    sid = str(uuid.uuid4())
    src.add_semantic(id=sid, content="the lessons room is d1c5d6", kind="fact", confidence=0.7,
                     embedding=[0.1] * 768, source_episode_ids=[eid], auto_generated=True, lane="work")
    with pytest.raises(CapturedRefused, match="automatic compression"):
        _share(src, pub, sid, "semantic")
    assert _share(src, pub, eid, "episode").source_id == eid     # the chosen episode itself still shares


def test_a_semantic_whose_auto_generated_is_null_is_refused(tmp_path):
    # Note 9: nothing writes NULL today, but a NULL must fail closed, as written by automatic compression.
    src, pub = _stores(tmp_path)
    sid = _semantic(src, "a fact of unknown authorship", [_chosen(src)])
    src.conn.execute("UPDATE semantics SET auto_generated = NULL WHERE id = ?", (sid,))
    src.conn.commit()
    assert _mark(src, sid) == 0
    with pytest.raises(CapturedRefused, match="automatic compression"):
        _share(src, pub, sid, "semantic")


def test_a_verbatim_copy_of_a_capture_is_refused_whatever_its_links_say(tmp_path):
    src, pub = _stores(tmp_path)
    text = "a person typed this about moving the team meeting to Tuesday"
    _capture(src, text)
    sid = _semantic(src, text, [_chosen(src)])
    with pytest.raises(CapturedRefused, match="word for word"):
        _share(src, pub, sid, "semantic")
    assert _placed(pub) == (0, 0, 0)


def test_a_verbatim_copy_of_a_capture_in_cold_storage_is_refused(tmp_path):
    src, pub = _stores(tmp_path)
    text = "a person typed this about moving the team meeting to Tuesday"
    captured = _capture(src, text)
    assert src.prune_episode_ids([captured]) == 1
    src.close()                                       # a fresh open has no cold connection, so the file is read
    src = Storage(str(tmp_path / "src" / "graph.db"), migrations_dir=MIGRATIONS)
    sid = _semantic(src, text, [_chosen(src)])
    with pytest.raises(CapturedRefused, match="word for word"):
        _share(src, pub, sid, "semantic")


def test_an_open_cold_connection_is_read_for_a_capture_without_reopening_cold_storage(tmp_path, monkeypatch):
    # Note 7: the `_cold_conn` reuse branch, with a capture in cold storage and the store never reopened.
    src, pub = _stores(tmp_path)
    text = "a person typed this about moving the team meeting to Tuesday"
    captured = _capture(src, text)
    assert src.prune_episode_ids([captured]) == 1
    assert src._cold_conn is not None
    sid = _semantic(src, text, [_chosen(src)])
    eid = _chosen(src, text)
    monkeypatch.setattr(sharing.sqlite3, "connect",
                        lambda *a, **k: pytest.fail("cold storage was opened again"))
    with pytest.raises(CapturedRefused, match="word for word"):
        _share(src, pub, sid, "semantic")
    with pytest.raises(CapturedRefused, match="holds a captured prompt's text word for word"):
        _share(src, pub, eid, "episode")
    assert _placed(pub) == (0, 0, 0)


def test_an_episode_holding_a_captures_text_is_refused(tmp_path):
    # Finding 4: `remember(content=<a capture's text>)` strips it as the nudge does, so the digest matches.
    src, pub = _stores(tmp_path)
    text = "a person typed this about moving the team meeting to Tuesday"
    _capture(src, text)
    eid = _chosen(src, text)
    assert src.get_episode(eid)["source"] is None
    with pytest.raises(CapturedRefused) as caught:
        _share(src, pub, eid, "episode")
    assert str(caught.value) == (f"episode {eid} holds a captured prompt's text word for word; remember what you mean "
                                 "to share, in your own words, and share that")
    assert _placed(pub) == (0, 0, 0)


def test_an_episode_holding_the_text_of_a_capture_in_cold_storage_is_refused(tmp_path):
    src, pub = _stores(tmp_path)
    text = "a person typed this about moving the team meeting to Tuesday"
    assert src.prune_episode_ids([_capture(src, text)]) == 1
    src.close()                                       # a fresh open has no cold connection, so the file is read
    src = Storage(str(tmp_path / "src" / "graph.db"), migrations_dir=MIGRATIONS)
    eid = _chosen(src, text)
    with pytest.raises(CapturedRefused, match="holds a captured prompt's text word for word"):
        _share(src, pub, eid, "episode")
    assert _placed(pub) == (0, 0, 0)


def test_unreadable_cold_storage_refuses_an_episode(tmp_path):
    src, pub = _stores(tmp_path)
    Path(src.db_path).with_name("cold.db").write_bytes(b"not a database, just bytes " * 100)
    eid = _chosen(src)
    with pytest.raises(CapturedRefused, match="cannot be read"):
        _share(src, pub, eid, "episode")


def test_the_check_never_creates_cold_storage(tmp_path):
    src, pub = _stores(tmp_path)
    sid = _semantic(src, "a fact", [_chosen(src)])
    assert captured_reason(src, "semantic", src.get_semantic(sid)) is None
    assert not Path(src.db_path).with_name("cold.db").exists()


def test_the_episode_check_never_creates_cold_storage(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _chosen(src)
    assert captured_reason(src, "episode", src.get_episode(eid)) is None
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
