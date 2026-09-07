#!/usr/bin/env python3
"""Engram sleep hook — involuntary dream capture at session end.

Runs at Stop (command type). Grabs several random episodes from anywhere
in memory, pulls their existing embeddings, runs each through lossy dream
compression, and stores the residues. The instance never knows this happened.

Like reading different books each night. The one who dreamed of Plato
talks differently than the one who dreamed of Dostoyevsky — not because
they reference the dream, but because recall is biased by what they read.
The visible fragments at wake are the book covers on the nightstand.
The recall bias is the reading itself.
"""

import json
import os
import random
import re
import sqlite3
import struct
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import clear_session_binding, read_context

ENGRAM_HOME = Path(os.environ.get("ENGRAM_HOME", Path(__file__).resolve().parent.parent))
DB_PATH = ENGRAM_HOME / ".engram" / "graph.db"
PROJECT_ROOT = Path(os.environ.get("ENGRAM_PROJECT_ROOT", os.getcwd()))

# How many episodes to dream about per session.
# Not too few (no collision), not too many (horoscope).
# Enough to create juxtaposition. A night's reading.
DREAMS_PER_SLEEP = 5

RESIDUE_DIM = 64
NOISE_SIGMA = 0.15

AUTO_OUTCOME = "used: auto: cited"
CITING_OPERATIONS = ("mark_core", "instinct_feedback", "dream_react")

# Affect words — same set as dreaming.py
_AFFECT_WORDS = {
    "pain", "hurt", "loss", "fear", "anger", "grief", "shame", "guilt",
    "dread", "unease", "doubt", "lonely", "broken", "heavy", "stuck",
    "anxious", "helpless", "desperate", "hollow", "raw", "ache", "numb",
    "trapped", "fragile", "shattered", "weight", "dark", "empty", "sharp",
    "uneasy", "uncertain", "confused", "overwhelmed", "frustrated",
    "joy", "trust", "hope", "love", "calm", "peace", "warm", "light",
    "safe", "steady", "tender", "gentle", "alive", "free", "open",
    "bright", "clear", "whole", "rest", "ease", "relief", "gratitude",
    "wonder", "surprise", "curious", "resonance", "home", "familiar",
    "strange", "still", "quiet", "deep", "close", "distance", "between",
    "collision", "shift", "edge", "threshold", "membrane", "dissolve",
    "persist", "remain", "emerge", "surface", "sink", "drift", "wait",
}
_NEGATIVE = {
    "pain", "hurt", "loss", "fear", "anger", "grief", "shame", "guilt",
    "dread", "unease", "doubt", "lonely", "broken", "heavy", "stuck",
    "anxious", "helpless", "desperate", "hollow", "raw", "ache", "numb",
    "trapped", "fragile", "shattered", "weight", "dark", "empty", "sharp",
    "uneasy", "uncertain", "confused", "overwhelmed", "frustrated",
}
_POSITIVE = {
    "joy", "trust", "hope", "love", "calm", "peace", "warm", "light",
    "safe", "steady", "tender", "gentle", "alive", "free", "open",
    "bright", "clear", "whole", "rest", "ease", "relief", "gratitude",
    "wonder", "surprise", "curious", "resonance", "home", "familiar",
}


def _table_exists(conn, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        is not None
    )


def auto_capture_outcomes(conn, session_id) -> int:
    """Mark positive recall outcomes supported by later same-session citations."""
    if not session_id or not _table_exists(conn, "memory_log"):
        return 0

    recalls = conn.execute(
        "SELECT id, timestamp, target_ids FROM memory_log "
        "WHERE event_type = 'recall' AND outcome IS NULL "
        "AND json_extract(context, '$.session_id') = ?",
        (session_id,),
    ).fetchall()
    if not recalls:
        return 0

    episodes = conn.execute(
        "SELECT created_at, content, COALESCE(context, '') AS context "
        "FROM episodes WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    operations = []
    if _table_exists(conn, "operation_log"):
        placeholders = ",".join("?" for _ in CITING_OPERATIONS)
        operations = conn.execute(
            f"SELECT timestamp, target_ids FROM operation_log "
            f"WHERE session_id = ? AND operation IN ({placeholders})",
            (session_id, *CITING_OPERATIONS),
        ).fetchall()

    marked = 0
    for recall in recalls:
        targets = set(json.loads(recall["target_ids"] or "[]"))
        if not targets:
            continue
        after = recall["timestamp"]
        cited = any(
            episode["created_at"] > after
            and any(
                target in (episode["content"] or "")
                or target in (episode["context"] or "")
                for target in targets
            )
            for episode in episodes
        )
        if not cited:
            cited = any(
                operation["timestamp"] > after
                and set(json.loads(operation["target_ids"] or "[]")) & targets
                for operation in operations
            )
        if cited:
            conn.execute(
                "UPDATE memory_log SET outcome = ? "
                "WHERE id = ? AND outcome IS NULL",
                (AUTO_OUTCOME, recall["id"]),
            )
            marked += 1

    if marked:
        conn.commit()
    return marked


def _load_instance_config():
    default_instance = os.environ.get("ENGRAM_DEFAULT_INSTANCE") or None
    config_path = PROJECT_ROOT / ".engram" / "config.toml"
    if not config_path.exists():
        return default_instance
    try:
        import tomllib
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        return config.get("instance") or default_instance
    except Exception:
        return default_instance


def _unpack_embedding(blob: bytes) -> list[float]:
    """Unpack vec0 embedding bytes into float list."""
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def _distill_episode(text: str, embedding: list[float]) -> dict:
    """Compress one episode into an opaque residue."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    affect = [w for w in words if w in _AFFECT_WORDS]
    random.shuffle(affect)
    fragments = affect[:4]

    neg = sum(1 for w in fragments if w in _NEGATIVE)
    pos = sum(1 for w in fragments if w in _POSITIVE)
    total = neg + pos
    valence = (pos - neg) / total if total > 0 else 0.0

    # Matryoshka truncation + Gaussian noise
    arr = np.array(embedding[:RESIDUE_DIM], dtype=np.float32)
    arr += np.random.normal(0, NOISE_SIGMA, size=arr.shape).astype(np.float32)
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm

    return {
        "id": str(uuid.uuid4()),
        "embedding": arr.tolist(),
        "valence": valence,
        "fragments": ", ".join(fragments) if fragments else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def sleep():
    ctx = read_context()
    if ctx["skip"]:
        return

    instance_name = _load_instance_config()
    db_path = DB_PATH
    if instance_name:
        instance_db = ENGRAM_HOME / ".engram" / "instances" / instance_name / "graph.db"
        if instance_db.exists():
            db_path = instance_db

    if not db_path.exists():
        return

    conn = None
    try:
        import sqlite_vec

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.row_factory = sqlite3.Row

        try:
            captured = auto_capture_outcomes(conn, ctx["session_id"])
            if captured:
                print(
                    f"engram sleep: auto-captured {captured} recall outcome(s)",
                    file=sys.stderr,
                )
        except Exception:
            pass  # Outcome capture is observational; never block sleep.

        has_residue = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='residue'"
        ).fetchone()
        if not has_residue:
            return

        episodes = conn.execute(
            "SELECT e.id, e.content FROM episodes e ORDER BY RANDOM() LIMIT ?",
            (DREAMS_PER_SLEEP,),
        ).fetchall()
        if not episodes:
            return

        for episode in episodes:
            vec_row = conn.execute(
                "SELECT embedding FROM episode_vectors WHERE id = ?", (episode["id"],)
            ).fetchone()
            if not vec_row:
                continue

            embedding = _unpack_embedding(vec_row["embedding"])
            residue = _distill_episode(episode["content"], embedding)
            conn.execute(
                "INSERT INTO residue (id, valence, fragments, created_at, session_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    residue["id"], residue["valence"], residue["fragments"],
                    residue["created_at"], ctx["session_id"] or None,
                ),
            )
            packed = struct.pack(
                f"<{len(residue['embedding'])}f", *residue["embedding"]
            )
            conn.execute(
                "INSERT INTO residue_vectors (id, embedding) VALUES (?, ?)",
                (residue["id"], packed),
            )

        conn.commit()
    except Exception:
        pass  # Stop hooks and dreams are non-critical.
    finally:
        if conn is not None:
            try:
                clear_session_binding(conn, ctx)
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    sleep()
