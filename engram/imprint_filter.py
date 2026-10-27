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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, NamedTuple, Sequence

import sharing
import store_identity
import store_reader
from lighthouse_protocol import content_digest
from permissions import (MAX_COPY_CHAIN, MAX_SUBJECTS, Use, home_of, parse_object_ref, place_retired,
                         record_matches)

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
    terms: Terms | None = None  # the plan's terms: the purposes a deny is tested against (I 5.2 denied(m))
    now: int = 0                # the plan's clock, integer UTC seconds
    _memo: dict = field(default_factory=dict, compare=False, repr=False)   # what is built once per plan


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

AGENT = "agent:station-imprints"        # the requester of the uses the imprint needs (I 5.2 denied(m))
NAMES_SHOWN = 10
NEEDED_ACTIONS = ("recall", "read", "imprint")      # Need(admission); with route, Need(trail-evaluation) adds route
ROAD_NAME = "imprint"                   # the name of the road ref a deny is tested on; its content is never read

# ---- The permissions ledger (I 5.1, 5.2) -------------------------------------------------------------------

# cosubjects(m): subjects_of (permissions.py) at the plan's clock, less the owner. The ref and up to MAX_COPY_CHAIN
# sources up the copies chain, each with its subjects rows not removed and its store's owner when the store is
# registered and no imprint.
COSUBJECTS_SQL = """
WITH RECURSIVE chain(ref, links) AS (
  SELECT :ref, 0
  UNION
  SELECT copies.source, chain.links + 1 FROM chain JOIN copies ON copies.object = chain.ref
   WHERE chain.links < :max_links)
SELECT subjects.subject FROM chain JOIN subjects
    ON subjects.object = chain.ref AND subjects.removed_seq IS NULL
UNION
SELECT stores.owner FROM chain JOIN stores
    ON chain.ref LIKE 'mem:%'
   AND stores.instance_id = substr(chain.ref, 5, instr(substr(chain.ref, 5), '/') - 1)
   AND stores.imprint_of IS NULL
EXCEPT SELECT :owner
ORDER BY 1 LIMIT :limit
"""

# One query: every deny that is not revoked or ended outside the owner's home, and every retirement (I 5.2).
REFUSALS_SQL = """
SELECT 'deny' AS kind, id FROM records
 WHERE effect = 'deny' AND revoked IS NULL AND (valid_until IS NULL OR valid_until > :now) AND layer != :home
UNION ALL SELECT 'retired', id FROM persons WHERE retired_seq IS NOT NULL
UNION ALL SELECT 'retired', id FROM places WHERE retired_seq IS NOT NULL
"""


def open_ledger(engram_home: Path):
    """The machine's permissions ledger, read-only; None when it has none."""
    from permission_ledger import Ledger, LedgerUnreadable

    try:
        return Ledger.open_read_only(Path(engram_home))
    except FileNotFoundError:
        return None
    except (LedgerUnreadable, sqlite3.Error):
        raise PlanRefused("The permissions ledger can't be read; nothing was planned.") from None


def check_owner(ledger, source_id: str, owner: str) -> None:
    """D37: with a ledger, the source store is registered there with the ship's owner as its owner."""
    if ledger is None:
        return
    row = ledger.store_row(source_id)
    if row is None:
        raise PlanRefused("The source store is not registered in the permissions ledger; nothing was planned.")
    if row["owner"] != f"person:{owner}":
        raise PlanRefused(f"The source store belongs to {row['owner']} in the permissions ledger, "
                          f"not to person:{owner}; nothing was planned.")


def cosubjects_of(ledger, ref: str, *, owner: str) -> frozenset[str]:
    """I 5.2's cosubjects(m): at most MAX_SUBJECTS of them, which is enough to tell ``bound``."""
    if ledger is None:
        return frozenset()
    rows = ledger.conn.execute(COSUBJECTS_SQL, {"ref": ref, "max_links": MAX_COPY_CHAIN, "owner": f"person:{owner}",
                                                "limit": MAX_SUBJECTS}).fetchall()
    return frozenset(r[0] for r in rows)


def _with_agent(state, place: str):
    """P26: the State with agent:station-imprints acting for and placed in ``place``, when the ledger has no
    such agent or placement. Added to this State's tables only, never to the ledger."""
    from permissions import State

    tables = state.to_tables()
    if AGENT not in state.agents:
        tables["agents"].append(dict(id=AGENT, acts_for=place, created_seq=0, retired_seq=None))
    if not state.agent_places.get(AGENT):
        tables["agent_places"].append(dict(agent=AGENT, place=place, added_seq=0, removed_seq=None))
    return State.from_tables(tables, seq=state.seq, seq_at={**state.seq_at, 0: 0}, meta=state.meta,
                             names=state.names)


class Refusals:
    """What the ledger refuses whole or by a co-subject's deny (I 5.2 retired(m) and denied(m)).

    One query decides ``any``. With no deny outside the owner's home and no retirement, no State is built.
    """

    def __init__(self, ledger, ctx: SourceContext):
        self._now = ctx.now
        self._home = f"place:home/{ctx.owner}"
        self._route = bool(ctx.terms is not None and ctx.terms.route)
        self._purposes = sorted(ctx.terms.purposes) if ctx.terms is not None else []
        rows = ledger.conn.execute(REFUSALS_SQL, {"now": ctx.now, "home": self._home}).fetchall()
        self.any = bool(rows)
        self._state = None
        self._denies: dict[str, list] = {}
        if not self.any:
            return
        self._state = _with_agent(ledger.state(), self._home)
        for r in rows:
            record = self._state.records.get(r["id"]) if r["kind"] == "deny" else None
            if record is not None:
                self._denies.setdefault(record.layer, []).append(record)

    def retired(self, subject: str) -> bool:
        """A person with a retirement, or whose home or a place above it is retired; never a place."""
        if not self.any:
            return False
        row = self._state.persons.get(subject)
        return row is not None and (row.retired_seq is not None or place_retired(self._state, row.home))

    def _layer(self, subject: str) -> str:
        row = self._state.persons.get(subject)
        if row is not None:
            return row.home
        return home_of(subject) if subject.startswith("person:") else subject

    def refuses(self, ref: str, subject: str) -> bool:
        """Does one of ``subject``'s denies refuse a use the imprint needs on ``ref`` (or, with route, on a road)?"""
        if not self.any:
            return False
        uses = [(ref, x) for x in NEEDED_ACTIONS]
        if self._route:
            road = f"road:{parse_object_ref(ref).instance_id}/{ROAD_NAME}"
            uses += [(road, x) for x in (*NEEDED_ACTIONS, "route")]
        for record in self._denies.get(self._layer(subject), ()):
            at = max(self._now, record.valid_from)
            for obj, x in uses:
                for p in self._purposes:
                    use = Use(requester=AGENT, place=self._home, obj=obj, copy="", action=x, purpose=p, at=at)
                    if record_matches(self._state, record, use, x):
                        return True
        return False


def _refusals(ctx: SourceContext) -> Refusals:
    key = ("refusals", id(ctx.ledger), ctx.now, ctx.owner, ctx.terms)
    if key not in ctx._memo:
        ctx._memo[key] = Refusals(ctx.ledger, ctx)
    return ctx._memo[key]


# ---- The people a plan counts (I 5.2, S3) -------------------------------------------------------------------

class People(NamedTuple):
    count: int                              # distinct people
    named: tuple[tuple[str, int], ...]      # (person, distinct memories), most first, ties by id
    more: int                               # count - len(named)


def _people_table(scratch: Scratch) -> None:
    scratch.conn.execute("CREATE TABLE IF NOT EXISTS plan_people(reason TEXT NOT NULL, subject TEXT NOT NULL, "
                         "memory_id TEXT NOT NULL, layer TEXT NOT NULL)")


def _note_people(scratch: Scratch, reason: str, memory_id: str, layer: str, subjects: Iterable[str]) -> None:
    _people_table(scratch)
    scratch.conn.executemany("INSERT INTO plan_people VALUES (?, ?, ?, ?)",
                             [(reason, s, memory_id, layer) for s in sorted(subjects)])


def people(scratch: Scratch, reason: str, *, names: int = NAMES_SHOWN) -> People:
    """By SQL on ``plan_people``: the distinct people for ``reason``, at most ``names`` of them."""
    _people_table(scratch)
    conn = scratch.conn
    count = conn.execute("SELECT COUNT(DISTINCT subject) FROM plan_people WHERE reason = ?", (reason,)).fetchone()[0]
    named = tuple((s, n) for s, n in conn.execute(
        "SELECT subject, COUNT(DISTINCT memory_id || '/' || layer) AS n FROM plan_people WHERE reason = ? "
        "GROUP BY subject ORDER BY n DESC, subject LIMIT ?", (reason, names)))
    return People(count, named, count - len(named))


def base(conn: sqlite3.Connection, layer: str, sel: Selection, ctx: SourceContext,
         counts: Counter) -> Iterator[str]:
    """Ids of ``layer`` that pass I 5.2's base(m), in (created_at, id) order.

    The source is read one row at a time from a cursor, so a row and its content are all that is in memory.
    A row whose time does not parse is counted in ``counts["unparseable_time"]`` and left out. With a ledger a
    memory is also left out, and counted once, for an unsettled lane (``lane_unsettled``); without ``home`` for a
    co-subject (``needs_yes``); with it, in this order, for a retired co-subject (``retired``), more than 8
    subjects (``bound``) or a co-subject's no (``said_no``). One that ships with co-subjects is counted in
    ``others_memories``. The people go to ``plan_people``; no key of ``counts`` names one.
    """
    table = _TABLES[layer]
    t0 = None if sel.since is None else datetime.fromtimestamp(sel.since, timezone.utc)
    t1 = datetime.fromtimestamp(sel.until, timezone.utc)
    ledger = ctx.ledger
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
            if ledger is not None and not _admits(ledger, ctx, layer, id, lane, counts):
                continue
            yield id
    finally:
        if house is not None:
            house.close()


def _admits(ledger, ctx: SourceContext, layer: str, id: str, lane: str, counts: Counter) -> bool:
    """The ledger's terms of base(m) for one memory (D40, D27, I 5.2)."""
    ref = f"mem:{ctx.source_id}/{layer}/{id}"
    note = ledger.latest_lane_note(ref)
    if note is not None and (note == "pending" or note != lane):
        counts["lane_unsettled"] += 1
        return False
    cos = cosubjects_of(ledger, ref, owner=ctx.owner)
    if not cos:
        return True
    scratch = ctx.scratch
    if not ctx.home:
        counts["needs_yes"] += 1
        _note_people(scratch, "needs_yes", id, layer, cos)
        return False
    refusals = _refusals(ctx)
    if refusals.any:
        retired = [s for s in cos if refusals.retired(s)]
        if retired:
            counts["retired"] += 1
            _note_people(scratch, "retired", id, layer, retired)
            return False
    if len(cos) >= MAX_SUBJECTS:
        counts["bound"] += 1
        return False
    if refusals.any:
        said_no = [s for s in cos if refusals.refuses(ref, s)]
        if said_no:
            counts["said_no"] += 1
            _note_people(scratch, "said_no", id, layer, said_no)
            return False
    counts["others_memories"] += 1
    _note_people(scratch, "others", id, layer, cos)
    return True


# ---- Down-closure, the memories that ship and the links induced on them (I 5.2, 6.2, 6.4) -------------------

MAX_MEMORIES = 100_000
BATCH = 500                     # ids per query when rows are read back for the memories that ship


class Admissible(NamedTuple):
    """Ê and Ŝ in scratch tables. Ê need not ship, so it isn't capped (R26). ``counts`` holds base()'s counts
    and ``semantic_source_stays`` and ``semantic_unsourced``."""
    episodes: IdSet
    semantics: IdSet
    counts: Counter


def admissible(conn: sqlite3.Connection, sel: Selection, ctx: SourceContext) -> Admissible:
    """Ê = base episodes; Ŝ = base semantics whose recorded sources all lie in Ê, and that have one (or
    ``sel.unsourced``). Layers choose what ships, never what is admissible, so both are always computed.

    Each semantic's sources are read from ``semantic_sources`` as it is now (pruning cascaded, I 5.2) and each
    is looked up in Ê's scratch table by SQL; no source list is held in memory.
    """
    counts: Counter = Counter()
    episodes = IdSet(ctx.scratch)
    for id in base(conn, "episode", sel, ctx, counts):
        episodes.add(id)
    semantics = IdSet(ctx.scratch)
    for id in base(conn, "semantic", sel, ctx, counts):
        sources = [r[0] for r in conn.execute(
            "SELECT episode_id FROM semantic_sources WHERE semantic_id = ?", (id,))]
        if not sources:
            if sel.unsourced:
                semantics.add(id)
            else:
                counts["semantic_unsourced"] += 1
        elif all(e in episodes for e in sources):
            semantics.add(id)
        else:
            counts["semantic_source_stays"] += 1
    return Admissible(episodes, semantics, counts)


class Shipped(NamedTuple):
    """The memories that ship (Λ of the admissible ones): episode ids and semantic ids, in base order."""
    episodes: tuple[str, ...]
    semantics: tuple[str, ...]

    def members(self) -> frozenset[tuple[str, str]]:
        """``(layer, id)`` of every memory that ships."""
        return frozenset([("episode", i) for i in self.episodes] + [("semantic", i) for i in self.semantics])

    def refs(self, source_id: str) -> Iterator[str]:
        """The ``mem:`` ref of every memory that ships, sorted."""
        yield from sorted(f"mem:{source_id}/{layer}/{i}" for layer, i in self.members())


def shipped(adm: Admissible, sel: Selection) -> Shipped:
    """Λ: ``sel.layers`` chooses what ships from what is admissible. It counts first and refuses none or more
    than ``MAX_MEMORIES`` before it builds the tuples (R26)."""
    n = (len(adm.episodes) if "episode" in sel.layers else 0) + (len(adm.semantics) if "semantic" in sel.layers else 0)
    if n == 0:
        raise PlanRefused("This selection holds no memories; nothing was planned.")
    if n > MAX_MEMORIES:
        raise PlanRefused("This selection holds more than 100,000 memories, the most one imprint can hold. "
                          "Narrow it.")
    return Shipped(tuple(adm.episodes) if "episode" in sel.layers else (),
                   tuple(adm.semantics) if "semantic" in sel.layers else ())


def _batches(ids: Sequence[str]) -> Iterator[Sequence[str]]:
    for i in range(0, len(ids), BATCH):
        yield ids[i:i + BATCH]


def semantic_rows(conn: sqlite3.Connection, sh: Shipped) -> Iterator[dict]:
    """The shipped semantics as stored, in memory order; ``contradicted_by`` is null when it names a semantic
    outside S."""
    stays = frozenset(sh.semantics)
    for batch in _batches(sh.semantics):
        marks = ", ".join("?" * len(batch))
        cur = conn.cursor()
        cur.row_factory = sqlite3.Row
        found = {r["id"]: dict(r) for r in cur.execute(f"SELECT * FROM semantics WHERE id IN ({marks})", batch)}
        for id in batch:
            if id in found:
                row = found[id]
                if row.get("contradicted_by") not in stays:
                    row["contradicted_by"] = None
                yield row


def vector_rows(conn: sqlite3.Connection, layer: str, ids: Sequence[str]) -> Iterator[dict]:
    """``{"id", "embedding"}`` (bytes as stored) for ``ids`` in the order given; one batch of ids per query."""
    table = f"{_TABLES[layer][:-1]}_vectors" if layer in _TABLES else None
    if table is None:
        raise ValueError(f"unknown layer {layer!r}")
    for batch in _batches(ids):
        marks = ", ".join("?" * len(batch))
        found = {r[0]: r[1] for r in conn.execute(f"SELECT id, embedding FROM {table} WHERE id IN ({marks})", batch)}
        for id in batch:
            if id in found:
                yield {"id": id, "embedding": bytes(found[id])}


def link_rows(conn: sqlite3.Connection, sel: Selection, sh: Shipped) -> dict[str, Iterator[dict]]:
    """The rows of each link table induced on the memories that ship (I 6.2). Each is a lazy cursor over the
    table in key order; a row with an endpoint outside M is dropped."""
    members = sh.members()
    episodes = frozenset(sh.episodes)
    semantics = frozenset(sh.semantics)

    def rows(sql: str) -> Iterator[sqlite3.Row]:
        cur = conn.cursor()
        cur.row_factory = sqlite3.Row
        yield from cur.execute(sql)

    def sources() -> Iterator[dict]:
        for r in rows("SELECT * FROM semantic_sources ORDER BY semantic_id, episode_id"):
            if r["semantic_id"] in semantics and r["episode_id"] in episodes:
                yield dict(r)

    def resonances() -> Iterator[dict]:
        t0 = sel.since
        for r in rows("SELECT * FROM resonances ORDER BY id"):
            if (r["layer_a"], r["memory_a"]) not in members or (r["layer_b"], r["memory_b"]) not in members:
                continue
            at = parse_instant(r["created_at"])
            if at is None or (t0 is not None and at.timestamp() < t0) or at.timestamp() >= sel.until:
                continue
            yield dict(r)

    def peers() -> Iterator[dict]:
        for r in rows("SELECT * FROM semantic_peers ORDER BY peer_id, parent_id"):
            if r["peer_id"] in semantics and r["parent_id"] in semantics:
                yield dict(r)

    def subdivisions() -> Iterator[dict]:
        for r in rows("SELECT * FROM subdivision_events ORDER BY id"):
            if r["parent_id"] not in semantics:
                continue
            try:
                peer_ids = json.loads(r["peer_ids"])
            except (TypeError, ValueError):
                continue
            if isinstance(peer_ids, list) and all(isinstance(p, str) and p in semantics for p in peer_ids):
                yield dict(r)

    return {"semantic_sources": sources(), "resonances": resonances(), "semantic_peers": peers(),
            "subdivision_events": subdivisions()}


def cosubject_rows(sh: Shipped, ctx: SourceContext) -> Iterator[tuple[str, str, str]]:
    """I 6.2's ``imprint_subjects``: ``(memory_id, layer, subject)`` sorted, one memory at a time; empty without
    ``home`` or a ledger (D43)."""
    if not ctx.home or ctx.ledger is None:
        return
    for id, layer in sorted([(i, "episode") for i in sh.episodes] + [(i, "semantic") for i in sh.semantics]):
        for subject in sorted(cosubjects_of(ctx.ledger, f"mem:{ctx.source_id}/{layer}/{id}", owner=ctx.owner)):
            yield id, layer, subject


# ---- Sessions closed at t1 (I 5.2), session ids and operation_log (D6, D7) ----------------------------------

CLOSED_SECONDS = 3600

_SESSION_ROWS_SQL = """
SELECT sid, ts FROM (
    SELECT session_id AS sid, inst(created_at) AS ts FROM episodes
    UNION ALL
    SELECT CASE WHEN json_valid(context) AND json_type(context, '$.session_id') = 'text'
                THEN json_extract(context, '$.session_id') END AS sid, inst(timestamp) AS ts FROM memory_log
    UNION ALL
    SELECT session_id AS sid, inst(timestamp) AS ts FROM operation_log
) WHERE sid IS NOT NULL AND sid != '' AND ts IS NOT NULL AND ts < :t1
"""


def _instant_seconds(text: Any) -> float | None:
    at = parse_instant(text)
    return None if at is None else at.timestamp()


def closed_sessions(conn: sqlite3.Connection, t1: int, *, scratch: Scratch | None = None) -> IdSet:
    """The sessions closed at t1: the newest of a session's rows before t1 (episodes by ``session_id``,
    ``memory_log`` by ``context.session_id`` of any event type, ``operation_log`` by ``session_id``) is older than
    ``t1 - CLOSED_SECONDS``. Rows whose time does not parse take no part. The ``GROUP BY`` runs in SQL and its
    groups stream into the scratch file's id set."""
    own = scratch if scratch is not None else Scratch(":memory:")
    closed = IdSet(own)
    conn.create_function("inst", 1, _instant_seconds, deterministic=True)
    cur = conn.cursor()
    cur.row_factory = None
    for (sid,) in cur.execute(
            f"SELECT sid FROM ({_SESSION_ROWS_SQL}) GROUP BY sid HAVING MAX(ts) < :cutoff ORDER BY sid",
            {"t1": t1, "cutoff": t1 - CLOSED_SECONDS}):
        closed.add(sid)
    return closed


def episode_rows(conn: sqlite3.Connection, sh: Shipped, terms: Terms, closed: IdSet) -> Iterator[dict]:
    """The shipped episodes, every column but ``rowid``, in ``(created_at, id)`` order. ``session_id`` is kept
    only when the terms include ``route`` and its session is closed at t1; otherwise it is null (D6, D7)."""
    stays = frozenset(sh.episodes)
    columns = [r[1] for r in conn.execute("PRAGMA table_info(episodes)") if r[1] != "rowid"]
    names = ", ".join(f'"{c}"' for c in columns)
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    for r in cur.execute(f"SELECT {names} FROM episodes ORDER BY created_at, id"):
        if r["id"] not in stays:
            continue
        row = dict(r)
        if not (terms.route and row.get("session_id") is not None and row["session_id"] in closed):
            row["session_id"] = None
        yield row


def operation_rows(conn: sqlite3.Connection, sel: Selection, terms: Terms, closed: IdSet,
                   sh: Shipped) -> Iterator[dict]:
    """The ``operation_log`` rows that ship (empty without ``route``): ``operation`` in ``CITING_OPERATIONS``,
    ``t0 <= tau < t1``, a closed session, and at least one target, every one an episode or semantic in M.
    ``harness``, ``model`` and ``repo`` are null and ``details`` is ``{}``."""
    if not terms.route:
        return
    inside = frozenset(sh.episodes) | frozenset(sh.semantics)
    marks = ", ".join("?" * len(CITING_OPERATIONS))
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    for r in cur.execute(f"SELECT * FROM operation_log WHERE operation IN ({marks}) ORDER BY timestamp, id",
                         CITING_OPERATIONS):
        sid = r["session_id"]
        if not sid or sid not in closed:
            continue
        at = parse_instant(r["timestamp"])
        if at is None or (sel.since is not None and at.timestamp() < sel.since) or at.timestamp() >= sel.until:
            continue
        try:
            targets = json.loads(r["target_ids"])
        except (TypeError, ValueError):
            continue
        if not (isinstance(targets, list) and targets
                and all(isinstance(t, str) and t in inside for t in targets)):
            continue
        row = dict(r)
        row.update(harness=None, model=None, repo=None, details="{}")
        yield row


def normalize_outcome(text: str | None) -> str | None:
    """A recall row's outcome as it ships: ``used: auto: cited`` when equal to it, else ``used`` or ``not_used``
    by prefix, else null. Any free-text note after the prefix never leaves (I 6.2)."""
    if not isinstance(text, str):
        return None
    if text == "used: auto: cited":
        return text
    if text.startswith("not_used"):
        return "not_used"
    if text.startswith("used"):
        return "used"
    return None


def instinct_ids(conn: sqlite3.Connection, scratch: Scratch) -> IdSet:
    """Every id in the source's ``instincts`` table, as an id set in the scratch file (R26)."""
    found = IdSet(scratch)
    cur = conn.cursor()
    cur.row_factory = None
    for (id,) in cur.execute("SELECT id FROM instincts ORDER BY id"):
        found.add(id)
    return found


_LOG_KEEP = {"recall": ("recall_id", "session_id"), "route_shown": ("receipt_id", "session_id", "tool", "lane")}


def memory_log_rows(conn: sqlite3.Connection, sel: Selection, terms: Terms, closed: IdSet, sh: Shipped,
                    instinct_ids: IdSet) -> Iterator[dict]:
    """The ``memory_log`` rows that ship (empty without ``route``; I 6.2, D35), in ``(timestamp, id)`` order.

    A recall row loses its instinct ids and ships whole only when the rest is not empty and every id is in M.
    A ``route_shown`` row ships with its targets cut to M, in order, unless that leaves nothing or ``context.lane``
    is not in ``sel.lanes``; its outcome is null. Context keeps only the keys named for the event type. Every
    other event type is dropped, as is a row without a closed session or outside ``t0 <= tau < t1``. No row
    carries a mark of what was cut."""
    if not terms.route:
        return
    inside = frozenset(sh.episodes) | frozenset(sh.semantics)
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    for r in cur.execute("SELECT * FROM memory_log WHERE event_type IN ('recall', 'route_shown') "
                         "ORDER BY timestamp, id"):
        at = parse_instant(r["timestamp"])
        if at is None or (sel.since is not None and at.timestamp() < sel.since) or at.timestamp() >= sel.until:
            continue
        try:
            context = json.loads(r["context"])
            targets = json.loads(r["target_ids"])
        except (TypeError, ValueError):
            continue
        sid = context.get("session_id") if isinstance(context, dict) else None
        if not (isinstance(sid, str) and sid in closed and isinstance(targets, list)
                and all(isinstance(t, str) for t in targets)):
            continue
        row = dict(r)
        if r["event_type"] == "recall":
            targets = [t for t in targets if t not in instinct_ids]
            if not targets or not all(t in inside for t in targets):
                continue
            row["outcome"] = normalize_outcome(r["outcome"])
        else:
            if context.get("lane") not in sel.lanes:
                continue
            targets = [t for t in targets if t in inside]
            if not targets:
                continue
            row["outcome"] = None
        row["target_ids"] = json.dumps(targets)
        row["context"] = json.dumps({k: context[k] for k in _LOG_KEEP[r["event_type"]] if k in context})
        yield row


# ---- The source (I 5.1) -------------------------------------------------------------------------------------

def published_house(engram_home: Path) -> Path:
    return Path(engram_home) / ".engram" / "instances" / "lighthouse" / "graph.db"


def check_source(path: Path, conn: sqlite3.Connection, *, engram_home: Path,
                 imprint_roots: Sequence[Path] = ()) -> None:
    """The plan refuses the published house, an imprint, a store newer than this code and one with no identity.

    Paths are compared resolved. The messages name the reason, never a memory."""
    here = Path(path).resolve()
    if here == published_house(engram_home).resolve():
        raise PlanRefused("The source is the published house; nothing was planned.")
    for root in imprint_roots:
        if here == Path(root).resolve() or Path(root).resolve() in here.parents:
            raise PlanRefused("The source is inside the imprints directory; nothing was planned.")
    if store_identity.is_imprint(conn):
        raise PlanRefused("The source is an imprint; nothing was planned.")
    tables = store_reader._tables(conn)
    if store_reader._schema(conn, tables)["unknown"]:
        raise PlanRefused("The source store is newer than this code (it has migrations this code doesn't know); "
                          "nothing was planned.")
    if store_identity.effective_id(conn) is None:
        raise PlanRefused("The source store has no identity this code can derive; nothing was planned.")
