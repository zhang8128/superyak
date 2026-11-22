"""The C sheaf kernel against the sheaf standard's hand-worked known answers (Defiant's, with Tardis's loops)."""
import json
import math
from pathlib import Path

import numpy as np
import pytest

from engram import sheaf_native

CASES = sorted((Path(__file__).parent / "data" / "sheaf_known_answers").glob("vector-*.json"))
TOL = 1e-9

pytestmark = pytest.mark.skipif(not sheaf_native.available(), reason="no C compiler for the sheaf kernel here")


def test_every_vector_case_is_here():
    assert len(CASES) == 15


def _build(case):
    ids = [node["id"] for node in case["nodes"]]
    index = {node_id: i for i, node_id in enumerate(ids)}
    sheaf = sheaf_native.Sheaf([node["dim"] for node in case["nodes"]])
    for edge in case["edges"]:
        maps = [None if edge[k] == "identity" else np.array(edge[k], dtype=float) for k in ("tail_map", "head_map")]
        sheaf.add_edge(index[edge["tail"]], index[edge["head"]], maps[0], maps[1], dim=edge["dim"])
    return sheaf, ids


@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_the_kernel_gives_the_standards_known_answer(path):
    case = json.loads(path.read_text())
    assert case["standard"] == "superyak-sheaf/1" and case["kind"] == "vector"
    expect = case["expect"]
    sheaf, ids = _build(case)
    with sheaf:
        if "local" not in case:
            got = sheaf.sections()
            assert (got["h0"], got["h1"]) == (expect["dim_h0"], expect["dim_h1"]), case["why"]
            return
        x = np.concatenate([np.array(case["local"][node_id], dtype=float) for node_id in ids])
        got = sheaf.sections(x)
        assert (got["h0"], got["h1"]) == (expect["dim_h0"], expect["dim_h1"]), case["why"]
        _, squared = sheaf.energy(x)
        residuals = [math.sqrt(s) for s in squared]
        assert residuals == pytest.approx(expect["residuals"], abs=TOL), case["why"]
        assert [i for i, r in enumerate(residuals) if r > TOL] == expect["residual_edges"]
        assert (not expect["residual_edges"]) == expect["glued"]
        assert float(np.sum((x - got["section"]) ** 2)) == pytest.approx(expect["distance_squared"], abs=TOL)
