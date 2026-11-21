"""Issue #8's open test: the two arms over a frozen corpus, on a hand-made one."""
import sqlite3

import pytest

from tests.multihop_atlas import loaded_from_atlas, research_corpus

FrozenCorpus, build = research_corpus().FrozenCorpus, research_corpus().build
from experiments.multihop.hotpot_open import current_title, evaluate, pick_bm25, pick_hop  # noqa: E402

MANIFEST = {"id": "t", "name": "T", "snapshot": "2026-11-07", "question_derived": False}
RECORDS = [
    {"title": "Lotus (band)", "page_id": 1, "rev_id": 1, "text": "Lotus is a band whose singer was Ann Vale.",
     "links": ["Ann Vale"]},
    {"title": "Ann Vale", "page_id": 2, "rev_id": 2, "text": "Ann Vale grew up in Leeds in 1970.", "links": []},
    {"title": "Lotus Temple", "page_id": 3, "rev_id": 3, "text": "The Lotus Temple is a building in Delhi.",
     "links": []},
]


@pytest.fixture
def corpus(tmp_path):
    summary = build(RECORDS, MANIFEST, tmp_path / "c.sqlite3")
    return FrozenCorpus(tmp_path / "c.sqlite3", digest=summary["digest"])


def question(text, gold, kind="bridge", qid="q"):
    return {"id": qid, "question": text, "type": kind, "supporting_facts": {"title": gold, "sent_id": [0] * len(gold)}}


def test_the_hop_follows_a_link_that_bm25_misses(corpus):
    q = "Where did the singer of the band Lotus grow up?"
    assert pick_bm25(corpus, q)[0] == "Lotus (band)" and "Ann Vale" not in pick_bm25(corpus, q)
    assert pick_hop(corpus, q) == ["Lotus (band)", "Ann Vale"]


def test_with_no_matching_link_the_hop_is_bm25(corpus):
    q = "Lotus Temple Delhi"
    assert pick_hop(corpus, q) == pick_bm25(corpus, q)


def test_gold_titles_map_through_redirects_and_coverage_is_counted(corpus, tmp_path):
    redirects = sqlite3.connect(tmp_path / "r.sqlite3")
    redirects.execute("CREATE TABLE r (title TEXT PRIMARY KEY, target TEXT NOT NULL) WITHOUT ROWID")
    redirects.execute("INSERT INTO r VALUES ('Lotus band', 'Lotus (band)')")
    assert current_title("Lotus_band", redirects) == "Lotus (band)"
    questions = [question("Where did the singer of the band Lotus grow up?", ["Lotus band", "Ann Vale"]),
                 question("Lotus Temple and Atlantis?", ["Lotus Temple", "Atlantis"], kind="comparison", qid="q2")]
    summary, rows = evaluate(corpus, questions, redirects)
    assert summary["both_gold_in_corpus"] == 1                   # Atlantis isn't in the corpus
    assert summary["both_gold"]["hop"]["hits"] == 1 and summary["both_gold"]["bm25"]["hits"] == 0
    assert rows[1]["gold_in_corpus"] == 1 and rows[1]["hop_both"] is False
    assert summary["verified"] is True


def test_hotpotqa_titles_are_unescaped_before_mapping():
    assert current_title("Merck &amp; Co.", None) == "Merck & Co."
    assert current_title("S&amp;M (song)", None) == "S&M (song)"


def test_evidence_reads_the_picks_in_order_and_skips_a_missing_title(corpus):
    from experiments.multihop.hotpot_open_answers import evidence
    got = evidence(corpus, ["Ann Vale", "No Such Page", "Lotus (band)"])
    assert [t for t, _ in got] == ["Ann Vale", "Lotus (band)"]
    assert got[0][1] == "Ann Vale grew up in Leeds in 1970."


def test_no_module_from_atlas_workbench_is_left_loaded():
    # research_poc.atlas_bridge refuses its frozen snapshot beside one (CI, 11-21: 16 bridge tests errored).
    assert loaded_from_atlas() == []
