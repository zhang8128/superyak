"""The C++ sheaf core against its oracle, sheaf_core: the standard's known answers, then agreement on random sheaves,
then what the kernel does with arguments no caller should send."""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import numpy as np
import pytest

import sheaf_core as sc
import sheaf_native as sn
from tests.test_sheaf_core import (KNOWN, constant_sheaf, flat_sheaf, good_doc, random_graph, random_set_sheaf,
                             random_sheaf)

ENGRAM = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- the standard's known answers

@pytest.mark.parametrize("path", KNOWN, ids=lambda p: p.stem)
def test_known_answer(path):
    report = sc.check_file(path, compute=sn.answers)
    assert report["status"] == "ok", report
    assert set(json.loads(path.read_text())["expect"]) <= set(report["answers"])


def test_the_check_command_can_use_the_kernel():
    done = subprocess.run([sys.executable, str(ENGRAM / "sheaf_core.py"), "check", "--native", *map(str, KNOWN)],
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    assert all(line.startswith("ok") for line in done.stdout.splitlines()) and done.stdout.count("\n") == len(KNOWN)
    refused = subprocess.run([sys.executable, str(ENGRAM / "sheaf_core.py"), "check", "--native",
                              "--budget-bytes", "10", str(KNOWN[-1])], capture_output=True, text=True, timeout=300)
    assert refused.returncode == 2 and refused.stdout.startswith("refused"), refused.stdout + refused.stderr


# ---------------------------------------------------------------- agreement with the oracle

def same_subspace(a: np.ndarray, b: np.ndarray, atol=1e-8) -> bool:
    return a.shape == b.shape and np.allclose(a @ a.T, b @ b.T, atol=atol)


@pytest.mark.parametrize("seed", range(60))
def test_cohomology_agrees_on_random_sheaves(seed):
    rng = np.random.default_rng(1000 + seed)
    F = random_sheaf(rng, n_nodes=int(rng.integers(1, 7)), n_edges=int(rng.integers(0, 10)))
    want, got = sc.cohomology(F), sn.cohomology(F)
    assert (got.dim_c0, got.dim_c1, got.dim_h0, got.dim_h1) == (want.dim_c0, want.dim_c1, want.dim_h0, want.dim_h1)
    assert got.sigma_max == pytest.approx(want.sigma_max, rel=1e-10, abs=1e-12)
    assert np.allclose(got.h0_basis.T @ got.h0_basis, np.eye(got.dim_h0), atol=1e-10)
    assert same_subspace(got.h0_basis, want.h0_basis)
    assert got.method in ("jacobi", "trivial") and (got.method == "trivial") == (want.method == "trivial")
    for mine, theirs in ((got.kept_min, want.kept_min), (got.dropped_max, want.dropped_max)):
        assert (mine is None) == (theirs is None)
        if mine is not None:
            assert mine == pytest.approx(theirs, rel=1e-6, abs=1e-12)


@pytest.mark.parametrize("seed", range(30))
def test_structured_sheaves_agree(seed):
    rng = np.random.default_rng(2000 + seed)
    nodes, edges = random_graph(rng, int(rng.integers(2, 8)), int(rng.integers(1, 12)), connected=bool(seed % 2))
    k = int(rng.integers(1, 4))
    for F in (constant_sheaf(nodes, edges, k), flat_sheaf(rng, nodes, edges, k)[0]):
        want, got = sc.cohomology(F), sn.cohomology(F)
        assert (got.dim_h0, got.dim_h1) == (want.dim_h0, want.dim_h1)
        assert same_subspace(got.h0_basis, want.h0_basis)


def test_the_tolerance_rule_is_the_same_rule():
    eps = 1e-12
    nodes, edges = ("a", "b", "c"), (("a", "b"), ("b", "c"), ("c", "a"))
    F = sc.VectorSheaf(sc.Base(nodes, edges), {v: 2 for v in nodes}, (2, 2, 2),
                       ("identity",) * 3, ("identity", "identity", (1 + eps) * np.eye(2)))
    loose, strict = sn.cohomology(F), sn.cohomology(F, tol=1e-15)
    assert (loose.dim_h0, loose.dim_h1, strict.dim_h0, strict.dim_h1) == (2, 2, 0, 0)
    assert 0 < loose.dropped_max < 1e-9 < loose.kept_min
    assert strict.dropped_max is None
    assert loose.dropped_max == pytest.approx(sc.cohomology(F).dropped_max, rel=1e-3)


@pytest.mark.parametrize("seed", range(30))
def test_gluing_agrees(seed):
    rng = np.random.default_rng(3000 + seed)
    F = random_sheaf(rng, n_nodes=int(rng.integers(1, 6)), n_edges=int(rng.integers(0, 8)))
    local = {v: rng.standard_normal(F.node_dim[v]) for v in F.base.nodes}
    want, got = sc.glue(F, local), sn.glue(F, local)
    assert got.residuals == pytest.approx(want.residuals, abs=1e-10)
    assert (got.glued, got.residual_edges) == (want.glued, want.residual_edges)
    assert got.distance_squared == pytest.approx(want.distance_squared, abs=1e-9)
    for v in F.base.nodes:
        assert np.allclose(got.nearest[v], want.nearest[v], atol=1e-8)
    for loose in (0.5, 5.0):
        assert sn.glue(F, local, glue_tol=loose).residual_edges == sc.glue(F, local, glue_tol=loose).residual_edges


@pytest.mark.parametrize("seed", range(30))
def test_transport_and_holonomy_agree(seed):
    rng = np.random.default_rng(4000 + seed)
    nodes = ("a", "b", "c", "d")
    edges = (("a", "b"), ("b", "c"), ("a", "c"), ("c", "d"), ("d", "a"))
    faces = ((((0, 1), (1, 1)), ((2, 1),)), (((2, 1), (3, 1)), ((4, -1),)))
    node_dim = {v: int(rng.integers(1, 4)) for v in nodes}
    edge_dim = tuple(int(rng.integers(1, 4)) for _ in edges)
    F = sc.VectorSheaf(sc.Base(nodes, edges, faces), node_dim, edge_dim,
                       tuple(rng.standard_normal((m, node_dim[t])) for m, (t, _) in zip(edge_dim, edges)),
                       tuple(rng.standard_normal((m, node_dim[h])) for m, (_, h) in zip(edge_dim, edges)))
    for route in (((0, 1),), ((0, -1),), ((0, 1), (1, 1), (3, 1), (4, 1)), ((4, -1), (3, -1), (2, -1))):
        assert np.allclose(sn.transport(F, route), sc.transport(F, route), atol=1e-8)
    for i in range(2):
        assert np.allclose(sn.holonomy(F, i), sc.holonomy(F, i), atol=1e-8)
    assert np.allclose(sn.holonomy(F, faces[0]), sc.holonomy(F, 0), atol=1e-8)


def test_transport_through_a_map_that_loses_rank_uses_the_same_pseudo_inverse():
    base = sc.Base(("a", "b"), (("a", "b"),))
    F = sc.VectorSheaf(base, {"a": 2, "b": 2}, (2,), ([[1, 2], [3, 4]],), ([[1, 1], [1, 1]],))
    assert np.allclose(sn.transport(F, ((0, 1),)), sc.transport(F, ((0, 1),)), atol=1e-10)
    zero = sc.VectorSheaf(base, {"a": 2, "b": 3}, (2,), ([[1, 2], [3, 4]],), ([[0, 0, 0], [0, 0, 0]],))
    assert sn.transport(zero, ((0, 1),)).shape == (3, 2) and not sn.transport(zero, ((0, 1),)).any()


@pytest.mark.parametrize("seed", range(80))
def test_set_sheaves_agree(seed):
    rng = np.random.default_rng(5000 + seed)
    F = random_set_sheaf(rng, n_nodes=int(rng.integers(1, 6)), n_edges=int(rng.integers(0, 8)),
                         connected=bool(seed % 2))
    assert sn.count_sections(F) == sc.count_sections(F)
    if all(F.node_stalk[v] for v in F.base.nodes):
        for _ in range(5):
            local = {v: F.node_stalk[v][int(rng.integers(0, len(F.node_stalk[v])))] for v in F.base.nodes}
            assert sn.glue_sets(F, local) == sc.glue_sets(F, local)


def test_both_refuse_at_the_same_step_budget():
    bit = ("0", "1")
    nodes = tuple(f"n{i}" for i in range(12))
    edges = tuple((nodes[i], nodes[i + 1]) for i in range(11))
    same = {"0": "0", "1": "1"}
    F = sc.SetSheaf(sc.Base(nodes, edges), {v: bit for v in nodes}, tuple(bit for _ in edges),
                    tuple(same for _ in edges), tuple(same for _ in edges))
    lowest = None
    for budget in range(1, 200):
        try:
            assert sc.count_sections(F, budget_steps=budget) == 2
            lowest = budget
            break
        except sc.SheafBudgetError:
            with pytest.raises(sc.SheafBudgetError):
                sn.count_sections(F, budget_steps=budget)
    assert lowest and sn.count_sections(F, budget_steps=lowest) == 2


def test_budgets_refuse_with_the_oracles_exception():
    rng = np.random.default_rng(6)
    nodes, edges = random_graph(rng, 8, 20)
    F, _ = flat_sheaf(rng, nodes, edges, 4)
    local = {v: [0.0] * 4 for v in nodes}
    for call in (lambda **kw: sn.cohomology(F, **kw), lambda **kw: sn.glue(F, local, **kw)):
        with pytest.raises(sc.SheafBudgetError):
            call(budget_bytes=1000)
        with pytest.raises(sc.SheafBudgetError):
            call(budget_work=1000)
    with pytest.raises(sc.SheafBudgetError):
        sn.transport(F, ((0, 1),), budget_work=3)
    with pytest.raises(sc.SheafBudgetError):
        sn.transport(F, ((0, 1),), budget_bytes=8)
    for bad in (-1, 1.5, True, 2 ** 63):
        with pytest.raises(sc.SheafError):
            sn.cohomology(F, budget_work=bad)
    for bad in (-1e-9, 1.0, float("nan"), "x", True):
        with pytest.raises(sc.SheafError):
            sn.cohomology(F, tol=bad)
    with pytest.raises(sc.SheafError):
        sn.glue(F, local, glue_tol=-1)
    with pytest.raises(sc.SheafError):
        sn.glue(F, {"v0": [0.0] * 4})
    with pytest.raises(sc.SheafError):
        sn.cohomology(random_set_sheaf(rng))
    with pytest.raises(sc.SheafError):
        sn.count_sections(F)


def test_a_neighbourhood_sized_sheaf_is_answered_and_agrees():
    rng = np.random.default_rng(8)
    nodes, edges = random_graph(rng, 24, 60)
    F, _ = flat_sheaf(rng, nodes, edges, 6)          # 144 unknowns, 360 equations
    want, got = sc.cohomology(F), sn.cohomology(F)
    assert (got.dim_h0, got.dim_h1) == (want.dim_h0, want.dim_h1) == (6, 6 * (60 - 24 + 1))
    assert same_subspace(got.h0_basis, want.h0_basis, atol=1e-7)


def test_many_threads_get_the_same_answers():
    rng = np.random.default_rng(9)
    sheaves = [random_sheaf(rng) for _ in range(12)]
    want = [(H.dim_h0, H.dim_h1) for H in map(sc.cohomology, sheaves)]
    got, errors = [None] * 8, []

    def run(i):
        try:
            got[i] = [(H.dim_h0, H.dim_h1) for H in map(sn.cohomology, sheaves)]
        except Exception as exc:  # noqa: BLE001 - the test reports whatever a thread hit
            errors.append(exc)
    threads = [threading.Thread(target=run, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and all(g == want for g in got)


# ---------------------------------------------------------------- arguments no caller should send

I32, I64, F64 = ctypes.c_int32, ctypes.c_int64, ctypes.c_double


def raw_cohomology(n_nodes=2, node_dim=(1, 1), n_edges=1, tail=(0,), head=(1,), edge_dim=(1,), maps=(1.0, 1.0),
                   maps_len=None, tol=1e-9, budget_bytes=1 << 20, budget_work=1 << 30, null=()):
    lib = sn._kernel()
    arrays = {"node_dim": (I32 * max(len(node_dim), 1))(*node_dim), "tail": (I32 * max(len(tail), 1))(*tail),
              "head": (I32 * max(len(head), 1))(*head), "edge_dim": (I32 * max(len(edge_dim), 1))(*edge_dim),
              "maps": (F64 * max(len(maps), 1))(*maps), "dims": (I64 * 4)(), "stats": (F64 * 3)()}
    for name in null:
        arrays[name] = None
    return lib.sheaf_cohomology(n_nodes, arrays["node_dim"], n_edges, arrays["tail"], arrays["head"],
                                arrays["edge_dim"], arrays["maps"], len(maps) if maps_len is None else maps_len,
                                tol, budget_bytes, budget_work, arrays["dims"], arrays["stats"], None, 0)


def test_the_raw_call_works_before_it_is_abused():
    assert raw_cohomology() == 0
    assert sn._kernel().sheaf_abi_version() == sn.ABI_VERSION


@pytest.mark.parametrize("abuse", [
    {"n_nodes": -1}, {"n_edges": -1}, {"maps_len": -1}, {"maps_len": 1}, {"maps_len": 3},
    {"node_dim": (1, -1)}, {"edge_dim": (-1,), "maps": (), "maps_len": 0},
    {"tail": (2,)}, {"tail": (-1,)}, {"head": (2,)}, {"head": (-5,)},
    {"maps": (1.0, float("nan"))}, {"maps": (float("inf"), 1.0)},
    {"tol": -1.0}, {"tol": 1.0}, {"tol": float("nan")},
    {"budget_bytes": -1}, {"budget_work": -1},
    {"null": ("node_dim",)}, {"null": ("tail",)}, {"null": ("head",)}, {"null": ("edge_dim",)},
    {"null": ("maps",)}, {"null": ("dims",)}, {"null": ("stats",)},
    {"node_dim": (2 ** 31 - 1, 2 ** 31 - 1), "edge_dim": (2 ** 31 - 1,), "maps_len": 2 ** 62},
])
def test_bad_arguments_are_refused_not_followed(abuse):
    assert raw_cohomology(**abuse) == -1


def test_a_node_number_past_the_declared_count_is_refused_even_when_memory_there_looks_valid():
    """The arrays are longer than the kernel is told, and what lies past the end would make a consistent sheaf.
    A kernel that skipped the range check would read it and answer; this one must refuse."""
    lib = sn._kernel()
    padded = (I32 * 4)(1, 1, 1, 1)                      # node_dim[-1] and node_dim[2] both read as 1
    inside = ctypes.cast(ctypes.byref(padded, ctypes.sizeof(I32)), ctypes.POINTER(I32))
    dims, stats, maps = (I64 * 4)(), (F64 * 3)(), (F64 * 2)(1.0, 1.0)

    def call(tail, head):
        return lib.sheaf_cohomology(2, inside, 1, (I32 * 1)(tail), (I32 * 1)(head), (I32 * 1)(1), maps, 2,
                                    1e-9, 1 << 20, 1 << 30, dims, stats, None, 0)
    assert call(0, 1) == 0
    for tail, head in ((2, 1), (-1, 1), (0, 2), (0, -1)):
        assert call(tail, head) == -1, (tail, head)


def test_the_kernel_checks_a_route_itself():
    lib = sn._kernel()
    eye = (1.0, 0.0, 0.0, 1.0)
    sheaf = [3, (I32 * 3)(2, 2, 2), 2, (I32 * 2)(0, 1), (I32 * 2)(1, 2), (I32 * 2)(2, 2), (F64 * 16)(*(eye * 4)), 16]
    out, shape = (F64 * 4)(), (I64 * 2)()

    def call(edges, dirs, n=None, cap=4, edge_ptr=True, shape_ptr=True):
        return lib.sheaf_transport(*sheaf, len(edges) if n is None else n,
                                   (I32 * max(len(edges), 1))(*edges) if edge_ptr else None,
                                   (I32 * max(len(dirs), 1))(*dirs), 1 << 20, 1 << 30, out, cap,
                                   shape if shape_ptr else None)
    assert call((0, 1), (1, 1)) == 0 and list(out) == list(eye) and list(shape) == [2, 2]
    assert call((1, 0), (-1, -1)) == 0
    for edges, dirs in (((0, 0), (1, 1)), ((0, 1), (1, -1)), ((1, 0), (1, 1)), ((2,), (1,)), ((-1,), (1,)),
                        ((0,), (0,)), ((0,), (2,))):
        assert call(edges, dirs) == -1, (edges, dirs)
    assert call((), (), n=0) == -1 and call((0,), (1,), n=-1) == -1
    assert call((0,), (1,), cap=3) == -1
    assert call((0,), (1,), edge_ptr=False) == -1 and call((0,), (1,), shape_ptr=False) == -1


def test_budget_codes():
    assert raw_cohomology(budget_bytes=8) == -2
    assert raw_cohomology(node_dim=(3, 3), edge_dim=(3,), maps=tuple(float(i % 7 + 1) for i in range(18)),
                          budget_work=5) == -4


def test_set_calls_refuse_maps_that_point_outside_a_stalk():
    lib = sn._kernel()
    out = I64()
    args = [2, (I32 * 2)(2, 2), 1, (I32 * 1)(0), (I32 * 1)(1), (I32 * 1)(2)]
    assert lib.sheaf_count_sections(*args, (I32 * 4)(0, 1, 0, 1), 4, 1000, ctypes.byref(out)) == 0 and out.value == 2
    for bad in ((0, 2, 0, 1), (0, 1, -1, 1)):
        assert lib.sheaf_count_sections(*args, (I32 * 4)(*bad), 4, 1000, ctypes.byref(out)) == -1
        assert lib.sheaf_glue_sets(*args, (I32 * 4)(*bad), 4, (I32 * 2)(0, 0), (I32 * 1)()) == -1
    assert lib.sheaf_count_sections(*args, (I32 * 4)(0, 1, 0, 1), 3, 1000, ctypes.byref(out)) == -1
    assert lib.sheaf_count_sections(*args, (I32 * 4)(0, 1, 0, 1), 4, 1000, None) == -1
    assert lib.sheaf_glue_sets(*args, (I32 * 4)(0, 1, 0, 1), 4, (I32 * 2)(0, 2), (I32 * 1)()) == -1
    assert lib.sheaf_count_sections(*args, (I32 * 4)(0, 1, 0, 1), 4, 2, ctypes.byref(out)) == -4


# ---------------------------------------------------------------- under the sanitizers

SANITIZED = textwrap.dedent("""
    import sys
    sys.path[:0] = [{engram!r}]
    import numpy as np
    import sheaf_core as sc, sheaf_native as sn
    import tests.test_sheaf_core as helpers, tests.test_sheaf_native as native
    for path in helpers.KNOWN:
        assert sc.check_file(path, compute=sn.answers)["status"] == "ok", path
    rng = np.random.default_rng(77)
    for _ in range(40):
        F = helpers.random_sheaf(rng)
        assert sn.cohomology(F).dim_h0 == sc.cohomology(F).dim_h0
        sn.glue(F, {{v: rng.standard_normal(F.node_dim[v]) for v in F.base.nodes}})
        S = helpers.random_set_sheaf(rng)
        assert sn.count_sections(S) == sc.count_sections(S)
    for abuse in native.test_bad_arguments_are_refused_not_followed.pytestmark[0].args[1]:
        assert native.raw_cohomology(**abuse) == -1, abuse
    native.test_set_calls_refuse_maps_that_point_outside_a_stalk()
    native.test_transport_and_holonomy_agree(3)
    print("sanitized ok")
""")


def run_sanitized(so: Path, extra_env: dict) -> subprocess.CompletedProcess:
    so.chmod(0o700)
    env = {**os.environ, "SHEAF_TEST_SO": str(so), **extra_env}
    return subprocess.run([sys.executable, "-c", SANITIZED.format(engram=str(ENGRAM))], capture_output=True,
                          text=True, env=env, timeout=600)


def test_the_kernel_is_clean_with_undefined_behaviour_traps_and_checked_containers(tmp_path):
    """Needs no sanitizer runtime, so it runs everywhere: undefined behaviour traps, and std::vector checks its bounds."""
    compiler = next(c for c in sn.COMPILERS if os.access(c, os.X_OK))
    so = tmp_path / "sheaf-trapping.so"
    subprocess.run([compiler, "-std=c++20", "-O1", "-g", "-fPIC", "-shared", "-fsanitize=undefined",
                    "-fsanitize-trap=undefined", "-D_GLIBCXX_ASSERTIONS", str(sn.SOURCE), "-o", str(so)],
                   check=True, capture_output=True)
    done = run_sanitized(so, {})
    assert done.returncode == 0 and "sanitized ok" in done.stdout, done.stdout[-2000:] + done.stderr[-4000:]


def test_the_kernel_is_clean_under_address_and_undefined_behaviour_sanitizers(tmp_path):
    compiler = next(c for c in sn.COMPILERS if os.access(c, os.X_OK))
    flags = ["-std=c++20", "-O1", "-g", "-fPIC", "-shared", "-fsanitize=address,undefined",
             "-fno-sanitize-recover=undefined", "-fno-omit-frame-pointer"]
    probe = tmp_path / "probe.cpp"
    probe.write_text("int probe() { return 0; }\n")
    if subprocess.run([compiler, *flags, str(probe), "-o", str(tmp_path / "probe.so")],
                      capture_output=True).returncode != 0:
        pytest.skip("this machine has no AddressSanitizer runtime to link against")
    so = tmp_path / "sheaf-sanitized.so"
    subprocess.run([compiler, *flags, str(sn.SOURCE), "-o", str(so)], check=True, capture_output=True)
    linked = subprocess.run(["ldd", str(so)], capture_output=True, text=True).stdout
    def linked_path(name):
        return next((line.split("=>")[1].split()[0] for line in linked.splitlines()
                     if name in line and "=>" in line and line.split("=>")[1].strip().startswith("/")), None)
    runtime, cxx = linked_path("libasan"), linked_path("libstdc++")
    if not runtime or not cxx:
        pytest.skip("could not find the AddressSanitizer and C++ runtimes the build linked")
    # Python doesn't link the C++ runtime, so it has to be loaded with the sanitizer, before the kernel is.
    # Otherwise the sanitizer starts without a real __cxa_throw to wrap, and stops at the kernel's first throw.
    done = run_sanitized(so, {"LD_PRELOAD": f"{runtime} {cxx}", "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=1",
                              "UBSAN_OPTIONS": "halt_on_error=1"})
    assert done.returncode == 0 and "sanitized ok" in done.stdout, done.stdout[-2000:] + done.stderr[-4000:]


def test_good_doc_through_the_kernel():
    out = sn.answers(good_doc())
    assert (out["dim_h0"], out["dim_h1"], out["glued"], out["method"]) == (2, 0, True, "jacobi")
