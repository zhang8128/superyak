"""The kernel against Rio Grande's exact engine (whiskered steps modulo exchange moves), at n <= 4, on random regular
polygraphs built to reach 4-cells. The random cross-checks reached 4-cells only 370 times. This one aims at them.

Each world has twin generators in every dimension, so parallel cells exist, and a chain of them that composes along 1.
It composes cells along every lower dimension. It also builds both sides of every exchange it can find: for 4-cells A: X -> X' and B: Y -> Y' with X #k Y
defined (k < 3), (A #k Y) #3 (X' #k B) and (X #k B) #3 (A #k Y'). Those must be one cell.

What's checked, with every cell built through both:
- **Equality:** one map from kernel cells to engine cells, and one back, per formal dimension. A kernel cell that
  meets two engine cells over-identifies. An engine cell that meets two kernel cells under-identifies.
- **Composability:** on pairs chosen at random, not only matching ones, the kernel refuses (-1) exactly when the
  engine does.
- **Generators:** the engine accepts each generator the kernel accepted.

The kernel's allowed refusals (-4 not round, -5 not loop-free, and the size and work bounds) are counted, not compared.
Any other refusal is a disagreement. A world stops where the engine runs out of time, and a run where no world reached
an exchange of 4-cells fails as vacuous. Run from
engram/: python experiments/ncat/cross4.py --engine <the folder holding engine.py>"""
import argparse
import collections
import random
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ncat import NCat, NCatError  # noqa: E402


# The refusals the spec allows here. -8 (the traversal couldn't finish) isn't one: no test has hit it, so here it's a defect.
EXPECTED_GEN = {-4, -5}  # not round, not loop-free; the pairs are parallel and of full shape, so -2 and -3 can't arise
EXPECTED_COMPOSITE = {-5, -9, -10, -11}  # not loop-free, too large, over budget, too much work


class Timeout(Exception):
    pass


def _alarm(*_):
    raise Timeout


class Disagree(Exception):
    pass


class Abandon(Exception):
    """The engine ran out of time or size mid-call. Its tables may be half-written, so the world stops there."""


class World:
    def __init__(self, E, rng, seed, timeout, max_size):
        E.reset()
        self.E, self.rng, self.seed, self.timeout, self.max_size = E, rng, seed, timeout, max_size
        self.C = NCat(budget_bytes=1 << 28, work=1 << 26)
        self.pool = collections.defaultdict(list)  # formal dim -> [(engine cell, kernel cell)]
        self.k2e, self.e2k = {}, {}
        self.n = 0
        self.stats = collections.Counter()

    def fail(self, what):
        raise Disagree(f'seed {self.seed}: {what}')

    def register(self, e, k):
        """Adds a cell built through both, and checks the two maps."""
        d = k.dim
        if k.shape_dim != e.e:
            self.fail(f'shape dimension {k.shape_dim} in the kernel, {e.e} in the engine')
        old_e = self.k2e.get(k.id)
        if old_e is not None and old_e is not e:
            self.fail(f'the kernel over-identifies at formal dimension {d}: {old_e} and {e}')
        old_k = self.e2k.get((d, id(e)))
        if old_k is not None and old_k != k.id:
            self.fail(f'the kernel under-identifies at formal dimension {d}: {e}')
        if old_e is None:
            self.k2e[k.id] = e
            self.e2k[(d, id(e))] = k.id
            self.pool[d].append((e, k))
            self.stats[f'cells at {d}'] += 1
        else:
            self.stats[f'met again at {d}'] += 1
        return e, k

    def engine(self, f):
        signal.setitimer(signal.ITIMER_REAL, self.timeout)
        try:
            return f()
        except (Timeout, self.E.TooBig, RecursionError) as err:
            raise Abandon(type(err).__name__) from None
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)

    def gen(self, s, t):
        """A generator on parallel cells, if the kernel accepts it; the engine must too."""
        try:
            k = self.C.generator(s[1], t[1])
        except NCatError as err:
            if err.code not in EXPECTED_GEN:
                self.fail(f'the kernel refused a generator with {err.code}: {err}')
            self.stats[f'kernel refused a generator ({err.code})'] += 1
            return None
        self.n += 1
        try:
            g = self.E.Gen(f'g{self.n}', k.dim, s[0], t[0], allow_identity_target=False)
        except self.E.Refused as err:
            self.fail(f'the engine refuses a generator the kernel accepts: {err}')
        return self.register(self.E.atom(g), k)

    def comp(self, a, b, j, matched):
        """a #j b through both. Returns the pair, or None when it was refused or ran out of time."""
        try:
            k = a[1].then(b[1], j)
        except NCatError as err:
            if err.code == -1:
                try:
                    self.engine(lambda: self.E.comp(j, a[0], b[0]))
                except self.E.NotComposable:
                    self.stats['both refused, not composable'] += 1
                    return None
                self.fail(f'the kernel says not composable along {j}; the engine composes {a[0]} and {b[0]}')
            if err.code not in EXPECTED_COMPOSITE:
                self.fail(f'the kernel refused a composite along {j} with {err.code}: {err}')
            self.stats[f'kernel refused a composite ({err.code})'] += 1
            return None
        if k.size > self.max_size:
            self.stats['too large for the engine here'] += 1
            return None
        try:
            e = self.engine(lambda: self.E.comp(j, a[0], b[0]))
        except self.E.NotComposable:
            self.fail(f'the kernel composes along {j}; the engine says not composable')
        if not matched:
            self.stats['composed at random'] += 1
        return self.register(e, k)

    # building

    def parallel_pairs(self, d):
        """Pairs of distinct parallel cells of shape d, grouped by their (d-1)-boundaries."""
        groups = collections.defaultdict(list)
        for p in self.pool[d]:
            if p[1].shape_dim == d:
                groups[(p[1].source().id, p[1].target().id)].append(p)
        return [(x, y) for g in groups.values() for x in g for y in g if x is not y]

    def generators(self, d, count):
        pairs = self.parallel_pairs(d - 1)
        self.rng.shuffle(pairs)
        made = []
        for s, t in pairs[:count]:
            g = self.gen(s, t)
            if g is not None:
                made.append(g)
                if self.rng.random() < .8:  # a twin, so cells on one boundary can differ
                    twin = self.gen(s, t)
                    if twin is not None:
                        made.append(twin)
        return made

    def grow(self, d, steps):
        """Composes cells of formal dimension d with others, along every dimension below d."""
        for _ in range(steps):
            if not self.pool[d]:
                return
            a = self.rng.choice(self.pool[d])
            j = self.rng.randrange(d)
            if self.rng.random() < .15:  # a pair at random, to check refusals agree
                b = self.rng.choice(self.pool[self.rng.choice([dd for dd in range(j + 1, d + 1) if self.pool[dd]])])
                matched = False
            else:
                end = a[1].target(j).id
                cands = [p for dd in range(j + 1, d + 1) for p in self.pool[dd] if p[1].source(j).id == end]
                if not cands:
                    continue
                b = self.rng.choice(cands)
                matched = True
            if not matched and self.rng.random() < .5:
                a, b = b, a
            if self.rng.random() < .1:  # an identity on one side, for the unit laws
                a = self.register(a[0], a[1].identity()) if a[1].dim < 4 else a
            self.comp(a, b, j, matched)

    def exchanges(self, limit):
        """Both sides of interchange for 4-cells along each k < 3, with the 3-dimensional composition."""
        fours = [p for p in self.pool[4] if p[1].shape_dim == 4]
        ends = {k: collections.defaultdict(list) for k in range(3)}  # where each 4-cell's k-boundary starts
        for B in fours:
            for k in range(3):
                ends[k][B[1].source(k).id].append(B)
        for k in range(3):
            pairs = [(A, B) for A in fours for B in ends[k][A[1].target(k).id]]
            self.rng.shuffle(pairs)
            for A, B in pairs[:limit]:
                self.stats[f'exchange pairs found along {k}'] += 1
                pX, pXt = self.boundary(A, 3, -1), self.boundary(A, 3, 1)
                pY, pYt = self.boundary(B, 3, -1), self.boundary(B, 3, 1)
                left = [self.comp(A, pY, k, True), self.comp(pXt, B, k, True)]
                right = [self.comp(pX, B, k, True), self.comp(A, pYt, k, True)]
                whole = self.comp(A, B, k, True)
                sides = []
                for first, second in (left, right):
                    if first is not None and second is not None:
                        sides.append(self.comp(first, second, 3, True))
                sides = [s for s in sides if s is not None]
                if whole is not None:
                    sides.append(whole)
                if len(sides) >= 2:
                    if any(s[1] != sides[0][1] for s in sides):
                        self.fail(f'an exchange along {k} gave different kernel cells')
                    if any(s[0] is not sides[0][0] for s in sides):
                        self.fail(f'an exchange along {k} gave different engine cells')
                    self.stats[f'exchanges checked along {k}'] += 1

    def boundary(self, p, j, sign):
        k = p[1].source(j) if sign < 0 else p[1].target(j)
        e = self.E.bd(p[0], j, 0 if sign < 0 else 1)
        return self.register(e, k)

    def chain(self, x, y):
        """Cells that compose along 1 in every dimension, which random worlds rarely reach: 2-generators p => q => r
        on three parallel 1-cells, then twin 3- and 4-generators over each."""
        p, q, r = (self.gen(x, y) for _ in range(3))
        if None in (p, q, r):
            return
        for s, t in ((p, q), (q, r)):
            two = [self.gen(s, t), self.gen(s, t)]
            if None in two:
                continue
            three = [self.gen(two[0], two[1]), self.gen(two[0], two[1])]
            if None in three:
                continue
            self.gen(three[0], three[1])
            self.gen(three[0], three[1])

    def build(self, steps):
        rng, E = self.rng, self.E
        objects = []
        for i in range(rng.randint(1, 3)):
            objects.append(self.register(E.cell0(E.g0(f'x{i}')), self.C.object()))
        self.chain(rng.choice(objects), rng.choice(objects))
        for _ in range(rng.randint(3, 6)):
            s, t = rng.choice(objects), rng.choice(objects)
            self.gen(s, t)
            if rng.random() < .5:
                self.gen(s, t)
        self.grow(1, steps // 2)
        for d in (2, 3, 4):
            self.generators(d, rng.randint(2, 5))
            if d == 4:  # whiskers, so a 4-cell sits inside larger 3-cells
                self.grow(3, steps // 2)
                self.generators(4, rng.randint(1, 3))
            self.grow(d, steps)
            for p in list(self.pool[d])[:40]:  # every boundary of a cell is a cell, built both ways
                for j in range(d):
                    self.boundary(p, j, -1)
                    self.boundary(p, j, 1)
        self.exchanges(200)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--engine', required=True, help='the folder holding engine.py')
    ap.add_argument('--seeds', type=int, default=200)
    ap.add_argument('--first', type=int, default=0)
    ap.add_argument('--steps', type=int, default=60)
    ap.add_argument('--timeout', type=float, default=5.0, help='seconds for one engine composition')
    ap.add_argument('--max-size', type=int, default=400, help='skip composites with more elements than this')
    args = ap.parse_args()
    sys.path.insert(0, args.engine)
    import engine as E
    signal.signal(signal.SIGALRM, _alarm)
    total, failures, started = collections.Counter(), [], time.time()
    for seed in range(args.first, args.first + args.seeds):
        w = World(E, random.Random(seed), seed, args.timeout, args.max_size)
        try:
            w.build(args.steps)
        except Disagree as err:
            failures.append(str(err))
        except NCatError as err:  # composites are caught where they're made, so this is a held cell's boundary or words
            failures.append(f'seed {seed}: the kernel failed on a cell it holds: {err}')
        except Abandon as err:
            w.stats[f'world stopped early: engine {err}'] += 1
        total.update(w.stats)
        if w.stats['exchanges checked along 0'] + w.stats['exchanges checked along 1'] + w.stats['exchanges checked along 2']:
            total['worlds with an exchange checked'] += 1
    for key in sorted(total):
        print(f'{key}: {total[key]}')
    print(f'{args.seeds} worlds in {time.time() - started:.0f} s, {len(failures)} disagreements')
    for f in failures[:20]:
        print('DISAGREE', f)
    if failures:
        return 1
    if not total['worlds with an exchange checked']:
        print('VACUOUS: no world reached an exchange of 4-cells, so nothing at dimension 4 was compared')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
