"""Live publisher operations honor policy and explicit-share withdrawal."""

from __future__ import annotations

import json
import socket
import sqlite3
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from lighthouse_daemon import PublisherDaemon, PublisherStore
from lighthouse_policy import Policy
from lighthouse_protocol import artifact_digest, decode, encode, read_frame, recall_frame
from sharing import share, unshare
from storage import Storage
from tests.test_lighthouse_daemon import CONTEXT, NOW, FakeEmbeddings, write_policy


CONTENT = "shared: rivers need bridges"


@pytest.fixture
def live_publisher(tmp_path):
    source_path = tmp_path / "private.db"
    published_path = tmp_path / "published.db"
    source = Storage(str(source_path))
    published = Storage(str(published_path))
    source_id = str(uuid.uuid4())
    source.add_episode(
        source_id, None, CONTENT, embedding=FakeEmbeddings().embed([CONTENT])[0],
        lane="personal",
    )
    record = share(
        source_storage=source, published_storage=published, source_id=source_id,
        source_instance="private", layer="episode", audience="commons",
        reason="disposable withdrawal test",
    )
    # A work lane alone must never authorize publication.
    published.add_episode(
        str(uuid.uuid4()), None, "unshared work about rivers",
        embedding=FakeEmbeddings().embed([CONTENT])[0], lane="work",
    )
    source.close()
    published.close()
    publisher = PublisherStore(
        name="why", db_path=published_path,
        policy_path=tmp_path / "policy.json",
        disclosures_path=tmp_path / "disclosures.db",
    )
    write_policy(publisher.policy_path)
    # Keep below Darwin's short Unix socket path limit.
    socket_path = Path("/tmp") / f"engram-withdraw-{uuid.uuid4().hex}.sock"
    daemon = PublisherDaemon({"why": publisher}, socket_path, FakeEmbeddings())
    thread = threading.Thread(target=daemon.serve_forever, daemon=True)
    thread.start()
    try:
        assert daemon.wait_ready(timeout=5)
        yield SimpleNamespace(
            publisher=publisher, daemon=daemon, socket_path=socket_path,
            record=record, source_path=source_path,
        )
    finally:
        daemon.stop()
        thread.join(timeout=5)
        assert not thread.is_alive()


def _exchange(live, action):
    if action == "recall":
        frame = recall_frame(
            receiver="engram", publisher="why", context=CONTEXT,
            purpose="session-recall", query=CONTENT, k=5, at=NOW,
        )
    else:
        frame = read_frame(
            receiver="engram", publisher="why", context=CONTEXT,
            purpose="session-recall", turn_id="withdrawal-test",
            memory_ids=[live.record.memory_id],
        )
        frame["at"] = NOW
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(str(live.socket_path))
        client.sendall(encode(frame))
        with client.makefile("rb") as reader:
            return decode(reader.readline(1024 * 1024))


def _decision(response):
    if response["kind"] == "recall_result":
        return response["decision"]
    return response["items"][0]["decision"]


def _assert_delivered(response, live):
    assert _decision(response)["effect"] == "allow"
    if response["kind"] == "recall_result":
        assert [item["memoryId"] for item in response["candidates"]] == [
            live.record.memory_id
        ]
    else:
        assert response["items"][0]["content"] == CONTENT
        assert response["items"][0]["audiences"] == ["commons"]


def _assert_withheld(response):
    if response["kind"] == "recall_result":
        assert response["candidates"] == []
    else:
        assert response["items"][0]["content"] is None
        assert response["items"][0]["audiences"] == []


def _rewrite_policy(path, edit):
    artifact = json.loads(path.read_text())
    edit(artifact)
    artifact["digest"] = artifact_digest(artifact)
    replacement = path.with_suffix(".next")
    replacement.write_text(json.dumps(artifact))
    replacement.replace(path)


def _disclosure(live, response):
    with sqlite3.connect(live.publisher.disclosures_path) as connection:
        return connection.execute(
            "SELECT action, effect, code, memory_ids FROM disclosures WHERE id = ?",
            (response["disclosureId"],),
        ).fetchone()


@pytest.mark.parametrize("action", ["recall", "read"])
def test_caller_cannot_backdate_expired_publisher_grant(live_publisher, action):
    from datetime import datetime, timezone
    live = live_publisher
    live.daemon.clock = lambda: datetime(2026, 9, 6, tzinfo=timezone.utc)
    _rewrite_policy(live.publisher.policy_path, lambda artifact:
                    artifact["payload"]["rules"][0].update(validUntil="2026-09-02T00:00:00Z"))
    # _exchange sends September 1 on both recall and read frames.
    response = _exchange(live, action)
    assert _decision(response)["code"] == "OUTSIDE_VALIDITY"
    _assert_withheld(response)


@pytest.mark.parametrize("action", ["recall", "read"])
@pytest.mark.parametrize(
    ("withdrawal", "code"),
    [("deny", "EXPLICIT_DENY"), ("expired", "OUTSIDE_VALIDITY"),
     ("remove_action", "NO_MATCHING_ALLOW")],
)
def test_action_withdrawal_after_delivery(live_publisher, action, withdrawal, code):
    live = live_publisher
    before = live.publisher.db_path.read_bytes()
    private_before = live.source_path.read_bytes()
    _assert_delivered(_exchange(live, action), live)

    def edit(artifact):
        rule = artifact["payload"]["rules"][0]
        if withdrawal == "deny":
            rule["effect"] = "deny"
        elif withdrawal == "expired":
            rule["validUntil"] = "2026-08-01T00:00:00Z"
        else:
            rule["actions"].remove(action)

    _rewrite_policy(live.publisher.policy_path, edit)
    response = _exchange(live, action)

    assert _decision(response)["effect"] == "deny"
    assert _decision(response)["code"] == code
    _assert_withheld(response)
    assert _disclosure(live, response) == (action, "deny", code, "[]")
    assert live.publisher.db_path.read_bytes() == before
    assert live.source_path.read_bytes() == private_before


@pytest.mark.parametrize("action", ["recall", "read"])
@pytest.mark.parametrize("invalid", ["json", "digest", "missing", "rule", "string_selector", "issuer"])
def test_invalid_policy_never_reuses_earlier_allow(live_publisher, action, invalid):
    live = live_publisher
    before = live.publisher.db_path.read_bytes()
    _assert_delivered(_exchange(live, action), live)
    path = live.publisher.policy_path
    if invalid == "json":
        path.write_text("{")
    elif invalid == "digest":
        artifact = json.loads(path.read_text())
        artifact["payload"]["rules"][0]["effect"] = "deny"
        path.write_text(json.dumps(artifact))
    elif invalid == "missing":
        path.unlink()
    elif invalid == "string_selector":
        _rewrite_policy(path, lambda artifact: artifact["payload"]["rules"][0].update(contexts="unrelated/*"))
    elif invalid == "issuer":
        _rewrite_policy(path, lambda artifact: artifact.update(issuer="urn:engram:stranger"))
    else:
        _rewrite_policy(
            path, lambda artifact: artifact["payload"]["rules"][0].pop("actions")
        )

    response = _exchange(live, action)

    assert response["kind"] == "error"
    assert response["code"] == "PUBLISHER_UNAVAILABLE"
    assert live.publisher.db_path.read_bytes() == before
    # Repair is also live: no daemon restart is required.
    write_policy(path)
    _assert_delivered(_exchange(live, action), live)


@pytest.mark.parametrize("action", ["recall", "read"])
def test_action_and_audience_use_one_snapshot(live_publisher, monkeypatch, action):
    live = live_publisher
    _assert_delivered(_exchange(live, action), live)
    write_policy(live.publisher.policy_path, audience_map={})
    original_decide = Policy.decide

    def decide_then_replace(policy, request):
        decision = original_decide(policy, request)
        # Neither snapshot permits delivery: the first lacks an audience,
        # the second denies actions. Combining them would disclose content.
        def edit(artifact):
            artifact["payload"]["rules"][0]["effect"] = "deny"
            artifact["extensions"]["engram:audiences"] = {
                "urn:engram:engram": ["commons"]
            }

        _rewrite_policy(live.publisher.policy_path, edit)
        return decision

    monkeypatch.setattr(Policy, "decide", decide_then_replace)
    response = _exchange(live, action)
    _assert_withheld(response)
    assert _disclosure(live, response) == (action, "allow", None, "[]")
    subsequent = _exchange(live, action)
    assert _decision(subsequent)["effect"] == "deny"
    _assert_withheld(subsequent)


@pytest.mark.parametrize("action", ["recall", "read"])
def test_audience_withdrawal_after_delivery(live_publisher, action):
    live = live_publisher
    before = live.publisher.db_path.read_bytes()
    _assert_delivered(_exchange(live, action), live)
    write_policy(live.publisher.policy_path, audience_map={})

    response = _exchange(live, action)

    assert _decision(response)["effect"] == "allow"
    _assert_withheld(response)
    assert _disclosure(live, response) == (action, "allow", None, "[]")
    assert live.publisher.db_path.read_bytes() == before


def test_unshare_withdraws_recall_and_read_without_changing_private_source(live_publisher):
    live = live_publisher
    private_before = live.source_path.read_bytes()
    _assert_delivered(_exchange(live, "recall"), live)
    _assert_delivered(_exchange(live, "read"), live)
    published = Storage(str(live.publisher.db_path))
    try:
        assert unshare(published_storage=published, share_id=live.record.share_id)
    finally:
        published.close()
    # Only the explicit writer above may change the published database.
    after_unshare = live.publisher.db_path.read_bytes()

    for action in ("recall", "read"):
        response = _exchange(live, action)
        _assert_withheld(response)
        assert _disclosure(live, response) == (action, "allow", None, "[]")
    assert live.source_path.read_bytes() == private_before
    assert live.publisher.db_path.read_bytes() == after_unshare


def test_explicit_personal_share_reports_its_lane(live_publisher):
    response = _exchange(live_publisher, "recall")
    _assert_delivered(response, live_publisher)
    assert response["candidates"][0]["lane"] == "personal"
    assert response["candidates"][0]["layer"] == "episode"


@pytest.mark.parametrize("action", ["recall", "read"])
def test_invalid_published_lane_fails_closed(live_publisher, action):
    live = live_publisher
    _assert_delivered(_exchange(live, action), live)
    with sqlite3.connect(live.publisher.db_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(
            "UPDATE episodes SET lane = 'unknown' WHERE id = ?",
            (live.record.memory_id,),
        )

    _assert_withheld(_exchange(live, action))


@pytest.mark.parametrize("action", ["recall", "read"])
def test_withdrawn_action_denies_before_retrieval(live_publisher, action):
    live = live_publisher
    _assert_delivered(_exchange(live, action), live)
    _rewrite_policy(live.publisher.policy_path, lambda artifact: artifact["payload"].update(rules=[]))

    # Observe actual SQLite access after the authorization changes. A denial
    # must not even read a memory row or vector from the published store.
    statements = []
    live.publisher.storage.conn.set_trace_callback(statements.append)
    response = _exchange(live, action)

    assert _decision(response)["effect"] == "deny"
    _assert_withheld(response)
    assert statements == []
