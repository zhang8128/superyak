"""Issue #8's native speed-up: the Rust ``corpus-index`` crate against a brute-force Python BM25
with the exact same formula, on a tiny corpus built with ``atlas/workbench/research_corpus.build``.

Skips (rather than fails) when either half of the toolchain isn't here: ``atlas`` beside
``engram`` (the pattern ``test_multihop_open.py`` uses), or ``cargo`` to build the crate with.
Nothing here runs the crate's own ``cargo test`` suite; this is a black-box check that the
compiled binary's picks agree with an independent reimplementation of the same math.
"""
from __future__ import annotations

from collections import Counter
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.multihop_atlas import research_corpus
from experiments.multihop.export_corpus_tsv import export

build = research_corpus().build

CRATE_DIR = Path(__file__).resolve().parents[1] / "native" / "corpus_index"

MANIFEST = {"id": "t", "name": "T", "snapshot": "2026-11-07", "question_derived": False}
RECORDS = [
    {"title": "Lotus (band)", "page_id": 1, "rev_id": 1, "text": "Lotus is a band whose singer was Ann Vale.",
     "links": ["Ann Vale"]},
    {"title": "Ann Vale", "page_id": 2, "rev_id": 2, "text": "Ann Vale grew up in Leeds in 1970.", "links": []},
    {"title": "Lotus Temple", "page_id": 3, "rev_id": 3, "text": "The Lotus Temple is a building in Delhi.",
     "links": []},
]

QUERIES = [
    ("q_hop", "Where did the singer of the band Lotus grow up"),
    ("q_fallback", "Lotus Temple Delhi building"),
    ("q_zero_score_link", "Lotus band"),
    ("q_top1", "Lotus band singer"),
    ("q_unknown", "xyzzyplughquux nosuchword"),
]

K1, B = 1.2, 0.75


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
    env = {**os.environ, "PATH": f"{Path(cargo).parent}:{os.environ.get('PATH', '')}"}
    result = subprocess.run([cargo, "build", "--offline", "--message-format=json"], cwd=CRATE_DIR,
                            capture_output=True, text=True, env=env)
    if result.returncode != 0:
        pytest.fail(f"cargo build --offline failed:\n{result.stdout}\n{result.stderr}")
    # cargo names the executable it built, wherever CARGO_TARGET_DIR or a config puts it.
    built = [m["executable"] for m in map(json.loads, result.stdout.splitlines())
             if m.get("reason") == "compiler-artifact" and m.get("executable")
             and m.get("target", {}).get("name") == "corpus-index"]
    if len(built) != 1 or not Path(built[0]).exists():
        pytest.fail(f"cargo's build messages name no single corpus-index executable: {built}")
    return Path(built[0])


@pytest.fixture
def tsvs(tmp_path):
    corpus_path = tmp_path / "c.sqlite3"
    build(RECORDS, MANIFEST, corpus_path)
    docs_path, links_path = tmp_path / "docs.tsv", tmp_path / "links.tsv"
    export(corpus_path, docs_path, links_path)
    return docs_path, links_path


def _read_docs(docs_path) -> list[tuple[int, str, str]]:
    docs = []
    for line in docs_path.read_text(encoding="utf-8").splitlines():
        page_id, title, text = line.split("\t", 2)
        docs.append((int(page_id), title, text))
    return docs


def _read_links(links_path) -> list[tuple[int, int]]:
    links = []
    for line in links_path.read_text(encoding="utf-8").splitlines():
        src, dst = line.split("\t")
        links.append((int(src), int(dst)))
    return links


def _tokenize(text: str) -> list[str]:
    """The same rule as the crate's ``tokenize::tokenize``: lowercase, then split on anything
    that isn't alphanumeric."""
    lowered = text.lower()
    return "".join(ch if ch.isalnum() else " " for ch in lowered).split()


def _idf(n: int, df: int) -> float:
    return math.log(1 + (n - df + 0.5) / (df + 0.5))


def _contribution(idf_value: float, tf: int, doc_len: int, avg_len: float) -> float:
    if tf <= 0:
        return 0.0
    length_norm = (1 - B + B * doc_len / avg_len) if avg_len > 0 else (1 - B)
    denom = tf + K1 * length_norm
    return 0.0 if denom <= 0 else idf_value * (tf * (K1 + 1)) / denom


def brute_force_bm25(docs: list[tuple[int, str, str]], links: list[tuple[int, int]],
                      query: str, k: int) -> tuple[list[int], list[int]]:
    """A line-for-line transliteration of ``Index::query`` in ``src/index.rs``: same idf, same
    length normalization, same "> 0" hop guard, same tie-break by the smaller doc index, same
    fallback to BM25's rank-2 pick. ``docs`` must be in the order ``docs.tsv`` lists them (doc
    index 0..N-1), exactly as the crate assigns doc indices."""
    n = len(docs)
    page_ids = [d[0] for d in docs]
    tokens = [_tokenize(f"{title} {text}") for _, title, text in docs]
    doc_len = [len(t) for t in tokens]
    avg_len = sum(doc_len) / n if n else 0.0
    tf = [Counter(t) for t in tokens]
    df: Counter[str] = Counter()
    for counts in tf:
        for term in counts:
            df[term] += 1

    page_id_to_idx: dict[int, int] = {}
    for idx, pid in enumerate(page_ids):
        page_id_to_idx.setdefault(pid, idx)
    adjacency: list[list[int]] = [[] for _ in range(n)]
    for src, dst in links:
        s, d = page_id_to_idx.get(src), page_id_to_idx.get(dst)
        if s is not None and d is not None:
            adjacency[s].append(d)
    adjacency = [sorted(set(row)) for row in adjacency]

    terms = list(dict.fromkeys(_tokenize(query)))

    def score_doc(idx: int, terms: list[str]) -> float:
        total = 0.0
        for term in terms:
            d = df.get(term, 0)
            f = tf[idx].get(term, 0)
            if d == 0 or f == 0:
                continue
            total += _contribution(_idf(n, d), f, doc_len[idx], avg_len)
        return total

    if not terms:
        return [], []
    scores = {idx: s for idx in range(n) if (s := score_doc(idx, terms)) > 0}
    if not scores:
        return [], []

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    need = max(k, 2)
    top = ranked[:need]
    bm25_ids = [page_ids[idx] for idx, _ in top[:k]]

    hop_ids: list[int] = []
    if top:
        first_idx, _ = top[0]
        best: tuple[int, float] | None = None
        for target in adjacency[first_idx]:
            s = score_doc(target, terms)
            if s > 0 and (best is None or s > best[1] or (s == best[1] and target < best[0])):
                best = (target, s)
        if best is not None:
            hop_ids = [page_ids[first_idx], page_ids[best[0]]]
        elif len(top) >= 2:
            hop_ids = [page_ids[first_idx], page_ids[top[1][0]]]
        else:
            hop_ids = [page_ids[first_idx]]
    return bm25_ids, hop_ids


def run_rust_queries(binary, index_path, queries: list[tuple[str, str]], k: int) -> dict[str, tuple[list[int], list[int]]]:
    stdin = "".join(f"{qid}\t{text}\n" for qid, text in queries)
    result = subprocess.run([str(binary), "query", "--index", str(index_path), "--k", str(k)],
                             input=stdin, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    picks = {}
    for line in result.stdout.splitlines():
        qid, bm25_field, hop_field = line.split("\t")
        picks[qid] = ([int(x) for x in bm25_field.split(",") if x], [int(x) for x in hop_field.split(",") if x])
    return picks


def test_rust_picks_equal_the_brute_force_python_bm25(corpus_index_bin, tsvs, tmp_path):
    docs_path, links_path = tsvs
    index_path = tmp_path / "index.bin"
    build_result = subprocess.run(
        [str(corpus_index_bin), "build", "--docs", str(docs_path), "--links", str(links_path),
         "--out", str(index_path)],
        capture_output=True, text=True)
    assert build_result.returncode == 0, build_result.stderr
    import json
    summary = json.loads(build_result.stdout)
    assert summary["docs"] == 3
    assert summary["links_kept"] == 1 and summary["links_dropped"] == 0

    docs, links = _read_docs(docs_path), _read_links(links_path)
    rust_picks = run_rust_queries(corpus_index_bin, index_path, QUERIES, k=2)

    assert set(rust_picks) == {qid for qid, _ in QUERIES}
    for qid, query in QUERIES:
        expected_bm25, expected_hop = brute_force_bm25(docs, links, query, k=2)
        got_bm25, got_hop = rust_picks[qid]
        assert got_bm25 == expected_bm25, f"{qid}: bm25 {got_bm25} != brute-force {expected_bm25}"
        assert got_hop == expected_hop, f"{qid}: hop {got_hop} != brute-force {expected_hop}"


def test_unknown_query_terms_give_empty_picks_through_the_real_binary(corpus_index_bin, tsvs, tmp_path):
    docs_path, links_path = tsvs
    index_path = tmp_path / "index.bin"
    subprocess.run([str(corpus_index_bin), "build", "--docs", str(docs_path), "--links", str(links_path),
                     "--out", str(index_path)], capture_output=True, text=True, check=True)
    picks = run_rust_queries(corpus_index_bin, index_path, [("q", "xyzzyplughquux nosuchword")], k=2)
    assert picks["q"] == ([], [])
