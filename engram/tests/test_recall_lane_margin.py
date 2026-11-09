"""A lane-filtered recall's margin describes the lane it returned."""

from __future__ import annotations

import json

import server
from tests.test_recall_margins import add_session_bias
from tests.test_recall_margins import engram_server_env  # noqa: F401


def _seed_two_lanes():
    server._init()
    server._session_episode_count = 0
    server._config.compression.auto_threshold = 1000
    for i in range(3):
        server.remember(
            content=f"work note {i} about rivers and mapping", work=True
        )
    for i in range(3):
        server.remember(
            content=f"personal note {i} about rivers and mapping"
        )


def test_work_lane_recall_fills_max_results(engram_server_env):
    _seed_two_lanes()
    out = server.recall(
        query="rivers and mapping", lane="work", max_results=3, uninvited=0
    )
    assert len(out["results"]) == 3
    assert all(r["lane"] == "work" for r in out["results"])


def test_margin_counts_only_requested_lane(engram_server_env):
    _seed_two_lanes()
    out = server.recall(
        query="rivers and mapping", lane="work", max_results=3, uninvited=0
    )
    assert out["margin"]["n"] == 3


def test_unfiltered_recall_still_sees_both_lanes(engram_server_env):
    _seed_two_lanes()
    out = server.recall(
        query="rivers and mapping", max_results=10, uninvited=0
    )
    assert {r["lane"] for r in out["results"]} == {"work", "personal"}
    assert out["margin"]["n"] == 6


def test_log_target_ids_match_returned_ids(engram_server_env):
    _seed_two_lanes()
    out = server.recall(
        query="rivers and mapping", lane="personal", max_results=2, uninvited=0
    )
    row = server._storage.conn.execute(
        "SELECT target_ids FROM memory_log WHERE event_type = 'recall' "
        "AND json_extract(context, '$.recall_id') = ?",
        (out["recall_id"],),
    ).fetchone()
    assert json.loads(row["target_ids"]) == [r["id"] for r in out["results"]]


def test_biased_lane_recall_counterfactual_stays_in_requested_lane(
    engram_server_env, monkeypatch
):
    server._init()
    server._config.compression.auto_threshold = 1000
    work_id = server.remember(content="work rivers", work=True)["episode_id"]
    personal_id = server.remember(content="personal rivers")["episode_id"]
    add_session_bias("rivers")
    searches = iter(
        [
            {
                work_id: {"layer": "episode", "similarity": 0.9},
                personal_id: {"layer": "episode", "similarity": 0.8},
            },
            {
                personal_id: {"layer": "episode", "similarity": 0.99},
                work_id: {"layer": "episode", "similarity": 0.7},
            },
        ]
    )
    monkeypatch.setattr(
        server, "_vector_candidates", lambda *_args, **_kwargs: (next(searches), [])
    )

    out = server.recall(query="rivers", lane="work", max_results=2, uninvited=0)

    assert [row["id"] for row in out["results"]] == [work_id]
    assert out["margin"]["stability"] == {
        "checked": True,
        "survives": True,
        "displaced": None,
    }


def test_a_recall_kept_to_one_lane_returns_no_transfers(engram_server_env, monkeypatch):
    """A transfer's text quotes earlier queries word for word, and a cell doesn't know its lane."""
    _seed_two_lanes()

    class Transfers:
        def search(self, embedding, level=None, limit=10):
            return [{"content": "cross-domain: 'a personal question' connects to 'a work question'", "level": 2, "context": {}}]

    monkeypatch.setattr(server, "_category_store", Transfers())

    assert server.recall(query="rivers", max_results=2, uninvited=0)["transfers"]  # the store is wired, and both lanes still see them
    out = server.recall(query="rivers", lane="work", max_results=2, uninvited=0)
    assert "transfers" not in out
    assert "a personal question" not in json.dumps(out)


def test_a_recall_kept_to_one_lane_returns_no_knowledge(engram_server_env, monkeypatch):
    """The knowledge graph is fed episodes from both lanes and keeps no lane, so its facts can quote either."""
    _seed_two_lanes()

    class Knowledge:
        enabled = True

        def search(self, query, num_results=10):
            return {"facts": [{"id": "f1", "relationship": "a personal fact about rivers"}], "historical": []}

    monkeypatch.setattr(server, "_knowledge_graph", Knowledge())

    assert server.recall(query="rivers", max_results=2, uninvited=0)["knowledge"]  # the graph is wired, and an unkept recall still sees it
    out = server.recall(query="rivers", lane="work", max_results=2, uninvited=0)
    assert "knowledge" not in out
    assert "a personal fact" not in json.dumps(out)


def test_dream_verify_names_no_memory_from_another_lane(engram_server_env, monkeypatch):
    """Hidden scores are kept before the lane filter runs; verifying them names only what the lane let through."""
    _seed_two_lanes()
    lanes = dict(server._storage.conn.execute("SELECT id, lane FROM episodes").fetchall())
    personal = [i for i, lane in lanes.items() if lane == "personal"]
    monkeypatch.setattr(server, "_has_active_residue", lambda: True)
    monkeypatch.setattr(
        server._storage, "sample_distant_memories",
        lambda *a, **k: [(i, "episode", 0.5) for i in personal],
    )

    unkept = server.dream_verify(server.recall(query="rivers", max_results=2, uninvited=3)["recall_id"])
    assert set(unkept["uninvited_scores"]) & set(personal)  # the draw reaches the other lane, and an unkept recall shows it

    kept = server.dream_verify(server.recall(query="rivers", lane="work", max_results=2, uninvited=3)["recall_id"])
    named = set(kept["scores"]) | set(kept["uninvited_scores"])
    assert named and all(lanes.get(i) == "work" for i in named)
