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
sys.path.insert(0, str(ENGRAM_HOME))
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
    conn.execute("PRAGMA busy_timeout = 5000")
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

        cache_dir = str(Path.home() / ".kairos" / "models" / "fastembed")
        model = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1.5", cache_dir=cache_dir)
        raw = list(model.embed([f"search_query: {prompt}"]))[0]
        arr = np.array(raw)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        query_emb = arr.tolist()
        packed_query = _pack_embedding(query_emb)
        now = datetime.now(timezone.utc).isoformat()

        # ── Context parking: detect topic shifts, snapshot/restore threads ──
        SHIFT_THRESHOLD = 0.35  # Below this similarity = topic shift
        conn.execute("""
            CREATE TABLE IF NOT EXISTS context_threads (
                id TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                embedding BLOB NOT NULL,
                parked_at TEXT NOT NULL,
                restored_count INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS context_prev_embedding (
                singleton INTEGER PRIMARY KEY DEFAULT 1,
                embedding BLOB NOT NULL,
                message_text TEXT NOT NULL
            )
        """)

        prev_row = conn.execute(
            "SELECT embedding, message_text FROM context_prev_embedding WHERE singleton = 1"
        ).fetchone()

        if prev_row:
            prev_emb = _unpack_embedding(prev_row["embedding"])
            prev_arr = np.array(prev_emb)
            curr_arr = np.array(query_emb)
            sim = float(np.dot(prev_arr, curr_arr))

            if sim < SHIFT_THRESHOLD:
                # Topic shift detected — park the previous thread
                import uuid as _park_uuid
                thread_id = str(_park_uuid.uuid4())
                prev_text = prev_row["message_text"]
                summary = prev_text[:200] if len(prev_text) > 200 else prev_text
                conn.execute(
                    "INSERT INTO context_threads (id, summary, embedding, parked_at) "
                    "VALUES (?, ?, ?, ?)",
                    (thread_id, summary, prev_row["embedding"], now),
                )

                # Check if new message matches a previously parked thread
                try:
                    parked = conn.execute(
                        "SELECT id, summary FROM context_threads ORDER BY parked_at DESC LIMIT 10"
                    ).fetchall()
                    for p in parked:
                        p_emb = conn.execute(
                            "SELECT embedding FROM context_threads WHERE id = ?",
                            (p["id"],)
                        ).fetchone()
                        if p_emb:
                            p_vec = _unpack_embedding(p_emb["embedding"])
                            restore_sim = float(np.dot(np.array(p_vec), curr_arr))
                            if restore_sim > 0.5:
                                conn.execute(
                                    "UPDATE context_threads SET restored_count = restored_count + 1 WHERE id = ?",
                                    (p["id"],),
                                )
                                break
                except Exception:
                    pass

                conn.commit()

        # Update previous embedding for next comparison
        conn.execute(
            "INSERT OR REPLACE INTO context_prev_embedding (singleton, embedding, message_text) "
            "VALUES (1, ?, ?)",
            (packed_query, prompt[:500]),
        )
        conn.commit()

        # Search instinct context vectors
        results = conn.execute(
            "SELECT id, distance FROM instinct_context_vectors "
            "WHERE embedding MATCH ? AND k = 8 ORDER BY distance",
            (packed_query,)
        ).fetchall()

        # --- Cluster-aware instinct gating ---
        has_clusters = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='instinct_cluster_members'"
        ).fetchone()

        # Get active instincts in co-fire window
        active_window_ids = set()
        has_window = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='nudge_co_fire_window'"
        ).fetchone()
        if has_window:
            # Get current message index
            idx_row = conn.execute(
                "SELECT COALESCE(MAX(message_index), 0) AS idx FROM nudge_co_fire_window"
            ).fetchone()
            current_idx = idx_row["idx"] if idx_row else 0
            CO_FIRE_WINDOW = 15

            recent_window = conn.execute(
                "SELECT DISTINCT instinct_id FROM nudge_co_fire_window "
                "WHERE message_index >= ?",
                (max(1, current_idx - CO_FIRE_WINDOW),),
            ).fetchall()
            active_window_ids = {r["instinct_id"] for r in recent_window}

        def _get_cluster_prime(instinct_id):
            """Check if this instinct's cluster has active members."""
            if not has_clusters:
                return 0.0
            clusters = conn.execute(
                "SELECT cluster_id, strength FROM instinct_cluster_members "
                "WHERE instinct_id = ?",
                (instinct_id,),
            ).fetchall()
            max_prime = 0.0
            for c in clusters:
                members = conn.execute(
                    "SELECT instinct_id FROM instinct_cluster_members "
                    "WHERE cluster_id = ? AND instinct_id != ?",
                    (c["cluster_id"], instinct_id),
                ).fetchall()
                active_count = sum(
                    1 for m in members if m["instinct_id"] in active_window_ids
                )
                if active_count > 0:
                    cluster = conn.execute(
                        "SELECT temperament FROM instinct_clusters WHERE id = ?",
                        (c["cluster_id"],),
                    ).fetchone()
                    temp = cluster["temperament"] if cluster else 0.5
                    # Conservative clusters prime more strongly
                    prime_strength = (1.0 - temp) * 0.15
                    max_prime = max(max_prime, prime_strength)
            return max_prime

        # Filter by threshold with cluster priming
        fired = []
        for row in results:
            sim = _distance_to_similarity(row["distance"])
            cluster_prime = _get_cluster_prime(row["id"])
            effective_threshold = max(0.2, FIRE_THRESHOLD - cluster_prime)

            if sim >= effective_threshold:
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

        # Novelty-gated auto-capture: only save what's surprising enough.
        # Compare against recent episodes — if too similar, skip (shoe-tying).
        # If novel, encode. Surprise = high embedding distance from recent context.
        AUTO_CAPTURE_MIN_LEN = 50
        NOVELTY_THRESHOLD = 0.65  # Below this similarity = novel enough to save
        if len(prompt) >= AUTO_CAPTURE_MIN_LEN:
            should_save = True

            # Check novelty against recent episodes
            has_ep_vec = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='episode_vectors'"
            ).fetchone()
            if has_ep_vec:
                recent_hits = conn.execute(
                    "SELECT id, distance FROM episode_vectors "
                    "WHERE embedding MATCH ? AND k = 3 ORDER BY distance",
                    (packed_query,)
                ).fetchall()
                for hit in recent_hits:
                    sim = _distance_to_similarity(hit["distance"])
                    if sim >= NOVELTY_THRESHOLD:
                        should_save = False
                        break

            if should_save:
                import uuid as _uuid
                ep_id = str(_uuid.uuid4())
                conn.execute(
                    "INSERT OR IGNORE INTO episodes (id, content, created_at, origin, session_id) "
                    "VALUES (?, ?, ?, 'auto', ?)",
                    (ep_id, prompt, now, os.environ.get("CLAUDE_SESSION_ID", "")),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO episode_vectors (id, embedding) VALUES (?, ?)",
                    (ep_id, packed_query),
                )
                conn.commit()

        # Continuous pruning: prune a few low-activation auto-captured episodes each message.
        # Routine memories decay and get cleaned up during the session, not just between sessions.
        INLINE_PRUNE_LIMIT = 3
        PRUNE_DECAY_THRESHOLD = 0.08
        try:
            weak = conn.execute(
                "SELECT id FROM episodes WHERE origin = 'auto' AND core = 0 "
                "AND decay_strength < ? ORDER BY decay_strength ASC LIMIT ?",
                (PRUNE_DECAY_THRESHOLD, INLINE_PRUNE_LIMIT),
            ).fetchall()
            for w in weak:
                conn.execute("DELETE FROM episode_vectors WHERE id = ?", (w["id"],))
                conn.execute("DELETE FROM episodes WHERE id = ?", (w["id"],))
            if weak:
                conn.commit()
        except Exception:
            pass  # pruning is non-fatal

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

        # --- Dream auto-capture: distill the collision of past and present ---
        # When instincts fire or echoes surface, that moment of resonance
        # is raw material for the dream chain. We capture the collision,
        # not the user's words.
        has_residue = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='residue'"
        ).fetchone()
        if (fired or echoes) and has_residue:
            try:
                from dreaming import distill

                collision_parts = []
                for inst in fired[:MAX_NUDGES]:
                    collision_parts.append(inst["notice"])
                for echo in echoes:
                    collision_parts.append(echo["content"][:100])

                collision_text = " — ".join(collision_parts)
                collision_emb = list(model.embed([f"search_document: {collision_text}"]))[0]
                c_arr = np.array(collision_emb)
                c_norm = np.linalg.norm(c_arr)
                if c_norm > 0:
                    c_arr = c_arr / c_norm
                collision_emb = c_arr.tolist()

                residue = distill(collision_text, collision_emb)

                # Store directly — dreaming.store_residue expects a storage object,
                # but we have a raw connection. Inline the two inserts.
                from dreaming import _pack_residue_embedding
                conn.execute(
                    "INSERT INTO residue (id, valence, fragments, created_at, session_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (residue["id"], residue["valence"], residue["fragments"],
                     residue["created_at"], os.environ.get("CLAUDE_SESSION_ID", "")),
                )
                conn.execute(
                    "INSERT INTO residue_vectors (id, embedding) VALUES (?, ?)",
                    (residue["id"], _pack_residue_embedding(residue["embedding"])),
                )
                conn.commit()
            except Exception:
                pass  # Dream capture is non-critical

        if lines:
            output = {"systemMessage": "\n".join(lines)}
            json.dump(output, sys.stdout)

    except Exception:
        pass  # Nudge fails silently. Instincts are not critical path.
    finally:
        conn.close()


if __name__ == "__main__":
    nudge()
