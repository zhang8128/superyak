"""North-star test 2's pieces: the draw, the seven arms' pool construction, the scoring (each pinned to
what it compares against -- test 1's bug was exactly this), the primary verdict, and the coupling between
G's and W's pools. No model, no network, no full corpus; the cargo-built real corpus-index binary is used
only for the small set of true end-to-end integration tests, following test_northstar_test1.py's pattern.
"""
from __future__ import annotations

import inspect
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from tests.multihop_atlas import research_corpus

from experiments.northstar import test2 as ns2

RECORDS = [
    # A bridge pair for the draw/qualifying tests (test 1's own fixture shape).
    {"title": "Lotus (band)", "page_id": 1, "rev_id": 1,
     "text": "Lotus is a band whose singer was Ann Vale.", "links": ["Ann Vale"]},
    {"title": "Ann Vale", "page_id": 2, "rev_id": 2,
     "text": "Ann Vale grew up in Leeds in 1970.", "links": []},
    # A page linking to a "silent" page that shares no words with any query below, so it can only ever
    # enter a pool through the hop, never through BM25 -- the coupling tests' fixture.
    {"title": "Alpha Band", "page_id": 3, "rev_id": 1,
     "text": "Alpha Band is a music group from Bristol.", "links": ["Silent Target"]},
    {"title": "Silent Target", "page_id": 4, "rev_id": 1,
     "text": "Zyzzyx qqwwee flibber jibber unrelated gibberish placeholder filler nonsense.", "links": []},
    {"title": "Beta Band", "page_id": 5, "rev_id": 1, "text": "Beta Band is another music group.", "links": []},
]


@pytest.fixture
def corpus_path(tmp_path):
    path = tmp_path / "corpus.sqlite3"
    research_corpus().build(RECORDS, {"id": "t", "name": "T", "snapshot": "2026-11-07",
                                      "question_derived": False}, path)
    return path


@pytest.fixture
def corpus(corpus_path):
    return ns2.CorpusLookup.open(corpus_path)


@pytest.fixture
def redirects(tmp_path):
    db = sqlite3.connect(tmp_path / "r.sqlite3")
    db.execute("CREATE TABLE r (title TEXT PRIMARY KEY, target TEXT NOT NULL) WITHOUT ROWID")
    db.commit()
    return db


def bridge(qid, question, answer, gold):
    return {"id": qid, "question": question, "answer": answer, "type": "bridge",
            "supporting_facts": {"title": gold, "sent_id": [0] * len(gold)}}


def make_q(answer="1970", answer_lead_index=1):
    return {"answer": answer, "answer_lead_index": answer_lead_index,
           "gold_leads": [{"page_id": 1, "rev_id": 1, "title": "A"}, {"page_id": 2, "rev_id": 2, "title": "B"}]}


# =====================================================================================
# load_excluded_ids: reads either a "rows" key (the fresh-router files) or "questions"
# (test 1's own plan file) -- the spec's reviewer finding 4.
# =====================================================================================

class TestLoadExcludedIds:
    def test_reads_a_rows_key(self, tmp_path):
        path = tmp_path / "a.json"
        path.write_text(json.dumps({"rows": [{"id": "x1"}, {"id": "x2"}]}))
        assert ns2.load_excluded_ids([str(path)]) == {"x1", "x2"}

    def test_reads_a_questions_key(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text(json.dumps({"questions": [{"id": "y1"}, {"id": "y2"}]}))
        assert ns2.load_excluded_ids([str(path)]) == {"y1", "y2"}

    def test_unions_several_files_of_either_kind(self, tmp_path):
        a, b = tmp_path / "a.json", tmp_path / "b.json"
        a.write_text(json.dumps({"rows": [{"id": "x1"}]}))
        b.write_text(json.dumps({"questions": [{"id": "y1"}]}))
        assert ns2.load_excluded_ids([str(a), str(b)]) == {"x1", "y1"}


# =====================================================================================
# The draw: reuses test 1's qualifying_leads as-is.
# =====================================================================================

def comparison(qid, question, answer, gold):
    return {"id": qid, "question": question, "answer": answer, "type": "comparison",
            "supporting_facts": {"title": gold, "sent_id": [0] * len(gold)}}


class TestQualifyingLeadsByType:
    def test_a_bridge_row_qualifies_with_qtype_bridge(self, corpus, redirects):
        row = bridge("q1", "Ignored", "1970", ["Lotus (band)", "Ann Vale"])
        assert ns2.qualifying_leads_by_type(row, corpus, redirects, qtype="bridge") is not None

    def test_a_comparison_row_qualifies_with_qtype_comparison(self, corpus, redirects):
        # The reviewer's finding: test1.py's own qualifying_leads hardcodes "bridge" and would qualify 0
        # comparison rows; the parameterized rule must accept one with otherwise the same shape.
        row = comparison("q2", "Ignored", "1970", ["Lotus (band)", "Ann Vale"])
        info = ns2.qualifying_leads_by_type(row, corpus, redirects, qtype="comparison")
        assert info is not None
        assert info["answer_class"] == "year"

    def test_a_bridge_row_never_qualifies_as_comparison_and_vice_versa(self, corpus, redirects):
        bridge_row = bridge("q1", "Ignored", "1970", ["Lotus (band)", "Ann Vale"])
        comparison_row = comparison("q2", "Ignored", "1970", ["Lotus (band)", "Ann Vale"])
        assert ns2.qualifying_leads_by_type(bridge_row, corpus, redirects, qtype="comparison") is None
        assert ns2.qualifying_leads_by_type(comparison_row, corpus, redirects, qtype="bridge") is None


class TestDraw:
    def test_draws_qualifying_bridge_questions_by_seed(self, corpus, redirects):
        pool = [bridge(f"q{i}", "Ignored", "1970", ["Lotus (band)", "Ann Vale"]) for i in range(6)]
        qualifying, draws, own_draws = ns2.draw_qualifying_by_type(pool, corpus, redirects, qtype="bridge",
                                                                   target=3, seed=1)
        assert len(qualifying) == 3
        assert draws >= 3
        assert own_draws <= draws  # every pool row here is "bridge", but the inequality must hold in general

    def test_is_reproducible_for_the_same_seed(self, corpus, redirects):
        pool = [bridge(f"q{i}", "Ignored", "1970", ["Lotus (band)", "Ann Vale"]) for i in range(6)]
        a, _, _ = ns2.draw_qualifying_by_type(pool, corpus, redirects, qtype="bridge", target=3, seed=7)
        b, _, _ = ns2.draw_qualifying_by_type(pool, corpus, redirects, qtype="bridge", target=3, seed=7)
        assert [q["id"] for q in a] == [q["id"] for q in b]

    def test_draws_qualifying_comparison_questions_by_its_own_seed(self, corpus, redirects):
        pool = [comparison(f"c{i}", "Ignored", "1970", ["Lotus (band)", "Ann Vale"]) for i in range(6)]
        qualifying, draws, own_draws = ns2.draw_qualifying_by_type(pool, corpus, redirects, qtype="comparison",
                                                                   target=3, seed=ns2.COMPARISON_SEED)
        assert len(qualifying) == 3
        assert all(q["type"] == "comparison" for q in qualifying)

    def test_own_type_draws_counts_only_rows_of_the_stratum_s_own_type(self, corpus, redirects):
        # A pool where comparison rows are a small minority: own_type_draws must count only those,
        # never the many bridge rows examined and skipped along the way.
        pool = ([bridge(f"b{i}", "Ignored", "1970", ["Lotus (band)", "Ann Vale"]) for i in range(20)]
               + [comparison(f"c{i}", "Ignored", "1970", ["Lotus (band)", "Ann Vale"]) for i in range(3)])
        qualifying, draws, own_draws = ns2.draw_qualifying_by_type(pool, corpus, redirects, qtype="comparison",
                                                                   target=3, seed=1)
        assert len(qualifying) == 3
        assert own_draws == 3   # every comparison row here qualifies, so own_draws == qualifying_found
        assert own_draws < draws  # strictly fewer than the total, since bridge rows were examined too

    def test_a_mixed_pool_never_crosses_bridge_and_comparison_draws(self, corpus, redirects):
        # The coordinator's disjointness test: with both types in the same pool, each draw's own type
        # filter keeps every one of its own rows, and admits nothing of the other's.
        pool = ([bridge(f"b{i}", "Ignored", "1970", ["Lotus (band)", "Ann Vale"]) for i in range(5)]
               + [comparison(f"c{i}", "Ignored", "1970", ["Lotus (band)", "Ann Vale"]) for i in range(5)])
        bridge_drawn, _, _ = ns2.draw_qualifying_by_type(pool, corpus, redirects, qtype="bridge", target=5, seed=1)
        comparison_drawn, _, _ = ns2.draw_qualifying_by_type(pool, corpus, redirects, qtype="comparison",
                                                             target=5, seed=2)
        bridge_ids = {q["id"] for q in bridge_drawn}
        comparison_ids = {q["id"] for q in comparison_drawn}
        assert bridge_ids.isdisjoint(comparison_ids)
        assert all(qid.startswith("b") for qid in bridge_ids)
        assert all(qid.startswith("c") for qid in comparison_ids)


# =====================================================================================
# G's pool (BM25 base plus the top-5 seeds' out-links) and W's (BM25 alone, size-matched)
# -- pure functions, tested with a minimal links stand-in, no cargo binary needed.
# =====================================================================================

class FakeLinks:
    """A minimal stand-in for CorpusLookup: only links_from, by page id."""

    def __init__(self, links: dict[int, list[int]]):
        self._links = links

    def links_from(self, page_id: int) -> list[int]:
        return self._links.get(page_id, [])


class TestGPool:
    def test_base_pool_comes_first_then_new_outlinks_in_first_seen_order(self):
        links = {1: [10, 11], 2: [11, 12], 3: [], 4: [], 5: [13]}
        bm25_ids = [1, 2, 3, 4, 5, 6, 7]
        pool = ns2.g_pool_ids(bm25_ids, FakeLinks(links), base_k=7, seeds=5)
        assert pool == [1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13]

    def test_only_the_top_seeds_outlinks_are_added_not_the_rest_of_the_base_pool(self):
        links = {6: [999]}  # id 6 is in the base pool but not among the top-5 seeds
        bm25_ids = [1, 2, 3, 4, 5, 6, 7]
        pool = ns2.g_pool_ids(bm25_ids, FakeLinks(links), base_k=7, seeds=5)
        assert 999 not in pool

    def test_g_pool_contains_every_one_of_the_top_5s_outlinks(self):
        # The coordinator's guard: G's pool really contains the top 5's out-links.
        links = {1: [100], 2: [101], 3: [102], 4: [103], 5: [104], 6: [999]}
        bm25_ids = list(range(1, 11))
        pool = set(ns2.g_pool_ids(bm25_ids, FakeLinks(links), base_k=10, seeds=5))
        for seed_id in bm25_ids[:5]:
            for dst in links[seed_id]:
                assert dst in pool
        assert 999 not in pool  # id 6's outlink: 6 isn't one of the top 5

    def test_a_link_back_into_the_base_pool_is_not_duplicated(self):
        links = {1: [2, 3]}  # 2 and 3 are already in the base pool
        bm25_ids = [1, 2, 3]
        pool = ns2.g_pool_ids(bm25_ids, FakeLinks(links), base_k=3, seeds=5)
        assert pool == [1, 2, 3]

    def test_real_corpus_links_from_feeds_g_pool_correctly(self, corpus):
        # Using the real (tiny) corpus's own links table, not the fake: Alpha Band's only out-link,
        # "Silent Target," shares no words with any query, so it can only ever enter through the hop.
        bm25_ids = [3, 5, 1, 2, 4]  # Alpha Band (3) is among the top 5 seeds
        pool = ns2.g_pool_ids(bm25_ids, corpus, base_k=5, seeds=5)
        assert 4 in pool  # Silent Target's page id


class TestWPool:
    def test_w_pool_is_exactly_the_top_n(self):
        big = list(range(1, 51))
        w = ns2.w_pool_ids(big, 23)
        assert len(w) == 23
        assert w == big[:23]

    def test_w_pool_size_matches_the_given_n_when_enough_candidates_exist(self):
        big = list(range(1, 200))
        for n in (1, 50, 126, 199):
            assert len(ns2.w_pool_ids(big, n)) == n

    def test_w_pool_is_shorter_than_n_when_bm25_has_fewer_candidates_never_padded(self):
        small = [1, 2, 3]
        w = ns2.w_pool_ids(small, 10)
        assert len(w) == 3
        assert w == small


class TestBuildPlan:
    def _query_fn(self, items, k):
        return {qid: (list(range(1, 10)), [1, 2]) for qid, _ in items}

    def test_build_plan_computes_both_strata_disjointly(self, corpus, redirects):
        bridge_rows = [bridge(f"b{i}", "Ignored", "1970", ["Lotus (band)", "Ann Vale"]) for i in range(5)]
        comparison_rows = [comparison(f"c{i}", "Ignored", "1970", ["Lotus (band)", "Ann Vale"]) for i in range(5)]
        plan = ns2.build_plan(bridge_rows + comparison_rows, set(), corpus, redirects, query_fn=self._query_fn,
                              target=3, min_qualifying=3, seed=1,
                              comparison_target=3, min_comparison_qualifying=3, comparison_seed=2)
        assert plan["qualifying_found"] == 3
        assert plan["comparison_qualifying_found"] == 3
        assert len(plan["questions"]) == 3
        assert len(plan["comparison_questions"]) == 3
        bridge_ids = {q["id"] for q in plan["questions"]}
        comparison_ids = {q["id"] for q in plan["comparison_questions"]}
        assert bridge_ids.isdisjoint(comparison_ids)
        assert all(q["id"].startswith("b") for q in plan["questions"])
        assert all(q["id"].startswith("c") for q in plan["comparison_questions"])
        for q in plan["questions"] + plan["comparison_questions"]:
            assert isinstance(q["g_pool_size"], int) and isinstance(q["w_pool_size"], int)

    def test_build_plan_raises_when_the_comparison_pool_is_too_thin(self, corpus, redirects):
        comparison_rows = [comparison(f"c{i}", "Ignored", "1970", ["Lotus (band)", "Ann Vale"]) for i in range(2)]
        with pytest.raises(RuntimeError):
            ns2.build_plan(comparison_rows, set(), corpus, redirects, query_fn=self._query_fn,
                          target=3, min_qualifying=0,  # the bridge draw finds none, but 0 is allowed
                          comparison_target=3, min_comparison_qualifying=3, comparison_seed=2)


class TestComputePools:
    def _query_fn(self, calls_log=None):
        def query_fn(items, k):
            if calls_log is not None:
                calls_log.append(k)
            return {qid: (list(range(1, 300)), [1, 2]) for qid, _ in items}
        return query_fn

    def test_w_pool_size_equals_g_pool_size_per_question(self):
        # The coordinator's guard, at the orchestration level: W's N always comes from G's own size.
        links = {i: [1000 + i] for i in range(1, 6)}
        pools = ns2.compute_pools(self._query_fn(), FakeLinks(links), [("q1", "text")], base_k=10, hop_seeds=5)
        g, w = pools["q1"]["g_pool"], pools["q1"]["w_pool"]
        assert len(w) == len(g)
        assert not pools["q1"]["w_short"]

    def test_only_queries_twice_when_some_question_s_g_pool_exceeds_base_k(self):
        calls: list[int] = []
        links = {i: [1000 + i] for i in range(1, 6)}  # 5 new outlinks: G pool = 10 + 5 = 15 > base_k
        ns2.compute_pools(self._query_fn(calls), FakeLinks(links), [("q1", "text")], base_k=10, hop_seeds=5)
        assert calls == [10, 15]

    def test_queries_once_when_no_question_s_g_pool_exceeds_base_k(self):
        calls: list[int] = []
        ns2.compute_pools(self._query_fn(calls), FakeLinks({}), [("q1", "text")], base_k=10, hop_seeds=5)
        assert calls == [10]

    def test_the_larger_pass_covers_every_question_s_own_n_at_once(self):
        # q1's top-5 seeds (1..5) have no out-links at all, so its G pool is just the base 10. q2's top-5
        # seeds (101..105) add 4 new out-links, so its G pool is 14 -- the larger of the two, and the one
        # pass's --k must be sized to it, serving both questions' own N from the one call.
        calls: list[int] = []
        links = {101: [1001], 102: [1002, 1003, 1004]}
        def query_fn(items, k):
            calls.append(k)
            return {"q1": (list(range(1, 300)), []), "q2": (list(range(101, 400)), [])}
        pools = ns2.compute_pools(query_fn, FakeLinks(links), [("q1", "t1"), ("q2", "t2")], base_k=10, hop_seeds=5)
        assert calls == [10, 14]  # one big pass, sized to the largest G pool (q2's 10 base + 4 new outlinks)
        assert len(pools["q1"]["w_pool"]) == len(pools["q1"]["g_pool"]) == 10
        assert len(pools["q2"]["w_pool"]) == len(pools["q2"]["g_pool"]) == 14


# =====================================================================================
# Scoring: each measure pinned to what it compares against (test 1's bug was exactly a
# measure drifting onto the wrong target).
# =====================================================================================

class TestAnswerLeadRecall:
    def test_true_when_the_answer_bearing_lead_is_among_the_two(self):
        leads = [{"page_id": 2, "title": "B"}, {"page_id": 99, "title": "Z"}]
        assert ns2.answer_lead_recall_at_two(leads, make_q(answer_lead_index=1)) is True

    def test_false_when_it_is_not(self):
        leads = [{"page_id": 1, "title": "A"}, {"page_id": 99, "title": "Z"}]
        assert ns2.answer_lead_recall_at_two(leads, make_q(answer_lead_index=1)) is False

    def test_checks_the_answer_bearing_lead_specifically_not_either_gold_lead(self):
        # The non-answer-bearing gold lead alone must not count.
        leads = [{"page_id": 1, "title": "A"}, {"page_id": 99, "title": "Z"}]
        assert ns2.answer_lead_recall_at_two(leads, make_q(answer_lead_index=0)) is True
        assert ns2.answer_lead_recall_at_two(leads, make_q(answer_lead_index=1)) is False


class TestBothGoldAtTwo:
    def test_true_when_both_gold_leads_are_given(self):
        leads = [{"page_id": 2, "title": "B"}, {"page_id": 1, "title": "A"}]
        assert ns2.both_gold_at_two(leads, make_q()) is True

    def test_false_when_only_one_is(self):
        leads = [{"page_id": 2, "title": "B"}, {"page_id": 99, "title": "Z"}]
        assert ns2.both_gold_at_two(leads, make_q()) is False


class TestPoolRecall:
    def test_true_when_the_answer_bearing_lead_is_anywhere_in_the_pool(self):
        assert ns2.pool_recall([5, 9, 2, 3], make_q(answer_lead_index=1)) is True

    def test_false_when_it_is_nowhere_in_the_pool(self):
        assert ns2.pool_recall([5, 9, 3], make_q(answer_lead_index=1)) is False


class TestScoreReader:
    """Pins which answer `score_reader` compares against -- there is no substitute in test 2 (no
    corrections), so the only correct target is ever `q["answer"]`; test 1's bug was exactly a measure
    drifting onto the wrong one."""

    def test_em_and_f1_target_q_answer(self):
        q = {"answer": "1970"}
        assert ns2.score_reader("1970", q) == {"em": True, "f1": 1.0}
        assert ns2.score_reader("1992", q)["em"] is False

    def test_has_no_parameter_for_any_other_target(self):
        assert set(inspect.signature(ns2.score_reader).parameters) == {"answer", "q"}


class TestEarnsItsPlace:
    def test_earns_its_place_when_lower_above_zero_and_point_at_least_the_margin(self):
        result = ns2.earns_its_place({"points": 6.0, "ci95": [1.0, 11.0]})
        assert result["verdict"] == "earns its place"

    def test_no_measured_gain_when_the_ci_straddles_zero(self):
        result = ns2.earns_its_place({"points": 2.0, "ci95": [-3.0, 7.0]})
        assert result["verdict"] == "no measured gain"

    def test_measured_gain_under_the_margin_when_lower_above_zero_but_point_too_small(self):
        result = ns2.earns_its_place({"points": 2.0, "ci95": [0.5, 3.5]})
        assert result["verdict"] == "measured gain under the margin"

    def test_measured_loss_when_the_ci_is_entirely_below_zero(self):
        result = ns2.earns_its_place({"points": -4.0, "ci95": [-8.0, -1.0]})
        assert result["verdict"] == "measured loss"

    def test_margin_is_configurable(self):
        result = ns2.earns_its_place({"points": 6.0, "ci95": [1.0, 11.0]}, margin=10.0)
        assert result["verdict"] == "measured gain under the margin"

    def test_a_point_estimate_exactly_at_the_margin_earns_its_place(self):
        # The spec's wording is inclusive ("at least 5 points"), not "more than".
        result = ns2.earns_its_place({"points": 5.0, "ci95": [1.0, 9.0]}, margin=5.0)
        assert result["verdict"] == "earns its place"


class TestCeilingOverride:
    """Revision 3's comparison-stratum ceiling rule, both sides of 90%."""

    def test_relabels_no_measured_gain_at_or_above_the_ceiling(self):
        assert ns2.ceiling_override("no measured gain", 0.90) == "uninformative at ceiling"
        assert ns2.ceiling_override("no measured gain", 0.95) == "uninformative at ceiling"

    def test_leaves_no_measured_gain_alone_below_the_ceiling(self):
        assert ns2.ceiling_override("no measured gain", 0.89) == "no measured gain"

    def test_leaves_any_other_verdict_alone_regardless_of_the_baseline_rate(self):
        for verdict in ("earns its place", "measured gain under the margin", "measured loss"):
            assert ns2.ceiling_override(verdict, 0.99) == verdict

    def test_the_boundary_at_exactly_90_percent_counts_as_at_ceiling(self):
        assert ns2.ceiling_override("no measured gain", 0.90) == "uninformative at ceiling"


# =====================================================================================
# Cross-encoder reranking and truncation accounting -- fake tokenizer/reranker, no
# ~1 GB model load.
# =====================================================================================

def fake_rerank(query: str, documents):
    return [float(len(d)) for d in documents]  # longer "document" scores higher, deterministic


class FakeEncoding:
    def __init__(self, real_length: int, padded_length: int):
        self.ids = list(range(padded_length))
        self.attention_mask = [1] * real_length + [0] * (padded_length - real_length)


class FakeTokenizer:
    """A minimal stand-in for `tokenizers.Tokenizer`: `encode_batch`'s real length is the combined
    character count of the pair (a crude proxy for token count, but enough to test
    count_truncated_pairs' own disable/measure/restore logic without the real ~1 GB cross-encoder) --
    and, like the real tokenizer (``padding: {"length": None, ...}``, confirmed against the loaded
    model), every pair in one ``encode_batch`` call is padded to the *longest* pair's length, with
    ``attention_mask`` the only field that still says how long each pair really was."""

    def __init__(self, max_length: int | None = 10):
        self.truncation = None if max_length is None else {
            "max_length": max_length, "stride": 0, "strategy": "longest_first", "direction": "right"}

    def no_truncation(self):
        self.truncation = None

    def enable_truncation(self, max_length, stride, strategy, direction):
        self.truncation = {"max_length": max_length, "stride": stride, "strategy": strategy, "direction": direction}

    def encode_batch(self, pairs):
        real_lengths = [len(q) + len(d) for q, d in pairs]
        padded_length = max(real_lengths) if real_lengths else 0
        return [FakeEncoding(length, padded_length) for length in real_lengths]


class TestCrossRerank:
    def test_orders_candidates_by_score_descending(self):
        candidates = [{"title": "A", "text": "short"}, {"title": "B", "text": "a much longer document text"}]
        leads = ns2.cross_rerank("q", candidates, fake_rerank, top=1)
        assert leads[0]["title"] == "B"

    def test_empty_candidates_gives_no_leads(self):
        assert ns2.cross_rerank("q", [], fake_rerank, top=2) == []


class TestCountTruncatedPairs:
    def test_counts_only_pairs_whose_natural_length_exceeds_max_length(self):
        tok = FakeTokenizer(max_length=10)
        pairs = [("short", "doc"), ("a very long query indeed", "and an equally long document too")]
        assert ns2.count_truncated_pairs(tok, pairs) == 1

    def test_restores_the_original_truncation_settings_afterward(self):
        tok = FakeTokenizer(max_length=10)
        original = dict(tok.truncation)
        ns2.count_truncated_pairs(tok, [("a", "b")])
        assert tok.truncation == original

    def test_zero_when_no_truncation_is_configured_at_all(self):
        tok = FakeTokenizer(max_length=None)
        assert ns2.count_truncated_pairs(tok, [("a" * 1000, "b" * 1000)]) == 0

    def test_a_short_pair_sharing_a_batch_with_a_long_one_is_not_miscounted_as_truncated(self):
        # The real bug: the tokenizer pads every pair in a batch to the longest pair's length
        # (confirmed against the loaded model: padding "length": None means dynamic, to-longest), so
        # len(ids) alone makes the short pair here look exactly as long as the long one. Only the real
        # token count (sum(attention_mask)) tells them apart; this batch must count exactly 1.
        tok = FakeTokenizer(max_length=10)
        pairs = [("short", "doc"), ("a", "b" * 20)]  # pair 1 real length 8 (<= 10); pair 2's is 21 (> 10)
        assert ns2.count_truncated_pairs(tok, pairs) == 1


class TestModelDigestAndTruncationSettings:
    class FakeModel:
        def __init__(self, model_dir):
            self._model_dir = model_dir

    def test_model_digest_is_the_snapshot_directory_name(self):
        model = self.FakeModel("/x/models--A--B/snapshots/abc123def")
        assert ns2.model_digest(model) == "abc123def"

    def test_reranker_truncation_settings_reads_the_tokenizer(self):
        tok = FakeTokenizer(max_length=512)
        assert ns2.reranker_truncation_settings(tok) == {
            "max_length": 512, "stride": 0, "strategy": "longest_first", "direction": "right"}

    def test_reranker_truncation_settings_none_when_untruncated(self):
        tok = FakeTokenizer(max_length=None)
        assert ns2.reranker_truncation_settings(tok) is None


# =====================================================================================
# summarize2 and rescore2 on hand-made rows.
# =====================================================================================

class TestSummarize2:
    def _rows(self):
        ids = [f"q{i}" for i in range(6)]
        rows = {}
        for arm in ns2.ARMS:
            rows[arm] = {}
            for i, qid in enumerate(ids):
                # g_dense and g_cross always recall the answer; w_dense/w_cross/b_dense/b_cross recall it
                # for the first 3 only, e never does -- enough spread for a real (non-degenerate) CI.
                recalls = arm in ("g_dense", "g_cross") or (arm.startswith(("w_", "b_")) and i < 3)
                rows[arm][qid] = {
                    "answer": "right" if recalls else "wrong", "leads": [],
                    "answer_lead_recall": recalls, "both_gold": False, "pool_recall": True,
                    "em": recalls, "f1": 1.0 if recalls else 0.0, "seconds": 0.1,
                }
        return ids, rows

    def test_primary_is_g_dense_against_w_dense_recall(self):
        ids, rows = self._rows()
        sample = [{"id": qid} for qid in ids]
        usage = {arm: {} for arm in ns2.ARMS}
        truncation = {"b_cross": {"pairs": 0, "truncated": 0}, "g_cross": {"pairs": 0, "truncated": 0},
                     "w_cross": {"pairs": 0, "truncated": 0}}
        summary = ns2.summarize2(sample, rows, usage, truncation)
        assert summary["primary"]["diff_ci"]["n"] == 6
        assert summary["by_arm"]["g_dense"]["answer_lead_recall"] == 6
        assert summary["by_arm"]["w_dense"]["answer_lead_recall"] == 3
        assert summary["by_arm"]["e"]["answer_lead_recall"] == 0

    def test_truncation_share_is_computed_per_cross_arm(self):
        ids, rows = self._rows()
        sample = [{"id": qid} for qid in ids]
        usage = {arm: {} for arm in ns2.ARMS}
        truncation = {"b_cross": {"pairs": 100, "truncated": 10}, "g_cross": {"pairs": 50, "truncated": 0},
                     "w_cross": {"pairs": 0, "truncated": 0}}
        summary = ns2.summarize2(sample, rows, usage, truncation)
        assert summary["truncation"]["b_cross"]["share"] == 0.1
        assert summary["truncation"]["g_cross"]["share"] == 0.0
        assert summary["truncation"]["w_cross"]["share"] is None  # no pairs scored at all


class TestSummarize2Ceiling:
    """Revision 3's comparison-stratum ceiling rule, exercised through summarize2 end to end (not just
    ceiling_override in isolation): g_dense ties w_dense exactly on both_gold, so the paired diff is zero
    ("no measured gain") before any ceiling override -- isolating the ceiling rule from the CI arithmetic."""

    _USAGE = {arm: {} for arm in ns2.ARMS}
    _TRUNCATION = {"b_cross": {"pairs": 0, "truncated": 0}, "g_cross": {"pairs": 0, "truncated": 0},
                   "w_cross": {"pairs": 0, "truncated": 0}}

    def _rows_at_rate(self, rate: float, n: int = 20):
        ids = [f"q{i}" for i in range(n)]
        true_count = round(rate * n)
        rows = {arm: {} for arm in ns2.ARMS}
        for i, qid in enumerate(ids):
            both_gold = i < true_count
            for arm in ns2.ARMS:
                rows[arm][qid] = {"answer": "x", "leads": [], "answer_lead_recall": both_gold,
                                  "both_gold": both_gold, "pool_recall": True, "em": False, "f1": 0.0,
                                  "seconds": 0.1}
        return [{"id": qid} for qid in ids], rows

    def test_at_or_above_90_percent_labels_uninformative_at_ceiling(self):
        sample, rows = self._rows_at_rate(0.90)
        summary = ns2.summarize2(sample, rows, self._USAGE, self._TRUNCATION, both_gold_primary=True)
        assert summary["at_ceiling"] is True
        assert summary["w_dense_both_gold_rate"] == 0.9
        assert summary["primary_both_gold"]["verdict"] == "uninformative at ceiling"
        assert summary["primary"]["verdict"] == "uninformative at ceiling"

    def test_below_90_percent_reports_no_measured_gain_plainly(self):
        sample, rows = self._rows_at_rate(0.80)
        summary = ns2.summarize2(sample, rows, self._USAGE, self._TRUNCATION, both_gold_primary=True)
        assert summary["at_ceiling"] is False
        assert summary["primary_both_gold"]["verdict"] == "no measured gain"
        assert summary["primary"]["verdict"] == "no measured gain"

    def test_the_bridge_stratum_never_applies_the_ceiling_even_at_100_percent(self):
        # both_gold_primary=False: the bridge stratum's own summary, which never checks the ceiling at all.
        sample, rows = self._rows_at_rate(1.0)
        summary = ns2.summarize2(sample, rows, self._USAGE, self._TRUNCATION, both_gold_primary=False)
        assert summary["at_ceiling"] is False
        assert summary["w_dense_both_gold_rate"] is None
        assert summary["primary"]["verdict"] == "no measured gain"

    def test_reporting_order_is_by_arm_then_both_gold_then_recall(self):
        # The coordinator's ordering: each arm's own rate before any paired difference, and both-gold
        # before answer-lead recall.
        sample, rows = self._rows_at_rate(0.5)
        summary = ns2.summarize2(sample, rows, self._USAGE, self._TRUNCATION, both_gold_primary=True)
        keys = list(summary.keys())
        assert keys.index("by_arm") < keys.index("primary_both_gold") < keys.index("primary")
        arm_keys = list(summary["by_arm"]["g_dense"].keys())
        assert arm_keys.index("both_gold") < arm_keys.index("answer_lead_recall")


class TestSummarize2FewerThanTwo:
    def test_primary_and_secondary_are_none_with_fewer_than_two_paired_rows(self):
        rows = {arm: {"q0": {"answer_lead_recall": True, "em": True, "both_gold": False, "pool_recall": True,
                             "answer": "x", "f1": 1.0}}
               for arm in ns2.ARMS}
        usage = {arm: {} for arm in ns2.ARMS}
        truncation = {"b_cross": {"pairs": 0, "truncated": 0}, "g_cross": {"pairs": 0, "truncated": 0},
                     "w_cross": {"pairs": 0, "truncated": 0}}
        summary = ns2.summarize2([{"id": "q0"}], rows, usage, truncation)
        assert summary["primary"] is None
        assert summary["secondary"]["g_dense_vs_b_dense_recall"] is None
        assert summary["by_arm"]["g_dense"]["n"] == 1  # per-arm counts still compute with just one


def _tiny_stratum_results(qid="q0", answer="1970", leads=None):
    leads = leads if leads is not None else [{"page_id": 2, "title": "B"}]
    return {
        "rows": {arm: {qid: {"answer": answer, "leads": leads, "answer_lead_recall": False, "both_gold": True,
                            "em": False, "f1": 0.0, "pool_recall": True, "seconds": 0.1}}
                for arm in ns2.ARMS},
        "usage": {arm: {} for arm in ns2.ARMS},
        "truncation": {"b_cross": {"pairs": 0, "truncated": 0}, "g_cross": {"pairs": 0, "truncated": 0},
                      "w_cross": {"pairs": 0, "truncated": 0}},
    }


class TestRescore2:
    def test_rescore_recomputes_recall_and_em_from_saved_leads_and_answers(self):
        plan = {"questions": [
            {"id": "q0", "answer": "1970", "answer_lead_index": 1,
             "gold_leads": [{"page_id": 1, "rev_id": 1, "title": "A"}, {"page_id": 2, "rev_id": 2, "title": "B"}]},
        ], "comparison_questions": []}
        # The saved row's own (possibly wrong) em/recall fields are deliberately wrong here; rescore must
        # not trust them, only the saved answer and leads.
        results = {"bridge": _tiny_stratum_results(), "comparison": None}
        summary = ns2.rescore2(results, plan)
        assert summary["bridge"]["by_arm"]["g_dense"]["answer_lead_recall"] == 1  # recomputed True
        assert summary["bridge"]["by_arm"]["g_dense"]["reader"]["em"] == 1       # recomputed True
        assert summary["comparison"] is None

    def test_rescore_handles_both_strata_reported_apart(self):
        plan = {
            "questions": [{"id": "q0", "answer": "1970", "answer_lead_index": 1,
                          "gold_leads": [{"page_id": 1, "rev_id": 1, "title": "A"},
                                        {"page_id": 2, "rev_id": 2, "title": "B"}]}],
            "comparison_questions": [{"id": "c0", "answer": "1985", "answer_lead_index": 0,
                                     "gold_leads": [{"page_id": 3, "rev_id": 1, "title": "C"},
                                                   {"page_id": 4, "rev_id": 1, "title": "D"}]}],
        }
        results = {"bridge": _tiny_stratum_results(),
                  "comparison": _tiny_stratum_results(qid="c0", answer="1985",
                                                       leads=[{"page_id": 3, "title": "C"}])}
        summary = ns2.rescore2(results, plan)
        assert summary["bridge"]["by_arm"]["g_dense"]["answer_lead_recall"] == 1
        assert summary["comparison"]["by_arm"]["g_dense"]["answer_lead_recall"] == 1
        assert summary["comparison"]["primary_both_gold"] is None  # only one row: below paired_ci's minimum


# =====================================================================================
# End-to-end, against the real corpus-index binary (skipped, not failed, when cargo
# isn't here): run_smoke with fake model/embedder/reranker, no ~1 GB download.
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
    cargo = _cargo_path()
    if cargo is None:
        pytest.skip("cargo isn't available; can't build the corpus-index crate")
    import os

    env = {**os.environ, "PATH": f"{Path(cargo).parent}:{os.environ.get('PATH', '')}"}
    result = subprocess.run([cargo, "build", "--release", "--offline", "--message-format=json"],
                            cwd=CRATE_DIR, capture_output=True, text=True, env=env)
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
    from experiments.multihop.export_corpus_tsv import export as export_corpus_tsv

    docs_path, links_path = tmp_path / "docs.tsv", tmp_path / "links.tsv"
    export_corpus_tsv(corpus_path, docs_path, links_path)
    index_path = tmp_path / "index.bin"
    result = subprocess.run([str(corpus_index_bin), "build", "--docs", str(docs_path), "--links", str(links_path),
                             "--out", str(index_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return corpus_index_bin, index_path


def fake_embed(texts, prefix="search_document"):
    vocab = ["ann", "vale", "leeds", "lotus", "band", "alpha", "bristol", "silent"]
    return [[float(text.lower().count(word)) for word in vocab] for text in texts]


def fake_ask(model, prompt_text):
    return "an answer", 0.01, {"prompt_eval_count": 1, "eval_count": 1}


class TestRunSmokeEndToEnd:
    def test_run_smoke_produces_all_seven_arms_for_both_strata(self, real_index, corpus_path, tmp_path):
        bin_path, index_path = real_index
        bridge_q = {"id": "q0", "question": "Where did the singer of the band Lotus grow up?", "answer": "Leeds",
                   "answer_lead_index": 1, "answer_class": "name",
                   "gold_leads": [{"page_id": 1, "rev_id": 1, "title": "Lotus (band)"},
                                 {"page_id": 2, "rev_id": 2, "title": "Ann Vale"}]}
        comparison_q = {**bridge_q, "id": "c0", "type": "comparison"}
        plan = {"model": "fake", "questions": [bridge_q], "comparison_questions": [comparison_q]}
        workdir = tmp_path / "work"
        workdir.mkdir()
        result = ns2.run_smoke(
            plan, corpus_path=corpus_path, index_path=index_path, bin_path=bin_path, capped_sh=None,
            count=1, model="fake", ask_fn=fake_ask, embed_fn=fake_embed, cross_rerank_fn=fake_rerank,
            cross_tokenizer=FakeTokenizer(), workdir=workdir,
        )
        for stratum, qid in (("bridge", "q0"), ("comparison", "c0")):
            data = result[stratum]
            assert set(data["rows"].keys()) == set(ns2.ARMS)
            for arm in ns2.ARMS:
                assert qid in data["rows"][arm]
                row = data["rows"][arm][qid]
                assert row["answer"] == "an answer"
                assert row["em"] is False  # "an answer" != "Leeds"
            assert data["summary"]["primary"] is None  # one question: paired_ci needs at least two
            assert data["usage"]["e"]["calls"] == 1
            for name in ("b_cross", "g_cross", "w_cross"):
                assert data["truncation"][name]["pairs"] >= 1
        assert result["comparison"]["summary"]["primary_both_gold"] is None  # one question: below the minimum too

    def test_usage_counts_each_reranks_work_and_its_wall_time(self, real_index, corpus_path, tmp_path):
        """The spec's cost measure: per arm, the embeddings and cross-encoder pairs computed and the rerank's
        wall time, beside the reader's calls. The first build recorded only the reader's. The fakes sleep, so
        a timer that never ran can't pass."""
        import time as _time
        bin_path, index_path = real_index
        bridge_q = {"id": "q0", "question": "Where did the singer of the band Lotus grow up?", "answer": "Leeds",
                   "answer_lead_index": 1, "answer_class": "name",
                   "gold_leads": [{"page_id": 1, "rev_id": 1, "title": "Lotus (band)"},
                                 {"page_id": 2, "rev_id": 2, "title": "Ann Vale"}]}
        plan = {"model": "fake", "questions": [bridge_q],
                "comparison_questions": [{**bridge_q, "id": "c0", "type": "comparison"}]}
        seen = {"texts": 0, "docs": 0}

        def slow_embed(texts, prefix="search_document"):
            _time.sleep(0.02)
            seen["texts"] += len(texts)
            return fake_embed(texts, prefix)

        def slow_rerank(query, documents):
            _time.sleep(0.02)
            seen["docs"] += len(documents)
            return fake_rerank(query, documents)

        workdir = tmp_path / "work"
        workdir.mkdir()
        result = ns2.run_smoke(
            plan, corpus_path=corpus_path, index_path=index_path, bin_path=bin_path, capped_sh=None,
            count=1, model="fake", ask_fn=fake_ask, embed_fn=slow_embed, cross_rerank_fn=slow_rerank,
            cross_tokenizer=FakeTokenizer(), workdir=workdir,
        )
        embeddings = pairs = 0
        for stratum in ("bridge", "comparison"):
            usage = result[stratum]["usage"]
            assert usage["e"]["embeddings"] == 0 and usage["e"]["pairs"] == 0
            assert usage["e"]["rerank_seconds"] == 0.0
            for arm in ("b_dense", "g_dense", "w_dense"):
                assert usage[arm]["embeddings"] >= 2  # the question and at least one candidate
                assert usage[arm]["pairs"] == 0
                assert usage[arm]["rerank_seconds"] >= 0.04  # two embed calls, 0.02 s each
                embeddings += usage[arm]["embeddings"]
            for arm in ("b_cross", "g_cross", "w_cross"):
                assert usage[arm]["embeddings"] == 0
                assert usage[arm]["pairs"] == result[stratum]["truncation"][arm]["pairs"] >= 1
                assert usage[arm]["rerank_seconds"] >= 0.02
                pairs += usage[arm]["pairs"]
            assert result[stratum]["wall_seconds"] >= 6 * 0.02
            assert result[stratum]["summary"]["cost"]["g_dense"]["embeddings"] == usage["g_dense"]["embeddings"]
        assert embeddings == seen["texts"]
        assert pairs == seen["docs"]
