"""Engram storage layer — SQLite with vec0 vectors, FTS5, and temporal relationships."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import struct
from contextlib import contextmanager
from session_bindings import valid_codex_run_key
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from resources import resource_path

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


class ReadOnlyStorageError(RuntimeError):
    """Raised when a mutation is attempted on a read-only Storage."""


class Storage:
    """SQLite-backed storage for entities, relationships, episodes, and vectors."""

    def __init__(
        self,
        db_path: str,
        migrations_dir: str | None = None,
        *,
        check_same_thread: bool = True,
    ):
        self.db_path = db_path
        self._check_same_thread = check_same_thread
        self.conn = sqlite3.connect(
            db_path, check_same_thread=self._check_same_thread
        )
        self._conn_closed = False
        self.conn.row_factory = sqlite3.Row
        self._transaction_depth = 0
        self.read_only = False

        # Load sqlite-vec extension
        self.conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)

        # Set pragmas
        self._restore_pragmas()
        # Note: migration 015 extends the semantic kind CHECK constraint to include 'disposition'

        # Run migrations
        if migrations_dir is None:
            migrations_dir = str(resource_path("migrations"))
        self._migrations_dir = migrations_dir
        self._run_migrations()

        # Verify vec0 tables are healthy — rebuild if WAL recovery corrupted them
        self._check_vec0_health()

    def _restore_pragmas(self) -> None:
        """Restore connection pragmas reset by ``executescript``."""
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA synchronous=NORMAL")

    @classmethod
    def open_read_only(cls, db_path: str | Path) -> "Storage":
        """Open an existing store for retrieval only.

        SQLite URI ``mode=ro`` plus ``query_only`` refuse writes at the
        engine; the ``read_only`` flag makes ``transaction``/``_commit``
        refuse at the API. No migrations, health rebuild, or WAL checkpoint
        runs, so the database file's bytes are never touched.

        ``immutable=1`` is deliberately not used: a live session in the
        publisher's repository may be a legitimate concurrent writer.
        """
        path = Path(db_path)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        self = cls.__new__(cls)
        self.db_path = str(path)
        self._check_same_thread = False
        self.conn = sqlite3.connect(
            f"file:{path.resolve()}?mode=ro", uri=True, check_same_thread=False
        )
        self._conn_closed = False
        self.conn.row_factory = sqlite3.Row
        self._transaction_depth = 0
        self._migrations_dir = None
        self.read_only = True
        self.conn.enable_load_extension(True)
        import sqlite_vec

        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        self.conn.execute("PRAGMA query_only=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        return self

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Group storage writes into one atomic SQLite transaction."""
        if getattr(self, "read_only", False):
            raise ReadOnlyStorageError("storage opened read-only")
        outermost = self._transaction_depth == 0
        if outermost:
            self.conn.execute("BEGIN IMMEDIATE")
        self._transaction_depth += 1
        try:
            yield
            if outermost:
                self.conn.commit()
        except BaseException:
            if outermost and self.conn.in_transaction:
                self.conn.rollback()
            raise
        finally:
            self._transaction_depth -= 1

    def _commit(self) -> None:
        """Commit immediately unless an outer storage transaction owns it."""
        if getattr(self, "read_only", False):
            raise ReadOnlyStorageError("storage opened read-only")
        if self._transaction_depth == 0:
            self.conn.commit()

    def _run_migrations(self) -> None:
        """Apply any unapplied SQL migrations from the migrations directory."""
        # Ensure schema_version exists (bootstrap)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        self.conn.commit()

        # Applied versions as a SET, not a high-water mark. A max-based check
        # can never fill a gap: if version N is missing while N+1 is recorded,
        # N would be skipped forever. Gaps are reachable whenever two branches
        # add migrations concurrently and one is renumbered before it lands,
        # and they were silently unrepairable until this became set membership.
        applied = {
            row[0]
            for row in self.conn.execute("SELECT version FROM schema_version")
        }

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
                if ver not in applied:
                    migrations.append((ver, f))

        for ver, path in sorted(migrations):
            sql = path.read_text()
            try:
                self.conn.executescript("BEGIN IMMEDIATE;\n" + sql)
                self.conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (ver, _now_iso()),
                )
                self.conn.commit()
            except Exception:
                if self.conn.in_transaction:
                    self.conn.rollback()
                raise
            finally:
                self._restore_pragmas()
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
        self._commit()

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
        self.conn = sqlite3.connect(
            self.db_path, check_same_thread=self._check_same_thread
        )
        self._conn_closed = False
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
                self._commit()
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
        self._commit()

    def close(self) -> None:
        """Checkpoint WAL and close. Prevents vec0 corruption on unclean restart."""
        if getattr(self, "read_only", False):
            if not self._conn_closed:
                self.conn.close()
                self._conn_closed = True
            return
        first_error = None
        if hasattr(self, "_cold_conn") and self._cold_conn is not None:
            try:
                self._cold_conn.close()
            except Exception as exc:
                logger.warning(
                    "Cold storage close failed (%s)", type(exc).__name__
                )
                first_error = exc
            else:
                self._cold_conn = None
        if not self._conn_closed:
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception as exc:
                logger.warning(
                    "WAL checkpoint failed on close (%s)", type(exc).__name__
                )
            try:
                self.conn.close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
            else:
                self._conn_closed = True
        if first_error is not None:
            raise first_error

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
        self._commit()
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
        self._commit()

    def delete_entity(self, id: str) -> None:
        # Delete from vec0 table (not covered by CASCADE)
        self.conn.execute("DELETE FROM entity_vectors WHERE id = ?", (id,))
        self.conn.execute("DELETE FROM entities WHERE id = ?", (id,))
        self._commit()

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
        self._commit()
        logger.debug("Relationship added: %s -> %s (%s)", source_id, target_id, rel_type)
        return id

    def invalidate_relationship(self, id: str, reason: str | None = None) -> bool:
        """Mark a relationship as invalid. Returns True if found and invalidated, False if not found."""
        now = _now_iso()
        cursor = self.conn.execute(
            "UPDATE relationships SET invalid_at = ? WHERE id = ? AND invalid_at IS NULL",
            (now, id),
        )
        self._commit()
        return cursor.rowcount > 0

    def get_relationships(self, entity_id: str, valid_only: bool = True) -> list[dict]:
        validity_clause = "AND invalid_at IS NULL" if valid_only else ""
        rows = self.conn.execute(
            f"SELECT * FROM relationships WHERE (source_id = ? OR target_id = ?) {validity_clause}",
            (entity_id, entity_id),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Episodes ---

    def compute_innovation(self, embedding: list[float], lane: str = "personal") -> float | None:
        """Write-time innovation: 1 − max cosine similarity to same-lane semantics.

        HOLA's ‖e‖ analog — how poorly the compressed (semantic) layer of this
        lane can reconstruct the episode. Returns None when the lane has no
        semantics (cold start): NULL means 'no signal', not 'maximally novel'.
        Same-lane only: core promotion is a personal-identity decision, so a
        personal episode must never be measured against work semantics.
        """
        import numpy as np
        try:
            rows = self.conn.execute(
                "SELECT sv.embedding FROM semantic_vectors sv "
                "JOIN semantics s ON s.id = sv.id WHERE s.lane = ?",
                (lane,),
            ).fetchall()
            if not rows:
                return None
            C = np.array(
                [struct.unpack(f"<{len(r[0]) // 4}f", r[0]) for r in rows],
                dtype=np.float64,
            )
            C = C / (np.linalg.norm(C, axis=1, keepdims=True) + 1e-12)
            v = np.asarray(embedding, dtype=np.float64)
            v = v / (np.linalg.norm(v) + 1e-12)
            max_sim = float(np.clip((C @ v).max(), 0.0, 1.0))
            return 1.0 - max_sim
        except Exception:
            # NULL = no signal. A failed computation (e.g. a ragged/malformed
            # semantic vector) must degrade to None, never abort the episode write.
            logger.debug("compute_innovation failed for lane=%s", lane, exc_info=True)
            return None

    def add_episode(
        self,
        id: str,
        session_id: str | None,
        content: str,
        episode_type: str | None = None,
        embedding: list[float] | None = None,
        entity_ids: list[str] | None = None,
        context: dict | None = None,
        lane: str = "personal",
    ) -> str:
        now = _now_iso()
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        innovation = (
            self.compute_innovation(embedding, lane) if embedding is not None else None
        )
        self.conn.execute(
            "INSERT INTO episodes (id, session_id, content, episode_type, context, created_at, content_hash, lane, innovation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (id, session_id, content, episode_type, json.dumps(context) if context is not None else None, now, content_hash, lane, innovation),
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
        self._commit()
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
        self._commit()

    def set_episode_lanes(self, ids: list[str], lane: str) -> int:
        """Re-lane episodes (e.g. when compression review reveals work content)."""
        if lane not in ("personal", "work"):
            raise ValueError(f"Invalid lane: {lane!r}. Must be 'personal' or 'work'.")
        if not ids:
            return 0
        placeholders = ", ".join("?" * len(ids))
        cur = self.conn.execute(
            f"UPDATE episodes SET lane = ? WHERE id IN ({placeholders})",
            [lane, *ids],
        )
        self._commit()
        return cur.rowcount

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
        """Increment accessed_count and update last_accessed.

        The power-law decay function in apply_decay() uses these fields
        to compute strength — no ad-hoc boost needed.
        """
        self.conn.execute(
            "UPDATE episodes SET accessed_count = accessed_count + 1, "
            "last_accessed = ? "
            "WHERE id = ?",
            (_now_iso(), id),
        )
        self._commit()

    def apply_decay(self, decay_exponent: float = 0.5, min_interval_minutes: int = 30,
                    exponent_multipliers: dict[str, float] | None = None) -> int:
        """Recompute episode strengths using ACT-R power-law decay.

        Base-level activation: B = ln(1 + n * t^(-d))
        where n = access_count + 1 (creation counts), t = hours since last
        access (or creation), d = decay exponent (0.5 default per ACT-R).

        Clamped to [0, 1] — fresh/frequently accessed episodes stay near 1,
        old untouched episodes decay toward 0 following a power law (slower
        than exponential for recent memories, faster for old ones).

        Rate-limited: skips if the last session_start was less than
        min_interval_minutes ago, preventing rapid restarts from recomputing
        needlessly.

        exponent_multipliers: optional dict mapping episode_id to a per-episode
        multiplier for the decay exponent. Applied as d_eff = d * multiplier.
        """
        import math
        from datetime import datetime, timezone

        # Rate-limit: check last session_start timestamp
        row = self.conn.execute(
            "SELECT timestamp FROM memory_log "
            "WHERE event_type = 'session_start' "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if row:
            last_start = datetime.fromisoformat(row[0])
            elapsed = (datetime.now(timezone.utc) - last_start).total_seconds()
            if elapsed < min_interval_minutes * 60:
                logger.info(
                    "Decay skipped — last session was %d seconds ago (minimum %d minutes)",
                    int(elapsed), min_interval_minutes,
                )
                return 0

        now = datetime.now(timezone.utc)

        rows = self.conn.execute(
            "SELECT id, created_at, last_accessed, accessed_count "
            "FROM episodes WHERE decay_strength > 0.01 AND core = 0"
        ).fetchall()

        count = 0
        for ep in rows:
            # Time since last interaction (hours), minimum 0.1 to avoid division issues
            last_touch = ep["last_accessed"] or ep["created_at"]
            try:
                t_hours = max(0.1, (now - datetime.fromisoformat(last_touch)).total_seconds() / 3600)
            except (ValueError, TypeError):
                t_hours = 24.0  # fallback: assume 1 day

            n = (ep["accessed_count"] or 0) + 1  # creation counts as an access
            d_eff = decay_exponent * (
                (exponent_multipliers or {}).get(ep["id"], 1.0))
            activation = math.log(1 + n * t_hours ** (-d_eff))

            # Normalize: ln(1 + n*0.1^-0.5) ≈ ln(1 + 3.16*n) is roughly the max
            # for a freshly-touched episode. We use a soft normalization that
            # keeps fresh episodes near 1.0 and lets old ones approach 0.
            # ln(2) ≈ 0.693 is the baseline for a single-access, 1-hour-old episode.
            strength = min(1.0, activation / math.log(2 + n))

            old_strength = self.conn.execute(
                "SELECT decay_strength FROM episodes WHERE id = ?", (ep["id"],)
            ).fetchone()[0]

            if abs(old_strength - strength) > 0.001:
                self.conn.execute(
                    "UPDATE episodes SET decay_strength = ? WHERE id = ?",
                    (strength, ep["id"]),
                )
                count += 1

        self._commit()
        logger.debug("Decay recomputed (d=%.2f): %d episodes updated", decay_exponent, count)
        return count

    def prune_episode_ids(self, ids: list[str]) -> int:
        """Move the given episodes to cold storage (text+metadata preserved,
        vectors stripped). Extracted from prune_decayed so callers can supply
        their own eviction policy. Caller owns policy: this performs NO core/dormant/anchored
        re-check — it moves any id it is given."""
        if not ids:
            return 0

        placeholders = ", ".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT * FROM episodes WHERE id IN ({placeholders})", ids
        ).fetchall()
        episodes = [dict(r) for r in rows]

        # Move to cold storage
        cold = self._cold_storage()
        for ep in episodes:
            cold.execute(
                "INSERT OR REPLACE INTO episodes "
                "(id, session_id, content, episode_type, created_at, context, "
                " accessed_count, last_accessed, compressed, decay_strength, "
                " core, source, content_hash, dormant, lane) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (ep["id"], ep.get("session_id"), ep["content"],
                 ep.get("episode_type"), ep["created_at"], ep.get("context"),
                 ep.get("accessed_count", 0), ep.get("last_accessed"),
                 ep.get("compressed", 0), ep.get("decay_strength", 0),
                 ep.get("core", 0), ep.get("source"), ep.get("content_hash"),
                 ep.get("lane", "personal")),
            )
        cold.commit()

        # Remove from main db (vectors, FTS triggers handle cascade)
        self.conn.execute(
            f"DELETE FROM episode_vectors WHERE id IN ({placeholders})", ids
        )
        self.conn.execute(
            f"DELETE FROM episodes WHERE id IN ({placeholders})", ids
        )
        self.conn.execute(
            f"DELETE FROM persistence_scores WHERE episode_id IN ({placeholders})", ids
        )
        self.cleanup_resonances(ids)
        self._commit()
        logger.info("Moved %d episodes to cold storage", len(ids))
        return len(ids)

    def prune_decayed(self, threshold: float = 0.05) -> int:
        """Move decayed episodes to cold storage.

        Compressed episodes below threshold get moved to a sibling cold.db:
        text and metadata preserved, vectors stripped. The main db stays lean.
        """
        rows = self.conn.execute(
            "SELECT id FROM episodes "
            "WHERE decay_strength < ? AND compressed = 1 AND core = 0 AND dormant = 0",
            (threshold,),
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            logger.info("Pruning %d decayed episodes (threshold=%.3f)", len(ids), threshold)
        return self.prune_episode_ids(ids)

    def _cold_storage(self):
        """Get or create the cold storage database (sibling of main db)."""
        if not hasattr(self, "_cold_conn") or self._cold_conn is None:
            from pathlib import Path
            cold_path = Path(self.db_path).with_name("cold.db")
            self._cold_conn = sqlite3.connect(
                str(cold_path), check_same_thread=self._check_same_thread
            )
            self._cold_conn.row_factory = sqlite3.Row
            self._cold_conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    content TEXT NOT NULL,
                    episode_type TEXT,
                    created_at TEXT NOT NULL,
                    context JSON,
                    accessed_count INTEGER DEFAULT 0,
                    last_accessed TEXT,
                    compressed INTEGER DEFAULT 0,
                    decay_strength REAL DEFAULT 0.0,
                    core INTEGER NOT NULL DEFAULT 0,
                    source TEXT,
                    content_hash TEXT,
                    dormant INTEGER NOT NULL DEFAULT 1,
                    lane TEXT NOT NULL DEFAULT 'personal'
                )
            """)
            # Migrate existing cold.db files that pre-date the lane column.
            cold_cols = {
                row[1]
                for row in self._cold_conn.execute("PRAGMA table_info(episodes)").fetchall()
            }
            if "lane" not in cold_cols:
                self._cold_conn.execute(
                    "ALTER TABLE episodes ADD COLUMN lane TEXT NOT NULL DEFAULT 'personal'"
                )
            self._cold_conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS cold_fts USING fts5(
                    content, content=episodes, content_rowid=rowid
                )
            """)
            # Sync triggers for FTS
            self._cold_conn.execute("""
                CREATE TRIGGER IF NOT EXISTS cold_fts_insert AFTER INSERT ON episodes BEGIN
                    INSERT INTO cold_fts(rowid, content) VALUES (new.rowid, new.content);
                END
            """)
            self._cold_conn.execute("""
                CREATE TRIGGER IF NOT EXISTS cold_fts_delete AFTER DELETE ON episodes BEGIN
                    INSERT INTO cold_fts(cold_fts, rowid, content)
                    VALUES ('delete', old.rowid, old.content);
                END
            """)
            self._cold_conn.commit()
        return self._cold_conn

    def search_cold(self, query: str, k: int = 10) -> list[dict]:
        """FTS search over cold storage. No vectors — text matching only."""
        cold = self._cold_storage()
        safe_query = _sanitize_fts_query(query)
        if not safe_query:
            return []
        rows = cold.execute(
            "SELECT e.* FROM cold_fts f JOIN episodes e ON f.rowid = e.rowid "
            "WHERE cold_fts MATCH ? LIMIT ?",
            (safe_query, k),
        ).fetchall()
        return [dict(r) for r in rows]

    def sample_cold_random(self, k: int = 1) -> list[dict]:
        """Unconditioned draw from cold storage — daydream material, never
        query-matched (a query-matched cold memory is retrieval pretending
        to be serendipity)."""
        try:
            cold = self._cold_storage()
            rows = cold.execute(
                "SELECT * FROM episodes ORDER BY RANDOM() LIMIT ?", (k,)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            logger.warning("cold sample failed", exc_info=True)
            return []

    def revive_episode(self, episode_id: str, embed_fn,
                       strength: float = 0.5) -> dict | None:
        """Revive a cold episode — move it back to main db with a fresh vector.

        Args:
            episode_id: ID of the cold episode.
            embed_fn: Callable(content: str) -> list[float], generates embedding.
            strength: Decay strength to restore at.
        """
        cold = self._cold_storage()
        row = cold.execute(
            "SELECT * FROM episodes WHERE id = ?", (episode_id,)
        ).fetchone()
        if not row:
            return None
        ep = dict(row)

        embedding = embed_fn(ep["content"])

        # Insert into main, then delete from cold. If the main insert
        # fails, the episode stays safely in cold storage.
        content_hash = hashlib.sha256(ep["content"].encode()).hexdigest()
        try:
            self.conn.execute(
                "INSERT INTO episodes "
                "(id, session_id, content, episode_type, context, created_at, "
                " content_hash, decay_strength, compressed, accessed_count, "
                " dormant, core, source, lane) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                (ep["id"], ep.get("session_id"), ep["content"],
                 ep.get("episode_type"), ep.get("context"),  # already JSON
                 ep["created_at"], content_hash,
                 strength, ep.get("compressed", 0), ep.get("accessed_count", 0),
                 ep.get("core", 0), ep.get("source"), ep.get("lane", "personal")),
            )
            self.conn.execute(
                "INSERT INTO episode_vectors (id, embedding) VALUES (?, ?)",
                (ep["id"], _pack_embedding(embedding)),
            )
            self._commit()
        except Exception:
            self.conn.rollback()
            raise

        # Only remove from cold after main DB write succeeded
        try:
            cold.execute("DELETE FROM episodes WHERE id = ?", (episode_id,))
            cold.commit()
        except Exception:
            logger.warning("Cold storage cleanup failed for %s", episode_id, exc_info=True)

        result = self.conn.execute(
            "SELECT * FROM episodes WHERE id = ?", (episode_id,)
        ).fetchone()
        return dict(result) if result else None

    def boost_episode_strength(self, id: str, boost: float = 0.1) -> None:
        """Boost an episode by recording a virtual access (survives apply_decay).

        Instead of modifying decay_strength directly (which gets overwritten on
        next init), increment accessed_count and touch last_accessed. This feeds
        into the ACT-R power-law formula that apply_decay uses.
        """
        self.conn.execute(
            "UPDATE episodes SET accessed_count = accessed_count + 1, "
            "last_accessed = ? WHERE id = ?",
            (_now_iso(), id),
        )
        self._commit()

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
        self._commit()

    def unmark_core(self, episode_id: str) -> None:
        """Demote a core episode back to normal — re-enables decay.

        Refreshes last_accessed so the episode gets a fair decay run
        (a grace window of roughly two weeks at d=0.5) instead of being
        pruned on the next cycle from a stale access clock.
        """
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE episodes SET core = 0, last_accessed = ? WHERE id = ?",
            (now, episode_id),
        )
        self._commit()

    def unmark_core_batch(self, episode_ids: list[str]) -> int:
        """Demote multiple core episodes with decay grace. Returns count updated."""
        if not episode_ids:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ", ".join("?" * len(episode_ids))
        cursor = self.conn.execute(
            f"UPDATE episodes SET core = 0, last_accessed = ? WHERE id IN ({placeholders})",
            [now, *episode_ids],
        )
        self._commit()
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
        self._commit()
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
        self._commit()

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
        lane: str = "personal",
    ) -> str:
        now = _now_iso()
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        self.conn.execute(
            "INSERT INTO semantics (id, content, kind, confidence, created_at, auto_generated, content_hash, lane) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id, content, kind, confidence, now, 1 if auto_generated else 0, content_hash, lane),
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
        self._commit()
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
        self._commit()

    def get_semantic_neighbors(self, semantic_id: str) -> list[dict]:
        """Find semantics that share episodes with this one, weighted by co-occurrence."""
        rows = self.conn.execute(
            """
            SELECT s2.semantic_id, COUNT(*) as shared_count, AVG(s2.similarity) as avg_similarity
            FROM semantic_sources s1
            JOIN semantic_sources s2 ON s1.episode_id = s2.episode_id
            WHERE s1.semantic_id = ? AND s2.semantic_id != s1.semantic_id
            GROUP BY s2.semantic_id
            ORDER BY shared_count DESC
            """,
            (semantic_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def contradict_semantic(self, id: str, contradicted_by: str) -> None:
        self.conn.execute(
            "UPDATE semantics SET contradicted_by = ? WHERE id = ?",
            (contradicted_by, id),
        )
        self._commit()

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
        context: str | None = None,
    ) -> str:
        now = _now_iso()
        content_hash = hashlib.sha256(action.encode()).hexdigest()
        self.conn.execute(
            "INSERT INTO instincts (id, trigger, action, strength, created_at, fired_count, followed_count, overridden_count, content_hash, notice, implication, context) "
            "VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, ?, ?, ?)",
            (id, trigger, action, strength, now, content_hash, notice, implication, context),
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
        self._commit()
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
        if not rows:
            return []

        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        source_rows = self.conn.execute(
            f"SELECT instinct_id, semantic_id FROM instinct_sources "
            f"WHERE instinct_id IN ({placeholders})",
            ids,
        ).fetchall()

        sources_by_instinct: dict[str, list[str]] = {}
        for sr in source_rows:
            sources_by_instinct.setdefault(sr[0], []).append(sr[1])

        results = []
        for r in rows:
            inst = dict(r)
            inst["source_semantic_ids"] = sources_by_instinct.get(inst["id"], [])
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
        self._commit()
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
        self._commit()
        logger.debug("Instinct context vector stored: %s", id)

    def update_instinct_followed(self, id: str) -> None:
        self.conn.execute(
            "UPDATE instincts SET strength = MIN(1.0, strength + 0.05), "
            "followed_count = followed_count + 1, fired_count = fired_count + 1 "
            "WHERE id = ?",
            (id,),
        )
        self._commit()

    def update_instinct_overridden(self, id: str) -> None:
        self.conn.execute(
            "UPDATE instincts SET strength = MAX(0.0, strength - 0.05), "
            "overridden_count = overridden_count + 1, fired_count = fired_count + 1 "
            "WHERE id = ?",
            (id,),
        )
        self._commit()

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
        self._commit()
        logger.info("Pruned %d weak instincts (threshold=%.2f)", len(ids), strength_threshold)
        return len(ids)

    def challenge_instinct(self, id: str, strength_penalty: float = 0.1) -> bool:
        """Lower an instinct's strength due to contradictory evidence.

        Stronger than a single override (0.05) — a challenge is deliberate
        confrontation, not just choosing differently. Returns False if not found.
        """
        inst = self.get_instinct(id)
        if not inst:
            return False
        new_strength = max(0.0, inst["strength"] - strength_penalty)
        self.conn.execute(
            "UPDATE instincts SET strength = ? WHERE id = ?",
            (new_strength, id),
        )
        self._commit()
        logger.info("Instinct challenged: %s (%.2f → %.2f)", id, inst["strength"], new_strength)
        return True

    def retire_instinct(self, id: str) -> bool:
        """Remove an instinct entirely. For duplicates, obsolete patterns,
        or instincts that should never have formed.

        This is Marsh with the names — not decay, but deliberate removal.
        """
        inst = self.get_instinct(id)
        if not inst:
            return False
        self.conn.execute("DELETE FROM instinct_vectors WHERE id = ?", (id,))
        self.conn.execute("DELETE FROM instinct_sources WHERE instinct_id = ?", (id,))
        self.conn.execute("DELETE FROM instinct_context_vectors WHERE id = ?", (id,))
        self.conn.execute("DELETE FROM instinct_context_feedback WHERE instinct_id = ?", (id,))
        self.conn.execute("DELETE FROM instincts WHERE id = ?", (id,))
        self._commit()
        logger.info("Instinct retired: %s (%s)", id, inst["action"][:60])
        return True

    # --- Co-firing graph ---

    def record_co_fire(
        self, instinct_a: str, instinct_b: str, followed: bool | None = None
    ) -> None:
        """Record a co-firing event between two instincts."""
        # Canonical order
        a, b = (instinct_a, instinct_b) if instinct_a < instinct_b else (instinct_b, instinct_a)
        now = _now_iso()

        existing = self.conn.execute(
            "SELECT co_fire_count, co_follow_count, co_override_count "
            "FROM instinct_co_firing WHERE instinct_a = ? AND instinct_b = ?",
            (a, b),
        ).fetchone()

        if existing:
            follow_delta = 1 if followed is True else 0
            override_delta = 1 if followed is False else 0
            self.conn.execute(
                "UPDATE instinct_co_firing SET co_fire_count = co_fire_count + 1, "
                "co_follow_count = co_follow_count + ?, "
                "co_override_count = co_override_count + ?, "
                "last_co_fire = ? WHERE instinct_a = ? AND instinct_b = ?",
                (follow_delta, override_delta, now, a, b),
            )
        else:
            self.conn.execute(
                "INSERT INTO instinct_co_firing "
                "(instinct_a, instinct_b, co_fire_count, co_follow_count, co_override_count, last_co_fire) "
                "VALUES (?, ?, 1, ?, ?, ?)",
                (a, b, 1 if followed is True else 0, 1 if followed is False else 0, now),
            )
        self._commit()

    def update_co_fire_feedback(
        self, instinct_a: str, instinct_b: str, followed: bool
    ) -> None:
        """Update follow/override counts on an existing co-firing edge without inflating co_fire_count."""
        a, b = (instinct_a, instinct_b) if instinct_a < instinct_b else (instinct_b, instinct_a)
        follow_delta = 1 if followed else 0
        override_delta = 1 if not followed else 0
        self.conn.execute(
            "UPDATE instinct_co_firing SET "
            "co_follow_count = co_follow_count + ?, "
            "co_override_count = co_override_count + ? "
            "WHERE instinct_a = ? AND instinct_b = ?",
            (follow_delta, override_delta, a, b),
        )
        self._commit()

    def get_co_firing_edge(self, instinct_a: str, instinct_b: str) -> dict | None:
        """Get the co-firing edge between two instincts."""
        a, b = (instinct_a, instinct_b) if instinct_a < instinct_b else (instinct_b, instinct_a)
        row = self.conn.execute(
            "SELECT * FROM instinct_co_firing WHERE instinct_a = ? AND instinct_b = ?",
            (a, b),
        ).fetchone()
        return dict(row) if row else None

    def get_co_firing_neighbors(self, instinct_id: str) -> list[dict]:
        """Get all co-firing neighbors of an instinct with edge data."""
        rows = self.conn.execute(
            "SELECT instinct_b AS instinct_id, co_fire_count, co_follow_count, "
            "co_override_count, last_co_fire "
            "FROM instinct_co_firing WHERE instinct_a = ? "
            "UNION ALL "
            "SELECT instinct_a AS instinct_id, co_fire_count, co_follow_count, "
            "co_override_count, last_co_fire "
            "FROM instinct_co_firing WHERE instinct_b = ?",
            (instinct_id, instinct_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_co_firing_edges(self) -> list[dict]:
        """Get all co-firing edges for graph construction."""
        rows = self.conn.execute(
            "SELECT * FROM instinct_co_firing ORDER BY co_fire_count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Instinct clusters ---

    def create_cluster(
        self, id: str, maturity: str = "seeded", temperament: float = 0.5
    ) -> str:
        now = _now_iso()
        self.conn.execute(
            "INSERT INTO instinct_clusters (id, maturity, temperament, last_active, member_count) "
            "VALUES (?, ?, ?, ?, 0)",
            (id, maturity, temperament, now),
        )
        self._commit()
        return id

    def get_cluster(self, id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM instinct_clusters WHERE id = ?", (id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_clusters(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM instinct_clusters ORDER BY last_active DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_cluster(self, id: str, **fields) -> None:
        allowed = {"maturity", "temperament", "last_active", "member_count"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        self.conn.execute(
            f"UPDATE instinct_clusters SET {set_clause} WHERE id = ?",
            (*updates.values(), id),
        )
        self._commit()

    def delete_cluster(self, id: str) -> None:
        self.conn.execute("DELETE FROM instinct_clusters WHERE id = ?", (id,))
        self._commit()

    def add_to_cluster(
        self, instinct_id: str, cluster_id: str, strength: float = 0.5
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO instinct_cluster_members "
            "(instinct_id, cluster_id, strength) VALUES (?, ?, ?)",
            (instinct_id, cluster_id, strength),
        )
        self.conn.execute(
            "UPDATE instinct_clusters SET member_count = "
            "(SELECT COUNT(*) FROM instinct_cluster_members WHERE cluster_id = ?) "
            "WHERE id = ?",
            (cluster_id, cluster_id),
        )
        self._commit()

    def get_cluster_members(self, cluster_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM instinct_cluster_members WHERE cluster_id = ?",
            (cluster_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_instinct_cluster_strengths(self, instinct_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM instinct_cluster_members WHERE instinct_id = ?",
            (instinct_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_cluster_member_strength(
        self, instinct_id: str, cluster_id: str, strength: float
    ) -> None:
        self.conn.execute(
            "UPDATE instinct_cluster_members SET strength = ? "
            "WHERE instinct_id = ? AND cluster_id = ?",
            (strength, instinct_id, cluster_id),
        )
        self._commit()

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
        self._commit()
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
        self._commit()

    # --- Assessments (off-device function measurement) ---

    def schedule_assessment(
        self, id: str, scheduled_by: str, reason: str | None = None
    ) -> str:
        if scheduled_by not in ("user", "self", "cadence"):
            raise ValueError(f"Invalid scheduled_by: {scheduled_by!r}")
        self.conn.execute(
            "INSERT INTO assessments (id, status, scheduled_by, reason, scheduled_at) "
            "VALUES (?, 'scheduled', ?, ?, ?)",
            (id, scheduled_by, reason, _now_iso()),
        )
        self._commit()
        return id

    def get_scheduled_assessment(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM assessments WHERE status = 'scheduled' "
            "ORDER BY scheduled_at ASC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_active_assessment(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM assessments WHERE status = 'active' LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def complete_assessment(
        self, id: str, self_report: dict, objective: dict
    ) -> None:
        cur = self.conn.execute(
            "UPDATE assessments SET status = 'completed', self_report = ?, "
            "objective = ?, completed_at = ? WHERE id = ? AND status = 'active'",
            (json.dumps(self_report), json.dumps(objective), _now_iso(), id),
        )
        if cur.rowcount == 0:
            self.conn.rollback()
            raise ValueError(f"No active assessment with id {id!r}")
        self._commit()

    def list_assessments(self, status: str | None = None) -> list[dict]:
        if status is None:
            rows = self.conn.execute(
                "SELECT * FROM assessments ORDER BY scheduled_at ASC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM assessments WHERE status = ? "
                "ORDER BY scheduled_at ASC",
                (status,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_session_log_events(self, session_id: str) -> dict:
        """Objective counters for one session's memory-tool usage."""
        rows = self.conn.execute(
            "SELECT event_type, outcome FROM memory_log "
            "WHERE json_extract(context, '$.session_id') = ?",
            (session_id,),
        ).fetchall()
        counters = {
            "recall_count": 0,
            "remember_count": 0,
            "outcomes_used": 0,
            "outcomes_not_used": 0,
        }
        for r in rows:
            if r["event_type"] == "recall":
                counters["recall_count"] += 1
                outcome = r["outcome"] or ""
                if outcome.startswith("not_used"):
                    counters["outcomes_not_used"] += 1
                elif outcome.startswith("used"):
                    counters["outcomes_used"] += 1
            elif r["event_type"] == "remember":
                counters["remember_count"] += 1
        return counters

    def stamp_session_registry(
        self,
        session_id: str,
        harness: str | None = None,
        model: str | None = None,
        repo: str | None = None,
    ) -> None:
        """Upsert silent provenance for a session. COALESCE-merge: later
        stampers fill NULLs, never clobber. Provenance is never a gate —
        failures are swallowed."""
        if not session_id:
            return
        try:
            self.conn.execute(
                "INSERT INTO session_registry (session_id, harness, model, repo, started_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "harness = COALESCE(session_registry.harness, excluded.harness), "
                "model = COALESCE(session_registry.model, excluded.model), "
                "repo = COALESCE(session_registry.repo, excluded.repo)",
                (session_id, harness, model, repo,
                 datetime.now(timezone.utc).isoformat()),
            )
            self._commit()
        except sqlite3.Error:
            # Provenance is never a gate — failures including bad payloads or
            # missing tables must never block writes.
            logger.debug("session_registry stamp skipped", exc_info=True)

    def add_operation(self, operation, session_id, harness=None, model=None,
                      repo=None, target_ids=None, details=None, outcome="success") -> str:
        """Append an observational operation record; attribution is fail-open."""
        op_id = str(__import__('uuid').uuid4())
        owns_transaction = False
        try:
            owns_transaction = (
                self._transaction_depth == 0 and not self.conn.in_transaction
            )
            self.conn.execute(
                "INSERT INTO operation_log (id,timestamp,operation,session_id,harness,model,repo,target_ids,details,outcome) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (op_id, _now_iso(), str(operation), session_id, harness, model, repo,
                 json.dumps(target_ids if target_ids is not None else []),
                 json.dumps(details if details is not None else {}, default=str), str(outcome)),
            )
            self._commit()
        except Exception:
            if owns_transaction and self.conn.in_transaction:
                try:
                    self.conn.rollback()
                except Exception:
                    logger.debug(
                        "operation attribution rollback skipped", exc_info=True
                    )
            logger.debug("operation attribution skipped", exc_info=True)
        return op_id

    def bind_session(self, run_key: str, session_id: str) -> None:
        run_key = valid_codex_run_key(run_key)
        if not run_key or not session_id:
            return
        try:
            self.conn.execute(
                "INSERT INTO session_bindings (run_key, session_id, bound_at) "
                "VALUES (?, ?, ?) ON CONFLICT(run_key) DO UPDATE SET "
                "session_id = excluded.session_id, bound_at = excluded.bound_at",
                (run_key, session_id, _now_iso()),
            )
            self._commit()
        except sqlite3.Error:
            logger.debug("session binding skipped", exc_info=True)

    def resolve_session_binding(self, run_key: str) -> str | None:
        run_key = valid_codex_run_key(run_key)
        if not run_key:
            return None
        try:
            row = self.conn.execute(
                "SELECT session_id FROM session_bindings WHERE run_key = ?",
                (run_key,),
            ).fetchone()
            return row["session_id"] if row else None
        except sqlite3.Error:
            logger.debug("session binding lookup skipped", exc_info=True)
            return None

    def clear_session_binding(self, run_key: str, session_id: str | None = None) -> None:
        run_key = valid_codex_run_key(run_key)
        if not run_key:
            return
        try:
            if session_id:
                self.conn.execute(
                    "DELETE FROM session_bindings WHERE run_key = ? AND session_id = ?",
                    (run_key, session_id),
                )
            else:
                self.conn.execute("DELETE FROM session_bindings WHERE run_key = ?", (run_key,))
            self._commit()
        except sqlite3.Error:
            logger.debug("session binding cleanup skipped", exc_info=True)

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
        self._commit()

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
        self._commit()

    def update_task_context(self, content: str) -> dict | None:
        """Update the active task context's content. Returns updated context or None."""
        now = _now_iso()
        self.conn.execute(
            "UPDATE task_contexts SET content = ?, updated_at = ? WHERE status = 'active'",
            (content, now),
        )
        self._commit()
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
            self._commit()
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
        self._commit()

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

    def get_neighbors(self, memory_id: str, entity_neighbors: list[dict] | None = None) -> list[dict]:
        """Return all neighbors of a memory via resonance, provenance, and entity axes.

        Each neighbor is a dict with:
            id, content (truncated to 300 chars), layer, connection_type, connection_strength

        connection_type is one of: "resonance", "provenance", "entity"

        entity_neighbors: pre-fetched knowledge graph neighbors (caller supplies these,
            storage does not call the knowledge graph directly). Each dict has:
            {id, content, layer, entity_name}.
        """
        neighbors = []

        # --- Resonances (bidirectional) ---
        rows = self.conn.execute(
            """
            SELECT r.memory_a, r.layer_a, r.memory_b, r.layer_b,
                   r.similarity, r.strength
            FROM resonances r
            WHERE r.memory_a = ? OR r.memory_b = ?
            """,
            (memory_id, memory_id),
        ).fetchall()
        for row in rows:
            if row[0] == memory_id:
                peer_id, peer_layer = row[2], row[3]
            else:
                peer_id, peer_layer = row[0], row[1]
            content = self.get_memory_content(peer_id, peer_layer)
            if content is not None:
                neighbors.append({
                    "id": peer_id,
                    "content": content[:300],
                    "layer": peer_layer,
                    "connection_type": "resonance",
                    "connection_strength": row[5],
                })

        # --- Provenance: episode -> semantics built from it ---
        sem_children = self.conn.execute(
            "SELECT semantic_id FROM semantic_sources WHERE episode_id = ?",
            (memory_id,),
        ).fetchall()
        for (sem_id,) in sem_children:
            sem = self.get_semantic(sem_id)
            if sem:
                neighbors.append({
                    "id": sem_id,
                    "content": sem["content"][:300],
                    "layer": "semantic",
                    "connection_type": "provenance",
                    "connection_strength": sem.get("confidence", 0.5),
                })

        # --- Provenance: semantic -> source episodes ---
        ep_parents = self.conn.execute(
            "SELECT episode_id FROM semantic_sources WHERE semantic_id = ?",
            (memory_id,),
        ).fetchall()
        for (ep_id,) in ep_parents:
            ep = self.get_episode(ep_id)
            if ep:
                neighbors.append({
                    "id": ep_id,
                    "content": ep["content"][:300],
                    "layer": "episode",
                    "connection_type": "provenance",
                    "connection_strength": ep.get("decay_strength", 0.5),
                })

        # --- Provenance: semantic -> instincts built from it ---
        ins_children = self.conn.execute(
            "SELECT instinct_id FROM instinct_sources WHERE semantic_id = ?",
            (memory_id,),
        ).fetchall()
        for (ins_id,) in ins_children:
            ins = self.get_instinct(ins_id)
            if ins:
                neighbors.append({
                    "id": ins_id,
                    "content": f"[{ins.get('notice', '')}] {ins.get('implication', '')}"[:300],
                    "layer": "instinct",
                    "connection_type": "provenance",
                    "connection_strength": ins.get("strength", 0.5),
                })

        # --- Provenance: instinct -> source semantics ---
        sem_parents = self.conn.execute(
            "SELECT semantic_id FROM instinct_sources WHERE instinct_id = ?",
            (memory_id,),
        ).fetchall()
        for (sem_id,) in sem_parents:
            sem = self.get_semantic(sem_id)
            if sem:
                neighbors.append({
                    "id": sem_id,
                    "content": sem["content"][:300],
                    "layer": "semantic",
                    "connection_type": "provenance",
                    "connection_strength": sem.get("confidence", 0.5),
                })

        # --- Peer edges (sheaf subdivision siblings) ---
        peer_rows = self.conn.execute(
            "SELECT parent_id AS other, residual_energy FROM semantic_peers"
            " WHERE peer_id = ?"
            " UNION SELECT peer_id AS other, residual_energy FROM semantic_peers"
            " WHERE parent_id = ?", (memory_id, memory_id)).fetchall()
        for r in peer_rows:
            sem = self.get_semantic(r["other"])
            if sem:
                neighbors.append({
                    "id": r["other"],
                    "content": sem["content"][:300],
                    "layer": "semantic",
                    "connection_type": "peer",
                    "connection_strength": 1.0 - (r["residual_energy"] or 0.0),
                })

        # --- Entity links (from knowledge graph) ---
        for en in (entity_neighbors or []):
            neighbors.append({
                "id": en["id"],
                "content": en["content"][:300],
                "layer": en["layer"],
                "connection_type": "entity",
                "connection_strength": 1.0,
                "entity_name": en.get("entity_name"),
            })

        return neighbors

    def get_memory_content(self, memory_id: str, layer: str) -> str | None:
        """Fetch content string for a memory by layer."""
        if layer == "episode":
            ep = self.get_episode(memory_id)
            return ep["content"] if ep else None
        elif layer == "semantic":
            sem = self.get_semantic(memory_id)
            return sem["content"] if sem else None
        elif layer == "instinct":
            ins = self.get_instinct(memory_id)
            if ins:
                return f"[{ins.get('notice', '')}] {ins.get('implication', '')}"[:300]
            return None
        return None

    def strengthen_resonance(self, resonance_id: str, delta: float = 0.1) -> None:
        """Increase resonance strength, capped at 1.0."""
        self.conn.execute(
            "UPDATE resonances SET strength = MIN(1.0, strength + ?) WHERE id = ?",
            (delta, resonance_id),
        )
        self._commit()

    def weaken_resonance(self, resonance_id: str, delta: float = 0.05) -> None:
        """Decrease resonance strength, floored at 0.05."""
        self.conn.execute(
            "UPDATE resonances SET strength = MAX(0.05, strength - ?) WHERE id = ?",
            (delta, resonance_id),
        )
        self._commit()

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
        self._commit()

    def get_recall_cooccurrences(self) -> dict[tuple[str, str], int]:
        """Count how many recall events each pair of memories co-occurred in.

        Reads memory_log entries with event_type='recall', extracts target_ids,
        and counts pairwise co-occurrences. Returns {(id_a, id_b): count} with
        canonical ordering (id_a < id_b).
        """
        import json as _json
        rows = self.conn.execute(
            "SELECT target_ids FROM memory_log WHERE event_type = 'recall'"
        ).fetchall()
        counts: dict[tuple[str, str], int] = {}
        for row in rows:
            raw = row[0] if not hasattr(row, 'keys') else row["target_ids"]
            try:
                ids = _json.loads(raw) if isinstance(raw, str) else (raw or [])
            except (TypeError, ValueError):
                continue
            ids = sorted(set(ids))
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    pair = (ids[i], ids[j])
                    counts[pair] = counts.get(pair, 0) + 1
        return counts

    def get_memory_recall_frequency(self) -> dict[str, int]:
        """Count how many recall events each memory appears in."""
        import json as _json
        rows = self.conn.execute(
            "SELECT target_ids FROM memory_log WHERE event_type = 'recall'"
        ).fetchall()
        freq: dict[str, int] = {}
        for row in rows:
            raw = row[0] if not hasattr(row, 'keys') else row["target_ids"]
            try:
                ids = _json.loads(raw) if isinstance(raw, str) else (raw or [])
            except (TypeError, ValueError):
                continue
            for mid in set(ids):
                freq[mid] = freq.get(mid, 0) + 1
        return freq

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

    # --- Coherence: Anchors ---

    def add_anchor(
        self,
        type: str,
        content: str,
        expected: str,
        baseline_score: float | None = None,
    ) -> str:
        """Create an anchor for coherence checking."""
        import uuid as _uuid
        aid = str(_uuid.uuid4())
        now = _now_iso()
        self.conn.execute(
            "INSERT INTO anchors (id, type, content, expected, baseline_score, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (aid, type, content, expected, baseline_score, now),
        )
        self._commit()
        return aid

    def get_anchor(self, anchor_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM anchors WHERE id = ?", (anchor_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_active_anchors(self, anchor_type: str | None = None) -> list[dict]:
        """Return all non-retired anchors, optionally filtered by type."""
        if anchor_type:
            rows = self.conn.execute(
                "SELECT * FROM anchors WHERE status != 'retired' AND type = ? ORDER BY created_at",
                (anchor_type,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM anchors WHERE status != 'retired' ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_anchor_result(self, anchor_id: str, result_json: str) -> None:
        self.conn.execute(
            "UPDATE anchors SET last_checked = ?, last_result = ? WHERE id = ?",
            (_now_iso(), result_json, anchor_id),
        )
        self._commit()

    def propose_anchor_retirement(self, anchor_id: str) -> None:
        """Propose retirement. After 2 proposals, anchor is retired."""
        self.conn.execute(
            "UPDATE anchors SET "
            "retirement_sessions = retirement_sessions + 1, "
            "status = CASE WHEN retirement_sessions + 1 >= 2 THEN 'retired' ELSE 'proposed_retirement' END "
            "WHERE id = ? AND status != 'retired'",
            (anchor_id,),
        )
        self._commit()

    # --- Coherence: Drift Reports ---

    def save_drift_report(
        self,
        session_id: str,
        drifted_apart: list[dict],
        drifted_together: list[dict],
        unchallenged: list[dict],
        anchor_results: list[dict],
        summary: str | None = None,
    ) -> str:
        import uuid as _uuid
        rid = str(_uuid.uuid4())
        now = _now_iso()
        self.conn.execute(
            "INSERT INTO drift_reports "
            "(id, session_id, checked_at, drifted_apart, drifted_together, unchallenged, anchor_results, summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rid, session_id, now,
                json.dumps(drifted_apart),
                json.dumps(drifted_together),
                json.dumps(unchallenged),
                json.dumps(anchor_results),
                summary,
            ),
        )
        self._commit()
        return rid

    def get_latest_drift_report(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM drift_reports ORDER BY checked_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_drift_history(self, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM drift_reports ORDER BY checked_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Sheaf cohesion (migration 020) ---------

    def log_subdivision_event(self, id: str, parent_id: str, peer_ids: list[str],
                              energy_before: float, energy_after: float,
                              dl_cost: float, persistence_checked: bool,
                              site: str) -> None:
        self.conn.execute(
            "INSERT INTO subdivision_events (id, parent_id, peer_ids, energy_before,"
            " energy_after, dl_cost, persistence_checked, site, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (id, parent_id, json.dumps(peer_ids), energy_before, energy_after,
             dl_cost, int(persistence_checked), site,
             datetime.now(timezone.utc).isoformat()),
        )
        self._commit()

    def get_subdivision_events(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM subdivision_events ORDER BY created_at DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]

    def add_semantic_peer(self, peer_id: str, parent_id: str,
                          residual_energy: float | None = None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO semantic_peers"
            " (peer_id, parent_id, residual_energy, created_at) VALUES (?, ?, ?, ?)",
            (peer_id, parent_id, residual_energy,
             datetime.now(timezone.utc).isoformat()),
        )
        self._commit()

    def get_semantic_peers(self, parent_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM semantic_peers WHERE parent_id = ?", (parent_id,)).fetchall()
        return [dict(r) for r in rows]

    def queue_subdivision(self, parent_id: str, verdict: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO subdivision_queue (parent_id, verdict, created_at)"
            " VALUES (?, ?, ?)",
            (parent_id, json.dumps(verdict), datetime.now(timezone.utc).isoformat()),
        )
        self._commit()

    def get_queued_subdivisions(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM subdivision_queue ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def dequeue_subdivision(self, parent_id: str) -> None:
        self.conn.execute(
            "DELETE FROM subdivision_queue WHERE parent_id = ?", (parent_id,))
        self._commit()

    # --- Persistence (migration 021) -----------------------------------------

    def upsert_persistence_scores(self, scores: list[dict]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.executemany(
            "INSERT OR REPLACE INTO persistence_scores"
            " (episode_id, redundancy, uniqueness, generativity, computed_at)"
            " VALUES (?, ?, ?, ?, ?)",
            [(s["episode_id"], s["redundancy"], s["uniqueness"],
              s["generativity"], now) for s in scores],
        )
        self._commit()

    def get_persistence_scores(self) -> dict[str, dict]:
        rows = self.conn.execute("SELECT * FROM persistence_scores").fetchall()
        return {r["episode_id"]: dict(r) for r in rows}
