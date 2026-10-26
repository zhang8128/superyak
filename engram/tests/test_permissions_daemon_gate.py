"""The daemon's gate and the outside-home rule (P 12.1, 12.3, P29; Task 19)."""

import pytest

from lighthouse_daemon import _allowed_audiences
from lighthouse_policy import Policy
from tests.permissions_support import (
    OUTSIDE_HOME, add_publisher_house, add_publisher_without_store, daemon_with_outside_home_placement,
    delete_ledger, hold_ledger_lock, make_real_house, raised_daemon, read, recall, rerun_gate,
)


@pytest.mark.parametrize("mode", ["no-ledger", "off", "shadow"])
def test_u23_an_outside_home_placement_is_never_served_below_enforce(tmp_path, mode):
    daemon, pub, outside_id = daemon_with_outside_home_placement(
        tmp_path, mode=mode, hand_written_audiences=["commons", OUTSIDE_HOME])
    assert daemon.handle_frame(recall(pub, "outside home: rivers need bridges"))["candidates"] == []
    assert all(i["content"] is None for i in daemon.handle_frame(read(pub, outside_id))["items"])


def test_an_outside_home_placement_is_served_under_enforce_when_the_policy_has_a_rule_for_the_receiver(tmp_path):
    daemon, pub, outside_id = daemon_with_outside_home_placement(
        tmp_path, mode="enforce", hand_written_audiences=["commons"])
    assert len(daemon.handle_frame(recall(pub, "outside home: rivers need bridges"))["candidates"]) == 1
    assert [i["content"] is not None for i in daemon.handle_frame(read(pub, outside_id))["items"]] == [True]


def test_the_audience_rule_adds_the_name_back_only_for_a_receiver_the_policy_has_a_rule_for():
    def policy(rules, audiences):
        return Policy({"issuer": "urn:engram:why", "payload": {"rules": rules},
                       "extensions": {"engram:audiences": audiences}})
    rule = {"id": "r", "effect": "allow", "publishers": ["urn:engram:engram"]}
    p = policy([rule], {"urn:engram:engram": ["commons", OUTSIDE_HOME], "urn:engram:other": [OUTSIDE_HOME]})
    assert _allowed_audiences(p, "urn:engram:engram") == {"commons"}
    assert _allowed_audiences(p, "urn:engram:engram", mode="shadow") == {"commons"}
    assert _allowed_audiences(p, "urn:engram:engram", mode="enforce") == {"commons", OUTSIDE_HOME}
    assert _allowed_audiences(p, "urn:engram:other", mode="enforce") == frozenset()


def test_u16_closed_serves_nothing_and_warns(tmp_path, caplog):
    daemon, pub = raised_daemon(tmp_path, mode="enforce")
    assert daemon.handle_frame(recall(pub))["candidates"]
    delete_ledger(tmp_path)
    assert daemon.handle_frame(recall(pub))["candidates"] == []
    assert "closed" in caplog.text and "ledger" in caplog.text


def test_u16_a_served_house_added_without_the_id_closes_every_frame_until_gate_marks_it(tmp_path, caplog):
    daemon, pub = raised_daemon(tmp_path, mode="shadow")
    late = add_publisher_house(daemon, tmp_path, "late")
    assert daemon.handle_frame(recall(late))["candidates"] == []
    assert daemon.handle_frame(recall(pub))["candidates"] == []      # the gate is over every served house
    assert "late" in caplog.text
    rerun_gate(tmp_path, "shadow")
    assert daemon.handle_frame(recall(late))["candidates"] and daemon.handle_frame(recall(pub))["candidates"]


def test_closed_answers_a_read_with_every_content_null(tmp_path):
    daemon, pub = raised_daemon(tmp_path, mode="enforce")
    memory_id = daemon.handle_frame(recall(pub))["candidates"][0]["memoryId"]
    assert daemon.handle_frame(read(pub, memory_id))["items"][0]["content"] is not None
    delete_ledger(tmp_path)
    assert [i["content"] for i in daemon.handle_frame(read(pub, memory_id))["items"]] == [None]


def test_rf2_locked_ledger_reads_closed(tmp_path):
    daemon, pub = raised_daemon(tmp_path, mode="enforce", busy_timeout_ms=50)
    with hold_ledger_lock(tmp_path, "IMMEDIATE"):        # RESERVED: readers still read the last commit
        assert daemon.handle_frame(recall(pub))["candidates"]
    with hold_ledger_lock(tmp_path, "EXCLUSIVE"):        # what a commit or a cache spill holds
        assert daemon.handle_frame(recall(pub))["candidates"] == []
    assert daemon.handle_frame(recall(pub))["candidates"]


def test_rs5_a_configured_publisher_with_no_store_yet_closes_nothing(tmp_path):
    daemon, pub = raised_daemon(tmp_path, mode="enforce")
    pending = add_publisher_without_store(daemon, tmp_path, "pending")
    assert daemon.handle_frame(recall(pub))["candidates"]
    assert daemon.handle_frame(recall(pending))["code"] == "PUBLISHER_UNAVAILABLE"
    make_real_house(tmp_path, "pending")                 # made now: 029 gives it the ledger's id (Task 16)
    assert daemon.handle_frame(recall(pub))["candidates"]
