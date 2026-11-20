"""The sheaf kernel (`sheaf_kernel.c`) from Python: a cellular sheaf on a graph, its Laplacian, its global sections and
what fails to glue, and the two measures Engram takes with one (a summary's cohesion, and several stores' agreement on
a topic). The head of the C file says what each thing is.

The kernel keeps no state of its own, and every call lets the GIL go. A `Sheaf` holds its own lock, so threads may share
one. Arrays go in as float64 and come back as numpy arrays; nothing here reads a store or writes anywhere.

`sheaf.py` and `lighthouse_sheaf.py` use this when it loads and their numpy code when it does not. The numpy code is the
oracle the kernel is tested against (tests/test_sheaf_kernel.py)."""
import ctypes
import os
import threading
from pathlib import Path

import numpy as np

import native_build

SOURCE = native_build.source('sheaf_kernel.c')
ABI = 1
MAX_N, MAX_COLS, MAX_CELLS, MAX_VERTICES, MAX_STALK = 2048, 16384, 1 << 24, 4096, 256
ERRORS = {-6: 'out of memory', -7: 'bad argument: a value that is not finite, is beyond 1e150, or is out of range',
          -8: "the decomposition didn't settle", -9: 'too large for the kernel'}
_double_p, _int_p = ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_int32)


class SheafKernelError(ValueError):
    def __init__(self, code):
        super().__init__(ERRORS.get(code, f'error {code}'))
        self.code = code


class _Glue(ctypes.Structure):
    _fields_ = [('k', ctypes.c_int32), ('kernel_dim', ctypes.c_int32), ('glued_dim', ctypes.c_int32),
                ('consensus_unweighted', ctypes.c_int32), ('all_edges_zero', ctypes.c_int32),
                ('energy', ctypes.c_double), ('energy_unweighted', ctypes.c_double), ('harmonic', ctypes.c_double)]


def _load():
    chosen = os.environ.get('SHEAF_TEST_SO')  # tests only, such as a sanitizer build; never set it for a service
    path = Path(chosen) if chosen else native_build.built(SOURCE, 'sheaf', libs=('-lm',))
    if chosen:
        native_build.private(path, 'library', 'sheaf')
    lib = ctypes.CDLL(str(path))  # releases the GIL during each call
    i32, f64, ptr = ctypes.c_int32, ctypes.c_double, ctypes.c_void_p
    lib.sheaf_abi.restype = i32
    if lib.sheaf_abi() != ABI:
        raise RuntimeError(f'the sheaf kernel at {path} speaks ABI {lib.sheaf_abi()}, and this module speaks {ABI}')
    for name, args in (
            ('sheaf_sym_eig', [i32, _double_p, _double_p, _double_p]),
            ('sheaf_basis', [i32, i32, _double_p, f64, i32, i32, _double_p, _double_p, _int_p]),
            ('sheaf_cohesion', [i32, i32, _double_p, f64, i32, _double_p, _double_p, _double_p, _int_p, i32, _int_p,
                                _int_p, _double_p, _int_p]),
            ('sheaf_add_edge', [ptr, i32, i32, i32, _double_p, _double_p, f64]),
            ('sheaf_dims', [ptr, _int_p, _int_p, _int_p]),
            ('sheaf_coboundary', [ptr, _double_p, _double_p]),
            ('sheaf_energy', [ptr, _double_p, _double_p, _double_p]),
            ('sheaf_laplacian', [ptr, _double_p]),
            ('sheaf_sections', [ptr, f64, _int_p, _int_p, _double_p, _double_p, _double_p]),
            ('sheaf_glue', [i32, i32, _int_p, _double_p, _double_p, _double_p, i32, f64, i32, ctypes.POINTER(_Glue),
                            _double_p, _double_p, _double_p, _int_p, _double_p, _double_p, _double_p, _double_p])):
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, i32
    lib.sheaf_new.argtypes, lib.sheaf_new.restype = [i32, _int_p], ptr
    lib.sheaf_free.argtypes, lib.sheaf_free.restype = [ptr], None
    return lib


_lib, _why_not, _lib_lock = None, None, threading.Lock()


def _kernel():
    global _lib, _why_not
    with _lib_lock:
        if _lib is None:
            if _why_not is not None:
                raise RuntimeError(_why_not)
            try:
                _lib = _load()
            except Exception as error:  # no compiler, a refused cache, a library that won't load
                _why_not = f'the sheaf kernel is not available: {error}'
                raise RuntimeError(_why_not) from error
        return _lib


def available():
    """Whether the kernel loads here. It is tried once; `why_not()` says what stopped it."""
    try:
        _kernel()
        return True
    except RuntimeError:
        return False


def why_not():
    return _why_not


def chosen(backend=None):
    """Whether a call goes to the kernel. `backend` is 'native', 'numpy' or None. None takes ENGRAM_SHEAF_BACKEND when
    that is set, and otherwise uses the kernel wherever it loads. Asking for 'native' where it can't load raises."""
    backend = backend or os.environ.get('ENGRAM_SHEAF_BACKEND') or None
    if backend == 'numpy':
        return False
    if backend == 'native':
        _kernel()
        return True
    if backend is not None:
        raise ValueError("backend must be 'native' or 'numpy'")
    return available()


def insisted(backend=None):
    """True when the caller or the environment named the kernel, so a refusal is theirs to see and numpy does not
    quietly take the call."""
    return (backend or os.environ.get('ENGRAM_SHEAF_BACKEND')) == 'native'


def _checked(value):
    if value < 0:
        raise SheafKernelError(value)
    return value


def _small(value, low, high, what):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{what} must be a whole number from {low} to {high}')
    return value


def _vector(value, what, n=None):
    out = np.ascontiguousarray(value, dtype=np.float64)
    if out.ndim != 1 or (n is not None and len(out) != n):
        raise ValueError(f'{what} must be a vector' + ('' if n is None else f' of {n}'))
    return out


def _matrix(value, what):
    out = np.ascontiguousarray(value, dtype=np.float64)
    if out.ndim != 2 or not out.shape[0] or not out.shape[1]:
        raise ValueError(f'{what} must be a matrix with at least one row and one column')
    if out.shape[1] > MAX_COLS or out.shape[0] * out.shape[1] > MAX_CELLS:
        raise SheafKernelError(-9)
    return out


def _p(array):
    return array.ctypes.data_as(_double_p)


def _ip(array):
    return array.ctypes.data_as(_int_p)


def sym_eig(a):
    """The eigenvalues of a symmetric matrix, ascending, and its eigenvectors as the columns of a matrix."""
    a = _matrix(a, 'a')
    n = a.shape[0]
    if a.shape[1] != n:
        raise ValueError('a must be square')
    if n > MAX_N:
        raise SheafKernelError(-9)
    evals, evecs = np.zeros(n), np.zeros((n, n))
    _checked(_kernel().sheaf_sym_eig(n, _p(a), _p(evals), _p(evecs)))
    return evals, evecs


def basis(x, variance_threshold=0.90, min_dim=2, max_dim=8):
    """The top principal directions of x's rows, with no mean-centring, as the rows of a matrix, and every singular
    value. As many directions as carry `variance_threshold`, at least `min_dim`, at most `max_dim`."""
    x = _matrix(x, 'x')
    n, d = x.shape
    _small(min_dim, 1, MAX_STALK, 'min_dim')
    _small(max_dim, 1, MAX_STALK, 'max_dim')
    rows, sing, k = np.zeros((max(min_dim, max_dim), d)), np.zeros(min(n, d)), ctypes.c_int32()
    _checked(_kernel().sheaf_basis(n, d, _p(x), float(variance_threshold), min_dim, max_dim, _p(rows), _p(sing),
                                   ctypes.byref(k)))
    return rows[:k.value].copy(), sing


def cohesion(x, variance_threshold=0.90, max_dim=8, max_worst=10):
    """One summary's episodes (the rows of x): the energy in [0, 1], the second eigenvalue, the Fiedler vector, and the
    pairs (i, j, residual) that glue worst. `lambda2` is None under three episodes."""
    x = _matrix(x, 'x')
    n, d = x.shape
    _small(max_dim, 1, MAX_STALK, 'max_dim')
    _small(max_worst, 0, 4096, 'max_worst')
    energy, lambda2, k, kept = ctypes.c_double(), ctypes.c_double(), ctypes.c_int32(), ctypes.c_int32()
    fiedler = np.zeros(n)
    wi, wj, wr = np.zeros(max(max_worst, 1), np.int32), np.zeros(max(max_worst, 1), np.int32), np.zeros(max(max_worst, 1))
    kind = _checked(_kernel().sheaf_cohesion(
        n, d, _p(x), float(variance_threshold), max_dim, ctypes.byref(energy), ctypes.byref(lambda2), _p(fiedler),
        ctypes.byref(k), max_worst, _ip(wi), _ip(wj), _p(wr), ctypes.byref(kept)))
    if kind == 1:
        return {'energy': 0.0, 'lambda2': None, 'fiedler': [], 'worst': [], 'n': n, 'k': k.value}
    worst = [(int(wi[t]), int(wj[t]), float(wr[t])) for t in range(kept.value)]
    return {'energy': energy.value, 'lambda2': lambda2.value, 'fiedler': fiedler.tolist(), 'worst': worst, 'n': n,
            'k': k.value}


def glue(sections, weights=None, trust=None, edge_weighting='product', variance_threshold=0.90, max_dim=8):
    """Several stores' hits for one topic, each a matrix of unit rows in one embedding space. `weights[i]` weights store
    i's hits in its mean (None: equally) and `trust[i]` in [0, 1] weights its edges (None: 1). Pairs are in the order
    (0, 1), (0, 2), ..., (1, 2), ..."""
    if edge_weighting not in ('product', 'min'):
        raise ValueError("edge_weighting must be 'product' or 'min'")
    _small(max_dim, 1, MAX_STALK, 'max_dim')
    mats = [_matrix(s, 'a section') for s in sections]
    m = len(mats)
    if not 1 <= m <= MAX_VERTICES:
        raise ValueError(f'there must be from 1 to {MAX_VERTICES} sections')
    d = mats[0].shape[1]
    if any(s.shape[1] != d for s in mats):
        raise ValueError('every section must be in one embedding space')
    if sum(len(s) for s in mats) * d > MAX_CELLS:
        raise SheafKernelError(-9)
    hits = np.ascontiguousarray(np.vstack(mats))
    counts = np.array([len(s) for s in mats], np.int32)
    w = None
    if weights is not None:
        if len(weights) != m:
            raise ValueError('weights must have one entry for each section')
        w = np.concatenate([np.ones(len(s)) if ws is None else _vector(ws, 'weights for a section', len(s))
                            for s, ws in zip(mats, weights)])
    t = np.ones(m) if trust is None else _vector(trust, 'trust', m)
    kmax, pairs = max(2, max_dim), m * (m - 1) // 2
    out = _Glue()
    rows, stalks, off, zeroed = np.zeros((kmax, d)), np.zeros((m, kmax)), np.zeros(m), np.zeros(m, np.int32)
    residual, edge_weight = np.zeros(max(pairs, 1)), np.zeros(max(pairs, 1))
    consensus, deviation = np.zeros(kmax), np.zeros(m)
    _checked(_kernel().sheaf_glue(
        m, d, _ip(counts), _p(hits), None if w is None else _p(w), _p(t), int(edge_weighting == 'min'),
        float(variance_threshold), max_dim, ctypes.byref(out), _p(rows), _p(stalks), _p(off), _ip(zeroed),
        _p(residual), _p(edge_weight), _p(consensus), _p(deviation)))
    k = out.k
    return {'k': k, 'basis': rows[:k].copy(), 'stalks': stalks[:, :k].copy(), 'off_basis': off,
            'zeroed': zeroed.astype(bool), 'energy': out.energy, 'energy_unweighted': out.energy_unweighted,
            'residual': residual[:pairs].copy(), 'edge_weight': edge_weight[:pairs].copy(),
            'consensus': consensus[:k].copy(), 'consensus_unweighted': bool(out.consensus_unweighted),
            'all_edges_zero': bool(out.all_edges_zero), 'deviation': deviation, 'kernel_dim': out.kernel_dim,
            'glued_dim': out.glued_dim, 'harmonic': out.harmonic}


class Sheaf:
    """A cellular sheaf on a graph: a stalk R^d on every vertex and every edge, and a linear map from each end of an
    edge to the edge. Add the edges, then ask."""

    def __init__(self, vertex_dims):
        self._lock, self._handle = threading.Lock(), None  # first, so a refused sheaf can still be closed
        dims = [_small(d, 1, MAX_STALK, 'a stalk dimension') for d in vertex_dims]
        if not 1 <= len(dims) <= MAX_VERTICES:
            raise ValueError(f'a sheaf has from 1 to {MAX_VERTICES} vertices')
        self.vertex_dims = tuple(dims)
        self._lib = _kernel()
        self._handle = self._lib.sheaf_new(len(dims), _ip(np.array(dims, np.int32)))
        if not self._handle:
            raise SheafKernelError(-9 if sum(dims) > MAX_N else -6)
        self.n0, self.n1, self.edges = sum(dims), 0, 0

    def close(self):
        with self._lock:
            if self._handle:
                self._lib.sheaf_free(self._handle)
                self._handle = None

    __del__ = close

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _open(self):
        if not self._handle:
            raise ValueError('this sheaf is closed')
        return self._handle

    def add_edge(self, u, v, map_u=None, map_v=None, weight=1.0, dim=None):
        """An edge from u to v. `map_u` and `map_v` take each end's stalk to the edge's; None is the identity. The
        edge's dimension is the maps' row count, or `dim`, or (with two identities) the vertices' own."""
        n = len(self.vertex_dims)
        _small(u, 0, n - 1, 'u')
        _small(v, 0, n - 1, 'v')
        mats = []
        for end, m in ((u, map_u), (v, map_v)):
            if m is None:
                mats.append(None)
                continue
            m = _matrix(m, 'a restriction map')
            if m.shape[1] != self.vertex_dims[end]:
                raise ValueError(f"a restriction map from vertex {end} must have {self.vertex_dims[end]} columns")
            mats.append(m)
        rows = {m.shape[0] for m in mats if m is not None}
        if dim is None:
            dim = rows.pop() if len(rows) == 1 else self.vertex_dims[u]
        _small(dim, 1, MAX_STALK, 'dim')
        if any(m is not None and m.shape[0] != dim for m in mats):
            raise ValueError("the restriction maps' rows must match the edge's dimension")
        with self._lock:
            index = _checked(self._lib.sheaf_add_edge(
                self._open(), u, v, dim, None if mats[0] is None else _p(mats[0]),
                None if mats[1] is None else _p(mats[1]), float(weight)))
            self.n1 += dim
            self.edges += 1
        return index

    def coboundary(self, x):
        """dx: what each edge's two ends say about it, subtracted, one edge after another."""
        x = _vector(x, 'x', self.n0)
        dx = np.zeros(max(self.n1, 1))
        with self._lock:
            _checked(self._lib.sheaf_coboundary(self._open(), _p(x), _p(dx)))
        return dx[:self.n1].copy()

    def laplacian(self):
        L = np.zeros((self.n0, self.n0))
        with self._lock:
            _checked(self._lib.sheaf_laplacian(self._open(), _p(L)))
        return L

    def energy(self, x):
        """(x' L x, each edge's |dx|^2 without its weight)."""
        x = _vector(x, 'x', self.n0)
        energy, residual = ctypes.c_double(), np.zeros(max(self.edges, 1))
        with self._lock:
            _checked(self._lib.sheaf_energy(self._open(), _p(x), ctypes.byref(energy), _p(residual)))
        return energy.value, residual[:self.edges].copy()

    def sections(self, x=None, tol=1e-9):
        """h0 and h1, and with x the global section nearest to it and the share of x that does not glue."""
        h0, h1, harmonic = ctypes.c_int32(), ctypes.c_int32(), ctypes.c_double()
        out = {}
        with self._lock:
            if x is None:
                _checked(self._lib.sheaf_sections(self._open(), float(tol), ctypes.byref(h0), ctypes.byref(h1), None,
                                                  None, None))
            else:
                x = _vector(x, 'x', self.n0)
                nearest = np.zeros(self.n0)
                _checked(self._lib.sheaf_sections(self._open(), float(tol), ctypes.byref(h0), ctypes.byref(h1), _p(x),
                                                  _p(nearest), ctypes.byref(harmonic)))
                out = {'section': nearest, 'harmonic': harmonic.value}
        return {'h0': h0.value, 'h1': h1.value, **out}
