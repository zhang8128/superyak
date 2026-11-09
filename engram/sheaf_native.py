"""The native sheaf core (`sheaf_kernel.cpp`, C++20) behind the same functions as `sheaf_core`, its oracle.

The kernel is compiled on first use with the system C++ compiler and kept in this user's private cache. It is
stateless, so calls from several threads need no lock, and ctypes lets the GIL go during each call. A refusal by
the kernel becomes the same exception `sheaf_core` raises: `SheafBudgetError` for a budget, `SheafError` otherwise.
"""
from __future__ import annotations

import ctypes
import hashlib
import math
import os
import stat
import subprocess
import sys
import threading
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

import sheaf_core as sc

SOURCE = Path(__file__).with_name("sheaf_kernel.cpp")
if not SOURCE.exists():  # an installed wheel keeps it with the other shared files
    SOURCE = Path(sys.prefix) / "share" / "engram" / "sheaf_kernel.cpp"
ABI_VERSION = 1
FLAGS = ("-std=c++20", "-O2", "-fPIC", "-shared", "-fstack-protector-strong", "-D_FORTIFY_SOURCE=2", "-Wall")
LINUX_FLAGS = ("-Wl,-z,relro", "-Wl,-z,now", "-Wl,-z,noexecstack")
COMPILERS = ("/usr/bin/c++", "/usr/bin/g++", "/usr/bin/clang++")  # never one found on PATH
DEFAULT_BUDGET_WORK = 20_000_000_000
BUDGET_CODES = (-2, -4)
ERRORS = {-1: "the kernel refused its arguments", -2: "over the byte budget. Take a neighbourhood.",
          -3: "out of memory", -4: "more work than one call may do. Take a neighbourhood, or a smaller sheaf."}

_i32, _i64, _f64 = ctypes.c_int32, ctypes.c_int64, ctypes.c_double
_pi32, _pi64, _pf64 = ctypes.POINTER(_i32), ctypes.POINTER(_i64), ctypes.POINTER(_f64)


def _private(path: Path, kind: str) -> None:
    """Ours alone: owned by this user, and nobody else may write it. A shared or loose cache could hand us someone's code."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise RuntimeError(f"sheaf_native won't use {path}: the {kind} must be this user's own, and writable by nobody else")


def _built() -> Path:
    source = SOURCE.read_bytes()
    compiler = next((c for c in COMPILERS if os.access(c, os.X_OK)), None)
    if compiler is None:
        raise RuntimeError("sheaf_native needs a C++ compiler at /usr/bin/c++, /usr/bin/g++ or /usr/bin/clang++")
    flags = FLAGS + (LINUX_FLAGS if sys.platform.startswith("linux") else ())
    tag = hashlib.blake2b(source + compiler.encode() + " ".join(flags).encode(), digest_size=12).hexdigest()
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "superyak" / "sheaf"
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private(cache, "cache folder")
    out = cache / f"sheaf-{tag}.so"
    if not out.exists():
        partial = cache / f".{out.name}.{os.getpid()}.{threading.get_ident()}"
        try:
            subprocess.run([compiler, *flags, str(SOURCE), "-o", str(partial)], check=True, capture_output=True)
            partial.chmod(0o700)
            partial.replace(out)
        finally:
            partial.unlink(missing_ok=True)
    _private(out, "library")
    return out


def _load() -> ctypes.CDLL:
    chosen = os.environ.get("SHEAF_TEST_SO")  # tests only, such as a sanitizer build; never set it for a service
    path = Path(chosen) if chosen else _built()
    if chosen:
        _private(path, "library")
    lib = ctypes.CDLL(str(path))
    lib.sheaf_abi_version.restype = _i32
    if lib.sheaf_abi_version() != ABI_VERSION:
        raise RuntimeError(f"{path} speaks sheaf ABI {lib.sheaf_abi_version()}, and this module speaks {ABI_VERSION}")
    vector = [_i32, _pi32, _i32, _pi32, _pi32, _pi32, _pf64, _i64]
    sets = [_i32, _pi32, _i32, _pi32, _pi32, _pi32, _pi32, _i64]
    for name, args in (
        ("sheaf_cohomology", vector + [_f64, _i64, _i64, _pi64, _pf64, _pf64, _i64]),
        ("sheaf_glue", vector + [_pf64, _i64, _f64, _i64, _i64, _pf64, _pf64, _pf64]),
        ("sheaf_transport", vector + [_i32, _pi32, _pi32, _i64, _i64, _pf64, _i64, _pi64]),
        ("sheaf_glue_sets", sets + [_pi32, _pi32]),
        ("sheaf_count_sections", sets + [_i64, _pi64]),
    ):
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, _i32
    return lib


_lib, _lib_lock = None, threading.Lock()


def _kernel() -> ctypes.CDLL:
    global _lib
    with _lib_lock:
        if _lib is None:
            _lib = _load()
        return _lib


def _checked(code: int) -> None:
    if code == 0:
        return
    message = ERRORS.get(code, f"the kernel returned {code}")
    raise (sc.SheafBudgetError if code in BUDGET_CODES else sc.SheafError)(message)


def _budget(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2 ** 63:
        raise sc.SheafError(f"{what} must be a whole number, 0 or more")
    return value


def _ints(values) -> ctypes.Array:
    return (_i32 * max(len(values), 1))(*values)


def _doubles(array: np.ndarray):
    array = np.ascontiguousarray(array, dtype=np.float64).reshape(-1)
    if array.size == 0:
        array = np.zeros(1)
    return array, array.ctypes.data_as(_pf64)


def _vector_args(F: sc.VectorSheaf):
    if not isinstance(F, sc.VectorSheaf):
        raise sc.SheafError("expected a VectorSheaf")
    number = {v: i for i, v in enumerate(F.base.nodes)}
    parts = [m.reshape(-1) for pair in zip(F.tail_maps, F.head_maps) for m in pair]
    flat = np.concatenate(parts) if parts else np.zeros(0)
    keep, maps = _doubles(flat)
    args = [len(F.base.nodes), _ints([F.node_dim[v] for v in F.base.nodes]), len(F.base.edges),
            _ints([number[t] for t, _ in F.base.edges]), _ints([number[h] for _, h in F.base.edges]),
            _ints(list(F.edge_dim)), maps, int(flat.size)]
    return args, keep


def _set_args(F: sc.SetSheaf):
    if not isinstance(F, sc.SetSheaf):
        raise sc.SheafError("expected a SetSheaf")
    number = {v: i for i, v in enumerate(F.base.nodes)}
    flat: list[int] = []
    for e, (tail, head) in enumerate(F.base.edges):
        at = {x: i for i, x in enumerate(F.edge_stalk[e])}
        flat += [at[F.tail_maps[e][x]] for x in F.node_stalk[tail]]
        flat += [at[F.head_maps[e][x]] for x in F.node_stalk[head]]
    return [len(F.base.nodes), _ints([len(F.node_stalk[v]) for v in F.base.nodes]), len(F.base.edges),
            _ints([number[t] for t, _ in F.base.edges]), _ints([number[h] for _, h in F.base.edges]),
            _ints([len(s) for s in F.edge_stalk]), _ints(flat), len(flat)]


def _ratio(value: float):
    return None if math.isnan(value) else float(value)


def cohomology(F: sc.VectorSheaf, *, tol: float = sc.DEFAULT_TOL, budget_bytes: int = sc.DEFAULT_BUDGET_BYTES,
               budget_work: int = DEFAULT_BUDGET_WORK) -> sc.Cohomology:
    if isinstance(tol, bool) or not isinstance(tol, (int, float)) or not (math.isfinite(tol) and 0 <= tol < 1):
        raise sc.SheafError("tol must be a number from 0 up to, not including, 1")
    args, keep = _vector_args(F)
    n0 = F.dim_c0
    if 8 * n0 * n0 > _budget(budget_bytes, "budget_bytes"):
        raise sc.SheafBudgetError(ERRORS[-2])
    basis = np.zeros(max(n0 * n0, 1))
    dims, stats = (_i64 * 4)(), (_f64 * 3)()
    _checked(_kernel().sheaf_cohomology(*args, float(tol), budget_bytes, _budget(budget_work, "budget_work"),
                                        dims, stats, basis.ctypes.data_as(_pf64), n0 * n0))
    h0 = int(dims[2])
    trivial = n0 == 0 or F.dim_c1 == 0
    return sc.Cohomology(int(dims[0]), int(dims[1]), h0, int(dims[3]), basis[:n0 * h0].reshape(n0, h0).copy(),
                         tol, tol, "trivial" if trivial else "jacobi", float(stats[0]),
                         _ratio(stats[1]), _ratio(stats[2]))


def glue(F: sc.VectorSheaf, local: Mapping[str, Sequence[float]], *, tol: float = sc.DEFAULT_TOL,
         glue_tol: float = sc.DEFAULT_GLUE_TOL, budget_bytes: int = sc.DEFAULT_BUDGET_BYTES,
         budget_work: int = DEFAULT_BUDGET_WORK) -> sc.Glued:
    if isinstance(glue_tol, bool) or not isinstance(glue_tol, (int, float)) or not (
            math.isfinite(glue_tol) and glue_tol >= 0):
        raise sc.SheafError("glue_tol must be a finite number, 0 or more")
    if isinstance(tol, bool) or not isinstance(tol, (int, float)):
        raise sc.SheafError("tol must be a number from 0 up to, not including, 1")
    args, keep = _vector_args(F)
    x = sc._local_vector(F, local)
    keep_x, px = _doubles(x)
    n0, n_edges = F.dim_c0, len(F.base.edges)
    residuals, nearest, dist = np.zeros(max(n_edges, 1)), np.zeros(max(n0, 1)), _f64()
    _checked(_kernel().sheaf_glue(*args, px, n0, float(tol), _budget(budget_bytes, "budget_bytes"),
                                  _budget(budget_work, "budget_work"), residuals.ctypes.data_as(_pf64),
                                  nearest.ctypes.data_as(_pf64), ctypes.byref(dist)))
    lengths = tuple(float(r) for r in residuals[:n_edges])
    bad = tuple(e for e, length in enumerate(lengths) if length > glue_tol)
    off = F.offsets()
    return sc.Glued(not bad, lengths, bad, {v: nearest[off[v]:off[v] + F.node_dim[v]].copy() for v in F.base.nodes},
                    float(dist.value), glue_tol)


def transport(F: sc.VectorSheaf, route, *, budget_bytes: int = sc.DEFAULT_BUDGET_BYTES,
              budget_work: int = DEFAULT_BUDGET_WORK) -> np.ndarray:
    start, end = F.base.route_ends(route)   # checks the route as the oracle does
    args, keep = _vector_args(F)
    rows, cols = F.node_dim[end], F.node_dim[start]
    out, shape = np.zeros(max(rows * cols, 1)), (_i64 * 2)()
    _checked(_kernel().sheaf_transport(*args, len(route), _ints([e for e, _ in route]), _ints([d for _, d in route]),
                                       _budget(budget_bytes, "budget_bytes"), _budget(budget_work, "budget_work"),
                                       out.ctypes.data_as(_pf64), rows * cols, shape))
    if (int(shape[0]), int(shape[1])) != (rows, cols):
        raise sc.SheafError("the kernel and this module disagree about a route's ends")
    return out[:rows * cols].reshape(rows, cols).copy()


def holonomy(F: sc.VectorSheaf, face, **budgets) -> np.ndarray:
    if isinstance(face, int) and not isinstance(face, bool):
        if not 0 <= face < len(F.base.faces):
            raise sc.SheafError(f"face {face} is not in the base")
        a, b = F.base.faces[face]
    else:
        a, b = face
        if F.base.route_ends(a) != F.base.route_ends(b):
            raise sc.SheafError("a face's two routes must share their start and their end")
    return transport(F, a, **budgets) - transport(F, b, **budgets)


def glue_sets(F: sc.SetSheaf, local: Mapping[str, str]) -> sc.GluedSets:
    args = _set_args(F)
    if set(local) != set(F.base.nodes):
        raise sc.SheafError("local data must pick an element for every node and nothing else")
    picks = []
    for v in F.base.nodes:
        if local[v] not in F.node_stalk[v]:
            raise sc.SheafError(f"local data at {v!r} is not in its stalk")
        picks.append(F.node_stalk[v].index(local[v]))
    bad = _ints([0] * len(F.base.edges))
    _checked(_kernel().sheaf_glue_sets(*args, _ints(picks), bad))
    edges = tuple(e for e in range(len(F.base.edges)) if bad[e])
    return sc.GluedSets(not edges, edges)


def count_sections(F: sc.SetSheaf, *, budget_steps: int = sc.DEFAULT_BUDGET_STEPS) -> int:
    out = _i64()
    _checked(_kernel().sheaf_count_sections(*_set_args(F), _budget(budget_steps, "budget_steps"), ctypes.byref(out)))
    return int(out.value)


def answers(doc, *, budget_bytes: int = sc.DEFAULT_BUDGET_BYTES, budget_steps: int = sc.DEFAULT_BUDGET_STEPS,
            budget_work: int = DEFAULT_BUDGET_WORK) -> dict:
    """What `sheaf_core.answers` returns, computed by the kernel."""
    sheaf, rest = sc.load(doc)
    out: dict = {}
    if isinstance(sheaf, sc.VectorSheaf):
        tol, glue_tol = rest.get("tol", sc.DEFAULT_TOL), rest.get("glue_tol", sc.DEFAULT_GLUE_TOL)
        H = cohomology(sheaf, tol=tol, budget_bytes=budget_bytes, budget_work=budget_work)
        out.update(dim_h0=H.dim_h0, dim_h1=H.dim_h1, tol_used=H.tol_used, method=H.method,
                   kept_min=H.kept_min, dropped_max=H.dropped_max)
        if "local" in rest:
            g = glue(sheaf, rest["local"], tol=tol, glue_tol=glue_tol, budget_bytes=budget_bytes,
                     budget_work=budget_work)
            out.update(glued=g.glued, residual_edges=list(g.residual_edges), residuals=list(g.residuals),
                       distance_squared=g.distance_squared)
        if sheaf.base.faces:
            out["holonomy_frobenius"] = [
                float(np.linalg.norm(holonomy(sheaf, i, budget_bytes=budget_bytes, budget_work=budget_work)))
                for i in range(len(sheaf.base.faces))]
    else:
        out["sections"] = count_sections(sheaf, budget_steps=budget_steps)
        if "local" in rest:
            g = glue_sets(sheaf, rest["local"])
            out.update(glued=g.glued, residual_edges=list(g.residual_edges))
    return out
