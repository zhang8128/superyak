"""Explicit sharing into the published house, with an audience.

Sharing is an act, not a derivation. A shared row is a COPY: the private
original keeps decaying and compressing on its own terms, and withdrawing a
share never deletes a memory.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import store_identity
from lighthouse_protocol import content_digest
from permissions import MAX_PLACEMENTS

AUDIENCE_COMMONS = "commons"
GROUP_RE = re.compile(r"group:[a-z][a-z0-9-]{0,63}\Z")
SHAREABLE_LAYERS = ("episode", "semantic")
REASON_INVALID_AUDIENCE = "invalid_audience"
REASON_INVALID_LAYER = "invalid_layer"
INVALID_REASONS = (REASON_INVALID_AUDIENCE, REASON_INVALID_LAYER)
CAPTURED_SOURCE = "auto"            # hooks/nudge.py stores a person's novel prompts verbatim with this source

logger = logging.getLogger(__name__)


class CapturedRefused(ValueError):
    """A captured prompt, or knowledge built from one, is never shared: it is what a person typed, not what a ship
    chose to remember."""


def _read_cold(source_storage, read, absent):
    """`read(conn)` over the store's cold storage, read-only: its open cold connection when it has one, else the
    file opened `mode=ro`. `absent` when there is no cold storage; None when it exists but cannot be read. Never
    creates cold.db (Storage._cold_storage would)."""
    conn = getattr(source_storage, "_cold_conn", None)
    opened = None
    try:
        if conn is None:
            db_path = getattr(source_storage, "db_path", None)
            if not db_path or db_path == ":memory:" or not Path(db_path).is_file():
                return absent
            cold = Path(db_path).with_name("cold.db")
            if not cold.is_file():
                return absent
            conn = opened = sqlite3.connect(f"file:{cold}?mode=ro", uri=True)
        return read(conn)
    except sqlite3.Error:
        return None
    finally:
        if opened is not None:
            opened.close()


def _cold_holds_capture(source_storage, digest: str) -> bool | None:
    """Whether the store's cold storage holds a capture whose text has this digest, read-only. None when cold
    storage exists but cannot be read."""
    return _read_cold(source_storage, lambda conn: _holds_capture(conn, digest), False)


def _holds_capture(conn, digest: str) -> bool:
    return conn.execute("SELECT 1 FROM episodes WHERE source = ? AND content_hash = ? LIMIT 1",
                        (CAPTURED_SOURCE, digest)).fetchone() is not None


def _capture_digests_in(conn) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT content_hash FROM episodes WHERE source = ? AND content_hash IS NOT NULL", (CAPTURED_SOURCE,))}


def capture_digests(source_storage) -> frozenset[str] | None:
    """The digest of every capture's text (`content_hash` where source is 'auto'), in the store and in its cold
    storage, each read once and read-only, for a caller judging many rows at once, as the `shares` tool does. Cold
    storage is never created. None when cold storage exists but cannot be read."""
    cold = _read_cold(source_storage, _capture_digests_in, set())
    if cold is None:
        return None
    return frozenset(_capture_digests_in(source_storage.conn) | cold)


def copies_capture(source_storage, digests) -> bool | None:
    """Whether any of `digests` is a capture's text digest: True when the store or its cold storage holds such a
    capture, False when neither does, None when the store holds none and cold storage exists but cannot be read. Each
    is read once and read-only, and cold storage is never created. The capture mark (migration 030) uses it to count
    `remember`'s copy of a prompt as a capture."""
    digests = set(digests)
    if not digests:
        return False
    if not digests.isdisjoint(_capture_digests_in(source_storage.conn)):
        return True
    cold = _read_cold(source_storage, _capture_digests_in, set())
    return None if cold is None else not digests.isdisjoint(cold)


_LOOK_UP = object()     # captured_reason looks the text up in the store and its cold storage itself


def _verbatim_capture(source_storage, text: str, captures=_LOOK_UP) -> bool | None:
    """Whether `text` is a capture's text word for word, in the store or in its cold storage (read-only), or in
    `captures` when one is given. None when that cannot be told: the store holds none and its cold storage exists but
    cannot be read, or `captures` is None (capture_digests could not read cold storage)."""
    digest = content_digest(text)["value"]
    if captures is not _LOOK_UP:
        return None if captures is None else digest in captures
    if _holds_capture(source_storage.conn, digest):
        return True
    return _cold_holds_capture(source_storage, digest)


def captured_reason(source_storage, layer: str, row: dict, *, captures=_LOOK_UP) -> str | None:
    """Why `row` must not be shared because it is, or may be built from, a captured prompt; None when it may be.
    `captures`, from `capture_digests`, answers the word-for-word rule from digests read once; without it each call
    reads the store and its cold storage.

    An episode is refused when its source is 'auto', and when its text is a capture's text word for word, in the
    store or in its cold storage (`remember` strips a prompt as the nudge does, so a copy has the capture's digest).

    A semantic's links can't say what it was built from: compression links only the cluster's episodes similar to the
    summary, and moving an episode to cold storage deletes its links (ON DELETE CASCADE). So each writer stamps
    `touched_capture` (migration 030) when the semantic is made, reinforced or linked, in a column no cascade touches:
    1 when a capture, or a copy of a capture's text, was in its cluster or among its sources, or the semantic it
    restates was marked 1; NULL when that semantic's mark is unknown, or cold storage could not be read; 0
    otherwise. It never goes down, and 030's trigger raises it for every link to a capture, whatever code writes the
    link. A semantic is refused when:
    - `auto_generated` is not 0, NULL included: automatic compression wrote it from its episodes' own text;
    - a link names an episode that is gone (the nudge hard-deletes weak captures without foreign keys, so the link
      stays);
    - a linked episode is a capture;
    - its text is a capture's text word for word, in the store or in its cold storage;
    - `touched_capture` is NULL: it was made before migration 030, or by a path that doesn't record the mark;
    - `touched_capture` is 1: a capture was in its cluster or among its sources, or reinforced or linked it.
    A semantic stamped 0 whose source episodes have since moved to cold storage is known clean, and shares.
    When cold storage exists but cannot be read, an episode or semantic that passes every other rule is refused."""
    remedy = "remember what you mean to share, in your own words, and share that"
    if layer == "episode":
        eid = row.get("id")
        if (row.get("source") or "") == CAPTURED_SOURCE:
            return (f"episode {eid} is a captured prompt (source 'auto'): what a person typed, never shared; "
                    f"{remedy}")
        verbatim = _verbatim_capture(source_storage, row.get("content", ""), captures)
        if verbatim is None:
            return (f"episode {eid}: its store's cold storage cannot be read, so whether its text is a captured "
                    f"prompt's cannot be told; {remedy}")
        if verbatim:
            return f"episode {eid} holds a captured prompt's text word for word; {remedy}"
        return None
    if layer != "semantic":
        return None
    sid = row.get("id")
    if row.get("auto_generated") != 0:
        return (f"semantic {sid} was written by automatic compression from its episodes' own text, which may be "
                f"captured prompts; share the episodes you chose, or {remedy}")
    ids = list(row.get("source_episode_ids") or [])
    found = {}
    if ids:
        placeholders = ", ".join("?" * len(ids))
        found = {r[0]: r[1] for r in source_storage.conn.execute(
            f"SELECT id, source FROM episodes WHERE id IN ({placeholders})", ids)}
    for eid in ids:
        if eid not in found:
            return (f"semantic {sid}: its source episode {eid} is gone, so whether it was a captured prompt cannot "
                    f"be told; {remedy}")
        if (found[eid] or "") == CAPTURED_SOURCE:
            return f"semantic {sid} is built from captured prompt {eid} (source 'auto'); {remedy}"
    # Before the mark: unreadable cold storage also leaves the mark of a semantic made meanwhile NULL, and these words
    # name that cause.
    verbatim = _verbatim_capture(source_storage, row.get("content", ""), captures)
    if verbatim is None:
        return (f"semantic {sid}: its store's cold storage cannot be read, so whether its text is a captured "
                f"prompt's cannot be told; {remedy}")
    if verbatim:
        return f"semantic {sid} is a captured prompt's text word for word; {remedy}"
    mark = row.get("touched_capture")
    if mark is None:
        return (f"semantic {sid} was made before Engram recorded whether a captured prompt went into it, or by a path "
                f"that doesn't record it, so that cannot be told; {remedy}")
    if mark != 0:
        return f"semantic {sid} was built from or reinforced by a captured prompt; {remedy}"
    return None


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
    if store_identity.is_imprint(source_storage.conn):
        raise store_identity.ImprintRefused("the source is an imprint; imprints are never shared from")
    audience = validate_audience(audience)
    if layer not in SHAREABLE_LAYERS:
        raise ValueError(f"layer {layer!r} is not shareable")
    getter = source_storage.get_episode if layer == "episode" else source_storage.get_semantic
    row = getter(source_id)
    if row is None:
        raise ValueError(f"no {layer} {source_id!r} in the source instance")
    refused = captured_reason(source_storage, layer, row)
    if refused is not None:
        raise CapturedRefused(refused)

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
    return SweepReport(relinked, removed, would_remove, _settle_lane_notes(ledger, now))


def _settle_lane_notes(ledger, now: int) -> int:
    """A `pending` lane note that nothing settled (the process died between the store's commit and the settling
    note) gets the lane the source store holds now. The store is opened read-only; a store that is not found,
    or a memory it no longer has, stays pending, which only narrows."""
    import sqlite3
    from permission_ledger import houses
    from store_identity import read as read_identity
    pending: dict[str, list[tuple[str, str]]] = {}
    for obj in ledger.pending_lane_notes():
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
