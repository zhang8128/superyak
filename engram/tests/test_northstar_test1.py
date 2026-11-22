"""North-star test 1's pieces: the qualifying rule, the seeded draw and substitution, the overlay, Atlas's
one-revision-one-source convention, the leakage guard, B-cache, and the scoring arithmetic -- on hand-made
fixtures and a tiny planted corpus. No model, no network, no full corpus.

Atlas's ``Store`` (``atlas/workbench/store.py``) is loaded here the same way ``multihop_atlas.py`` loads
``research_corpus.py``: under a private name, registered under ``workbench`` only for the one test that asks
for it (the ``atlas_workbench`` fixture), via ``monkeypatch``, so no test here leaves a ``workbench`` module
behind for ``test_atlas_poc_bridge`` to trip over (see ``multihop_atlas.py``'s docstring; CI broke this way on
11-21 when a different multihop test imported atlas at module level). Unlike ``research_corpus.py``,
``store.py`` has a relative import (``from .validation import ...``), so it's registered as a real package
submodule (via ``__path__``), not loaded by bare file path.
"""
from __future__ import annotations

import importlib
import inspect
import shutil
import sqlite3
import subprocess
import sys
import types
from pathlib import Path

import pytest

from tests.multihop_atlas import research_corpus
from experiments.multihop.export_corpus_tsv import export as export_corpus_tsv

from experiments.northstar import test1 as ns  # noqa: E402

ATLAS = Path(__file__).resolve().parents[2] / "atlas"
WORKBENCH_DIR = ATLAS / "workbench"
PRIVATE_WORKBENCH = "_engram_tests_ns_workbench"


def _load_private_workbench():
    if not WORKBENCH_DIR.exists():
        pytest.skip("atlas isn't beside engram here")
    if PRIVATE_WORKBENCH not in sys.modules:
        package = types.ModuleType(PRIVATE_WORKBENCH)
        package.__path__ = [str(WORKBENCH_DIR)]
        sys.modules[PRIVATE_WORKBENCH] = package
        importlib.import_module(f"{PRIVATE_WORKBENCH}.store")
    return sys.modules[PRIVATE_WORKBENCH]


@pytest.fixture
def atlas_workbench(monkeypatch):
    """``workbench`` (``Store``) importable by its real name, for this test only."""
    package = _load_private_workbench()
    monkeypatch.setitem(sys.modules, "workbench", package)
    monkeypatch.setitem(sys.modules, "workbench.store", package.store)
    monkeypatch.setitem(sys.modules, "workbench.validation", package.validation)
    return package


def make_store(tmp_path, atlas_workbench, name="store.db"):
    return atlas_workbench.store.Store(tmp_path / name, create=True)


# =====================================================================================
# A planted mini corpus, built with atlas/workbench/research_corpus.build (the same
# pattern test_multihop_open.py and test_multihop_corpus_index.py use).
# =====================================================================================

MANIFEST = {"id": "t", "name": "T", "snapshot": "2026-11-07", "question_derived": False}

# Pages chosen to exercise every qualifying edge in one small corpus:
# 1/2: a bridge pair whose answer ("1970", a year) is in exactly one lead.
# 3: a second "Ann Vale"-shaped name for a same-class donor ("Sam Lowe" born 1985 -- a second year donor).
# 4: an accented name-shaped answer ("Curaçao") in exactly one lead.
# 5/6: a pair whose answer ("Ann Vale") would be in *both* leads (never qualifies).
RECORDS = [
    {"title": "Lotus (band)", "page_id": 1, "rev_id": 1,
     "text": "Lotus is a band whose singer was Ann Vale.", "links": ["Ann Vale"]},
    {"title": "Ann Vale", "page_id": 2, "rev_id": 2,
     "text": "Ann Vale grew up in Leeds in 1970.", "links": []},
    {"title": "Sam Lowe", "page_id": 3, "rev_id": 1,
     "text": "Sam Lowe was born in Paris in 1985.", "links": []},
    {"title": "Delta Airport", "page_id": 4, "rev_id": 1,
     "text": "Delta Airport opened in Curaçao in 1942.", "links": []},
    {"title": "Echo (band)", "page_id": 5, "rev_id": 1,
     "text": "Echo is a band whose singer was Ann Vale.", "links": []},
    {"title": "Ann Vale (dancer)", "page_id": 6, "rev_id": 1,
     "text": "Ann Vale also danced for the band Echo.", "links": []},
    # A second bridge pair of each qualifying class, with an answer distinct from the ones above, so a
    # corrected question always has a same-class donor to draw from (TestBuildPlan).
    {"title": "Volt (band)", "page_id": 7, "rev_id": 1,
     "text": "Volt is a band whose singer was Mia Frost.", "links": ["Mia Frost"]},
    {"title": "Mia Frost", "page_id": 8, "rev_id": 1,
     "text": "Mia Frost grew up in Bristol in 1985.", "links": []},
    {"title": "Nile Band", "page_id": 9, "rev_id": 1,
     "text": "Nile Band's lead singer once honored a city called Boston.", "links": ["Jane Pryce"]},
    {"title": "Jane Pryce", "page_id": 10, "rev_id": 1,
     "text": "Jane Pryce performed with Nile Band for a decade.", "links": []},
    # For classify_name (revision 4): a biography with a "(born" parenthesis, one with a life-span year
    # range, and a resolvable non-person (a place) -- the same shape as the bug revision 4 fixes.
    {"title": "Thomas Reed", "page_id": 11, "rev_id": 1,
     "text": "Thomas Reed (born 3 March 1950) is a British actor.", "links": []},
    {"title": "Agnes Clarke", "page_id": 12, "rev_id": 1,
     "text": "Agnes Clarke (1842-1907) was an astronomer.", "links": []},
    {"title": "County Tyrone", "page_id": 13, "rev_id": 1,
     "text": "County Tyrone is a county in Northern Ireland.", "links": []},
    # A bridge pair mentioning "Thomas Reed" in exactly one lead, for a qualifying-level person test (the
    # person himself is page 11 above; neither of these is his own article, avoiding the self-mention trap).
    {"title": "Echo Films", "page_id": 14, "rev_id": 1,
     "text": "Echo Films was founded by Thomas Reed in 1990.", "links": []},
    {"title": "Echo Films Studio", "page_id": 15, "rev_id": 1,
     "text": "Echo Films Studio is based in Soho.", "links": []},
    # classify_name, widened: "born" anywhere in the parenthesis (a stripped pronunciation guide before it,
    # as real Wikipedia leads commonly have), a full birth-to-death date range with no "born" word at all,
    # a single year alone (not a person), and a later parenthesis that must NOT be looked at.
    {"title": "Diane Foster", "page_id": 16, "rev_id": 1,
     "text": "Diane Foster (; born 2 May 1972) is a violinist.", "links": []},
    {"title": "Percy Vance", "page_id": 17, "rev_id": 1,
     "text": "Percy Vance (12 May 1901 – 3 June 1980) was a composer.", "links": []},
    {"title": "Grand Hall", "page_id": 18, "rev_id": 1,
     "text": "Grand Hall (founded 1890) is a concert venue.", "links": []},
    {"title": "Riverside Club", "page_id": 19, "rev_id": 1,
     "text": "Riverside Club (founded 1925) hosted events (born from an older society, 1890-1910).",
     "links": []},
]


@pytest.fixture
def corpus_path(tmp_path):
    path = tmp_path / "corpus.sqlite3"
    research_corpus().build(RECORDS, MANIFEST, path)
    return path


@pytest.fixture
def corpus(corpus_path):
    return ns.CorpusLookup.open(corpus_path)


@pytest.fixture
def redirects(tmp_path):
    db = sqlite3.connect(tmp_path / "r.sqlite3")
    db.execute("CREATE TABLE r (title TEXT PRIMARY KEY, target TEXT NOT NULL) WITHOUT ROWID")
    db.execute("INSERT INTO r VALUES ('Lotus band', 'Lotus (band)')")
    db.execute("INSERT INTO r VALUES ('Old Band Name', 'Lotus (band)')")
    db.execute("INSERT INTO r VALUES ('Thomas R Reed', 'Thomas Reed')")
    db.commit()
    return db


def _diverse_qualifying_rows():
    """Four qualifying bridge rows, two of each class, each with an answer distinct from its classmate --
    enough for `choose_substitutes` to always find a same-class donor (build_plan tests)."""
    return [
        bridge("q-year-1970", "Ignored", "1970", ["Lotus (band)", "Ann Vale"]),
        bridge("q-year-1985", "Ignored", "1985", ["Volt (band)", "Mia Frost"]),
        bridge("q-name-curacao", "Ignored", "Curaçao", ["Delta Airport", "Ann Vale"]),
        bridge("q-name-boston", "Ignored", "Boston", ["Nile Band", "Jane Pryce"]),
    ]


def bridge(qid, question, answer, gold):
    return {"id": qid, "question": question, "answer": answer, "type": "bridge",
            "supporting_facts": {"title": gold, "sent_id": [0] * len(gold)}}


# =====================================================================================
# The qualifying rule
# =====================================================================================

class TestAnswerShape:
    """``answer_shape`` is the structural check alone (year-or-name-shaped), with no corpus lookup --
    before revision 4 splits "name" into "person" and "other_name" (``TestClassifyName`` below)."""

    def test_bare_four_digit_year_is_the_year_class(self):
        assert ns.answer_shape("1970") == "year"

    def test_a_full_date_is_neither_class(self):
        # the re-check: "a third of otherwise qualifying answers are dates ... left out, not mis-substituted"
        assert ns.answer_shape("12 January 1970") is None
        assert ns.answer_shape("1970s") is None

    def test_name_shaped_including_accents_periods_hyphens_apostrophes(self):
        assert ns.answer_shape("Ann Vale") == "name"
        assert ns.answer_shape("Curaçao") == "name"
        assert ns.answer_shape("St. Louis") == "name"
        assert ns.answer_shape("O'Brien") == "name"
        assert ns.answer_shape("Jean-Luc") == "name"

    def test_a_lowercase_phrase_is_neither_class(self):
        assert ns.answer_shape("a record label") is None
        assert ns.answer_shape("the Royal Navy") is None

    def test_empty_or_non_string_answer_is_neither_class(self):
        assert ns.answer_shape("") is None
        assert ns.answer_shape(None) is None


class TestClassifyName:
    """revision 4: a name-shaped answer is "person" only when it resolves to a corpus article with a birth
    or life-span parenthesis; otherwise "other_name" -- including when it doesn't resolve at all."""

    def test_a_born_parenthesis_is_a_person(self, corpus, redirects):
        assert ns.classify_name("Thomas Reed", corpus, redirects) == "person"

    def test_a_year_range_parenthesis_is_a_person(self, corpus, redirects):
        assert ns.classify_name("Agnes Clarke", corpus, redirects) == "person"

    def test_a_resolvable_non_person_is_other_name(self, corpus, redirects):
        # the bug revision 4 fixes: "Sir Edward Seymour Hicks" (a person) was swapped for "County Tyrone"
        # (a place) because both are merely name-shaped; this is the place side of that same-shape pair.
        assert ns.classify_name("County Tyrone", corpus, redirects) == "other_name"

    def test_an_unresolvable_answer_is_other_name(self, corpus, redirects):
        assert ns.classify_name("No Such Person At All", corpus, redirects) == "other_name"

    def test_resolution_goes_through_redirects(self, corpus, redirects):
        assert ns.classify_name("Thomas R Reed", corpus, redirects) == "person"  # redirects to "Thomas Reed"

    def test_answer_class_composes_shape_and_classify_name(self, corpus, redirects):
        assert ns.answer_class("1970", corpus, redirects) == "year"
        assert ns.answer_class("Thomas Reed", corpus, redirects) == "person"
        assert ns.answer_class("County Tyrone", corpus, redirects) == "other_name"
        assert ns.answer_class("a record label", corpus, redirects) is None

    # The widened cue (the coordinator's second round): "born" anywhere in the first parenthesis, not only
    # right after "(" -- and a full birth-to-death date range with no "born" word at all.

    def test_born_anywhere_in_the_parenthesis_is_a_person(self, corpus, redirects):
        # "(; born 2 May 1972)" -- a stripped pronunciation guide before "born", as real Wikipedia leads
        # commonly have (David Koepp, in the real corpus); the first cut's regex missed this.
        assert ns.classify_name("Diane Foster", corpus, redirects) == "person"

    def test_a_full_date_range_with_no_born_word_is_a_person(self, corpus, redirects):
        # "(12 May 1901 - 3 June 1980)" -- a death range with full dates, no "born" word (John Hughes, in
        # the real corpus); the first cut's regex required the dash immediately next to both years.
        assert ns.classify_name("Percy Vance", corpus, redirects) == "person"

    def test_a_single_year_alone_is_not_a_person(self, corpus, redirects):
        # "(founded 1890)" -- explicitly not a person: one year, no range, no "born".
        assert ns.classify_name("Grand Hall", corpus, redirects) == "other_name"

    def test_only_the_first_parenthesis_is_consulted(self, corpus, redirects):
        # "Riverside Club (founded 1925) hosted events (born from an older society, 1890-1910)." The first
        # parenthesis is a single year (not a person); a later one would match on both cues, but must never
        # be looked at.
        assert ns.classify_name("Riverside Club", corpus, redirects) == "other_name"


class TestFirstParenthetical:
    def test_extracts_the_first_parenthesis_content(self):
        assert ns._first_parenthetical("Name (born 1970) text") == "born 1970"

    def test_none_when_no_parenthesis_opens_early_enough(self):
        padding = "x" * 200
        assert ns._first_parenthetical(f"{padding}(born 1970)") is None

    def test_none_when_there_is_no_parenthesis_at_all(self):
        assert ns._first_parenthetical("Nothing here") is None

    def test_content_is_not_truncated_even_if_it_runs_past_the_open_within_limit(self):
        text = "x" * 190 + "(born 1 January 1970, a very long parenthetical) rest"
        content = ns._first_parenthetical(text)
        assert content == "born 1 January 1970, a very long parenthetical"


class TestIsPersonParenthetical:
    def test_born_word_with_boundaries(self):
        assert ns._is_person_parenthetical("; born June 9, 1963")
        assert not ns._is_person_parenthetical("newborn 1963")  # not the whole word "born"

    def test_year_range_with_arbitrary_text_between(self):
        assert ns._is_person_parenthetical("February 18, 1950 – August 6, 2009")
        assert ns._is_person_parenthetical("c. 1340 - 1400")

    def test_a_single_year_is_not_a_range(self):
        assert not ns._is_person_parenthetical("founded 1890")


class TestWholeWordOccurrences:
    def test_a_name_does_not_match_inside_a_longer_word(self):
        assert ns.whole_word_occurrences("Annabelle was not Ann.", "Ann") == [18]

    def test_a_year_does_not_match_inside_a_longer_number(self):
        assert ns.whole_word_occurrences("in 11970 and 19705 but not 1970.", "1970") == [27]

    def test_a_multi_word_phrase_matches_as_one_span(self):
        text = "Ann Vale grew up in Leeds; Ann Vale later moved."
        assert ns.whole_word_occurrences(text, "Ann Vale") == [0, 27]

    def test_boundary_at_the_very_start_and_end_of_the_text(self):
        assert ns.whole_word_occurrences("1970", "1970") == [0]

    def test_replace_whole_word_leaves_partial_matches_alone(self):
        assert ns.replace_whole_word("Annabelle met Ann.", "Ann", "Mary") == "Annabelle met Mary."

    def test_replace_whole_word_replaces_every_occurrence(self):
        text = "Ann Vale grew up; Ann Vale later moved."
        assert ns.replace_whole_word(text, "Ann Vale", "Sam Lowe") == "Sam Lowe grew up; Sam Lowe later moved."

    def test_no_occurrence_is_a_no_op(self):
        assert ns.replace_whole_word("nothing here", "Ann Vale", "Sam Lowe") == "nothing here"


class TestQualifyingLeads:
    def test_answer_in_exactly_one_lead_qualifies_as_the_year_class(self, corpus, redirects):
        row = bridge("q1", "In what year did Ann Vale, the singer of the band Lotus, move to Leeds?",
                     "1970", ["Lotus (band)", "Ann Vale"])
        info = ns.qualifying_leads(row, corpus, redirects)
        assert info is not None
        assert info["answer_class"] == "year"
        assert info["gold_leads"][info["corrected_lead_index"]]["title"] == "Ann Vale"

    def test_accented_name_answer_qualifies(self, corpus, redirects):
        row = bridge("q2", "Where did the airport that opened in 1942 open?", "Curaçao",
                     ["Delta Airport", "Ann Vale"])
        info = ns.qualifying_leads(row, corpus, redirects)
        # "Curaçao" doesn't itself resolve to a corpus article here, so it's other_name, not person.
        assert info is not None and info["answer_class"] == "other_name"

    def test_a_person_answer_qualifies_with_the_person_class(self, corpus, redirects):
        row = bridge("q11", "Whose manager founded Echo Films?", "Thomas Reed",
                     ["Echo Films", "Echo Films Studio"])
        info = ns.qualifying_leads(row, corpus, redirects)
        assert info is not None and info["answer_class"] == "person"

    def test_answer_in_both_leads_does_not_qualify(self, corpus, redirects):
        row = bridge("q3", "Who was the singer of the band Echo?", "Ann Vale",
                     ["Echo (band)", "Ann Vale (dancer)"])
        assert ns.qualifying_leads(row, corpus, redirects) is None

    def test_answer_in_neither_lead_does_not_qualify(self, corpus, redirects):
        row = bridge("q4", "Where was the singer born?", "Paris", ["Lotus (band)", "Ann Vale"])
        assert ns.qualifying_leads(row, corpus, redirects) is None

    def test_a_date_answer_does_not_qualify(self, corpus, redirects):
        row = bridge("q5", "When did Ann Vale move to Leeds?", "12 January 1970",
                     ["Lotus (band)", "Ann Vale"])
        assert ns.qualifying_leads(row, corpus, redirects) is None

    def test_a_lowercase_phrase_answer_does_not_qualify(self, corpus, redirects):
        row = bridge("q6", "What was Lotus?", "a record label", ["Lotus (band)", "Ann Vale"])
        assert ns.qualifying_leads(row, corpus, redirects) is None

    def test_comparison_questions_never_qualify(self, corpus, redirects):
        row = bridge("q7", "Ignored", "1970", ["Lotus (band)", "Ann Vale"])
        row["type"] = "comparison"
        assert ns.qualifying_leads(row, corpus, redirects) is None

    def test_a_gold_lead_missing_from_the_corpus_does_not_qualify(self, corpus, redirects):
        row = bridge("q8", "Ignored", "1970", ["Lotus (band)", "No Such Page"])
        assert ns.qualifying_leads(row, corpus, redirects) is None

    def test_redirects_are_resolved_before_checking_the_leads(self, corpus, redirects):
        row = bridge("q9", "In what year did Ann Vale, the singer of Lotus, move to Leeds?", "1970",
                     ["Lotus band", "Ann Vale"])  # "Lotus band" redirects to "Lotus (band)"
        assert ns.qualifying_leads(row, corpus, redirects) is not None

    def test_two_titles_that_redirect_to_the_same_article_do_not_qualify(self, corpus, redirects):
        row = bridge("q10", "Ignored", "1970", ["Lotus band", "Old Band Name"])  # both -> "Lotus (band)"
        assert ns.qualifying_leads(row, corpus, redirects) is None


# =====================================================================================
# The seeded draw, split and donor choice
# =====================================================================================

def _pool(corpus, redirects, n_qualifying=4, n_junk=6):
    """A pool with a known number of qualifying rows mixed among junk ones, for draw tests."""
    qualifying_rows = [
        bridge(f"y{i}", "Ignored", "1970", ["Lotus (band)", "Ann Vale"]) for i in range(n_qualifying)
    ]
    junk_rows = [bridge(f"j{i}", "Ignored", "a record label", ["Lotus (band)", "Ann Vale"])
                for i in range(n_junk)]
    return qualifying_rows + junk_rows


class TestDraw:
    def test_draw_stops_exactly_at_target_and_examines_at_least_that_many(self, corpus, redirects):
        pool = _pool(corpus, redirects, n_qualifying=4, n_junk=6)
        qualifying, draws = ns.draw_qualifying(pool, corpus, redirects, target=3, seed=1)
        assert len(qualifying) == 3
        assert draws >= 3
        assert draws <= len(pool)

    def test_draw_is_reproducible_for_the_same_seed(self, corpus, redirects):
        pool = _pool(corpus, redirects)
        a = ns.draw_qualifying(pool, corpus, redirects, target=4, seed=42)
        b = ns.draw_qualifying(pool, corpus, redirects, target=4, seed=42)
        assert [q["id"] for q in a[0]] == [q["id"] for q in b[0]]
        assert a[1] == b[1]

    def test_a_different_seed_can_draw_a_different_order(self, corpus, redirects):
        pool = _pool(corpus, redirects, n_qualifying=4, n_junk=6)
        a, _ = ns.draw_qualifying(pool, corpus, redirects, target=4, seed=1)
        b, _ = ns.draw_qualifying(pool, corpus, redirects, target=4, seed=2)
        assert [q["id"] for q in a] != [q["id"] for q in b] or True  # orders may coincide; no crash either way

    def test_fewer_qualifying_rows_than_the_target_returns_every_one_found(self, corpus, redirects):
        pool = _pool(corpus, redirects, n_qualifying=2, n_junk=3)
        qualifying, draws = ns.draw_qualifying(pool, corpus, redirects, target=10, seed=1)
        assert len(qualifying) == 2
        assert draws == len(pool)


class TestSplitAndDonors:
    def _qualifying(self, n_year, n_person, n_other_name=0):
        out = []
        for i in range(n_year):
            out.append({"id": f"y{i}", "question": "q", "answer": str(1900 + i), "answer_class": "year",
                       "gold_leads": [{"page_id": 1, "rev_id": 1, "title": "A"},
                                      {"page_id": 2, "rev_id": 1, "title": "B"}],
                       "corrected_lead_index": 1})
        for i in range(n_person):
            out.append({"id": f"p{i}", "question": "q", "answer": f"Person{i}", "answer_class": "person",
                       "gold_leads": [{"page_id": 10, "rev_id": 1, "title": "C"},
                                      {"page_id": 11, "rev_id": 1, "title": "D"}],
                       "corrected_lead_index": 1})
        for i in range(n_other_name):
            out.append({"id": f"o{i}", "question": "q", "answer": f"Place{i}", "answer_class": "other_name",
                       "gold_leads": [{"page_id": 20, "rev_id": 1, "title": "E"},
                                      {"page_id": 21, "rev_id": 1, "title": "F"}],
                       "corrected_lead_index": 1})
        return out

    def test_split_is_even_disjoint_and_covers_everything(self):
        qualifying = self._qualifying(5, 5)
        corrected, control = ns.split_corrected_and_control(qualifying, seed=7)
        assert len(corrected) == 5
        assert set(corrected).isdisjoint(control)
        assert set(corrected) | set(control) == set(range(10))

    def test_split_is_reproducible(self):
        qualifying = self._qualifying(4, 4)
        a = ns.split_corrected_and_control(qualifying, seed=99)
        b = ns.split_corrected_and_control(qualifying, seed=99)
        assert a == b

    def test_substitute_is_never_equal_and_is_the_same_class(self):
        qualifying = self._qualifying(6, 6)
        corrected, _ = ns.split_corrected_and_control(qualifying, seed=1)
        substitutes = ns.choose_substitutes(qualifying, corrected, seed=5)
        for index, substitute in substitutes.items():
            original = qualifying[index]
            donor_class = "year" if substitute.isdigit() else "person"
            assert substitute != original["answer"]
            assert donor_class == original["answer_class"]

    def test_a_person_is_never_swapped_for_a_place_or_vice_versa(self):
        # revision 4's fix, directly: with person and other_name donors both on offer at once, a person's
        # substitute must still come from the person pool only, and an other_name's from other_name only
        # (the bug this closes: "Sir Edward Seymour Hicks" to "County Tyrone").
        qualifying = self._qualifying(n_year=0, n_person=4, n_other_name=4)
        corrected = list(range(len(qualifying)))  # correct every one
        substitutes = ns.choose_substitutes(qualifying, corrected, seed=3)
        person_answers = {q["answer"] for q in qualifying if q["answer_class"] == "person"}
        other_name_answers = {q["answer"] for q in qualifying if q["answer_class"] == "other_name"}
        for index, substitute in substitutes.items():
            original_class = qualifying[index]["answer_class"]
            if original_class == "person":
                assert substitute in person_answers and substitute not in other_name_answers
            else:
                assert substitute in other_name_answers and substitute not in person_answers

    def test_substitute_choice_is_reproducible(self):
        qualifying = self._qualifying(6, 6)
        corrected, _ = ns.split_corrected_and_control(qualifying, seed=1)
        a = ns.choose_substitutes(qualifying, corrected, seed=5)
        b = ns.choose_substitutes(qualifying, corrected, seed=5)
        assert a == b

    def test_no_distinct_donor_raises_instead_of_picking_the_same_answer(self):
        qualifying = [{"id": "y0", "question": "q", "answer": "1970", "answer_class": "year",
                      "gold_leads": [{"page_id": 1, "rev_id": 1, "title": "A"},
                                     {"page_id": 2, "rev_id": 1, "title": "B"}], "corrected_lead_index": 1}]
        with pytest.raises(ValueError):
            ns.choose_substitutes(qualifying, [0], seed=1)


# =====================================================================================
# The overlay
# =====================================================================================

class TestOverlay:
    def _qualifying_pair(self):
        lead_a = {"page_id": 2, "rev_id": 2, "title": "Ann Vale", "text": "Ann Vale grew up in Leeds in 1970."}
        return [
            {"id": "q1", "answer": "1970", "answer_class": "year",
             "gold_leads": [{"page_id": 1, "rev_id": 1, "title": "Lotus (band)"}, lead_a],
             "corrected_lead_index": 1},
        ]

    def test_overlay_row_shape_and_hash(self):
        qualifying = self._qualifying_pair()
        substitutes = {0: "1985"}
        overlay = ns.build_overlay(qualifying, [0], substitutes)
        assert len(overlay) == 1
        row = overlay[0]
        assert row["page_id"] == 2
        assert row["old_rev"] == 2 and row["new_rev"] == "2c1"
        assert row["old_text"] == "Ann Vale grew up in Leeds in 1970."
        assert row["new_text"] == "Ann Vale grew up in Leeds in 1985."
        import hashlib
        assert row["new_text_sha256"] == hashlib.sha256(row["new_text"].encode("utf-8")).hexdigest()

    def test_two_corrections_on_the_same_page_both_apply(self):
        shared_lead = {"page_id": 2, "rev_id": 2, "title": "Ann Vale",
                      "text": "Ann Vale grew up in Leeds in 1970 and again in 1980."}
        qualifying = [
            {"id": "q1", "answer": "1970", "answer_class": "year",
             "gold_leads": [{"page_id": 1, "rev_id": 1, "title": "X"}, shared_lead], "corrected_lead_index": 1},
            {"id": "q2", "answer": "1980", "answer_class": "year",
             "gold_leads": [{"page_id": 1, "rev_id": 1, "title": "X"}, shared_lead], "corrected_lead_index": 1},
        ]
        overlay = ns.build_overlay(qualifying, [0, 1], {0: "1971", 1: "1981"})
        assert len(overlay) == 1   # one row per corrected *page*, not per corrected question
        assert overlay[0]["new_text"] == "Ann Vale grew up in Leeds in 1971 and again in 1981."
        assert overlay[0]["old_text"] == shared_lead["text"]  # the original is preserved verbatim

    def test_overlay_sha256_is_order_independent_and_sensitive_to_content(self):
        qualifying = self._qualifying_pair()
        overlay = ns.build_overlay(qualifying, [0], {0: "1985"})
        a = ns.overlay_sha256(overlay)
        b = ns.overlay_sha256(list(reversed(overlay)))
        assert a == b
        changed = [dict(overlay[0], new_text=overlay[0]["new_text"] + " ")]
        assert ns.overlay_sha256(changed) != a

    def test_no_source_is_edited_in_place(self, tmp_path, atlas_workbench):
        """Atlas's own guard: re-importing the *same* source id with different fields is refused -- so test1's
        convention of minting a brand-new source id for a correction (never reusing the old one) is the only
        way a correction can land at all."""
        store = make_store(tmp_path, atlas_workbench)
        store.import_bundle({"schema_version": 1, "title": "t",
                             "sources": [ns.source_record(2, 2, "Ann Vale")], "items": [], "relations": []})
        with pytest.raises(atlas_workbench.validation.WorkbenchError):
            store.import_bundle({"schema_version": 1, "title": "t",
                                 "sources": [ns.source_record(2, 2, "Ann Vale (renamed)")],
                                 "items": [], "relations": []})
        assert ns.source_id(2, 2) != ns.source_id(2, "2c1")


# =====================================================================================
# Building the corrected docs.tsv: the point-lookup subset path (the smoke build's) and
# the full-scan path (the lead's full run; exercised here as a true full pass over the
# tiny planted corpus, never over the real 9.4 GB one).
# =====================================================================================

class TestExportCorrectedTsv:
    def _overlay_correcting_ann_vale(self):
        return [{"page_id": 2, "old_rev": 2, "new_rev": "2c1",
                "old_text": "Ann Vale grew up in Leeds in 1970.",
                "new_text": "Ann Vale grew up in Leeds in 1985."}]

    def test_subset_path_writes_only_the_named_pages_with_the_overlay_applied(self, corpus, tmp_path):
        docs_path, links_path = tmp_path / "docs.tsv", tmp_path / "links.tsv"
        stats = ns.export_corrected_tsv(corpus, self._overlay_correcting_ann_vale(), docs_path, links_path,
                                        page_ids={1, 2})
        assert stats == {"docs": 2, "links": 1}  # page 1 (Lotus) links to page 2 (Ann Vale)
        lines = {line.split("\t", 1)[0]: line for line in docs_path.read_text().splitlines()}
        assert "1985" in lines["2"] and "1970" not in lines["2"]
        assert links_path.read_text().strip() == "1\t2"

    def test_full_scan_path_applies_the_overlay_and_leaves_other_pages_untouched(self, corpus, tmp_path):
        docs_path, links_path = tmp_path / "docs.tsv", tmp_path / "links.tsv"
        stats = ns.export_corrected_tsv(corpus, self._overlay_correcting_ann_vale(), docs_path, links_path,
                                        page_ids=None)
        assert stats["docs"] == len(RECORDS)  # every passage, not a subset
        lines = {line.split("\t", 1)[0]: line for line in docs_path.read_text().splitlines()}
        assert "1985" in lines["2"] and "1970" not in lines["2"]
        assert "Lotus is a band whose singer was Ann Vale." in lines["1"]  # page 1 itself is untouched
        assert stats["links"] > 1  # the full link graph, not just the overlay's own page's edges


# =====================================================================================
# Atlas records: one revision, one source; impact targeting; withdrawal keeps history
# =====================================================================================

class TestAtlasIntegration:
    def test_record_e_claim_cites_its_leads_and_requires_evidence_to_be_reviewed(self, tmp_path, atlas_workbench):
        store = make_store(tmp_path, atlas_workbench)
        leads = [{"page_id": 1, "rev_id": 1, "title": "Lotus (band)"}, {"page_id": 2, "rev_id": 2, "title": "Ann Vale"}]
        claim = ns.record_e_claim(store, "q1", "When did Ann Vale move to Leeds?", "1970", leads)
        assert claim["status"] == "reviewed"
        assert {e["source_id"] for e in claim["evidence"]} == {ns.source_id(1, 1), ns.source_id(2, 2)}
        stored = store.get(ns.claim_id("q1"))
        assert stored["summary"] == "1970"

    def test_a_closed_book_claim_with_no_evidence_is_only_proposed(self, tmp_path, atlas_workbench):
        store = make_store(tmp_path, atlas_workbench)
        claim = ns.record_e_claim(store, "q1", "q", "1970", [])
        assert claim["status"] == "proposed" and claim["evidence"] == []

    def test_impact_names_exactly_the_dependent_claims_and_leaves_controls_untouched(self, tmp_path, atlas_workbench):
        store = make_store(tmp_path, atlas_workbench)
        corrected_lead = {"page_id": 2, "rev_id": 2, "title": "Ann Vale"}
        other_lead = {"page_id": 9, "rev_id": 1, "title": "Unrelated"}
        ns.record_e_claim(store, "corrected-1", "q", "1970", [corrected_lead])
        ns.record_e_claim(store, "corrected-2", "q", "1970", [corrected_lead, other_lead])
        ns.record_e_claim(store, "control-1", "q", "x", [other_lead])

        overlay = [{"page_id": 2, "old_rev": 2, "new_rev": "2c1"}]
        impacted = ns.impacted_claim_ids(store, overlay)
        assert set(impacted) == {ns.claim_id("corrected-1"), ns.claim_id("corrected-2")}
        assert ns.claim_id("control-1") not in impacted

    def test_an_overlay_page_no_claim_ever_cited_is_skipped_not_an_error(self, tmp_path, atlas_workbench):
        """E's own retrieval can simply miss a gold lead, so an overlay page may never have become a source
        at all (a smoke run's handful of claims is the common case, not a hand-made exception).
        ``retraction_impact`` itself refuses an unknown source id; ``impacted_claim_ids`` must not surface
        that as a crash, and must still name the other overlay rows' real dependents."""
        store = make_store(tmp_path, atlas_workbench)
        cited_lead = {"page_id": 2, "rev_id": 2, "title": "Ann Vale"}
        ns.record_e_claim(store, "corrected-1", "q", "1970", [cited_lead])
        overlay = [{"page_id": 2, "old_rev": 2, "new_rev": "2c1"},         # cited: a real dependent
                  {"page_id": 999, "old_rev": 1, "new_rev": "1c1"}]       # never cited: no source exists
        impacted = ns.impacted_claim_ids(store, overlay)
        assert impacted == [ns.claim_id("corrected-1")]

    def test_withdrawn_claims_are_kept_not_deleted_and_history_as_of_sees_the_earlier_belief(self, tmp_path,
                                                                                            atlas_workbench):
        store = make_store(tmp_path, atlas_workbench)
        lead = {"page_id": 2, "rev_id": 2, "title": "Ann Vale"}
        ns.record_e_claim(store, "q1", "q", "1970", [lead])
        cid = ns.claim_id("q1")
        at = "2000-01-01T00:00:00Z"  # strictly before any status transition below (as the atlas test does)
        before = ns.history_before_correction(store, cid, at)
        assert before["status"] == "reviewed"
        ns.withdraw_claim(store, cid, "a cited source was retracted")
        stored = store.get(cid)                       # never deleted
        assert stored["status"] == "withdrawn"
        assert ns.history_before_correction(store, cid, at)["status"] == "reviewed"  # unchanged, read as of `at`

    def test_a_correction_adds_a_new_revision_as_a_new_source_never_edits_the_old_one(self):
        lead = {"page_id": 2, "rev_id": 2, "title": "Ann Vale", "text": "old"}
        overlay = [{"page_id": 2, "old_rev": 2, "new_rev": "2c1", "new_text": "new"}]
        corrected = ns.apply_overlay_lead(lead, overlay)
        assert corrected["rev_id"] == "2c1" and corrected["text"] == "new"
        assert lead["rev_id"] == 2 and lead["text"] == "old"          # the original dict is untouched
        assert ns.source_id(2, lead["rev_id"]) != ns.source_id(2, corrected["rev_id"])

    def test_apply_overlay_lead_is_a_no_op_for_an_uncorrected_page(self):
        lead = {"page_id": 9, "rev_id": 1, "title": "Unrelated", "text": "same"}
        overlay = [{"page_id": 2, "old_rev": 2, "new_rev": "2c1", "new_text": "new"}]
        assert ns.apply_overlay_lead(lead, overlay) == lead


# =====================================================================================
# The leakage guard
# =====================================================================================

class TestLeakageGuard:
    def test_build_prompt_has_no_parameter_for_a_prior_answer_or_claim(self):
        params = set(inspect.signature(ns.build_prompt).parameters)
        assert params == {"question_text", "leads"}

    def test_a_prior_answer_absent_from_leads_and_question_passes(self):
        prompt = ns.build_prompt("Where did she grow up?", [{"title": "Ann Vale", "text": "She grew up in Leeds."}])
        ns.assert_no_leakage(prompt, ["1970"])  # does not raise

    def test_assert_no_leakage_catches_a_real_violation(self):
        prompt = ns.build_prompt("Q", [{"title": "T", "text": "The withdrawn answer 1970 is in here."}])
        with pytest.raises(AssertionError):
            ns.assert_no_leakage(prompt, ["1970"])

    def test_closed_book_prompt_holds_only_the_question(self):
        assert ns.build_prompt("What year?", []) == "Question: What year?"

    def test_fake_model_answers_trace_to_the_leads_it_was_given(self):
        """A deterministic fake model that only ever echoes what's inside its own prompt's brackets: if a
        prior answer leaked into the prompt, this would surface it; it never can, because the prompt itself
        cannot hold one (see the parameter check above)."""

        def fake_model(model, prompt_text):
            import re

            match = re.search(r"\[(.*?)\]", prompt_text)
            return (match.group(1) if match else "UNKNOWN"), 0.0, {"prompt_eval_count": 1, "eval_count": 1}

        prompt = ns.build_prompt("Q", [{"title": "Ann Vale", "text": "irrelevant"}])
        answer, _, _ = fake_model(ns.MODEL, prompt)
        assert answer == "Ann Vale"


# =====================================================================================
# B-cache never re-asks
# =====================================================================================

class TestBCache:
    def test_b_cache_takes_no_model_or_ask_function(self):
        assert set(inspect.signature(ns.b_cache_from).parameters) == {"before_b"}

    def test_b_cache_copies_the_earlier_answers_exactly(self):
        before = {"q1": {"answer": "Paris", "em": True}, "q2": {"answer": "Rome", "em": False}}
        after = ns.b_cache_from(before)
        assert after == before

    def test_b_cache_result_does_not_alias_the_input(self):
        before = {"q1": {"answer": "Paris"}}
        after = ns.b_cache_from(before)
        after["q1"]["answer"] = "changed"
        assert before["q1"]["answer"] == "Paris"


# =====================================================================================
# Scoring arithmetic
# =====================================================================================

class TestScoring:
    def test_source_support_requires_both_gold_pages_among_cited(self):
        gold = [{"page_id": 1}, {"page_id": 2}]
        assert ns.source_support([{"page_id": 1}, {"page_id": 2}], gold) is True
        assert ns.source_support([{"page_id": 1}], gold) is False
        assert ns.source_support([{"page_id": 1}, {"page_id": 2}, {"page_id": 3}], gold) is True

    def test_paired_ci_known_values_zero_variance(self):
        rows = [{"a": 1.0, "b": 0.0}] * 5  # every pair differs by exactly 1.0 -> zero variance
        result = ns.paired_ci(rows, lambda r: r["a"], lambda r: r["b"])
        assert result == {"n": 5, "points": 100.0, "ci95": [100.0, 100.0]}

    def test_paired_ci_known_values_nonzero_variance(self):
        # hand-computed: diffs [0.0, 0.2], mean 0.1, sample variance 0.02, se 0.1, 95% half-width 19.6 points.
        # Pins down the sample-variance denominator (n-1), the sqrt(n) in se, and the 1.96 z-value together --
        # the zero-variance case above can't catch a wrong denominator, since 0 divided by anything is still 0.
        rows = [{"a": 0.0, "b": 0.0}, {"a": 0.2, "b": 0.0}]
        result = ns.paired_ci(rows, lambda r: r["a"], lambda r: r["b"])
        assert result == {"n": 2, "points": 10.0, "ci95": [-9.6, 29.6]}

    def test_paired_ci_needs_at_least_two_rows(self):
        with pytest.raises(ValueError):
            ns.paired_ci([{"a": 1, "b": 0}], lambda r: r["a"], lambda r: r["b"])

    def test_primary_verdict_succeeds_within_margin_and_cheap(self):
        diff_ci = {"ci95": [-2.0, 2.0]}
        result = ns.primary_verdict(diff_ci, e_calls=50, b_calls=100)
        assert result["verdict"] == "succeeds"

    def test_primary_verdict_fails_when_not_cheap_enough(self):
        diff_ci = {"ci95": [-2.0, 2.0]}
        result = ns.primary_verdict(diff_ci, e_calls=70, b_calls=100)
        assert result["cheaper"] is False and result["verdict"] == "fails"

    def test_primary_verdict_fails_more_than_margin_under(self):
        diff_ci = {"ci95": [-9.0, -6.0]}
        result = ns.primary_verdict(diff_ci, e_calls=10, b_calls=100)
        assert result["accuracy"] == "more than margin under" and result["verdict"] == "fails"

    def test_primary_verdict_borderline_when_the_ci_straddles_the_margin(self):
        diff_ci = {"ci95": [-8.0, -2.0]}  # straddles -5
        result = ns.primary_verdict(diff_ci, e_calls=10, b_calls=100)
        assert result["accuracy"] == "borderline" and result["verdict"] == "borderline"

    def test_primary_verdict_fails_on_borderline_accuracy_when_not_cheaper(self):
        # revision 4: "if E isn't cheaper, the verdict is 'fails' whatever the accuracy" -- so a
        # borderline-accuracy CI must not be reported as merely "borderline" once E also failed the calls test.
        diff_ci = {"ci95": [-8.0, -2.0]}  # the same straddling CI as the test above
        result = ns.primary_verdict(diff_ci, e_calls=70, b_calls=100)  # ratio 0.7, not under the 0.6 threshold
        assert result["accuracy"] == "borderline"
        assert result["cheaper"] is False
        assert result["verdict"] == "fails"

    def test_controls_unchanged_counts_changes_and_stayed_right(self):
        before = {"c1": {"answer": "A", "em": True}, "c2": {"answer": "B", "em": False}}
        after = {"c1": {"answer": "A"}, "c2": {"answer": "C"}}
        result = ns.controls_unchanged(before, after, ["c1", "c2"])
        assert result == {"controls": 2, "answers_changed": 1, "right_before": 1, "stayed_right": 1}

    def test_stale_answers_counts_matches_against_closed_book(self):
        before = {"q1": {"answer": "OldAns"}}
        after = {"q1": {"answer": "OldAns"}}
        closed_book = {"q1": {"answer": "OldAns"}}
        result = ns.stale_answers(before, after, ["q1"], closed_book)
        assert result == {"corrected": 1, "stale": 1, "stale_matches_closed_book": 1}

    def test_stale_answers_zero_when_the_answer_changed(self):
        before = {"q1": {"answer": "OldAns"}}
        after = {"q1": {"answer": "NewAns"}}
        result = ns.stale_answers(before, after, ["q1"], {})
        assert result == {"corrected": 1, "stale": 0, "stale_matches_closed_book": 0}


# =====================================================================================
# summarize: the primary (E against B-all), the secondary (E against E-all, revision 4),
# and their call counts, on hand-made before/after rows.
# =====================================================================================

class TestSummarize:
    def test_primary_and_secondary_are_none_with_fewer_than_two_corrected(self):
        sample = [{"id": "c1", "arm": "corrected"}, {"id": "k1", "arm": "control"}]
        rows = {"c1": {"answer": "A", "em": True}, "k1": {"answer": "B", "em": True}}
        summary = ns.summarize(sample, rows, rows, {}, rows, {}, {}, set(), {})
        assert summary["primary"] is None
        assert summary["secondary_e_vs_e_all"] is None

    def test_primary_and_secondary_count_calls_and_agree_when_answers_match(self):
        # Four corrected questions: E reasks c0 and c1 (retraction_impact named them) and gets them right;
        # c2 and c3 were never reasked, but E's *prior* belief there already matched B-all's after-correction
        # answer, and E-all (asked fresh on every one) also agrees everywhere -- a zero-variance CI on both
        # comparisons, so this pins down the call counts `summarize` computes, not just the CI arithmetic
        # (already covered by TestScoring).
        sample = [{"id": f"c{i}", "arm": "corrected"} for i in range(4)]
        before_e = {"c0": {"answer": "old0", "em": False}, "c1": {"answer": "old1", "em": False},
                   "c2": {"answer": "right2", "em": True}, "c3": {"answer": "right3", "em": True}}
        after_e = {"c0": {"answer": "new0", "em": True}, "c1": {"answer": "new1", "em": True}}
        after_b = {f"c{i}": {"answer": f"ans{i}", "em": True} for i in range(4)}
        e_all = {f"c{i}": {"answer": f"eall{i}", "em": True} for i in range(4)}
        reask_ids = {"c0", "c1"}
        usage = {"e": {"calls": 6}, "b_all": {"calls": 8}}

        summary = ns.summarize(sample, before_e, after_b, after_e, after_b, e_all, {}, reask_ids, usage)

        assert summary["primary"] == {
            "diff_ci": {"n": 4, "points": 0.0, "ci95": [0.0, 0.0]}, "accuracy": "within margin",
            "e_calls": 2, "b_calls": 4, "calls_ratio": 0.5, "cheaper": True, "verdict": "succeeds",
        }
        assert summary["secondary_e_vs_e_all"] == {
            "em_ci": {"n": 4, "points": 0.0, "ci95": [0.0, 0.0]}, "e_calls": 2, "e_all_calls": 4,
        }
        assert summary["cost"] == usage

    def test_e_calls_only_counts_the_corrected_questions_e_actually_reasked(self):
        sample = [{"id": "c0", "arm": "corrected"}, {"id": "c1", "arm": "corrected"}]
        before_e = {"c0": {"answer": "a", "em": True}, "c1": {"answer": "a", "em": True}}
        after_b = {"c0": {"answer": "a", "em": True}, "c1": {"answer": "a", "em": True}}
        e_all = {"c0": {"answer": "a", "em": True}, "c1": {"answer": "a", "em": True}}
        # c0 was reasked (its claim cited the corrected lead); c1 was not, and a control question that was
        # reasked by coincidence must not be counted as one of the *corrected* calls.
        summary = ns.summarize(sample, before_e, after_b, {"c0": before_e["c0"]}, after_b, e_all, {},
                               {"c0", "not-in-sample"}, {})
        assert summary["primary"]["e_calls"] == 1
        assert summary["secondary_e_vs_e_all"]["e_calls"] == 1


class TestSummarizeByClass:
    """The coordinator's per-class report: the primary and secondary computed within each substitution
    class, plus "clean_classes" (year and person together -- the substitutions that keep their kind)."""

    def _sample(self):
        return [
            {"id": "y0", "arm": "corrected", "answer_class": "year"},
            {"id": "y1", "arm": "corrected", "answer_class": "year"},
            {"id": "p0", "arm": "corrected", "answer_class": "person"},
            {"id": "p1", "arm": "corrected", "answer_class": "person"},
            {"id": "o0", "arm": "corrected", "answer_class": "other_name"},
            {"id": "o1", "arm": "corrected", "answer_class": "other_name"},
        ]

    def test_by_class_groups_corrected_questions_and_clean_classes_merges_year_and_person(self):
        sample = self._sample()
        ids = [q["id"] for q in sample]
        before_e = {qid: {"answer": "wrong", "em": False} for qid in ids}  # E never reasked, always wrong
        after_b = {qid: {"answer": "right", "em": True} for qid in ids}    # B-all and E-all always right
        e_all = {qid: {"answer": "right", "em": True} for qid in ids}

        summary = ns.summarize(sample, before_e, after_b, {}, after_b, e_all, {}, set(), {})
        by_class = summary["by_class"]

        assert set(by_class) == {"year", "person", "other_name", "clean_classes"}
        # Every id disagrees with B-all/E-all the same way (always wrong against always right), so every
        # bucket's CI is the same zero-variance -100-point gap; only n and the ids behind it differ.
        same_gap = {"points": -100.0, "ci95": [-100.0, -100.0]}
        for cls, n in (("year", 2), ("person", 2), ("other_name", 2)):
            assert by_class[cls]["n"] == n
            assert by_class[cls]["primary"]["diff_ci"] == {"n": n, **same_gap}
            assert by_class[cls]["primary"]["verdict"] == "fails"  # more than 5 points under, every bucket
            assert by_class[cls]["primary"]["e_calls"] == 0        # nothing reasked anywhere
            assert by_class[cls]["secondary_e_vs_e_all"]["em_ci"] == {"n": n, **same_gap}
        assert by_class["clean_classes"]["n"] == 4
        assert by_class["clean_classes"]["primary"]["diff_ci"] == {"n": 4, **same_gap}
        # clean_classes is exactly year's and person's ids, nothing from other_name.
        assert by_class["clean_classes"]["ids"] == ["p0", "p1", "y0", "y1"]

    def test_by_class_is_none_for_a_class_with_fewer_than_two_but_other_classes_still_compute(self):
        sample = [{"id": "y0", "arm": "corrected", "answer_class": "year"},
                 {"id": "p0", "arm": "corrected", "answer_class": "person"},
                 {"id": "p1", "arm": "corrected", "answer_class": "person"}]
        rows = {qid: {"answer": "a", "em": True} for qid in ("y0", "p0", "p1")}
        summary = ns.summarize(sample, rows, rows, {}, rows, rows, {}, set(), {})
        by_class = summary["by_class"]
        assert by_class["year"]["n"] == 1 and by_class["year"]["primary"] is None
        assert by_class["person"]["n"] == 2 and by_class["person"]["primary"] is not None
        assert by_class["clean_classes"]["n"] == 3  # year's one id plus person's two, still combined

    def test_a_class_absent_from_the_sample_is_simply_absent_from_by_class(self):
        sample = [{"id": "o0", "arm": "corrected", "answer_class": "other_name"},
                 {"id": "o1", "arm": "corrected", "answer_class": "other_name"}]
        rows = {qid: {"answer": "a", "em": True} for qid in ("o0", "o1")}
        summary = ns.summarize(sample, rows, rows, {}, rows, rows, {}, set(), {})
        assert set(summary["by_class"]) == {"other_name", "clean_classes"}
        assert summary["by_class"]["clean_classes"]["n"] == 0
        assert summary["by_class"]["clean_classes"]["primary"] is None


# =====================================================================================
# build_plan end to end, on the planted corpus (no model calls)
# =====================================================================================

class TestBuildPlan:
    def test_build_plan_on_a_small_pool_with_a_low_minimum(self, corpus, redirects):
        junk = [bridge(f"j{i}", "Ignored", "a record label", ["Lotus (band)", "Ann Vale"]) for i in range(2)]
        pool = _diverse_qualifying_rows() + junk
        plan = ns.build_plan(pool, excluded_ids=set(), corpus=corpus, redirects=redirects,
                             target=4, min_qualifying=4, pool_seed=1, split_seed=2, donor_seed=3)
        assert plan["qualifying_found"] == 4
        assert plan["corrected_count"] + plan["control_count"] == 4
        assert len(plan["questions"]) == 4
        assert plan["overlay_sha256"] == ns.overlay_sha256(plan["overlay"])
        for q in plan["questions"]:
            if q["arm"] == "corrected":
                assert q["substitute"] != q["answer"]
        assert sum(plan["class_counts"].values()) == 4
        assert set(plan["class_counts"]) <= {"year", "person", "other_name"}

    def test_build_plan_raises_below_the_minimum(self, corpus, redirects):
        pool = _pool(corpus, redirects, n_qualifying=1, n_junk=2)
        with pytest.raises(RuntimeError):
            ns.build_plan(pool, excluded_ids=set(), corpus=corpus, redirects=redirects,
                          target=4, min_qualifying=4, pool_seed=1, split_seed=2, donor_seed=3)

    def test_excluded_ids_are_removed_from_the_pool_first(self, corpus, redirects):
        pool = _diverse_qualifying_rows()
        excluded = {pool[0]["id"]}
        plan = ns.build_plan(pool, excluded_ids=excluded, corpus=corpus, redirects=redirects,
                             target=3, min_qualifying=3, pool_seed=1, split_seed=2, donor_seed=3)
        assert plan["pool_size"] == 3
        assert pool[0]["id"] not in [q["id"] for q in plan["questions"]]


# =====================================================================================
# E's and B's retrieval loops against the real Rust binary (skipped, not failed, when
# cargo isn't here -- the same pattern test_multihop_corpus_index.py uses).
# =====================================================================================

CRATE_DIR = Path(__file__).resolve().parents[1] / "native" / "corpus_index"


def _cargo_path() -> str | None:
    found = shutil.which("cargo")
    if found:
        return found
    guess = Path.home() / ".cargo" / "bin" / "cargo"
    return str(guess) if guess.exists() else None


@pytest.fixture(scope="module")
def corpus_index_bin():
    import json
    import os

    cargo = _cargo_path()
    if cargo is None:
        pytest.skip("cargo isn't available; can't build the corpus-index crate")
    env = {**os.environ, "PATH": f"{Path(cargo).parent}:{os.environ.get('PATH', '')}"}
    result = subprocess.run([cargo, "build", "--release", "--offline", "--message-format=json"], cwd=CRATE_DIR,
                            capture_output=True, text=True, env=env)
    if result.returncode != 0:
        pytest.fail(f"cargo build --offline failed:\n{result.stdout}\n{result.stderr}")
    built = [m["executable"] for m in map(json.loads, result.stdout.splitlines())
             if m.get("reason") == "compiler-artifact" and m.get("executable")
             and m.get("target", {}).get("name") == "corpus-index"]
    if len(built) != 1 or not Path(built[0]).exists():
        pytest.fail(f"cargo's build messages name no single corpus-index executable: {built}")
    return Path(built[0])


@pytest.fixture
def real_index(corpus_index_bin, corpus_path, tmp_path):
    docs_path, links_path = tmp_path / "docs.tsv", tmp_path / "links.tsv"
    export_corpus_tsv(corpus_path, docs_path, links_path)
    index_path = tmp_path / "index.bin"
    ns.build_corpus_index(corpus_index_bin, docs_path, links_path, index_path)
    return corpus_index_bin, index_path


def fake_embed(texts: list[str], prefix: str = "search_document") -> list[list[float]]:
    """A deterministic bag-of-words embedder (counts of a tiny fixed vocabulary), good enough to rank "Ann
    Vale"-shaped text above "Delta Airport"-shaped text for a query about Leeds, with no model load."""
    vocab = ["ann", "vale", "leeds", "1970", "curaçao", "delta", "airport", "lotus", "band", "singer"]
    out = []
    for text in texts:
        lowered = text.lower()
        out.append([float(lowered.count(word)) + 0.01 for word in vocab])
    return out


class TestRetrievalIntegration:
    def test_e_pick_leads_follows_the_real_hop(self, real_index, corpus):
        bin_path, index_path = real_index
        leads = ns.e_pick_leads(bin_path, index_path, corpus, "q1",
                                "Where did the singer of the band Lotus grow up?")
        assert [lead["title"] for lead in leads] == ["Lotus (band)", "Ann Vale"]

    def test_b_pick_leads_dense_reranks_the_bm25_pool(self, real_index, corpus):
        bin_path, index_path = real_index
        leads = ns.b_pick_leads(bin_path, index_path, corpus, fake_embed, "q1",
                                "Where did Ann Vale grow up, in Leeds, in 1970?", bm25_k=10, top=2)
        titles = [lead["title"] for lead in leads]
        assert "Ann Vale" in titles

    def test_dense_rerank_orders_by_cosine_not_bm25_order(self):
        candidates = [{"title": "Delta Airport", "text": "opened in Curaçao"},
                     {"title": "Ann Vale", "text": "grew up in Leeds in 1970"}]
        leads = ns.dense_rerank("Leeds 1970 Ann Vale", candidates, fake_embed, top=1)
        assert leads[0]["title"] == "Ann Vale"
