"""A bulk decision keeps a small working set per object (SH-3; P 6.4, 15)."""
import gc
import tracemalloc

from permissions import decide_bulk
from tests.permissions_support import HOME, andy_world, bulk_use, memories

MB = 1 << 20
TRAILS, TOUCHES, UNIVERSE = 10_000, 4, 10_000


def test_bulk_working_set_per_object():
    w = andy_world()
    w.allow(HOME, audience=["self"], kinds=["memory", "trail"], actions=["recall", "read", "imprint"])
    w.allow(HOME, audience=["self"], kinds=["memory"], actions=["recall"], valid_until=w.start + 400 * 86400)
    w.allow(HOME, audience=["self"], kinds=["trail"], actions=["imprint"], valid_until=w.start + 500 * 86400)
    state = w.state()
    mems = memories(UNIVERSE)
    trails = tuple(f"trail:S/t{i}" for i in range(TRAILS))
    index = {t: i for i, t in enumerate(trails)}
    names = lambda o: tuple(mems[(index[o] * TOUCHES + j) % UNIVERSE] for j in range(TOUCHES))
    bulk = bulk_use(trails, action="imprint", names=names, named=False)
    gc.collect()
    tracemalloc.start()
    try:
        d = decide_bulk(state, bulk, group=False)
        gc.collect()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert d.allowed, d.refusal
    decided = TRAILS + UNIVERSE
    assert peak < 450 * decided, f"peak {peak / MB:.1f} MB, {peak / decided:.0f} B per decided object"
