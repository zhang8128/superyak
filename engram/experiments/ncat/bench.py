"""What the kernel costs, and what the same canonicalising costs in pure Python. Synthetic shapes, one process, one core."""
import pathlib
import random
import sys
import time

sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[2]), str(pathlib.Path(__file__).resolve().parents[2] / 'tests')]
from ncat import NCat  # noqa: E402
from test_ncat import canonical_words, parse  # noqa: E402


def timed(fn, repeat=1):
    begun = time.perf_counter()
    for _ in range(repeat):
        out = fn()
    return (time.perf_counter() - begun) / repeat * 1e6, out


def show(what, c_us, py_us, size):
    print(f'{what:44} {size:7d} elements  C {c_us:10.1f} us   Python {py_us:12.1f} us   x{py_us / c_us:6.0f}', flush=True)


def fresh_compose(make):
    """Each round builds the two sides new, since composing the same two cells again is one table lookup."""
    C, a, b, k = make()
    begun = time.perf_counter()
    out = a.then(b, k)
    return (time.perf_counter() - begun) * 1e6, out


rng = random.Random(1)
print('--- 1-cells: one more step on a path')
for length in (10, 50, 1000, 10000):
    C = NCat()
    x = C.object()
    fs = [C.generator(x, x) for _ in range(8)]
    p = fs[0]
    for i in range(length - 1):
        p = p.then(fs[i % 8])
    us = []
    for f in fs:
        begun = time.perf_counter()
        p.then(f)
        us.append((time.perf_counter() - begun) * 1e6)
    py, _ = timed(lambda: canonical_words(parse(p.words()), rng), 1 if length > 1000 else 3)
    show(f'path of {length}', sorted(us)[len(us) // 2], py, p.size)

print('--- 2-cells: one more operation on a tree, across a front of w wires')
for ops in (10, 100, 400):
    C = NCat()
    x = C.object()
    f = C.generator(x, x)
    a = C.generator(f, f.then(f))
    cell, wires = f.identity(), 1
    for _ in range(ops):
        pos = rng.randrange(wires)
        w = a
        for _ in range(pos):
            w = f.then(w, 0)
        for _ in range(wires - 1 - pos):
            w = w.then(f, 0)
        cell = cell.then(w, 1)
        wires += 1
    w = a
    for _ in range(wires - 1):
        w = w.then(f, 0)
    begun = time.perf_counter()
    cell.then(w, 1)
    c_us = (time.perf_counter() - begun) * 1e6
    py, _ = timed(lambda: canonical_words(parse(cell.words()), rng))
    show(f'tree of {ops}, front {wires}', c_us, py, cell.size)

print('--- 3-cells: one more mark on a stack of s sheets')
for sheets, marks in ((5, 10), (20, 40), (50, 100)):
    C = NCat()
    x = C.object()
    f = C.generator(x, x)
    a = C.generator(f, f)
    mark = C.generator(a, a)
    stack = a
    for _ in range(sheets - 1):
        stack = stack.then(a, 1)
    def on(s):
        w = mark
        for _ in range(s):
            w = a.then(w, 1)
        for _ in range(sheets - 1 - s):
            w = w.then(a, 1)
        return w
    cell = stack.identity()
    for _ in range(marks):
        cell = cell.then(on(rng.randrange(sheets)), 2)
    w = on(0)
    begun = time.perf_counter()
    cell.then(w, 2)
    c_us = (time.perf_counter() - begun) * 1e6
    py, _ = timed(lambda: canonical_words(parse(cell.words()), rng))
    show(f'stack of {sheets}, {marks} marks', c_us, py, cell.size)

print('--- equal or not, once a cell is held')
C = NCat()
x = C.object()
f = C.generator(x, x)
p = f
for _ in range(999):
    p = p.then(f)
q = f
for _ in range(999):
    q = f.then(q)
us, same = timed(lambda: p == q, 100000)
print(f'two 1000-step paths built opposite ways: same cell {same}, compare {us * 1000:.0f} ns (a Python call around two integers)')
