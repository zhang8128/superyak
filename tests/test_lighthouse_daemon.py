from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from lighthouse_daemon import PublisherDaemon, PublisherStore, retrieve
from lighthouse_protocol import (
    artifact_digest,
    decode,
    encode,
    read_frame,
    recall_frame,
)
from storage import Storage


class FakeEmbeddings:
    def embed(self, texts, prefix=None):
        out = []
        for text in texts:
            vec = [0.0] * 768
            vec[sum(map(ord, text)) % 768] = 1.0
            out.append(vec)
        return out


def unit(text: str) -> list[float]:
    return FakeEmbeddings().embed([text])[0]


def write_policy(
    path: Path,
    *,
    receiver: str = "engram",
    actions=("recall", "read"),
) -> None:
    artifact = {
        "kind": "ConnectionPolicy",
        "protocolVersion": "0.1",
        "id": "urn:policy:why",
        "issuedAt": "2026-09-01T00:00:00Z",
        "issuer": "urn:engram:why",
        "payloadMediaType": "application/vnd.lighthouse.connection-policy+json",
        "payload": {
            "rules": [
                {
                    "id": "allow-engram-technical",
                    "effect": "allow",
                    "publishers": [f"urn:engram:{receiver}"],
                    "profiles": [
                        "urn:lighthouse:profile:engram-recall-trace"
                    ],
                    "domains": ["memory.recall"],
                    "actions": list(actions),
                    "contexts": ["memory/technical"],
                    "claimMediaTypes": [
                        "application/vnd.engram.recall-rank-claim+json"
                    ],
                    "purposes": ["session-recall"],
                    "audiences": ["self"],
                    "validFrom": "2026-01-01T00:00:00Z",
                    "validUntil": "2027-01-01T00:00:00Z",
                    "requiredEvidence": [],
                    "requiredAttestations": [],
                }
            ]
        },
    }
    artifact["digest"] = artifact_digest(artifact)
    path.write_text(json.dumps(artifact))


def build_publisher(root: Path, name: str = "why") -> PublisherStore:
    inst = root / ".engram" / "instances" / name
    inst.mkdir(parents=True)
    store = Storage(str(inst / "graph.db"))
    store.add_episode(
        str(uuid.uuid4()),
        "s",
        "work: rivers need bridges",
        embedding=unit("work: rivers need bridges"),
        lane="work",
    )
    store.add_episode(
        str(uuid.uuid4()),
        "s",
        "personal: rivers at dusk",
        embedding=unit("rivers"),
        lane="personal",
    )
    store.close()
    write_policy(inst / "lighthouse-policy.json")
    return PublisherStore(
        name=name,
        db_path=inst / "graph.db",
        policy_path=inst / "lighthouse-policy.json",
        disclosures_path=inst / "lighthouse-disclosures.db",
    )


CONTEXT = {"id": "memory/technical", "path": ["memory", "technical"]}
NOW = datetime(2026, 9, 1, tzinfo=timezone.utc).isoformat()


def _valid_recall():
    return recall_frame(
        receiver="engram",
        publisher="why",
        context=CONTEXT,
        purpose="session-recall",
        query="rivers",
        k=1,
        at=NOW,
    )


def _valid_read():
    return read_frame(
        receiver="engram",
        publisher="why",
        context=CONTEXT,
        purpose="session-recall",
        turn_id="turn-1",
        memory_ids=["m1"],
    )


def test_retrieve_returns_work_lane_only(tmp_path):
    pub = build_publisher(tmp_path)
    assert pub.open() is True
    hits = retrieve(pub.storage, FakeEmbeddings(), "rivers", k=5)
    assert hits
    assert all(hit["lane"] == "work" for hit in hits)
    assert all(hit["layer"] in ("episode", "semantic") for hit in hits)
    assert hits[0]["rank"] == 1
    assert hits[0]["contentDigest"]["algorithm"] == "sha256"


def test_handle_recall_denies_before_retrieval(tmp_path):
    pub = build_publisher(tmp_path)
    daemon = PublisherDaemon(
        {"why": pub}, tmp_path / "s.sock", FakeEmbeddings()
    )
    frame = recall_frame(
        receiver="stranger",
        publisher="why",
        context=CONTEXT,
        purpose="session-recall",
        query="rivers",
        k=5,
        at=NOW,
    )
    out = daemon.handle_frame(frame)
    assert out["kind"] == "recall_result"
    assert out["candidates"] == []
    assert out["decision"]["effect"] == "deny"
    assert out["decision"]["code"] == "NO_MATCHING_ALLOW"
    rows = sqlite3.connect(pub.disclosures_path).execute(
        "SELECT effect, receiver FROM disclosures"
    ).fetchall()
    assert rows == [("deny", "stranger")]


def test_handle_recall_allows_and_discloses(tmp_path):
    pub = build_publisher(tmp_path)
    daemon = PublisherDaemon(
        {"why": pub}, tmp_path / "s.sock", FakeEmbeddings()
    )
    frame = recall_frame(
        receiver="engram",
        publisher="why",
        context=CONTEXT,
        purpose="session-recall",
        query="work: rivers need bridges",
        k=5,
        at=NOW,
    )
    out = daemon.handle_frame(frame)
    assert out["decision"] == {
        "effect": "allow",
        "ruleId": "allow-engram-technical",
        "code": None,
    }
    assert len(out["candidates"]) == 1
    assert out["queryDigest"]["value"] == hashlib.sha256(
        b"work: rivers need bridges"
    ).hexdigest()
    row = sqlite3.connect(pub.disclosures_path).execute(
        "SELECT action, memory_ids FROM disclosures"
    ).fetchone()
    assert row[0] == "recall"
    assert json.loads(row[1]) == [out["candidates"][0]["memoryId"]]


def test_read_requires_read_action(tmp_path):
    pub = build_publisher(tmp_path)
    write_policy(pub.policy_path, actions=("recall",))
    daemon = PublisherDaemon(
        {"why": pub}, tmp_path / "s.sock", FakeEmbeddings()
    )
    recall = daemon.handle_frame(
        recall_frame(
            receiver="engram",
            publisher="why",
            context=CONTEXT,
            purpose="session-recall",
            query="work: rivers need bridges",
            k=5,
            at=NOW,
        )
    )
    memory_id = recall["candidates"][0]["memoryId"]
    out = daemon.handle_frame(
        read_frame(
            receiver="engram",
            publisher="why",
            context=CONTEXT,
            purpose="session-recall",
            turn_id=recall["turnId"],
            memory_ids=[memory_id],
        )
    )
    assert out["kind"] == "read_result"
    assert out["items"][0]["content"] is None
    assert out["items"][0]["decision"]["code"] == "NO_MATCHING_ALLOW"


def test_read_delivers_content_when_allowed(tmp_path):
    pub = build_publisher(tmp_path)
    daemon = PublisherDaemon(
        {"why": pub}, tmp_path / "s.sock", FakeEmbeddings()
    )
    recall = daemon.handle_frame(
        recall_frame(
            receiver="engram",
            publisher="why",
            context=CONTEXT,
            purpose="session-recall",
            query="work: rivers need bridges",
            k=5,
            at=NOW,
        )
    )
    memory_id = recall["candidates"][0]["memoryId"]
    out = daemon.handle_frame(
        read_frame(
            receiver="engram",
            publisher="why",
            context=CONTEXT,
            purpose="session-recall",
            turn_id=recall["turnId"],
            memory_ids=[memory_id],
        )
    )
    assert out["items"][0]["content"] == "work: rivers need bridges"
    assert out["items"][0]["decision"]["effect"] == "allow"


def test_unknown_publisher_and_unavailable_store(tmp_path):
    pub = build_publisher(tmp_path)
    daemon = PublisherDaemon(
        {"why": pub}, tmp_path / "s.sock", FakeEmbeddings()
    )
    unknown = daemon.handle_frame(
        recall_frame(
            receiver="engram",
            publisher="ghost",
            context=CONTEXT,
            purpose="session-recall",
            query="x",
            k=1,
            at=NOW,
        )
    )
    assert unknown["kind"] == "error"
    assert unknown["code"] == "PUBLISHER_UNAVAILABLE"

    pub.db_path.unlink()
    gone = daemon.handle_frame(
        recall_frame(
            receiver="engram",
            publisher="why",
            context=CONTEXT,
            purpose="session-recall",
            query="x",
            k=1,
            at=NOW,
        )
    )
    assert gone["kind"] == "error"
    assert gone["code"] == "PUBLISHER_UNAVAILABLE"


def test_missing_publisher_is_malformed_before_store_lookup(tmp_path):
    daemon = PublisherDaemon({}, tmp_path / "s.sock", FakeEmbeddings())
    frame = _valid_recall()
    del frame["publisher"]

    out = daemon.handle_frame(frame)

    assert out["kind"] == "error"
    assert out["code"] == "MALFORMED_FRAME"


def test_invalid_recall_fields_are_malformed_before_store_lookup(tmp_path):
    daemon = PublisherDaemon({}, tmp_path / "s.sock", FakeEmbeddings())
    invalid_frames = []
    for field, value in (
        ("at", "not-a-timestamp"),
        ("context", []),
        ("k", True),
        ("k", 0),
    ):
        frame = _valid_recall()
        frame[field] = value
        invalid_frames.append(frame)

    for frame in invalid_frames:
        out = daemon.handle_frame(frame)
        assert out["kind"] == "error"
        assert out["code"] == "MALFORMED_FRAME"


def test_invalid_read_memory_ids_are_malformed_before_store_lookup(tmp_path):
    daemon = PublisherDaemon({}, tmp_path / "s.sock", FakeEmbeddings())
    frame = _valid_read()
    frame["memoryIds"] = [1]

    out = daemon.handle_frame(frame)

    assert out["kind"] == "error"
    assert out["code"] == "MALFORMED_FRAME"


def test_socket_round_trip_leaves_store_unchanged(tmp_path):
    pub = build_publisher(tmp_path)
    before = hashlib.sha256(pub.db_path.read_bytes()).hexdigest()
    # Darwin's sockaddr_un.sun_path is shorter than pytest's nested tmp path.
    sock_path = Path("/private/tmp") / f"engram-lh-{uuid.uuid4().hex}.sock"
    daemon = PublisherDaemon({"why": pub}, sock_path, FakeEmbeddings())
    thread = threading.Thread(target=daemon.serve_forever, daemon=True)
    thread.start()
    try:
        daemon.wait_ready(timeout=5)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(5)
            client.connect(str(sock_path))
            client.sendall(
                encode(
                    recall_frame(
                        receiver="engram",
                        publisher="why",
                        context=CONTEXT,
                        purpose="session-recall",
                        query="work: rivers need bridges",
                        k=3,
                        at=NOW,
                    )
                )
            )
            line = client.makefile("rb").readline()
        out = decode(line)
        assert out["kind"] == "recall_result"
        assert len(out["candidates"]) == 1
    finally:
        daemon.stop()
        thread.join(timeout=5)
    assert hashlib.sha256(pub.db_path.read_bytes()).hexdigest() == before


def test_operational_error_on_open_is_publisher_unavailable(
    tmp_path, monkeypatch
):
    pub = build_publisher(tmp_path)

    def refuse(cls, path):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(Storage, "open_read_only", classmethod(refuse))
    daemon = PublisherDaemon(
        {"why": pub}, tmp_path / "s.sock", FakeEmbeddings()
    )
    out = daemon.handle_frame(
        recall_frame(
            receiver="engram",
            publisher="why",
            context=CONTEXT,
            purpose="session-recall",
            query="x",
            k=1,
            at=NOW,
        )
    )
    assert out["kind"] == "error"
    assert out["code"] == "PUBLISHER_UNAVAILABLE"
    assert pub.storage is None


def test_pre_migration_store_without_lane_column_is_unavailable(tmp_path):
    inst = tmp_path / ".engram" / "instances" / "agi"
    inst.mkdir(parents=True)
    connection = sqlite3.connect(inst / "graph.db")
    connection.execute(
        "CREATE TABLE episodes (id TEXT PRIMARY KEY, content TEXT)"
    )
    connection.commit()
    connection.close()
    write_policy(inst / "lighthouse-policy.json")
    pub = PublisherStore(
        name="agi",
        db_path=inst / "graph.db",
        policy_path=inst / "lighthouse-policy.json",
        disclosures_path=inst / "lighthouse-disclosures.db",
    )
    daemon = PublisherDaemon(
        {"agi": pub}, tmp_path / "s.sock", FakeEmbeddings()
    )
    out = daemon.handle_frame(
        recall_frame(
            receiver="engram",
            publisher="agi",
            context=CONTEXT,
            purpose="session-recall",
            query="x",
            k=1,
            at=NOW,
        )
    )
    assert out["kind"] == "error"
    assert out["code"] == "PUBLISHER_UNAVAILABLE"
    assert pub.storage is None


def test_daemon_never_imports_server():
    import lighthouse_daemon

    source = Path(lighthouse_daemon.__file__).read_text()
    assert "import server" not in source
    assert "from server" not in source
