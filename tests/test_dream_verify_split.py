"""dream_verify reveals matched and uninvited scores as two maps."""

from __future__ import annotations

import server
from tests.test_recall_margins import engram_server_env, seed  # noqa: F401


def test_uninvited_scores_are_not_mixed_into_matched_scores(engram_server_env):
    seed(8)
    server.dream_capture(reaction="a low hum I cannot place")
    out = server.recall(
        query="rivers and mapping", max_results=3, uninvited=2
    )
    assert out.get("dreaming") is True

    revealed = server.dream_verify(out["recall_id"])
    matched_ids = {r["id"] for r in out["results"] if not r.get("uninvited")}
    uninvited_ids = {r["id"] for r in out["results"] if r.get("uninvited")}

    assert set(revealed["scores"]) == matched_ids
    assert set(revealed["uninvited_scores"]) == uninvited_ids
    assert not (set(revealed["scores"]) & set(revealed["uninvited_scores"]))


def test_recall_without_uninvited_reveals_empty_uninvited_map(
    engram_server_env,
):
    seed(3)
    server.dream_capture(reaction="a low hum I cannot place")
    out = server.recall(query="rivers and mapping", uninvited=0)

    revealed = server.dream_verify(out["recall_id"])
    assert revealed["uninvited_scores"] == {}
    assert len(revealed["scores"]) == len(out["results"])


def test_unknown_recall_id_still_errors(engram_server_env):
    seed(1)
    assert "error" in server.dream_verify("does-not-exist")
