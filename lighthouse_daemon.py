"""Publisher daemon for the Lighthouse local city.

One process hosts the publisher side of every local engram instance listed
in its config. Each store is opened read-only (never migrated or written),
each instance carries its own deny-by-default ConnectionPolicy, and policy
is evaluated before retrieval. Retrieval is restricted to work-lane
episodes and semantics. Decisions and disclosures are appended to a sidecar
SQLite file so the store's bytes never change. This module never imports
``server.py``.

Usage:
    python -m lighthouse_daemon --config ~/.engram/lighthouse-daemon.toml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import socketserver
import sqlite3
import sys
import threading
import tomllib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from lighthouse_policy import Policy, PolicyError, PolicyRequest, load_policy
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
from storage import Storage, vec0_distance_to_similarity

logger = logging.getLogger("engram.lighthouse_daemon")

PROFILE = "urn:lighthouse:profile:engram-recall-trace"
DOMAIN = "memory.recall"
CLAIM_TYPE = "application/vnd.engram.recall-rank-claim+json"
PUBLISHED_LAYERS = ("episode", "semantic")

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
    policy: Policy | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def publisher_id(self) -> str:
        return f"urn:engram:{self.name}"

    def open(self) -> bool:
        with self._lock:
            if self.storage is not None and self.policy is not None:
                return True
            try:
                self.policy = load_policy(self.policy_path)
                self.storage = Storage.open_read_only(self.db_path)
                columns = {
                    row[1]
                    for row in self.storage.conn.execute(
                        "PRAGMA table_info(episodes)"
                    )
                }
                if "lane" not in columns:
                    raise sqlite3.OperationalError(
                        "episodes.lane missing (pre-migration store)"
                    )
            except (PolicyError, FileNotFoundError, sqlite3.Error) as error:
                logger.warning("publisher %s unavailable: %s", self.name, error)
                if self.storage is not None:
                    try:
                        self.storage.close()
                    except Exception:
                        pass
                self.storage = None
                self.policy = None
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
            self.policy = None

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


def retrieve(store: Storage, embeddings, query: str, k: int) -> list[dict]:
    """Return work-lane episodes and semantics ranked by similarity."""
    vector = embeddings.embed([query], prefix="search_query")[0]
    scored: list[tuple[float, str, str, dict]] = []
    for layer in PUBLISHED_LAYERS:
        try:
            hits = store.search_vectors(layer, vector, k=max(k * 4, 8))
        except Exception:
            logger.debug("vector search failed for %s", layer, exc_info=True)
            continue
        for memory_id, distance in hits:
            row = (
                store.get_episode(memory_id)
                if layer == "episode"
                else store.get_semantic(memory_id)
            )
            if row is None or (row.get("lane") or "personal") != "work":
                continue
            scored.append(
                (
                    vec0_distance_to_similarity(distance),
                    layer,
                    memory_id,
                    row,
                )
            )
    scored.sort(key=lambda item: (-item[0], item[2]))
    return [
        {
            "memoryId": memory_id,
            "rank": rank,
            "layer": layer,
            "lane": "work",
            "contentDigest": content_digest(row.get("content", "")),
            "similarity": similarity,
        }
        for rank, (similarity, layer, memory_id, row) in enumerate(
            scored[:k], start=1
        )
    ]


class PublisherDaemon:
    def __init__(
        self,
        publishers: dict[str, PublisherStore],
        socket_path: Path,
        embeddings,
    ):
        self.publishers = publishers
        self.socket_path = Path(socket_path)
        self.embeddings = embeddings
        self._server: socketserver.ThreadingUnixStreamServer | None = None
        self._ready = threading.Event()

    def _request(self, frame: dict, action: str) -> PolicyRequest:
        at = datetime.fromisoformat(
            str(frame.get("at", _now())).replace("Z", "+00:00")
        )
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
            if (
                publisher is None
                or not publisher.db_path.is_file()
                or not publisher.open()
            ):
                if publisher is not None:
                    publisher.reset()
                return error_frame(
                    "PUBLISHER_UNAVAILABLE",
                    "no such publisher or store unavailable",
                )
            if frame["kind"] == "recall":
                return self._recall(publisher, frame)
            if frame["kind"] == "read":
                return self._read(publisher, frame)
        except FrameError as error:
            return error_frame(error.code, "")
        except KeyError as error:
            return error_frame("MALFORMED_FRAME", f"missing {error}")
        except Exception:
            logger.warning("frame handling failed", exc_info=True)
            return error_frame("PUBLISHER_UNAVAILABLE", "internal failure")

    def _recall(self, publisher: PublisherStore, frame: dict) -> dict:
        decision = publisher.policy.decide(self._request(frame, "recall"))
        turn_id = str(uuid.uuid4())
        candidates: list[dict] = []
        if decision.effect == "allow":
            candidates = retrieve(
                publisher.storage,
                self.embeddings,
                frame["query"],
                int(frame["k"]),
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

    def _read(self, publisher: PublisherStore, frame: dict) -> dict:
        decision = publisher.policy.decide(self._request(frame, "read"))
        items = []
        delivered: list[str] = []
        for memory_id in frame["memoryIds"]:
            content = None
            if decision.effect == "allow":
                row = publisher.storage.get_episode(memory_id)
                if row is None:
                    row = publisher.storage.get_semantic(memory_id)
                if row is not None and (row.get("lane") or "personal") == "work":
                    content = row.get("content", "")
                    delivered.append(memory_id)
            items.append(
                {
                    "memoryId": memory_id,
                    "content": content,
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
    from embeddings import NomicEmbedProvider

    daemon = PublisherDaemon(
        build_publishers(engram_home, config["publishers"]),
        socket_path,
        NomicEmbedProvider(),
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
