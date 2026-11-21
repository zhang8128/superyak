"""Issue #12's router: the kind rule and the split, without data."""
from experiments.multihop.hotpot_router import kind_of, split


def test_the_kind_rule():
    assert kind_of("Are Lotus and Kestrel both rock bands?") == "comparison"
    assert kind_of("Which is older, the Lotus Temple or the Taj Mahal?") == "comparison"
    assert kind_of("Who was born first, Ann Vale or Bob Moss?") == "comparison"
    assert kind_of("Where did the singer of the band Lotus grow up?") == "bridge"
    assert kind_of("What year was the film directed by Ann Vale released?") == "bridge"


def test_the_split_is_seeded_disjoint_and_complete():
    a, b = split(10)
    assert a | b == set(range(10)) and not a & b and len(a) == 5
    assert split(10) == (a, b)
