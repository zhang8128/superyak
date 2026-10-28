"""Task 17: lane notes (P 5.3; U6, U25, MF2, R20). The store tells the ledger before and after every re-lane."""
import logging
import sqlite3
import time
import uuid
from pathlib import Path

import pytest

import server
from permission_ledger import Ledger, ledger_path
from permissions import parse_selector, record_matches
from storage import LaneNoteError, Storage
from tests.permissions_support import (
    ANDY, HOME, T, do, home_use, make_house_with_029, make_ledger_unreadable, raise_gate)
from tests.test_recall_margins import engram_server_env  # noqa: F401


def now() -> int:
    return int(time.time())


# ---------------------------------------------------------------- helpers

def add_personal_episode(store, content="a personal note"):
    ep = str(uuid.uuid4())
    store.add_episode(id=ep, session_id="t", content=content)
    return ep


def refusing_listener():
    def listener(phase, rows, target):
        raise RuntimeError("the ledger is not writable")
    return listener


def store_id(store) -> str:
    return store.instance_identity()["instance_id"]


def ref(store, ep) -> str:
    return f"mem:{store_id(store)}/episode/{ep}"


def ledger_listener(led, store, crash_at=None):
    sid = store_id(store)

    def listener(phase, rows, target):
        if phase == crash_at:
            raise SystemExit("crash between the store's commit and the settling note")
        led.note_lanes(phase, rows, target, store_id=sid, now=now())
    return listener


def raised_ledger_and_store(tmp_path, mode="shadow"):
    path = tmp_path / ".engram" / "instances" / "lighthouse" / "graph.db"
    path.parent.mkdir(parents=True)
    store = Storage(str(path))
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    do(led, ANDY, "register-store", instance_id=store_id(store), name="engram", owner=ANDY, place=HOME,
       imprint_of=None)
    do(led, ANDY, "register-agent", agent="agent:rio-grande", acts_for=HOME)
    do(led, ANDY, "put-agent", agent="agent:rio-grande", place=HOME)
    raise_gate(led, mode)
    return led, store, add_personal_episode(store)


class FailingUpdate:
    """The store's connection, with the next `UPDATE episodes SET lane` failing."""

    def __init__(self, real):
        self._real = real

    def execute(self, sql, *args):
        if sql.lstrip().startswith("UPDATE episodes SET lane"):
            raise sqlite3.OperationalError("disk I/O error")
        return self._real.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._real, name)


def fail_the_next_update(store):
    store.conn = FailingUpdate(store.conn)


def latest(state, r):
    return state.lane_notes[r][-1].lane          # ordered by (at, seq), ties in insertion order


def lane_selector(lane):
    return parse_selector({
        "audience": [HOME], "requesters": "*",
        "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": [lane], "collections": "*",
                    "memories": "*"},
        "actions": ["recall"], "purposes": "*"})


def lane_record(led, effect, lane):
    out = led.perform(
        __import__("permissions").Act(effect, {"layer": HOME, "selector": lane_selector(lane),
                                                "valid_from": now() - 5, "valid_until": now() + 86400,
                                                "reason": "lane test"}),
        actor=ANDY, channel="terminal", now=now())
    return led.state().records[out.ref]


def allow_anchored_now(led, lanes):
    return lane_record(led, "allow", lanes[0])


# ---------------------------------------------------------------- the store's side

def test_u6_a_failing_first_note_refuses_the_re_lane(tmp_db):
    ep = add_personal_episode(tmp_db)
    tmp_db.lane_listener = refusing_listener()
    with pytest.raises(LaneNoteError):
        tmp_db.set_episode_lanes([ep], "work")
    assert tmp_db.get_episode(ep)["lane"] == "personal"


def test_the_listener_sees_before_and_after_with_the_rows_read_before_the_update(tmp_db):
    ep = add_personal_episode(tmp_db)
    seen = []
    tmp_db.lane_listener = lambda phase, rows, target: seen.append((phase, [dict(r) for r in rows], target))
    assert tmp_db.set_episode_lanes([ep], "work") == 1
    created = tmp_db.get_episode(ep)["created_at"]
    row = {"id": ep, "lane": "personal", "created_at": created}
    assert seen == [("before", [row], "work"), ("after", [row], "work")]


def test_with_no_listener_nothing_changes(tmp_db):
    ep = add_personal_episode(tmp_db)
    assert tmp_db.lane_listener is None
    assert tmp_db.set_episode_lanes([ep], "work") == 1
    with tmp_db.transaction():
        assert tmp_db.set_episode_lanes([ep], "personal") == 1
    assert tmp_db.get_episode(ep)["lane"] == "personal"


def test_after_outcome_outside_a_transaction_runs_on_commit_at_once(tmp_db):
    calls = []
    tmp_db.after_outcome(lambda: calls.append("commit"), lambda: calls.append("rollback"))
    assert calls == ["commit"]


def test_after_outcome_inside_a_transaction_waits_and_the_queues_clear(tmp_db):
    calls = []
    with tmp_db.transaction():
        tmp_db.after_outcome(lambda: calls.append("commit"), lambda: calls.append("rollback"))
        with tmp_db.transaction():
            tmp_db.after_outcome(lambda: calls.append("commit2"), lambda: calls.append("rollback2"))
        assert calls == []
    assert calls == ["commit", "commit2"]
    with pytest.raises(ValueError):
        with tmp_db.transaction():
            tmp_db.after_outcome(lambda: calls.append("commit3"), lambda: calls.append("rollback3"))
            raise ValueError("x")
    assert calls == ["commit", "commit2", "rollback3"]
    with tmp_db.transaction():
        pass
    assert calls == ["commit", "commit2", "rollback3"]          # nothing left over


def test_a_callback_exception_is_logged_not_raised_but_a_system_exit_propagates(tmp_db, caplog):
    def boom():
        raise RuntimeError("callback broke")

    def quit_():
        raise SystemExit(3)

    with caplog.at_level(logging.WARNING):
        with tmp_db.transaction():
            tmp_db.after_outcome(boom, lambda: None)
        tmp_db.after_outcome(boom, lambda: None)
    assert "callback broke" in caplog.text
    with pytest.raises(SystemExit):
        with tmp_db.transaction():
            tmp_db.after_outcome(quit_, lambda: None)


def test_a_commit_that_fails_runs_the_rollback_calls(tmp_db):
    calls = []

    class BadCommit:
        def __init__(self, real):
            self._real = real

        def commit(self):
            raise sqlite3.OperationalError("database is locked")

        def __getattr__(self, name):
            return getattr(self._real, name)

    real = tmp_db.conn
    with pytest.raises(sqlite3.OperationalError):
        with tmp_db.transaction():
            tmp_db.after_outcome(lambda: calls.append("commit"), lambda: calls.append("rollback"))
            tmp_db.conn = BadCommit(real)
    tmp_db.conn = real
    assert calls == ["rollback"]


# ---------------------------------------------------------------- the ledger's side

def test_u25_a_failed_update_settles_to_the_old_lane(tmp_path):
    led, store, ep = raised_ledger_and_store(tmp_path, mode="shadow")
    store.lane_listener = ledger_listener(led, store)
    fail_the_next_update(store)
    with pytest.raises(sqlite3.OperationalError):
        store.set_episode_lanes([ep], "work")
    assert [n.lane for n in led.state().lane_notes[ref(store, ep)]] == ["personal", "pending", "personal"]


def test_u25_a_crash_between_the_calls_leaves_a_pending_note(tmp_path):
    led, store, ep = raised_ledger_and_store(tmp_path, mode="shadow")
    store.lane_listener = ledger_listener(led, store, crash_at="after")   # the UPDATE committed, no settling note
    with pytest.raises(SystemExit):
        store.set_episode_lanes([ep], "work")
    s = led.state()
    assert latest(s, ref(store, ep)) == "pending"
    assert store.get_episode(ep)["lane"] == "work"
    work_allow = lane_record(led, "allow", "work")
    personal_deny = lane_record(led, "deny", "personal")
    s = led.state()
    assert not record_matches(s, work_allow, home_use(ref(store, ep), now()), "recall")
    assert record_matches(s, personal_deny, home_use(ref(store, ep), now()), "recall")


def test_mf2_inside_a_transaction_the_settling_note_waits_for_the_outer_commit(tmp_path):
    led, store, ep = raised_ledger_and_store(tmp_path, mode="shadow")
    store.lane_listener = ledger_listener(led, store)
    with store.transaction():
        store.set_episode_lanes([ep], "work")
        assert latest(led.state(), ref(store, ep)) == "pending"        # the store's UPDATE is not committed yet
    assert latest(led.state(), ref(store, ep)) == "work" and store.get_episode(ep)["lane"] == "work"


def test_mf2_a_re_lane_inside_a_transaction_that_raises_settles_to_the_old_lane(tmp_path):
    led, store, ep = raised_ledger_and_store(tmp_path, mode="shadow")
    store.lane_listener = ledger_listener(led, store)
    with pytest.raises(RuntimeError, match="later step"):
        with store.transaction():
            store.set_episode_lanes([ep], "work")
            raise RuntimeError("a later step of the commit failed")
    assert store.get_episode(ep)["lane"] == "personal"
    assert [n.lane for n in led.state().lane_notes[ref(store, ep)]] == ["personal", "pending", "personal"]
    work_allow = allow_anchored_now(led, lanes=["work"])                # anchored after the failed move
    assert not record_matches(led.state(), work_allow, home_use(ref(store, ep), now()), "recall")


def test_note_lanes_writes_a_first_note_only_for_a_ref_with_none_and_latest_lane_note_reads_it(tmp_path):
    led, store, ep = raised_ledger_and_store(tmp_path, mode="shadow")
    r = ref(store, ep)
    assert led.latest_lane_note(r) is None
    store.lane_listener = ledger_listener(led, store)
    store.set_episode_lanes([ep], "work")
    store.set_episode_lanes([ep], "personal")
    assert [n.lane for n in led.state().lane_notes[r]] == ["personal", "pending", "work", "pending", "personal"]
    assert led.latest_lane_note(r) == "personal"
    assert led.verify() is None


# ---------------------------------------------------------------- the server's side

@pytest.fixture
def shadow_server(engram_server_env, tmp_path):
    server._init()
    make_house_with_029(tmp_path, "lighthouse")
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    do(led, ANDY, "register-store", instance_id=store_id(server._storage), name="engram", owner=ANDY,
       place=HOME, imprint_of=None)
    raise_gate(led, "shadow")
    led.close()
    return server


@pytest.fixture
def closed_server(shadow_server, tmp_path):
    make_ledger_unreadable(tmp_path)
    return shadow_server


def store_lane(ep):
    return server._storage.get_episode(ep)["lane"]


def latest_note(ep, home):
    led = Ledger.open_read_only(home)
    try:
        return led.latest_lane_note(ref(server._storage, ep))
    finally:
        led.close()


def remember_personal_cluster():
    text = "a walk by the river"         # the same words, so the three share one embedding and one cluster
    emb = server._embeddings.embed([text])[0]
    eps = []
    for _ in range(3):
        ep = str(uuid.uuid4())
        server._storage.add_episode(id=ep, session_id="t", content=text, embedding=emb)
        eps.append(ep)
    return eps


def prepare_compression_relaning_to(lane):
    result = server._compressor.cluster_episodes()
    assert len(result["clusters"]) == 1
    summaries = [{"content": "a summary of the cluster", "kind": "fact", "action": "new", "lane": lane}
                 for _ in result["clusters"]]
    return result["compress_id"], summaries


def new_semantic_lane(result):
    rows = server._storage.conn.execute("SELECT lane FROM semantics").fetchall()
    assert len(rows) == 1
    return rows[0]["lane"]


def test_mf2_a_compression_commit_that_rolls_back_leaves_no_work_note(shadow_server, monkeypatch, tmp_path):
    eps = remember_personal_cluster()                                   # three personal episodes, one cluster
    cid, summaries = prepare_compression_relaning_to("work")            # the review sets the cluster's lane to work

    def disk_full(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(server._storage, "add_semantic", disk_full)
    with pytest.raises(RuntimeError, match="disk full"):
        server._compressor.commit(cid, summaries)                       # inside storage.transaction() (:466)
    assert {store_lane(ep) for ep in eps} == {latest_note(ep, tmp_path) for ep in eps} == {"personal"}


def test_a_compression_commit_that_succeeds_ends_on_work_notes(shadow_server, tmp_path):
    eps = remember_personal_cluster()
    cid, summaries = prepare_compression_relaning_to("work")
    server._compressor.commit(cid, summaries)
    assert {store_lane(ep) for ep in eps} == {latest_note(ep, tmp_path) for ep in eps} == {"work"}


def test_compression_keeps_the_lane_when_the_note_cannot_be_written(closed_server, caplog):   # R20
    eps = remember_personal_cluster()                                   # the gate reads closed: no note can be written
    cid, summaries = prepare_compression_relaning_to("work")
    with caplog.at_level(logging.WARNING):
        result = server._compressor.commit(cid, summaries)
    assert result["semantics_created"] == 1 and "lane" in caplog.text
    assert {store_lane(ep) for ep in eps} == {"personal"}
    assert new_semantic_lane(result) == "personal"                      # the summary keeps its evidence's lane


def test_off_writes_no_note_and_closed_refuses_the_re_lane(engram_server_env, tmp_path):
    ep = server.remember(content="a personal note long enough")["episode_id"]
    assert server._storage.set_episode_lanes([ep], "work") == 1 and not ledger_path(tmp_path).exists()   # off
    make_house_with_029(tmp_path, "lighthouse")
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    raise_gate(led, "shadow")
    led.close()
    make_ledger_unreadable(tmp_path)                                    # a raised ledger, then made unreadable
    with pytest.raises(LaneNoteError):
        server._storage.set_episode_lanes([ep], "personal")
    assert server._storage.get_episode(ep)["lane"] == "work"
