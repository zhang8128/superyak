from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

import numpy as np
import pytest

import lighthouse_sheaf as ls
from storage import Storage

ENGRAM = Path(__file__).resolve().parents[1]
DIM = 768


def unit(*weights: tuple[int, float], dim: int = DIM) -> np.ndarray:
    v = np.zeros(dim)
    for axis, w in weights:
        v[axis] = w
    return v / np.linalg.norm(v)


def jitter(v: np.ndarray, n: int, seed: int, scale: float = 0.02) -> np.ndarray:
    rng = np.random.default_rng(seed)
    X = v + scale * rng.standard_normal((n, len(v)))
    return X / np.linalg.norm(X, axis=1, keepdims=True)


CHEESE = unit((0, 1.0), (1, 0.3))
DISSENT = unit((0, 0.4), (2, 1.0))


def three_way(dissent: bool = True) -> dict[str, np.ndarray]:
    return {
        "france": jitter(CHEESE, 5, 1, 0.0),
        "italy": jitter(CHEESE, 4, 2, 0.0),
        "spain": jitter(DISSENT if dissent else CHEESE, 3, 3, 0.0),
    }


# --- core ----------------------------------------------------------------

def test_identical_sections_glue_fully():
    r = ls.glue(three_way(dissent=False))
    assert r.covered == ["france", "italy", "spain"]
    assert r.energy == pytest.approx(0.0, abs=1e-9)
    assert r.kernel_dim == r.k
    assert r.glued_dim == r.k
    assert r.glued
    assert r.harmonic_fraction == pytest.approx(0.0, abs=1e-9)


def test_dissenting_lighthouse_carries_top_residuals_and_deviates_most():
    r = ls.glue({n: jitter(v[0], 6, i) for i, (n, v) in enumerate(three_way().items())})
    assert r.energy > 0.05
    assert not r.glued
    assert r.glued_dim < r.k
    top_two = r.edges[:2]
    assert all("spain" in (e["a"], e["b"]) for e in top_two)
    assert r.edges[-1]["residual"] < top_two[1]["residual"]
    assert max(r.deviations, key=r.deviations.get) == "spain"
    assert r.harmonic_fraction > 0.0


def test_uncovered_lighthouse_is_reported_and_changes_nothing():
    base = three_way()
    without = ls.glue(base)
    with_empty = ls.glue({**base, "greece": np.zeros((0, DIM))})
    assert with_empty.uncovered == ["greece"]
    assert "greece" not in with_empty.covered
    assert with_empty.energy == pytest.approx(without.energy)
    assert with_empty.consensus == pytest.approx(without.consensus)
    assert [(e["a"], e["b"]) for e in with_empty.edges] == \
           [(e["a"], e["b"]) for e in without.edges]


def test_below_threshold_hits_mean_uncovered_not_dissent():
    base = three_way()
    scores = {"france": np.full(5, 0.9), "italy": np.full(4, 0.9),
              "spain": np.full(3, 0.1)}
    r = ls.glue(base, scores=scores, min_score=0.5)
    assert r.uncovered == ["spain"]
    assert r.energy == pytest.approx(0.0, abs=1e-9)
    assert r.glued


def test_lowering_trust_moves_consensus_away():
    base = three_way()
    full = ls.glue(base)
    low = ls.glue(base, trust={"spain": 0.1})
    spain = np.array(full.stalks["spain"])
    assert np.linalg.norm(np.array(low.consensus) - spain) > \
           np.linalg.norm(np.array(full.consensus) - spain)
    assert low.deviations["spain"] > full.deviations["spain"]
    # trust weights the verdict, never hides the disagreement
    assert low.energy_unweighted == pytest.approx(full.energy_unweighted)
    assert low.energy < full.energy


def test_min_edge_weighting_and_invalid_trust():
    r = ls.glue(three_way(), trust={"spain": 0.5, "italy": 0.8}, edge_weighting="min")
    w = {frozenset((e["a"], e["b"])): e["weight"] for e in r.edges}
    assert w[frozenset(("italy", "spain"))] == pytest.approx(0.5)
    assert w[frozenset(("france", "italy"))] == pytest.approx(0.8)
    with pytest.raises(ValueError):
        ls.glue(three_way(), trust={"spain": 1.5})


@pytest.mark.parametrize("seed", range(8))
def test_energy_stays_in_unit_interval(seed):
    rng = np.random.default_rng(seed)
    hits = {f"l{i}": rng.standard_normal((rng.integers(1, 6), 32)) for i in range(5)}
    trust = {f"l{i}": float(rng.uniform()) for i in range(5)}
    r = ls.glue(hits, trust=trust)
    for value in (r.energy, r.energy_unweighted, r.harmonic_fraction):
        assert 0.0 <= value <= 1.0
    assert all(0.0 <= d <= 1.0 for d in r.deviations.values())


def test_antipodal_sections_reach_maximal_energy():
    v = unit((0, 1.0))
    r = ls.glue({"a": v[None, :], "b": -v[None, :]})
    assert r.energy == pytest.approx(1.0)


def test_single_covered_lighthouse_is_trivially_consistent():
    r = ls.glue({"france": jitter(CHEESE, 4, 5), "greece": np.zeros((0, DIM))})
    assert r.covered == ["france"] and r.uncovered == ["greece"]
    assert r.energy == 0.0 and r.edges == []
    assert r.glued and r.kernel_dim == r.k


def test_nothing_covered():
    r = ls.glue({"a": np.zeros((0, DIM))})
    assert r.covered == [] and r.uncovered == ["a"] and r.energy == 0.0


def test_mismatched_embedding_spaces_are_refused():
    with pytest.raises(ValueError, match="restriction map"):
        ls.glue({"a": np.ones((2, 8)), "b": np.ones((2, 16))})


# --- disk adapter / CLI ----------------------------------------------------

def _add(store: Storage, vec: np.ndarray, lane: str, content: str) -> str:
    mid = str(uuid.uuid4())
    store.add_episode(mid, "s", content, embedding=vec.tolist(), lane=lane)
    return mid


def build_stores(tmp_path: Path) -> tuple[dict[str, Path], str]:
    paths = {}
    semantic_id = str(uuid.uuid4())
    plan = {"france": CHEESE, "italy": CHEESE, "spain": DISSENT}
    for i, (name, direction) in enumerate(plan.items()):
        path = tmp_path / name / "graph.db"
        path.parent.mkdir()
        store = Storage(str(path))
        ids = [_add(store, v, "work", f"{name} cheese note {j}")
               for j, v in enumerate(jitter(direction, 4, 10 + i))]
        # personal-lane memories that would flip spain if the lane leaked
        for v in jitter(CHEESE, 6, 20 + i):
            _add(store, v, "personal", f"{name} private cheese")
        if name == "france":
            store.add_semantic(semantic_id, "cheese topic", "fact", 0.9,
                               embedding=CHEESE.tolist(), source_episode_ids=ids,
                               lane="work")
        store.close()
        paths[name] = path
    return paths, semantic_id


def snapshot(paths) -> dict[str, str]:
    out = {}
    for p in paths.values():
        for f in sorted(p.parent.iterdir()):
            out[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def assert_unchanged(before: dict[str, str], after: dict[str, str]) -> None:
    """Every pre-existing file is byte-identical. SQLite may create WAL side
    files for a read-only reader of a WAL store; any new -wal must be empty."""
    for f, digest in before.items():
        assert after[f] == digest, f"{f} changed"
    for f in set(after) - set(before):
        assert f.endswith(("-wal", "-shm")), f"unexpected new file {f}"
        if f.endswith("-wal"):
            assert Path(f).stat().st_size == 0, f"{f} has content"


def test_disk_adapter_finds_dissent_without_writing(tmp_path):
    paths, sid = build_stores(tmp_path)
    before = snapshot(paths)
    query = ls.query_vector(paths["france"], "semantic", sid)
    out = ls.compare_stores(paths, query, k=4, lane="work")
    assert out["covered"] == ["france", "italy", "spain"]
    assert all(len(h) == 4 for h in out["hits"].values())
    assert all("private" not in h["content"]
               for hits in out["hits"].values() for h in hits)
    assert max(out["deviations"], key=out["deviations"].get) == "spain"
    assert "spain" in (out["edges"][0]["a"], out["edges"][0]["b"])
    assert_unchanged(before, snapshot(paths))


def test_lane_any_includes_personal(tmp_path):
    paths, sid = build_stores(tmp_path)
    query = ls.query_vector(paths["france"], "semantic", sid)
    work = ls.compare_stores(paths, query, k=10, lane="work")
    anyl = ls.compare_stores(paths, query, k=10, lane="any")
    assert all(len(h) == 4 for h in work["hits"].values())
    assert all(len(h) == 10 for h in anyl["hits"].values())
    # spain's personal cheese notes pull it back toward the others
    assert anyl["deviations"]["spain"] < work["deviations"]["spain"]


def test_min_score_leaves_far_lighthouse_uncovered(tmp_path):
    paths, sid = build_stores(tmp_path)
    query = ls.query_vector(paths["france"], "semantic", sid)
    out = ls.compare_stores(paths, query, k=4, lane="work", min_score=0.8)
    assert out["uncovered"] == ["spain"]
    assert out["glued"] or out["energy"] < 0.01


def test_cli_json_semantic_and_episode_queries(tmp_path):
    paths, sid = build_stores(tmp_path)
    before = snapshot(paths)
    stores = [a for n, p in paths.items() for a in ("--store", f"{n}={p}")]
    run = subprocess.run(
        [sys.executable, "lighthouse_sheaf.py", *stores, "--semantic",
         f"france:{sid}", "--trust", "spain=0.5", "--k", "4", "--json"],
        cwd=ENGRAM, capture_output=True, text=True, check=True)
    out = json.loads(run.stdout)
    assert out["trust"]["spain"] == 0.5
    assert max(out["deviations"], key=out["deviations"].get) == "spain"

    ro = Storage.open_read_only(paths["italy"])
    ep = ro.conn.execute(
        "SELECT id FROM episodes WHERE lane = 'work' LIMIT 1").fetchone()[0]
    ro.close()
    text = subprocess.run(
        [sys.executable, "lighthouse_sheaf.py", *stores, "--episode",
         f"italy:{ep}", "--k", "4"],
        cwd=ENGRAM, capture_output=True, text=True, check=True).stdout
    assert "energy=" in text and "spain" in text
    assert_unchanged(before, snapshot(paths))
