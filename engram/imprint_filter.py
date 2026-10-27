"""Which tables an imprint copies, and how (store-copy spec I 6.2, D4).

Deny by default: a table with no rule here is not copied, and a package table with no rule stops the build.
Rules: ``filtered`` (some rows copy), ``dropped`` (no row copies; a migration's table exists empty, a hook-only
table is absent), ``rebuilt`` (SQLite, a trigger or the migrations fill it), ``built`` (only the build creates it)
and ``never`` (not copied, not created).
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, NamedTuple

import sharing
import store_reader
from lighthouse_protocol import content_digest

# Every table of I 6.2, in its order.
TABLE_RULES: dict[str, str] = {
    "episodes": "filtered",                 # the memories chosen; session_id scrubbed without route (D7)
    "semantics": "filtered",                # rows in S; contradicted_by outside S set to null
    "instincts": "dropped",                 # instincts never leave (permissions spec 5.2)
    "episode_vectors": "filtered",          # id in E; bytes as stored, no embedder needed
    "semantic_vectors": "filtered",         # id in S
    "instinct_vectors": "dropped",          # instincts
    "instinct_context_vectors": "dropped",  # instincts
    "entity_vectors": "dropped",            # code index
    "residue_vectors": "dropped",           # dream residue
    "episode_fts": "rebuilt",               # external-content index; the insert triggers fill it
    "semantic_fts": "rebuilt",              # same
    "entity_fts": "rebuilt",                # entities dropped, so empty
    "semantic_sources": "filtered",         # semantic in S and episode in E
    "instinct_sources": "dropped",          # instincts
    "instinct_co_firing": "dropped",        # instincts
    "resonances": "filtered",               # both ends in M, created_at in [t0, t1)
    "semantic_peers": "filtered",           # peer_id and parent_id in S
    "subdivision_events": "filtered",       # parent_id and every peer id in S
    "imprint_subjects": "built",            # the co-subjects a shipped memory keeps; only the build creates it (D43)
    "entities": "dropped",                  # the code index of the repository the server ran in
    "relationships": "dropped",             # same
    "episode_entities": "dropped",          # same
    "memory_log": "filtered",               # only with route (D7); recall and route_shown rows, scrubbed
    "operation_log": "filtered",            # only with route (D7); CITING_OPERATIONS rows, scrubbed
    "session_registry": "dropped",          # harness, model and repo provenance
    "session_bindings": "dropped",          # runtime-only
    "persistence_scores": "dropped",        # a cache; calibration recomputes
    "subdivision_queue": "dropped",         # maintenance queue
    "instinct_context_feedback": "dropped", # free text about what the person was doing, with no lane
    "instinct_clusters": "dropped",         # instincts
    "instinct_cluster_members": "dropped",  # instincts
    "lens_cluster_affinity": "dropped",     # reserved, unused
    "session_bias": "dropped",              # per-session tilt (011_session_bias.sql, hooks/nudge.py)
    "context_threads": "dropped",           # made in graph.db by the hooks
    "context_prev_embedding": "dropped",    # holds the person's last prompt
    "nudge_co_fire_window": "dropped",      # hook table
    "nudge_surfaced": "dropped",            # hook table
    "residue": "dropped",                   # reaction holds raw text
    "task_contexts": "dropped",             # working plans, no lane
    "anchors": "dropped",                   # identity anchors
    "drift_reports": "dropped",             # drift summaries
    "assessments": "dropped",               # self-reports
    "shared_memories": "dropped",           # records copies made for other audiences
    "shared_memories_changes": "rebuilt",   # 029 seeds its one counter row (id 1, count 0); not copied, so not empty (check 9 skips it)
    "schema_version": "rebuilt",            # the migrations that create the package
    "meta": "rebuilt",                      # only the imprint's identity keys (section 11)
    "sqlite_sequence": "rebuilt",           # the vec0 inserts fill it; never copied
    "sqlite_stat1": "never",                # the build runs no ANALYZE
    "sqlite_stat2": "never",
    "sqlite_stat3": "never",
    "sqlite_stat4": "never",
}

# Made in graph.db by the hooks, so absent from a package. session_bias is a migration table.
HOOK_TABLES = ("context_threads", "context_prev_embedding", "nudge_co_fire_window", "nudge_surfaced")

# The eleven tables of I 5.4, in its order.
DIGEST_TABLES = ("episodes", "semantics", "episode_vectors", "semantic_vectors", "semantic_sources", "resonances",
                 "semantic_peers", "subdivision_events", "memory_log", "operation_log", "imprint_subjects")

# A copy of hooks/sleep.py's tuple (a test compares them), so no hook module is imported.
CITING_OPERATIONS = ("mark_core", "instinct_feedback", "dream_react")


class UnclassifiedTable(RuntimeError):
    """A package table has no rule: a bug in this code (D4)."""


class SourceTables(NamedTuple):
    copied: tuple[str, ...]     # rule filtered, in TABLE_RULES order
    dropped: tuple[str, ...]    # rule dropped, in TABLE_RULES order
    unnamed: tuple[str, ...]    # no rule and not a shadow: not copied, named by the dry run, sorted


def is_shadow(name: str, virtual: Iterable[str]) -> bool:
    """A table whose name starts with a virtual table's name and `_` is its shadow."""
    return any(name.startswith(v + "_") for v in virtual)


def _tables(conn: sqlite3.Connection) -> tuple[list[str], list[str]]:
    rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'").fetchall()
    names = [r[0] for r in rows]
    virtual = [r[0] for r in rows if (r[1] or "").lstrip().upper().startswith("CREATE VIRTUAL TABLE")]
    return names, virtual


def classify_source(conn: sqlite3.Connection) -> SourceTables:
    names, virtual = _tables(conn)
    present = set(names)
    return SourceTables(
        copied=tuple(t for t, r in TABLE_RULES.items() if r == "filtered" and t in present),
        dropped=tuple(t for t, r in TABLE_RULES.items() if r == "dropped" and t in present),
        unnamed=tuple(sorted(n for n in names if n not in TABLE_RULES and not is_shadow(n, virtual))))


def check_package_tables(conn: sqlite3.Connection) -> None:
    """D4: a package table with no rule stops the build."""
    missing = classify_source(conn).unnamed
    if missing:
        raise UnclassifiedTable("no imprint rule for table(s): " + ", ".join(missing))


# ---- The scratch file (R26) --------------------------------------------------------------------------------

class Scratch:
    """A SQLite file on disk that holds the id collections which grow with the store (R26).

    Temporary tables and sorts go to files (``temp_store = FILE``); there is no rollback journal. The directory
    reaches SQLite's temporary files only through the environment at start (``ensure_scratch_env``, Task 15).
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path), isolation_level=None)
        self.conn.execute("PRAGMA temp_store = FILE")
        self.conn.execute("PRAGMA journal_mode = OFF")
        self.conn.execute("PRAGMA synchronous = OFF")
        self._tables = 0

    def new_table(self, ddl: str) -> str:
        """Create a table of this file from ``ddl`` (which holds ``{t}``) and return its name."""
        self._tables += 1
        name = f"t{self._tables}"
        self.conn.execute(ddl.format(t=name))
        return name

    def close(self) -> None:
        self.conn.close()


class IdSet:
    """A set of ids in a scratch table: ``in``, ``len`` and iteration in insertion order."""

    def __init__(self, scratch: Scratch):
        self._conn = scratch.conn
        self._t = scratch.new_table("CREATE TABLE {t} (id TEXT PRIMARY KEY, n INTEGER NOT NULL) WITHOUT ROWID")
        self._i = scratch.new_table("CREATE TABLE {t} (n INTEGER PRIMARY KEY, id TEXT NOT NULL)")

    def add(self, id: str) -> None:
        if id in self:
            return
        cur = self._conn.execute(f"INSERT INTO {self._i} (id) VALUES (?)", (id,))
        self._conn.execute(f"INSERT INTO {self._t} (id, n) VALUES (?, ?)", (id, cur.lastrowid))

    def __contains__(self, id: object) -> bool:
        return self._conn.execute(f"SELECT 1 FROM {self._t} WHERE id = ?", (id,)).fetchone() is not None

    def __len__(self) -> int:
        return self._conn.execute(f"SELECT COUNT(*) FROM {self._t}").fetchone()[0]

    def __iter__(self) -> Iterator[str]:
        cur = self._conn.cursor()
        for (id,) in cur.execute(f"SELECT id FROM {self._i} ORDER BY n"):
            yield id


class ScratchMap(MutableMapping):
    """A keyed table in a scratch file with the ``Mapping`` protocol; values are JSON, keys are text."""

    def __init__(self, scratch: Scratch):
        self._conn = scratch.conn
        self._t = scratch.new_table("CREATE TABLE {t} (n INTEGER PRIMARY KEY, k TEXT NOT NULL UNIQUE, v TEXT NOT NULL)")

    def __setitem__(self, key: str, value: Any) -> None:
        self._conn.execute(
            f"INSERT INTO {self._t} (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (key, json.dumps(value)))

    def __getitem__(self, key: str) -> Any:
        row = self._conn.execute(f"SELECT v FROM {self._t} WHERE k = ?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    def __delitem__(self, key: str) -> None:
        if self._conn.execute(f"DELETE FROM {self._t} WHERE k = ?", (key,)).rowcount == 0:
            raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        cur = self._conn.cursor()
        for (k,) in cur.execute(f"SELECT k FROM {self._t} ORDER BY n"):
            yield k

    def __len__(self) -> int:
        return self._conn.execute(f"SELECT COUNT(*) FROM {self._t}").fetchone()[0]


# ---- The selection (I 5.2) and the terms (I 5.3) ------------------------------------------------------------

LANES = frozenset({"personal", "work"})
LAYERS = frozenset({"episode", "semantic"})
OPERATOR_RE = re.compile(r"[a-z][a-z0-9-]{0,62}")


class PlanRefused(ValueError):
    """The owner's flags or the source can't make a plan; nothing was planned."""


def parse_instant(text: str | None) -> datetime | None:
    """An ISO-8601 date or time as an aware UTC datetime; a value with no zone is UTC; None when it won't parse."""
    if not isinstance(text, str):
        return None
    try:
        at = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    return at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at.astimezone(timezone.utc)


@dataclass(frozen=True)
class Selection:
    lanes: frozenset[str]
    layers: frozenset[str]
    since: int | None           # t0, integer UTC seconds, or None for -infinity
    until: int                  # t1; the window is [t0, t1)
    shared_with: str | None
    exclude: frozenset[str]
    unsourced: bool


def _choice(name: str, text: str | None, allowed: frozenset[str]) -> frozenset[str]:
    chosen = frozenset(p.strip() for p in (text or "").split(",") if p.strip())
    if not chosen:
        raise PlanRefused(f"--{name} is required: choose from {', '.join(sorted(allowed))}.")
    if not chosen <= allowed:
        raise PlanRefused(f"--{name} holds {', '.join(sorted(chosen - allowed))}; choose from "
                          f"{', '.join(sorted(allowed))}.")
    return chosen


def _seconds(flag: str, text: str) -> int:
    at = parse_instant(text)
    if at is None:
        raise PlanRefused(f"--{flag} {text!r} is not an ISO-8601 date or time.")
    return int(at.timestamp() // 1)


def parse_selection(*, lanes: str | None, layers: str | None, since: str | None, until: str | None,
                    shared_with: str | None, exclude_file: str | Path | None, unsourced: bool,
                    now: int) -> Selection:
    chosen_lanes = _choice("lanes", lanes, LANES)
    chosen_layers = _choice("layers", layers, LAYERS)
    t0 = None if since is None else _seconds("since", since)
    t1 = now if until is None else _seconds("until", until)
    if shared_with is not None:
        try:
            sharing.validate_audience(shared_with)
        except (TypeError, ValueError):
            raise PlanRefused(f"--shared-with {shared_with!r} is not an audience.") from None
    exclude: frozenset[str] = frozenset()
    if exclude_file is not None:
        try:
            lines = Path(exclude_file).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise PlanRefused(f"--exclude file can't be read: {exc}") from None
        exclude = frozenset(line.strip() for line in lines if line.strip())
    return Selection(lanes=chosen_lanes, layers=chosen_layers, since=t0, until=t1, shared_with=shared_with,
                     exclude=exclude, unsourced=bool(unsourced))


@dataclass(frozen=True)
class Terms:
    audience: str
    actions: frozenset[str]
    purposes: frozenset[str]
    days: int

    @property
    def route(self) -> bool:
        return "route" in self.actions


def parse_terms(*, audience: str, actions: str, purposes: str, days: int, operator: str) -> Terms:
    """Step 1 accepts only the values whose meaning I 5.3 fixes."""
    if not isinstance(operator, str) or not OPERATOR_RE.fullmatch(operator):
        raise PlanRefused("The operator's name must fit [a-z][a-z0-9-]{0,62} to be a home place in step 1.")
    if audience != f"place:home/{operator}":
        raise PlanRefused(f"--audience must be exactly place:home/{operator} in step 1.")
    acts = frozenset(p.strip() for p in (actions or "").split(",") if p.strip())
    if acts not in (frozenset({"imprint"}), frozenset({"imprint", "route"})):
        raise PlanRefused("--actions must be imprint, or imprint,route, in step 1.")
    purps = frozenset(p.strip() for p in (purposes or "").split(",") if p.strip())
    want = frozenset({"calibration", "trail-evaluation"}) if "route" in acts else frozenset({"calibration"})
    if purps != want:
        raise PlanRefused("--purposes must be " + ",".join(sorted(want)) + " for these actions.")
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
        raise PlanRefused("--days must be a whole number from 1 to 365.")
    return Terms(audience=audience, actions=acts, purposes=purps, days=days)


@dataclass(frozen=True)
class SourceContext:
    source_path: Path
    source_id: str
    instance_name: str
    owner: str
    published: Path | None
    ledger: object | None
    home: bool                  # the audience is place:home/<owner> (I 5.2)
    scratch: Scratch


class _House:
    """The slice of ``Storage`` that ``sharing.audiences_for`` reads, over a read-only connection."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _get(self, table: str, id: str) -> dict | None:
        row = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (id,)).fetchone()
        return None if row is None else dict(row)

    def get_episode(self, id: str) -> dict | None:
        return self._get("episodes", id)

    def get_semantic(self, id: str) -> dict | None:
        return self._get("semantics", id)


def shared(published_conn: sqlite3.Connection, row: dict, layer: str, ctx: SourceContext, audience: str) -> bool:
    """I 5.2's shared(m, A). ``published_conn`` needs ``sqlite3.Row`` rows (``store_reader.connect`` gives them)."""
    columns = {r[1] for r in published_conn.execute("PRAGMA table_info(shared_memories)")}
    if "source_instance_id" in columns:
        if not ctx.source_id:
            return False
        who, key = "source_instance_id", ctx.source_id
    else:
        who, key = "source_instance", ctx.instance_name
    candidates = published_conn.execute(
        f"SELECT memory_id, content_digest FROM shared_memories "
        f"WHERE {who} = ? AND source_id = ? AND layer = ? AND audience = ?",
        (key, row["id"], layer, audience)).fetchall()
    if not candidates:
        return False
    digest = content_digest(row.get("content", ""))["value"]
    house = _House(published_conn)
    return any(c["content_digest"] == digest and audience in sharing.audiences_for(house, c["memory_id"])
               for c in candidates)


_TABLES = {"episode": "episodes", "semantic": "semantics"}


def base(conn: sqlite3.Connection, layer: str, sel: Selection, ctx: SourceContext,
         counts: Counter) -> Iterator[str]:
    """Ids of ``layer`` that pass I 5.2's base(m) less its ledger terms, in (created_at, id) order.

    The source is read one row at a time from a cursor, so a row and its content are all that is in memory.
    A row whose time does not parse is counted in ``counts["unparseable_time"]`` and left out.
    """
    table = _TABLES[layer]
    t0 = None if sel.since is None else datetime.fromtimestamp(sel.since, timezone.utc)
    t1 = datetime.fromtimestamp(sel.until, timezone.utc)
    house = None
    try:
        if sel.shared_with is not None and ctx.published is not None:
            house = store_reader.connect(ctx.published)
        cur = conn.cursor()
        cur.execute(f"SELECT id, lane, created_at, content FROM {table} ORDER BY created_at, id")
        for id, lane, created_at, content in cur:
            if lane not in sel.lanes:
                continue
            at = parse_instant(created_at)
            if at is None:
                counts["unparseable_time"] += 1
                continue
            if (t0 is not None and at < t0) or at >= t1 or id in sel.exclude:
                continue
            if sel.shared_with is not None and (
                    house is None or not shared(house, {"id": id, "content": content}, layer, ctx,
                                                sel.shared_with)):
                continue
            yield id
    finally:
        if house is not None:
            house.close()
