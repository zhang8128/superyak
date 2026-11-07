"""The free strict n-category: known answers first, because a law can hold in a structure that's simply too small, then the
laws on random polygraphs up to n = 5, then what it refuses. ncat_kernel.c says what a cell is."""
import itertools
import os
import math
import random

import pytest

from ncat import NCat, NCatError


def whisker(cat, cell, f, left, right):
    for _ in range(left):
        cell = f.then(cell, 0)
    for _ in range(right):
        cell = cell.then(f, 0)
    return cell


def path(f, n):
    cell = f
    for _ in range(n - 1):
        cell = cell.then(f)
    return cell


# ---- Known answers, counted by hand: too few means too much was identified, too many means a law doesn't hold.

@pytest.mark.parametrize('m', range(0, 8))
def test_a_binary_operation_gives_the_catalan_numbers(m):
    """2-cells f => f^(m+1) from m copies of a: f => ff are the planar binary trees. Every order of building a tree is the
    same cell (interchange), and different trees stay different."""
    C = NCat()
    x = C.object()
    f = C.generator(x, x)
    a = C.generator(f, f.then(f))
    level = {f.identity()}
    for step in range(m):
        level = {cell.then(whisker(C, a, f, pos, step - pos), 1) for cell in level for pos in range(step + 1)}
    assert len(level) == math.comb(2 * m, m) // (m + 1)


@pytest.mark.parametrize('top, m', [(3, 4), (3, 5), (4, 4), (4, 5), (5, 4), (5, 5)])
def test_a_binary_operation_one_or_more_dimensions_up_gives_the_catalan_numbers_too(top, m):
    """The same count at the top of a tower: a bead u on a bead on f, up to dimension top - 1, and at dimension top an
    operation u then u => u. Its m-fold composites u^(m+1) => u are planar binary trees again, at every dimension."""
    C = NCat()
    x = C.object()
    u = C.generator(x, x)
    for _ in range(top - 2):
        u = C.generator(u, u)
    op = C.generator(u.then(u), u)
    level = {path(u, m + 1).identity()}
    for step in range(m):
        size = m + 1 - step  # u^size, about to become u^(size - 1)
        next_level = set()
        for cell in level:
            for pos in range(size - 1):
                w = op
                for _ in range(pos):
                    w = u.then(w, top - 2)
                for _ in range(size - 2 - pos):
                    w = w.then(u, top - 2)
                next_level.add(cell.then(w, top - 1))
        level = next_level
    assert len(level) == math.comb(2 * m, m) // (m + 1)


@pytest.mark.parametrize('wires, beads', [(1, 4), (2, 3), (3, 3), (4, 2), (5, 3)])
def test_beads_on_wires_are_counted_by_stars_and_bars(wires, beads):
    """One bead type on w wires: only how many on each wire can matter, since beads on different wires commute."""
    C = NCat()
    x = C.object()
    f = C.generator(x, x)
    bead = C.generator(f, f)
    base = path(f, wires).identity()
    level = {base}
    for _ in range(beads):
        level = {cell.then(whisker(C, bead, f, w, wires - 1 - w), 1) for cell in level for w in range(wires)}
    assert len(level) == math.comb(beads + wires - 1, wires - 1)


@pytest.mark.parametrize('wires, beads', [(1, 4), (2, 3), (3, 2)])
def test_two_bead_types_keep_their_order_on_a_wire(wires, beads):
    """Each wire keeps a word, so the count is the words of the given length, shared out among the wires."""
    C = NCat()
    x = C.object()
    f = C.generator(x, x)
    red, blue = C.generator(f, f), C.generator(f, f)
    level = {path(f, wires).identity()}
    for _ in range(beads):
        level = {cell.then(whisker(C, b, f, w, wires - 1 - w), 1) for cell in level for b in (red, blue) for w in range(wires)}
    assert len(level) == math.comb(beads + wires - 1, wires - 1) * 2 ** beads


@pytest.mark.parametrize('sheets, marks', [(1, 3), (2, 3), (3, 2), (4, 2)])
def test_three_cells_on_stacked_sheets_are_counted_the_same_way(sheets, marks):
    """The same count one dimension up: a 3-cell on each 2-cell of a stack, where those on different sheets commute."""
    C = NCat()
    x = C.object()
    f = C.generator(x, x)
    a = C.generator(f, f)
    mark = C.generator(a, a)
    def on_sheet(s):
        cell = mark
        for _ in range(s):
            cell = a.then(cell, 1)
        for _ in range(sheets - 1 - s):
            cell = cell.then(a, 1)
        return cell
    level = {path(a, sheets).identity()}
    for _ in range(marks):
        level = {cell.then(on_sheet(s), 2) for cell in level for s in range(sheets)}
    assert len(level) == math.comb(marks + sheets - 1, sheets - 1)


@pytest.mark.parametrize('j', [0, 1, 2])
@pytest.mark.parametrize('marks', [2, 3, 4])
def test_four_cells_on_separate_blocks_commute_along_each_lower_dimension(j, marks):
    """Real exchanges at n = 4, the case a torsion check could wrongly refuse: 4-cells on two 3-cells composed along j. Interchange
    says they commute, so only how many on each can matter: marks + 1 cells, and nothing refused."""
    C = NCat()
    x = C.object()
    f = C.generator(x, x)
    a = C.generator(f, f)
    b = C.generator(a, a)
    mark = C.generator(b, b)
    left, right = mark.then(b, j), b.then(mark, j)
    assert left.then(right) == right.then(left) == mark.then(mark, j)
    level = {b.then(b, j).identity()}
    for _ in range(marks):
        level = {cell.then(step) for cell in level for step in (left, right)}
    assert len(level) == marks + 1


def test_shapes_inside_a_loop_free_shape_need_no_check_of_their_own():
    """Rio Grande's doubt: can a later identity or whisker change what a checked shape determines? An identity is the same shape,
    and a whisker makes a new shape, which is checked. A boundary is a closed part of a shape, and an atom's own boundaries are the
    same inside it, so its relation is part of the larger one: if that has no cycle, nor has this. Its boundaries never refuse."""
    _, d1, _, a, b = torsion()
    for cell in (a, b, d1):
        for k in range(cell.dim):
            assert cell.source(k).identity().source() == cell.source(k)
            assert cell.target(k).then(cell.target(k), k) == cell.target(k)
    assert a.identity().then(a.identity()) == a.identity()


@pytest.mark.parametrize('sides, marks', [(2, 3), (3, 2)])
def test_three_cells_on_side_by_side_sheets_are_counted_too(sides, marks):
    C = NCat()
    x = C.object()
    f = C.generator(x, x)
    a = C.generator(f, f)
    mark = C.generator(a, a)
    def beside(cell, i):
        for _ in range(i):
            cell = a.then(cell, 0)
        for _ in range(sides - 1 - i):
            cell = cell.then(a, 0)
        return cell
    base = beside(a, 0).identity()
    level = {base}
    for _ in range(marks):
        level = {cell.then(beside(mark, i), 2) for cell in level for i in range(sides)}
    assert len(level) == math.comb(marks + sides - 1, sides - 1)


# ---- What a person using it would rely on

def test_loops_keep_their_order():
    """The catch in chain tables, where composing is addition: two loops at one memory would commute."""
    C = NCat()
    x = C.object()
    f, g = C.generator(x, x), C.generator(x, x)
    assert f.then(g) != g.then(f)
    assert f.then(f.then(f)) == f.then(f).then(f)
    assert f.then(g).size == 5


def test_parallel_generators_stay_different_and_the_same_boundaries_are_kept():
    C = NCat()
    x, y = C.object(), C.object()
    f, g = C.generator(x, y), C.generator(x, y)
    assert f != g
    a, b = C.generator(f, g), C.generator(f, g)
    assert a != b
    assert (a.source(), a.target()) == (f, g) == (b.source(), b.target())
    assert (a.source(0), a.target(0)) == (x, y)


def test_composing_needs_matching_boundaries():
    C = NCat()
    x, y = C.object(), C.object()
    f = C.generator(x, y)
    with pytest.raises(NCatError) as caught:
        f.then(f)
    assert caught.value.code == -1
    g = C.generator(y, x)
    a = C.generator(f.then(g), f.then(g))
    with pytest.raises(NCatError):
        a.then(C.generator(g.then(f), g.then(f)), 1)


def test_a_cell_is_the_same_however_it_was_reached():
    C = NCat()
    x = C.object()
    f = C.generator(x, x)
    a, b = C.generator(f, f), C.generator(f, f)
    left, right = whisker(C, a, f, 0, 1), whisker(C, b, f, 1, 0)
    one, two = left.then(right, 1), right.then(left, 1)
    assert one == two == a.then(b, 0)
    assert one.key() == two.key() and one.id == two.id


# ---- What it refuses

def test_an_identity_boundary_is_refused_so_eckmann_hilton_cant_collapse_anything():
    C = NCat()
    x = C.object()
    with pytest.raises(NCatError) as caught:
        C.generator(x.identity(), x.identity())
    assert caught.value.code == -2


def test_a_boundary_that_isnt_parallel_is_refused():
    C = NCat()
    x, y = C.object(), C.object()
    f, g = C.generator(x, y), C.generator(y, x)
    with pytest.raises(NCatError) as caught:
        C.generator(f, g)
    assert caught.value.code == -3
    with pytest.raises(NCatError) as caught:
        C.generator(f, x)
    assert caught.value.code == -3


def test_a_boundary_that_isnt_round_is_refused():
    """Two 2-cells side by side touch at the point between them, so a 3-cell can't have that as its source."""
    C = NCat()
    x = C.object()
    f = C.generator(x, x)
    a = C.generator(f, f)
    beside = a.then(a, 0)
    with pytest.raises(NCatError) as caught:
        C.generator(beside, beside)
    assert caught.value.code == -4


def test_either_side_of_a_generator_being_not_round_is_refused():
    C = NCat()
    x = C.object()
    f = C.generator(x, x)
    a = C.generator(f, f)
    beside = a.then(a, 0)
    whole = C.generator(f.then(f), f.then(f))
    for source, target in ((beside, whole), (whole, beside)):
        with pytest.raises(NCatError) as caught:
            C.generator(source, target)
        assert caught.value.code == -4


def torsion():
    """Rio Grande's example (2026-11-07). A 3-cell D with events m < a < c < n, d < b, d < n, m < b. The block {m, a, b} and the
    block {d, c, n} each come together in one way of building D, and never both, because a feeds c and d feeds b. So 4-cells on
    the two blocks have no interchange between their two orders, and they share no 3-dimensional face, so the shape can't record
    which came first. The free category tells A;B from B;A, and a shape can't. Returns the pieces."""
    C = NCat()
    def seq(j, *cells):
        whole = cells[0]
        for cell in cells[1:]:
            whole = whole.then(cell, j)
        return whole
    x, w, mid = C.object(), C.object(), C.object()
    z_, y_ = C.generator(x, w), C.generator(x, w)
    z1, e1, y1 = C.generator(x, mid), C.generator(x, mid), C.generator(x, mid)
    z2, e2, y2 = C.generator(mid, w), C.generator(mid, w), C.generator(mid, w)
    mu, nu = C.generator(z_, e1.then(e2, 0)), C.generator(e1.then(e2, 0), y_)
    wt, wb = C.generator(z_, z1.then(z2, 0)), C.generator(y1.then(y2, 0), y_)
    uL, uR, uR1, uR2 = C.generator(z1, e1), C.generator(z2, e2), C.generator(z2, e2), C.generator(z2, e2)
    vL, vR, beta, rho = C.generator(e1, y1), C.generator(e2, y2), C.generator(z1, y1), C.generator(z2, y2)
    m = C.generator(mu, seq(1, wt, uL.then(uR, 0)))
    d3 = C.generator(nu, seq(1, vL.then(vR, 0), wb))
    a3, c3 = C.generator(uR, uR1), C.generator(uR1, uR2)
    b3, n3 = C.generator(uL.then(vL, 1), beta), C.generator(uR2.then(vR, 1), rho)
    s1 = seq(2, seq(1, m, vL.then(e2, 0)), seq(1, wt, uL.then(a3, 0), vL.then(e2, 0)), seq(1, wt, b3.then(uR1, 0)))
    s2 = seq(2, seq(1, e1.then(uR1, 0), d3), seq(1, e1.then(c3, 0), vL.then(vR, 0), wb), seq(1, vL.then(n3, 0), wb))
    head = seq(1, mu, d3)
    def whisker_a(block):
        return seq(2, head, seq(1, block, y1.then(vR, 0), wb), seq(1, wt, beta.then(c3, 0), y1.then(vR, 0), wb),
                   seq(1, wt, beta.then(n3, 0), wb))
    def whisker_b(block):
        return seq(2, seq(1, m, nu), seq(1, wt, uL.then(a3, 0), nu), seq(1, wt, uL.then(z2, 0), block),
                   seq(1, wt, b3.then(rho, 0), wb))
    return C, whisker_a(s1), whisker_b(s2), whisker_a(C.generator(s1, s1)), whisker_b(C.generator(s2, s2))


def test_torsion_is_refused_and_not_answered():
    """Both ways of building D are one 3-cell, which is fine, and each 4-cell alone is fine. Composing them is what the shape
    can't decide, and the kernel used to say A;B == B;A. It refuses, both ways round."""
    _, d1, d2, a, b = torsion()
    assert d1 == d2
    assert a.source(3) == d1 == a.target(3)
    assert b.source(3) == d1 == b.target(3)
    for first, second in ((a, b), (b, a)):
        with pytest.raises(NCatError) as caught:
            first.then(second, 3)
        assert caught.value.code == -5


def test_a_4_cell_composes_with_itself_when_nothing_is_tangled():
    """The refusal is for torsion only: the same 4-cell twice is a stack, with an order the shape records."""
    _, _, _, a, b = torsion()
    assert a.then(a, 3).source(3) == a.source(3)
    assert b.then(b, 3).target(3) == b.target(3)


def a_cautious_refusal_at_dimension_3():
    """A spec reviewer's example (2026-11-07). R and R' are parallel 2-cells from x->a->y to x->b->y: R passes through an edge t:
    b -> a, and R' through t': a -> b. A 3-cell R => c => R' holds both, so its 1-skeleton has a directed cycle, and Steiner's
    condition fails at i = 0. The reviewer's reference finds exactly one way to build it, so the cell is determined, and the
    kernel refuses it anyway: the condition is sufficient, not necessary."""
    C = NCat()
    x, a, b, y = (C.object() for _ in range(4))
    f1, f2, g1, g2 = C.generator(x, a), C.generator(a, y), C.generator(x, b), C.generator(b, y)
    t, t2 = C.generator(b, a), C.generator(a, b)
    p, q = f1.then(f2), g1.then(g2)
    alpha, beta = C.generator(f1, g1.then(t)), C.generator(t.then(f2), g2)
    r = alpha.then(f2, 0).then(g1.then(beta, 0), 1)
    gamma, delta = C.generator(f1.then(t2), g1), C.generator(f2, t2.then(g2))
    r2 = f1.then(delta, 0).then(gamma.then(g2, 0), 1)
    c = C.generator(p, q)
    return C, r, r2, c


def test_a_determined_3_cell_can_still_be_refused_and_says_so():
    C, r, r2, c = a_cautious_refusal_at_dimension_3()
    assert r.source() == r2.source() and r.target() == r2.target()
    into, out = C.generator(r, c), C.generator(c, r2)  # each alone is loop-free
    with pytest.raises(NCatError) as caught:
        into.then(out, 2)
    assert caught.value.code == -5 and 'may still be determined' in str(caught.value)
    with pytest.raises(NCatError) as caught:
        C.generator(r, r2)  # an atom is checked too
    assert caught.value.code == -5


@pytest.mark.parametrize('seed', range(24))
def test_nothing_up_to_dimension_2_is_refused(seed):
    """A planar 2-cell's edges all run one way, so no cycle can form, and the free strict 2-category is total here."""
    rng, _, pool = random_polygraph(seed, 2)
    cells = everything(pool)
    for _ in range(1500):
        a, b = rng.choice(cells), rng.choice(cells)
        k = rng.randrange(max(a.dim, b.dim) or 1)
        try:
            c = a.then(b, k)
        except NCatError as e:
            assert e.code == -1, e
            continue
        if c.size <= 200:
            cells.append(c)


# ---- A second traversal, in Python on shuffled numbering: the canonical form has to depend on the shape and nothing else

def parse(words):
    elements, at = [], 0
    while at < len(words):
        dim, label, nin, nout = words[at:at + 4]
        at += 4
        elements.append((dim, label, words[at:at + nin], words[at + nin:at + nin + nout]))
        at += nin + nout
    return elements


def closure(dims, ins, outs, seeds):
    seen, todo = set(seeds), list(seeds)
    while todo:
        for f in (*ins[todo[-1]], *outs[todo.pop()]):
            if f not in seen:
                seen.add(f)
                todo.append(f)
    return seen


def traverse(dims, ins, outs, subset):
    n = max(dims[e] for e in subset)
    if n == 0:
        assert len(subset) == 1
        return list(subset)
    tops = {e for e in subset if dims[e] == n}
    faced = {f for e in subset for f in (*ins[e], *outs[e])}
    output = {f for e in tops for f in outs[e]}
    down = {f: e for e in tops for f in ins[e]}
    front = {e for e in subset if dims[e] == n - 1 and e not in output}
    lower = {e for e in subset if dims[e] < n - 1 and e not in faced}
    order = traverse(dims, ins, outs, closure(dims, ins, outs, front | lower))
    seq, seen = list(order), set(order)
    while tops:
        x = next(down[f] for f in order if f in front and f in down and down[f] in tops and set(ins[down[f]]) <= front)
        tops.discard(x)
        seq.append(x)
        seen.add(x)
        front = (front - set(ins[x])) | set(outs[x])
        order = traverse(dims, ins, outs, closure(dims, ins, outs, front | lower))
        for e in order:
            if e not in seen:
                seen.add(e)
                seq.append(e)
    assert seen == subset
    return seq


def canonical_words(elements, rng):
    """The words again, from the elements numbered at random."""
    size = len(elements)
    new = list(range(size))
    rng.shuffle(new)
    dims, labels, ins, outs = [0] * size, [0] * size, [[]] * size, [[]] * size
    for old, (dim, label, i, o) in enumerate(elements):
        e = new[old]
        dims[e], labels[e] = dim, label
        ins[e], outs[e] = rng.sample([new[f] for f in i], len(i)), rng.sample([new[f] for f in o], len(o))
    seq = traverse(dims, ins, outs, set(range(size)))
    pos = {e: i for i, e in enumerate(seq)}
    words = []
    for e in seq:
        words += [dims[e], labels[e], len(ins[e]), len(outs[e]), *sorted(pos[f] for f in ins[e]), *sorted(pos[f] for f in outs[e])]
    return words


# ---- Safe to use as a component: threads, ownership, ranges, budget, and what it will load

def test_threads_sharing_one_category_dont_corrupt_it():
    """A spec reviewer crashed 3 of 3 runs with four threads on one category, a use-after-free. Each call now holds the GIL and
    the category's lock, so the same work from four threads gives the same cells as from one."""
    import threading
    C = NCat()
    x = C.object()
    f = C.generator(x, x)
    a = C.generator(f, f.then(f))
    errors, results = [], []

    def work(offset):
        try:
            cell = f.identity()
            for step in range(60):
                cell = cell.then(whisker(C, a, f, (step + offset) % (step + 1), step - (step + offset) % (step + 1)), 1)
            results.append(cell.size)
        except Exception as error:  # noqa: BLE001
            errors.append(error)
    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors and len(results) == 4 and len(set(results)) == 1


def test_cells_from_two_categories_never_mix():
    one, two = NCat(), NCat()
    f, g = one.generator(one.object(), one.object()), two.generator(two.object(), two.object())
    for call in (lambda: g.then(f), lambda: f.then(g), lambda: one.generator(g.source(), g.target())):
        with pytest.raises(NCatError) as caught:
            call()
        assert caught.value.code == -7


def test_a_dimension_out_of_range_is_refused_not_wrapped():
    C = NCat()
    x = C.object()
    f = C.generator(x, x)
    for k in (2 ** 32, 2 ** 31, -1, 16, 1.0):
        with pytest.raises(NCatError):
            f.then(f, k)
        with pytest.raises(NCatError):
            f.source(k)


def test_a_cell_cant_be_changed():
    C = NCat()
    f = C.generator(C.object(), C.object())
    for name in ('id', '_id', 'cat', 'other'):
        with pytest.raises(AttributeError):
            setattr(f, name, 0)


def test_the_kernel_checks_its_own_arguments():
    import ncat
    C = NCat()
    f = C.generator(C.object(), C.object())
    lib = ncat._kernel()
    assert lib.ncat_words(C._ptr, f.id, None, -1) == -7
    assert lib.ncat_words(C._ptr, f.id, None, 5) == -7
    assert lib.ncat_compose(C._ptr, f.id, f.id, 99) == -7
    assert lib.ncat_boundary(C._ptr, f.id, 99, 1) == -7
    assert lib.ncat_boundary(C._ptr, 10 ** 6, 0, 1) == -7


def test_the_budget_counts_everything_held_not_just_one_cell():
    """Many small cells, none near the budget alone, still run out of it together."""
    C = NCat(budget_bytes=60_000)
    made = 0
    with pytest.raises(NCatError) as caught:
        for _ in range(2000):
            C.object()
            made += 1
    assert caught.value.code == -10
    assert 100 < made < 1000 and 0 < C.bytes_held <= 60_000


@pytest.mark.skipif(not os.path.exists('/proc/self/statm'), reason='reads resident memory from /proc')
@pytest.mark.parametrize('kind', ['small cells', 'long paths'])
def test_the_budget_bounds_resident_memory(kind):
    """A spec reviewer found 64 MB of counted words came to 364 MB resident. The budget counts bytes with every overhead now, so
    filling it raises resident memory by no more than the budget."""
    def resident():
        return int(open('/proc/self/statm').read().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    budget = 32 << 20
    C = NCat(budget_bytes=budget)
    before = resident()
    with pytest.raises(NCatError) as caught:
        if kind == 'small cells':
            while True:
                C.object()
        else:
            x = C.object()
            loops = [C.generator(x, x) for _ in range(64)]
            p = loops[0]
            while True:
                for g in loops:
                    p = p.then(g)
    assert caught.value.code == -10
    assert resident() - before <= budget * 1.25  # the allocator keeps a little more than it hands out


def test_a_refusal_never_leaves_the_category_over_its_budget():
    """The traversal's working space counts too, and is checked before it grows: doubling a path until refused leaves what's held,
    scratch included, inside the budget."""
    C = NCat(budget_bytes=160_000)  # tight enough that the scratch for the next doubling, not the cell, is what runs out
    x = C.object()
    p = C.generator(x, x)
    with pytest.raises(NCatError) as caught:
        for _ in range(30):
            p = p.then(p)
    assert caught.value.code == -10
    assert C.bytes_held <= 160_000


def test_a_long_composition_lets_other_threads_run():
    """The reviewer froze a second thread for 58.6 s behind one composition. The GIL is let go during a call now."""
    import threading
    import time
    C = NCat()
    x = C.object()
    f = C.generator(x, x)
    a = C.generator(f, f)
    row = a
    for _ in range(900):
        row = row.then(a, 0)
    ticks, stop = [0], [False]

    def spin():
        while not stop[0]:
            ticks[0] += 1
    spinner = threading.Thread(target=spin)
    spinner.start()
    time.sleep(0.05)
    before, started = ticks[0], time.perf_counter()
    row.then(row, 1)
    took, during = time.perf_counter() - started, ticks[0] - before
    stop[0] = True
    spinner.join()
    assert took > 0.02, took  # long enough that a held GIL would have shown
    assert during > 1000, during


def test_one_call_has_a_bound_on_its_work():
    C = NCat(work=10_000)
    x = C.object()
    f = C.generator(x, x)
    a = C.generator(f, f)
    row = a
    with pytest.raises(NCatError) as caught:
        for _ in range(400):
            row = row.then(a, 0)
    assert caught.value.code == -11
    assert a.then(a, 0) == a.then(a, 0)  # small calls still answer


def test_a_category_over_its_budget_refuses_and_keeps_working():
    C = NCat(budget_bytes=40_000)  # the context's own arrays are a few kilobytes of that
    x = C.object()
    f = C.generator(x, x)
    cell = f
    with pytest.raises(NCatError) as caught:
        for _ in range(100):
            cell = cell.then(f)
    assert caught.value.code == -10
    assert C.bytes_held <= 40_000
    assert f.then(f) == f.then(f)  # what it already holds still answers


def test_it_wont_load_a_library_or_cache_that_others_could_write(tmp_path, monkeypatch):
    import ncat
    loose = tmp_path / 'cache'
    (loose / 'superyak' / 'ncat').mkdir(parents=True)
    (loose / 'superyak' / 'ncat').chmod(0o777)
    monkeypatch.setenv('XDG_CACHE_HOME', str(loose))
    with pytest.raises(RuntimeError, match='writable by nobody else'):
        ncat._built()
    library = tmp_path / 'other.so'
    library.write_bytes(b'')
    library.chmod(0o666)
    with pytest.raises(RuntimeError, match='writable by nobody else'):
        ncat._private(library, 'library')


@pytest.mark.parametrize('seed', range(12))
def test_the_canonical_form_ignores_how_a_shape_is_numbered(seed):
    rng, _, pool = random_polygraph(seed, 5)
    checked = 0
    for c in everything(pool):
        words = c.words()
        assert canonical_words(parse(words), rng) == words
        checked += 1
    assert checked > 20


# ---- The laws, on random polygraphs

def random_polygraph(seed, top):
    """Generators in every dimension up to `top`, among parallel cells of the shapes that a random walk reaches."""
    rng = random.Random(seed)
    C = NCat()
    pool = {0: [C.object() for _ in range(rng.randint(1, 3))]}
    for _ in range(rng.randint(3, 6)):
        pool.setdefault(1, []).append(C.generator(rng.choice(pool[0]), rng.choice(pool[0])))
    grow(rng, pool, 1, 40)
    for d in range(2, top + 1):
        pool.setdefault(d, [])
        made, tries = 0, 0
        lower = [c for c in pool[d - 1] if c.shape_dim == d - 1]
        while lower and made < rng.randint(3, 5) and tries < 800:
            tries += 1
            s, t = rng.choice(lower), rng.choice(lower)
            try:
                pool[d].append(C.generator(s, t))
                made += 1
            except NCatError as e:
                assert e.code in (-3, -4), e
        if pool[d]:
            grow(rng, pool, d, 40)
    return rng, C, pool


def grow(rng, pool, d, want):
    """More cells of dimension d, by composing along any lower dimension, whiskers included."""
    cells = pool[d]
    for _ in range(want * 8):
        if len(cells) >= want:
            break
        a = rng.choice(cells)
        k = rng.randrange(d)
        if rng.random() < 0.3 and k + 1 in pool and pool[k + 1]:
            b = rng.choice([c for dd, some in pool.items() if k < dd <= d for c in some])
        else:
            b = rng.choice(cells)
        try:
            c = a.then(b, k) if rng.random() < 0.5 else b.then(a, k)
        except NCatError as e:
            assert e.code in (-1, -5), e  # -5 is torsion, from dimension 4
            continue
        if c.size <= 120:
            cells.append(c)


SEEDS = list(range(12))


def everything(pool):
    return [c for cells in pool.values() for c in cells]


@pytest.mark.parametrize('seed', SEEDS)
def test_globularity(seed):
    _, _, pool = random_polygraph(seed, 5)
    for c in everything(pool):
        for j in range(c.dim):
            for k in range(j):
                assert c.source(j).source(k) == c.source(k)
                assert c.source(j).target(k) == c.target(k)
                assert c.target(j).source(k) == c.source(k)
                assert c.target(j).target(k) == c.target(k)


@pytest.mark.parametrize('seed', SEEDS)
def test_units(seed):
    _, _, pool = random_polygraph(seed, 5)
    for c in everything(pool):
        for k in range(c.dim):
            assert c.source(k).then(c, k) == c
            assert c.then(c.target(k), k) == c
        lifted = c.identity()
        assert lifted.dim == c.dim + 1 and lifted.source() == c == lifted.target()
        assert lifted.then(lifted) == lifted


def composable(rng, pool, tries=600):
    cells = everything(pool)
    for _ in range(tries):
        a, b = rng.choice(cells), rng.choice(cells)
        k = rng.randrange(max(a.dim, b.dim) or 1)
        try:
            yield a, b, k, a.then(b, k)
        except NCatError as e:
            assert e.code in (-1, -5), e


@pytest.mark.parametrize('seed', SEEDS)
def test_associativity(seed):
    rng, _, pool = random_polygraph(seed, 5)
    hits = 0
    pairs = list(composable(rng, pool))
    for (a, b, k, ab), c in itertools.product(pairs[:60], everything(pool)[:80]):
        try:
            bc = b.then(c, k)
        except NCatError:
            continue
        hits += 1
        assert ab.then(c, k) == a.then(bc, k)
    assert hits > 0


@pytest.mark.parametrize('seed', SEEDS)
def test_boundaries_of_a_composite(seed):
    rng, _, pool = random_polygraph(seed, 5)
    for a, b, k, ab in composable(rng, pool):
        for j in range(ab.dim):
            if j < k:
                assert ab.source(j) == a.source(j) == b.source(j)
                assert ab.target(j) == a.target(j) == b.target(j)
            elif j == k:
                assert ab.source(j) == a.source(j) and ab.target(j) == b.target(j)
            else:
                assert ab.source(j) == a.source(j).then(b.source(j), k)
                assert ab.target(j) == a.target(j).then(b.target(j), k)


@pytest.mark.parametrize('seed', SEEDS)
def test_identities_respect_composition(seed):
    rng, _, pool = random_polygraph(seed, 5)
    for a, b, k, ab in composable(rng, pool, 300):
        assert a.identity().then(b.identity(), k) == ab.identity()


@pytest.mark.parametrize('seed', SEEDS)
def test_interchange(seed):
    """(a then b along k) then (c then d along k), along j below k, is (a then c) then (b then d) the other way round."""
    rng, _, pool = random_polygraph(seed, 5)
    pairs = [p for p in composable(rng, pool, 300) if p[2] > 0][:60]
    for (a, b, k, ab), (c, d, k2, cd) in itertools.product(pairs, pairs):
        if k != k2:
            continue
        for j in range(k):
            try:
                whole = ab.then(cd, j)
            except NCatError:
                continue
            assert a.then(c, j).then(b.then(d, j), k) == whole


def test_interchange_was_really_exercised():
    """The random test above would pass on nothing, so this counts that it didn't."""
    hits = 0
    for seed in SEEDS:
        rng, _, pool = random_polygraph(seed, 5)
        pairs = [p for p in composable(rng, pool, 300) if p[2] > 0][:60]
        for (a, b, k, ab), (c, d, k2, cd) in itertools.product(pairs, pairs):
            if k == k2:
                for j in range(k):
                    try:
                        ab.then(cd, j)
                        hits += 1
                    except NCatError:
                        pass
    assert hits >= 100, hits


def test_the_top_dimensions_were_really_reached():
    reached = {d: 0 for d in range(6)}
    for seed in SEEDS:
        _, _, pool = random_polygraph(seed, 5)
        for d, cells in pool.items():
            reached[d] += len(cells)
    assert all(reached[d] > 20 for d in range(6)), reached
