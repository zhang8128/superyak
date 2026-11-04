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


def test_rf2_locked_ledger_reads_closed(tmp_path, monkeypatch):
    monkeypatch.setattr("lighthouse_daemon.LEDGER_BUSY_MS", 50)       # put back after the test
    daemon, pub = raised_daemon(tmp_path, mode="enforce")
    with hold_ledger_lock(tmp_path, "IMMEDIATE"):        # RESERVED: readers still read the last commit
        assert daemon.handle_frame(recall(pub))["candidates"]
    with hold_ledger_lock(tmp_path, "EXCLUSIVE"):        # what a commit or a cache spill holds
        assert daemon.handle_frame(recall(pub)) == LEDGER_BUSY        # nothing served, and it says so
    assert daemon.handle_frame(recall(pub))["candidates"]


LEDGER_BUSY = {"protocolVersion": "0.1", "kind": "error", "code": "LEDGER_BUSY",
               "detail": "ledger busy, nothing served, retry"}


def test_s4_a_recall_whose_ledger_read_times_out_carries_ledger_busy_into_the_recalls_neighbors(tmp_path,
                                                                                                 monkeypatch):
    """The projection digest's section 2 review, S4's reader side (Rio Grande, all hands 973f3aa1): a frame that
    times out behind a writer's lock (a writer that waits out a rare full check holds it) serves nothing under
    enforce, which fails closed; its answer says so with LEDGER_BUSY, and the receiver puts the code in
    `neighbors.diagnostics` and marks `neighbors` degraded, so no ship takes an empty result for an answer."""
    import lighthouse_client
    import neighbors
    from lighthouse_protocol import encode
    from tests.test_neighbors import CONTEXT, NOW, Log, policy
    monkeypatch.setattr("lighthouse_daemon.LEDGER_BUSY_MS", 50)       # put back after the test
    daemon, pub = raised_daemon(tmp_path, mode="enforce")
    policy(tmp_path / "receiver-policy.json")

    def call(self, frame, *, deadline=None):         # the receiver's client, reaching this daemon in this process
        expected = {"recall": "recall_result", "read": "read_result"}[frame["kind"]]
        return lighthouse_client._decode_reply(encode(daemon.handle_frame(frame)), expected)

    monkeypatch.setattr(neighbors.LighthouseClient, "call", call)
    args = dict(query="shared: rivers need bridges", context=CONTEXT, purpose="session-recall", k=1, storage=Log(),
                session_id="s", recall_id="t1", receiver="engram", publishers=[pub], socket_path=tmp_path / "s.sock",
                policy_path=tmp_path / "receiver-policy.json", now=lambda: NOW)
    served = neighbors.neighbor_arm(**args)
    assert served["sources"][0]["traceOutcome"] == "matched" and not served["degraded"]   # the control
    with hold_ledger_lock(tmp_path, "EXCLUSIVE"):
        busy = neighbors.neighbor_arm(**{**args, "recall_id": "t2"})
    assert {"publisher": f"urn:engram:{pub}", "code": "LEDGER_BUSY"} in busy["diagnostics"]
    assert busy["degraded"] is True and busy["delivered"] == [] and busy["selected"] == []


def test_s4_a_frame_whose_own_state_times_out_after_the_gate_read_says_ledger_busy_too(tmp_path, monkeypatch):
    """The gate read can pass and the frame's own State then wait out the lock: the same answer, under enforce, for a
    recall and a read; under shadow the legacy path serves, as before."""
    import sqlite3

    from permission_ledger import Ledger
    daemon, pub = raised_daemon(tmp_path, mode="enforce")
    memory_id = daemon.handle_frame(recall(pub))["candidates"][0]["memoryId"]
    real = Ledger.state

    def locked(self, *args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(Ledger, "state", locked)
    assert daemon.handle_frame(recall(pub)) == LEDGER_BUSY
    assert daemon.handle_frame(read(pub, memory_id)) == LEDGER_BUSY
    monkeypatch.setattr(Ledger, "state", real)
    assert daemon.handle_frame(recall(pub))["candidates"]


def test_rs5_a_configured_publisher_with_no_store_yet_closes_nothing(tmp_path):
    daemon, pub = raised_daemon(tmp_path, mode="enforce")
    pending = add_publisher_without_store(daemon, tmp_path, "pending")
    assert daemon.handle_frame(recall(pub))["candidates"]
    assert daemon.handle_frame(recall(pending))["code"] == "PUBLISHER_UNAVAILABLE"
    make_real_house(tmp_path, "pending")                 # made now: 029 gives it the ledger's id (Task 16)
    assert daemon.handle_frame(recall(pub))["candidates"]


def _locked_read_item(monkeypatch, on_call):
    """`_LedgerSide.read_item` raising LedgerUnreadable from "database is locked" on call number `on_call` (1-based)."""
    import sqlite3

    import lighthouse_daemon
    from permission_ledger import LedgerUnreadable
    real, calls = lighthouse_daemon._LedgerSide.read_item, []

    def read_item(self, memory_id, content):
        calls.append(memory_id)
        if len(calls) == on_call:
            try:
                raise sqlite3.OperationalError("database is locked")
            except sqlite3.OperationalError as e:
                raise LedgerUnreadable(f"the permission ledger's rows could not be read: {e}") from e
        return real(self, memory_id, content)

    monkeypatch.setattr(lighthouse_daemon._LedgerSide, "read_item", read_item)


def test_n1_a_read_busy_after_an_item_was_receipted_answers_what_was_decided(tmp_path, monkeypatch):
    """The re-check's N1 (the reviewer's probe): `_read` decides items one by one and writes each item's receipt as it
    goes, so LEDGER_BUSY raised at item 2 left item 1's `allowed` receipt for an item never delivered, against
    read_item's own rule (M8). LEDGER_BUSY is the answer only while no item of the frame has a receipt; after that,
    that item and the rest are not delivered, and the frame answers with what was decided."""
    from lighthouse_protocol import read_frame
    from tests.permissions_support import _daemon_frame_kwargs, receipt_rows
    daemon, pub = raised_daemon(tmp_path, mode="enforce")
    first, second = [c["memoryId"] for c in daemon.handle_frame(recall(pub))["candidates"][:2]]
    frame = read_frame(**_daemon_frame_kwargs(pub), turn_id="turn-1", memory_ids=[first, second])

    def allowed_receipts(since):
        return [r for r in receipt_rows(tmp_path)[since:] if r["action"] == "inject_context" and r["allowed"] == 1]

    _locked_read_item(monkeypatch, on_call=2)
    before = len(receipt_rows(tmp_path))
    reply = daemon.handle_frame(frame)
    delivered = [] if reply["kind"] == "error" else [i for i in reply["items"] if i["content"] is not None]
    assert len(allowed_receipts(before)) <= len(delivered), (reply, allowed_receipts(before))   # no allowed receipt
    assert reply["kind"] == "read_result" and [i["content"] is not None for i in reply["items"]] == [True, False]
    _locked_read_item(monkeypatch, on_call=1)      # the first item busy: no receipt yet, so the frame says so
    before = len(receipt_rows(tmp_path))
    assert daemon.handle_frame(frame) == LEDGER_BUSY and allowed_receipts(before) == []
