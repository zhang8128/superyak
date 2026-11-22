"""North-star test 6 (docs/north-star.md row 6; all hands 9d952ee2, b1ca960b): on identity data, a set-valued sheaf can
at best tie an exact enumeration over candidate sets. This is the property test that checks the argument. It isn't a
measurement of capability.

Fixed before it runs (this commit): 500 instances from seed 20261122. Each has 2 to 4 works and 3 to 7 records.
- **A record's stalk** is its candidate works: one for a record keyed by a DOI, several for one keyed only by a url
  that more than one work shares, such as fixture case 20's proceedings page.
- **Its edges** are the pairs a source comparison called a match, each an equality constraint: identity maps into the
  set of all works.

The sheaf's `count_sections` must equal a plain `itertools.product` count on every instance. The three outcomes are
counted and printed: contradictory (0 sections), settled (1) and ambiguous (2 or more)."""
from __future__ import annotations

import itertools
import random

import sheaf_core as sc

SEED, INSTANCES = 20261122, 500


def instance(rng):
    works = [f"w{i}" for i in range(rng.randint(2, 4))]
    records = [f"r{i}" for i in range(rng.randint(3, 7))]
    stalks = {r: tuple(sorted(rng.sample(works, rng.choice([1, 1, 2, len(works)])))) for r in records}
    pairs = list(itertools.combinations(records, 2))
    edges = tuple(p for p in pairs if rng.random() < 0.4)
    return works, records, stalks, edges


def as_sheaf(works, records, stalks, edges):
    base = sc.Base(nodes=tuple(records), edges=edges)
    identity = {w: w for w in works}
    return sc.SetSheaf(base=base, node_stalk=stalks, edge_stalk=tuple(tuple(works) for _ in edges),
                       tail_maps=tuple({x: identity[x] for x in stalks[t]} for t, _ in edges),
                       head_maps=tuple({x: identity[x] for x in stalks[h]} for _, h in edges))


def plain_count(records, stalks, edges):
    """The plain rule: every assignment of one candidate per record, kept when every matched pair agrees."""
    count = 0
    for choice in itertools.product(*(stalks[r] for r in records)):
        chosen = dict(zip(records, choice))
        count += all(chosen[a] == chosen[b] for a, b in edges)
    return count


def test_the_set_sheaf_ties_exact_enumeration_on_identity_data(capsys):
    rng = random.Random(SEED)
    outcomes = {"contradictory": 0, "settled": 0, "ambiguous": 0}
    for _ in range(INSTANCES):
        works, records, stalks, edges = instance(rng)
        sections = sc.count_sections(as_sheaf(works, records, stalks, edges))
        assert sections == plain_count(records, stalks, edges)
        outcomes["contradictory" if sections == 0 else "settled" if sections == 1 else "ambiguous"] += 1
    with capsys.disabled():
        print(f"\ntest 6 identity property: {INSTANCES} instances, seed {SEED}, every count equal; {outcomes}")
    assert all(outcomes.values())  # each kind occurred, so the agreement covers ambiguity and contradiction both


def test_case_20s_third_record_is_ambiguous_not_contradictory():
    """Serenity's point: a url-only record that fits both of two distinct papers gives two global sections, not zero.
    Union-find over 'match' would call it a contradiction."""
    works, records = ["paper-a", "paper-b"], ["doi-a", "doi-b", "url-only"]
    stalks = {"doi-a": ("paper-a",), "doi-b": ("paper-b",), "url-only": ("paper-a", "paper-b")}
    assert sc.count_sections(as_sheaf(works, records, stalks, ())) == 2
    one_side = (("doi-a", "url-only"),)
    assert sc.count_sections(as_sheaf(works, records, stalks, one_side)) == 1 == plain_count(records, stalks, one_side)
    both = (("doi-a", "url-only"), ("doi-b", "url-only"))
    assert sc.count_sections(as_sheaf(works, records, stalks, both)) == 0 == plain_count(records, stalks, both)
