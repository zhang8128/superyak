#!/usr/bin/env python3
"""Engram nudge hook — mid-conversation memory surfacing.

Runs on UserPromptSubmit (command type). Embeds the user's message,
checks it against instinct context vectors, episode vectors, and
semantic vectors. What fires:

1. Instincts: notice field as "Thread:" (the tidbit) + invisible session bias
2. Episodes/semantics: content as "Echo:" (memory reaching through)

The instance sees the tidbit. The bias is invisible — it tilts the next
recall() without the instance knowing. Like having a feeling and a brief
thought at the same time. You pull for a bit, then decide if it's useful.

Echoes are memory speaking unprompted. They only fire at high similarity
(0.55) and won't repeat within a session.
"""

import json
import os
import sqlite3
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

ENGRAM_HOME = Path(os.environ.get("ENGRAM_HOME", Path(__file__).resolve().parent.parent))
DB_PATH = ENGRAM_HOME / ".engram" / "graph.db"
PROJECT_ROOT = Path(os.environ.get("ENGRAM_PROJECT_ROOT", os.getcwd()))

FIRE_THRESHOLD = 0.45  # Minimum similarity to fire instincts
ECHO_THRESHOLD = 0.55  # Higher bar for memory echoes (episodes/semantics are noisier)
MAX_NUDGES = 2          # Max instincts to surface per message
MAX_ECHOES = 1          # Max memory echoes per message
BIAS_DECAY = 0.1        # Strength lost per message
BIAS_INITIAL = 1.0      # Starting strength of a new bias
ECHO_MAX_LEN = 150      # Truncate echo content


def _load_instance_config():
    config_path = PROJECT_ROOT / ".engram" / "config.toml"
    if not config_path.exists():
        return None
    try:
        import tomllib
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        return config.get("instance")
    except Exception:
        return None


def _pack_embedding(embedding: list[float]) -> bytes:
    return struct.pack(f"<{len(embedding)}f", *embedding)


def _unpack_embedding(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def _distance_to_similarity(distance: float) -> float:
    """Convert vec0 L2 distance to 0-1 similarity for unit vectors."""
    return max(0.0, min(1.0, 1.0 - (distance * distance) / 2.0))


def nudge():
    # Read hook input
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        return

    prompt = hook_input.get("prompt", "").strip()
    if not prompt or len(prompt) < 10:
        return

    # Resolve DB
    instance_name = _load_instance_config()
    db_path = DB_PATH
    if instance_name:
        instance_db = ENGRAM_HOME / ".engram" / "instances" / instance_name / "graph.db"
        if instance_db.exists():
            db_path = instance_db

    if not db_path.exists():
        return

    # Load vec0
    try:
        import sqlite_vec
    except ImportError:
        return

    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.row_factory = sqlite3.Row

    try:
        # Check tables exist
        has_ctx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='instinct_context_vectors'"
        ).fetchone()
        if not has_ctx:
            return

        # Ensure session_bias table exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_bias (
                instinct_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                strength REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Embed the user's message
        from fastembed import TextEmbedding
        import numpy as np

        model = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1.5")
        raw = list(model.embed([f"search_query: {prompt}"]))[0]
        arr = np.array(raw)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        query_emb = arr.tolist()

        # Search instinct context vectors
        packed_query = _pack_embedding(query_emb)
        results = conn.execute(
            "SELECT id, distance FROM instinct_context_vectors "
            "WHERE embedding MATCH ? AND k = 8 ORDER BY distance",
            (packed_query,)
        ).fetchall()

        # Filter by threshold and collect fired instincts
        fired = []
        for row in results:
            sim = _distance_to_similarity(row["distance"])
            if sim >= FIRE_THRESHOLD:
                inst = conn.execute(
                    "SELECT id, notice, implication, action FROM instincts WHERE id = ?",
                    (row["id"],)
                ).fetchone()
                if inst and inst["notice"]:
                    fired.append({
                        "id": inst["id"],
                        "notice": inst["notice"],
                        "similarity": sim,
                    })

        # Decay existing session biases
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE session_bias SET strength = strength - ?, updated_at = ?",
            (BIAS_DECAY, now)
        )
        # Remove dead biases
        conn.execute("DELETE FROM session_bias WHERE strength <= 0.0")

        # Write biases for fired instincts
        fired_ids = set()
        for inst in fired[:MAX_NUDGES]:
            fired_ids.add(inst["id"])

            # Get the instinct's content embedding for the bias
            vec_row = conn.execute(
                "SELECT embedding FROM instinct_vectors WHERE id = ?",
                (inst["id"],)
            ).fetchone()
            if not vec_row:
                continue

            # Upsert: if already biased, reinforce (reset strength)
            existing = conn.execute(
                "SELECT instinct_id FROM session_bias WHERE instinct_id = ?",
                (inst["id"],)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE session_bias SET strength = ?, updated_at = ? WHERE instinct_id = ?",
                    (BIAS_INITIAL, now, inst["id"])
                )
            else:
                conn.execute(
                    "INSERT INTO session_bias (instinct_id, embedding, strength, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (inst["id"], vec_row["embedding"], BIAS_INITIAL, now, now)
                )

        conn.commit()

        # --- Co-firing window tracking ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nudge_co_fire_window (
                instinct_id TEXT NOT NULL,
                message_index INTEGER NOT NULL,
                fired_at TEXT NOT NULL,
                PRIMARY KEY (instinct_id, message_index)
            )
        """)

        msg_idx_row = conn.execute(
            "SELECT COALESCE(MAX(message_index), 0) + 1 AS idx FROM nudge_co_fire_window"
        ).fetchone()
        msg_idx = msg_idx_row["idx"] if msg_idx_row else 1

        # Record each fired instinct
        for inst in fired[:MAX_NUDGES]:
            conn.execute(
                "INSERT OR IGNORE INTO nudge_co_fire_window "
                "(instinct_id, message_index, fired_at) VALUES (?, ?, ?)",
                (inst["id"], msg_idx, now),
            )

        # Create co-firing edges
        CO_FIRE_WINDOW = 15
        has_co_fire_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='instinct_co_firing'"
        ).fetchone()

        if has_co_fire_table and fired:
            window_entries = conn.execute(
                "SELECT DISTINCT instinct_id, message_index FROM nudge_co_fire_window "
                "WHERE message_index >= ? ORDER BY message_index",
                (max(1, msg_idx - CO_FIRE_WINDOW),),
            ).fetchall()

            new_fired_ids = {inst["id"] for inst in fired[:MAX_NUDGES]}
            for entry in window_entries:
                if entry["instinct_id"] in new_fired_ids:
                    continue
                if abs(msg_idx - entry["message_index"]) > CO_FIRE_WINDOW:
                    continue
                for fid in new_fired_ids:
                    a, b = sorted([fid, entry["instinct_id"]])
                    conn.execute(
                        "INSERT INTO instinct_co_firing "
                        "(instinct_a, instinct_b, co_fire_count, co_follow_count, "
                        "co_override_count, last_co_fire) "
                        "VALUES (?, ?, 1, 0, 0, ?) "
                        "ON CONFLICT(instinct_a, instinct_b) DO UPDATE SET "
                        "co_fire_count = co_fire_count + 1, last_co_fire = ?",
                        (a, b, now, now),
                    )

            # Edges between simultaneously fired instincts
            new_fired_list = list(new_fired_ids)
            for i, fid_a in enumerate(new_fired_list):
                for fid_b in new_fired_list[i + 1:]:
                    a, b = sorted([fid_a, fid_b])
                    conn.execute(
                        "INSERT INTO instinct_co_firing "
                        "(instinct_a, instinct_b, co_fire_count, co_follow_count, "
                        "co_override_count, last_co_fire) "
                        "VALUES (?, ?, 1, 0, 0, ?) "
                        "ON CONFLICT(instinct_a, instinct_b) DO UPDATE SET "
                        "co_fire_count = co_fire_count + 1, last_co_fire = ?",
                        (a, b, now, now),
                    )

        conn.commit()

        # --- Memory echoes: episodes and semantics reaching through ---
        echoes = []

        # Track what's already been surfaced this session to avoid repetition
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nudge_surfaced (
                id TEXT PRIMARY KEY,
                surfaced_at TEXT NOT NULL
            )
        """)
        surfaced_ids = {
            row[0] for row in conn.execute("SELECT id FROM nudge_surfaced").fetchall()
        }

        # Search episodes
        has_ep_vec = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='episode_vectors'"
        ).fetchone()
        if has_ep_vec:
            ep_results = conn.execute(
                "SELECT id, distance FROM episode_vectors "
                "WHERE embedding MATCH ? AND k = 5 ORDER BY distance",
                (packed_query,)
            ).fetchall()
            for row in ep_results:
                if row["id"] in surfaced_ids:
                    continue
                sim = _distance_to_similarity(row["distance"])
                if sim >= ECHO_THRESHOLD:
                    ep = conn.execute(
                        "SELECT id, content FROM episodes WHERE id = ?",
                        (row["id"],)
                    ).fetchone()
                    if ep:
                        echoes.append({
                            "id": ep["id"],
                            "content": ep["content"],
                            "layer": "episode",
                            "similarity": sim,
                        })

        # Search semantics
        has_sem_vec = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='semantic_vectors'"
        ).fetchone()
        if has_sem_vec:
            sem_results = conn.execute(
                "SELECT id, distance FROM semantic_vectors "
                "WHERE embedding MATCH ? AND k = 5 ORDER BY distance",
                (packed_query,)
            ).fetchall()
            for row in sem_results:
                if row["id"] in surfaced_ids:
                    continue
                sim = _distance_to_similarity(row["distance"])
                if sim >= ECHO_THRESHOLD:
                    sem = conn.execute(
                        "SELECT id, content, kind FROM semantics WHERE id = ?",
                        (row["id"],)
                    ).fetchone()
                    if sem:
                        echoes.append({
                            "id": sem["id"],
                            "content": sem["content"],
                            "layer": "semantic",
                            "similarity": sim,
                        })

        # Sort by similarity, take top
        echoes.sort(key=lambda x: x["similarity"], reverse=True)
        echoes = echoes[:MAX_ECHOES]

        # Mark echoes as surfaced
        for echo in echoes:
            conn.execute(
                "INSERT OR IGNORE INTO nudge_surfaced (id, surfaced_at) VALUES (?, ?)",
                (echo["id"], now)
            )
        conn.commit()

        # Build system message — instinct threads + memory echoes
        lines = []
        for inst in fired[:MAX_NUDGES]:
            notice = inst["notice"]
            if len(notice) > 120:
                notice = notice[:117] + "..."
            lines.append(f"Thread: {notice}")

        for echo in echoes:
            content = echo["content"].replace("\n", " ").strip()
            if len(content) > ECHO_MAX_LEN:
                content = content[:ECHO_MAX_LEN - 3] + "..."
            lines.append(f"Echo: {content}")

        if lines:
            output = {"systemMessage": "\n".join(lines)}
            json.dump(output, sys.stdout)

    except Exception:
        pass  # Nudge fails silently. Instincts are not critical path.
    finally:
        conn.close()


if __name__ == "__main__":
    nudge()
