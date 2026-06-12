"""Tests for sheaf sleep pass and content distillation."""

import json

import numpy as np
import pytest

import sheaf


def _emb(axis: int, noise: float, seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    v = np.zeros(768); v[axis] = 1.0
    v = v + noise * rng.standard_normal(768)
    return (v / np.linalg.norm(v)).tolist()


def _seed_store(tmp_db):
    """sem-hot conflates axes 0 and 1; sem-cool is tight on axis 2."""
    hot_eps, cool_eps = [], []
    for i in range(10):
        eid = f"hot-{i}"
        tmp_db.add_episode(id=eid, session_id="s", content=f"hot episode {i}",
                           embedding=_emb(0 if i < 5 else 1, 0.05, i))
        hot_eps.append(eid)
    for i in range(6):
        eid = f"cool-{i}"
        tmp_db.add_episode(id=eid, session_id="s", content=f"cool episode {i}",
                           embedding=_emb(2, 0.05, 50 + i))
        cool_eps.append(eid)
    tmp_db.add_semantic(id="sem-hot", content="conflated", kind="fact",
                        confidence=0.8, embedding=_emb(0, 0.3, 99),
                        source_episode_ids=hot_eps)
    tmp_db.add_semantic(id="sem-cool", content="coherent", kind="fact",
                        confidence=0.8, embedding=_emb(2, 0.05, 98),
                        source_episode_ids=cool_eps)


class TestSleepPass:
    def _run(self, tmp_db, monkeypatch, **kw):
        monkeypatch.setattr(
            sheaf, "distill_subdivision",
            lambda parent, parts, amb, cfg: ([f"peer {i}" for i in range(len(parts))],
                                             "shared" if amb else None))
        from config import CohesionConfig
        return sheaf.run_sleep_pass(
            tmp_db, embed_fn=lambda t: _emb(5, 0.1, abs(hash(t)) % 1000),
            framing_cfg=None, cfg=CohesionConfig(), **kw)

    def test_splits_hot_not_cool(self, tmp_db, monkeypatch):
        _seed_store(tmp_db)
        report = self._run(tmp_db, monkeypatch)
        assert "sem-hot" in [s["parent_id"] for s in report["subdivided"]]
        assert tmp_db.get_semantic_peers("sem-hot") != []
        assert tmp_db.get_semantic_peers("sem-cool") == []

    def test_narration_episode_written(self, tmp_db, monkeypatch):
        _seed_store(tmp_db)
        self._run(tmp_db, monkeypatch)
        row = tmp_db.conn.execute(
            "SELECT content FROM episodes WHERE content LIKE"
            " 'Sleep-time subdivision:%'").fetchone()
        assert row is not None

    def test_budget_respected(self, tmp_db, monkeypatch):
        _seed_store(tmp_db)
        from config import CohesionConfig
        monkeypatch.setattr(
            sheaf, "distill_subdivision",
            lambda parent, parts, amb, cfg: ([f"p{i}" for i in range(len(parts))], None))
        report = sheaf.run_sleep_pass(
            tmp_db, embed_fn=lambda t: _emb(5, 0.1, 1),
            framing_cfg=None, cfg=CohesionConfig(sleep_budget=0))
        assert report["subdivided"] == []

    def test_distill_failure_queues(self, tmp_db, monkeypatch):
        _seed_store(tmp_db)
        monkeypatch.setattr(sheaf, "distill_subdivision",
                            lambda parent, parts, amb, cfg: None)
        from config import CohesionConfig
        report = sheaf.run_sleep_pass(
            tmp_db, embed_fn=lambda t: _emb(5, 0.1, 1),
            framing_cfg=None, cfg=CohesionConfig())
        assert report["subdivided"] == []
        assert "sem-hot" in [q["parent_id"] for q in tmp_db.get_queued_subdivisions()]
        assert tmp_db.get_semantic_peers("sem-hot") == []

    def test_rate_limited_second_run_skips(self, tmp_db, monkeypatch):
        _seed_store(tmp_db)
        self._run(tmp_db, monkeypatch)
        report2 = self._run(tmp_db, monkeypatch)
        assert report2.get("skipped") == "rate_limited"


class TestDistillSubdivision:
    def test_parses_valid_response(self, monkeypatch):
        reply = json.dumps({"peers": ["About Mistborn.", "About Perfect State."],
                            "hub": "Reading sessions in general."})
        monkeypatch.setattr(sheaf, "_ollama_generate", lambda prompt, cfg: reply)
        out = sheaf.distill_subdivision(
            parent_content="Reading sessions: Mistborn and Perfect State",
            part_episode_contents=[["read mistborn ch1"], ["read perfect state"]],
            has_ambiguous=True, framing_cfg=None)
        assert out == (["About Mistborn.", "About Perfect State."],
                       "Reading sessions in general.")

    def test_none_on_transport_failure(self, monkeypatch):
        monkeypatch.setattr(sheaf, "_ollama_generate", lambda prompt, cfg: None)
        assert sheaf.distill_subdivision("x", [["a"], ["b"]], False, None) is None

    def test_none_on_wrong_peer_count(self, monkeypatch):
        reply = json.dumps({"peers": ["only one"], "hub": None})
        monkeypatch.setattr(sheaf, "_ollama_generate", lambda prompt, cfg: reply)
        assert sheaf.distill_subdivision("x", [["a"], ["b"]], False, None) is None
