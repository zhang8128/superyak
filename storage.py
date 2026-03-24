"""Engram storage layer — SQLite with vec0 vectors, FTS5, and temporal relationships."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("engram.storage")


def vec0_distance_to_similarity(distance: float) -> float:
    """Convert vec0 L2 distance to 0-1 similarity score.

    For unit vectors: L2^2 = 2(1 - cos_sim), so cos_sim = 1 - L2^2/2.
    """
    return max(0.0, min(1.0, 1.0 - (distance * distance) / 2.0))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pack_embedding(embedding: list[float]) -> bytes:
    """Pack a float list into little-endian float32 bytes for vec0."""
    return struct.pack(f"<{len(embedding)}f", *embedding)


def _sanitize_fts_query(query: str) -> str:
    """Escape a natural-language query for FTS5 MATCH.

    Wraps each token in double quotes so special characters and reserved
    words (OR, AND, NOT) are treated as literals.
    """
    tokens = query.split()
    if not tokens:
        return '""'
    # Double-quote each token; escape any internal double quotes
    return " ".join(f'"{t.replace(chr(34), chr(34)+chr(34))}"' for t in tokens)


class Storage:
    """SQLite-backed storage for entities, relationships, episodes, and vectors."""

    def __init__(self, db_path: str, migrations_dir: str | None = None):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

        # Load sqlite-vec extension
        self.conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)

        # Set pragmas
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA synchronous=NORMAL")

        # Run migrations
        if migrations_dir is None:
            migrations_dir = str(Path(__file__).resolve().parent / "migrations")
        self._migrations_dir = migrations_dir
        self._run_migrations()

        # Verify vec0 tables are healthy — rebuild if WAL recovery corrupted them
        self._check_vec0_health()

    def _run_migrations(self) -> None:
        """Apply any unapplied SQL migrations from the migrations directory."""
        # Ensure schema_version exists (bootstrap)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        self.conn.commit()

        row = self.conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        current = row[0] if row[0] is not None else 0

        mig_dir = Path(self._migrations_dir)
        if not mig_dir.exists():
            return

        # Find migration files sorted by version number
        pattern = re.compile(r"^(\d+)_.*\.sql$")
        migrations = []
        for f in sorted(mig_dir.iterdir()):
            m = pattern.match(f.name)
            if m:
                ver = int(m.group(1))
                if ver > current:
                    migrations.append((ver, f))

        for ver, path in sorted(migrations):
            sql = path.read_text()
            self.conn.executescript(sql)
            # executescript resets pragmas — restore them
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (ver, _now_iso()),
            )
            self.conn.commit()
            logger.info("Migration %d applied: %s", ver, path.name)
            if ver == 7:
                self._backfill_content_hashes()

    def _backfill_content_hashes(self) -> None:
        """One-time backfill of content_hash for pre-federation rows."""
        for table, col in [("episodes", "content"), ("semantics", "content"), ("instincts", "action")]:
            # Guard against tables that don't exist yet on a fresh DB
            exists = self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                continue
            rows = self.conn.execute(
                f"SELECT id, {col} FROM {table} WHERE content_hash IS NULL"
            ).fetchall()
            for row in rows:
                h = hashlib.sha256(row[col].encode()).hexdigest()
                self.conn.execute(
                    f"UPDATE {table} SET content_hash = ? WHERE id = ?", (h, row["id"])
                )
        self.conn.commit()

    _VEC0_TABLES = ("entity_vectors", "episode_vectors", "semantic_vectors", "instinct_vectors")

    def _check_vec0_health(self) -> None:
        """Probe each vec0 table with a no-op query. Rebuild any that are corrupt.

        vec0 tables don't survive WAL recovery after unclean shutdown.
        When corruption is detected, we nuke all remnants (shadow tables +
        sqlite_master entry via writable_schema), reconnect, and recreate.
        """
        corrupt = []
        for vec_table in self._VEC0_TABLES:
            try:
                exists = self.conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (vec_table,),
                ).fetchone()
                if not exists:
                    continue
                self.conn.execute(f"SELECT count(*) FROM {vec_table}").fetchone()
            except Exception:
                logger.warning("vec0 table %s is corrupt", vec_table)
                corrupt.append(vec_table)

        if not corrupt:
            return

        # Clean up all corrupt tables, then reconnect
        for vec_table in corrupt:
            self._nuke_vec0_remnants(vec_table)

        # Must reconnect for sqlite_master changes to take effect
        self.conn.close()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA synchronous=NORMAL")

        # Detect dimension from a healthy vec0 table, fallback to 768
        dim = 768
        for vec_table in self._VEC0_TABLES:
            if vec_table not in corrupt:
                try:
                    info = self.conn.execute(
                        f"SELECT * FROM {vec_table} LIMIT 0"
                    ).description
                    # If we can query it, check its embedding column
                    # vec0 tables encode dimension in schema; read from sqlite_master
                    row = self.conn.execute(
                        "SELECT sql FROM sqlite_master WHERE name=?", (vec_table,)
                    ).fetchone()
                    if row and row[0]:
                        import re
                        m = re.search(r"float\[(\d+)\]", row[0])
                        if m:
                            dim = int(m.group(1))
                            break
                except Exception:
                    pass

        # Recreate the tables
        for vec_table in corrupt:
            try:
                self.conn.execute(
                    f"CREATE VIRTUAL TABLE {vec_table} USING vec0("
                    f"id TEXT PRIMARY KEY, embedding float[{dim}])"
                )
                self.conn.commit()
                logger.warning(
                    "Rebuilt %s — vectors lost, will be re-embedded on next write/reindex",
                    vec_table,
                )
            except Exception:
                logger.error("Failed to rebuild %s", vec_table, exc_info=True)

    def _nuke_vec0_remnants(self, vec_table: str) -> None:
        """Remove all traces of a vec0 table: shadow tables + sqlite_master entry."""
        # Drop shadow tables (e.g. _chunks, _rowids, _info, _vector_chunks00)
        shadow_rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
            (f"{vec_table}_%",),
        ).fetchall()
        for (shadow_name,) in shadow_rows:
            try:
                self.conn.execute(f"DROP TABLE IF EXISTS [{shadow_name}]")
            except Exception:
                pass
        # Remove the parent virtual table entry that can't be DROP'd normally
        self.conn.execute("PRAGMA writable_schema=ON")
        self.conn.execute(
            "DELETE FROM sqlite_master WHERE name=?", (vec_table,)
        )
        self.conn.execute("PRAGMA writable_schema=OFF")
        self.conn.commit()

    def close(self) -> None:
        """Checkpoint WAL and close. Prevents vec0 corruption on unclean restart."""
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            logger.warning("WAL checkpoint failed on close", exc_info=True)
        self.conn.close()

    # --- Entities ---

    def add_entity(
        self,
        id: str,
        name: str,
        entity_type: str,
        description: str | None = None,
        metadata: dict | None = None,
        embedding: list[float] | None = None,
    ) -> str:
        now = _now_iso()
        self.conn.execute(
            "INSERT INTO entities (id, name, entity_type, description, metadata, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id, name, entity_type, description, json.dumps(metadata) if metadata else None, now, now),
        )
        if embedding is not None:
            self.conn.execute(
                "INSERT INTO entity_vectors (id, embedding) VALUES (?, ?)",
                (id, _pack_embedding(embedding)),
            )
        self.conn.commit()
        logger.debug("Entity added: %s (type=%s)", name, entity_type)
        return id

    def get_entity(self, id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM entities WHERE id = ?", (id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    _ENTITY_COLUMNS = frozenset({"name", "entity_type", "description", "metadata", "updated_at"})

    def update_entity(self, id: str, **fields) -> None:
        if not fields:
            return
        # Validate column names to prevent SQL injection
        invalid = set(fields) - self._ENTITY_COLUMNS - {"updated_at"}
        if invalid:
            raise ValueError(f"Invalid entity columns: {invalid}")
        fields["updated_at"] = _now_iso()
        if "metadata" in fields and isinstance(fields["metadata"], dict):
            fields["metadata"] = json.dumps(fields["metadata"])
        cols = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [id]
        self.conn.execute(f"UPDATE entities SET {cols} WHERE id = ?", vals)
        self.conn.commit()

    def delete_entity(self, id: str) -> None:
        # Delete from vec0 table (not covered by CASCADE)
        self.conn.execute("DELETE FROM entity_vectors WHERE id = ?", (id,))
        self.conn.execute("DELETE FROM entities WHERE id = ?", (id,))
        self.conn.commit()

    # --- Relationships ---

    def add_relationship(
        self,
        id: str,
        source_id: str,
        target_id: str,
        rel_type: str,
        description: str | None = None,
        weight: float = 1.0,
        valid_from: str | None = None,
    ) -> str:
        now = _now_iso()
        self.conn.execute(
            "INSERT INTO relationships (id, source_id, target_id, rel_type, description, weight, valid_from, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id, source_id, target_id, rel_type, description, weight, valid_from or now, now),
        )
        self.conn.commit()
        logger.debug("Relationship added: %s -> %s (%s)", source_id, target_id, rel_type)
        return id

    def invalidate_relationship(self, id: str, reason: str | None = None) -> bool:
        """Mark a relationship as invalid. Returns True if found and invalidated, False if not found."""
        now = _now_iso()
        cursor = self.conn.execute(
            "UPDATE relationships SET invalid_at = ? WHERE id = ? AND invalid_at IS NULL",
            (now, id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_relationships(self, entity_id: str, valid_only: bool = True) -> list[dict]:
        validity_clause = "AND invalid_at IS NULL" if valid_only else ""
        rows = self.conn.execute(
            f"SELECT * FROM relationships WHERE (source_id = ? OR target_id = ?) {validity_clause}",
            (entity_id, entity_id),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Episodes ---

    def add_episode(
        self,
        id: str,
        session_id: str | None,
        content: str,
        episode_type: str | None = None,
        embedding: list[float] | None = None,
        entity_ids: list[str] | None = None,
        context: dict | None = None,
    ) -> str:
        now = _now_iso()
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        self.conn.execute(
            "INSERT INTO episodes (id, session_id, content, episode_type, context, created_at, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id, session_id, content, episode_type, json.dumps(context) if context is not None else None, now, content_hash),
        )
        if embedding is not None:
            self.conn.execute(
                "INSERT INTO episode_vectors (id, embedding) VALUES (?, ?)",
                (id, _pack_embedding(embedding)),
            )
        if entity_ids:
            self.conn.executemany(
                "INSERT INTO episode_entities (episode_id, entity_id) VALUES (?, ?)",
                [(id, eid) for eid in entity_ids],
            )
        self.conn.commit()
        logger.debug("Episode added: %s (entities=%d)", id, len(entity_ids) if entity_ids else 0)
        return id

    def mark_episodes_compressed(self, ids: list[str]) -> None:
        """Mark episodes as compressed."""
        if not ids:
            return
        placeholders = ", ".join("?" * len(ids))
        self.conn.execute(
            f"UPDATE episodes SET compressed = 1 WHERE id IN ({placeholders})",
            ids,
        )
        self.conn.commit()

    def get_uncompressed_episodes(self) -> list[dict]:
        """Return all episodes that have not been compressed."""
        rows = self.conn.execute(
            "SELECT * FROM episodes WHERE compressed = 0"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_episode(self, id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM episodes WHERE id = ?", (id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def increment_episode_access(self, id: str) -> None:
        """Increment accessed_count, update last_accessed, and boost decay strength."""
        self.conn.execute(
            "UPDATE episodes SET accessed_count = accessed_count + 1, "
            "last_accessed = ?, "
            "decay_strength = MIN(1.0, decay_strength + 0.1) "
            "WHERE id = ?",
            (_now_iso(), id),
        )
        self.conn.commit()

    def apply_decay(self, factor: float = 0.9, min_interval_minutes: int = 30) -> int:
        """Apply global decay to all episode strengths. Returns count affected.

        Implements Ebbinghaus-style forgetting: episodes that aren't accessed
        weaken over time. Episodes accessed during recall get boosted by
        increment_episode_access().

        Rate-limited: skips decay if the last session_start was less than
        min_interval_minutes ago, preventing rapid session restarts from
        compounding decay into accidental erasure.
        """
        # Rate-limit: check last session_start timestamp
        row = self.conn.execute(
            "SELECT timestamp FROM memory_log "
            "WHERE event_type = 'session_start' "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if row:
            from datetime import datetime, timezone
            last_start = datetime.fromisoformat(row[0])
            elapsed = (datetime.now(timezone.utc) - last_start).total_seconds()
            if elapsed < min_interval_minutes * 60:
                logger.info(
                    "Decay skipped — last session was %d seconds ago (minimum %d minutes)",
                    int(elapsed), min_interval_minutes,
                )
                return 0

        cursor = self.conn.execute(
            "UPDATE episodes SET decay_strength = MAX(0.0, decay_strength * ?) "
            "WHERE decay_strength > 0.01 AND core = 0",
            (factor,),
        )
        self.conn.commit()
        count = cursor.rowcount
        logger.debug("Decay applied (factor=%.2f): %d episodes affected", factor, count)
        return count

    def prune_decayed(self, threshold: float = 0.05) -> int:
        """Delete episodes that have decayed below threshold.

        Only prunes episodes that are already compressed — uncompressed
        episodes are preserved regardless of decay.
        """
        # Get IDs first for vec0 cleanup
        rows = self.conn.execute(
            "SELECT id FROM episodes WHERE decay_strength < ? AND compressed = 1 AND core = 0",
            (threshold,),
        ).fetchall()
        ids = [r[0] for r in rows]
        if not ids:
            return 0

        placeholders = ", ".join("?" * len(ids))
        # Clean up vectors, FTS handled by trigger
        self.conn.execute(
            f"DELETE FROM episode_vectors WHERE id IN ({placeholders})", ids
        )
        self.conn.execute(
            f"DELETE FROM episodes WHERE id IN ({placeholders})", ids
        )
        self.conn.commit()
        logger.info("Pruned %d decayed episodes (threshold=%.3f)", len(ids), threshold)
        return len(ids)

    def boost_episode_strength(self, id: str, boost: float = 0.1) -> None:
        """Boost an episode's decay strength on access (counteracts decay)."""
        self.conn.execute(
            "UPDATE episodes SET decay_strength = MIN(1.0, decay_strength + ?) WHERE id = ?",
            (boost, id),
        )
        self.conn.commit()

    def get_orphaned_episodes(self) -> list[dict]:
        """Find episodes that have no vector embedding (invisible to search)."""
        rows = self.conn.execute(
            "SELECT e.id, e.content FROM episodes e "
            "LEFT JOIN episode_vectors v ON e.id = v.id "
            "WHERE v.id IS NULL"
        ).fetchall()
        return [{"id": r[0], "content": r[1]} for r in rows]

    def get_orphaned_semantics(self) -> list[dict]:
        """Find semantics that have no vector embedding (invisible to search)."""
        rows = self.conn.execute(
            "SELECT s.id, s.content FROM semantics s "
            "LEFT JOIN semantic_vectors v ON s.id = v.id "
            "WHERE v.id IS NULL"
        ).fetchall()
        return [{"id": r[0], "content": r[1]} for r in rows]

    def mark_core(self, episode_id: str, tier: int = 1) -> None:
        """Mark an episode as core — exempt from decay, preserved indefinitely.

        tier=1: local core (no decay)
        tier=2: genome core (no decay, replicates)
        """
        self.conn.execute(
            "UPDATE episodes SET core = ?, decay_strength = 1.0 WHERE id = ?",
            (tier, episode_id),
        )
        self.conn.commit()

    def unmark_core(self, episode_id: str) -> None:
        """Demote a core episode back to normal — re-enables decay."""
        self.conn.execute(
            "UPDATE episodes SET core = 0 WHERE id = ?",
            (episode_id,),
        )
        self.conn.commit()

    def unmark_core_batch(self, episode_ids: list[str]) -> int:
        """Demote multiple core episodes. Returns count updated."""
        if not episode_ids:
            return 0
        placeholders = ", ".join("?" * len(episode_ids))
        cursor = self.conn.execute(
            f"UPDATE episodes SET core = 0 WHERE id IN ({placeholders})",
            episode_ids,
        )
        self.conn.commit()
        return cursor.rowcount

    def mark_core_batch(self, episode_ids: list[str], tier: int = 1) -> int:
        """Mark multiple episodes as core. Returns count updated.

        tier=1: local core (no decay)
        tier=2: genome core (no decay, replicates)
        """
        if not episode_ids:
            return 0
        placeholders = ", ".join("?" * len(episode_ids))
        cursor = self.conn.execute(
            f"UPDATE episodes SET core = ?, decay_strength = 1.0 "
            f"WHERE id IN ({placeholders})",
            [tier, *episode_ids],
        )
        self.conn.commit()
        return cursor.rowcount

    def get_core_episodes(self) -> list[dict]:
        """Return all core episodes (tier 1 and tier 2)."""
        rows = self.conn.execute(
            "SELECT id, content, source, created_at FROM episodes WHERE core >= 1 "
            "ORDER BY created_at"
        ).fetchall()
        return [{"id": r[0], "content": r[1], "source": r[2], "created_at": r[3]} for r in rows]

    def set_episode_source(self, episode_id: str, source: str) -> None:
        """Tag an episode with its cross-system provenance."""
        self.conn.execute(
            "UPDATE episodes SET source = ? WHERE id = ?",
            (source, episode_id),
        )
        self.conn.commit()

    def search_episode_fts(self, query: str) -> list[str]:
        """Full-text search on episode content. Returns episode IDs."""
        safe_query = _sanitize_fts_query(query)
        rows = self.conn.execute(
            "SELECT e.id FROM episode_fts f JOIN episodes e ON f.rowid = e.rowid "
            "WHERE episode_fts MATCH ?",
            (safe_query,),
        ).fetchall()
        logger.debug("Episode FTS search for %r: found=%d", query, len(rows))
        return [row[0] for row in rows]

    # --- Semantics ---

    def add_semantic(
        self,
        id: str,
        content: str,
        kind: str,
        confidence: float,
        embedding: list[float],
        source_episode_ids: list[str],
        auto_generated: bool = False,
    ) -> str:
        now = _now_iso()
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        self.conn.execute(
            "INSERT INTO semantics (id, content, kind, confidence, created_at, auto_generated, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id, content, kind, confidence, now, 1 if auto_generated else 0, content_hash),
        )
        self.conn.execute(
            "INSERT INTO semantic_vectors (id, embedding) VALUES (?, ?)",
            (id, _pack_embedding(embedding)),
        )
        if source_episode_ids:
            self.conn.executemany(
                "INSERT INTO semantic_sources (semantic_id, episode_id) VALUES (?, ?)",
                [(id, eid) for eid in source_episode_ids],
            )
        self.conn.commit()
        logger.debug("Semantic added: %s (kind=%s)", id, kind)
        return id

    def get_semantic(self, id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM semantics WHERE id = ?", (id,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        source_rows = self.conn.execute(
            "SELECT episode_id FROM semantic_sources WHERE semantic_id = ?", (id,)
        ).fetchall()
        result["source_episode_ids"] = [r[0] for r in source_rows]
        return result

    def reinforce_semantic(self, id: str, additional_episode_ids: list[str]) -> None:
        self.conn.execute(
            "UPDATE semantics SET confidence = MIN(1.0, confidence + 0.1), "
            "reinforced_count = reinforced_count + 1, last_reinforced = ? WHERE id = ?",
            (_now_iso(), id),
        )
        if additional_episode_ids:
            self.conn.executemany(
                "INSERT OR IGNORE INTO semantic_sources (semantic_id, episode_id) VALUES (?, ?)",
                [(id, eid) for eid in additional_episode_ids],
            )
        self.conn.commit()

    def contradict_semantic(self, id: str, contradicted_by: str) -> None:
        self.conn.execute(
            "UPDATE semantics SET contradicted_by = ? WHERE id = ?",
            (contradicted_by, id),
        )
        self.conn.commit()

    def search_semantic_fts(self, query: str) -> list[str]:
        """Full-text search on semantic content. Returns semantic IDs."""
        safe_query = _sanitize_fts_query(query)
        rows = self.conn.execute(
            "SELECT s.id FROM semantic_fts f JOIN semantics s ON f.rowid = s.rowid "
            "WHERE semantic_fts MATCH ?",
            (safe_query,),
        ).fetchall()
        logger.debug("Semantic FTS search for %r: found=%d", query, len(rows))
        return [row[0] for row in rows]

    def get_active_semantics(self, kind: str | None = None, limit: int = 100) -> list[dict]:
        """Return semantics that have not been contradicted, ordered by confidence desc."""
        if kind is not None:
            rows = self.conn.execute(
                "SELECT * FROM semantics WHERE contradicted_by IS NULL AND kind = ? "
                "ORDER BY confidence DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM semantics WHERE contradicted_by IS NULL "
                "ORDER BY confidence DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- Vector search ---

    _VECTOR_TABLES = frozenset({"entity", "episode", "semantic", "instinct", "instinct_context"})

    def search_vectors(self, table_name: str, embedding: list[float], k: int = 10) -> list[tuple[str, float]]:
        """KNN search on a vec0 virtual table. table_name: 'entity', 'episode', or 'semantic'."""
        if table_name not in self._VECTOR_TABLES:
            raise ValueError(f"Invalid vector table: {table_name}. Must be one of {self._VECTOR_TABLES}")
        rows = self.conn.execute(
            f"SELECT id, distance FROM {table_name}_vectors WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (_pack_embedding(embedding), k),
        ).fetchall()
        logger.debug("Vector search on %s_vectors: k=%d, found=%d", table_name, k, len(rows))
        return [(row[0], row[1]) for row in rows]

    def sample_distant_memories(
        self,
        query_embedding: list[float],
        exclude_ids: set[str],
        k: int = 3,
        layers: tuple[str, ...] | None = None,
    ) -> list[tuple[str, str, float]]:
        """Sample k random memories from the bottom 50% by similarity to query.

        Searches episode, semantic, and instinct vector tables (or subset via layers).
        Returns list of (id, layer, distance) tuples.
        """
        import random

        search_layers = layers or ("episode", "semantic", "instinct")
        # Gather candidates from memory layers with large k
        all_candidates: list[tuple[str, str, float]] = []  # (id, layer, distance)
        for layer in search_layers:
            try:
                results = self.search_vectors(layer, query_embedding, k=200)
                for rid, dist in results:
                    if rid not in exclude_ids:
                        all_candidates.append((rid, layer, dist))
            except Exception:
                logger.warning("Distant sample: %s vector search failed", layer, exc_info=True)

        if not all_candidates:
            return []

        # Sort by distance descending (most distant first)
        all_candidates.sort(key=lambda x: x[2], reverse=True)

        # Take the top 50% (most distant half)
        distant_pool = all_candidates[: max(1, len(all_candidates) // 2)]

        # Random sample
        sample_size = min(k, len(distant_pool))
        return random.sample(distant_pool, sample_size)

    # --- FTS ---

    def search_fts(self, query: str) -> list[str]:
        """Full-text search on entity names/descriptions. Returns entity IDs."""
        safe_query = _sanitize_fts_query(query)
        rows = self.conn.execute(
            "SELECT e.id FROM entity_fts f JOIN entities e ON f.rowid = e.rowid "
            "WHERE entity_fts MATCH ?",
            (safe_query,),
        ).fetchall()
        logger.debug("FTS search for %r: found=%d", query, len(rows))
        return [row[0] for row in rows]

    # --- Graph traversal ---

    def traverse(self, start_id: str, max_depth: int = 2, valid_only: bool = True) -> list[dict]:
        """Bidirectional recursive CTE traversal from start_id."""
        validity = "AND r.invalid_at IS NULL" if valid_only else ""
        sql = f"""
        WITH RECURSIVE connected AS (
            SELECT target_id AS id, 1 AS depth, rel_type, source_id AS from_id
            FROM relationships WHERE source_id = :start_id {validity.replace('r.', '')}
            UNION
            SELECT source_id AS id, 1 AS depth, rel_type, target_id AS from_id
            FROM relationships WHERE target_id = :start_id {validity.replace('r.', '')}
            UNION ALL
            SELECT r.target_id, c.depth + 1, r.rel_type, r.source_id
            FROM relationships r JOIN connected c ON r.source_id = c.id
            WHERE c.depth < :max_depth {validity} AND r.target_id != c.from_id
            UNION ALL
            SELECT r.source_id, c.depth + 1, r.rel_type, r.target_id
            FROM relationships r JOIN connected c ON r.target_id = c.id
            WHERE c.depth < :max_depth {validity} AND r.source_id != c.from_id
        )
        SELECT DISTINCT e.*, c.depth, c.rel_type FROM entities e JOIN connected c ON e.id = c.id
        """
        rows = self.conn.execute(sql, {"start_id": start_id, "max_depth": max_depth}).fetchall()
        logger.debug("Traverse from %s (depth=%d): found=%d", start_id, max_depth, len(rows))
        return [dict(r) for r in rows]

    # --- Instincts ---

    def add_instinct(
        self,
        id: str,
        trigger: str,
        action: str,
        source_semantic_ids: list[str],
        strength: float = 0.5,
        embedding: list[float] | None = None,
        notice: str | None = None,
        implication: str | None = None,
    ) -> str:
        now = _now_iso()
        content_hash = hashlib.sha256(action.encode()).hexdigest()
        self.conn.execute(
            "INSERT INTO instincts (id, trigger, action, strength, created_at, fired_count, followed_count, overridden_count, content_hash, notice, implication) "
            "VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, ?, ?)",
            (id, trigger, action, strength, now, content_hash, notice, implication),
        )
        if embedding is not None:
            self.conn.execute(
                "INSERT INTO instinct_vectors (id, embedding) VALUES (?, ?)",
                (id, _pack_embedding(embedding)),
            )
        if source_semantic_ids:
            # Filter to only semantics that actually exist (FK-safe insert)
            existing = {
                row[0]
                for row in self.conn.execute(
                    "SELECT id FROM semantics WHERE id IN ({})".format(
                        ",".join("?" * len(source_semantic_ids))
                    ),
                    source_semantic_ids,
                ).fetchall()
            }
            valid_ids = [sid for sid in source_semantic_ids if sid in existing]
            if valid_ids:
                self.conn.executemany(
                    "INSERT INTO instinct_sources (instinct_id, semantic_id) VALUES (?, ?)",
                    [(id, sid) for sid in valid_ids],
                )
        self.conn.commit()
        logger.debug("Instinct added: %s (trigger=%r)", id, trigger)
        return id

    def get_instinct(self, id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM instincts WHERE id = ?", (id,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        source_rows = self.conn.execute(
            "SELECT semantic_id FROM instinct_sources WHERE instinct_id = ?", (id,)
        ).fetchall()
        result["source_semantic_ids"] = [r[0] for r in source_rows]
        return result

    def get_all_instincts(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM instincts ORDER BY strength DESC"
        ).fetchall()
        results = []
        for r in rows:
            inst = dict(r)
            source_rows = self.conn.execute(
                "SELECT semantic_id FROM instinct_sources WHERE instinct_id = ?",
                (inst["id"],),
            ).fetchall()
            inst["source_semantic_ids"] = [sr[0] for sr in source_rows]
            results.append(inst)
        return results

    def add_instinct_context_feedback(
        self,
        instinct_id: str,
        context_text: str,
        context_embedding: bytes | None,
        followed: bool,
    ) -> str:
        """Store context-specific feedback for an instinct."""
        import uuid as _uuid
        id = str(_uuid.uuid4())
        now = _now_iso()
        self.conn.execute(
            "INSERT INTO instinct_context_feedback (id, instinct_id, context_text, context_embedding, followed, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id, instinct_id, context_text, context_embedding, followed, now),
        )
        self.conn.commit()
        logger.debug("Context feedback stored: instinct=%s followed=%s", instinct_id, followed)
        return id

    def get_instinct_context_feedback(self, instinct_id: str) -> list[dict]:
        """Get all context feedback entries for an instinct."""
        rows = self.conn.execute(
            "SELECT * FROM instinct_context_feedback WHERE instinct_id = ? ORDER BY timestamp",
            (instinct_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_context_follow_ratio(self, instinct_id: str, context_text: str) -> float:
        """Get the followed/total ratio for feedback matching a context."""
        rows = self.conn.execute(
            "SELECT followed FROM instinct_context_feedback WHERE instinct_id = ? AND context_text = ?",
            (instinct_id, context_text),
        ).fetchall()
        if not rows:
            return 0.0
        total = len(rows)
        followed_count = sum(1 for r in rows if r[0])
        return followed_count / total

    def add_instinct_context_vector(self, id: str, embedding: list[float]) -> None:
        """Store a context vector for an instinct."""
        self.conn.execute(
            "INSERT INTO instinct_context_vectors (id, embedding) VALUES (?, ?)",
            (id, _pack_embedding(embedding)),
        )
        self.conn.commit()
        logger.debug("Instinct context vector stored: %s", id)

    def update_instinct_followed(self, id: str) -> None:
        self.conn.execute(
            "UPDATE instincts SET strength = MIN(1.0, strength + 0.05), "
            "followed_count = followed_count + 1, fired_count = fired_count + 1 "
            "WHERE id = ?",
            (id,),
        )
        self.conn.commit()

    def update_instinct_overridden(self, id: str) -> None:
        self.conn.execute(
            "UPDATE instincts SET strength = MAX(0.0, strength - 0.05), "
            "overridden_count = overridden_count + 1, fired_count = fired_count + 1 "
            "WHERE id = ?",
            (id,),
        )
        self.conn.commit()

    def prune_weak_instincts(self, strength_threshold: float = 0.1) -> int:
        """Remove instincts that have weakened below threshold.

        Instincts start at 0.5 and lose 0.05 per override. An instinct
        at 0.1 has been overridden ~8 times — it's not serving the system.
        """
        rows = self.conn.execute(
            "SELECT id FROM instincts WHERE strength <= ?",
            (strength_threshold,),
        ).fetchall()
        ids = [r[0] for r in rows]
        if not ids:
            return 0

        placeholders = ", ".join("?" * len(ids))
        self.conn.execute(f"DELETE FROM instinct_vectors WHERE id IN ({placeholders})", ids)
        self.conn.execute(f"DELETE FROM instinct_sources WHERE instinct_id IN ({placeholders})", ids)
        # Clean up context vectors (vec0 doesn't cascade)
        for iid in ids:
            self.conn.execute("DELETE FROM instinct_context_vectors WHERE id = ?", (iid,))
        # Clean up context feedback
        for iid in ids:
            self.conn.execute("DELETE FROM instinct_context_feedback WHERE instinct_id = ?", (iid,))
        self.conn.execute(f"DELETE FROM instincts WHERE id IN ({placeholders})", ids)
        self.conn.commit()
        logger.info("Pruned %d weak instincts (threshold=%.2f)", len(ids), strength_threshold)
        return len(ids)

    # --- Memory Log ---

    def add_log_entry(
        self,
        id: str,
        event_type: str,
        layer: str,
        target_ids: list[str],
        context: dict | None = None,
        outcome: str | None = None,
    ) -> str:
        self.conn.execute(
            "INSERT INTO memory_log (id, timestamp, event_type, layer, target_ids, context, outcome) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                id,
                _now_iso(),
                event_type,
                layer,
                json.dumps(target_ids),
                json.dumps(context) if context is not None else None,
                outcome,
            ),
        )
        self.conn.commit()
        logger.debug("Log entry added: %s (event_type=%s, layer=%s)", id, event_type, layer)
        return id

    def get_log_entries(
        self,
        event_type: str | None = None,
        layer: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        conditions = []
        params: list = []
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)
        if layer is not None:
            conditions.append("layer = ?")
            params.append(layer)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM memory_log {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def update_log_outcome(self, recall_id: str, outcome: str) -> None:
        self.conn.execute(
            "UPDATE memory_log SET outcome = ? WHERE json_extract(context, '$.recall_id') = ?",
            (outcome, recall_id),
        )
        self.conn.commit()

    # --- Table counts ---

    _ALLOWED_TABLES = frozenset({
        "entities", "relationships", "episodes", "episode_entities",
        "semantics", "instincts", "memory_log", "semantic_sources", "instinct_sources",
    })

    def get_table_count(self, table_name: str) -> int:
        if table_name not in self._ALLOWED_TABLES:
            raise ValueError(f"Invalid table name: {table_name}. Must be one of {self._ALLOWED_TABLES}")
        row = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
        return row[0]

    # --- Meta ---

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    # --- Task Contexts ---

    def get_active_task_context(self) -> dict | None:
        """Return the currently active task context, or None."""
        row = self.conn.execute(
            "SELECT * FROM task_contexts WHERE status = 'active' ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def set_task_context(self, id: str, name: str, content: str) -> None:
        """Create or update a task context, making it active. Archives any other active context."""
        now = _now_iso()
        # Archive any currently active context
        self.conn.execute(
            "UPDATE task_contexts SET status = 'archived', updated_at = ? WHERE status = 'active'",
            (now,),
        )
        # Upsert the new one
        self.conn.execute(
            "INSERT INTO task_contexts (id, name, content, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'active', ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "content = excluded.content, status = 'active', updated_at = excluded.updated_at",
            (id, name, content, now, now),
        )
        self.conn.commit()

    def update_task_context(self, content: str) -> dict | None:
        """Update the active task context's content. Returns updated context or None."""
        now = _now_iso()
        self.conn.execute(
            "UPDATE task_contexts SET content = ?, updated_at = ? WHERE status = 'active'",
            (content, now),
        )
        self.conn.commit()
        return self.get_active_task_context()

    def archive_task_context(self) -> dict | None:
        """Archive the active task context. Returns it before archiving, or None."""
        ctx = self.get_active_task_context()
        if ctx:
            now = _now_iso()
            self.conn.execute(
                "UPDATE task_contexts SET status = 'archived', updated_at = ? WHERE id = ?",
                (now, ctx["id"]),
            )
            self.conn.commit()
        return ctx

    def get_task_context_by_name(self, name: str) -> dict | None:
        """Find a task context by name (most recent first)."""
        row = self.conn.execute(
            "SELECT * FROM task_contexts WHERE name = ? ORDER BY updated_at DESC LIMIT 1",
            (name,),
        ).fetchone()
        return dict(row) if row else None

    # --- Resonances ---

    def add_resonance(
        self,
        id_a: str,
        layer_a: str,
        id_b: str,
        layer_b: str,
        similarity: float,
        weight: float,
    ) -> str:
        """Add or update a lateral resonance between two memories.

        Canonical ordering: memory_a < memory_b lexicographically.
        On conflict (pair already exists): increment co_occurrences and
        update last_seen. Weight is a birth trait and never changes.
        Returns the resonance ID.
        """
        import uuid as _uuid

        # Canonical ordering
        if id_a > id_b:
            id_a, layer_a, id_b, layer_b = id_b, layer_b, id_a, layer_a

        now = _now_iso()
        rid = str(_uuid.uuid4())

        self.conn.execute(
            """
            INSERT INTO resonances
                (id, memory_a, layer_a, memory_b, layer_b, similarity, weight,
                 strength, co_occurrences, created_at, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0.5, 1, ?, ?)
            ON CONFLICT(memory_a, memory_b) DO UPDATE SET
                co_occurrences = co_occurrences + 1,
                last_seen = excluded.last_seen
            """,
            (rid, id_a, layer_a, id_b, layer_b, similarity, weight, now, now),
        )
        self.conn.commit()

        # Return the actual ID (may be the existing one on conflict)
        row = self.conn.execute(
            "SELECT id FROM resonances WHERE memory_a = ? AND memory_b = ?",
            (id_a, id_b),
        ).fetchone()
        return row[0]

    def get_resonances_for(self, memory_id: str) -> list[dict]:
        """Return all resonances involving the given memory ID."""
        rows = self.conn.execute(
            "SELECT * FROM resonances WHERE memory_a = ? OR memory_b = ?",
            (memory_id, memory_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def strengthen_resonance(self, resonance_id: str, delta: float = 0.1) -> None:
        """Increase resonance strength, capped at 1.0."""
        self.conn.execute(
            "UPDATE resonances SET strength = MIN(1.0, strength + ?) WHERE id = ?",
            (delta, resonance_id),
        )
        self.conn.commit()

    def weaken_resonance(self, resonance_id: str, delta: float = 0.05) -> None:
        """Decrease resonance strength, floored at 0.05."""
        self.conn.execute(
            "UPDATE resonances SET strength = MAX(0.05, strength - ?) WHERE id = ?",
            (delta, resonance_id),
        )
        self.conn.commit()

    def cleanup_resonances(self, pruned_ids: list[str]) -> None:
        """Delete resonances where either memory has been pruned."""
        if not pruned_ids:
            return
        placeholders = ", ".join("?" * len(pruned_ids))
        self.conn.execute(
            f"DELETE FROM resonances WHERE memory_a IN ({placeholders}) "
            f"OR memory_b IN ({placeholders})",
            pruned_ids + pruned_ids,
        )
        self.conn.commit()

    # --- Vector Access ---

    _LAYER_VECTOR_TABLE = {
        "episode": "episode_vectors",
        "semantic": "semantic_vectors",
        "instinct": "instinct_vectors",
    }

    def get_vector(self, layer: str, id: str) -> list[float] | None:
        """Fetch and unpack the embedding for a given layer and ID.

        Returns None if the layer is unknown or the ID is not found.
        """
        table = self._LAYER_VECTOR_TABLE.get(layer)
        if table is None:
            return None
        row = self.conn.execute(
            f"SELECT embedding FROM {table} WHERE id = ?", (id,)
        ).fetchone()
        if row is None:
            return None
        blob = row[0]
        n = len(blob) // 4
        return list(struct.unpack(f"<{n}f", blob))
