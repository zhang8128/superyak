"""Issue #7's retrieval measure: the arms pick what their rules say, on hand-made questions."""
from experiments.multihop.hotpot_retrieval import (
    BM25, Question, bare_title, both_gold, links, pick_bm25, pick_hop, pick_oracle, run,
)


def question(paragraphs, gold, text="Which band did the singer of Lotus join?", kind="bridge"):
    return Question(qid="q", question=text, kind=kind, gold=frozenset(gold), paragraphs=tuple(paragraphs))


PARAGRAPHS = [
    ("Lotus (band)", "Lotus is a band whose singer was Ann Vale."),
    ("Ann Vale", "Ann Vale later joined the band Kestrel."),
    ("Lotus Temple", "The Lotus Temple is a building of marble."),
    ("Kestrel", "Kestrel is a bird."),
]


def index(paragraphs):
    return BM25({t: t + " " + x for t, x in paragraphs})


def test_a_title_is_mentioned_without_its_parenthesis():
    assert bare_title("Lotus (band)") == "Lotus"
    assert bare_title("Ann Vale") == "Ann Vale"


def test_links_follow_whole_word_title_mentions():
    graph = links(tuple(PARAGRAPHS))
    assert 1 in graph[0]          # "Ann Vale" is in Lotus's text
    assert 3 in graph[1]          # "Kestrel" is in Ann Vale's text
    assert 0 not in graph[0]      # never a link to itself
    assert 2 not in graph[1]      # "Lotus Temple" is not in Ann Vale's text


def test_a_partial_word_is_not_a_link():
    # "Ann" ends Joann (needs the left boundary) and starts Annabel (needs the right one)
    assert links((("Ann", "a"), ("Bob", "Joann sang."))) == {0: set(), 1: set()}
    assert links((("Ann", "a"), ("Bob", "Annabel sang."))) == {0: set(), 1: set()}
    assert links((("Ann", "a"), ("Bob", "Ann sang."))) == {0: set(), 1: {0}}


def test_the_hop_follows_the_first_picks_link():
    q = question(PARAGRAPHS, {"Lotus (band)", "Ann Vale"})
    picks = pick_hop(q, index(PARAGRAPHS))
    assert picks[0] == 0 and picks[1] == 1
    assert both_gold(q, picks)


def test_with_no_link_out_the_hop_takes_a_paragraph_that_links_in():
    paragraphs = [("Kestrel", "A small bird of prey."), ("Moss", "Moss is a small plant, not a bird."),
                  ("Ann Vale", "Ann Vale joined Kestrel.")]
    q = question(paragraphs, {"Kestrel", "Ann Vale"}, text="small bird prey")
    bm25 = index(paragraphs)
    assert pick_bm25(q, bm25) == [0, 1]   # keywords alone take the distractor
    assert pick_hop(q, bm25) == [0, 2]    # Kestrel links nowhere; Ann Vale links in


def test_the_hop_falls_back_to_bm25_with_no_link_either_way():
    paragraphs = [("Alpha", "alpha alpha"), ("Beta", "beta"), ("Gamma", "alpha beta")]
    q = question(paragraphs, {"Alpha", "Gamma"}, text="alpha")
    bm25 = index(paragraphs)
    assert pick_hop(q, bm25) == pick_bm25(q, bm25)


def test_both_gold_means_every_gold_title_is_among_the_picks():
    q = question(PARAGRAPHS, {"Ann Vale"})
    assert both_gold(q, [1, 3])
    assert not both_gold(q, [0, 3])


def test_the_oracle_and_the_scorer_agree():
    q = question(PARAGRAPHS, {"Ann Vale", "Kestrel"})
    assert both_gold(q, pick_oracle(q))
    assert not both_gold(q, [0, 1])


def test_run_reports_each_arm_by_type_and_the_oracle_is_perfect():
    q1 = question(PARAGRAPHS, {"Lotus (band)", "Ann Vale"})
    q2 = question(PARAGRAPHS, {"Lotus (band)", "Lotus Temple"}, text="Lotus band or Lotus Temple?", kind="comparison")
    result = run([q1, q2])
    assert result["by_type"] == {"bridge": 1, "comparison": 1, "all": 2}
    assert result["both_gold"]["oracle"] == {"bridge": 1.0, "comparison": 1.0, "all": 1.0}
    assert set(result["both_gold"]) == {"random", "oracle", "bm25", "hop"}
