import sqlite3
import uuid

import pytest

from sharing import (AUDIENCE_COMMONS, INVALID_REASONS, REASON_INVALID_AUDIENCE,
                     REASON_INVALID_LAYER, ShareRecord, audiences_for,
                     list_invalid_shares, list_shares, share, unshare,
                     validate_audience)
from storage import Storage

MIGRATIONS = "migrations"


def test_commons_and_group_audiences_accepted():
    assert validate_audience(AUDIENCE_COMMONS) == "commons"
    assert validate_audience("group:engram-system") == "group:engram-system"
    assert validate_audience("group:a") == "group:a"


@pytest.mark.parametrize("bad", [
    "", "COMMONS", "commons ", "group:", "group:Engram", "group:-x", "group:x_y",
    "group:" + "a" * 65, "world", "group:a:b", None, 3,
])
def test_bad_audiences_fail_closed(bad):
    with pytest.raises((ValueError, TypeError)):
        validate_audience(bad)


def test_share_record_is_frozen_and_complete():
    rec = ShareRecord(share_id="s", memory_id="m", source_instance="engram", source_id="e",
                      layer="episode", audience="commons", reason="why",
                      content_digest="d", shared_at="2026-09-02T00:00:00Z")
    assert rec.layer == "episode"
    with pytest.raises(Exception):
        rec.audience = "group:x"


def _stores(tmp_path):
    src = Storage(str(tmp_path / "src.db"), migrations_dir=MIGRATIONS)
    pub = Storage(str(tmp_path / "pub.db"), migrations_dir=MIGRATIONS)
    return src, pub


def _episode(src, content="a lived thing"):
    eid = str(uuid.uuid4())
    src.add_episode(id=eid, session_id=None, content=content, episode_type="test")
    src.conn.commit()
    return eid


def _semantic(src, content="a learned thing", embedding=None):
    sid = str(uuid.uuid4())
    if embedding is None:
        src.conn.execute(
            "INSERT INTO semantics (id, content, kind, confidence, created_at, "
            "auto_generated, content_hash, lane) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, content, "fact", 0.75, "2026-09-02T00:00:00Z", 0, None, "personal"),
        )
        src.conn.commit()
    else:
        src.add_semantic(id=sid, content=content, kind="fact", confidence=0.75,
                         embedding=embedding, source_episode_ids=[])
    return sid


def test_share_copies_content_and_records_provenance(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _episode(src)
    rec = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
                audience="commons", reason="worth meeting me through", source_instance="engram")
    assert rec.source_id == eid and rec.source_instance == "engram" and rec.audience == "commons"
    assert rec.memory_id != eid
    copied = pub.get_episode(rec.memory_id)
    assert copied is not None and copied["content"] == "a lived thing"
    assert src.get_episode(eid) is not None


def test_share_is_idempotent_per_audience(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _episode(src)
    a = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="commons", reason="r", source_instance="engram")
    b = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="commons", reason="r2", source_instance="engram")
    assert a.share_id == b.share_id
    assert len(list_shares(published_storage=pub)) == 1


def test_second_audience_reuses_one_published_copy(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _episode(src)
    a = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="commons", reason="r", source_instance="engram")
    b = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="group:crossing", reason="r", source_instance="engram")
    assert a.memory_id == b.memory_id and a.share_id != b.share_id
    assert audiences_for(pub, a.memory_id) == {"commons", "group:crossing"}


def test_unshare_keeps_the_copy_while_another_audience_holds_it(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _episode(src)
    a = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="commons", reason="r", source_instance="engram")
    b = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="group:crossing", reason="r", source_instance="engram")
    assert unshare(published_storage=pub, share_id=a.share_id) is True
    assert pub.get_episode(a.memory_id) is not None
    assert unshare(published_storage=pub, share_id=b.share_id) is True
    assert pub.get_episode(b.memory_id) is None
    assert unshare(published_storage=pub, share_id=b.share_id) is False


def test_missing_source_and_bad_audience_fail_closed(tmp_path):
    src, pub = _stores(tmp_path)
    with pytest.raises(ValueError):
        share(source_storage=src, published_storage=pub, source_id=str(uuid.uuid4()),
              layer="episode", audience="commons", reason="r", source_instance="engram")
    eid = _episode(src)
    with pytest.raises(ValueError):
        share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="everyone", reason="r", source_instance="engram")
    with pytest.raises(ValueError):
        share(source_storage=src, published_storage=pub, source_id=eid, layer="instinct",
              audience="commons", reason="r", source_instance="engram")
    assert list_shares(published_storage=pub) == []


def test_list_shares_filters_by_audience(tmp_path):
    src, pub = _stores(tmp_path)
    e1, e2 = _episode(src, "one"), _episode(src, "two")
    share(source_storage=src, published_storage=pub, source_id=e1, layer="episode",
          audience="commons", reason="r", source_instance="engram")
    share(source_storage=src, published_storage=pub, source_id=e2, layer="episode",
          audience="group:crossing", reason="r", source_instance="engram")
    assert len(list_shares(published_storage=pub, audience="commons")) == 1
    assert len(list_shares(published_storage=pub)) == 2


def test_share_records_digest_as_hex_string(tmp_path):
    src, pub = _stores(tmp_path)
    rec = share(source_storage=src, published_storage=pub, source_id=_episode(src),
                layer="episode", audience="commons", reason="r", source_instance="engram")
    assert rec.content_digest == "7c1d39d9c11290524f7413e9e4bb01040df9c2a79024bb2f19362ab3cd4c1093"
    assert isinstance(rec.content_digest, str)


def test_share_copies_semantic_vector(tmp_path):
    src, pub = _stores(tmp_path)
    vector = [0.25] * 768
    sid = _semantic(src, embedding=vector)
    rec = share(source_storage=src, published_storage=pub, source_id=sid, layer="semantic",
                audience="commons", reason="r", source_instance="engram")
    assert pub.get_semantic(rec.memory_id)["content"] == "a learned thing"
    assert pub.get_vector("semantic", rec.memory_id) == pytest.approx(vector)


def test_share_copies_vectorless_semantic(tmp_path):
    src, pub = _stores(tmp_path)
    sid = _semantic(src)
    assert src.get_vector("semantic", sid) is None
    rec = share(source_storage=src, published_storage=pub, source_id=sid, layer="semantic",
                audience="commons", reason="r", source_instance="engram")
    copied = pub.get_semantic(rec.memory_id)
    assert copied is not None and copied["content"] == "a learned thing"
    assert copied["kind"] == "fact" and copied["confidence"] == pytest.approx(0.75)
    assert pub.get_vector("semantic", rec.memory_id) is None


@pytest.mark.parametrize("tamper", ["source", "published", "record"])
def test_idempotent_reshare_rejects_digest_mismatch(tmp_path, tamper):
    src, pub = _stores(tmp_path)
    eid = _episode(src)
    rec = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
                audience="commons", reason="r", source_instance="engram")
    if tamper == "source":
        src.conn.execute("UPDATE episodes SET content = ? WHERE id = ?", ("changed", eid))
        src.conn.commit()
    elif tamper == "published":
        pub.conn.execute("UPDATE episodes SET content = ? WHERE id = ?",
                         ("changed", rec.memory_id))
        pub.conn.commit()
    else:
        pub.conn.execute("UPDATE shared_memories SET content_digest = ? WHERE share_id = ?",
                         ("0" * 64, rec.share_id))
        pub.conn.commit()
    with pytest.raises(ValueError, match="digest mismatch"):
        share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="commons", reason="again", source_instance="engram")


def test_audiences_for_hides_tampered_published_copy(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _episode(src)
    a = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="commons", reason="r", source_instance="engram")
    share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
          audience="group:crossing", reason="r", source_instance="engram")
    pub.conn.execute("UPDATE episodes SET content = ? WHERE id = ?", ("tampered", a.memory_id))
    pub.conn.commit()
    assert audiences_for(pub, a.memory_id) == set()


def test_second_audience_rejects_tampered_sibling_before_insert(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _episode(src)
    rec = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
                audience="commons", reason="r", source_instance="engram")
    pub.conn.execute("UPDATE episodes SET content = ? WHERE id = ?",
                     ("tampered", rec.memory_id))
    pub.conn.commit()
    with pytest.raises(ValueError, match="digest mismatch"):
        share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="group:crossing", reason="r", source_instance="engram")
    assert [item.audience for item in list_shares(published_storage=pub)] == ["commons"]


def test_share_rolls_back_copy_and_vector_when_record_insert_fails(tmp_path, monkeypatch):
    class FailingSharedInsertConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, parameters=()):
            if sql.startswith("INSERT INTO shared_memories"):
                raise sqlite3.OperationalError("injected shared_memories insert failure")
            return self._connection.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self._connection, name)

    src, pub = _stores(tmp_path)
    eid = str(uuid.uuid4())
    src.add_episode(id=eid, session_id=None, content="atomic copy",
                    episode_type="test", embedding=[0.25] * 768)
    monkeypatch.setattr(pub, "conn", FailingSharedInsertConnection(pub.conn))

    with pytest.raises(sqlite3.OperationalError, match="injected shared_memories"):
        share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="commons", reason="r", source_instance="engram")

    assert pub.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 0
    assert pub.conn.execute("SELECT COUNT(*) FROM episode_vectors").fetchone()[0] == 0
    assert pub.conn.execute("SELECT COUNT(*) FROM shared_memories").fetchone()[0] == 0
    assert pub.conn.in_transaction is False


def test_corrupt_audience_is_visible_for_repair_but_not_disclosure(tmp_path, caplog):
    src, pub = _stores(tmp_path)
    eid = _episode(src)
    rec = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
                audience="commons", reason="original provenance", source_instance="engram",
                now="2026-09-02T12:00:00Z")
    pub.conn.execute(
        "UPDATE shared_memories SET audience = ? WHERE share_id = ?",
        ("everyone", rec.share_id),
    )
    pub.conn.commit()

    with caplog.at_level("WARNING", logger="sharing"):
        assert list_shares(published_storage=pub) == []
    warnings = [record for record in caplog.records if record.name == "sharing"]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == "list_shares skipped 1 invalid share records"
    assert rec.share_id not in warnings[0].getMessage()

    assert list_invalid_shares(published_storage=pub) == [{
        "share_id": rec.share_id,
        "memory_id": rec.memory_id,
        "source_instance": "engram",
        "source_id": eid,
        "layer": "episode",
        "audience": "everyone",
        "reason": "original provenance",
        "content_digest": rec.content_digest,
        "shared_at": "2026-09-02T12:00:00Z",
        "reasons": [REASON_INVALID_AUDIENCE],
    }]
    assert list_invalid_shares(published_storage=pub)[0]["reasons"] == [
        "invalid_audience"
    ]
    assert audiences_for(pub, rec.memory_id) == set()


def test_corrupt_layer_is_visible_and_unshare_preserves_copy(tmp_path, caplog):
    src, pub = _stores(tmp_path)
    eid = _episode(src)
    rec = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
                audience="commons", reason="original provenance", source_instance="engram",
                now="2026-09-02T12:00:00Z")
    pub.conn.execute(
        "UPDATE shared_memories SET layer = ? WHERE share_id = ?",
        ("instinct", rec.share_id),
    )
    pub.conn.commit()

    with caplog.at_level("WARNING", logger="sharing"):
        assert list_shares(published_storage=pub) == []
    assert [record.getMessage() for record in caplog.records if record.name == "sharing"] == [
        "list_shares skipped 1 invalid share records"
    ]
    assert list_invalid_shares(published_storage=pub) == [{
        "share_id": rec.share_id,
        "memory_id": rec.memory_id,
        "source_instance": "engram",
        "source_id": eid,
        "layer": "instinct",
        "audience": "commons",
        "reason": "original provenance",
        "content_digest": rec.content_digest,
        "shared_at": "2026-09-02T12:00:00Z",
        "reasons": [REASON_INVALID_LAYER],
    }]
    assert list_invalid_shares(published_storage=pub)[0]["reasons"] == ["invalid_layer"]

    caplog.clear()
    with caplog.at_level("WARNING"):
        assert unshare(published_storage=pub, share_id=rec.share_id) is True
    assert pub.conn.execute(
        "SELECT 1 FROM shared_memories WHERE share_id = ?", (rec.share_id,)
    ).fetchone() is None
    assert pub.get_episode(rec.memory_id) is not None
    assert [record.getMessage() for record in caplog.records if record.name == "sharing"] == [
        f"unshare kept published copy for invalid layer: "
        f"share_id={rec.share_id} memory_id={rec.memory_id}"
    ]


def test_share_with_corrupt_audience_and_layer_reports_both_sorted_reasons(tmp_path):
    src, pub = _stores(tmp_path)
    rec = share(source_storage=src, published_storage=pub, source_id=_episode(src),
                layer="episode", audience="commons", reason="r", source_instance="engram")
    pub.conn.execute(
        "UPDATE shared_memories SET audience = ?, layer = ? WHERE share_id = ?",
        ("everyone", "instinct", rec.share_id),
    )
    pub.conn.commit()

    reasons = list_invalid_shares(published_storage=pub)[0]["reasons"]
    assert reasons == [REASON_INVALID_AUDIENCE, REASON_INVALID_LAYER]
    assert reasons == ["invalid_audience", "invalid_layer"]
    assert INVALID_REASONS == tuple(reasons)
    assert reasons == sorted(reasons)


def test_valid_share_is_only_in_valid_listing(tmp_path):
    src, pub = _stores(tmp_path)
    rec = share(source_storage=src, published_storage=pub, source_id=_episode(src),
                layer="episode", audience="commons", reason="r", source_instance="engram")

    assert list_invalid_shares(published_storage=pub) == []
    assert list_shares(published_storage=pub) == [rec]


def test_invalid_shares_are_ordered_by_shared_at_then_share_id(tmp_path):
    src, pub = _stores(tmp_path)
    first = share(source_storage=src, published_storage=pub, source_id=_episode(src, "one"),
                  layer="episode", audience="commons", reason="r", source_instance="engram",
                  now="2026-09-02T12:00:00Z")
    second = share(source_storage=src, published_storage=pub, source_id=_episode(src, "two"),
                   layer="episode", audience="commons", reason="r", source_instance="engram",
                   now="2026-09-02T12:00:00Z")
    pub.conn.execute(
        "UPDATE shared_memories SET share_id = ?, audience = ? WHERE share_id = ?",
        ("z-share", "everyone", first.share_id),
    )
    pub.conn.execute(
        "UPDATE shared_memories SET share_id = ?, audience = ? WHERE share_id = ?",
        ("a-share", "everyone", second.share_id),
    )
    pub.conn.commit()

    assert [row["share_id"] for row in list_invalid_shares(published_storage=pub)] == [
        "a-share", "z-share"
    ]


def test_unknown_unshare_returns_false_without_mutation(tmp_path):
    src, pub = _stores(tmp_path)
    rec = share(source_storage=src, published_storage=pub, source_id=_episode(src),
                layer="episode", audience="commons", reason="r", source_instance="engram")

    assert unshare(published_storage=pub, share_id="missing") is False
    assert list_shares(published_storage=pub) == [rec]
    assert pub.get_episode(rec.memory_id) is not None
