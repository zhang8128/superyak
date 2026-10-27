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
   preview, redundant cores, and session path signatures (Layer 5);
5. reports the store identity: the source's, read from the snapshot (for a
   store that predates identity, the id its migration would derive; it is
   never written there), beside the one migration gave ``working.db``;
6. re-hashes the source, refusing to report success if anything changed.

Results go to ``report.json`` and ``report.md`` in NEW_DIR. Each analysis is
isolated: one that cannot run on this schema records its error and the rest
continue. Nothing is enabled or gated by this report; it is the evidence the
cohesion and persistence specs require before either ``enabled`` flag is set.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import shutil
import sqlite3
import stat
import sys
import traceback
from array import array
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import store_reader

PRUNE_THRESHOLD = 0.05  # server.py sleep maintenance: prune_decayed(threshold=0.05)
DECAY_EXPONENT = 0.5
MAX_LANE_EPISODES = 16_000      # lane and core sets, in blocks (I 10, D31)
MAX_SEMANTIC_EPISODES = 1_024   # per-semantic dense sets (I 10, D31)


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
    stored, recomputed = array("d"), array("d")   # the cursor is read once; only these and a count are kept
    pruned_n, pruned_ids, last_touch = 0, [], None
    for r in conn.execute(
        "SELECT id, created_at, last_accessed, accessed_count, decay_strength,"
        " compressed, core, dormant FROM episodes"
    ):
        if r["decay_strength"] is not None:
            stored.append(r["decay_strength"])
        strength = r["decay_strength"]
        if r["core"] == 0 and (strength or 0) > 0.01:
            strength = decay_strength(r["accessed_count"], r["last_accessed"] or r["created_at"], now)
        if strength is not None:
            recomputed.append(strength)
        if (strength or 0) < PRUNE_THRESHOLD and r["compressed"] == 1 \
                and r["core"] == 0 and r["dormant"] == 0:
            pruned_n += 1
            if len(pruned_ids) < 50:
                pruned_ids.append(r["id"])
        touch = r["last_accessed"] or r["created_at"]
        if touch and (last_touch is None or touch > last_touch):
            last_touch = touch

    def dist(values):
        arr = np.array(values, dtype=np.float64)
        if not arr.size:
            return {"count": 0}
        return {"count": int(arr.size),
                "p10/p50/p90": [round(float(np.percentile(arr, p)), 4) for p in (10, 50, 90)],
                "below_prune_threshold": int((arr < PRUNE_THRESHOLD).sum())}

    return {
        "as_of": now.isoformat(),
        "last_touch": last_touch,
        "stored_strength": dist(stored),
        "strength_if_opened_now": dist(recomputed),
        "would_prune_to_cold": pruned_n,
        "would_prune_ids": pruned_ids,
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


def persistence_scores(conn, *, max_episodes: int | None = None, skips: list | None = None) -> dict[str, dict]:
    """``persistence.compute_scores`` without its cache write.

    With ``max_episodes`` each lane is counted first (``COUNT(*)``, before any vector is read). A lane over
    the bound is not scored (never sampled) and is named in ``skips`` as ``lane:<lane>``; the others use the
    blocked filtration (R28). Without it, today's dense filtration.
    """
    import persistence

    gen = persistence.generativity_scores(conn)
    out = {}
    for lane in ("personal", "work"):
        if max_episodes is None:
            ids, X = persistence._episodes_with_vectors(conn, lane=lane)
            if not ids:
                continue
            f = persistence.build_filtration(X)
        else:
            n = conn.execute("SELECT COUNT(*)" + persistence._LANE_SET, (lane,)).fetchone()[0]
            if not n:
                continue
            if n > max_episodes:
                persistence._skip(skips, f"lane:{lane}", n, max_episodes)
                continue
            ids, U = persistence._unit_rows(
                conn, "SELECT e.id, ev.embedding" + persistence._LANE_SET, (lane,), n)
            f = persistence.build_filtration_blocked(U, unit=True)
            del U
        red, uniq = persistence.redundancy(f), persistence.uniqueness(f)
        for i, eid in enumerate(ids):
            out[eid] = {"episode_id": eid, "lane": lane,
                        "redundancy": float(red[i]), "uniqueness": float(uniq[i]),
                        "generativity": float(gen.get(eid, 0.0))}
    return out


PATHS_NOT_MEASURED = "not measured at admission; trails are used only by the trail evaluation"

# Report sections a note may sit beside, by the key a caller names.
NOTE_SECTIONS = ("snapshot", "identity", "migration", "first_open", "cohesion", "persistence", "paths")


def strip_content(value):
    """A copy of ``value`` with every ``content`` key removed at any depth."""
    if isinstance(value, dict):
        return {k: strip_content(v) for k, v in value.items() if k != "content"}
    if isinstance(value, list):
        return [strip_content(v) for v in value]
    if isinstance(value, tuple):
        return tuple(strip_content(v) for v in value)
    return value


def cohesion_report(store, *, max_episodes: int | None = None, skips: list | None = None) -> dict:
    """The cohesion summary, one semantic at a time: a five-bin histogram, the 15 hottest and the 5 coolest.

    Two bounded heaps hold the extremes, so the ranked list ``sheaf.measure_all`` builds never exists. Ties
    keep ``measure_all``'s order (energy descending, then the order measured)."""
    import sheaf
    from config import CohesionConfig

    hist = np.zeros(5, dtype=np.int64)
    hottest: list = []   # min-heap of (energy, -seq, m): the 15 largest
    coolest: list = []   # min-heap of (-energy, seq, m): the 5 smallest energies
    measured = 0
    for seq, m in enumerate(sheaf.measure_each(store, CohesionConfig(), max_episodes=max_episodes, skips=skips)):
        measured += 1
        hist += np.histogram([m["energy"]], bins=5, range=(0, 1))[0]
        for heap, key, size in ((hottest, (m["energy"], -seq), 15), (coolest, (-m["energy"], seq), 5)):
            item = (*key, m)
            if len(heap) < size:
                heapq.heappush(heap, item)
            elif key > heap[0][:2]:
                heapq.heapreplace(heap, item)
    ranked_hot = [it[2] for it in sorted(hottest, key=lambda it: it[:2], reverse=True)]
    ranked_cool = [it[2] for it in sorted(coolest, key=lambda it: it[:2], reverse=True)]
    for m in ranked_hot + ranked_cool:
        sem = store.get_semantic(m["semantic_id"]) or {}
        m["content"] = (sem.get("content") or "")[:100]
    return {
        "measured": measured,
        "energy_histogram": [int(x) for x in hist] if measured else [],
        "hottest": ranked_hot,
        "coolest": ranked_cool if measured > 15 else [],
    }


def persistence_preview(store, *, max_episodes: int | None = None, max_semantic_episodes: int | None = None,
                        skips: list | None = None) -> dict:
    """The persistence section. ``max_episodes`` bounds the core set (lane sets are bounded where the
    scores are made); ``max_semantic_episodes`` bounds each hub and each audited event."""
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
    prune = persistence.evaluate_prune(store, cfg, counts_only=True)
    return {
        "lanes": lanes,
        "two_key_prune": {"would_evict": prune["evict"], "protected": prune["protected"]},
        "hubs": persistence.classify_hubs(store, cfg, max_episodes=max_semantic_episodes, skips=skips),
        "conjunct_audit": persistence.audit_unchecked_events(
            store, cfg, max_episodes=max_semantic_episodes, skips=skips),
        "redundant_cores": persistence.flag_redundant_cores(
            store, cfg, max_episodes=max_episodes, skips=skips)[:20],
    }


def identity_report(snapshot_survey: dict, working_conn) -> dict:
    """The source's identity (read from the snapshot, never assigned there)
    beside the working copy's after migration.

    For a store that predates identity, ``source.would_assign`` is what its
    own migration will derive; ``agrees`` says the working copy got the same
    id. ``None`` when either side is random and so cannot be compared.
    """
    import store_identity

    source = snapshot_survey.get("identity", {})
    working = store_identity.describe(working_conn)
    source_id = source.get("instance_id") or source.get("would_assign", {}).get("instance_id")
    working_id = working.get("instance_id")
    return {
        "source": source,
        "working": working,
        "agrees": (source_id == working_id) if source_id and working_id else None,
    }


def _connect_read_only(path):
    """The one place calibration opens the working copy: a read-only ``Storage``."""
    from storage import Storage

    return Storage.open_read_only(path)


def _error(e: Exception, no_content: bool, *, trace: bool = False) -> dict:
    """An analysis's error for the report. With ``no_content`` only its class name: a message or a traceback can
    quote a value, a path or a memory, and the report reaches the owner's ship (final review M4)."""
    if no_content:
        return {"error": type(e).__name__}
    out = {"error": f"{type(e).__name__}: {e}"}
    if trace:
        out["trace"] = traceback.format_exc(limit=3)
    return out


def _run(report: dict, name: str, fn, *args, no_content: bool = False) -> None:
    try:
        report["analyses"][name] = fn(*args)
    except Exception as e:  # one schema gap must not hide the other analyses
        report["analyses"][name] = _error(e, no_content, trace=True)


def calibrate(source: str | Path, out: str | Path, migrate: bool = True,
              now: datetime | None = None, *, no_content: bool = False,
              no_paths: bool = False, notes: Mapping[str, str] | None = None,
              create_parents: bool = True, max_lane_episodes: int | None = None,
              max_semantic_episodes: int | None = None) -> dict:
    from storage import Storage

    unknown = sorted(set(notes or {}) - set(NOTE_SECTIONS))
    if unknown:
        raise ValueError(f"notes name no report section: {unknown}")

    source, out = Path(source), Path(out)
    if not source.is_file():
        raise FileNotFoundError(str(source))
    out.mkdir(parents=create_parents, exist_ok=False)
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
        Storage(str(working), imprint_working_copy=True).close()
        after = store_reader.survey(working)
        report["migration"] = {
            "applied": pending,
            "episode_vector_rows_before": vectors_before,
            "episode_vector_rows_after": after.get("row_counts", {}).get("episode_vectors_rowids"),
            "note": "migration 004 recreates vector tables; vectors older than it are lost",
        }
    else:
        report["migration"] = {"applied": [], "skipped": bool(pending)}

    skips: list[dict] = []   # dense sets over their bound, named (I 10); never sampled
    ro = _connect_read_only(working)
    try:
        conn = ro.conn
        try:
            report["identity"] = identity_report(report["snapshot"], conn)
        except Exception as e:  # reported, like any analysis that cannot run
            report["identity"] = _error(e, no_content)
        _run(report, "first_open", first_open_preview, conn, now, no_content=no_content)
        scores: dict = {}
        try:
            scores = persistence_scores(conn, max_episodes=max_lane_episodes, skips=skips)
        except Exception as e:
            report["analyses"]["persistence_scores"] = _error(e, no_content)
        store = _ReadOnlyStore(ro, scores)
        _run(report, "cohesion", lambda: cohesion_report(
            store, max_episodes=max_semantic_episodes, skips=skips), no_content=no_content)
        _run(report, "persistence", lambda: persistence_preview(
            store, max_episodes=max_lane_episodes, max_semantic_episodes=max_semantic_episodes, skips=skips),
            no_content=no_content)
        if no_paths:
            report["analyses"]["paths"] = PATHS_NOT_MEASURED
        else:
            import paths
            _run(report, "paths", paths.report, conn, no_content=no_content)
    finally:
        ro.close()
    report["analyses"]["skipped_dense_sets"] = skips

    source_after = store_reader.file_facts(source)
    # -shm is SQLite's shared-memory index, rewritten by any WAL reader.
    report["source_unchanged"] = all(
        source_after.get(k) == source_before.get(k) for k in ("sha256", "bytes", "wal"))
    report["source_side_files_created"] = sorted(
        k for k in ("wal", "shm") if k in source_after and k not in source_before)
    if not report["source_unchanged"]:
        report["source_after"] = source_after
    if notes:
        report["notes"] = dict(notes)
    if no_content:
        report = strip_content(report)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "report.md").write_text(render_markdown(report))
    return report


def render_markdown(report: dict) -> str:
    src, snap, a = report["source"], report["snapshot"], report["analyses"]
    notes = report.get("notes", {})

    def note(name):
        return [f"- Note: {notes[name]}"] if name in notes else []

    lines = [
        "# Calibration report",
        "",
        f"Source: `{src['path']}` — {src['bytes']} bytes, sha256 `{src['sha256']}`",
        f"Source unchanged after calibration: **{report['source_unchanged']}**",
        "",
        "## Snapshot",
    ] + note("snapshot")
    schema = snap.get("schema", {})
    lines += [
        f"- Applied migrations: {schema.get('applied')}",
        f"- Pending: {schema.get('pending')}  Unknown: {schema.get('unknown')}",
    ]
    if "episodes" in snap:
        e = snap["episodes"]
        lines.append(f"- Episodes {snap['row_counts'].get('episodes')} from {e['first']} "
                     f"to {e['last']}, {e['sessions']} sessions")
    ident = report.get("identity", {})
    if "error" in ident:
        lines += ["", "## Store identity", *note("identity"),
                  f"- Not determined: {ident['error']}"]
    elif ident:
        src_id, wk = ident.get("source", {}), ident.get("working", {})
        lines += ["", "## Store identity", *note("identity")]
        if src_id.get("status") == "present":
            lines.append(f"- Source: `{src_id['instance_id']}` "
                         f"({src_id.get('instance_id_origin')})")
        else:
            plan = src_id.get("would_assign", {})
            lines.append(f"- Source: none stored; migration would assign "
                         f"`{plan.get('instance_id') or 'a random id'}` "
                         f"({plan.get('instance_id_origin')}, basis {plan.get('instance_id_basis')})")
        if wk.get("status") == "present":
            lines.append(f"- Working copy: `{wk['instance_id']}` ({wk.get('instance_id_origin')})")
        else:
            lines.append("- Working copy: none (not migrated)")
        lines.append(f"- Agrees: {ident.get('agrees')}")
    mig = report.get("migration", {})
    lines += ["", "## Working copy migration", *note("migration"), f"- Applied: {mig.get('applied')}"]
    if mig.get("applied"):
        lines.append(f"- Episode vector rows {mig.get('episode_vector_rows_before')} → "
                     f"{mig.get('episode_vector_rows_after')}")

    def section(title, body, key):
        lines.extend(["", f"## {title}", *note(key)])
        if isinstance(body, str):
            lines.append(f"- {body}")
            return False
        if isinstance(body, dict) and "error" in body:
            lines.append(f"- Not run: {body['error']}")
            return False
        return True

    fo = a.get("first_open", {})
    if section("First normal open, if it happened now", fo, "first_open"):
        lines += [
            f"- Last touch in store: {fo['last_touch']}",
            f"- Stored strength: {fo['stored_strength']}",
            f"- Strength after decay now: {fo['strength_if_opened_now']}",
            f"- Would move to cold.db: **{fo['would_prune_to_cold']}** episodes",
        ]
    co = a.get("cohesion", {})
    if section("Sheaf cohesion (hottest first)", co, "cohesion"):
        lines.append(f"- Semantics measured: {co['measured']}; histogram 0→1: {co['energy_histogram']}")
        for m in co["hottest"]:
            text = f"  {m['content']}" if "content" in m else ""
            lines.append(f"  - {m['energy']:.3f}  n={m['n']}{text}")
    pe = a.get("persistence", {})
    if section("Persistence", pe, "persistence"):
        for lane, s in pe["lanes"].items():
            lines.append(f"- [{lane}] {s}")
        lines.append(f"- Two-key prune: {pe['two_key_prune']}")
        for h in pe["hubs"]:
            text = f"  {h['content'][:60]}" if "content" in h else ""
            lines.append(f"  - {h['classification']:>11}  n={h['n']}  band={h['band']}{text}")
        lines.append(f"- Conjunct audit entries: {len(pe['conjunct_audit'])}; "
                     f"redundant cores flagged: {len(pe['redundant_cores'])}")
    if a.get("skipped_dense_sets"):
        lines += ["", "## Dense sets over their bound (not measured)"]
        lines += [f"- {k['set']}: {k['n']} episodes, bound {k['bound']}" for k in a["skipped_dense_sets"]]
    pa = a.get("paths", {})
    if section("Session paths (Layer 5)", pa, "paths"):
        lines.append(f"- Sessions with paths: {pa['sessions_with_paths']} of {pa['sessions_total']}; "
                     f"basis {pa['basis']}")
        lines.append(f"- Tortuosity: {pa['tortuosity']}")
        for r in pa["different_routes"][:5]:
            lines.append(f"  - different route: {r}")
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
