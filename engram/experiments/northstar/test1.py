"""North-star test 1: one environment, end to end, with a correction.

Spec: ``docs/superpowers/specs/2026-11-22-north-star-test-1-design.md`` (approved, revision 4). Draws 800
qualifying HotpotQA bridge questions from the train split, corrects half of their gold leads with a seeded
substitute (a year, a person, or any other name -- revision 4 splits "name" in two so a donor never swaps a
person for a place), and compares the environment arm (E: BM25 then one link hop through ``corpus-index``,
answers recorded as Atlas claims citing the leads used) against a hybrid baseline (B-all: BM25's top 100
reranked by a dense embedder) on exact match and model calls after the correction, paired, with a 95% CI --
"fails" whatever the accuracy if E isn't cheaper (revision 4). E-all (revision 4, secondary: E's own
retrieval re-asking every question) isolates what targeting saves from how well E retrieves. B-cache (a
floor: B's first answers, never re-asked) and closed book (the corrected half with no evidence) read beside it.

Two modes:
- ``plan``: everything the pre-registration fixes -- seeds, the qualifying count and draws needed, the 800
  ids, the corrected/control split, each substitute, and the overlay's sha256 -- with **no model calls**.
  Writes ``plan.json``.
- ``run --plan plan.json``: a smoke of at most 10 questions (the default), with a *small* corrected index
  built only from the pages that smoke touches -- this build's limits. ``run --plan plan.json --full`` runs
  every one of the 800 with the real, full-corpus corrected index, every full-index query through
  ``capped.sh``; expensive, and not run by this build.

Usage (PYTHONPATH must include this repo's ``engram`` and, for ``run``, ``atlas`` too -- as
``hotpot_open.py``'s docstring already asks for Atlas-backed scripts here):
``PYTHONPATH=engram python -m experiments.northstar.test1 plan --corpus C.sqlite3 --redirects R.sqlite3
--parquet P.parquet --out plan.json``
``PYTHONPATH=engram:atlas python -m experiments.northstar.test1 run --plan plan.json --corpus C.sqlite3
--index index.bin --store store.db --out results.json``
``PYTHONPATH=engram:atlas python -m experiments.northstar.test1 run --plan plan.json --full --corpus C.sqlite3
--index index.bin --store store.db --capped-sh capped.sh --out results.json``

Atlas's sources are immutable and ``retraction_impact`` only reads (R4), so this module holds its own
convention instead of editing anything in place: each lead revision is its own source (``wiki:<page
id>@<revision>``), a correction adds the new revision as a *new* source, and the claims to re-ask are exactly
what ``retraction_impact([old revisions])`` names -- withdrawn with ``set_status``, never deleted.

Atlas is imported only inside the functions that need it (never at module level): pytest imports every test
module before running any test, and a ``workbench`` import left at module level breaks the frozen Atlas
snapshot's bridge tests (``engram/tests/multihop_atlas.py``'s docstring; CI broke this way on 11-21).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shlex
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from experiments.multihop.hotpot_open import current_title
    from experiments.multihop.hotpot_open_rs import run_queries
    from experiments.multihop.hotpot_smoke import PROMPTS, ask, exact, f1
except ImportError:  # pragma: no cover - running as a bare file beside the other scripts
    from hotpot_open import current_title
    from hotpot_open_rs import run_queries
    from hotpot_smoke import PROMPTS, ask, exact, f1

# ---- Fixed before the run (the pre-registration; plan.json records every one of these) ----
POOL_SEED = 2026112201      # the pool's fixed draw order
SPLIT_SEED = 2026112202     # which half of the 800 qualifying is corrected
DONOR_SEED = 2026112203     # each correction's seeded donor choice
TARGET_QUALIFYING = 800
MIN_QUALIFYING = 500        # below this the run stops and the spec is revised (spec: "Draw")
MODEL = "nemotron-mini:latest"
PROMPT_VERSION = "v2"
E_K = 2                     # E's hop arm: BM25's top 1, then one link hop (as in the open test)
B_BM25_K = 100               # B-all's BM25 candidate pool before dense rerank
B_TOP = 2                    # leads either system actually reads
MARGIN = 5.0                 # the primary's accuracy margin, in exact-match points
CALLS_RATIO_THRESHOLD = 0.60  # E must use under this share of B-all's calls
SMOKE_LIMIT = 10
WIKI_URL_TEMPLATE = "https://en.wikipedia.org/?curid={page_id}&oldid={rev_id}"

DEFAULT_CORPUS_INDEX_BIN = (
    Path(__file__).resolve().parents[2] / "native" / "corpus_index" / "target" / "release" / "corpus-index"
)
DEFAULT_EXCLUDE_FILES = (
    "engram/experiments/multihop/results/router-fresh-c1-2026-11-21.json",
    "engram/experiments/multihop/results/router-fresh-c2-2026-11-21.json",
)


# =====================================================================================
# The corpus: point lookups only (by title or page id) -- never a full-table scan.
# =====================================================================================

class CorpusLookup:
    """Read-only, indexed lookups into a frozen corpus's ``passages`` table. ``title`` and ``page_id`` are
    both ``UNIQUE`` (``research_corpus.build``'s schema), so every lookup here is a single indexed row read,
    never a scan of the corpus's 7.2 million rows."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, path) -> "CorpusLookup":
        return cls(sqlite3.connect(f"file:{path}?mode=ro", uri=True))

    def by_title(self, title: str) -> dict | None:
        row = self._connection.execute(
            "SELECT page_id, rev_id, title, text FROM passages WHERE title = ?", (title,)
        ).fetchone()
        return None if row is None else {"page_id": row[0], "rev_id": row[1], "title": row[2], "text": row[3]}

    def by_page_id(self, page_id: int) -> dict | None:
        row = self._connection.execute(
            "SELECT page_id, rev_id, title, text FROM passages WHERE page_id = ?", (page_id,)
        ).fetchone()
        return None if row is None else {"page_id": row[0], "rev_id": row[1], "title": row[2], "text": row[3]}

    def iter_all(self):
        """Every ``(page_id, title, text)``, in page-id order -- the one deliberate full scan in this
        module, for the real, full-corpus corrected export only (``export_corrected_tsv`` with
        ``page_ids=None``). The smoke build and every other lookup here stay point lookups."""
        yield from self._connection.execute("SELECT page_id, title, text FROM passages ORDER BY page_id")

    def iter_links(self):
        """Every ``(src_title, dst_title)`` link, for the full-corpus export's link pass."""
        yield from self._connection.execute("SELECT src, dst FROM links ORDER BY src, dst")

    def links_from(self, page_id: int) -> list[int]:
        """Out-links from this page id, resolved to page ids -- a point lookup by ``links.src``, joined on
        ``title`` (``links`` is keyed by title; one row's worth of joins, not a scan)."""
        row = self.by_page_id(page_id)
        if row is None:
            return []
        rows = self._connection.execute(
            "SELECT p.page_id FROM links l JOIN passages p ON p.title = l.dst WHERE l.src = ?", (row["title"],)
        ).fetchall()
        return [r[0] for r in rows]


# =====================================================================================
# The qualifying rule (spec: "Questions and corrections")
# =====================================================================================

_YEAR_RE = None  # set below to keep `re` import local to this section
_BORN_WORD_RE = None
_YEAR_RANGE_RE = None


def _year_re():
    global _YEAR_RE
    if _YEAR_RE is None:
        import re

        _YEAR_RE = re.compile(r"^\d{4}$")
    return _YEAR_RE


def _born_word_re():
    global _BORN_WORD_RE
    if _BORN_WORD_RE is None:
        import re

        _BORN_WORD_RE = re.compile(r"\bborn\b")
    return _BORN_WORD_RE


def _year_range_re():
    """Two 3-or-4-digit years joined by a dash or en dash, with any text in between (a founding or life
    span: "1935-2010", "February 18, 1950 – August 6, 2009", "c. 1340 – 1400") -- widened from
    revision 4's first cut, which only caught a dash immediately next to both years."""
    global _YEAR_RANGE_RE
    if _YEAR_RANGE_RE is None:
        import re

        en_dash = chr(0x2013)  # built from its code point, not pasted, so this file's diff stays ASCII
        _YEAR_RANGE_RE = re.compile(r"\b\d{3,4}\b.*?[" + en_dash + r"-].*?\b\d{3,4}\b")
    return _YEAR_RANGE_RE


def _first_parenthetical(text: str, open_within: int = 200) -> str | None:
    """The content of the first parenthesis in ``text`` that *opens* within its first ``open_within``
    characters, or ``None`` when none does. Not nested-paren aware (a birth or life-span parenthesis in a
    Wikipedia lead isn't either), and the content itself isn't truncated at ``open_within`` -- only where
    the "(" falls is bounded, not how far the matching ")" is."""
    opens_at = text.find("(")
    if opens_at == -1 or opens_at >= open_within:
        return None
    closes_at = text.find(")", opens_at + 1)
    if closes_at == -1:
        return None
    return text[opens_at + 1:closes_at]


def _is_person_parenthetical(content: str) -> bool:
    """revision 4, widened: the word "born" anywhere in the parenthesis (so "(; born ...)", a stripped
    pronunciation guide before it, still counts), or two 3-or-4-digit years joined by a dash with any text
    between them (so a full birth-to-death date range with no "born" word, like "(February 18, 1950 -
    August 6, 2009)", counts too). A single year alone ("(founded 1890)") does not."""
    return bool(_born_word_re().search(content)) or bool(_year_range_re().search(content))


def _is_name_word(word: str) -> bool:
    """A single space-separated word of a name-shaped answer: starts with an uppercase letter, and every
    character is a (Unicode) letter, a period, a hyphen, or an apostrophe."""
    return bool(word) and word[0].isupper() and all(ch.isalpha() or ch in ".-'" for ch in word)


def is_name_shaped(answer: str) -> bool:
    """Every space-separated word starts with an uppercase letter and holds only letters (Unicode letters
    count, so "Curaçao" qualifies), periods, hyphens and apostrophes."""
    if not answer:
        return False
    words = answer.split(" ")
    return all(_is_name_word(word) for word in words)


def answer_shape(answer: str) -> str | None:
    """"year" for a bare four-digit year, "name" for a name-shaped answer (the structural check alone --
    before revision 4's split of "name" into "person" and "other_name"), else ``None`` (not a class this
    test substitutes)."""
    if not isinstance(answer, str):
        return None
    if _year_re().fullmatch(answer):
        return "year"
    if is_name_shaped(answer):
        return "name"
    return None


def classify_name(answer: str, corpus: CorpusLookup, redirects) -> str:
    """"person" when ``answer``, resolved through redirects the same way a gold title is, names a corpus v0
    article whose lead's *first* parenthesis opening in its first 200 characters is a birth or life-span one
    (see ``_is_person_parenthetical``); "other_name" otherwise -- including when ``answer`` doesn't resolve
    to any article in the corpus at all (revision 4: the re-check found a same-shape donor had swapped a
    person, "Sir Edward Seymour Hicks", for a county, "County Tyrone"; an unresolvable answer is treated the
    same as a resolvable non-person, not as an error), and including when the lead opens with a parenthesis
    that isn't a birth or life span at all ("(founded 1890)")."""
    lead = corpus.by_title(current_title(answer, redirects))
    if lead is None:
        return "other_name"
    content = _first_parenthetical(lead["text"])
    if content is None:
        return "other_name"
    return "person" if _is_person_parenthetical(content) else "other_name"


def answer_class(answer: str, corpus: CorpusLookup, redirects) -> str | None:
    """"year", "person" or "other_name" (revision 4's three substitution classes), or ``None`` when
    ``answer`` is neither a bare four-digit year nor name-shaped at all."""
    shape = answer_shape(answer)
    if shape is None:
        return None
    if shape == "year":
        return "year"
    return classify_name(answer, corpus, redirects)


def whole_word_occurrences(text: str, word: str) -> list[int]:
    """Start indices of ``word`` in ``text`` as a whole word: the character immediately before and after a
    match is never a *continuation* character for ``word``'s own class -- a digit, for a digit word ("1970"
    must not match inside "11970" or "19705"); a letter, for a letter-starting word ("Ann" must not match
    inside "Annabelle"). Case-sensitive. Overlapping occurrences can't happen since a match always consumes
    ``word``'s own length before the next search starts."""
    if not word or not text:
        return []
    is_continuation = (lambda ch: ch.isdigit()) if word[0].isdigit() else (lambda ch: ch.isalpha())
    occurrences = []
    start = 0
    while True:
        index = text.find(word, start)
        if index == -1:
            break
        before_ok = index == 0 or not is_continuation(text[index - 1])
        after_ok = index + len(word) == len(text) or not is_continuation(text[index + len(word)])
        if before_ok and after_ok:
            occurrences.append(index)
        start = index + 1
    return occurrences


def replace_whole_word(text: str, word: str, substitute: str) -> str:
    """``text`` with every whole-word occurrence of ``word`` (see ``whole_word_occurrences``) replaced by
    ``substitute``, left to right. A no-op (returns ``text`` itself) when there's nothing to replace."""
    occurrences = whole_word_occurrences(text, word)
    if not occurrences:
        return text
    pieces = []
    cursor = 0
    for index in occurrences:
        pieces.append(text[cursor:index])
        pieces.append(substitute)
        cursor = index + len(word)
    pieces.append(text[cursor:])
    return "".join(pieces)


def qualifying_leads(row: dict, corpus: CorpusLookup, redirects) -> dict | None:
    """``None`` when ``row`` (one HotpotQA record) doesn't qualify for this test; otherwise a dict holding
    ``gold_leads`` (the two lead dicts from ``CorpusLookup``, in the order their 2017 titles originally came
    in), ``answer_class`` ("year", "person" or "other_name", revision 4), and ``corrected_lead_index`` (0 or
    1: which of the two holds the answer as a whole word -- exactly one must).

    The rule (spec, "Qualifying rule"): a bridge question, whose answer is a bare four-digit year or
    name-shaped, whose two gold leads both resolve (through redirects) to distinct articles present in the
    corpus, and whose answer occurs as a whole word in exactly one of those two leads' text.
    """
    if row.get("type") != "bridge":
        return None
    cls = answer_class(row.get("answer", ""), corpus, redirects)
    if cls is None:
        return None
    gold_titles_2017 = row["supporting_facts"]["title"]
    if len(set(gold_titles_2017)) != 2:
        return None
    current_titles = [current_title(t, redirects) for t in gold_titles_2017]
    if len(set(current_titles)) != 2:  # a 2017 pair that now redirects to one article isn't two gold leads
        return None
    leads = [corpus.by_title(t) for t in current_titles]
    if any(lead is None for lead in leads):
        return None
    hits = [bool(whole_word_occurrences(lead["text"], row["answer"])) for lead in leads]
    if sum(hits) != 1:
        return None
    return {"gold_leads": leads, "answer_class": cls, "corrected_lead_index": hits.index(True)}


# =====================================================================================
# The seeded draw (spec: "Draw")
# =====================================================================================

def draw_qualifying(pool_rows: list[dict], corpus: CorpusLookup, redirects, *,
                     target: int = TARGET_QUALIFYING, seed: int = POOL_SEED) -> tuple[list[dict], int]:
    """``pool_rows`` visited in the order a seeded shuffle fixes, keeping each ``row | qualifying_leads(row)``
    that qualifies, until ``target`` are found (or the pool runs out). Returns ``(qualifying, draws)``, where
    ``draws`` is how many rows were examined to find them -- reported even when every one qualified."""
    order = list(range(len(pool_rows)))
    random.Random(seed).shuffle(order)
    qualifying: list[dict] = []
    draws = 0
    for index in order:
        draws += 1
        row = pool_rows[index]
        info = qualifying_leads(row, corpus, redirects)
        if info is not None:
            qualifying.append({**row, **info})
            if len(qualifying) >= target:
                break
    return qualifying, draws


def split_corrected_and_control(qualifying: list[dict], *, seed: int = SPLIT_SEED) -> tuple[list[int], list[int]]:
    """Indices into ``qualifying`` for the corrected half and the control half, chosen by seed (an even split;
    an odd count leaves the extra one a control)."""
    n = len(qualifying)
    half = n // 2
    corrected = sorted(random.Random(seed).sample(range(n), half))
    control = sorted(set(range(n)) - set(corrected))
    return corrected, control


def choose_substitutes(qualifying: list[dict], corrected_indices: list[int], *,
                        seed: int = DONOR_SEED) -> dict[int, str]:
    """For each corrected index: another qualifying question's answer of the same class, never equal to the
    original, from a single seeded ``random.Random`` consumed in ascending index order (so the draw doesn't
    depend on how the caller orders ``corrected_indices``)."""
    rng = random.Random(seed)
    by_class: dict[str, list[str]] = {}
    for q in qualifying:
        by_class.setdefault(q["answer_class"], []).append(q["answer"])
    substitutes: dict[int, str] = {}
    for index in sorted(corrected_indices):
        q = qualifying[index]
        candidates = [a for a in by_class[q["answer_class"]] if a != q["answer"]]
        if not candidates:
            raise ValueError(f"no distinct same-class donor answer for qualifying question {index} ({q['id']!r})")
        substitutes[index] = rng.choice(candidates)
    return substitutes


# =====================================================================================
# The overlay (spec: "The corrected corpus (R5)")
# =====================================================================================

def build_overlay(qualifying: list[dict], corrected_indices: list[int], substitutes: dict[int, str]) -> list[dict]:
    """One row per corrected page: ``page_id``, ``old_rev``/``new_rev``, ``old_text``/``new_text``, and the new
    text's sha256. When two corrected questions' answers fall on the same page, both substitutions apply to
    that one page (in ascending corrected-index order), still one row."""
    by_page: dict[int, dict] = {}
    for index in sorted(corrected_indices):
        q = qualifying[index]
        lead = q["gold_leads"][q["corrected_lead_index"]]
        page_id = lead["page_id"]
        entry = by_page.setdefault(page_id, {
            "page_id": page_id, "old_rev": lead["rev_id"], "title": lead["title"],
            "old_text": lead["text"], "new_text": lead["text"],
        })
        entry["new_text"] = replace_whole_word(entry["new_text"], q["answer"], substitutes[index])
    rows = []
    for page_id in sorted(by_page):
        entry = by_page[page_id]
        new_rev = f"{entry['old_rev']}c1"
        rows.append({
            "page_id": entry["page_id"], "title": entry["title"],
            "old_rev": entry["old_rev"], "new_rev": new_rev,
            "old_text": entry["old_text"], "new_text": entry["new_text"],
            "new_text_sha256": hashlib.sha256(entry["new_text"].encode("utf-8")).hexdigest(),
        })
    return rows


def overlay_sha256(rows: list[dict]) -> str:
    """The overlay's identity: one escaped JSON line per row (page id, old/new rev, old/new text), in page-id
    order, hashed -- so a reordered or edited overlay is caught by a value recorded outside it (the same
    convention ``research_corpus._digest`` uses for the corpus itself)."""
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda r: r["page_id"]):
        line = json.dumps(
            {k: row[k] for k in ("page_id", "old_rev", "new_rev", "old_text", "new_text")},
            sort_keys=True, ensure_ascii=False,
        )
        digest.update((line + "\n").encode("utf-8"))
    return digest.hexdigest()


# =====================================================================================
# The pre-registered plan
# =====================================================================================

def build_plan(rows: list[dict], excluded_ids: set, corpus: CorpusLookup, redirects, *,
               target: int = TARGET_QUALIFYING, min_qualifying: int = MIN_QUALIFYING,
               pool_seed: int = POOL_SEED, split_seed: int = SPLIT_SEED, donor_seed: int = DONOR_SEED) -> dict:
    """Everything the pre-registration fixes, with no model call: the pool, the draw, the correction/control
    split, every substitute, and the overlay with its sha256."""
    pool_rows = [row for row in rows if row["id"] not in excluded_ids]
    qualifying, draws = draw_qualifying(pool_rows, corpus, redirects, target=target, seed=pool_seed)
    if len(qualifying) < min_qualifying:
        raise RuntimeError(
            f"only {len(qualifying)} qualifying questions in the whole pool of {len(pool_rows)}; "
            f"the spec requires at least {min_qualifying} before a run (spec: 'Draw')"
        )

    corrected_idx, control_idx = split_corrected_and_control(qualifying, seed=split_seed)
    substitutes = choose_substitutes(qualifying, corrected_idx, seed=donor_seed)
    overlay = build_overlay(qualifying, corrected_idx, substitutes)
    corrected_set = set(corrected_idx)

    questions = []
    for i, q in enumerate(qualifying):
        entry = {
            "id": q["id"], "question": q["question"], "answer": q["answer"], "answer_class": q["answer_class"],
            "gold_leads": [{"page_id": lead["page_id"], "rev_id": lead["rev_id"], "title": lead["title"]}
                          for lead in q["gold_leads"]],
            "corrected_lead_index": q["corrected_lead_index"],
            "arm": "corrected" if i in corrected_set else "control",
        }
        if i in corrected_set:
            entry["substitute"] = substitutes[i]
        questions.append(entry)

    class_counts: dict[str, int] = {}
    for q in qualifying:
        class_counts[q["answer_class"]] = class_counts.get(q["answer_class"], 0) + 1

    return {
        "seeds": {"pool": pool_seed, "split": split_seed, "donor": donor_seed},
        "target": target, "min_qualifying": min_qualifying,
        "pool_size": len(pool_rows), "excluded_ids": len(excluded_ids),
        "qualifying_found": len(qualifying), "draws_needed": draws,
        "corrected_count": len(corrected_idx), "control_count": len(control_idx),
        "class_counts": class_counts,
        "questions": questions,
        "overlay": overlay, "overlay_sha256": overlay_sha256(overlay),
        "model": MODEL, "prompt_version": PROMPT_VERSION,
        "e_k": E_K, "b_bm25_k": B_BM25_K, "b_top": B_TOP,
        "margin": MARGIN, "calls_ratio_threshold": CALLS_RATIO_THRESHOLD,
    }


# =====================================================================================
# Atlas records -- one revision, one source (spec: "One revision, one source (R4)")
# =====================================================================================

def source_id(page_id: int, rev_id) -> str:
    return f"wiki:{page_id}@{rev_id}"


def source_url(page_id: int, rev_id) -> str:
    return WIKI_URL_TEMPLATE.format(page_id=page_id, rev_id=rev_id)


def source_record(page_id: int, rev_id, title: str, year: int = 2026) -> dict:
    return {
        "id": source_id(page_id, rev_id), "title": title, "url": source_url(page_id, rev_id),
        "year": year, "citation": f"{title}. Wikipedia, revision {rev_id}.",
    }


def claim_id(question_id: str, attempt: int = 1) -> str:
    return f"claim-e-{question_id}-{attempt}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def claim_record(question_id: str, question_text: str, answer: str, leads: list[dict], attempt: int = 1) -> dict:
    """E's claim for one question: the answer, citing each lead it used. No evidence (a closed-book answer)
    means it can only be ``proposed`` -- Atlas's validation refuses source-backed statuses without evidence."""
    evidence = [
        {"source_id": source_id(lead["page_id"], lead["rev_id"]), "locator": lead["title"], "note": question_text}
        for lead in leads
    ]
    reviewed = bool(evidence)
    return {
        "id": claim_id(question_id, attempt), "kind": "claim",
        "title": f"E's answer to {question_id} (attempt {attempt})", "summary": answer,
        "status": "reviewed" if reviewed else "proposed",
        "evidence": evidence,
        "reviewed_by": "test1" if reviewed else "", "reviewed_at": _utc_now() if reviewed else "",
    }


def open_store(path, *, create: bool = False):
    """Atlas's ``Store``, imported only here (never at module level -- see the module docstring)."""
    from workbench.store import Store

    return Store(path, create=create)


def record_e_claim(store, question_id: str, question_text: str, answer: str, leads: list[dict],
                   attempt: int = 1) -> dict:
    """Imports the question's lead sources (each its own revision; a repeat import of the same source id with
    the same fields is a no-op) and the claim itself, and returns the normalized claim record."""
    sources = [source_record(lead["page_id"], lead["rev_id"], lead["title"]) for lead in leads]
    claim = claim_record(question_id, question_text, answer, leads, attempt=attempt)
    bundle = {"schema_version": 1, "title": "North-star test 1", "sources": sources, "items": [claim],
              "relations": []}
    store.import_bundle(bundle)
    return claim


def impacted_claim_ids(store, overlay_rows: list[dict]) -> list[str]:
    """The claims to re-ask: exactly what ``retraction_impact`` names over the overlay's *old* revisions
    (spec: "The questions to ask again are exactly the claims retraction_impact([old revisions]) names").

    ``retraction_impact`` refuses a source id it has never seen -- and an overlay page that no claim ever
    cited (E's own BM25/hop retrieval can simply miss a gold lead) never became a source at all, on a smoke
    run's handful of claims as much as on a full 800-question run. Such a page can't be "the claims that
    cite it" because nothing cites a source that doesn't exist, so it's dropped before asking, not an error."""
    old_sources = [source_id(row["page_id"], row["old_rev"]) for row in overlay_rows]
    existing = {record["id"] for record in store.export_bundle()["sources"]}
    old_sources = [s for s in old_sources if s in existing]
    if not old_sources:
        return []
    report = store.retraction_impact(old_sources)
    return [item["id"] for item in report["items"] if item["kind"] == "claim"]


def withdraw_claim(store, claim_id_: str, reason: str, actor: str = "test1") -> None:
    """Never deletes -- ``set_status`` keeps the withdrawn claim for ``history_as_of`` (spec: "withdraw ...
    never delete")."""
    store.set_status(claim_id_, "withdrawn", reason, actor)


def history_before_correction(store, claim_id_: str, at: str) -> dict:
    """What ``history_as_of`` says the claim's status was just before ``at`` -- the measure in "History"."""
    return store.history_as_of(claim_id_, at)


# =====================================================================================
# Retrieval: E's loop and B's loop
# =====================================================================================

def e_pick_leads(bin_path, index_path, corpus: CorpusLookup, question_id: str, question_text: str,
                 k: int = E_K, picks=None) -> list[dict]:
    """E's evidence: BM25 then one link hop through ``corpus-index`` (the open test's hop arm), read back as
    lead dicts. ``picks`` lets a caller reuse one batched ``run_queries`` call across many questions."""
    if picks is None:
        picks = run_queries(bin_path, index_path, [(question_id, question_text)], k)
    _, hop_ids = picks.get(question_id, ([], []))
    return [lead for pid in hop_ids if (lead := corpus.by_page_id(pid)) is not None]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. ``NomicEmbedProvider.embed`` already L2-normalizes, so this is a plain dot product
    for vectors it returns, but it normalizes itself too, to stay correct for any vectors a test hands it."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def dense_rerank(question_text: str, candidates: list[dict], embed_fn, top: int = B_TOP) -> list[dict]:
    """``candidates`` (each with "title"/"text"), reranked by cosine similarity to the question in the dense
    embedder's space (``search_query``/``search_document`` prefixes, as ``engram/embeddings.py`` does),
    highest first, truncated to ``top``. ``embed_fn(texts, prefix) -> list[list[float]]`` so a test can stand
    in a fake embedder with no model load."""
    if not candidates:
        return []
    query_vec = embed_fn([question_text], prefix="search_query")[0]
    doc_vecs = embed_fn([f"{c['title']} {c['text']}" for c in candidates], prefix="search_document")
    scored = sorted(zip(candidates, doc_vecs), key=lambda pair: -cosine(query_vec, pair[1]))
    return [candidate for candidate, _ in scored[:top]]


def b_pick_leads(bin_path, index_path, corpus: CorpusLookup, embed_fn, question_id: str, question_text: str,
                 bm25_k: int = B_BM25_K, top: int = B_TOP, picks=None) -> list[dict]:
    """B-all's evidence: BM25's top ``bm25_k`` from ``corpus-index``, dense-reranked, top ``top`` leads."""
    if picks is None:
        picks = run_queries(bin_path, index_path, [(question_id, question_text)], bm25_k)
    bm25_ids, _ = picks.get(question_id, ([], []))
    candidates = [lead for pid in bm25_ids if (lead := corpus.by_page_id(pid)) is not None]
    return dense_rerank(question_text, candidates, embed_fn, top=top)


# =====================================================================================
# The prompt and the leakage guard (spec: "No leakage (R6)")
# =====================================================================================

def build_prompt(question_text: str, leads: list[dict]) -> str:
    """The question with its retrieved leads only. There is no parameter for a prior answer or claim, so a
    caller literally cannot pass one in -- the leakage guard holds by construction, and
    ``assert_no_leakage`` double-checks a specific run's output against it."""
    if not leads:
        return f"Question: {question_text}"
    evidence = "\n\n".join(f"[{lead['title']}] {lead['text']}" for lead in leads)
    return f"Paragraphs:\n{evidence}\n\nQuestion: {question_text}"


def assert_no_leakage(built_prompt: str, forbidden: list[str]) -> None:
    """Raises when a re-ask prompt holds a string it must never hold (a prior answer, a withdrawn claim's
    text)."""
    for text in forbidden:
        if text and text in built_prompt:
            raise AssertionError(f"leakage guard violated: {text!r} found in the re-ask prompt")


def real_ask(model: str, prompt_text: str) -> tuple[str, float, dict]:
    return ask(model, prompt_text, system=PROMPTS[PROMPT_VERSION])


# =====================================================================================
# Scoring (spec: "Measures, fixed before the run")
# =====================================================================================

def source_support(cited_leads: list[dict], gold_leads: list[dict]) -> bool:
    """Both gold leads are among the leads an answer's claim cited."""
    cited_pages = {lead["page_id"] for lead in cited_leads}
    gold_pages = {lead["page_id"] for lead in gold_leads}
    return gold_pages <= cited_pages


def paired_ci(rows: list, f, g) -> dict:
    """The mean paired difference ``f(row) - g(row)`` over ``rows``, in points (x100), with a 95% CI (the
    normal approximation ``hotpot_router_fresh.paired`` already uses in this repo)."""
    diffs = [float(f(row)) - float(g(row)) for row in rows]
    n = len(diffs)
    if n < 2:
        raise ValueError("paired_ci needs at least two rows")
    mean = sum(diffs) / n
    variance = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    se = math.sqrt(variance) / math.sqrt(n)
    return {
        "n": n, "points": round(mean * 100, 2),
        "ci95": [round((mean - 1.96 * se) * 100, 2), round((mean + 1.96 * se) * 100, 2)],
    }


def primary_verdict(diff_ci: dict, e_calls: int, b_calls: int, *,
                    margin: float = MARGIN, calls_ratio_threshold: float = CALLS_RATIO_THRESHOLD) -> dict:
    """R2's primary, read off a 95% CI on (E's exact match - B-all's exact match), never off the point
    estimate alone: "succeeds" when the CI holds E within ``margin`` points of B-all AND E used under
    ``calls_ratio_threshold`` of B-all's calls; "borderline" when the CI straddles ``-margin`` (the
    pre-registered rule for when the interval can't decide it either way) *and* E was cheap enough; "fails"
    otherwise -- in particular, if E isn't cheaper, the verdict is "fails" whatever the accuracy (revision 4:
    a borderline-accuracy, not-cheaper case must not read as merely "borderline")."""
    lower, upper = diff_ci["ci95"]
    if lower > -margin:
        accuracy = "within margin"
    elif upper < -margin:
        accuracy = "more than margin under"
    else:
        accuracy = "borderline"
    calls_ratio = (e_calls / b_calls) if b_calls else float("inf")
    cheaper = calls_ratio < calls_ratio_threshold
    if not cheaper:
        verdict = "fails"
    elif accuracy == "borderline":
        verdict = "borderline"
    elif accuracy == "within margin":
        verdict = "succeeds"
    else:
        verdict = "fails"
    return {"diff_ci": diff_ci, "accuracy": accuracy, "e_calls": e_calls, "b_calls": b_calls,
            "calls_ratio": round(calls_ratio, 4), "cheaper": cheaper, "verdict": verdict}


def controls_unchanged(before: dict, after: dict, control_ids) -> dict:
    """For control questions only: how many answers changed across the correction, and how many of the ones
    that were exactly right before stayed right."""
    control_ids = set(control_ids)
    changed = right_before = right_and_unchanged = 0
    for qid in control_ids:
        b, a = before.get(qid), after.get(qid)
        if b is None or a is None:
            continue
        if b["answer"] != a["answer"]:
            changed += 1
        if b["em"]:
            right_before += 1
            if b["answer"] == a["answer"]:
                right_and_unchanged += 1
    return {"controls": len(control_ids), "answers_changed": changed,
            "right_before": right_before, "stayed_right": right_and_unchanged}


def stale_answers(before: dict, after: dict, corrected_ids, closed_book: dict) -> dict:
    """After the correction, how often an arm's answer still equals its *pre-correction* answer (plausibly
    stale), read beside how often the closed-book arm (no evidence at all) gives that same old answer."""
    corrected_ids = set(corrected_ids)
    stale = stale_matches_closed_book = 0
    for qid in corrected_ids:
        b, a = before.get(qid), after.get(qid)
        if b is None or a is None:
            continue
        if a["answer"] == b["answer"]:
            stale += 1
            cb = closed_book.get(qid)
            if cb is not None and cb["answer"] == b["answer"]:
                stale_matches_closed_book += 1
    return {"corrected": len(corrected_ids), "stale": stale, "stale_matches_closed_book": stale_matches_closed_book}


# =====================================================================================
# Building a corrected index -- the real export for a full run, and a small-subset
# export for this build's smoke (spec limits: never the full 7.2M rebuild here).
# =====================================================================================

def apply_overlay_text(page_id: int, text: str, overlay_by_page: dict[int, str]) -> str:
    return overlay_by_page.get(page_id, text)


def apply_overlay_lead(lead: dict, overlay_rows: list[dict]) -> dict:
    """``lead`` (a ``CorpusLookup`` row) with its revision and text replaced by the overlay's, when its page
    id is one of the corrected pages; unchanged otherwise. A claim that cites this lead then cites the *new*
    revision's own source id -- never the old one reused in place (R4: sources are immutable)."""
    by_page = {row["page_id"]: row for row in overlay_rows}
    row = by_page.get(lead["page_id"])
    if row is None:
        return lead
    return {**lead, "rev_id": row["new_rev"], "text": row["new_text"]}


def b_cache_from(before_b: dict) -> dict:
    """B-cache, a floor only: B's earlier answers, never asked again (spec: "B's earlier answers, never
    asked again"). Takes no model or ask function at all, so it cannot re-ask by construction."""
    return {qid: dict(row) for qid, row in before_b.items()}


def export_corrected_tsv(corpus: CorpusLookup, overlay_rows: list[dict], docs_path, links_path, *,
                         page_ids: set | None = None) -> dict:
    """``docs.tsv``/``links.tsv`` for ``corpus-index build``, with the overlay's corrected text applied.

    ``page_ids`` given (a smoke's handful of pages): each is a point lookup, never a scan of the corpus --
    the small stand-in ``run_smoke`` uses, per this build's limits (never the full 7.2M rebuild in this
    build). ``page_ids=None``: the real, full-corpus export (the same single scan
    ``export_corpus_tsv.export`` already does, with the overlay's substitutions folded in) -- what the
    lead's full run uses; this build never calls it against the real corpus."""
    import re

    bad = re.compile(r"[\t\r\n]")
    overlay_by_page = {row["page_id"]: row["new_text"] for row in overlay_rows}
    docs_written = links_written = 0

    if page_ids is None:
        title_to_page_id: dict[str, int] = {}
        with open(docs_path, "w", encoding="utf-8", newline="\n") as docs_out:
            for page_id, title, text in corpus.iter_all():
                title_to_page_id[title] = page_id
                text = apply_overlay_text(page_id, text, overlay_by_page)
                docs_out.write(f"{page_id}\t{bad.sub(' ', title)}\t{bad.sub(' ', text)}\n")
                docs_written += 1
        with open(links_path, "w", encoding="utf-8", newline="\n") as links_out:
            for src_title, dst_title in corpus.iter_links():
                src_id, dst_id = title_to_page_id.get(src_title), title_to_page_id.get(dst_title)
                if src_id is not None and dst_id is not None:
                    links_out.write(f"{src_id}\t{dst_id}\n")
                    links_written += 1
        return {"docs": docs_written, "links": links_written}

    with open(docs_path, "w", encoding="utf-8", newline="\n") as docs_out:
        for page_id in sorted(page_ids):
            lead = corpus.by_page_id(page_id)
            if lead is None:
                continue
            text = apply_overlay_text(page_id, lead["text"], overlay_by_page)
            docs_out.write(f"{page_id}\t{bad.sub(' ', lead['title'])}\t{bad.sub(' ', text)}\n")
            docs_written += 1
    with open(links_path, "w", encoding="utf-8", newline="\n") as links_out:
        for page_id in sorted(page_ids):
            for dst in corpus.links_from(page_id):
                if dst in page_ids:
                    links_out.write(f"{page_id}\t{dst}\n")
                    links_written += 1
    return {"docs": docs_written, "links": links_written}


def build_corpus_index(bin_path, docs_path, links_path, out_path) -> dict:
    result = subprocess.run(
        [str(bin_path), "build", "--docs", str(docs_path), "--links", str(links_path), "--out", str(out_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"corpus-index build failed (exit {result.returncode}): {result.stderr.strip()}")
    return json.loads(result.stdout)


def run_queries_capped(bin_path, index_path, items: list[tuple[str, str]], k: int, *,
                       capped_sh, mem_gb: int = 16, workdir=None) -> dict:
    """Like ``hotpot_open_rs.run_queries``, but through ``capped.sh``: loading the real, full ``index.bin``
    (gigabytes) must stay under a measured memory cap on this machine (macOS has no ``RLIMIT_AS``, and this
    lead's machine has run out of memory before). ``capped.sh`` redirects the backgrounded command's own
    stdout/stderr to a log file, so the query batch is fed through a temp file (``exec <`` inside a ``bash
    -c``, verified to carry stdin into the backgrounded process) and the picks are parsed back out of that
    log, after its two capped.sh-written trailer lines (``CAPPED:``/``EXIT=``) are dropped."""
    workdir = Path(workdir or tempfile.mkdtemp(prefix="northstar-query-"))
    stdin_path = workdir / "queries.tsv"
    stdin_path.write_text("".join(f"{qid}\t{text}\n" for qid, text in items), encoding="utf-8")
    log_path = workdir / "query.log"
    inner = (f"exec < {shlex.quote(str(stdin_path))}; "
            f"exec {shlex.quote(str(bin_path))} query --index {shlex.quote(str(index_path))} --k {k}")
    result = subprocess.run(
        [str(capped_sh), str(mem_gb), str(log_path), "--", "bash", "-c", inner],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"capped.sh failed (exit {result.returncode}): {result.stderr.strip()}")
    lines = log_path.read_text(encoding="utf-8").splitlines()
    if any(line.startswith("CAPPED:") for line in lines):
        raise RuntimeError(f"corpus-index query exceeded the {mem_gb} GB cap; see {log_path}")
    picks: dict[str, tuple[list[int], list[int]]] = {}
    for line in lines:
        if line.startswith("EXIT=") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        qid, bm25_field, hop_field = parts
        picks[qid] = ([int(x) for x in bm25_field.split(",") if x], [int(x) for x in hop_field.split(",") if x])
    return picks


# =====================================================================================
# The smoke run (CLI's `run` subcommand): at most SMOKE_LIMIT real questions, a small-
# subset corrected index. Never the full-corpus rebuild (the spec limits for this build).
# =====================================================================================

def _usage(prior: dict | None, new: dict, seconds: float = 0.0) -> dict:
    out = dict(prior or {"calls": 0, "prompt_tokens": 0, "eval_tokens": 0, "seconds": 0.0})
    out["calls"] += 1
    out["prompt_tokens"] += new.get("prompt_eval_count") or 0
    out["eval_tokens"] += new.get("eval_count") or 0
    out["seconds"] += seconds
    return out


def _primary_and_secondary(ids: list[str], e_final: dict, after_b: dict, e_all: dict, reask_ids) -> tuple:
    """The primary (E against B-all, paired em CI and calls, through ``primary_verdict``) and the secondary
    (E against E-all, revision 4: what provenance targeting saves apart from how well E retrieves) over
    exactly ``ids`` -- ``(None, None)`` below ``paired_ci``'s own minimum of two rows."""
    if len(ids) < 2:
        return None, None
    rows = [{"e": e_final[qid]["em"], "b_all": after_b[qid]["em"], "e_all": e_all[qid]["em"]} for qid in ids]
    em_ci = paired_ci(rows, lambda r: r["e"], lambda r: r["b_all"])
    e_calls = sum(1 for qid in ids if qid in reask_ids)
    b_calls = len(ids)  # B-all re-asks every question after the correction
    primary = primary_verdict(em_ci, e_calls, b_calls)
    secondary = {"em_ci": paired_ci(rows, lambda r: r["e"], lambda r: r["e_all"]),
                "e_calls": e_calls, "e_all_calls": len(ids)}
    return primary, secondary


def summarize(sample: list[dict], before_e: dict, before_b: dict, after_e: dict, after_b: dict,
             e_all: dict, closed_book: dict, reask_ids, usage: dict) -> dict:
    """The measures computed the same way regardless of sample size (10 for a smoke, 800 for the full run):
    the primary (E against B-all on the corrected half) and the secondary (E against E-all, revision 4),
    both overall and ``by_class`` (year, person, other_name, and person+year together as "clean_classes" --
    the coordinator's label for the substitutions that keep their kind), controls left unchanged, and stale
    answers read beside closed book."""
    corrected_ids = sorted(q["id"] for q in sample if q["arm"] == "corrected")
    control_ids = sorted(q["id"] for q in sample if q["arm"] == "control")
    e_final = {qid: (after_e[qid] if qid in reask_ids else before_e[qid]) for qid in before_e}

    ids_by_class: dict[str, list[str]] = {}
    for q in sample:
        if q["arm"] == "corrected":
            ids_by_class.setdefault(q.get("answer_class"), []).append(q["id"])

    by_class = {}
    for cls, ids in ids_by_class.items():
        ids = sorted(ids)
        primary, secondary = _primary_and_secondary(ids, e_final, after_b, e_all, reask_ids)
        by_class[cls] = {"n": len(ids), "ids": ids, "primary": primary, "secondary_e_vs_e_all": secondary}
    clean_ids = sorted(ids_by_class.get("year", []) + ids_by_class.get("person", []))
    clean_primary, clean_secondary = _primary_and_secondary(clean_ids, e_final, after_b, e_all, reask_ids)
    by_class["clean_classes"] = {"n": len(clean_ids), "ids": clean_ids, "primary": clean_primary,
                                 "secondary_e_vs_e_all": clean_secondary}

    primary, secondary = _primary_and_secondary(corrected_ids, e_final, after_b, e_all, reask_ids)

    return {
        "corrected_ids": corrected_ids, "control_ids": control_ids,
        "primary": primary, "secondary_e_vs_e_all": secondary, "by_class": by_class,
        "controls": controls_unchanged(before_b, after_b, control_ids),
        "stale_answers": stale_answers(before_e, e_final, corrected_ids, closed_book),
        "cost": usage,
    }


def _run_arms(plan: dict, sample: list[dict], *, corpus_path, index_path, bin_path, store_path,
              capped_sh, capped_gb: int, model: str, ask_fn, embed_fn, workdir: Path, full: bool) -> dict:
    """The arms shared by the smoke (``full=False``, a handful of pages in the corrected index, queried
    directly) and the full run (``full=True``, the real corrected index, queried through ``capped.sh`` like
    the original one): E's and B-all's first pass, the corrected index, E's targeted reask (only what
    ``retraction_impact`` names) and E-all's untargeted one (every question, revision 4), B-all's reask,
    closed book, B-cache, and the summary measures."""
    corpus = CorpusLookup.open(corpus_path)
    store = open_store(Path(store_path), create=True)

    def query(path, items, k, through_cap):
        # `through_cap` asks for capped.sh; `run_full` has already refused to start without --capped-sh, so
        # only the smoke (optional capped_sh) can still fall through to a direct, uncapped query here.
        if through_cap and capped_sh is not None:
            return run_queries_capped(bin_path, path, items, k, capped_sh=capped_sh, mem_gb=capped_gb,
                                      workdir=workdir)
        return run_queries(bin_path, path, items, k)

    items = [(q["id"], q["question"]) for q in sample]
    e_picks = query(index_path, items, E_K, through_cap=True)
    b_picks = query(index_path, items, B_BM25_K, through_cap=True)

    usage: dict[str, dict] = {}
    before_e, before_b = {}, {}
    touched_pages = set()
    for q in sample:
        e_leads = e_pick_leads(bin_path, index_path, corpus, q["id"], q["question"], k=E_K, picks=e_picks)
        b_leads = b_pick_leads(bin_path, index_path, corpus, embed_fn, q["id"], q["question"],
                               bm25_k=B_BM25_K, top=B_TOP, picks=b_picks)
        touched_pages.update(lead["page_id"] for lead in e_leads + b_leads)

        e_answer, e_seconds, e_info = ask_fn(model, build_prompt(q["question"], e_leads))
        record_e_claim(store, q["id"], q["question"], e_answer, e_leads)
        usage["e"] = _usage(usage.get("e"), e_info, e_seconds)
        before_e[q["id"]] = {"answer": e_answer, "leads": e_leads, "em": exact(e_answer, q["answer"]),
                             "f1": round(f1(e_answer, q["answer"]), 4), "seconds": e_seconds}

        b_answer, b_seconds, b_info = ask_fn(model, build_prompt(q["question"], b_leads))
        usage["b_all"] = _usage(usage.get("b_all"), b_info, b_seconds)
        before_b[q["id"]] = {"answer": b_answer, "leads": b_leads, "em": exact(b_answer, q["answer"]),
                             "f1": round(f1(b_answer, q["answer"]), 4), "seconds": b_seconds}

    overlay = plan["overlay"]
    docs_path, links_path, corrected_index_path = workdir / "docs.tsv", workdir / "links.tsv", workdir / "corrected.bin"
    page_ids = None if full else touched_pages | {row["page_id"] for row in overlay}
    export_stats = export_corrected_tsv(corpus, overlay, docs_path, links_path, page_ids=page_ids)
    build_stats = build_corpus_index(bin_path, docs_path, links_path, corrected_index_path)

    sample_corrected_ids = {q["id"] for q in sample if q["arm"] == "corrected"}
    sample_control_ids = {q["id"] for q in sample if q["arm"] == "control"}
    corrected_claims = {cid for cid in impacted_claim_ids(store, overlay) if cid.startswith("claim-e-")}
    now = _utc_now()
    history_before = {}
    reask_ids: set[str] = set()
    for q in sample:
        cid = claim_id(q["id"])
        if cid in corrected_claims:
            history_before[q["id"]] = history_before_correction(store, cid, now)
            withdraw_claim(store, cid, "test1: a cited source was retracted (north-star test 1)")
            reask_ids.add(q["id"])

    # E-all (revision 4, secondary): E's own retrieval, every question re-asked on the corrected index --
    # isolates what provenance targeting saves from how well E retrieves, apart from E's targeted reask below.
    e_all_picks = query(corrected_index_path, items, E_K, through_cap=full)
    e_all = {}
    for q in sample:
        leads = [apply_overlay_lead(lead, overlay) for pid in e_all_picks.get(q["id"], ([], []))[1]
                if (lead := corpus.by_page_id(pid)) is not None]
        answer, seconds, info = ask_fn(model, build_prompt(q["question"], leads))
        usage["e_all"] = _usage(usage.get("e_all"), info, seconds)
        e_all[q["id"]] = {"answer": answer, "em": exact(answer, q["answer"]),
                          "f1": round(f1(answer, q["answer"]), 4), "seconds": seconds}

    # E's targeted reask: only the claims retraction_impact named. The leakage guard (R6) holds here by
    # construction, not by scanning this prompt's text for the prior answer: real evidence can legitimately
    # contain the correct answer word again (it did, on this build's own smoke run -- "Seymour Hicks" was
    # both the earlier answer and a name genuinely in the retrieved lead), so that scan is a false-positive
    # generator, not a guard. build_prompt takes only (question_text, leads) -- see its signature test.
    reask_items = [(q["id"], q["question"]) for q in sample if q["id"] in reask_ids]
    e_reask_picks = query(corrected_index_path, reask_items, E_K, through_cap=full) if reask_items else {}
    after_e, after_b, closed_book = {}, {}, {}
    for q in sample:
        if q["id"] not in reask_ids:
            continue
        leads = [apply_overlay_lead(lead, overlay) for pid in e_reask_picks.get(q["id"], ([], []))[1]
                if (lead := corpus.by_page_id(pid)) is not None]
        prompt_text = build_prompt(q["question"], leads)
        answer, seconds, info = ask_fn(model, prompt_text)
        record_e_claim(store, q["id"], q["question"], answer, leads, attempt=2)
        usage["e"] = _usage(usage["e"], info, seconds)
        after_e[q["id"]] = {"answer": answer, "em": exact(answer, q["answer"]),
                            "f1": round(f1(answer, q["answer"]), 4), "seconds": seconds}

    # B-all: every question re-asked on the corrected index (never targeted).
    b_reask_picks = query(corrected_index_path, items, B_BM25_K, through_cap=full)
    for q in sample:
        candidates = [apply_overlay_lead(lead, overlay) for pid in b_reask_picks.get(q["id"], ([], []))[0]
                     if (lead := corpus.by_page_id(pid)) is not None]
        leads = dense_rerank(q["question"], candidates, embed_fn, top=B_TOP)
        prompt_text = build_prompt(q["question"], leads)
        answer, seconds, info = ask_fn(model, prompt_text)
        usage["b_all"] = _usage(usage["b_all"], info, seconds)
        after_b[q["id"]] = {"answer": answer, "em": exact(answer, q["answer"]),
                            "f1": round(f1(answer, q["answer"]), 4), "seconds": seconds}

        if q["id"] in sample_corrected_ids:
            cb_prompt = build_prompt(q["question"], [])
            cb_answer, cb_seconds, cb_info = ask_fn(model, cb_prompt)
            usage["closed_book"] = _usage(usage.get("closed_book"), cb_info, cb_seconds)
            closed_book[q["id"]] = {"answer": cb_answer, "em": exact(cb_answer, q["answer"]),
                                    "f1": round(f1(cb_answer, q["answer"]), 4), "seconds": cb_seconds}

    b_cache_after = b_cache_from(before_b)
    summary = summarize(sample, before_e, before_b, after_e, after_b, e_all, closed_book, reask_ids, usage)

    return {
        "sample": [q["id"] for q in sample], "corrected_in_sample": sorted(sample_corrected_ids),
        "control_in_sample": sorted(sample_control_ids), "reasked_by_e": sorted(reask_ids),
        "export_stats": export_stats, "build_stats": build_stats,
        "before": {"e": before_e, "b_all": before_b},
        "after": {"e": after_e, "b_all": after_b, "e_all": e_all, "b_cache": b_cache_after,
                  "closed_book": closed_book},
        "history_before_correction": history_before, "usage": usage, "summary": summary,
    }


def run_smoke(plan: dict, *, corpus_path, index_path, bin_path, store_path,
             capped_sh=None, capped_gb: int = 16, count: int = SMOKE_LIMIT,
             model: str = MODEL, ask_fn=real_ask, embed_fn=None, workdir=None) -> dict:
    """Runs the first ``count`` (<= 10) of the plan's 800 questions against the real model and data: a
    *small* corrected index built only from the pages this smoke's questions and the overlay touch (queried
    directly, not through ``capped.sh`` -- it's tiny), with every other arm as ``run_full`` has them. Not a
    result: too few questions, and the corrected index is a small stand-in, not the real corrected corpus."""
    if count > SMOKE_LIMIT:
        raise ValueError(f"run_smoke is capped at {SMOKE_LIMIT} questions; got {count}")
    if embed_fn is None:
        from embeddings import NomicEmbedProvider

        embed_fn = NomicEmbedProvider().embed
    workdir = Path(workdir or tempfile.mkdtemp(prefix="northstar-smoke-"))
    sample = plan["questions"][:count]
    return _run_arms(plan, sample, corpus_path=corpus_path, index_path=index_path, bin_path=bin_path,
                     store_path=store_path, capped_sh=capped_sh, capped_gb=capped_gb, model=model,
                     ask_fn=ask_fn, embed_fn=embed_fn, workdir=workdir, full=False)


def run_full(plan: dict, *, corpus_path, index_path, bin_path, store_path,
             capped_sh, capped_gb: int = 16, model: str = MODEL, ask_fn=real_ask, embed_fn=None,
             workdir=None) -> dict:
    """All 800 of the plan's questions against the real model and data: the *real*, full-corpus corrected
    index (``export_corrected_tsv(..., page_ids=None)`` then ``build_corpus_index``), with every query
    against either full index -- the original and the corrected -- routed through ``capped.sh`` (``full``
    and the full corrected index are each gigabytes). Expensive; not run by this build (the spec's limits)."""
    if capped_sh is None:
        raise ValueError("run_full needs --capped-sh: every full-index query must be memory-capped")
    if embed_fn is None:
        from embeddings import NomicEmbedProvider

        embed_fn = NomicEmbedProvider().embed
    workdir = Path(workdir or tempfile.mkdtemp(prefix="northstar-full-"))
    return _run_arms(plan, plan["questions"], corpus_path=corpus_path, index_path=index_path, bin_path=bin_path,
                     store_path=store_path, capped_sh=capped_sh, capped_gb=capped_gb, model=model,
                     ask_fn=ask_fn, embed_fn=embed_fn, workdir=workdir, full=True)


# =====================================================================================
# CLI
# =====================================================================================

def _load_excluded_ids(paths: list[str]) -> set:
    excluded = set()
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            excluded.update(row["id"] for row in json.load(handle)["rows"])
    return excluded


def _cmd_plan(args: argparse.Namespace) -> int:
    import pyarrow.parquet as pq

    rows = pq.read_table(args.parquet).to_pylist()
    excluded = _load_excluded_ids(args.exclude)
    corpus = CorpusLookup.open(args.corpus)
    redirects = sqlite3.connect(f"file:{args.redirects}?mode=ro", uri=True)
    plan = build_plan(rows, excluded, corpus, redirects, target=args.target, min_qualifying=args.min_qualifying)
    if args.out:
        # sort_keys so the file is byte-identical across runs over the same inputs (no timestamp or other
        # run-varying field is written anywhere in `plan`) -- a deterministic pre-registration artifact.
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(plan, handle, indent=1, sort_keys=True)
    summary = {k: v for k, v in plan.items() if k not in ("questions", "overlay")}
    summary["first_substitutes"] = [
        {"id": q["id"], "class": q["answer_class"], "answer": q["answer"], "substitute": q["substitute"]}
        for q in plan["questions"] if q["arm"] == "corrected"
    ][:5]
    print(json.dumps(summary, indent=1))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    with open(args.plan, encoding="utf-8") as handle:
        plan = json.load(handle)
    if args.full:
        result = run_full(
            plan, corpus_path=args.corpus, index_path=args.index, bin_path=args.bin, store_path=args.store,
            capped_sh=args.capped_sh, capped_gb=args.capped_gb, model=plan.get("model", MODEL),
        )
    else:
        result = run_smoke(
            plan, corpus_path=args.corpus, index_path=args.index, bin_path=args.bin, store_path=args.store,
            capped_sh=args.capped_sh, capped_gb=args.capped_gb, count=args.count, model=plan.get("model", MODEL),
        )
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=1)
    print(json.dumps({k: v for k, v in result.items() if k not in ("before", "after")}, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="North-star test 1: one environment, end to end, with a correction")
    sub = parser.add_subparsers(dest="mode", required=True)

    plan_parser = sub.add_parser("plan", help="compute the pre-registration; no model calls")
    plan_parser.add_argument("--corpus", required=True)
    plan_parser.add_argument("--redirects", required=True)
    plan_parser.add_argument("--parquet", required=True)
    plan_parser.add_argument("--exclude", nargs="+", default=list(DEFAULT_EXCLUDE_FILES))
    plan_parser.add_argument("--target", type=int, default=TARGET_QUALIFYING)
    plan_parser.add_argument("--min-qualifying", type=int, default=MIN_QUALIFYING)
    plan_parser.add_argument("--out", default="plan.json")
    plan_parser.set_defaults(func=_cmd_plan)

    run_parser = sub.add_parser("run", help="execute a plan (a smoke of at most 10 questions by default)")
    run_parser.add_argument("--plan", required=True)
    run_parser.add_argument("--corpus", required=True)
    run_parser.add_argument("--index", required=True)
    run_parser.add_argument("--bin", default=str(DEFAULT_CORPUS_INDEX_BIN))
    run_parser.add_argument("--store", required=True)
    run_parser.add_argument("--capped-sh", default=None, help="capped.sh, required while --index is the full corpus")
    run_parser.add_argument("--capped-gb", type=int, default=16)
    run_parser.add_argument("--count", type=int, default=SMOKE_LIMIT, help="ignored with --full (always all 800)")
    run_parser.add_argument("--full", action="store_true",
                            help="run every question in the plan with the real, full-corpus corrected index "
                                 "(needs --capped-sh); the default without this flag is a smoke of --count "
                                 "questions (at most 10) with a small-subset corrected index")
    run_parser.add_argument("--out")
    run_parser.set_defaults(func=_cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
