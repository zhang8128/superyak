"""A lane-filtered recall's margin describes the lane it returned."""

from __future__ import annotations

import json

import server
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
