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
from permissions import MAX_PLACEMENTS

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
          source_instance, now=None, source_instance_id=None, record_id=None) -> ShareRecord:
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
            # A row `migrate` left unmatched is mended here (P 12.3 step 2): fill what is null, never overwrite.
            for column, value in (("source_instance_id", source_instance_id), ("record_id", record_id)):
                if value is not None and existing[column] is None:
                    published_storage.conn.execute(
                        f"UPDATE shared_memories SET {column} = ? WHERE share_id = ? AND {column} IS NULL",
                        (value, existing["share_id"]))
            return _record(existing)

        placed = published_storage.conn.execute("SELECT COUNT(*) FROM shared_memories").fetchone()[0]
        if placed >= MAX_PLACEMENTS:
            raise ValueError(f"a house holds at most {MAX_PLACEMENTS:,} placements")

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
            " audience, reason, content_digest, shared_at, source_instance_id, record_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record.share_id, record.memory_id, record.source_instance, record.source_id,
             record.layer, record.audience, record.reason, record.content_digest, record.shared_at,
             source_instance_id, record_id),
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


@dataclass(frozen=True, slots=True)
class SweepReport:
    relinked: int = 0
    removed: int = 0
    would_remove: int = 0
    settled: int = 0


def sweep_placements(*, published_storage, ledger, mode: str, now: int, limit: int = 256) -> SweepReport:
    """P 10: make the house follow the ledger. A placement whose linked record no longer counts is relinked to
    another effective allow with the same placement audience, or removed (its copy and vector go with its last
    share row, as `unshare` does). Under `shadow` removals are only counted. At most `limit` placements are
    changed per pass, oldest first. Pending lane notes are settled from the source store's own lane, read-only.
    A placement with no record is not the sweep's. Under any other mode nothing is done."""
    if mode not in ("shadow", "enforce"):
        return SweepReport()
    from permissions import placement_still_counts, relink_cover
    state = ledger.state()
    owner = state.meta["owner"]
    relinked = removed = would_remove = 0
    rows = published_storage.conn.execute(
        "SELECT share_id, layer, audience, source_id, source_instance_id, record_id FROM shared_memories "
        "WHERE record_id IS NOT NULL AND source_instance_id IS NOT NULL ORDER BY shared_at, share_id").fetchall()
    for row in rows:
        if relinked + removed + would_remove >= limit:
            break
        if row["record_id"] not in state.records:
            continue            # not a record of this ledger: the sweep cannot judge it, and a use is refused anyway
        obj = f"mem:{row['source_instance_id']}/{row['layer']}/{row['source_id']}"
        try:
            if placement_still_counts(state, row["record_id"], owner=owner, obj=obj, at=now):
                continue
            target = relink_cover(state, old_id=row["record_id"], owner=owner, obj=obj,
                                  audience=row["audience"], at=now)
        except ValueError:
            logger.warning("sweep: placement %s has an unreadable object ref", row["share_id"])
            continue
        if mode == "shadow":
            if target is None:
                would_remove += 1
        elif target is not None:
            with published_storage.transaction():
                published_storage.conn.execute(
                    "UPDATE shared_memories SET record_id = ? WHERE share_id = ?", (target, row["share_id"]))
            relinked += 1
        else:
            unshare(published_storage=published_storage, share_id=row["share_id"])
            removed += 1
    return SweepReport(relinked, removed, would_remove, _settle_lane_notes(ledger, state, now))


def _settle_lane_notes(ledger, state, now: int) -> int:
    """A `pending` lane note that nothing settled (the process died between the store's commit and the settling
    note) gets the lane the source store holds now. The store is opened read-only; a store that is not found,
    or a memory it no longer has, stays pending, which only narrows."""
    import sqlite3
    from permission_ledger import houses
    from store_identity import read as read_identity
    pending: dict[str, list[tuple[str, str]]] = {}
    for obj, notes in state.lane_notes.items():
        if notes and notes[-1].lane == "pending":
            parts = obj[len("mem:"):].split("/") if obj.startswith("mem:") else []
            if len(parts) == 3 and parts[1] == "episode":
                pending.setdefault(parts[0], []).append((parts[2], obj))
    settled = 0
    if not pending:
        return 0
    for path in houses(ledger.root):
        try:
            con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            con.row_factory = sqlite3.Row
            wanted = pending.get(read_identity(con).get("instance_id"))
            if not wanted:
                continue
            for ep, _obj in wanted:
                found = con.execute("SELECT lane FROM episodes WHERE id = ?", (ep,)).fetchone()
                lane = None if found is None else (found["lane"] or "personal")
                if lane in ("personal", "work"):
                    ledger.note_lanes("after", [{"id": ep}], lane, store_id=read_identity(con)["instance_id"],
                                      now=now)
                    settled += 1
        except sqlite3.Error:
            logger.warning("sweep: could not read lanes from %s", path, exc_info=True)
        finally:
            con.close()
    return settled
