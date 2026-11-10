"""The C++ port against its oracle (Defiant's plan, phase 1; Rio Grande's differential check, 0b565bcb): the C kernel and
the C++ one take the same seeded random calls, and every return code, every new cell's words and the bytes held are
compared call by call. The suite checks what it reaches; this checks every path the calls reach, the caps included, built
small (NCAT_MASK_MAX) so the interning table's and the memo's limits are met, with budgets and work limits set to bite.
Then each public call is made to throw inside, to show no exception crosses the C line."""
import ctypes
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ENGRAM = Path(__file__).resolve().parents[1]
FLAGS = ['-O1', '-fPIC', '-shared', '-Wall']
CALLS = {'ncat_gen': 2, 'ncat_compose': 3, 'ncat_boundary': 3, 'ncat_identity': 1, 'ncat_formal': 1, 'ncat_shape': 1,
         'ncat_size': 1}


def build(tmp_path, kind, *extra):
    """The C oracle (cc, C11) or the port (c++, C++20), with the same extra flags."""
    if kind == 'c':
        compiler, source, std = '/usr/bin/cc', ENGRAM / 'ncat_kernel.c', '-std=c11'
    else:
        compiler, source, std = '/usr/bin/c++', ENGRAM / 'ncat_kernel.cpp', '-std=c++20'
    if not os.access(compiler, os.X_OK):
        pytest.skip(f'no {compiler}')
    out = tmp_path / f'ncat-{kind}-{abs(hash(extra))}.so'
    subprocess.run([compiler, std, *FLAGS, *extra, str(source), '-o', str(out)], check=True, capture_output=True,
                   env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    return out


def load(path):
    lib = ctypes.CDLL(str(path))  # each library its own handle, so the two kernels' symbols never meet
    lib.ncat_new.restype = ctypes.c_void_p
    lib.ncat_free.argtypes = [ctypes.c_void_p]
    for name, args in CALLS.items():
        getattr(lib, name).argtypes = [ctypes.c_void_p] + [ctypes.c_int32] * args
        getattr(lib, name).restype = ctypes.c_int32
    lib.ncat_words.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32), ctypes.c_int32]
    lib.ncat_words.restype = ctypes.c_int32
    for name in ('ncat_ncells', 'ncat_ngens'):
        getattr(lib, name).argtypes = [ctypes.c_void_p]
        getattr(lib, name).restype = ctypes.c_int32
    lib.ncat_held.argtypes = [ctypes.c_void_p]
    lib.ncat_held.restype = ctypes.c_int64
    for name in ('ncat_set_budget', 'ncat_set_work'):
        getattr(lib, name).argtypes = [ctypes.c_void_p, ctypes.c_int64]
        getattr(lib, name).restype = ctypes.c_int32
    return lib


def words(lib, ctx, cell):
    n = lib.ncat_words(ctx, cell, None, 0)
    if n < 0:
        return n
    buf = (ctypes.c_int32 * max(n, 1))()
    lib.ncat_words(ctx, cell, buf, n)
    return list(buf[:n])


class Pair:
    """The two kernels side by side: every call goes to both, and must answer alike."""

    def __init__(self, c, cpp):
        self.libs = (c, cpp)
        self.ctxs = (c.ncat_new(), cpp.ncat_new())
        assert all(self.ctxs)
        self.calls = 0

    def close(self):
        for lib, ctx in zip(self.libs, self.ctxs):
            lib.ncat_free(ctx)

    def __call__(self, name, *args):
        answers = [getattr(lib, name)(ctx, *args) for lib, ctx in zip(self.libs, self.ctxs)]
        self.calls += 1
        assert answers[0] == answers[1], (name, args, answers)
        held = [lib.ncat_held(ctx) for lib, ctx in zip(self.libs, self.ctxs)]
        assert held[0] == held[1], (name, args, 'bytes held', held)
        return answers[0]

    def words(self, cell):
        got = [words(lib, ctx, cell) for lib, ctx in zip(self.libs, self.ctxs)]
        assert got[0] == got[1], ('words', cell)
        return got[0]


def drive(pair, seed, steps):
    """A random polygraph grown by the calls a user makes, biased toward the ones that succeed: generators between
    parallel cells, composites along a shared boundary, boundaries and identities; with the budget and the work limit set
    now and then to just above what's used, so their refusals are met. Returns the codes seen."""
    rng = random.Random(seed)
    cells, seen = [], set()
    for _ in range(rng.randint(1, 3)):
        cells.append(pair('ncat_gen', -1, -1))
    for _ in range(steps):
        op = rng.random()
        if op < 0.04:
            got = pair('ncat_gen', -1, -1)
        elif op < 0.40 and cells:
            s = rng.choice(cells)
            m = pair('ncat_formal', s)
            same = [t for t in cells if pair('ncat_formal', t) == m]
            parallel = [t for t in rng.sample(same, min(len(same), 12))
                        if m == 0 or all(pair('ncat_boundary', t, m - 1, sign) == pair('ncat_boundary', s, m - 1, sign)
                                         for sign in (-1, 1))]
            got = pair('ncat_gen', s, rng.choice(parallel or same))
        elif op < 0.75 and cells:
            a = rng.choice(cells)
            top = max(pair('ncat_formal', a), 1)
            k = rng.randrange(top)
            out = pair('ncat_boundary', a, k, 1)
            fits = [b for b in rng.sample(cells, min(len(cells), 16)) if pair('ncat_boundary', b, k, -1) == out]
            got = pair('ncat_compose', a, rng.choice(fits or cells), k)
        elif op < 0.85 and cells:
            got = pair('ncat_boundary', rng.choice(cells), rng.randrange(4), rng.choice((-1, 1)))
        elif op < 0.92 and cells:
            got = pair('ncat_identity', rng.choice(cells))
        elif op < 0.96:
            held = pair.libs[0].ncat_held(pair.ctxs[0])
            got = pair('ncat_set_budget', held + rng.choice((0, 64, 4_096, 1 << 20, 1 << 30)))
        else:
            got = pair('ncat_set_work', rng.choice((1, 8, 64, 4_096, 1 << 30)))
        seen.add(got if got < 0 else 'ok')
        if got >= 0 and got not in cells and got < pair('ncat_ncells'):
            pair.words(got)
            cells.append(got)
    for cell in cells:
        pair.words(cell)
    return seen


@pytest.fixture(scope='module')
def kernels(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('port')
    return {name: (load(build(tmp, 'c', *extra)), load(build(tmp, 'cpp', *extra)))
            for name, extra in (('full', ()), ('small', ('-DNCAT_MASK_MAX=255',)))}


@pytest.mark.parametrize('seed', range(40))
def test_the_port_answers_as_the_c_kernel_does(kernels, seed):
    pair = Pair(*kernels['full'])
    try:
        drive(pair, seed, 300)
    finally:
        pair.close()


def test_the_port_meets_the_caps_and_budgets_as_the_c_kernel_does(kernels):
    """Built with the table and memo capped at 256 slots, the calls reach the cap's refusal, the budget's and the work
    limit's, and the two kernels refuse each one alike."""
    seen = set()
    for seed in range(24):
        pair = Pair(*kernels['small'])
        try:
            seen |= drive(pair, 1000 + seed, 600)
        finally:
            pair.close()
    assert {'ok', -9, -10, -11} <= seen, seen


def test_no_exception_crosses_the_c_line(tmp_path):
    """Each public call made to throw inside: an allocation failure answers -6, as a failed malloc did, and anything
    else -7, and the category still answers after."""
    lib = load(build(tmp_path, 'cpp', '-DNCAT_TEST_THROW'))
    lib.ncat_test_throw_next.argtypes = [ctypes.c_int32]
    ctx = lib.ncat_new()
    x, y = lib.ncat_gen(ctx, -1, -1), lib.ncat_gen(ctx, -1, -1)
    f = lib.ncat_gen(ctx, x, y)
    calls = {'ncat_gen': (x, y), 'ncat_compose': (f, f, 0), 'ncat_boundary': (f, 0, 1), 'ncat_identity': (f,),
             'ncat_formal': (f,), 'ncat_shape': (f,), 'ncat_size': (f,), 'ncat_ncells': (), 'ncat_ngens': (),
             'ncat_set_budget': (1 << 30,), 'ncat_set_work': (1 << 30,)}
    for name, args in calls.items():
        for kind, code in ((1, -6), (2, -7)):
            lib.ncat_test_throw_next(kind)
            assert getattr(lib, name)(ctx, *args) == code, (name, kind)
    lib.ncat_test_throw_next(1)
    buf = (ctypes.c_int32 * 4)()
    assert lib.ncat_words(ctx, x, buf, 4) == -6
    assert lib.ncat_boundary(ctx, f, 0, 1) == y and lib.ncat_ncells(ctx) >= 3  # still answers
    lib.ncat_free(ctx)


def _runtime(name):
    found = subprocess.run(['/usr/bin/c++', f'-print-file-name={name}'], capture_output=True, text=True).stdout.strip()
    return found if found and os.path.isabs(found) and os.path.exists(found) else None


def test_the_differential_run_is_clean_under_asan_and_ubsan(tmp_path):
    """The same comparison with both kernels built under AddressSanitizer and UndefinedBehaviorSanitizer, in a process of
    its own with the runtimes preloaded (Python links neither, nor libstdc++)."""
    asan, stdcxx = _runtime('libasan.so'), _runtime('libstdc++.so')
    if not asan or not stdcxx:
        pytest.skip('no AddressSanitizer runtime here')
    flags = ('-fsanitize=address,undefined', '-fno-sanitize-recover=undefined', '-fno-omit-frame-pointer', '-g')
    c, cpp = build(tmp_path, 'c', *flags), build(tmp_path, 'cpp', *flags)
    small = (build(tmp_path, 'c', *flags, '-DNCAT_MASK_MAX=255'), build(tmp_path, 'cpp', *flags, '-DNCAT_MASK_MAX=255'))
    script = (f"import sys; sys.path.insert(0, {str(ENGRAM)!r}); from tests.test_ncat_port import Pair, load, drive\n"
              f"for (c, cpp), seeds in ((({str(c)!r}, {str(cpp)!r}), range(12)), (({str(small[0])!r}, {str(small[1])!r}), "
              f"range(1000, 1008))):\n"
              "    for seed in seeds:\n"
              "        pair = Pair(load(c), load(cpp)); drive(pair, seed, 300); pair.close()\n"
              "print('clean')\n")
    env = {**os.environ, 'LD_PRELOAD': f'{asan}:{stdcxx}', 'ASAN_OPTIONS': 'detect_leaks=0',
           'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1'}
    done = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, env=env, timeout=900)
    assert done.returncode == 0 and 'clean' in done.stdout, done.stderr[-3000:]


def test_both_kernels_keep_the_real_cap_and_codes_by_default():
    """The harness builds both small (-DNCAT_MASK_MAX=255) to reach the cap; without it each has the real one, 2^30 - 1,
    and the two name the same error codes."""
    import re
    texts = [(ENGRAM / name).read_text() for name in ('ncat_kernel.c', 'ncat_kernel.cpp')]
    for text in texts:
        assert '#ifndef NCAT_MASK_MAX' in text and '#define NCAT_MASK_MAX ((1u << 30) - 1)' in text
    codes = [re.search(r'enum \{ NCAT_ENOTCOMPOSABLE = -1,.*?\};', text, re.S).group(0) for text in texts]
    assert codes[0] == codes[1]

