from pathlib import Path

import server
from tests.test_recall_margins import engram_server_env, seed  # noqa: F401


MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


def _published_house(tmp_path):
    from storage import Storage
    path = tmp_path / ".engram" / "instances" / "lighthouse" / "graph.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    store = Storage(str(path), migrations_dir=MIGRATIONS_DIR)
    store.close()
    return path


def test_share_returns_a_record_and_unshare_removes_it(engram_server_env, tmp_path):
    _published_house(tmp_path)
    seed()
    episode = server.remember(content="a thing worth sharing")

    out = server.share(
        memory_id=episode["episode_id"], audience="commons", reason="meeting me"
    )

    assert out["audience"] == "commons" and out["share_id"]
    assert any(
        item["share_id"] == out["share_id"]
        for item in server.shares(audience="commons")["shares"]
    )
    assert server.unshare(share_id=out["share_id"])["removed"] is True
    assert server.shares()["shares"] == []


def test_bad_audience_is_an_error_not_a_crash(engram_server_env, tmp_path):
    _published_house(tmp_path)
    seed()
    episode = server.remember(content="another thing")

    out = server.share(
        memory_id=episode["episode_id"], audience="everyone", reason="r"
    )

    assert "error" in out and "audience" in out["error"]


def test_sharing_an_unknown_memory_is_an_error(engram_server_env, tmp_path):
    _published_house(tmp_path)
    seed()

    out = server.share(
        memory_id="00000000-0000-4000-8000-000000000000",
        audience="commons",
        reason="r",
    )

    assert "error" in out


def test_share_tools_fail_without_creating_a_missing_published_house(
    engram_server_env, tmp_path
):
    path = tmp_path / ".engram" / "instances" / "lighthouse" / "graph.db"
    error = {"error": f"no published house at {path}"}

    assert server.share(memory_id="missing", audience="commons", reason="r") == error
    assert server.shares() == error
    assert server.unshare(share_id="missing") == error
    assert not path.exists()
    assert not path.parent.exists()


def test_sharing_a_captured_prompt_is_an_error_and_places_nothing(engram_server_env, tmp_path):
    # fix:share-refuses-captured-memories: the nudge's captures (source 'auto') are a person's typed words.
    _published_house(tmp_path)
    seed()
    episode = server.remember(content="a prompt the nudge hook captured, typed by a person")
    server._storage.conn.execute("UPDATE episodes SET source = 'auto' WHERE id = ?", (episode["episode_id"],))
    server._storage.conn.commit()

    out = server.share(memory_id=episode["episode_id"], audience="commons", reason="r")

    assert "error" in out and "captured prompt" in out["error"]
    assert server.shares()["shares"] == []


def test_shares_names_refused_now_for_a_placement_whose_source_became_a_capture(engram_server_env, tmp_path):
    # Finding 5: a placement made before the check stays served, so the owner's list says which ones it would refuse.
    import sharing
    from storage import Storage
    path = _published_house(tmp_path)
    seed()
    became = server.remember(content="a note that a later rewrite marks as a person's captured prompt")["episode_id"]
    chosen = server.remember(content="a note the ship chose and still means to share")["episode_id"]
    gone = server.remember(content="a note shared and later removed from this store")["episode_id"]
    placed = {mid: server.share(memory_id=mid, audience="commons", reason="r")["share_id"]
              for mid in (became, chosen, gone)}
    house = Storage(str(path), migrations_dir=MIGRATIONS_DIR)
    try:                                              # the same source id, placed by another instance
        elsewhere = sharing.share(source_storage=server._storage, published_storage=house, source_id=became,
                                  layer="episode", audience="group:ph", reason="r",
                                  source_instance="elsewhere").share_id
    finally:
        house.close()
    server._storage.conn.execute("UPDATE episodes SET source = 'auto' WHERE id = ?", (became,))
    server._storage.conn.execute("DELETE FROM episodes WHERE id = ?", (gone,))
    server._storage.conn.commit()

    listed = {item["share_id"]: item for item in server.shares()["shares"]}

    assert set(listed) == {*placed.values(), elsewhere}
    assert listed[placed[became]]["refused_now"] == sharing.captured_reason(
        server._storage, "episode", server._storage.get_episode(became))
    assert "captured prompt" in listed[placed[became]]["refused_now"]
    for share_id in (placed[chosen], placed[gone], elsewhere):
        assert "refused_now" not in listed[share_id]
