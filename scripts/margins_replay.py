"""Margins replay — how often recency, not similarity, picks recall's winner.

Read-only. Takes a path to a COPY of graph.db (refuses anything under
``.engram/instances/``). Re-embeds each logged query, re-runs vector search on
episodes and semantics, and scores the candidate set under both recency modes
with recency computed at the recall's logged timestamp.

Usage::

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


def rank(
    cands: list[dict],
    *,
    mode: str,
    w_sim: float,
    w_rec: float,
    cap: float,
    near_tie: float = NEAR_TIE,
) -> dict:
    """Return the winner, top-two gap, and near-tie state for ``cands``."""
    scored = sorted(
        (
            (
                score_candidate(
                    c["similarity"],
                    c["recency"],
                    c.get("auto_generated", False),
                    mode=mode,
                    w_sim=w_sim,
                    w_rec=w_rec,
                    cap=cap,
                ),
                c["id"],
            )
            for c in cands
        ),
        reverse=True,
    )
    if not scored:
        return {"winner": None, "gamma": None, "near_tie": False}
    if len(scored) < 2:
        return {"winner": scored[0][1], "gamma": None, "near_tie": False}
    gamma = scored[0][0] - scored[1][0]
    return {
        "winner": scored[0][1],
        "gamma": gamma,
        "near_tie": gamma <= near_tie,
    }


def summarize(rows: list[dict]) -> dict:
    """Aggregate per-recall rank results for both modes."""
    out = {"recalls": len(rows), "winner_changed": 0}
    for mode in ("additive", "tiebreak"):
        near = sum(1 for row in rows if row[mode]["near_tie"])
        le7 = sum(
            1
            for row in rows
            if row[mode]["winner_age_days"] is not None
            and row[mode]["winner_age_days"] <= 7
        )
        le1 = sum(
            1
            for row in rows
            if row[mode]["winner_age_days"] is not None
            and row[mode]["winner_age_days"] <= 1
        )
        out[mode] = {
            "near_tie_rate": (near / len(rows)) if rows else 0.0,
            "winner_le_7d": le7,
            "winner_le_1d": le1,
        }
    out["winner_changed"] = sum(
        1
        for row in rows
        if row["additive"]["winner"] != row["tiebreak"]["winner"]
    )
    return out


def _refuse_live(path: Path) -> None:
    if "instances" in path.parts and ".engram" in path.parts:
        sys.exit(
            f"refusing to open a live instance store: {path}\n"
            f'make a copy first: sqlite3 {path} ".backup /tmp/graph-copy.db"'
        )


def _recency(created_at: str | None, at: datetime) -> float:
    if not created_at:
        return 1.0
    created = datetime.fromisoformat(created_at)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return 1.0 / (1.0 + (at - created).total_seconds() / 86400)


def _age_days(created_at: str | None, at: datetime) -> float | None:
    if not created_at:
        return None
    created = datetime.fromisoformat(created_at)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (at - created).total_seconds() / 86400


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
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        rows: list[dict] = []
        for log in logs:
            ctx = json.loads(log["context"] or "{}")
            query = ctx.get("query")
            if not query:
                continue
            at = datetime.fromisoformat(log["timestamp"])
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            embedding = embedder.embed([query], prefix="search_query")[0]
            cands: list[dict] = []
            created: dict[str, str | None] = {}
            for table, getter in (
                ("episode", store.get_episode),
                ("semantic", store.get_semantic),
            ):
                for candidate_id, distance in store.search_vectors(
                    table, embedding, k=40
                ):
                    row = getter(candidate_id)
                    if row is None:
                        continue
                    created[candidate_id] = row.get("created_at")
                    cands.append(
                        {
                            "id": candidate_id,
                            "similarity": vec0_distance_to_similarity(distance),
                            "recency": _recency(row.get("created_at"), at),
                            "auto_generated": bool(row.get("auto_generated", 0)),
                        }
                    )
            entry = {"query": query[:60], "at": log["timestamp"]}
            for mode in ("additive", "tiebreak"):
                result = rank(cands, mode=mode, **cfg)
                result["winner_age_days"] = (
                    _age_days(created.get(result["winner"]), at)
                    if result["winner"]
                    else None
                )
                entry[mode] = result
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
    total = summary["recalls"]
    for mode in ("additive", "tiebreak"):
        mode_summary = summary[mode]
        le7 = mode_summary["winner_le_7d"]
        le1 = mode_summary["winner_le_1d"]
        le7_share = (le7 / total * 100) if total else 0.0
        le1_share = (le1 / total * 100) if total else 0.0
        lines.append(
            f"| {mode} | {mode_summary['near_tie_rate']:.2f} | "
            f"{le7}/{total} ({le7_share:.1f}%) | "
            f"{le1}/{total} ({le1_share:.1f}%) |"
        )
    lines += [
        "",
        f"Winners that change between modes: {summary['winner_changed']} "
        f"of {summary['recalls']}.",
        "",
    ]
    changed = [
        row
        for row in rows
        if row["additive"]["winner"] != row["tiebreak"]["winner"]
    ]
    if changed:
        lines += [
            "| Query | additive winner | tiebreak winner |",
            "|---|---|---|",
        ]
        for row in changed[:25]:
            lines.append(
                f"| {row['query']} | {row['additive']['winner'][:8]} | "
                f"{row['tiebreak']['winner'][:8]} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("db_copy")
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--phase", default="Before", help="Section heading: Before or After")
    args = parser.parse_args(argv)
    db_copy = Path(args.db_copy)
    _refuse_live(db_copy)
    if not db_copy.exists():
        sys.exit(f"no such file: {db_copy}")
    rows, summary = replay(db_copy, args.limit)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    header = "" if output.exists() else "# Margins replay — recency as decider\n\n"
    with output.open("a") as report:
        report.write(header + render(rows, summary, db_copy, args.phase) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
