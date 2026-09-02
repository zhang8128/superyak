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
