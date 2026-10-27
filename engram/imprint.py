"""Store imprints: copy part of a store, with its owner's permission (store-copy spec I 5, 6, 13).

This module holds the package writer (Task 13) and the ``plan`` command with its dry run (Task 15). It imports no
numpy: ``calibrate`` is imported inside the functions that need it (P35).
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import heapq
import itertools
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import store_identity
import store_reader
from imprint_checks import l1_values, l2_fts, l3_vec0, l4_raw
from imprint_filter import (CLOSED_SECONDS, FILTER, DIGEST_TABLES, IMPRINT_SUBJECTS_DDL, NAMES_SHOWN, OTHERS_AWAY_WORDS,
                            OTHERS_HOME_WORDS, OTHERS_NO_LEDGER_WORDS, TIMES_WORDS, WITHOUT_ROUTE_WORDS, IdSet,
                            PackageRows, People, PlanRefused, Scratch, ScratchMap, Selection, Terms, check_owner,
                            canonical, check_package_tables, check_source, classify_source, contents_of, cross_references, left_out_keys, open_ledger,
                            package_rows, parse_selection, parse_terms, people, plan_digest, row_key, scope_of, semantic_rows)
from imprint_filter import _instant_text

BATCH_ROWS = 1000                   # rows per insert batch (D42, I 14)
BATCH_BYTES = 8 * 2**20             # bytes per insert batch; a row alone over it is a batch of one


def _connect(path: Path | str, *, read_only: bool, immutable: bool = False, vec: bool = False) -> sqlite3.Connection:
    """The one place this module opens SQLite (P30). Every connection keeps its temp files on disk."""
    if read_only:
        uri = f"file:{Path(path).resolve()}?mode=ro" + ("&immutable=1" if immutable else "")
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(str(path))
    if vec:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    conn.execute("PRAGMA temp_store = FILE")
    return conn


def _size(values: tuple) -> int:
    return 16 + sum(len(v) if isinstance(v, (str, bytes)) else 8 for v in values)


def _batched(rows: Iterable[tuple]) -> Iterator[list[tuple]]:
    """Batches of at most ``BATCH_ROWS`` rows or ``BATCH_BYTES`` bytes; a row over the bytes alone is a batch."""
    batch: list[tuple] = []
    size = 0
    for row in rows:
        batch.append(row)
        size += _size(row)
        if len(batch) >= BATCH_ROWS or size >= BATCH_BYTES:
            yield batch
            batch, size = [], 0
    if batch:
        yield batch


def _insert_table(conn: sqlite3.Connection, table: str, rows: Iterable[dict]) -> None:
    """Stream ``rows`` into ``table`` with an explicit column list that never names ``rowid`` (D33), committing
    after each batch."""
    it = iter(rows)
    first = next(it, None)
    if first is None:
        return
    columns = list(first)
    known = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
    extra = [c for c in columns if c not in known or c == "rowid"]
    if extra:
        raise ValueError(f"{table}: no such column(s) in the package: {', '.join(extra)}")
    sql = (f'INSERT INTO "{table}" ({", ".join(chr(34) + c + chr(34) for c in columns)}) '
           f'VALUES ({", ".join("?" * len(columns))})')
    tuples = (tuple(r[c] for c in columns) for r in itertools.chain([first], it))
    for batch in _batched(tuples):
        conn.executemany(sql, batch)
        conn.commit()


def write_package(rows: PackageRows, dest: Path, *, source_id: str, source_ancestry: list[str],
                  source_complete: bool, imprint_id: str) -> None:
    """I 6.1 steps 4 to 7: a fresh file with every migration, the imprint's identity and ``imprint_subjects``;
    the rows of ``rows`` inserted table by table in memory order; then the checks, ``journal_mode=DELETE`` and
    ``VACUUM``. It never writes over an existing file."""
    from storage import Storage

    dest = Path(dest)
    if dest.exists():
        raise FileExistsError(f"{dest} exists; a package is never written over a file")
    store = None
    try:
        store = Storage(str(dest))
        conn = store.conn
        store_identity.stamp_imprint(conn, source_id, source_ancestry, source_complete, imprint_id)
        conn.execute(IMPRINT_SUBJECTS_DDL)
        conn.commit()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("PRAGMA temp_store = FILE")
        source: Mapping = rows.rows
        for table in DIGEST_TABLES:
            _insert_table(conn, table, source[table])
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("the package breaks a foreign key")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("the package fails its integrity check")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("VACUUM")
        if conn.execute("PRAGMA freelist_count").fetchone()[0] != 0:
            raise RuntimeError("the package has free pages after VACUUM")
        store.close()
        store = None
        check = _connect(dest, read_only=True)
        try:
            check_package_tables(check)
        finally:
            check.close()
    except BaseException:
        if store is not None:
            store.close()
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(dest) + suffix).unlink(missing_ok=True)
        raise


# ---- The station's answer (R7) and the store (I 5.1) --------------------------------------------------------

PART_BYTES = 4_194_304              # one part of the package on the wire (I 14)
DEFAULT_DAYS = 90


@dataclass(frozen=True)
class Context:
    """What ``agent imprint context`` saved: the station, the requesting ship, its owner and the operator whose home
    an audience may name."""
    station: str                    # how the dry run names the station (its address, else its peer id)
    ship: str
    owner: str
    operator: str
    station_peer_id: str


def read_context(home: Path) -> Context:
    """``home/imprints/context.json`` (R7). ``station`` is the station's peer id and ``url`` its address."""
    again = "Run make imprint-plan again; it asks the station first."
    path = Path(home) / "imprints" / "context.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PlanRefused("No station context. " + again) from None
    except (OSError, ValueError):
        raise PlanRefused("The station context can't be read. " + again) from None
    if not isinstance(data, dict):
        raise PlanRefused("The station context can't be read. " + again)
    values = {k: data.get(k) for k in ("ship", "owner", "operator", "station")}
    if not all(isinstance(v, str) and v for v in values.values()):
        raise PlanRefused("The station context is incomplete. " + again)
    url = data.get("url")
    return Context(station=url if isinstance(url, str) and url else values["station"], ship=values["ship"],
                   owner=values["owner"], operator=values["operator"], station_peer_id=values["station"])


def resolve_store(store: Path | None, *, engram_home: Path, project_root: Path) -> Path:
    """``--store``, else the store the engram server would open from ``project_root`` (I 5.1)."""
    if store is not None:
        return Path(store)
    from config import resolve_db_path

    return resolve_db_path(Path(engram_home), Path(project_root))


# ---- The plan --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Plan:
    id: str
    created: int
    store: Path
    source_id: str
    source_identity: str            # "present" (stored) or "derived" (what migration would assign)
    ancestry: tuple[str, ...]
    ancestry_complete: bool
    selection: Selection
    terms: Terms
    digest: str
    counts: dict                    # what stays and why, as numbers; no key names a person or a memory
    contents: dict                  # the digest tables with a row, and their counts (I 7.1)
    package_bytes: int
    parts: int
    others: dict                    # {"memories": n, "people": p}: shipped memories with co-subjects (D27, D43)
    home: bool                      # the copy stays in the owner's home (I 5.2)
    people: dict                    # reason -> People: "others", "needs_yes", "said_no", "retired"
    origin: str | None              # the store's instance_id_origin
    not_copied: tuple[str, ...]     # source tables no rule names (D4)
    owner: str
    cross_references: tuple = ()   # CrossRef(table, id, keys): shipped text that names something that stays


PEOPLE_REASONS = ("others", "needs_yes", "said_no", "retired")
_WORK_FILES = ("snapshot.db", "working.db", "scratch.db", "package.db")


def plans_dir(home: Path) -> Path:
    path = Path(home) / "imprints" / "plans"
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def _new_scratch(home: Path) -> Path:
    return Path(tempfile.mkdtemp(prefix="scratch-", dir=plans_dir(home)))      # 0700


def _remove_work(work: Path, *, whole: bool) -> None:
    if whole:
        shutil.rmtree(work, ignore_errors=True)
        return
    for name in _WORK_FILES:
        for suffix in ("", "-journal", "-wal", "-shm"):
            (work / (name + suffix)).unlink(missing_ok=True)


def _default_engram_home() -> Path:
    return Path(os.environ.get("ENGRAM_HOME", Path(__file__).resolve().parent))


def _write_private(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _plan_file(plan: Plan) -> str:
    """The saved plan: selection, terms and digest with the counts. Memory ids never appear but ``--exclude``'s own."""
    return json.dumps({
        "version": 1, "id": plan.id, "created": plan.created, "store": str(plan.store),
        "source_id": plan.source_id, "owner": plan.owner, "home": plan.home,
        "scope": scope_of(plan.selection), "exclude": sorted(plan.selection.exclude),
        "terms": {"audience": plan.terms.audience, "actions": sorted(plan.terms.actions),
                  "purposes": sorted(plan.terms.purposes), "days": plan.terms.days},
        "digest": plan.digest, "counts": plan.counts, "contents": plan.contents, "others": plan.others,
        "package_bytes": plan.package_bytes, "parts": plan.parts,
        "cross_references": len({c.id for c in plan.cross_references})}, indent=2, sort_keys=True) + "\n"


def _working_copy(store: Path, work: Path, *, engram_home: Path, home: Path, ledger, owner: str,
                  expected_id: str, wrong_id: str):
    """Snapshot ``store`` into ``work``, check it is a source the plan may read, and migrate a working copy.
    Returns ``(source_id, identity, ancestry, complete, not_copied, working_path)``. The source is read only
    through ``calibrate.snapshot``."""
    import calibrate                                    # numpy: only when a plan runs (P35)
    from storage import Storage

    snap = work / "snapshot.db"
    calibrate.snapshot(store, snap)
    reader = store_reader.connect(snap)
    try:
        check_source(store, reader, engram_home=engram_home,
                     imprint_roots=(Path.home() / ".engram" / "imprints", home / "imprints"))
        source_id = store_identity.effective_id(reader)
        if source_id != expected_id:
            raise PlanRefused(wrong_id)
        check_owner(ledger, source_id, owner)
        identity = store_identity.describe(reader)
        ancestry, complete = store_identity.ancestry(reader)
        not_copied = classify_source(reader).unnamed
        pending = store_reader._schema(reader, store_reader._tables(reader))["pending"]
    finally:
        reader.close()
    working = work / "working.db"
    shutil.copyfile(snap, working)
    working.chmod(0o600)
    if pending:
        Storage(str(working)).close()                   # imprint_working_copy stays False: an imprint fails closed
    return source_id, identity, ancestry, complete, not_copied, working


def make_plan(store: Path, sel: Selection, terms: Terms, ctx, context: Context, home: Path, now: int, *,
              scratch_dir: Path | None = None, engram_home: Path | None = None, list_to: Path | None = None) -> Plan:
    """Snapshot the source, migrate a working copy, compute M, the digest, the contents and the size, save the plan
    and return it. The source is read only through ``calibrate.snapshot``. The snapshot, the working copy and the
    scratch file live in a 0700 directory under ``home/imprints/plans/`` (``scratch_dir``, which the caller removes,
    or one made here and removed here). ``make_plan`` sets no environment variable (R26)."""
    store, home = Path(store), Path(home)
    if ctx.owner != context.owner:
        raise PlanRefused("The plan's owner is not the owner the station named; nothing was planned.")
    engram_home = _default_engram_home() if engram_home is None else Path(engram_home)
    work = _new_scratch(home) if scratch_dir is None else Path(scratch_dir)
    scratch = conn = None
    try:
        source_id, identity, ancestry, complete, not_copied, working = _working_copy(
            store, work, engram_home=engram_home, home=home, ledger=ctx.ledger, owner=context.owner,
            expected_id=ctx.source_id,
            wrong_id="The source store is not the one this plan was set up for; nothing was planned.")
        scratch = Scratch(work / "scratch.db")
        c = replace(ctx, scratch=scratch, terms=terms, now=now)
        conn = _connect(working, read_only=True, vec=True)
        conn.row_factory = sqlite3.Row
        pr = package_rows(conn, sel, terms, c)
        digest = plan_digest(scope_of(sel), pr.rows, scratch=scratch)
        contents = contents_of(pr.rows)
        sessions = IdSet(scratch)
        for row in pr.rows["episodes"]:
            if row["session_id"]:
                sessions.add(row["session_id"])
        counts = dict(pr.counts)
        counts.update(sessions=len(sessions),
                      source_episodes=conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0],
                      source_semantics=conn.execute("SELECT COUNT(*) FROM semantics").fetchone()[0])
        who = {reason: people(scratch, reason) for reason in PEOPLE_REASONS}
        cold = Path(store).with_name("cold.db")
        cold_conn = store_reader.connect(cold, immutable=True) if cold.is_file() else None
        try:
            crossed = tuple(cross_references(pr, left_out_keys(conn, cold_conn, pr, scratch=scratch)))
        finally:
            if cold_conn is not None:
                cold_conn.close()
        if list_to is not None:
            _write_list(Path(list_to), pr.rows)
        package = work / "package.db"
        write_package(pr, package, source_id=source_id, source_ancestry=ancestry, source_complete=complete,
                      imprint_id=str(uuid.uuid4()))
        size = package.stat().st_size
        plan = Plan(
            id=uuid.uuid4().hex, created=now, store=store, source_id=source_id,
            source_identity="present" if identity["status"] == "present" else "derived", ancestry=tuple(ancestry),
            ancestry_complete=bool(complete), selection=sel, terms=terms, digest=digest, counts=counts,
            contents=contents, package_bytes=size, parts=max(1, -(-size // PART_BYTES)), others=pr.others,
            home=bool(ctx.home), people=who, origin=identity.get("instance_id_origin"),
            not_copied=tuple(not_copied), owner=context.owner, cross_references=crossed)
        _write_private(plans_dir(home) / f"{plan.id}.json", _plan_file(plan))
        return plan
    finally:
        if conn is not None:
            conn.close()
        if scratch is not None:
            scratch.close()
        _remove_work(work, whole=scratch_dir is None)


def _write_list(path: Path, rows: Mapping[str, Iterable[dict]]) -> None:
    """``--list``: one JSON line ``{table, key}`` per row that would leave, written as the rows are read."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for table in DIGEST_TABLES:
            for row in rows[table]:
                f.write(json.dumps({"table": table, "key": row_key(table, row)}, sort_keys=True) + "\n")


# ---- The dry run in words (I 5.4) ------------------------------------------------------------------------------

def _n(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


def _name(subject: str) -> str:
    return subject.removeprefix("person:")


def _when(seconds: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(seconds))


def _names(p: People) -> str:
    text = ", ".join(_name(s) for s, _ in p.named)
    return text + (f" and {p.more:,} more" if p.more else "")


def _reason_lines(p: People, one: str, many: str, rest: str) -> list[str]:
    """At most ``NAMES_SHOWN`` lines for one reason, then one line for the rest (the re-check's S3)."""
    lines = [f"  {_n(n, 'memory', 'memories')} {one if n == 1 else many}".replace("{name}", _name(s))
             for s, n in p.named]
    if p.more:
        lines.append("  " + rest.format(more=_n(p.more, "more person", "more people")))
    return lines


def _ancestry_line(plan: Plan) -> str:
    how = "stored, " + ("made after store identity" if plan.origin == "creation" else
                        "made before store identity" if plan.origin == "retroactive" else
                        "a fork of another store" if plan.origin == "fork" else "recorded in the store")
    if plan.source_identity == "derived":
        how = "not stored; derived from the store's earliest episode, as its first open would"
    shown = ", ".join(i[:8] for i in plan.ancestry[:4])
    if plan.ancestry:
        more = len(plan.ancestry) - 4
        copied = "copied from " + shown + (f" and {more} more" if more > 0 else "")
    else:
        copied = "copied from no recorded store"
    return (f"{plan.source_id[:8]} ({how}; {copied}; "
            f"{'lineage complete' if plan.ancestry_complete else 'lineage incomplete'})")


def _others_paragraph(plan: Plan) -> str:
    n, p = plan.others["memories"], plan.others["people"]
    if plan.home:
        if n == 0:
            return "Other people: " + OTHERS_NO_LEDGER_WORDS
        return (f"Other people: {_n(n, 'memory has', 'memories have')} other people recorded on them "
                f"({_n(p, 'person', 'people')}: {_names(plan.people['others'])}). " + OTHERS_HOME_WORDS)
    stay = plan.counts.get("needs_yes", 0)
    if stay == 0:
        return "Other people: " + OTHERS_AWAY_WORDS
    return (f"Other people: {_n(stay, 'memory has', 'memories have')} another person recorded on them "
            f"({_n(plan.people['needs_yes'].count, 'person', 'people')}: {_names(plan.people['needs_yes'])}). "
            "This copy leaves your home, so they stay here: no use of them at the station could be allowed "
            "without that person's yes. " + OTHERS_AWAY_WORDS)


def _cross_reference_lines(plan: Plan, show: bool) -> list[str]:
    """The count of shipped memories whose text names something that stays (I 6.4 item 1), and with ``show`` each
    one's id and the table of the key it names, never the key."""
    ids: dict[str, str] = {}
    for c in plan.cross_references:
        ids.setdefault(c.id, c.layer)
    if not ids:
        return []
    layers = Counter(ids.values())
    what = " and ".join(_n(layers[k], k, plural) for k, plural in (("episode", "episodes"), ("semantic", "semantics"))
                        if layers[k])
    out = ["", f"Text that names something staying here: {what}. See them with --show-cross-references,",
           "then leave them out with --exclude FILE and plan again."]
    if show:
        out += [f"  {c.id} names a key in {c.table} ({_n(c.keys, 'mention', 'mentions')})" for c in plan.cross_references]
    return out


def render_dry_run(plan: Plan, context: Context, *, show_cross_references: bool = False) -> str:
    sel, terms, c, k = plan.selection, plan.terms, plan.counts, plan.contents
    route = terms.route
    lanes = ", ".join(sorted(sel.lanes)) + (" lane" if len(sel.lanes) == 1 else " lanes")
    window = f"{'the beginning' if sel.since is None else _when(sel.since)} to {_when(sel.until)}"
    vectors = k.get("episode_vectors", 0) + k.get("semantic_vectors", 0)
    links = [(k.get("semantic_sources", 0), "semantic sources"), (k.get("resonances", 0), "resonances"),
             (k.get("semantic_peers", 0), "semantic peers"), (k.get("subdivision_events", 0), "subdivision events")]
    def row(label: str, n: int, text: str) -> str:
        return f"  {label:<15}{n:>7,}   {text}"

    link_text = ", ".join(f"{n:,} {w}" for n, w in links if n) or "none"
    out = [f"Imprint plan {plan.id[:4]} (nothing has left this machine)", "",
           f"Store     {plan.store}",
           f"Store id  {_ancestry_line(plan)}",
           f"Station   {context.station} as ship {context.ship} (owner {context.owner})", "",
           "What would leave",
           row("Episodes", k.get("episodes", 0), f"{lanes}, {window}"),
           row("Semantics", k.get("semantics", 0), f"{lanes}; every recorded source is also leaving"),
           row("Vectors", vectors, "copied as stored, never re-embedded")]
    if route:
        out += [row("Session ids", c.get("sessions", 0), f"sessions closed by {_when(sel.until - CLOSED_SECONDS)}: "
                    "which of them wrote each episode, sent only because you chose route"),
                row("Recall log", k.get("memory_log", 0), "rows from those sessions, sent only because you chose "
                    "route; instinct results, query text and notes removed"),
                row("Citing actions", k.get("operation_log", 0), "mark_core, instinct_feedback and dream_react rows "
                    "from those sessions, sent only because you chose route")]
    out.append(row("Links", sum(n for n, _ in links), link_text))
    if plan.home and plan.others["memories"]:
        out.append(row("Other people", plan.others["memories"], "memories with other people recorded on them "
                       f"({_n(plan.others['people'], 'person', 'people')}), copied with them as co-subjects"))
    out += [f"  {TIMES_WORDS}", "", "What stays here"]
    left_e = max(0, c.get("source_episodes", 0) - k.get("episodes", 0))
    left_s = max(0, c.get("source_semantics", 0) - k.get("semantics", 0))
    out.append(f"  {_n(left_e, 'episode', 'episodes')}, {_n(left_s, 'semantic', 'semantics')}, every instinct, dream "
               "residue, task contexts, anchors, assessments, notes, clipboard, code index, cold storage, category "
               "stores, knowledge graph, the session registry (harness, model, working directory).")
    if not route:
        out.append("  " + WITHOUT_ROUTE_WORDS)
    if c.get("semantic_source_stays"):
        out.append(f"  {_n(c['semantic_source_stays'], 'semantic stays', 'semantics stay')} because a recorded source "
                   "episode stays.")
    if c.get("semantic_unsourced"):
        out.append(f"  {_n(c['semantic_unsourced'], 'semantic stays', 'semantics stay')} because no source is "
                   "recorded (add --include-unsourced-semantics to send them).")
    if c.get("lane_unsettled"):
        out.append(f"  {_n(c['lane_unsettled'], 'memory stays', 'memories stay')} because a lane change at home has "
                   "not settled.")
    if c.get("unparseable_time"):
        out.append(f"  {_n(c['unparseable_time'], 'memory stays', 'memories stay')} because its time can't be read.")
    out += _reason_lines(plan.people["needs_yes"], "stays because it needs {name}'s yes",
                         "stay because each needs {name}'s yes", "Others stay because they need the yes of {more}.")
    out += _reason_lines(plan.people["said_no"], "stays because {name} said no", "stay because {name} said no",
                         "Others stay because {more} said no.")
    out += _reason_lines(plan.people["retired"], "stays because {name} is retired in your permissions ledger",
                         "stay because {name} is retired in your permissions ledger",
                         "Others stay because {more} are retired in your permissions ledger.")
    if c.get("bound"):
        out.append(f"  {_n(c['bound'], 'memory stays', 'memories stay')} because more than 8 people or places are "
                   "recorded on them")
    if plan.not_copied:
        out.append("  Tables no rule names, not copied: " + ", ".join(plan.not_copied[:NAMES_SHOWN])
                   + (f" and {len(plan.not_copied) - NAMES_SHOWN} more" if len(plan.not_copied) > NAMES_SHOWN else ""))
    out += _cross_reference_lines(plan, show_cross_references)
    out += ["", _others_paragraph(plan), "", "Permission you would give",
            f"  Audience  {terms.audience} (the station's imprint agent, acting for {context.operator})",
            "  Allows    recall, read and imprint on these memories"
            + ("; for the trail evaluation, keeping which session wrote each memory and the recall log, which make "
               "your trails, and route over their roads and trails" if route else ""),
            "  Purposes  " + ", ".join(sorted(terms.purposes)),
            f"  Ends      {terms.days} days after you say yes",
            f"  Size      {plan.package_bytes / 2**20:.1f} MiB in {_n(plan.parts, 'part', 'parts')}", "",
            f"Plan digest {plan.digest[:8]}...  (your browser will show the same 8 characters)",
            f"Read what would leave: make imprint-read PLAN={plan.id[:4]}",
            f"Send it:               make imprint-send PLAN={plan.id[:4]}"]
    return "\n".join(out) + "\n"


def plan_dict(plan: Plan, *, show_cross_references: bool = False) -> dict:
    """``--json``: the whole dry run as numbers and at most ``NAMES_SHOWN`` names a reason."""
    return {"id": plan.id, "created": plan.created, "store": str(plan.store), "source_id": plan.source_id,
            "source_identity": plan.source_identity, "ancestry": list(plan.ancestry),
            "ancestry_complete": plan.ancestry_complete, "scope": scope_of(plan.selection),
            "terms": {"audience": plan.terms.audience, "actions": sorted(plan.terms.actions),
                      "purposes": sorted(plan.terms.purposes), "days": plan.terms.days},
            "digest": plan.digest, "counts": plan.counts, "contents": plan.contents, "others": plan.others,
            "home": plan.home, "package_bytes": plan.package_bytes, "parts": plan.parts,
            "people": {r: {"count": p.count, "named": [[_name(s), n] for s, n in p.named], "more": p.more}
                       for r, p in plan.people.items()},
            "not_copied": list(plan.not_copied),
            "cross_references": ({"memories": len({c.id for c in plan.cross_references}),
                                  **({"named": [{"id": c.id, "table": c.table, "keys": c.keys}
                                                for c in plan.cross_references]} if show_cross_references else {})})}


# ---- Reading what would leave ----------------------------------------------------------------------------------

# ---- The request (I 7.1), the manifest (I 7.2) and the owner's lists (R30) ---------------------------------------

REQUEST_KEYS = {
    "kind": None, "version": None, "imprint_id": None, "plan_digest": None, "source_instance_id": None,
    "source_ancestry": None, "source_ancestry_complete": None,
    "scope": {"lanes": None, "layers": None, "since": None, "until": None, "shared_with": None,
              "unsourced_semantics": None},
    "contents": None,                               # table name -> row count; which tables is data, not form
    "others": {"memories": None, "people": None},
    "package": {"bytes": None, "parts": None},
    "terms": {"audience": None, "actions": None, "purposes": None, "days": None},
}

STATION_KEEPS_WORDS = (
    "This goes to the station now, before you say yes. It holds only what your browser will show. No memory leaves "
    "until you allow it. If you decline, or don't answer within 10 minutes, the station deletes the request (at once "
    "when you decline, within an hour when it expires) and keeps a row with its ids, your ship and its times, and no "
    "scope or counts, for 30 days. Its nightly backups keep that row about 8 weeks more. If you allow, the station "
    "keeps the permission, its receipts and that row until 400 days after the copy is deleted (backups about 8 weeks "
    "more). Nothing is kept with no end.")

_HASH_READ = 2**20                  # the package is hashed 1 MiB at a time (I 14)


def request_for(plan: Plan, imprint_id: str, package_bytes: int) -> dict:
    """The request of I 7.1 from a plan: only what the confirm view shows, and no name or memory id."""
    return {
        "kind": "engram-imprint-request", "version": 1, "imprint_id": imprint_id, "plan_digest": plan.digest,
        "source_instance_id": plan.source_id, "source_ancestry": list(plan.ancestry),
        "source_ancestry_complete": bool(plan.ancestry_complete), "scope": scope_of(plan.selection),
        "contents": {t: int(n) for t, n in plan.contents.items()},
        "others": {"memories": int(plan.others["memories"]), "people": int(plan.others["people"])},
        "package": {"bytes": int(package_bytes), "parts": max(1, -(-int(package_bytes) // PART_BYTES))},
        "terms": {"audience": [plan.terms.audience], "actions": sorted(plan.terms.actions),
                  "purposes": sorted(plan.terms.purposes), "days": int(plan.terms.days)}}


def engram_commit_of(checkout: Path | None = None) -> str | None:
    """``git rev-parse HEAD`` in the engram checkout, or None when that fails."""
    import subprocess

    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout or Path(__file__).resolve().parent,
                              capture_output=True, text=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    commit = done.stdout.strip()
    return commit or None


def _package_facts(package: Path, parts: int) -> tuple[str, list[str], int]:
    """``(sha256, part hashes, size)``: part n covers bytes [n*B, min((n+1)*B, size)); reads are 1 MiB."""
    whole = hashlib.sha256()
    hashes = []
    with open(package, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        for n in range(parts):
            part = hashlib.sha256()
            left = max(0, min(PART_BYTES, size - n * PART_BYTES))
            while left:
                chunk = f.read(min(_HASH_READ, left))
                if not chunk:
                    raise OSError("the package is shorter than its size")
                part.update(chunk)
                whole.update(chunk)
                left -= len(chunk)
            hashes.append(part.hexdigest())
        if f.read(1):
            raise OSError("the package grew while it was hashed")
    return whole.hexdigest(), hashes, size


def manifest_for(request: dict, package: Path, *, built_at: int, engram_commit: str | None,
                 source_identity: str = "present") -> dict:
    """The manifest of I 7.2. ``source_identity`` is ``Plan.source_identity`` ("present" or "derived")."""
    from embeddings import NomicEmbedProvider

    conn = _connect(package, read_only=True)
    try:
        applied = [r[0] for r in conn.execute("SELECT version FROM schema_version ORDER BY version")]
        ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'episode_vectors'").fetchone()
        found = re.search(r"float\[(\d+)\]", ddl[0] if ddl else "")
        row = conn.execute("SELECT value FROM episode_vectors_info WHERE key = 'CREATE_VERSION'").fetchone()
    finally:
        conn.close()
    if not found or row is None:
        raise ValueError("the package holds no episode_vectors table to describe")
    parts = request["package"]["parts"]
    sha, hashes, size = _package_facts(Path(package), parts)
    if size != request["package"]["bytes"]:
        raise ValueError("the package is not the size the request named")
    return {
        "kind": "engram-imprint-manifest", "version": 1, "imprint_id": request["imprint_id"], "filter": FILTER,
        "plan_digest": request["plan_digest"], "request_sha256": hashlib.sha256(canonical(request)).hexdigest(),
        "built_at": _instant_text(built_at), "engram_commit": engram_commit,
        "source": {"instance_id": request["source_instance_id"], "identity": source_identity,
                   "ancestry": list(request["source_ancestry"]),
                   "ancestry_complete": request["source_ancestry_complete"]},
        "schema": {"applied": applied},
        "embedding": {"model": NomicEmbedProvider.MODEL_NAME, "dimension": int(found.group(1))},
        "vec": {"create_version": row[0]},
        "scope": request["scope"], "contents": request["contents"], "others": request["others"],
        "package": {"file": "imprint.db", "bytes": size, "sha256": sha, "part_bytes": PART_BYTES, "parts": hashes}}


def render_request(request: dict) -> str:
    """The request in words, then what the station keeps and for how long (I 7.1)."""
    scope, terms, pkg = request["scope"], request["terms"], request["package"]
    since = "the beginning" if scope["since"] is None else scope["since"]
    ancestry = request["source_ancestry"]
    copied = ("copied from " + ", ".join(i[:8] for i in ancestry) if ancestry else "copied from no recorded store")
    lines = [
        f"Imprint request {request['imprint_id'][:4]}",
        f"Source store: {request['source_instance_id'][:8]} ({copied}; "
        f"{'lineage complete' if request['source_ancestry_complete'] else 'lineage incomplete'})",
        f"Scope: lanes {', '.join(scope['lanes'])}; layers {', '.join(scope['layers'])}; from {since} "
        f"until {scope['until']}" + (f"; shared with {scope['shared_with']}" if scope["shared_with"] else "")
        + ("; semantic memories with no source included" if scope["unsourced_semantics"] else ""),
        "Rows: " + ", ".join(f"{t} {n}" for t, n in request["contents"].items()),
        f"Other people: {_n(request['others']['memories'], 'memory', 'memories')} with other people recorded on "
        f"them ({_n(request['others']['people'], 'person', 'people')})",
        f"Package: {pkg['bytes']} bytes in {_n(pkg['parts'], 'part', 'parts')}",
        f"Terms: for {', '.join(terms['audience'])}; actions {', '.join(terms['actions'])}; purposes "
        f"{', '.join(terms['purposes'])}; {terms['days']} days",
        f"Plan digest: {request['plan_digest'][:8]} (the whole 64-character digest is sent)",
        "", STATION_KEEPS_WORDS]
    return "\n".join(lines) + "\n"


def objects_for(rows: PackageRows, source_id: str) -> Iterator[str]:
    """The sorted ``mem:`` ref of every memory that ships: ``objects.json``."""
    yield from rows.shipped.refs(source_id)


def subjects_for(rows: PackageRows, source_id: str) -> Iterator[list[str]]:
    """The sorted ``[ref, subject]`` pairs of ``imprint_subjects``: ``subjects.json``. The rows come sorted by id and
    then layer; refs sort by layer first, so one pass for each layer (the same prefix keeps ids in order)."""
    for layer in ("episode", "semantic"):
        for row in rows.rows["imprint_subjects"]:
            if row["layer"] == layer:
                yield [f"mem:{source_id}/{layer}/{row['memory_id']}", row["subject"]]


def _write_json_lines(path: Path, items: Iterable) -> None:
    """A JSON array, one element per line, ``[`` and ``]`` on lines of their own (R30)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("[\n")
        last = None
        for item in items:
            if last is not None:
                f.write(last + ",\n")
            last = json.dumps(item, ensure_ascii=True)
        if last is not None:
            f.write(last + "\n")
        f.write("]\n")


def write_owner_lists(dir: Path, rows: PackageRows, source_id: str) -> None:
    """``objects.json`` and ``subjects.json`` in ``dir``, written as the rows are read (R30)."""
    dir = Path(dir)
    dir.mkdir(parents=True, exist_ok=True)
    _write_json_lines(dir / "objects.json", objects_for(rows, source_id))
    _write_json_lines(dir / "subjects.json", subjects_for(rows, source_id))


_CHANGED = "Your store changed since the plan. Run the plan again."


def resolve_plan(home: Path, prefix: str) -> Path:
    """The saved plan a unique prefix of at least 4 characters names (R6)."""
    prefix = (prefix or "").strip().lower()
    if len(prefix) < 4 or not all(c in "0123456789abcdef" for c in prefix):
        raise PlanRefused("Name a plan by at least its first 4 characters, as the dry run showed them.")
    found = sorted(plans_dir(home).glob(f"{prefix}*.json"))
    if not found:
        raise PlanRefused(f"There is no plan {prefix}. Run the plan again.")
    if len(found) > 1:
        raise PlanRefused(f"More than one plan starts with {prefix}; give more of its characters.")
    return found[0]


def _saved_plan(path: Path) -> dict:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        scope, terms = saved["scope"], saved["terms"]
        for key in ("id", "store", "source_id", "owner", "digest"):
            if not isinstance(saved[key], str):
                raise ValueError(key)
        int(saved["created"])
        Terms(audience=terms["audience"], actions=frozenset(terms["actions"]),
              purposes=frozenset(terms["purposes"]), days=int(terms["days"]))
        scope["lanes"], scope["layers"], scope["until"]
    except (OSError, ValueError, KeyError, TypeError):
        raise PlanRefused("The saved plan can't be read. Run the plan again.") from None
    return saved


def _selection_of(saved: dict) -> tuple[Selection, Terms]:
    scope, t = saved["scope"], saved["terms"]
    sel = parse_selection(lanes=",".join(scope["lanes"]), layers=",".join(scope["layers"]), since=scope.get("since"),
                          until=scope["until"], shared_with=scope.get("shared_with"), exclude_file=None,
                          unsourced=bool(scope.get("unsourced_semantics")), now=int(saved["created"]))
    sel = replace(sel, exclude=frozenset(saved.get("exclude") or ()))
    return sel, Terms(audience=t["audience"], actions=frozenset(t["actions"]), purposes=frozenset(t["purposes"]),
                      days=int(t["days"]))


def _semantic_rows_in_order(conn: sqlite3.Connection, pr: PackageRows) -> Iterator[dict]:
    """The shipped semantics as the package will hold them (``contradicted_by`` null when it names a semantic
    outside S), in ``(created_at, id)`` order."""
    return iter(sorted(semantic_rows(conn, pr.shipped), key=lambda r: (r["created_at"], r["id"])))


def read_plan(plan_id: str, *, home: Path, start: int = 0, limit: int = 1, engram_home: Path | None = None,
              scratch_dir: Path | None = None) -> list[dict]:
    """A page of what would leave, every memory in ``(created_at, id)`` order, episodes and semantics together.
    It takes a new snapshot, rebuilds the package rows the plan was made from and refuses unless the digest is the
    plan's. Episodes are read by ``store_reader.read_episodes`` and shown with the ``session_id`` the package holds;
    ``position`` is the place in this reading. ``engram_home`` names the machine's permissions ledger, as
    ``plan`` was told."""
    home = Path(home)
    if start < 0 or limit < 1:
        raise PlanRefused("--start can't be negative and --limit must be at least 1.")
    saved = _saved_plan(resolve_plan(home, plan_id))
    sel, terms = _selection_of(saved)
    store, owner, now = Path(saved["store"]), saved["owner"], int(saved["created"])
    engram_home = _default_engram_home() if engram_home is None else Path(engram_home)
    work = _new_scratch(home) if scratch_dir is None else Path(scratch_dir)
    scratch = conn = ledger = None
    try:
        if not store.is_file():
            raise PlanRefused(_CHANGED)
        ledger = open_ledger(engram_home)
        try:
            source_id, _, _, _, _, working = _working_copy(store, work, engram_home=engram_home, home=home,
                                                          ledger=ledger, owner=owner,
                                                          expected_id=saved["source_id"], wrong_id=_CHANGED)
        except sqlite3.Error:
            raise PlanRefused(_CHANGED) from None
        from imprint_filter import SourceContext

        scratch = Scratch(work / "scratch.db")
        published = published_house_path(engram_home)
        ctx = SourceContext(source_path=store, source_id=source_id, instance_name=_instance_name(store), owner=owner,
                            published=published if published.is_file() else None, ledger=ledger,
                            home=bool(saved.get("home")), scratch=scratch, terms=terms, now=now)
        conn = _connect(working, read_only=True, vec=True)
        conn.row_factory = sqlite3.Row
        pr = package_rows(conn, sel, terms, ctx)
        if plan_digest(scope_of(sel), pr.rows, scratch=scratch) != saved["digest"]:
            raise PlanRefused(_CHANGED)
        episodes = ((r["created_at"], r["id"], 0, r) for r in pr.rows["episodes"])
        semantics = ((r["created_at"], r["id"], 1, r) for r in _semantic_rows_in_order(conn, pr))
        merged = heapq.merge(episodes, semantics, key=lambda t: t[:3])
        page = []
        for i, (at, id, layer, row) in enumerate(itertools.islice(merged, start, start + limit), start=start):
            if layer == 0:
                before = conn.execute("SELECT COUNT(*) FROM episodes WHERE created_at < ? OR (created_at = ? AND id < ?)",
                                      (at, at, id)).fetchone()[0]
                memory, = store_reader.read_episodes(conn, start=before, limit=1)
                memory["session_id"] = row["session_id"]
                memory["layer"] = "episode"
            else:
                memory = dict(row, layer="semantic")
            memory["position"] = i
            page.append(memory)
        return page
    finally:
        if conn is not None:
            conn.close()
        if scratch is not None:
            scratch.close()
        if ledger is not None:
            ledger.conn.close()
        _remove_work(work, whole=scratch_dir is None)


# ---- Building the package (I 6.1) ------------------------------------------------------------------------------

class PlanBusy(PlanRefused):
    """Another ``build`` of this plan holds its lock (RF5)."""


@dataclass(frozen=True)
class Built:
    imprint_id: str
    dir: Path
    request: dict
    manifest: dict
    fresh: bool = True              # False when ``--if-needed`` found the plan already built


_BUSY = "Another make imprint-send of this plan is running."


def _lock_plan(plan_path: Path) -> int:
    """An exclusive, non-blocking ``flock`` on ``<plan id>.lock`` beside the plan file; the caller closes the fd."""
    fd = os.open(plan_path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise PlanBusy(_BUSY) from None
    except BaseException:
        os.close(fd)
        raise
    return fd


def _built_of(home: Path, imprint_id: str) -> Built:
    dir = Path(home) / "imprints" / imprint_id
    try:
        request = json.loads((dir / "request.json").read_text(encoding="utf-8"))
        manifest = json.loads((dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise PlanRefused(f"The imprint {imprint_id[:4]} this plan made is gone. Run the plan again.") from None
    return Built(imprint_id, dir, request, manifest, fresh=False)


def _write_bytes_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def _vector_hashes(pr: PackageRows, scratch: Scratch) -> dict:
    """``{"episode_vectors": {id: sha256}, "semantic_vectors": ...}``: the source's embedding bytes hashed into
    ``ScratchMap``s in the scratch file (R26), which L3 looks up one chunk's ids at a time."""
    expected = {}
    for layer in ("episode", "semantic"):
        table = f"{layer}_vectors"
        hashes = ScratchMap(scratch)
        scratch.conn.execute("BEGIN")
        try:
            for row in pr.rows[table]:
                hashes[row["id"]] = hashlib.sha256(row["embedding"]).hexdigest()
        finally:
            scratch.conn.execute("COMMIT")
        expected[table] = hashes
    return expected


def _leak_checks(package: Path, x_star, pr: PackageRows, scratch: Scratch, work: Path) -> list[str]:
    """L1 to L4 on the finished package (I 6.4)."""
    expected = _vector_hashes(pr, scratch)
    l2_dir = work / "l2"
    conn = _connect(package, read_only=True, immutable=True, vec=True)
    try:
        return l1_values(conn, x_star) + l2_fts(conn, l2_dir) + l3_vec0(conn, expected) + l4_raw(package, x_star)
    finally:
        conn.close()
        shutil.rmtree(l2_dir, ignore_errors=True)


def _cross_reference_refusal(crossed) -> str:
    n = len({c.id for c in crossed})
    return (f"{_n(n, 'memory', 'memories')} in this plan: the text of each names something staying here. "
            "See them with --show-cross-references, then leave them out with --exclude FILE and plan again.")


def _build_one(saved: dict, *, home: Path, now: int, engram_home: Path, work: Path) -> Built:
    """I 6.1 steps 1 to 10 for a plan nobody has built. A failure removes the half-made imprint directory."""
    from imprint_filter import SourceContext

    sel, terms = _selection_of(saved)
    store, owner, created = Path(saved["store"]), saved["owner"], int(saved["created"])
    imprint_id = str(uuid.uuid4())
    dest = home / "imprints" / imprint_id
    scratch = conn = ledger = cold_conn = None
    made = False
    try:
        if not store.is_file():
            raise PlanRefused(_CHANGED)
        ledger = open_ledger(engram_home)
        try:
            source_id, identity, ancestry, complete, _, working = _working_copy(
                store, work, engram_home=engram_home, home=home, ledger=ledger, owner=owner,
                expected_id=saved["source_id"], wrong_id=_CHANGED)
        except sqlite3.Error:
            raise PlanRefused(_CHANGED) from None
        scratch = Scratch(work / "scratch.db")
        published = published_house_path(engram_home)
        ctx = SourceContext(source_path=store, source_id=source_id, instance_name=_instance_name(store), owner=owner,
                            published=published if published.is_file() else None, ledger=ledger,
                            home=bool(saved.get("home")), scratch=scratch, terms=terms, now=created)
        conn = _connect(working, read_only=True, vec=True)
        conn.row_factory = sqlite3.Row
        pr = package_rows(conn, sel, terms, ctx)                      # the one reading of the rows (step 1)
        digest = plan_digest(scope_of(sel), pr.rows, scratch=scratch)
        if digest != saved["digest"]:
            raise PlanRefused(_CHANGED)
        cold = store.with_name("cold.db")
        cold_conn = store_reader.connect(cold, immutable=True) if cold.is_file() else None
        x_star = left_out_keys(conn, cold_conn, pr, scratch=scratch)
        crossed = cross_references(pr, x_star)
        if crossed:                                                    # step 2
            raise PlanRefused(_cross_reference_refusal(crossed))
        dest.mkdir(mode=0o700)                                         # step 3
        made = True
        dest.chmod(0o700)
        package = dest / "imprint.db"
        write_package(pr, package, source_id=source_id, source_ancestry=ancestry, source_complete=complete,
                      imprint_id=imprint_id)                           # steps 4 to 7
        failures = _leak_checks(package, x_star, pr, scratch, work)    # step 8
        if failures:
            raise PlanRefused("The package failed its leak checks, so nothing was kept: " + "; ".join(failures[:5]))
        size = package.stat().st_size
        plan = Plan(
            id=saved["id"], created=created, store=store, source_id=source_id,
            source_identity="present" if identity["status"] == "present" else "derived", ancestry=tuple(ancestry),
            ancestry_complete=bool(complete), selection=sel, terms=terms, digest=digest,
            counts=saved.get("counts") or {}, contents=contents_of(pr.rows), package_bytes=size,
            parts=max(1, -(-size // PART_BYTES)), others=pr.others, home=bool(saved.get("home")), people={},
            origin=identity.get("instance_id_origin"), not_copied=(), owner=owner)
        request = request_for(plan, imprint_id, size)
        manifest = manifest_for(request, package, built_at=now, engram_commit=engram_commit_of(),
                                source_identity=plan.source_identity)
        _write_bytes_private(dest / "request.json", canonical(request))
        _write_bytes_private(dest / "manifest.json", canonical(manifest))
        write_owner_lists(dest, pr, source_id)
        package.chmod(0o400)                                           # step 9
        return Built(imprint_id, dest, request, manifest)
    except BaseException:
        if made:
            shutil.rmtree(dest, ignore_errors=True)
        raise
    finally:
        for c in (conn, cold_conn):
            if c is not None:
                c.close()
        if scratch is not None:
            scratch.close()
        if ledger is not None:
            ledger.conn.close()


def build(plan_id: str, *, home: Path, now: int, if_needed: bool = False, engram_home: Path | None = None,
          scratch_dir: Path | None = None) -> Built:
    """``imprint.py build`` (I 6.1). It holds the plan's lock from before it reads the plan file until the plan file
    names the imprint (RF5). With ``if_needed`` a plan already built returns its ``Built``; without, it is refused.
    ``scratch_dir`` is the 0700 directory the caller made and removes; without it one is made and removed here.
    ``now`` is the build's time (``built_at``); the rows are read as of the plan's own time."""
    home = Path(home)
    engram_home = _default_engram_home() if engram_home is None else Path(engram_home)
    path = resolve_plan(home, plan_id)
    fd = _lock_plan(path)
    work = None
    try:
        saved = _saved_plan(path)
        if saved.get("imprint_id"):
            if if_needed:
                return _built_of(home, saved["imprint_id"])
            raise PlanRefused(f"This plan was already built as imprint {saved['imprint_id'][:4]}; "
                              "send it, or run the plan again.")
        work = _new_scratch(home) if scratch_dir is None else Path(scratch_dir)
        built = _build_one(saved, home=home, now=int(now), engram_home=engram_home, work=work)
        try:
            _write_private(path, json.dumps(dict(saved, imprint_id=built.imprint_id), indent=2, sort_keys=True) + "\n")
        except BaseException:
            shutil.rmtree(built.dir, ignore_errors=True)
            raise
        return built
    finally:
        if work is not None:
            _remove_work(work, whole=scratch_dir is None)
        os.close(fd)


# ---- The command ---------------------------------------------------------------------------------------------

def ensure_scratch_env(scratch: Path, *, environ, execve) -> None:
    """R26: SQLite reads ``SQLITE_TMPDIR`` and ``TMPDIR`` once, when ``sqlite3`` is imported, so the process starts
    again with the three variables naming ``scratch`` unless they already do. Every subcommand that opens SQLite
    calls this first."""
    value = str(scratch)
    keys = ("SQLITE_TMPDIR", "TMPDIR", "IMPRINT_SCRATCH")
    if all(environ.get(k) == value for k in keys):
        return
    env = dict(environ)
    env.update({k: value for k in keys})
    execve(sys.executable, [sys.executable, *sys.orig_argv[1:]], env)


def _run_scratch(home: Path) -> Path:
    """The directory the re-executed process was given (a 0700 directory directly under the plans directory), else
    a new one."""
    named = os.environ.get("IMPRINT_SCRATCH")
    plans = plans_dir(home)
    if named:
        path = Path(named)
        if path.is_dir() and path.resolve().parent == plans.resolve() and path.stat().st_uid == os.getuid():
            return path
    return _new_scratch(home)


def _project_root(flag: str | None) -> Path:
    return Path(flag or os.environ.get("ENGRAM_PROJECT_ROOT") or os.getcwd())


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="imprint.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan", help="choose what would leave and show it; nothing leaves this machine")
    p.add_argument("--store", type=Path, help="the store to copy; use it when unsure")
    p.add_argument("--project-root", help="where the engram server would run (default $ENGRAM_PROJECT_ROOT, else here)")
    p.add_argument("--lanes", help="personal, work or both, comma separated")
    p.add_argument("--layers", help="episode, semantic or both, comma separated")
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--shared-with")
    p.add_argument("--exclude", type=Path, metavar="FILE", help="a file of memory ids, one a line, to leave out")
    p.add_argument("--include-unsourced-semantics", action="store_true")
    p.add_argument("--audience", help="place:home/<the operator the station named>")
    p.add_argument("--actions", default="imprint", help="imprint, or imprint,route")
    p.add_argument("--purposes", help="calibration, or calibration,trail-evaluation with route")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    p.add_argument("--list", type=Path, metavar="FILE", help="write one JSON line per row that would leave")
    p.add_argument("--json", action="store_true", help="print the dry run as JSON")
    p.add_argument("--show-cross-references", action="store_true",
                   help="list each memory whose text names something that stays here, and the table of that key")
    p.add_argument("--superyak-home", type=Path, default=Path.home() / ".superyak")
    p.add_argument("--engram-home", type=Path)
    r = sub.add_parser("read", help="page through what a plan would send, one JSON line a memory")
    r.add_argument("--plan", required=True, help="the plan's first 4 or more characters")
    r.add_argument("--start", type=int, default=0)
    r.add_argument("--limit", type=int, default=1)
    r.add_argument("--superyak-home", type=Path, default=Path.home() / ".superyak")
    r.add_argument("--engram-home", type=Path)
    b = sub.add_parser("build", help="build the package of a plan, check it and write its request and manifest")
    b.add_argument("--plan", required=True, help="the plan's first 4 or more characters")
    b.add_argument("--if-needed", action="store_true", help="a plan already built prints nothing and succeeds")
    b.add_argument("--superyak-home", type=Path, default=Path.home() / ".superyak")
    b.add_argument("--engram-home", type=Path)
    return ap


def _identity_of(store: Path) -> tuple[str, str]:
    """The source's effective id and instance name, from a read-only look that writes nothing."""
    if not Path(store).is_file():
        raise PlanRefused(f"There is no store at {store}; nothing was planned.")
    try:
        conn = store_reader.connect(store)
    except sqlite3.Error:
        raise PlanRefused(f"{store} can't be opened as a store; nothing was planned.") from None
    try:
        source_id = store_identity.effective_id(conn)
    except sqlite3.Error:
        raise PlanRefused(f"{store} is not an engram store; nothing was planned.") from None
    finally:
        conn.close()
    if source_id is None:
        raise PlanRefused("The source store has no identity this code can derive; nothing was planned.")
    return source_id, _instance_name(store)


def _instance_name(store: Path) -> str:
    here = Path(store).resolve()
    return here.parent.name if here.parent.parent.name == "instances" else "default"


def _plan(args, *, clock) -> int:
    from imprint_filter import SourceContext

    home = Path(args.superyak_home)
    engram_home = Path(args.engram_home) if args.engram_home else _default_engram_home()
    now = int(clock())
    context = read_context(home)
    purposes = args.purposes or ("calibration,trail-evaluation" if "route" in (args.actions or "") else "calibration")
    terms = parse_terms(audience=args.audience, actions=args.actions, purposes=purposes, days=args.days,
                        operator=context.operator)
    sel = parse_selection(lanes=args.lanes, layers=args.layers, since=args.since, until=args.until,
                          shared_with=args.shared_with, exclude_file=args.exclude,
                          unsourced=args.include_unsourced_semantics, now=now)
    store = resolve_store(args.store, engram_home=engram_home, project_root=_project_root(args.project_root))
    source_id, instance_name = _identity_of(store)          # nothing is written yet
    scratch = _run_scratch(home)
    try:
        ensure_scratch_env(scratch, environ=os.environ, execve=os.execve)
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
    ledger = None
    try:
        ledger = open_ledger(engram_home)
        published = published_house_path(engram_home)
        ctx = SourceContext(
            source_path=store, source_id=source_id, instance_name=instance_name, owner=context.owner,
            published=published if published.is_file() else None, ledger=ledger,
            home=terms.audience == f"place:home/{context.owner}", scratch=None, terms=terms, now=now)
        plan = make_plan(store, sel, terms, ctx, context, home, now, scratch_dir=scratch, engram_home=engram_home,
                         list_to=args.list)
    finally:
        if ledger is not None:
            ledger.conn.close()
        shutil.rmtree(scratch, ignore_errors=True)
    show = args.show_cross_references
    print(json.dumps(plan_dict(plan, show_cross_references=show), indent=2, sort_keys=True) if args.json
          else render_dry_run(plan, context, show_cross_references=show),
          end="\n" if args.json else "")
    return 0


def _read(args) -> int:
    home = Path(args.superyak_home)
    engram_home = Path(args.engram_home) if args.engram_home else _default_engram_home()
    resolve_plan(home, args.plan)                       # a bad name is refused before anything runs
    scratch = _run_scratch(home)
    try:
        ensure_scratch_env(scratch, environ=os.environ, execve=os.execve)
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
    try:
        page = read_plan(args.plan, home=home, start=args.start, limit=args.limit, engram_home=engram_home,
                         scratch_dir=scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    for memory in page:
        print(json.dumps(memory, sort_keys=True))
    return 0


def _build(args, *, clock) -> int:
    home = Path(args.superyak_home)
    engram_home = Path(args.engram_home) if args.engram_home else _default_engram_home()
    resolve_plan(home, args.plan)                       # a bad name is refused before anything runs
    scratch = _run_scratch(home)
    try:
        ensure_scratch_env(scratch, environ=os.environ, execve=os.execve)
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
    try:
        built = build(args.plan, home=home, now=int(clock()), if_needed=args.if_needed, engram_home=engram_home,
                      scratch_dir=scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if built.fresh:
        print(render_request(built.request), end="")
    return 0


def published_house_path(engram_home: Path) -> Path:
    from imprint_filter import published_house

    return published_house(engram_home)


def main(argv: list[str] | None = None, *, clock=time.time) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            return _plan(args, clock=clock)
        if args.command == "read":
            return _read(args)
        if args.command == "build":
            return _build(args, clock=clock)
    except PlanBusy as busy:
        print(str(busy), file=sys.stderr)
        return 4
    except PlanRefused as refusal:
        print(str(refusal), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
