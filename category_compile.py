"""Bounded, deterministic compilation of an active category epoch."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
import heapq
from itertools import chain
import json
import math
import os
from pathlib import Path
import re
import select
import sqlite3
import struct
import threading
import time
from typing import Any
import uuid

from categories import WeightVector


_MMR_LAMBDA = 0.75
_TIME_CHECK_BATCH = 32
_MAX_WALL_TIME_MS = 500
_MAX_ACTIVE_SNAPSHOT_BYTES = 64 * 1024 * 1024
_MAX_ACTIVE_MEMBERS = 1_000_000
_MAX_CONTENT_BYTES = 1024 * 1024
_MAX_EMBEDDING_BYTES = 64 * 1024
_MAX_EMBEDDING_DIMENSIONS = 4096
_MAX_RETAINED_FEATURE_BYTES = 256 * 1024 * 1024
_SQL_PROGRESS_OPCODES = 1000
_CONNECTION_POOL_SIZE = 4
_CONNECTION_OPEN_LOCK = threading.Lock()
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_ZERO_WEIGHTS = WeightVector(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


class _FrozenMapping(Mapping[str, float]):
    """Small insertion-ordered mapping that keeps frozen cells hashable."""

    __slots__ = ("_items",)

    def __init__(self, values: Mapping[str, float]):
        self._items = tuple(values.items())

    def __getitem__(self, key: str) -> float:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _value in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __hash__(self) -> int:
        return hash(frozenset(self._items))

    def __repr__(self) -> str:
        return repr(dict(self._items))


@dataclass(frozen=True)
class _ReverseId:
    """Heap wrapper whose smallest item is the lexicographically largest ID."""

    value: str

    def __lt__(self, other: _ReverseId) -> bool:
        return self.value > other.value


@dataclass(frozen=True)
class CompileBudget:
    normal_target: int = 36_000
    rotation_watermark: int = 40_000
    hard_ceiling: int = 65_536
    base_tokens: int = 0
    max_depth: int = 4
    max_neighbors: int = 64
    max_candidates: int = 50_000
    wall_time_ms: int = 500

    def __post_init__(self) -> None:
        values = {
            "normal_target": self.normal_target,
            "rotation_watermark": self.rotation_watermark,
            "hard_ceiling": self.hard_ceiling,
            "base_tokens": self.base_tokens,
            "max_depth": self.max_depth,
            "max_neighbors": self.max_neighbors,
            "max_candidates": self.max_candidates,
            "wall_time_ms": self.wall_time_ms,
        }
        for name, value in values.items():
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
        if not (
            0
            <= self.normal_target
            <= self.rotation_watermark
            <= self.hard_ceiling
            <= 65_536
        ):
            raise ValueError("token limits must satisfy normal <= rotation <= hard <= 65536")
        if not 0 <= self.base_tokens <= self.hard_ceiling:
            raise ValueError("base tokens must be within the hard ceiling")
        if not 0 <= self.max_depth <= 4:
            raise ValueError("max depth must be between 0 and 4")
        if not 0 <= self.max_neighbors <= 64:
            raise ValueError("max neighbors must be between 0 and 64")
        if not 0 <= self.max_candidates <= 50_000:
            raise ValueError("max candidates must be between 0 and 50000")
        if not 1 <= self.wall_time_ms <= _MAX_WALL_TIME_MS:
            raise ValueError("wall time must be between 1 and 500 milliseconds")


@dataclass(frozen=True)
class CompiledCell:
    id: str
    content: str
    dimension: int
    score: float
    contributions: Mapping[str, float]
    hops: int
    token_count: int
    affect: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.contributions, _FrozenMapping):
            object.__setattr__(self, "contributions", _FrozenMapping(self.contributions))


@dataclass(frozen=True)
class CompiledCategory:
    epoch_id: str
    context_id: str | None
    cells: tuple[CompiledCell, ...]
    token_count: int
    candidate_count: int
    truncated: bool
    rotation_required: bool
    policy_version: str = "v1"


@dataclass(frozen=True)
class _Candidate:
    cell: CompiledCell
    embedding: tuple[float, ...] | None = field(compare=False)
    words: Counter[str] = field(compare=False, hash=False)
    embedding_norm: float | None = field(compare=False, hash=False)


class _DeadlineExceeded(RuntimeError):
    pass


class _ResourceLimitExceeded(RuntimeError):
    pass


def _weighted(value: float) -> float:
    """Suppress binary floating noise while retaining meaningful precision."""
    return round(value, 12)


def valuation_v1(weights: WeightVector) -> tuple[float, Mapping[str, float]]:
    """Value one observation without blending its independent channels."""
    parts = {
        "relevance": _weighted(0.30 * weights.relevance),
        "evidence": _weighted(0.20 * weights.evidence),
        "recency": _weighted(0.10 * weights.recency),
        "affect_salience": _weighted(0.10 * abs(weights.affect)),
        "adoption": _weighted(0.10 * weights.adoption),
        "novelty": _weighted(0.15 * weights.novelty),
        "cost": _weighted(-0.05 * weights.cost),
    }
    return sum(parts.values()), parts


def estimate_tokens(text: str) -> int:
    """Return the fixed v1 UTF-8 byte estimate."""
    return max(1, (len(text.encode("utf-8")) + 3) // 4)


class CategoryCompiler:
    """Compile a bounded working set from one immutable epoch snapshot."""

    def __init__(self, store: Any, budget: CompileBudget | None = None):
        self.store = store
        self.budget = budget or CompileBudget()
        self.store_connection = getattr(store, "connection", None)
        if self.store_connection is None:
            self.store_connection = getattr(store, "conn", None)
        if self.store_connection is None:
            raise TypeError("category compiler requires a SQLite-backed store")
        main_rows = self.store_connection.execute("PRAGMA database_list")
        main_path = next(
            (str(row[2]) for row in main_rows if str(row[1]) == "main"), ""
        )
        if not main_path:
            raise ValueError("category compilation requires a file-backed SQLite store")
        self.database_path = Path(main_path).resolve(strict=True)
        database_stat = self.database_path.stat()
        self.database_identity = (database_stat.st_dev, database_stat.st_ino)
        self._pool_condition = threading.Condition()
        self._available_connections: list[sqlite3.Connection] = []
        self._leased_connections: dict[sqlite3.Connection, int] = {}
        self._shutdown_errors: list[Exception] = []
        self._closed = False
        self._closing = False
        self._close_in_progress = False
        try:
            for _index in range(_CONNECTION_POOL_SIZE):
                self._available_connections.append(self._create_compile_connection())
        except Exception:
            for connection in self._available_connections:
                connection.close()
            self._available_connections.clear()
            self._closed = True
            raise
        self._compile_connection: ContextVar[sqlite3.Connection | None] = ContextVar(
            f"category_compile_connection_{id(self)}", default=None
        )

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the connection owned by this invocation's execution context."""
        return self._compile_connection.get() or self.store_connection

    def compile(
        self,
        epoch_id: str,
        context_id: str | None = None,
        seed_cell_ids: Iterable[str] = (),
        base_tokens: int | None = None,
    ) -> CompiledCategory:
        base = self.budget.base_tokens if base_tokens is None else base_tokens
        if type(base) is not int:
            raise TypeError("base tokens must be an integer")
        if not 0 <= base <= self.budget.hard_ceiling:
            raise ValueError("base tokens must be within the hard ceiling")
        rotation_at_start = base >= self.budget.rotation_watermark
        started = time.monotonic_ns()
        deadline = started + self.budget.wall_time_ms * 1_000_000
        seed_iterator = iter(seed_cell_ids)
        if self._expired(deadline):
            return self._empty_result(epoch_id, context_id, True, rotation_at_start)
        try:
            first_seed = next(seed_iterator)
        except StopIteration:
            return self._empty_result(epoch_id, context_id, False, rotation_at_start)
        if self._expired(deadline):
            return self._empty_result(epoch_id, context_id, True, rotation_at_start)
        if base >= self.budget.hard_ceiling:
            return self._empty_result(epoch_id, context_id, True, rotation_at_start)

        seed_stream = chain((first_seed,), seed_iterator)
        active_table = f"category_compile_active_{uuid.uuid4().hex}"
        try:
            compile_connection = self._acquire_compile_connection(deadline)
        except _DeadlineExceeded:
            return self._empty_result(epoch_id, context_id, True, rotation_at_start)
        connection_token = self._compile_connection.set(compile_connection)
        try:
            compile_connection.set_progress_handler(
                lambda: int(self._expired(deadline)), _SQL_PROGRESS_OPCODES
            )
            compile_connection.execute("BEGIN")
            self._stage_active_membership(epoch_id, active_table, deadline)
            bounded_seeds, seed_truncated = self._bounded_seed_ids(
                seed_stream, deadline, active_table
            )
            if not bounded_seeds:
                self._assert_database_identity()
                return self._empty_result(
                    epoch_id, context_id, seed_truncated, rotation_at_start
                )
            result = self._compile_active(
                epoch_id,
                context_id,
                bounded_seeds,
                seed_truncated,
                base,
                deadline,
                active_table,
            )
            self._assert_database_identity()
            return result
        except (_DeadlineExceeded, _ResourceLimitExceeded):
            return self._empty_result(epoch_id, context_id, True, rotation_at_start)
        except sqlite3.OperationalError as exc:
            if not self._is_sql_interrupt(exc):
                raise
            return self._empty_result(epoch_id, context_id, True, rotation_at_start)
        finally:
            try:
                compile_connection.set_progress_handler(None, 0)
            finally:
                try:
                    if compile_connection.in_transaction:
                        compile_connection.rollback()
                finally:
                    try:
                        compile_connection.execute(
                            f'DROP TABLE IF EXISTS temp."{active_table}"'
                        )
                    finally:
                        try:
                            self._assert_database_identity()
                        finally:
                            try:
                                self._release_compile_connection(compile_connection)
                            finally:
                                self._compile_connection.reset(connection_token)

    def _create_compile_connection(self) -> sqlite3.Connection:
        anchor_fd = -1
        vnode_queue = None
        connection: sqlite3.Connection | None = None
        try:
            self._assert_database_identity()
            anchor_fd = os.open(self.database_path, os.O_RDONLY)
            anchored = os.fstat(anchor_fd)
            if (anchored.st_dev, anchored.st_ino) != self.database_identity:
                raise ValueError("category database file identity changed")
            if hasattr(select, "kqueue"):
                vnode_queue = select.kqueue()
                vnode_queue.control(
                    [
                        select.kevent(
                            anchor_fd,
                            filter=select.KQ_FILTER_VNODE,
                            flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                            fflags=(
                                select.KQ_NOTE_RENAME
                                | select.KQ_NOTE_DELETE
                                | select.KQ_NOTE_REVOKE
                            ),
                        )
                    ],
                    0,
                    0,
                )
            self._assert_database_identity()
            database_uri = f"{self.database_path.as_uri()}?mode=ro"
            with _CONNECTION_OPEN_LOCK:
                connection = sqlite3.connect(
                    database_uri, uri=True, timeout=0, check_same_thread=False
                )
                self._assert_database_identity()
                if vnode_queue is not None and vnode_queue.control(None, 1, 0):
                    raise ValueError("category database file identity changed")
                # Platforms without kqueue retain the pathname checks above.
                # That fallback detects ordinary replacement but cannot latch ABA.
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA temp_store = FILE")
            vector_schema = connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'cat_vectors'"
            ).fetchone()
            if vector_schema is not None and "using vec0" in str(vector_schema[0]).lower():
                import sqlite_vec

                connection.enable_load_extension(True)
                try:
                    sqlite_vec.load(connection)
                finally:
                    connection.enable_load_extension(False)
            return connection
        except Exception:
            if connection is not None:
                connection.set_progress_handler(None, 0)
                connection.close()
            raise
        finally:
            if vnode_queue is not None:
                vnode_queue.close()
            if anchor_fd >= 0:
                os.close(anchor_fd)

    def _assert_database_identity(self) -> None:
        try:
            database_stat = self.database_path.stat()
        except OSError as exc:
            raise ValueError("category database file identity changed") from exc
        if (database_stat.st_dev, database_stat.st_ino) != self.database_identity:
            raise ValueError("category database file identity changed")

    def _acquire_compile_connection(self, deadline: int) -> sqlite3.Connection:
        self._assert_database_identity()
        with self._pool_condition:
            if self._closed or self._closing:
                raise RuntimeError("category compiler is closed")
            while not self._available_connections:
                if self._closed or self._closing:
                    raise RuntimeError("category compiler is closed")
                remaining_ns = deadline - time.monotonic_ns()
                if remaining_ns <= 0:
                    raise _DeadlineExceeded
                self._pool_condition.wait(remaining_ns / 1_000_000_000)
            if self._closed or self._closing:
                raise RuntimeError("category compiler is closed")
            if time.monotonic_ns() >= deadline:
                raise _DeadlineExceeded
            connection = self._available_connections.pop()
            self._leased_connections[connection] = threading.get_ident()
        try:
            self._assert_database_identity()
            if time.monotonic_ns() >= deadline:
                raise _DeadlineExceeded
        except Exception:
            self._release_compile_connection(connection)
            raise
        return connection

    def _release_compile_connection(self, connection: sqlite3.Connection) -> None:
        with self._pool_condition:
            if connection not in self._leased_connections:
                raise RuntimeError("category compiler connection is not leased")
            should_close = self._closed or self._closing
            if not should_close:
                del self._leased_connections[connection]
                self._available_connections.append(connection)
                self._pool_condition.notify()
                return
        try:
            connection.close()
        except Exception as exc:
            with self._pool_condition:
                del self._leased_connections[connection]
                self._available_connections.append(connection)
                self._shutdown_errors.append(exc)
                self._closed = False
                self._closing = True
                self._pool_condition.notify_all()
        else:
            with self._pool_condition:
                del self._leased_connections[connection]
                self._pool_condition.notify_all()

    def close(self) -> None:
        with self._pool_condition:
            while self._close_in_progress:
                if threading.get_ident() in self._leased_connections.values():
                    raise RuntimeError(
                        "category compiler cannot close from a connection lease"
                    )
                self._pool_condition.wait()
            if self._closed:
                return
            if threading.get_ident() in self._leased_connections.values():
                raise RuntimeError(
                    "category compiler cannot close from a connection lease"
                )
            self._closing = True
            self._close_in_progress = True
            self._shutdown_errors = []
            connections = self._available_connections
            self._available_connections = []
            self._pool_condition.notify_all()
        failed = []
        first_error: Exception | None = None
        for connection in connections:
            try:
                connection.close()
            except Exception as exc:
                failed.append(connection)
                if first_error is None:
                    first_error = exc
        with self._pool_condition:
            self._available_connections.extend(failed)
            if first_error is not None:
                self._shutdown_errors.append(first_error)
            while self._leased_connections:
                self._pool_condition.wait()
            first_error = (
                self._shutdown_errors[0] if self._shutdown_errors else None
            )
            self._shutdown_errors = []
            self._close_in_progress = False
            if not self._available_connections:
                self._closed = True
                self._closing = False
            else:
                self._closed = False
                self._closing = True
            self._pool_condition.notify_all()
        if first_error is not None:
            raise first_error

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _compile_active(
        self,
        epoch_id: str,
        context_id: str | None,
        seed_cell_ids: tuple[str, ...],
        seed_truncated: bool,
        base: int,
        deadline: int,
        active_table: str,
    ) -> CompiledCategory:
        candidate_heap: list[tuple[float, str, _Candidate]] = []
        queue: deque[tuple[str, int]] = deque()
        visited: set[str] = set()
        retained_feature_bytes = [0]
        truncated = seed_truncated
        stopped = False

        active_seeds = tuple(
            cell_id
            for cell_id in seed_cell_ids
            if self._is_active(active_table, cell_id)
        )
        active_seed_set = set(active_seeds)
        inactive_seeds = tuple(
            cell_id for cell_id in seed_cell_ids if cell_id not in active_seed_set
        )
        translated = active_seeds
        timed_out = False
        if inactive_seeds:
            ancestor_ids, ancestry_truncated = self._ancestor_epoch_ids(
                epoch_id, deadline
            )
            translated_inactive, lineage_truncated, timed_out = self._translate_seeds(
                inactive_seeds, deadline, active_table, ancestor_ids
            )
            translated = tuple(sorted(set(active_seeds) | set(translated_inactive)))
            truncated |= ancestry_truncated or lineage_truncated or timed_out
        if not timed_out:
            for index, cell_id in enumerate(translated):
                if index % _TIME_CHECK_BATCH == 0 and self._expired(deadline):
                    truncated = True
                    break
                admitted, cap_hit, resource_truncated = self._admit(
                    cell_id,
                    0,
                    context_id,
                    queue,
                    visited,
                    candidate_heap,
                    retained_feature_bytes,
                    deadline,
                )
                truncated |= resource_truncated
                if cap_hit:
                    truncated = True
                    stopped = True
                    break
                if not admitted:
                    continue

        expansions = 0
        while queue and not stopped:
            if expansions % _TIME_CHECK_BATCH == 0 and self._expired(deadline):
                truncated = True
                break
            cell_id, hops = queue.popleft()
            neighbors, neighbor_limited, neighbor_resource_limited = self._neighbors(
                active_table, cell_id, deadline
            )
            truncated |= neighbor_limited or neighbor_resource_limited
            unseen = [neighbor for neighbor in neighbors if neighbor not in visited]
            if hops >= self.budget.max_depth:
                if unseen:
                    truncated = True
                expansions += 1
                continue

            for neighbor in unseen:
                _admitted, cap_hit, resource_truncated = self._admit(
                    neighbor,
                    hops + 1,
                    context_id,
                    queue,
                    visited,
                    candidate_heap,
                    retained_feature_bytes,
                    deadline,
                )
                truncated |= resource_truncated
                if cap_hit:
                    truncated = True
                    stopped = True
                    break
            expansions += 1

        candidate_count = len(candidate_heap)
        capacity = max(
            0,
            min(
                self.budget.normal_target - base,
                self.budget.hard_ceiling - base,
            ),
        )
        selected, selected_tokens, packing_truncated, packing_timed_out = self._pack(
            candidate_heap, capacity, deadline
        )
        truncated |= packing_truncated or packing_timed_out
        total = base + selected_tokens
        return CompiledCategory(
            epoch_id=epoch_id,
            context_id=context_id,
            cells=tuple(candidate.cell for candidate in selected),
            token_count=selected_tokens,
            candidate_count=candidate_count,
            truncated=truncated,
            rotation_required=total >= self.budget.rotation_watermark,
        )

    @staticmethod
    def _empty_result(
        epoch_id: str,
        context_id: str | None,
        truncated: bool,
        rotation_required: bool,
    ) -> CompiledCategory:
        return CompiledCategory(
            epoch_id,
            context_id,
            (),
            0,
            0,
            truncated,
            rotation_required,
        )

    def _stage_active_membership(
        self, epoch_id: str, active_table: str, deadline: int
    ) -> None:
        size_row = self.connection.execute(
            "SELECT length(CAST(active_cell_ids_json AS BLOB)) "
            "FROM cat_snapshots WHERE epoch_id = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (epoch_id,),
        ).fetchone()
        if size_row is not None and int(size_row[0]) > _MAX_ACTIVE_SNAPSHOT_BYTES:
            raise _ResourceLimitExceeded
        self.connection.execute(
            f'CREATE TEMP TABLE "{active_table}" '
            "(id TEXT PRIMARY KEY) WITHOUT ROWID"
        )
        if size_row is None:
            return
        if self._expired(deadline):
            raise _DeadlineExceeded
        self.connection.execute(
            f"""
            INSERT OR IGNORE INTO temp."{active_table}" (id)
            SELECT id FROM (
                SELECT DISTINCT CAST(active.value AS TEXT) AS id
                FROM cat_snapshots AS snapshot,
                     json_each(snapshot.active_cell_ids_json) AS active
                WHERE snapshot.rowid = (
                    SELECT MAX(rowid) FROM cat_snapshots WHERE epoch_id = ?
                )
                LIMIT ?
            )
            """,
            (epoch_id, _MAX_ACTIVE_MEMBERS + 1),
        )
        count = self.connection.execute(
            f'SELECT COUNT(*) FROM temp."{active_table}"'
        ).fetchone()[0]
        if int(count) > _MAX_ACTIVE_MEMBERS:
            raise _ResourceLimitExceeded
        if self._expired(deadline):
            raise _DeadlineExceeded

    def _translate_seeds(
        self,
        seed_cell_ids: Sequence[str],
        deadline: int,
        active_table: str,
        ancestor_ids: set[str],
    ) -> tuple[tuple[str, ...], bool, bool]:
        truncated = False
        pending = deque(seed_cell_ids)
        discovered = set(seed_cell_ids)
        active: set[str] = set()
        steps = 0
        while pending:
            if steps % _TIME_CHECK_BATCH == 0 and self._expired(deadline):
                return tuple(sorted(active)), True, True
            cell_id = pending.popleft()
            if self._is_active(active_table, cell_id):
                active.add(cell_id)
            else:
                descendants, descendants_limited = self._lineage_descendants(
                    cell_id, ancestor_ids, active_table, deadline
                )
                truncated |= descendants_limited
                for descendant in descendants:
                    if descendant in discovered:
                        continue
                    if len(discovered) >= self.budget.max_candidates:
                        truncated = True
                        break
                    discovered.add(descendant)
                    pending.append(descendant)
            steps += 1
        return tuple(sorted(active)), truncated, False

    def _bounded_seed_ids(
        self, seed_cell_ids: Iterable[str], deadline: int, active_table: str
    ) -> tuple[tuple[str, ...], bool]:
        """Keep active-first viable seeds without letting invalid IDs use the cap."""
        limit = self.budget.max_candidates
        selected: dict[str, bool] = {}
        worst_first: list[tuple[int, _ReverseId, str]] = []
        overflow = False
        iterator = iter(seed_cell_ids)
        index = 0
        while True:
            if index % _TIME_CHECK_BATCH == 0 and self._expired(deadline):
                raise _DeadlineExceeded
            try:
                cell_id = next(iterator)
            except StopIteration:
                break
            if self._expired(deadline):
                raise _DeadlineExceeded
            index += 1
            if not isinstance(cell_id, str):
                raise TypeError("seed cell IDs must be strings")
            if cell_id in selected:
                continue
            viable, resource_limited = self._cell_viability(cell_id, deadline)
            overflow |= resource_limited
            if not viable:
                continue
            active = self._is_active(active_table, cell_id)
            if len(selected) < limit:
                selected[cell_id] = active
                heapq.heappush(
                    worst_first,
                    (0 if not active else 1, _ReverseId(cell_id), cell_id),
                )
                continue
            overflow = True
            if limit:
                worst = worst_first[0]
                worst_priority = (0 if worst[0] else 1, worst[2])
                new_priority = (0 if active else 1, cell_id)
                if new_priority < worst_priority:
                    removed = heapq.heapreplace(
                        worst_first,
                        (0 if not active else 1, _ReverseId(cell_id), cell_id),
                    )
                    del selected[removed[2]]
                    selected[cell_id] = active
        return tuple(sorted(selected)), overflow

    def _cell_viability(self, cell_id: str, deadline: int) -> tuple[bool, bool]:
        """Return candidate/lineage viability and whether a resource cap rejected it.

        Oversized content is not retained even as a structural lineage waypoint;
        callers propagate the resource flag as truncation and continue siblings.
        """
        if self._expired(deadline):
            raise _DeadlineExceeded
        row = self.connection.execute(
            "SELECT dimension, length(CAST(content AS BLOB)) FROM cat_cells "
            "WHERE id = ?",
            (cell_id,),
        ).fetchone()
        if row is None or not 0 <= int(row[0]) <= 2:
            return False, False
        if int(row[1]) > _MAX_CONTENT_BYTES:
            return False, True
        return self._is_interpretable(cell_id, deadline), False

    def _is_active(self, active_table: str, cell_id: str) -> bool:
        row = self.connection.execute(
            f'SELECT 1 FROM temp."{active_table}" WHERE id = ?',
            (cell_id,),
        ).fetchone()
        return row is not None

    def _ancestor_epoch_ids(
        self, epoch_id: str, deadline: int
    ) -> tuple[set[str], bool]:
        pending = deque((epoch_id,))
        discovered = {epoch_id}
        truncated = False
        steps = 0
        while pending:
            if steps % _TIME_CHECK_BATCH == 0 and self._expired(deadline):
                raise _DeadlineExceeded
            current = pending.popleft()
            cursor = self.connection.execute(
                "SELECT parent_id FROM cat_epoch_parents "
                "WHERE epoch_id = ? ORDER BY position LIMIT ?",
                (current, self.budget.max_candidates + 1),
            )
            for row in cursor:
                parent_id = str(row[0])
                if parent_id in discovered:
                    continue
                if len(discovered) >= self.budget.max_candidates:
                    truncated = True
                    break
                discovered.add(parent_id)
                pending.append(parent_id)
            steps += 1
        return discovered, truncated

    def _lineage_descendants(
        self,
        cell_id: str,
        ancestor_ids: set[str],
        active_table: str,
        deadline: int,
    ) -> tuple[tuple[str, ...], bool]:
        limit = self.budget.max_candidates
        if limit <= 0:
            return (), False
        truncated = False
        rewrites: list[tuple[str, str]] = []
        for index, epoch_id in enumerate(sorted(ancestor_ids)):
            if index % _TIME_CHECK_BATCH == 0 and self._expired(deadline):
                raise _DeadlineExceeded
            epoch = self.connection.execute(
                "SELECT rewrite_id FROM cat_epochs WHERE id = ?", (epoch_id,)
            ).fetchone()
            if epoch is None or epoch[0] is None:
                continue
            rewrite_id = str(epoch[0])
            is_input = self.connection.execute(
                "SELECT 1 FROM cat_rewrite_members "
                "WHERE rewrite_id = ? AND role = 'input' AND cell_id = ? LIMIT 1",
                (rewrite_id, cell_id),
            ).fetchone()
            if is_input is not None:
                rewrites.append((epoch_id, rewrite_id))

        descendants: dict[str, bool] = {}
        worst_first: list[tuple[int, _ReverseId, str]] = []
        for _epoch_id, rewrite_id in rewrites:
            cursor = self.connection.execute(
                "SELECT cell_id FROM cat_rewrite_members "
                "WHERE rewrite_id = ? AND role = 'output' "
                "ORDER BY position",
                (rewrite_id,),
            )
            for row in cursor:
                descendant = str(row[0])
                if descendant in descendants:
                    continue
                viable, resource_limited = self._cell_viability(descendant, deadline)
                truncated |= resource_limited
                if not viable:
                    continue
                active = self._is_active(active_table, descendant)
                if len(descendants) < limit:
                    descendants[descendant] = active
                    heapq.heappush(
                        worst_first,
                        (
                            0 if not active else 1,
                            _ReverseId(descendant),
                            descendant,
                        ),
                    )
                    continue
                worst = worst_first[0]
                worst_priority = (0 if worst[0] else 1, worst[2])
                new_priority = (0 if active else 1, descendant)
                if new_priority < worst_priority:
                    truncated = True
                    removed = heapq.heapreplace(
                        worst_first,
                        (
                            0 if not active else 1,
                            _ReverseId(descendant),
                            descendant,
                        ),
                    )
                    del descendants[removed[2]]
                    descendants[descendant] = active
                else:
                    truncated = True
        ordered = sorted(
            descendants, key=lambda descendant: (not descendants[descendant], descendant)
        )
        return tuple(ordered), truncated

    def _neighbors(
        self, active_table: str, cell_id: str, deadline: int
    ) -> tuple[tuple[str, ...], bool, bool]:
        limit = self.budget.max_neighbors + 1
        selected: set[str] = set()
        largest_first: list[_ReverseId] = []
        overflow = False
        resource_truncated = False
        queries = (
            (
                f"SELECT boundary.boundary_id, length(CAST(cell.content AS BLOB)) "
                "FROM cat_boundaries AS boundary "
                f'JOIN temp."{active_table}" AS active '
                "ON active.id = boundary.boundary_id "
                "JOIN cat_cells AS cell ON cell.id = boundary.boundary_id "
                "WHERE boundary.cell_id = ? AND cell.dimension BETWEEN 0 AND 2",
                cell_id,
            ),
            (
                f"SELECT boundary.cell_id, length(CAST(cell.content AS BLOB)) "
                "FROM cat_boundaries AS boundary "
                f'JOIN temp."{active_table}" AS active ON active.id = boundary.cell_id '
                "JOIN cat_cells AS cell ON cell.id = boundary.cell_id "
                "WHERE boundary.boundary_id = ? AND cell.dimension BETWEEN 0 AND 2",
                cell_id,
            ),
        )
        scanned = 0
        for sql, parameter in queries:
            cursor = self.connection.execute(sql, (parameter,))
            for row in cursor:
                if scanned % _TIME_CHECK_BATCH == 0 and self._expired(deadline):
                    raise _DeadlineExceeded
                scanned += 1
                neighbor = str(row[0])
                if int(row[1]) > _MAX_CONTENT_BYTES:
                    resource_truncated = True
                    continue
                if neighbor in selected or not self._is_interpretable(neighbor, deadline):
                    continue
                if len(selected) < limit:
                    selected.add(neighbor)
                    heapq.heappush(largest_first, _ReverseId(neighbor))
                else:
                    overflow = True
                    if neighbor < largest_first[0].value:
                        removed = heapq.heapreplace(
                            largest_first, _ReverseId(neighbor)
                        )
                        selected.remove(removed.value)
                        selected.add(neighbor)
        neighbors = tuple(sorted(selected))
        limited = overflow or len(neighbors) > self.budget.max_neighbors
        return (
            neighbors[: self.budget.max_neighbors],
            limited,
            resource_truncated,
        )

    def _admit(
        self,
        cell_id: str,
        hops: int,
        context_id: str | None,
        queue: deque[tuple[str, int]],
        visited: set[str],
        candidate_heap: list[tuple[float, str, _Candidate]],
        retained_feature_bytes: list[int],
        deadline: int,
    ) -> tuple[bool, bool, bool]:
        if cell_id in visited:
            return False, False, False
        if len(visited) >= self.budget.max_candidates:
            return False, True, False
        candidate, resource_limited, feature_bytes = self._candidate(
            cell_id, hops, context_id, deadline
        )
        if candidate is None:
            return False, False, resource_limited
        if len(candidate_heap) >= self.budget.max_candidates:
            return False, True, resource_limited
        if retained_feature_bytes[0] + feature_bytes > _MAX_RETAINED_FEATURE_BYTES:
            return False, True, resource_limited
        visited.add(cell_id)
        queue.append((cell_id, hops))
        retained_feature_bytes[0] += feature_bytes
        heapq.heappush(
            candidate_heap,
            (candidate.cell.score, candidate.cell.id, candidate),
        )
        return True, False, resource_limited

    def _candidate(
        self, cell_id: str, hops: int, context_id: str | None, deadline: int
    ) -> tuple[_Candidate | None, bool, int]:
        row = self.connection.execute(
            "SELECT id, dimension, length(CAST(content AS BLOB)) AS content_bytes "
            "FROM cat_cells WHERE id = ?",
            (cell_id,),
        ).fetchone()
        if row is None or not 0 <= int(row["dimension"]) <= 2:
            return None, False, 0
        content_bytes = int(row["content_bytes"])
        if content_bytes > _MAX_CONTENT_BYTES:
            return None, True, 0
        if not self._is_interpretable(cell_id, deadline):
            return None, False, 0
        if self._expired(deadline):
            raise _DeadlineExceeded
        content_row = self.connection.execute(
            "SELECT content FROM cat_cells WHERE id = ?", (cell_id,)
        ).fetchone()
        if content_row is None:
            return None, False, 0
        content = str(content_row[0])
        if self._expired(deadline):
            raise _DeadlineExceeded
        weights = self._latest_weight(cell_id, context_id)
        score, parts = valuation_v1(weights)
        compiled = CompiledCell(
            id=str(row["id"]),
            content=content,
            dimension=int(row["dimension"]),
            score=score,
            contributions=parts,
            hops=hops,
            token_count=max(1, (content_bytes + 3) // 4),
            affect=weights.affect,
        )
        if self._expired(deadline):
            raise _DeadlineExceeded
        words = self._word_counts(content, deadline)
        embedding, embedding_limited = self._embedding(cell_id, deadline)
        embedding = self._normalize_embedding(embedding, deadline)
        embedding_norm = 1.0 if embedding is not None else None
        # Counters can retain many short token objects; a conservative 64x
        # multiplier keeps total Python-side candidate state well below 1 GiB.
        feature_bytes = content_bytes * 64 + (len(embedding or ()) * 32)
        return (
            _Candidate(compiled, embedding, words, embedding_norm),
            embedding_limited,
            feature_bytes,
        )

    def _word_counts(self, content: str, deadline: int) -> Counter[str]:
        words: Counter[str] = Counter()
        for index, match in enumerate(_WORD_RE.finditer(content)):
            if index % _TIME_CHECK_BATCH == 0 and self._expired(deadline):
                raise _DeadlineExceeded
            words[match.group().lower()] += 1
        if self._expired(deadline):
            raise _DeadlineExceeded
        return words

    def _is_interpretable(self, cell_id: str, deadline: int) -> bool:
        row = self.connection.execute(
            "SELECT dimension FROM cat_cells WHERE id = ?", (cell_id,)
        ).fetchone()
        if row is None:
            return False
        dimension = int(row[0])
        if dimension in (0, 1):
            return True
        if dimension != 2:
            return False
        source = self._path_endpoints(cell_id, "source", deadline)
        if source is None:
            return False
        target = self._path_endpoints(cell_id, "target", deadline)
        return target is not None and source == target

    def _path_endpoints(
        self, cell_id: str, side: str, deadline: int
    ) -> tuple[str, str] | None:
        first_source: str | None = None
        prior_target: str | None = None
        expected_position = 0
        cursor = self.connection.execute(
            "SELECT position, boundary_id FROM cat_boundaries "
            "WHERE cell_id = ? AND side = ? ORDER BY position",
            (cell_id, side),
        )
        for position, boundary_id in cursor:
            if expected_position % _TIME_CHECK_BATCH == 0 and self._expired(deadline):
                raise _DeadlineExceeded
            if int(position) != expected_position:
                return None
            endpoints = self._arrow_endpoints(str(boundary_id), deadline)
            if endpoints is None or (
                prior_target is not None and prior_target != endpoints[0]
            ):
                return None
            if first_source is None:
                first_source = endpoints[0]
            prior_target = endpoints[1]
            expected_position += 1
        if first_source is None or prior_target is None:
            return None
        return first_source, prior_target

    def _arrow_endpoints(
        self, cell_id: str, deadline: int
    ) -> tuple[str, str] | None:
        if self._expired(deadline):
            raise _DeadlineExceeded
        row = self.connection.execute(
            """
            SELECT source.boundary_id, target.boundary_id,
                   (SELECT COUNT(*) FROM cat_boundaries WHERE cell_id = arrow.id)
            FROM cat_cells AS arrow
            JOIN cat_boundaries AS source
              ON source.cell_id = arrow.id AND source.side = 'source' AND source.position = 0
            JOIN cat_boundaries AS target
              ON target.cell_id = arrow.id AND target.side = 'target' AND target.position = 0
            WHERE arrow.id = ? AND arrow.dimension = 1
            """,
            (cell_id,),
        ).fetchone()
        if row is None or int(row[2]) != 2:
            return None
        return str(row[0]), str(row[1])

    def _latest_weight(self, cell_id: str, context_id: str | None) -> WeightVector:
        row = self.connection.execute(
            """
            SELECT relevance, evidence, recency, affect, adoption, novelty, cost
            FROM cat_weight_observations
            WHERE cell_id = ? AND context_id IS ?
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (cell_id, context_id),
        ).fetchone()
        if row is None:
            return _ZERO_WEIGHTS
        return WeightVector(*(float(row[index]) for index in range(7)))

    def _embedding(
        self, cell_id: str, deadline: int
    ) -> tuple[tuple[float, ...] | None, bool]:
        table = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'cat_vectors' LIMIT 1"
        ).fetchone()
        if table is None:
            return None, False
        size_row = self.connection.execute(
            "SELECT length(CAST(embedding AS BLOB)) "
            "FROM cat_vectors WHERE cell_id = ?",
            (cell_id,),
        ).fetchone()
        if size_row is None or size_row[0] is None:
            return None, False
        if int(size_row[0]) > _MAX_EMBEDDING_BYTES:
            return None, True
        if self._expired(deadline):
            raise _DeadlineExceeded
        row = self.connection.execute(
            "SELECT embedding FROM cat_vectors WHERE cell_id = ?", (cell_id,)
        ).fetchone()
        if row is None or row[0] is None:
            return None, False
        value = row[0]
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
                embedding = tuple(float(item) for item in decoded)
            except (
                TypeError,
                ValueError,
                OverflowError,
                RecursionError,
                json.JSONDecodeError,
            ):
                return None, True
        elif isinstance(value, (bytes, bytearray, memoryview)):
            raw = bytes(value)
            if not raw or len(raw) % 4:
                return None, True
            embedding = tuple(struct.unpack(f"<{len(raw) // 4}f", raw))
        else:
            try:
                embedding = tuple(float(item) for item in value)
            except (TypeError, ValueError, OverflowError, RecursionError):
                return None, True
        if (
            len(embedding) > _MAX_EMBEDDING_DIMENSIONS
            or any(not math.isfinite(item) for item in embedding)
        ):
            return None, True
        if self._expired(deadline):
            raise _DeadlineExceeded
        return embedding, False

    def _normalize_embedding(
        self, embedding: tuple[float, ...] | None, deadline: int
    ) -> tuple[float, ...] | None:
        if embedding is None:
            return None
        scale = max((abs(value) for value in embedding), default=0.0)
        if not scale:
            return None
        squared = 0.0
        for index, value in enumerate(embedding):
            if index % (_TIME_CHECK_BATCH * 8) == 0 and self._expired(deadline):
                raise _DeadlineExceeded
            scaled = value / scale
            squared += scaled * scaled
        norm = math.sqrt(squared)
        normalized: list[float] = []
        for index, value in enumerate(embedding):
            if index % (_TIME_CHECK_BATCH * 8) == 0 and self._expired(deadline):
                raise _DeadlineExceeded
            normalized.append((value / scale) / norm)
        return tuple(normalized)

    def _pack(
        self,
        candidate_heap: list[tuple[float, str, _Candidate]],
        capacity: int,
        deadline: int,
    ) -> tuple[list[_Candidate], int, bool, bool]:
        selected: list[_Candidate] = []
        token_count = 0
        token_truncated = False
        comparisons = 0
        max_redundancy: dict[str, float | None] = {
            candidate.cell.id: None
            for _score, _cell_id, candidate in candidate_heap
        }
        if capacity <= 0:
            return selected, token_count, bool(candidate_heap), False

        while candidate_heap:
            best: _Candidate | None = None
            best_index = -1
            best_value = -math.inf
            for index, (_score, _cell_id, candidate) in enumerate(candidate_heap):
                if comparisons % (_TIME_CHECK_BATCH * 8) == 0 and self._expired(deadline):
                    return selected, token_count, True, True
                redundancy = max_redundancy[candidate.cell.id]
                penalty = 0.0 if redundancy is None else redundancy
                value = _MMR_LAMBDA * candidate.cell.score - (1.0 - _MMR_LAMBDA) * penalty
                if (
                    best is None
                    or value > best_value
                    or (value == best_value and candidate.cell.id < best.cell.id)
                ):
                    best = candidate
                    best_index = index
                    best_value = value
                comparisons += 1
            assert best is not None
            candidate_heap.pop(best_index)
            del max_redundancy[best.cell.id]
            if token_count + best.cell.token_count <= capacity:
                selected.append(best)
                token_count += best.cell.token_count
                if token_count == capacity and candidate_heap:
                    token_truncated = True
                    break
                for _score, _cell_id, candidate in candidate_heap:
                    if comparisons % (_TIME_CHECK_BATCH * 8) == 0 and self._expired(deadline):
                        return selected, token_count, True, True
                    similarity = self._similarity(candidate, best, deadline)
                    previous = max_redundancy[candidate.cell.id]
                    if previous is None or similarity > previous:
                        max_redundancy[candidate.cell.id] = similarity
                    comparisons += 1
            else:
                token_truncated = True
        return selected, token_count, token_truncated, False

    def _similarity(
        self, left: _Candidate, right: _Candidate, deadline: int
    ) -> float:
        if left.embedding is not None and right.embedding is not None:
            if len(left.embedding) == len(right.embedding) and left.embedding:
                dot = 0.0
                for index, (a, b) in enumerate(zip(left.embedding, right.embedding)):
                    if index % (_TIME_CHECK_BATCH * 8) == 0 and self._expired(deadline):
                        raise _DeadlineExceeded
                    dot += a * b
                left_norm = left.embedding_norm
                right_norm = right.embedding_norm
                if left_norm and right_norm:
                    cosine = dot / (left_norm * right_norm)
                    if math.isfinite(cosine):
                        return max(-1.0, min(1.0, cosine))
        if not left.words and not right.words:
            return 0.0
        overlap = 0
        union = 0
        for index, (key, left_count) in enumerate(left.words.items()):
            if index % (_TIME_CHECK_BATCH * 8) == 0 and self._expired(deadline):
                raise _DeadlineExceeded
            right_count = right.words.get(key, 0)
            overlap += min(left_count, right_count)
            union += max(left_count, right_count)
        for index, (key, right_count) in enumerate(right.words.items()):
            if index % (_TIME_CHECK_BATCH * 8) == 0 and self._expired(deadline):
                raise _DeadlineExceeded
            if key not in left.words:
                union += right_count
        return overlap / union if union else 0.0

    @staticmethod
    def _expired(deadline: int) -> bool:
        return time.monotonic_ns() >= deadline

    @staticmethod
    def _is_sql_interrupt(exc: sqlite3.OperationalError) -> bool:
        return (
            getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_INTERRUPT
            or str(exc).lower() == "interrupted"
        )


__all__ = [
    "CompileBudget",
    "CompiledCell",
    "CompiledCategory",
    "CategoryCompiler",
    "estimate_tokens",
    "valuation_v1",
]
