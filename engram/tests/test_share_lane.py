"""A house copy keeps its source's lane (the Pi's first real lighthouse share,
2026-11-04: three work decisions crossed labelled personal)."""

from __future__ import annotations

import uuid

import pytest

from sharing import share
from storage import Storage
from tests.test_recall_margins import engram_server_env  # noqa: F401  (a fixture)

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


# A copy made before copies kept their lane (the Pi house's three, 2026-11-04) is mended when it is shared again,
# and the answer says so: never silently.

from sharing import share_noting  # noqa: E402


def _set_copy_lane(pub, layer, memory_id, lane):
    table = "episodes" if layer == "episode" else "semantics"
    pub.conn.execute(f"UPDATE {table} SET lane = ? WHERE id = ?", (lane, memory_id))
    pub.conn.commit()


def _noting(src, pub, source_id, layer, audience="commons"):
    return share_noting(source_storage=src, published_storage=pub, source_id=source_id, layer=layer,
                        audience=audience, reason="worth meeting me through", source_instance="engram")


@pytest.mark.parametrize("layer", ["episode", "semantic"])
def test_sharing_again_mends_an_older_copy_and_says_so(tmp_path, layer):
    src, pub = _stores(tmp_path)
    source = _episode(src, "work") if layer == "episode" else _semantic(src, "work", [0.1] * 768)
    first, note = _noting(src, pub, source, layer)
    assert note is None
    _set_copy_lane(pub, layer, first.memory_id, "personal")  # as copies were made before
    again, note = _noting(src, pub, source, layer)
    assert again.share_id == first.share_id
    assert note == "the house copy's lane was personal; it now follows its source: work"
    getter = pub.get_episode if layer == "episode" else pub.get_semantic
    assert getter(first.memory_id)["lane"] == "work"


def test_a_sibling_placement_mends_the_shared_copy(tmp_path):
    src, pub = _stores(tmp_path)
    source = _episode(src, "work")
    first, _ = _noting(src, pub, source, "episode")
    _set_copy_lane(pub, "episode", first.memory_id, "personal")
    sibling, note = _noting(src, pub, source, "episode", audience="group:friends")
    assert sibling.memory_id == first.memory_id and sibling.share_id != first.share_id
    assert note == "the house copy's lane was personal; it now follows its source: work"
    assert pub.get_episode(first.memory_id)["lane"] == "work"


def test_share_without_notes_still_mends(tmp_path):
    src, pub = _stores(tmp_path)
    source = _episode(src, "work")
    record = _share(src, pub, source, "episode")
    _set_copy_lane(pub, "episode", record.memory_id, "personal")
    _share(src, pub, source, "episode")
    assert pub.get_episode(record.memory_id)["lane"] == "work"


def test_the_share_tool_answer_names_the_mend(engram_server_env, tmp_path):
    import server
    from tests.test_share_tools import _published_house
    from tests.test_recall_margins import seed

    house_path = _published_house(tmp_path)
    seed()
    episode = server.remember(content="a work decision worth sharing", work=True)
    first = server.share(memory_id=episode["episode_id"], audience="commons", reason="meeting me")
    assert "lane_mended" not in first
    house = Storage(str(house_path), migrations_dir=MIGRATIONS)
    _set_copy_lane(house, "episode", first["memory_id"], "personal")
    house.close()
    again = server.share(memory_id=episode["episode_id"], audience="commons", reason="meeting me")
    assert again["lane_mended"] == "the house copy's lane was personal; it now follows its source: work"
