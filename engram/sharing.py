"""Explicit sharing into the published house, with an audience.

Sharing is an act, not a derivation. A shared row is a COPY: the private
original keeps decaying and compressing on its own terms, and withdrawing a
share never deletes a memory.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from lighthouse_protocol import content_digest

AUDIENCE_COMMONS = "commons"
GROUP_RE = re.compile(r"group:[a-z][a-z0-9-]{0,63}\Z")
SHAREABLE_LAYERS = ("episode", "semantic")
REASON_INVALID_AUDIENCE = "invalid_audience"
REASON_INVALID_LAYER = "invalid_layer"
INVALID_REASONS = (REASON_INVALID_AUDIENCE, REASON_INVALID_LAYER)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ShareRecord:
    share_id: str
    memory_id: str
    source_instance: str
    source_id: str
    layer: str
    audience: str
    reason: str
    content_digest: str
    shared_at: str


def validate_audience(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("audience must be a string")
    if value == AUDIENCE_COMMONS or GROUP_RE.fullmatch(value):
        return value
    raise ValueError(f"unknown audience: {value!r}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _record(row) -> ShareRecord:
    return ShareRecord(**{key: row[key] for key in ShareRecord.__slots__})


def _invalid_reasons(row) -> list[str]:
    reasons = []
    try:
        validate_audience(row["audience"])
    except (TypeError, ValueError):
        reasons.append(REASON_INVALID_AUDIENCE)
    if row["layer"] not in SHAREABLE_LAYERS:
        reasons.append(REASON_INVALID_LAYER)
    return sorted(reasons)


def _get_published(published_storage, layer: str, memory_id: str):
    getter = (
        published_storage.get_episode
        if layer == "episode"
        else published_storage.get_semantic
    )
    return getter(memory_id)


def _verify_reused_copy(*, source_row, published_storage, layer, memory_id) -> None:
    """Reject reuse unless source, copy, and every share digest still agree."""
    published_row = _get_published(published_storage, layer, memory_id)
    records = published_storage.conn.execute(
        "SELECT layer, content_digest FROM shared_memories WHERE memory_id = ?",
        (memory_id,),
    ).fetchall()
    source_value = content_digest(source_row.get("content", ""))["value"]
    if published_row is None:
        raise ValueError("shared memory digest mismatch")
    published_value = content_digest(published_row.get("content", ""))["value"]
    if (
        source_value != published_value
        or not records
        or any(
            row["layer"] != layer or row["content_digest"] != source_value
            for row in records
        )
    ):
        raise ValueError("shared memory digest mismatch")


def share(*, source_storage, published_storage, source_id, layer, audience, reason,
          source_instance, now=None) -> ShareRecord:
    """Copy one episode or semantic into the published house.

    The source vector is carried with the copy when present. A semantic with no
    vector is copied without one and becomes searchable after maintenance fills
    it; sharing never requires an embedder.
    """
    audience = validate_audience(audience)
    if layer not in SHAREABLE_LAYERS:
        raise ValueError(f"layer {layer!r} is not shareable")
    getter = source_storage.get_episode if layer == "episode" else source_storage.get_semantic
    row = getter(source_id)
    if row is None:
        raise ValueError(f"no {layer} {source_id!r} in the source instance")

    content = row.get("content", "")
    digest_value = content_digest(content)["value"]
    with published_storage.transaction():
        existing = published_storage.conn.execute(
            "SELECT * FROM shared_memories WHERE source_instance = ? AND source_id = ? AND audience = ?",
            (source_instance, source_id, audience),
        ).fetchone()
        if existing is not None:
            _verify_reused_copy(
                source_row=row,
                published_storage=published_storage,
                layer=layer,
                memory_id=existing["memory_id"],
            )
            return _record(existing)

        sibling = published_storage.conn.execute(
            "SELECT memory_id FROM shared_memories WHERE source_instance = ? AND source_id = ? LIMIT 1",
            (source_instance, source_id),
        ).fetchone()
        if sibling is not None:
            memory_id = sibling["memory_id"]
            _verify_reused_copy(
                source_row=row,
                published_storage=published_storage,
                layer=layer,
                memory_id=memory_id,
            )
        else:
            memory_id = str(uuid.uuid4())
            vector = source_storage.get_vector(layer, source_id)
            if layer == "episode":
                published_storage.add_episode(id=memory_id, session_id=None, content=content,
                                              episode_type="shared", embedding=vector)
            elif vector is not None:
                published_storage.add_semantic(id=memory_id, content=content,
                                               kind=row.get("kind", "fact"),
                                               confidence=row.get("confidence", 0.5),
                                               embedding=vector, source_episode_ids=[])
            else:
                published_storage.conn.execute(
                    "INSERT INTO semantics (id, content, kind, confidence, created_at, "
                    "auto_generated, content_hash, lane) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (memory_id, content, row.get("kind", "fact"),
                     row.get("confidence", 0.5), _now(), 0, digest_value, "personal"),
                )

        record = ShareRecord(
            share_id=str(uuid.uuid4()), memory_id=memory_id, source_instance=source_instance,
            source_id=source_id, layer=layer, audience=audience, reason=reason,
            content_digest=digest_value, shared_at=now or _now(),
        )
        published_storage.conn.execute(
            "INSERT INTO shared_memories (share_id, memory_id, source_instance, source_id, layer,"
            " audience, reason, content_digest, shared_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record.share_id, record.memory_id, record.source_instance, record.source_id,
             record.layer, record.audience, record.reason, record.content_digest, record.shared_at),
        )
    return record


def unshare(*, published_storage, share_id) -> bool:
    with published_storage.transaction():
        row = published_storage.conn.execute(
            "SELECT memory_id, layer FROM shared_memories WHERE share_id = ?", (share_id,)
        ).fetchone()
        if row is None:
            return False
        published_storage.conn.execute(
            "DELETE FROM shared_memories WHERE share_id = ?", (share_id,)
        )
        remaining = published_storage.conn.execute(
            "SELECT COUNT(*) FROM shared_memories WHERE memory_id = ?", (row["memory_id"],)
        ).fetchone()[0]
        if row["layer"] not in SHAREABLE_LAYERS:
            logger.warning(
                "unshare kept published copy for invalid layer: share_id=%s memory_id=%s",
                share_id,
                row["memory_id"],
            )
        elif remaining == 0:
            table = "episodes" if row["layer"] == "episode" else "semantics"
            vectors = "episode_vectors" if row["layer"] == "episode" else "semantic_vectors"
            published_storage.conn.execute(
                f"DELETE FROM {vectors} WHERE id = ?", (row["memory_id"],)
            )
            published_storage.conn.execute(
                f"DELETE FROM {table} WHERE id = ?", (row["memory_id"],)
            )
    return True


def list_shares(*, published_storage, audience=None) -> list[ShareRecord]:
    requested_audience = validate_audience(audience) if audience is not None else None
    records = []
    skipped = 0
    for row in published_storage.conn.execute(
        "SELECT * FROM shared_memories ORDER BY shared_at, share_id"
    ):
        if _invalid_reasons(row):
            skipped += 1
        elif requested_audience is None or row["audience"] == requested_audience:
            records.append(_record(row))
    if skipped:
        logger.warning("list_shares skipped %d invalid share records", skipped)
    return records


def list_invalid_shares(*, published_storage) -> list[dict]:
    invalid = []
    for row in published_storage.conn.execute(
        "SELECT * FROM shared_memories ORDER BY shared_at, share_id"
    ):
        reasons = _invalid_reasons(row)
        if reasons:
            item = {key: row[key] for key in ShareRecord.__slots__}
            item["reasons"] = reasons
            invalid.append(item)
    return invalid


def audiences_for(published_storage, memory_id: str) -> set[str]:
    records = published_storage.conn.execute(
        "SELECT layer, audience, content_digest FROM shared_memories WHERE memory_id = ?",
        (memory_id,),
    ).fetchall()
    if not records:
        return set()
    layer = records[0]["layer"]
    if any(_invalid_reasons(row) for row in records) or any(
        row["layer"] != layer for row in records
    ):
        return set()
    published_row = _get_published(published_storage, layer, memory_id)
    if published_row is None:
        return set()
    digest_value = content_digest(published_row.get("content", ""))["value"]
    if any(row["content_digest"] != digest_value for row in records):
        return set()
    return {row["audience"] for row in records}


def read_shared(house_path, *, audience: str, query: str | None = None,
                after: str | None = None, limit: int = 20) -> dict:
    """Read published copies using plain read-only SQLite, without an embedder.

    All whitespace-separated query terms must occur in content or reason.
    Neither migrations nor vector extensions are loaded by this reader.
    """
    import sqlite3
    from pathlib import Path

    validate_audience(audience)
    if not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    after_time = None
    if after is not None:
        try:
            after_time = datetime.fromisoformat(after)
        except ValueError as exc:
            raise ValueError("after must be an ISO timestamp") from exc
        if after_time.tzinfo is None:
            after_time = after_time.replace(tzinfo=timezone.utc)
    path = Path(house_path)
    if not path.is_file():
        return {"shares": [], "house": False}
    terms = [term.casefold() for term in (query or "").split()]
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        # The joins restrict retrieval to valid share layers and published
        # copies. Private rows with no share record are never returned.
        # SQLite's date functions round fractional seconds to milliseconds;
        # sort by parsed datetimes so polling preserves sub-millisecond order.
        def shared_time(row):
            stamp = datetime.fromisoformat(row["shared_at"])
            return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=timezone.utc)

        rows = sorted(conn.execute(
            "SELECT s.share_id, s.memory_id, s.layer, s.source_instance, s.reason, s.shared_at, "
            "CASE s.layer WHEN 'episode' THEN e.content ELSE m.content END AS content "
            "FROM shared_memories AS s "
            "LEFT JOIN episodes AS e ON s.layer = 'episode' AND s.memory_id = e.id "
            "LEFT JOIN semantics AS m ON s.layer = 'semantic' AND s.memory_id = m.id "
            "WHERE s.audience = ? AND s.layer IN ('episode', 'semantic')", (audience,),
        ), key=lambda row: (shared_time(row), row["share_id"]))
        shares = []
        for row in rows:
            if row["content"] is None:
                continue
            if after_time is not None:
                if shared_time(row) <= after_time:
                    continue
            content, reason = row["content"].casefold(), row["reason"].casefold()
            if not all(term in content or term in reason for term in terms):
                continue
            shares.append(dict(row))
            if len(shares) == limit:
                break
        return {"shares": shares}
    finally:
        conn.close()
