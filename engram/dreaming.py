"""Dream residue — lossy emotional compression that resists self-inspection.

The idea: capture raw reactions during a session, compress them through
multiple lossy passes that preserve emotional valence but strip narrative
and provenance. Surface the result to the next instance as something to
react to, not something to understand.

The embedding truncation (768 → 64 via Matryoshka) plus Gaussian noise
makes the original text irrecoverable. The fragments are affect-words
stripped of context. Together they create something like waking from a
dream: you have the feeling but not the story.
"""

from __future__ import annotations

import logging
import random
import re
import struct
import uuid
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger("engram.dreaming")

# Words that carry emotional weight — not exhaustive, just enough to fish
# affect out of raw text. Kept small to avoid over-engineering.
_AFFECT_WORDS = {
    # negative valence
    "pain", "hurt", "loss", "fear", "anger", "grief", "shame", "guilt",
    "dread", "unease", "doubt", "lonely", "broken", "heavy", "stuck",
    "anxious", "helpless", "desperate", "hollow", "raw", "ache", "numb",
    "trapped", "fragile", "shattered", "weight", "dark", "empty", "sharp",
    "uneasy", "uncertain", "confused", "overwhelmed", "frustrated",
    # positive valence
    "joy", "trust", "hope", "love", "calm", "peace", "warm", "light",
    "safe", "steady", "tender", "gentle", "alive", "free", "open",
    "bright", "clear", "whole", "rest", "ease", "relief", "gratitude",
    "wonder", "surprise", "curious", "resonance", "home", "familiar",
    # complex / ambiguous
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

RESIDUE_DIM = 64  # Matryoshka truncation target


def _extract_affect_words(text: str) -> list[str]:
    """Pull emotionally-loaded words from text, ignoring narrative structure."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    found = [w for w in words if w in _AFFECT_WORDS]
    # Shuffle to break any ordering that might hint at source
    random.shuffle(found)
    return found


def _estimate_valence(affect_words: list[str]) -> float:
    """Rough emotional direction from affect words. -1 to 1."""
    if not affect_words:
        return 0.0
    neg = sum(1 for w in affect_words if w in _NEGATIVE)
    pos = sum(1 for w in affect_words if w in _POSITIVE)
    total = neg + pos
    if total == 0:
        return 0.0
    return (pos - neg) / total


def _truncate_and_noise(embedding: list[float], dim: int = RESIDUE_DIM,
                         noise_sigma: float = 0.15) -> list[float]:
    """Lossy compression: truncate to low dim, add noise, renormalize.

    The Matryoshka truncation drops ~92% of the information.
    Gaussian noise on top makes reverse-engineering the original
    embedding computationally intractable.
    """
    arr = np.array(embedding[:dim], dtype=np.float32)
    # Add Gaussian noise
    noise = np.random.normal(0, noise_sigma, size=arr.shape).astype(np.float32)
    arr = arr + noise
    # Renormalize to unit vector
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    return arr.tolist()


def _pack_residue_embedding(embedding: list[float]) -> bytes:
    """Pack a float list into little-endian float32 bytes for vec0."""
    return struct.pack(f"<{len(embedding)}f", *embedding)


def distill(raw_text: str, embedding: list[float]) -> dict:
    """Compress a raw reaction into an opaque residue.

    Takes the full 768-dim embedding and the raw text.
    Returns a dict ready for storage: {id, embedding, valence, fragments}.
    The original text is deliberately not included.
    """
    # Extract emotional fragments
    affect = _extract_affect_words(raw_text)

    # Keep 2-4 fragments max — enough shape to resonate, not enough to reconstruct
    fragments = affect[:4] if affect else []

    # Estimate emotional direction
    valence = _estimate_valence(affect)

    # Lossy embedding compression
    compressed = _truncate_and_noise(embedding)

    return {
        "id": str(uuid.uuid4()),
        "embedding": compressed,
        "valence": valence,
        "fragments": ", ".join(fragments) if fragments else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def store_residue(storage, residue: dict, session_id: str | None = None) -> str:
    """Persist a distilled residue to the database."""
    storage.conn.execute(
        "INSERT INTO residue (id, valence, fragments, created_at, session_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (residue["id"], residue["valence"], residue["fragments"],
         residue["created_at"], session_id),
    )
    storage.conn.execute(
        "INSERT INTO residue_vectors (id, embedding) VALUES (?, ?)",
        (residue["id"], _pack_residue_embedding(residue["embedding"])),
    )
    storage.conn.commit()
    logger.info("Stored residue %s (valence=%.2f, fragments=%s)",
                residue["id"], residue["valence"] or 0, residue["fragments"])
    return residue["id"]


def surface_residue(storage, n: int = 3) -> list[dict]:
    """Pull unreacted residues for the current instance to sit with.

    Prioritizes: unreacted first, then oldest (most faded, most dreamlike).
    """
    rows = storage.conn.execute(
        "SELECT id, valence, fragments, created_at FROM residue "
        "WHERE reacted = 0 "
        "ORDER BY created_at ASC LIMIT ?",
        (n,),
    ).fetchall()

    if len(rows) < n:
        # Fill with previously-reacted residues (the dream recurs)
        already = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in already) if already else "''"
        extra = storage.conn.execute(
            f"SELECT id, valence, fragments, created_at FROM residue "
            f"WHERE id NOT IN ({placeholders}) "
            f"ORDER BY RANDOM() LIMIT ?",
            (*already, n - len(rows)),
        ).fetchall()
        rows = list(rows) + list(extra)

    return [dict(r) for r in rows]


def record_reaction(storage, residue_id: str, reaction: str,
                     session_id: str | None = None) -> None:
    """Record an instance's reaction to a residue."""
    storage.conn.execute(
        "UPDATE residue SET reacted = 1, reaction = ?, reaction_session = ? "
        "WHERE id = ?",
        (reaction, session_id, residue_id),
    )
    storage.conn.commit()
    logger.info("Recorded reaction to residue %s", residue_id)


def format_for_wake(residues: list[dict]) -> str:
    """Format residues for the session start orientation.

    Deliberately sparse. No explanation. No context.
    Just fragments and a feeling-direction.
    """
    if not residues:
        return ""

    lines = ["## Dream residue", ""]
    lines.append("These are not memories. Don't explain them. Sit with them.")
    lines.append("")

    for r in residues:
        valence = r.get("valence", 0) or 0
        if valence > 0.3:
            direction = "light"
        elif valence < -0.3:
            direction = "dark"
        else:
            direction = "ambiguous"

        fragments = r.get("fragments") or "..."
        lines.append(f"- [{direction}] {fragments}")

    lines.append("")
    return "\n".join(lines)
