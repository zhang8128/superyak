"""Read-only calibration of a store before it is ever opened normally.

``python calibrate.py SOURCE_DB --out NEW_DIR`` never writes SOURCE_DB. It:

1. hashes the source (and its ``-wal``/``-shm``), then takes a consistent
   snapshot through a ``mode=ro`` connection with the SQLite backup API, so
   uncheckpointed WAL pages are included and the source is left alone;
2. surveys the snapshot (``store_reader.survey``) and marks it read-only;
3. copies the snapshot to ``working.db`` and, unless ``--no-migrate``, applies
   pending migrations there (``Storage.__init__`` migrates and checks vec0
   health; decay, pruning, compression and genome/inbox sync live in the
   server and never run here);
4. analyses ``working.db`` read-only: the decay and prune that a first normal
   open would apply now, sheaf cohesion energies, persistence distributions,
   hub classification, the retroactive conjunct audit, the two-key prune
   preview and redundant cores;
5. re-hashes the source, refusing to report success if anything changed.

Results go to ``report.json`` and ``report.md`` in NEW_DIR. Each analysis is
isolated: one that cannot run on this schema records its error and the rest
continue. Nothing is enabled or gated by this report; it is the evidence the
cohesion and persistence specs require before either ``enabled`` flag is set.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
import stat
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import store_reader

PRUNE_THRESHOLD = 0.05  # server.py sleep maintenance: prune_decayed(threshold=0.05)
DECAY_EXPONENT = 0.5


def _pending_wal(source: Path) -> bool:
    wal = source.with_name(source.name + "-wal")
    return wal.is_file() and wal.stat().st_size > 0


def snapshot(source: Path, dest: Path) -> None:
    """Copy ``source`` into ``dest`` through a read-only connection.

    Without pending WAL pages the source is opened ``immutable``, so SQLite
    creates no ``-wal``/``-shm`` beside it. With them, ``mode=ro`` is needed
    to include those pages, and SQLite may create or update ``-shm``.
    """
    src = store_reader.connect(source, immutable=not _pending_wal(source))
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    dest.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def decay_strength(accessed_count: int | None, last_touch: str | None,
                   now: datetime, d: float = DECAY_EXPONENT) -> float:
    """``Storage.apply_decay``'s strength for one episode at ``now``."""
    try:
        t_hours = max(0.1, (now - datetime.fromisoformat(last_touch)).total_seconds() / 3600)
    except (ValueError, TypeError):
        t_hours = 24.0
    n = (accessed_count or 0) + 1
    return min(1.0, math.log(1 + n * t_hours ** (-d)) / math.log(2 + n))


def first_open_preview(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """What decay then ``prune_decayed`` would do if the store opened now.

    Mirrors the server's non-persistence path; with ``[persistence] enabled``
    the prune additionally requires redundancy (see ``persistence_preview``)
    and decay exponents vary by ±15%, so treat this as the upper bound.
    """
    now = now or datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT id, created_at, last_accessed, accessed_count, decay_strength,"
        " compressed, core, dormant FROM episodes"
    ).fetchall()
    stored, recomputed, pruned = [], [], []
    last_touches = []
    for r in rows:
        stored.append(r["decay_strength"])
        strength = r["decay_strength"]
        if r["core"] == 0 and (strength or 0) > 0.01:
            strength = decay_strength(r["accessed_count"], r["last_accessed"] or r["created_at"], now)
        recomputed.append(strength)
        if (strength or 0) < PRUNE_THRESHOLD and r["compressed"] == 1 \
                and r["core"] == 0 and r["dormant"] == 0:
            pruned.append(r["id"])
        last_touches.append(r["last_accessed"] or r["created_at"])

    def dist(values):
        arr = np.array([v for v in values if v is not None], dtype=np.float64)
        if not arr.size:
            return {"count": 0}
        return {"count": int(arr.size),
                "p10/p50/p90": [round(float(np.percentile(arr, p)), 4) for p in (10, 50, 90)],
                "below_prune_threshold": int((arr < PRUNE_THRESHOLD).sum())}

    return {
        "as_of": now.isoformat(),
        "last_touch": max((t for t in last_touches if t), default=None),
        "stored_strength": dist(stored),
        "strength_if_opened_now": dist(recomputed),
        "would_prune_to_cold": len(pruned),
        "would_prune_ids": pruned[:50],
    }


class _ReadOnlyStore:
    """The storage surface the analyses use, over a read-only Storage."""

    def __init__(self, storage, scores: dict[str, dict]):
        self._storage = storage
        self.conn = storage.conn
        self._scores = scores

    def get_semantic(self, sid):
        return self._storage.get_semantic(sid)

    def get_episode(self, eid):
        return self._storage.get_episode(eid)

    def get_persistence_scores(self):
        return self._scores

    def upsert_persistence_scores(self, scores):
        pass  # scores are reported, never cached


def persistence_scores(conn) -> dict[str, dict]:
    """``persistence.compute_scores`` without its cache write."""
    import persistence

    gen = persistence.generativity_scores(conn)
    out = {}
    for lane in ("personal", "work"):
        ids, X = persistence._episodes_with_vectors(conn, lane=lane)
        if not ids:
            continue
        f = persistence.build_filtration(X)
        red, uniq = persistence.redundancy(f), persistence.uniqueness(f)
        for i, eid in enumerate(ids):
            out[eid] = {"episode_id": eid, "lane": lane,
                        "redundancy": float(red[i]), "uniqueness": float(uniq[i]),
                        "generativity": float(gen.get(eid, 0.0))}
    return out


def cohesion_report(store) -> dict:
    import sheaf
    from config import CohesionConfig

    ranked = sheaf.measure_all(store, CohesionConfig())
    for m in ranked:
        sem = store.get_semantic(m["semantic_id"]) or {}
        m["content"] = (sem.get("content") or "")[:100]
    energies = [m["energy"] for m in ranked]
    return {
        "measured": len(ranked),
        "energy_histogram": [int(x) for x in np.histogram(energies, bins=5, range=(0, 1))[0]]
        if energies else [],
        "hottest": ranked[:15],
        "coolest": ranked[-5:][::-1] if len(ranked) > 15 else [],
    }


def persistence_preview(store) -> dict:
    import persistence
    from config import PersistenceConfig

    cfg = PersistenceConfig(enabled=True)  # evaluation only; nothing writes
    scores = store.get_persistence_scores()
    lanes = {}
    for lane in ("personal", "work"):
        rows = [s for s in scores.values() if s["lane"] == lane]
        if not rows:
            continue
        red = np.array([s["redundancy"] for s in rows])
        uniq = np.array([s["uniqueness"] for s in rows])
        lanes[lane] = {
            "n": len(rows),
            "redundancy_p50/p90": [round(float(np.percentile(red, p)), 3) for p in (50, 90)],
            "uniqueness_p50/p90": [round(float(np.percentile(uniq, p)), 3) for p in (50, 90)],
            "would_protect_unique": int((uniq >= cfg.protect_threshold).sum()),
            "redundant_enough": int((red >= cfg.redundancy_floor).sum()),
            "generative": sum(1 for s in rows if s["generativity"] > 0),
        }
    prune = persistence.evaluate_prune(store, cfg)
    return {
        "lanes": lanes,
        "two_key_prune": {"would_evict": len(prune["evict"]),
                          "protected": len(prune["protected"])},
        "hubs": persistence.classify_hubs(store, cfg),
        "conjunct_audit": persistence.audit_unchecked_events(store, cfg),
        "redundant_cores": persistence.flag_redundant_cores(store, cfg)[:20],
    }


def _run(report: dict, name: str, fn, *args) -> None:
    try:
        report["analyses"][name] = fn(*args)
    except Exception as e:  # one schema gap must not hide the other analyses
        report["analyses"][name] = {"error": f"{type(e).__name__}: {e}",
                                    "trace": traceback.format_exc(limit=3)}


def calibrate(source: str | Path, out: str | Path, migrate: bool = True,
              now: datetime | None = None) -> dict:
    from storage import Storage

    source, out = Path(source), Path(out)
    if not source.is_file():
        raise FileNotFoundError(str(source))
    out.mkdir(parents=True, exist_ok=False)
    source_before = store_reader.file_facts(source)

    snap = out / "snapshot.db"
    snapshot(source, snap)
    report = {
        "source": source_before,
        "snapshot": store_reader.survey(snap),
        "analyses": {},
    }

    working = out / "working.db"
    shutil.copyfile(snap, working)
    working.chmod(stat.S_IRUSR | stat.S_IWUSR)
    pending = report["snapshot"].get("schema", {}).get("pending", [])
    if migrate and pending:
        vectors_before = report["snapshot"].get("row_counts", {}).get("episode_vectors_rowids")
        Storage(str(working)).close()
        after = store_reader.survey(working)
        report["migration"] = {
            "applied": pending,
            "episode_vector_rows_before": vectors_before,
            "episode_vector_rows_after": after.get("row_counts", {}).get("episode_vectors_rowids"),
            "note": "migration 004 recreates vector tables; vectors older than it are lost",
        }
    else:
        report["migration"] = {"applied": [], "skipped": bool(pending)}

    ro = Storage.open_read_only(working)
    try:
        conn = ro.conn
        _run(report, "first_open", first_open_preview, conn, now)
        scores: dict = {}
        try:
            scores = persistence_scores(conn)
        except Exception as e:
            report["analyses"]["persistence_scores"] = {"error": f"{type(e).__name__}: {e}"}
        store = _ReadOnlyStore(ro, scores)
        _run(report, "cohesion", cohesion_report, store)
        _run(report, "persistence", persistence_preview, store)
    finally:
        ro.close()

    source_after = store_reader.file_facts(source)
    # -shm is SQLite's shared-memory index, rewritten by any WAL reader.
    report["source_unchanged"] = all(
        source_after.get(k) == source_before.get(k) for k in ("sha256", "bytes", "wal"))
    report["source_side_files_created"] = sorted(
        k for k in ("wal", "shm") if k in source_after and k not in source_before)
    if not report["source_unchanged"]:
        report["source_after"] = source_after
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "report.md").write_text(render_markdown(report))
    return report


def render_markdown(report: dict) -> str:
    src, snap, a = report["source"], report["snapshot"], report["analyses"]
    lines = [
        "# Calibration report",
        "",
        f"Source: `{src['path']}` — {src['bytes']} bytes, sha256 `{src['sha256']}`",
        f"Source unchanged after calibration: **{report['source_unchanged']}**",
        "",
        "## Snapshot",
    ]
    schema = snap.get("schema", {})
    lines += [
        f"- Applied migrations: {schema.get('applied')}",
        f"- Pending: {schema.get('pending')}  Unknown: {schema.get('unknown')}",
    ]
    if "episodes" in snap:
        e = snap["episodes"]
        lines.append(f"- Episodes {snap['row_counts'].get('episodes')} from {e['first']} "
                     f"to {e['last']}, {e['sessions']} sessions")
    mig = report.get("migration", {})
    lines += ["", "## Working copy migration", f"- Applied: {mig.get('applied')}"]
    if mig.get("applied"):
        lines.append(f"- Episode vector rows {mig.get('episode_vector_rows_before')} → "
                     f"{mig.get('episode_vector_rows_after')}")

    def section(title, body):
        lines.extend(["", f"## {title}"])
        if isinstance(body, dict) and "error" in body:
            lines.append(f"- Not run: {body['error']}")
            return False
        return True

    fo = a.get("first_open", {})
    if section("First normal open, if it happened now", fo):
        lines += [
            f"- Last touch in store: {fo['last_touch']}",
            f"- Stored strength: {fo['stored_strength']}",
            f"- Strength after decay now: {fo['strength_if_opened_now']}",
            f"- Would move to cold.db: **{fo['would_prune_to_cold']}** episodes",
        ]
    co = a.get("cohesion", {})
    if section("Sheaf cohesion (hottest first)", co):
        lines.append(f"- Semantics measured: {co['measured']}; histogram 0→1: {co['energy_histogram']}")
        for m in co["hottest"]:
            lines.append(f"  - {m['energy']:.3f}  n={m['n']}  {m['content']}")
    pe = a.get("persistence", {})
    if section("Persistence", pe):
        for lane, s in pe["lanes"].items():
            lines.append(f"- [{lane}] {s}")
        lines.append(f"- Two-key prune: {pe['two_key_prune']}")
        for h in pe["hubs"]:
            lines.append(f"  - {h['classification']:>11}  n={h['n']}  band={h['band']}  {h['content'][:60]}")
        lines.append(f"- Conjunct audit entries: {len(pe['conjunct_audit'])}; "
                     f"redundant cores flagged: {len(pe['redundant_cores'])}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engram-calibrate", description=__doc__.splitlines()[0])
    parser.add_argument("source")
    parser.add_argument("--out", required=True, help="new directory; must not exist")
    parser.add_argument("--no-migrate", action="store_true",
                        help="analyse the working copy at its own schema")
    args = parser.parse_args(argv)
    try:
        report = calibrate(args.source, args.out, migrate=not args.no_migrate)
    except (FileNotFoundError, FileExistsError, sqlite3.Error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print((Path(args.out) / "report.md").read_text())
    return 0 if report["source_unchanged"] else 2


if __name__ == "__main__":
    sys.exit(main())
