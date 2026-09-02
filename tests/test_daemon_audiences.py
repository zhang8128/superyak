"""The daemon serves only rows shared to an audience the receiver may see."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid

import pytest

from lighthouse_daemon import PublisherDaemon, retrieve
from lighthouse_protocol import read_frame, recall_frame
from storage import Storage
from tests.test_lighthouse_daemon import (
    CONTEXT,
    NOW,
    FakeEmbeddings,
    build_publisher,
    write_policy,
)


def _insert_share(
    store: Storage,
    *,
    memory_id: str,
    content: str,
    audience: str,
    layer: str = "episode",
) -> None:
    store.conn.execute(
        "INSERT INTO shared_memories (share_id, memory_id, source_instance, "
        "source_id, layer, audience, reason, content_digest, shared_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            memory_id,
            "source",
            memory_id,
            layer,
            audience,
            "test fixture",
            hashlib.sha256(content.encode()).hexdigest(),
            "2026-09-01T00:00:00Z",
        ),
    )
    store.conn.commit()


@pytest.fixture
def published(tmp_path):
    store = Storage(str(tmp_path / "published.db"))
    ids = {}
    for name, audience in (
        ("alpha", "commons"),
        ("beta", "group:crossing"),
        ("gamma", "group:research"),
    ):
        memory_id = str(uuid.uuid4())
        content = f"{name} content about rivers"
        store.add_episode(
            id=memory_id,
            session_id=None,
            content=content,
            episode_type="shared",
            embedding=FakeEmbeddings().embed([content])[0],
        )
        _insert_share(
            store,
            memory_id=memory_id,
            content=content,
            audience=audience,
        )
        ids[name] = memory_id
    yield store, ids
    store.close()


def test_only_allowed_audiences_are_returned(published):
    store, ids = published
    out = retrieve(
        store, FakeEmbeddings(), "rivers", 10, frozenset({"commons"})
    )
    assert [entry["memoryId"] for entry in out] == [ids["alpha"]]
    assert out[0]["audiences"] == ["commons"]


def test_group_audience_widens_the_result(published):
    store, ids = published
    out = retrieve(
        store,
        FakeEmbeddings(),
        "rivers",
        10,
        frozenset({"commons", "group:crossing"}),
    )
    assert {entry["memoryId"] for entry in out} == {
        ids["alpha"],
        ids["beta"],
    }


def test_empty_allowed_set_returns_nothing(published):
    store, _ = published
    assert retrieve(store, FakeEmbeddings(), "rivers", 10, frozenset()) == []


def test_unshared_rows_are_never_returned(published):
    store, _ = published
    orphan = str(uuid.uuid4())
    text = "rivers but never shared"
    store.add_episode(
        id=orphan,
        session_id=None,
        content=text,
        episode_type="test",
        embedding=FakeEmbeddings().embed([text])[0],
    )
    out = retrieve(
        store,
        FakeEmbeddings(),
        "rivers",
        10,
        frozenset({"commons", "group:crossing", "group:research"}),
    )
    assert orphan not in {entry["memoryId"] for entry in out}


def test_entries_have_sorted_intersection_and_no_lane_key(published):
    store, ids = published
    alpha = store.get_episode(ids["alpha"])
    _insert_share(
        store,
        memory_id=ids["alpha"],
        content=alpha["content"],
        audience="group:crossing",
    )
    out = retrieve(
        store,
        FakeEmbeddings(),
        "alpha content about rivers",
        10,
        frozenset({"group:crossing", "commons"}),
    )
    entry = next(item for item in out if item["memoryId"] == ids["alpha"])
    assert entry["audiences"] == ["commons", "group:crossing"]
    assert "lane" not in entry


def test_shared_semantic_is_filtered_by_audience(published):
    store, _ = published
    memory_id = str(uuid.uuid4())
    content = "semantic knowledge about rivers"
    store.add_semantic(
        id=memory_id,
        content=content,
        kind="fact",
        confidence=0.8,
        embedding=FakeEmbeddings().embed([content])[0],
        source_episode_ids=[],
    )
    _insert_share(
        store,
        memory_id=memory_id,
        content=content,
        audience="group:crossing",
        layer="semantic",
    )
    out = retrieve(
        store,
        FakeEmbeddings(),
        content,
        10,
        frozenset({"group:crossing"}),
    )
    item = next(entry for entry in out if entry["memoryId"] == memory_id)
    assert item["layer"] == "semantic"
    assert item["audiences"] == ["group:crossing"]


def test_allowed_receiver_absent_from_policy_audience_map_sees_nothing(tmp_path):
    publisher = build_publisher(tmp_path)
    write_policy(
        publisher.policy_path,
        receiver="stranger",
        audience_map={"urn:engram:engram": ["commons"]},
    )
    daemon = PublisherDaemon(
        {"why": publisher}, tmp_path / "lighthouse.sock", FakeEmbeddings()
    )
    out = daemon.handle_frame(
        recall_frame(
            receiver="stranger",
            publisher="why",
            context=CONTEXT,
            purpose="session-recall",
            query="shared: rivers need bridges",
            k=5,
            at=NOW,
        )
    )
    assert out["decision"]["effect"] == "allow"
    assert out["candidates"] == []


def test_read_refuses_share_outside_receiver_audiences(tmp_path):
    publisher = build_publisher(tmp_path)
    connection = sqlite3.connect(publisher.db_path)
    try:
        memory_id = connection.execute(
            "SELECT memory_id FROM shared_memories"
        ).fetchone()[0]
    finally:
        connection.close()
    write_policy(
        publisher.policy_path,
        audience_map={"urn:engram:engram": ["group:crossing"]},
    )
    daemon = PublisherDaemon(
        {"why": publisher}, tmp_path / "lighthouse.sock", FakeEmbeddings()
    )
    out = daemon.handle_frame(
        read_frame(
            receiver="engram",
            publisher="why",
            context=CONTEXT,
            purpose="session-recall",
            turn_id="turn-1",
            memory_ids=[memory_id],
        )
    )
    assert out["items"] == [
        {
            "memoryId": memory_id,
            "content": None,
            "audiences": [],
            "decision": {
                "effect": "allow",
                "ruleId": "allow-engram-technical",
                "code": None,
            },
        }
    ]


def test_tampered_share_metadata_fails_closed(published):
    store, ids = published
    store.conn.execute(
        "UPDATE shared_memories SET content_digest = ? WHERE memory_id = ?",
        ("0" * 64, ids["alpha"]),
    )
    store.conn.commit()
    out = retrieve(
        store, FakeEmbeddings(), "alpha", 10, frozenset({"commons"})
    )
    assert ids["alpha"] not in {entry["memoryId"] for entry in out}
