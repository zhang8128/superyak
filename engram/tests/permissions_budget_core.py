"""What U24's world and its probes share, with no import beyond the standard library, so a probe process measures
the code under test and not pytest (Task 31; spec 15)."""
AGENT = "agent:budget-requester"
PLACE = "place:req-15"                     # the bottom of the requester's chain of 16 places
HOLDING_PLACE = "place:hold-15"            # the bottom of the holding chain
STORE_HOUSE = "HOUSE"
COPY = "store:" + STORE_HOUSE
OWNER = "person:andy"
HOME = "place:home/andy"
REBUILD_BUDGET_S, BULK_BUDGET_S = 2, 40
PEAK_LIMIT_KB = 512 * 1024                 # MB means 2**20 bytes, as systemd's 512M does (spec 15)
HOMES = (OWNER,) + tuple(f"person:co{k}" for k in range(1, 8))     # a memory's 8 subjects
REQUESTER_CHAIN = tuple(f"place:req-{i}" for i in range(16))
HOLDING_CHAIN = tuple(f"place:hold-{i}" for i in range(16))
COLLECTIONS = tuple(f"collection:andy/c{k}" for k in range(8))
ALL = "collection:andy/all"                # every memory of the reference ledger, for the gluing checks
JOINT, LEFT, RIGHT = "place:joint", "place:joint-left", "place:joint-right"
_REFS: dict = {}                           # universe -> the memory refs, made once


def budget_refs(universe: int) -> list:
    """The `universe` memory refs of store S, m0 on; the same list every time."""
    if universe not in _REFS:
        _REFS[universe] = [f"mem:S/episode/m{i}" for i in range(universe)]
    return _REFS[universe]


def derived_trails(n: int) -> tuple:
    return tuple(f"trail:S/t{i}" for i in range(n))


def touches(trail: str, count: int, *, universe: int):
    """The `count` memories a derived trail names, one after another and never stored: a deterministic stride
    through the universe, so trails differ and each names `count` distinct memories."""
    refs = budget_refs(universe)
    base = int(trail[len("trail:S/t"):])
    step = 2 * (base % 977) + 1
    while step % 5 == 0:
        step += 2
    return (refs[(base + j * step) % universe] for j in range(count))
