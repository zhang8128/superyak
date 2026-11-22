"""North-star test 2: retrieving the evidence that holds the answer, against strong baselines.

Spec: ``docs/superpowers/specs/2026-11-22-north-star-test-2-design.md`` (approved, revision 2). Draws 800
new qualifying HotpotQA bridge questions (test 1's qualifying rule, a new seed, excluding test 1's 800 too)
and compares seven arms, all giving the same reader (nemotron-mini, temperature 0, prompt v2) two leads
from corpus v0, with **no corrections** -- this test is about retrieval and answering alone:

- **E**: BM25 then one hop (test 1's E, reused as-is).
- **B-dense**/**B-cross**: BM25 top 100, dense (nomic) or cross-encoder (BAAI/bge-reranker-base) rerank.
- **G-dense**/**G-cross**: BM25 top 100 plus the out-links of BM25's top 5, the same two rerankers.
- **W-dense**/**W-cross**: BM25's top N (N = that question's G pool size), the same two rerankers --
  the size-matched baseline the primary compares G against (revision 2).

Primary: answer-lead recall at two, G-dense against W-dense, paired, 95% CI. "Earns its place" needs the
CI's lower end above 0 *and* a point estimate of at least 5 points; a CI straddling 0 is "no measured
gain" (``earns_its_place``, which also names the two cases the spec's prose doesn't: a positive-but-small
gain, and a measured loss).

Two modes, as test 1: ``plan`` (the draw, the pool sizes, the reranker's truncation settings, model
digests -- no reader-model calls, but it does load the rerankers and query the real index, so it still
needs ``--capped-sh`` against the real ``index.bin``) and ``run`` (a smoke of at most 10 by default,
``--full`` for all 800, both under capped.sh for the real index). ``rescore`` recomputes the summary from a
saved run's answers, no model calls.

Atlas is never imported here: test 2 has no corrections, so no claims, no store.

Usage:
``PYTHONPATH=engram:atlas python -m experiments.northstar.test2 plan --corpus C.sqlite3 --redirects R.sqlite3
--parquet P.parquet --index index.bin --bin corpus-index --capped-sh capped.sh --out plan.json``
``PYTHONPATH=engram:atlas python -m experiments.northstar.test2 run --plan plan.json --corpus C.sqlite3
--index index.bin --capped-sh capped.sh --out results.json``
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

try:
    from experiments.multihop.hotpot_open import current_title
    from experiments.multihop.hotpot_open_rs import run_queries
    from experiments.multihop.hotpot_smoke import PROMPTS, ask, exact, f1
    from experiments.northstar.test1 import (
        B_BM25_K, B_TOP, DEFAULT_CORPUS_INDEX_BIN, E_K, MODEL, PROMPT_VERSION,
        CorpusLookup, answer_class, build_prompt, dense_rerank, paired_ci, run_queries_capped,
        whole_word_occurrences,
    )
except ImportError:  # pragma: no cover - running as a bare file beside the other scripts
    from hotpot_open import current_title
    from hotpot_open_rs import run_queries
    from hotpot_smoke import PROMPTS, ask, exact, f1
    from test1 import (
        B_BM25_K, B_TOP, DEFAULT_CORPUS_INDEX_BIN, E_K, MODEL, PROMPT_VERSION,
        CorpusLookup, answer_class, build_prompt, dense_rerank, paired_ci, run_queries_capped,
        whole_word_occurrences,
    )

# ---- Fixed before the run (the pre-registration; plan.json records this) ----
POOL_SEED = 2026112205      # test 2's own draw: a new seed, distinct from test 1's 201/202/203/204
TARGET_QUALIFYING = 800
MIN_QUALIFYING = 500
COMPARISON_SEED = 2026112206       # the comparison stratum's own draw (revision 3)
COMPARISON_TARGET = 300
MIN_COMPARISON_QUALIFYING = 150   # half the proportion test 1's 500/800 set, since the pool of qualifying
                                   # comparison questions is thinner (RESULTS.md: comparison rarely hops well)
HOP_SEEDS = 5                # G's pool: the out-links of BM25's top this-many
CROSS_ENCODER_MODEL = "BAAI/bge-reranker-base"
PRIMARY_MARGIN = 5.0         # "earns its place" needs the point estimate at least this many points
SMOKE_LIMIT = 10

DEFAULT_EXCLUDE_FILES = (
    "engram/experiments/multihop/results/router-fresh-c1-2026-11-21.json",
    "engram/experiments/multihop/results/router-fresh-c2-2026-11-21.json",
)
DEFAULT_TEST1_PLAN = "engram/experiments/northstar/results/test1-plan-2026-11-22.json"

ARMS = ("e", "b_dense", "b_cross", "g_dense", "g_cross", "w_dense", "w_cross")


# =====================================================================================
# The draw: test 1's qualifying rule, a new seed, excluding test 1's 800 too
# =====================================================================================

def load_excluded_ids(paths: list[str]) -> set:
    """Each file's question ids, to exclude from test 2's pool. The two fresh-router files use a ``rows``
    key (test1.py's own exclusion-reader convention); test 1's own plan file uses ``questions`` instead
    (spec: "test 1's exclusion reader expects a rows key... so test 2 reads both")."""
    excluded = set()
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        key = "rows" if "rows" in data else "questions"
        excluded.update(row["id"] for row in data[key])
    return excluded


def qualifying_leads_by_type(row: dict, corpus: CorpusLookup, redirects, *, qtype: str) -> dict | None:
    """Test 1's qualifying rule (``qualifying_leads``'s own body: both gold leads present, the answer a
    whole word in exactly one, year-or-name-shaped), parameterized by HotpotQA's ``type`` field instead of
    test1.py's hardcoded "bridge" -- so test 2's comparison stratum (revision 3) can reuse the rule without
    duplicating or editing test1.py's bridge-only function. With ``qtype="bridge"`` this accepts exactly
    what ``qualifying_leads`` does; a bridge row is never accepted with ``qtype="comparison"`` and vice
    versa, since a HotpotQA question's ``type`` is always exactly one of the two -- the two draws' promised
    disjointness follows from this alone, not from any extra cross-exclusion."""
    if row.get("type") != qtype:
        return None
    cls = answer_class(row.get("answer", ""), corpus, redirects)
    if cls is None:
        return None
    gold_titles_2017 = row["supporting_facts"]["title"]
    if len(set(gold_titles_2017)) != 2:
        return None
    current_titles = [current_title(t, redirects) for t in gold_titles_2017]
    if len(set(current_titles)) != 2:
        return None
    leads = [corpus.by_title(t) for t in current_titles]
    if any(lead is None for lead in leads):
        return None
    hits = [bool(whole_word_occurrences(lead["text"], row["answer"])) for lead in leads]
    if sum(hits) != 1:
        return None
    return {"gold_leads": leads, "answer_class": cls, "corrected_lead_index": hits.index(True)}


def draw_qualifying_by_type(pool_rows: list[dict], corpus: CorpusLookup, redirects, *, qtype: str,
                            target: int, seed: int) -> tuple[list[dict], int]:
    """``pool_rows`` in a seeded shuffle's order, keeping each one ``qualifying_leads_by_type`` accepts for
    ``qtype``, until ``target`` are found. Returns ``(qualifying, draws)``."""
    import random

    order = list(range(len(pool_rows)))
    random.Random(seed).shuffle(order)
    qualifying: list[dict] = []
    draws = 0
    for index in order:
        draws += 1
        row = pool_rows[index]
        info = qualifying_leads_by_type(row, corpus, redirects, qtype=qtype)
        if info is not None:
            qualifying.append({**row, **info})
            if len(qualifying) >= target:
                break
    return qualifying, draws


# =====================================================================================
# The arms' candidate pools: G adds the link graph to BM25's top 100; W matches G's size
# from BM25 alone (the reviewer's size-matched baseline, revision 2).
# =====================================================================================

def g_pool_ids(bm25_ids: list[int], corpus: CorpusLookup, *, base_k: int = B_BM25_K,
              seeds: int = HOP_SEEDS) -> list[int]:
    """BM25's top ``base_k`` ids, plus the out-links of its top ``seeds`` -- in a fixed order (the base
    pool first, then each new out-link the first time it appears), so the same inputs always give the same
    pool in the same order. A link back into the base pool, or repeated from two seeds, isn't added twice."""
    base = bm25_ids[:base_k]
    pool = list(dict.fromkeys(base))
    seen = set(pool)
    for page_id in bm25_ids[:seeds]:
        for dst in corpus.links_from(page_id):
            if dst not in seen:
                seen.add(dst)
                pool.append(dst)
    return pool


def w_pool_ids(bm25_ranked_ids: list[int], n: int) -> list[int]:
    """BM25's top ``n`` ids -- test 2's size-matched baseline pool (revision 2): same ranking as every
    other arm's BM25 candidates, just as many of them as G's own pool held for this question.
    ``bm25_ranked_ids`` must already hold at least ``n`` ids for an exact match; when BM25 itself touched
    fewer documents than that (a rare, narrow-vocabulary question), this returns every one it has, shorter
    than ``n`` -- flagged by the caller (``compute_pools``' ``w_short`` set), never padded with a guess."""
    return bm25_ranked_ids[:n]


def compute_pools(query_fn, corpus: CorpusLookup, items: list[tuple[str, str]], *,
                  base_k: int = B_BM25_K, hop_seeds: int = HOP_SEEDS) -> dict[str, dict]:
    """For every ``(qid, question_text)`` in ``items``: E's hop pick, the base BM25-``base_k`` pool, G's
    pool (the graph addition), and W's pool (BM25 alone, sized to match G's, from a second, larger query
    only issued if some question's G pool exceeds ``base_k``). ``query_fn(items, k)`` is one batched
    ``corpus-index query`` call (``run_queries`` or ``run_queries_capped``), reused for both passes."""
    picks = query_fn(items, base_k)
    info: dict[str, dict] = {}
    max_n = 0
    for qid, _ in items:
        bm25_ids, hop_ids = picks.get(qid, ([], []))
        g_ids = g_pool_ids(bm25_ids, corpus, base_k=base_k, seeds=hop_seeds)
        info[qid] = {"bm25": bm25_ids, "hop": hop_ids, "g_pool": g_ids}
        max_n = max(max_n, len(g_ids))

    big_picks = picks if max_n <= base_k else query_fn(items, max_n)
    for qid, _ in items:
        n = len(info[qid]["g_pool"])
        bm25_big, _ = big_picks.get(qid, ([], []))
        info[qid]["w_pool"] = w_pool_ids(bm25_big, n)
        info[qid]["w_short"] = len(info[qid]["w_pool"]) < n
    return info


# =====================================================================================
# Reranking: dense (test 1's) and cross-encoder (new), plus the truncation accounting
# the spec's known-limits section asks for.
# =====================================================================================

def cross_rerank(question_text: str, candidates: list[dict], rerank_fn, top: int = B_TOP) -> list[dict]:
    """``candidates`` reranked by a cross-encoder's pair score, highest first, truncated to ``top``.
    ``rerank_fn(query, documents) -> scores`` matches ``TextCrossEncoder.rerank``'s own signature, so a
    test can stand in a fake reranker with no model load."""
    if not candidates:
        return []
    documents = [f"{c['title']} {c['text']}" for c in candidates]
    scores = list(rerank_fn(question_text, documents))
    scored = sorted(zip(candidates, scores), key=lambda pair: -pair[1])
    return [candidate for candidate, _ in scored[:top]]


def reranker_truncation_settings(tokenizer) -> dict | None:
    """The ``max_length``/strategy a loaded cross-encoder's own tokenizer truncates pairs at, read from the
    tokenizer itself (not guessed from the model card) -- ``None`` if it has no truncation configured at
    all, so it would never cut anything."""
    truncation = tokenizer.truncation
    return dict(truncation) if truncation else None


def count_truncated_pairs(tokenizer, pairs: list[tuple[str, str]]) -> int:
    """How many ``(query, document)`` pairs would be truncated by this tokenizer's own settings: disables
    truncation, measures each pair's natural encoded length through the exact same ``encode_batch`` path
    ``OnnxTextCrossEncoder.tokenize`` calls, restores truncation, and counts how many exceeded
    ``max_length``. A tokenizer with no truncation configured can't truncate anything, so 0 without
    encoding a thing."""
    original = tokenizer.truncation
    if not original:
        return 0
    max_length = original["max_length"]
    tokenizer.no_truncation()
    try:
        encodings = tokenizer.encode_batch(list(pairs))
    finally:
        tokenizer.enable_truncation(max_length=max_length, stride=original["stride"],
                                    strategy=original["strategy"], direction=original["direction"])
    return sum(1 for encoding in encodings if len(encoding.ids) > max_length)


def model_digest(loaded_model) -> str:
    """A loaded fastembed model's content identity: the HuggingFace snapshot revision its cache directory
    is named for (``model._model_dir``'s last path component) -- not a fresh hash of a ~1 GB file, but the
    same commit-hash-shaped identity HuggingFace itself uses, read from the files already on disk."""
    return Path(loaded_model._model_dir).name


# =====================================================================================
# Scoring (spec: "Measures, fixed before the run") -- each pinned to what it compares
# against, with a test for it: test 1's bug was exactly this.
# =====================================================================================

def answer_lead_id(q: dict) -> int:
    """The page id of ``q``'s answer-bearing lead (the one ``qualifying_leads`` found holds the answer)."""
    return q["gold_leads"][q["answer_lead_index"]]["page_id"]


def answer_lead_recall_at_two(picked_leads: list[dict], q: dict) -> bool:
    """Whether the two leads given to the reader include the answer-bearing lead."""
    return answer_lead_id(q) in {lead["page_id"] for lead in picked_leads}


def both_gold_at_two(picked_leads: list[dict], q: dict) -> bool:
    """Whether the two leads given to the reader are exactly ``q``'s two gold leads (in either order)."""
    gold_ids = {lead["page_id"] for lead in q["gold_leads"]}
    picked_ids = {lead["page_id"] for lead in picked_leads}
    return gold_ids <= picked_ids


def pool_recall(pool_ids, q: dict) -> bool:
    """Whether the answer-bearing lead is anywhere in an arm's candidate pool, before the final two are
    chosen -- the ceiling a reranker alone can't exceed."""
    return answer_lead_id(q) in set(pool_ids)


def score_reader(answer: str, q: dict) -> dict:
    """The reader's exact match and F1 against ``q["answer"]`` -- test 2's only answer; there is no
    substitute, ever (no corrections here). Named and tested on its own, pinned to this one target, since
    test 1's bug was exactly scoring an answer against the wrong one."""
    return {"em": exact(answer, q["answer"]), "f1": round(f1(answer, q["answer"]), 4)}


def earns_its_place(diff_ci: dict, margin: float = PRIMARY_MARGIN) -> dict:
    """Test 2's primary rule (G-dense against W-dense, answer-lead recall at two, revision 2): "earns its
    place" when the CI's lower end is above 0 *and* the point estimate is at least ``margin`` points;
    "no measured gain" when the CI straddles 0. The spec names only those two outcomes; a lower end above 0
    with a point estimate under ``margin``, and a CI entirely below 0, are real possibilities its prose
    doesn't name, so they're reported as their own cases here rather than folded into either one."""
    lower, upper = diff_ci["ci95"]
    points = diff_ci["points"]
    if lower <= 0 <= upper:
        verdict = "no measured gain"
    elif lower > 0 and points >= margin:
        verdict = "earns its place"
    elif lower > 0:
        verdict = "measured gain under the margin"
    else:
        verdict = "measured loss"
    return {"diff_ci": diff_ci, "verdict": verdict}


CEILING = 0.90  # the comparison stratum's ceiling rule (revision 3)


def ceiling_override(verdict: str, baseline_rate: float, *, ceiling: float = CEILING) -> str:
    """Revision 3's comparison-stratum rule: when the baseline (W-dense) is already at or above
    ``ceiling`` on both-gold at two, a "no measured gain" verdict is relabelled "uninformative at ceiling"
    -- a baseline with almost no headroom left reads the same as "no measured gain" either way, and
    reporting it as "no gain" would wrongly suggest the graph doesn't help rather than that there was
    barely anything left to show. Any other verdict (a real gain, or a loss) is returned unchanged: the
    ceiling only ever overrides the specific case that could be misread."""
    if baseline_rate >= ceiling and verdict == "no measured gain":
        return "uninformative at ceiling"
    return verdict


def arm_recall_counts(ids, rows_by_arm: dict) -> dict:
    """Over ``ids``: how many times this arm's two leads held the answer-bearing lead, both gold leads, and
    how many times the answer-bearing lead was anywhere in its pool at all."""
    n = answer = both = pool = 0
    for qid in ids:
        row = rows_by_arm.get(qid)
        if row is None:
            continue
        n += 1
        answer += bool(row["answer_lead_recall"])
        both += bool(row["both_gold"])
        pool += bool(row["pool_recall"])
    return {"n": n, "both_gold": both, "answer_lead_recall": answer, "pool_recall": pool}


def arm_reader_counts(ids, rows_by_arm: dict) -> dict:
    """Over ``ids``: how many times this arm's reader answer was exact, and the mean F1."""
    n = em = 0
    f1_total = 0.0
    for qid in ids:
        row = rows_by_arm.get(qid)
        if row is None:
            continue
        n += 1
        em += bool(row["em"])
        f1_total += row["f1"]
    return {"n": n, "em": em, "f1_mean": round(f1_total / n, 4) if n else None}


def summarize2(sample: list[dict], rows: dict, usage: dict, truncation: dict, *,
              both_gold_primary: bool = False, ceiling: float = CEILING) -> dict:
    """Every measure the spec fixes before the run, computed the same way for the bridge 800 or the
    comparison 300 (revision 3): each arm's own recall and reader rates first, then the primary (G-dense
    against W-dense, answer-lead recall at two, through ``earns_its_place``), the secondaries (G-cross
    against W-cross; G against B under each reranker, on recall and on exact match), and the truncation
    share per cross-encoder arm. ``both_gold_primary`` (the comparison stratum, revision 3) also pairs
    G-dense against W-dense on both-gold at two, reported before recall and apart from the bridge figures
    -- and, when W-dense's own both-gold rate is at or above ``ceiling``, labels the stratum
    "uninformative at ceiling" rather than a misleading "no measured gain" (``ceiling_override``)."""
    ids = [q["id"] for q in sample]

    def paired(arm_a: str, arm_b: str, field: str) -> dict | None:
        paired_rows = [{"a": rows[arm_a][qid][field], "b": rows[arm_b][qid][field]}
                      for qid in ids if qid in rows.get(arm_a, {}) and qid in rows.get(arm_b, {})]
        return paired_ci(paired_rows, lambda r: r["a"], lambda r: r["b"]) if len(paired_rows) >= 2 else None

    by_arm = {
        arm: {**arm_recall_counts(ids, rows.get(arm, {})), "reader": arm_reader_counts(ids, rows.get(arm, {}))}
        for arm in ARMS
    }
    w_dense = by_arm["w_dense"]
    w_dense_both_gold_rate = (w_dense["both_gold"] / w_dense["n"]) if w_dense["n"] else 0.0
    at_ceiling = both_gold_primary and w_dense_both_gold_rate >= ceiling

    def earns_its_place_or_none(arm_a: str, arm_b: str, field: str) -> dict | None:
        diff_ci = paired(arm_a, arm_b, field)
        if diff_ci is None:
            return None
        result = earns_its_place(diff_ci)
        if at_ceiling:
            result = {**result, "verdict": ceiling_override(result["verdict"], w_dense_both_gold_rate,
                                                            ceiling=ceiling)}
        return result

    primary_both_gold = earns_its_place_or_none("g_dense", "w_dense", "both_gold") if both_gold_primary else None
    primary = earns_its_place_or_none("g_dense", "w_dense", "answer_lead_recall")
    secondary = {
        "g_cross_vs_w_cross_recall": earns_its_place_or_none("g_cross", "w_cross", "answer_lead_recall"),
        "g_dense_vs_b_dense_recall": paired("g_dense", "b_dense", "answer_lead_recall"),
        "g_cross_vs_b_cross_recall": paired("g_cross", "b_cross", "answer_lead_recall"),
        "g_dense_vs_b_dense_em": paired("g_dense", "b_dense", "em"),
        "g_cross_vs_b_cross_em": paired("g_cross", "b_cross", "em"),
    }
    truncation_share = {
        name: {"pairs": t["pairs"], "truncated": t["truncated"],
              "share": round(t["truncated"] / t["pairs"], 4) if t["pairs"] else None}
        for name, t in truncation.items()
    }
    return {"by_arm": by_arm, "at_ceiling": at_ceiling,
           "w_dense_both_gold_rate": round(w_dense_both_gold_rate, 4) if both_gold_primary else None,
           "primary_both_gold": primary_both_gold, "primary": primary,
           "secondary": secondary, "truncation": truncation_share, "cost": usage}


# =====================================================================================
# The pre-registered plan
# =====================================================================================

def ollama_model_digest(model: str = MODEL, *, host: str = "http://127.0.0.1:11434") -> str | None:
    """``model``'s digest from Ollama's own ``/api/tags`` -- a metadata read, not a generation call."""
    import urllib.request

    with urllib.request.urlopen(f"{host}/api/tags", timeout=10) as response:
        data = json.load(response)
    for entry in data.get("models", []):
        if entry.get("name") == model:
            return entry.get("digest")
    return None


def _build_questions(qualifying: list[dict], pools: dict[str, dict]) -> tuple[list[dict], int]:
    """``qualifying`` rows turned into the plan's per-question schema, each with its G and W pool sizes.
    Returns the questions and how many had a short (not size-matched) W pool."""
    questions = []
    w_short = 0
    for q in qualifying:
        pool = pools[q["id"]]
        if pool["w_short"]:
            w_short += 1
        questions.append({
            "id": q["id"], "question": q["question"], "answer": q["answer"], "answer_class": q["answer_class"],
            "type": q["type"],
            "gold_leads": [{"page_id": lead["page_id"], "rev_id": lead["rev_id"], "title": lead["title"]}
                          for lead in q["gold_leads"]],
            "answer_lead_index": q["corrected_lead_index"],
            "g_pool_size": len(pool["g_pool"]), "w_pool_size": len(pool["w_pool"]), "w_short": pool["w_short"],
        })
    return questions, w_short


def build_plan(rows: list[dict], excluded_ids: set, corpus: CorpusLookup, redirects, *, query_fn,
               target: int = TARGET_QUALIFYING, min_qualifying: int = MIN_QUALIFYING, seed: int = POOL_SEED,
               comparison_target: int = COMPARISON_TARGET,
               min_comparison_qualifying: int = MIN_COMPARISON_QUALIFYING, comparison_seed: int = COMPARISON_SEED,
               nemotron_digest: str | None = None, dense_digest: str | None = None,
               cross_digest: str | None = None, cross_truncation: dict | None = None) -> dict:
    """Everything the pre-registration fixes, with no reader-model call: the pool, both draws (800 bridge
    questions, 300 comparison, revision 3 -- disjoint by construction, since a HotpotQA question's type is
    never both), every question's G and W pool sizes (from real retrieval against the real index, hence
    ``query_fn``), the reranker's truncation settings, and both models' digests."""
    pool_rows = [row for row in rows if row["id"] not in excluded_ids]

    bridge, bridge_draws = draw_qualifying_by_type(pool_rows, corpus, redirects, qtype="bridge",
                                                   target=target, seed=seed)
    if len(bridge) < min_qualifying:
        raise RuntimeError(
            f"only {len(bridge)} qualifying bridge questions in the whole pool of {len(pool_rows)}; "
            f"the spec requires at least {min_qualifying} before a run"
        )
    comparison, comparison_draws = draw_qualifying_by_type(pool_rows, corpus, redirects, qtype="comparison",
                                                           target=comparison_target, seed=comparison_seed)
    if len(comparison) < min_comparison_qualifying:
        raise RuntimeError(
            f"only {len(comparison)} qualifying comparison questions in the whole pool of {len(pool_rows)}; "
            f"the spec requires at least {min_comparison_qualifying} before a run"
        )

    bridge_pools = compute_pools(query_fn, corpus, [(q["id"], q["question"]) for q in bridge])
    comparison_pools = compute_pools(query_fn, corpus, [(q["id"], q["question"]) for q in comparison])
    questions, w_short = _build_questions(bridge, bridge_pools)
    comparison_questions, comparison_w_short = _build_questions(comparison, comparison_pools)

    return {
        "seed": seed, "target": target, "min_qualifying": min_qualifying,
        "comparison_seed": comparison_seed, "comparison_target": comparison_target,
        "min_comparison_qualifying": min_comparison_qualifying,
        "pool_size": len(pool_rows), "excluded_ids": len(excluded_ids),
        "qualifying_found": len(bridge), "draws_needed": bridge_draws, "w_short_count": w_short,
        "comparison_qualifying_found": len(comparison), "comparison_draws_needed": comparison_draws,
        "comparison_w_short_count": comparison_w_short,
        "questions": questions, "comparison_questions": comparison_questions,
        "model": MODEL, "prompt_version": PROMPT_VERSION,
        "e_k": E_K, "b_bm25_k": B_BM25_K, "b_top": B_TOP, "hop_seeds": HOP_SEEDS,
        "cross_encoder_model": CROSS_ENCODER_MODEL, "primary_margin": PRIMARY_MARGIN,
        "digests": {"nemotron": nemotron_digest, "dense": dense_digest, "cross": cross_digest},
        "cross_truncation": cross_truncation,
    }


# =====================================================================================
# Running the arms
# =====================================================================================

def _leads_for(corpus: CorpusLookup, page_ids: list[int]) -> list[dict]:
    return [lead for pid in page_ids if (lead := corpus.by_page_id(pid)) is not None]


def _run_arms(sample: list[dict], *, corpus_path, index_path, bin_path, capped_sh,
              capped_gb: int, model: str, ask_fn, embed_fn, cross_rerank_fn, cross_tokenizer,
              workdir: Path, full: bool, both_gold_primary: bool = False) -> dict:
    """All seven arms, for every question in ``sample``: the shared retrieval (one batched query for the
    base pool, a second only if some question's G pool exceeds it), each arm's rerank and reader call, and
    the truncation accounting for the three cross-encoder arms."""
    corpus = CorpusLookup.open(corpus_path)

    def query(items, k):
        if capped_sh is not None:
            return run_queries_capped(bin_path, index_path, items, k, capped_sh=capped_sh, mem_gb=capped_gb,
                                      workdir=workdir)
        return run_queries(bin_path, index_path, items, k)

    items = [(q["id"], q["question"]) for q in sample]
    pools = compute_pools(query, corpus, items)

    rows: dict[str, dict] = {arm: {} for arm in ARMS}
    usage: dict[str, dict] = {arm: {"calls": 0, "prompt_tokens": 0, "eval_tokens": 0, "seconds": 0.0}
                             for arm in ARMS}
    truncation = {"b_cross": {"pairs": 0, "truncated": 0}, "g_cross": {"pairs": 0, "truncated": 0},
                 "w_cross": {"pairs": 0, "truncated": 0}}

    for q in sample:
        qid = q["id"]
        pool = pools[qid]
        bm25_top = pool["bm25"][:B_BM25_K]
        b_candidates = _leads_for(corpus, bm25_top)
        g_candidates = _leads_for(corpus, pool["g_pool"])
        w_candidates = _leads_for(corpus, pool["w_pool"])

        arm_leads = {
            "e": _leads_for(corpus, pool["hop"]),
            "b_dense": dense_rerank(q["question"], b_candidates, embed_fn, top=B_TOP),
            "g_dense": dense_rerank(q["question"], g_candidates, embed_fn, top=B_TOP),
            "w_dense": dense_rerank(q["question"], w_candidates, embed_fn, top=B_TOP),
        }
        for name, candidates in (("b_cross", b_candidates), ("g_cross", g_candidates), ("w_cross", w_candidates)):
            pairs = [(q["question"], f"{c['title']} {c['text']}") for c in candidates]
            truncation[name]["pairs"] += len(pairs)
            truncation[name]["truncated"] += count_truncated_pairs(cross_tokenizer, pairs)
            arm_leads[name] = cross_rerank(q["question"], candidates, cross_rerank_fn, top=B_TOP)

        pool_ids_by_arm = {"e": pool["hop"], "b_dense": bm25_top, "b_cross": bm25_top,
                          "g_dense": pool["g_pool"], "g_cross": pool["g_pool"],
                          "w_dense": pool["w_pool"], "w_cross": pool["w_pool"]}

        for arm in ARMS:
            leads = arm_leads[arm]
            prompt_text = build_prompt(q["question"], leads)
            answer, seconds, info = ask_fn(model, prompt_text)
            u = usage[arm]
            u["calls"] += 1
            u["prompt_tokens"] += info.get("prompt_eval_count") or 0
            u["eval_tokens"] += info.get("eval_count") or 0
            u["seconds"] += seconds
            rows[arm][qid] = {
                "answer": answer,
                "leads": [{"page_id": lead["page_id"], "title": lead["title"]} for lead in leads],
                "pool_size": len(pool_ids_by_arm[arm]),
                "answer_lead_recall": answer_lead_recall_at_two(leads, q),
                "both_gold": both_gold_at_two(leads, q),
                "pool_recall": pool_recall(pool_ids_by_arm[arm], q),
                **score_reader(answer, q), "seconds": seconds,
            }

    summary = summarize2(sample, rows, usage, truncation, both_gold_primary=both_gold_primary)
    return {"sample": [q["id"] for q in sample], "rows": rows, "usage": usage,
           "truncation": truncation, "summary": summary}


def run_smoke(plan: dict, *, corpus_path, index_path, bin_path=DEFAULT_CORPUS_INDEX_BIN, capped_sh=None,
             capped_gb: int = 16, count: int = SMOKE_LIMIT, model: str = MODEL, ask_fn=None,
             embed_fn=None, cross_rerank_fn=None, cross_tokenizer=None, workdir=None) -> dict:
    """The first ``count`` (<= 10) of the plan's bridge questions *and* its comparison questions (revision
    3), against the real model and data, all seven arms -- reported apart (``{"bridge": ..., "comparison":
    ...}``), never pooled. Not a result: too few questions to read anything from."""
    if count > SMOKE_LIMIT:
        raise ValueError(f"run_smoke is capped at {SMOKE_LIMIT} questions; got {count}")
    ask_fn, embed_fn, cross_rerank_fn, cross_tokenizer = _real_fns(ask_fn, embed_fn, cross_rerank_fn, cross_tokenizer)
    workdir = Path(workdir or tempfile.mkdtemp(prefix="northstar2-smoke-"))
    (workdir / "bridge").mkdir(parents=True, exist_ok=True)
    (workdir / "comparison").mkdir(parents=True, exist_ok=True)
    common = dict(corpus_path=corpus_path, index_path=index_path, bin_path=bin_path, capped_sh=capped_sh,
                 capped_gb=capped_gb, model=model, ask_fn=ask_fn, embed_fn=embed_fn,
                 cross_rerank_fn=cross_rerank_fn, cross_tokenizer=cross_tokenizer, full=False)
    bridge = _run_arms(plan["questions"][:count], workdir=workdir / "bridge", **common)
    comparison_sample = plan.get("comparison_questions", [])[:count]
    comparison = (_run_arms(comparison_sample, workdir=workdir / "comparison", both_gold_primary=True, **common)
                 if comparison_sample else None)
    return {"bridge": bridge, "comparison": comparison}


def run_full(plan: dict, *, corpus_path, index_path, bin_path=DEFAULT_CORPUS_INDEX_BIN, capped_sh,
            capped_gb: int = 16, model: str = MODEL, ask_fn=None, embed_fn=None, cross_rerank_fn=None,
            cross_tokenizer=None, workdir=None) -> dict:
    """All 800 bridge questions and all 300 comparison questions (revision 3) against the real model and
    data, all seven arms, every query against the real index routed through ``capped.sh``. Expensive (7
    reader calls a question, over 1,100 questions); not run by this build (the spec's limits)."""
    if capped_sh is None:
        raise ValueError("run_full needs --capped-sh: every query against the real index must be capped")
    ask_fn, embed_fn, cross_rerank_fn, cross_tokenizer = _real_fns(ask_fn, embed_fn, cross_rerank_fn, cross_tokenizer)
    workdir = Path(workdir or tempfile.mkdtemp(prefix="northstar2-full-"))
    (workdir / "bridge").mkdir(parents=True, exist_ok=True)
    (workdir / "comparison").mkdir(parents=True, exist_ok=True)
    common = dict(corpus_path=corpus_path, index_path=index_path, bin_path=bin_path, capped_sh=capped_sh,
                 capped_gb=capped_gb, model=model, ask_fn=ask_fn, embed_fn=embed_fn,
                 cross_rerank_fn=cross_rerank_fn, cross_tokenizer=cross_tokenizer, full=True)
    bridge = _run_arms(plan["questions"], workdir=workdir / "bridge", **common)
    comparison = _run_arms(plan["comparison_questions"], workdir=workdir / "comparison",
                           both_gold_primary=True, **common)
    return {"bridge": bridge, "comparison": comparison}


def _real_fns(ask_fn, embed_fn, cross_rerank_fn, cross_tokenizer):
    """Fills in the real model/embedder/reranker where a caller left one out -- factored out of
    ``run_smoke``/``run_full`` so loading them (expensive; the reranker is ~1 GB) happens at most once."""
    if ask_fn is None:
        def ask_fn(model, prompt_text):
            return ask(model, prompt_text, system=PROMPTS[PROMPT_VERSION])
    if embed_fn is None or cross_rerank_fn is None or cross_tokenizer is None:
        if embed_fn is None:
            from embeddings import NomicEmbedProvider

            embed_fn = NomicEmbedProvider().embed
        if cross_rerank_fn is None or cross_tokenizer is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            cross_encoder = TextCrossEncoder(model_name=CROSS_ENCODER_MODEL)
            list(cross_encoder.rerank("warm", ["up"]))  # force the load so .model.tokenizer exists
            cross_rerank_fn = cross_encoder.rerank
            cross_tokenizer = cross_encoder.model.tokenizer
    return ask_fn, embed_fn, cross_rerank_fn, cross_tokenizer


# =====================================================================================
# rescore: recompute the whole summary from a saved run's own answers, no model calls.
# =====================================================================================

def _rescore_stratum(stratum_results: dict, questions: list[dict], *, both_gold_primary: bool) -> dict:
    """One stratum's whole summary, recomputed from its saved rows and the questions that produced them --
    no model calls, no retrieval. ``answer_lead_recall``/``both_gold`` are rebuilt fresh from each row's
    saved ``leads``; ``em``/``f1`` are rebuilt fresh from each row's saved ``answer`` through
    ``score_reader``, never read from the row's own (possibly wrong) field -- the same guard test 1's bug
    taught."""
    by_id = {q["id"]: q for q in questions}
    rows = {}
    for arm, arm_rows in stratum_results["rows"].items():
        rescored = {}
        for qid, row in arm_rows.items():
            if qid not in by_id:
                continue
            q = by_id[qid]
            leads = row["leads"]
            rescored[qid] = {
                **row,
                "answer_lead_recall": answer_lead_recall_at_two(leads, q),
                "both_gold": both_gold_at_two(leads, q),
                **score_reader(row["answer"], q),
            }
        rows[arm] = rescored
    return summarize2(questions, rows, stratum_results.get("usage", {}), stratum_results.get("truncation", {}),
                      both_gold_primary=both_gold_primary)


def rescore2(results: dict, plan: dict) -> dict:
    """Both strata's whole summaries (revision 3), recomputed from a saved run's saved rows and the plan
    that produced them -- no model calls, no retrieval, reported apart."""
    bridge = _rescore_stratum(results["bridge"], plan["questions"], both_gold_primary=False)
    comparison = (_rescore_stratum(results["comparison"], plan["comparison_questions"], both_gold_primary=True)
                 if results.get("comparison") else None)
    return {"bridge": bridge, "comparison": comparison}


# =====================================================================================
# CLI
# =====================================================================================

def _cmd_plan(args: argparse.Namespace) -> int:
    import pyarrow.parquet as pq

    rows = pq.read_table(args.parquet).to_pylist()
    excluded = load_excluded_ids(args.exclude)
    corpus = CorpusLookup.open(args.corpus)
    redirects = sqlite3.connect(f"file:{args.redirects}?mode=ro", uri=True)

    def query_fn(items, k):
        if args.capped_sh:
            return run_queries_capped(args.bin, args.index, items, k, capped_sh=args.capped_sh,
                                      mem_gb=args.capped_gb)
        return run_queries(args.bin, args.index, items, k)

    nemotron_digest = ollama_model_digest(MODEL)

    from embeddings import NomicEmbedProvider
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    dense = NomicEmbedProvider()
    dense.embed(["warm up"])
    dense_digest = model_digest(dense._model.model)

    cross_encoder = TextCrossEncoder(model_name=CROSS_ENCODER_MODEL)
    list(cross_encoder.rerank("warm", ["up"]))
    cross_digest = model_digest(cross_encoder.model)
    cross_truncation = reranker_truncation_settings(cross_encoder.model.tokenizer)

    plan = build_plan(rows, excluded, corpus, redirects, query_fn=query_fn, target=args.target,
                      min_qualifying=args.min_qualifying, nemotron_digest=nemotron_digest,
                      dense_digest=dense_digest, cross_digest=cross_digest, cross_truncation=cross_truncation)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(plan, handle, indent=1, sort_keys=True)
    summary = {k: v for k, v in plan.items() if k not in ("questions", "comparison_questions")}
    sizes = [q["g_pool_size"] for q in plan["questions"]]
    summary["g_pool_size_sample"] = sizes[:10]
    summary["g_pool_size_median"] = sorted(sizes)[len(sizes) // 2] if sizes else None
    comparison_sizes = [q["g_pool_size"] for q in plan["comparison_questions"]]
    summary["comparison_g_pool_size_sample"] = comparison_sizes[:10]
    summary["comparison_g_pool_size_median"] = (sorted(comparison_sizes)[len(comparison_sizes) // 2]
                                                if comparison_sizes else None)
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    with open(args.plan, encoding="utf-8") as handle:
        plan = json.load(handle)
    if args.full:
        result = run_full(plan, corpus_path=args.corpus, index_path=args.index, bin_path=args.bin,
                          capped_sh=args.capped_sh, capped_gb=args.capped_gb, model=plan.get("model", MODEL))
    else:
        result = run_smoke(plan, corpus_path=args.corpus, index_path=args.index, bin_path=args.bin,
                           capped_sh=args.capped_sh, capped_gb=args.capped_gb, count=args.count,
                           model=plan.get("model", MODEL))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=1)
    slim = {stratum: ({k: v for k, v in data.items() if k != "rows"} if data else None)
           for stratum, data in result.items()}
    print(json.dumps(slim, indent=1))
    return 0


def _cmd_rescore(args: argparse.Namespace) -> int:
    with open(args.results, encoding="utf-8") as handle:
        results = json.load(handle)
    with open(args.plan, encoding="utf-8") as handle:
        plan = json.load(handle)
    summary = rescore2(results, plan)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=1, sort_keys=True)
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="North-star test 2: retrieval against strong baselines")
    sub = parser.add_subparsers(dest="mode", required=True)

    plan_parser = sub.add_parser("plan", help="compute the pre-registration; no reader-model calls")
    plan_parser.add_argument("--corpus", required=True)
    plan_parser.add_argument("--redirects", required=True)
    plan_parser.add_argument("--parquet", required=True)
    plan_parser.add_argument("--index", required=True)
    plan_parser.add_argument("--bin", default=str(DEFAULT_CORPUS_INDEX_BIN))
    plan_parser.add_argument("--exclude", nargs="+", default=list(DEFAULT_EXCLUDE_FILES) + [DEFAULT_TEST1_PLAN])
    plan_parser.add_argument("--capped-sh", default=None, help="capped.sh, required for a real --index")
    plan_parser.add_argument("--capped-gb", type=int, default=16)
    plan_parser.add_argument("--target", type=int, default=TARGET_QUALIFYING)
    plan_parser.add_argument("--min-qualifying", type=int, default=MIN_QUALIFYING)
    plan_parser.add_argument("--out", default="plan.json")
    plan_parser.set_defaults(func=_cmd_plan)

    run_parser = sub.add_parser("run", help="execute a plan (a smoke of at most 10 questions by default)")
    run_parser.add_argument("--plan", required=True)
    run_parser.add_argument("--corpus", required=True)
    run_parser.add_argument("--index", required=True)
    run_parser.add_argument("--bin", default=str(DEFAULT_CORPUS_INDEX_BIN))
    run_parser.add_argument("--capped-sh", default=None, help="capped.sh, required while --index is the full corpus")
    run_parser.add_argument("--capped-gb", type=int, default=16)
    run_parser.add_argument("--count", type=int, default=SMOKE_LIMIT, help="ignored with --full (always all 800)")
    run_parser.add_argument("--full", action="store_true",
                            help="run every question in the plan (needs --capped-sh); the default is a "
                                 "smoke of --count questions (at most 10)")
    run_parser.add_argument("--out")
    run_parser.set_defaults(func=_cmd_run)

    rescore_parser = sub.add_parser("rescore", help="recompute the whole summary from a saved run; no model calls")
    rescore_parser.add_argument("--results", required=True)
    rescore_parser.add_argument("--plan", required=True)
    rescore_parser.add_argument("--out")
    rescore_parser.set_defaults(func=_cmd_rescore)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
