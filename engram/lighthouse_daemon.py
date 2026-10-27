"""Publisher daemon for the Lighthouse local city.

One process hosts the publisher side of every local engram instance listed
in its config. Each store is opened read-only (never migrated or written),
each instance carries its own deny-by-default ConnectionPolicy, and policy
is evaluated before retrieval. Retrieval is restricted to episodes and
semantics explicitly shared to an audience the receiver may see. Decisions
and disclosures are appended to a sidecar SQLite file so the store's bytes
never change. This module never imports ``server.py``.

Usage:
    python -m lighthouse_daemon --config ~/.engram/lighthouse-daemon.toml
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import heapq
import json
import logging
import os
import socketserver
import sqlite3
import struct
import sys
import threading
import tomllib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from lighthouse_client import MAX_CANDIDATES
from lighthouse_policy import Policy, PolicyRequest
from lighthouse_validation import load_owned_policy
from lighthouse_protocol import (
    FrameError,
    content_digest,
    decode,
    encode,
    error_frame,
    read_result_frame,
    recall_result_frame,
    validate_frame,
)
from permission_ledger import LedgerUnreadable
from permissions import CACHE_BYTES, CACHE_ENTRIES, FRAMES_AT_ONCE
from sharing import validate_audience
from storage import Storage, vec0_distance_to_similarity

logger = logging.getLogger("engram.lighthouse_daemon")

# The busy timeout of the daemon's read-only ledger open (R19); a module constant so a test can lower it.
LEDGER_BUSY_MS = 5000
OUTSIDE_HOME = "group:outside-home"

PROFILE = "urn:lighthouse:profile:engram-recall-trace"
DOMAIN = "memory.recall"
CLAIM_TYPE = "application/vnd.engram.recall-rank-claim+json"
PUBLISHED_LAYERS = ("episode", "semantic")
_RETRIEVAL_BATCH_SIZE = 256

_SIDECAR_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS disclosures ("
    "id TEXT PRIMARY KEY, at TEXT NOT NULL, receiver TEXT NOT NULL, "
    "action TEXT NOT NULL, context_id TEXT NOT NULL, purpose TEXT NOT NULL, "
    "effect TEXT NOT NULL, rule_id TEXT, code TEXT, memory_ids TEXT NOT NULL)"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PublisherStore:
    name: str
    db_path: Path
    policy_path: Path
    disclosures_path: Path
    storage: Storage | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def publisher_id(self) -> str:
        return f"urn:engram:{self.name}"

    def open(self) -> bool:
        """Open only the read-only store; authorization is per operation."""
        with self._lock:
            if self.storage is not None:
                return True
            try:
                self.storage = Storage.open_read_only(self.db_path)
                columns = {
                    row[1]
                    for row in self.storage.conn.execute(
                        "PRAGMA table_info(shared_memories)"
                    )
                }
                if not {
                    "memory_id",
                    "layer",
                    "audience",
                    "content_digest",
                }.issubset(columns):
                    raise sqlite3.OperationalError(
                        "shared_memories missing (pre-migration store)"
                    )
            except (FileNotFoundError, sqlite3.Error) as error:
                logger.warning("publisher %s unavailable: %s", self.name, error)
                if self.storage is not None:
                    try:
                        self.storage.close()
                    except Exception:
                        pass
                self.storage = None
                return False
            return True

    def reset(self) -> None:
        with self._lock:
            if self.storage is not None:
                try:
                    self.storage.close()
                except Exception:
                    pass
            self.storage = None

    def store_digest(self) -> dict:
        with self.db_path.open("rb") as handle:
            value = hashlib.file_digest(handle, "sha256").hexdigest()
        return {"algorithm": "sha256", "value": value}

    def record_disclosure(self, event: dict) -> str:
        disclosure_id = str(uuid.uuid4())
        connection = sqlite3.connect(self.disclosures_path)
        try:
            connection.execute(_SIDECAR_SCHEMA)
            connection.execute(
                "INSERT INTO disclosures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    disclosure_id,
                    _now(),
                    event["receiver"],
                    event["action"],
                    event["context_id"],
                    event["purpose"],
                    event["effect"],
                    event.get("rule_id"),
                    event.get("code"),
                    json.dumps(event.get("memory_ids", [])),
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return disclosure_id


def _allowed_audiences(
    policy: Policy, receiver: str, *, mode: str = "off"
) -> frozenset[str]:
    """Read audience grants from the operation's validated policy snapshot.

    ``group:outside-home`` is reserved (P29): it is stripped from whatever the
    policy lists, under every gate and with no ledger, and added back only
    under ``enforce`` for a receiver some rule of the policy names.
    """
    try:
        extensions = policy.artifact.get("extensions")
        if not isinstance(extensions, dict):
            return frozenset()
        mapping = extensions.get("engram:audiences")
        if not isinstance(mapping, dict):
            return frozenset()
        values = mapping.get(receiver)
        if not isinstance(values, list):
            return frozenset()
        allowed = {validate_audience(value) for value in values}
        allowed.discard(OUTSIDE_HOME)
        if mode == "enforce" and any(
            isinstance(rule, dict) and receiver in (rule.get("publishers") or ())
            for rule in policy.rules
        ):
            allowed.add(OUTSIDE_HOME)
        return frozenset(allowed)
    except (TypeError, ValueError):
        return frozenset()


def _shared_audiences(
    store: Storage,
    *,
    memory_id: str,
    layer: str,
    content: str,
) -> frozenset[str]:
    """Return validated audiences for an intact published copy."""
    records = store.conn.execute(
        "SELECT layer, audience, content_digest FROM shared_memories "
        "WHERE memory_id = ?",
        (memory_id,),
    ).fetchall()
    if not records:
        return frozenset()
    digest = content_digest(content)["value"]
    try:
        if any(
            record["layer"] != layer
            or record["layer"] not in PUBLISHED_LAYERS
            or record["content_digest"] != digest
            for record in records
        ):
            return frozenset()
        return frozenset(
            validate_audience(record["audience"]) for record in records
        )
    except (TypeError, ValueError):
        return frozenset()


def _rank_shared_layer(
    store: Storage,
    layer: str,
    vector: list[float],
    k: int,
    allowed_audiences: frozenset[str],
    eligible_ids: frozenset[str] | None = None,
) -> list[tuple[float, str, str, dict, list[str]]]:
    """Rank every intact authorized copy, with bounded queries and working set. With ``eligible_ids`` only those
    memory ids are ranked."""
    packed_vector = struct.pack(f"<{len(vector)}f", *vector)
    best: list[tuple[float, str, str, dict, list[str]]] = []
    after = ""
    while True:
        rows = store.conn.execute(
            f"SELECT id, content, lane FROM {layer}s AS memory "
            "WHERE id > ? AND lane IN ('personal', 'work') AND EXISTS ("
            "SELECT 1 FROM shared_memories AS shared "
            "WHERE shared.memory_id = memory.id AND shared.layer = ?) "
            "ORDER BY id LIMIT ?",
            (after, layer, _RETRIEVAL_BATCH_SIZE),
        ).fetchall()
        if not rows:
            return best
        after = rows[-1]["id"]
        eligible = {}
        for record in rows:
            row = dict(record)
            if eligible_ids is not None and row["id"] not in eligible_ids:
                continue
            audiences = sorted(
                _shared_audiences(
                    store, memory_id=row["id"], layer=layer,
                    content=row["content"],
                ) & allowed_audiences
            )
            if audiences:
                eligible[row["id"]] = (row, audiences)
        if not eligible:
            continue
        placeholders = ",".join("?" for _ in eligible)
        # A scalar distance over authorized IDs avoids global KNN truncation.
        # This also admits every distance tie before the final memory-ID sort.
        hits = store.conn.execute(
            f"SELECT id, vec_distance_L2(embedding, ?) AS distance "
            f"FROM {layer}_vectors WHERE id IN ({placeholders})",
            (packed_vector, *eligible),
        ).fetchall()
        for memory_id, distance in hits:
            row, audiences = eligible[memory_id]
            best.append((
                vec0_distance_to_similarity(distance), layer, memory_id,
                row, audiences,
            ))
        best = heapq.nsmallest(k, best, key=lambda item: (-item[0], item[2]))


def retrieve(
    store: Storage,
    embeddings,
    query: str,
    k: int,
    allowed_audiences: frozenset[str],
    eligible: frozenset[str] | None = None,
) -> list[dict]:
    """Return audience-visible episodes and semantics ranked by similarity. With ``eligible`` (the memory ids the
    permission decisions allow) a copy outside it is refused before ranking, not dropped after it."""
    if not allowed_audiences or eligible == frozenset():
        return []
    vector = embeddings.embed([query], prefix="search_query")[0]
    scored: list[tuple[float, str, str, dict, list[str]]] = []
    for layer in PUBLISHED_LAYERS:
        try:
            scored.extend(_rank_shared_layer(
                store, layer, vector, k, allowed_audiences, eligible,
            ))
        except Exception:
            logger.debug("vector search failed for %s", layer, exc_info=True)
            continue
    scored.sort(key=lambda item: (-item[0], item[2]))
    return [
        {
            "memoryId": memory_id,
            "rank": rank,
            "layer": layer,
            "lane": row["lane"],
            "audiences": audiences,
            "contentDigest": content_digest(row.get("content", "")),
            "similarity": similarity,
        }
        for rank, (similarity, layer, memory_id, row, audiences) in enumerate(
            scored[:k], start=1
        )
    ]


_COPY_EXISTS = (
    "SELECT s.memory_id, s.layer, s.source_instance_id, s.source_id FROM shared_memories AS s WHERE "
    "(s.layer = 'episode' AND EXISTS (SELECT 1 FROM episodes AS e WHERE e.id = s.memory_id "
    "AND e.lane IN ('personal', 'work'))) OR "
    "(s.layer = 'semantic' AND EXISTS (SELECT 1 FROM semantics AS m WHERE m.id = s.memory_id "
    "AND m.lane IN ('personal', 'work')))"
)


def _house_lacks_029(storage: Storage) -> bool:
    """R27: ``shared_memories`` lacks ``source_instance_id`` or ``record_id``, or there is no change counter."""
    columns = {row[1] for row in storage.conn.execute("PRAGMA table_info(shared_memories)")}
    counter = storage.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'shared_memories_changes'"
    ).fetchone()
    return not {"source_instance_id", "record_id"} <= columns or counter is None


def _object_of(layer: str, source_instance_id, source_id) -> str | None:
    """A placement's object, ``mem:<source_instance_id>/<layer>/<source_id>``; None for a row without a source."""
    if not source_instance_id or not source_id:
        return None
    return f"mem:{source_instance_id}/{layer}/{source_id}"


@dataclass(frozen=True)
class _CacheEntry:
    """An eligible set (P 12.2) and what it was built from. It serves a frame while the ledger is the same one at
    the same ``seq``, the house's placements have the same change count and copy, and ``at <= t < horizon``."""
    seq: int
    ledger_id: str
    changes: int
    copy: str
    eligible: object        # permissions.EligibleSet

    def estimate(self) -> int:
        """The bytes this entry holds, by the unit sizes measured for P 15: a decision 169 B, its dict entry 29 B
        and its object key 134 B; each distinct ``cited`` tuple 56 B and 8 B an entry; each memory id 80 B and
        26 B of its frozenset's slots. Worked out once."""
        est = self.__dict__.get("_est")
        if est is None:
            decisions = self.eligible.decisions
            tuples = {id(d.cited): len(d.cited) for d in decisions.values()}
            est = (len(decisions) * (169 + 29 + 134) + sum(56 + 8 * n for n in tuples.values())
                   + len(self.eligible.memory_ids) * (80 + 26))
            object.__setattr__(self, "_est", est)
        return est

    def serves(self, seq: int, ledger_id: str, changes: int, copy: str, t: int) -> bool:
        return ((self.seq, self.ledger_id, self.changes, self.copy) == (seq, ledger_id, changes, copy)
                and self.eligible.at <= t and (self.eligible.horizon is None or t < self.eligible.horizon))


@dataclass
class _Placed:
    """What the permission decisions say of every placed copy of a house, for one recall."""
    eligible: frozenset
    objects: dict          # memory id -> its distinct objects (None for a row without a source)
    decisions: dict        # object -> Decision (None when the object could not be decided)
    filtered: int


class _LedgerSide:
    """One frame's permission decisions and receipts (P 12.2). Built per frame from the ledger read-only. The
    ledger decisions of a house's placements are the daemon's cached eligible set; the legacy layers are met with
    them afresh at every frame and never cached (P 6.3 item 4)."""

    def __init__(self, daemon: "PublisherDaemon", publisher: "PublisherStore", frame: dict, mode: str,
                 frame_decision, state, ledger_id: str, now: datetime, release=None):
        from permission_uses import Uses  # noqa: F401  (opened lazily by ``_uses``)
        from permissions import LegacyLayer, acts_for_place, agent_place_at
        self._release = release
        self.daemon, self.publisher, self.frame, self.mode = daemon, publisher, frame, mode
        self.state, self.ledger_id, self.now = state, ledger_id, now
        self.t = int(now.timestamp())
        self.agent = f"agent:{frame['receiver']}"
        self.place = agent_place_at(state, self.agent, self.t) or ""
        row = state.agents.get(self.agent)
        self.acting_for = "" if row is None else row.acts_for
        identity = publisher.storage.instance_identity().get("instance_id") or publisher.name
        self.copy = f"store:{identity}"
        self.shadow = mode == "shadow"
        self._uses = None
        self._receiver = self._load_receiver_policy()
        self._receiver_verdicts: dict[str, bool] = {}
        self.legacy = (
            LegacyLayer("publisher", lambda use, action: frame_decision.effect == "allow"),
            LegacyLayer("receiver", self._receiver_allows),
        )

    # ------------------------------------------------------------ the receiver's legacy layer (P 6.3 item 4)
    def _load_receiver_policy(self):
        """The receiver's own policy, read the way the receiver finds it (``neighbors.py:183-184``), at every
        frame. None when it has no settings file, is disabled or fails to load: its layer then refuses."""
        from lighthouse_receiver_config import load_receiver_policy, load_settings
        receiver = self.frame["receiver"]
        try:
            settings = load_settings(
                self.daemon.engram_home / ".engram" / "instances" / receiver / "lighthouse-receiver.toml")
            if settings is None:
                return None
            return load_receiver_policy(settings["policy_path"], receiver)
        except Exception as error:
            logger.warning("receiver %s policy unavailable: %s", receiver, error)
            return None

    def _receiver_allows(self, use, action: str) -> bool:
        if self._receiver is None:
            return False
        if action not in self._receiver_verdicts:
            self._receiver_verdicts[action] = self._receiver.decide(PolicyRequest(
                publisher=f"urn:engram:{self.frame['publisher']}", profile=PROFILE, domain=DOMAIN, action=action,
                context_id=self.frame["context"]["id"], claim_type=CLAIM_TYPE, purpose=self.frame["purpose"],
                audience="self", at=self.now)).effect == "allow"
        return self._receiver_verdicts[action]

    # ------------------------------------------------------------ deciding
    def _use(self, obj: str, action: str):
        from permissions import Use
        return Use(requester=self.agent, place=self.place, obj=obj, copy=self.copy, action=action,
                   purpose=self.frame["purpose"], at=self.t)

    def decide(self, obj: str, action: str):
        from permissions import RuleError, decide
        try:
            return decide(self.state, self._use(obj, action), legacy=self.legacy)
        except RuleError:
            logger.warning("permission: %s is not a decidable object in %s", obj, self.publisher.name)
            return None

    def recall_set(self) -> _Placed:
        """Decide ``recall`` for each placed copy that has a copy to rank, before ranking (P 12.2): the cached
        ledger decision of its object, met with this frame's legacy verdicts."""
        from permissions import meet_legacy
        objects: dict[str, set] = {}
        for row in self.publisher.storage.conn.execute(_COPY_EXISTS):
            objects.setdefault(row["memory_id"], set()).add(
                _object_of(row["layer"], row["source_instance_id"], row["source_id"]))
        ledger = self.daemon._eligible(self).decisions
        decisions: dict = {}
        eligible = set()
        for memory_id, objs in objects.items():
            allowed = True
            for obj in objs:
                if obj is None:
                    allowed = False
                    continue
                if obj not in decisions:
                    base = ledger.get(obj)
                    decisions[obj] = None if base is None else meet_legacy(base, self._use(obj, "recall"), self.legacy)
                if decisions[obj] is None or not decisions[obj].allowed:
                    allowed = False
            if allowed:
                eligible.add(memory_id)
        return _Placed(frozenset(eligible), objects, decisions, len(objects) - len(eligible))

    # ------------------------------------------------------------ receipts
    def _append(self, row, subjects) -> str | None:
        """Write one receipt; None (after a warning) when it cannot be written."""
        from permission_uses import Uses
        try:
            if self._uses is None:
                self._uses = Uses.open(self.daemon.engram_home)
            return self._uses.append(row, subjects)
        except Exception as error:
            logger.warning("permission receipt not written for %s: %s", self.publisher.name, error)
            return None

    def close(self) -> None:
        """Close the receipts, drop the State and give the frame's turn back (once)."""
        if self._uses is not None:
            try:
                self._uses.close()
            except Exception:
                pass
            self._uses = None
        self.state = None
        release, self._release = self._release, None
        if release is not None:
            release()

    def receipt_recall(self, candidates: list[dict], placed: _Placed) -> bool:
        """One receipt for a recall: the object refs it returned and how many copies were filtered. False when it
        could not be written."""
        from dataclasses import replace
        from permission_uses import row_for_recall
        from permissions import subjects_of
        returned = sorted({obj for c in candidates for obj in placed.objects.get(c["memoryId"], ()) if obj})
        decisions = [placed.decisions[o] for o in returned if placed.decisions.get(o) is not None]
        row = replace(row_for_recall(decisions, self._use("", "recall"), acting_for=self.acting_for,
                                     returned=returned, filtered=placed.filtered, shadow=self.shadow,
                                     ledger_id=self.ledger_id), ledger_seq=self.state.seq)
        subjects = [(s, o) for o in returned for s in subjects_of(self.state, o, self.t)]
        return self._append(row, subjects) is not None

    def read_item(self, memory_id: str, content: str | None) -> tuple[bool, dict | None]:
        """Decide one read item as ``inject_context`` and write its receipt. ``content`` is what the legacy path
        would deliver (None if it refuses). Returns (deliver, permission): under ``enforce`` an item is delivered
        only when both paths allow it and its receipt is written; under ``shadow`` the legacy path decides."""
        from dataclasses import replace
        from permission_uses import row_for_decision
        from permissions import Refusal, annotation, subjects_of
        legacy_delivers = content is not None
        objs = sorted({o for o in (_object_of(r["layer"], r["source_instance_id"], r["source_id"])
                                   for r in self.publisher.storage.conn.execute(
                                       "SELECT layer, source_instance_id, source_id FROM shared_memories "
                                       "WHERE memory_id = ?", (memory_id,))) if o})
        decided = [(o, self.decide(o, "inject_context")) for o in objs]
        if not decided or any(d is None for _, d in decided):
            return (legacy_delivers and self.shadow), None        # no object to name: no receipt
        obj, decision = next(((o, d) for o, d in decided if not d.allowed), decided[0])
        if not legacy_delivers and (self.shadow or decision.allowed):
            # The audience check is the publisher's policy refusing. Under shadow it is recorded on the receipt
            # whether or not the ledger also refuses, so `report shadow` reads it instead of inferring it (P 12.3);
            # an allowing ledger keeps its verdict and only notes the refusal. Under enforce the receipt must not
            # say "allowed" for an item not delivered; a ledger refusal there stays the receipt's refusal.
            legacy_refusal = Refusal("LEGACY_DENY", "publisher", "inject_context")
            decision = replace(decision, refusal=legacy_refusal) if self.shadow else replace(
                decision, allowed=False, refusal=legacy_refusal)
        from lighthouse_protocol import content_digest as _digest
        row = row_for_decision(
            decision, self._use(obj, "inject_context"), acting_for=self.acting_for,
            content_digest=_digest(content)["value"] if legacy_delivers and (decision.allowed or self.shadow) else None,
            shadow=self.shadow, ledger_id=self.ledger_id)
        receipt = self._append(row, [(s, obj) for s in subjects_of(self.state, obj, self.t)])
        if self.shadow:
            deliver = legacy_delivers
        else:
            deliver = legacy_delivers and decision.allowed and receipt is not None
        if not (deliver and decision.allowed and receipt is not None):
            return deliver, None
        return deliver, annotation(self.state, decision, laid_by=self._laid_by(obj), receipt_id=receipt)

    def _laid_by(self, obj: str) -> str:
        """``<owner handle> (<store name>)`` from the source store's ``stores`` row."""
        from permissions import parse_object_ref
        iid = parse_object_ref(obj).instance_id
        store = self.state.stores.get(iid)
        if store is None:
            return f"unknown ({iid})"
        return f"{store.owner.removeprefix('person:')} ({store.name})"


class PublisherDaemon:
    def __init__(
        self,
        publishers: dict[str, PublisherStore],
        socket_path: Path,
        embeddings,
        *, clock=None,
        engram_home: Path | None = None,
    ):
        self.publishers = publishers
        self.socket_path = Path(socket_path)
        self.embeddings = embeddings
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.engram_home = Path(engram_home) if engram_home is not None else None
        self._server: socketserver.ThreadingUnixStreamServer | None = None
        self._ready = threading.Event()
        # The eligible-set cache (P 12.2, R31): (house, agent, place, purpose, action) -> _CacheEntry, least
        # recently served first, at most CACHE_ENTRIES over all houses. ``rebuilds`` counts the sets built.
        self._cache: collections.OrderedDict = collections.OrderedDict()
        self._cache_lock = threading.Lock()
        self.rebuilds = 0
        # At most FRAMES_AT_ONCE frames build or hold a State at once; a frame waits for its turn (P 12.2, 15).
        self._frames = threading.BoundedSemaphore(FRAMES_AT_ONCE)

    def _eligible(self, side: "_LedgerSide"):
        """This frame's eligible set of ``recall`` decisions for the house, from the cache while it is valid,
        otherwise built from every placement the house holds and kept. The house is its ``db_path``: an entry is
        read against that house's own change count and no other's."""
        from permissions import Placement, eligible_set
        publisher, action = side.publisher, "recall"
        key = (publisher.db_path, side.agent, side.place, side.frame["purpose"], action)
        changes = publisher.storage.placement_changes()      # read before the rows: a later change only shows stale
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is not None and entry.serves(side.state.seq, side.ledger_id, changes, side.copy, side.t):
                self._cache.move_to_end(key)
                return entry.eligible
        placements = [
            Placement(row["memory_id"], _object_of(row["layer"], row["source_instance_id"], row["source_id"]),
                      side.copy)
            for row in publisher.storage.conn.execute(
                "SELECT memory_id, layer, source_instance_id, source_id FROM shared_memories")]
        got = eligible_set(side.state, placements, requester=side.agent, place=side.place,
                           purpose=side.frame["purpose"], action=action, at=side.t)
        for obj in sorted({p.obj for p in placements if p.obj and p.obj not in got.decisions}):
            logger.warning("permission: %s is not a decidable object in %s", obj, publisher.name)
        entry = _CacheEntry(side.state.seq, side.ledger_id, changes, side.copy, got)
        with self._cache_lock:
            self.rebuilds += 1
            self._cache.pop(key, None)
            if entry.estimate() <= CACHE_BYTES:          # an entry over the bound alone serves this frame only
                self._cache[key] = entry
                total = sum(e.estimate() for e in self._cache.values())
                while len(self._cache) > CACHE_ENTRIES or total > CACHE_BYTES:
                    _, dropped = self._cache.popitem(last=False)
                    total -= dropped.estimate()
        return got

    def _request(self, frame: dict, action: str) -> PolicyRequest:
        # A receiver's recorded request time cannot extend a publisher grant.
        at = self.clock()
        return PolicyRequest(
            publisher=f"urn:engram:{frame['receiver']}",
            profile=PROFILE,
            domain=DOMAIN,
            action=action,
            context_id=frame["context"]["id"],
            claim_type=CLAIM_TYPE,
            purpose=frame["purpose"],
            audience=frame.get("audience", "self"),
            at=at if at.tzinfo else at.replace(tzinfo=timezone.utc),
        )

    def _gate(self):
        """The effective gate over every house this daemon serves (P 12.3), read afresh at every frame. A served
        path with no file is left out by ``effective_gate`` (R32). With no engram home there is no ledger to read."""
        from permission_ledger import Gate, effective_gate

        if self.engram_home is None:
            return Gate("off", None)
        served = [self.publishers[name].db_path for name in sorted(self.publishers)]
        return effective_gate(self.engram_home, served, busy_ms=LEDGER_BUSY_MS)

    def handle_frame(self, frame: dict) -> dict:
        try:
            validate_frame(frame)
            if frame["kind"] not in ("recall", "read"):
                return error_frame(
                    "MALFORMED_FRAME", f"unexpected kind {frame['kind']}"
                )
            publisher = self.publishers.get(frame.get("publisher"))
            if publisher is None or not publisher.db_path.is_file():
                if publisher is not None:
                    publisher.reset()
                return error_frame(
                    "PUBLISHER_UNAVAILABLE",
                    "no such publisher or store unavailable",
                )
            gate = self._gate()
            # Never retain action permissions between requests or reread the
            # artifact for audiences: concurrent edits must not combine grants
            # from different policy snapshots.
            try:
                policy = load_owned_policy(publisher.policy_path, publisher.name)
            except (OSError, ValueError, KeyError, TypeError) as error:
                logger.warning(
                    "publisher %s policy unavailable: %s", publisher.name, error
                )
                return error_frame("PUBLISHER_UNAVAILABLE", "policy unavailable")
            if not publisher.open():
                return error_frame("PUBLISHER_UNAVAILABLE", "store unavailable")
            if frame["kind"] == "recall":
                return self._recall(publisher, frame, policy, gate)
            if frame["kind"] == "read":
                return self._read(publisher, frame, policy, gate)
        except FrameError as error:
            return error_frame(error.code, "")
        except Exception:
            logger.warning("frame handling failed", exc_info=True)
            return error_frame("PUBLISHER_UNAVAILABLE", "internal failure")

    def _ledger_side(self, publisher: PublisherStore, frame: dict, gate, frame_decision):
        """Under ``shadow`` and ``enforce``, this frame's permission decisions. Returns (side, serve_nothing):
        ``side`` is None when there is nothing to decide with, and ``serve_nothing`` says the frame must answer
        with no candidates and null content (R27, the placement bound, an unreadable ledger under ``enforce``)."""
        if gate.mode not in ("shadow", "enforce"):
            return None, False
        enforce = gate.mode == "enforce"
        if _house_lacks_029(publisher.storage):
            logger.warning(
                "house %s lacks migration 029 (source_instance_id, record_id or the change counter): serving "
                "nothing; an engram server must open it once", publisher.name)
            return None, True
        from permissions import MAX_PLACEMENTS
        count = publisher.storage.conn.execute("SELECT COUNT(*) FROM shared_memories").fetchone()[0]
        if count > MAX_PLACEMENTS:
            logger.warning(
                "house %s holds %d placements, more than %s: %s", publisher.name, count, f"{MAX_PLACEMENTS:,}",
                "serving nothing" if enforce else "deciding by the legacy path alone")
            return None, enforce
        from permission_ledger import Ledger
        self._frames.acquire()          # held until the side closes: a frame waits, it is never refused
        try:
            ledger = Ledger.open_read_only(self.engram_home, LEDGER_BUSY_MS)
            try:
                state, ledger_id = ledger.state(), ledger.meta()["ledger_id"]
            finally:
                ledger.close()
            now = self.clock()
            return _LedgerSide(self, publisher, frame, gate.mode, frame_decision, state, ledger_id,
                               now if now.tzinfo else now.replace(tzinfo=timezone.utc),
                               release=self._frames.release), False
        except Exception as error:
            self._frames.release()
            logger.warning("permission ledger unreadable while serving %s: %s", publisher.name, error)
            return None, enforce

    @staticmethod
    def _closed(gate, publisher: PublisherStore) -> bool:
        """Under a closed gate nothing is served; the cause is logged once per request."""
        if gate.mode != "closed":
            return False
        logger.warning(
            "permissions gate closed, serving nothing from %s: %s",
            publisher.name,
            gate.cause,
        )
        return True

    def _recall(
        self, publisher: PublisherStore, frame: dict, policy: Policy, gate
    ) -> dict:
        decision = policy.decide(self._request(frame, "recall"))
        turn_id = str(uuid.uuid4())
        candidates: list[dict] = []
        closed = self._closed(gate, publisher)
        if decision.effect == "allow" and not closed:
            side, serve_nothing = self._ledger_side(publisher, frame, gate, decision)
            try:
                if not serve_nothing:
                    candidates = self._rank_recall(publisher, frame, policy, gate, side)
            finally:
                if side is not None:
                    side.close()
        disclosure_id = publisher.record_disclosure(
            {
                "receiver": frame["receiver"],
                "action": "recall",
                "context_id": frame["context"]["id"],
                "purpose": frame["purpose"],
                "effect": decision.effect,
                "rule_id": decision.rule_id,
                "code": decision.code,
                "memory_ids": [c["memoryId"] for c in candidates],
            }
        )
        return recall_result_frame(
            turn_id=turn_id,
            query_digest=content_digest(frame["query"]),
            context=frame["context"],
            candidates=[
                {key: value for key, value in candidate.items() if key != "similarity"}
                for candidate in candidates
            ],
            decision=decision.to_json(),
            disclosure_id=disclosure_id,
        )

    def _rank_recall(self, publisher, frame, policy, gate, side) -> list[dict]:
        """Rank the copies the policy and the audiences allow. With a ledger side, ``recall`` is decided for each
        placement first: under ``enforce`` the refused are left out before ranking, under ``shadow`` they are only
        counted. The receipt is written before the reply, so a reply never names a candidate whose receipt failed
        (under ``enforce``, a recall with no receipt returns nothing)."""
        enforce = gate.mode == "enforce"
        placed = None
        try:
            placed = None if side is None else side.recall_set()
        except LedgerUnreadable as error:       # a lazy read failed: the gate's closed answer, or the legacy one
            self._unreadable(publisher, error)
            if enforce:
                return []
            side = None
        candidates = retrieve(
            publisher.storage,
            self.embeddings,
            frame["query"],
            min(int(frame["k"]), MAX_CANDIDATES),
            _allowed_audiences(policy, f"urn:engram:{frame['receiver']}", mode=gate.mode),
            eligible=placed.eligible if placed is not None and enforce else None,
        )
        if side is not None:
            try:
                written = side.receipt_recall(candidates, placed)
            except LedgerUnreadable as error:
                self._unreadable(publisher, error)
                return [] if enforce else candidates
            if not written and enforce:
                return []
        return candidates

    @staticmethod
    def _unreadable(publisher: PublisherStore, error: Exception) -> None:
        logger.warning("permission ledger unreadable while serving %s: %s", publisher.name, error)

    def _read(
        self, publisher: PublisherStore, frame: dict, policy: Policy, gate
    ) -> dict:
        decision = policy.decide(self._request(frame, "read"))
        items = []
        delivered: list[str] = []
        allowed_audiences = frozenset()
        side, serve_nothing = None, False
        closed = self._closed(gate, publisher)
        if decision.effect == "allow" and not closed:
            allowed_audiences = _allowed_audiences(
                policy,
                f"urn:engram:{frame['receiver']}",
                mode=gate.mode,
            )
        if not closed:
            side, serve_nothing = self._ledger_side(publisher, frame, gate, decision)
        try:
            for memory_id in frame["memoryIds"]:
                content, audiences = None, []
                if decision.effect == "allow" and allowed_audiences and not serve_nothing:
                    content, audiences = self._legacy_item(publisher, memory_id, allowed_audiences)
                item_permission = None
                if side is not None and not serve_nothing:
                    try:
                        deliver, item_permission = side.read_item(memory_id, content)
                    except LedgerUnreadable as error:       # enforce serves nothing, shadow the legacy content
                        self._unreadable(publisher, error)
                        deliver, item_permission = gate.mode == "shadow" and content is not None, None
                    if not deliver:
                        content, audiences, item_permission = None, [], None
                if content is not None:
                    delivered.append(memory_id)
                item = {
                    "memoryId": memory_id,
                    "content": content,
                    "audiences": audiences,
                    "decision": decision.to_json(),
                }
                if item_permission is not None:
                    item["permission"] = item_permission
                items.append(item)
        finally:
            if side is not None:
                side.close()
        disclosure_id = publisher.record_disclosure(
            {
                "receiver": frame["receiver"],
                "action": "read",
                "context_id": frame["context"]["id"],
                "purpose": frame["purpose"],
                "effect": decision.effect,
                "rule_id": decision.rule_id,
                "code": decision.code,
                "memory_ids": delivered,
            }
        )
        return read_result_frame(items=items, disclosure_id=disclosure_id)

    @staticmethod
    def _legacy_item(publisher, memory_id, allowed_audiences) -> tuple[str | None, list[str]]:
        """The content and audiences the audience policy lets out for one item, as before the ledger."""
        row = publisher.storage.get_episode(memory_id)
        layer = "episode"
        if row is None:
            row = publisher.storage.get_semantic(memory_id)
            layer = "semantic"
        if row is None or row.get("lane") not in ("personal", "work"):
            return None, []
        audiences = sorted(
            _shared_audiences(
                publisher.storage,
                memory_id=memory_id,
                layer=layer,
                content=row.get("content", ""),
            )
            & allowed_audiences
        )
        if not audiences:
            return None, []
        return row.get("content", ""), audiences

    def serve_forever(self) -> None:
        daemon = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                for line in self.rfile:
                    try:
                        frame = decode(line)
                    except FrameError as error:
                        self.wfile.write(encode(error_frame(error.code, "")))
                        continue
                    self.wfile.write(encode(daemon.handle_frame(frame)))
                    self.wfile.flush()

        if self.socket_path.exists():
            self.socket_path.unlink()
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self._server = socketserver.ThreadingUnixStreamServer(
            str(self.socket_path), Handler
        )
        self._server.daemon_threads = True
        os.chmod(self.socket_path, 0o600)
        self._ready.set()
        try:
            self._server.serve_forever(poll_interval=0.2)
        finally:
            self._ready.clear()

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self.socket_path.exists():
            self.socket_path.unlink()
        for publisher in self.publishers.values():
            publisher.reset()


def load_daemon_config(path: Path) -> dict:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    publishers = raw.get("publishers")
    if not isinstance(publishers, list) or not all(
        isinstance(publisher, str) and publisher for publisher in publishers
    ):
        raise ValueError("config needs a non-empty publishers list")
    return {"publishers": publishers, "socket": raw.get("socket")}


def build_publishers(
    engram_home: Path, names: list[str]
) -> dict[str, PublisherStore]:
    publishers = {}
    for name in names:
        instance = engram_home / ".engram" / "instances" / name
        publishers[name] = PublisherStore(
            name=name,
            db_path=instance / "graph.db",
            policy_path=instance / "lighthouse-policy.json",
            disclosures_path=instance / "lighthouse-disclosures.db",
        )
    return publishers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lighthouse_daemon")
    parser.add_argument("--config", required=True)
    parser.add_argument("--socket")
    args = parser.parse_args(argv)
    engram_home = Path(
        os.environ.get("ENGRAM_HOME", Path(__file__).resolve().parent)
    )
    config = load_daemon_config(Path(args.config))
    socket_path = Path(
        args.socket
        or config["socket"]
        or engram_home / ".engram" / "lighthouse.sock"
    )
    logging.basicConfig(level=os.environ.get("ENGRAM_LOG_LEVEL", "INFO"))
    embedder_socket = os.environ.get("ENGRAM_EMBEDDER_SOCKET")
    if not embedder_socket:
        logger.error(
            "the lighthouse daemon embeds through the shared embedder service: "
            "set ENGRAM_EMBEDDER_SOCKET (scripts/superyak-embedder.service)"
        )
        return 2
    from embeddings import RemoteEmbedProvider

    daemon = PublisherDaemon(
        build_publishers(engram_home, config["publishers"]),
        socket_path,
        RemoteEmbedProvider(embedder_socket),
        engram_home=engram_home,
    )
    logger.info("publishing %s on %s", ", ".join(config["publishers"]), socket_path)
    try:
        daemon.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
