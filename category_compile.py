"""Bounded, deterministic compilation of an active category epoch."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
import heapq
import json
import math
import re
import struct
import time
from typing import Any

from categories import WeightVector


_MMR_LAMBDA = 0.75
_TIME_CHECK_BATCH = 32
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


@dataclass(frozen=True)
class CompiledCell:
    id: str
    content: str
    dimension: int
    score: float
    contributions: Mapping[str, float]
    hops: int
    token_count: int

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
        self.connection = getattr(store, "connection", None)
        if self.connection is None:
            self.connection = getattr(store, "conn", None)
        if self.connection is None:
            raise TypeError("category compiler requires a SQLite-backed store")
        limits = (
            self.budget.normal_target,
            self.budget.rotation_watermark,
            self.budget.hard_ceiling,
            self.budget.base_tokens,
            self.budget.max_depth,
            self.budget.max_neighbors,
            self.budget.max_candidates,
            self.budget.wall_time_ms,
        )
        if any(value < 0 for value in limits):
            raise ValueError("compile budget limits must be non-negative")

    def compile(
        self,
        epoch_id: str,
        context_id: str | None = None,
        seed_cell_ids: Sequence[str] = (),
        base_tokens: int | None = None,
    ) -> CompiledCategory:
        base = self.budget.base_tokens if base_tokens is None else base_tokens
        if base < 0:
            raise ValueError("base tokens must be non-negative")
        rotation_at_start = base >= self.budget.rotation_watermark
        if base >= self.budget.hard_ceiling:
            return CompiledCategory(
                epoch_id,
                context_id,
                (),
                0,
                0,
                bool(seed_cell_ids),
                rotation_at_start,
            )

        started = time.monotonic_ns()
        deadline = started + self.budget.wall_time_ms * 1_000_000
        candidate_heap: list[tuple[float, str, _Candidate]] = []
        queue: deque[tuple[str, int]] = deque()
        visited: set[str] = set()
        truncated = False
        stopped = False

        translated, lineage_truncated, timed_out = self._translate_seeds(
            epoch_id, seed_cell_ids, deadline
        )
        truncated |= lineage_truncated or timed_out
        if not timed_out:
            for index, cell_id in enumerate(translated):
                if index % _TIME_CHECK_BATCH == 0 and self._expired(deadline):
                    truncated = True
                    break
                admitted, cap_hit = self._admit(
                    cell_id, 0, context_id, queue, visited, candidate_heap
                )
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
            neighbors, neighbor_limited = self._neighbors(epoch_id, cell_id)
            truncated |= neighbor_limited
            unseen = [neighbor for neighbor in neighbors if neighbor not in visited]
            if hops >= self.budget.max_depth:
                if unseen:
                    truncated = True
                expansions += 1
                continue

            for neighbor in unseen:
                _admitted, cap_hit = self._admit(
                    neighbor,
                    hops + 1,
                    context_id,
                    queue,
                    visited,
                    candidate_heap,
                )
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

    def _translate_seeds(
        self, epoch_id: str, seed_cell_ids: Sequence[str], deadline: int
    ) -> tuple[tuple[str, ...], bool, bool]:
        bounded_seeds, truncated = self._bounded_seed_ids(seed_cell_ids)
        pending = deque(bounded_seeds)
        discovered = set(bounded_seeds)
        active: set[str] = set()
        steps = 0
        while pending:
            if steps % _TIME_CHECK_BATCH == 0 and self._expired(deadline):
                return tuple(sorted(active)), True, True
            cell_id = pending.popleft()
            if self._is_active(epoch_id, cell_id):
                active.add(cell_id)
            else:
                descendants = self._lineage_descendants(
                    epoch_id, cell_id, self.budget.max_candidates + 1
                )
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
        self, seed_cell_ids: Sequence[str]
    ) -> tuple[tuple[str, ...], bool]:
        """Keep the lexicographically first distinct seeds in bounded memory."""
        limit = self.budget.max_candidates
        selected: set[str] = set()
        largest_first: list[_ReverseId] = []
        overflow = False
        for cell_id in seed_cell_ids:
            if cell_id in selected:
                continue
            if len(selected) < limit:
                selected.add(cell_id)
                heapq.heappush(largest_first, _ReverseId(cell_id))
                continue
            overflow = True
            if limit and cell_id < largest_first[0].value:
                removed = heapq.heapreplace(largest_first, _ReverseId(cell_id))
                selected.remove(removed.value)
                selected.add(cell_id)
        return tuple(sorted(selected)), overflow

    def _is_active(self, epoch_id: str, cell_id: str) -> bool:
        row = self.connection.execute(
            """
            SELECT 1
            FROM cat_snapshots AS snapshot, json_each(snapshot.active_cell_ids_json) AS active
            WHERE snapshot.rowid = (
                SELECT MAX(rowid) FROM cat_snapshots WHERE epoch_id = ?
            ) AND active.value = ?
            LIMIT 1
            """,
            (epoch_id, cell_id),
        ).fetchone()
        return row is not None

    def _lineage_descendants(
        self, epoch_id: str, cell_id: str, limit: int
    ) -> tuple[str, ...]:
        if limit <= 0:
            return ()
        rows = self.connection.execute(
            """
            WITH RECURSIVE ancestors(id) AS (
                SELECT ?
                UNION
                SELECT parent.parent_id
                FROM cat_epoch_parents AS parent
                JOIN ancestors ON parent.epoch_id = ancestors.id
            )
            SELECT DISTINCT output.cell_id
            FROM cat_rewrite_members AS input
            JOIN cat_epochs AS epoch ON epoch.rewrite_id = input.rewrite_id
            JOIN ancestors ON ancestors.id = epoch.id
            JOIN cat_rewrite_members AS output
              ON output.rewrite_id = input.rewrite_id AND output.role = 'output'
            WHERE input.role = 'input' AND input.cell_id = ?
            ORDER BY output.cell_id
            LIMIT ?
            """,
            (epoch_id, cell_id, limit),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def _neighbors(self, epoch_id: str, cell_id: str) -> tuple[tuple[str, ...], bool]:
        limit = self.budget.max_neighbors + 1
        rows = self.connection.execute(
            """
            WITH latest(active_cell_ids_json) AS (
                SELECT active_cell_ids_json FROM cat_snapshots
                WHERE epoch_id = ? ORDER BY rowid DESC LIMIT 1
            ), active(id) AS (
                SELECT value FROM latest, json_each(latest.active_cell_ids_json)
            ), adjacent(id) AS (
                SELECT boundary.boundary_id
                FROM cat_boundaries AS boundary
                JOIN active ON active.id = boundary.boundary_id
                WHERE boundary.cell_id = ?
                UNION
                SELECT boundary.cell_id
                FROM cat_boundaries AS boundary
                JOIN active ON active.id = boundary.cell_id
                WHERE boundary.boundary_id = ?
            )
            SELECT id FROM adjacent ORDER BY id LIMIT ?
            """,
            (epoch_id, cell_id, cell_id, limit),
        ).fetchall()
        neighbors = tuple(str(row[0]) for row in rows)
        return neighbors[: self.budget.max_neighbors], len(neighbors) > self.budget.max_neighbors

    def _admit(
        self,
        cell_id: str,
        hops: int,
        context_id: str | None,
        queue: deque[tuple[str, int]],
        visited: set[str],
        candidate_heap: list[tuple[float, str, _Candidate]],
    ) -> tuple[bool, bool]:
        if cell_id in visited:
            return False, False
        if len(visited) >= self.budget.max_candidates:
            return False, True
        candidate = self._candidate(cell_id, hops, context_id)
        if candidate is not None and len(candidate_heap) >= self.budget.max_candidates:
            return False, True
        visited.add(cell_id)
        queue.append((cell_id, hops))
        if candidate is not None:
            heapq.heappush(
                candidate_heap,
                (candidate.cell.score, candidate.cell.id, candidate),
            )
        return True, False

    def _candidate(
        self, cell_id: str, hops: int, context_id: str | None
    ) -> _Candidate | None:
        row = self.connection.execute(
            "SELECT id, content, dimension FROM cat_cells WHERE id = ?",
            (cell_id,),
        ).fetchone()
        if row is None or int(row["dimension"]) > 2:
            return None
        if not self.store.is_interpretable(cell_id):
            return None
        weights = self._latest_weight(cell_id, context_id)
        score, parts = valuation_v1(weights)
        content = str(row["content"])
        compiled = CompiledCell(
            id=str(row["id"]),
            content=content,
            dimension=int(row["dimension"]),
            score=score,
            contributions=parts,
            hops=hops,
            token_count=estimate_tokens(content),
        )
        return _Candidate(
            compiled,
            self._embedding(cell_id),
            Counter(_WORD_RE.findall(content.lower())),
        )

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

    def _embedding(self, cell_id: str) -> tuple[float, ...] | None:
        table = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'cat_vectors' LIMIT 1"
        ).fetchone()
        if table is None:
            return None
        try:
            row = self.connection.execute(
                "SELECT embedding FROM cat_vectors WHERE cell_id = ?", (cell_id,)
            ).fetchone()
        except Exception:
            return None
        if row is None or row[0] is None:
            return None
        value = row[0]
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
                return tuple(float(item) for item in decoded)
            except (TypeError, ValueError, json.JSONDecodeError):
                return None
        if isinstance(value, (bytes, bytearray, memoryview)):
            raw = bytes(value)
            if not raw or len(raw) % 4:
                return None
            return tuple(struct.unpack(f"<{len(raw) // 4}f", raw))
        try:
            return tuple(float(item) for item in value)
        except (TypeError, ValueError):
            return None

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
        if capacity <= 0:
            return selected, token_count, bool(candidate_heap), False

        while candidate_heap:
            best: _Candidate | None = None
            best_index = -1
            best_value = -math.inf
            for index, (_score, _cell_id, candidate) in enumerate(candidate_heap):
                if comparisons % (_TIME_CHECK_BATCH * 8) == 0 and self._expired(deadline):
                    return selected, token_count, True, True
                redundancy = -math.inf if selected else 0.0
                for prior in selected:
                    if comparisons % (_TIME_CHECK_BATCH * 8) == 0 and self._expired(deadline):
                        return selected, token_count, True, True
                    redundancy = max(redundancy, self._similarity(candidate, prior))
                    comparisons += 1
                value = _MMR_LAMBDA * candidate.cell.score - (1.0 - _MMR_LAMBDA) * redundancy
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
            if token_count + best.cell.token_count <= capacity:
                selected.append(best)
                token_count += best.cell.token_count
                if token_count == capacity and candidate_heap:
                    token_truncated = True
                    break
            else:
                token_truncated = True
        return selected, token_count, token_truncated, False

    @staticmethod
    def _similarity(left: _Candidate, right: _Candidate) -> float:
        if left.embedding is not None and right.embedding is not None:
            if len(left.embedding) == len(right.embedding) and left.embedding:
                dot = sum(a * b for a, b in zip(left.embedding, right.embedding))
                left_norm = math.sqrt(sum(value * value for value in left.embedding))
                right_norm = math.sqrt(sum(value * value for value in right.embedding))
                if left_norm and right_norm:
                    return dot / (left_norm * right_norm)
        keys = left.words.keys() | right.words.keys()
        if not keys:
            return 0.0
        overlap = sum(min(left.words[key], right.words[key]) for key in keys)
        union = sum(max(left.words[key], right.words[key]) for key in keys)
        return overlap / union if union else 0.0

    @staticmethod
    def _expired(deadline: int) -> bool:
        return time.monotonic_ns() >= deadline


__all__ = [
    "CompileBudget",
    "CompiledCell",
    "CompiledCategory",
    "CategoryCompiler",
    "estimate_tokens",
    "valuation_v1",
]
