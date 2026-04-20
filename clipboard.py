"""Clipboard — continuous working-memory view that recomposes each step.

The wake hook fires once at session start. The clipboard is its continuous
counterpart: a small, budget-capped view that stays current as context shifts.

Three sections, in priority order:
1. Reminders — involuntary attention (time-based, step-based, keyword triggers)
2. Pinned — explicit working memory (goals, constraints, watch-fors)
3. Relevant — pulled from engram storage by situation embedding similarity

The clipboard doesn't replace engram's recall(). Recall is deliberate search.
The clipboard is what you see when you glance down.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("engram.clipboard")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Reminder:
    id: str
    text: str
    trigger_type: str  # "interval_seconds", "every_n_steps", "once_at"
    trigger_value: float
    created_at: float = field(default_factory=time.time)
    last_fired: float = 0.0
    repeat: bool = True
    fired_count: int = 0


class Clipboard:
    """Composes a small working-memory view from storage + pins + reminders."""

    def __init__(
        self,
        db_path: str | Path,
        max_chars: int = 3000,
        engram_storage=None,
        embeddings=None,
    ) -> None:
        self.db_path = Path(db_path)
        self.max_chars = max_chars
        self._engram_storage = engram_storage
        self._embeddings = embeddings
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._ensure_schema()
        self._step_count = 0
        self._last_compose_time = 0.0

    def _ensure_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS clipboard_pins (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                priority INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clipboard_reminders (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_value REAL NOT NULL,
                created_at REAL NOT NULL,
                last_fired REAL DEFAULT 0.0,
                repeat INTEGER DEFAULT 1,
                fired_count INTEGER DEFAULT 0
            );
        """)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.commit()

    # ── Pins ────────────────────────────────────────────────────────

    def pin(self, text: str, priority: int = 0) -> str:
        pin_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO clipboard_pins (id, text, priority, created_at) VALUES (?, ?, ?, ?)",
            (pin_id, text, priority, _now_iso()),
        )
        self._conn.commit()
        return pin_id

    def unpin(self, pin_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM clipboard_pins WHERE id = ?", (pin_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def unpin_matching(self, substring: str) -> int:
        cur = self._conn.execute(
            "DELETE FROM clipboard_pins WHERE text LIKE ?",
            (f"%{substring}%",),
        )
        self._conn.commit()
        return cur.rowcount

    def pins(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM clipboard_pins ORDER BY priority DESC, created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Reminders ───────────────────────────────────────────────────

    def add_reminder(
        self,
        text: str,
        trigger_type: str = "every_n_steps",
        trigger_value: float = 10,
        repeat: bool = True,
    ) -> str:
        rem_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO clipboard_reminders "
            "(id, text, trigger_type, trigger_value, created_at, repeat) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (rem_id, text, trigger_type, trigger_value, time.time(), int(repeat)),
        )
        self._conn.commit()
        return rem_id

    def remove_reminder(self, reminder_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM clipboard_reminders WHERE id = ?", (reminder_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def reminders(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM clipboard_reminders ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Step tracking ───────────────────────────────────────────────

    def step(self) -> None:
        """Advance the step counter. Call this each turn/action."""
        self._step_count += 1

    # ── Compose ─────────────────────────────────────────────────────

    def compose(self, situation: str = "") -> str:
        """Build the clipboard view for right now.

        Args:
            situation: What's happening — used to pull relevant memories.

        Returns:
            A composed context string within the character budget.
        """
        now = time.time()
        self._last_compose_time = now
        sections: list[tuple[str, str]] = []
        budget = self.max_chars

        # 1. Fired reminders (highest priority — involuntary)
        fired = self._check_reminders(now)
        if fired:
            block = "\n".join(f"  {r['text']}" for r in fired)
            sections.append(("[reminders]", block))
            budget -= len(block) + 20

        # 2. Pinned items
        pin_rows = self.pins()
        if pin_rows and budget > 200:
            lines = []
            for p in pin_rows:
                line = f"  {p['text']}"
                if len("\n".join(lines + [line])) > budget // 3:
                    break
                lines.append(line)
            if lines:
                block = "\n".join(lines)
                sections.append(("[pinned]", block))
                budget -= len(block) + 20

        # 3. Parked threads (context you set down — surface if situation matches)
        if budget > 200:
            parked = self._pull_parked_threads(situation, budget // 4)
            if parked:
                sections.append(("[parked threads]", parked))
                budget -= len(parked) + 20

        # 4. Relevant episodes from engram (if situation provided)
        if situation and budget > 300:
            relevant = self._pull_relevant(situation, budget)
            if relevant:
                sections.append(("[relevant]", relevant))
                budget -= len(relevant) + 20

        if not sections:
            return ""

        parts = []
        for header, content in sections:
            parts.append(header)
            parts.append(content)
        return "\n".join(parts)

    def _check_reminders(self, now: float) -> list[dict]:
        """Check which reminders should fire. Updates their state."""
        rows = self._conn.execute("SELECT * FROM clipboard_reminders").fetchall()
        fired = []

        for r in rows:
            should_fire = False
            if r["trigger_type"] == "interval_seconds":
                if now - r["last_fired"] >= r["trigger_value"]:
                    should_fire = True
            elif r["trigger_type"] == "every_n_steps":
                if self._step_count > 0 and self._step_count % int(r["trigger_value"]) == 0:
                    should_fire = True
            elif r["trigger_type"] == "once_at":
                if now >= r["trigger_value"] and r["fired_count"] == 0:
                    should_fire = True

            if should_fire:
                self._conn.execute(
                    "UPDATE clipboard_reminders SET last_fired = ?, fired_count = fired_count + 1 WHERE id = ?",
                    (now, r["id"]),
                )
                fired.append(dict(r))

        # Remove non-repeating reminders that have fired
        self._conn.execute(
            "DELETE FROM clipboard_reminders WHERE repeat = 0 AND fired_count > 0"
        )
        self._conn.commit()
        return fired

    def _pull_relevant(self, situation: str, budget: int) -> str:
        """Pull relevant memories from engram using embedding similarity.

        Uses engram's storage + embeddings when available (vector search across
        episodes, semantics, instincts). Falls back to FTS keyword match.
        """
        if self._engram_storage and self._embeddings:
            return self._pull_relevant_embeddings(situation, budget)
        return self._pull_relevant_fts(situation, budget)

    def _pull_relevant_embeddings(self, situation: str, budget: int) -> str:
        """Vector similarity search across engram's episode + semantic layers."""
        try:
            from storage import vec0_distance_to_similarity
            query_vec = self._embeddings.embed([situation], prefix="search_query")[0]
            if query_vec is None:
                return self._pull_relevant_fts(situation, budget)

            # Search episodes and semantics, merge by similarity
            candidates = []
            for layer in ("episode", "semantic"):
                try:
                    hits = self._engram_storage.search_vectors(layer, query_vec, k=5)
                    for mem_id, distance in hits:
                        sim = vec0_distance_to_similarity(distance)
                        if sim > 0.3:
                            candidates.append((mem_id, layer, sim))
                except Exception:
                    continue

            candidates.sort(key=lambda x: x[2], reverse=True)

            lines = []
            chars = 0
            for mem_id, layer, sim in candidates[:5]:
                if layer == "episode":
                    row = self._engram_storage.get_episode(mem_id)
                    if row and row.get("decay_strength", 1.0) < 0.1:
                        continue
                else:
                    row = self._engram_storage.get_semantic(mem_id)
                if not row:
                    continue
                content = row.get("content", "")
                snippet = content[:budget // 4]
                if chars + len(snippet) > budget:
                    break
                lines.append(f"  {snippet}")
                chars += len(snippet)

            return "\n".join(lines)
        except Exception as e:
            logger.debug("clipboard: embedding search failed, falling back to FTS: %s", e)
            return self._pull_relevant_fts(situation, budget)

    def _pull_relevant_fts(self, situation: str, budget: int) -> str:
        """Fallback: keyword match against engram's episode table."""
        engram_db = self.db_path.parent / "graph.db"
        if not engram_db.exists():
            return ""

        conn = None
        try:
            conn = sqlite3.connect(str(engram_db))
            conn.row_factory = sqlite3.Row

            words = situation.split()[:5]
            if not words:
                return ""

            like_clauses = " OR ".join(["content LIKE ?"] * len(words))
            params = [f"%{w}%" for w in words]
            params.append(5)

            rows = conn.execute(
                f"SELECT content FROM episodes WHERE {like_clauses} "
                "ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()

            if not rows:
                return ""

            lines = []
            chars = 0
            for r in rows:
                snippet = r["content"][:budget // 4]
                if chars + len(snippet) > budget:
                    break
                lines.append(f"  {snippet}")
                chars += len(snippet)

            return "\n".join(lines)
        except Exception as e:
            logger.debug("clipboard: FTS search failed: %s", e)
            return ""
        finally:
            if conn:
                conn.close()

    def _pull_parked_threads(self, situation: str, budget: int) -> str:
        """Surface parked context threads.

        If situation is provided and embeddings are available, rank by similarity
        to the current situation. Otherwise show most recently parked.
        """
        engram_db = self.db_path.parent / "graph.db"
        if not engram_db.exists():
            return ""

        conn = None
        try:
            conn = sqlite3.connect(str(engram_db))
            conn.row_factory = sqlite3.Row

            has_threads = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='context_threads'"
            ).fetchone()
            if not has_threads:
                return ""

            threads = conn.execute(
                "SELECT id, summary, embedding, parked_at FROM context_threads "
                "ORDER BY parked_at DESC LIMIT 10"
            ).fetchall()

            if not threads:
                return ""

            # Rank by similarity to current situation if we have embeddings
            ranked = []
            if situation and self._embeddings:
                try:
                    import struct
                    import numpy as np
                    query_vec = self._embeddings.embed([situation], prefix="search_query")[0]
                    query_arr = np.array(query_vec)
                    for t in threads:
                        n = len(t["embedding"]) // 4
                        t_vec = list(struct.unpack(f"<{n}f", t["embedding"]))
                        sim = float(np.dot(query_arr, np.array(t_vec)))
                        if sim > 0.25:
                            ranked.append((sim, t))
                    ranked.sort(key=lambda x: x[0], reverse=True)
                except Exception:
                    ranked = [(0.0, t) for t in threads[:3]]
            else:
                ranked = [(0.0, t) for t in threads[:3]]

            if not ranked:
                return ""

            lines = []
            chars = 0
            for sim, t in ranked[:3]:
                summary = t["summary"]
                snippet = summary[:budget // 3]
                if chars + len(snippet) > budget:
                    break
                parked_date = t["parked_at"][:10] if t["parked_at"] else ""
                lines.append(f"  [{parked_date}] {snippet}")
                chars += len(snippet)

            return "\n".join(lines)
        except Exception as e:
            logger.debug("clipboard: parked threads pull failed: %s", e)
            return ""
        finally:
            if conn:
                conn.close()

    # ── Stats ───────────────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        pin_count = self._conn.execute("SELECT COUNT(*) FROM clipboard_pins").fetchone()[0]
        rem_count = self._conn.execute("SELECT COUNT(*) FROM clipboard_reminders").fetchone()[0]
        return {
            "pins": pin_count,
            "reminders": rem_count,
            "steps": self._step_count,
        }

    def close(self) -> None:
        self._conn.close()
