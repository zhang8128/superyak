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
from sharing import validate_audience
from storage import Storage, vec0_distance_to_similarity

logger = logging.getLogger("engram.lighthouse_daemon")

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
        return {
            "algorithm": "sha256",
            "value": hashlib.sha256(self.db_path.read_bytes()).hexdigest(),
        }

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


def _allowed_audiences(policy: Policy, receiver: str) -> frozenset[str]:
    """Read audience grants from the operation's validated policy snapshot."""
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
        return frozenset(validate_audience(value) for value in values)
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
) -> list[tuple[float, str, str, dict, list[str]]]:
    """Rank every intact authorized copy, with bounded queries and working set."""
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
) -> list[dict]:
    """Return audience-visible episodes and semantics ranked by similarity."""
    if not allowed_audiences:
        return []
    vector = embeddings.embed([query], prefix="search_query")[0]
    scored: list[tuple[float, str, str, dict, list[str]]] = []
    for layer in PUBLISHED_LAYERS:
        try:
            scored.extend(_rank_shared_layer(
                store, layer, vector, k, allowed_audiences,
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


class PublisherDaemon:
    def __init__(
        self,
        publishers: dict[str, PublisherStore],
        socket_path: Path,
        embeddings,
        *, clock=None,
    ):
        self.publishers = publishers
        self.socket_path = Path(socket_path)
        self.embeddings = embeddings
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._server: socketserver.ThreadingUnixStreamServer | None = None
        self._ready = threading.Event()

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
                return self._recall(publisher, frame, policy)
            if frame["kind"] == "read":
                return self._read(publisher, frame, policy)
        except FrameError as error:
            return error_frame(error.code, "")
        except Exception:
            logger.warning("frame handling failed", exc_info=True)
            return error_frame("PUBLISHER_UNAVAILABLE", "internal failure")

    def _recall(self, publisher: PublisherStore, frame: dict, policy: Policy) -> dict:
        decision = policy.decide(self._request(frame, "recall"))
        turn_id = str(uuid.uuid4())
        candidates: list[dict] = []
        if decision.effect == "allow":
            allowed_audiences = _allowed_audiences(
                policy,
                f"urn:engram:{frame['receiver']}",
            )
            candidates = retrieve(
                publisher.storage,
                self.embeddings,
                frame["query"],
                int(frame["k"]),
                allowed_audiences,
            )
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

    def _read(self, publisher: PublisherStore, frame: dict, policy: Policy) -> dict:
        decision = policy.decide(self._request(frame, "read"))
        items = []
        delivered: list[str] = []
        allowed_audiences = frozenset()
        if decision.effect == "allow":
            allowed_audiences = _allowed_audiences(
                policy,
                f"urn:engram:{frame['receiver']}",
            )
        for memory_id in frame["memoryIds"]:
            content = None
            audiences: list[str] = []
            if decision.effect == "allow" and allowed_audiences:
                row = publisher.storage.get_episode(memory_id)
                layer = "episode"
                if row is None:
                    row = publisher.storage.get_semantic(memory_id)
                    layer = "semantic"
                if row is not None and row.get("lane") in ("personal", "work"):
                    audiences = sorted(
                        _shared_audiences(
                            publisher.storage,
                            memory_id=memory_id,
                            layer=layer,
                            content=row.get("content", ""),
                        )
                        & allowed_audiences
                    )
                    if audiences:
                        content = row.get("content", "")
                        delivered.append(memory_id)
            items.append(
                {
                    "memoryId": memory_id,
                    "content": content,
                    "audiences": audiences,
                    "decision": decision.to_json(),
                }
            )
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
    from embeddings import create_embedding_provider

    daemon = PublisherDaemon(
        build_publishers(engram_home, config["publishers"]),
        socket_path,
        create_embedding_provider(),
    )
    logging.basicConfig(level=os.environ.get("ENGRAM_LOG_LEVEL", "INFO"))
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
