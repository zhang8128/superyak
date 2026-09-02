# Local City E2: Recall Targeting Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make engram's local recall targeted on evidence: measure how recency decides winners, then demote it to a tiebreak; derive lane at write time; separate matched and uninvited scores in `dream_verify`; filter lane before the margin; and auto-capture positive recall outcomes at session end.

**Architecture:** One pure scoring module (`scoring.py`) shared by `recall()`, the margin counterfactual, and a read-only replay script so the three never diverge. Every behavior change is preceded by a report from the replay script over a copy of the live store. All changes stay inside the E2 seam: the scoring loop, margin block, lane filter, `remember()`, `dream_verify()`, `hooks/sleep.py`, and config.

**Tech Stack:** Python 3.12, SQLite + sqlite-vec, FastEmbed (nomic-embed-text-v1.5), pytest. Tests use the existing `engram_server_env` fixture pattern (real `server._init()` against a temp `ENGRAM_HOME` with a hash-based fake embedder).

**Spec:** `docs/superpowers/specs/2026-09-01-lighthouse-local-city-design.md` (sections 9 E2 row, 9.1, 10 E2 acceptance). Shared contracts: the "E2 owns" block of the Local City contracts (recency_mode/recency_cap keys, lane rule, dream_verify split, auto-capture rule).

## Global Constraints

- Base ref: `main` **after** the integrator's step-zero commit of the current working tree (margins, dedup/framing fix, research docs). Do not start from a base that lacks `margins.py`.
- Full suite must stay green: `.venv/bin/python -m pytest tests/ -q`.
- The replay report `docs/reports/2026-09-margins-replay.md` must exist and be committed **before** the commit that changes the scoring formula (Task 2). Acceptance cites it.
- `recency_cap` default is `0.02` and is labeled provisional in code and config; no calibration claim is made.
- Never run the replay script against a live store under `.engram/instances/`; it refuses such paths.
- Outcome auto-capture writes only positive evidence (`used: auto: cited`); it never writes `not_used` and never overwrites an existing outcome.
- Forbidden (the seam, owned by E1): `neighbors.py`, any `lighthouse_*.py`, the `response["neighbors"]` key, and the lines around the `_observe_category_recall(...)` call in `recall()`.
- The running MCP server executes old code until restarted; say so in every report that touches `server.py`.

### Work package brief (paste to the Codex lead)

- **Base ref:** `main` at the integrator's step-zero commit (contains `margins.py`, `tests/test_recall_margins.py`).
- **Scope:** Recall targeting fixes with measurement first: replay report, recency tiebreak mode, write-time lane derivation, `dream_verify` score split, lane filter before margin, session-end positive outcome auto-capture, CLAUDE.md update.
- **Allowed files:** `scoring.py` (new), `scripts/margins_replay.py` (new), `docs/reports/2026-09-margins-replay.md` (new), `config.py` (`MemoryConfig` and `_DEFAULT_TOML` `[memory]` block only), `server.py` (only: the scoring loop in `recall()`, `_unbiased_top`, the margin block, the `_recall_scores[...]` population, the lane filter, `remember()` lane assignment, `dream_verify()`), `hooks/sleep.py`, `pyproject.toml` (`py-modules` list only), `CLAUDE.md`, `tests/test_scoring.py` (new), `tests/test_margins_replay.py` (new), `tests/test_recall_lane_margin.py` (new), `tests/test_remember_lane.py` (new), `tests/test_dream_verify_split.py` (new), `tests/test_sleep_outcomes.py` (new).
- **Forbidden files:** `neighbors.py`, `lighthouse_policy.py`, `lighthouse_protocol.py`, `lighthouse_daemon.py`, `lighthouse_receipts.py`, `lighthouse_label.py`, `lighthouse_export.py`, the `response["neighbors"]` key, the `_observe_category_recall` call region in `recall()`, `storage.py`.
- **Acceptance criteria:**
  1. `docs/reports/2026-09-margins-replay.md` exists in a commit that precedes the commit touching `scoring.py`/`server.py` scoring (`git log --oneline -- docs/reports/2026-09-margins-replay.md scoring.py` shows the report first).
  2. The report states near-tie rate, winner-under-7-days share, and winner-under-1-day share under both modes, and the count of recalls whose winner changes.
  3. `.venv/bin/python -m pytest tests/test_scoring.py tests/test_margins_replay.py -q` green; `score_candidate(..., mode="tiebreak")` bounds the recency contribution by `recency_cap`.
  4. `.venv/bin/python -m pytest tests/test_recall_margins.py -q` green with the default mode `tiebreak` (the counterfactual arm uses the same function as `recall()`).
  5. `.venv/bin/python -m pytest tests/test_remember_lane.py -q` green: `remember(context={"project": "x"})` stores `lane="work"`; `context={"project": "x", "lane": "personal"}` stores `personal`; `core=True` with a project tag stores `personal`.
  6. `.venv/bin/python -m pytest tests/test_dream_verify_split.py -q` green: `dream_verify` returns `scores` (matched only) and `uninvited_scores`.
  7. `.venv/bin/python -m pytest tests/test_recall_lane_margin.py -q` green: `recall(lane="work", max_results=3)` returns 3 work items and `margin["n"]` equals the work-lane candidate count.
  8. `.venv/bin/python -m pytest tests/test_sleep_outcomes.py -q` green: a recall whose result id is cited by a later same-session episode gets `outcome = "used: auto: cited"`; an uncited recall keeps `NULL`; an existing outcome is untouched.
  9. `.venv/bin/python -m pytest tests/ -q` green.
  10. CLAUDE.md documents `recency_mode`/`recency_cap`, the lane derivation rule, `uninvited_scores`, lane-before-margin, and sleep-time auto-capture.
- **Reports to produce:** `docs/reports/2026-09-margins-replay.md` (before Task 2), and the same script re-run after Task 5 appended to that file under "After" (integrator re-runs on a fresh copy; E3 re-measures independently).

---

## File map

| File | Responsibility |
|---|---|
| `scoring.py` (new) | Pure recall score: `score_candidate(similarity, recency, auto_generated, *, mode, w_sim, w_rec, cap)`. No imports from `server`. |
| `scripts/margins_replay.py` (new) | Read-only replay of logged recalls over a **copy** of a store, both modes, writes the markdown report. |
| `docs/reports/2026-09-margins-replay.md` (new) | The measurement that licenses the formula change. |
| `config.py` | `MemoryConfig.recency_mode`, `MemoryConfig.recency_cap`; defaults in `_DEFAULT_TOML`. |
| `server.py` | Use `score_candidate` in the scoring loop and `_unbiased_top`; `_derive_lane` in `remember()`; split `_recall_scores`; lane filter before margin. |
| `hooks/sleep.py` | `auto_capture_outcomes(conn, session_id)` run at session end. |
| `pyproject.toml` | Add `scoring` to `py-modules`. |
| `CLAUDE.md` | Doc updates. |

---

### Task 1: Pure scoring module and the replay report

**Files:**
- Create: `scoring.py`
- Create: `scripts/margins_replay.py`
- Create: `docs/reports/2026-09-margins-replay.md` (generated)
- Modify: `pyproject.toml` (`py-modules`, after `"resonance"` or wherever alphabetical order puts `scoring`)
- Test: `tests/test_scoring.py`, `tests/test_margins_replay.py`

**Interfaces:**
- Produces: `scoring.score_candidate(similarity: float, recency: float, auto_generated: bool, *, mode: str, w_sim: float, w_rec: float, cap: float) -> float`; `scoring.MODES = ("tiebreak", "additive")`; `scoring.DEFAULT_RECENCY_CAP = 0.02`.
- Produces: `scripts/margins_replay.py` pure helpers `rank(cands, mode, w_sim, w_rec, cap, near_tie=0.02) -> dict` and `summarize(per_recall: list[dict]) -> dict`, plus `main(argv)`.

- [ ] **Step 1: Write the failing scoring tests**

```python
# tests/test_scoring.py
"""Pure recall scoring shared by recall(), the margin counterfactual, and the replay."""
import pytest

from scoring import DEFAULT_RECENCY_CAP, MODES, score_candidate


def test_modes_are_exactly_tiebreak_and_additive():
    assert MODES == ("tiebreak", "additive")


def test_additive_matches_the_historical_formula():
    s = score_candidate(0.8, 0.5, False, mode="additive", w_sim=0.6, w_rec=0.4, cap=0.02)
    assert s == pytest.approx(0.8 * 0.6 + 0.5 * 0.4)


def test_tiebreak_bounds_recency_by_cap():
    fresh = score_candidate(0.8, 1.0, False, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02)
    stale = score_candidate(0.8, 0.0, False, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02)
    assert fresh - stale == pytest.approx(0.02)


def test_tiebreak_cannot_overturn_a_similarity_gap_wider_than_cap():
    better_old = score_candidate(0.83, 0.0, False, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02)
    worse_new = score_candidate(0.80, 1.0, False, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02)
    assert better_old > worse_new


def test_auto_generated_penalty_applies_in_both_modes():
    for mode in MODES:
        plain = score_candidate(0.8, 0.5, False, mode=mode, w_sim=0.6, w_rec=0.4, cap=0.02)
        auto = score_candidate(0.8, 0.5, True, mode=mode, w_sim=0.6, w_rec=0.4, cap=0.02)
        assert auto == pytest.approx(plain * 0.7)


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        score_candidate(0.8, 0.5, False, mode="sideways", w_sim=0.6, w_rec=0.4, cap=0.02)


def test_default_cap_is_provisional_near_tie_threshold():
    assert DEFAULT_RECENCY_CAP == 0.02
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_scoring.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scoring'`

- [ ] **Step 3: Write `scoring.py`**

```python
"""Recall scoring — one function, three callers.

`recall()`, the margin counterfactual (`server._unbiased_top`), and the
replay script (`scripts/margins_replay.py`) all score candidates through
`score_candidate` so a control arm and a replay measure the formula, not a
second implementation of it.

Two modes:

- ``additive`` — the historical formula ``similarity * w_sim + recency * w_rec``.
  With w_rec = 0.4 a day-old memory earns about 0.2 from age alone, which on
  the September 2026 store decided roughly half of all winners.
- ``tiebreak`` — ``similarity * w_sim + recency * cap``. Recency can move a
  score by at most ``cap``, so it decides near-ties and nothing else.

``cap`` defaults to the margins near-tie threshold. Provisional: no
calibration exists yet; `docs/reports/2026-09-margins-replay.md` is the
first measurement.
"""

from __future__ import annotations

MODES = ("tiebreak", "additive")

# Provisional — equals margins.DEFAULT_NEAR_TIE by design, kept separate so a
# calibration pass can move either without touching the other.
DEFAULT_RECENCY_CAP = 0.02

AUTO_GENERATED_PENALTY = 0.7


def score_candidate(similarity: float, recency: float, auto_generated: bool, *,
                    mode: str, w_sim: float, w_rec: float, cap: float) -> float:
    """Score one recall candidate.

    `recency` is in [0, 1] (1 / (1 + days)). `auto_generated` marks concatenated
    semantics that were never AI-summarized; they keep the historical 0.7 penalty.
    """
    if mode not in MODES:
        raise ValueError(f"unknown recency_mode {mode!r}; expected one of {MODES}")
    if mode == "additive":
        score = similarity * w_sim + recency * w_rec
    else:
        score = similarity * w_sim + recency * cap
    if auto_generated:
        score *= AUTO_GENERATED_PENALTY
    return score
```

- [ ] **Step 4: Add `scoring` to `pyproject.toml`**

In the `py-modules = [` list, insert `"scoring",` in alphabetical position (between `"resonance"` and `"sheaf"` if those are the neighbors; keep the list sorted as it is).

- [ ] **Step 5: Run scoring tests**

Run: `.venv/bin/python -m pytest tests/test_scoring.py -q`
Expected: 7 passed

- [ ] **Step 6: Write the failing replay-helper tests**

```python
# tests/test_margins_replay.py
"""Pure helpers of the replay script (no model, no database)."""
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "margins_replay.py"


def _load():
    spec = importlib.util.spec_from_file_location("margins_replay", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cand(cid, sim, recency, auto=False):
    return {"id": cid, "similarity": sim, "recency": recency, "auto_generated": auto}


def test_rank_reports_winner_gamma_and_near_tie():
    m = _load()
    out = m.rank([cand("a", 0.80, 1.0), cand("b", 0.79, 0.0)],
                 mode="additive", w_sim=0.6, w_rec=0.4, cap=0.02)
    assert out["winner"] == "a"
    assert out["gamma"] == pytest.approx((0.80 * 0.6 + 0.4) - (0.79 * 0.6))
    assert out["near_tie"] is False


def test_same_candidates_can_have_different_winners_per_mode():
    m = _load()
    cands = [cand("old-better", 0.83, 0.0), cand("new-worse", 0.80, 1.0)]
    add = m.rank(cands, mode="additive", w_sim=0.6, w_rec=0.4, cap=0.02)
    tie = m.rank(cands, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02)
    assert add["winner"] == "new-worse"
    assert tie["winner"] == "old-better"


def test_rank_with_fewer_than_two_candidates_has_no_gamma():
    m = _load()
    out = m.rank([cand("a", 0.8, 0.5)], mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02)
    assert out["winner"] == "a"
    assert out["gamma"] is None
    assert out["near_tie"] is False


def test_summarize_counts_near_ties_recent_winners_and_changes():
    m = _load()
    rows = [
        {"additive": {"winner": "x", "near_tie": True, "winner_age_days": 0.5},
         "tiebreak": {"winner": "y", "near_tie": False, "winner_age_days": 40.0}},
        {"additive": {"winner": "z", "near_tie": False, "winner_age_days": 3.0},
         "tiebreak": {"winner": "z", "near_tie": False, "winner_age_days": 3.0}},
    ]
    s = m.summarize(rows)
    assert s["recalls"] == 2
    assert s["additive"]["near_tie_rate"] == pytest.approx(0.5)
    assert s["additive"]["winner_le_7d"] == 2
    assert s["additive"]["winner_le_1d"] == 1
    assert s["tiebreak"]["winner_le_7d"] == 1
    assert s["tiebreak"]["winner_le_1d"] == 0
    assert s["winner_changed"] == 1


def test_refuses_live_instance_paths(tmp_path):
    m = _load()
    live = tmp_path / ".engram" / "instances" / "engram" / "graph.db"
    live.parent.mkdir(parents=True)
    live.touch()
    with pytest.raises(SystemExit):
        m.main([str(live), "--output", str(tmp_path / "r.md")])
```

- [ ] **Step 7: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_margins_replay.py -q`
Expected: FAIL with `FileNotFoundError` (script does not exist)

- [ ] **Step 8: Write `scripts/margins_replay.py`**

```python
"""Margins replay — how often recency, not similarity, picks recall's winner.

Read-only. Takes a path to a COPY of graph.db (refuses anything under
`.engram/instances/`). Re-embeds each logged query, re-runs vector search on
episodes and semantics, and scores the candidate set under both recency
modes with recency computed at the recall's logged timestamp.

Usage:
    sqlite3 .engram/instances/engram/graph.db ".backup /tmp/graph-copy.db"
    .venv/bin/python scripts/margins_replay.py /tmp/graph-copy.db \
        --output docs/reports/2026-09-margins-replay.md [--limit 200]

Not replayed: dream/session bias (the query vector is unbiased here) and the
FTS keyword fallback. Both are noted in the report.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scoring import DEFAULT_RECENCY_CAP, score_candidate  # noqa: E402

NEAR_TIE = 0.02


def rank(cands: list[dict], *, mode: str, w_sim: float, w_rec: float, cap: float,
         near_tie: float = NEAR_TIE) -> dict:
    """Score `cands` (dicts with id, similarity, recency, auto_generated) and
    return the winner, the top-two gap, and whether that gap is a near-tie."""
    scored = sorted(
        ((score_candidate(c["similarity"], c["recency"], c.get("auto_generated", False),
                          mode=mode, w_sim=w_sim, w_rec=w_rec, cap=cap), c["id"])
         for c in cands),
        reverse=True,
    )
    if not scored:
        return {"winner": None, "gamma": None, "near_tie": False}
    if len(scored) < 2:
        return {"winner": scored[0][1], "gamma": None, "near_tie": False}
    gamma = scored[0][0] - scored[1][0]
    return {"winner": scored[0][1], "gamma": gamma, "near_tie": gamma <= near_tie}


def summarize(rows: list[dict]) -> dict:
    """Aggregate per-recall rank results for both modes."""
    out = {"recalls": len(rows), "winner_changed": 0}
    for mode in ("additive", "tiebreak"):
        near = sum(1 for r in rows if r[mode]["near_tie"])
        le7 = sum(1 for r in rows if r[mode]["winner_age_days"] is not None
                  and r[mode]["winner_age_days"] <= 7)
        le1 = sum(1 for r in rows if r[mode]["winner_age_days"] is not None
                  and r[mode]["winner_age_days"] <= 1)
        out[mode] = {
            "near_tie_rate": (near / len(rows)) if rows else 0.0,
            "winner_le_7d": le7,
            "winner_le_1d": le1,
        }
    out["winner_changed"] = sum(
        1 for r in rows if r["additive"]["winner"] != r["tiebreak"]["winner"])
    return out


def _refuse_live(path: Path) -> None:
    if "instances" in path.parts and ".engram" in path.parts:
        sys.exit(f"refusing to open a live instance store: {path}\n"
                 f"make a copy first: sqlite3 {path} \".backup /tmp/graph-copy.db\"")


def _recency(created_at: str | None, at: datetime) -> float:
    if not created_at:
        return 1.0
    dt = datetime.fromisoformat(created_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return 1.0 / (1.0 + (at - dt).total_seconds() / 86400)


def _age_days(created_at: str | None, at: datetime) -> float | None:
    if not created_at:
        return None
    dt = datetime.fromisoformat(created_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (at - dt).total_seconds() / 86400


def replay(db_copy: Path, limit: int) -> tuple[list[dict], dict]:
    from embeddings import NomicEmbedProvider
    from storage import Storage, vec0_distance_to_similarity

    store = Storage(str(db_copy))
    embedder = NomicEmbedProvider()
    try:
        cfg = {"w_sim": 0.6, "w_rec": 0.4, "cap": DEFAULT_RECENCY_CAP}
        logs = store.conn.execute(
            "SELECT timestamp, context FROM memory_log WHERE event_type = 'recall' "
            "AND layer = 'all' AND json_extract(context, '$.query') IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
        rows: list[dict] = []
        for log in logs:
            ctx = json.loads(log["context"] or "{}")
            query = ctx.get("query")
            if not query:
                continue
            at = datetime.fromisoformat(log["timestamp"])
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            emb = embedder.embed([query], prefix="search_query")[0]
            cands: list[dict] = []
            created: dict[str, str | None] = {}
            for table, getter in (("episode", store.get_episode), ("semantic", store.get_semantic)):
                for cid, dist in store.search_vectors(table, emb, k=40):
                    row = getter(cid)
                    if row is None:
                        continue
                    created[cid] = row.get("created_at")
                    cands.append({
                        "id": cid,
                        "similarity": vec0_distance_to_similarity(dist),
                        "recency": _recency(row.get("created_at"), at),
                        "auto_generated": bool(row.get("auto_generated", 0)),
                    })
            entry = {"query": query[:60], "at": log["timestamp"]}
            for mode in ("additive", "tiebreak"):
                r = rank(cands, mode=mode, **cfg)
                r["winner_age_days"] = _age_days(created.get(r["winner"]), at) if r["winner"] else None
                entry[mode] = r
            rows.append(entry)
        return rows, summarize(rows)
    finally:
        store.close()


def render(rows: list[dict], summary: dict, db_copy: Path, phase: str) -> str:
    lines = [
        f"## {phase} ({datetime.now(timezone.utc).date().isoformat()})",
        "",
        f"Source: copy at `{db_copy}`; recalls replayed: {summary['recalls']}.",
        "Bias (dream/session) and FTS fallback not replayed; recency at logged timestamp.",
        "",
        "| Mode | Near-tie rate | Winner ≤ 7d | Winner ≤ 1d |",
        "|---|---|---|---|",
    ]
    for mode in ("additive", "tiebreak"):
        s = summary[mode]
        lines.append(f"| {mode} | {s['near_tie_rate']:.2f} | {s['winner_le_7d']} | {s['winner_le_1d']} |")
    lines += ["", f"Winners that change between modes: {summary['winner_changed']} of {summary['recalls']}.", ""]
    changed = [r for r in rows if r["additive"]["winner"] != r["tiebreak"]["winner"]]
    if changed:
        lines += ["| Query | additive winner | tiebreak winner |", "|---|---|---|"]
        for r in changed[:25]:
            lines.append(f"| {r['query']} | {r['additive']['winner'][:8]} | {r['tiebreak']['winner'][:8]} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("db_copy")
    p.add_argument("--output", required=True)
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--phase", default="Before", help="Section heading: Before or After")
    args = p.parse_args(argv)
    db_copy = Path(args.db_copy)
    _refuse_live(db_copy)
    if not db_copy.exists():
        sys.exit(f"no such file: {db_copy}")
    rows, summary = replay(db_copy, args.limit)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = "" if out.exists() else "# Margins replay — recency as decider\n\n"
    with out.open("a") as fh:
        fh.write(header + render(rows, summary, db_copy, args.phase) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 9: Run replay-helper tests**

Run: `.venv/bin/python -m pytest tests/test_margins_replay.py -q`
Expected: 5 passed

- [ ] **Step 10: Produce the report on a copy of the live store**

```bash
mkdir -p /tmp/e2-replay
sqlite3 .engram/instances/engram/graph.db ".backup /tmp/e2-replay/graph-copy.db"
.venv/bin/python scripts/margins_replay.py /tmp/e2-replay/graph-copy.db \
  --output docs/reports/2026-09-margins-replay.md --limit 200 --phase Before
```

Expected: JSON summary on stdout; `docs/reports/2026-09-margins-replay.md` created with a `## Before` section. Open it and confirm the table has both modes and the changed-winner list. (This needs the embedding model; first run downloads it.)

- [ ] **Step 11: Commit (report first, by itself)**

```bash
git add scoring.py scripts/margins_replay.py pyproject.toml tests/test_scoring.py tests/test_margins_replay.py docs/reports/2026-09-margins-replay.md
git commit -m "feat: add shared recall scoring and margins replay report"
```

---

### Task 2: Recency mode in config and both recall arms

**Files:**
- Modify: `config.py` (`MemoryConfig`, and the `[memory]` block in `_DEFAULT_TOML`)
- Modify: `server.py` — the scoring loop in `recall()` (the lines computing `recency`, `score`, and the `auto_generated` penalty) and `_unbiased_top`
- Test: `tests/test_recall_margins.py` (existing, must stay green), `tests/test_scoring.py` (append)

**Interfaces:**
- Consumes: `scoring.score_candidate`.
- Produces: `MemoryConfig.recency_mode: str = "tiebreak"`, `MemoryConfig.recency_cap: float = 0.02`; `server._unbiased_top(..., mode: str | None = None, cap: float | None = None)` (keyword-only additions; `None` means read `_config`).

- [ ] **Step 1: Write the failing config and integration tests** (append to `tests/test_scoring.py`)

```python
def test_memory_config_defaults_to_tiebreak():
    from config import MemoryConfig
    cfg = MemoryConfig()
    assert cfg.recency_mode == "tiebreak"
    assert cfg.recency_cap == 0.02


def test_default_toml_declares_recency_keys():
    from config import _DEFAULT_TOML
    assert 'recency_mode = "tiebreak"' in _DEFAULT_TOML
    assert "recency_cap = 0.02" in _DEFAULT_TOML
```

And a new integration test file:

```python
# tests/test_recall_recency_mode.py
"""recall() and its counterfactual arm score through one function and one mode."""
from __future__ import annotations

import pytest

import server
from tests.test_recall_margins import (  # reuse the real-_init() fixture and helpers
    FakeEmbeddingProvider, engram_server_env, seed, add_session_bias,
)


def test_tiebreak_and_additive_differ_by_the_recency_term(engram_server_env):
    seed(1)
    server._config.memory.recency_mode = "additive"
    add = server.recall(query="episode number 0 about rivers and mapping", uninvited=0)["results"][0]["score"]
    server._config.memory.recency_mode = "tiebreak"
    tie = server.recall(query="episode number 0 about rivers and mapping", uninvited=0)["results"][0]["score"]
    # A just-created episode has recency ~1.0: additive adds ~0.4, tiebreak adds ~0.02.
    assert add - tie == pytest.approx(0.4 - 0.02, abs=0.02)


def test_both_arms_score_with_the_configured_mode(engram_server_env, monkeypatch):
    seed(3)
    seen: list[str] = []
    real = server.score_candidate

    def spy(*args, **kwargs):
        seen.append(kwargs["mode"])
        return real(*args, **kwargs)

    monkeypatch.setattr(server, "score_candidate", spy)
    add_session_bias("rivers and mapping")          # forces the counterfactual arm to run
    out = server.recall(query="rivers and mapping", uninvited=0)
    assert out["margin"]["stability"]["checked"] is True
    assert set(seen) == {"tiebreak"}
    assert len(seen) >= 2 * 3                        # both arms scored every candidate
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_scoring.py tests/test_recall_recency_mode.py -q`
Expected: FAIL — `AttributeError: 'MemoryConfig' object has no attribute 'recency_mode'` and `AttributeError: module 'server' has no attribute 'score_candidate'`

- [ ] **Step 3: Add the config keys**

In `config.py`, `MemoryConfig`:

```python
@dataclass
class MemoryConfig:
    max_recall_results: int = 20
    graph_expansion_depth: int = 2
    similarity_weight: float = 0.6
    recency_weight: float = 0.4
    # How recency enters the recall score. "tiebreak" caps its contribution at
    # recency_cap so it decides near-ties only; "additive" is the historical
    # similarity*w_sim + recency*w_rec. See docs/reports/2026-09-margins-replay.md.
    recency_mode: str = "tiebreak"
    recency_cap: float = 0.02  # provisional — equals the margins near-tie threshold
```

In `_DEFAULT_TOML`, the `[memory]` block becomes:

```toml
[memory]
max_recall_results = 20
graph_expansion_depth = 2
similarity_weight = 0.6
recency_weight = 0.4
recency_mode = "tiebreak"
recency_cap = 0.02
```

- [ ] **Step 4: Route `recall()`'s scoring loop through `score_candidate`**

At the top of `server.py`, next to `import margins`, add:

```python
from scoring import score_candidate
```

In `recall()`, after `w_sim`/`w_rec` are read, add:

```python
    recency_mode = _config.memory.recency_mode if _config else "tiebreak"
    recency_cap = _config.memory.recency_cap if _config else 0.02
```

In the scoring loop replace

```python
        recency = 1.0 / (1.0 + days)
        score = info["similarity"] * w_sim + recency * w_rec
        # Penalize auto-generated semantics (concatenated, not AI-summarized)
        if info.get("auto_generated"):
            score *= 0.7
```

with

```python
        recency = 1.0 / (1.0 + days)
        score = score_candidate(
            info["similarity"], recency, bool(info.get("auto_generated")),
            mode=recency_mode, w_sim=w_sim, w_rec=w_rec, cap=recency_cap)
```

- [ ] **Step 5: Route `_unbiased_top` through the same function**

Change the signature to

```python
def _unbiased_top(raw_embedding: list[float], layer: str | None, max_results: int,
                  query: str, biased: dict[str, dict], now: datetime,
                  w_sim: float, w_rec: float, *,
                  mode: str | None = None, cap: float | None = None) -> str | None:
```

At the top of its body:

```python
    if mode is None:
        mode = _config.memory.recency_mode if _config else "tiebreak"
    if cap is None:
        cap = _config.memory.recency_cap if _config else 0.02
```

Replace

```python
        score = info["similarity"] * w_sim + _recency_at(created_at, now) * w_rec
        if auto_generated:
            score *= 0.7
```

with

```python
        score = score_candidate(
            info["similarity"], _recency_at(created_at, now), bool(auto_generated),
            mode=mode, w_sim=w_sim, w_rec=w_rec, cap=cap)
```

In `recall()`'s margin block, pass the mode explicitly so the control arm is pinned to the same setting as the biased arm:

```python
            unbiased_top = _unbiased_top(raw_embedding, layer, max_results, query,
                                         candidates, now, w_sim, w_rec,
                                         mode=recency_mode, cap=recency_cap)
```

- [ ] **Step 6: Run the new tests and the margins suite**

Run: `.venv/bin/python -m pytest tests/test_scoring.py tests/test_recall_recency_mode.py tests/test_recall_margins.py tests/test_recall_when.py -q`
Expected: all passed. If any pre-existing test asserts the additive numbers, set `server._config.memory.recency_mode = "additive"` inside that test rather than changing the default.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add config.py server.py tests/test_scoring.py tests/test_recall_recency_mode.py
git commit -m "feat: score recall through one function with recency as tiebreak"
```

---

### Task 3: Derive lane at write time

**Files:**
- Modify: `server.py` — `remember()` (the `lane="work" if work else "personal"` argument and the `result["lane"]` line); add `_derive_lane` just above `remember`
- Test: `tests/test_remember_lane.py`

**Interfaces:**
- Produces: `server._derive_lane(work: bool, core: bool, genome: bool, context: dict | None) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_remember_lane.py
"""Lane is derived at write time, not only from the work flag."""
from __future__ import annotations

import server
from tests.test_recall_margins import FakeEmbeddingProvider, engram_server_env  # noqa: F401


def _lane(episode_id: str) -> str:
    return server._storage.get_episode(episode_id)["lane"] or "personal"


def test_project_tag_derives_work_lane(engram_server_env):
    out = server.remember(content="deployed the rowing tenant to staging", context={"project": "hyper-nimbus"})
    assert _lane(out["episode_id"]) == "work"
    assert out["lane"] == "work"


def test_explicit_personal_lane_in_context_wins_over_project_tag(engram_server_env):
    out = server.remember(content="the reader session with Danielle tonight",
                          context={"project": "reader", "lane": "personal"})
    assert _lane(out["episode_id"]) == "personal"
    assert "lane" not in out


def test_work_flag_still_derives_work_lane(engram_server_env):
    out = server.remember(content="client review answers pending", work=True)
    assert _lane(out["episode_id"]) == "work"


def test_no_signal_stays_personal(engram_server_env):
    out = server.remember(content="a quiet thought with no project attached")
    assert _lane(out["episode_id"]) == "personal"


def test_core_with_project_tag_stays_personal(engram_server_env):
    """Core is an identity claim; an inferred work lane must not silently make a core work episode."""
    out = server.remember(content="the day the contract for Region 1 came through",
                          context={"project": "guyana"}, core=True)
    assert _lane(out["episode_id"]) == "personal"


def test_pure_derivation_rules():
    assert server._derive_lane(False, False, False, {"project": "x"}) == "work"
    assert server._derive_lane(False, False, False, {"project": "x", "lane": "personal"}) == "personal"
    assert server._derive_lane(True, False, False, None) == "work"
    assert server._derive_lane(False, True, False, {"project": "x"}) == "personal"
    assert server._derive_lane(False, False, True, {"project": "x"}) == "personal"
    assert server._derive_lane(False, False, False, {"project": ""}) == "personal"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_remember_lane.py -q`
Expected: FAIL — `test_project_tag_derives_work_lane` asserts `'personal' == 'work'`; `test_pure_derivation_rules` fails with `AttributeError: _derive_lane`

- [ ] **Step 3: Implement `_derive_lane` and use it**

Above `def remember(` in `server.py`:

```python
def _derive_lane(work: bool, core: bool, genome: bool, context: dict | None) -> str:
    """Lane at write time.

    `work=True` is explicit and wins. Otherwise a project tag in context marks
    reference material and derives the work lane — the September 2026 store
    had 20 of 28 recent personal-lane episodes carrying a project tag, which
    is how work checkpoints leaked into identity recall. `context.lane ==
    "personal"` opts out. Core and genome are identity claims and stay
    personal (the work flag with core/genome is already rejected upstream).
    """
    if work:
        return "work"
    if core or genome:
        return "personal"
    if context and context.get("lane") == "personal":
        return "personal"
    if context and context.get("project"):
        return "work"
    return "personal"
```

In `remember()`, after the validation block and before `episode_id = ...`:

```python
    lane = _derive_lane(work, core, genome, context)
```

Change the `add_episode(...)` call's `lane="work" if work else "personal",` to `lane=lane,`.

Change

```python
    if work:
        result["lane"] = "work"
```

to

```python
    if lane == "work":
        result["lane"] = "work"
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_remember_lane.py -q`
Expected: 6 passed

- [ ] **Step 5: Run lane-related suites**

Run: `.venv/bin/python -m pytest tests/ -q -k "lane or remember"`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_remember_lane.py
git commit -m "feat: derive memory lane from project context at write time"
```

---

### Task 4: Split matched and uninvited scores in `dream_verify`

**Files:**
- Modify: `server.py` — the `_recall_scores[recall_id] = {...}` line in `recall()`; `dream_verify()`
- Test: `tests/test_dream_verify_split.py`

**Interfaces:**
- Produces: `_recall_scores[recall_id] == {"matched": {id: score}, "uninvited": {id: raw_similarity}}`; `dream_verify()` returns `scores` (matched) and `uninvited_scores`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dream_verify_split.py
"""dream_verify reveals matched scores and uninvited similarities as two maps."""
from __future__ import annotations

import server
from tests.test_recall_margins import FakeEmbeddingProvider, engram_server_env, seed  # noqa: F401


def test_uninvited_scores_are_not_mixed_into_matched_scores(engram_server_env):
    seed(8)
    server.dream_capture(reaction="a low hum I cannot place")
    out = server.recall(query="rivers and mapping", max_results=3, uninvited=2)
    assert out.get("dreaming") is True
    revealed = server.dream_verify(out["recall_id"])
    matched_ids = {r["id"] for r in out["results"] if not r.get("uninvited")}
    uninvited_ids = {r["id"] for r in out["results"] if r.get("uninvited")}
    assert set(revealed["scores"]) == matched_ids
    assert set(revealed["uninvited_scores"]) == uninvited_ids
    assert not (set(revealed["scores"]) & set(revealed["uninvited_scores"]))


def test_recall_without_uninvited_reveals_empty_uninvited_map(engram_server_env):
    seed(3)
    server.dream_capture(reaction="a low hum I cannot place")
    out = server.recall(query="rivers and mapping", uninvited=0)
    revealed = server.dream_verify(out["recall_id"])
    assert revealed["uninvited_scores"] == {}
    assert len(revealed["scores"]) == len(out["results"])


def test_unknown_recall_id_still_errors(engram_server_env):
    seed(1)
    assert "error" in server.dream_verify("does-not-exist")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_dream_verify_split.py -q`
Expected: FAIL — `KeyError: 'uninvited_scores'` and the first test's `set(revealed["scores"]) == matched_ids` fails because uninvited ids are included.

- [ ] **Step 3: Split at population**

In `recall()`, replace

```python
        _recall_scores[recall_id] = {r["id"]: r.get("score") for r in results}
```

with

```python
        # Two score regimes: matched results carry the recall score, uninvited
        # results carry raw similarity. Revealing them in one sorted map made
        # random distant memories look like the strongest matches.
        _recall_scores[recall_id] = {
            "matched": {r["id"]: r.get("score") for r in results if not r.get("uninvited")},
            "uninvited": {r["id"]: r.get("score") for r in results if r.get("uninvited")},
        }
```

Run `grep -n "_recall_scores" server.py` and confirm the only readers are `dream_verify` and the two reset functions (which assign `{}`); no other code indexes the per-recall dict.

- [ ] **Step 4: Reveal both maps in `dream_verify`**

Replace the body from `scores = _recall_scores.get(recall_id)` through the `revealed = {...}` literal with:

```python
    entry = _recall_scores.get(recall_id)
    if entry is None:
        return {"error": "No hidden scores for this recall_id. Either it wasn't dream-influenced, or the session has reset."}

    matched = entry["matched"]
    uninvited = entry["uninvited"]
    # Sort by score descending so the instance can see which were strong matches
    sorted_scores = sorted(matched.items(), key=lambda x: x[1] or 0, reverse=True)
    revealed = {
        "recall_id": recall_id,
        "scores": {rid: round(s, 4) if s else None for rid, s in sorted_scores},
        # Raw similarity of the random distant pulls — a different regime, kept apart.
        "uninvited_scores": {rid: round(s, 4) if s else None for rid, s in uninvited.items()},
        "note": "Now you can see which memories were pulled by the dream. What did you engage with before checking?",
    }
```

Keep the `margin` attachment lines that follow unchanged.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_dream_verify_split.py tests/test_recall_margins.py -q -k "dream or Dream"`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_dream_verify_split.py
git commit -m "fix: reveal matched and uninvited recall scores separately"
```

---

### Task 5: Lane filter before the margin and truncation

**Files:**
- Modify: `server.py` — insert a lane filter on `scored` between `scored.sort(...)` and the margin block; leave the existing post-uninvited lane filter in place
- Test: `tests/test_recall_lane_margin.py`

**Interfaces:**
- Consumes: `margins.margin_stats` (unchanged).
- Produces: `recall(lane=...)` returns up to `max_results` lane-matching items; `margin["n"]` counts lane-matching candidates only.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_recall_lane_margin.py
"""A lane-filtered recall's margin describes the lane it returned."""
from __future__ import annotations

import server
from tests.test_recall_margins import FakeEmbeddingProvider, engram_server_env  # noqa: F401


def _seed_two_lanes():
    for i in range(3):
        server.remember(content=f"work note {i} about rivers and mapping", work=True)
    for i in range(3):
        server.remember(content=f"personal note {i} about rivers and mapping")


def test_work_lane_recall_fills_max_results(engram_server_env):
    _seed_two_lanes()
    out = server.recall(query="rivers and mapping", lane="work", max_results=3, uninvited=0)
    assert len(out["results"]) == 3
    assert all(r["lane"] == "work" for r in out["results"])


def test_margin_counts_only_the_requested_lane(engram_server_env):
    _seed_two_lanes()
    out = server.recall(query="rivers and mapping", lane="work", max_results=3, uninvited=0)
    assert out["margin"]["n"] == 3   # six candidates exist; three are work-lane


def test_unfiltered_recall_still_sees_both_lanes(engram_server_env):
    _seed_two_lanes()
    out = server.recall(query="rivers and mapping", max_results=10, uninvited=0)
    assert {r["lane"] for r in out["results"]} == {"work", "personal"}
    assert out["margin"]["n"] == 6


def test_log_target_ids_match_returned_ids(engram_server_env):
    import json
    _seed_two_lanes()
    out = server.recall(query="rivers and mapping", lane="personal", max_results=2, uninvited=0)
    row = server._storage.conn.execute(
        "SELECT target_ids FROM memory_log WHERE event_type = 'recall' "
        "AND json_extract(context, '$.recall_id') = ?", (out["recall_id"],)).fetchone()
    assert json.loads(row["target_ids"]) == [r["id"] for r in out["results"]]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_recall_lane_margin.py -q`
Expected: FAIL — `margin["n"] == 3` sees 6; with `max_results=3` the work recall may return fewer than 3 because truncation precedes filtering.

- [ ] **Step 3: Filter `scored` before the margin**

In `recall()`, immediately after

```python
    scored.sort(key=lambda x: x["score"], reverse=True)
```

insert

```python
    # Lane filter on the ranked candidate set, before the margin and before
    # truncation: the margin must describe the lane the caller receives, and a
    # lane-filtered recall should be able to fill max_results.
    if lane is not None:
        scored = [r for r in scored if (r.get("lane") or "personal") == lane]
```

Leave the later block (`# Lane filter — applied after uninvited memories are appended`) exactly as it is; it still governs uninvited and resonant results and rewrites `target_ids`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_recall_lane_margin.py tests/test_recall_margins.py tests/test_recall_when.py -q`
Expected: green.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_recall_lane_margin.py
git commit -m "fix: apply lane filter before recall margin and truncation"
```

---

### Task 6: Positive outcome auto-capture at session end

**Files:**
- Modify: `hooks/sleep.py` — add `auto_capture_outcomes(conn, session_id)`; call it from `sleep()` right after the connection is opened
- Test: `tests/test_sleep_outcomes.py`

**Interfaces:**
- Consumes: `memory_log` (recall rows: `context.session_id`, `target_ids`, `outcome`), `episodes` (`session_id`, `content`, `context`, `created_at`), `operation_log` (`session_id`, `operation`, `target_ids`, `timestamp`).
- Produces: `sleep.auto_capture_outcomes(conn: sqlite3.Connection, session_id: str | None) -> int`; `sleep.AUTO_OUTCOME = "used: auto: cited"`; `sleep.CITING_OPERATIONS = ("mark_core", "instinct_feedback", "dream_react", "remember")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sleep_outcomes.py
"""Session-end auto-capture of positive recall outcomes."""
from __future__ import annotations

import json
import sqlite3

import pytest

from tests.test_nudge_harness import MIGRATIONS_DIR, _load, _seed_episodes


def _conn(db_path):
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    return c


def _log_recall(conn, rid, session, targets, ts, outcome=None):
    conn.execute(
        "INSERT INTO memory_log (id, timestamp, event_type, layer, target_ids, context, outcome) "
        "VALUES (?, ?, 'recall', 'all', ?, ?, ?)",
        (f"log-{rid}", ts, json.dumps(targets),
         json.dumps({"recall_id": rid, "query": "q", "session_id": session}), outcome))


def _cite_by_episode(conn, session, text, ts):
    # episodes.core, .dormant, .lane are NOT NULL; supply them explicitly.
    conn.execute(
        "INSERT INTO episodes (id, session_id, content, created_at, core, dormant, lane) "
        "VALUES (?, ?, ?, ?, 0, 0, 'personal')",
        (f"cite-{ts}", session, text, ts))


def _cite_by_operation(conn, session, op, targets, ts):
    conn.execute(
        "INSERT INTO operation_log (id, timestamp, operation, session_id, target_ids, details, outcome) "
        "VALUES (?, ?, ?, ?, ?, '{}', 'success')",
        (f"op-{ts}", ts, op, session, json.dumps(targets)))


def _outcome(conn, rid):
    return conn.execute(
        "SELECT outcome FROM memory_log WHERE json_extract(context, '$.recall_id') = ?", (rid,)
    ).fetchone()["outcome"]


@pytest.fixture
def db(tmp_path):
    path = _seed_episodes(tmp_path, n=3)
    return path


def test_recall_cited_by_later_episode_is_marked_used(db):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(conn, "r1", "s1", ["ep-0", "ep-1"], "2026-09-01T10:00:00+00:00")
    _cite_by_episode(conn, "s1", "building on ep-0 from the earlier recall", "2026-09-01T10:05:00+00:00")
    conn.commit()
    assert sleep.auto_capture_outcomes(conn, "s1") == 1
    assert _outcome(conn, "r1") == sleep.AUTO_OUTCOME


def test_recall_cited_by_operation_log_is_marked_used(db):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(conn, "r2", "s1", ["ep-2"], "2026-09-01T10:00:00+00:00")
    _cite_by_operation(conn, "s1", "mark_core", ["ep-2"], "2026-09-01T10:01:00+00:00")
    conn.commit()
    assert sleep.auto_capture_outcomes(conn, "s1") == 1
    assert _outcome(conn, "r2") == sleep.AUTO_OUTCOME


def test_uncited_recall_stays_unlabeled(db):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(conn, "r3", "s1", ["ep-0"], "2026-09-01T10:00:00+00:00")
    _cite_by_episode(conn, "s1", "nothing to do with that", "2026-09-01T10:05:00+00:00")
    conn.commit()
    assert sleep.auto_capture_outcomes(conn, "s1") == 0
    assert _outcome(conn, "r3") is None


def test_citation_before_the_recall_does_not_count(db):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(conn, "r4", "s1", ["ep-0"], "2026-09-01T10:00:00+00:00")
    _cite_by_episode(conn, "s1", "mentions ep-0 earlier", "2026-09-01T09:00:00+00:00")
    conn.commit()
    assert sleep.auto_capture_outcomes(conn, "s1") == 0


def test_existing_outcome_is_never_overwritten(db):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(conn, "r5", "s1", ["ep-0"], "2026-09-01T10:00:00+00:00", outcome="not_used: wrong")
    _cite_by_episode(conn, "s1", "ep-0 again", "2026-09-01T10:05:00+00:00")
    conn.commit()
    assert sleep.auto_capture_outcomes(conn, "s1") == 0
    assert _outcome(conn, "r5") == "not_used: wrong"


def test_other_sessions_are_untouched(db):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(conn, "r6", "s2", ["ep-0"], "2026-09-01T10:00:00+00:00")
    _cite_by_episode(conn, "s1", "ep-0 cited by a different session", "2026-09-01T10:05:00+00:00")
    conn.commit()
    assert sleep.auto_capture_outcomes(conn, "s1") == 0
    assert _outcome(conn, "r6") is None


def test_no_session_id_is_a_noop(db):
    sleep = _load("sleep")
    conn = _conn(db)
    assert sleep.auto_capture_outcomes(conn, None) == 0


def test_sleep_runs_auto_capture(db, monkeypatch, capsys):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(conn, "r7", "s1", ["ep-1"], "2026-09-01T10:00:00+00:00")
    _cite_by_episode(conn, "s1", "ep-1 was the one", "2026-09-01T10:05:00+00:00")
    conn.commit()
    conn.close()
    monkeypatch.setattr(sleep, "DB_PATH", db)
    monkeypatch.setattr(sleep, "_load_instance_config", lambda: None)
    monkeypatch.setattr(sleep, "read_context", lambda: {"skip": False, "session_id": "s1"})
    monkeypatch.setattr(sleep, "clear_session_binding", lambda conn, ctx: None)
    sleep.sleep()
    assert "auto-captured 1" in capsys.readouterr().err
    assert _outcome(_conn(db), "r7") == sleep.AUTO_OUTCOME
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_sleep_outcomes.py -q`
Expected: FAIL — `AttributeError: module 'sleep' has no attribute 'auto_capture_outcomes'`

- [ ] **Step 3: Implement `auto_capture_outcomes`**

In `hooks/sleep.py`, after the module constants (near `DREAMS_PER_SLEEP`), add:

```python
AUTO_OUTCOME = "used: auto: cited"
CITING_OPERATIONS = ("mark_core", "instinct_feedback", "dream_react", "remember")


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def auto_capture_outcomes(conn, session_id) -> int:
    """Mark this session's recalls `used` when a later same-session act cited a result.

    Only positive evidence: a result id that reappears in a later remember()
    episode's content or context, or in the target_ids of a later mark_core,
    instinct_feedback, dream_react, or remember operation. Absence stays
    missing data — nothing is ever marked not_used here, and an outcome the
    instance already logged is never overwritten. Returns the count marked.
    """
    if not session_id or not _table_exists(conn, "memory_log"):
        return 0
    recalls = conn.execute(
        "SELECT id, timestamp, target_ids FROM memory_log WHERE event_type = 'recall' "
        "AND outcome IS NULL AND json_extract(context, '$.session_id') = ?",
        (session_id,),
    ).fetchall()
    if not recalls:
        return 0

    episodes = conn.execute(
        "SELECT created_at, content, COALESCE(context, '') AS context FROM episodes "
        "WHERE session_id = ?", (session_id,),
    ).fetchall()
    operations = []
    if _table_exists(conn, "operation_log"):
        placeholders = ",".join("?" for _ in CITING_OPERATIONS)
        operations = conn.execute(
            f"SELECT timestamp, target_ids FROM operation_log WHERE session_id = ? "
            f"AND operation IN ({placeholders})", (session_id, *CITING_OPERATIONS),
        ).fetchall()

    marked = 0
    for recall in recalls:
        targets = json.loads(recall["target_ids"] or "[]")
        after = recall["timestamp"]
        cited = False
        for ep in episodes:
            if ep["created_at"] > after and any(t in ep["content"] or t in ep["context"] for t in targets):
                cited = True
                break
        if not cited:
            for op in operations:
                if op["timestamp"] > after and set(json.loads(op["target_ids"] or "[]")) & set(targets):
                    cited = True
                    break
        if cited:
            conn.execute(
                "UPDATE memory_log SET outcome = ? WHERE id = ? AND outcome IS NULL",
                (AUTO_OUTCOME, recall["id"]),
            )
            marked += 1
    if marked:
        conn.commit()
    return marked
```

Add `import json` to the module imports (it is not imported today).

- [ ] **Step 4: Call it from `sleep()`**

Immediately after `conn.row_factory = sqlite3.Row` in `sleep()`, insert:

```python
        try:
            captured = auto_capture_outcomes(conn, ctx["session_id"])
            if captured:
                print(f"engram sleep: auto-captured {captured} recall outcome(s)", file=sys.stderr)
        except Exception:
            pass  # outcome capture is observational; never block sleep
```

This runs before the residue-table check so sessions without residue still capture outcomes.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_sleep_outcomes.py tests/test_nudge_harness.py -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add hooks/sleep.py tests/test_sleep_outcomes.py
git commit -m "feat: auto-capture positive recall outcomes at session end"
```

---

### Task 7: Documentation

**Files:**
- Modify: `CLAUDE.md` — the **Memory lanes** paragraph, the **Tropical margins** paragraph, the `dream_verify` row of the MCP tools table, and the `hooks/wake.py` row's neighbor in Key Files (add a `hooks/sleep.py` row)

- [ ] **Step 1: Update the Memory lanes paragraph**

Append to the paragraph that begins `**Memory lanes:**`:

```
Lane is derived at write time: `work=True` wins; otherwise a `project` key in
`context` derives the work lane (`context.lane = "personal"` opts out); core
and genome episodes stay personal. Lane filtering is applied to the ranked
candidate set before the margin and before truncation, so a lane-filtered
recall can fill `max_results` and its margin describes the lane returned.
```

- [ ] **Step 2: Update the Tropical margins paragraph**

Replace the sentence beginning `Measured on the full candidate set before truncation,` with:

```
Measured on the lane-filtered candidate set before truncation, normalized by
```

and append at the end of the paragraph:

```
Recall scoring is one function (`scoring.score_candidate`) shared by `recall()`,
the counterfactual arm, and `scripts/margins_replay.py`. `[memory] recency_mode`
selects `tiebreak` (default: recency contributes at most `recency_cap`, 0.02,
provisional) or `additive` (the historical `similarity * 0.6 + recency * 0.4`).
The replay report that licensed the default lives at
`docs/reports/2026-09-margins-replay.md`.
```

- [ ] **Step 3: Update the tools table and key files**

Change the `dream_verify` row to:

```
| `dream_verify(recall_id)` | Reveal hidden scores from dream-influenced recall: `scores` (matched) and `uninvited_scores` (raw similarity of distant pulls) as separate maps. Use after engaging. |
```

Add after the `hooks/wake.py` row:

```
| `hooks/sleep.py` | Stop hook — dream residue distillation; marks this session's recalls `used: auto: cited` when a later act cited a result (positive evidence only) |
| `scoring.py` | Recall score shared by `recall()`, the margin counterfactual, and the replay script (`recency_mode`, `recency_cap`) |
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document recency tiebreak, lane derivation, and outcome auto-capture"
```

---

### Task 8: Final verification and the "After" replay

- [ ] **Step 1: Full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 2: Re-run the replay on a fresh copy, appending an After section**

```bash
sqlite3 .engram/instances/engram/graph.db ".backup /tmp/e2-replay/graph-copy-after.db"
.venv/bin/python scripts/margins_replay.py /tmp/e2-replay/graph-copy-after.db \
  --output docs/reports/2026-09-margins-replay.md --limit 200 --phase After
```

Note in the report's After section that the replay scores the same historical candidate sets; the live effect appears only in recalls made after the MCP server is restarted on this code. The integrator restarts the server; E3 re-measures the live near-tie rate a week later.

- [ ] **Step 3: Commit**

```bash
git add docs/reports/2026-09-margins-replay.md
git commit -m "docs: append after-change margins replay"
```

- [ ] **Step 4: Report to the lead**

State: commits in order, the Before and After summary tables, that `server.py` changed and the running MCP server needs a restart, and that no file outside the allowed list was touched (`git diff --stat <base>..HEAD`).
