"""Which tables an imprint copies, and how (store-copy spec I 6.2, D4).

Deny by default: a table with no rule here is not copied, and a package table with no rule stops the build.
Rules: ``filtered`` (some rows copy), ``dropped`` (no row copies; a migration's table exists empty, a hook-only
table is absent), ``rebuilt`` (SQLite, a trigger or the migrations fill it), ``built`` (only the build creates it)
and ``never`` (not copied, not created).
"""
from __future__ import annotations

import sqlite3
from typing import Iterable, NamedTuple

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
    "shared_memories_changes": "dropped",   # 029's change counter for shared_memories (not in I 6.2's table)
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
